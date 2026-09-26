import { expect, test } from "@playwright/test";
import { addStaff, assignTable, guestPage, setUpVenue, staffApp } from "./helpers";

test("golden flow 2, up to the manager's alert: a waiter adds a big item, the guest says it isn't theirs", async ({ browser, request }) => {
  const venue = await setUpVenue(request);
  const waiterToken = await addStaff(request, venue, "waiter");
  const kitchenToken = await addStaff(request, venue, "kitchen");
  await assignTable(request, venue, "T1", waiterToken);

  const guest = await guestPage(browser, venue.qrToken);

  // The waiter sees only their table, and the guest's tab is on it.
  const { staffPage } = await import("./helpers");
  const waiter = await staffPage(browser, waiterToken);
  await waiter.goto(`${staffApp}/o/${venue.outletId}/floor`);
  await expect(waiter.getByRole("heading", { level: 1, name: "Floor" })).toBeVisible();
  await expect(waiter.getByRole("link", { name: /T1/ })).toBeVisible();
  await expect(waiter.getByText("T2", { exact: true })).toHaveCount(0);

  // Add two Paneer Tikka (₹640, over the ₹500 threshold) for the guest.
  await waiter.getByRole("link", { name: /T1/ }).click();
  await waiter.getByRole("link", { name: "Add items" }).click();
  await waiter.getByRole("button", { name: "Add" }).first().click();
  await waiter.getByLabel("Mild").check();
  await waiter.getByRole("button", { name: "One more" }).click();
  await waiter.getByRole("button", { name: /Add to cart · ₹640\.00/ }).click();
  await waiter.getByRole("button", { name: "Send to the kitchen" }).click();
  await expect(waiter.getByText("Awaiting the guest's OK")).toBeVisible();

  // The guest is asked, live, and says it isn't theirs.
  await guest.getByRole("link", { name: "My tab" }).click();
  await expect(guest.getByText("Your waiter added this. Is it yours?")).toBeVisible({ timeout: 6_000 });
  await guest.getByRole("button", { name: "Not ours" }).click();
  await expect(guest.getByText(/You said this isn't yours/)).toBeVisible();

  // A manager sees the alert without reloading, and the waiter sees the dispute on the table.
  const manager = await (await import("./helpers")).staffPage(browser, venue.ownerToken);
  await manager.goto(`${staffApp}/o/${venue.outletId}/floor`);
  await expect(manager.getByRole("region", { name: "Alerts" })).toContainText("isn't theirs");
  await expect(waiter.getByText("Guest says this isn't theirs")).toBeVisible({ timeout: 6_000 });

  // The kitchen sees the item at once, with no prices, and bumps it; the waiter serves it.
  const kitchen = await (await import("./helpers")).staffPage(browser, kitchenToken);
  await kitchen.goto(`${staffApp}/o/${venue.outletId}/kitchen`);
  const ticket = kitchen.getByRole("article", { name: /Table T1/ });
  await expect(ticket).toContainText("2 × Paneer Tikka");
  await expect(ticket).not.toContainText("₹");
  await ticket.getByRole("button", { name: "Start" }).click();
  await ticket.getByRole("button", { name: "Ready" }).click();
  await expect(kitchen.getByRole("region", { name: "Recently bumped" })).toBeVisible();
  await expect(waiter.getByText("Ready to serve").first()).toBeVisible({ timeout: 6_000 });
  await waiter.getByRole("button", { name: "Serve everything that's ready" }).click();
  await expect(waiter.getByText("Served").first()).toBeVisible();
  await expect(guest.getByText("Served").first()).toBeVisible({ timeout: 6_000 });
});

test("the kitchen sees a guest's round at once but cannot start it until the guest can no longer undo", async ({ browser, request }) => {
  const venue = await setUpVenue(request);
  const kitchenToken = await addStaff(request, venue, "kitchen");
  const { staffPage } = await import("./helpers");
  const kitchen = await staffPage(browser, kitchenToken);
  await kitchen.goto(`${staffApp}/o/${venue.outletId}/kitchen`);
  await expect(kitchen.getByText("No tickets waiting.")).toBeVisible();

  const guest = await guestPage(browser, venue.qrToken);
  await guest.getByRole("button", { name: "Add Spring Roll" }).click(); // adds in place: no options to choose
  await guest.getByRole("link", { name: /View cart/ }).click();
  await guest.getByRole("button", { name: "Place order" }).click();

  const ticket = kitchen.getByRole("article", { name: /Table T1/ });
  await expect(ticket).toBeVisible({ timeout: 4_000 }); // within seconds, not after the undo window
  await expect(ticket).toContainText("1 × Spring Roll");
  await expect(ticket).toContainText("can still undo");
  await expect(ticket.getByRole("button", { name: /Wait \d+s/ })).toBeDisabled();

  // The guest changes their mind: the ticket disappears from the kitchen.
  await guest.getByRole("button", { name: "Undo this order" }).click();
  await expect(kitchen.getByText("No tickets waiting.")).toBeVisible({ timeout: 4_000 });
});

test("marking an item sold out in the kitchen greys it on the guest's menu at once", async ({ browser, request }) => {
  const venue = await setUpVenue(request);
  const kitchenToken = await addStaff(request, venue, "kitchen");
  const { staffPage } = await import("./helpers");
  const kitchen = await staffPage(browser, kitchenToken);
  await kitchen.goto(`${staffApp}/o/${venue.outletId}/kitchen`);
  const guest = await guestPage(browser, venue.qrToken);
  await expect(guest.getByRole("button", { name: /Spring Roll/ })).toBeEnabled();

  await kitchen.getByLabel("Find an item").fill("spring");
  await kitchen.getByRole("button", { name: "Mark sold out" }).first().click();
  await expect(kitchen.getByRole("status").filter({ hasText: "marked sold out" })).toBeVisible();
  await expect(guest.getByRole("button", { name: /Spring Roll/ })).toBeDisabled({ timeout: 4_000 });
  await expect(guest.getByRole("button", { name: /Spring Roll/ })).toContainText("Sold out");
});

test("a manager assigns a table and the waiter's map gains it without reloading", async ({ browser, request }) => {
  const venue = await setUpVenue(request);
  const waiterToken = await addStaff(request, venue, "waiter");
  const { staffPage } = await import("./helpers");
  const waiter = await staffPage(browser, waiterToken);
  await waiter.goto(`${staffApp}/o/${venue.outletId}/floor`);
  await expect(waiter.getByText("You have no tables yet")).toBeVisible();

  const manager = await staffPage(browser, venue.ownerToken);
  await manager.goto(`${staffApp}/o/${venue.outletId}/assignments`);
  const box = manager.getByLabel("waiter for table T2");
  await box.click(); // the box ticks once the server has saved it
  await expect(box).toBeChecked();
  await expect(waiter.getByRole("button", { name: /T2/ })).toBeVisible({ timeout: 4_000 });
  await expect(waiter.getByText("You have no tables yet")).toHaveCount(0);
  await expect(waiter.getByText("T1", { exact: true })).toHaveCount(0);
});

test("a waiter adds items with no connection; they are kept and sent once when it returns", async ({ browser, request }) => {
  const venue = await setUpVenue(request);
  const waiterToken = await addStaff(request, venue, "waiter");
  await assignTable(request, venue, "T1", waiterToken);
  const guest = await guestPage(browser, venue.qrToken);
  const { staffPage } = await import("./helpers");
  const waiter = await staffPage(browser, waiterToken);
  await waiter.goto(`${staffApp}/o/${venue.outletId}/floor`);
  await waiter.getByRole("link", { name: /T1/ }).click();
  await waiter.getByRole("link", { name: "Add items" }).click();
  await waiter.locator(".line-row", { hasText: "Spring Roll" }).getByRole("button", { name: "Add" }).click();
  await waiter.getByRole("button", { name: /Add to cart/ }).click();

  await waiter.context().setOffline(true);
  await waiter.getByRole("button", { name: "Send to the kitchen" }).click();
  await expect(waiter.getByText("Saved on this device")).toBeVisible();
  await expect(waiter.locator(".offline")).toContainText("Add 1 × Spring Roll");

  await waiter.context().setOffline(false);
  await expect(waiter.locator(".offline")).toHaveCount(0, { timeout: 20_000 });
  await waiter.getByRole("link", { name: "Back to the table", exact: true }).click();
  await expect(waiter.getByText("1 × Spring Roll")).toBeVisible({ timeout: 10_000 });
  await expect(waiter.getByText(/^Round \d/)).toHaveCount(1); // placed once, not per attempt
  await guest.getByRole("link", { name: "My tab" }).click();
  await expect(guest.getByText("1 × Spring Roll")).toBeVisible({ timeout: 6_000 });
});

test("an action the server refuses after reconnecting is shown for review, not lost or forced", async ({ browser, request }) => {
  const venue = await setUpVenue(request);
  const waiterToken = await addStaff(request, venue, "waiter");
  const kitchenToken = await addStaff(request, venue, "kitchen");
  await assignTable(request, venue, "T1", waiterToken);
  await guestPage(browser, venue.qrToken);
  const { staffPage } = await import("./helpers");
  const waiter = await staffPage(browser, waiterToken);
  await waiter.goto(`${staffApp}/o/${venue.outletId}/floor`);
  await waiter.getByRole("link", { name: /T1/ }).click();
  await waiter.getByRole("link", { name: "Add items" }).click();
  await waiter.locator(".line-row", { hasText: "Spring Roll" }).getByRole("button", { name: "Add" }).click();
  await waiter.getByRole("button", { name: /Add to cart/ }).click();
  await waiter.context().setOffline(true);
  await waiter.getByRole("button", { name: "Send to the kitchen" }).click();
  await expect(waiter.locator(".offline")).toContainText("1 action");

  // While the waiter is offline the kitchen runs out of it.
  const items = (await (await request.get(`${venue.base}/menu`, { headers: venue.owner })).json()) as { categories: { items: { id: string; name: string }[] }[] };
  const roll = items.categories.flatMap((c) => c.items).find((i) => i.name === "Spring Roll")!;
  expect((await request.put(`${venue.base}/items/${roll.id}/sold-out`, { headers: { Authorization: `Bearer ${kitchenToken}` }, data: { sold_out: true } })).ok()).toBe(true);

  await waiter.context().setOffline(false);
  const notice = waiter.locator(".offline .warn");
  await expect(notice).toContainText("Add 1 × Spring Roll", { timeout: 20_000 });
  await expect(notice).toContainText("not available");
  await notice.getByRole("button", { name: "Discard" }).click();
  await expect(waiter.locator(".offline")).toHaveCount(0);
});
