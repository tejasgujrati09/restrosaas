"""The three tools the phone agent can call, described in vendor-neutral terms. The Gupshup
adapter turns these into the platform's format. The caller's phone is always bound to the
`caller` call variable, never asked of the model (docs/DECISIONS.md "Voice ordering agent")."""

from __future__ import annotations

from app.domains.voice.platform import ToolParam, ToolSpec

CALLER_VARIABLE = "caller"
KEY_HEADER = "X-Voice-Key"

_PHONE = ToolParam("phone", source="call_variable", value=CALLER_VARIABLE, required=False)


def build_tools(base_url: str, voice_key: str) -> tuple[ToolSpec, ...]:
    base = base_url.rstrip("/") + "/v1/voice/tools"
    headers = {KEY_HEADER: voice_key}
    return (
        ToolSpec(
            name="lookup_customer",
            description=(
                "Look up the person calling: whether they are a known customer and their saved "
                "addresses. Call this once, right after your greeting, before taking an order."
            ),
            url=f"{base}/lookup_customer",
            body=(_PHONE,),
            secret_headers=headers,
        ),
        ToolSpec(
            name="save_address",
            description=(
                "Save a delivery address for the caller. Use it when a new caller gives an "
                "address, or a known caller gives a different one."
            ),
            url=f"{base}/save_address",
            body=(
                _PHONE,
                ToolParam(
                    "address", description="The full delivery address, as the caller said it."
                ),
                ToolParam(
                    "name", description="The caller's name, if they gave it.", required=False
                ),
                ToolParam(
                    "make_preferred",
                    type="boolean",
                    description="True if the caller wants this to be their usual address.",
                    required=False,
                ),
                ToolParam(
                    "contact_phone",
                    description="A mobile number the caller gave, only if theirs was unavailable.",
                    required=False,
                ),
            ),
            secret_headers=headers,
        ),
        ToolSpec(
            name="place_order",
            description=(
                "Send the caller's confirmed order to the restaurant. Call it only after the "
                "caller has clearly agreed to the order you read back. The restaurant still has "
                "to accept it, so never tell the caller it is confirmed."
            ),
            url=f"{base}/place_order",
            body=(
                _PHONE,
                ToolParam("fulfillment", description="Either 'pickup' or 'delivery'."),
                ToolParam(
                    "items",
                    type="array",
                    description="The items ordered, using item_id values from the menu.",
                    items=ToolParam(
                        "item",
                        type="object",
                        properties=(
                            ToolParam("item_id", description="The item_id from the menu."),
                            ToolParam("qty", type="integer", description="How many."),
                            ToolParam(
                                "modifier_ids",
                                type="array",
                                description="Chosen modifier_id values, if the item has options.",
                                required=False,
                                items=ToolParam(
                                    "modifier_id", description="A modifier_id from the menu."
                                ),
                            ),
                        ),
                    ),
                ),
                ToolParam(
                    "address_id",
                    description="For delivery: the address_id of a saved address the caller chose.",
                    required=False,
                ),
                ToolParam(
                    "address",
                    description="For delivery: a new address the caller gave, if not a saved one.",
                    required=False,
                ),
                ToolParam(
                    "name", description="The caller's name, if they gave it.", required=False
                ),
                ToolParam(
                    "contact_phone",
                    description="A mobile number the caller gave, only if theirs was unavailable.",
                    required=False,
                ),
            ),
            secret_headers=headers,
        ),
    )
