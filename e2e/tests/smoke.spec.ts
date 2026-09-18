import { expect, test } from "@playwright/test";
import { ports } from "../ports";

const apps = [
  { name: "guest", port: ports.guest, heading: "Order at your table" },
  { name: "staff", port: ports.staff, heading: "Sign in" },
  { name: "admin", port: ports.admin, heading: "Platform admin" },
];

for (const { name, port, heading } of apps) {
  test(`${name} app boots`, async ({ page }) => {
    await page.goto(`http://localhost:${port}`);
    await expect(page.getByRole("heading", { level: 1, name: heading })).toBeVisible();
  });
}

test("API is up and reaches the database", async ({ request }) => {
  const api = `http://localhost:${ports.api}`;
  const health = await request.get(`${api}/health`);
  expect(health.ok()).toBe(true);
  // Unknown phone still returns 202 (no user enumeration) but exercises a DB query.
  const otp = await request.post(`${api}/v1/auth/otp/request`, {
    data: { phone: "+919000000001" },
  });
  expect(otp.status()).toBe(202);
});
