# CLAUDE.md — rules for AI agents working in this repo

You are building a multi-tenant QR ordering and billing SaaS for Indian restaurants, bars and clubs.
The product spec is `docs/SPEC.md`; screen flows are `docs/UI-FLOWS.md`; how every screen looks and behaves is `docs/DESIGN.md`. Read all three before your first task.
When the spec and this file disagree, this file wins; when either disagrees with a human's instruction in the task, ask before proceeding.

## 1. What we are optimising for

1. A guest scans a table QR and places a first order in under 20 seconds, with no login.
2. Every bill is explainable: locked prices, an append-only event log, immutable invoices.
3. Staff see only what their role needs, enforced at the API and database, not the UI.
4. The system survives a bar at 11 PM on a Saturday: flaky Wi-Fi, cheap Android phones, double taps.

If a change makes any of these worse, stop and say so rather than shipping it.

## 2. Stack (fixed unless a human changes this section)

Two languages by design: **Python owns every business rule; TypeScript owns only rendering.** Money, tax, state machines and permissions exist once, in Python. Front-ends consume generated types from the API's OpenAPI schema and never re-implement a rule.

- Monorepo: `apps/api` (Python) plus a pnpm workspace for the three Next.js apps and `packages/ui`. `make check` runs every gate locally in the same order as CI.
- `apps/api` — Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 (async, asyncpg), Alembic migrations checked in as SQL-visible revisions, `uv` for dependency management, `ruff` for lint/format, `mypy --strict`. One service, packages by domain: `menu`, `tab`, `order`, `billing`, `staff`, `tenant`, `realtime`.
- `apps/api/app/core/` — money (integer paise, Indian formatting), tax maths, Tab/Order state machines, permission matrix. Pure functions, no I/O, 100% branch coverage enforced.
- Real-time: FastAPI WebSocket endpoint, one channel per outlet, messages filtered by role; Redis pub/sub fans out across API replicas.
- Jobs: Celery on Redis for invoice PDFs (WeasyPrint), WhatsApp/SMS, exports.
- Database: Postgres 16. RLS policies live in Alembic migrations. Migration lint (`scripts/check_rls.py`) fails CI if a tenant table lacks a policy.
- `apps/guest`, `apps/staff`, `apps/admin` — Next.js PWAs (App Router). `packages/ui` for components used by two or more apps. `packages/api-client` is **generated** from `openapi.json` with `openapi-typescript`; it is committed and CI fails if it is stale.
- Tests: `pytest` (+ `pytest-asyncio`, `httpx`) against a real Postgres container, never mocked; Vitest for front-end units; Playwright for the golden flows (section 7).
- CI: GitHub Actions, `.github/workflows/ci.yml`. All jobs are required status checks on `main`; see section 10.

Do not introduce a new framework, ORM, task queue, state library or UI kit without a human saying yes in the task text.

## 3. Domain invariants (never violate; write a test for each when you touch the area)

- **Tenancy.** Every tenant-owned table has `restaurant_id`. Every query runs with `SET LOCAL app.restaurant_id`. RLS policies exist on every tenant table; the app role has no `BYPASSRLS`. A cross-tenant read in a test must return zero rows, not an error.
- **Money.** Integers in paise. No floats anywhere in money code. Rounding happens once, at bill issue, into `round_off`.
- **Price lock.** `OrderLine` stores `item_name_snapshot`, `unit_price_snapshot`, `tax_class_snapshot`, `modifiers_snapshot`, `price_rule_id`. Bills are computed only from snapshots. Editing a `MenuItem` must never change any existing `OrderLine` or `Bill`.
- **Event log.** `TabEvent` is insert-only. Every state change on a tab or order line writes an event with `actor_type`, `actor_user_id`, `reason` where relevant. No UPDATE/DELETE grants on `tab_event` or `bill` for the app role.
- **Immutable bills.** `Bill` and `BillLine` are written once at tab close inside a transaction that allocates `invoice_no` via `SELECT ... FOR UPDATE` on `outlet`. Corrections are `CreditNote` rows. There is no "edit bill" endpoint.
- **Idempotency.** Every write endpoint from a client accepts an `Idempotency-Key` header (client UUID). Replays return the original response. Order placement in particular must be safe against double submission.
- **Staff-added lines.** `placed_by = 'staff'` lines record `staff_user_id`; lines with `line_total >= outlet.ack_threshold` (default ₹500) set `needs_customer_ack = true`.
- **State machines.** Tab and Order transitions are defined once in `apps/api/app/core/state.py` and enforced server-side. Illegal transitions return HTTP 409 with the current state.
- **Roles.** Permission checks live in `apps/api/app/core/permissions.py` as a single matrix mirroring `docs/SPEC.md` §6. Route handlers call `assertCan(actor, capability, outletId)`. The UI hiding a button is not a permission check.
- **Delivery hooks.** `Order.fulfillment_type` defaults to `dine_in`. Do not remove or hard-code around `pickup`/`delivery`, `DeliveryJob`, `AggregatorOrder`; they are Phase 3 hooks.
- **Personal data.** Customer phone numbers are optional, collected only for receipts, never joined into analytics or exports.

