"""Novels written as jobs (novelization Task 5): start, Continue, and the novels a stopped Delve left behind.

A novel is written by a conversion-runner job of the kind `novel` (`runner.start_job`), titled "Novel: <source name>"
and targeting `{"novel_id"}`, so it has the runner's progress events, cancel, `cost_usd` and the rule of one job at a
time. Its steps are `condensing` (only for material longer than `MAX_PROMPT_CHARS`), `outlining` and `writing`, whose
`done/total` count the chapters. The outline and each chapter are stored as they end, so a cut-off novel keeps them.
The events carry only the job's title, step and counts: never the outline or a chapter.

The material is read when the job starts, from the novel's source: a campaign (all its sessions, or a range), or a
module at the revision the novel pins (the latest, when none is asked for). A failed job leaves the novel `failed`
with the job's message, a cancel leaves it `cancelled`; a Delve that stops leaves it `writing`, and the next start
fails it with `ORPHANED` (`close_orphan_novels`). `continue_novel` picks such a novel up: it keeps the outline and the
chapters written, outlines first when there is no outline, and rebuilds the running summary from what is stored.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from typing import Literal

from delve.conversions import ConversionRunning, ConversionServices, complete_with, finish, progress_for, start_job
from delve.conversions.runner import CONVERSION_TIMEOUT, ChoiceFor
from delve.dm.prompt import TONES
from delve.domain.novels import LENGTHS, Novel, NovelStatus
from delve.novels.material import Material, campaign_material, condense, module_material, render
from delve.novels.writer import LANGUAGES, Choices, outline, running_summary, write_chapter
from delve.storage import Storage

__all__ = [
    "NOVEL_TIMEOUT",
    "ORPHANED",
    "NovelGone",
    "NovelRequest",
    "NovelServices",
    "NovelStateError",
    "close_orphan_novels",
    "continue_novel",
    "start_novel",
]

NOVEL_TIMEOUT = CONVERSION_TIMEOUT
"""Seconds one Claude call of a novel may take: a novella's chapter is long work, as a chunk of pages is."""
ORPHANED = "Delve stopped while writing."
GONE = "The novel's source was deleted."
TITLE_LENGTH = 200


class NovelStateError(ValueError):
    """A novel that can't do what was asked in its status: Continue a novel that isn't failed or cancelled."""


class NovelGone(Exception):
    """The novel went while it was written, with its campaign or its module."""

    def __init__(self) -> None:
        super().__init__(GONE)


@dataclass
class NovelServices:
    """The app's conversion services (the runner's), and Preferences' choice for the `novel` job (`writer`)."""

    conversions: ConversionServices
    writer: ChoiceFor

    @property
    def storage(self) -> Storage:
        return self.conversions.storage


@dataclass(frozen=True)
class NovelRequest:
    """What the owner asks for: the source (a campaign or a module, by id) and the choices. `sessions` is a
    campaign's range, first and last (None: all); `revision` a module's (None: the latest)."""

    source: Literal["campaign", "module"]
    id: str
    length: str = "recap"
    tone: str = "classic"
    custom_tone: str = ""
    language: str = "en"
    instructions: str = ""
    sessions: tuple[int, int] | None = None
    revision: int | None = None


# ----- starting -----


async def start_novel(services: NovelServices, request: NovelRequest) -> Novel:
    """Check the request, make the novel (`writing`) and start its job. `ValueError` for a bad choice,
    `SessionRangeError` for a bad range, `KeyError` for no such campaign, module or revision, `ConversionRunning`
    while another job runs; a refused start makes no novel."""
    _check(request)
    storage = services.storage
    close_orphan_novels(storage)
    if request.source == "campaign":
        campaign = storage.campaigns.get(request.id)
        if campaign is None:
            raise KeyError(request.id)
        material = campaign_material(storage, campaign.id, request.sessions)
        name, source = campaign.name, {"campaign_id": campaign.id, "sessions": request.sessions}
    else:
        module = storage.modules.get(request.id)
        if module is None:
            raise KeyError(request.id)
        revision = _revision(storage, module.id, request.revision)
        material = module_material(storage, module.id, revision)
        name, source = module.title, {"module_id": module.id, "revision": revision}
    _check_free(services)
    novel = storage.novels.create(
        Novel(
            id="",
            title=name,
            length=request.length,  # type: ignore[arg-type]
            tone=request.tone,
            custom_tone=request.custom_tone.strip() if request.tone == "custom" else "",
            language=request.language,
            instructions=request.instructions.strip(),
            **source,  # type: ignore[arg-type]
        )
    )
    return await _start(services, novel, name, material)


def _check(request: NovelRequest) -> None:
    if request.source not in ("campaign", "module"):
        raise ValueError(f"A novel's source is a campaign or a module, not {request.source!r}.")
    if request.length not in LENGTHS:
        raise ValueError(f"A novel's length is one of {', '.join(LENGTHS)}, not {request.length!r}.")
    if request.tone not in TONES:
        raise ValueError(f"A novel's tone is one of {', '.join(TONES)}, not {request.tone!r}.")
    if request.tone == "custom" and not request.custom_tone.strip():
        raise ValueError("Describe the custom tone.")
    if request.language not in LANGUAGES:
        raise ValueError(f"A novel's language is one of {', '.join(LANGUAGES)}, not {request.language!r}.")
    if request.source == "module" and request.sessions is not None:
        raise ValueError("A module's novel has no sessions.")
    if request.source == "campaign" and request.revision is not None:
        raise ValueError("A campaign's novel reads the revision the campaign plays.")


