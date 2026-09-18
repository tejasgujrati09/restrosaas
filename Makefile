.PHONY: up down status dev test-db check api-lint api-test migrations openapi-client web-lint guest-budget golden-flows secrets

# Runtime role (non-superuser, subject to RLS) and owner role (migrations, test seeding).
RUNTIME_DB := postgresql+asyncpg://app:app@localhost:5432/app_dev
OWNER_DB   := postgresql+asyncpg://postgres:postgres@localhost:5432/app_dev
# DYLD_FALLBACK_LIBRARY_PATH lets WeasyPrint find Homebrew's Pango on macOS; harmless elsewhere.
API_ENV    := DATABASE_URL=$(RUNTIME_DB) MIGRATION_DATABASE_URL=$(OWNER_DB) REDIS_URL=redis://localhost:6380/0 DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib

# The whole local stack on the host (Postgres, Redis, migrations, API, guest/staff/admin apps, demo data).
up:
	scripts/dev.sh up

down:
	scripts/dev.sh down

status:
	scripts/dev.sh status

# Boots Postgres + Redis + the API with autoreload.
dev:
	docker compose up

# Starts Postgres, migrates it, and runs the API tests against it (real database, never mocked).
test-db:
	docker compose up -d --wait postgres redis
	cd apps/api && $(API_ENV) uv run alembic upgrade head
	cd apps/api && $(API_ENV) uv run pytest

# Runs every CI gate locally, in the same order as .github/workflows/ci.yml.
check: api-lint api-test migrations openapi-client web-lint guest-budget golden-flows secrets

api-lint:
	cd apps/api && uv run ruff check .
	cd apps/api && uv run ruff format --check .
	cd apps/api && uv run mypy --strict app

api-test:
	docker compose up -d --wait postgres redis
	cd apps/api && $(API_ENV) uv run alembic upgrade head
	cd apps/api && $(API_ENV) uv run pytest --cov=app --cov-branch --cov-report=term
	cd apps/api && uv run coverage report --include='app/core/*' --fail-under=100
	cd apps/api && uv run coverage report --fail-under=85

migrations:
	docker compose up -d --wait postgres
	cd apps/api && $(API_ENV) uv run alembic upgrade head
	cd apps/api && $(API_ENV) uv run alembic downgrade -1
	cd apps/api && $(API_ENV) uv run alembic upgrade head
	cd apps/api && $(API_ENV) uv run python ../../scripts/check_rls.py

openapi-client:
	cd apps/api && uv run python -m app.export_openapi ../../openapi.json
	pnpm --filter api-client generate
	git diff --exit-code -- openapi.json packages/api-client

web-lint:
	pnpm install --frozen-lockfile
	pnpm lint
	pnpm typecheck
	pnpm test

guest-budget:
	pnpm --filter guest build
	node scripts/check_bundle_budget.mjs apps/guest/.next 170
	pnpm --filter guest lighthouse:ci

golden-flows:
	docker compose -f docker-compose.ci.yml up -d --build --wait
	pnpm --filter e2e exec playwright install --with-deps chromium
	pnpm --filter e2e test; status=$$?; docker compose -f docker-compose.ci.yml down -v; exit $$status

secrets:
	gitleaks detect -v
