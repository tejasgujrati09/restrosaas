"""staff_invite, idempotency_key, uniqueness and price-rule constraints

`staff_invite` carries a second, SELECT-only policy keyed on
`app.invite_token_hash`. An invitee is unauthenticated: the API hashes the token
from the link, sets that setting for one transaction, and can read exactly that
one invite row. It then switches to a normal tenant session (using the invite's
restaurant) for everything else. Same shape as `staff_role_self_read`.

`idempotency_key` is scoped per (restaurant, user, key) so one staff member can
never replay another's key and read their stored response.

Reversal in intent: downgrade drops the two tables and the added constraints.
"""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

_TENANT = "restaurant_id = nullif(current_setting('app.restaurant_id', true), '')::uuid"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE staff_invite (
            id uuid PRIMARY KEY,
            restaurant_id uuid NOT NULL REFERENCES restaurant (id),
            outlet_id uuid NOT NULL REFERENCES outlet (id),
            phone text NOT NULL,
            role text NOT NULL CHECK (role IN ('waiter', 'kitchen', 'bar', 'manager', 'owner')),
            station_id uuid REFERENCES station (id),
            token_hash text NOT NULL UNIQUE,
            invited_by uuid NOT NULL REFERENCES app_user (id),
            expires_at timestamptz NOT NULL,
            accepted_at timestamptz,
            revoked_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("ALTER TABLE staff_invite ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY staff_invite_tenant_isolation ON staff_invite "
        f"USING ({_TENANT}) WITH CHECK ({_TENANT})"
    )
    op.execute(
        """
        CREATE POLICY staff_invite_by_token ON staff_invite FOR SELECT
            USING (token_hash = nullif(current_setting('app.invite_token_hash', true), ''))
        """
    )

    op.execute(
        """
        CREATE TABLE idempotency_key (
            restaurant_id uuid NOT NULL REFERENCES restaurant (id),
            user_id uuid NOT NULL REFERENCES app_user (id),
            key uuid NOT NULL,
            method text NOT NULL,
            path text NOT NULL,
            request_hash text NOT NULL,
            status_code integer,
            response jsonb,
            created_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (restaurant_id, user_id, key)
        )
        """
    )
    op.execute("ALTER TABLE idempotency_key ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY idempotency_key_tenant_isolation ON idempotency_key "
        f"USING ({_TENANT}) WITH CHECK ({_TENANT})"
    )

    op.execute(
        "CREATE UNIQUE INDEX menu_category_name_uq ON menu_category (outlet_id, lower(name))"
    )
    op.execute("CREATE UNIQUE INDEX menu_item_name_uq ON menu_item (category_id, lower(name))")
    op.execute("CREATE UNIQUE INDEX tax_class_name_uq ON tax_class (outlet_id, name)")
    op.execute("CREATE UNIQUE INDEX station_name_uq ON station (outlet_id, name)")
    op.execute("CREATE UNIQUE INDEX modifier_group_name_uq ON modifier_group (outlet_id, name)")
    op.execute("CREATE UNIQUE INDEX modifier_name_uq ON modifier (group_id, name)")
    op.execute(
        """
        ALTER TABLE price_rule
            ADD CONSTRAINT price_rule_days_valid CHECK (
                cardinality(days_of_week) BETWEEN 1 AND 7
                AND days_of_week <@ ARRAY[0, 1, 2, 3, 4, 5, 6]::smallint[]
            ),
            ADD CONSTRAINT price_rule_percent_valid CHECK (
                rule_type <> 'percent_off' OR value <= 10000
            )
        """
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON staff_invite, idempotency_key TO app")


def downgrade() -> None:
    op.execute("ALTER TABLE price_rule DROP CONSTRAINT price_rule_percent_valid")
    op.execute("ALTER TABLE price_rule DROP CONSTRAINT price_rule_days_valid")
    for index in (
        "modifier_name_uq",
        "modifier_group_name_uq",
        "station_name_uq",
        "tax_class_name_uq",
        "menu_item_name_uq",
        "menu_category_name_uq",
    ):
        op.execute(f"DROP INDEX {index}")
    op.execute("DROP TABLE idempotency_key")
    op.execute("DROP TABLE staff_invite")
