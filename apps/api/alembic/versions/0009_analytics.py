"""analytics: expected prep time, who served a line and when, and the indexes that read them

* `outlet.expected_prep_minutes` (default 10): the owner-editable yardstick for "delayed".
* `order_line.served_at` / `served_by`: serving was only in `tab_event` (a JSON payload), which
  is too slow to aggregate. Backfilled from `line_served` events.
* Indexes for range scans by outlet and time. No new table, so no new RLS policy is needed;
  the existing policies on these tables still apply.

Reversal in intent: downgrade drops the indexes and the three columns (the served data stays
in `tab_event`, which is never modified).
"""

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE outlet ADD COLUMN expected_prep_minutes integer NOT NULL DEFAULT 10 "
        "CHECK (expected_prep_minutes BETWEEN 1 AND 240)"
    )
    op.execute("ALTER TABLE order_line ADD COLUMN served_at timestamptz")
    op.execute("ALTER TABLE order_line ADD COLUMN served_by uuid REFERENCES app_user (id)")
    op.execute(
        """
        UPDATE order_line ol
           SET served_at = e.at, served_by = e.actor_user_id
          FROM tab_event e
         WHERE e.event = 'line_served'
           AND e.payload ->> 'line_id' = ol.id::text
           AND ol.status = 'served'
        """
    )
    op.execute("CREATE INDEX tab_order_outlet_placed ON tab_order (outlet_id, placed_at)")
    op.execute("CREATE INDEX ticket_outlet_created ON ticket (outlet_id, created_at)")
    op.execute(
        "CREATE INDEX order_line_served ON order_line (served_by, served_at) "
        "WHERE served_at IS NOT NULL"
    )
    op.execute("CREATE INDEX tab_outlet_opened ON tab (outlet_id, opened_at)")


def downgrade() -> None:
    op.execute("DROP INDEX tab_outlet_opened")
    op.execute("DROP INDEX order_line_served")
    op.execute("DROP INDEX ticket_outlet_created")
    op.execute("DROP INDEX tab_order_outlet_placed")
    op.execute("ALTER TABLE order_line DROP COLUMN served_by")
    op.execute("ALTER TABLE order_line DROP COLUMN served_at")
    op.execute("ALTER TABLE outlet DROP COLUMN expected_prep_minutes")
