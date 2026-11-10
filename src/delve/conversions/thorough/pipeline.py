"""The stages of a thorough conversion (thorough conversion Task 6; spec "How it works"), run on its job folder.

`run_thorough` runs them in order, each skipped once `state.json` records it done, so a resume starts at the first
unfinished stage, and within it at the first unfinished piece (`pieces.run_piece`). What each stage reads and writes
in the folder (the names are `workspace`'s, the briefs' `prompts/thorough/common.md`):

1. `reading` (code): `book.pdf` read as the quick conversion reads it (`read_pdf`), into `book.json` and `pictures/`;
   every page to `pages/` (`p-NNN.png` at 150 dpi, `ocr-NNN.txt`), the pages with pictures to `scan/` at 200 dpi.
2. `classifying` (a look per doubtful picture page, `classify_pages`): `book.json` again, and `classes.json`.
3. `drafting` (side calls): `convert_book`'s chunk step, as it is, without its entities, pictures or sketches; one
   draft per text in `draft/` (`NN-<text id>.md`, in the book's order), and a copy in `drafted/`.
4. `sorting`: the piece `sort` (`sort.md`) writes `parts.json`, `original.md`, `draft/<part id>.md` and `keys/`. Each
   attempt starts from `drafted/`. Skipped: each draft is a part of its own, a chapter, with a doubt.
5. `cleaning`: a piece `clean-<n>` per group of parts holding at most `CLEAN_PAGES` pages of text (`clean_groups`),
   writing `clean/<part id>.md`; then `sort-orphans` when a piece left `clean/*-orphans.md`. A skipped clean keeps
   its parts' drafts, each with a doubt, "not cleaned".
6. `tracing`: a piece `trace-<map name>` per map in `parts.json`, writing `maps/<name>.dmap`, which must parse, and
   `maps/<name>.exits.json` (and the `.svg` and `.png` its `qa mapcheck` draws). A skipped trace is sketched from its part's room key (`sketch_map`, side calls), named
   as the map, and so is a part with `SKETCHED_KEYS` keyed headings or more and no map, named after the part, "no
   map in the book". A sketch starts with `runner.SKETCHED`, is listed in `sketches.json` and is a doubt
   (`sketched-map`). Review focus 2: a book with no map pages traces nothing, and every keyed part is sketched.
7. `joining` (code, `qa.join`): `joined/`, its guessed landings as doubts.
8. `describing`: the book's pictures cut whole into `art/` (`cut_art`), then the piece `describe`, writing
   `art/descriptions.json`.
9. `entities` (side calls): `convert_book`'s entity step on the cleaned texts, merged and deduplicated, into
   `entities.json`.
10. `making`: `make.build_source` (Task 7) and the module made in one transaction with the job's end, its doubts
    (`doubts.gather`) on the job; then the folder is removed.

Every agent is a `claude -p` session in the folder, run by `ConversionServices.agent` (`claude_cli.agent.run_agent`,
which the app hands in, as it hands in the DM provider), at most `THOROUGH_AGENTS` at once, and every agent, side
call and look uses the same choice: Preferences' `conversion.thorough` job (`ConversionServices.thorough`). Each session's cost goes to the job as it ends, and so does each side call's. The
code stages' warnings are kept in `warnings.json` and stored on the job with the module.
Every agent's brief, side call and look ends with the organiser's comments on the PDF form, when there are any
(`runner.commented`, table voice and fixes Task F1).

A piece whose session was stopped halfway starts again from a clean slate (owner decision, DEL-92): its own files, as
each stage's `_piece` call names them (`owns`), its `work/<piece>/` and `doubts/<piece>.json` are removed before the
next session begins, and never another piece's files, the job's inputs or a finished piece's outputs. `sort-orphans`
edits the cleaning pieces' files, so it owns none: Delve keeps `clean/` as the cleaning left it in `cleaned/` before
its first session, and a restarted `sort-orphans` starts from that copy.

The job holds the one running slot, as every job does: other jobs are refused while it runs."""

from __future__ import annotations

import asyncio
import hashlib
import io
import re
import shlex
import shutil
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import asdict, dataclass, field, replace
from importlib import resources
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PIL import Image

from delve.conversions import runner
from delve.conversions.qa.join import join_folder
from delve.conversions.qa.pages import PAGE_DPI, SCAN_DPI, page_image, page_text, render_pages
from delve.conversions.thorough import pieces
from delve.conversions.thorough.make import build_source
from delve.conversions.thorough.pieces import AgentResult, PieceOutcome, run_piece
from delve.conversions.thorough.workspace import (
    ART,
    BOOK,
    BOOK_JSON,
    CLASSES,
    CLEAN,
    CLEANED,
    DOUBTS,
    DRAFT,
    DRAFTED,
    ENTITIES,
    JOINED,
    KEYS,
    MAPS,
    ORIGINAL,
    PAGES,
    PARTS,
    PICTURES,
    SCAN,
    SKETCHES,
    WARNINGS,
    WORK,
    Workspace,
    qa_path,
)
from delve.dm.claude_cli.stream import RESETS, USAGE_LIMIT
from delve.maps.dsl import validate
from delve.maps.sources import parse_source
from delve.modules.books.classify import classify_pages, cut
from delve.modules.books.convert import (
    Converted,
    _convert_chunks,
    _entities,
    _numbers_warning,
    _short_warning,
    _texts,
    _titled,
    chapter_titles,
    chunk_pages,
    front_pages,
)
from delve.modules.books.dedupe import dedupe_entities
from delve.modules.books.pdf import HandoutBox, PdfBook, PdfPage, Picture, read_pdf, render_page
from delve.modules.books.sketch import sketch_map
from delve.modules.dscn import parse_text
from delve.modules.source import Attachment, TextDoc, Warning
from delve.modules.text import unique

