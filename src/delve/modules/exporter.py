"""The whole module as a `.dscn` bundle of the current version (plan 3 Task 2, spec §8.3): its metadata and maps, as
`importer.export_bundle` writes them, with the libraries they include vendored, and its source: texts, keys, entities,
attachments, whose bytes come from the blob store, and world maps, to `worldmaps/<name>.map`, or (plan 7) as Delve
GeoJSON to `worldmaps/<name>.geojson` with the picture as the asset `worldmap-<name>`. A map in review is left out.

Texts are written to `text/<id>.md` and attachments to `assets/<id>.<ext>`. Audiences are the format's `gm` and `player`
throughout, as Delve stores them (`docs/data-dictionary.md`). A heading that links itself to its room is written as a
`keys[]` entry, since in the bundle `keys[]` is the only source of truth (format §5.3): its `key:` refs resolve there.
So is a heading with no room that a `key:` ref names, without a node.

The bundle is written from the source with its keys scoped (`scoped_entries`) and its refs repaired (`repair_refs`):
a bare `key:7` two parts share becomes the key of its record's own part, or is dropped, so no ref dangles. The source
stored is left as it is.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import replace
from typing import Any

from delve.domain.modules import ModuleMap
from delve.domain.world import WorldMapSource
from delve.maps.geo.tiles import picture_type
from delve.modules.books.repair import repair_refs
from delve.modules.dscn import ENTITY_KINDS, Bundle, parse_ref
from delve.modules.importer import BANNER_ASSET, BANNER_MARK, export_bundle
from delve.modules.source import (
    GEOJSON_TYPE,
    ModuleSource,
    SourceStorage,
    derive,
    load_source,
    refs_of,
    scoped_entries,
)


def _keys(source: ModuleSource, maps: Sequence[ModuleMap]) -> list[dict[str, Any]]:
    """The explicit keys, an entry without a node with its heading's room, then a key for every other heading that
    links itself, as `dscn keys --suggest` would write it, then one without a node for a heading with no room that a
    `key:` ref names (an encounter placed there). Keys are written as derive scopes them (`scoped_keys`), so no two
    entries share a key."""
    derived = derive(source, maps)
    rooms = {(k.key, f"text:{k.text_anchor}"): k.node for k in derived.text.keys if k.node and k.text_anchor}
    explicit = []
    for entry in scoped_entries(source):
        room = None if entry.get("node") else rooms.get((str(entry.get("key")), str(entry.get("text"))))
        if room is not None:
            entry["node"] = room
        explicit.append(entry)
    placed = {entry.get("text") for entry in explicit if entry.get("node")}
    titles = {(k.text_anchor, k.key): k.title for k in derived.text.keys}
    found = [
        {
            "key": link.key,
            "title": titles.get((f"{link.text_id}#{link.anchor}", link.key), link.label),
            "node": f"map:{link.map}#{link.node}",
            "text": f"text:{link.text_id}#{link.anchor}",
        }
        for link in derived.links
        if not link.explicit and f"text:{link.text_id}#{link.anchor}" not in placed
    ]
    written = {entry.get("key") for entry in explicit + found}
    named = {ref.id for raw, _ in refs_of(source) if (ref := parse_ref(raw)) is not None and ref.kind == "key"}
    waiting = [
        {"key": h.key, "title": h.title, "text": f"text:{h.text_id}#{h.anchor}"}
        for h in derived.headings
        if h.key in named and h.key not in written
    ]
    return explicit + found + waiting


def _with_picture(bundle: Bundle, storage: SourceStorage, worldmap: WorldMapSource) -> dict[str, Any]:
    """The map's document, its picture added to the bundle as the asset `worldmap-<name>` and named in
    `delve.picture.asset`. The asset is the DM's (`gm`): the picture uncovered would show what the fog hides."""
    document = dict(worldmap.geo or {})
    meta = document.get("delve")
    picture = meta.get("picture") if isinstance(meta, dict) else None
    if worldmap.picture is None or not isinstance(picture, dict):
        return document
    data = storage.blobs.get(worldmap.picture)
    if data is None:
        raise LookupError(f"the picture of world map {worldmap.name} is missing")
    mime = picture_type(data)
    if mime is None:
        raise LookupError(f"the picture of world map {worldmap.name} isn't a PNG, JPEG or WebP")
    asset = f"worldmap-{worldmap.name}"
    description = f"The picture of the world map {worldmap.title}"
    bundle.add_asset(asset, data, mime, audience="gm", role="attachment", description=description)
    return {**document, "delve": {**meta, "picture": {**picture, "asset": asset}}}


def export_module(storage: SourceStorage, module_id: str) -> Bundle:
    """The module `module_id` as a `.dscn` bundle. Raises `KeyError` for an unknown module, and `LookupError` when an
    attachment's bytes are missing from the blob store. A `source` attachment (a converted book's PDF) is left out:
    the format makes a published source opt-in on export (R8)."""
    module = storage.modules.get(module_id)
    if module is None:
        raise KeyError(module_id)
    source = load_source(storage, module_id)
    source, _ = repair_refs(replace(source, keys=scoped_entries(source)), maps=module.maps, headings_are_keys=True)
    bundle = export_bundle(module)

    exported = {m["name"] for m in bundle.entries("maps")}
    for doc in source.texts:
        on = doc.map if doc.map in exported else None  # a text may name a map left out as empty
        bundle.add_text(doc.id, doc.markdown, title=doc.title, audience=doc.audience, map=on)
    for worldmap in source.worldmaps:
        if worldmap.status == "review":
            continue  # a `worldmap-in-review` warning says so
        title = worldmap.title if worldmap.title != worldmap.name else None
        if worldmap.geo is None:
            bundle.add_worldmap(worldmap.name, worldmap.dsl, title=title)
            continue
        document = _with_picture(bundle, storage, worldmap)
        text = json.dumps(document, ensure_ascii=False, indent=1) + "\n"
        bundle.add_worldmap(
            worldmap.name, text, type=GEOJSON_TYPE, file=f"worldmaps/{worldmap.name}.geojson", title=title
        )
    for attachment in source.attachments:
        if attachment.role == "source":
            continue
        data = storage.blobs.get(attachment.sha256)
        if data is None:
            raise LookupError(f"the bytes of attachment {attachment.id} are missing")
        bundle.add_asset(
            attachment.id,
            data,
            attachment.type,
            audience=attachment.audience,
            description=attachment.description,
        )
    for kind, records in source.entities.items():
        if kind in ENTITY_KINDS:
            bundle.set_entities(kind, records)
    bundle.set_keys(_keys(source, module.maps))

    # The module's banner (DEL-123): an image every player may see, marked so Delve's import makes it the banner again.
    if module.banner is not None and module.banner.blob is not None:
        data = storage.blobs.get(module.banner.blob)
        if data is None:
            raise LookupError("the bytes of the module's banner are missing")
        asset = BANNER_ASSET if source.attachment(BANNER_ASSET) is None else f"{BANNER_ASSET}-1"
        bundle.add_asset(asset, data, module.banner.mime or "image/webp", audience="player",
                         description="The module's banner.", **{BANNER_MARK: module.banner.source or "uploaded"})  # fmt: skip

    # `export_bundle` leaves out an `asset:` cover; it is back when its attachment is in the bundle.
    cover = parse_ref(str(module.metadata.get("cover") or ""))
    if cover is not None and cover.kind == "asset" and source.attachment(cover.id) is not None:
        bundle.manifest["cover"] = module.metadata["cover"]
    return bundle
