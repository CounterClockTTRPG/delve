"""Fix-it comments on a module (table voice and fixes Task F2.1): a `fixit` job that takes a module's open
comments and proposes the change they ask for, with the module's own editing operations, saved only when the
organiser keeps it, as a new revision.

A comment is sent `open` (`send_comment`), and starts a job unless the module has one running or waiting for review:
a module runs one fix-it job at a time, so no two jobs build on the same source. The job takes every `open` comment
of its module (`working`) and runs on the conversions' one slot, `queued` while it is taken (`runner._admit`), so a
queued job starts by itself, after a restart too (`restored`). When it starts it reads the module's working source and
maps, remembers their fingerprint (`fingerprint`, a hash of what Keep would write over; no revision is made), and asks
Claude once (`FIXIT_PROMPT`) for the operations that do what the comments ask: put or delete a text (Markdown), an
entity, the explicit keys, or a map (in the map language). Its `result` is the module as it would be,
`{revision, fingerprint, source, maps, summary}`, and its comments become `review` ("ready to review"); an answer that
isn't one, a map that doesn't parse, or one that changes a part an anchored comment didn't ask about
(`CHANGED_UNASKED`) fails the job and its comments, with the reason. Nothing is saved to the module.

The prompt holds what the comments touch, not the whole module (DEL-170: Thracia's 1.46 M characters were beyond the
window for a one-room comment): the parts they are anchored to, with a room's or a map's texts, the parts they name by
id, title or name, the explicit keys of those parts, and an index of the rest (texts with their headings, maps,
entities), within `PROMPT_BUDGET` characters, cut with a note beyond it. A comment with no anchor that names nothing
gets the whole module, in its order, within the same budget. The call has no tools, so Claude asks for more by
changing nothing and saying what it needs. An answer that replaces a part the prompt didn't show whole
(`NOT_SHOWN_WHOLE`) fails the job, and `put_keys` replaces only the keys shown.

`keep` writes the result over the module and snapshots a new revision, so campaigns pinned to the older one stay as
they are; it refuses with `FixitStale` when the module's source or maps changed since the job read them (an edit in
the editor), and `rerun` sends the comments again on the module as it now is. `reject` drops the result. Either starts
the next job when comments are `open`. A comment can be closed without running (`close_comment`). A job that ended
without a result (cancelled, or left running by a Delve that stopped) fails its `working` comments when they are next
read (`comments`)."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field, replace
from typing import Any

from delve.conversions import runner
from delve.conversions.runner import ConversionServices, _complete, _Live, _Start, conversion_json, finish, progress_for
from delve.domain.conversions import Conversion
from delve.domain.modules import ModuleComment, ModuleMap, Revision
from delve.maps.dsl.errors import DmapError
from delve.maps.sources import parse_map
from delve.modules.books.fences import unfenced
from delve.modules.dscn import parse_text
from delve.modules.source import Link, ModuleSource, TextDoc, derive, load_source, save_source
from delve.storage.interfaces import Storage

__all__ = [
    "CHANGED_UNASKED",
    "FIXIT_PROMPT",
    "NOT_SHOWN_WHOLE",
    "PROMPT_BUDGET",
    "FixitStale",
    "NotReviewable",
    "close_comment",
    "comment_json",
    "comments",
    "fingerprint",
    "keep",
    "reject",
    "rerun",
    "restored",
    "send_comment",
]

FIXIT_PROMPT = "You fix up a role-playing adventure module."
"""The first line of the fix-it prompt, by which the fake `claude` of the browser tests knows it."""
CHANGED_UNASKED = "It changed what the comment didn't ask"
"""The start of a job's reason when its result changes a part outside its comments' anchors."""
NOT_AN_ANSWER = "Claude's answer wasn't the operations asked for"
ENDED_WITHOUT_RESULT = "The job ended without a result."
STALE = "The module was changed since the job read it: run the comment again on the module as it is now."
ACTIVE = ("working", "review")
"""The statuses of a module's comments while it has a fix-it job running or waiting for review."""
TEXT_AUDIENCES = ("gm", "player")
TITLE_LENGTH = 80
PROMPT_BUDGET = 200_000
"""The most characters of a fix-it prompt, about 50k tokens, well inside a 200k-token window (DEL-170): Thracia's
whole module was 1.46 M characters. Parts beyond it are cut, or left to the index, with a note."""
INDEX_BUDGET = 40_000
"""The part of `PROMPT_BUDGET` kept for the index of the parts not shown (their names, titles and headings)."""
NOTES_BUDGET = 4_000
"""The part of `PROMPT_BUDGET` kept for the notes on what was cut or left out."""
CUT_LEAST = 2_000
"""A part is cut to what is left of the budget only when that is at least this much; else it is left to the index."""
NAME_LEAST = 3
"""The shortest id, title or name a comment's words are matched against, so `a` or `1` names nothing."""
NOT_SHOWN_WHOLE = "It replaced a part it wasn't shown whole"
"""The start of a job's reason when its answer puts a part the prompt cut or left out (DEL-170)."""


