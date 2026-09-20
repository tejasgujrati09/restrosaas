import { execFileSync } from "node:child_process";
import { join } from "node:path";
import { expect, test } from "@playwright/test";
import { ports } from "../ports";
import { api, guest, setUpVenue, staffApp, staffPage } from "./helpers";

const adminApp = `http://localhost:${ports.admin}`;

/** Admins have no signup by design: they are made with the operator script. */
function makeAdmin(phone: string): void {
  execFileSync("uv", ["run", "python", "../../scripts/create_platform_admin.py", phone, "--name", "E2E Admin"], {
    cwd: join(process.cwd(), "..", "apps", "api"),
    stdio: "pipe",
  });
}

test("a platform admin suspends a restaurant, staff and guests are refused, then reactivates it", async ({ page, browser, request }) => {
  const venue = await setUpVenue(request);
  const brand = `E2E Suspend ${Date.now()}`;
  const renamed = await request.patch(`${venue.base}/settings`, { headers: venue.owner, data: { brand_name: brand } });
  expect(renamed.ok(), await renamed.text()).toBe(true);
  const phone = `+91999${Math.floor(1_000_000 + Math.random() * 9_000_000)}`;
  makeAdmin(phone);

  // Sign in with a phone code.
  await page.goto(`${adminApp}/login`);
  await page.getByLabel("Mobile number").fill(phone.slice(3));
  await page.getByRole("button", { name: "Send code" }).click();
  await page.getByLabel("Code", { exact: true }).fill("123456");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Restaurants" })).toBeVisible();

  // Find the restaurant and suspend it; a reason is required.
  await page.getByLabel("Search restaurants").fill(brand);
  const card = page.getByRole("listitem").filter({ hasText: brand });
  await expect(card).toHaveCount(1);
  await card.getByRole("button", { name: `Suspend ${brand}` }).click();
  const confirm = page.getByRole("button", { name: "Suspend restaurant" });
  await expect(confirm).toBeDisabled();
  await page.getByLabel("Reason").fill("Unpaid invoice");
  await confirm.click();
  await expect(card.getByText("Suspended", { exact: true })).toBeVisible();

  // Staff can still look but not change anything, and the app says why.
  expect((await request.get(`${venue.base}/tables`, { headers: venue.owner })).status()).toBe(200);
  const write = await request.patch(`${venue.base}/settings`, {
    headers: { ...venue.owner, "Idempotency-Key": crypto.randomUUID() },
    data: { brand_name: "Sneaky" },
  });
  expect(write.status()).toBe(403);
  expect(((await write.json()) as { code: string }).code).toBe("restaurant_suspended");
  const owner = await staffPage(browser, venue.ownerToken);
  await owner.goto(`${staffApp}/o/${venue.outletId}/setup`);
  await expect(owner.getByText(/account is suspended/)).toBeVisible();
  await expect(owner.getByRole("heading", { name: "Outlet setup" })).toBeVisible();
  await expect(owner.getByRole("button", { name: "Save" })).toBeDisabled();
  await expect(owner.getByRole("link", { name: "Floor" }).first()).toBeEnabled();
  await owner.close();
  // A guest scanning the QR is turned away.
  const scanner = await browser.newPage();
  await scanner.goto(`${guest}/t/${venue.qrToken}`);
  await expect(scanner.getByText(/not taking orders/)).toBeVisible();

  // The audit log says who, what and why.
  await page.getByRole("link", { name: "Audit log" }).click();
  const row = page.getByRole("row").filter({ hasText: brand }).first();
  await expect(row).toContainText("Suspended");
  await expect(row).toContainText("Unpaid invoice");
  await expect(row).toContainText("E2E Admin");

  // Reactivate: the guest can order again.
  await page.getByRole("link", { name: "Restaurants" }).click();
  await page.getByLabel("Search restaurants").fill(brand);
  await card.getByRole("button", { name: `Reactivate ${brand}` }).click();
  await page.getByRole("button", { name: "Reactivate restaurant" }).click();
  await expect(card.getByText("Active", { exact: true })).toBeVisible();
  const back = await request.patch(`${venue.base}/settings`, {
    headers: { ...venue.owner, "Idempotency-Key": crypto.randomUUID() },
    data: { brand_name: brand },
  });
  expect(back.status()).toBe(200);
  await scanner.goto(`${guest}/t/${venue.qrToken}`);
  await expect(scanner).toHaveURL(/\/menu/);
});

test("staff and unknown phones cannot sign in to the admin", async ({ page }) => {
  await page.goto(`${adminApp}/login`);
  await page.getByLabel("Mobile number").fill("9999123456");
  await page.getByRole("button", { name: "Send code" }).click();
  await page.getByLabel("Code", { exact: true }).fill("123456");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.locator("p[role=alert]")).toContainText("not right");
  expect(api).toContain("localhost");
});
