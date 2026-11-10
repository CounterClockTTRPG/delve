"""A scripted DM for tests and development: each `send` replays the next entry of its script."""

from __future__ import annotations

import asyncio
import dataclasses
import json
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

from delve.dm.provider import (
    ConversationSpec,
    DMError,
    DMEvent,
    TextDelta,
    ToolCall,
    ToolResult,
    TurnEnd,
    Usage,
)
from delve.domain.backends import ProviderCapabilities
from delve.domain.settings import BackendChoice, Effort, Job

FAKE_DM_CAPABILITIES = ProviderCapabilities(
    id="fake",
    title="Fake DM (scripted)",
    jobs=frozenset({Job.DM, Job.SIDE, Job.TRANSLATION, Job.CONVERSION, Job.NOVEL}),
    models=("fake-large", "fake-small"),
    efforts=tuple(Effort),
    default_model="fake-large",
)

# The "type" each event has in a script fixture.
_EVENT_TYPES: dict[str, type] = {
    "text": TextDelta,
    "tool_call": ToolCall,
    "tool_result": ToolResult,
    "usage": Usage,
    "turn_end": TurnEnd,
    "error": DMError,
}
_TYPE_NAMES = {cls: name for name, cls in _EVENT_TYPES.items()}


def event_to_dict(event: DMEvent) -> dict[str, Any]:
    """The fixture form of an event, for example `{"type": "text", "text": "…"}`."""
    return {"type": _TYPE_NAMES[type(event)], **dataclasses.asdict(event)}


def event_from_dict(raw: dict[str, Any]) -> DMEvent:
    fields = dict(raw)
    kind = fields.pop("type")
    if kind not in _EVENT_TYPES:
        raise ValueError(f"unknown event type '{kind}'; known: {', '.join(_EVENT_TYPES)}")
    return _EVENT_TYPES[kind](**fields)


class FakeDM:
    """A DM provider that replays a script: one list of events per `send`, shared by all its conversations.

    An entry without a `TurnEnd` gets `TurnEnd("done")` appended. Once the script runs out, a send yields
    `DMError("script exhausted", False)` and `TurnEnd("error")`. Every text sent is recorded in `sent`.

    A side call answers from `side_answers` by its exact prompt, else with `side_handler(prompt)` (which may raise, as
    a failed call does), else with an echo. Every side prompt is recorded in `side_prompts`, and its `timeout` in
    `side_timeouts`.

    A vision call answers the same way, from `vision_answers` by its prompt, else with `vision_handler(prompt, image,
    media_type)`, else with an echo. Its prompts are recorded in `vision_prompts`, and its pictures as `(media type,
    size)` in `vision_images`.

    Given `side_usage`, every side and vision call reports it to its `on_usage`.
    """

    capabilities = FAKE_DM_CAPABILITIES

    def __init__(
        self,
        script: list[list[DMEvent]],
        side_answers: dict[str, str] | None = None,
        side_handler: Callable[[str], str] | None = None,
        vision_answers: dict[str, str] | None = None,
        vision_handler: Callable[[str, bytes, str], str] | None = None,
        side_usage: Usage | None = None,
    ) -> None:
        self._script = [list(entry) for entry in script]
        self._side_answers = dict(side_answers or {})
        self._side_handler = side_handler
        self._opened = 0
        self.sent: list[str] = []
        self.side_prompts: list[str] = []
        self.side_timeouts: list[float | None] = []
        self._vision_answers = dict(vision_answers or {})
        self._vision_handler = vision_handler
        self.vision_prompts: list[str] = []
        self.vision_images: list[tuple[str, int]] = []
        self.side_usage = side_usage

    @classmethod
    def from_json(cls, path: Path) -> FakeDM:
        """Load a script fixture: `[[{"type": "text", "text": "…"}, …], …]`."""
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls([[event_from_dict(event) for event in entry] for entry in raw])

    async def open(self, spec: ConversationSpec) -> FakeConversation:
        self._opened += 1
        return FakeConversation(self, spec.resume_id or f"fake-{self._opened}")

    async def side_call(
        self,
        prompt: str,
        choice: BackendChoice,
        *,
        timeout: float | None = None,
        on_usage: Callable[[Usage], None] | None = None,
    ) -> str:
        """The scripted answer for `prompt`, else the side handler's, else an echo of it."""
        self.side_prompts.append(prompt)
        self.side_timeouts.append(timeout)
        if prompt in self._side_answers:
            answer = self._side_answers[prompt]
        elif self._side_handler is not None:
            answer = self._side_handler(prompt)
        else:
            answer = f"(fake answer to: {prompt})"
        self._used(on_usage)
        # Let other tasks run after each answer, as a real call would, so a caller can be cancelled between calls.
        await asyncio.sleep(0)
        return answer

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
        """The scripted answer for `prompt`, else the vision handler's, else an echo of it."""
        self.vision_prompts.append(prompt)
        self.vision_images.append((media_type, len(image)))
        if prompt in self._vision_answers:
            answer = self._vision_answers[prompt]
        elif self._vision_handler is not None:
            answer = self._vision_handler(prompt, image, media_type)
        else:
            answer = f"(fake vision answer to: {prompt})"
        self._used(on_usage)
        await asyncio.sleep(0)
        return answer

    def _used(self, on_usage: Callable[[Usage], None] | None) -> None:
        if on_usage is not None and self.side_usage is not None:
            on_usage(self.side_usage)

    def _next_entry(self) -> list[DMEvent] | None:
        return self._script.pop(0) if self._script else None


class FakeConversation:
    def __init__(self, dm: FakeDM, id: str) -> None:
        self._dm = dm
        self.id = id
        self._cancelled = False

    async def send(self, text: str) -> AsyncIterator[DMEvent]:
        self._dm.sent.append(text)
        self._cancelled = False
        entry = self._dm._next_entry()
        if entry is None:
            entry = [DMError("script exhausted", False), TurnEnd("error")]
        elif not any(isinstance(event, TurnEnd) for event in entry):
            entry = [*entry, TurnEnd("done")]
        for event in entry:
            # Let the consumer run between events, as a streaming DM would, so it can cancel mid-reply.
            await asyncio.sleep(0)
            if self._cancelled:
                yield TurnEnd("cancelled")
                return
            yield event
            if isinstance(event, TurnEnd):
                return

    async def cancel(self) -> None:
        self._cancelled = True

    async def close(self) -> None:
        self._cancelled = True
