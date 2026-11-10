"""Conversions in the background (plan 5 Task 4; spec §6.4, §8.3): a PDF or a request becomes a module.

A job is a `conversions` row and an `asyncio` task of its own, as `play.table.run_beat` runs a beat: the start answers
at once, and the task runs on when the request that started it goes away. Each progress call is stored on the row, so
a reload sees it, and published as a `conversion` event, `{id, status, step, done, total, steps}`; so is the end.
`steps` is `{index, count}`, "Step 2 of 4" (`STEPS`), and the reading counts its pages as it reads them.

Every Claude step is a side call of the DM provider with Preferences' choice for the `conversion` job and
`CONVERSION_TIMEOUT` per call; a picture step (classifying the picture pages, reading the glyphs the text layer lost
from a page's picture, `gaps.fill_gaps`) is a vision call of the same choice (`look_for`). What each call cost is
added to the job's `cost_usd` as it goes (`_spend`). A converted text with three or more keyed headings gets a map
sketched from its room key, which its headings then link to, unless one of the book's map pages is titled like it
(`plate_matches`): that page is drafted after the conversion instead (`dungeon_maps.draw_book_maps`, faithful modules
B5). A sketch is an invented layout, and its source says so first
(`SKETCHED`, then `NO_BOOK_MAP`); it is named after its text, never the module.

The module is made only at the end, in one transaction: the module (a draft or not, from the mode), its sketched maps,
the links to its attachments' blobs (the original PDF among them, as a `source` attachment), its source, and the job's
end. The blobs are written just before, off the event loop, the PDF streamed from its file. A job that is cancelled or
fails leaves no module; a blob it wrote before that stays unlinked, as an upload's does. A cancel during the reading
stops the reading thread at its next page. One job runs at a time, and a job left running by a Delve that stopped is
closed as failed (`close_orphans`, and before every start). Once a job has ended, its progress calls change nothing.

**The queue** (thorough conversion, owner addition 2026-10-23; design d1, option A). A PDF uploaded while the slot
is taken, while the queue's switch is paused, or while others wait, is `queued` (`_admit`): it holds no slot, and
keeps how it starts (`_Start`) in `ConversionServices.starts`, its row the book it waits with (`target.upload`, and
`book_maps`), so a queued job survives a restart (`_restored`; one whose book is gone fails at the start,
`close_lost`). `start_queue` starts the oldest queued job when the slot frees: when a job ends, is cancelled or
pauses, once its follow-up (`then`, the book's maps drawn one job after another) has ended, and when the switch
(`set_queue_paused`, stored) is unpaused; never while it is paused. A request to generate a module is queued the same
way (DEL-141), its request on its row (`target.request`). The other kinds of job still refuse to start while one runs
(`ConversionRunning`).

A thorough conversion (`delve.conversions.thorough`, thorough conversion Task 4) is a `pdf` job with a job folder
(`target` `{"thorough": true, "folder"}`): left running by a Delve that stopped, it is `paused` with the reason
`DELVE_STOPPED`, not failed, and its folder kept; a paused job holds no slot. Its cancel, running or paused, deletes
its folder and the resume its pause had scheduled. Paused by hand (`thorough.pause`), its task is cancelled with
`_Live.pausing` set, and it ends `paused` (`PAUSED_BY_ORGANISER`) instead of cancelled. Its steps are the pipeline's stages (`STEPS["pdf-thorough"]`,
thorough conversion Task 6), and its doubts are stored with its questions, `{"questions", "remarks", "doubts"}`.

**Comments** (table voice and fixes Task F1): the organiser's comments on the PDF form are kept on the job
(`Conversion.comments`, at most `COMMENTS_MAX` characters), a queued one's too, and every prompt of the job is given
them after its task, under "The organiser's comments" (`with_comments`): its side calls and looks here, and a
thorough job's agents, side calls and looks.

What Claude asked while making the module (`Converted.questions`) is stored on the job, `{"questions": [{id, text,
default, answer}], "remarks": []}`. The organiser's answers and remarks (`answer_questions`) are written into the
module's `gm` text `MAKING_NOTES`, which the DM reads with the module; the job isn't run again. Its questions and
doubts can be closed once dealt with (`close_items`, table voice and fixes Task F3): `Conversion.closed` holds their
keys, `question:<id>` and `doubt:<index>`, which only closing writes, so a job's own saves can't reopen them. Closing
only hides: it changes neither `MAKING_NOTES` nor what the DM is told.
"""

from __future__ import annotations

import asyncio
import importlib
import logging
import os
import re
import textwrap
import threading
from collections.abc import Awaitable, Callable, Coroutine, Mapping, Sequence
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

from delve.conversions.thorough.pieces import AgentRunner
from delve.conversions.thorough.workspace import DELVE_STOPPED, PAUSED_BY_ORGANISER, Workspace
from delve.dm.claude_cli.stream import USAGE_LIMIT
from delve.dm.provider import DMProvider, Usage
from delve.domain.conversions import CONVERSION_MODES, Conversion, ConversionKind, ConversionMode, ConversionStatus
from delve.domain.image_styles import stored_style_text
from delve.domain.modules import ModuleMap, homebrew
from delve.domain.settings import BackendChoice, Job
from delve.images.provider import ImageFile, ImageRequest
from delve.maps.geo.reading.ocr import PictureOcr
from delve.maps.vision import Look
from delve.modules.books.calls import Halt
from delve.modules.books.campaign import SCALES, Answer, Scale, Scope, generate_campaign, scope_request, with_answers
from delve.modules.books.classify import classify_pages
from delve.modules.books.convert import Complete, Converted, Progress, Question, convert_book, map_title
from delve.modules.books.gaps import fill_gaps
from delve.modules.books.generate import generate_module
from delve.modules.books.metadata import complete_metadata
from delve.modules.books.pdf import Ocr, PdfBook, ReadStopped, read_pdf, render_page, tesseract_ocr
from delve.modules.books.pictures import MAX_PICTURES, PICTURE_NOT_PAINTED, Planned, paint_pictures, plan_pictures
from delve.modules.books.sandbox import generate_sandbox
from delve.modules.books.sketch import sketch_map
from delve.modules.dscn import parse_text
from delve.modules.dscn.text import split_front_matter
from delve.modules.source import ATTACHMENT, Attachment, TextDoc, Warning, load_source, save_source
from delve.modules.text import unique
from delve.setting.catalog import CATALOG, SettingEntry
from delve.storage.interfaces import Storage

__all__ = [
    "COMMENTS_MAX",
    "CONVERSION_TIMEOUT",
    "MAKING_NOTES",
    "ChoiceFor",
    "ConversionRunning",
    "ConversionServices",
    "answer_questions",
    "cancel",
    "check_pdf",
    "close_folders",
    "close_items",
    "close_orphans",
    "complete_with",
    "conversion_json",
    "finish",
    "look_for",
    "module_questions",
    "plate_matches",
    "progress_for",
    "queue",
    "scope_generate",
    "set_queue_paused",
    "start_generate",
    "start_job",
    "start_pdf",
    "start_queue",
    "tell_dm",
    "wait",
    "with_comments",
]

log = logging.getLogger(__name__)

COMMENTS_MAX = 2000
"""The most characters the PDF form's comments may have."""
COMMENTS_HEADING = "## The organiser's comments"
DEFAULT_CONVERSION_TIMEOUT = 600.0


