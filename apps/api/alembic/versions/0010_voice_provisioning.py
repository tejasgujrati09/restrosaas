"""voice ordering: admin allowance, provisioning state machine, attempt history

A platform admin decides per restaurant whether voice ordering may be used
(`restaurant.voice_orders_allowed`, default false). The owner's own switch stays on
`voice_agent`, whose `status` widens from four values to the provisioning state machine
(docs/DECISIONS.md "Voice provisioning"): enable_requested, provisioning, active,
provisioning_failed, disable_requested, deprovisioning, disabled, deprovisioning_failed.

`completed_steps` records which provisioning steps have succeeded, so a retry resumes rather
than repeating them. A phone number is reserved for at most one agent by a unique index on
`sr_plan_id`, so two restaurants enabling at once cannot both take the same number.
`drain_until` is the end of the window after a disable in which a call already in progress may
still place its order. `voice_provisioning_attempt` is the per-run history (who asked, what
failed, the internal detail the owner never sees).

Existing rows keep meaning: 'pending' becomes 'provisioning' and 'failed' becomes
'provisioning_failed'. Existing restaurants that already run voice are allowed, so nothing
is cut off.

Reversal in intent: downgrade drops the new table and columns and maps the new statuses back
onto the old four (in-flight ones become 'pending', failed ones 'failed'). Only an empty or
development database should ever be downgraded.
"""

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

_TENANT = "restaurant_id = nullif(current_setting('app.restaurant_id', true), '')::uuid"

_NEW = (
    "enable_requested",
    "provisioning",
    "active",
    "provisioning_failed",
    "disable_requested",
    "deprovisioning",
    "disabled",
    "deprovisioning_failed",
)


def upgrade() -> None:
    op.execute(
        "ALTER TABLE restaurant ADD COLUMN voice_orders_allowed boolean NOT NULL DEFAULT false"
    )
    op.execute(
        "UPDATE restaurant SET voice_orders_allowed = true "
        "WHERE id IN (SELECT restaurant_id FROM voice_agent)"
    )

    op.execute("ALTER TABLE voice_agent DROP CONSTRAINT voice_agent_status_check")
    op.execute("UPDATE voice_agent SET status = 'provisioning' WHERE status = 'pending'")
    op.execute("UPDATE voice_agent SET status = 'provisioning_failed' WHERE status = 'failed'")
    values = ", ".join(f"'{s}'" for s in _NEW)
    op.execute(
        "ALTER TABLE voice_agent ADD CONSTRAINT voice_agent_status_check "
        f"CHECK (status IN ({values}))"
    )
    op.execute("ALTER TABLE voice_agent ALTER COLUMN status SET DEFAULT 'enable_requested'")
    op.execute(
        """
        ALTER TABLE voice_agent
            ADD COLUMN completed_steps text[] NOT NULL DEFAULT '{}',
            ADD COLUMN failed_step text,
            ADD COLUMN drain_until timestamptz,
            ADD COLUMN enabled_at timestamptz,
            ADD COLUMN disabled_at timestamptz,
            ADD COLUMN disabled_by uuid REFERENCES app_user (id)
        """
    )
    # Rows made before this migration were provisioned in one go: every step is done.
    op.execute(
        "UPDATE voice_agent SET completed_steps = ARRAY['number','agent','configure','link',"
        "'route','verify'], enabled_at = created_at WHERE status IN ('active', 'disabled')"
    )
    op.execute(
        "CREATE UNIQUE INDEX voice_agent_one_agent_per_number ON voice_agent (sr_plan_id) "
        "WHERE sr_plan_id IS NOT NULL"
    )

    op.execute(
        """
        CREATE TABLE voice_provisioning_attempt (
            id uuid PRIMARY KEY,
            restaurant_id uuid NOT NULL REFERENCES restaurant (id),
            voice_agent_id uuid NOT NULL REFERENCES voice_agent (id),
            kind text NOT NULL CHECK (kind IN ('enable', 'disable')),
            requested_by uuid REFERENCES app_user (id),
            requested_by_platform_admin boolean NOT NULL DEFAULT false,
            started_at timestamptz NOT NULL,
            finished_at timestamptz,
            outcome text CHECK (outcome IN ('succeeded', 'failed', 'retrying', 'superseded')),
            failed_step text,
            error text
        )
        """
    )
    op.execute(
        "CREATE INDEX voice_provisioning_attempt_agent "
        "ON voice_provisioning_attempt (voice_agent_id, started_at DESC)"
    )
    op.execute("ALTER TABLE voice_provisioning_attempt ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY voice_provisioning_attempt_tenant_isolation ON voice_provisioning_attempt "
        f"USING ({_TENANT}) WITH CHECK ({_TENANT})"
    )
    op.execute("GRANT SELECT, INSERT, UPDATE ON voice_provisioning_attempt TO app")


def downgrade() -> None:
    op.execute("DROP TABLE voice_provisioning_attempt")
    op.execute("DROP INDEX voice_agent_one_agent_per_number")
    op.execute(
        """
        ALTER TABLE voice_agent
            DROP COLUMN disabled_by,
            DROP COLUMN disabled_at,
            DROP COLUMN enabled_at,
            DROP COLUMN drain_until,
            DROP COLUMN failed_step,
            DROP COLUMN completed_steps
        """
    )
    op.execute("ALTER TABLE voice_agent DROP CONSTRAINT voice_agent_status_check")
    op.execute(
        "UPDATE voice_agent SET status = 'pending' WHERE status IN "
        "('enable_requested', 'provisioning', 'disable_requested', 'deprovisioning')"
    )
    op.execute(
        "UPDATE voice_agent SET status = 'failed' WHERE status IN "
        "('provisioning_failed', 'deprovisioning_failed')"
    )
    op.execute(
        "ALTER TABLE voice_agent ADD CONSTRAINT voice_agent_status_check "
        "CHECK (status IN ('pending', 'active', 'disabled', 'failed'))"
    )
    op.execute("ALTER TABLE voice_agent ALTER COLUMN status SET DEFAULT 'pending'")
    op.execute("ALTER TABLE restaurant DROP COLUMN voice_orders_allowed")
