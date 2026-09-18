# Decisions

Record of choices made where `docs/SPEC.md` was silent and the answer affects the schema or a public API. Newest first. Each entry: date, decision, reason, impact.

## 2026-09-18 — Milestone 3 choices (guest ordering and live tab)

- **TabSession token transport.** The API returns an opaque token in the response body; the guest PWA stores it and sends `Authorization: Bearer`. No cookie. Reason: guest app and API are different origins in dev and the production domain is undecided; a header avoids cross-origin cookie, SameSite and CSRF handling. This deviates from the word "cookie" in `docs/AGENT-KICKOFF.md`. Trade-off: a token in `localStorage` is readable by any XSS on the guest origin; the token only authorises one tab for at most 6 h.
- **Token shape.** `<restaurant_id>.<random>`; only a hash of the random part is stored. The restaurant id prefix lets later requests open a normal `tenant_session`, so `tab_session` needs no cross-tenant RLS policy.
- **Undo window and `accepted`.** A new order stays `placed` for 60 s so customer undo is real. In auto mode it becomes `accepted` at `placed_at + 60 s`; there is no manual accept in Milestone 3 (a staff accept action arrives with tickets in Milestone 4). Waiter-confirm mode gates the *tab*: the guest can browse but not order until a waiter confirms the tab. Consequence: kitchen and bar tickets appear up to 60 s after placing in auto mode. If pilots find that too slow, revisit before Milestone 4 ships tickets.
- **QR lookup under RLS (needs human review, CLAUDE.md §9).** One new read-only policy on `dining_table`, `dining_table_by_qr_token`, matching `app.qr_token` (same pattern as `staff_invite_by_token`). Used only by the QR-landing exchange, before the tenant is known.
- **Session lifetime and join policy.** A TabSession expires 6 h after issue, or immediately when its tab closes or is voided. Any scan of the table's QR joins the table's open tab (several phones per tab); the stale-photo risk is covered by expiry plus per-table waiter-confirm mode.
- **One live tab per table.** The unique index is `(table_id) WHERE status IN ('open','bill_requested')`, not just `'open'` as SPEC §7.6 words it. With `'open'` only, a second guest scanning while the first has requested the bill would open a second tab, and the bill_requested→open transition (more items added) would then violate the index.
- **Undo.** Whole-round cancel (the state machine cancels an Order, not a line), by the placing TabSession only. Line-level removal after that is a manager void (Milestone 5). Auto-accept is lazy: an atomic `UPDATE … WHERE status='placed' AND placed_at < now-60s` runs on every tab read, order placement and undo, and writes the `order_accepted` event once. Milestone 3c adds a scheduled push so kitchen screens don't wait for a read.
- **Guest cannot order liquor that needs approval.** If the outlet has `liquor_approval_required` and the item has `needs_approval`, the guest gets 409 `needs_waiter` ("Ask your waiter"). The approval workflow itself is Milestone 5; ignoring the setting would let restricted items through unapproved.
- **Snapshots.** `unit_price_snapshot` is the effective item price (base or price-rule) in the outlet's tax mode; modifier deltas live in `modifiers_snapshot`; `line_total = (unit + Σ deltas) × qty`. `tax_class_snapshot` is `{name, rate_bp, is_liquor, prices_include_tax}`. `price_rule_id` has no foreign key and the rule name is snapshotted too, so deleting a rule never touches an order line. `menu_item_id` does have one: an item with order history cannot be deleted (409), only made unavailable.
- **Running total is an estimate.** The live tab shows service charge as a separate line computed on taxable value with no GST on it, and labels the total an estimate. How GST applies to service charge is a tax question for the CA (like liquor billing) and is settled with the bill in Milestone 5; nothing is persisted from this estimate.
- **Idempotency scope.** `idempotency_key.user_id` becomes `actor_id` (a staff user id or a guest TabSession id, no foreign key) so guest order placement can be idempotent.
- **Ack rule is pure and unwired.** `decide_staff_line_ack` (threshold and `ack_waived`) lands in `core` with tests now; it is called when staff can add lines in Milestone 4.
- **Slices.** 3a tab/session/order API, 3b guest PWA, 3c realtime and Playwright. Each is its own commit on `milestone-3/guest-ordering`.

## 2026-09-18 — Milestone 2 choices (menu and tables)