def conversion_timeout(env: Mapping[str, str] = os.environ) -> float:
    """`DELVE_CALL_TIMEOUT` seconds (DEL-139), read when Delve starts: a positive number, else 600."""
    try:
        value = float(env.get("DELVE_CALL_TIMEOUT") or DEFAULT_CONVERSION_TIMEOUT)
    except ValueError:
        return DEFAULT_CONVERSION_TIMEOUT
    return value if value > 0 else DEFAULT_CONVERSION_TIMEOUT


CONVERSION_TIMEOUT = conversion_timeout()
"""Seconds one Claude call of a conversion, a novel or a history may take: a chunk of pages is long work.
`DELVE_CALL_TIMEOUT` sets it (DEL-139); the DM's turns have their own, `DELVE_DM_TURN_TIMEOUT`."""
GENERATE_TIMEOUT = 1800.0
"""Seconds Generate's one call may take for a module (`scale` `module`): one plan answer; a request for a campaign
that wasn't scoped as one took 682 s (2026-10-25). A campaign's calls each have `CONVERSION_TIMEOUT` (DEL-134)."""
SCOPE_TIMEOUT = 180.0
RETRY_DELAYS = (10.0, 30.0)
"""Seconds waited before a chunk's call is asked again after it failed, once per wait: a transient failure (a timeout,
an overloaded backend) shouldn't lose a whole book for one chunk. The thorough drafting has its own,
`pipeline.DRAFT_RETRY_DELAYS`."""
FILTERED = re.compile(r"blocked by content filtering", re.IGNORECASE)
FOLLOW_UP_FAILED = "follow-up-failed"
"""The warning of a done job whose follow-up (`then`, the book's maps drawn) failed."""
ANSWERS_NOT_NOTED = "answers-not-noted"
"""The warning of a generated module whose scope answers couldn't be written into its making notes."""
"""Seconds the scope call before Generate may take: the organiser waits on it in New module."""
SKETCHED_KEYS = 3
"""A converted text with at least this many keyed headings gets a sketched map."""
SOURCE_PDF = "source-pdf"
"""The attachment id of a converted book's original PDF."""

RUNNING = "A conversion is running."
ORPHANED = "Delve stopped during the conversion."
LOST = "Delve stopped while the conversion was queued, and its book was lost."
SKETCHED = "# Sketched from the room key: an invented layout."
"""The first line of a sketched map's source; the web app shows a notice for a map that starts with it."""
NO_BOOK_MAP = "No map page was found in the book."
BOOK_MAP = "The book's map is asset:{page}."
"""What a sketch's first line says after `SKETCHED` when the book has a map page."""
UNTITLED_SKETCH = "sketch"
"""The name of a sketch whose text is titled by the module and whose book has no map title."""
STEPS: dict[ConversionKind | str, tuple[tuple[str, ...], ...]] = {
    "pdf": (("reading",), ("classifying",), ("converting", "gaps"), ("entities", "pictures"), ("maps",)),
    "pdf-thorough": (
        ("reading",),
        ("classifying",),
        ("drafting",),
        ("sorting",),
        ("cleaning",),
        ("tracing",),
        ("joining",),
        ("describing",),
        ("entities",),
        ("making",),
    ),
    "generate": (("scoping", "generating"), ("maps",)),
    "generate-campaign": (("scoping",), ("planning",), ("campaign",), ("levels",), ("maps",)),
    "generate-sandbox": (("scoping",), ("planning",), ("sites",), ("maps",)),
    "worldmap": (("tiles",), ("grid",), ("terrain",), ("water",), ("places",), ("routes",)),
    "dungeon-map": (("drawing",),),
    "book-map": (("drawing",),),
    "novel": (("condensing",), ("outlining",), ("writing",)),
    "history": (("condensing",), ("writing",)),
    "fixit": (("fixing",),),
}
"""The steps of each kind of job, in order, for "Step 2 of 4"; the pictures are part of the entities' step, and the
lost glyphs read from the pages' pictures (`gaps`, after the entities) part of the converting step. A thorough `pdf`
job's are `pdf-thorough`'s, the stages of `thorough.pipeline` (thorough conversion Task 6); a request scoped as a
campaign's are `generate-campaign`'s (DEL-134), and one scoped as a sandbox `generate-sandbox`'s (DEL-349). A request with pictures has `PAINTING` as its last (DEL-347)."""
PAINTING = ("painting",)

PLATE_STOP = frozenset(
    {"part", "map", "maps", "level", "levels", "floor", "floors", "deck", "decks", "plan", "page", "the", "and", "with"}
)
"""The words a text's title and a plate's title may share without naming the same place."""
PLATE_WORD = 4
"""The shortest word `plate_matches` counts."""

REPEATED_KEYS = "The keys repeat in this text, so its map wasn't sketched; draw it by hand."

ChoiceFor = Callable[[], tuple[DMProvider, BackendChoice]]


class ConversionRunning(Exception):
    """A job was started while `conversion` runs."""

    def __init__(self, conversion: Conversion | None) -> None:
        self.conversion = conversion
        super().__init__(RUNNING)


@dataclass
class _Live:
    """A job this process runs: its row as last stored, its task, the upload it owns, and `stop`, set when it is
    cancelled, which the reading thread asks before each page."""

    conversion: Conversion
    task: asyncio.Task | None = None
    cancelled: bool = False
    pausing: bool = False
    """Set when the organiser pauses the job (`thorough.pause`): its stopped task ends it `paused`, not cancelled."""
    upload: Path | None = None
    stop: threading.Event = field(default_factory=threading.Event)


@dataclass
class _Start:
    """How a job starts: its `work(live)`, the `cleanup` when it ends (or is cancelled while queued), its follow-up
    (`then`, once it is done) and the upload it owns."""

    work: Callable[[_Live], Coroutine[Any, Any, None]]
    cleanup: Callable[[], None] = lambda: None
    then: Callable[[Conversion], Awaitable[Any]] | None = None
    upload: Path | None = None


@dataclass
class ConversionServices:
    """What the conversions are handed by the app: the storage, the DM provider and choice of the `conversion` job
    (Preferences'), `publish(kind, data, **where)` for the app's event stream (`where`: a table event's `scope` and
    `campaign_id`), the OCR for scanned pages (tesseract when it is
    installed), and the OCR for a world map's picture (none: its labels go to Claude). `live` holds the job this
    process runs, `follow_ups` the work started once a job ended (`start_pdf`'s `then`), and `resumes` the paused
    thorough jobs' scheduled resumes."""

    storage: Storage
    conversion: ChoiceFor
    publish: Callable[..., None] = lambda kind, data, **where: None
    ocr: Ocr | None = field(default_factory=tesseract_ocr)
    picture_ocr: PictureOcr | None = None
    live: dict[str, _Live] = field(default_factory=dict)
    follow_ups: set[asyncio.Task] = field(default_factory=set)
    resumes: dict[str, asyncio.TimerHandle] = field(default_factory=dict)
    """The resumes a thorough job paused at the usage limit has scheduled, by job id (`thorough.resume`)."""
    settings: Sequence[SettingEntry] = CATALOG
    """The install's settings (its catalogs'), which a world map read for a setting must name."""
    game: str = ""
    """The game a generated module is written for: the title of the ruleset a new campaign takes (none: OSRIC's)."""
    thorough: ChoiceFor | None = None
    """The provider and choice of Preferences' `conversion.thorough` job, for a thorough job's agents, side calls and
    looks; None uses `conversion`'s."""
    agent: AgentRunner | None = None
    """What runs a thorough job's agent sessions (`claude_cli.agent.run_agent`); None when the Claude CLI isn't there,
    and a thorough job then pauses with `pipeline.NO_AGENT`."""
    starts: dict[str, _Start] = field(default_factory=dict)
    """How each job queued by this process starts, by job id; a job queued before a restart starts from its row."""
    holds: set[asyncio.Task] = field(default_factory=set)
    """The follow-ups that hold the queue until they end (a quick job's book maps)."""
    stopping: bool = False
    """Set when Delve stops: the queue starts nothing more."""
    pipeline: Any = None
    """The thorough jobs' stages (`thorough.Pipeline`); None for `thorough.pipeline.run_thorough`. Tests give theirs."""
    images: Callable[[Job], tuple[Any, BackendChoice]] | None = None
    """The image provider and choice of an image job, for a generated module's pictures (DEL-347); None for none."""
    image_paid: Callable[[Job], bool] = lambda job: True
    """Whether the image job's model costs money; a wrong guess never spends the owner's money."""