class FixitStale(Exception):
    """Keep on a result whose module changed since its job read it."""

    def __init__(self) -> None:
        super().__init__(STALE)


class NotAnAnswer(ValueError):
    """Claude's answer isn't the operations asked for."""

    def __init__(self, why: str = "") -> None:
        super().__init__(f"{NOT_AN_ANSWER}: {why}." if why else f"{NOT_AN_ANSWER}.")


class NotReviewable(KeyError):
    """No fix-it job with a result waiting for review."""


# ----- sending and starting -----


def send_comment(
    services: ConversionServices, module_id: str, text: str, *, anchor: dict[str, Any] | None, author: str
) -> ModuleComment:
    """Store the comment `open` and, unless the module has a fix-it job running or waiting for review, start one now
    (queued while the slot is taken). Answers the comment as stored once its job is started. `KeyError` for an
    unknown module, `ValueError` for an empty comment or an anchor that names nothing of the module."""
    text = text.strip()
    if not text:
        raise ValueError("Write what should be fixed.")
    storage = services.storage
    if storage.modules.get(module_id) is None:
        raise KeyError(module_id)
    _check_anchor(storage, module_id, anchor)
    comment = storage.module_comments.create(module_id, text, anchor=anchor, author=author)
    _start_next(services, module_id)
    return storage.module_comments.get(comment.id) or comment


def _check_anchor(storage: Storage, module_id: str, anchor: dict[str, Any] | None) -> None:
    if anchor is None:
        return
    module = storage.modules.get(module_id)
    source = load_source(storage, module_id)
    maps = {m.name for m in module.maps} if module is not None else set()
    kind = anchor.get("kind")
    if kind in ("map", "room") and anchor.get("map") in maps and (kind == "map" or anchor.get("node")):
        return
    if kind == "text" and any(t.id == anchor.get("text_id") for t in source.texts):
        return
    records = source.entities.get(str(anchor.get("entity_kind")), [])
    if kind == "entity" and any(r.get("id") == anchor.get("entity_id") for r in records):
        return
    raise ValueError("The comment's anchor names nothing of this module.")


def _start_next(services: ConversionServices, module_id: str) -> Conversion | None:
    """Start a job on the module's open comments, unless it has none, or has a job running or waiting for review."""
    storage = services.storage
    comments(storage, module_id)  # a job that ended without a result frees its comments first
    if storage.module_comments.with_status(module_id, *ACTIVE):
        return None
    taken = storage.module_comments.with_status(module_id, "open")
    if not taken:
        return None
    module = storage.modules.get(module_id)
    assert module is not None
    target = {"module_id": module_id, "revision": module.head_revision, "comment_ids": [c.id for c in taken]}
    with storage.transaction():
        admitted = runner._admit(services, "fixit", module.title[:TITLE_LENGTH], "ready", target=target)
        job = admitted.conversion if isinstance(admitted, runner._Live) else admitted
        for comment in taken:
            storage.module_comments.save(
                replace(comment, status="working", conversion_id=job.id, revision=module.head_revision, error=None)
            )
    return runner._begin(services, admitted, _start(services))


def _start(services: ConversionServices) -> _Start:
    return _Start(lambda live: _fix(services, live))


def restored(services: ConversionServices, conversion: Conversion) -> _Start | None:
    """How a `fixit` job queued before a restart starts, from its row; None while it can't (its module is gone)."""
    module_id = (conversion.target or {}).get("module_id")
    if not module_id or services.storage.modules.get(module_id) is None:
        return None
    return _start(services)


# ----- the job -----


