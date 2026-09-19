"""The boundary to whichever voice platform runs the phone call.

Nothing outside `app/domains/voice/gupshup.py` may import an HTTP client for a vendor or know
a vendor's JSON. Business code builds an `AgentSpec` in these terms and calls a
`VoicePlatform`; swapping vendors means one new adapter file and a config change, never
edits to the provisioning or tool code (docs/DECISIONS.md "Voice ordering agent").
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol

ParamType = Literal["string", "number", "integer", "boolean", "object", "array"]
ParamSource = Literal["model", "call_variable", "fixed"]


@dataclass(frozen=True)
class ToolParam:
    """One parameter of a tool the agent can call.

    `source` says who supplies the value: the language model (`model`), a per-call
    variable such as the caller's number (`call_variable`, `value` is the variable's
    name), or a constant (`fixed`, `value` is the constant). The caller's phone must
    always be a `call_variable`, never `model`: the model must not choose who is calling.
    """

    name: str
    type: ParamType = "string"
    description: str = ""
    required: bool = True
    source: ParamSource = "model"
    value: str | None = None
    properties: tuple[ToolParam, ...] = ()
    items: ToolParam | None = None


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    url: str
    method: Literal["GET", "POST"] = "POST"
    query: tuple[ToolParam, ...] = ()
    body: tuple[ToolParam, ...] = ()
    # Sent on every call and stored by the platform as secrets.
    secret_headers: dict[str, str] = field(default_factory=dict)
    timeout_seconds: int = 15


@dataclass(frozen=True)
class AgentSpec:
    name: str
    description: str
    system_prompt: str
    first_message: str
    tools: tuple[ToolSpec, ...] = ()
    # Per-call variables the platform fills in (for example "caller").
    call_variables: tuple[str, ...] = ()
    active: bool = True


@dataclass(frozen=True)
class PhoneNumber:
    plan_id: int
    number: str
    linked_agent_id: str | None


class VoicePlatformError(Exception):
    """A call to the platform failed. `detail` never contains credentials."""

    def __init__(
        self, op: str, message: str, *, status: int | None = None, retryable: bool = False
    ) -> None:
        self.op = op
        self.status = status
        self.retryable = retryable
        super().__init__(f"{op}: {message}")


class VoicePlatform(Protocol):
    async def create_agent(self, spec: AgentSpec) -> str:
        """Create the agent and return its platform id."""
        ...

    async def update_agent(self, agent_id: str, spec: AgentSpec) -> None:
        """Replace the agent's prompt, tools and variables (used to re-sync the menu)."""
        ...

    async def delete_agent(self, agent_id: str) -> None: ...

    async def list_numbers(self) -> list[PhoneNumber]:
        """Every phone number on the account, with the agent it is linked to, if any."""
        ...

    async def link_number(
        self, plan_id: int, agent_id: str, agent_name: str, number: str
    ) -> None: ...

    async def pass_caller_to_agent(self, plan_id: int) -> None:
        """Make the number send the caller's and the dialed number to the agent as its
        `caller` call variable, so tools can be bound to it."""
        ...

    async def caller_of_call(self, call_id: str) -> str | None:
        """The caller's number as the platform recorded it. A fallback for when the call
        variable did not arrive."""
        ...