def conversion_json(conversion: Conversion) -> dict[str, Any]:
    """The conversion as the API answers it: its row, its `steps`, whether it is `thorough`, and a paused thorough
    job's `paused` `{reason, resets_at}` from its folder (null otherwise; thorough conversion Task 8)."""
    folder = job_folder(conversion)
    paused = None
    if conversion.status == "paused" and folder is not None and folder.exists():
        try:
            pause = folder.state().paused
        except (OSError, ValueError, TypeError):  # a state Delve can't read: the job is paused, for no known reason
            pause = None
        paused = asdict(pause) if pause is not None else None
    return {**asdict(conversion), "steps": _steps(conversion), "thorough": folder is not None, "paused": paused}


def _steps(conversion: Conversion) -> dict[str, int]:
    """Which step of how many `conversion` is at: `{index, count}`, the index from 1, and 0 before the first."""
    target = conversion.target or {}
    if target.get("thorough"):
        steps = STEPS["pdf-thorough"]
    elif conversion.kind == "generate" and target.get("scale") in ("campaign", "sandbox"):
        steps = STEPS[f"generate-{target['scale']}"]
    else:
        steps = STEPS[conversion.kind]
    if conversion.kind == "generate" and target.get("pictures"):
        steps = (*steps, PAINTING)
    index = next((n for n, names in enumerate(steps, start=1) if conversion.step in names), 0)
    return {"index": index, "count": len(steps)}


def _event(conversion: Conversion) -> dict[str, Any]:
    return {
        "id": conversion.id,
        "status": conversion.status,
        "step": conversion.step,
        "done": conversion.done,
        "total": conversion.total,
        "steps": _steps(conversion),
        "cost_usd": conversion.cost_usd,
    }


# ----- starting, cancelling, waiting -----


async def start_pdf(
    services: ConversionServices,
    path: Path,
    title: str,
    mode: ConversionMode,
    *,
    then: Callable[[Conversion], Awaitable[Any]] | None = None,
    book_maps: bool = False,
    comments: str = "",
) -> Conversion:
    """Start converting the PDF at `path` into a module titled `title`, a draft or ready to play, or queue it while
    the slot is taken or the queue paused. The job owns `path` from here and removes it when it ends, or at once
    when it is refused. `then(job)` runs once the module is made and no job runs any more; with `book_maps` it is
    the book's maps drawn (`dungeon_maps.draw_book_maps`), which a job queued over a restart keeps too. Not for a
    job that failed or was cancelled. Every prompt of the job is given the organiser's `comments`. Answers the job,
    running or queued; `ValueError` for no title, another mode or comments over `COMMENTS_MAX`."""
    try:
        check_pdf(title, mode, comments)
        waiting = {"upload": str(path), "book_maps": book_maps}
        admitted = _admit(services, "pdf", title.strip(), mode, waiting=waiting, comments=comments.strip())
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return _begin(services, admitted, _pdf_start(services, path, then or (_book_maps(services) if book_maps else None)))


def _pdf_start(
    services: ConversionServices, path: Path, then: Callable[[Conversion], Awaitable[Any]] | None
) -> _Start:
    return _Start(
        lambda live: _convert_pdf(services, live, path),
        cleanup=lambda: path.unlink(missing_ok=True),
        then=then,
        upload=path,
    )


def _book_maps(services: ConversionServices) -> Callable[[Conversion], Awaitable[Any]]:
    """The follow-up that draws a made module's book maps (`dungeon_maps` imports this module)."""
    draw = importlib.import_module("delve.conversions.dungeon_maps").draw_book_maps
    return lambda job: draw(services, job.module_id)


def check_pdf(title: str, mode: str, comments: str = "") -> None:
    """`ValueError` for a PDF conversion with no title, another mode or comments over `COMMENTS_MAX`, before its book
    is taken in."""
    if not title.strip():
        raise ValueError("A conversion needs a title.")
    _check_mode(mode)
    if len(comments) > COMMENTS_MAX:
        raise ValueError(f"The comments may be at most {COMMENTS_MAX} characters.")


def with_comments(prompt: str, comments: str) -> str:
    """`prompt` with the organiser's `comments` after its task, under `COMMENTS_HEADING`; as it is without any."""
    comments = comments.strip()
    if not comments:
        return prompt
    return f"{prompt.rstrip()}\n\n{COMMENTS_HEADING}\n\n{comments}\n"


def _check_mode(mode: str) -> None:
    if mode not in CONVERSION_MODES:
        raise ValueError(f"A conversion's mode is ready or draft, not {mode!r}.")


async def scope_generate(services: ConversionServices, request: str) -> Scope:
    """Before Generate (DEL-134): the request's scale and the questions to ask the organiser first, from one short
    side call of Preferences' `conversion` job (`campaign.scope_request`), run at once, beside any job. `ValueError`
    for an empty request."""
    request = request.strip()
    if not request:
        raise ValueError("Describe the module you want.")
    return await scope_request(
        request, complete_with(services, None, services.conversion, SCOPE_TIMEOUT), game=services.game
    )


async def start_generate(
    services: ConversionServices,
    request: str,
    mode: ConversionMode,
    *,
    scale: Scale | None = None,
    answers: Sequence[Answer] = (),
    pictures: int = 0,
    owner: bool = False,
) -> Conversion:
    """Start generating a module from `request` (spec §8.3, "a dungeon with kobolds, no plot"). The job is titled
    by the request until the module has its own title. Queued as a PDF is while the slot is taken, the queue paused
    or others wait (DEL-141), the request kept on its row (`target.request`) so it survives a restart, with its
    `scale` and the organiser's `answers` to the scope questions (DEL-134; without a scale, the job scopes it first).
    With `pictures`, the module also gets at most that many painted handouts (DEL-347), kept on the row with whether
    the `owner` asked, as the job checks a paid model when it paints. Answers the job, running or queued; `ValueError`
    for an empty request, another mode, an unknown scale or too many pictures."""
    request = request.strip()
    if not request:
        raise ValueError("Describe the module you want.")
    if scale is not None and scale not in SCALES:
        raise ValueError(f"A module's scale is module or campaign, not {scale!r}.")
    if not 0 <= pictures <= MAX_PICTURES:
        raise ValueError(f"A module may ask for at most {MAX_PICTURES} pictures.")
    first_line = request.splitlines()[0]
    title = textwrap.shorten(first_line, 80, placeholder="…")
    if title == "…":  # one word longer than the title: cut it, then
        title = first_line[:79] + "…"
    answered = [asdict(a) for a in answers]
    waiting = {"request": request} | ({"scale": scale} if scale else {}) | ({"answers": answered} if answered else {})
    target = ({"scale": scale} if scale else {}) | ({"pictures": pictures, "owner": owner} if pictures else {})
    admitted = _admit(services, "generate", title, mode, target=target or None, waiting=waiting)
    return _begin(services, admitted, _generate_start(services, request, scale, list(answers)))