if TYPE_CHECKING:
    from delve.conversions.runner import ConversionServices, _Live

__all__ = ["CLEAN_PAGES", "STAGES", "THOROUGH_AGENTS", "clean_groups", "cut_art", "run_thorough"]

STAGES = tuple(stage for (stage,) in runner.STEPS["pdf-thorough"])
THOROUGH_AGENTS = 4
"""Agent sessions at once (the hand QA ran 3 to 6)."""
CLEAN_PAGES = 25
"""The most pages of text one cleaning piece is given; a part longer than that is a piece alone."""
DRAFT_CALLS = 3
"""Side calls at once while drafting and reading the entities, as `convert_book`'s."""
DRAFT_RETRY_DELAYS = (10.0, 30.0)
"""The waits before a failed draft call is tried again (an overloaded API, a claude that exited 1); after the last,
the error pauses the job. The usage limit isn't tried again: it pauses the job until its reset."""
FILTERED = runner.FILTERED
"""The API's refusal of an answer that repeats a published text at length: asked again, it is refused again."""
CONTENT_FILTERED = (
    "The API's content filter blocked Claude's Markdown for {count} part(s) of the book, as it repeats the book's "
    "text at length; the text read from the PDF is kept there instead (see the pages the other warnings name)."
)
CHUNKS = "chunks"
"""Each draft call's answer, `<sha256 of the prompt>.md`, kept as it comes: a resumed drafting sends only the chunks
that have none (Temple of Elemental Evil's 83 chunks started over at every resume, 2026-10-24)."""
STRIP_RATIO = 5.0
"""A picture this many times longer than it is wide, or wider than long, is a strip (a border, a line of text) and
isn't offered to the describing agent."""

NO_AGENT = "Thorough conversions need the Claude CLI, and it isn't available."
NOT_SORTED = "The sort didn't finish: each draft is a part of its own, unkeyed. Check the texts' order and keys."
NOT_CLEANED = "The text of {title} was not cleaned: it is the sorted draft. Check it against pages {pages}."
NO_MAP = "There is no map in the book for {title}: the map {name} is sketched from its room key, an invented layout."
TRACE_SKIPPED = (
    "The book's map on page {page} couldn't be traced: the map {name} is sketched from the room key of {title}, an "
    "invented layout. Draw it from the page."
)
NOT_SKETCHED = "The map {name} couldn't be sketched from the room key of {title}: {reason}"
REPEATED = "The keys repeat in {title}, so no map was sketched for it."
TRACE_FAILED_LINE = "The book's map on page {page} couldn't be traced."
"""What a skipped trace's sketch says after `runner.SKETCHED`; a part with no map says `runner.NO_BOOK_MAP`."""

_ID = re.compile(r"^[a-z0-9][a-z0-9-]*$")


async def run_thorough(services: ConversionServices, live: _Live, ws: Workspace) -> None:
    """Run the stages not yet done on the job folder `ws`; the last makes the module and ends the job as done.
    Without an agent runner (no Claude CLI) nothing runs: the error pauses the job, its folder kept."""
    if services.agent is None:
        raise RuntimeError(NO_AGENT)
    job = _Job(services, live, ws)
    stages: dict[str, Callable[[], Awaitable[None]]] = {
        "reading": job.read,
        "classifying": job.classify,
        "drafting": job.draft,
        "sorting": job.sort,
        "cleaning": job.clean,
        "tracing": job.trace,
        "joining": job.join,
        "describing": job.describe,
        "entities": job.entities,
        "making": job.make,
    }
    for stage in STAGES:
        if ws.is_stage_done(stage):
            continue
        job.progress(stage, 0, 0)
        await stages[stage]()
        if stage != "making":  # the making removes the folder
            ws.stage_done(stage)


