"""voice ordering: customer, customer_address, voice_agent, and order links

A restaurant owner can switch on a phone ordering agent (docs/DECISIONS.md "Voice ordering
agent"). `customer` and `customer_address` are per-restaurant and keyed by phone.
`voice_agent` links an outlet to its Gupshup agent and number and holds the hash of the
per-agent key the agent's tools authenticate with.

`tab.opened_by` and `tab_order.source` gain 'voice'. `tab_order` links to the customer and
the address used, and keeps a text snapshot of the address (a later edit or delete of the
saved address never changes an existing order). `external_call_id` is the Gupshup call id,
indexed but deliberately not unique: one call may place two orders.

Reversal in intent: downgrade drops the added columns, restores the two CHECK lists and
drops the three tables. It refuses (the restored CHECKs fail) if any tab or order still uses
'voice'; those rows, and what references them, must be removed first. Only an empty or
development database should ever be downgraded.
"""

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

_TENANT = "restaurant_id = nullif(current_setting('app.restaurant_id', true), '')::uuid"


def _tenant_policy(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {table}_tenant_isolation ON {table} "
        f"USING ({_TENANT}) WITH CHECK ({_TENANT})"
    )


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE customer (
            id uuid PRIMARY KEY,
            restaurant_id uuid NOT NULL REFERENCES restaurant (id),
            phone text NOT NULL,
            name text,
            created_at timestamptz NOT NULL,
            UNIQUE (restaurant_id, phone),
            UNIQUE (restaurant_id, id)
        )
        """
    )
    _tenant_policy("customer")

    op.execute(
        """
        CREATE TABLE customer_address (
            id uuid PRIMARY KEY,
            restaurant_id uuid NOT NULL REFERENCES restaurant (id),
            customer_id uuid NOT NULL,
            address_text text NOT NULL CHECK (length(btrim(address_text)) > 0),
            is_preferred boolean NOT NULL DEFAULT false,
            created_at timestamptz NOT NULL,
            UNIQUE (restaurant_id, id),
            FOREIGN KEY (restaurant_id, customer_id)
                REFERENCES customer (restaurant_id, id) ON DELETE CASCADE
        )
        """
    )
    _tenant_policy("customer_address")
    op.execute("CREATE INDEX customer_address_customer ON customer_address (customer_id)")
    op.execute(
        "CREATE UNIQUE INDEX customer_address_one_preferred "
        "ON customer_address (customer_id) WHERE is_preferred"
    )

    op.execute(
        """
        CREATE TABLE voice_agent (
            id uuid PRIMARY KEY,
            restaurant_id uuid NOT NULL REFERENCES restaurant (id),
            outlet_id uuid NOT NULL UNIQUE REFERENCES outlet (id),
            status text NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'active', 'disabled', 'failed')),
            gupshup_agent_id text,
            sr_plan_id integer,
            phone_number text,
            key_hash text NOT NULL,
            last_error text,
            enabled_by uuid REFERENCES app_user (id),
            created_at timestamptz NOT NULL,
            updated_at timestamptz NOT NULL
        )
        """
    )
    _tenant_policy("voice_agent")

    op.execute("ALTER TABLE tab DROP CONSTRAINT tab_opened_by_check")
    op.execute(
        "ALTER TABLE tab ADD CONSTRAINT tab_opened_by_check "
        "CHECK (opened_by IN ('customer', 'waiter', 'voice'))"
    )
    op.execute("ALTER TABLE tab_order DROP CONSTRAINT tab_order_source_check")
    op.execute(
        "ALTER TABLE tab_order ADD CONSTRAINT tab_order_source_check "
        "CHECK (source IN ('customer', 'waiter', 'aggregator', 'voice'))"
    )
    op.execute(
        """
        ALTER TABLE tab_order
            ADD COLUMN customer_id uuid,
            ADD COLUMN address_id uuid,
            ADD COLUMN delivery_address_snapshot text,
            ADD COLUMN external_call_id text,
            ADD CONSTRAINT tab_order_customer_fk FOREIGN KEY (restaurant_id, customer_id)
                REFERENCES customer (restaurant_id, id),
            ADD CONSTRAINT tab_order_address_fk FOREIGN KEY (restaurant_id, address_id)
                REFERENCES customer_address (restaurant_id, id) ON DELETE SET NULL (address_id),
            ADD CONSTRAINT tab_order_address_needs_customer
                CHECK (address_id IS NULL OR customer_id IS NOT NULL)
        """
    )
    op.execute("CREATE INDEX tab_order_customer ON tab_order (customer_id)")
    op.execute(
        "CREATE INDEX tab_order_external_call ON tab_order (restaurant_id, external_call_id) "
        "WHERE external_call_id IS NOT NULL"
    )

    op.execute("GRANT SELECT, INSERT, UPDATE ON customer TO app")
    op.execute("GRANT SELECT, INSERT, UPDATE ON customer_address TO app")
    op.execute("GRANT SELECT, INSERT, UPDATE ON voice_agent TO app")


def downgrade() -> None:
    op.execute("DROP INDEX tab_order_external_call")
    op.execute("DROP INDEX tab_order_customer")
    op.execute(
        """
        ALTER TABLE tab_order
            DROP CONSTRAINT tab_order_address_needs_customer,
            DROP CONSTRAINT tab_order_address_fk,
            DROP CONSTRAINT tab_order_customer_fk,
            DROP COLUMN external_call_id,
            DROP COLUMN delivery_address_snapshot,
            DROP COLUMN address_id,
            DROP COLUMN customer_id
        """
    )
    op.execute("ALTER TABLE tab_order DROP CONSTRAINT tab_order_source_check")
    op.execute(
        "ALTER TABLE tab_order ADD CONSTRAINT tab_order_source_check "
        "CHECK (source IN ('customer', 'waiter', 'aggregator'))"
    )
    op.execute("ALTER TABLE tab DROP CONSTRAINT tab_opened_by_check")
    op.execute(
        "ALTER TABLE tab ADD CONSTRAINT tab_opened_by_check "
        "CHECK (opened_by IN ('customer', 'waiter'))"
    )
    op.execute("DROP TABLE voice_agent")
    op.execute("DROP TABLE customer_address")
    op.execute("DROP TABLE customer")