def _generate_start(services: ConversionServices, request: str, scale: Scale | None, answers: list[Answer]) -> _Start:
    return _Start(lambda live: _generate(services, live, request, scale, answers))


def _answers(raw: Any) -> list[Answer]:
    """The answers kept on a queued job's row."""
    return [
        Answer(str(a.get("text") or ""), str(a.get("default") or ""), str(a.get("answer") or ""))
        for a in raw or []
        if isinstance(a, dict) and a.get("text")
    ]


async def start_job(
    services: ConversionServices,
    kind: ConversionKind,
    title: str,
    work: Callable[[_Live], Coroutine[Any, Any, None]],
    *,
    target: dict[str, Any] | None = None,
    cleanup: Callable[[], None] = lambda: None,
) -> Conversion:
    """Start a job of `kind` that runs `work(live)`, on what `target` names, one at a time as every job. Plateau 7's
    jobs make no module: their work ends them with `finish`. `cleanup` runs when the job ends, and at once when it is
    refused. Answers the running job; `ConversionRunning` while another runs.

    Its mode is `ready`: `conversions.mode` is never empty, and a job that makes no module ignores it."""
    try:
        live = _open(services, kind, title, "ready", target=target)
    except BaseException:
        cleanup()
        raise
    return _run(services, live, work(live), cleanup=cleanup)


def finish(
    services: ConversionServices, live: _Live, *, result: dict[str, Any] | None = None, warnings: Sequence[Warning] = ()
) -> Conversion:
    """End a job that makes no module as done, with what it made (`result`) and its warnings. Once the job has ended,
    a late call changes nothing."""
    if live.conversion.status != "running":
        return live.conversion
    live.conversion = services.storage.conversions.save(
        replace(live.conversion, status="done", result=result, warnings=[asdict(w) for w in warnings])
    )
    services.publish("conversion", _event(live.conversion))
    return live.conversion


async def cancel(services: ConversionServices, id: str) -> Conversion:
    """Stop the job `id`: it ends as `cancelled` and leaves no module. A job that has ended stays as it is, done
    even when its module was made as the cancel came. A queued job leaves the queue, its book removed. A thorough
    job's folder is deleted (a done one's too), and its scheduled resume dropped. The next queued job starts once a running one has stopped. `KeyError` for an unknown id."""
    conversion = services.storage.conversions.get(id)
    if conversion is None:
        raise KeyError(id)
    live = services.live.get(id)
    if live is not None and live.task is not None and not live.task.done():
        live.cancelled = True
        live.stop.set()
        live.task.cancel()
        await asyncio.gather(live.task, return_exceptions=True)
        _never_began(services, live, lambda: _end(services, live.conversion, "cancelled", live=live))
        conversion = services.storage.conversions.get(id)
    elif conversion.status in ("running", "paused", "queued"):  # or left running by a Delve that stopped
        if conversion.status == "queued":
            _drop_queued(services, conversion)
        conversion = _end(services, conversion, "cancelled")
    if conversion.status == "cancelled":
        scheduled = services.resumes.pop(id, None)
        if scheduled is not None:
            scheduled.cancel()
    folder = job_folder(conversion)
    if folder is not None and conversion.status in ("cancelled", "done"):  # a done job's removal the cancel stopped
        await asyncio.to_thread(folder.remove)
    return conversion


async def wait(services: ConversionServices, id: str) -> Conversion:
    """Wait for the job `id` to end, if this process runs it; the job as stored. `KeyError` for an unknown id."""
    live = services.live.get(id)
    if live is not None and live.task is not None:
        await asyncio.shield(live.task)
    conversion = services.storage.conversions.get(id)
    if conversion is None:
        raise KeyError(id)
    return conversion


def _never_began(services: ConversionServices, live: _Live, end: Callable[[], Any]) -> None:
    """A job whose task was stopped before it began: `_job` never ran, so `end` ends it here, and the queue moves."""
    if services.live.get(live.conversion.id) is live:
        services.live.pop(live.conversion.id)
        end()
        start_queue(services)


def _drop_queued(services: ConversionServices, conversion: Conversion) -> None:
    """A queued job leaves the queue: how it would start is forgotten, and the book it waited with removed."""
    start = services.starts.pop(conversion.id, None)
    if start is not None:
        start.cleanup()
    upload = (conversion.target or {}).get("upload")
    if upload:
        Path(upload).unlink(missing_ok=True)


def close_orphans(storage: Storage) -> list[Conversion]:
    """At start: a job still `running` was left by a Delve that stopped, and fails; a thorough job is paused instead,
    `DELVE_STOPPED`, unless its folder never got its state (Delve stopped while copying the book in). Answers the
    jobs closed."""
    running = storage.conversions.running()
    if running is None:
        return []
    folder = job_folder(running)
    if folder is not None and folder.exists():
        folder.pause(DELVE_STOPPED)
        return [storage.conversions.save(replace(running, status="paused"))]
    if folder is not None:
        folder.remove()
    return [storage.conversions.save(replace(running, status="failed", error=ORPHANED))]


def close_lost(storage: Storage) -> list[Conversion]:
    """At start: a queued job whose book is gone (Delve stopped as it was taken in) fails with `LOST`, and its
    folder is removed. Answers the jobs closed."""
    lost = []
    for conversion in storage.conversions.queued():
        folder = job_folder(conversion)
        upload = (conversion.target or {}).get("upload")
        if (folder is not None and folder.exists()) or (upload and Path(upload).is_file()):
            continue
        if folder is not None:
            folder.remove()
        lost.append(storage.conversions.save(replace(conversion, status="failed", error=LOST)))
    return lost


def close_folders(storage: Storage, data_dir: Path) -> list[Path]:
    """At start, after `close_orphans`: remove the job folders in `<data_dir>/conversions/` that no unfinished job
    owns, those of a job that ended (done, cancelled or failed: Delve stopped before it removed the folder) or that
    no job row names. A paused or queued job's folder stays. Answers the folders removed."""
    removed = []
    for path in sorted((data_dir / "conversions").glob("*")):
        conversion = storage.conversions.get(path.name) if path.is_dir() else None
        if not path.is_dir() or (conversion is not None and conversion.status in ("running", "paused", "queued")):
            continue
        Workspace(path).remove()
        removed.append(path)
    return removed


# ----- the queue -----


def queue(storage: Storage) -> list[Conversion]:
    """The jobs that aren't over, in the order they get the slot: the running one, the queued ones oldest first, then
    the paused ones, oldest first."""
    running = storage.conversions.running()
    return [*([running] if running is not None else []), *storage.conversions.queued(), *storage.conversions.paused()]


def set_queue_paused(services: ConversionServices, paused: bool) -> bool:
    """Pause the queue (no queued job starts, a running one runs on) or unpause it, which starts the oldest queued
    job when the slot is free. The switch is stored, so it survives a restart, and published as a `conversion-queue`
    event, `{paused}`. Answers it."""
    services.storage.conversions.set_queue_paused(paused)
    services.publish("conversion-queue", {"paused": paused})
    if not paused:
        start_queue(services)
    return paused


def _free(services: ConversionServices) -> bool:
    return not services.live and not services.holds and not services.stopping


