"""OpenAI chat-completions adapter for `MenuExtractionProvider` (structured JSON output).

Uses httpx directly, so there is no extra SDK dependency. Works with any server that speaks the
same protocol by changing `openai_base_url`."""

from __future__ import annotations

import base64
import json

import httpx

from app.domains.menu.extract.prompt import SYSTEM_PROMPT
from app.domains.menu.extract.provider import (
    PageInput,
    ProviderError,
    ProviderResult,
    Usage,
)
from app.domains.menu.extract.schema import page_json_schema


class OpenAIProvider:
    name = "openai"

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str,
        model: str,
        timeout: float,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._model = model
        self._client = client or httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    def _user_content(self, page: PageInput) -> list[dict[str, object]]:
        if page.text is not None:
            return [{"type": "text", "text": f"Menu page text ({page.label}):\n\n{page.text}"}]
        assert page.image is not None
        encoded = base64.b64encode(page.image).decode()
        return [
            {"type": "text", "text": f"Menu page image ({page.label})."},
            {
                "type": "image_url",
                "image_url": {"url": f"data:{page.image_mime};base64,{encoded}", "detail": "high"},
            },
        ]

    async def extract_page(self, page: PageInput) -> ProviderResult:
        payload = {
            "model": self._model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": self._user_content(page)},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "menu_page", "strict": True, "schema": page_json_schema()},
            },
        }
        try:
            response = await self._client.post("/chat/completions", json=payload)
        except httpx.TimeoutException as exc:
            raise ProviderError("The model timed out.", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise ProviderError("The model could not be reached.", retryable=True) from exc

        if response.status_code == 429 or response.status_code >= 500:
            retry_after = _retry_after(response)
            raise ProviderError(
                f"The model service is busy or unavailable ({response.status_code}).",
                retryable=True,
                retry_after=retry_after,
            )
        if response.status_code >= 400:
            raise ProviderError(
                f"The model service rejected the request ({response.status_code}).",
                retryable=False,
            )
        try:
            body = response.json()
            message = body["choices"][0]["message"]
            usage = body.get("usage") or {}
            if message.get("refusal"):
                raise ProviderError("The model declined to read this page.", retryable=False)
            data = json.loads(message["content"])
        except ProviderError:
            raise
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ProviderError("The model returned an unreadable answer.", retryable=True) from exc
        if not isinstance(data, dict):
            raise ProviderError("The model returned an unreadable answer.", retryable=True)
        return ProviderResult(
            data=data,
            usage=Usage(
                requests=1,
                prompt_tokens=int(usage.get("prompt_tokens") or 0),
                completion_tokens=int(usage.get("completion_tokens") or 0),
            ),
        )


def _retry_after(response: httpx.Response) -> float | None:
    raw = response.headers.get("retry-after")
    try:
        return min(float(raw), 60.0) if raw else None
    except ValueError:
        return None
