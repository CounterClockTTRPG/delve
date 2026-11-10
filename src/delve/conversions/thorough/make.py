"""The module made from a thorough conversion's job folder (thorough conversion Task 7; it generalises the hand QA's
`apply_texts.py` and `apply_all.py`).

`build_source` reads what the stages left in the folder and answers the module's source, its maps, its pictures with
their bytes, and the doubts; the making stage (`pipeline._Job.make`) adds the source PDF and makes the module in one
transaction with the job's end (`runner._make_module`), then removes the folder.

- **Texts:** `clean/<part id>.md` in `parts.json`'s order, titled and with the audience as the part, each pointing at
  the map of its first keyed room, else its part's first map (`TextDoc.map`).
- **Maps:** `joined/<name>.dmap`, each part's in its order (those `parts.json` lists, then its sketch from
  `sketches.json`), then any other. The default is the map the first part that is a level or an area points at, else
  the first map.
- **Keys are scoped per part** (Review Focus 1: U1's house and Sea Ghost both have rooms 1, 2, 3): a map's room is
  linked only to a keyed heading of its own part's text, by an explicit `keys[]` entry `{key, title, text, node}`
  under the heading's scoped key (`scoped_keys`, as `dungeon_maps._link_levels`). A heading keyed `12` is the room
  `r12` (a sketch's `room_name`, and a traced map's, whose names are the key in lower case with an `r` before a
  digit), `W211` the room `w211` or `rW211`; a key on two maps of its part is linked on the first.
- **Pictures:** the `art/` pictures `art/descriptions.json` describes, with its id, audience and description, and
  nothing else: the crops the agent left out are never attached. A picture naming a part and a room key is in the
  `assets` of that room's entry, in that part only. An entry's `rotate` and `crop` (DEL-40) cut its picture from the
  file, which is kept as the cut's original: one file listed several times is split into its pieces. The cut is
  `proposed`, for the organiser to look at; a cut that can't be made attaches the picture whole, for the DM only,
  with a doubt.
- **Entities:** `entities.json` (the `entities` stage), keyed to their headings (`key_entities`, by their `origins`;
  an encounter named as a keyed heading of its own text, "3. Poop Deck", is placed there first, `_named_rooms`),
  and every dangling ref repaired (`repair_refs`, with the stage's `renamed`). The repair's and the pictures' warnings
  are kept in `warnings.json` under `making`, with the other stages' warnings.
- **Doubts:** `doubts.gather`, last."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

from delve.conversions.thorough import doubts
from delve.conversions.thorough.workspace import ART, CLEAN, ENTITIES, JOINED, SKETCHES, WARNINGS, Workspace
from delve.domain.modules import ModuleMap
from delve.maps.sources import parse_source
from delve.modules.books.convert import bare, key_entities
from delve.modules.books.repair import repair_refs
from delve.modules.books.sketch import room_name
from delve.modules.cuts import CutRefused, cut_picture
from delve.modules.dscn import parse_text, sha256, slugify
from delve.modules.source import Attachment, Cut, ModuleSource, TextDoc, Warning, scoped_keys
from delve.modules.text import unique

DESCRIPTIONS = f"{ART}/descriptions.json"
MAKING = "making"
"""The label of the making's warnings in `warnings.json`."""
DUNGEON_KINDS = frozenset({"level", "area"})
"""The kinds of part whose first map can be the module's default."""
PICTURE_NOT_LINKED = (
    "The picture {id} shows room {key} of {part}, which has no such heading: add it to its room by hand."
)

_ID = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def build_source(
    ws: Workspace, title: str
) -> tuple[ModuleSource, list[ModuleMap], list[tuple[Attachment, bytes]], list[dict[str, Any]]]:
    """The module's source, its maps, its pictures with their bytes, and the doubts, from the job folder `ws`."""
    parts = ws.parts()
    drawn = {path.stem: path.read_text("utf-8") for path in sorted((ws.root / JOINED).glob("*.dmap"))}
    maps_of = _maps_of(ws, parts, drawn)
    texts = []
    for part in parts:
        path = ws.root / CLEAN / f"{part['id']}.md"
        if path.is_file():
            audience = "player" if part.get("audience") == "player" else "gm"
            on = maps_of.get(part["id"]) or [None]
            texts.append(TextDoc(part["id"], part["title"], audience, on[0], path.read_text("utf-8")))
    keys = _room_keys(texts, maps_of, drawn)
    texts = [replace(text, map=_first_room_map(text, keys) or text.map) for text in texts]
    maps = _maps(parts, maps_of, drawn, {text.id: text.map for text in texts})

    pictures, originals, placed = _pictures(ws)
    stored = ws.read_json(ENTITIES, {}) or {}
    source = ModuleSource(
        texts=texts,
        entities=stored.get("entities") or {},
        keys=keys,
        attachments=[attachment for attachment, _ in pictures],
    )
    origins = stored.get("origins") or {}
    source = key_entities(_named_rooms(source, origins), origins)
    source, linked = _link_pictures(source, placed)
    source, repaired = repair_refs(source, stored.get("renamed") or {}, maps=maps)
    _keep_warnings(ws, [*linked, *repaired])
    return source, maps, [*pictures, *originals], doubts.gather(ws)


