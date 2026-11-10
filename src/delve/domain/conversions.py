"""Conversions (plan 5 Task 4): a job that makes a module from a PDF or from a request, in the background. Plateau 7
adds the jobs that read a world map's picture (`worldmap`) and draw a dungeon map from a description (`dungeon-map`)
or from a book's map page (`book-map`) for a module that already exists (`target`). The novelization plan adds
the job that writes a novel (`novel`, its `target` `{"novel_id"}`), and carrying the party on the job that writes a
carried party's history (`history`, its `target` `{"campaign_id"}`, the new campaign's). The thorough conversion
(Task 4) is a `pdf` job whose `target` is `{"thorough": true, "folder"}`, its job folder; it is `paused`, not failed,
when Delve stops or the usage limit is reached, and resumes. `paused` isn't an end. A PDF job uploaded while another
job runs (or while the queue is paused) is `queued`, and starts by itself, oldest first, when the slot frees (owner
addition 2026-10-23); `queued` isn't an end either. A `fixit` job (table voice and fixes Task 0) acts on a module's
fix-it comments, its `target` `{"module_id", "revision", "comment_ids"}`, and proposes the change as its `result`,
which is saved only when the organiser keeps it."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

ConversionKind = Literal["pdf", "generate", "worldmap", "dungeon-map", "book-map", "novel", "history", "fixit"]
ConversionMode = Literal["ready", "draft"]
ConversionStatus = Literal["queued", "running", "paused", "done", "failed", "cancelled"]
CONVERSION_MODES: tuple[ConversionMode, ...] = ("ready", "draft")


@dataclass(frozen=True)
class Conversion:
    """One job. `step` is the step it is at (`reading`, `converting`, `entities`, `pictures`, `maps`, or
        `generating`), and `done` out of `total` its progress there: pages while converting. `module_id` is the module it
        made, once done; `warnings` are the module's `{code, message, ref}`; `error` is why it failed. `target` names
        what a job works on (`{"module_id", …}`), `result` is what a job that makes no module made (a draft), and
        `questions` are the questions asked while making a module, with their answers. `cost_usd` is what its Claude
        calls cost so far, None while none reported a cost. `comments` are the PDF form's comments for Claude, and
    `closed` the keys of the questions and doubts an organiser closed (`question:<id>`, `doubt:<index>`), written only
    through `ConversionRepository.set_closed`."""

    id: str
    kind: ConversionKind
    title: str
    mode: ConversionMode
    status: ConversionStatus = "running"
    step: str = ""
    done: int = 0
    total: int = 0
    module_id: str | None = None
    warnings: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    created_at: str = ""
    updated_at: str = ""
    target: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    questions: dict[str, Any] | None = None
    cost_usd: float | None = None
    comments: str = ""
    closed: list[str] = field(default_factory=list)
