"""menu_import: state of one "import a menu from a PDF or photos" job

Builds the `MenuImport` table reserved in docs/SPEC.md §7. A row holds the uploaded files (only
their storage keys), per-page extraction progress and results, the owner's editable draft rows and
the usage figures. Nothing here touches the live menu: confirming a job runs the existing CSV
import (`menu/import/apply`) on the draft rows, and only then does the row become `applied`.

`status`: queued -> processing -> ready | failed; ready -> applied. A failed job can be retried
(back to queued) and keeps its files until it is applied or expires.

The app role gets SELECT, INSERT and UPDATE only. RLS isolates tenants exactly as on every other
tenant table.

Reversal in intent: downgrade drops the table. Uploaded objects live in object storage and are
deleted by the application, not by this migration. Only an empty or development database should
ever be downgraded.
"""

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

_TENANT = "restaurant_id = nullif(current_setting('app.restaurant_id', true), '')::uuid"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE menu_import (
            id uuid PRIMARY KEY,
            restaurant_id uuid NOT NULL REFERENCES restaurant (id),
            outlet_id uuid NOT NULL REFERENCES outlet (id),
            created_by uuid NOT NULL REFERENCES app_user (id),
            status text NOT NULL DEFAULT 'queued'
                CHECK (status IN ('queued', 'processing', 'ready', 'failed', 'applied')),
            stage text,
            error text,
            files jsonb NOT NULL DEFAULT '[]',
            pages jsonb NOT NULL DEFAULT '[]',
            rows jsonb NOT NULL DEFAULT '[]',
            defaults jsonb NOT NULL DEFAULT '{}',
            usage jsonb NOT NULL DEFAULT '{}',
            created_at timestamptz NOT NULL,
            updated_at timestamptz NOT NULL,
            applied_at timestamptz
        )
        """
    )
    op.execute("CREATE INDEX menu_import_outlet ON menu_import (outlet_id, created_at DESC)")
    op.execute("ALTER TABLE menu_import ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY menu_import_tenant_isolation ON menu_import "
        f"USING ({_TENANT}) WITH CHECK ({_TENANT})"
    )
    op.execute("GRANT SELECT, INSERT, UPDATE ON menu_import TO app")


def downgrade() -> None:
    op.execute("DROP TABLE menu_import")