# ----- entities -----

_NUMBERED = re.compile(r"^\s*([A-Za-z]*\d+[A-Za-z]?)\.\s+(.+)$")


def _named_rooms(source: ModuleSource, origins: dict[str, str]) -> ModuleSource:
    """`source` with each encounter that has no location and is named as a keyed heading of its own text ("3. Poop
    Deck": the key, then the heading's title) placed in that heading, for `key_entities` to key it. U1's encounters
    came back so named, with no location: by its words alone, the poop deck went to the cabin whose text names it."""
    headings = {
        (doc.id, str(section.key).casefold(), bare(section.title).casefold()): f"text:{doc.id}#{section.anchor}"
        for doc in source.texts
        for section in parse_text(doc.markdown).keyed()
    }
    encounters = []
    for record in source.entities.get("encounters", []):
        named = _NUMBERED.match(str(record.get("name") or ""))
        own = origins.get(f"encounter:{record.get('id')}")
        if named and own and not record.get("location") and not record.get("key"):
            ref = headings.get((own, named[1].casefold(), bare(named[2]).casefold()))
            record = {**record, "location": ref} if ref else record
        encounters.append(record)
    if "encounters" not in source.entities:
        return source
    return replace(source, entities={**source.entities, "encounters": encounters})


# ----- maps -----


def _maps_of(ws: Workspace, parts: Sequence[dict[str, Any]], drawn: dict[str, str]) -> dict[str, list[str]]:
    """Each part's drawn maps, by part id: those `parts.json` lists, in its order, then its sketch."""
    maps_of: dict[str, list[str]] = {}
    for part in parts:
        for listed in part.get("maps") or []:
            name = listed.get("name") if isinstance(listed, dict) else None
            if name in drawn and name not in maps_of.get(part["id"], []):
                maps_of.setdefault(part["id"], []).append(name)
    for name, sketch in (ws.read_json(SKETCHES, {}) or {}).items():
        if name in drawn and isinstance(sketch, dict) and name not in maps_of.get(sketch.get("part"), []):
            maps_of.setdefault(sketch["part"], []).append(name)
    return maps_of


def _maps(
    parts: Sequence[dict[str, Any]], maps_of: dict[str, list[str]], drawn: dict[str, str], opens: dict[str, str | None]
) -> list[ModuleMap]:
    ordered = list(dict.fromkeys([*(name for part in parts for name in maps_of.get(part["id"], [])), *drawn]))
    dungeons = [
        opens.get(p["id"]) or maps_of[p["id"]][0]
        for p in parts
        if p.get("kind") in DUNGEON_KINDS and maps_of.get(p["id"])
    ]
    default = dungeons[0] if dungeons else (ordered[0] if ordered else None)
    return [ModuleMap(name, "map", drawn[name], name == default) for name in ordered]


def _first_room_map(text: TextDoc, keys: Sequence[dict[str, Any]]) -> str | None:
    """The map of the text's first keyed room that one of its maps holds (U1: the Sea Ghost's room 1 is on its main
    deck, though the upper deck is listed first); None when no room of it is on a map."""
    node = next((entry["node"] for entry in keys if entry["text"].startswith(f"text:{text.id}#")), None)
    return node.removeprefix("map:").partition("#")[0] if node else None


def room_names(key: str) -> list[str]:
    """The names a room keyed `key` may have on a map: a sketch's `r<key>` (`room_name`), and a traced map's, the key
    in lower case, with an `r` before a digit (`12` is `r12`, `W211` is `w211`)."""
    lower = room_name(key.lower())
    traced = lower if key[:1].isdigit() else lower[1:]
    return list(dict.fromkeys([traced, room_name(key), lower]))


def _room_keys(texts: Sequence[TextDoc], maps_of: dict[str, list[str]], drawn: dict[str, str]) -> list[dict[str, Any]]:
    """An explicit `keys[]` entry for each keyed heading whose room is on one of its own part's maps (the first that
    has it), under the heading's scoped key: so a room links only within its part."""
    scoped = scoped_keys(texts)
    rooms = {name: set(parse_source(drawn[name]).rooms) for names in maps_of.values() for name in names}
    entries = []
    for text in texts:
        on = maps_of.get(text.id, [])
        for section in parse_text(text.markdown).keyed():
            found = next(
                ((name, room) for name in on for room in room_names(str(section.key)) if room in rooms[name]), None
            )
            if found is None:
                continue
            name, room = found
            entries.append(
                {
                    "key": scoped[(text.id, str(section.anchor))],
                    "title": section.title,
                    "text": f"text:{text.id}#{section.anchor}",
                    "node": f"map:{name}#room.{room}",
                }
            )
    return entries


