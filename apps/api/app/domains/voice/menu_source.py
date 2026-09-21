"""The menu the phone agent is told about. Only what a caller could really order: listed, in
stock, and not gated behind a manager's approval (a phone call cannot get that approval).
Shared by the request path (re-sync) and the provisioning job."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app import clock
from app.domains.tenant.models import Restaurant
from app.domains.voice.prompt import (
    PromptCategory,
    PromptItem,
    PromptMenu,
    PromptModifier,
    PromptModifierGroup,
)


async def load_prompt_menu(
    session: AsyncSession, restaurant_id: UUID, outlet_id: UUID
) -> PromptMenu:
    from app.api.v1.guest import build_guest_menu  # the guest menu is the source of truth

    restaurant = await session.get(Restaurant, restaurant_id)
    assert restaurant is not None
    menu = await build_guest_menu(session, outlet_id, clock.utcnow())
    categories: list[PromptCategory] = []
    for category in menu.categories:
        items = tuple(
            PromptItem(
                id=item.id,
                name=item.name,
                price_paise=item.price_paise,
                veg=item.veg,
                description=item.description,
                modifier_groups=tuple(
                    PromptModifierGroup(
                        name=g.name,
                        min_select=g.min_select,
                        max_select=g.max_select,
                        modifiers=tuple(
                            PromptModifier(m.id, m.name, m.price_delta_paise) for m in g.modifiers
                        ),
                    )
                    for g in item.modifier_groups
                ),
            )
            for item in category.items
            if item.available and item.self_orderable
        )
        if items:
            categories.append(PromptCategory(category.name, items))
    return PromptMenu(restaurant.brand_name, tuple(categories))
