import { expect, test, type Page } from "@playwright/test";
import { ports } from "../ports";

const staff = `http://localhost:${ports.staff}`;
// GSTIN with a valid check character for state 29 (Karnataka).
const GSTIN = "29AAPFU0939F1ZR";

function randomPhone(): string {
  // Numbers starting 999 are reserved for tests, matching the API test fixtures.
  return `999${Math.floor(1_000_000 + Math.random() * 9_000_000)}`;
}

async function signIn(page: Page, phone: string) {
  await page.goto(`${staff}/login`);
  await page.getByLabel("Mobile number").fill(phone);
  await page.getByRole("button", { name: "Send code" }).click();
  await page.getByLabel("Code", { exact: true }).fill("123456");
  await page.getByRole("button", { name: "Sign in" }).click();
}

test("an owner goes from sign-up to a menu, tables, staff and a happy hour", async ({ page }) => {
  const phone = randomPhone();

  // Sign up.
  await page.goto(`${staff}/signup`);
  await page.getByLabel("Your mobile number").fill(phone);
  await page.getByRole("button", { name: "Send code" }).click();
  await page.getByLabel("Code from your phone").fill("123456");
  await page.getByLabel("Your name").fill("Asha");
  await page.getByLabel("Registered business name").fill("E2E Legal Pvt Ltd");
  await page.getByLabel("Restaurant name").fill("E2E Cafe");
  await page.getByLabel("Outlet name").fill("Indiranagar");
  await page.getByRole("button", { name: "Create restaurant" }).click();

  // Setup: the checklist blocks go-live until a tax class exists; GSTIN is optional.
  await expect(page.getByRole("heading", { name: "Outlet setup" })).toBeVisible();
  await expect(page.getByText("Add your GSTIN.")).toHaveCount(0);
  await expect(page.getByText("Add at least one tax class.")).toBeVisible();
  await page.getByLabel("GSTIN").fill(GSTIN);
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByRole("status")).toHaveText("Saved");

  const taxCard = page.locator("section", { hasText: "Tax classes" });
  await taxCard.getByLabel("Name").fill("Food 5%");
  await taxCard.getByRole("button", { name: "Add tax class" }).click();
  await expect(taxCard.getByText("GST 5%")).toBeVisible();
  await page.reload();
  await expect(page.getByText("All set. Your outlet is ready for guests.")).toBeVisible();

  // Menu: a category, an item priced exactly as typed, and a sold-out toggle.
  await page.getByRole("link", { name: "Menu" }).click();
  await expect(page.getByRole("heading", { name: "Menu", level: 1 })).toBeVisible();
  const addCategory = page.locator("section", { hasText: "Add a category" });
  await addCategory.getByLabel("Name").fill("Starters");
  await addCategory.getByRole("button", { name: "Add category" }).click();
  const starters = page.locator("section", { has: page.getByRole("heading", { name: "Starters", exact: true }) });
  await starters.getByText("Add an item to Starters").click();
  await starters.getByLabel("Item name").fill("Paneer Tikka");
  await starters.getByLabel(/^Price/).fill("320.50");
  await starters.getByRole("button", { name: "Add item" }).click();
  await expect(starters.getByRole("row", { name: /Paneer Tikka/ })).toContainText("₹320.50");
  await starters.getByRole("button", { name: "Available" }).click();
  await expect(starters.getByRole("button", { name: "Sold out" })).toBeVisible();

  // CSV import: preview first, nothing changes until Apply.
  const csv = "category,item,description,price,tax_class,veg,is_liquor,station,available,sku,modifier_groups\n" +
    "Starters,Spring Roll,,150.50,Food 5%,yes,no,,yes,,\n";
  await page.locator('input[type="file"]').setInputFiles({ name: "menu.csv", mimeType: "text/csv", buffer: Buffer.from(csv) });
  await expect(page.getByText("1 new items")).toBeVisible();
  await expect(page.getByRole("row", { name: /Spring Roll/ })).toHaveCount(1);
  await page.getByRole("button", { name: "Apply changes" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Added 1 items" })).toBeVisible();
  await expect(starters.getByRole("row", { name: /Spring Roll/ })).toContainText("₹150.50");

  // A bad file shows row-level errors and cannot be applied.
  const bad = "category,item,price,tax_class\nStarters,Broken,abc,No such class\n";
  await page.locator('input[type="file"]').setInputFiles({ name: "bad.csv", mimeType: "text/csv", buffer: Buffer.from(bad) });
  await expect(page.getByText("Fix these first")).toBeVisible();
  await expect(page.getByRole("button", { name: "Apply changes" })).toHaveCount(0);

  // Tables: bar counter seats B1..B3, each with its own QR link.
  await page.getByRole("link", { name: "Tables & QR" }).click();
  await expect(page.getByRole("heading", { name: "Tables and QR codes" })).toBeVisible();
  await page.getByLabel("Zone").fill("bar");
  await page.getByLabel("Label starts with").fill("B");
  await page.getByLabel("How many").fill("3");
  await page.getByRole("button", { name: "Add", exact: true }).click();
  const bar = page.locator("section", { has: page.getByRole("heading", { name: "bar", exact: true }) });
  for (const label of ["B1", "B2", "B3"]) await expect(bar.getByRole("cell", { name: label })).toBeVisible();
  await expect(bar.getByRole("link", { name: "Open" })).toHaveCount(3);

  // Staff: an invite bound to a phone, with a WhatsApp link.
  await page.getByRole("link", { name: "Staff" }).click();
  await expect(page.getByRole("heading", { name: "Staff", level: 1 })).toBeVisible();
  await page.getByLabel("Their mobile number").fill(randomPhone());
  await page.getByRole("button", { name: "Create invite" }).click();
  await expect(page.getByRole("link", { name: "Send on WhatsApp" })).toHaveAttribute("href", /^https:\/\/wa\.me\/91999/);

  // Happy hour.
  await page.getByRole("link", { name: "Happy hours" }).click();
  await expect(page.getByRole("heading", { name: "Happy hours and event pricing" })).toBeVisible();
  await page.getByRole("textbox", { name: "Percent off" }).fill("50");
  await page.getByRole("button", { name: "Add rule" }).click();
  await expect(page.getByText("50% off, 17:00–20:00, every day")).toBeVisible();

  // Sign out, sign back in: straight to the menu of the only outlet.
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login$/);
  await signIn(page, phone);
  await expect(page).toHaveURL(/\/o\/[0-9a-f-]+\/menu$/);
  await expect(page.getByRole("heading", { name: "Menu" })).toBeVisible();
});

test("an unregistered phone cannot sign in", async ({ page }) => {
  await page.goto(`${staff}/login`);
  await page.getByLabel("Mobile number").fill(randomPhone());
  await page.getByRole("button", { name: "Send code" }).click();
  await page.getByLabel("Code", { exact: true }).fill("123456");
  await page.getByRole("button", { name: "Sign in" }).click();
  // Unknown phone: the API says 202 but no code exists, so the code is rejected.
  await expect(page.locator("p[role=alert]")).toContainText("not right");
  await expect(page).toHaveURL(/\/login$/);
});
