"""Dungeon-map drafts (plan 7 Task 13): Claude draws a module's map from a description (`dungeon-map`), or from the
book's own map page, seen through a vision call (`book-map`). Either is a conversion job that makes no module.

A draft is the job's `result`, `{module_id, name, source, warnings, kept, discarded}`; nothing is saved in the module
until the organiser keeps it, so several drafts can be compared first. A kept description draft is a new map (a name
taken gets `-2`); a kept book draft replaces the sketch it was drawn for, its first line `FROM_BOOK` instead of
`SKETCHED`. A description draft carries the room key of the texts no map links yet, so their headings link to its
rooms once it is kept (`texts`, the texts it then points to); a book draft the room key of the texts on its sketch.
A discarded draft stays in `conversions`, marked, and is no longer listed. A PDF conversion draws a book draft for
each of the book's map pages once the module is made, unless asked not to (`draw_book_maps`, faithful modules B2).

Faithful modules (Task 3): any of the book's map pages or full-page pictures (`BOOK_PICTURE`) can be drawn, for a map
or as a new one, and for a part (a text): its rooms come from that part only, never from the default map's texts.
Keep compares the draft's rooms with its part (`mismatch`) and refuses one labelled with another part's rooms, unless
forced.

Faithful modules (Task 4): a book draft is one map per level of its page (`maps`, `{name, title, source, part}`), each
for a part; `name` and `source` are its first level's, for older readers. Keep saves every level, the first over the
map it replaces, checks each against its own part, and links each room `r<key>` of a level to its part's heading with
that key by an explicit `keys[]` entry with a `node`, so one text can span several maps (`_link_levels`).
"""

from __future__ import annotations

import re
from dataclasses import asdict, replace
from typing import Any

from delve.conversions.runner import (
    BOOK_MAP,
    SKETCHED,
    ConversionRunning,
    ConversionServices,
    _complete,
    _keyed_rooms,
    _Live,
    finish,
    look_for,
    plate_matches,
    progress_for,
    start_job,
    wait,
)
from delve.domain.conversions import Conversion
from delve.domain.modules import Module, ModuleMap
from delve.maps.dsl import DungeonMap
from delve.maps.sources import graph_of, parse_source
from delve.modules.books.convert import text_id
from delve.modules.books.sketch import DESCRIBED, FROM_BOOK, Part, describe_map, draw_from_page, room_name
from delve.modules.dscn import parse_ref
from delve.modules.dscn.text import parse_heading, parse_text
from delve.modules.source import (
    Attachment,
    SourceStorage,
    TextDoc,
    derive,
    load_source,
    save_source,
    scoped_keys,
)
from delve.modules.text import unique
from delve.storage.interfaces import Storage

__all__ = [
    "BOOK_PICTURE",
    "DRAFT_KINDS",
    "DraftMismatch",
    "discard_draft",
    "drafts",
    "draw_book_maps",
    "keep_draft",
    "mismatch",
    "start_book_map",
    "start_dungeon_map",
]

DRAFT_KINDS = ("dungeon-map", "book-map")
MAP_PAGE = re.compile(r"map-page-(\d+)")
SKETCH_OF_PAGE = re.compile(re.escape(f"{SKETCHED} {BOOK_MAP}").replace(re.escape("{page}"), f"({MAP_PAGE.pattern})"))
"""A sketch's first line when it names the book's map page."""
BOOK_PICTURE = re.compile(r"(?:map-)?page-(\d+)(?:-\d+)?")
"""The ids of the book's pictures a map can be drawn from: a map page of the book (`map-page-<n>`), or another
picture, which must be a full-page one (`_is_book_picture`)."""
FULL_PAGE = "Page {page}: a map or full-page picture"
"""How the conversion describes a full-page picture that isn't a map page; a smaller one is described by its page and
nearest heading, and can't be drawn from."""
_TITLE = re.compile(r"\(([^()]*)\)\s*$")
"""The title at the end of a map page's description, `Page 2: a map from the book (The Haunted House)`."""
NAME_LENGTH = 40
"""The longest name a draft takes from its description."""
UNNAMED = "map"


