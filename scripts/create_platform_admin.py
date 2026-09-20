"""Create (or re-activate) a platform admin. The only way to make one: there is no signup
and no API route for it, on purpose.

Run it with the API's environment, from anywhere:

    uv run --project apps/api python scripts/create_platform_admin.py +919876543210 --name "Asha"

Uses the table-owner database URL (MIGRATION_DATABASE_URL, else DATABASE_URL), because the
runtime role is not allowed to write `platform_admin` rows from the API. Add
`--deactivate` to lock an admin out at once.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
import uuid
from pathlib import Path

import asyncpg

# Load the API's settings (and its .env) whatever the caller's working directory is.
API_DIR = Path(__file__).resolve().parents[1] / "apps" / "api"
os.chdir(API_DIR)
sys.path.insert(0, str(API_DIR))

from app.config import settings  # noqa: E402

PHONE = re.compile(r"^\+[1-9][0-9]{7,14}$")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("phone", help="E.164, e.g. +919876543210")
    parser.add_argument("--name", default=None)
    parser.add_argument("--deactivate", action="store_true")
    args = parser.parse_args()
    if not PHONE.match(args.phone):
        print("Phone must be E.164, like +919876543210.", file=sys.stderr)
        return 2

    url = (settings.migration_database_url or settings.database_url).replace(
        "postgresql+asyncpg://", "postgresql://"
    )
    conn = await asyncpg.connect(url)
    try:
        async with conn.transaction():
            user_id = await conn.fetchval("SELECT id FROM app_user WHERE phone = $1", args.phone)
            if user_id is None:
                user_id = uuid.uuid4()
                await conn.execute(
                    "INSERT INTO app_user (id, phone, name) VALUES ($1, $2, $3)",
                    user_id, args.phone, args.name,
                )
            elif args.name:
                await conn.execute("UPDATE app_user SET name = $2 WHERE id = $1", user_id, args.name)
            await conn.execute(
                """
                INSERT INTO platform_admin (id, user_id, active) VALUES ($1, $2, $3)
                ON CONFLICT (user_id) DO UPDATE SET active = EXCLUDED.active
                """,
                uuid.uuid4(), user_id, not args.deactivate,
            )
    finally:
        await conn.close()
    print(f"Platform admin {args.phone}: {'deactivated' if args.deactivate else 'active'}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
