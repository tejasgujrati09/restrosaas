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
  await guest.getByRole("button", { name: /Spring Roll/ }).click();
  await guest.getByRole("button", { name: /Add to cart/ }).click();
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
  await kitchen.getByRole("button", { name: "Sold out", exact: true }).first().click();
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
