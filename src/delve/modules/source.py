"""A module's source (plan 3 Task 1): the one editable copy of its texts, entities, keys and attachments.

The source is the working copy the editor changes, stored as JSON beside the maps; a revision pins a copy of it.
Everything the DM and the search use is derived from it by `derive`: the `ModuleText` (sections, keys, entities), the
links between keyed headings and map rooms, and the warnings the editor lists. An attachment's bytes are in the blob
store by sha256 and are never deleted, so a pinned revision always finds them.

A text's `markdown` is its whole file, front matter included. Audiences are the format's `gm` and `player`,
stored as they are (`docs/data-dictionary.md`). A world map (plan 6) is its DSL text, as the format's `ttrpg2-worldmap`
file holds it; one that doesn't read is kept, with a `worldmap-unreadable` warning. A `geojson` one (plan 7) is its
Delve document, its picture's asset kept out of the attachments; one in review gets a `worldmap-in-review` warning.

Links (spec §8.2, "no anchors to type"): the explicit `keys` come first. Then every keyed heading without an explicit
key links to a node of the text's `map`, else the module's default map: through `dscn.keys.match_node` (the node
named like the anchor or the key, or like the title), else the one node whose label is the title, else the one whose
label is the whole heading (a sketched map's `<key>. <name>`). A map that doesn't
parse links nothing and adds no warning. An explicit key without a `node` (an entity keyed to its heading before the
map was drawn) doesn't claim the heading: the heading links itself, and that one key gets its room.

Keys (faithful modules Task 8): a heading's key is written as printed when no other text has a heading with that key,
else as `<part>-<key>` (`scoped_keys`), so a `.dscn`'s `keys[].key` stays unique; an explicit entry that points at a
heading with its printed key takes the scoped one (`scoped_entries`).
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Iterator, Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import asdict, dataclass, field, replace
from typing import Any, Literal, Protocol

from delve.domain.modules import ModuleMap
from delve.domain.world import WorldMapSource
from delve.maps import world
from delve.maps.dsl import DmapParseError
from delve.maps.dsl.graph import Graph
from delve.maps.sources import cached_map, graph_of
from delve.modules.dscn import DEFAULT_LIMITS, Bundle, parse_ref, parse_text, refs_in_markdown, sha256, slugify
from delve.modules.dscn import keys as dscn_keys
from delve.modules.dscn.maps import MapInfo
from delve.modules.dscn.refs import ENTITY_REF_KINDS, refs_in_value
from delve.modules.dscn.text import Section, split_front_matter
from delve.modules.dscn.text import TextDoc as ParsedText
from delve.modules.text import Key, ModuleText, key_of, sections_of

Audience = Literal["gm", "player"]

SOURCE_BUNDLE = "source-bundle"
"""The blob role of the `.dscn` a module was imported from."""
ATTACHMENT = "attachment"
"""The blob role of an attachment's bytes."""

CHECKED_ENTITY_REFS = ("npc", "encounter", "faction", "quest", "pregen")
"""The entity refs a `missing-entity` warning is given for: the kinds the editor's forms make."""

DEFAULT_AUDIENCES: dict[str, Audience] = {"pregens": "player"}
"""The audience a record of these kinds gets when it has none; every other kind's is the format's, `gm`."""

WORLDMAP_TYPE = "ttrpg2-worldmap"
"""The `worldmaps[].type` of ttrpg2's world-map DSL (`delve.maps.world`)."""
GEOJSON_TYPE = "geojson"
"""The `worldmaps[].type` of a Delve GeoJSON document (plan 7), its picture an asset named in `delve.picture.asset`."""


@dataclass(frozen=True)
class TextDoc:
    id: str
    title: str
    audience: Audience
    map: str | None
    """The map its keyed headings link to; None for the module's default map."""
    markdown: str


@dataclass(frozen=True)
class Cut:
    """A picture cut from its original (DEL-40): turned clockwise by `rotate` degrees, then cut to `box`.

    The box is `[x, y, w, h]` in fractions of the turned original; None keeps all of it. The attachment's own
    sha256, type and size are the cut picture, which is all the players see; the original stays in the blob store for
    the organiser to cut again. `proposed` marks a cut a conversion made, until the organiser says it looks right.
    """

    original: str
    original_type: str
    original_size: int
    rotate: int = 0
    box: tuple[float, float, float, float] | None = None
    proposed: bool = False

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Cut:
        box = raw.get("box")
        return cls(**{**raw, "box": tuple(box) if box is not None else None})