# ----- pictures -----


def _pictures(
    ws: Workspace,
) -> tuple[list[tuple[Attachment, bytes]], list[tuple[Attachment, bytes]], list[tuple[str, str, str]]]:
    """The pictures `art/descriptions.json` describes, in its order, each cut as its entry says; the originals of the
    cut ones, once each, as the files they are (stored and linked, never attached); and where the pictures that name a
    room key show, `(picture id, part id, key)`. A listed file that isn't in `art/` is left out; a cut that can't be
    made is a `crop-refused` doubt, in `doubts/describe.crops.json`."""
    described = ws.read_json(DESCRIPTIONS, []) or []
    pictures: list[tuple[Attachment, bytes]] = []
    originals: dict[str, tuple[Attachment, bytes]] = {}
    placed: list[tuple[str, str, str]] = []
    refused: list[dict[str, Any]] = []
    used: set[str] = set()
    for entry in described if isinstance(described, list) else []:
        if not isinstance(entry, dict):
            continue
        file = str(entry.get("file") or "")
        path = ws.root / ART / file
        if not file or Path(file).name != file or not path.is_file():
            continue
        id = unique(_picture_id(entry.get("id"), file), used)
        data = path.read_bytes()
        audience = "player" if entry.get("audience") == "player" else "gm"
        description = str(entry.get("description") or "").strip()
        attachment = Attachment(id, "image/png", sha256(data), len(data), description, audience)
        if entry.get("rotate") or entry.get("crop") is not None:
            try:
                cut, cut_data = _cut(attachment, data, entry.get("rotate"), entry.get("crop"))
            except CutRefused as why:
                refused.append(
                    {
                        "part": entry.get("part") or "art",
                        "pages": [],
                        "kind": "crop-refused",
                        "text": f"{file} ({id}) is attached whole, for the DM only: {why}",
                    }
                )
                # The crop was to hide something from the players: the whole picture is the DM's until checked.
                attachment = replace(attachment, audience="gm")
            else:
                originals.setdefault(attachment.sha256, (attachment, data))
                attachment, data = cut, cut_data
        pictures.append((attachment, data))
        if entry.get("key"):
            placed.append((id, str(entry.get("part") or ""), str(entry["key"])))
    if refused:
        ws.doubt("describe.crops", refused)
    return pictures, list(originals.values()), placed


def _cut(attachment: Attachment, data: bytes, rotate: Any, crop: Any) -> tuple[Attachment, bytes]:
    """`attachment` cut as an entry of `descriptions.json` says, with the cut's bytes; `CutRefused` when it can't be."""
    turn = rotate if isinstance(rotate, int) and not isinstance(rotate, bool) else -1 if rotate else 0
    box = None
    if crop is not None:
        if not (isinstance(crop, list) and len(crop) == 4 and all(isinstance(v, int | float) for v in crop)):
            raise CutRefused("its crop isn't four numbers [x, y, w, h].")
        box = (float(crop[0]), float(crop[1]), float(crop[2]), float(crop[3]))
    cut_data, cut_type = cut_picture(data, attachment.type, turn, box)
    cut = Cut(attachment.sha256, attachment.type, attachment.size, turn, box, proposed=True)
    return replace(attachment, type=cut_type, sha256=sha256(cut_data), size=len(cut_data), cut=cut), cut_data


def _picture_id(given: Any, file: str) -> str:
    id = str(given or "").strip()
    return id if _ID.match(id) else slugify(id or Path(file).stem) or "picture"


def _link_pictures(source: ModuleSource, placed: Sequence[tuple[str, str, str]]) -> tuple[ModuleSource, list[Warning]]:
    """`source` with each picture `(id, part, key)` in the `assets` of the room's entry with that key in that part's
    text only; a key the part has no heading for is a `handout-not-linked` warning."""
    texts = {doc.id: doc for doc in source.texts}
    keys = [dict(entry) for entry in source.keys]
    warnings: list[Warning] = []
    for id, part, key in placed:
        doc = texts.get(part)
        headings = parse_text(doc.markdown).keyed() if doc is not None else []
        section = next((s for s in headings if str(s.key).casefold() == key.casefold()), None)
        ref = f"text:{part}#{section.anchor}" if section is not None else None
        room = next((k for k in keys if ref is not None and k.get("text") == ref), None)
        if room is None:
            message = PICTURE_NOT_LINKED.format(id=id, key=key, part=part or "no part")
            warnings.append(Warning("handout-not-linked", message, f"asset:{id}"))
            continue
        room["assets"] = [*room.get("assets", []), f"asset:{id}"]
    return replace(source, keys=keys), warnings


def _keep_warnings(ws: Workspace, warnings: Sequence[Warning]) -> None:
    kept = ws.read_json(WARNINGS, {}) or {}
    kept[MAKING] = [asdict(w) for w in warnings]
    ws.write_json(WARNINGS, kept)
