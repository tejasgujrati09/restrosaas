"""A scripted stand-in for the extraction model, so no test calls a real service."""

from __future__ import annotations

from typing import Any

from app.domains.menu.extract.provider import PageInput, ProviderError, ProviderResult, Usage


def item(
    name: str,
    price: str | None = "100",
    *,
    options: list[tuple[str | None, str | None]] | None = None,
    veg: bool | None = True,
    liquor: bool | None = False,
    confidence: str = "high",
    addons: list[str] | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    prices = options if options is not None else [(None, price)]
    return {
        "name": name,
        "description": description,
        "price_options": [{"label": lb, "price": p} for lb, p in prices],
        "veg": veg,
        "is_liquor": liquor,
        "addons": addons or [],
        "confidence": confidence,
        "source_text": None,
    }


def page(
    *categories: tuple[str | None, list[dict[str, Any]]], is_menu: bool = True
) -> dict[str, Any]:
    return {
        "is_menu": is_menu,
        "categories": [{"name": n, "items": items} for n, items in categories],
    }


class FakeProvider:
    """`script` maps page number to a result: a dict (success) or an exception to raise. A list
    is consumed one entry per call, so a page can fail and then succeed."""

    name = "fake"

    def __init__(self, script: dict[int, Any]) -> None:
        self.script = script
        self.calls: list[int] = []
        self.inputs: dict[int, PageInput] = {}

    async def extract_page(self, page: PageInput) -> ProviderResult:
        self.calls.append(page.number)
        self.inputs[page.number] = page
        outcome = self.script[page.number]
        if isinstance(outcome, list):
            outcome = outcome.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return ProviderResult(outcome, Usage(requests=1, prompt_tokens=1000, completion_tokens=200))

    async def aclose(self) -> None:
        return None


def transient() -> ProviderError:
    return ProviderError("The model timed out.", retryable=True)


def fatal() -> ProviderError:
    return ProviderError("The model service rejected the request (401).", retryable=False)