@dataclass(frozen=True)
class Attachment:
    id: str
    type: str
    sha256: str
    size: int
    description: str
    """What it shows and when it fits: the DM reads it to decide when to show an image."""
    audience: Audience
    role: Literal["attachment", "source"] = "attachment"
    """The format's asset role: `source` marks a published source, such as a converted book's PDF, which an export
    leaves out (format R8)."""
    cut: Cut | None = None
    """The original it is cut from, the turn and the box; None for a picture as uploaded."""

    @property
    def is_image(self) -> bool:
        return self.type.startswith("image/")


@dataclass(frozen=True)
class ModuleSource:
    texts: list[TextDoc] = field(default_factory=list)
    entities: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    """The entity records by manifest kind (`npcs`, `encounters`, `secrets`…), as the format's YAML holds them."""
    keys: list[dict[str, Any]] = field(default_factory=list)
    """The explicit `keys[]` entries, as the format's manifest holds them."""
    attachments: list[Attachment] = field(default_factory=list)
    worldmaps: tuple[WorldMapSource, ...] = ()

    def attachment(self, id: str) -> Attachment | None:
        return next((a for a in self.attachments if a.id == id), None)

    def player_images(self) -> list[Attachment]:
        """The images the DM may show the players: the attachments for the players that are images, not PDFs."""
        return [a for a in self.attachments if a.audience == "player" and a.is_image]

    def to_json(self) -> dict[str, Any]:
        return {
            "texts": [asdict(t) for t in self.texts],
            "entities": self.entities,
            "keys": self.keys,
            "attachments": [asdict(a) for a in self.attachments],
            "worldmaps": [w.to_dict() for w in self.worldmaps],
        }

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> ModuleSource:
        return cls(
            texts=[TextDoc(**t) for t in raw.get("texts", [])],
            entities={kind: list(records) for kind, records in raw.get("entities", {}).items()},
            keys=[dict(k) for k in raw.get("keys", [])],
            attachments=[_attachment(a) for a in raw.get("attachments", [])],
            worldmaps=tuple(WorldMapSource.from_dict(w) for w in raw.get("worldmaps", [])),
        )


def _attachment(raw: dict[str, Any]) -> Attachment:
    cut = raw.get("cut")
    return Attachment(**{**raw, "cut": Cut.from_dict(cut) if cut is not None else None})


@dataclass(frozen=True)
class Link:
    """A keyed heading joined to a map node: from an explicit key, or found by itself."""

    text_id: str
    anchor: str
    key: str
    map: str
    node: str
    label: str
    """The node's label on the map, else its name (or the key's title when the map doesn't parse)."""
    explicit: bool


@dataclass(frozen=True)
class Warning:
    code: str
    """`room-without-text`, `key-without-room`, `missing-attachment`, `missing-entity`, `missing-key`,
    `worldmap-unreadable`, `worldmap-in-review`; from a job, also such as `picture-not-painted` (DEL-347)."""
    message: str
    ref: str
    """What it is about: `map:<map>#<node>`, `text:<text>#<anchor>`, `worldmap:<name>`, or the dangling ref."""


@dataclass(frozen=True)
class Heading:
    """A keyed heading of a text, linked to a room or not: the key as written (`scoped_keys`), its title and where."""

    key: str
    title: str
    text_id: str
    anchor: str


@dataclass(frozen=True)
class Derived:
    text: ModuleText
    links: list[Link]
    warnings: list[Warning]
    headings: list[Heading] = field(default_factory=list)
    """Every keyed heading, in text order: what the editor's Where offers."""


def _audience(value: Any) -> Audience:
    return "player" if value == "player" else "gm"


