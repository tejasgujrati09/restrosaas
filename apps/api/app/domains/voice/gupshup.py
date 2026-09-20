"""Gupshup VoiceAI adapter for `VoicePlatform`. The only place that knows Gupshup's JSON.

Request shapes were checked against a running platform (docs/DECISIONS.md "Voice ordering
agent"). Every call is logged the same way (operation, duration, outcome) so providers can
be compared on real numbers later; credentials never reach a log line or an error message.
"""

from __future__ import annotations

import json
import time
from typing import Any

import httpx
import structlog

from app.domains.voice.platform import (
    AgentSpec,
    PhoneNumber,
    ToolParam,
    ToolSpec,
    VoicePlatformError,
)

logger = structlog.get_logger()

# How the number maps a call onto the agent's variables. `${...}` are SR's own placeholders
# for the call's session, the caller and the dialed number.
_SIP_METADATA = json.dumps(
    {
        "session_id": "${SESSION_ID_SYS}",
        "caller": "${app_params0}",
        "destination_number": "${IVR_DISP_NUM_SYS}",
    },
    indent=2,
)


def _schema_json(p: ToolParam) -> dict[str, Any]:
    """A nested schema node: nameless when it is the `items` of an array."""
    node: dict[str, Any] = {"type": p.type, "description": p.description}
    if p.properties:
        node["properties"] = [_param_json(c) for c in p.properties]
    if p.items is not None:
        node["items"] = _schema_json(p.items)
    return node


def _param_json(p: ToolParam) -> dict[str, Any]:
    node = _schema_json(p)
    node["name"] = p.name
    node["required"] = p.required
    if p.source == "call_variable":
        node["value_type"] = "dynamic"
        node["variable"] = "{{" + (p.value or "") + "}}"
    elif p.source == "fixed":
        node["value_type"] = "static"
        node["value"] = p.value or ""
    else:
        node["value_type"] = "llm_prompt"
    return node


def _tool_json(t: ToolSpec) -> dict[str, Any]:
    return {
        "name": t.name,
        "description": t.description,
        "webhook_url": t.url,
        "method": t.method,
        "content_type": "json",
        "path_params": [],
        "query_params": [_param_json(p) for p in t.query],
        "body_params": [_param_json(p) for p in t.body],
        "headers": [{"key": k, "value": v, "is_secret": True} for k, v in t.secret_headers.items()],
        "response_mappings": [],
        "options": {
            "timeout_seconds": t.timeout_seconds,
            "disable_interruptions": False,
            "execution_mode": "immediate",
            "force_pre_speech": False,
            "tool_call_sound": "none",
            "error_handling": "auto",
        },
    }


def agent_json(spec: AgentSpec) -> dict[str, Any]:
    return {
        "name": spec.name,
        "description": spec.description,
        "system_prompt": spec.system_prompt,
        "first_message": spec.first_message,
        "text_only": False,
        "is_active": spec.active,
        "dynamic_variables_schema": [
            {"name": v, "sample_value": "", "sip_header": f"sip_h_X-{v}"}
            for v in spec.call_variables
        ],
        "custom_tools": [_tool_json(t) for t in spec.tools],
    }


class GupshupPlatform:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout_seconds: float = 20.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"X-API-Key": api_key},
            timeout=timeout_seconds,
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _call(
        self, op: str, method: str, path: str, *, json_body: dict[str, Any] | None = None
    ) -> Any:
        started = time.perf_counter()
        status: int | None = None
        try:
            response = await self._client.request(method, path, json=json_body)
            status = response.status_code
            if status >= 400:
                raise VoicePlatformError(
                    op,
                    f"HTTP {status}: {_detail(response)}",
                    status=status,
                    retryable=status >= 500 or status == 429,
                )
            return response.json() if response.content else None
        except httpx.TimeoutException as exc:
            raise VoicePlatformError(op, "timed out", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise VoicePlatformError(
                op, f"network error: {type(exc).__name__}", retryable=True
            ) from exc
        except ValueError as exc:
            raise VoicePlatformError(op, "response was not valid JSON", status=status) from exc
        finally:
            logger.info(
                "voice_platform_call",
                provider="gupshup",
                op=op,
                status=status,
                duration_ms=round((time.perf_counter() - started) * 1000),
            )

    async def create_agent(self, spec: AgentSpec) -> str:
        data = await self._call(
            "create_agent", "POST", "/api/v1/agents", json_body=agent_json(spec)
        )
        agent_id = data.get("id") if isinstance(data, dict) else None
        if not isinstance(agent_id, str) or not agent_id:
            raise VoicePlatformError("create_agent", "response had no agent id")
        return agent_id

    async def update_agent(self, agent_id: str, spec: AgentSpec) -> None:
        await self._call(
            "update_agent", "PUT", f"/api/v1/agents/{agent_id}", json_body=agent_json(spec)
        )

    async def set_agent_active(self, agent_id: str, active: bool) -> None:
        await self._call(
            "set_agent_active",
            "PUT",
            f"/api/v1/agents/{agent_id}",
            json_body={"is_active": active},
        )

    async def delete_agent(self, agent_id: str) -> None:
        await self._call("delete_agent", "DELETE", f"/api/v1/agents/{agent_id}")

    async def list_numbers(self) -> list[PhoneNumber]:
        numbers = await self._call("list_numbers", "GET", "/api/v1/sr/numbers")
        links = await self._call("list_agent_links", "GET", "/api/v1/sr/numbers/agent-links")
        linked: dict[int, str] = {}
        for link in (links or {}).get("links", []):
            linked[int(link["plan_id"])] = str(link["agent_id"])
        result: list[PhoneNumber] = []
        for row in (numbers or {}).get("success", []):
            plan_id = int(row["user_plan_id"])
            result.append(
                PhoneNumber(
                    plan_id=plan_id,
                    number=str(row.get("phone_number") or row.get("number")),
                    linked_agent_id=linked.get(plan_id),
                )
            )
        return result

    async def link_number(self, plan_id: int, agent_id: str, agent_name: str, number: str) -> None:
        await self._call(
            "link_number",
            "POST",
            "/api/v1/sr/numbers/link-agent",
            json_body={
                "plan_id": plan_id,
                "agent_id": agent_id,
                "agent_name": agent_name,
                "phone_number": number,
            },
        )

    async def pass_caller_to_agent(self, plan_id: int) -> None:
        await self._call(
            "pass_caller_to_agent",
            "POST",
            "/api/v1/sr/numbers/metadata",
            json_body={"plan_id": plan_id, "sip_metadata": _SIP_METADATA},
        )

    async def caller_of_call(self, call_id: str) -> str | None:
        data = await self._call("caller_of_call", "GET", f"/api/v1/calls/{call_id}")
        caller = data.get("from_number") if isinstance(data, dict) else None
        return caller if isinstance(caller, str) and caller else None


def _detail(response: httpx.Response) -> str:
    """A short, safe description of an error body."""
    try:
        body = response.json()
    except ValueError:
        return response.text[:200]
    if isinstance(body, dict) and isinstance(body.get("detail"), str):
        return str(body["detail"])[:200]
    return "error"
