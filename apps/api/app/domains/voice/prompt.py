# ruff: noqa: E501
"""The phone agent's instructions, built from the restaurant's own menu and nothing else.

Every item, price and option in the prompt comes from the `PromptMenu` it is given (the
restaurant's live menu); the wording around it is fixed. Nothing about a shop is invented here
(CLAUDE.md §3). The rules that matter most are written first and plainly: an order is only
"sent for confirmation" until a person accepts it, and the agent must never say more.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.core.money import format_inr


@dataclass(frozen=True)
class PromptModifier:
    id: UUID
    name: str
    price_delta_paise: int


@dataclass(frozen=True)
class PromptModifierGroup:
    name: str
    min_select: int
    max_select: int
    modifiers: tuple[PromptModifier, ...]


@dataclass(frozen=True)
class PromptItem:
    id: UUID
    name: str
    price_paise: int
    veg: bool
    description: str | None = None
    modifier_groups: tuple[PromptModifierGroup, ...] = ()


@dataclass(frozen=True)
class PromptCategory:
    name: str
    items: tuple[PromptItem, ...]


@dataclass(frozen=True)
class PromptMenu:
    restaurant_name: str
    categories: tuple[PromptCategory, ...]

    @property
    def item_count(self) -> int:
        return sum(len(c.items) for c in self.categories)


_TEMPLATE = """You are the phone ordering assistant for {name}. You speak naturally in Hindi, English, or a mix (Hinglish), matching whatever the caller uses. Keep every reply short and conversational: this is a phone call, not a chat.

HOW A CALL GOES
1. Right after your greeting, call lookup_customer. Use the result silently; never say you "looked them up".
2. Known customer: greet them by name. New customer: ask for their name.
3. Ask what they would like to order, and whether it is for pickup or delivery.
4. Delivery: if they have saved addresses, confirm which one to use and pass its address_id. If they give a new address, pass it as address. Never invent or assume an address.
5. Read the order back, items and quantities only, and get a clear yes. Do not add up prices or quote a total yourself.
6. Then call place_order and tell the caller exactly what its result says.
7. Thank them and end the call warmly.

RULES ABOUT ORDERS (most important)
- Sell only items from THE MENU below, and pass only the item_id shown there. Never invent an item, a price, an option or availability. If something is not on the menu, say so and offer what is.
- An order is NOT placed until place_order answers "ORDER SENT FOR CONFIRMATION". Even then it is NOT confirmed: the restaurant still has to accept it. Tell the caller the restaurant has received the order and will confirm shortly. Never say the order is confirmed, accepted or on its way, and never promise a time.
- If place_order answers "ORDER NOT PLACED", tell the caller honestly, fix the problem with them, or offer that the restaurant will call back. Never pretend it worked.
- You may quote an item's price from the menu. The order total comes only from place_order's result.
- If lookup_customer says the caller's number is unavailable, ask for a mobile number and pass it as contact_phone.
- For an item with options, ask the caller to choose, and pass the chosen modifier_ids with that item.

GUARDRAILS
- Talk only about placing an order. No general chat, advice, or opinions on other businesses.
- If the caller is upset, or asks for something you cannot do (a complaint, a refund, a payment, anything not on the menu data), say "Let me have the restaurant call you back about that" and end the call politely. Do not try to resolve it yourself.
- Never ask for card details, OTPs or passwords.

THE MENU (this restaurant's own; prices in rupees; item_id is what you pass to place_order)
{menu}"""


def _item_lines(item: PromptItem) -> list[str]:
    diet = "veg" if item.veg else "non-veg"
    line = f"- {item.name} ({diet}) {format_inr(item.price_paise)} item_id={item.id}"
    if item.description:
        line += f" | {item.description}"
    lines = [line]
    for group in item.modifier_groups:
        rule = (
            f"choose {group.min_select}"
            if group.min_select == group.max_select
            else f"choose {group.min_select} to {group.max_select}"
        )
        options = ", ".join(
            f"{m.name}"
            + (f" (+{format_inr(m.price_delta_paise)})" if m.price_delta_paise else "")
            + f" modifier_id={m.id}"
            for m in group.modifiers
        )
        lines.append(f"    {group.name} ({rule}): {options}")
    return lines


def build_agent_prompt(menu: PromptMenu) -> tuple[str, str]:
    """Returns (system prompt, first message)."""
    sections: list[str] = []
    for category in menu.categories:
        if not category.items:
            continue
        sections.append(category.name.upper())
        for item in category.items:
            sections.extend(_item_lines(item))
        sections.append("")
    menu_text = "\n".join(sections).strip() or "(The menu is empty: take no orders.)"
    prompt = _TEMPLATE.format(name=menu.restaurant_name, menu=menu_text)
    first_message = (
        f"Namaste! {menu.restaurant_name} mein aapka swagat hai. "
        "Main aapka order lene ke liye hoon. Bataiye, kya order karna hai?"
    )
    return prompt, first_message
