"""tab, tab_session, tab_order, order_line, tab_event, service_request

Guests are unauthenticated, so the only RLS change for them is one SELECT-only
policy on `dining_table`, keyed on `app.qr_token` (same shape as
`staff_invite_by_token`): the QR landing reads exactly the one table whose token
it holds, then opens a normal tenant session using that table's restaurant.
TabSession tokens carry the restaurant id, so `tab_session` needs no such policy.

`tab_event` is insert-only for the app role (CLAUDE.md §3). `order` is a
reserved SQL word, hence `tab_order`.

One live tab per table: the unique index covers `open` and `bill_requested`
(docs/DECISIONS.md "Milestone 3 choices").

`idempotency_key.user_id` becomes `actor_id` and loses its foreign key so a
guest's TabSession id can scope a key as a staff user id does.

Reversal in intent: downgrade drops the six tables and the policy, and turns
`actor_id` back into `user_id`, deleting any key rows written by guests.
"""

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

_TENANT = "restaurant_id = nullif(current_setting('app.restaurant_id', true), '')::uuid"

_EVENTS = (
    "opened",
    "confirmed",
    "line_added",
    "line_acked",
    "line_voided",
    "discount_applied",
    "price_rule_applied",
    "transferred",
    "merged",
    "bill_requested",
    "bill_request_cleared",
    "closed",
    "reopened",
    "order_placed",
    "order_accepted",
    "order_cancelled",
    "service_charge_changed",
    "service_requested",
)


def _tenant_policy(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {table}_tenant_isolation ON {table} "
        f"USING ({_TENANT}) WITH CHECK ({_TENANT})"
    )


