"""The DM provider interface: conversations that stream events back, and stateless side and vision calls (spec §5.2,
§6.1)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from delve.domain.backends import ProviderCapabilities
from delve.domain.settings import BackendChoice


@dataclass(frozen=True)
class TextDelta:
    """A piece of the DM's narration, in the order it streams."""

    text: str


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    args: dict


@dataclass(frozen=True)
class ToolResult:
    """The answer to the `ToolCall` with the same id."""

    id: str
    ok: bool
    content: Any


@dataclass(frozen=True)
class Usage:
    """What a reply or a call used. `cost_usd` is this reply's own cost (never a running total), None when unknown."""

    input_tokens: int
    output_tokens: int
    cost_usd: float | None


@dataclass(frozen=True)
class TurnEnd:
    """The last event of every `send`: the DM's reply is complete, failed or was cancelled."""

    reason: Literal["done", "error", "cancelled"]


@dataclass(frozen=True)
class DMError:
    """Why the DM didn't answer. `retryable` when trying the beat again may get an answer (the usage limit, a crash),
    and `resets_at` when the usage limit ends (ISO 8601), if known. `detail` is for the DM log only, such as the stderr
    tail of a crashed `claude`."""

    message: str
    retryable: bool
    detail: str = ""
    resets_at: str | None = None


DMEvent = TextDelta | ToolCall | ToolResult | Usage | TurnEnd | DMError


@dataclass(frozen=True)
class ConversationSpec:
    """What a DM conversation is opened for; `resume_id` picks up an earlier conversation."""

    campaign_id: str
    system_prompt: str
    choice: BackendChoice
    resume_id: str | None = None


class DMConversation(Protocol):
    id: str

    def send(self, text: str) -> AsyncIterator[DMEvent]:
        """Send a beat and stream the DM's reply. The stream always ends with exactly one `TurnEnd`.

        Implementations are async generators (`async def send` with `yield`), used as `async for`.
        """
        ...

    async def cancel(self) -> None:
        """Stop the reply being streamed; the stream ends with `TurnEnd("cancelled")`."""
        ...

    async def close(self) -> None: ...


class DMProvider(Protocol):
    capabilities: ProviderCapabilities

    async def open(self, spec: ConversationSpec) -> DMConversation: ...

    async def side_call(
        self,
        prompt: str,
        choice: BackendChoice,
        *,
        timeout: float | None = None,
        on_usage: Callable[[Usage], None] | None = None,
    ) -> str:
        """A stateless call with no tools: translation, Ask the DM, suggestions, image-prompt rewrites, and each step
        of a conversion. `timeout` is how many seconds to wait for the answer; None is the provider's own limit.
        `on_usage` hears the call's usage and cost, when the provider knows them."""
        ...

    async def vision_call(
        self,
        prompt: str,
        image: bytes,
        media_type: str,
        choice: BackendChoice,
        *,
        timeout: float | None = None,
        on_usage: Callable[[Usage], None] | None = None,
    ) -> str:
        """A stateless call with no tools that sees `image` (a PNG, JPEG, WebP or GIF of `media_type`) with `prompt`:
        reading a world map's picture, and drawing a dungeon map from a book's map page. `timeout` and `on_usage` as
        `side_call`."""
        ...