Confirmed by a human: **public self-serve signup**, **segno + WeasyPrint** as new dependencies, **price-rule semantics**, and **staff invites bound to the invited phone**. Everything else below is a choice the spec left open.

- **Signup** (`POST /v1/signup/otp`, `POST /v1/signup`): a verified phone creates a restaurant, first outlet and owner; an existing staff phone may start a second restaurant. This is an unauthenticated, tenant-creating endpoint. Controls today: single-use OTP, 5 code requests per phone per 15 minutes (same limit for known and unknown numbers). **Not covered:** per-IP limits and CAPTCHA, which belong at the edge (WAF / gateway) before this is exposed publicly. The OTP store and throttle are in-process, so limits are per API replica until Redis backs them. Exempt from `Idempotency-Key`: the single-use OTP already makes a replay a no-op.
- **Price rules.** `fixed` replaces the base price (in the outlet's with-tax / plus-tax mode); `percent_off` is basis points off the base, rounded half up once. Item beats category beats all; ties pick the lowest price, then lowest rule id. Modifier deltas are never discounted. A window that crosses midnight belongs to its start day; `start_time == end_time` is rejected by the API. Weekdays are 0 = Monday. Evaluated in the outlet timezone by the pure `app.core.pricing.effective_price`.
- **Staff invites** are bound to the invited phone: 7-day expiry, single use, token stored as SHA-256, link opens the staff app at `/invite/<token>`, plus a `wa.me` deep link (no WhatsApp API needed). A new invite for the same person and role revokes the pending one. **RLS change needing review:** `staff_invite_by_token`, a SELECT-only policy on `app.invite_token_hash`, the same pattern as `staff_role_self_read`.
- **Roles.** Managers invite, deactivate and reactivate **waiters only**; every other role, and every role change, is owner-only (SPEC §6 "Waiters only"). An outlet cannot lose its last active owner (409). Three capabilities not in SPEC §6 were added: `VIEW_MENU` and `VIEW_OUTLET_SETTINGS` (every staff role) and `EDIT_OUTLET_SETTINGS` (owner). Table create/edit/rotate uses `GENERATE_TABLE_QRS` (manager, owner). QR links are returned only to roles that may print them.
- **Roles are re-read from the database on every request.** The JWT only says which tenant to look in, so deactivating someone takes effect on their next request instead of when the token expires (up to 1 hour). Cost: one indexed query per request. Access tokens still have no refresh; the UI re-authenticates on 401.
- **Settings.** `state_code` is the 2-digit GST state code (`29`, not `KA`); GSTIN is checksum-validated and its first two digits must match. Changing `prices_include_tax` is refused (409 `prices_mode_locked`) once the outlet has any menu item, because it would silently reinterpret every stored price. `invoice_prefix` changes write two audit rows; the counter is never touched. "Go-live" is computed (`ready_to_go_live` plus blockers: GSTIN, one tax class), not a stored flag; a stored flag arrives with the guest QR landing in Milestone 3.
- **Menu rules.** Liquor items need a liquor-VAT tax class, food items a GST class, and liquor needs a licensed outlet. Category, item, station, tax-class and modifier names are unique per parent, case-insensitively. Writes use PUT (full replacement) except settings and staff (PATCH).
- **CSV import.** Columns: `category,item,description,price,tax_class,veg,is_liquor,station,available,sku,modifier_groups` (price in rupees as printed on the card, converted with `Decimal`). Tax classes, stations and modifier groups must already exist; categories are created. Import only **adds and updates**: items missing from the file are listed in the preview but never deleted. `POST .../menu/import/preview` returns errors and a diff plus a `diff_hash`; `.../apply` needs that hash and refuses (409 `menu_changed`) if the menu moved since the preview. The body is raw `text/csv` (no multipart dependency); limits are 1 MB and 2,000 rows. `GET .../menu/export.csv` is both the template and a full export.
- **Idempotency** (`Idempotency-Key` header, optional): stored in `idempotency_key`, scoped per (restaurant, user, key), written in the handler's own transaction, only successful responses are replayed, a different body or operation under the same key is 422. **Pending:** no expiry job yet (rows accumulate until the Celery jobs milestone).
- **Owner UI** lives in `apps/staff` and is plain client-rendered React over the generated API types. The access token is kept in `localStorage` so a reload keeps the owner signed in; the trade-off is that a script on that origin could read it, so the app renders no untrusted HTML. The UI hides links by role but the API is what enforces them. Prices are typed in rupees and converted to paise with string maths (`parseRupees` in `packages/ui`), never floats.
- **Browser tests.** They cannot read the API console, so the API accepts `OTP_DEV_FIXED_CODE`; startup fails if it is set with `ENVIRONMENT=production`. CORS allows only the configured app origins (`CORS_ORIGINS`) and the `Idempotency-Key` header.
- **QR.** `qr_token` is 12 URL-safe characters. Links are `PUBLIC_BASE_URL/t/<token>`; the product domain is still undecided (SPEC §12), so it is configuration. PDFs are rendered with WeasyPrint from escaped HTML: one QR page per zone, and a menu PDF of visible categories only. WeasyPrint needs Pango (`brew install pango` on macOS, plus `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib`; the Docker image installs it).

## 2026-09-18 — Milestone 1 implementation choices the spec did not dictate

- **Naming.** `table` and `user` are reserved SQL words, so the tables are `dining_table` and `app_user` (models `DiningTable`, `AppUser`). Money columns are `*_paise`; every rate is stored as basis points (`percent * 100`: 5% is 500), including `outlet.liquor_vat_rate_bp`, `outlet.service_charge_bp`, `tax_class.gst_rate_bp` and percent-off `price_rule.value`, so fractional rates never need a float.
- **`restaurant_id` on every tenant table**, including `staff_role`, `modifier` and `menu_item_modifier_group`, which docs/SPEC.md §7 lists without it. CLAUDE.md §3 requires it and wins over the spec; it keeps every RLS policy a direct column check. `restaurant` itself is also under RLS (`id = app.restaurant_id`) so a tenant session cannot list other tenants.
- **Tenant comes from the signed JWT, not the request.** Each role claim is `{restaurant_id, outlet_id, role}` (SPEC §6 only says `(outlet_id, role)`); the API sets `app.restaurant_id` from the claim matching the path's `outlet_id`. No claim for that outlet is a 403.
- **`staff_role_self_read` policy (RLS change, needs human review per CLAUDE.md §9).** At login the API knows the user but not their restaurants, and `staff_role` is otherwise unreadable without a tenant. After OTP verification one transaction sets `app.user_id`; a second, SELECT-only policy lets that user read exactly their own role rows. Alternatives considered: a `SECURITY DEFINER` lookup function, or storing restaurant on `app_user`. The policy is smaller and stays inside RLS.
- **OTP store is an in-process stub** (5-minute expiry, 5 attempts, single use, OTP printed to the console when `OTP_DEV_MODE`). It does not work across API replicas. Replace with Redis plus the WhatsApp/SMS sender when the Celery job queue lands.
- **Deferred to Milestone 3:** the "TabSession for tab A cannot write to tab B" API test. The pure-function rule (`assert_can_write_own_tab`) is implemented and unit-tested now; the API test needs `Tab`/`TabSession`, which do not exist yet.
- **Tooling pins.** TypeScript is pinned to 5.x (7.x removed the JS compiler API that `openapi-typescript` and `next build` use) and ESLint to 9 (`eslint-plugin-react` does not support 10). ESLint, `@lhci/cli` (needed by CI's `lighthouse:ci`) and the Next/React/Vitest/Playwright/`openapi-typescript` stack were added because `ci.yml` requires them; no other frameworks were introduced.
- **Local ports.** Dev Redis is published on 6380 (6379 was taken by another container on the dev machine). E2E ports are configurable via `E2E_*_PORT`, and Playwright only reuses existing servers when `CI` is set.
- **Guest bundle baseline.** An empty Next 16 / React 19 page is already 130 kB gzipped first-load JS (polyfills excluded) against the 170 kB budget, leaving about 40 kB for the entire guest app. Worth watching from Milestone 3.

## 2026-09-18 — Separate migration-owner and runtime DB roles (CI change needed)

**Decision:** Migrations and test seeding run as an owner role; the API runs as `app`, a `NOSUPERUSER NOBYPASSRLS` role created by migration 0001 that owns nothing. `MIGRATION_DATABASE_URL` is the owner connection (falls back to `DATABASE_URL`). Local and compose Postgres use `postgres` as the bootstrap owner.

**Reason:** Postgres refuses to demote the bootstrap superuser, and superusers skip RLS regardless of policies. `.github/workflows/ci.yml` sets `POSTGRES_USER: app`, which makes `app` the bootstrap superuser, so as written CI cannot enforce or verify RLS: `scripts/check_rls.py` reports `role 'app' has BYPASSRLS`, and the cross-tenant API tests would run as a superuser. A separate owner also lets us `REVOKE UPDATE, DELETE` on `tab_event`/`bill` later without fighting table ownership.

**Impact / needs a human:** I may not edit `.github/workflows/ci.yml`. The fix is small: in the `api-test` and `migrations` jobs set `POSTGRES_USER: postgres` / `POSTGRES_PASSWORD: postgres`, `pg_isready -U postgres`, add `MIGRATION_DATABASE_URL: postgresql+asyncpg://postgres:postgres@localhost:5432/<db>` and keep `DATABASE_URL` on `app:app`. Until then those two jobs fail on this branch by design (the failing test is `test_app_role_cannot_bypass_rls`).

## 2026-09-18 — Milestones 1–4 land on a long-lived `integration` branch, not `main`

**Decision:** `.github/workflows/ci.yml` requires `golden-flows` (all three Playwright flows) and `guest-budget` (Lighthouse) to pass on every PR. Those flows exercise ordering, staff-added-line disputes, and billing UI that don't exist until Milestone 5. Milestones 1–4 merge into a shared `integration` branch instead of `main`; `golden-flows`/`guest-budget` only need to go green once Milestone 5 lands and `integration` merges into `main`. `main`'s branch protection and `.github/workflows/ci.yml` are untouched, per CLAUDE.md §10 ("agent must not ... edit `.github/workflows/`").

**Reason:** CLAUDE.md forbids weakening a CI gate to get green, and forbids editing the workflow without a human's yes; faking golden-flow Playwright specs before the features exist would violate both. A real golden flow needs real ordering/billing UI, which is sequenced for Milestone 5.

**Impact:** No change to `.github/workflows/ci.yml` or branch protection. Each milestone PR targets `integration`, not `main`, and only `api-lint`, `api-test`, `migrations`, `openapi-client`, `web-lint` need to be green on those PRs (jobs whose preconditions already exist). `golden-flows`/`guest-budget` remain configured to run on every PR per the workflow file as-is; they are expected to fail on `integration`-bound PRs until Milestone 5's slice lands, and that failure is not a milestone blocker until the final `integration` → `main` PR.

## 2026-09-18 — Staff-added lines on a tab with no live TabSession waive customer ack

**Decision:** A walk-in `Tab` opened by a waiter (no phone, no QR scan) has no `TabSession` to ack against. Staff-added lines on such a tab — regardless of `line_total` vs. `outlet.ack_threshold` — skip `needs_customer_ack` and instead write a `TabEvent` with `event = 'line_added'` and `payload.ack_waived = true` (no customer ever gets the chance to acknowledge, since there is no device to ask).

**Reason:** `needs_customer_ack` (SPEC §7.3, §3 in CLAUDE.md) assumes a guest device is present to tap "Yes, ours" / "Not ours." A tab with no `TabSession` has nowhere to route that ack, and the code must not silently drop the requirement or silently mark it acked as if a guest had responded.

**Impact:** `OrderLine.needs_customer_ack` computation branches on whether the tab has a live `TabSession` (not only on `line_total`/threshold). `TabEvent` gains the `ack_waived` payload flag as a first-class, tested case alongside `line_acked` — distinct from a real acknowledgement, so the event log and manager UI can show "no guest device to ask" rather than implying consent.

## 2026-09-18 — QR short-URL scheme: single domain, opaque token

**Decision:** `https://<product-domain>/t/<qr_token>` — a single domain, no outlet subdomain or slug in the path. `qr_token` is an opaque, rotatable token; the server looks up outlet and table from it.

**Reason:** Required before Milestone 1 per `docs/AGENT-KICKOFF.md` and listed as open in SPEC §12. Avoids wildcard-subdomain DNS/TLS setup and keeps table identity out of the URL.

**Impact:** No outlet slug/subdomain field needed on `Outlet` for routing. `Table.qr_token` remains the sole lookup key; rotating it (per SPEC §7.2) is the only way to invalidate a printed QR. Actual product/domain name is a branding decision, still open — not addressed here.

## 2026-09-18 — Liquor billing: one Bill per Tab, sections not separate invoices

**Decision:** MVP always issues a single `Bill` per closed `Tab`, with food and liquor as separate subtotal/tax sections (`subtotal_food`, `subtotal_liquor`, `cgst`, `sgst`, `liquor_vat` on `Bill`). Two-invoice mode (`Outlet.liquor_billing_mode`) is out of MVP scope.

**Reason:** SPEC §9 raises two-invoice mode as a possibility but SPEC §7's schema only supports one `Bill` per `Tab`; splitting invoices is a compliance question, not a product one.

**Impact:** No `Outlet.liquor_billing_mode` field in Milestone 1. Pending CA input before this is revisited — see open compliance questions in SPEC §9.

## 2026-09-18 — Invoice numbering: owner-editable prefix, length-constrained, audited

**Decision:** `invoice_no` renders as `{invoice_prefix}/{next_invoice_no}`, monotonically increasing, never resets automatically. Total rendered length ≤ 16 characters (GST rule). `Outlet.invoice_prefix` is owner-editable so a new series can start at a financial-year boundary without touching the counter. Changing `invoice_prefix` writes an `AuditLog` entry.

**Reason:** SPEC §7 defines `invoice_prefix` and `next_invoice_no` but not the rendered format or reset policy; invoice numbering is named in CLAUDE.md §9 as something to stop and ask a human about.

**Impact:** `Outlet.invoice_prefix` becomes owner-editable via API (previously assumed fixed at onboarding); the update path must write `AuditLog` and validate combined length against `next_invoice_no`'s expected max digits.

## 2026-09-18 — One open tab per table, no outlet flag

**Decision:** Hard unique index `(table_id) WHERE status = 'open'` on `Tab`. No `Outlet` setting to allow multiple open tabs per table. Bar counter seats are modelled as `Table` rows (e.g. "B1", "B2").

**Reason:** SPEC §7.6 mentions multiple tabs per table as a possible outlet option but doesn't specify it elsewhere; keeping it out simplifies QR-scan tab resolution for MVP.

**Impact:** No `Outlet.allows_multiple_tabs_per_table` field. QR scan always resolves to the single open `Tab` for that `table_id`, or opens a new one.

## 2026-09-18 — Customer actor model for unauthenticated guests

**Decision:** `TabEvent.actor_user_id` is nullable. `actor_type = 'customer'` writes are authorised by ownership of a live (unexpired, unrevoked) `TabSession` scoped to that `tab_id`, not by the `docs/SPEC.md` §6 role matrix.

**Reason:** Guests never log in (CLAUDE.md §1, §4), so `assertCan()`'s role-matrix model doesn't apply to their writes.

**Impact:** `assertCan()` gains a second authorization path for customer actors, keyed on `TabSession` ownership rather than `(outlet_id, role)`. Must add an API test: a `TabSession` issued for tab A must fail to write to tab B in the same outlet.

## 2026-09-18 — Tax storage: outlet-configurable inclusive/exclusive, not hard-coded

**Decision:** `Outlet.prices_include_tax` (bool, default `true`). `MenuItem.base_price` stores exactly what the owner typed, interpreted per the outlet's mode. `OrderLine` snapshots the mode alongside price/tax-class at order time. At bill time, per-line taxable value and tax are derived from the snapshot; tax totals on `Bill` are the sum of line-level taxable values (not computed top-down), so the invoice reconciles; `round_off` absorbs the final paise difference.

**Reason:** Restaurant menus in India commonly show tax-inclusive prices; bars and clubs commonly show "+ taxes as applicable" (tax-exclusive). Hard-coding one mode would make the owner-entered price differ from the printed menu, which is exactly the "menu says a different price" dispute the product exists to prevent.

**Impact:** New `Outlet.prices_include_tax` field. `OrderLine` needs a `prices_include_tax` (or equivalent) value in its snapshot set, alongside `tax_class_snapshot`. Tax computation in `apps/api/app/core/` derives per-line taxable value from `(unit_price_snapshot, prices_include_tax_snapshot, tax_class_snapshot)` rather than assuming exclusive storage; `Bill.cgst`/`sgst`/`liquor_vat` are sums of line-level amounts, not rate × subtotal.
