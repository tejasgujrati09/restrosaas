# Design system and UI audit

The single reference for how every screen looks and behaves. **Read this before building or changing any screen** (CLAUDE.md §5, §8). It has two parts: the rules (Part 1, binding) and the audit that produced them (Part 2, the record of what was wrong and what is done).

Visual direction: the "QR Ordering — Customer, Waiter & Manager Screens" design canvas (https://claude.ai/artifact/AuPcBoka9QYuqGbYXbtbFV). It is phone-only and has no admin, kitchen, login or desktop layouts; those follow the same tokens. Where the mock and this file disagree, this file wins: the mock's accent and grey fail WCAG AA, so they are darkened here.

Decisions confirmed by a human (2026-09-19): self-host fonts (Fraunces + Manrope); keep `₹1,23,456.00` everywhere (CLAUDE.md §4 wins over the mock's `₹320`); dark surfaces for waiter, kitchen and bar, light for guest and owner/manager, no user toggle; mock-only features (menu search, repeat last round, split bill, UPI QR, Print KOT, day close, reports) are **not** built by the UI refresh; the refresh lands before Milestone 5.

---

# Part 1 — Rules

## 1. Principles
1. **The next action is obvious.** One primary action per screen region; everything else is visibly quieter.
2. **State is never colour alone.** Every status has text or an icon as well.
3. **Phone first, then widen.** Design at 390 px, then use the extra width; never just scale up.
4. **No rule lives in the UI.** Labels, states and totals come from the API. The UI never recomputes money, tax or permissions.
5. **Every data screen has four states:** loading, empty, error, loaded. A screen without all four is not done.

## 2. Tokens

All values are CSS custom properties in `packages/ui/src/tokens.css`. **Never write a hex, pixel size or shadow in an app stylesheet or component; use a token.** A missing token is a design change: add it here first.

### Colour — light (guest, owner, manager)
| Token | Value | Use |
| --- | --- | --- |
| `--bg` | `#f6f1ea` | page |
| `--surface` | `#fffdfa` | cards, inputs, sheets |
| `--sunken` | `#f0ece5` | disabled, sold out, table stripes |
| `--border` | `#e8e1d6` | dividers, card edges |
| `--border-strong` | `#d9d2c7` | input and outline-button edges |
| `--ink` | `#1c1a17` | primary text |
| `--ink-2` | `#5c5751` | secondary text |
| `--ink-3` | `#6b655d` | captions (the lowest-contrast text allowed) |
| `--accent` | `#b34a26` | primary fills |
| `--accent-hover` / `--accent-active` | `#a04220` / `#8f3a1c` | |
| `--accent-text` | `#9a3f1f` | accent used as text or icon on light |
| `--ok` / `--ok-bg` | `#2a7148` / `#e6f0e9` | success, veg mark |
| `--warn` / `--warn-bg` / `--warn-line` | `#8a5a0c` / `#fff7e6` / `#f0d9a8` | needs attention, awaiting |
| `--danger` / `--danger-bg` / `--danger-line` | `#8a2f2f` / `#fdecec` / `#f2c4c4` | errors, destructive, disputes |
| `--info` / `--info-bg` | `#1f5f8b` / `#e7f0f7` | neutral notices |
| `--accent-bg` | `#fbf3ee` | tint behind accent text (tertiary button hover) |
| `--ok-line` / `--info-line` | `#bcd6c5` / `#b9d3e6` | borders for those tones |
| `--ok-solid` / `--danger-solid` | `#2a7148` / `#8a2f2f` | solid pills with white text (`--on-accent`), same in both themes |
| `--on-accent` | `#ffffff` | text on accent and solid fills |
| `--overlay` | `rgb(28 26 23 / .45)` | sheet backdrop |

### Colour — dark (waiter, kitchen, bar: `data-theme="dark"`)
`--bg #1c1a17`, `--surface #2a2724`, `--sunken #3a3632`, `--border #3a3632`, `--border-strong #4a4540`, `--ink #f6f1ea`, `--ink-2 #b5aea3`, `--ink-3 #aca59a`, `--accent #b34a26`, `--accent-text #f0a488`, `--ok #7fc99a`, `--warn #d9a441`, `--danger #f2a0a0`, `--info #8fc1e3`. Floor tile states, both themes: `--tile-empty`, `--tile-seated`, `--tile-new` (accent), `--tile-bill`, each with a matching `--tile-*-ink`. **Text on a tinted tile uses the tile's ink only**; grey secondary text fails contrast on the fills. Dark tints for the status backgrounds are in `tokens.css`.

Every text/background pair in `tokens.css`, light and dark, was checked at ≥ 4.5:1 (the mock's own accent, caption grey and green failed and were darkened). Re-check any new pair; do not eyeball it.

**Layers.** `tokens.css` declares `@layer ui-base, ui;`. Base element styles and the shared components live in those layers, so an app's own unlayered CSS overrides them with no specificity fight. App CSS holds layout for its own screens only.

### Type
Fraunces 600 (Display, H1, H2, and money totals); Manrope 500/600/700 for everything else. Self-hosted, Latin subset, `font-display: swap`. Money and quantities use `font-variant-numeric: tabular-nums`.

| Style | Token | Size / line | Weight |
| --- | --- | --- | --- |
| Display | `--t-display` | 28/34 | Fraunces 600 |
| H1 | `--t-h1` | 24/30 | Fraunces 600 |
| H2 | `--t-h2` | 18/24 | Fraunces 600 |
| H3 | `--t-h3` | 16/22 | Manrope 700 |
| Body | `--t-body` | 15/22 | Manrope 500 |
| Body small | `--t-small` | 13/18 | Manrope 500 |
| Label | `--t-label` | 12/16, +0.04em, uppercase | Manrope 700 |
| Caption | `--t-caption` | 12/16 | Manrope 500 |
| Button | `--t-button` | 15/1 | Manrope 700 |

Nothing below 12 px. Uppercase only for Label.

### Space, radius, elevation, motion
- **Space** (4-point): `--s-1` 4, `--s-2` 8, `--s-3` 12, `--s-4` 16, `--s-5` 20, `--s-6` 24, `--s-8` 32, `--s-10` 40, `--s-12` 48.
- **Layout:** page gutter `--s-5` (20) on phones and `--s-8` (32) from 768 px; section gap `--s-6`; content max-width 720 (forms and lists), 1120 (floor, tables), 560 (guest). Use `gap` and container padding, not margins on individual elements.
- **Radius:** `--r-sm` 8 (tags), `--r-md` 12 (inputs, buttons), `--r-lg` 14 (cards), `--r-xl` 20 (sheet top), `--r-pill` 999.
- **Elevation:** cards have a border and no shadow. `--shadow-pop` (`0 8px 24px rgb(28 26 23 / .14)`) only for sheets, menus and toasts.
- **Focus:** `:focus-visible` shows a 2 px ring, 2 px offset, colour `--ink`. Never `outline: none` without a replacement.
- **Motion:** 120–200 ms ease-out on colour, opacity and transform only. Everything is disabled under `prefers-reduced-motion`.
- **Touch targets:** 44 px minimum; 48 px for bar actions; 52 px for the main call to action.
- **Breakpoints:** phone < 640, tablet 640–1023, desktop ≥ 1024.

## 3. Components (in `packages/ui`)

Plain CSS classes and small React components; **no new UI library** (CLAUDE.md §2). Icons are inline SVG. Real `<button>`, `<a>`, `<input>` only.

- **Button** — `primary` (accent fill), `secondary` (surface + strong border), `tertiary` (text only), `danger` (danger text, never a solid red except in the confirm step of a destructive dialog). Sizes 44/48/52. Loading shows a spinner and keeps its width; disabled uses `--sunken` and `--ink-3`, not opacity. **At most one primary per screen region.**
- **Field** — visible label above, hint or error below (linked with `aria-describedby`), never placeholder-as-label. Error text names the fix. Short values get short inputs.
- **Card** — only for a meaningful group. Lists inside a card are rows with dividers, not nested cards.
- **Badge / StatusPill** — text plus a tone (`ok`, `warn`, `danger`, `info`, `neutral`). Never colour alone.
- **Banner** — inline notice with tone; `role="alert"` only for errors that just happened, `role="status"` otherwise.
- **Skeleton** — for loading lists and cards, sized like the content. A bare "Loading…" line is not allowed on a data screen.
- **EmptyState** — what is empty, why, and the next action.
- **Toast** — confirmation of a completed action (saved, sent). One live region; auto-dismiss after 4 s; errors stay.
- **PageHeader** — title (H1), one line of context, actions on the right (desktop) or below (phone).
- **DataList** — a real `<table>` from 640 px; the same rows stacked as labelled pairs below. Never a horizontally scrolling page.
- **Sheet, Stepper** — existing; restyled by tokens.
- **Money** — renders `formatInr`; display only.

## 4. Shell and navigation
- **Guest:** header (venue name in Fraunces, a `Table` pill, one line for the current happy hour) + bottom bar with a contextual primary action (view round, request bill) above the tab links (Menu, My tab, Call waiter).
- **Restaurant picker** (after sign-in, for people who work at more than one place): a grid of cards, one per outlet, each with an initial avatar, restaurant name, outlet and state, a role badge and a readiness badge. One outlet skips the picker.
- **Staff, phone:** slim top bar (venue, connection dot with text, account menu with Sign out) + bottom tab bar of at most four role-based destinations; the rest under **More**.
- **Staff, desktop (≥ 1024):** left sidebar grouped **Service** (Floor, Requests, Kitchen), **Manage** (Menu, Happy hours, Tables & QR, Assign tables, Staff), **Settings** (Setup); page header in the content column. The active item has `aria-current="page"` and a filled row. Sign out is in the account menu, never styled like a page action.
- Role filtering of links stays (`NAV` in `apps/staff/lib/nav.ts`); hiding a link is convenience, the API is the check.

## 5. Copy
Short, plain English, sentence case, no jargon on guest screens ("Taxes included", not "Included in prices: CGST/SGST/VAT"). Buttons say what they do ("Place order · ₹624", not "Submit"). Errors say what happened and what to do next.

## 6. Checklist for any new screen or change
Copy into the PR description and tick each.
- [ ] Uses tokens and shared components; no new hex, px size or one-off button style
- [ ] One clear primary action; secondary actions visibly quieter; destructive actions separated
- [ ] Loading (skeleton), empty (with next step), error (with recovery) and loaded states all built
- [ ] Checked at **390 px and 1280 px**; no horizontal page scroll; screenshots attached
- [ ] Every interactive element reachable and visible by keyboard (`:focus-visible`), labelled, ≥ 44 px
- [ ] Text contrast ≥ 4.5:1 (3:1 for 24 px+); status never by colour alone
- [ ] Money formatted with `formatInr`/`format_inr`; no rule re-implemented in TypeScript
- [ ] Guest bundle still ≤ 170 kB and Lighthouse ≥ 90 if `apps/guest` changed
- [ ] Existing Playwright flows still pass; accessible names kept stable unless the copy was the point

---

# Part 2 — Audit record

Audit date 2026-09-19, from screenshots of 24 screens at 390 and 1280 px against the running app. **Status** is updated by whoever fixes a finding.

## Findings
| # | Area | Finding | Status |
| --- | --- | --- | --- |
| 1 | Nav | Staff nav: 9 equal links wrap to 3–4 rows on a phone; no grouping; Sign out styled like a page action | done (UI-3): grouped sidebar on desktop; top bar + 3-tab bar + More sheet on phones; Sign out in the sidebar / More |
| 2 | Guest menu | Rows do not look tappable (no add control); no venue brand | done (UI-2) |
| 3 | Staff menu | Page overflows sideways at 390 px; Edit/Delete clipped; 4-line item names | done (UI-4): rows stack on phones, no sideways scroll; secondary actions quieter |
| 4 | Kitchen | Every sold-out button reads "Sold out" (action looks like state); list flush under tickets | done (UI-3): "Mark sold out" / "Available again" with a visible Sold out badge; neutral buttons |
| 5 | Buttons | Everything solid or outlined blue; no primary/secondary/destructive hierarchy | done (UI-1, applied per slice): one primary per region, secondary and tertiary quieter |
| 6 | Setup | Ten stacked full-width cards; one Save mid-page covers only some sections | done (UI-4): 720px column, short fields short, sticky Save bar that says what it covers |
| 7 | Menu page | Daily tasks and rare tasks (options, CSV) at one level; about 1,900 px tall | partly done (UI-4): clearer hierarchy and stacked rows; options and CSV import still on the same page |
| 8 | Guest tab | Round-level status only; "Request bill" below totals, not sticky | done (UI-2): sticky "Request the bill · ₹", running total, per-item progress (the API already sends line status) |
| 9 | Copy | "Included in prices: CGST/SGST/VAT" on guest screens | done (UI-2): "Taxes are already in your prices." |
| 10 | States | "Loading…", "Nothing waiting.", a red paragraph; no skeletons, no next step | partly done: `Skeleton` and `EmptyState` exist; screens adopt them per slice |
| 11 | Styles | Two near-identical `globals.css`; `.check`/`.grow` defined 3×; ~15 hard-coded hex | done (UI-1): one `tokens.css` + `components.css`; app CSS is token-only |
| 12 | Type/motion | System font only; no focus, transition or dark rules | done (UI-1): self-hosted Manrope + Fraunces with ₹, transitions, reduced-motion |
| 13 | Alignment | Desktop staff nav starts at x=16, content at x=176; no shared left edge | done (UI-3): everything sits in one content column beside the sidebar |
| 14 | Floor | Free tiles centred, seated tiles left-aligned; zone shows raw lowercase "floor" | done (UI-3): one left-aligned tile layout, legend, capitalised zones |
| 15 | Desktop | Floor map uses a fraction of the width | done (UI-3): sidebar + wide content column |
| 16 | A11y | No designed focus indicator; mock palette fails AA (accent 4.48, accent text 3.99, grey 3.15) | done (UI-1): global `:focus-visible` ring, AA palette |
| 17 | Auth | Sign-in and sign-up are bare forms at the top-left | done (UI-4): centred card, plain-English lines, full-width actions |
| 18 | Admin app | Stub; nothing to polish until it has screens | n/a |

## Remaining after UI-4
- Menu page still mixes daily work with options and CSV import; splitting them into tabs is the next improvement.
- Toasts are specified but not built; "Saved" is still an inline status.
- The admin app (platform admin) is a stub.
- One Playwright test (`a waiter adds items with no connection…`) failed once in a full parallel run and passed alone and on rerun; treat as a possible flake and fix it in its own PR if it recurs.

## Screen map and slices
| Slice | Screens | Status |
| --- | --- | --- |
| UI-1 Foundation | tokens, fonts, shared components, focus, shrink both `globals.css` | **done** (branch `ui/design-system`) |
| UI-2 Guest | QR landing/errors, menu, item sheet, cart, tab, call sheet | **done** |
| UI-3 Staff service | shell + nav, floor, table view, add items, requests, kitchen | **done** |
| UI-4 Owner admin | sign-in/sign-up/invite, outlet picker, setup, menu, tables & QR, staff, happy hours, assignments | **done** |
