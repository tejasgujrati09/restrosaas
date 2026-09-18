# RestoSaaS

Multi-tenant QR ordering and billing for Indian restaurants, bars and clubs.
Read `CLAUDE.md` (rules), `docs/SPEC.md` (product) and `docs/DECISIONS.md` (choices the spec left open) first.

Python owns every business rule (`apps/api`); TypeScript only renders (`apps/guest`, `apps/staff`, `apps/admin`).

## Setup

Needs Docker, [uv](https://docs.astral.sh/uv/), Node 22+ and pnpm.

```bash
brew install pango                                # macOS only: PDFs (QR sheets, menu) need it
cp .env.example apps/api/.env                     # dev-only credentials
docker compose up -d --wait postgres redis        # Postgres 16 + Redis
(cd apps/api && uv sync && uv run alembic upgrade head)
pnpm install
(cd apps/api && DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib uv run uvicorn app.main:app --reload)   # API :8000, docs at /docs
pnpm --filter staff dev                           # owner and staff app on :3001  (guest :3000, admin :3002)
```

Then open http://localhost:3001/signup. Sign-in and sign-up use a phone number and a one-time code;
in development the code is printed in the API console (the `[dev] OTP for ...` line).

Guests scan a table's QR (`http://localhost:3000/t/<token>`, printed from **Tables & QR**), order, and see their tab
update live over a WebSocket. Redis must be running (it fans events out between API replicas).

Owner path to printed QR codes: sign up, then **Setup** (GSTIN, tax classes), **Menu** (add items or import a CSV),
**Tables & QR** (add tables, print the QR sheet), **Staff** (invite by WhatsApp link).

## Everyday commands

| Command | What it does |
| --- | --- |
| `make dev` | Postgres, Redis and the API in Docker with autoreload |
| `make test-db` | Start Postgres, migrate, run the API tests against the real database |
| `make check` | Every CI gate, in CI order (see `CLAUDE.md` §10) |
| `pnpm --filter e2e test` | Browser tests: boots the API and all three apps and walks the owner journey (set `E2E_*_PORT` if 3000-3002 or 8000 are taken) |
| `pnpm --filter api-client generate` | Regenerate the TypeScript client after the API changes (export first: `cd apps/api && uv run python -m app.export_openapi ../../openapi.json`) |

## Two database roles

Migrations run as an owner role (`MIGRATION_DATABASE_URL`, locally `postgres`). The API runs as `app`
(`DATABASE_URL`), which is not a superuser and cannot bypass row-level security. Never point the API at the
owner role: tenant isolation would silently stop working. See `docs/DECISIONS.md`.

## Layout

```
apps/api            FastAPI, SQLAlchemy 2 (async), Alembic (raw SQL revisions)
  app/core          money, tax, state machines, permissions: pure, 100% branch coverage
apps/guest|staff|admin   Next.js PWAs
packages/ui         shared components and the display-only INR formatter
packages/api-client generated from openapi.json (committed; CI fails if stale)
e2e                 Playwright (smoke, owner setup, guest ordering; the full golden flows land in Milestone 5)
```