## 4. India-specific rules

- Tax is configured per outlet via `TaxClass`; never a constant. Food lines get CGST + SGST split equally; liquor lines get state VAT and no GST.
- Service charge is a separate, removable line. Removal is not a void and needs no reason.
- Invoice shows outlet GSTIN, sequential per-outlet invoice number, date, per-line taxable value and rate, optional customer GSTIN.
- Phone-number OTP login for staff; no email or password fields anywhere.
- Currency formatting: `₹1,23,456.00` (Indian grouping). Use `app.core.money.format_inr` server-side and the generated formatter in `packages/ui` client-side (display only).
- Times are stored UTC and rendered in `outlet.timezone`.

## 5. How to work

1. **Read before writing.** Open `docs/SPEC.md` §4 (scope), §6 (roles), §7 (schema), §8 (state machines) for any task in that area.
2. **Plan first for anything over ~50 lines.** Post a short plan (files to touch, tests to add, open questions) before editing. If a question changes the design, stop and ask; do not guess.
3. **One vertical slice per PR.** Migration + API + regenerated client + UI + tests together, behind a feature flag if it is not complete. Never merge a migration without the code that uses it.
4. **Migrations are forward-only and reviewed.** Alembic revisions named `NNNN_short_description.py` with raw SQL for DDL so the diff is readable. Include the RLS policy for every new tenant table in the same migration.
5. **Tests are not optional.** `pytest` units for money, tax and state machines; API tests for every endpoint including a cross-tenant and a wrong-role case; a Playwright test if you touched a golden flow.
6. **Do not mock the database in API tests.** Use the test Postgres container (`make test-db`).
7. **Keep the guest app small.** Budget: first load under 2 s on a mid-range Android over 4G. Check bundle size in CI; no new dependency in `apps/guest` over 20 kB gzipped without justification in the PR.
8. **Out-of-scope means out.** Do not build KDS station routing, in-app payment gateways, OCR import, POS integrations, delivery UI or native apps unless the task explicitly opens that phase. Leave the schema hooks alone.
9. **Feature flags** live in `apps/api/app/core/flags.py` and are per outlet, exposed to clients via the outlet settings endpoint. Waiter-confirm mode, liquor approval and ack threshold are outlet settings, not global.
10. **Secrets** never enter the repo. Use `.env.example` with placeholder values; real values come from the environment.
11. **UI follows `docs/DESIGN.md`.** Read it before building or changing any screen, component or style. Use its tokens and shared components; do not add hex colours, pixel sizes or one-off button styles. If a screen needs something the doc lacks (a token, a component, a pattern), add it to the doc first, in the same PR, then use it. Every data screen ships its loading, empty and error states. When you fix a finding from its audit table, mark it done there.

## 6. Code conventions

