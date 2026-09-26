"""What a menu-reading model may return, and what the owner edits before import.

`PageExtraction` is the strict shape of one page's model output; anything outside it is dropped.
`DraftRow` is one CSV row in editable form. The model never produces CSV and never reaches the
database: rows are built from this schema, checked by the existing CSV validator, and only then
applied by the existing import (docs/DECISIONS.md "Menu import from PDF or photos")."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Confidence = Literal["high", "medium", "low"]


class PriceOption(BaseModel):
    model_config = ConfigDict(extra="ignore")

    label: str | None = None
    # Rupees as printed, e.g. "120" or "120.50". A string so no float ever touches money.
    price: str | None = None


class ExtractedItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    description: str | None = None
    price_options: list[PriceOption] = Field(default_factory=list)
    veg: bool | None = None
    is_liquor: bool | None = None
    addons: list[str] = Field(default_factory=list)
    confidence: Confidence = "medium"
    source_text: str | None = None


class ExtractedCategory(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str | None = None
    items: list[ExtractedItem] = Field(default_factory=list)


class PageExtraction(BaseModel):
    model_config = ConfigDict(extra="ignore")

    is_menu: bool = True
    categories: list[ExtractedCategory] = Field(default_factory=list)


# The same shape as a JSON Schema in OpenAI "strict" form (every property required, nullable
# where optional, no extra properties). Kept beside the models so the two change together.
def page_json_schema() -> dict[str, Any]:
    nullable_str: dict[str, Any] = {"type": ["string", "null"]}
    option = {
        "type": "object",
        "additionalProperties": False,
        "required": ["label", "price"],
        "properties": {"label": nullable_str, "price": nullable_str},
    }
    item = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "name",
            "description",
            "price_options",
            "veg",
            "is_liquor",
            "addons",
            "confidence",
            "source_text",
        ],
        "properties": {
            "name": {"type": "string"},
            "description": nullable_str,
            "price_options": {"type": "array", "items": option},
            "veg": {"type": ["boolean", "null"]},
            "is_liquor": {"type": ["boolean", "null"]},
            "addons": {"type": "array", "items": {"type": "string"}},
            "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
            "source_text": nullable_str,
        },
    }
    category = {
        "type": "object",
        "additionalProperties": False,
        "required": ["name", "items"],
        "properties": {"name": nullable_str, "items": {"type": "array", "items": item}},
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["is_menu", "categories"],
        "properties": {
            "is_menu": {"type": "boolean"},
            "categories": {"type": "array", "items": category},
        },
    }


class DraftRow(BaseModel):
    """One row of the CSV the owner will import. `price` is rupees text and may be empty until
    the owner fills it. `notes` and `confidence` are for the owner's review only."""

    model_config = ConfigDict(extra="ignore")

    category: str = ""
    item: str = ""
    description: str | None = None
    price: str = ""
    veg: bool | None = None
    is_liquor: bool = False
    available: bool = True
    # Overrides the default tax class for this row when set.
    tax_class: str | None = None
    skip: bool = False
    confidence: Confidence = "high"
    source_page: int | None = None
    notes: list[str] = Field(default_factory=list)


class Defaults(BaseModel):
    model_config = ConfigDict(extra="ignore")

    food_tax_class: str | None = None
    liquor_tax_class: str | None = None