def _module(storage: Storage, module_id: str) -> Module:
    module = storage.modules.get(module_id)
    if module is None:
        raise KeyError(module_id)
    return module


def _draft_name(description: str) -> str:
    """A draft's name from its description's first words, when it is given none."""
    first = description.strip().splitlines()[0][:NAME_LENGTH]
    name = text_id(first).strip("-_.")
    return name if name and name != "text" else UNNAMED


def _rooms(texts: list[TextDoc]) -> list[tuple[str, str]]:
    """The texts' keyed rooms, each key once."""
    rooms: dict[str, str] = {}
    for text in texts:
        for key, room in _keyed_rooms(text):
            rooms.setdefault(key, room)
    return list(rooms.items())


def _unlinked(storage: SourceStorage, module: Module) -> list[TextDoc]:
    """The texts with keyed headings none of which a map links yet, and whose keys don't repeat."""
    source = load_source(storage, module.id)
    linked = {link.text_id for link in derive(source, module.maps).links}
    unlinked = []
    for text in source.texts:
        keys = [key for key, _ in _keyed_rooms(text)]
        if keys and text.id not in linked and len(set(keys)) == len(keys):
            unlinked.append(text)
    return unlinked


def _part_texts(storage: SourceStorage, module: Module, map_name: str | None, part: str | None) -> list[TextDoc]:
    """The texts a book draft takes its rooms from: the text `part`, else the texts that name the map `map_name`, else
    none. Never the default map's texts by default: a part's draft holds no other part's rooms."""
    texts = load_source(storage, module.id).texts
    if part is not None:
        return [t for t in texts if t.id == part]
    return [t for t in texts if map_name is not None and t.map == map_name]


def _draft_parts(storage: SourceStorage, module: Module, map_name: str | None, part: str | None) -> list[Part]:
    """The parts a book draft's levels may be for, with their keyed headings: those of `_part_texts`, else every text
    with keyed headings, each level then naming its own part, which Keep checks it against."""
    texts = _part_texts(storage, module, map_name, part) or load_source(storage, module.id).texts
    parts = []
    for text in texts:
        rooms = [(str(s.key), s.heading) for s in parse_text(text.markdown).keyed()]
        if rooms:
            parts.append(Part(text.id, text.title, list(dict(rooms).items())))
    return parts


def _is_book_picture(attachment: Attachment) -> bool:
    """A map page of the book, or a full-page picture of it as the conversion describes one."""
    match = BOOK_PICTURE.fullmatch(attachment.id)
    if match is None or not attachment.is_image:
        return False
    return attachment.id.startswith("map-") or attachment.description.startswith(FULL_PAGE.format(page=match.group(1)))


def _page_map_name(attachment: Attachment) -> str:
    """A new map's name from the page's description: its title in parentheses, else the page's id."""
    title = _TITLE.search(attachment.description)
    name = text_id(title.group(1)) if title else "text"
    return name if name != "text" else attachment.id


def _normalized(title: str) -> str:
    """A title to compare: its leading key removed, casefolded, alphanumerics only."""
    _, _, _, rest = parse_heading(title.strip())
    return "".join(c for c in rest.casefold() if c.isalnum())


def mismatch(source: str | DungeonMap, part_text: TextDoc) -> list[str]:
    """What doesn't match between a draft's rooms and its part's keyed headings: each `r<key>` room of one of the part's
    keys labelled with another title, and the draft as a whole when over half its `r<key>` rooms are no key of it.
    `source` may be parsed already."""
    titles = {room_name(s.key): (s.key, s.title) for s in parse_text(part_text.markdown).sections if s.key}
    rooms = (parse_source(source) if isinstance(source, str) else source).rooms
    keyed = [room for name, room in rooms.items() if name.startswith("r") and len(name) > 1]
    problems = []
    for room in keyed:
        if room.name in titles and room.label is not None:
            key, title = titles[room.name]
            if _normalized(room.label.text) != _normalized(title):
                problems.append(
                    f"Room {room.name} is labelled “{room.label.text}”, but {key} of {part_text.title} is “{title}”."
                )
    strangers = [room for room in keyed if room.name not in titles]
    if keyed and len(strangers) * 2 > len(keyed):
        problems.append(f"{len(strangers)} of the draft's {len(keyed)} keyed rooms aren't keys of {part_text.title}.")
    return problems


