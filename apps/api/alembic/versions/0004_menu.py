"""menu_category, menu_item, modifier_group, modifier, menu_item_modifier_group,
price_rule

Money is integer paise; percentage rules are basis points (percent * 100).
`menu_item.base_price_paise` holds exactly what the owner typed, in the
outlet's `prices_include_tax` mode (docs/DECISIONS.md "Tax storage").

Reversal in intent: downgrade drops the six tables.
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

_POLICY_USING = "restaurant_id = nullif(current_setting('app.restaurant_id', true), '')::uuid"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE menu_category (
            id uuid PRIMARY KEY,
            restaurant_id uuid NOT NULL REFERENCES restaurant (id),
            outlet_id uuid NOT NULL REFERENCES outlet (id),
            name text NOT NULL,
            sort_order integer NOT NULL DEFAULT 0,
            visible boolean NOT NULL DEFAULT true,
            available_from time,
            available_to time
        )
        """
    )
    op.execute("ALTER TABLE menu_category ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY menu_category_tenant_isolation ON menu_category "
        f"USING ({_POLICY_USING}) WITH CHECK ({_POLICY_USING})"
    )

    op.execute(
        """
        CREATE TABLE menu_item (
            id uuid PRIMARY KEY,
            restaurant_id uuid NOT NULL REFERENCES restaurant (id),
            outlet_id uuid NOT NULL REFERENCES outlet (id),
            category_id uuid NOT NULL REFERENCES menu_category (id),
            name text NOT NULL,
            description text,
            base_price_paise integer NOT NULL CHECK (base_price_paise >= 0),
            tax_class_id uuid NOT NULL REFERENCES tax_class (id),
            station_id uuid REFERENCES station (id),
            veg_flag boolean NOT NULL DEFAULT true,
            is_liquor boolean NOT NULL DEFAULT false,
            needs_approval boolean NOT NULL DEFAULT false,
            available boolean NOT NULL DEFAULT true,
            image_url text,
            sort_order integer NOT NULL DEFAULT 0,
            sku text
        )
        """
    )
    op.execute("ALTER TABLE menu_item ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY menu_item_tenant_isolation ON menu_item "
        f"USING ({_POLICY_USING}) WITH CHECK ({_POLICY_USING})"
    )

    op.execute(
        """
        CREATE TABLE modifier_group (
            id uuid PRIMARY KEY,
            restaurant_id uuid NOT NULL REFERENCES restaurant (id),
            outlet_id uuid NOT NULL REFERENCES outlet (id),
            name text NOT NULL,
            min_select integer NOT NULL DEFAULT 0 CHECK (min_select >= 0),
            max_select integer NOT NULL DEFAULT 1,
            CHECK (max_select >= min_select)
        )
        """
    )
    op.execute("ALTER TABLE modifier_group ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY modifier_group_tenant_isolation ON modifier_group "
        f"USING ({_POLICY_USING}) WITH CHECK ({_POLICY_USING})"
    )

    op.execute(
        """
        CREATE TABLE modifier (
            id uuid PRIMARY KEY,
            restaurant_id uuid NOT NULL REFERENCES restaurant (id),
            group_id uuid NOT NULL REFERENCES modifier_group (id),
            name text NOT NULL,
            price_delta_paise integer NOT NULL DEFAULT 0
        )
        """
    )
    op.execute("ALTER TABLE modifier ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY modifier_tenant_isolation ON modifier "
        f"USING ({_POLICY_USING}) WITH CHECK ({_POLICY_USING})"
    )

    op.execute(
        """
        CREATE TABLE menu_item_modifier_group (
            item_id uuid NOT NULL REFERENCES menu_item (id),
            group_id uuid NOT NULL REFERENCES modifier_group (id),
            restaurant_id uuid NOT NULL REFERENCES restaurant (id),
            PRIMARY KEY (item_id, group_id)
        )
        """
    )
    op.execute("ALTER TABLE menu_item_modifier_group ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY menu_item_modifier_group_tenant_isolation ON menu_item_modifier_group "
        f"USING ({_POLICY_USING}) WITH CHECK ({_POLICY_USING})"
    )

    op.execute(
        """
        CREATE TABLE price_rule (
            id uuid PRIMARY KEY,
            restaurant_id uuid NOT NULL REFERENCES restaurant (id),
            outlet_id uuid NOT NULL REFERENCES outlet (id),
            name text NOT NULL,
            scope text NOT NULL CHECK (scope IN ('item', 'category', 'all')),
            target_id uuid,
            rule_type text NOT NULL CHECK (rule_type IN ('fixed', 'percent_off')),
            value integer NOT NULL CHECK (value >= 0),
            days_of_week smallint[] NOT NULL,
            start_time time NOT NULL,
            end_time time NOT NULL,
            valid_from timestamptz,
            valid_to timestamptz,
            active boolean NOT NULL DEFAULT true,
            CHECK ((scope = 'all') = (target_id IS NULL))
        )
        """
    )
    op.execute("ALTER TABLE price_rule ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY price_rule_tenant_isolation ON price_rule "
        f"USING ({_POLICY_USING}) WITH CHECK ({_POLICY_USING})"
    )

    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON "
        "menu_category, menu_item, modifier_group, modifier, "
        "menu_item_modifier_group, price_rule TO app"
    )


def downgrade() -> None:
    op.execute("DROP TABLE price_rule")
    op.execute("DROP TABLE menu_item_modifier_group")
    op.execute("DROP TABLE modifier")
    op.execute("DROP TABLE modifier_group")
    op.execute("DROP TABLE menu_item")
    op.execute("DROP TABLE menu_category")
