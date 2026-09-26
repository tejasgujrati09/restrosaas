"""restaurant.plan_expires_at: when the restaurant's plan ends

Nullable: `trial` and any plan without a fixed end simply have none. It is display and
bookkeeping only for now (nothing is suspended automatically); a platform admin sets it from
the restaurant's details. Existing rows keep NULL. No new table, so no new RLS policy.

Reversal in intent: downgrade drops the column.
"""

from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE restaurant ADD COLUMN plan_expires_at timestamptz")


def downgrade() -> None:
    op.execute("ALTER TABLE restaurant DROP COLUMN plan_expires_at")
