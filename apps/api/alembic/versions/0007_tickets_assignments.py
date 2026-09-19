"""ticket, table_assignment, tab_event.table_id, order_line.ticket_id, disputed_at and position

`ticket` is the kitchen and bar queue: one per station per round, created when the
round is placed (docs/DECISIONS.md "Milestone 4 choices"). `table_assignment` says which
waiters serve which tables; managers and owners see every table.

`tab_event.table_id` records the table a tab was at when the event happened, so the live
channel can show a waiter only events for their tables without a join. The event CHECK
list grows for ticket, serving, dispute and merge events.

Reversal in intent: downgrade drops the two tables and the added columns and restores the
previous event list (rows using newer event names are deleted first, which only a
development database should ever need).
"""

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

_TENANT = "restaurant_id = nullif(current_setting('app.restaurant_id', true), '')::uuid"

_OLD_EVENTS = (
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
_NEW_EVENTS = _OLD_EVENTS + (
    "line_disputed",
    "ticket_started",
    "ticket_ready",
    "ticket_recalled",
    "order_preparing",
    "order_ready",
    "order_served",
    "line_served",
    "service_request_resolved",
)


def _quoted(events: tuple[str, ...]) -> str:
    return ", ".join(f"'{e}'" for e in events)


def _tenant_policy(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {table}_tenant_isolation ON {table} "
        f"USING ({_TENANT}) WITH CHECK ({_TENANT})"
    )


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE ticket (
            id uuid PRIMARY KEY,
            restaurant_id uuid NOT NULL REFERENCES restaurant (id),
            outlet_id uuid NOT NULL REFERENCES outlet (id),
            order_id uuid NOT NULL REFERENCES tab_order (id),
            tab_id uuid NOT NULL REFERENCES tab (id),
            station_id uuid REFERENCES station (id),
            status text NOT NULL DEFAULT 'queued'
                CHECK (status IN ('queued', 'preparing', 'ready', 'bumped', 'cancelled')),
            created_at timestamptz NOT NULL,
            started_at timestamptz,
            started_by uuid REFERENCES app_user (id),
            ready_at timestamptz,
            ready_by uuid REFERENCES app_user (id),
            printed_at timestamptz,
            bumped_by uuid REFERENCES app_user (id)
        )
        """
    )
    _tenant_policy("ticket")
    op.execute(
        "CREATE INDEX ticket_live ON ticket (outlet_id, status) "
        "WHERE status IN ('queued', 'preparing', 'ready')"
    )
    op.execute("CREATE INDEX ticket_order ON ticket (order_id)")

    op.execute(
        """
        ALTER TABLE order_line
            ADD COLUMN ticket_id uuid REFERENCES ticket (id),
            ADD COLUMN disputed_at timestamptz,
            ADD COLUMN position integer NOT NULL DEFAULT 0
        """
    )
    op.execute("CREATE INDEX order_line_ticket ON order_line (ticket_id)")

    op.execute(
        """
        CREATE TABLE table_assignment (
            restaurant_id uuid NOT NULL REFERENCES restaurant (id),
            outlet_id uuid NOT NULL REFERENCES outlet (id),
            table_id uuid NOT NULL REFERENCES dining_table (id) ON DELETE CASCADE,
            user_id uuid NOT NULL REFERENCES app_user (id),
            assigned_by uuid NOT NULL REFERENCES app_user (id),
            assigned_at timestamptz NOT NULL,
            PRIMARY KEY (table_id, user_id)
        )
        """
    )
    _tenant_policy("table_assignment")
    op.execute("CREATE INDEX table_assignment_user ON table_assignment (user_id, outlet_id)")

    op.execute("ALTER TABLE tab_event ADD COLUMN table_id uuid REFERENCES dining_table (id)")
    op.execute("ALTER TABLE tab_event DROP CONSTRAINT tab_event_event_check")
    op.execute(
        f"ALTER TABLE tab_event ADD CONSTRAINT tab_event_event_check "
        f"CHECK (event IN ({_quoted(_NEW_EVENTS)}))"
    )

    op.execute("GRANT SELECT, INSERT, UPDATE ON ticket TO app")
    op.execute("GRANT SELECT, INSERT, DELETE ON table_assignment TO app")


def downgrade() -> None:
    op.execute(f"DELETE FROM tab_event WHERE event NOT IN ({_quoted(_OLD_EVENTS)})")
    op.execute("ALTER TABLE tab_event DROP CONSTRAINT tab_event_event_check")
    op.execute(
        f"ALTER TABLE tab_event ADD CONSTRAINT tab_event_event_check "
        f"CHECK (event IN ({_quoted(_OLD_EVENTS)}))"
    )
    op.execute("ALTER TABLE tab_event DROP COLUMN table_id")
    op.execute("DROP TABLE table_assignment")
    op.execute(
        "ALTER TABLE order_line "
        "DROP COLUMN ticket_id, DROP COLUMN disputed_at, DROP COLUMN position"
    )
    op.execute("DROP TABLE ticket")