class DraftMismatch(ValueError):
    """A draft whose rooms don't match its part: Keep refuses it unless forced."""

    def __init__(self, part_title: str, problems: list[str]) -> None:
        super().__init__(f"The draft's rooms don't match {part_title}.")
        self.problems = problems


def _result(module_id: str, name: str, source: str | None, warnings: list, **more: Any) -> dict[str, Any]:
    return {
        "module_id": module_id,
        "name": name,
        "source": source,
        "warnings": [asdict(w) for w in warnings],
        "kept": False,
        "discarded": False,
        **more,
    }


async def start_dungeon_map(
    services: ConversionServices, module_id: str, name: str | None, description: str
) -> Conversion:
    """Start drawing a map for the module from `description`, named `name` (else after the description).
    `KeyError` for an unknown module, `ValueError` for an empty description, `ConversionRunning` while a job runs."""
    description = description.strip()
    if not description:
        raise ValueError("Describe the map you want.")
    _module(services.storage, module_id)
    name = (name or "").strip() or _draft_name(description)

    async def work(live: _Live) -> None:
        progress = progress_for(services, live)
        progress("drawing", 0, 1)
        texts = _unlinked(services.storage, _module(services.storage, module_id))
        source, warnings = await describe_map(name, description, _rooms(texts), _complete(services))
        progress("drawing", 1, 1)
        drawn = f"{DESCRIBED}\n{source}" if source is not None else None
        texts_ids = [t.id for t in texts] if source is not None else []
        result = _result(module_id, name, drawn, warnings, texts=texts_ids)
        finish(services, live, result=result, warnings=warnings)

    title = description.splitlines()[0][:80]
    return await start_job(services, "dungeon-map", title, work, target={"module_id": module_id, "name": name})


async def start_book_map(
    services: ConversionServices,
    module_id: str,
    map_name: str | None,
    page_asset: str,
    *,
    part: str | None = None,
    batch: dict[str, int] | None = None,
) -> Conversion:
    """Start drawing the module's map `map_name` (else a new map, named after the page) from the book's picture
    `page_asset` (`BOOK_PICTURE`), with the rooms of the text `part` (else of the texts that name the map, else of
    every text). `batch`, `{index, count}`, is its place among the pages a conversion drafts: the job is then titled
    "page <n>". `KeyError` for an unknown module, map or part, `ValueError` for a picture that isn't a map page or a
    full-page picture of the book, `ConversionRunning` while a job runs."""
    storage = services.storage
    module = _module(storage, module_id)
    if map_name is not None and not any(m.name == map_name and m.role == "map" for m in module.maps):
        raise KeyError(map_name)
    source = load_source(storage, module_id)
    if part is not None and not any(t.id == part for t in source.texts):
        raise KeyError(part)
    attachment = next((a for a in source.attachments if a.id == page_asset), None)
    if attachment is None or not _is_book_picture(attachment):
        raise ValueError(f"{page_asset} isn't one of the book's map pages or full-page pictures.")
    name = map_name if map_name is not None else _page_map_name(attachment)

    async def work(live: _Live) -> None:
        progress = progress_for(services, live)
        progress("drawing", 0, 1)
        page = storage.blobs.get(attachment.sha256)
        if page is None:
            raise RuntimeError(f"The map page {page_asset} has no picture.")
        parts = _draft_parts(storage, _module(storage, module_id), map_name, part)
        levels, warnings = await draw_from_page(name, page, attachment.type, parts, look_for(services, live))
        progress("drawing", 1, 1)
        drawn = [
            {"name": lv.name, "title": lv.title, "source": f"{FROM_BOOK} asset:{page_asset}.\n{lv.source}", "part": lv.part}
            for lv in levels
        ]
        # The draft's part: the one given, else the one text on its map.
        drawn_for = part if part is not None else (parts[0].id if len(parts) == 1 else None)
        first = drawn[0] if drawn else {"name": name, "source": None}
        result = _result(
            module_id, first["name"], first["source"], warnings, replaces=map_name, part=drawn_for, page=page_asset,
            maps=drawn,
        )  # fmt: skip
        finish(services, live, result=result, warnings=warnings)

    target: dict[str, Any] = {"module_id": module_id, "name": name, "page": page_asset, "part": part}
    if batch is not None:
        target["batch"] = batch
    number = BOOK_PICTURE.fullmatch(page_asset)
    title = f"page {number.group(1)}" if batch is not None and number else name
    return await start_job(services, "book-map", title, work, target=target)


