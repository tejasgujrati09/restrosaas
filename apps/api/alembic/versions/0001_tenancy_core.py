"""restaurant and outlet; create the non-superuser `app` runtime role

Two roles, on purpose. The role that runs migrations owns the tables (locally
the bootstrap superuser). The API connects as `app`: NOSUPERUSER, NOBYPASSRLS,
not the table owner, so every RLS policy below is enforced against it. A
superuser role can never be demoted, so `app` cannot double as the bootstrap
user (docs/DECISIONS.md "Separate migration-owner and runtime DB roles").

If a role named `app` already exists it is left untouched; scripts/check_rls.py
then reports honestly if it can bypass RLS.

Reversal in intent: downgrade drops the tables. The `app` role is kept.
"""

import os

import sqlalchemy as sa

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    role_exists = op.get_bind().execute(sa.text("SELECT 1 FROM pg_roles WHERE rolname = 'app'"))
    if role_exists.scalar() is None:
        password = os.environ.get("APP_DB_PASSWORD", "app").replace("'", "''")
        op.execute(
            f"CREATE ROLE app LOGIN PASSWORD '{password}' "
            "NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE"
        )
    op.execute("GRANT USAGE ON SCHEMA public TO app")

    op.execute(
        """
        CREATE TABLE restaurant (
            id uuid PRIMARY KEY,
            legal_name text NOT NULL,
            brand_name text NOT NULL,
            gstin text,
            subscription_plan text NOT NULL DEFAULT 'trial',
            status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'suspended')),
            created_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    # `restaurant` is the tenant itself: a session may only see its own row.
    op.execute("ALTER TABLE restaurant ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY restaurant_tenant_isolation ON restaurant
            USING (id = nullif(current_setting('app.restaurant_id', true), '')::uuid)
            WITH CHECK (id = nullif(current_setting('app.restaurant_id', true), '')::uuid)
        """
    )

    op.execute(
        """
        CREATE TABLE outlet (
            id uuid PRIMARY KEY,
            restaurant_id uuid NOT NULL REFERENCES restaurant (id),
            name text NOT NULL,
            address text,
            timezone text NOT NULL DEFAULT 'Asia/Kolkata',
            state_code text NOT NULL,
            liquor_licensed boolean NOT NULL DEFAULT false,
            liquor_vat_rate_bp integer NOT NULL DEFAULT 0 CHECK (liquor_vat_rate_bp >= 0),
            service_charge_bp integer NOT NULL DEFAULT 0 CHECK (service_charge_bp >= 0),
            prices_include_tax boolean NOT NULL DEFAULT true,
            ack_threshold_paise integer NOT NULL DEFAULT 50000 CHECK (ack_threshold_paise >= 0),
            waiter_confirm_mode boolean NOT NULL DEFAULT false,
            liquor_approval_required boolean NOT NULL DEFAULT false,
            invoice_prefix text NOT NULL CHECK (char_length(invoice_prefix) BETWEEN 1 AND 10),
            next_invoice_no integer NOT NULL DEFAULT 1 CHECK (next_invoice_no >= 1),
            created_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("ALTER TABLE outlet ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY outlet_tenant_isolation ON outlet
            USING (restaurant_id = nullif(current_setting('app.restaurant_id', true), '')::uuid)
            WITH CHECK (
                restaurant_id = nullif(current_setting('app.restaurant_id', true), '')::uuid
            )
        """
    )

    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON restaurant, outlet TO app")


def downgrade() -> None:
    op.execute("DROP TABLE outlet")
    op.execute("DROP TABLE restaurant")
