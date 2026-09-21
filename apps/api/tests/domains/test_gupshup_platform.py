"""The Gupshup adapter against a mocked transport: request shapes, error mapping and logging.
No network. The API key below is a fixture, not a real credential."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from structlog.testing import capture_logs

from app.domains.voice.gupshup import GupshupPlatform, agent_json
from app.domains.voice.platform import AgentSpec, ToolParam, ToolSpec, VoicePlatformError

KEY = "fixture-key-not-real"


def _spec() -> AgentSpec:
    tool = ToolSpec(
        name="place_order",
        description="Place the order once the caller has confirmed it.",
        url="https://tools.example.test/v1/voice/tools/place_order",
        method="POST",
        body=(
            ToolParam("phone", source="call_variable", value="caller"),
            ToolParam("fulfillment", description="pickup or delivery"),
            ToolParam(
                "items",
                type="array",
                items=ToolParam(
                    "item",
                    type="object",
                    properties=(
                        ToolParam("item_id", description="id from the menu"),
                        ToolParam("qty", type="integer"),
                    ),
                ),
            ),
        ),
        secret_headers={"X-Voice-Key": "fixture-secret"},
    )
    return AgentSpec(
        name="Test Kitchen",
        description="fixture",
        system_prompt="You take orders.",
        first_message="Hello",
        tools=(tool,),
        call_variables=("caller",),
    )


def _platform(handler: Any) -> GupshupPlatform:
    return GupshupPlatform("http://gupshup.test", KEY, transport=httpx.MockTransport(handler))


def test_agent_json_binds_the_caller_to_a_variable_and_marks_secrets() -> None:
    body = agent_json(_spec())
    assert body["dynamic_variables_schema"] == [
        {"name": "caller", "sample_value": "", "sip_header": "sip_h_X-caller"}
    ]
    tool = body["custom_tools"][0]
    assert tool["headers"] == [{"key": "X-Voice-Key", "value": "fixture-secret", "is_secret": True}]
    phone, fulfillment, items = tool["body_params"]
    assert (phone["value_type"], phone["variable"]) == ("dynamic", "{{caller}}")
    assert fulfillment["value_type"] == "llm_prompt"
    assert items["type"] == "array"
    assert items["items"]["type"] == "object"
    assert [p["name"] for p in items["items"]["properties"]] == ["item_id", "qty"]
    assert body["text_only"] is False


async def test_create_agent_sends_key_and_returns_id() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["key"] = request.headers.get("X-API-Key")
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"id": "agent-123"})

    platform = _platform(handler)
    assert await platform.create_agent(_spec()) == "agent-123"
    assert seen["key"] == KEY
    assert seen["url"] == "http://gupshup.test/api/v1/agents"
    assert seen["body"]["name"] == "Test Kitchen"
    await platform.aclose()


@pytest.mark.parametrize(
    ("status", "retryable"), [(500, True), (429, True), (401, False), (422, False)]
)
async def test_http_errors_map_to_platform_errors_without_leaking_the_key(
    status: int, retryable: bool
) -> None:
    platform = _platform(lambda r: httpx.Response(status, json={"detail": "nope"}))
    with pytest.raises(VoicePlatformError) as caught:
        await platform.create_agent(_spec())
    assert caught.value.status == status
    assert caught.value.retryable is retryable
    assert KEY not in str(caught.value)
    await platform.aclose()


async def test_timeout_is_retryable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    platform = _platform(handler)
    with pytest.raises(VoicePlatformError) as caught:
        await platform.delete_agent("agent-1")
    assert caught.value.retryable is True
    await platform.aclose()


async def test_create_agent_without_an_id_is_an_error() -> None:
    platform = _platform(lambda r: httpx.Response(200, json={"name": "x"}))
    with pytest.raises(VoicePlatformError):
        await platform.create_agent(_spec())
    await platform.aclose()


async def test_list_numbers_joins_links_by_plan() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/agent-links"):
            return httpx.Response(
                200, json={"success": True, "links": [{"plan_id": 2, "agent_id": "agent-9"}]}
            )
        return httpx.Response(
            200,
            json={
                "success": [
                    {"user_plan_id": 1, "phone_number": "+910000000001"},
                    {"user_plan_id": 2, "phone_number": "+910000000002"},
                ]
            },
        )

    platform = _platform(handler)
    numbers = await platform.list_numbers()
    assert [(n.plan_id, n.number, n.linked_agent_id) for n in numbers] == [
        (1, "+910000000001", None),
        (2, "+910000000002", "agent-9"),
    ]
    await platform.aclose()


async def test_link_number_and_caller_mapping_requests() -> None:
    requests: list[tuple[str, dict[str, Any]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.url.path, json.loads(request.content)))
        return httpx.Response(200)

    platform = _platform(handler)
    await platform.link_number(7, "agent-1", "Test Kitchen", "+910000000007")
    await platform.pass_caller_to_agent(7, "agent-1", "+910000000007")
    assert requests[0] == (
        "/api/v1/sr/numbers/link-agent",
        {
            "plan_id": 7,
            "agent_id": "agent-1",
            "agent_name": "Test Kitchen",
            "phone_number": "+910000000007",
        },
    )
    path, body = requests[1]
    assert path == "/api/v1/sr/ivr/setup"
    assert (body["plan_id"], body["agent_id"], body["call_type"]) == (7, "agent-1", "inbound")
    assert body["phone_number"] == "+910000000007"
    assert json.loads(body["sip_metadata"])["caller"] == "${app_params0}"
    await platform.aclose()


async def test_caller_of_call() -> None:
    platform = _platform(
        lambda r: (
            httpx.Response(200, json={"from_number": "+919999900009"})
            if r.url.path.endswith("/call-1")
            else httpx.Response(200, json={"from_number": None})
        )
    )
    assert await platform.caller_of_call("call-1") == "+919999900009"
    assert await platform.caller_of_call("call-2") is None
    await platform.aclose()


async def test_every_call_is_logged_with_duration_and_status_and_no_secret() -> None:
    platform = _platform(lambda r: httpx.Response(200, json={"id": "a"}))
    with capture_logs() as logs:
        await platform.create_agent(_spec())
    (entry,) = [e for e in logs if e["event"] == "voice_platform_call"]
    assert entry["op"] == "create_agent"
    assert entry["provider"] == "gupshup"
    assert entry["status"] == 200
    assert isinstance(entry["duration_ms"], int)
    assert KEY not in json.dumps(logs)
    await platform.aclose()


async def test_set_agent_active_sends_only_the_flag() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={})

    platform = _platform(handler)
    await platform.set_agent_active("agent-5", False)
    assert seen == {"method": "PUT", "path": "/api/v1/agents/agent-5", "body": {"is_active": False}}
    await platform.aclose()


async def test_find_agent_matches_only_the_exact_name() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(
            200,
            json={
                "items": [
                    {"id": "a-1", "name": "Test Kitchen phone orders [abcd1234] (copy)"},
                    {"id": "a-2", "name": "Test Kitchen phone orders [abcd1234]"},
                ]
            },
        )

    platform = _platform(handler)
    assert await platform.find_agent_by_name("Test Kitchen phone orders [abcd1234]") == "a-2"
    assert "search=Test%20Kitchen" in seen["url"] and "page_size=100" in seen["url"]
    assert await platform.find_agent_by_name("Somebody else") is None
    await platform.aclose()


async def test_agent_is_active_reads_the_flag_and_treats_404_as_missing() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/gone"):
            return httpx.Response(404, json={"detail": "not found"})
        return httpx.Response(
            200, json={"id": "a-1", "is_active": request.url.path.endswith("/on")}
        )

    platform = _platform(handler)
    assert await platform.agent_is_active("on") is True
    assert await platform.agent_is_active("off") is False
    assert await platform.agent_is_active("gone") is None
    await platform.aclose()


async def test_agent_is_active_still_raises_for_other_errors() -> None:
    platform = _platform(lambda r: httpx.Response(500, json={"detail": "boom"}))
    with pytest.raises(VoicePlatformError) as caught:
        await platform.agent_is_active("a-1")
    assert caught.value.retryable is True
    await platform.aclose()