def _sketches_of_pages(module: Module) -> dict[str, str]:
    """The module's sketches that name the book's map page, as `{page: map name}`."""
    found = {}
    for module_map in module.maps:
        match = SKETCH_OF_PAGE.fullmatch(module_map.source.split("\n", 1)[0])
        if module_map.role == "map" and match:
            found.setdefault(match.group(1), module_map.name)
    return found


def _drawn_pages(module: Module) -> set[str]:
    """The pictures the module's maps were drawn from already."""
    drawn = set()
    for module_map in module.maps:
        first = module_map.source.split("\n", 1)[0]
        if first.startswith(f"{FROM_BOOK} asset:"):
            drawn.add(first.removeprefix(f"{FROM_BOOK} asset:").rstrip("."))
    return drawn


def _page_part(texts: list[TextDoc], attachment: Attachment) -> TextDoc | None:
    """The keyed text whose title shares the most words with the page's title (`plate_matches`); None when none
    shares one, or the page has no title."""
    title = _TITLE.search(attachment.description)
    if title is None:
        return None
    scored = [(plate_matches(t.title, title.group(1)), t) for t in texts if _keyed_rooms(t)]
    best = max(scored, key=lambda pair: pair[0], default=(0, None))
    return best[1] if best[0] > 0 else None


async def draw_book_maps(services: ConversionServices, module_id: str) -> list[Conversion]:
    """A book draft for every map page of the module's book (`map-page-<n>`) that no map was drawn from yet, in page
    order, one job after another, each kept only on Keep: what a PDF conversion does once its module is made, unless
    asked not to; a job cancelled stops the rest. A page is drafted for the text titled most like it (`_page_part`), else for no part, and Claude
    names each level's. It replaces the sketch that names the page only when that sketch's text is the page's part,
    so a page never replaces another part's map. Answers the jobs once ended. It stops at a job started by someone
    else first; the sketch's own button still draws the rest."""
    storage = services.storage
    module = _module(storage, module_id)
    source = load_source(storage, module_id)
    drawn_already = _drawn_pages(module)
    pages = sorted(
        (a for a in source.attachments if MAP_PAGE.fullmatch(a.id) and a.is_image and a.id not in drawn_already),
        key=lambda a: int(MAP_PAGE.fullmatch(a.id).group(1)),
    )
    sketches = _sketches_of_pages(module)
    drawn = []
    for index, attachment in enumerate(pages, start=1):
        part = _page_part(source.texts, attachment)
        sketch = sketches.get(attachment.id)
        map_name = sketch if sketch is not None and part is not None and part.map == sketch else None
        batch = {"index": index, "count": len(pages)}
        try:
            started = await start_book_map(
                services, module_id, map_name, attachment.id, part=part.id if part else None, batch=batch
            )
        except ConversionRunning:
            break
        except (KeyError, ValueError):  # the map or its page changed since
            continue
        ended = await wait(services, started.id)
        drawn.append(ended)
        if ended.status == "cancelled":  # the organiser stopped the drawing: the pages after it aren't drawn either
            break
    return drawn


# ----- the drafts -----


def _drafts(storage: Storage, module_id: str) -> list[Conversion]:
    """The module's drafts that are done and neither kept nor discarded, newest first."""
    return [
        c
        for c in storage.conversions.for_module(module_id)
        if c.kind in DRAFT_KINDS
        and c.status == "done"
        and c.result is not None
        and c.result.get("module_id") == module_id
        and not c.result.get("kept")
        and not c.result.get("discarded")
    ]


