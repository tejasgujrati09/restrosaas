"""auto-assignment of unassigned tables: outlet settings, rotation cursor, automatic marker

Per outlet (docs/DECISIONS.md "Table assignment: bulk and automatic"):

* `outlet.auto_assign_unassigned_table_orders` (default false): when an order arrives at a table
  with no waiter, pick one by `auto_assignment_strategy` (nearest, least_loaded, rotation).
* `outlet.assignment_rotation_last_user_id`: the rotation cursor, persisted so it is the same in
  every API process. It is read and written under the outlet row lock, so concurrent orders
  cannot both take the same turn.
* `table_assignment.auto_assigned`: marks assignments made by the system so they can be
  released when the guest leaves. Manual assignments are never released automatically.
  `assigned_by` becomes nullable because the system is not a user.
* `tab_event` gains `waiter_assigned` (the dispute log records who was given the table).

No new table, so no new RLS policy; existing policies still apply.

Reversal in intent: downgrade drops the new columns, restores NOT NULL on `assigned_by` (rows the
system made are deleted first) and the old event list. Only an empty or development database
should ever be downgraded.
"""

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None

_OLD = [
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
    "line_disputed",
    "ticket_started",
    "ticket_ready",
    "ticket_recalled",
    "order_preparing",
    "order_ready",
    "order_served",
    "line_served",
    "service_request_resolved",
]


def _check(events: list[str]) -> str:
    values = ", ".join(f"'{e}'" for e in events)
    return f"ALTER TABLE tab_event ADD CONSTRAINT tab_event_event_check CHECK (event IN ({values}))"


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE outlet
            ADD COLUMN auto_assign_unassigned_table_orders boolean NOT NULL DEFAULT false,
            ADD COLUMN auto_assignment_strategy text NOT NULL DEFAULT 'least_loaded'
                CHECK (auto_assignment_strategy IN ('nearest', 'least_loaded', 'rotation')),
            ADD COLUMN assignment_rotation_last_user_id uuid REFERENCES app_user (id)
        """
    )
    op.execute(
        "ALTER TABLE table_assignment ADD COLUMN auto_assigned boolean NOT NULL DEFAULT false"
    )
    op.execute("ALTER TABLE table_assignment ALTER COLUMN assigned_by DROP NOT NULL")
    op.execute("ALTER TABLE tab_event DROP CONSTRAINT tab_event_event_check")
    op.execute(_check([*_OLD, "waiter_assigned"]))


def downgrade() -> None:
    op.execute("DELETE FROM tab_event WHERE event = 'waiter_assigned'")
    op.execute("ALTER TABLE tab_event DROP CONSTRAINT tab_event_event_check")
    op.execute(_check(_OLD))
    op.execute("DELETE FROM table_assignment WHERE assigned_by IS NULL")
    op.execute("ALTER TABLE table_assignment ALTER COLUMN assigned_by SET NOT NULL")
    op.execute("ALTER TABLE table_assignment DROP COLUMN auto_assigned")
    op.execute(
        """
        ALTER TABLE outlet
            DROP COLUMN assignment_rotation_last_user_id,
            DROP COLUMN auto_assignment_strategy,
            DROP COLUMN auto_assign_unassigned_table_orders
        """
    )
