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

All values are CSS custom properties in `packages/ui/src/tokens.css`. **Never write a hex, pixel size or shadow in an app stylesheet or component; use a token.** Hairlines are the one allowance: borders, outlines and dividers of 1 to 3 px may be written as literals. Sizes of boxes, marks, gaps, offsets, widths, font weights, z-indexes and durations are always tokens (`--dot`, `--avatar`, `--bottom-bar`, `--sidebar-w`, `--w-auth`, `--fw-bold`, `--z-bar` and so on). `tokens.css` and `components.css` are where sizes are defined and may hold them. `manifest.ts` files hold the page colour as a hex because a web manifest cannot read CSS variables; keep it equal to `--bg`. A missing token is a design change: add it here first.

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

### Type weight and capitalization (one standard, set once)
- **Headings are bold (700):** page title, card and section headings, and h3 subsections all take the `--f-h1`, `--f-h2` and `--f-h3` tokens; never a weight set on a page. Fraunces ships as a single static weight-600 file (see `packages/ui/fonts/README.md`), so display headings render from that face until a true 700 is added; the declared weight is still 700 so they follow the token if the font changes.
- **Table column headings and form labels are bold, small, and sentence case.** No CSS `text-transform`: not uppercase, not `capitalize` (which would Title Case every word).
- **Sentence case everywhere:** "Invite someone", "Their mobile number", "Phone orders". Only proper names and acronyms (QR, PDF, GSTIN, OTP, API, SMS, UPI) keep their capitals.
- **Stored values are shown through a label helper, never edited.** Enums and free text a person typed (a role, a zone, a plan, a request type) are formatted at display time with `roleLabel`, `sentenceCase` or `humanize` from `@restosaas/ui`. The stored value is what the API takes, returns and compares; do not compare or send display text.

## 3. Components (in `packages/ui`)

Plain CSS classes and small React components; **no new UI library** (CLAUDE.md §2). Icons are inline SVG. Real `<button>`, `<a>`, `<input>` only.

