import { expect, test } from "@playwright/test";
import { guest, setUpVenue } from "./helpers";

test("a guest scans, orders two items with a modifier, sees locked prices and asks for the bill", async ({ page, request }) => {
  const venue = await setUpVenue(request);
  const started = Date.now();

  await page.goto(`${guest}/t/${venue.qrToken}`);
  await expect(page.getByRole("heading", { level: 1, name: "Main" })).toBeVisible();
  await expect(page.getByText("Table T1")).toBeVisible();

  // A required modifier group: nothing is preselected, so the guest must choose.
  await page.getByRole("button", { name: /Paneer Tikka/ }).click();
  await expect(page.getByRole("button", { name: "Choose your options" })).toBeDisabled();
  await page.getByLabel("Hot").check();
  await expect(page.getByRole("button", { name: /Add to cart · ₹330\.00/ })).toBeVisible();
  await page.getByRole("button", { name: "One more" }).click();
  await page.getByRole("button", { name: /Add to cart · ₹660\.00/ }).click();
  await page.getByRole("button", { name: "Add Spring Roll" }).click(); // adds in place: no options to choose
  console.log(`scan to cart ready: ${Date.now() - started} ms`);

  await page.getByRole("link", { name: /View cart/ }).click();
  await expect(page.getByRole("heading", { name: "Your cart" })).toBeVisible();
  await expect(page.getByText("Hot", { exact: true })).toBeVisible();
  // 2 x 330.00 + 150.00 = 810.00 inclusive of 5% GST; service charge is a separate line.
  const totals = page.getByRole("region", { name: "Totals" });
  await expect(totals.getByText("₹810.00").first()).toBeVisible();
  await expect(totals.getByText(/CGST/)).toBeVisible();
  await expect(totals.getByText("Service charge", { exact: true })).toBeVisible();

  // Removing service charge is the guest's right and needs no reason.
  await totals.getByRole("button", { name: "Remove service charge" }).click();
  await expect(totals.getByText("Removed")).toBeVisible();

  await page.getByRole("button", { name: "Place order" }).click();
  await expect(page.getByText("Order placed")).toBeVisible();
  await expect(page.getByText(/Round 1/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Undo this order" })).toBeVisible();

  await page.getByRole("link", { name: "See my tab" }).click();
  await expect(page.getByRole("heading", { name: "My tab" })).toBeVisible();
  const round = page.getByRole("region", { name: "Round 1" });
  await expect(round.getByText("2 × Paneer Tikka")).toBeVisible();
  await expect(round.getByText("₹660.00")).toBeVisible();
  await expect(round.getByText("1 × Spring Roll")).toBeVisible();
  await expect(round.getByText("You", { exact: true }).first()).toBeVisible();

  // A reload keeps the guest on the same tab.
  await page.reload();
  await expect(page.getByRole("region", { name: "Round 1" })).toBeVisible();

  await page.getByRole("button", { name: "Request the bill" }).click();
  await page.getByRole("button", { name: "Yes, request it" }).click();
  await expect(page.getByText(/Bill requested/)).toBeVisible();
});

test("undo within the window cancels the round and leaves nothing on the tab", async ({ page, request }) => {
  const venue = await setUpVenue(request);
  await page.goto(`${guest}/t/${venue.qrToken}`);
  await page.getByRole("button", { name: "Add Spring Roll" }).click(); // adds in place: no options to choose
  await page.getByRole("link", { name: /View cart/ }).click();
  await page.getByRole("button", { name: "Place order" }).click();
  await page.getByRole("button", { name: "Undo this order" }).click();
  await expect(page.getByText("Order cancelled")).toBeVisible();
  await page.getByRole("link", { name: "See my tab" }).click();
  await expect(page.getByText("Cancelled")).toBeVisible();
  await expect(page.getByRole("button", { name: "Request the bill" })).toHaveCount(0);
});

test("golden flow 3: a happy-hour price stays locked after the rule ends and the menu price changes", async ({ page, request }) => {
  const venue = await setUpVenue(request);
  const rule = await (
    await request.post(`${venue.base}/price-rules`, {
      headers: venue.owner,
      data: {
        name: "Happy hour",
        scope: "item",
        target_id: venue.itemId,
        rule_type: "fixed",
        value: 20000,
        days_of_week: [0, 1, 2, 3, 4, 5, 6],
        start_time: "00:00:00",
        end_time: "23:59:00",
      },
    })
  ).json();

  await page.goto(`${guest}/t/${venue.qrToken}`);
  const beer = page.getByRole("button", { name: /Paneer Tikka/ });
  await expect(beer).toContainText("Happy hour");
  await expect(beer).toContainText("₹200.00");
  await beer.click();
  await page.getByLabel("Mild").check();
  await page.getByRole("button", { name: /Add to cart · ₹200\.00/ }).click();
  await page.getByRole("link", { name: /View cart/ }).click();
  await page.getByRole("button", { name: "Place order" }).click();
  await expect(page.getByText("Order placed")).toBeVisible();

  // The rule ends and the owner changes the menu price.
  const off = await request.put(`${venue.base}/price-rules/${rule.id}`, {
    headers: venue.owner,
    data: { ...rule, active: false },
  });
  expect(off.ok(), await off.text()).toBe(true);
  const raise = await request.put(`${venue.base}/items/${venue.itemId}`, {
    headers: venue.owner,
    data: { category_id: venue.categoryId, name: "Paneer Tikka", base_price_paise: 45000, tax_class_id: venue.taxId },
  });
  expect(raise.ok(), await raise.text()).toBe(true);

  await page.getByRole("link", { name: "See my tab" }).click();
  const line = page.getByRole("region", { name: "Round 1" });
  await expect(line.getByText("₹200.00")).toBeVisible();
  await expect(line.getByText(/Happy hour/)).toBeVisible();

  await page.getByRole("link", { name: "Menu" }).click();
  await expect(page.getByRole("button", { name: /Paneer Tikka/ })).toContainText("₹450.00");
  await expect(page.getByRole("button", { name: /Paneer Tikka/ })).not.toContainText("Happy hour");
});

test("waiter-confirm mode blocks ordering until the waiter confirms, and the guest hears about it at once", async ({ page, request }) => {
  const venue = await setUpVenue(request, { waiterConfirm: true });
  await page.goto(`${guest}/t/${venue.qrToken}`);
  await expect(page.getByText(/Waiting for your waiter to confirm/)).toBeVisible();
  await page.getByRole("button", { name: "Add Spring Roll" }).click(); // adds in place: no options to choose

  // With the socket up the page only re-polls every 40 s, so a change within seconds is a push.
  const tabId = await page.evaluate(() => JSON.parse(localStorage.getItem("restosaas.guest") ?? "{}").tab_id as string);
  const confirm = await request.post(`${venue.base}/tabs/${tabId}/confirm`, { headers: venue.owner });
  expect(confirm.ok(), await confirm.text()).toBe(true);
  await expect(page.getByText(/Waiting for your waiter to confirm/)).toHaveCount(0, { timeout: 4_000 });

  await page.getByRole("link", { name: /View cart/ }).click();
  await expect(page.getByRole("button", { name: "Place order" })).toBeEnabled();
});

test("a round accepted after the undo window shows up on the tab without a reload", async ({ page, request }) => {
  test.setTimeout(120_000); // waits out the real 60-second undo window
  const venue = await setUpVenue(request);
  await page.goto(`${guest}/t/${venue.qrToken}`);
  await page.getByRole("button", { name: "Add Spring Roll" }).click(); // adds in place: no options to choose
  await page.getByRole("link", { name: /View cart/ }).click();
  await page.getByRole("button", { name: "Place order" }).click();
  await page.getByRole("link", { name: "See my tab" }).click();
  const round = page.getByRole("region", { name: "Round 1" });
  await expect(round.getByText("Sent")).toBeVisible();
  // The server's timer accepts the round 61 s after it was placed and pushes the change.
  await expect(round.getByText("Accepted")).toBeVisible({ timeout: 75_000 });
  await expect(round.getByRole("button", { name: /Undo/ })).toHaveCount(0);
});

test("a rotated or unknown QR code says so instead of ordering", async ({ page }) => {
  await page.goto(`${guest}/t/not-a-real-code`);
  await expect(page.getByText(/no longer valid/)).toBeVisible();
});
