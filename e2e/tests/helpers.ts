import { expect, type APIRequestContext, type Browser, type Page } from "@playwright/test";
import { ports } from "../ports";

export const api = `http://localhost:${ports.api}`;
export const guest = `http://localhost:${ports.guest}`;
export const staffApp = `http://localhost:${ports.staff}`;

export type Venue = { owner: Record<string, string>; base: string; outletId: string; ownerToken: string; qrToken: string; itemId: string; taxId: string; categoryId: string };

/** Sets a venue up through the API (the owner UI has its own spec) so these tests are about the guest. */
export async function setUpVenue(request: APIRequestContext, opts: { waiterConfirm?: boolean } = {}): Promise<Venue> {
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
  await post("/tables", { label: "T2" });
  const tables = await (await request.get(`${base}/tables`, { headers: owner })).json();
  const qrToken = (tables[0].qr_url as string).split("/").pop() as string;
  return { owner, base, outletId: outlet_id, qrToken, itemId: item.id, taxId: tax.id, categoryId: category.id, ownerToken: access_token };
}

/** Invites someone by phone and accepts the invite, returning their access token. */
export async function addStaff(request: APIRequestContext, venue: Venue, role: string): Promise<string> {
  const phone = `+91999${Math.floor(1_000_000 + Math.random() * 9_000_000)}`;
  const invite = await request.post(`${venue.base}/invites`, { headers: venue.owner, data: { phone, role } });
  expect(invite.ok(), await invite.text()).toBe(true);
  const link = ((await invite.json()) as { link: string }).link;
  const token = link.split("/").pop() as string;
  await request.post(`${api}/v1/invites/otp`, { data: { token } });
  const accepted = await request.post(`${api}/v1/invites/accept`, { data: { token, code: "123456", name: role } });
  expect(accepted.ok(), await accepted.text()).toBe(true);
  return ((await accepted.json()) as { access_token: string }).access_token;
}

export async function assignTable(request: APIRequestContext, venue: Venue, label: string, staffToken: string): Promise<void> {
  const tables = (await (await request.get(`${venue.base}/table-assignments`, { headers: venue.owner })).json()) as { table_id: string; label: string }[];
  const table = tables.find((t) => t.label === label)!;
  const payload = JSON.parse(Buffer.from(staffToken.split(".")[1]!, "base64url").toString()) as { sub: string };
  const r = await request.put(`${venue.base}/tables/${table.table_id}/assignees`, { headers: venue.owner, data: { user_ids: [payload.sub] } });
  expect(r.ok(), await r.text()).toBe(true);
}

/** A page for someone signed in to the staff app with this token. */
export async function staffPage(browser: Browser, token: string): Promise<Page> {
  const context = await browser.newContext();
  await context.addInitScript((t) => window.localStorage.setItem("restosaas.token", t), token);
  return context.newPage();
}

export async function guestPage(browser: Browser, qrToken: string): Promise<Page> {
  const page = await (await browser.newContext()).newPage();
  await page.goto(`${guest}/t/${qrToken}`);
  await expect(page.getByRole("heading", { level: 1, name: "Main" })).toBeVisible();
  return page;
}