def drafts(storage: Storage, module_id: str) -> list[dict[str, Any]]:
    """The module's open drafts, `{id, kind, name, source, warnings, created_at, replaces, part, page, maps}`, newest
    first, however many. `replaces` is the map a book draft replaces (None for a new map, and for a description draft);
    `part` and `page` are a book draft's part and picture; `maps` its levels (`_levels`). A book draft from before
    Task 3 replaces its `name`."""
    return [
        {
            "id": c.id,
            "kind": c.kind,
            "name": c.result["name"],
            "source": c.result["source"],
            "warnings": c.result["warnings"],
            "created_at": c.created_at,
            "replaces": _replaces(c),
            "part": c.result.get("part"),
            "page": c.result.get("page"),
            "maps": _levels(c.result),
        }
        for c in _drafts(storage, module_id)
    ]


def _draft(storage: Storage, module_id: str, conversion_id: str) -> Conversion:
    found = next((c for c in _drafts(storage, module_id) if c.id == conversion_id), None)
    if found is None:
        raise KeyError(conversion_id)
    return found


def _levels(result: dict[str, Any]) -> list[dict[str, Any]]:
    """A draft's maps, `{name, title, source, part}`: a book draft's levels, else its one map (none when it drew
    none)."""
    if "maps" in result:
        return list(result["maps"])
    if result.get("source") is None:
        return []
    return [{"name": result["name"], "title": result["name"], "source": result["source"], "part": result.get("part")}]


def _replaces(draft: Conversion) -> str | None:
    result = draft.result or {}
    if draft.kind != "book-map":
        return None
    return result["replaces"] if "replaces" in result else result["name"]


def keep_draft(
    storage: Storage, module_id: str, conversion_id: str, name: str | None = None, *, force: bool = False
) -> ModuleMap:
    """Save the draft in the module, every level of a book draft: the first over the map it replaces, else as a new map
    named `name` (else its own), and the others as new maps under their own names (a name taken gets `-2`). The module's
    default map is unchanged unless it had none. A level whose rooms don't match its part (`mismatch`) is refused with
    `DraftMismatch`, unless `force`; a book draft's rooms are then linked to their parts' headings (`_link_levels`).
    Answers the first map kept. `KeyError` for no such open draft, `ValueError` for a draft that drew no map.

    Each level is parsed once, before the transaction (DEL-171, review P24: once per key entry, inside it, which held
    the write lock for seconds)."""
    draft = _draft(storage, module_id, conversion_id)
    result = draft.result or {}
    levels = _levels(result)
    if not levels:
        raise ValueError("This draft has no map to keep.")
    module = _module(storage, module_id)
    replaces = _replaces(draft)
    texts = {t.id: t for t in load_source(storage, module_id).texts}
    linked = draft.kind != "dungeon-map"
    wanted = [linked or (not force and level.get("part") in texts) for level in levels]
    parsed = [parse_source(level["source"]) if want else None for level, want in zip(levels, wanted, strict=True)]
    if not force:
        checked = [
            (level, map_, texts[level["part"]]) for level, map_ in zip(levels, parsed, strict=True) if level.get("part") in texts
        ]
        problems = [
            f"{level['title']}: {problem}" if len(levels) > 1 else problem
            for level, map_, part in checked
            for problem in mismatch(map_ if map_ is not None else level["source"], part)
        ]
        if problems:
            titles = list(dict.fromkeys(part.title for _, _, part in checked))
            raise DraftMismatch(" and ".join(titles), problems)
    with storage.transaction():
        used = {m.name for m in module.maps}
        has_default = any(m.is_default for m in module.maps)
        kept_maps: list[ModuleMap] = []
        for n, level in enumerate(levels):
            if n == 0 and replaces is not None:
                current = next((m for m in module.maps if m.name == replaces), None)
                if current is None:
                    raise KeyError(replaces)
                kept = replace(current, source=level["source"])
            else:
                chosen = ((name or "").strip() if n == 0 else "") or level["name"]
                kept = ModuleMap(unique(chosen, used), "map", level["source"], not has_default and not kept_maps)
            storage.modules.put_map(module_id, kept)
            kept_maps.append(kept)
        if draft.kind == "dungeon-map":
            _point_texts(storage, module_id, result.get("texts", []), kept_maps[0].name)
        else:
            on = [(kept.name, map_, level.get("part")) for kept, map_, level in zip(kept_maps, parsed, levels, strict=True)]
            _link_levels(storage, module_id, on)
        storage.conversions.save(replace(draft, result={**result, "kept": True, "name": kept_maps[0].name}))
    return kept_maps[0]


