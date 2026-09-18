# Kickoff prompt for the coding agent

Paste the block below as the first message to Claude Code (or an equivalent agent) in an empty repo that already contains `CLAUDE.md`, `docs/SPEC.md` and `docs/UI-FLOWS.md`. Run milestones one at a time; start a fresh session per milestone and paste the milestone block for it.

---

## Session 0 — orientation (paste first)

You are the lead engineer on this repo. Before writing any code:

1. Read `CLAUDE.md` in full. It contains the stack, the domain invariants and the rules for how you work. Treat it as binding.
2. Read `docs/SPEC.md` sections 1, 4, 5, 6, 7, 8, 9 and `docs/UI-FLOWS.md` sections 1, 2 and 6.
3. Reply with, in this order, and nothing else:
   - a ten-line summary of what the product is and what the MVP excludes;
   - the five invariants you think are easiest to accidentally break, and how you will test each;
   - any question where the spec is silent and the answer changes the schema or public API. Recommend an answer for each. Do not start Milestone 1 until these are answered.

---

## Milestone 1 — skeleton and tenancy

Goal: an empty but real monorepo where tenancy, roles and the golden-flow harness exist before any feature.

Deliver, as one PR:

- Monorepo per `CLAUDE.md` §2: `apps/api` (Python 3.12, FastAPI, `uv`), pnpm workspace with `apps/guest`, `apps/staff`, `apps/admin`, `packages/ui`, `packages/api-client` (generated). A root `Makefile` with `make dev`, `make test-db`, `make check`.
- Docker Compose for Postgres 16 and Redis; `make dev` runs everything; `make test-db` runs `pytest` against a throwaway database.
- Alembic revisions 0001–0004 creating: `restaurant`, `outlet`, `user`, `staff_role`, `platform_admin`, `audit_log`, `table`, `station`, `tax_class`, `menu_category`, `menu_item`, `modifier_group`, `modifier`, `menu_item_modifier_group`, `price_rule`. Every tenant table has `restaurant_id`, RLS enabled, and a policy `restaurant_id = current_setting('app.restaurant_id')::uuid`. The app DB role has no BYPASSRLS.
- `apps/api/app/core/`: money helpers (paise, Indian formatting), `TaxClass` maths with CGST/SGST split and liquor VAT, and the Tab and Order state machines from `docs/SPEC.md` §8 as pure functions with exhaustive `pytest` cases and 100% branch coverage.
- `apps/api`: FastAPI with a request-scoped session that runs `SET LOCAL app.restaurant_id`, phone-OTP auth stub (OTP printed to console in dev), JWT with `user_id` and the list of `(outlet_id, role)` pairs, `assert_can()` permission matrix mirroring SPEC §6, `/health`, structured JSON logging, OpenAPI export script and generated `packages/api-client`.
- `pytest` API tests proving: a user with a role at outlet A cannot read outlet B's rows (zero rows, not error); a waiter calling a manager-only endpoint gets 403; money and tax maths match ten hand-computed cases including rounding.
- Playwright installed with a single smoke test that boots all three apps against the API.
- `.github/workflows/ci.yml` implementing every job in `CLAUDE.md` §10, plus `scripts/check_rls.py`. This PR is not done until CI is green on it and branch protection on `main` requires all jobs. Do not edit the workflow in later milestones without a human's yes.
- `README.md` with setup in under ten commands.

Stop and ask before choosing: tax-inclusive vs tax-exclusive price storage (recommend one), and the short-URL scheme for QR links.

---

## Milestone 2 — menu and tables (owner surface)

Goal: an owner can set up an outlet, load a menu and print QRs.

- Outlet setup (GSTIN, state, liquor flag, VAT rate, service charge %, ack threshold, waiter-confirm mode, timezone).
- Menu CRUD with categories, modifiers, tax classes, availability toggle, sort order; CSV import with a validation report and a diff preview before apply.
- Price rules (happy hour): scope, window, days, value; a pure function `effectivePrice(item, rules, at)` with tests across midnight and timezone edges.
- Tables and zones; `qr_token` generation and rotation; QR sheet PDF (one page per zone) and menu PDF from current data.
- Staff invite by link + OTP; role assignment; deactivate.
- Owner UI in `apps/staff` for all of the above, per `docs/UI-FLOWS.md` §5.

Acceptance: a fresh outlet can go from sign-up to printed QRs in under 90 minutes by a non-engineer following `README.md`.

---

## Milestone 3 — guest ordering and live tab

Goal: golden flow 1 up to "request bill", and golden flow 3.

- QR landing: exchange `qr_token` for a `TabSession` (cookie), joining the table's open tab or opening one; waiter-confirm mode blocks ordering until confirmed.
- Menu home, item sheet with modifiers, cart, place order (idempotent, snapshots every price and name, records `price_rule_id`), 60-second customer undo before `accepted`.
- Live tab: rounds, per-line source and status, running total with tax split and removable service charge, voided lines struck through with reason.
- Service requests: waiter / water / bill.
- WebSocket gateway: outlet channel, role-filtered messages, reconnect with resume.
- Performance budget enforced in CI: guest first load under 2 s on a throttled 4G profile, bundle report in the PR.
- Playwright: golden flow 3 and the guest half of golden flow 1.

---

## Milestone 4 — waiter and kitchen

Goal: the staff side of golden flows 1 and 2.

- Table map with state colours and badges; table view with rounds; add items for guest (reusing the guest menu components; `placed_by='staff'`, `needs_customer_ack` above threshold); mark served; transfer and merge tabs with events.
- Basic ticket queue for bar/kitchen: start, ready, sold-out toggle; no station routing beyond one station per item.
- Guest acknowledgement of staff-added lines: "Yes, ours" / "Not ours" creates events and a manager alert.
- Offline queue in the staff app: IndexedDB action queue, idempotency keys, replay on reconnect, visible banner.

---

## Milestone 5 — billing, payments, manager

Goal: golden flows 1 and 2 end to end; a CA can sign off the invoice.

- Request bill → bill preview → close tab: allocate `invoice_no` under `FOR UPDATE`, write `bill` and `bill_line` from snapshots, compute CGST/SGST/VAT/service charge/round-off, generate PDF, send WhatsApp/SMS receipt via a job (stub provider in dev).
- Payment recording: UPI (reference optional), card, cash; split by amount; close only when recorded = total. Manager override to close with a pending balance: reason required, manager PIN/OTP, logged, surfaces on day close.
- Manager: home with alerts (bill requested > 5 min, ticket > 15 min, ack pending > 3 min), event log view with PDF share, void/discount with reason, liquor approval, remove service charge, credit note on a closed bill.
- Day close: totals by method, voids, discounts, unsettled; blocks until unsettled amounts are resolved or acknowledged; CSV export.
- Platform admin: onboard restaurant, subscription plan, suspend, impersonate with audit log.
- Playwright: golden flows 1 and 2 complete.

---

## Standing instructions for every session

- Post a plan before editing anything larger than a small fix. List files, tests, and open questions.
- Never invent business rules. If `docs/SPEC.md` is silent, ask with a recommended answer.
- Keep PRs to one vertical slice. Include the migration, API, shared schema, UI and tests together.
- Run `make check` before declaring anything done, and paste the summary. Never skip or weaken a CI job to get green.
- When you finish a milestone, write `docs/DECISIONS.md` entries for every choice you made that the spec did not dictate, with the date and the reason.
