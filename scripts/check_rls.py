"""CI gate: every tenant-owned table must have RLS enabled, at least one policy
referencing app.restaurant_id, and the application role must not bypass RLS.

Run after `alembic upgrade head` with DATABASE_URL set. Exits non-zero on any finding.
Tables that are legitimately global (no restaurant_id column) are ignored.
"""
from __future__ import annotations

import asyncio
import os
import sys

import asyncpg

APP_ROLE = os.environ.get("APP_DB_ROLE", "app")
EXEMPT = {"alembic_version"}


async def main() -> int:
    url = os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(url)
    try:
        tenant_tables = [
            r["table_name"]
            for r in await conn.fetch(
                """
                select table_name from information_schema.columns
                where table_schema = 'public' and column_name = 'restaurant_id'
                """
            )
            if r["table_name"] not in EXEMPT
        ]
        findings: list[str] = []
        for t in tenant_tables:
            rls = await conn.fetchval(
                "select relrowsecurity from pg_class where relname = $1 and relnamespace = 'public'::regnamespace",
                t,
            )
            if not rls:
                findings.append(f"{t}: row level security is not enabled")
            policies = await conn.fetch(
                "select qual, with_check from pg_policies where schemaname = 'public' and tablename = $1", t
            )
            if not any("app.restaurant_id" in (p["qual"] or "") or "app.restaurant_id" in (p["with_check"] or "") for p in policies):
                findings.append(f"{t}: no policy references current_setting('app.restaurant_id')")
        bypass = await conn.fetchval("select rolbypassrls from pg_roles where rolname = $1", APP_ROLE)
        if bypass is None:
            findings.append(f"role {APP_ROLE!r} does not exist")
        elif bypass:
            findings.append(f"role {APP_ROLE!r} has BYPASSRLS")
        # Append-only tables: app role must not hold UPDATE/DELETE.
        for t in ("tab_event", "bill", "bill_line"):
            if t in tenant_tables:
                grants = await conn.fetch(
                    "select privilege_type from information_schema.role_table_grants where grantee = $1 and table_name = $2",
                    APP_ROLE, t,
                )
                bad = {g["privilege_type"] for g in grants} & {"UPDATE", "DELETE"}
                if bad:
                    findings.append(f"{t}: app role holds {sorted(bad)}; table must be append-only")
    finally:
        await conn.close()

    if findings:
        print("RLS check failed:", file=sys.stderr)
        for f in findings:
            print(f"  - {f}", file=sys.stderr)
        return 1
    print(f"RLS check passed for {len(tenant_tables)} tenant tables")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
