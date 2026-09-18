"""Loads menu rows into the pure shapes `app.core.ordering` and
`app.core.pricing` work on. Shared by the guest menu and order placement so
both see the same availability and prices."""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ordering import ModifierGroupSpec, ModifierSpec, OrderableItem
from app.core.pricing import PriceRuleSpec, RuleScope, RuleType
from app.domains.menu.models import (
    MenuCategory,
    MenuItem,
    MenuItemModifierGroup,
    Modifier,
    ModifierGroup,
    PriceRule,
)
from app.domains.tenant.models import TaxClass


@dataclass(frozen=True)
class LoadedItem:
    row: MenuItem
    category: MenuCategory
    orderable: OrderableItem


def rule_spec(row: PriceRule) -> PriceRuleSpec:
    return PriceRuleSpec(
        id=row.id,
        scope=RuleScope(row.scope),
        target_id=row.target_id,
        rule_type=RuleType(row.rule_type),
        value=row.value,
        days_of_week=frozenset(row.days_of_week),
        start_time=row.start_time,
        end_time=row.end_time,
        valid_from=row.valid_from,
        valid_to=row.valid_to,
        active=row.active,
    )


async def load_price_rules(
    session: AsyncSession, outlet_id: UUID
) -> tuple[list[PriceRuleSpec], dict[UUID, str]]:
    rows = (await session.scalars(select(PriceRule).where(PriceRule.outlet_id == outlet_id))).all()
    return [rule_spec(r) for r in rows], {r.id: r.name for r in rows}


async def load_items(
    session: AsyncSession,
    outlet_id: UUID,
    liquor_vat_rate_bp: int,
    item_ids: Collection[UUID] | None = None,
) -> dict[UUID, LoadedItem]:
    """Liquor carries the outlet's state VAT rate (its tax class has no GST);
    everything else carries its tax class's GST rate."""
    query = (
        select(MenuItem, MenuCategory, TaxClass)
        .join(MenuCategory, MenuCategory.id == MenuItem.category_id)
        .join(TaxClass, TaxClass.id == MenuItem.tax_class_id)
        .where(MenuItem.outlet_id == outlet_id)
        .order_by(MenuItem.sort_order, MenuItem.name)
    )
    if item_ids is not None:
        query = query.where(MenuItem.id.in_(item_ids))
    rows = (await session.execute(query)).all()
    if not rows:
        return {}

    links = await session.execute(
        select(MenuItemModifierGroup.item_id, MenuItemModifierGroup.group_id).where(
            MenuItemModifierGroup.item_id.in_([r._tuple()[0].id for r in rows])
        )
    )
    group_ids_by_item: dict[UUID, list[UUID]] = {}
    for item_id, group_id in links:
        group_ids_by_item.setdefault(item_id, []).append(group_id)
    all_group_ids = {g for ids in group_ids_by_item.values() for g in ids}

    groups: dict[UUID, ModifierGroupSpec] = {}
    if all_group_ids:
        modifiers_by_group: dict[UUID, list[ModifierSpec]] = {}
        for m in await session.scalars(
            select(Modifier).where(Modifier.group_id.in_(all_group_ids)).order_by(Modifier.name)
        ):
            modifiers_by_group.setdefault(m.group_id, []).append(
                ModifierSpec(m.id, m.name, m.price_delta_paise)
            )
        for g in await session.scalars(
            select(ModifierGroup).where(ModifierGroup.id.in_(all_group_ids))
        ):
            groups[g.id] = ModifierGroupSpec(
                g.id, g.name, g.min_select, g.max_select, tuple(modifiers_by_group.get(g.id, []))
            )

    loaded: dict[UUID, LoadedItem] = {}
    for row in rows:
        item, category, tax = row._tuple()
        loaded[item.id] = LoadedItem(
            row=item,
            category=category,
            orderable=OrderableItem(
                id=item.id,
                name=item.name,
                category_id=category.id,
                category_visible=category.visible,
                category_from=category.available_from,
                category_to=category.available_to,
                available=item.available,
                is_liquor=item.is_liquor,
                needs_approval=item.needs_approval,
                base_price_paise=item.base_price_paise,
                tax_class_name=tax.name,
                tax_rate_bp=liquor_vat_rate_bp if tax.liquor_vat else tax.gst_rate_bp,
                groups=tuple(
                    groups[g] for g in sorted(group_ids_by_item.get(item.id, [])) if g in groups
                ),
            ),
        )
    return loaded