def _admit(
    services: ConversionServices,
    kind: ConversionKind,
    title: str,
    mode: ConversionMode,
    *,
    target: dict[str, Any] | None = None,
    waiting: dict[str, Any] | None = None,
    comments: str = "",
) -> _Live | Conversion:
    """The new job: its `_Live` when it starts now, or its row, queued with `waiting` added to its `target` (what it
    starts from after a restart), while the slot is taken, the queue is paused or others wait in it. Both keep the
    organiser's `comments`."""
    storage = services.storage
    if _free(services) and not storage.conversions.queue_paused() and not storage.conversions.queued():
        return _open(services, kind, title, mode, target=target, comments=comments)
    _check_mode(mode)
    queued = storage.conversions.create(
        kind, title, mode, target={**(target or {}), **(waiting or {})}, status="queued", comments=comments
    )
    services.publish("conversion", _event(queued))
    return queued


def _begin(services: ConversionServices, admitted: _Live | Conversion, start: _Start) -> Conversion:
    """Run the job admitted to start now; keep how a queued one starts, for when the queue reaches it. Answers it."""
    if isinstance(admitted, _Live):
        return _launch(services, admitted, start)
    services.starts[admitted.id] = start
    start_queue(services)
    live = services.live.get(admitted.id)
    return live.conversion if live is not None else services.storage.conversions.get(admitted.id) or admitted


def start_queue(services: ConversionServices) -> Conversion | None:
    """Start the oldest queued job that can start, when no job runs (nor a follow-up holds the slot) and the queue
    isn't paused. A job that can't start yet (its book still being taken in) waits its turn. Answers the job
    started, if any."""
    storage = services.storage
    if not _free(services) or storage.conversions.queue_paused():
        return None
    for conversion in storage.conversions.queued():
        start = services.starts.get(conversion.id) or _restored(services, conversion)
        if start is None:
            continue
        services.starts.pop(conversion.id, None)
        close_orphans(storage)
        live = _Live(storage.conversions.save(replace(conversion, status="running")))
        services.live[conversion.id] = live
        services.publish("conversion", _event(live.conversion))
        _launch(services, live, start)
        return live.conversion
    return None


def _restored(services: ConversionServices, conversion: Conversion) -> _Start | None:
    """How a job queued before a restart starts, from its row: a thorough job from its folder or its book
    (`thorough.restored`), a fix-it job from its comments (`fixit.restored`), a request from its row's, a quick one
    from its book, with its book maps if it asked for them. None while it can't."""
    target = conversion.target or {}
    if job_folder(conversion) is not None:
        return importlib.import_module("delve.conversions.thorough").restored(services, conversion)
    if conversion.kind == "fixit":
        return importlib.import_module("delve.conversions.fixit").restored(services, conversion)
    if conversion.kind == "generate":
        if not target.get("request"):
            return None
        scale = target.get("scale") if target.get("scale") in SCALES else None
        return _generate_start(services, target["request"], scale, _answers(target.get("answers")))
    upload = Path(target["upload"]) if conversion.kind == "pdf" and target.get("upload") else None
    if upload is None or not upload.is_file():
        return None
    return _pdf_start(services, upload, _book_maps(services) if target.get("book_maps") else None)


def job_folder(conversion: Conversion) -> Workspace | None:
    """A thorough job's folder; None for any other job."""
    target = conversion.target or {}
    if not target.get("thorough") or not target.get("folder"):
        return None
    return Workspace(Path(target["folder"]))


def _open(
    services: ConversionServices,
    kind: ConversionKind,
    title: str,
    mode: ConversionMode,
    *,
    target: dict[str, Any] | None = None,
    comments: str = "",
) -> _Live:
    """The new job's row, or `ConversionRunning`. No `await` here, so two starts can't both pass the check."""
    _check_mode(mode)
    hold_slot(services)
    try:
        conversion = services.storage.conversions.create(kind, title, mode, target=target, comments=comments)
    except ValueError:
        raise ConversionRunning(services.storage.conversions.running()) from None
    live = _Live(conversion)
    services.live[conversion.id] = live
    return live


def hold_slot(services: ConversionServices) -> None:
    """`ConversionRunning` while a job of this process runs; else the orphans are closed, so the slot is free. A
    paused job runs nothing and holds no slot."""
    running = next(iter(services.live.values()), None)
    if running is not None:
        raise ConversionRunning(services.storage.conversions.get(running.conversion.id))
    close_orphans(services.storage)


def _launch(services: ConversionServices, live: _Live, start: _Start) -> Conversion:
    live.upload = start.upload
    return _run(services, live, start.work(live), cleanup=start.cleanup, then=start.then)


def _run(
    services: ConversionServices,
    live: _Live,
    work: Coroutine[Any, Any, None],
    cleanup: Callable[[], None] = lambda: None,
    then: Callable[[Conversion], Awaitable[Any]] | None = None,
) -> Conversion:
    live.task = asyncio.create_task(_job(services, live, work, cleanup, then))
    return live.conversion


async def _job(
    services: ConversionServices,
    live: _Live,
    work: Coroutine[Any, Any, None],
    cleanup: Callable[[], None],
    then: Callable[[Conversion], Awaitable[Any]] | None = None,
) -> None:
    """Run the job's work; a job always ends, as done (the work's own end), failed with its reason, or cancelled,
    or pauses (a thorough job paused by hand, `live.pausing`). `then` starts once a done job is no longer running,
    as a task of its own, so waiting for the job doesn't wait for it; it holds the queue until it ends. Then the
    next queued job starts."""
    try:
        await work
    except asyncio.CancelledError:  # a cancel wins over a pause it raced
        if live.cancelled:
            _end(services, live.conversion, "cancelled", live=live)
        elif live.pausing:
            _paused_by_hand(services, live)
        else:
            raise  # Delve is stopping: the row stays running, and the next start closes it
    except ReadStopped:  # the reading saw the cancel (or the pause) first
        if live.cancelled or not live.pausing:
            _end(services, live.conversion, "cancelled", live=live)
        else:
            _paused_by_hand(services, live)
    except Exception as error:  # noqa: BLE001 (a job always ends, never a hung progress bar)
        _end(services, live.conversion, "failed", str(error) or type(error).__name__, live=live)
    finally:
        services.live.pop(live.conversion.id, None)
        cleanup()
    if then is None or live.conversion.status != "done":
        start_queue(services)
        return
    done = live.conversion

    async def follow_up() -> None:
        try:
            await then(done)
        except Exception as error:  # the module is made: what follows it failing is a warning
            log.exception("The follow-up of conversion %s failed", done.id)
            reason = str(error) or type(error).__name__
            message = f"What follows the conversion failed: {reason}."
            _warn_done(services, done.id, Warning(FOLLOW_UP_FAILED, message, None))
        finally:
            services.holds.discard(asyncio.current_task())  # type: ignore[arg-type]
            start_queue(services)

    task = asyncio.create_task(follow_up())
    services.follow_ups.add(task)
    services.holds.add(task)
    task.add_done_callback(services.follow_ups.discard)


def _warn_done(services: ConversionServices, conversion_id: str, warning: Warning) -> Conversion:
    """The done job with `warning` added and published: what failed after its module was made, which no `_end` can
    record any more."""
    conversion = services.storage.conversions.get(conversion_id)
    assert conversion is not None  # a done job is never deleted while its follow-up runs
    warnings = [*conversion.warnings, asdict(warning)]
    conversion = services.storage.conversions.save(replace(conversion, warnings=warnings))
    services.publish("conversion", _event(conversion))
    return conversion


def _paused_by_hand(services: ConversionServices, live: _Live) -> None:
    """A thorough job the organiser paused: its folder records why, and it is `paused`, its pieces in progress
    neither done nor a failed attempt (they are started over at the resume)."""
    if live.conversion.status != "running":
        return
    folder = job_folder(live.conversion)
    if folder is not None and folder.exists():
        folder.pause(PAUSED_BY_ORGANISER)
    live.conversion = services.storage.conversions.save(replace(live.conversion, status="paused", error=None))
    services.publish("conversion", _event(live.conversion))