def with_default_audiences(entities: dict[str, list[dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
    """The records, a pregen without an audience given `player` (`DEFAULT_AUDIENCES`)."""
    return {
        kind: [r if "audience" in r or kind not in DEFAULT_AUDIENCES else {**r, "audience": DEFAULT_AUDIENCES[kind]}
               for r in records]
        for kind, records in entities.items()
    }  # fmt: skip


def from_bundle(bundle: Bundle) -> ModuleSource:
    """The source of a `.dscn` bundle. An asset's `description` is its v2 description, else its v1 `caption`."""
    texts = []
    for entry in bundle.entries("text"):
        if not entry.get("id") or entry.get("file") not in bundle.files:
            continue
        markdown = bundle.read_text(entry["file"])
        front = split_front_matter(markdown)[0]
        texts.append(
            TextDoc(
                id=str(entry["id"]),
                title=str(entry.get("title") or front.get("title") or entry["id"]),
                audience=_audience(entry.get("audience", front.get("audience"))),
                map=str(entry["map"]) if entry.get("map") else None,
                markdown=markdown,
            )
        )
    kinds = bundle.manifest.get("entities") or {}
    entities = {kind: bundle.entities(kind) for kind in kinds} if isinstance(kinds, dict) else {}
    worldmaps, pictures = _worldmaps_of(bundle)
    attachments = []
    for entry in bundle.entries("assets"):
        if not entry.get("id") or entry.get("file") not in bundle.files or entry["id"] in pictures:
            continue
        data = bundle.files[entry["file"]]
        description = entry.get("description")
        if not isinstance(description, str):
            description = str(entry.get("caption") or "")
        attachments.append(
            Attachment(
                id=str(entry["id"]),
                type=str(entry.get("type") or ""),
                sha256=sha256(data),
                size=len(data),
                description=description,
                audience=_audience(entry.get("audience")),
                role="source" if entry.get("role") == "source" else "attachment",
            )
        )
    return ModuleSource(
        texts=texts,
        entities=with_default_audiences({kind: records for kind, records in entities.items() if records}),
        keys=[dict(k) for k in bundle.entries("keys")],
        attachments=attachments,
        worldmaps=worldmaps,
    )


def _geojson_worldmap(name: str, title: str, text: str, bundle: Bundle) -> tuple[WorldMapSource, str | None] | None:
    """A `geojson` entry's map, and the asset that carries its picture; None for a file that isn't a JSON object. The
    document's picture is the asset's bytes by their sha256 (the `world_pictures` id), and names no asset in the
    source: the export names it again."""
    try:
        doc = json.loads(text)
    except ValueError:
        return None
    if not isinstance(doc, dict):
        return None
    meta = doc.get("delve")
    picture = meta.get("picture") if isinstance(meta, dict) else None
    if not isinstance(picture, dict):
        return WorldMapSource(name, title, "", geo=doc), None
    asset_id = picture.get("asset")
    asset = next((a for a in bundle.entries("assets") if a.get("id") == asset_id), None)
    if asset is None or asset.get("file") not in bundle.files:
        return WorldMapSource(name, title, "", geo=doc), None
    sha = sha256(bundle.files[asset["file"]])
    doc = {**doc, "delve": {**meta, "picture": {**picture, "id": sha, "asset": None}}}
    return WorldMapSource(name, title, "", geo=doc, picture=sha), str(asset_id)


def _worldmaps_of(bundle: Bundle) -> tuple[tuple[WorldMapSource, ...], set[str]]:
    """The bundle's world maps of the types Delve reads, and the ids of the assets that are their pictures."""
    worldmaps: list[WorldMapSource] = []
    pictures: set[str] = set()
    for entry in bundle.entries("worldmaps"):
        if not entry.get("name") or entry.get("file") not in bundle.files:
            continue
        name, title, kind = str(entry["name"]), str(entry.get("title") or entry["name"]), entry.get("type", WORLDMAP_TYPE)
        if kind == WORLDMAP_TYPE:
            worldmaps.append(WorldMapSource(name, title, bundle.read_text(entry["file"])))
        elif kind == GEOJSON_TYPE and (read := _geojson_worldmap(name, title, bundle.read_text(entry["file"]), bundle)):
            worldmaps.append(read[0])
            if read[1] is not None:
                pictures.add(read[1])
    return tuple(worldmaps), pictures


def world_includes(worldmaps: Sequence[WorldMapSource]) -> dict[str, str]:
    """The texts a world map's `!include` may name: every other world map of the module, by its name and by its file's
    name (`sulm-akar-buildings.map`), as they sit side by side in the bundle's `worldmaps/`."""
    return {key: w.dsl for w in worldmaps for key in (w.name, f"{w.name}.map")}


_INCLUDE = re.compile(r'^\s*!include\s+"?([^"\s]+)"?', re.MULTILINE)


def _unreadable_worldmaps(worldmaps: Sequence[WorldMapSource]) -> Iterable[Warning]:
    """A warning for each world map that doesn't parse. A fragment that another map includes reads through it."""
    includes = world_includes(worldmaps)
    included = {name for w in worldmaps for name in _INCLUDE.findall(w.dsl)}
    for w in worldmaps:
        if w.geo is not None:
            continue
        if (w.name in included or f"{w.name}.map" in included) and not world.is_workspace(w.dsl):
            continue
        try:
            world.parse(w.dsl, includes)
        except world.WorldMapError as e:
            yield Warning("worldmap-unreadable", f"The world map {w.title} doesn't read: {e}.", f"worldmap:{w.name}")


def _worldmaps_in_review(worldmaps: Sequence[WorldMapSource]) -> Iterable[Warning]:
    """A warning for each world map still in review: it isn't exported until the organiser accepts it."""
    for w in worldmaps:
        if w.status == "review":
            yield Warning(
                "worldmap-in-review", f"The world map {w.title} is in review, so the export leaves it out.", f"worldmap:{w.name}"
            )


# --- derive --------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Parsed:
    info: MapInfo
    graph: Graph
    labels: dict[str, str]
    """Every node's label on the map, else its name, by node id."""


class _Maps:
    """The module's playable maps, each looked up once, on first use, in the one cache of parsed maps
    (`delve.maps.sources.cached_map`, DEL-166): a derive after a text save parses no map again. None for one that doesn't
    parse."""

    def __init__(self, maps: Sequence[ModuleMap]) -> None:
        self._all = maps
        self.playable = [m.name for m in maps if m.role == "map"]
        default = next((m.name for m in maps if m.role == "map" and m.is_default), None)
        self.default = default or (self.playable[0] if self.playable else None)
        self._parsed: dict[str, _Parsed | None] = {}

    def get(self, name: str | None) -> _Parsed | None:
        if name is None or name not in self.playable:
            return None
        if name not in self._parsed:
            try:
                dmap = cached_map(self._all, name)
            except (DmapParseError, KeyError):
                self._parsed[name] = None
            else:
                graph = graph_of(dmap)
                labelled = {f"room.{n}": r.label for n, r in dmap.rooms.items()}
                labelled |= {f"corridor.{n}": c.label for n, c in dmap.corridors.items()}
                labels = {}
                for nid, node in graph.nodes.items():
                    label = labelled.get(nid)
                    labels[nid] = label.text if label is not None else node.name
                self._parsed[name] = _Parsed(MapInfo(name=name, model=dmap, graph=graph), graph, labels)
        return self._parsed[name]


def _match(section: Section, parsed: _Parsed) -> str | None:
    node = dscn_keys.match_node(section, parsed.info)
    if node is not None:
        return node
    for text in (section.title, section.heading):
        want = dscn_keys._norm(text)
        hits = [nid for nid, label in parsed.labels.items() if want and dscn_keys._norm(label) == want]
        if len(hits) == 1:
            return hits[0]
    return None


# --- keys scoped to their part (faithful modules Task 8) ------------------------------------------------------------

PART_LENGTH = 19
"""A part's slug is at most this long, so a scoped key (`<part>-<key>`, a key at most 12) stays within the format's 32."""
PART_STOP_WORDS = frozenset(
    {"part", "chapter", "book", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "the",
     "a", "an", "of", "i", "ii", "iii", "iv", "v"}
)  # fmt: skip


def part_slug(text: TextDoc) -> str:
    """The short name of a part: its title's words without part numbers and articles, cut to `PART_LENGTH` at a hyphen
    ("PART ONE — THE HAUNTED HOUSE" is `haunted-house`); the text's id, cut, when nothing is left."""
    words = [w for w in re.split(r"[-._]+", slugify(text.title)) if w and w not in PART_STOP_WORDS and not w.isdigit()]
    slug = ""
    for word in words:
        if len(slug) + bool(slug) + len(word) > PART_LENGTH:
            break
        slug = f"{slug}-{word}" if slug else word
    if not slug and words:
        slug = words[0][:PART_LENGTH]
    return slug or text.id[:PART_LENGTH]


def _parsed_texts(texts: Sequence[TextDoc]) -> dict[str, ParsedText]:
    """Each text's Markdown parsed, by its id: `derive` parses each once and hands them on (DEL-166)."""
    return {doc.id: parse_text(doc.markdown) for doc in texts}


def _parts(texts: Sequence[TextDoc], parsed: Mapping[str, ParsedText] | None = None) -> dict[str, str]:
    """Each text's part, by its id: its `part_slug`, or its id (cut) when another text with keys shares the slug."""
    parsed = parsed if parsed is not None else _parsed_texts(texts)
    slugs = {doc.id: part_slug(doc) for doc in texts}
    keyed = [doc.id for doc in texts if parsed[doc.id].keyed()]
    shared = {slug for slug in slugs.values() if sum(slugs[tid] == slug for tid in keyed) > 1}
    return {tid: tid[:PART_LENGTH] if slug in shared else slug for tid, slug in slugs.items()}


def scoped_keys(
    texts: Sequence[TextDoc], parsed: Mapping[str, ParsedText] | None = None
) -> dict[tuple[str, str], str]:
    """The key as written of every keyed heading, by `(text id, anchor)`: as printed when no other text has a heading
    with that key (casefolded), else `<part>-<key>`, so a `.dscn`'s `keys[].key` stays unique. `parsed` is the texts'
    Markdown already parsed (`_parsed_texts`)."""
    parsed = parsed if parsed is not None else _parsed_texts(texts)
    headings = [(doc.id, section) for doc in texts for section in parsed[doc.id].keyed()]
    owners: dict[str, set[str]] = {}
    for tid, section in headings:
        owners.setdefault(str(section.key).casefold(), set()).add(tid)
    parts = _parts(texts, parsed)
    return {
        (tid, str(section.anchor)): (
            f"{parts[tid]}-{section.key}" if len(owners[str(section.key).casefold()]) > 1 else str(section.key)
        )
        for tid, section in headings
    }


def scoped_entries(source: ModuleSource, parsed: Mapping[str, ParsedText] | None = None) -> list[dict[str, Any]]:
    """The explicit `keys[]` entries, an entry whose `text` points at a keyed heading and whose key is that heading's
    printed key taking the heading's scoped key: so the bare duplicates of an older conversion become unique. An entry
    written with another key keeps it."""
    parsed = parsed if parsed is not None else _parsed_texts(source.texts)
    scoped = scoped_keys(source.texts, parsed)
    printed = {(doc.id, str(s.anchor)): str(s.key).casefold() for doc in source.texts for s in parsed[doc.id].keyed()}
    entries = []
    for raw in source.keys:
        text = parse_ref(str(raw.get("text") or ""))
        at = (text.id, text.fragment) if text is not None and text.kind == "text" and text.fragment else None
        if at in scoped and str(raw.get("key")).casefold() == printed[at] and raw["key"] != scoped[at]:
            raw = {**raw, "key": scoped[at]}
        entries.append(dict(raw))
    return entries


def derive(source: ModuleSource, maps: Sequence[ModuleMap]) -> Derived:
    """The DM's text, the room links and the editor's warnings of `source`, on the module's `maps`. Keys are scoped to
    their part (`scoped_keys`), and every key with a heading carries its text's part. Each text's Markdown is parsed
    once, and each map looked up once in the cache of parsed maps (DEL-166)."""
    parsed = _Maps(maps)
    docs = _parsed_texts(source.texts)
    links: list[Link] = []
    scoped = scoped_keys(source.texts, docs)
    parts = _parts(source.texts, docs)
    entries = scoped_entries(source, docs)
    keys = [_with_part(key_of(k), parts) for k in entries if k.get("key") is not None]

    for raw in entries:
        node, text = parse_ref(str(raw.get("node") or "")), parse_ref(str(raw.get("text") or ""))
        if raw.get("key") is None or node is None or text is None or node.kind != "map" or text.kind != "text":
            continue
        if node.fragment is None or text.fragment is None:
            continue
        on = parsed.get(node.id)
        label = (on.labels.get(node.fragment) if on else None) or str(raw.get("title") or raw["key"])
        links.append(Link(text.id, text.fragment, str(raw["key"]), node.id, node.fragment, label, True))

    # The entries without a node wait for their heading's room: by the heading they name, else by their key.
    by_text: dict[str, int] = {}
    by_key: dict[str, int] = {}
    for index, raw in enumerate(k for k in entries if k.get("key") is not None):
        if not raw.get("node"):
            if raw.get("text"):
                by_text.setdefault(str(raw["text"]), index)
            else:
                by_key.setdefault(str(raw["key"]), index)
    claiming = [k for k in entries if k.get("node")]
    explicit_texts = {k.get("text") for k in claiming}
    explicit_keys = {k.get("key") for k in claiming}
    explicitly_linked = {(link.text_id, link.anchor) for link in links}
    unlinked: list[tuple[TextDoc, Section]] = []
    for doc in source.texts:
        target = doc.map or parsed.default
        on = parsed.get(target)
        for section in docs[doc.id].keyed():
            anchor = str(section.anchor)
            key = scoped[(doc.id, anchor)]
            if f"text:{doc.id}#{anchor}" in explicit_texts or key in explicit_keys:
                if on is not None and (doc.id, anchor) not in explicitly_linked:
                    unlinked.append((doc, section))
                continue
            if target is None or on is None:
                continue
            node = _match(section, on)
            if node is None:
                unlinked.append((doc, section))
                continue
            links.append(Link(doc.id, anchor, key, target, node, on.labels[node], False))
            ref, text_anchor = f"map:{target}#{node}", f"{doc.id}#{anchor}"
            waiting = by_text.pop(f"text:{text_anchor}", None)
            if waiting is None:
                waiting = by_key.pop(key, None)
            if waiting is None:
                keys.append(Key(key, section.title, node=ref, text_anchor=text_anchor, part=parts[doc.id]))
            else:
                entry = keys[waiting]
                keys[waiting] = replace(entry, title=entry.title or section.title, node=ref, text_anchor=text_anchor)

    warnings: list[Warning] = []
    linked_nodes = {(link.map, link.node) for link in links}
    for name in parsed.playable:
        on = parsed.get(name)
        for nid, node in on.graph.nodes.items() if on else ():
            if node.kind == "room" and (name, nid) not in linked_nodes:
                message = f"The room “{on.labels[nid]}” on {name} has no text."
                warnings.append(Warning("room-without-text", message, f"map:{name}#{nid}"))
    for doc, section in unlinked:
        message = f"The heading “{section.heading}” in {doc.title} has no room on the map."
        warnings.append(Warning("key-without-room", message, f"text:{doc.id}#{section.anchor}"))
    warnings.extend(_missing_refs(source, entries, scoped))
    warnings.extend(_unreadable_worldmaps(source.worldmaps))
    warnings.extend(_worldmaps_in_review(source.worldmaps))

    text = ModuleText(
        sections=[
            s for doc in source.texts for s in sections_of(doc.id, doc.title, doc.audience, doc.markdown, docs[doc.id])
        ],
        keys=keys,
        entities={kind: list(records) for kind, records in source.entities.items() if records},
    )
    headings = [
        Heading(scoped[(doc.id, str(s.anchor))], s.title, doc.id, str(s.anchor))
        for doc in source.texts
        for s in docs[doc.id].keyed()
    ]
    return Derived(text, links, warnings, headings)


def _with_part(key: Key, parts: dict[str, str]) -> Key:
    """The key with the part of the text its heading is in; a key with no heading in the source keeps none."""
    tid = key.text_anchor.split("#", 1)[0] if key.text_anchor else None
    return replace(key, part=parts[tid]) if tid in parts else key


def refs_of(source: ModuleSource) -> Iterator[tuple[str, str]]:
    """Every ref of the source with where it is: in a text, an entity record or a key."""
    for doc in source.texts:
        for ref in refs_in_markdown(doc.markdown):
            yield ref, doc.title
    for kind, records in source.entities.items():
        for record in records:
            for ref in refs_in_value(record):
                yield ref, f"{kind} {record.get('id')}"
    for key in source.keys:
        for ref in refs_in_value(key):
            yield ref, f"key {key.get('key')}"


def missing_refs(source: ModuleSource) -> list[Warning]:
    """The `missing-attachment`, `missing-entity` and `missing-key` warnings `derive` gives, without parsing a map:
    an export asks for them before it derives the source it writes (DEL-171)."""
    return list(_missing_refs(source, scoped_entries(source), scoped_keys(source.texts)))


def _missing_refs(
    source: ModuleSource, entries: Sequence[dict[str, Any]], scoped: dict[tuple[str, str], str]
) -> Iterable[Warning]:
    """The refs that dangle: to an attachment, an entity record, or a key the export doesn't write (`missing-key`: a
    key is written as `scoped_entries` and `scoped_keys` write it, so a bare `key:7` two parts share is one)."""
    attachments = {a.id for a in source.attachments}
    keys = {str(k["key"]) for k in entries if k.get("key") is not None} | set(scoped.values())
    entities = {kind: {str(r.get("id")) for r in records} for kind, records in source.entities.items()}
    seen: set[str] = set()
    for raw, where in refs_of(source):
        ref = parse_ref(raw)
        if ref is None or raw in seen:
            continue
        if ref.kind == "asset" and ref.id not in attachments:
            seen.add(raw)
            yield Warning("missing-attachment", f"{where} shows the attachment {ref.id}, which isn't there.", raw)
        elif ref.kind in CHECKED_ENTITY_REFS and ref.id not in entities.get(ENTITY_REF_KINDS[ref.kind], set()):
            seen.add(raw)
            yield Warning("missing-entity", f"{where} refers to the {ref.kind} {ref.id}, which isn't there.", raw)
        elif ref.kind == "key" and ref.id not in keys:
            seen.add(raw)
            yield Warning("missing-key", f"{where} refers to the key {ref.id}, which isn't there as written.", raw)


# --- storage ---------------------------------------------------------------------------------------------------------


class _Modules(Protocol):
    def get(self, id: str) -> Any: ...


class _Sources(Protocol):
    def get(self, module_id: str) -> ModuleSource | None: ...

    def put(self, module_id: str, source: ModuleSource) -> None: ...

    def pin_legacy(self, module_id: str, source: ModuleSource) -> None: ...

    def revision(self, module_id: str, number: int) -> ModuleSource | None: ...


class _Texts(Protocol):
    def put(self, module_id: str, raw: dict[str, Any]) -> None: ...


class BlobWriter(Protocol):
    def put(self, data: bytes, mime: str) -> str: ...

    def link(self, module_id: str, role: str, sha: str) -> None: ...


class _Blobs(BlobWriter, Protocol):
    def get(self, sha: str) -> bytes | None: ...

    def links(self, module_id: str) -> list[tuple[str, str]]: ...


class SourceStorage(Protocol):
    """What the source needs of storage; `delve.storage.Storage` is one."""

    modules: _Modules
    module_sources: _Sources
    module_texts: _Texts
    blobs: _Blobs

    def transaction(self) -> AbstractContextManager[None]: ...


def store_attachments(blobs: BlobWriter, module_id: str, bundle: Bundle) -> None:
    """Put the bytes of every asset of `bundle` in the blob store, linked to the module as attachments."""
    for entry in bundle.entries("assets"):
        if entry.get("id") and entry.get("file") in bundle.files:
            sha = blobs.put(bundle.files[entry["file"]], str(entry.get("type") or "application/octet-stream"))
            blobs.link(module_id, ATTACHMENT, sha)


def load_source(storage: SourceStorage, module_id: str) -> ModuleSource:
    """The module's working source. A module imported before sources existed gets one built from its stored bundle
    (and its attachments' bytes stored); the revisions made then pin it too, since they came from that bundle."""
    stored = storage.module_sources.get(module_id)
    if stored is not None:
        return stored
    if storage.modules.get(module_id) is None:
        raise KeyError(module_id)
    bundle = next(
        (
            Bundle.load(data, limits=DEFAULT_LIMITS)
            for role, sha in storage.blobs.links(module_id)
            if role == SOURCE_BUNDLE and (data := storage.blobs.get(sha)) is not None
        ),
        None,
    )
    source = ModuleSource() if bundle is None else from_bundle(bundle)
    if bundle is not None:
        store_attachments(storage.blobs, module_id, bundle)
    with storage.transaction():
        storage.module_sources.put(module_id, source)
        storage.module_sources.pin_legacy(module_id, source)
    return source


def save_source(storage: SourceStorage, module_id: str, source: ModuleSource) -> Derived:
    """Store the working source and the DM's text derived from it, together or not at all."""
    module = storage.modules.get(module_id)
    if module is None:
        raise KeyError(module_id)
    source = replace(source, entities=with_default_audiences(source.entities))
    derived = derive(source, module.maps)
    with storage.transaction():
        storage.module_sources.put(module_id, source)
        storage.module_texts.put(module_id, derived.text.to_json())
    return derived


def pinned_source(storage: SourceStorage, module_id: str, number: int) -> ModuleSource | None:
    """The source a revision pinned, what a campaign on it plays; None when the module is gone. A revision made before
    sources existed gets the one `load_source` builds from the module's bundle."""
    pinned = storage.module_sources.revision(module_id, number)
    if pinned is None:
        try:
            load_source(storage, module_id)
        except KeyError:
            return None
        pinned = storage.module_sources.revision(module_id, number)
    return pinned