- **Button** — `primary` (accent fill), `secondary` (surface + strong border), `tertiary` (text only), `danger` (danger text, never a solid red except in the confirm step of a destructive dialog). Sizes 44/48/52. Loading shows a spinner and keeps its width; disabled uses `--sunken` and `--ink-3`, not opacity. **At most one primary per screen region.**
- **Field** — visible label above, hint or error below (linked with `aria-describedby`), never placeholder-as-label. Error text names the fix. Short values get short inputs. **A new-record form starts empty and shows an example as a placeholder** ("e.g. Happy hour, Lunch special", "e.g. 20"); never a typed-in default the person has to delete. When a blank should mean something, the hint says so ("Empty means none") and the code applies it on save. Only values that come from the server (editing an existing record) are prefilled.
- **Card** — only for a meaningful group. Lists inside a card are rows with dividers, not nested cards.
- **Badge / StatusPill** — text plus a tone (`ok`, `warn`, `danger`, `info`, `neutral`). Never colour alone.
- **Banner** — inline notice with tone; `role="alert"` only for errors that just happened, `role="status"` otherwise.
- **Skeleton** — for loading lists and cards, sized like the content. A bare "Loading…" line is not allowed on a data screen.
- **EmptyState** — what is empty, why, and the next action.
- **TabStrip** — views of one list, each with its own count (Orders: New, In progress, Ready, Completed, Cancelled). A `tablist` of real buttons; the selected tab is marked with `aria-selected`, a filled surface and an outline, and a count is text, never colour alone. Scrolls sideways inside itself on a phone. The panel it controls is a `role="tabpanel"` labelled by the tab.
- **Stepper** — a short list of things happening in order (setting up voice ordering). Each step has a mark (✓ ● ○ !) and hidden text for its state; the current step carries `aria-current="step"`. Use it for setup that takes seconds to minutes, not for progress bars.
- **Toast** (`toast.ok(message)`, `toast.error(message)`, `<ToastHost />` mounted once in each app's root layout) — the feedback for something the person just did: saved, sent, assigned, or failed. It floats above the page (bottom, above the phone tab bar), so showing or hiding it moves nothing. A confirmation dismisses itself after 4 s (`role="status"`); an error stays until dismissed (`role="alert"`, a 44 px Dismiss button); the same message twice is one toast; three at most. `useAction()` sends a failure to an error toast by itself. Never render an action's result as a paragraph in the page.
- **PageHeader** — title (H1), one line of context, actions on the right (desktop) or below (phone).
- **DataList** — a real `<table>` from 640 px; the same rows stacked as labelled pairs below. Never a horizontally scrolling page.
- **Sheet, Stepper** — existing; restyled by tokens. **A sheet never takes over the screen:** it is at most 85 % of the height (`dvh`), the title and close button are fixed at the top and only the content scrolls. **Drawer** (`<Sheet variant="drawer">`) is for a long record you read while looking at a list (an order): from 1024 px it fills the height at the right edge, `--w-drawer` (480 px) wide, with a clear backdrop so the list stays visible beside it; on a phone it is the same bottom sheet. Use a plain sheet for short forms and confirmations, a drawer for records.
- **Details sheet (platform admin)** — clicking a restaurant card opens its details: badges (status, plan, voice orders) and a notice if suspended (when, by whom, why), then sections of label and value rows (`.detail-list`): Business (registered name, GSTIN, joined with how long ago, ID), Plan (plan, when it ends with an Ended, Ends soon or Open-ended badge, and a date field to set or clear the last day), Outlets (name, address, state name, time zone, tables, liquor licence), Owner (name and a tap-to-call number), Team and menu (active staff by role, items and categories, tax classes) and Activity (rounds in total, 30 days, 7 days, open tabs, first and last round). Actions (Voice orders, Suspend or Reactivate) sit at the bottom. It shows counts and contacts only, never orders, guests or prices.
- **KpiCard, Bars, Heatmap** (analytics, `apps/staff/components/analytics-parts.tsx`) — a KPI card is label, number, "Based on N …", an optional change line (only when the API gives a valid comparison; direction is stated, never coloured good or bad) and a "How is this calculated?" disclosure. Bars are HTML columns using `--accent`, with a "See the numbers" table beneath so nothing lives only in a picture. The heatmap shades `--accent` over `--sunken` by share. Segmented choices (`.seg`) and section tabs (`.tabs`) use `aria-pressed` / `role="tab"`.
- **Menu row that adds in place** (guest) — an item with no option groups is not a button that opens something: it shows a **+** (44 px) on the right, and once added the same spot becomes a quantity control (minus, number, plus) so the count can be changed without leaving the menu. Only an item with option groups, which needs a choice, opens the item sheet; its row says "Choose options". Sold-out and ask-your-waiter items stay disabled rows. The guest never writes the kitchen note on the menu: each **cart line** has one link, "Add a note for the kitchen" (or "Edit note" beside the saved note), which opens one field that saves on Enter, on Save or when you tap away, so the cart is not re-priced on each key. The waiter's add-items screen still shows the note in the sheet (`ItemSheet showNote`).
- **Item sheet** (guest and waiter "add items") — the name in the sheet title, then the price (large; "was ₹300.00 · Happy hour" beside it when a price rule applies) and Veg or Non-veg, then the description, then option groups. The note for the kitchen is optional, so it is one link ("Add a note for the kitchen") that opens the field in place, not a permanent box. The action row sticks to the bottom of the sheet: a quantity stepper (minus, number, plus, in one row, `.qty-stepper`) and one full-width "Add to cart · ₹" button beside it. The quantity control and the setup step list used to share the class `.stepper`, which stacked the quantity buttons vertically; **a class name is defined once**, and a new component gets a new name.
- **Selectable table card** — the floor `tile` as a real `<button aria-pressed>`; selection is an accent outline plus a "Selected" pill (never colour alone). The selection bar is sticky, names the count, offers one waiter select, an Assign button and Clear selection, and lists what will be replaced. **Card size** comes from two tokens, `--tile-min` (184 px minimum width) and `--tile-h` (132 px minimum height), so cards and slots line up in a grid (`.tiles.roomy`; two per row on a phone); the floor map keeps its own denser 160 px grid. A card's actions sit in a footer row of equal-width, borderless buttons (`.tile-foot`, 44 px tall, a divider above and between) instead of stacked full buttons. **Add-table slot** (`.tile.placeholder`): a dashed "+ Add table" card; four when the venue is empty, then one always left at the end; clicking it turns that slot into an inline form (no modal).
- **Settings row and switch** — a setting is one row: the name in bold with one line under it saying what on and off mean (the line follows the switch as it moves, before saving), the control on the right, hairline dividers above and below. The switch is a real `<input type="checkbox" role="switch" class="switch">` drawn as a 48 × 28 track (`--switch-w`, `--switch-h`) with a knob; on is `--accent` fill with the knob moved right, and the whole row is the tap target (44 px). Fields that only apply when it is on sit below and are disabled, with a hint saying so; one Save at the end.
- **FileDrop** — a dashed `label` around a visually hidden `<input type="file" multiple>`, so it is keyboard and screen-reader reachable and also takes dropped files (`.filedrop`, tokens only; hover, drag and focus use `--accent` and `--accent-bg`). Chosen files show below as an ordered list with move up, move down and remove buttons (`.filelist`); progress uses a native `<progress>` with a text percentage.
- **Money** — renders `formatInr`; display only.

## 3a. Rhythm and grouping
Space is chosen by relationship, from three tokens, never ad hoc:
- **`--gap-block` (16 px)** between sibling blocks on a page: cards, tab rows, filters, banners, the selection bar. `.card`, `.tabstrip`, `.alerts` and `.filters` already carry it; a new block type must use it too.
- **`--section-gap` (24 px)** before a new section (a heading with its own content) and after the page header.
- **`--s-3` (12 px)** only inside a group, where two things belong together (a heading and what it labels, a back link and its title).
- **A legend, toolbar, filter or "select all" belongs to the thing it describes.** Put it on the heading row of that section (heading on the left, legend or action on the right), not floating between two blocks where it could belong to either. If a person could ask "is this part of the block above or below?", the grouping is wrong.
- Sections nest one level at a time: the page title is h1, a section such as "Tables" is h2, and a part inside it (a zone) is h3.
- Check a new screen by measuring the gaps between sibling blocks: every gap is 16 or 24, apart from deliberate 12 px groups.

### Anchors under sticky bars
A sticky bar hides whatever an in-page link scrolls to. Any element that is a jump target (`id` on a section) gets `scroll-margin-top` equal to the sticky bar's height plus a little air, built from tokens (the guest menu: `--hit` chips plus their padding). Check by tapping the last-but-one link on a long page: the heading must be visible under the bar.

## 3b. Feedback and layout stability
**Nothing on screen moves because of something the person did not ask to move.** A control stays where it is while its value changes, feedback appears, or data loads.
1. **Feedback goes in a toast** (see Components), or next to the control that caused it and below it, at the end of its block. Never above the controls, and never at the top of the page: a banner that appears there pushes everything down and the button the person is about to press moves under their finger. Sign-in style forms are the exception: their error belongs next to the field (`useAction({ inline: true })`).
2. **Text that changes with a choice keeps the height of its longest version.** Give the field `hintLines={n}` (the longest variant in lines on a desktop; one more line is added on a phone) or keep the sentence the same and let only a control change. Example: the strategy hint under "How to pick" reserves two lines, so Save does not move when the strategy changes.
3. **A description next to a switch or option is one fixed sentence.** It says what the setting does, not what the current value means. Put the current state in the control (the switch position and its label).
4. **Loading, empty and loaded states occupy the same space** where they can: a skeleton is sized like the content it stands in for.
5. **Optional rows are always in the layout or always out of it for the life of the screen.** If a row depends on a choice (a waiter for liquor rows), show it disabled with a hint rather than removing it.
6. **Check it:** in the browser, change every input on the screen and confirm the buttons below keep their y position (Playwright: read `boundingBox().y` before and after).

## 4. Shell and navigation
- **Guest:** header (venue name in Fraunces, a `Table` pill, one line for the current happy hour) + bottom bar with a contextual primary action (view round, request bill) above the tab links (Menu, My tab, Call waiter).
- **Restaurant picker** (after sign-in, for people who work at more than one place): a grid of cards, one per outlet, each with an initial avatar, restaurant name, outlet and state, a role badge and a readiness badge. One outlet skips the picker.
- **Staff, phone:** slim top bar (venue, connection dot with text, account menu with Sign out) + bottom tab bar of at most four role-based destinations; the rest under **More**.
- **Staff, desktop (≥ 1024):** left sidebar grouped **Service** (Floor, Requests, Kitchen, and for owners and managers Orders and Phone orders), **Manage** (Menu, Offers, Tables & QR, Assign tables, Staff), **Settings** (Setup); page header in the content column. The active item has `aria-current="page"` and a filled row. Sign out is in the account menu, never styled like a page action.
- **Suspended restaurant:** the shell shows a warn `Notice` above the page ("This restaurant's account is suspended…") and wraps the page in `<fieldset class="readonly" disabled>`, which turns off every button and field while links, and so reading, still work. The picker card shows a danger `Suspended` badge. Never hide a suspended restaurant.
- Role filtering of links stays (`NAV` in `apps/staff/lib/nav.ts`); hiding a link is convenience, the API is the check.

## 5. Copy
Short, plain English, sentence case, no jargon on guest screens ("Taxes included", not "Included in prices: CGST/SGST/VAT"). Buttons say what they do ("Place order · ₹624", not "Submit"). Errors say what happened and what to do next.

## 6. Checklist for any new screen or change
Copy into the PR description and tick each.
- [ ] Uses tokens and shared components; no new hex, px size or one-off button style
- [ ] One clear primary action; secondary actions visibly quieter; destructive actions separated
- [ ] Loading (skeleton), empty (with next step), error (with recovery, `ErrorBanner onRetry`) and loaded states all built
- [ ] Rhythm (§3a): gaps between blocks are 16 or 24; legends and toolbars sit on the heading row of what they describe
- [ ] Stability (§3b): action feedback is a toast; changing any input moves nothing below it; changing hint text reserves its height
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
| 18 | Admin app | Stub; nothing to polish until it has screens | done: sign-in, restaurants card grid with suspend/reactivate, audit log, on the shared tokens |
| 19 | Tokens | ~50 literal sizes, 25 literal `font-weight: 700`, a `1.2rem`, 2 to 3 px radii, bare z-indexes and an unknown `--t-display` in the three app stylesheets | done (audit 2026-09-26): new tokens for marks, layout widths, bottom bar, weights, radii and layers; app CSS uses them; hairline rule written above |
| 20 | Menu page | At 1280 px the page was 124 px wider than the window (the file input of the new PDF import spanned the page) | done: the input fills its drop zone invisibly and cannot widen the page; focus ring on the zone |
| 21 | Menu page | Category tables each had their own column widths, so columns did not line up card to card | done: `.menu-table` uses one fixed layout from 640 px |
| 22 | Analytics | Heading levels skipped (h1 to h3); the weekday heatmap scrolled but could not be reached by keyboard; the section tabs wrapped to a second row on a phone | done: hidden "Key figures" h2; heatmap is a focusable labelled region; tabs scroll sideways inside themselves |
| 23 | States | Load failures showed a message with no way to recover on 12 screens | done: `ErrorBanner` takes `onRetry` and shows "Try again"; every load-failure site uses it |
| 24 | States | Staff team list had no loading or empty state; offers (then "happy hours") had no loading state | done: skeleton and empty state added |
| 25 | Copy | "Voice Orders" in Title Case (admin) | done: "Voice orders" |
| 26 | Rhythm | Sibling blocks were 12, 16, 20 or 24 px apart with no rule; on Assign tables the legend sat closer to the panel above than to the tables it explains | done (2026-09-26): `--gap-block` and `--section-gap` applied to cards, tab rows, filters, alerts, page header and zone headings; the legend moved onto the "Tables" heading row; rules in §3a |
| 27 | Stability | 29 action errors rendered in the page flow (the page jumped when one appeared); success lines rendered inline; on Assign tables the Save button moved as the strategy hint changed length | done: toast built and mounted in all three apps; `useAction` toasts failures; in-flow action banners removed; `hintLines` reserves hint height; the switch description is one fixed sentence; rules in §3b |
| 28 | Guest menu | Tapping a category chip scrolled its section under the sticky chip bar, so the heading was hidden and only items showed | done (2026-09-26): `scroll-margin-top` on category sections; rule in "Anchors under sticky bars" |
| 29 | Item sheet | Quantity buttons stacked vertically (two CSS rules shared the class `.stepper`); the note field was always open; price and veg mark were missing | done: `.qty-stepper` row beside a sticky "Add to cart" button, optional note link, price and veg line |
| 30 | Guest ordering | Every item, even one with no choices, needed: tap the row, then "Add to cart" in a popup, then close; notes were asked for before anyone had decided what to order | done (2026-09-26): items without options add in place with a + that becomes a quantity control; the kitchen note moved to the cart line; the sheet is only for items with choices |
| 31 | Orders | The order popup was a 90 %-height sheet that scrolled its own title away and covered the list | done (2026-09-26): shared `Sheet` capped at 85 % with a fixed header; orders open in a right-hand drawer from 1024 px so the list stays visible |

## Remaining after the 2026-09-26 audit
- Checked with axe (WCAG 2 A and AA plus best practice), a touch-target measurement and an overflow check on every staff, guest and admin route at 390 and 1280 px. Contrast passes everywhere.
- The "New QR" confirmation still uses the browser's `window.confirm`; a designed confirm step (danger button in a sheet) is not built yet.
- The `role="switch"` checkbox is 24 px inside a 44 px label; the label is the target.
- Menu page still mixes daily work with options and CSV import; splitting them into tabs is the next improvement.
- The Setup page's "Saved" still sits inline in its sticky save bar (a fixed slot, so nothing moves); the offline "Saved on this device" notice on the add-items page is a persistent status, not a toast.
- The admin app has restaurants and audit only; plans, onboarding and impersonation come in slice A2 (see DECISIONS.md, 2026-09-20).
- One Playwright test (`a waiter adds items with no connection…`) failed once in a full parallel run and passed alone and on rerun; treat as a possible flake and fix it in its own PR if it recurs.

## Screen map and slices
| Slice | Screens | Status |
| --- | --- | --- |
| UI-1 Foundation | tokens, fonts, shared components, focus, shrink both `globals.css` | **done** (branch `ui/design-system`) |
| UI-2 Guest | QR landing/errors, menu, item sheet, cart, tab, call sheet | **done** |
| UI-3 Staff service | shell + nav, floor, table view, add items, requests, kitchen | **done** |
| UI-4 Owner admin | sign-in/sign-up/invite, outlet picker, setup, menu, tables & QR, staff, offers, assignments | **done** |