def _end(
    services: ConversionServices,
    conversion: Conversion,
    status: ConversionStatus,
    error: str | None = None,
    *,
    live: _Live | None = None,
) -> Conversion:
    """End the job as `status`; `live`, when this process runs it, holds the ended row from here. A job this
    process ran that has ended already (a cancel after its module was made) stays as it ended."""
    if live is not None and live.conversion.status != "running":
        return live.conversion
    ended = services.storage.conversions.save(replace(conversion, status=status, error=error))
    if live is not None:
        live.conversion = ended
    services.publish("conversion", _event(ended))
    return ended


def progress_for(services: ConversionServices, live: _Live) -> Progress:
    """Store and publish a step; once the job has ended, a late call changes nothing."""

    def progress(step: str, done: int, total: int) -> None:
        if live.conversion.status != "running":
            return
        live.conversion = services.storage.conversions.save(replace(live.conversion, step=step, done=done, total=total))
        services.publish("conversion", _event(live.conversion))

    return progress


def _spend(services: ConversionServices, live: _Live | None) -> Callable[[Usage], None] | None:
    """What hears a call's usage for the job `live`: its cost is added to the job's `cost_usd` and stored at once, so
    a reload sees what the job cost so far. None without a job; once the job has ended, a late call changes nothing."""
    if live is None:
        return None

    def spend(usage: Usage) -> None:
        if usage.cost_usd is None or live.conversion.status != "running":
            return
        cost = (live.conversion.cost_usd or 0.0) + usage.cost_usd
        live.conversion = services.storage.conversions.save(replace(live.conversion, cost_usd=cost))

    return spend


def _complete(services: ConversionServices, live: _Live | None = None) -> Complete:
    """A side call of Preferences' `conversion` job, with `CONVERSION_TIMEOUT` per call; its cost goes to `live`."""
    return complete_with(services, live, services.conversion, CONVERSION_TIMEOUT)


def complete_with(services: ConversionServices, live: _Live | None, choice_for: ChoiceFor, timeout: float) -> Complete:
    """A side call of the provider and choice `choice_for` gives (a job of Preferences' own, such as `novel`), with
    `timeout` per call; its cost goes to `live`, as every job's does, and its prompt holds the job's comments."""
    provider, choice = choice_for()
    on_usage = _spend(services, live)

    async def complete(prompt: str) -> str:
        prompt = commented(live, prompt)
        return await provider.side_call(prompt, choice, timeout=timeout, on_usage=on_usage)

    return complete


def lasting(error: Exception) -> bool:
    """Whether asking again can't mend `error`: the usage limit (as the provider says it, or as a `Halt` already) or
    an answer the content filter blocked. Those are the caller's to surface, at once."""
    said = str(error)
    return isinstance(error, Halt) or USAGE_LIMIT.search(said) is not None or FILTERED.search(said) is not None


async def retried[T](call: Callable[[], Awaitable[T]], delays: Sequence[float]) -> T:
    """`call`'s answer, asked again after each of `delays` while it fails; the last failure, or one that is
    `lasting`, is raised."""
    for delay in delays:
        try:
            return await call()
        except Exception as error:
            if lasting(error):
                raise
        await asyncio.sleep(delay)
    return await call()


def look_for(services: ConversionServices, live: _Live | None = None) -> Look:
    """A vision call of Preferences' `conversion` job, with `CONVERSION_TIMEOUT` per call; its cost goes to `live`."""
    provider, choice = services.conversion()
    on_usage = _spend(services, live)

    async def look(prompt: str, image: bytes, media_type: str) -> str:
        return await provider.vision_call(
            commented(live, prompt), image, media_type, choice, timeout=CONVERSION_TIMEOUT, on_usage=on_usage
        )

    return look


def commented(live: _Live | None, prompt: str) -> str:
    """`prompt` with the comments of the job `live` (`with_comments`); as it is without a job."""
    return prompt if live is None else with_comments(prompt, live.conversion.comments)


# ----- the jobs -----


async def _convert_pdf(services: ConversionServices, live: _Live, path: Path) -> None:
    progress = progress_for(services, live)
    complete = _complete(services, live)
    look = look_for(services, live)
    progress("reading", 0, 0)
    loop = asyncio.get_running_loop()

    def page_read(done: int, total: int) -> None:  # in the reading thread: the progress runs on the loop
        loop.call_soon_threadsafe(progress, "reading", done, total)

    try:
        book = await asyncio.to_thread(
            read_pdf, path, ocr=services.ocr, should_stop=live.stop.is_set, progress=page_read
        )
    except asyncio.CancelledError:
        live.stop.set()  # Delve is stopping: the thread stops at its next page too
        raise
    book = await classify_pages(book, look, progress)
    title = live.conversion.title
    # A chunk's call is asked again after a transient failure; the others' failures are warnings already.
    draft = lambda prompt: retried(lambda: complete(prompt), RETRY_DELAYS)
    converted = await convert_book(book, title, complete, progress, draft=draft)
    page_image = lambda number: asyncio.to_thread(render_page, path, number)
    converted.source, filled = await fill_gaps(converted.source, book, look, page_image, progress=progress)
    converted.warnings += filled
    await _sketch_maps(converted, book, complete, progress, title)
    sha = await asyncio.to_thread(services.storage.blobs.put_file, path, "application/pdf")
    size = path.stat().st_size
    original = Attachment(SOURCE_PDF, "application/pdf", sha, size, "The original PDF", "gm", "source")
    converted.source = replace(converted.source, attachments=[*converted.source.attachments, original])
    await _make_module(services, live, converted, title, blobs=(sha,))


async def _generate(
    services: ConversionServices, live: _Live, request: str, scale: Scale | None, answers: list[Answer]
) -> None:
    """A module from the request: scoped first when it came without a scale, then written in one call (a module) or
    in steps (a campaign, `campaign.generate_campaign`). The organiser's answers to the scope questions go into every
    prompt, and into the module's making notes as the job's first questions."""
    progress = progress_for(services, live)
    if scale is None:
        progress("scoping", 0, 1)
        scale = (await scope_request(request, _complete(services, live), game=services.game)).scale
        target = {**(live.conversion.target or {}), "scale": scale}
        live.conversion = services.storage.conversions.save(replace(live.conversion, target=target))
        progress("scoping", 1, 1)
    asked = with_answers(request, answers)
    if scale == "campaign":
        converted = await generate_campaign(asked, _complete(services, live), progress, game=services.game)
    elif scale == "sandbox":
        converted = await generate_sandbox(asked, _complete(services, live), progress, game=services.game)
    else:
        complete = complete_with(services, live, services.conversion, GENERATE_TIMEOUT)
        converted = await generate_module(asked, complete, progress)
    target = live.conversion.target or {}
    if target.get("pictures"):
        converted = await _with_pictures(services, live, converted, target["pictures"], bool(target.get("owner")))
    scoped = [Question("", a.text, a.default) for a in answers]
    later = converted.questions
    converted.questions = [replace(q, id=f"q{n}") for n, q in enumerate([*scoped, *later], start=1)]
    texts = converted.source.texts
    await _make_module(services, live, converted, texts[0].title if texts else live.conversion.title)
    if answers and live.conversion.module_id is not None:
        given = {f"q{n}": a.answer for n, a in enumerate(answers, start=1) if a.answer.strip()}
        try:
            answer_questions(services.storage, live.conversion.id, given, [])
        except Exception as error:  # the job is done: raised, this would be lost (`_end` keeps a done job)
            log.exception("The answers of conversion %s weren't noted", live.conversion.id)
            reason = str(error) or type(error).__name__
            message = f"The answers to the questions weren't written into the making notes: {reason}."
            live.conversion = _warn_done(services, live.conversion.id, Warning(ANSWERS_NOT_NOTED, message, None))


