"""In-memory `VoicePlatform` for tests. Never makes a network call. Fixture data only."""

from __future__ import annotations

import itertools
from collections.abc import Awaitable, Callable

from app.domains.voice.platform import AgentSpec, PhoneNumber, VoicePlatformError


class FakeVoicePlatform:
    def __init__(self, numbers: list[tuple[int, str]] | None = None) -> None:
        self.agents: dict[str, AgentSpec] = {}
        self.active: dict[str, bool] = {}
        self.numbers: dict[int, PhoneNumber] = {
            plan: PhoneNumber(plan, number, None)
            for plan, number in (numbers or [(1001, "+910000000001")])
        }
        self.caller_mapped: set[int] = set()
        self.calls: list[str] = []
        self.call_callers: dict[str, str] = {}
        self._ids = itertools.count(1)
        self._fail: dict[str, VoicePlatformError] = {}
        self._lose: set[str] = set()
        # Awaited once after the named op has taken effect (to act "in the middle" of a job).
        self.hooks: dict[str, Callable[[], Awaitable[None]]] = {}

    def fail_next(self, op: str, *, retryable: bool = False) -> None:
        self._fail[op] = VoicePlatformError(op, "injected failure", status=500, retryable=retryable)

    def lose_response(self, op: str) -> None:
        """The next `op` takes effect on the platform, but the caller sees a timeout."""
        self._lose.add(op)

    async def _after(self, op: str) -> None:
        if op in self._lose:
            self._lose.discard(op)
            raise VoicePlatformError(op, "timed out", retryable=True)
        hook = self.hooks.pop(op, None)
        if hook is not None:
            await hook()

    def _enter(self, op: str) -> None:
        self.calls.append(op)
        if op in self._fail:
            raise self._fail.pop(op)

    async def create_agent(self, spec: AgentSpec) -> str:
        self._enter("create_agent")
        agent_id = f"fake-agent-{next(self._ids)}"
        self.agents[agent_id] = spec
        self.active[agent_id] = spec.active
        await self._after("create_agent")
        return agent_id

    async def update_agent(self, agent_id: str, spec: AgentSpec) -> None:
        self._enter("update_agent")
        if agent_id not in self.agents:
            raise VoicePlatformError("update_agent", "no such agent", status=404)
        self.agents[agent_id] = spec
        self.active[agent_id] = spec.active  # the real adapter sends is_active on every update
        await self._after("update_agent")

    async def set_agent_active(self, agent_id: str, active: bool) -> None:
        self._enter("set_agent_active")
        if agent_id not in self.agents:
            raise VoicePlatformError("set_agent_active", "no such agent", status=404)
        self.active[agent_id] = active
        await self._after("set_agent_active")

    async def delete_agent(self, agent_id: str) -> None:
        self._enter("delete_agent")
        self.agents.pop(agent_id, None)
        self.active.pop(agent_id, None)

    async def find_agent_by_name(self, name: str) -> str | None:
        self._enter("find_agent")
        return next((i for i, spec in self.agents.items() if spec.name == name), None)

    async def agent_is_active(self, agent_id: str) -> bool | None:
        self._enter("get_agent")
        return self.active.get(agent_id) if agent_id in self.agents else None

    async def list_numbers(self) -> list[PhoneNumber]:
        self._enter("list_numbers")
        return list(self.numbers.values())

    async def link_number(self, plan_id: int, agent_id: str, agent_name: str, number: str) -> None:
        self._enter("link_number")
        current = self.numbers.get(plan_id)
        if current is None or current.number != number:
            raise VoicePlatformError("link_number", "unknown number", status=404)
        if current.linked_agent_id is not None:
            raise VoicePlatformError("link_number", "number already linked", status=409)
        self.numbers[plan_id] = PhoneNumber(plan_id, number, agent_id)
        await self._after("link_number")

    async def pass_caller_to_agent(self, plan_id: int, agent_id: str, number: str) -> None:
        self._enter("pass_caller_to_agent")
        current = self.numbers.get(plan_id)
        if current is None or current.linked_agent_id != agent_id:
            # The real platform: "No IVR allocation found for this plan_id" until it is linked.
            raise VoicePlatformError("pass_caller_to_agent", "number not linked", status=404)
        self.caller_mapped.add(plan_id)
        await self._after("pass_caller_to_agent")

    async def caller_of_call(self, call_id: str) -> str | None:
        self._enter("caller_of_call")
        return self.call_callers.get(call_id)
