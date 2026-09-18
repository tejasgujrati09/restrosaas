"""dining_table, station, tax_class

`restaurant_id` is denormalised onto every tenant table (CLAUDE.md §3), even
where docs/SPEC.md §7 lists only `outlet_id`, so each policy is a direct column
check. `table` is a reserved SQL word, hence `dining_table`.

Reversal in intent: downgrade drops the three tables.
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE dining_table (
            id uuid PRIMARY KEY,
            restaurant_id uuid NOT NULL REFERENCES restaurant (id),
            outlet_id uuid NOT NULL REFERENCES outlet (id),
            label text NOT NULL,
            zone text NOT NULL DEFAULT 'floor',
            seats integer NOT NULL DEFAULT 2 CHECK (seats > 0),
            qr_token text NOT NULL UNIQUE,
            requires_waiter_confirm boolean NOT NULL DEFAULT false,
            active boolean NOT NULL DEFAULT true,
            UNIQUE (outlet_id, label)
        )
        """
    )
    op.execute("ALTER TABLE dining_table ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY dining_table_tenant_isolation ON dining_table
            USING (restaurant_id = nullif(current_setting('app.restaurant_id', true), '')::uuid)
            WITH CHECK (
                restaurant_id = nullif(current_setting('app.restaurant_id', true), '')::uuid
            )
        """
    )

    op.execute(
        """
        CREATE TABLE station (
            id uuid PRIMARY KEY,
            restaurant_id uuid NOT NULL REFERENCES restaurant (id),
            outlet_id uuid NOT NULL REFERENCES outlet (id),
            name text NOT NULL,
            printer_id text
        )
        """
    )
    op.execute("ALTER TABLE station ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY station_tenant_isolation ON station
            USING (restaurant_id = nullif(current_setting('app.restaurant_id', true), '')::uuid)
            WITH CHECK (
                restaurant_id = nullif(current_setting('app.restaurant_id', true), '')::uuid
            )
        """
    )

    op.execute(
        """
        CREATE TABLE tax_class (
            id uuid PRIMARY KEY,
            restaurant_id uuid NOT NULL REFERENCES restaurant (id),
            outlet_id uuid NOT NULL REFERENCES outlet (id),
            name text NOT NULL,
            gst_rate_bp integer NOT NULL DEFAULT 0 CHECK (gst_rate_bp >= 0),
            liquor_vat boolean NOT NULL DEFAULT false,
            CHECK (NOT liquor_vat OR gst_rate_bp = 0)
        )
        """
    )
    op.execute("ALTER TABLE tax_class ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tax_class_tenant_isolation ON tax_class
            USING (restaurant_id = nullif(current_setting('app.restaurant_id', true), '')::uuid)
            WITH CHECK (
                restaurant_id = nullif(current_setting('app.restaurant_id', true), '')::uuid
            )
        """
    )

    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON dining_table, station, tax_class TO app")


def downgrade() -> None:
    op.execute("DROP TABLE tax_class")
    op.execute("DROP TABLE station")
    op.execute("DROP TABLE dining_table")