async def _with_pictures(
    services: ConversionServices, live: _Live, converted: Converted, limit: int, owner: bool
) -> Converted:
    """The generated module with at most `limit` painted handouts (DEL-347), inside the job so that the module is never
    played before they exist. Whatever goes wrong is a warning: the module stands without them."""
    progress = progress_for(services, live)
    progress("painting", 0, 1)
    if services.images is None:
        return _not_painted(converted, f"No provider does the {Job.IMAGE_SCENE} job.")
    if not owner and await asyncio.to_thread(services.image_paid, Job.IMAGE_SCENE):
        return _not_painted(converted, "Only the owner may paint with a paid image model.")
    complete = complete_with(services, live, services.conversion, GENERATE_TIMEOUT)
    planned, warnings = await plan_pictures(converted.source, limit, complete)
    style = stored_style_text(services.storage.settings.load())

    async def paint(picture: Planned) -> tuple[bytes, str]:
        provider, choice = services.images(Job.IMAGE_SCENE)
        result = await provider.generate(
            ImageRequest(Job.IMAGE_SCENE, picture.brief, choice, style=style, aspect=picture.aspect)
        )
        if not isinstance(result, ImageFile):
            raise TypeError("the provider answered no picture")
        return result.data, result.mime

    pictures, failed = await paint_pictures(planned, paint, progress)
    source = replace(converted.source, attachments=[*converted.source.attachments, *(a for a, _ in pictures)])
    return replace(
        converted,
        source=source,
        pictures=[*converted.pictures, *pictures],
        warnings=[*converted.warnings, *warnings, *failed],
    )


def _not_painted(converted: Converted, reason: str) -> Converted:
    warning = Warning(PICTURE_NOT_PAINTED, f"The pictures weren't painted: {reason}", None)
    return replace(converted, warnings=[*converted.warnings, warning])


async def _make_module(
    services: ConversionServices,
    live: _Live,
    converted: Converted,
    title: str,
    blobs: tuple[str, ...] = (),
    doubts: list[dict[str, Any]] | None = None,
    complete: Complete | None = None,
) -> None:
    """The module, in one transaction with the job's end, so it is made whole or not at all. Its pictures' blobs are
    written first, off the event loop, and linked in the transaction with `blobs`, already stored. A thorough job's
    `doubts` are stored with its questions. Its metadata's empty fields are read from its text first
    (`complete_metadata`, with `complete`, the conversion's call when None); a failure there is a warning, never a
    stop, but a `Halt` (a thorough job's pause at the usage limit)."""
    storage = services.storage
    metadata, unread = await complete_metadata(
        converted.metadata, converted.source.texts, title, complete or _complete(services, live)
    )
    converted = replace(converted, metadata=metadata, warnings=[*converted.warnings, *unread])
    pictures = await asyncio.to_thread(
        lambda: [storage.blobs.put(data, attachment.type) for attachment, data in converted.pictures]
    )
    with storage.transaction():
        # A module generated from a prompt is homebrew; one converted from a book isn't (DEL-226).
        made = homebrew(converted.metadata) if live.conversion.kind == "generate" else converted.metadata
        module = storage.modules.create(title, made, draft=live.conversion.mode == "draft")
        for module_map in converted.maps:
            storage.modules.put_map(module.id, module_map)
        for sha in [*blobs, *pictures]:
            storage.blobs.link(module.id, ATTACHMENT, sha)
        save_source(storage, module.id, converted.source)
        live.conversion = storage.conversions.save(
            replace(
                live.conversion,
                title=title,
                status="done",
                module_id=module.id,
                warnings=[asdict(w) for w in converted.warnings],
                questions=_asked(converted, doubts),
            )
        )
    services.publish("conversion", _event(live.conversion))


# ----- the questions -----

MAKING_NOTES = "making-notes"
"""The `gm` text the answers to a made module's questions are written into."""
MAKING_NOTES_TITLE = "Notes from making this module"