def _revision(storage: Storage, module_id: str, number: int | None) -> int:
    """The revision a module's novel pins: `number`, or the latest (the module as it is now, snapshotted if it
    changed since its last revision). `KeyError` for no such revision."""
    if number is None:
        return storage.revisions.snapshot(module_id).number
    if storage.revisions.get(module_id, number) is None:
        raise KeyError(number)
    return number


def _check_free(services: NovelServices) -> None:
    """`ConversionRunning` while a job runs, before the novel is made, so a refused start makes no novel."""
    running = next(iter(services.conversions.live.values()), None)
    if running is not None:
        raise ConversionRunning(services.storage.conversions.get(running.conversion.id))


async def continue_novel(services: NovelServices, novel_id: str) -> Novel:
    """Write the rest of a failed or cancelled novel, in a new job. `KeyError` for no such novel, `NovelStateError`
    for another status, `ConversionRunning` while another job runs, and the material's errors (a range the campaign
    no longer has) as `start_novel`'s."""
    storage = services.storage
    close_orphan_novels(storage)
    novel = storage.novels.get(novel_id)
    if novel is None:
        raise KeyError(novel_id)
    if novel.status not in ("failed", "cancelled"):
        raise NovelStateError(f"Only a failed or cancelled novel can be continued; this one is {novel.status}.")
    if novel.campaign_id is not None:
        campaign = storage.campaigns.get(novel.campaign_id)
        assert campaign is not None  # the novel goes with its campaign
        name, material = campaign.name, campaign_material(storage, campaign.id, novel.sessions)
    else:
        assert novel.module_id is not None and novel.revision is not None
        module = storage.modules.get(novel.module_id)
        assert module is not None  # the novel goes with its module
        name, material = module.title, module_material(storage, module.id, novel.revision)
    _check_free(services)
    writing = storage.novels.save(replace(novel, status="writing", error=None))
    return await _start(services, writing, name, material, before=novel)


async def _start(
    services: NovelServices, novel: Novel, name: str, material: Material, *, before: Novel | None = None
) -> Novel:
    """Start the novel's job and store its id. A refused start deletes a new novel, and puts a continued one back
    as it was (`before`)."""
    storage = services.storage
    spent = novel.cost_usd or 0.0
    try:
        job = await start_job(
            services.conversions,
            "novel",
            f"Novel: {name}",
            lambda live: _write(services, live, novel.id, material, spent),
            target={"novel_id": novel.id},
        )
    except BaseException:
        if before is None:
            storage.novels.delete(novel.id)
        else:
            storage.novels.save(before)
        raise
    # The job's task runs from the next `await`: the novel holds its job's id before it is first saved there.
    return storage.novels.save(replace(novel, conversion_id=job.id))


# ----- the job -----


async def _write(services: NovelServices, live, novel_id: str, material: Material, spent: float) -> None:
    """The job's work: condense, outline when there is no outline, write each missing chapter, then end the job.
    The novel is read again before each save, so a rename while it is written stays."""
    storage = services.storage
    progress = progress_for(services.conversions, live)
    complete = complete_with(services.conversions, live, services.writer, NOVEL_TIMEOUT)

    def save(**changes) -> Novel:
        current = storage.novels.get(novel_id)
        if current is None:
            raise NovelGone()
        cost = spent + (live.conversion.cost_usd or 0.0)
        try:
            return storage.novels.save(replace(current, cost_usd=cost or None, **changes))
        except KeyError:  # the source went between the read and the save
            raise NovelGone() from None

    try:
        novel = save()
        choices = Choices(novel.length, novel.tone, novel.custom_tone, novel.language, novel.instructions)
        material = await condense(material, complete, progress)
        text = render(material)
        if not novel.chapters:
            progress("outlining", 0, 1)
            title, chapters = await outline(complete, material.kind, text, choices)
            novel = save(title=title[:TITLE_LENGTH], chapters=chapters)
        chapters = list(novel.chapters)
        for index, chapter in enumerate(chapters):
            if chapter.text is not None:
                continue
            progress("writing", sum(c.text is not None for c in chapters), len(chapters))
            so_far = running_summary(chapters[:index])
            written = await write_chapter(complete, material.kind, text, choices, novel.title, chapters, index, so_far)
            chapters[index] = replace(chapter, text=written)
            novel = save(chapters=chapters)
        progress("writing", len(chapters), len(chapters))
        save(status="done", error=None)
        finish(services.conversions, live, result={"novel_id": novel_id})
    except asyncio.CancelledError:
        if live.cancelled:  # the owner's cancel; a Delve that stops leaves the novel writing, for the next start
            _end(storage, novel_id, "cancelled", None, spent + (live.conversion.cost_usd or 0.0))
        raise
    except Exception as error:
        _end(storage, novel_id, "failed", str(error) or type(error).__name__, spent + (live.conversion.cost_usd or 0.0))
        raise


def _end(storage: Storage, novel_id: str, status: NovelStatus, error: str | None, cost: float) -> None:
    current = storage.novels.get(novel_id)
    if current is None:
        return
    try:
        storage.novels.save(replace(current, status=status, error=error, cost_usd=cost or None))
    except KeyError:
        pass


# ----- orphans -----


def close_orphan_novels(storage: Storage) -> list[Novel]:
    """Every `writing` novel whose job isn't running (a Delve that stopped left it) becomes `failed` with `ORPHANED`,
    its chapters kept. Answers the novels closed. At start, after `close_orphans`, and before each start."""
    closed = []
    for novel in storage.novels.writing():
        job = storage.conversions.get(novel.conversion_id) if novel.conversion_id is not None else None
        if job is not None and job.status == "running":
            continue
        closed.append(storage.novels.save(replace(novel, status="failed", error=ORPHANED)))
    return closed