def clean_groups(parts: Sequence[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """The parts in groups, in order, each with at most `CLEAN_PAGES` pages of text (`pages`, first and last); a part
    with more is a group alone."""
    groups: list[list[dict[str, Any]]] = []
    size = 0
    for part in parts:
        pages = _page_count(part)
        if groups and size + pages <= CLEAN_PAGES:
            groups[-1].append(part)
            size += pages
        else:
            groups.append([part])
            size = pages
    return groups


def _pages(part: dict[str, Any]) -> list[int]:
    pages = part.get("pages")
    if isinstance(pages, list) and len(pages) == 2 and all(isinstance(p, int) for p in pages) and pages[0] <= pages[1]:
        return list(range(pages[0], pages[1] + 1))
    return []


def _page_count(part: dict[str, Any]) -> int:
    return max(len(_pages(part)), 1)


def _part_lines(parts: Iterable[dict[str, Any]]) -> str:
    """The `{parts}` of a brief: "- `house`: The Haunted House, pages 4 to 9, keys `^\\d+$`"."""
    lines = []
    for part in parts:
        pages = _pages(part)
        where = f"pages {pages[0]} to {pages[-1]}" if pages else "pages not known"
        keys = f"keys `{part['key_pattern']}`" if part.get("key_pattern") else "unkeyed"
        lines.append(f"- `{part['id']}`: {part['title']}, {where}, {keys}")
    return "\n".join(lines)


def _map_lines(maps: Iterable[tuple[dict[str, Any], dict[str, Any]]]) -> str:
    """The `{maps}` of a brief: "- `house-ground-floor`: The House, Ground Floor (part `house`, page 10)"."""
    lines = []
    for part, listed in maps:
        level = f", the drawing under “{listed['level']}”" if listed.get("level") else ""
        title = listed.get("title") or part["title"]
        lines.append(f"- `{listed['name']}`: {title} (part `{part['id']}`, page {listed.get('page')}{level})")
    return "\n".join(lines)


def _brief(name: str, *, qa: Path, **values: str) -> str:
    """A piece's prompt: its brief, then `common.md`, the placeholders filled by plain replacement (the briefs hold
    JSON and `{#key}` braces), so its first line is `PIECE: <piece>`; `{qa}` is the `qa` wrapper's absolute path,
    as the agent's one Bash rule names it (`agent.agent_settings`)."""
    folder = resources.files("delve.modules.books").joinpath("prompts", "thorough")
    text = folder.joinpath(f"{name}.md").read_text("utf-8") + "\n\n" + folder.joinpath("common.md").read_text("utf-8")
    values = {**values, "qa": shlex.quote(str(qa.resolve()))}
    for key in ("piece", "parts", "maps", "qa"):
        text = text.replace("{" + key + "}", values.get(key, ""))
    return text


@dataclass
class _Job:
    """One run of the stages: the job, its folder, and the choice its agents and calls use."""

    services: ConversionServices
    live: _Live
    ws: Workspace
    book: PdfBook | None = None
    filtered: int = 0
    """The drafting's chunks whose answer the content filter blocked."""
    _progress: Callable[[str, int, int], None] = field(init=False)

    def __post_init__(self) -> None:
        choice_for = self.services.thorough or self.services.conversion
        self.provider, self.choice = choice_for()
        self._complete = runner.complete_with(self.services, self.live, choice_for, runner.CONVERSION_TIMEOUT)
        self.spend = runner._spend(self.services, self.live)
        self._progress = runner.progress_for(self.services, self.live)

    @property
    def root(self) -> Path:
        return self.ws.root

    @property
    def title(self) -> str:
        return self.live.conversion.title

    @property
    def qa(self) -> Path:
        """The `qa` wrapper the briefs name: `<data dir>/bin/qa`, beside the job folders."""
        return qa_path(self.root.parent.parent)

    def progress(self, stage: str, done: int, total: int) -> None:
        self._progress(stage, done, total)

    def _finished(self, stage: str, pieces: Sequence[str]) -> None:
        self.progress(stage, sum(self.ws.is_done(piece) for piece in pieces), len(pieces))

    async def complete(self, prompt: str) -> str:
        """A side call of the job; the usage limit pauses it (`_pausing`)."""
        return await _pausing(self._complete(prompt))

    async def look(self, prompt: str, image: bytes, media_type: str) -> str:
        """A vision call of the job; the usage limit pauses it (`_pausing`)."""
        prompt = runner.commented(self.live, prompt)
        return await _pausing(
            self.provider.vision_call(
                prompt, image, media_type, self.choice, timeout=runner.CONVERSION_TIMEOUT, on_usage=self.spend
            )
        )

    async def _agent(self, prompt: str) -> AgentResult:
        assert self.services.agent is not None  # run_thorough checked it
        return await self.services.agent(runner.commented(self.live, prompt), self.root, self.choice)

    async def _piece(
        self,
        piece: str,
        prompt: str,
        check: Callable[[], list[str]],
        outputs: Sequence[str],
        *,
        owns: Sequence[str] = (),
        before: Callable[[], None] | None = None,
        restart: Callable[[], None] | None = None,
    ) -> PieceOutcome:
        """Run the agent piece `piece`. `owns` are the paths in the folder (files or folders) only it writes; with its
        `work/<piece>/` and `doubts/<piece>.json` they are cleared, then `restart` runs, before a session that
        follows one stopped halfway (DEL-92). `before` runs before every attempt."""

        async def attempt() -> AgentResult:
            if before is not None:
                await asyncio.to_thread(before)
            return await self._agent(prompt)

        def clear() -> None:
            _clear(self.root, [*owns, f"{WORK}/{piece}", f"{DOUBTS}/{piece}.json"])
            if restart is not None:
                restart()

        return await run_piece(self.ws, piece, attempt, check, spend=self.spend, outputs=outputs, clear=clear)

    async def _each[T](self, items: Sequence[T], run: Callable[[T], Awaitable[None]]) -> None:
        """`run` each item, `THOROUGH_AGENTS` at once; the first that raises (the usage limit, a bug) cancels the
        rest, whose pieces are started over at the resume."""
        limit = asyncio.Semaphore(THOROUGH_AGENTS)

        async def one(item: T) -> None:
            async with limit:
                await run(item)

        tasks = [asyncio.create_task(one(item)) for item in items]
        try:
            await asyncio.gather(*tasks)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    def _warn(self, label: str, warnings: Sequence[Warning]) -> None:
        """Keep a code stage's warnings, by `label`, for the module's."""
        kept = self.ws.read_json(WARNINGS, {})
        kept[label] = [asdict(w) for w in warnings]
        self.ws.write_json(WARNINGS, kept)

    def _warnings(self) -> list[Warning]:
        return [Warning(**w) for listed in self.ws.read_json(WARNINGS, {}).values() for w in listed]

    def _book(self) -> PdfBook:
        if self.book is None:
            self.book = _load_book(self.ws)
        return self.book

    # ----- 1. reading, 2. classifying -----

    async def read(self) -> None:
        loop = asyncio.get_running_loop()

        def page_read(done: int, total: int) -> None:  # in the reading thread: the progress runs on the loop
            loop.call_soon_threadsafe(self.progress, "reading", done, total)

        try:
            book = await asyncio.to_thread(
                read_pdf,
                self.root / BOOK,
                ocr=self.services.ocr,
                should_stop=self.live.stop.is_set,
                progress=page_read,
            )
        except asyncio.CancelledError:
            self.live.stop.set()  # Delve is stopping: the thread stops at its next page too
            raise
        await asyncio.to_thread(_write_pages, self.root, book)
        await asyncio.to_thread(_save_book, self.ws, book)
        self._warn("reading", book.warnings)
        self.book = book

    async def classify(self) -> None:
        before = self._book()
        book = await classify_pages(before, self.look, self.progress)
        await asyncio.to_thread(_save_book, self.ws, book)
        self.ws.write_json(CLASSES, _classes(book))
        self._warn("classifying", book.warnings[len(before.warnings) :])
        self.book = book

    # ----- 3. drafting -----

    async def draft(self) -> None:
        """`convert_book`'s chunk step: the chunks' Markdown, cut into a text per chapter."""
        book = self._book()
        title = self.title
        chunks = chunk_pages(book.pages, title=title)
        chapters = chapter_titles(book.pages, title)
        progress = lambda step, done, total: self.progress("drafting", done, total)
        self.filtered = 0
        replies = await _convert_chunks(chunks, title, self._drafted, progress, asyncio.Semaphore(DRAFT_CALLS))
        answers = [_titled(chapters.get(chunk[0].number), a) for chunk, a in zip(chunks, replies, strict=True)]
        warnings: list[Warning] = []
        markdowns: list[str] = []
        front: list[str] = []
        apart = front_pages(book.pages)
        for chunk, answer in zip(chunks, answers, strict=True):
            if answer is None:
                continue
            if answer.short:
                warnings.append(_short_warning(chunk))
            if answer.changed:
                warnings.append(_numbers_warning(chunk, answer.changed))
            if all(page.number in apart for page in chunk) and not parse_text(answer.markdown).keyed():
                front.append(answer.markdown)
            else:
                markdowns.append(answer.markdown)
        if self.filtered:
            warnings.append(Warning("content-filtered", CONTENT_FILTERED.format(count=self.filtered), "book"))
        texts = _texts("\n\n".join(markdowns), title, front)
        await asyncio.to_thread(_write_drafts, self.root, texts)
        self._warn("drafting", warnings)

    async def _drafted(self, prompt: str) -> str:
        """The draft call's answer: the one kept in `CHUNKS`, else the call's, tried again after each of
        `DRAFT_RETRY_DELAYS` and then kept. The usage limit pauses the job (`pieces.Paused`) at once; an answer the
        content filter blocks is kept empty, counted in `filtered`."""
        kept = self.root / CHUNKS / f"{hashlib.sha256(prompt.encode('utf-8')).hexdigest()}.md"
        if kept.exists():
            reply = await asyncio.to_thread(kept.read_text, "utf-8")
            self.filtered += not reply
            return reply
        try:
            reply = await runner.retried(lambda: self.complete(prompt), DRAFT_RETRY_DELAYS)
        except Exception as error:
            if not FILTERED.search(str(error)):
                raise
            # An empty answer: `_convert_chunks` keeps the chunk's text from the PDF, with its warning.
            reply, self.filtered = "", self.filtered + 1
        keeping = asyncio.ensure_future(asyncio.to_thread(_keep, kept, reply))
        try:
            await asyncio.shield(keeping)
        except asyncio.CancelledError:
            # Another chunk's failure cancels this one after its answer came: it is kept all the same, before the
            # job pauses, so the resume doesn't pay for it again.
            await keeping
            raise
        return reply

    # ----- 4. sorting -----

    async def sort(self) -> None:
        outcome = await self._piece(
            "sort",
            _brief("sort", qa=self.qa, piece="sort"),
            lambda: _sort_problems(self.root),
            [PARTS, ORIGINAL],
            owns=[PARTS, ORIGINAL, KEYS],  # `draft/` is restored from `drafted/` before every attempt
            before=lambda: _restore_drafts(self.root),
        )
        if outcome == "skipped":
            await asyncio.to_thread(_unsorted, self.ws, len(self._book().pages))
        self.progress("sorting", 1, 1)

    # ----- 5. cleaning -----

    async def clean(self) -> None:
        groups = [(f"clean-{n}", group) for n, group in enumerate(clean_groups(self.ws.parts()), start=1)]
        names = [piece for piece, _ in groups]
        self._finished("cleaning", names)

        async def one(item: tuple[str, list[dict[str, Any]]]) -> None:
            piece, group = item
            files = [f"{CLEAN}/{part['id']}.md" for part in group]
            check = lambda: [name for name in files if not (self.root / name).is_file()]
            prompt = _brief("clean", qa=self.qa, piece=piece, parts=_part_lines(group))
            owns = [*files, f"{CLEAN}/{piece}-orphans.md"]
            if await self._piece(piece, prompt, check, files, owns=owns) == "skipped":
                await asyncio.to_thread(_keep_drafts, self.ws, piece, group)
            self._finished("cleaning", names)

        await self._each(groups, one)
        orphans = "sort-orphans"
        if self.ws.piece(orphans) is not None or self.ws.was_stopped(orphans) or _orphans(self.root):
            # A stopped `sort-orphans` may have emptied every orphans file: it runs again all the same (DEL-92).
            names.append(orphans)
            check = lambda: [f"a place for {CLEAN}/{path.name}" for path in _orphans(self.root)]
            if not self.ws.is_done(orphans):
                await asyncio.to_thread(_keep_cleaned, self.root)
            prompt = _brief("sort", qa=self.qa, piece=orphans)
            await self._piece(orphans, prompt, check, [], restart=lambda: _restore_cleaned(self.root))
            self._finished("cleaning", names)
        _drop_placed(self.root)
        shutil.rmtree(self.root / CLEANED, ignore_errors=True)

    # ----- 6. tracing -----

    async def trace(self) -> None:
        parts = self.ws.parts()
        maps = [(part, listed) for part in parts for listed in part.get("maps") or [] if _map_name(listed)]
        used = {listed["name"] for _, listed in maps}
        unmapped = []
        for part in parts:
            mapped = any(_map_name(listed) for listed in part.get("maps") or [])
            if not mapped and len(_rooms(self.root, part)) >= runner.SKETCHED_KEYS:
                unmapped.append((unique(part["id"], used), part))
        names = [f"trace-{listed['name']}" for _, listed in maps] + [f"sketch-{name}" for name, _ in unmapped]
        self._finished("tracing", names)

        async def one(item: tuple[dict[str, Any], dict[str, Any]]) -> None:
            part, listed = item
            name, page = listed["name"], listed.get("page")
            piece = f"trace-{name}"
            files = [f"{MAPS}/{name}.dmap", f"{MAPS}/{name}.exits.json"]
            prompt = _brief("trace", qa=self.qa, piece=piece, parts=_part_lines([part]), maps=_map_lines([item]))
            owns = [*files, f"{MAPS}/{name}.svg", f"{MAPS}/{name}.png"]
            check = lambda: _trace_problems(self.root, name)
            if await self._piece(piece, prompt, check, files, owns=owns) == "skipped":
                first = TRACE_FAILED_LINE.format(page=page)
                doubt = TRACE_SKIPPED.format(page=page, name=name, title=part["title"])
                await self._sketch(name, part, first, doubt, [page] if isinstance(page, int) else _pages(part))
            self._finished("tracing", names)

        await self._each(maps, one)
        for name, part in unmapped:
            doubt = NO_MAP.format(title=part["title"], name=name)
            await self._sketch(name, part, runner.NO_BOOK_MAP, doubt, _pages(part))
            self._finished("tracing", names)

    async def _sketch(self, name: str, part: dict[str, Any], first: str, doubt: str, pages: list[int]) -> None:
        """The map `name` sketched from `part`'s room key in place of the book's, a doubt; once."""
        piece = f"sketch-{name}"
        if self.ws.is_done(piece):
            return
        rooms = _rooms(self.root, part)
        dmap, exits = self.root / MAPS / f"{name}.dmap", self.root / MAPS / f"{name}.exits.json"
        dmap.unlink(missing_ok=True)  # a trace that failed may have left one that doesn't parse
        exits.unlink(missing_ok=True)
        title = part["title"]
        if len({key for key, _ in rooms}) < len(rooms):
            self.ws.doubt(piece, [_doubt(part, pages, "other", REPEATED.format(title=title))])
            self.ws.done(piece, None, [])
            return
        source, warnings = await sketch_map(name, rooms, self.complete)
        self._warn(piece, warnings)
        if source is None:
            reason = warnings[0].message if warnings else "it has no keys"
            self.ws.doubt(
                piece, [_doubt(part, pages, "other", NOT_SKETCHED.format(name=name, title=title, reason=reason))]
            )
            self.ws.done(piece, None, [])
            return
        dmap.parent.mkdir(exist_ok=True)
        dmap.write_text(f"{runner.SKETCHED} {first}\n{source}", "utf-8")
        exits.write_text("[]\n", "utf-8")
        sketches = self.ws.read_json(SKETCHES, {})
        sketches[name] = {"part": part["id"], "reason": first}
        self.ws.write_json(SKETCHES, sketches)
        self.ws.doubt(piece, [_doubt(part, pages, "sketched-map", doubt)])
        self.ws.done(piece, None, [f"{MAPS}/{name}.dmap", f"{MAPS}/{name}.exits.json"])

    # ----- 7. joining -----

    async def join(self) -> None:
        self.progress("joining", 0, 1)
        (self.root / MAPS).mkdir(exist_ok=True)
        _, found = await asyncio.to_thread(join_folder, self.root / MAPS, self.root / JOINED)
        self.ws.doubt("join", [dict(doubt) for doubt in found])
        self.progress("joining", 1, 1)

    # ----- 8. describing -----

    async def describe(self) -> None:
        if not self.ws.is_done("art"):
            cut = await asyncio.to_thread(cut_art, self.ws, self._book())
            self.ws.done("art", None, cut)
        if not any((self.root / ART).glob("*.png")):
            return
        self.progress("describing", 0, 1)
        await self._piece(
            "describe",
            _brief("describe", qa=self.qa, piece="describe"),
            lambda: _describe_problems(self.root),
            [],
            owns=[f"{ART}/descriptions.json"],  # never the pictures: they are the `art` piece's
        )
        self.progress("describing", 1, 1)

    # ----- 9. entities -----

    async def entities(self) -> None:
        texts = _clean_texts(self.ws)
        limit = asyncio.Semaphore(DRAFT_CALLS)
        progress = lambda step, done, total: self.progress("entities", done, total)
        entities, warnings, renamed, origins = await _entities(texts, self.title, self.complete, progress, limit)

        async def limited(prompt: str) -> str:
            async with limit:
                return await self.complete(prompt)

        entities, grouped, deduped = await dedupe_entities(entities, limited)
        renamed = {old: grouped.get(new, new) for old, new in renamed.items()} | grouped
        self.ws.write_json(ENTITIES, {"entities": entities, "renamed": renamed, "origins": origins})
        self._warn("entities", [*warnings, *deduped])

    # ----- 10. making -----

    async def make(self) -> None:
        """The module, in one transaction with the job's end (`runner._make_module`), then the folder removed. The
        doubts end with the cost's, when sessions were stopped before their end (`pieces.stopped_doubt`)."""
        self.progress("making", 0, 1)
        title = self.title
        cost = pieces.stopped_doubt(self.ws)
        if cost is not None:
            self.ws.doubt(pieces.COST_PART, [cost])
        source, maps, pictures, found = await asyncio.to_thread(build_source, self.ws, title)
        pdf = self.root / BOOK
        sha = await asyncio.to_thread(self.services.storage.blobs.put_file, pdf, "application/pdf")
        original = Attachment(
            runner.SOURCE_PDF, "application/pdf", sha, pdf.stat().st_size, "The original PDF", "gm", "source"
        )
        source = replace(source, attachments=[*source.attachments, original])
        converted = Converted(source=source, pictures=pictures, warnings=self._warnings(), maps=maps)
        # The metadata's call is the conversion's, as a quick job's, but the usage limit pauses this job there too.
        metadata = runner._complete(self.services, self.live)
        complete = lambda prompt: _pausing(metadata(prompt))
        await runner._make_module(
            self.services, self.live, converted, title, blobs=(sha,), doubts=found, complete=complete
        )
        await asyncio.to_thread(self.ws.remove)


async def _pausing[T](call: Awaitable[T]) -> T:
    """`call`'s answer; at the usage limit the job pauses (`pieces.Paused`, a `Halt`) until the notice's reset. Raised
    as itself, the limit would be a warning to the books' steps that keep a module coming when a call fails
    (classifying a page, reading the entities), and the stage would be done with a poorer module."""
    try:
        return await call
    except Exception as error:
        if USAGE_LIMIT.search(str(error)) is None:
            raise
        resets = RESETS.search(str(error))
        raise pieces.Paused(resets.group(1).rstrip(".") if resets else None) from error


# ----- the folder -----


def _keep(path: Path, text: str) -> None:
    """Write `text` at `path` whole or not at all: a stop mid-write leaves no half answer to reuse."""
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(".partial")
    partial.write_text(text, "utf-8")
    partial.replace(path)


def _write_pages(root: Path, book: PdfBook) -> None:
    """`pages/` and `scan/`. The text of a page OCR read is the book's, so OCR runs once."""
    pdf = root / BOOK
    render_pages(pdf, root / PAGES, dpi=PAGE_DPI)
    (root / SCAN).mkdir(exist_ok=True)
    for page in book.pages:
        if page.ocr:
            text = (page.text or page.ocr_text).strip()
            (root / PAGES / page_text(page.number)).write_text(text + "\n" if text else "", "utf-8")
        if page.pictures:
            (root / SCAN / page_image(page.number)).write_bytes(render_page(pdf, page.number, SCAN_DPI))


def _picture_file(number: int, n: int) -> str:
    return f"{PICTURES}/p-{number:03d}-{n}.png"


def _save_book(ws: Workspace, book: PdfBook) -> None:
    """`book.json`, the pages without their pictures' bytes, which go to `pictures/`; the warnings stay out."""
    (ws.root / PICTURES).mkdir(exist_ok=True)
    pages = []
    for page in book.pages:
        pictures = []
        for n, picture in enumerate(page.pictures, start=1):
            name = _picture_file(page.number, n)
            (ws.root / name).write_bytes(picture.png)
            pictures.append({"file": name, "area": picture.area})
        pages.append(
            {
                "number": page.number,
                "text": page.text,
                "ocr": page.ocr,
                "map_page": page.map_page,
                "ocr_text": page.ocr_text,
                "plate_title": page.plate_title,
                "handouts": [asdict(handout) for handout in page.handouts],
                "pictures": pictures,
            }
        )
    ws.write_json(BOOK_JSON, {"pages": pages})


def _load_book(ws: Workspace) -> PdfBook:
    pages = []
    for page in ws.read_json(BOOK_JSON)["pages"]:
        pictures = [Picture(page["number"], (ws.root / p["file"]).read_bytes(), p["area"]) for p in page["pictures"]]
        handouts = tuple(HandoutBox(tuple(h["box"]), h["title"], h.get("key"), h.get("part")) for h in page["handouts"])
        pages.append(
            PdfPage(
                page["number"],
                page["text"],
                page["ocr"],
                pictures,
                map_page=page["map_page"],
                ocr_text=page["ocr_text"],
                plate_title=page["plate_title"],
                handouts=handouts,
            )
        )
    return PdfBook(pages=pages, warnings=[])


def _classes(book: PdfBook) -> dict[str, Any]:
    """What the classifier took each page for: `map`, `picture` (a page with pictures), `text` or `blank`."""

    def kind(page: PdfPage) -> str:
        if page.map_page:
            return "map"
        if page.pictures:
            return "picture"
        return "text" if page.text.strip() else "blank"

    return {
        "pages": [
            {
                "page": page.number,
                "kind": kind(page),
                "title": page.plate_title,
                "pictures": len(page.pictures),
                "handouts": [handout.title for handout in page.handouts],
            }
            for page in book.pages
        ]
    }


def _clear(root: Path, paths: Iterable[str]) -> None:
    """Remove `paths` (files or folders in the folder at `root`), those that are there: a stopped piece's own files,
    for its next session to start from a clean slate (DEL-92)."""
    for name in paths:
        path = root / name
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink(missing_ok=True)


def _keep_cleaned(root: Path) -> None:
    """`cleaned/`, a copy of `clean/` as the cleaning pieces left it, unless there is one: written beside it and
    renamed, so a stop mid-copy leaves none (DEL-92)."""
    kept = root / CLEANED
    if kept.is_dir():
        return
    partial = root / f"{CLEANED}.partial"
    shutil.rmtree(partial, ignore_errors=True)
    shutil.copytree(root / CLEAN, partial)
    partial.rename(kept)


def _restore_cleaned(root: Path) -> None:
    """`clean/` as `cleaned/` keeps it, for a restarted `sort-orphans`: the orphans it had placed go back to their
    files, and the files it had emptied hold them again (DEL-92)."""
    if not (root / CLEANED).is_dir():
        return
    shutil.rmtree(root / CLEAN, ignore_errors=True)
    shutil.copytree(root / CLEANED, root / CLEAN)


def _write_drafts(root: Path, texts: list[TextDoc]) -> None:
    """`drafted/NN-<text id>.md` with `drafted/texts.json`, and `draft/` a copy of the Markdown."""
    shutil.rmtree(root / DRAFTED, ignore_errors=True)
    (root / DRAFTED).mkdir()
    listed = []
    for n, text in enumerate(texts, start=1):
        name = f"{n:02d}-{text.id}.md"
        (root / DRAFTED / name).write_text(text.markdown, "utf-8")
        listed.append({"file": name, "id": text.id, "title": text.title, "audience": text.audience})
    Workspace(root).write_json(f"{DRAFTED}/texts.json", listed)
    _restore_drafts(root)


def _restore_drafts(root: Path) -> None:
    """`draft/` as the drafting wrote it, for an attempt at the sort to start from."""
    shutil.rmtree(root / DRAFT, ignore_errors=True)
    shutil.copytree(root / DRAFTED, root / DRAFT, ignore=shutil.ignore_patterns("*.json"))


def _sort_problems(root: Path) -> list[str]:
    """What the sort left out: `parts.json` that loads, a draft per part, a keys file per keyed part."""
    ws = Workspace(root)
    try:
        data = ws.read_json(PARTS)
    except ValueError:
        return [f"{PARTS} that loads"]
    listed = data.get("parts") if isinstance(data, dict) else data
    if not isinstance(listed, list) or not listed or not all(isinstance(part, dict) for part in listed):
        return [f"{PARTS} with its parts"]
    problems: list[str] = []
    pictures = data.get("pictures") if isinstance(data, dict) else None
    if not isinstance(pictures, list | None) or any(
        not _page(entry.get("page") if isinstance(entry, dict) else entry) for entry in pictures or []
    ):
        problems.append(f"{PARTS}: `pictures` as a list of page numbers")
    ids: set[str] = set()
    names: set[str] = set()
    for part in listed:
        id = part.get("id")
        if not isinstance(id, str) or not _ID.match(id) or id in ids or not isinstance(part.get("title"), str):
            problems.append(f"{PARTS}: a unique id and a title for every part ({id!r})")
            continue
        ids.add(id)
        if not (root / DRAFT / f"{id}.md").is_file():
            problems.append(f"{DRAFT}/{id}.md")
        pattern = part.get("key_pattern")
        if pattern:
            try:
                re.compile(pattern)
            except (re.error, TypeError):
                problems.append(f"{PARTS}: a key pattern for {id} that compiles")
            if not (root / KEYS / f"{id}.txt").is_file():
                problems.append(f"{KEYS}/{id}.txt")
        for listed_map in part.get("maps") or []:
            name = _map_name(listed_map)
            if name is None or name in names:
                problems.append(f"{PARTS}: a unique name for each map of {id}")
            else:
                names.add(name)
    return problems


def _page(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _map_name(listed: Any) -> str | None:
    name = listed.get("name") if isinstance(listed, dict) else None
    return name if isinstance(name, str) and _ID.match(name) else None


def _unsorted(ws: Workspace, pages: int) -> None:
    """The sort's fallback: every draft a part of its own, an unkeyed chapter over the whole book, with a doubt."""
    root = ws.root
    _restore_drafts(root)
    parts = []
    for n, text in enumerate(ws.read_json(f"{DRAFTED}/texts.json", []), start=1):
        (root / DRAFT / text["file"]).rename(root / DRAFT / f"{text['id']}.md")
        parts.append(
            {
                "id": text["id"],
                "title": text["title"],
                "kind": "chapter",
                "audience": text["audience"],
                "pages": [1, pages],
                "key_pattern": None,
                "map_pages": [],
                "maps": [],
                "order": n,
            }
        )
    ws.write_json(PARTS, {"parts": parts, "pictures": []})
    ws.doubt("sort.unsorted", [{"part": "sort", "pages": [], "kind": "other", "text": NOT_SORTED}])


def _keep_drafts(ws: Workspace, piece: str, group: list[dict[str, Any]]) -> None:
    """A skipped clean's fallback: its parts' sorted drafts, each a doubt."""
    (ws.root / CLEAN).mkdir(exist_ok=True)
    found = []
    for part in group:
        draft = ws.root / DRAFT / f"{part['id']}.md"
        if draft.is_file():
            shutil.copyfile(draft, ws.root / CLEAN / f"{part['id']}.md")
        pages = _pages(part)
        where = f"{pages[0]} to {pages[-1]}" if pages else "of the part"
        found.append(_doubt(part, pages, "other", NOT_CLEANED.format(title=part["title"], pages=where)))
    ws.doubt(f"{piece}.not-cleaned", found)


def _orphans(root: Path) -> list[Path]:
    """The orphans files still holding text: an agent may not delete a file, so it empties one it has placed (U1)."""
    return [path for path in sorted((root / CLEAN).glob("*-orphans.md")) if path.read_text("utf-8").strip()]


def _drop_placed(root: Path) -> None:
    for path in sorted((root / CLEAN).glob("*-orphans.md")):
        if not path.read_text("utf-8").strip():
            path.unlink()


def _trace_problems(root: Path, name: str) -> list[str]:
    """What a trace left out: its map, which parses and validates, and its exits file, a list."""
    problems = []
    dmap = root / MAPS / f"{name}.dmap"
    if not dmap.is_file():
        problems.append(f"{MAPS}/{name}.dmap")
    else:
        libraries = {p.name: p.read_text("utf-8") for p in (root / MAPS).glob("*.dmap") if p != dmap}
        error = _map_error(dmap.read_text("utf-8"), libraries)
        if error is not None:
            problems.append(f"{MAPS}/{name}.dmap that parses ({error})")
    try:
        exits = Workspace(root).read_json(f"{MAPS}/{name}.exits.json")
    except ValueError:
        exits = None
    if not isinstance(exits, list):
        problems.append(f"{MAPS}/{name}.exits.json")
    return problems


def _map_error(source: str, libraries: dict[str, str]) -> str | None:
    try:
        dmap = parse_source(source, libraries)
    except Exception as error:  # noqa: BLE001 (the DSL raises several kinds; each is a failed attempt)
        return str(error) or type(error).__name__
    errors = [d for d in validate(dmap) if d.severity == "error"]
    if errors:
        return f"{errors[0].message} (line {errors[0].line})"
    return None if dmap.rooms else "the map has no rooms"


def _describe_problems(root: Path) -> list[str]:
    try:
        described = Workspace(root).read_json(f"{ART}/descriptions.json")
    except ValueError:
        described = None
    if not isinstance(described, list) or not all(isinstance(d, dict) and "file" in d for d in described):
        return [f"{ART}/descriptions.json"]
    return []


def _part_text(root: Path, part: dict[str, Any]) -> str | None:
    """A part's cleaned text, else its draft."""
    for path in (root / CLEAN / f"{part['id']}.md", root / DRAFT / f"{part['id']}.md"):
        if path.is_file():
            return path.read_text("utf-8")
    return None


def _rooms(root: Path, part: dict[str, Any]) -> list[tuple[str, str]]:
    """A part's keyed headings with their paragraphs, as the quick conversion sketches from."""
    markdown = _part_text(root, part)
    if markdown is None:
        return []
    return runner._keyed_rooms(TextDoc(part["id"], part["title"], "gm", None, markdown))


def _clean_texts(ws: Workspace) -> list[TextDoc]:
    texts = []
    for part in ws.parts():
        markdown = _part_text(ws.root, part)
        if markdown is not None:
            audience = "player" if part.get("audience") == "player" else "gm"
            texts.append(TextDoc(part["id"], part["title"], audience, None, markdown))
    return texts


def _doubt(part: dict[str, Any], pages: list[int], kind: str, text: str) -> dict[str, Any]:
    return {"part": part["id"], "pages": pages, "kind": kind, "text": text}


def _strip(png: bytes) -> bool:
    with Image.open(io.BytesIO(png)) as image:
        width, height = image.size
    return max(width, height) >= STRIP_RATIO * max(min(width, height), 1)


def cut_art(ws: Workspace, book: PdfBook) -> list[str]:
    """The pictures offered to the describing agent, written to `art/` as `pNNN-K.png`; their paths. The pages
    `parts.json` lists as pictures are taken whole, from `scan/`; a traced map's page is left out; a page's handouts
    (the classifier's boxes) are cut from its whole-page picture; every other picture is taken as the reading cut it,
    unless it is a strip (`STRIP_RATIO`)."""
    root = ws.root
    shutil.rmtree(root / ART, ignore_errors=True)
    (root / ART).mkdir()
    whole = set(ws.pictures())
    traced = {listed.get("page") for part in ws.parts() for listed in part.get("maps") or []}
    written: list[str] = []

    def write(number: int, n: int, png: bytes) -> None:
        name = f"{ART}/p{number:03d}-{n}.png"
        (root / name).write_bytes(png)
        written.append(name)

    for page in book.pages:
        if page.number in whole:
            scan = root / SCAN / page_image(page.number)
            write(
                page.number, 1, scan.read_bytes() if scan.is_file() else render_page(root / BOOK, page.number, SCAN_DPI)
            )
        elif page.number in traced:
            continue
        elif page.handouts and any(picture.area >= 1.0 for picture in page.pictures):
            full = next(picture for picture in page.pictures if picture.area >= 1.0)
            for n, handout in enumerate(page.handouts, start=1):
                write(page.number, n, cut(full.png, handout.box))
        else:
            for n, picture in enumerate((p for p in page.pictures if not _strip(p.png)), start=1):
                write(page.number, n, picture.png)
    return written