async def _fix(services: ConversionServices, live: _Live) -> None:
    storage = services.storage
    target = live.conversion.target or {}
    module_id = target["module_id"]
    taken = [c for c in storage.module_comments.for_conversion(live.conversion.id) if c.status == "working"]
    progress = progress_for(services, live)
    progress("fixing", 0, 1)
    try:
        module = storage.modules.get(module_id)
        if module is None:
            raise KeyError(module_id)
        source = load_source(storage, module_id)
        maps = list(module.maps)
        prompt, shown = await asyncio.to_thread(_scoped, module.title, source, maps, taken)  # derive takes seconds
        answer = await _complete(services, live)(prompt)
        summary, after_source, after_maps = _applied(answer, source, maps, shown.keys)
        unasked = _unasked(taken, source, maps, after_source, after_maps)
        if unasked:
            raise ValueError(f"{CHANGED_UNASKED}: {', '.join(unasked)}.")
        unseen = _unseen(shown, source, maps, after_source, after_maps)
        if unseen:
            raise ValueError(f"{NOT_SHOWN_WHOLE}: {', '.join(unseen)}.")
    except Exception as error:
        _fail(storage, taken, str(error) or type(error).__name__)
        raise
    progress("fixing", 1, 1)
    result = {
        "revision": module.head_revision,
        "fingerprint": fingerprint(source, maps),
        "source": after_source.to_json(),
        "maps": [asdict(m) for m in after_maps],
        "summary": summary,
    }
    with storage.transaction():
        for comment in taken:
            storage.module_comments.save(replace(comment, status="review", revision=module.head_revision))
        finish(services, live, result=result)
    _changed(services, module_id)


def _fail(storage: Storage, taken: list[ModuleComment], reason: str) -> None:
    for comment in taken:
        current = storage.module_comments.get(comment.id)
        if current is not None and current.status == "working":
            storage.module_comments.save(replace(current, status="failed", error=reason))


def _changed(services: ConversionServices, module_id: str) -> None:
    services.publish("modules", {"id": module_id})