def _asked(converted: Converted, doubts: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
    """What the job stores of the questions asked while making the module, and of a thorough job's `doubts` (the
    key is there only for one); None when there were neither."""
    if not converted.questions and doubts is None:
        return None
    asked = {"questions": [{**asdict(q), "answer": None} for q in converted.questions], "remarks": []}
    return asked if doubts is None else {**asked, "doubts": doubts}


def _entry(conversion: Conversion) -> dict[str, Any]:
    """A job's questions and remarks, and the keys of those closed (`closed`); a thorough job's also its `doubts`,
    whether they were told to the DM (`told`) and what the job cost (thorough conversion Task 8)."""
    asked = conversion.questions or {}
    entry = {
        "conversion_id": conversion.id,
        "questions": asked.get("questions", []),
        "remarks": asked.get("remarks", []),
        "closed": list(conversion.closed),
    }
    if "doubts" in asked:
        entry |= {"doubts": asked["doubts"], "told": bool(asked.get("told")), "cost_usd": conversion.cost_usd}
    return entry


def module_questions(storage: Storage, module_id: str) -> list[dict[str, Any]]:
    """`[{conversion_id, questions, remarks}]` for each of the module's jobs that holds questions, newest first, from
    every job of the module (`conversions.for_module`), however many later conversions there were."""
    return [_entry(c) for c in storage.conversions.for_module(module_id) if c.questions]


def _notes(entries: list[dict[str, Any]]) -> str:
    """The `MAKING_NOTES` text: each question with its answer, else "Assumed: <default>", then the remarks."""
    lines = [f"# {MAKING_NOTES_TITLE}", ""]
    for question in [q for entry in entries for q in entry["questions"]]:
        answer = question["answer"] or f"Assumed: {question['default']}"
        lines += [f"- **{question['text']}** {answer}"]
    remarks = [remark for entry in entries for remark in entry["remarks"]]
    if remarks:
        lines += ["", "## Remarks", ""]
        for remark in remarks:
            lines += [remark, ""]
    doubts = [doubt for entry in entries if entry.get("told") for doubt in entry["doubts"]]
    if doubts:
        lines += ["", "## Doubts from the conversion", ""]
        lines += [_doubt_line(doubt) for doubt in doubts]
    return "\n".join(lines).rstrip() + "\n"


def _doubt_line(doubt: dict[str, Any]) -> str:
    """`- **house** (pages 3, 4; checker-flag): Key 3 covers 80%.`"""
    pages = ", ".join(str(page) for page in doubt.get("pages") or [])
    where = f"pages {pages}; " if len(doubt.get("pages") or []) > 1 else f"page {pages}; " if pages else ""
    return f"- **{doubt['part']}** ({where}{doubt['kind']}): {doubt['text']}"


def answer_questions(
    storage: Storage, conversion_id: str, answers: dict[str, str], remarks: Sequence[str]
) -> dict[str, Any]:
    """Store the answers (by question id; an empty one is none) and the remarks on the job, a thorough job's doubts
    kept, and write all of its
    module's into the `MAKING_NOTES` text, made after the module's texts or replaced where it is. Answers the job's
    `{conversion_id, questions, remarks}`. `KeyError` for a job that asked nothing or whose module is gone,
    `ValueError` for an answer to a question it didn't ask."""
    conversion = storage.conversions.get(conversion_id)
    if conversion is None or not conversion.questions or conversion.module_id is None:
        raise KeyError(conversion_id)
    if storage.modules.get(conversion.module_id) is None:
        raise KeyError(conversion.module_id)
    asked = conversion.questions["questions"]
    unknown = sorted(set(answers) - {q["id"] for q in asked})
    if unknown:
        raise ValueError(f"No question {', '.join(unknown)} was asked.")
    questions = [{**q, "answer": (answers.get(q["id"]) or "").strip() or None} for q in asked]
    kept = [remark.strip() for remark in remarks if remark.strip()]
    with storage.transaction():
        asked = {**conversion.questions, "questions": questions, "remarks": kept}  # a thorough job's doubts stay
        conversion = storage.conversions.save(replace(conversion, questions=asked))
        _write_notes(storage, conversion.module_id)
    return _entry(conversion)


def close_items(storage: Storage, conversion_id: str, closed: Sequence[str]) -> dict[str, Any]:
    """Close the job's questions and doubts named by `closed` (`question:<id>`, `doubt:<index>`), and reopen the
    others: stored on the job, de-duplicated in the order given. Nothing else changes, the notes neither. Answers the
    job's entry; `KeyError` for a job that asked nothing, `ValueError` for a key that names no question or doubt of
    it."""
    conversion = storage.conversions.get(conversion_id)
    if conversion is None or not conversion.questions:
        raise KeyError(conversion_id)
    unknown = [key for key in closed if key not in _item_keys(conversion)]
    if unknown:
        raise ValueError(f"{', '.join(unknown)} names no question or doubt of this conversion.")
    return _entry(storage.conversions.set_closed(conversion_id, closed))


def _item_keys(conversion: Conversion) -> set[str]:
    asked = conversion.questions or {}
    questions = {f"question:{q['id']}" for q in asked.get("questions", [])}
    return questions | {f"doubt:{n}" for n in range(len(asked.get("doubts") or []))}


def tell_dm(storage: Storage, conversion_id: str) -> dict[str, Any]:
    """Pass a thorough job's doubts to the DM: they are written into its module's `MAKING_NOTES` text, under
    "Doubts from the conversion", and stay there when the questions are answered again (thorough conversion Task 8).
    By default a job's doubts are the organiser's alone. Answers the job's entry; `KeyError` for a job with no
    doubts or whose module is gone."""
    conversion = storage.conversions.get(conversion_id)
    if conversion is None or "doubts" not in (conversion.questions or {}) or conversion.module_id is None:
        raise KeyError(conversion_id)
    if storage.modules.get(conversion.module_id) is None:
        raise KeyError(conversion.module_id)
    with storage.transaction():
        conversion = storage.conversions.save(replace(conversion, questions={**conversion.questions, "told": True}))
        _write_notes(storage, conversion.module_id)
    return _entry(conversion)


def _write_notes(storage: Storage, module_id: str) -> None:
    """The module's `MAKING_NOTES` text from all of its jobs' entries, made after its texts or replaced where it is."""
    source = load_source(storage, module_id)
    notes = TextDoc(MAKING_NOTES, MAKING_NOTES_TITLE, "gm", None, _notes(module_questions(storage, module_id)))
    texts = [notes if t.id == MAKING_NOTES else t for t in source.texts]
    if notes not in texts:
        texts.append(notes)
    save_source(storage, module_id, replace(source, texts=texts))


# ----- the sketches -----


def _plate_words(title: str) -> set[str]:
    return {w for w in re.findall(r"\w+", title.casefold()) if len(w) >= PLATE_WORD and w not in PLATE_STOP}


def plate_matches(text_title: str, plate_title: str) -> int:
    """How many words of `PLATE_WORD` letters or more a text's title and a map plate's title share, casefolded and
    without `PLATE_STOP`: "PART ONE — THE HAUNTED HOUSE" and "Haunted House" share 2."""
    return len(_plate_words(text_title) & _plate_words(plate_title))


def _plate_titles(book: PdfBook) -> list[str]:
    """The titles of the book's map pages: the plate's title, else its OCR's."""
    titles = (page.plate_title or map_title(page) for page in book.pages if page.map_page and page.pictures)
    return [title for title in titles if title]


async def _sketch_maps(
    converted: Converted, book: PdfBook, complete: Complete, progress: Progress, title: str
) -> None:
    """Sketch a map for every text with `SKETCHED_KEYS` keyed headings or more that no map page of the book is titled
    like (`plate_matches`), which then links its headings to it: a text with a map page gets that page drafted once
    the module is made. Its source starts with `SKETCHED` and `NO_BOOK_MAP`. It is named after its text, else, for a
    text titled by the module (`title`), `UNTITLED_SKETCH`. The first map drawn is the default. A text whose keys
    repeat (two levels, each keyed from 1) isn't sketched: it gets a `map-not-drawn` warning."""
    texts = list(converted.source.texts)
    plates = _plate_titles(book)
    keyed = []
    for n, text in enumerate(texts):
        rooms = _keyed_rooms(text)
        if len(rooms) < SKETCHED_KEYS or any(plate_matches(text.title, plate) > 0 for plate in plates):
            continue
        if len({key for key, _ in rooms}) < len(rooms):
            converted.warnings.append(Warning("map-not-drawn", REPEATED_KEYS, f"text:{text.id}"))
            continue
        keyed.append((n, rooms))
    progress("maps", 0, len(keyed))
    used = {module_map.name for module_map in converted.maps}
    for done, (n, rooms) in enumerate(keyed, start=1):
        base = UNTITLED_SKETCH if texts[n].title == title else texts[n].id
        name = unique(base, used)
        source, warnings = await sketch_map(name, rooms, complete, page=_picture_page(book, rooms[0][1]))
        converted.warnings += warnings
        if source is not None:
            converted.maps.append(ModuleMap(name, "map", f"{SKETCHED} {NO_BOOK_MAP}\n{source}", not converted.maps))
            texts[n] = replace(texts[n], map=name)
        progress("maps", done, len(keyed))
    converted.source = replace(converted.source, texts=texts)


def _keyed_rooms(text: TextDoc) -> list[tuple[str, str]]:
    """The text's keyed headings as `(key, its heading and paragraphs)`: up to the next heading of its level or
    higher."""
    doc = parse_text(text.markdown)
    lines = doc.body.splitlines()
    # `Section.line` counts from the top of the file, front matter included; the body starts after it (DEL-162).
    front = split_front_matter(text.markdown)[2]
    rooms = []
    for n, section in enumerate(doc.sections):
        if not section.keyed:
            continue
        end = next((s.line - 1 - front for s in doc.sections[n + 1 :] if s.level <= section.level), len(lines))
        rooms.append((section.key, "\n".join(lines[section.line - 1 - front : end]).strip()))
    return rooms


def _picture_page(book: PdfBook, room: str) -> int | None:
    """The picture page nearest to the page `room` (a heading and its paragraphs) is on, to compare a sketch with:
    a full-page picture if there is one, else any picture. None when there is no picture, or the room isn't found."""
    heading = parse_text(room).sections[0]
    want = " ".join(heading.title.lower().split())
    page = next((p.number for p in book.pages if want and want in " ".join(p.text.lower().split())), None)
    full = [p.number for p in book.pages if any(picture.area >= 1.0 for picture in p.pictures)]
    pages = full or [p.number for p in book.pages if p.pictures]
    if page is None or not pages:
        return None
    return min(pages, key=lambda number: (abs(number - page), number))
