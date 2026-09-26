"""The seam between the import flow and whichever vision/LLM service reads the menu.

A provider turns one page (text or image) into the JSON described by `schema.page_json_schema()`.
Everything else - retries, merging, validation, CSV, the database - is provider-independent and
lives elsewhere. To add a provider, implement `MenuExtractionProvider` and register it in
`factory.py`."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class PageInput:
    """`text` is set for a page with a real text layer; `image` (JPEG or PNG bytes) otherwise."""

    number: int
    label: str
    text: str | None = None
    image: bytes | None = None
    image_mime: str = "image/jpeg"


@dataclass(frozen=True)
class Usage:
    requests: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0


@dataclass(frozen=True)
class ProviderResult:
    data: dict[str, Any]
    usage: Usage


class ProviderError(Exception):
    """A failed call. `retryable` says whether trying the same page again can help (timeout,
    rate limit, provider 5xx) or not (bad key, refused content)."""

    def __init__(self, message: str, *, retryable: bool, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.retry_after = retry_after


class MenuExtractionProvider(Protocol):
    name: str

    async def extract_page(self, page: PageInput) -> ProviderResult: ...

    async def aclose(self) -> None: ...
