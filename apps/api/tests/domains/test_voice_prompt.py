"""The agent's prompt and tool descriptions: built only from the menu, with the guardrails
that stop it claiming more than it knows. Fixture menu data only."""

from __future__ import annotations

import uuid

from app.domains.voice.platform import ToolParam
from app.domains.voice.prompt import (
    PromptCategory,
    PromptItem,
    PromptMenu,
    PromptModifier,
    PromptModifierGroup,
    build_agent_prompt,
)
from app.domains.voice.tools import KEY_HEADER, build_tools

TIKKA = uuid.uuid4()
SPICE = uuid.uuid4()


def _menu() -> PromptMenu:
    return PromptMenu(
        "Fixture Kitchen",
        (
            PromptCategory(
                "Starters",
                (
                    PromptItem(
                        TIKKA,
                        "Fixture Tikka",
                        32000,
                        True,
                        "with mint",
                        (
                            PromptModifierGroup(
                                "Spice",
                                1,
                                1,
                                (PromptModifier(SPICE, "Extra hot", 2000),),
                            ),
                        ),
                    ),
                ),
            ),
        ),
    )


def test_every_item_price_and_option_comes_from_the_menu() -> None:
    prompt, first = build_agent_prompt(_menu())
    assert "Fixture Kitchen" in prompt and "Fixture Kitchen" in first
    assert f"Fixture Tikka (veg) ₹320.00 item_id={TIKKA} | with mint" in prompt
    assert f"Spice (choose 1): Extra hot (+₹20.00) modifier_id={SPICE}" in prompt


def test_the_prompt_forbids_claiming_an_order_is_confirmed() -> None:
    prompt, _ = build_agent_prompt(_menu())
    assert 'NOT placed until place_order answers "ORDER SENT FOR CONFIRMATION"' in prompt
    assert "Never say the order is confirmed" in prompt
    assert "ORDER NOT PLACED" in prompt
    assert "Never pretend it worked" in prompt
    assert "never promise a time" in prompt.lower()


def test_the_prompt_keeps_the_guardrails_from_the_pilot_template() -> None:
    prompt, _ = build_agent_prompt(_menu())
    assert "Let me have the restaurant call you back about that" in prompt
    assert "Never ask for card details, OTPs or passwords" in prompt
    assert "Never invent an item, a price, an option or availability" in prompt
    assert "Do not add up prices or quote a total yourself" in prompt


def test_an_empty_menu_takes_no_orders() -> None:
    prompt, _ = build_agent_prompt(PromptMenu("Fixture Kitchen", ()))
    assert "The menu is empty: take no orders" in prompt


def test_no_item_appears_that_is_not_in_the_menu() -> None:
    prompt, _ = build_agent_prompt(_menu())
    menu_part = prompt.split("THE MENU (")[1]
    assert menu_part.count("item_id=") == 1


def test_the_callers_phone_is_never_asked_of_the_model() -> None:
    for tool in build_tools("https://tools.example.test", "fixture-key"):
        phones = [p for p in tool.body if p.name == "phone"]
        assert len(phones) == 1
        assert phones[0].source == "call_variable"
        assert phones[0].value == "caller"


def test_every_tool_carries_the_key_as_a_secret_header_and_points_at_our_api() -> None:
    tools = build_tools("https://tools.example.test/", "fixture-key")
    assert [t.name for t in tools] == ["lookup_customer", "save_address", "place_order"]
    for tool in tools:
        assert tool.secret_headers == {KEY_HEADER: "fixture-key"}
        assert tool.url == f"https://tools.example.test/v1/voice/tools/{tool.name}"
        assert tool.method == "POST"


def test_place_order_takes_no_price_or_total() -> None:
    (place,) = [t for t in build_tools("https://t.example.test", "k") if t.name == "place_order"]

    def names(params: tuple[ToolParam, ...]) -> set[str]:
        found: set[str] = set()
        for p in params:
            found.add(p.name)
            found |= names(p.properties)
            if p.items is not None:
                found |= names((p.items,))
        return found

    assert names(place.body).isdisjoint({"price", "total", "amount", "unit_price"})
