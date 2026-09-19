"""In-memory `VoicePlatform` for tests. Never makes a network call. Fixture data only."""

from __future__ import annotations

import itertools

from app.domains.voice.platform import AgentSpec, PhoneNumber, VoicePlatformError


class FakeVoicePlatform:
    def __init__(self, numbers: list[tuple[int, str]] | None = None) -> None:
        self.agents: dict[str, AgentSpec] = {}
        self.numbers: dict[int, PhoneNumber] = {
            plan: PhoneNumber(plan, number, None)
            for plan, number in (numbers or [(1001, "+910000000001")])
        }
        self.caller_mapped: set[int] = set()
        self.calls: list[str] = []
        self.call_callers: dict[str, str] = {}
        self._ids = itertools.count(1)
        self._fail: dict[str, VoicePlatformError] = {}

    def fail_next(self, op: str, *, retryable: bool = False) -> None:
        self._fail[op] = VoicePlatformError(op, "injected failure", status=500, retryable=retryable)

    def _enter(self, op: str) -> None:
        self.calls.append(op)
        if op in self._fail:
            raise self._fail.pop(op)

    async def create_agent(self, spec: AgentSpec) -> str:
        self._enter("create_agent")
        agent_id = f"fake-agent-{next(self._ids)}"
        self.agents[agent_id] = spec
        return agent_id

    async def update_agent(self, agent_id: str, spec: AgentSpec) -> None:
        self._enter("update_agent")
        if agent_id not in self.agents:
            raise VoicePlatformError("update_agent", "no such agent", status=404)
        self.agents[agent_id] = spec

    async def delete_agent(self, agent_id: str) -> None:
        self._enter("delete_agent")
        self.agents.pop(agent_id, None)

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

    async def pass_caller_to_agent(self, plan_id: int) -> None:
        self._enter("pass_caller_to_agent")
        self.caller_mapped.add(plan_id)

    async def caller_of_call(self, call_id: str) -> str | None:
        self._enter("caller_of_call")
        return self.call_callers.get(call_id)