def fingerprint(source: ModuleSource, maps: list[ModuleMap] | tuple[ModuleMap, ...]) -> str:
    """A hash of a module's working source and maps, what Keep writes over: Keep refuses when it differs."""
    raw = json.dumps({"source": source.to_json(), "maps": [asdict(m) for m in maps]}, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ----- the prompt and the answer -----


def _where(anchor: dict[str, Any] | None, links: Sequence[Link] = ()) -> str:
    if anchor is None:
        return ""
    kind = anchor.get("kind")
    if kind == "map":
        return f" (on the map `{anchor.get('map')}`)"
    if kind == "room":
        held = [link for link in links if link.map == anchor.get("map") and link.node == anchor.get("node")]
        keyed = "".join(f", key {link.key} in the text `{link.text_id}`" for link in held)
        return f" (on the room `{anchor.get('node')}` of the map `{anchor.get('map')}`{keyed})"
    if kind == "text":
        return f" (on the text `{anchor.get('text_id')}`)"
    return f" (on the {anchor.get('entity_kind')} entity `{anchor.get('entity_id')}`)"


@dataclass
class _Shown:
    """What a fix-it prompt showed of the module (DEL-170): the parts shown whole (`text:<id>`, `map:<name>`,
    `entity:<kind>/<id>`), and the indices in `source.keys` of the explicit keys shown, which `put_keys` replaces."""

    whole: set[str] = field(default_factory=set)
    keys: list[int] = field(default_factory=list)


def _named_in(text: str, name: str) -> bool:
    """Whether the comment `text` names `name` (an id, a title or a name), as words, ignoring case."""
    if len(name.strip()) < NAME_LEAST:
        return False
    return re.search(rf"(?<![\w-]){re.escape(name.strip())}(?![\w-])", text, re.IGNORECASE) is not None


def _holders(
    name: str, source: ModuleSource, maps: list[ModuleMap], links: list[Link], node: str | None = None
) -> list[str]:
    """The texts that hold the map `name`'s rooms, those keyed to `node` first: the texts with a room linked on the map
    (`derive`'s links, explicit or found), the texts on it, and, for the default map, the texts on no map that have
    keyed sections."""
    default = next((m.name for m in maps if m.is_default), None)
    first = [f"text:{link.text_id}" for link in links if link.map == name and node is not None and link.node == node]
    on = [f"text:{link.text_id}" for link in links if link.map == name]
    for doc in source.texts:
        if doc.map == name or (doc.map is None and name == default and parse_text(doc.markdown).keyed()):
            on.append(f"text:{doc.id}")
    return list(dict.fromkeys([*first, *on]))


def _touched(
    taken: list[ModuleComment], source: ModuleSource, maps: list[ModuleMap], links: list[Link]
) -> list[str] | None:
    """The parts the comments touch, in the order a prompt shows them (DEL-170): each anchored part (a room's text
    before its map; a map's texts after it), then each part a comment names by its id, title or name. None when a
    comment has no anchor and names nothing: it may be about any part, so the whole module is shown, in its order."""
    parts: list[str] = []
    for comment in taken:
        anchor = comment.anchor or {}
        kind = anchor.get("kind")
        if kind == "text":
            parts.append(f"text:{anchor.get('text_id')}")
        elif kind == "entity":
            parts.append(f"entity:{anchor.get('entity_kind')}/{anchor.get('entity_id')}")
        elif kind == "room":
            held = _holders(str(anchor.get("map")), source, maps, links, str(anchor.get("node")))
            parts += [*held[:1], f"map:{anchor.get('map')}", *held[1:]]
        elif kind == "map":
            parts += [f"map:{anchor.get('map')}", *_holders(str(anchor.get("map")), source, maps, links)]
    named: list[str] = []
    for comment in taken:
        for doc in source.texts:
            if _named_in(comment.text, doc.id) or _named_in(comment.text, doc.title):
                named.append(f"text:{doc.id}")
        named += [f"map:{m.name}" for m in maps if _named_in(comment.text, m.name)]
        for kind, records in source.entities.items():
            for record in records:
                if any(_named_in(comment.text, str(record.get(field) or "")) for field in ("id", "name")):
                    named.append(f"entity:{kind}/{record.get('id')}")
    if not named and any(c.anchor is None for c in taken):
        return None
    return list(dict.fromkeys([*parts, *named]))


def _blocks(source: ModuleSource, maps: list[ModuleMap]) -> dict[str, tuple[str, str, str]]:
    """Every part of the module as the prompt shows it: `(heading, tag, body)`; an entity's body is its JSON."""
    blocks: dict[str, tuple[str, str, str]] = {}
    for doc in source.texts:
        on = f", map `{doc.map}`" if doc.map else ""
        blocks[f"text:{doc.id}"] = (f"### Text `{doc.id}`: {doc.title} ({doc.audience}{on})", "text", doc.markdown)
    for module_map in maps:
        default = ", the default" if module_map.is_default else ""
        blocks[f"map:{module_map.name}"] = (
            f"### Map `{module_map.name}` ({module_map.role}{default})",
            "map",
            module_map.source,
        )
    for kind, records in source.entities.items():
        for record in records:
            body = json.dumps(record, indent=2, ensure_ascii=False)
            blocks[f"entity:{kind}/{record.get('id')}"] = (f"### Entity `{kind}/{record.get('id')}`", "entity", body)
    return blocks


def _cut_note(shown: int, length: int) -> str:
    return (
        f"(Cut: the first {shown:,} of its {length:,} characters are shown, for the prompt's size. Don't replace it: "
        "you haven't seen it whole.)"
    )


def _index(source: ModuleSource, maps: list[ModuleMap], whole: set[str]) -> list[str]:
    """The module's parts not shown whole, for Claude to refer to by name: each text with its headings, each map, and
    each entity's id and name, cut at `INDEX_BUDGET` with a note."""
    lines: list[str] = []
    texts = [doc for doc in source.texts if f"text:{doc.id}" not in whole]
    if texts:
        lines += ["Texts:"]
        for doc in texts:
            on = f", map `{doc.map}`" if doc.map else ""
            headings = "; ".join(s.heading for s in parse_text(doc.markdown).sections)
            lines.append(f"- `{doc.id}`: {doc.title} ({doc.audience}{on}, {len(doc.markdown):,} characters)")
            if headings:
                lines.append(f"  Headings: {headings}")
    others = [m for m in maps if f"map:{m.name}" not in whole]
    if others:
        lines += ["Maps:"]
        for m in others:
            default = ", the default" if m.is_default else ""
            lines.append(f"- `{m.name}` ({m.role}{default}, {len(m.source):,} characters)")
    for kind, records in source.entities.items():
        rest = [r for r in records if f"entity:{kind}/{r.get('id')}" not in whole]
        if rest:
            named = ", ".join(f"`{r.get('id')}`" + (f" ({r['name']})" if r.get("name") else "") for r in rest)
            lines.append(f"Entities `{kind}`: {named}")
    kept: list[str] = []
    size = 0
    for line in lines:
        if size + len(line) + 1 > INDEX_BUDGET:
            kept.append(f"(The index is cut here, for the prompt's size: {len(lines) - len(kept)} lines more.)")
            break
        kept.append(line)
        size += len(line) + 1
    return kept


def _shown_keys(source: ModuleSource, whole: set[str]) -> list[int]:
    """The explicit keys that belong to a part shown whole (by their `text` or `node`), or to none."""
    shown = []
    for n, key in enumerate(source.keys):
        refs = [str(key.get(field) or "").partition("#")[0] for field in ("text", "node")]
        refs = [ref for ref in refs if ref.startswith(("text:", "map:"))]
        if not refs or any(ref in whole for ref in refs):
            shown.append(n)
    return shown


def _prompt(title: str, source: ModuleSource, maps: list[ModuleMap], taken: list[ModuleComment]) -> str:
    return _scoped(title, source, maps, taken)[0]


def _scoped(title: str, source: ModuleSource, maps: list[ModuleMap], taken: list[ModuleComment]) -> tuple[str, _Shown]:
    """The fix-it prompt, and what it shows of the module (DEL-170). It sends what the comments touch (`_touched`),
    whole while `PROMPT_BUDGET` lasts, then cut with a note, then left out; the explicit keys of the parts shown;
    and an index of the rest. The answer is one call with no tools, so Claude asks for more by changing nothing and
    naming what it needs in its summary."""
    on_maps = any((c.anchor or {}).get("kind") in ("map", "room") for c in taken)
    links = derive(source, maps).links if on_maps else []
    head = [
        FIXIT_PROMPT,
        "",
        f"The organiser of the module “{title}” left comments on it. Change what they ask, and nothing else: a comment",
        "tied to a part of the module (a map, a room, a text or an entity) changes that part only, and what holds it",
        "(a room's map and the texts keyed to it).",
        "",
        "## The comments",
        "",
        *[f"{n}. {c.text}{_where(c.anchor, links)}" for n, c in enumerate(taken, start=1)],
        "",
    ]
    tail = [
        "## How to answer",
        "",
        'Answer one JSON object, nothing else: {"summary": "<one sentence: what you changed>", "operations": [...]}.',
        "Each operation is one of:",
        '- {"op": "put_text", "id", "markdown", "title"?, "audience"?, "map"?}: the whole text, new or replaced;',
        '- {"op": "delete_text", "id"};',
        '- {"op": "put_map", "name", "source"}: the whole map in the map language, new or replaced;',
        '- {"op": "delete_map", "name"};',
        '- {"op": "put_entity", "kind", "record"}: the whole record, with its "id", new or replaced;',
        '- {"op": "delete_entity", "kind", "id"};',
        '- {"op": "put_keys", "keys"}: every explicit key shown under "Keys", which it replaces; the others stay.',
        "Leave out every part you don't change. Replace only a part shown whole above: one cut or only in the index",
        "can't be replaced. If the fix needs a part that isn't shown, change nothing and say in the summary which",
        "parts you need, so the organiser can tie the comment to them or name them.",
    ]
    blocks = _blocks(source, maps)
    touched = _touched(taken, source, maps, links)
    order = list(blocks) if touched is None else [part for part in touched if part in blocks]
    left = PROMPT_BUDGET - INDEX_BUDGET - len("\n".join([*head, *tail])) - NOTES_BUDGET
    shown = _Shown()
    body: list[str] = []
    entities: dict[str, list[dict[str, Any]]] = {}
    out: list[str] = []
    for part in order:
        heading, tag, text = blocks[part]
        if part.startswith("entity:"):
            kind, _, entity_id = part.removeprefix("entity:").partition("/")
            record = next(r for r in source.entities[kind] if str(r.get("id")) == entity_id)
            size = len(text) + 4 * (text.count("\n") + 1)  # indented twice in `### Entities`
            if size <= left:
                entities.setdefault(kind, []).append(record)
                shown.whole.add(part)
                left -= size
            else:
                out.append(part)
            continue
        size = len(heading) + len(text) + 2 * len(tag) + 10
        if size <= left:
            body += [heading, "", f"<{tag}>", text, f"</{tag}>", ""]
            shown.whole.add(part)
            left -= size
        elif left - len(heading) >= CUT_LEAST:
            cut = left - len(heading) - 400
            body += [heading, "", _cut_note(cut, len(text)), "", f"<{tag}>", text[:cut], f"</{tag}>", ""]
            left = 0
        else:
            out.append(part)
    if entities:
        body += ["### Entities", "", json.dumps(entities, indent=2, ensure_ascii=False), ""]
    keys = _shown_keys(source, shown.whole)
    listed: list[str] = []
    for n in keys:
        entry = json.dumps(source.keys[n], ensure_ascii=False)
        if len(entry) + 4 > left:
            break
        listed.append(entry)
        shown.keys.append(n)
        left -= len(entry) + 4
    if listed:
        more = len(source.keys) - len(listed)
        note = f" ({more:,} more, of parts not shown, stay as they are)" if more else ""
        body += [f"### Keys{note}", "", "[", ",\n".join(f"  {entry}" for entry in listed), "]", ""]
    module = ["## The module", ""]
    if touched is not None:
        module += ["Shown below: the parts of the module the comments touch; the index lists the others.", ""]
    if out:
        listed_out = ", ".join(f"`{part}`" for part in out[:50]) + (
            f" and {len(out) - 50} more" if len(out) > 50 else ""
        )
        module += [f"Left out for the prompt's size: {listed_out}.", ""]
    index = _index(source, maps, shown.whole)
    if index:
        body += ["### Index of the parts not shown", "", *index, ""]
    return "\n".join([*head, *module, *body, *tail]) + "\n", shown


def _applied(
    answer: str, source: ModuleSource, maps: list[ModuleMap], keys_shown: Sequence[int] | None = None
) -> tuple[str, ModuleSource, list[ModuleMap]]:
    """The answer's summary, and the module's source and maps with its operations applied. `ValueError` for an
    answer that isn't the operations asked for, or a map that doesn't parse. `keys_shown` are the indices of the
    explicit keys the prompt showed (all when None): `put_keys` replaces those, in the place of the first, and the
    others stay (DEL-170)."""
    try:
        parsed = json.loads(unfenced(answer))
    except ValueError:
        raise NotAnAnswer() from None
    if not isinstance(parsed, dict) or not isinstance(parsed.get("operations"), list):
        raise NotAnAnswer()
    texts = {t.id: t for t in source.texts}
    entities = {kind: list(records) for kind, records in source.entities.items()}
    keys = list(source.keys)
    after = {m.name: m for m in maps}
    for op in parsed["operations"]:
        _apply(op, texts, entities, keys, after)
        if isinstance(op, dict) and op.get("op") == "put_keys" and keys_shown is not None:
            keys[:] = _merged_keys(source.keys, keys_shown, keys)
    for name, module_map in after.items():
        if module_map.role == "map" and not any(m.source == module_map.source for m in maps if m.name == name):
            try:
                parse_map(list(after.values()), name)
            except DmapError as error:
                raise ValueError(f"The map {name} doesn't parse: {error}") from None
    first = next((m for m in after.values() if m.role == "map"), None)
    if first is not None and not any(m.is_default for m in after.values()):
        after[first.name] = replace(first, is_default=True)
    summary = parsed.get("summary")
    changed = replace(source, texts=list(texts.values()), entities=entities, keys=keys)
    return (summary if isinstance(summary, str) else ""), changed, list(after.values())


def _apply(
    op: Any,
    texts: dict[str, TextDoc],
    entities: dict[str, list[dict[str, Any]]],
    keys: list[dict[str, Any]],
    maps: dict[str, ModuleMap],
) -> None:
    if not isinstance(op, dict):
        raise NotAnAnswer("an operation isn't an object")
    kind = op.get("op")
    name = op.get("id") if kind in ("put_text", "delete_text", "delete_entity") else op.get("name")
    if kind in ("put_text", "delete_text", "put_map", "delete_map", "delete_entity") and not _named(name):
        raise NotAnAnswer(f"{kind} names nothing")
    if kind == "put_text":
        old = texts.get(name)
        audience = op.get("audience", old.audience if old else "gm")
        if not isinstance(op.get("markdown"), str) or audience not in TEXT_AUDIENCES:
            raise NotAnAnswer(f"the text {name} has no Markdown")
        title = op.get("title") or (old.title if old else name)
        on = op.get("map", old.map if old else None)
        texts[name] = TextDoc(name, str(title), audience, on if _named(on) else None, op["markdown"])
    elif kind == "delete_text":
        texts.pop(name, None)
    elif kind == "put_map":
        if not isinstance(op.get("source"), str):
            raise NotAnAnswer(f"the map {name} has no source")
        old_map = maps.get(name)
        role = old_map.role if old_map else "map"
        maps[name] = ModuleMap(name, role, op["source"], old_map.is_default if old_map else not maps)
    elif kind == "delete_map":
        maps.pop(name, None)
    elif kind in ("put_entity", "delete_entity"):
        record = op.get("record") if kind == "put_entity" else None
        entity_kind = op.get("kind")
        entity_id = record.get("id") if isinstance(record, dict) else name
        if not _named(entity_kind) or not _named(entity_id):
            raise NotAnAnswer(f"{kind} names no entity")
        records = [r for r in entities.get(entity_kind, []) if r.get("id") != entity_id]
        if kind == "put_entity":
            old_index = next((n for n, r in enumerate(entities.get(entity_kind, [])) if r.get("id") == entity_id), None)
            records.insert(len(records) if old_index is None else old_index, dict(record))  # type: ignore[arg-type]
        entities[entity_kind] = records
    elif kind == "put_keys":
        if not isinstance(op.get("keys"), list) or not all(isinstance(k, dict) for k in op["keys"]):
            raise NotAnAnswer("put_keys has no keys")
        keys[:] = [dict(k) for k in op["keys"]]
    else:
        raise NotAnAnswer(f"no operation {kind!r}")


def _merged_keys(old: list[dict[str, Any]], shown: Sequence[int], new: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The explicit keys after a `put_keys` of `new` on a prompt that showed `old`'s `shown`: those replaced by
    `new`, where the first of them was (at the end when none was shown); the others as they were (DEL-170)."""
    hidden = set(range(len(old))) - set(shown)
    at = min(shown) if shown else len(old)
    return [*(old[n] for n in sorted(hidden) if n < at), *new, *(old[n] for n in sorted(hidden) if n >= at)]


def _unseen(
    shown: _Shown,
    source: ModuleSource,
    maps: list[ModuleMap],
    after_source: ModuleSource,
    after_maps: list[ModuleMap],
) -> list[str]:
    """The parts the result replaced that the prompt didn't show whole (cut, or only in the index), sorted: Claude
    wrote them without seeing them, and would lose what it didn't see (DEL-170). A new part or a deleted one is
    no such part, nor are the keys, which `put_keys` merges."""
    before, after = _parts(source, maps), _parts(after_source, after_maps)
    changed = _changed_parts(source, maps, after_source, after_maps)
    return sorted(p for p in changed if p in before and p in after and p != "keys" and p not in shown.whole)


def _named(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _parts(source: ModuleSource, maps: list[ModuleMap]) -> dict[str, Any]:
    """Each part of a module by a name of its own (`text:<id>`, `map:<name>`, `entity:<kind>/<id>`, `keys`), for
    telling which ones a result changed."""
    parts: dict[str, Any] = {f"text:{t.id}": asdict(t) for t in source.texts}
    parts |= {f"map:{m.name}": asdict(m) for m in maps}
    for kind, records in source.entities.items():
        parts |= {f"entity:{kind}/{r.get('id')}": r for r in records}
    parts["keys"] = source.keys
    return parts


def _changed_parts(
    source: ModuleSource, maps: list[ModuleMap], after_source: ModuleSource, after_maps: list[ModuleMap]
) -> set[str]:
    before, after = _parts(source, maps), _parts(after_source, after_maps)
    return {name for name in before.keys() | after.keys() if before.get(name) != after.get(name)}


def _allowed(anchor: dict[str, Any], source: ModuleSource, maps: list[ModuleMap]) -> set[str]:
    """What a comment anchored at `anchor` may change: its text or entity; for a map or a room, the map, the texts
    keyed to it and the explicit keys."""
    kind = anchor.get("kind")
    if kind == "text":
        return {f"text:{anchor.get('text_id')}"}
    if kind == "entity":
        return {f"entity:{anchor.get('entity_kind')}/{anchor.get('entity_id')}"}
    name = anchor.get("map")
    default = next((m.name for m in maps if m.is_default), None)
    on = {f"text:{t.id}" for t in source.texts if (t.map or default) == name}
    return {f"map:{name}", "keys", *on}


def _unasked(
    taken: list[ModuleComment],
    source: ModuleSource,
    maps: list[ModuleMap],
    after_source: ModuleSource,
    after_maps: list[ModuleMap],
) -> list[str]:
    """The parts the result changed that no comment asked about, sorted; none when a comment has no anchor."""
    if any(c.anchor is None for c in taken):
        return []
    allowed = set().union(*(_allowed(c.anchor, source, maps) for c in taken if c.anchor is not None))
    return sorted(_changed_parts(source, maps, after_source, after_maps) - allowed)


# ----- the review -----


def _reviewable(storage: Storage, conversion_id: str) -> tuple[Conversion, list[ModuleComment]]:
    """The fix-it job with a result waiting for review, and its comments; `NotReviewable` for anything else."""
    job = storage.conversions.get(conversion_id)
    taken = [c for c in storage.module_comments.for_conversion(conversion_id) if c.status == "review"]
    if job is None or job.kind != "fixit" or job.status != "done" or not job.result or not taken:
        raise NotReviewable(conversion_id)
    return job, taken


def result_of(storage: Storage, conversion_id: str) -> tuple[Conversion, ModuleSource, list[ModuleMap]]:
    """The job waiting for review, and the module's source and maps as its result would make them."""
    job, _ = _reviewable(storage, conversion_id)
    return job, *_proposed(job)


def _proposed(job: Conversion) -> tuple[ModuleSource, list[ModuleMap]]:
    result = job.result or {}
    return ModuleSource.from_json(result["source"]), [ModuleMap(**m) for m in result["maps"]]


def is_stale(storage: Storage, job: Conversion) -> bool:
    """Whether the module's source or maps changed since the job read them."""
    module_id = (job.target or {})["module_id"]
    module = storage.modules.get(module_id)
    if module is None:
        return True
    return fingerprint(load_source(storage, module_id), module.maps) != (job.result or {}).get("fingerprint")


def keep(services: ConversionServices, conversion_id: str) -> Revision:
    """Write the job's result over the module and snapshot a new revision; its comments become `kept`, then the next
    job starts if comments are open. `FixitStale` when the module changed since the job read it; `NotReviewable`
    (a `KeyError`) for no job waiting for review."""
    storage = services.storage
    with storage.transaction():  # the checks too: an editor's save between them and the writes would be lost
        job, taken = _reviewable(storage, conversion_id)
        source, maps = _proposed(job)
        module_id = (job.target or {})["module_id"]
        if is_stale(storage, job):
            raise FixitStale()
        module = storage.modules.get(module_id)
        assert module is not None
        wanted = {m.name for m in maps}
        for old in module.maps:
            if old.name not in wanted:
                storage.modules.delete_map(module_id, old.name)
        for module_map in maps:
            if module_map not in module.maps:
                storage.modules.put_map(module_id, module_map)
        save_source(storage, module_id, source)
        revision = storage.revisions.snapshot(module_id)
        for comment in taken:
            storage.module_comments.save(replace(comment, status="kept", revision=revision.number))
        storage.conversions.save(replace(job, result={**(job.result or {}), "kept": revision.number}))
    _changed(services, module_id)
    _start_next(services, module_id)
    return revision


def reject(services: ConversionServices, conversion_id: str) -> None:
    """Drop the job's result: its comments become `rejected`, and the next job starts if comments are open.
    `NotReviewable` for no job waiting for review."""
    storage = services.storage
    job, taken = _reviewable(storage, conversion_id)
    with storage.transaction():
        for comment in taken:
            storage.module_comments.save(replace(comment, status="rejected"))
    module_id = (job.target or {})["module_id"]
    _changed(services, module_id)
    _start_next(services, module_id)


def rerun(services: ConversionServices, comment_id: str) -> ModuleComment:
    """A failed or rejected comment, or one waiting for review (with the other comments of its job, whose result is
    dropped), back to `open`, starting a job as `send_comment` does. `KeyError` for an unknown comment, `ValueError`
    for one open, working, kept or closed."""
    storage = services.storage
    comment = storage.module_comments.get(comment_id)
    if comment is None:
        raise KeyError(comment_id)
    comments(storage, comment.module_id)
    comment = storage.module_comments.get(comment_id) or comment
    if comment.status not in ("failed", "rejected", "review"):
        raise ValueError(f"A {comment.status} comment can't be run again.")
    again = [comment]
    if comment.status == "review" and comment.conversion_id is not None:
        again = [c for c in storage.module_comments.for_conversion(comment.conversion_id) if c.status == "review"]
    with storage.transaction():
        for each in again:
            storage.module_comments.save(replace(each, status="open", conversion_id=None, error=None))
    _start_next(services, comment.module_id)
    _changed(services, comment.module_id)
    return storage.module_comments.get(comment_id) or comment


def close_comment(storage: Storage, comment_id: str) -> ModuleComment:
    """An `open` comment closed without running. `KeyError` for an unknown comment, `ValueError` for another
    status."""
    comment = storage.module_comments.get(comment_id)
    if comment is None:
        raise KeyError(comment_id)
    if comment.status != "open":
        raise ValueError(f"Only an open comment can be closed, not a {comment.status} one.")
    return storage.module_comments.save(replace(comment, status="closed"))


def comments(storage: Storage, module_id: str) -> list[ModuleComment]:
    """The module's comments, oldest first. A `working` comment whose job ended without a result (cancelled, failed
    elsewhere, or left by a Delve that stopped) fails here, with its job's reason."""
    listed = storage.module_comments.list(module_id)
    settled = []
    for comment in listed:
        if comment.status == "working" and comment.conversion_id is not None:
            job = storage.conversions.get(comment.conversion_id)
            if job is None or job.status in ("failed", "cancelled") or (job.status == "done" and not job.result):
                reason = (job.error if job is not None else None) or ENDED_WITHOUT_RESULT
                comment = storage.module_comments.save(replace(comment, status="failed", error=reason))
        settled.append(comment)
    return settled


def comment_json(storage: Storage, comment: ModuleComment) -> dict[str, Any]:
    """A comment as the API answers it, with its job's `job` `{status, step, done, total, steps}` (null without one)."""
    job = storage.conversions.get(comment.conversion_id) if comment.conversion_id else None
    progress = None
    if job is not None:
        shown = conversion_json(job)
        progress = {k: shown[k] for k in ("id", "status", "step", "done", "total", "steps")}
    return {**asdict(comment), "job": progress}
