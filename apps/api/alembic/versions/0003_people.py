"""app_user, staff_role, platform_admin, audit_log

`app_user` and `platform_admin` are global (no `restaurant_id`, so no RLS by the
repo's definition of a tenant table). `staff_role` and `audit_log` are tenant
tables.

`staff_role` carries a second, SELECT-only policy keyed on `app.user_id`. At
login the API knows the user but not yet which restaurants they belong to; after
OTP verification it sets `app.user_id` for one transaction so the user can read
exactly their own roles, and nothing else. Every later request runs under
`app.restaurant_id` taken from the signed JWT.

`audit_log.restaurant_id` is nullable (platform-level entries). Tenant sessions
never match a NULL restaurant_id, so they cannot see those rows.

Reversal in intent: downgrade drops the four tables.
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE app_user (
            id uuid PRIMARY KEY,
            phone text NOT NULL UNIQUE,
            name text,
            last_login_at timestamptz
        )
        """
    )

    op.execute(
        """
        CREATE TABLE staff_role (
            id uuid PRIMARY KEY,
            restaurant_id uuid NOT NULL REFERENCES restaurant (id),
            user_id uuid NOT NULL REFERENCES app_user (id),
            outlet_id uuid NOT NULL REFERENCES outlet (id),
            role text NOT NULL CHECK (role IN ('waiter', 'kitchen', 'bar', 'manager', 'owner')),
            station_id uuid REFERENCES station (id),
            active boolean NOT NULL DEFAULT true,
            UNIQUE (user_id, outlet_id, role)
        )
        """
    )
    op.execute("ALTER TABLE staff_role ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY staff_role_tenant_isolation ON staff_role
            USING (restaurant_id = nullif(current_setting('app.restaurant_id', true), '')::uuid)
            WITH CHECK (
                restaurant_id = nullif(current_setting('app.restaurant_id', true), '')::uuid
            )
        """
    )
    op.execute(
        """
        CREATE POLICY staff_role_self_read ON staff_role FOR SELECT
            USING (user_id = nullif(current_setting('app.user_id', true), '')::uuid)
        """
    )

    op.execute(
        """
        CREATE TABLE platform_admin (
            id uuid PRIMARY KEY,
            user_id uuid NOT NULL UNIQUE REFERENCES app_user (id),
            permissions jsonb NOT NULL DEFAULT '{}'::jsonb
        )
        """
    )

    op.execute(
        """
        CREATE TABLE audit_log (
            id uuid PRIMARY KEY,
            actor_user_id uuid REFERENCES app_user (id),
            restaurant_id uuid REFERENCES restaurant (id),
            action text NOT NULL,
            target_type text NOT NULL,
            target_id uuid,
            before jsonb,
            after jsonb,
            at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY audit_log_tenant_isolation ON audit_log
            USING (restaurant_id = nullif(current_setting('app.restaurant_id', true), '')::uuid)
            WITH CHECK (
                restaurant_id = nullif(current_setting('app.restaurant_id', true), '')::uuid
            )
        """
    )

    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON "
        "app_user, staff_role, platform_admin, audit_log TO app"
    )


def downgrade() -> None:
    op.execute("DROP TABLE audit_log")
    op.execute("DROP TABLE platform_admin")
    op.execute("DROP TABLE staff_role")
    op.execute("DROP TABLE app_user")
