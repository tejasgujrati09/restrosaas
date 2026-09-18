from __future__ import annotations

from sqlalchemy import text

from app.db.base import Base
from app.db.session import anonymous_session
from app.domains.menu import models as _menu  # noqa: F401
from app.domains.staff import models as _staff  # noqa: F401
from app.domains.tenant import models as _tenant  # noqa: F401


async def test_orm_models_match_migrated_tables() -> None:
    """Migrations are hand-written SQL, so nothing else stops the ORM models
    drifting from the real schema."""
    async with anonymous_session() as session:
        rows = await session.execute(
            text(
                "SELECT table_name, column_name FROM information_schema.columns "
                "WHERE table_schema = 'public'"
            )
        )
    db_columns: dict[str, set[str]] = {}
    for table_name, column_name in rows:
        db_columns.setdefault(table_name, set()).add(column_name)

    for table in Base.metadata.sorted_tables:
        assert table.name in db_columns, f"{table.name} has a model but no migration"
        assert {c.name for c in table.columns} == db_columns[table.name], table.name
