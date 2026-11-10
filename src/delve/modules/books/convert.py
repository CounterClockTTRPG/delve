"""Converting a book (spec §8.3): a read PDF becomes a module's texts, entity drafts and attachments, with warnings.

Every Claude step goes through the injected `complete`, since `delve.modules` may not import `delve.dm`. The pages are
sent in chunks of whole pages (`chunk_pages`, from ttrpg3's `ingest.py`) with `prompts/convert.md`, which asks for the
chunk's own words as Markdown, never a summary. An answer under 70% of its source's words keeps the source instead,
with a `conversion-short` warning. The Markdown is split into a text per `#` chapter, and its keyed headings get
anchors. Then each text is sent with `prompts/entities.md` for its NPC, encounter, faction and quest drafts, each
checked against the format's schema, in chunks under the same budget (cut at headings, else at paragraphs). Each
picture becomes a `gm` attachment, described by its page. What the conversion marks for the players gets an
`audience-player` warning, for the owner to confirm. Each handout Claude's look found on a page (`classify`) is cut
from it as an attachment for the players (`handout-<page>-<n>`) and put in its room's `keys[]` entry (`link_handouts`).

A map page of the book (`PdfPage.map_page`) becomes the attachment `map-page-<n>`, described as a map from the book
with its title (`map_title`), and gets a `book-map` warning. Another picture page whose OCR starts with a title
(`chapter_title`: few words, and not the module's title or a running header) is a chapter's title page: it starts a
chunk, and the chunk's Markdown a chapter at that title. OCR text never becomes a text.

The cover, the title page and the back cover (`front_pages`: the first and last page of a book of `MIN_BOOK_PAGES` or
more) are chunks of their own and never a chapter's title page. Their Markdown, unless it holds a keyed heading, and
what comes before the first chapter when it holds none, are the last text, `FRONT_MATTER`, so the DM opens on the
first chapter.

The book's numbers win over tidiness: a chunk whose Markdown holds a number fewer times than its source, leaving out
each page's header and footer (`numbers_changed`), gets a `numbers-changed` warning. Records of one kind with one name are merged
(`merge_entities_mapped`, by exact name after trimming and case-folding, never fuzzy), and then the NPCs and factions Claude
groups as one (`dedupe.dedupe_entities`). Every keyed heading gets a `keys[]` entry, with its key as written
(`source.scoped_keys`), and the encounters and NPCs that name a keyed heading are keyed to it, in the text they were
read from first (`key_entities`), so the ship's 11 is never the house's. Last, the refs left dangling are rewritten to
the one record meant or dropped, with warnings (`repair.repair_refs`), so the module always exports.

The calls of a step run at once, up to `concurrency`; the first that fails cancels the others.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from functools import cache
from importlib import resources
from typing import Any

from jsonschema import Draft202012Validator

from delve.domain.modules import ModuleMap
from delve.modules.books.calls import Halt, all_of
from delve.modules.books.classify import cut
from delve.modules.books.dedupe import dedupe_entities, merge_into
from delve.modules.books.fences import unfenced
from delve.modules.books.pdf import (
    MAP_WORDS,
    MIN_REAL_SHARE,
    TITLE_PAGE_WORDS,
    HandoutBox,
    PdfBook,
    PdfPage,
    Picture,
    real_share,
    real_words,
)
from delve.modules.books.repair import repair_refs
from delve.modules.dscn import add_anchors, parse_text, schema, sha256, slugify
from delve.modules.source import (
    DEFAULT_AUDIENCES,
    PART_STOP_WORDS,
    Attachment,
    Audience,
    ModuleSource,
    TextDoc,
    Warning,
    part_slug,
    scoped_entries,
    scoped_keys,
)
from delve.modules.text import unique

Complete = Callable[[str], Awaitable[str]]
Progress = Callable[[str, int, int], None]


@dataclass
class Converted:
    source: ModuleSource
    pictures: list[tuple[Attachment, bytes]]
    warnings: list[Warning]
    maps: list[ModuleMap] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    """The module's descriptive metadata, as the format's manifest holds it (a generated module's `party`)."""
    questions: list[Question] = field(default_factory=list)
    """What Claude asked while making the module, each with the assumption it made (at most `MAX_QUESTIONS`)."""


@dataclass(frozen=True)
class Question:
    """A question Claude asked while making a module, and the assumption it made instead of an answer."""

    id: str
    text: str
    default: str


MAX_QUESTIONS = 5
"""The most questions a made module keeps; the prompts ask for no more."""
_QUESTIONS = re.compile(r"^[ \t]*```questions[ \t]*\n(.*?)\n?^[ \t]*```[ \t]*$\n?", re.MULTILINE | re.DOTALL)


def take_questions(reply: str) -> tuple[str, list[Question]]:
    """`reply` without its fenced `questions` blocks, and the questions they hold (`[{text, default}]`), numbered
    `q1`, `q2`… A block that isn't such a list, and an entry without a text, give none."""
    found: list[Question] = []
    for block in _QUESTIONS.finditer(reply):
        try:
            raw = json.loads(block.group(1))
        except json.JSONDecodeError:
            continue
        for item in raw if isinstance(raw, list) else []:
            text = item.get("text") if isinstance(item, dict) else None
            if isinstance(text, str) and text.strip():
                default = item.get("default")
                found.append(Question("", text.strip(), default.strip() if isinstance(default, str) else ""))
    return _QUESTIONS.sub("", reply).strip(), numbered(found)


def numbered(questions: list[Question]) -> list[Question]:
    """The first `MAX_QUESTIONS` of `questions`, with the ids `q1`, `q2`…"""
    return [replace(q, id=f"q{n}") for n, q in enumerate(questions[:MAX_QUESTIONS], start=1)]


CHUNK_BUDGET = 12_000
"""The characters of page text sent in one chunk."""
SHORT_SHARE = 0.7
"""An answer with fewer than this share of its source's words is cut short."""
CONTEXT_CHARS = 300
"""How much of the previous chunk's text a chunk gets as context."""
PLAYERS_MARK = "<!-- players -->"
"""The line `convert.md` puts after a chapter's heading when the book says the chapter is for the players."""
FRONT_MATTER = "front-matter"
"""The id of the text that holds the cover, the title page and the back cover, apart from the chapters."""
FRONT_MATTER_TITLE = "Front matter"
FRONT_PAGES = 1
"""The book's first pages that are its cover and title page…"""
BACK_PAGES = 1
"""… and its last, the back cover (with its ads)."""
MIN_BOOK_PAGES = 8
"""A book of fewer pages has no cover apart: a short PDF (a one-page room key, a handout) starts on its first page."""

ENTITY_KINDS = {"npcs": "npc", "encounters": "encounter", "factions": "faction", "quests": "quest", "pregens": "pregen"}
"""The kinds `entities.md` asks for, with their record's `$defs` entry in `scenario.schema.json`."""

_PARAGRAPHS = re.compile(r"\n[ \t]*\n")
PLAYERS_WARNING = "Marked for the players by the conversion; check it."
_MARKDOWN_START = re.compile(r"^([#>+\-|`~=<]|\*(\s|\**\s*$)|\d+[.)](\s|$))")
"""A line that reads as Markdown: a heading, a quote, a list, a rule… A line opening in `**bold**` or `*italic*`, as
the book's are kept, doesn't."""
_NUMBER = re.compile(r"(?<!\d)\d{1,3}(?!\d)")
_PAGE_NUMBER = re.compile(r"^\s*\d{1,3}\s*$", re.MULTILINE)
NUMBERS_LISTED = 10
"""How many changed numbers a `numbers-changed` warning lists."""
TITLE_WORDS = 6
"""A title-like line of OCR has one to this many words…"""
TITLE_CHARS = 60
"""… and at most this many characters, and no full stop."""
_LEGEND_WORDS = MAP_WORDS - {"map", "north"}
"""The words of a map's legend: a line holding one is the legend, not the map's title."""
_PLACED = re.compile(r"\b(?:area|room)\s+([a-z]?\d+[a-z]?)\b|\bin\s+([a-z]?\d+[a-z]?)\.", re.IGNORECASE)
# The words before an area that name it as somewhere else: "guards from area 2" aren't in area 2.
_ELSEWHERE = re.compile(r"\b(from|to|towards?|near|beyond|past|than)\s+(the\s+)?$", re.IGNORECASE)


def _prompt(name: str) -> str:
    return resources.files("delve.modules.books").joinpath("prompts", name).read_text("utf-8")


def _fill(template: str, **values: str) -> str:
    for name, value in values.items():
        template = template.replace("{{" + name + "}}", value)
    return template


def text_id(title: str) -> str:
    """A text's id from its title: its slug, or `text` when the title gives none."""
    if not re.search(r"[a-z0-9]", title.lower()):
        return "text"
    return slugify(title).lstrip("_.-") or "text"


def players_warning(ref: str) -> Warning:
    return Warning("audience-player", PLAYERS_WARNING, ref)


def title_line(text: str, *, legend: bool = True) -> str | None:
    """The first title-like line of OCR `text`: one to `TITLE_WORDS` words, at most `TITLE_CHARS` characters, no full
    stop, and words rather than noise (`real_share`). With `legend` false, a line holding a word of a map's legend
    (door, stairs…) isn't one."""
    for line in text.splitlines():
        line = " ".join(line.split())
        words = [w for w in line.split() if re.search(r"\w", w)]
        if not 1 <= len(words) <= TITLE_WORDS or len(line) > TITLE_CHARS or "." in line:
            continue
        if real_share(line) < MIN_REAL_SHARE:
            continue
        if not legend and _LEGEND_WORDS.intersection(re.findall(r"[a-z]+", line.lower())):
            continue
        return line
    return None


def map_title(page: PdfPage) -> str | None:
    """The title of a map page of the book: its plate's (`HAUNTED HOUSE`, `PdfPage.plate_title`), else the OCR's first
    title-like line (`Map C – The Cloud Castle`); None when it has none, or isn't a map page."""
    if not page.map_page:
        return None
    return page.plate_title or title_line(page.ocr_text, legend=False)


def _line_key(line: str) -> str:
    return " ".join(line.split()).casefold()


def _lines(text: str) -> list[str]:
    return [" ".join(line.split()) for line in text.splitlines() if line.strip()]


def repeated_lines(pages: list[PdfPage]) -> frozenset[str]:
    """The lines (by `_line_key`) of text or OCR that are on three pages or more: running headers and footers. A title
    page's title is on its page and on two others before it repeats, since its chapter's heading may say it again."""
    seen: dict[str, int] = {}
    for page in pages:
        for key in {_line_key(line) for line in _lines(page.text) + _lines(page.ocr_text)}:
            seen[key] = seen.get(key, 0) + 1
    return frozenset(key for key, count in seen.items() if count >= 3)


def chapter_title(page: PdfPage, *, title: str | None = None, repeated: frozenset[str] = frozenset()) -> str | None:
    """The chapter a picture page that isn't a map is the title page of, from its OCR; None for any other page.

    The title is the OCR's first line that isn't empty, when it is title-like (`title_line`), the OCR holds at most
    `TITLE_PAGE_WORDS` words, and it is neither the module's `title` nor one of the book's `repeated` lines (on two other pages or more)."""
    if page.text.strip() or page.map_page or not page.pictures:
        return None
    lines = _lines(page.ocr_text)
    if not lines or real_words(page.ocr_text) > TITLE_PAGE_WORDS:
        return None
    first = title_line(lines[0])
    if first is None or _line_key(first) in repeated or (title is not None and _line_key(first) == _line_key(title)):
        return None
    return first


def front_pages(pages: list[PdfPage]) -> frozenset[int]:
    """The numbers of the book's first `FRONT_PAGES` and last `BACK_PAGES` pages: its cover, title page and back
    cover. None in a book of fewer than `MIN_BOOK_PAGES` pages."""
    if len(pages) < MIN_BOOK_PAGES:
        return frozenset()
    return frozenset(page.number for page in [*pages[:FRONT_PAGES], *pages[len(pages) - BACK_PAGES :]])


def chapter_titles(pages: list[PdfPage], title: str | None = None) -> dict[int, str]:
    """The chapter titles of the book's title pages (`chapter_title`), by page number. The cover, the title page and
    the back cover (`front_pages`) are none."""
    repeated = repeated_lines(pages)
    front = front_pages(pages)
    found = {
        page.number: None if page.number in front else chapter_title(page, title=title, repeated=repeated)
        for page in pages
    }
    return {number: chapter for number, chapter in found.items() if chapter is not None}


def chunk_pages(pages: list[PdfPage], budget: int = CHUNK_BUDGET, *, title: str | None = None) -> list[list[PdfPage]]:
    """The pages in chunks of whole pages, each under `budget` characters of text; a page over it is a chunk alone,
    a chapter's title page (`chapter_titles`, for the module `title`) starts one, and the cover, the title page and the
    back cover (`front_pages`) are chunks of their own."""
    chapters = chapter_titles(pages, title)
    front = front_pages(pages)
    chunks: list[list[PdfPage]] = []
    size = 0
    for page in pages:
        apart = (page.number in front) != (chunks[-1][-1].number in front) if chunks and chunks[-1] else False
        if chunks and chunks[-1] and size + len(page.text) <= budget and page.number not in chapters and not apart:
            chunks[-1].append(page)
            size += len(page.text)
        else:
            chunks.append([page])
            size = len(page.text)
    return chunks


async def convert_book(
    book: PdfBook,
    title: str,
    complete: Complete,
    progress: Progress,
    *,
    concurrency: int = 3,
    draft: Complete | None = None,
) -> Converted:
    """The module made from `book`: its texts by chapter, entity drafts, and its pictures as attachments.

    `progress` hears `converting` (the pages of the chunks done out of the book's pages), `entities` (texts) and
    `pictures`. A failed `complete` while converting raises, once the other calls are cancelled; a failed entities
    call, and what Claude answers badly, become warnings. `draft`, when given, is the chunks' call in place of
    `complete` (the conversion's, asked again after a transient failure).
    """
    limit = asyncio.Semaphore(concurrency)
    warnings = list(book.warnings)

    chunks = chunk_pages(book.pages, title=title)
    chapters = chapter_titles(book.pages, title)
    drafted = await _convert_chunks(chunks, title, draft or complete, progress, limit)
    answers = [_titled(chapters.get(chunk[0].number), answer) for chunk, answer in zip(chunks, drafted, strict=True)]
    markdowns = []
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

    texts = _texts("\n\n".join(markdowns), title, front)
    warnings += [players_warning(f"text:{text.id}") for text in texts if text.audience == "player"]
    entities, entity_warnings, renamed, origins = await _entities(texts, title, complete, progress, limit)
    warnings += entity_warnings

    async def limited(prompt: str) -> str:
        async with limit:
            return await complete(prompt)

    entities, grouped, dedupe_warnings = await dedupe_entities(entities, limited)
    warnings += dedupe_warnings
    renamed = {old: grouped.get(new, new) for old, new in renamed.items()} | grouped

    headings = [h for chunk, answer in zip(chunks, answers, strict=True) if answer for h in _headings(chunk, answer)]
    attachments, picture_warnings, handouts = _attachments(book.pages, headings, progress)
    warnings += picture_warnings

    keyed = key_entities(ModuleSource(texts=texts, entities=entities, attachments=[a for a, _ in attachments]), origins)
    keyed, handout_warnings = link_handouts(keyed, handouts)
    warnings += handout_warnings
    source, repaired = repair_refs(keyed, renamed)
    warnings += repaired
    questions = numbered([q for answer in answers if answer for q in answer.questions])
    return Converted(source=source, pictures=attachments, warnings=warnings, questions=questions)


# --- chunks ----------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Answer:
    markdown: str
    short: bool
    """The answer was empty or cut short, and `markdown` is the source as plain paragraphs."""
    changed: list[str] = field(default_factory=list)
    """The numbers the answer holds fewer times than its source (`numbers_changed`)."""
    questions: list[Question] = field(default_factory=list)
    """The questions the answer ended with (`take_questions`)."""


def _titled(chapter: str | None, answer: _Answer | None) -> _Answer | None:
    """The answer of a chunk that starts at a chapter's title page (titled `chapter`), with the chapter's heading
    first, unless its Markdown already starts with that heading."""
    if answer is None or chapter is None:
        return answer
    sections = parse_text(answer.markdown).sections
    if sections and sections[0].level == 1 and sections[0].title.casefold() == chapter.casefold():
        return answer
    return replace(answer, markdown=f"# {chapter}\n\n{answer.markdown.lstrip()}")


def _source_text(chunk: list[PdfPage]) -> str:
    return "\n\n".join(page.text.strip() for page in chunk if page.text.strip())


def _words(text: str) -> int:
    return len(re.findall(r"\w+", text))


def _pages(chunk: list[PdfPage]) -> str:
    first, last = chunk[0].number, chunk[-1].number
    return f"page {first}" if first == last else f"pages {first}–{last}"


def _context(previous: list[PdfPage] | None) -> str:
    """The end of the previous chunk's text, for a chunk to know where it starts."""
    text = _source_text(previous) if previous else ""
    if not text:
        return ""
    tail = text[-CONTEXT_CHARS:]
    if len(text) > CONTEXT_CHARS and " " in tail:
        tail = tail.split(" ", 1)[1]
    return (
        f"<context>\n{tail}\n</context>\n\nThe text in `<context>` is the end of {_pages(previous)}, which are "
        "converted separately. It is there only to show where these pages begin: don't repeat it.\n\n"
    )


async def _convert_chunks(
    chunks: list[list[PdfPage]], title: str, complete: Complete, progress: Progress, limit: asyncio.Semaphore
) -> list[_Answer | None]:
    """Each chunk's answer, in page order; None for a chunk without words, which isn't sent."""
    template = _prompt("convert.md")
    done = 0
    pages = sum(len(chunk) for chunk in chunks)
    progress("converting", done, pages)
    failed = False

    async def convert(index: int) -> _Answer | None:
        nonlocal done, failed
        chunk = chunks[index]
        source = _source_text(chunk)
        if _words(source) == 0:
            answer = None
        else:
            # The chunks run at once, so a chunk's context is the end of the previous chunk's source text, not the
            # last heading of its answer, which the plan names (a decision of the Archmage, plateau 5 Task 2).
            prompt = _fill(
                template,
                pages=_pages(chunk),
                title=title,
                context=_context(chunks[index - 1] if index else None),
                text=source,
            )
            async with limit:
                # A call that failed frees its place before the task group cancels the rest: the one let in by it
                # is cancelled here, before it calls.
                if failed:
                    raise asyncio.CancelledError
                try:
                    reply = await complete(prompt)
                except Exception:
                    failed = True
                    raise
            answer = _checked(reply, chunk)
        done += len(chunk)
        progress("converting", done, pages)
        return answer

    return await all_of([convert(i) for i in range(len(chunks))])


def _checked(reply: str, chunk: list[PdfPage]) -> _Answer:
    source = _source_text(chunk)
    reply, questions = take_questions(reply)
    markdown = unfenced(reply)
    if _words(markdown) < SHORT_SHARE * _words(source):
        return _Answer(_plain(source), True, questions=questions)
    return _Answer(markdown, False, numbers_changed([page.text for page in chunk], markdown), questions)


def _numbers(text: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for number in _NUMBER.findall(text):
        counts[number] = counts.get(number, 0) + 1
    return counts


def numbers_changed(pages: list[str], markdown: str) -> list[str]:
    """The 1–3-digit numbers that `markdown` holds fewer times than the source `pages`, in numeric order. A line of the
    source that is only a number is a page number, and each page's first and last line that isn't empty its header
    and footer ("Page 26", "UK7 26"); the Markdown leaves them out, and they don't count."""
    body = []
    for page in pages:
        lines = page.splitlines()
        filled = [i for i, line in enumerate(lines) if line.strip()]
        edges = {filled[0], filled[-1]} if filled else set()
        body.append("\n".join(line for i, line in enumerate(lines) if i not in edges))
    had = _numbers(_PAGE_NUMBER.sub("", "\n\n".join(body)))
    has = _numbers(markdown)
    return sorted((n for n, count in had.items() if has.get(n, 0) < count), key=lambda n: (int(n), n))


def _numbers_warning(chunk: list[PdfPage], changed: list[str]) -> Warning:
    first, last = chunk[0].number, chunk[-1].number
    listed = ", ".join(changed[:NUMBERS_LISTED])
    more = f" … and {len(changed) - NUMBERS_LISTED} more" if len(changed) > NUMBERS_LISTED else ""
    message = (
        f"Claude's Markdown for {_pages(chunk)} has fewer of these numbers than the book: {listed}{more}. "
        "Check the tables, rolls and stat lines there against the book."
    )
    return Warning("numbers-changed", message, f"pages:{first}-{last}")


def _plain(source: str) -> str:
    """The source as plain paragraphs: a line that would read as Markdown (a heading, a quote, a list…) is escaped."""
    lines = []
    for line in source.splitlines():
        line = line.strip()
        if _MARKDOWN_START.match(line):
            at = len(line) - len(line.lstrip("0123456789"))
            line = f"{line[:at]}\\{line[at:]}"
        lines.append(line)
    return "\n".join(lines)


def _short_warning(chunk: list[PdfPage]) -> Warning:
    first, last = chunk[0].number, chunk[-1].number
    message = (
        f"Claude's Markdown for {_pages(chunk)} was empty or left words out, "
        "so the text read from the PDF is kept instead, without headings."
    )
    return Warning("conversion-short", message, f"pages:{first}-{last}")


# --- texts -----------------------------------------------------------------------------------------------------------


def _texts(markdown: str, title: str, front: Sequence[str] = ()) -> list[TextDoc]:
    """A text per `#` chapter, and one titled `title` for what comes before the first chapter. The `front` matter's
    Markdown (the cover, the title page, the back cover), and what comes before the first chapter when it holds no
    keyed heading, are the last text, `FRONT_MATTER`, with their chapters' headings one level down."""
    lines = markdown.splitlines()
    chapters = [s for s in parse_text(markdown).sections if s.level == 1]
    parts: list[tuple[str, list[str]]] = []
    starts = [s.line - 1 for s in chapters]
    front = list(front)
    if not chapters or starts[0] > 0:
        before = lines[: starts[0] if chapters else len(lines)]
        if chapters and not parse_text("\n".join(before)).keyed():
            front.insert(0, "\n".join(before))
        else:
            parts.append((title, before))
    for n, section in enumerate(chapters):
        parts.append((section.heading, lines[starts[n] : starts[n + 1] if n + 1 < len(starts) else len(lines)]))

    texts: list[TextDoc] = []
    used: set[str] = {FRONT_MATTER}
    for chapter, part in parts:
        audience: Audience = "gm"
        rest = next((i for i, line in enumerate(part[1:], start=1) if line.strip()), None)
        if rest is not None and part[rest].strip() == PLAYERS_MARK and part[0].startswith("#"):
            audience = "player"
            part = part[:rest] + part[rest + 1 :]
        body = "\n".join(part).strip()
        if not body:
            continue
        texts.append(
            TextDoc(
                unique(text_id(chapter), used),
                chapter,
                audience,
                None,
                add_anchors(body + "\n", read_aloud_marker=None)[0],
            )
        )
    body = "\n\n".join(_demoted(part).strip() for part in front if part.strip())
    if body:
        markdown = add_anchors(body + "\n", read_aloud_marker=None)[0]
        texts.append(TextDoc(FRONT_MATTER, FRONT_MATTER_TITLE, "gm", None, markdown))
    return texts


def _demoted(markdown: str) -> str:
    """`markdown` with its `#` chapter headings made `##`, so the front matter makes no chapter."""
    lines = markdown.splitlines()
    for section in parse_text(markdown).sections:
        if section.level == 1:
            lines[section.line - 1] = "#" + lines[section.line - 1].lstrip()
    return "\n".join(lines)


# --- entities --------------------------------------------------------------------------------------------------------


@cache
def _validator(kind: str) -> Draft202012Validator:
    defs = schema()["$defs"]
    return Draft202012Validator({**defs[ENTITY_KINDS[kind]], "$defs": defs})


async def _entities(
    texts: list[TextDoc], title: str, complete: Complete, progress: Progress, limit: asyncio.Semaphore
) -> tuple[dict[str, list[dict[str, Any]]], list[Warning], dict[str, str], dict[str, str]]:
    """The texts' records, each text sent in chunks (`_text_chunks`); `progress` counts the texts done. The third
    value is the refs of the records merged into another (`merge_entities_mapped`), as `{"npc:bosun-2": "npc:the-bosun"}`,
    and the fourth the text each record was read from, by its ref (`{"npc:the-bosun": "the-ship"}`; a merged record's
    is its first's)."""
    template = _prompt("entities.md")
    done = 0
    progress("entities", done, len(texts))

    async def ask(text: TextDoc, chunk: str) -> str | None:
        """Claude's answer for one chunk of `text`, or None when the call failed."""
        try:
            async with limit:
                return await complete(_fill(template, title=title, text_id=text.id, text=chunk))
        except Halt:
            raise
        except Exception:  # noqa: BLE001 (the rest of the module still arrives)
            return None

    async def read(text: TextDoc) -> list[str | None]:
        nonlocal done
        replies = await all_of([ask(text, chunk) for chunk in _text_chunks(text.markdown)])
        done += 1
        progress("entities", done, len(texts))
        return replies

    answers = await all_of([read(text) for text in texts])
    entities: dict[str, list[dict[str, Any]]] = {}
    warnings: list[Warning] = []
    ids: dict[str, set[str]] = {}
    origins: dict[str, str] = {}
    for text, replies in zip(texts, answers, strict=True):
        if None in replies:
            message = f"The NPCs, encounters, factions and quests of {text.title} couldn't be read: add them by hand."
            warnings.append(Warning("entities-not-read", message, f"text:{text.id}"))
        for reply in replies:
            if reply is None:
                continue
            for kind, record in _records(text, reply, warnings):
                record["id"] = unique(record["id"], ids.setdefault(kind, set()))
                entities.setdefault(kind, []).append(record)
                origins[f"{ENTITY_KINDS[kind]}:{record['id']}"] = text.id
    renamed: dict[str, str] = {}
    for kind, records in entities.items():
        entities[kind], dropped = merge_entities_mapped(records)
        renamed |= {f"{ENTITY_KINDS[kind]}:{old}": f"{ENTITY_KINDS[kind]}:{new}" for old, new in dropped.items()}
    renamed |= _pregens_not_npcs(entities)
    for kind, records in entities.items():
        if DEFAULT_AUDIENCES.get(kind) == "player":
            continue
        warnings += [players_warning(f"{ENTITY_KINDS[kind]}:{r['id']}") for r in records if r["audience"] == "player"]
    return entities, warnings, renamed, origins


def _pregens_not_npcs(entities: dict[str, list[dict[str, Any]]]) -> dict[str, str]:
    """The NPCs that are a pregen by name (`casefold().strip()`) dropped, as characters for the players are not
    NPCs; the value is their refs, rewritten to the pregen's (`{"npc:aldon-npc": "pregen:aldon"}`)."""
    pregens = {r["name"].casefold().strip(): r["id"] for r in entities.get("pregens", [])}
    renamed: dict[str, str] = {}
    kept: list[dict[str, Any]] = []
    for record in entities.get("npcs", []):
        pregen = pregens.get(record["name"].casefold().strip())
        if pregen is None:
            kept.append(record)
        else:
            renamed[f"npc:{record['id']}"] = f"pregen:{pregen}"
    if renamed:
        entities["npcs"] = kept
    return renamed


def merge_entities_mapped(records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Records of one kind with one name made one: names are equal after `casefold().strip()`, never by likeness, so
    "Bernhardt" and "Bernhardt the elder" stay two. The first record's `id` is kept, the `summary`s are joined with a
    blank line (each once), and of every other field the first value that isn't empty is kept. With the merged
    records, `{dropped id: kept id}` for the records merged into another."""
    merged: list[dict[str, Any]] = []
    renamed: dict[str, str] = {}
    by_name: dict[str, dict[str, Any]] = {}
    for record in records:
        name = record.get("name")
        same = by_name.get(name.casefold().strip()) if isinstance(name, str) else None
        if same is None:
            record = dict(record)
            if isinstance(name, str):
                by_name[name.casefold().strip()] = record
            merged.append(record)
            continue
        if record.get("id") != same.get("id"):
            renamed[str(record.get("id"))] = str(same.get("id"))
        merge_into(same, record)
    return merged, renamed


def _pack(pieces: list[str], budget: int, joiner: str) -> list[str]:
    """The pieces joined into chunks under `budget` characters; a piece over it is a chunk alone."""
    chunks: list[str] = []
    for piece in pieces:
        if chunks and len(chunks[-1]) + len(joiner) + len(piece) <= budget:
            chunks[-1] += joiner + piece
        else:
            chunks.append(piece)
    return chunks


def _text_chunks(markdown: str, budget: int = CHUNK_BUDGET) -> list[str]:
    """A text in chunks under `budget` characters: its parts cut at headings, and a part over it cut at paragraphs."""
    lines = markdown.strip().splitlines()
    starts = sorted({0, *(s.line - 1 for s in parse_text(markdown.strip()).sections)})
    parts = ["\n".join(lines[a:b]).strip() for a, b in zip(starts, [*starts[1:], len(lines)], strict=True)]
    pieces: list[str] = []
    for part in filter(None, parts):
        if len(part) <= budget:
            pieces.append(part)
        else:
            pieces += _pack([p.strip() for p in _PARAGRAPHS.split(part) if p.strip()], budget, "\n\n")
    return _pack(pieces, budget, "\n\n")


def _records(text: TextDoc, reply: str, warnings: list[Warning]) -> list[tuple[str, dict[str, Any]]]:
    """The valid records of one text's answer; the rest are warnings."""
    ref = f"text:{text.id}"
    try:
        data = json.loads(unfenced(reply))
    except ValueError:
        data = None
    if not isinstance(data, dict):
        message = f"The NPCs, encounters, factions and quests of {text.title} couldn't be read: add them by hand."
        warnings.append(Warning("entities-not-read", message, ref))
        return []
    records = []
    for kind, definition in ENTITY_KINDS.items():
        found = data.get(kind) or []
        if not isinstance(found, list):
            warnings.append(Warning("entity-dropped", f"The {kind} of {text.title} weren't a list.", ref))
            continue
        for record in found:
            if not isinstance(record, dict):
                warnings.append(Warning("entity-dropped", f"One of the {kind} of {text.title} wasn't a record.", ref))
                continue
            record = dict(record)
            if "id" not in record and isinstance(record.get("name"), str):
                record["id"] = slugify(record["name"]).lstrip("_") or "x"
            record.setdefault("audience", DEFAULT_AUDIENCES.get(kind, "gm"))
            error = next(iter(sorted(_validator(kind).iter_errors(record), key=lambda e: list(e.path))), None)
            if error is not None:
                name = record.get("name") or record.get("id") or "?"
                message = f"The {definition} “{name}” of {text.title} was dropped: {error.message}."
                warnings.append(Warning("entity-dropped", message, ref))
                continue
            records.append((kind, record))
    return records


# --- keys ------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Heading:
    key: str
    """As printed."""
    scoped: str
    """As written in `keys[]` (`source.scoped_keys`): the printed key, or `<part>-<key>` when two parts share it."""
    title: str
    """Without the book's bold and italic marks."""
    ref: str
    """`text:<id>#<anchor>`."""
    text: str
    body: str
    """The section's words, read-aloud and DM text, without marks."""


_CREATURE_STOP_WORDS = frozenset({"group", "of", "the"})


def bare(text: str) -> str:
    """`text` without the `*` of its bold and italic marks, as Task 14 keeps them from the book."""
    return " ".join(text.replace("*", "").split())


def _placed_in(record: dict[str, Any], headings: list[_Heading]) -> _Heading | None:
    """The heading of `headings` that `record` is in: the one its `location` (or an encounter's `key`) names, by its
    ref or its key (printed or as written), else the one titled like its name, else the first keyed N its summary
    names as "area N", "room N" or "in N.", unless it names it as somewhere else ("from area N", `_ELSEWHERE`)."""
    for ref in (record.get("location"), record.get("key")):
        if isinstance(ref, str):
            found = next((h for h in headings if ref in (h.ref, f"key:{h.key}", f"key:{h.scoped}")), None)
            if found is not None:
                return found
    name = record.get("name")
    if isinstance(name, str) and name.strip():
        found = next((h for h in headings if h.title.casefold() == bare(name).casefold()), None)
        if found is not None:
            return found
    summary = record.get("summary")
    summary = summary if isinstance(summary, str) else ""
    for match in _PLACED.finditer(summary):
        if _ELSEWHERE.search(summary[: match.start()]):
            continue
        said = (match.group(1) or match.group(2)).casefold()
        found = next((h for h in headings if h.key.casefold() == said), None)
        if found is not None:
            return found
    return None


def _place(record: dict[str, Any], headings: list[_Heading], own: str | None) -> _Heading | None:
    """The keyed heading `record` is in (`_placed_in`), among the headings of its `own` text first (all of them when
    its text isn't known); else the heading of any text its `location` names exactly, as `text:<id>#<anchor>`."""
    found = _placed_in(record, [h for h in headings if own is None or h.text == own])
    if found is not None:
        return found
    location = record.get("location")
    return next((h for h in headings if h.ref == location), None) if isinstance(location, str) else None


def _creatures(record: dict[str, Any]) -> list[list[str]]:
    """The creatures an encounter names, each as its words: its `fixed` creatures' ids, else its name's words."""
    fixed = [row.get("creature") for row in record.get("fixed") or [] if isinstance(row, dict)]
    ids = [ref.split(":", 1)[-1].split("#", 1)[0] for ref in fixed if isinstance(ref, str)]
    if ids:
        return [[w for w in re.split(r"[-._]+", id) if w] for id in ids]
    name = record.get("name")
    words = [w for w in re.findall(r"[a-z]+", bare(name).casefold()) if w not in _CREATURE_STOP_WORDS]
    return [words] if isinstance(name, str) and words else []


def _names(body: str, words: list[str]) -> bool:
    """`body` holds every one of `words`, each also as a plural ("rat" and "rats")."""
    for word in words:
        stem = word[:-1] if word.endswith("s") and len(word) > 3 else word
        if not re.search(rf"\b{re.escape(stem)}(?:s|es)?\b", body, re.IGNORECASE):
            return False
    return True


def _by_creature(record: dict[str, Any], headings: list[_Heading], own: str | None) -> _Heading | None:
    """The one keyed heading of the encounter's `own` text (any, when not known) whose section names all the creatures
    it names (`_creatures`); None when no section or more than one does."""
    creatures = _creatures(record)
    if not creatures:
        return None
    hits = [h for h in headings if (own is None or h.text == own) and all(_names(h.body, words) for words in creatures)]
    return hits[0] if len(hits) == 1 else None


def key_entities(source: ModuleSource, origins: Mapping[str, str] = {}) -> ModuleSource:
    """`source` with a `keys[]` entry for every keyed heading, as written (`scoped_keys`), and its encounters and NPCs
    keyed to the heading they are in, in the text they were read from (`origins`, by ref; `_place`, and an encounter
    placed nowhere by its creatures, `_by_creature`): the heading's entry names them in `npcs` and `encounter` (the
    room's first encounter), and an NPC gets the heading as its `location` (unless it has a text's), every encounter the heading's key as its
    `key`, so the DM's `module_key` lists all of a room's encounters. An entity placed nowhere stays as it is."""
    scoped = scoped_keys(source.texts)
    headings = [
        _Heading(
            str(section.key),
            scoped[(doc.id, str(section.anchor))],
            bare(section.title),
            f"text:{doc.id}#{section.anchor}",
            doc.id,
            bare(f"{section.read_aloud}\n{section.gm_md}"),
        )
        for doc in source.texts
        for section in parse_text(doc.markdown).keyed()
    ]
    keys = scoped_entries(source)
    entities = {kind: [dict(record) for record in records] for kind, records in source.entities.items()}

    def entry(heading: _Heading) -> dict[str, Any]:
        found = next((k for k in keys if k.get("text") == heading.ref), None)
        if found is None:
            found = {"key": heading.scoped, "title": heading.title, "text": heading.ref, "npcs": []}
            keys.append(found)
        return found

    for heading in headings:
        entry(heading)
    for record in entities.get("encounters", []):
        own = origins.get(f"encounter:{record['id']}")
        heading = _place(record, headings, own) or _by_creature(record, headings, own)
        if heading is not None:
            at = entry(heading)
            at.setdefault("encounter", f"encounter:{record['id']}")
            record["key"] = f"key:{at['key']}"
    for record in entities.get("npcs", []):
        heading = _place(record, headings, origins.get(f"npc:{record['id']}"))
        if heading is not None:
            at = entry(heading)
            npcs = at.setdefault("npcs", [])
            if f"npc:{record['id']}" not in npcs:
                npcs.append(f"npc:{record['id']}")
            if not str(record.get("location") or "").startswith("text:"):
                record["location"] = heading.ref
    return replace(source, keys=keys, entities=entities)


# --- pictures --------------------------------------------------------------------------------------------------------


def _headings(chunk: list[PdfPage], answer: _Answer) -> list[tuple[int, str]]:
    """The answer's headings with the page each is on: the first page from the previous heading's that holds its
    title, else that page."""
    found = []
    at = 0
    texts = [bare(page.text).lower() for page in chunk]
    for section in parse_text(answer.markdown).sections:
        want = bare(section.title).lower()
        at = next((i for i in range(at, len(chunk)) if want and want in texts[i]), at)
        found.append((chunk[at].number, section.heading))
    return found


def map_page_id(number: int) -> str:
    """The attachment id of the book's map page `number`."""
    return f"map-page-{number}"


def _attachments(
    pages: list[PdfPage], headings: list[tuple[int, str]], progress: Progress
) -> tuple[list[tuple[Attachment, bytes]], list[Warning], list[tuple[str, HandoutBox]]]:
    """Each picture as a `gm` attachment, described by its page; a map page of the book as `map-page-<n>`, with a
    `book-map` warning, and every other picture with an `image-to-describe` one. Each handout of a page
    (`PdfPage.handouts`) is cut from its whole-page picture as `handout-<page>-<n>`, for the players, with an
    `audience-player` warning; the third value is the handouts, by attachment id, for `link_handouts`."""
    pictures: list[tuple[PdfPage, Picture]] = [(page, picture) for page in pages for picture in page.pictures]
    progress("pictures", 0, len(pictures))
    made: list[tuple[Attachment, bytes]] = []
    warnings: list[Warning] = []
    handouts: list[tuple[str, HandoutBox]] = []
    used: set[str] = set()
    for done, (page, picture) in enumerate(pictures, start=1):
        if page.map_page:
            id = unique(map_page_id(picture.page), used)
            title = map_title(page)
            description = f"Page {picture.page}: a map from the book" + (f" ({title})" if title else "")
            message = (
                f"“{description}” is the book's map, kept as it is: check it, and draw a map from it if you want one."
            )
            warning = Warning("book-map", message, f"asset:{id}")
        else:
            id = unique(f"page-{picture.page}", used)
            if picture.area >= 1.0:
                description = f"Page {picture.page}: a map or full-page picture"
            else:
                near = [heading for number, heading in headings if number <= picture.page]
                description = f"Page {picture.page}, near “{near[-1]}”" if near else f"Page {picture.page}"
            message = (
                f"The image from page {picture.page} is described only by its page: say what it shows and when it fits."
            )
            warning = Warning("image-to-describe", message, f"asset:{id}")
        attachment = Attachment(id, "image/png", sha256(picture.png), len(picture.png), description, "gm")
        made.append((attachment, picture.png))
        warnings.append(warning)
        if picture.area >= 1.0:
            for n, handout in enumerate(page.handouts, start=1):
                hid = unique(f"handout-{page.number}-{n}", used)
                png = cut(picture.png, handout.box)
                described = f"Handout from page {page.number}" + (f": {handout.title}" if handout.title else "")
                made.append((Attachment(hid, "image/png", sha256(png), len(png), described, "player"), png))
                warnings.append(players_warning(f"asset:{hid}"))
                handouts.append((hid, handout))
        progress("pictures", done, len(pictures))
    return made, warnings, handouts


def _names_part(doc: TextDoc, part: str) -> bool:
    """`part` ("ship", "The Sea Ghost") names the text: its words, without articles and part numbers, are all words of
    its title or its `part_slug`."""
    wanted = {w for w in re.split(r"[-._]+", slugify(part)) if w and w not in PART_STOP_WORDS}
    have = {*re.split(r"[-._]+", slugify(doc.title)), *part_slug(doc).split("-")}
    return bool(wanted) and wanted <= have


def link_handouts(source: ModuleSource, handouts: list[tuple[str, HandoutBox]]) -> tuple[ModuleSource, list[Warning]]:
    """`source` with each handout (by attachment id) in the `assets` of its room's `keys[]` entry: the one keyed
    heading with the handout's printed key, or, when several have it, the one of the text its `part` names. A handout
    that names no key, or none or more than one heading, is linked nowhere, with a `handout-not-linked` warning."""
    scoped = scoped_keys(source.texts)
    headings = [(doc, section) for doc in source.texts for section in parse_text(doc.markdown).keyed()]
    keys = [dict(entry) for entry in source.keys]
    warnings: list[Warning] = []
    for id, handout in handouts:
        key = (handout.key or "").casefold()
        found = [(doc, s) for doc, s in headings if key and str(s.key).casefold() == key]
        if len(found) > 1 and handout.part:
            found = [(doc, s) for doc, s in found if _names_part(doc, handout.part)]
        if len(found) != 1:
            name = f"“{handout.title}”" if handout.title else f"{id}"
            message = f"The handout {name} isn't linked to its room: add it to the room's attachments by hand."
            warnings.append(Warning("handout-not-linked", message, f"asset:{id}"))
            continue
        doc, section = found[0]
        ref = f"text:{doc.id}#{section.anchor}"
        entry = next((k for k in keys if k.get("text") == ref), None)
        if entry is None:
            entry = {
                "key": scoped[(doc.id, str(section.anchor))],
                "title": bare(section.title),
                "text": ref,
                "npcs": [],
            }
            keys.append(entry)
        entry["assets"] = [*entry.get("assets", []), f"asset:{id}"]
    return replace(source, keys=keys), warnings