- Python: `snake_case` modules and functions, `PascalCase` classes, `StrEnum` for enums, Pydantic models suffixed `In`/`Out`. TypeScript: `kebab-case` files, `PascalCase` types. DB columns `snake_case`.
- API routes: `POST /outlets/:outletId/tabs/:tabId/orders`, resource-oriented, versioned under `/v1`.
- Errors: `{ code, message, details? }` with stable `code` strings; never leak stack traces.
- Logging: structured JSON with `restaurant_id`, `outlet_id`, `actor_user_id`, `request_id` on every line.
- UI: components in `packages/ui` only when used by two apps. Touch targets ≥ 44 px. Real `<button>`/`<a>`/`<input>`; no click handlers on `div`s. Styling comes from the tokens in `packages/ui/src/tokens.css` (see `docs/DESIGN.md`), never literal values.
- Copy: short, plain English; no jargon on guest screens. Currency with ₹.
- Commits: conventional commits (`feat(tab): ...`, `fix(billing): ...`). One logical change per commit.

## 7. Golden flows (Playwright, must stay green)

1. **Guest orders and pays:** scan → menu → add 2 items with a modifier → place → tab shows lines with locked prices → request bill → waiter records UPI → bill issued with correct CGST/SGST and VAT → guest sees "Paid".
2. **Staff-added line dispute:** waiter adds a ₹520 line → guest sees "awaiting your ack" → guest taps "Not ours" → manager opens event log → voids with reason "wrong table" → guest tab shows struck-through line with reason → bill excludes it.
3. **Happy hour lock:** order a beer during a price rule window → price rule ends → menu price changes → tab and bill still show the locked price and rule id.

## 8. Definition of done for any task

- [ ] Plan was posted and any blocking questions answered
- [ ] Migration (if any) includes RLS, passes `scripts/check_rls.py`, and is reversible in intent (documented)
- [ ] Unit + API tests added, including cross-tenant and wrong-role cases
- [ ] Golden flows pass; `packages/api-client` regenerated if the API changed
- [ ] `make check` green locally (same gates as CI)
- [ ] No new secrets, no new out-of-scope feature, no float money
- [ ] UI changes: the checklist in `docs/DESIGN.md` §6 is ticked in the PR (tokens only, all four states, checked at 390 px and 1280 px with screenshots, keyboard and contrast, guest bundle budget)
- [ ] PR description: what, why, how tested, screenshots for UI, anything you were unsure about

## 9. When to stop and ask a human

- The task conflicts with an invariant in §3 or a rule in §4.
- You need a new dependency, framework or external service.
- The task touches invoice numbering, tax computation or RLS policies.
- The spec is silent and the choice is hard to reverse (schema shape, public API shape, auth model).
- You are about to delete or rewrite more than ~200 lines someone else wrote.

Ask in the PR or task thread with the specific question and your recommended answer. Do not proceed on an assumption for these.

## 10. CI gate (required checks; no exceptions, including for agents)

`main` is protected. A PR merges only when every job below is green and one human has approved. The agent must not push to `main`, force-push, edit `.github/workflows/`, or change branch protection; if CI is wrong, open a PR that fixes it and say why.

| Job | What it runs | Fails when |
| --- | --- | --- |
| `api-lint` | `ruff check`, `ruff format --check`, `mypy --strict` | any finding |
| `api-test` | `pytest` against Postgres 16 + Redis services, coverage | any failure; `app/core/` below 100% branch coverage; overall below 85% |
| `migrations` | `alembic upgrade head` on empty DB, then `alembic downgrade -1 && upgrade head`, then `scripts/check_rls.py` | migration errors; any tenant table without an RLS policy; app role has BYPASSRLS |
| `openapi-client` | export `openapi.json`, regenerate `packages/api-client`, `git diff --exit-code` | committed client is stale |
| `web-lint` | `pnpm lint`, `pnpm typecheck`, Vitest | any finding |
| `guest-budget` | Next build of `apps/guest`, bundle size report | first-load JS over 170 kB gzipped, or Lighthouse mobile performance below 90 on throttled 4G |
| `golden-flows` | Playwright: the three flows in section 7 against the full stack in Compose | any flow fails; runs on every PR, not just main |
| `secrets` | gitleaks | any secret |

The same gates run locally with `make check`; do not open a PR until it passes. If a gate is flaky, fix the flake in its own PR; never mark a test skipped to get green.
