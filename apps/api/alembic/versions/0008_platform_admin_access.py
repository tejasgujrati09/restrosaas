"""platform admin: two SELECT-only policies, platform_admin.active, append-only audit_log

A platform admin is an `app_user` with a `platform_admin` row (0003). It never gets a
tenant's data by default: every tenant table is still filtered by `app.restaurant_id`.
Two narrow exceptions, both SELECT only, both true only when the session's
`app.platform_admin_id` names an *active* platform_admin row:

* `restaurant_platform_read` on `restaurant`: list every restaurant with its status.
* `audit_log_platform_read` on `audit_log`: read platform and tenant audit entries.

Everything the admin *does* to a restaurant (suspend, later impersonate) opens the normal
tenant session for that restaurant, so writes go through the existing tenant policies and
need no new ones. `audit_log` also becomes append-only for the app role.

Reversal in intent: downgrade drops both policies and the column and restores the
UPDATE/DELETE grants on audit_log.
"""

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

_IS_PLATFORM_ADMIN = """EXISTS (
    SELECT 1 FROM platform_admin pa
    WHERE pa.active
      AND pa.id = nullif(current_setting('app.platform_admin_id', true), '')::uuid
)"""


def upgrade() -> None:
    op.execute("ALTER TABLE platform_admin ADD COLUMN active boolean NOT NULL DEFAULT true")
    for table, policy in (
        ("restaurant", "restaurant_platform_read"),
        ("audit_log", "audit_log_platform_read"),
    ):
        op.execute(f"CREATE POLICY {policy} ON {table} FOR SELECT USING ({_IS_PLATFORM_ADMIN})")
    op.execute("REVOKE UPDATE, DELETE ON audit_log FROM app")
    op.execute("CREATE INDEX audit_log_at_idx ON audit_log (at DESC)")


def downgrade() -> None:
    op.execute("DROP INDEX audit_log_at_idx")
    op.execute("GRANT UPDATE, DELETE ON audit_log TO app")
    op.execute("DROP POLICY audit_log_platform_read ON audit_log")
    op.execute("DROP POLICY restaurant_platform_read ON restaurant")
    op.execute("ALTER TABLE platform_admin DROP COLUMN active")
