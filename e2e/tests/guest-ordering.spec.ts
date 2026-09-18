import { expect, test, type APIRequestContext } from "@playwright/test";
import { ports } from "../ports";

const api = `http://localhost:${ports.api}`;
const guest = `http://localhost:${ports.guest}`;

type Venue = { owner: Record<string, string>; base: string; qrToken: string; itemId: string; taxId: string; categoryId: string };

/** Sets a venue up through the API (the owner UI has its own spec) so these tests are about the guest. */
async function setUpVenue(request: APIRequestContext, opts: { waiterConfirm?: boolean } = {}): Promise<Venue> {
  const phone = `+91999${Math.floor(1_000_000 + Math.random() * 9_000_000)}`;
  await request.post(`${api}/v1/signup/otp`, { data: { phone } });
  const signup = await request.post(`${api}/v1/signup`, {
    data: { phone, code: "123456", owner_name: "Asha", legal_name: "E2E Legal", brand_name: "E2E Bar", outlet_name: "Main", state_code: "29" },
  });
  const { access_token, outlet_id } = (await signup.json()) as { access_token: string; outlet_id: string };
  const owner = { Authorization: `Bearer ${access_token}` };
  const base = `${api}/v1/outlets/${outlet_id}`;
  const post = async <T>(path: string, data: unknown, method: "post" | "put" | "patch" = "post"): Promise<T> => {
    const r = await request[method](`${base}${path}`, { data, headers: owner });
    expect(r.ok(), `${method} ${path}: ${await r.text()}`).toBe(true);
    return (await r.json()) as T;
  };
  await post("/settings", { service_charge_bp: 1000, waiter_confirm_mode: opts.waiterConfirm ?? false }, "patch");
  const tax = await post<{ id: string }>("/tax-classes", { name: "Food 5%", gst_rate_bp: 500 });
  const category = await post<{ id: string }>("/categories", { name: "Starters" });
  const group = await post<{ id: string }>("/modifier-groups", {
    name: "Spice",
    min_select: 1,
    max_select: 1,
    modifiers: [{ name: "Mild" }, { name: "Hot", price_delta_paise: 1000 }],
  });
  const item = await post<{ id: string }>("/items", {
    category_id: category.id,
    name: "Paneer Tikka",
    base_price_paise: 32000,
    tax_class_id: tax.id,
    modifier_group_ids: [group.id],
  });
  await post("/items", { category_id: category.id, name: "Spring Roll", base_price_paise: 15000, tax_class_id: tax.id });
  await post("/tables", { label: "T1" });
  const tables = await (await request.get(`${base}/tables`, { headers: owner })).json();
  const qrToken = (tables[0].qr_url as string).split("/").pop() as string;
  return { owner, base, qrToken, itemId: item.id, taxId: tax.id, categoryId: category.id };
}

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
  await page.getByRole("button", { name: /Spring Roll/ }).click();
  await page.getByRole("button", { name: /Add to cart/ }).click();
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
  await page.getByRole("button", { name: /Spring Roll/ }).click();
  await page.getByRole("button", { name: /Add to cart/ }).click();
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

test("waiter-confirm mode lets a guest browse but blocks ordering until the waiter confirms", async ({ page, request }) => {
  const venue = await setUpVenue(request, { waiterConfirm: true });
  await page.goto(`${guest}/t/${venue.qrToken}`);
  await expect(page.getByText(/Waiting for your waiter to confirm/)).toBeVisible();
  await page.getByRole("button", { name: /Spring Roll/ }).click();
  await page.getByRole("button", { name: /Add to cart/ }).click();
  await page.getByRole("link", { name: /View cart/ }).click();
  await expect(page.getByRole("button", { name: "Place order" })).toBeDisabled();

  // A waiter confirms the tab (waiter role via invite is Milestone 4's UI; the API is enough here).
  const tabId = await page.evaluate(() => JSON.parse(localStorage.getItem("restosaas.guest") ?? "{}").tab_id as string);
  const confirm = await request.post(`${venue.base}/tabs/${tabId}/confirm`, { headers: venue.owner });
  expect(confirm.ok(), await confirm.text()).toBe(true);
  await page.reload();
  await expect(page.getByRole("button", { name: "Place order" })).toBeEnabled();
});

test("a rotated or unknown QR code says so instead of ordering", async ({ page }) => {
  await page.goto(`${guest}/t/not-a-real-code`);
  await expect(page.getByText(/no longer valid/)).toBeVisible();
});