def upgrade() -> None:
    op.execute(
        """
        CREATE POLICY dining_table_by_qr_token ON dining_table FOR SELECT
            USING (qr_token = nullif(current_setting('app.qr_token', true), ''))
        """
    )

    op.execute("ALTER TABLE idempotency_key DROP CONSTRAINT idempotency_key_pkey")
    op.execute("ALTER TABLE idempotency_key DROP CONSTRAINT idempotency_key_user_id_fkey")
    op.execute("ALTER TABLE idempotency_key RENAME COLUMN user_id TO actor_id")
    op.execute("ALTER TABLE idempotency_key ADD PRIMARY KEY (restaurant_id, actor_id, key)")

    op.execute(
        """
        CREATE TABLE tab (
            id uuid PRIMARY KEY,
            restaurant_id uuid NOT NULL REFERENCES restaurant (id),
            outlet_id uuid NOT NULL REFERENCES outlet (id),
            table_id uuid REFERENCES dining_table (id),
            status text NOT NULL DEFAULT 'open'
                CHECK (status IN ('open', 'bill_requested', 'closed', 'voided')),
            opened_at timestamptz NOT NULL DEFAULT now(),
            closed_at timestamptz,
            opened_by text NOT NULL CHECK (opened_by IN ('customer', 'waiter')),
            guest_count integer CHECK (guest_count > 0),
            customer_phone text,
            notes text,
            confirmed_at timestamptz,
            service_charge_removed boolean NOT NULL DEFAULT false
        )
        """
    )
    _tenant_policy("tab")
    op.execute(
        "CREATE UNIQUE INDEX tab_one_live_per_table ON tab (table_id) "
        "WHERE status IN ('open', 'bill_requested')"
    )
    op.execute("CREATE INDEX tab_outlet_status ON tab (outlet_id, status)")

    op.execute(
        """
        CREATE TABLE tab_session (
            id uuid PRIMARY KEY,
            restaurant_id uuid NOT NULL REFERENCES restaurant (id),
            tab_id uuid NOT NULL REFERENCES tab (id),
            token_hash text NOT NULL UNIQUE,
            device_fingerprint text,
            created_at timestamptz NOT NULL DEFAULT now(),
            expires_at timestamptz NOT NULL,
            revoked boolean NOT NULL DEFAULT false
        )
        """
    )
    _tenant_policy("tab_session")
    op.execute("CREATE INDEX tab_session_tab ON tab_session (tab_id)")

    op.execute(
        """
        CREATE TABLE tab_order (
            id uuid PRIMARY KEY,
            restaurant_id uuid NOT NULL REFERENCES restaurant (id),
            outlet_id uuid NOT NULL REFERENCES outlet (id),
            tab_id uuid NOT NULL REFERENCES tab (id),
            seq_no integer NOT NULL CHECK (seq_no > 0),
            status text NOT NULL DEFAULT 'placed' CHECK (
                status IN ('placed', 'accepted', 'preparing', 'ready', 'served', 'cancelled',
                           'dispatched', 'delivered')
            ),
            fulfillment_type text NOT NULL DEFAULT 'dine_in'
                CHECK (fulfillment_type IN ('dine_in', 'pickup', 'delivery')),
            placed_at timestamptz NOT NULL,
            placed_by_user_id uuid REFERENCES app_user (id),
            placed_by_session_id uuid REFERENCES tab_session (id),
            source text NOT NULL CHECK (source IN ('customer', 'waiter', 'aggregator')),
            accepted_at timestamptz,
            cancelled_at timestamptz,
            UNIQUE (tab_id, seq_no),
            CHECK (num_nonnulls(placed_by_user_id, placed_by_session_id) <= 1)
        )
        """
    )
    _tenant_policy("tab_order")
    op.execute(
        "CREATE INDEX tab_order_live ON tab_order (outlet_id, status) "
        "WHERE status NOT IN ('served', 'cancelled')"
    )

    op.execute(
        """
        CREATE TABLE order_line (
            id uuid PRIMARY KEY,
            restaurant_id uuid NOT NULL REFERENCES restaurant (id),
            order_id uuid NOT NULL REFERENCES tab_order (id),
            tab_id uuid NOT NULL REFERENCES tab (id),
            menu_item_id uuid NOT NULL REFERENCES menu_item (id),
            item_name_snapshot text NOT NULL,
            qty integer NOT NULL CHECK (qty > 0),
            unit_price_snapshot integer NOT NULL CHECK (unit_price_snapshot >= 0),
            price_rule_id uuid,
            price_rule_name_snapshot text,
            tax_class_snapshot jsonb NOT NULL,
            modifiers_snapshot jsonb NOT NULL DEFAULT '[]',
            line_total integer NOT NULL CHECK (line_total >= 0),
            status text NOT NULL DEFAULT 'placed' CHECK (
                status IN ('placed', 'accepted', 'preparing', 'ready', 'served', 'cancelled',
                           'voided')
            ),
            placed_by text NOT NULL CHECK (placed_by IN ('customer', 'staff')),
            staff_user_id uuid REFERENCES app_user (id),
            needs_customer_ack boolean NOT NULL DEFAULT false,
            acked_at timestamptz,
            notes text,
            voided_at timestamptz,
            void_reason text,
            CHECK ((placed_by = 'staff') = (staff_user_id IS NOT NULL)),
            CHECK (NOT needs_customer_ack OR placed_by = 'staff'),
            CHECK (voided_at IS NULL OR void_reason IS NOT NULL)
        )
        """
    )
    _tenant_policy("order_line")
    op.execute("CREATE INDEX order_line_order ON order_line (order_id)")
    op.execute("CREATE INDEX order_line_tab ON order_line (tab_id)")

    events = ", ".join(f"'{e}'" for e in _EVENTS)
    op.execute(
        f"""
        CREATE TABLE tab_event (
            id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            restaurant_id uuid NOT NULL REFERENCES restaurant (id),
            tab_id uuid NOT NULL REFERENCES tab (id),
            at timestamptz NOT NULL DEFAULT now(),
            actor_type text NOT NULL CHECK (actor_type IN ('customer', 'staff', 'system')),
            actor_user_id uuid REFERENCES app_user (id),
            actor_session_id uuid REFERENCES tab_session (id),
            event text NOT NULL CHECK (event IN ({events})),
            payload jsonb NOT NULL DEFAULT '{{}}',
            reason text
        )
        """
    )
    _tenant_policy("tab_event")
    op.execute("CREATE INDEX tab_event_tab ON tab_event (tab_id, id)")

    op.execute(
        """
        CREATE TABLE service_request (
            id uuid PRIMARY KEY,
            restaurant_id uuid NOT NULL REFERENCES restaurant (id),
            outlet_id uuid NOT NULL REFERENCES outlet (id),
            tab_id uuid NOT NULL REFERENCES tab (id),
            type text NOT NULL CHECK (type IN ('waiter', 'water', 'bill', 'other')),
            created_at timestamptz NOT NULL,
            created_by_session_id uuid REFERENCES tab_session (id),
            resolved_by uuid REFERENCES app_user (id),
            resolved_at timestamptz
        )
        """
    )
    _tenant_policy("service_request")
    op.execute(
        "CREATE UNIQUE INDEX service_request_one_open ON service_request (tab_id, type) "
        "WHERE resolved_at IS NULL"
    )

    op.execute("GRANT SELECT, INSERT, UPDATE ON tab, tab_session, tab_order, order_line TO app")
    op.execute("GRANT SELECT, INSERT, UPDATE ON service_request TO app")
    op.execute("GRANT SELECT, INSERT ON tab_event TO app")


def downgrade() -> None:
    for table in (
        "service_request",
        "tab_event",
        "order_line",
        "tab_order",
        "tab_session",
        "tab",
    ):
        op.execute(f"DROP TABLE {table}")
    op.execute("DROP POLICY dining_table_by_qr_token ON dining_table")
    op.execute("DELETE FROM idempotency_key WHERE actor_id NOT IN (SELECT id FROM app_user)")
    op.execute("ALTER TABLE idempotency_key DROP CONSTRAINT idempotency_key_pkey")
    op.execute("ALTER TABLE idempotency_key RENAME COLUMN actor_id TO user_id")
    op.execute("ALTER TABLE idempotency_key ADD PRIMARY KEY (restaurant_id, user_id, key)")
    op.execute(
        "ALTER TABLE idempotency_key ADD CONSTRAINT idempotency_key_user_id_fkey "
        "FOREIGN KEY (user_id) REFERENCES app_user (id)"
    )