def _link_levels(storage: Storage, module_id: str, levels: list[tuple[str, DungeonMap, str | None]]) -> None:
    """Link each room `r<key>` of the kept levels, `(map name, parsed map, part)`, to the keyed heading of its part with
    that key, by an explicit `keys[]` entry `{key, title, text, node}` under the heading's scoped key: the entry for
    that heading when there is one (its other fields kept), else a new one. A key on two levels is linked on the first.
    A part's text that names no map is pointed at its first level. A level for no part links nothing. An entry whose
    `node` is on a level's map but not in its new source (a redraw without that room) loses its `node`."""
    source = load_source(storage, module_id)
    texts = {t.id: t for t in source.texts}
    scoped = scoped_keys(source.texts)
    nodes = {map_name: set(graph_of(level).nodes) for map_name, level, _ in levels}
    entries = [_without_stale_node(dict(k), nodes) for k in source.keys]
    linked: set[str] = set()
    first_level: dict[str, str] = {}
    for map_name, level, part in levels:
        text = texts.get(part) if part is not None else None
        if text is None:
            continue
        first_level.setdefault(text.id, map_name)
        headings = {room_name(str(s.key)): s for s in parse_text(text.markdown).keyed()}
        for room in level.rooms:
            section = headings.get(room)
            ref = f"text:{text.id}#{section.anchor}" if section is not None else None
            if section is None or ref in linked:
                continue
            linked.add(ref)
            key = scoped[(text.id, str(section.anchor))]
            entry = {"key": key, "title": section.title, "text": ref, "node": f"map:{map_name}#room.{room}"}
            at = next((i for i, e in enumerate(entries) if e.get("text") == ref), None)
            if at is None:
                at = next((i for i, e in enumerate(entries) if not e.get("text") and e.get("key") == key), None)
            if at is None:
                entries.append(entry)
            else:
                entries[at] = {**entries[at], **entry}
    pointed = [
        replace(t, map=first_level[t.id]) if t.id in first_level and t.map is None else t for t in source.texts
    ]
    save_source(storage, module_id, replace(source, texts=pointed, keys=entries))


def _without_stale_node(entry: dict[str, Any], nodes: dict[str, set[str]]) -> dict[str, Any]:
    """The entry without its `node` when that names a node of a kept level's map (`nodes`: their nodes by map name)
    that its new source lacks."""
    node = parse_ref(str(entry.get("node") or ""))
    if node is None or node.kind != "map" or node.fragment is None:
        return entry
    if node.id in nodes and node.fragment not in nodes[node.id]:
        return {k: v for k, v in entry.items() if k != "node"}
    return entry


def _point_texts(storage: Storage, module_id: str, text_ids: list[str], name: str) -> None:
    """Point the texts a new map was drawn for at it, those that still name none."""
    if not text_ids:
        return
    source = load_source(storage, module_id)
    texts = [replace(t, map=name) if t.id in text_ids and t.map is None else t for t in source.texts]
    save_source(storage, module_id, replace(source, texts=texts))


def discard_draft(storage: Storage, module_id: str, conversion_id: str) -> None:
    """Mark the draft discarded: it is no longer listed. `KeyError` for no such open draft."""
    draft = _draft(storage, module_id, conversion_id)
    storage.conversions.save(replace(draft, result={**(draft.result or {}), "discarded": True}))
