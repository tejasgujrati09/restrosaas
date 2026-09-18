# RestoSaaS

Multi-tenant QR ordering and billing for Indian restaurants, bars and clubs.
Read `CLAUDE.md` (rules), `docs/SPEC.md` (product) and `docs/DECISIONS.md` (choices the spec left open) first.

Python owns every business rule (`apps/api`); TypeScript only renders (`apps/guest`, `apps/staff`, `apps/admin`).

## Setup

Needs Docker, [uv](https://docs.astral.sh/uv/), Node 22+ and pnpm.

```bash
cp .env.example apps/api/.env                     # dev-only credentials
docker compose up -d --wait postgres redis        # Postgres 16 + Redis
(cd apps/api && uv sync && uv run alembic upgrade head)
pnpm install
(cd apps/api && uv run uvicorn app.main:app --reload)   # API on :8000, docs at /docs
pnpm --filter guest dev                           # :3000  (staff :3001, admin :3002)
```

Staff sign in with phone + OTP. In development the OTP is printed to the API console.

## Everyday commands

| Command | What it does |
| --- | --- |
| `make dev` | Postgres, Redis and the API in Docker with autoreload |
| `make test-db` | Start Postgres, migrate, run the API tests against the real database |
| `make check` | Every CI gate, in CI order (see `CLAUDE.md` §10) |
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
e2e                 Playwright (smoke now; golden flows from Milestone 5)
```
