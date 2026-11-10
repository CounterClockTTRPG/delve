"""A setting's additions on this install, as a file to take to another (DEL-366): the pages an organiser added or
overrode, the setting's facts and its own world maps with their pictures. The shipped setting is its pack's
(`delve.packs.transit`); this is only what the install put over it. DM-only pages, sections, facts and hidden map
features travel with their marks, as the owner decided: the file is for the organisers of another install.

The file is a zip: `additions.json` (`FORMAT`, `VERSION`, the setting's id, the pages, the facts and the maps) and
one `pictures/<sha256>` file for each map's picture. A campaign's proposals stay behind: they are its own.

Importing puts the file's pages, facts and maps into the same setting. A page or a map this install already has (by
title, by name) is kept or replaced as the organiser chose (`keep`), and a fact whose text the setting already holds
is never added twice.
"""

from __future__ import annotations

import io
import json
import zipfile
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Any

from delve.domain.setting_content import SettingAddition, SettingFact, title_key
from delve.domain.world import WorldMapSource
from delve.maps.geo import pictures, tiles
from delve.play.context import PlayError
from delve.storage import Storage

__all__ = [
    "FORMAT",
    "VERSION",
    "Imported",
    "export_additions",
    "import_additions",
]

FORMAT = "delve-setting-additions"
VERSION = 1
DATA_NAME = "additions.json"
PICTURES = "pictures/"
MAX_FILES = 2000
MAX_UNPACKED = 512 * 1024 * 1024
"""The most bytes a file's entries may unpack to: a zip that claims more is refused before anything is read."""
STATUSES = ("ready", "review")
PICTURE_TYPES = frozenset({"image/png", "image/jpeg", "image/webp"})
"""The pictures a world map may lie over, as its import takes them."""


@dataclass(frozen=True)
class Imported:
    """What an import did: pages, facts and maps added, replaced or kept as they were."""

    pages_added: int = 0
    pages_replaced: int = 0
    pages_kept: int = 0
    facts_added: int = 0
    facts_kept: int = 0
    maps_added: int = 0
    maps_replaced: int = 0
    maps_kept: int = 0

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


def export_additions(storage: Storage, setting_id: str, now: datetime | None = None) -> bytes:
    """The setting's additions on this install as the zip file `import_additions` reads."""
    pages = [
        {"title": p.title, "kind": p.kind, "fields": dict(p.fields), "text": p.text, "dm_only": p.dm_only}
        for p in storage.setting_pages.list(setting_id)
    ]
    facts = [
        {"text": f.text, "category": f.category, "dm_only": f.dm_only} for f in storage.setting_facts.list(setting_id)
    ]
    out = io.BytesIO()
    maps = []
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        written: set[str] = set()
        for world_map in storage.setting_maps.list(setting_id):
            raw = {
                "name": world_map.name,
                "title": world_map.title,
                "geo": world_map.geo,
                "status": world_map.status,
                "reading": world_map.reading,
                "picture": None,
            }
            found = pictures.original(storage, world_map.picture) if world_map.picture else None
            if found is not None:
                data, mime = found
                raw["picture"] = {"file": f"{PICTURES}{world_map.picture}", "mime": mime}
                if world_map.picture not in written:
                    archive.writestr(f"{PICTURES}{world_map.picture}", data)
                    written.add(world_map.picture)
            maps.append(raw)
        document = {
            "format": FORMAT,
            "version": VERSION,
            "setting": setting_id,
            "exported_at": (now or datetime.now(UTC)).isoformat(),
            "pages": pages,
            "facts": facts,
            "maps": maps,
        }
        archive.writestr(DATA_NAME, json.dumps(document, ensure_ascii=False, indent=1))
    return out.getvalue()


def import_additions(storage: Storage, setting_id: str, data: bytes, *, keep: bool = True) -> Imported:
    """Put the file's additions into the setting: its pages, its facts and its maps (with their pictures). A page or
    map the setting has already is kept as it is with `keep`, else replaced by the file's; a fact whose text the
    setting holds already is kept as it is. `PlayError` (nothing stored) for a file that isn't one, is of another
    version, or is another setting's."""
    document, files = _read(data)
    if document.get("setting") != setting_id:
        raise PlayError(
            f"This file holds the additions of '{document.get('setting')}', not of '{setting_id}'.",
            "Import it into that setting.",
        )
    pages = [_page(setting_id, raw) for raw in _list(document, "pages")]
    facts = [_fact(setting_id, raw) for raw in _list(document, "facts")]
    maps = [_map(raw, files) for raw in _list(document, "maps")]

    counts = dict.fromkeys(Imported.__dataclass_fields__, 0)
    # The pictures first: they are blobs, which a map names and nothing else does until it is stored.
    stored_pictures: dict[str, str] = {}
    for _world_map, picture_file, mime in maps:
        if picture_file is not None and picture_file not in stored_pictures:
            try:
                stored_pictures[picture_file] = pictures.store(storage, files[picture_file], mime).id
            except tiles.PictureRefused as refused:
                raise PlayError(f"A map's picture in the file can't be read: {refused.message}") from None
    with storage.transaction():
        have = {title_key(p.title) for p in storage.setting_pages.list(setting_id)}
        for page in pages:
            if title_key(page.title) in have:
                if keep:
                    counts["pages_kept"] += 1
                    continue
                counts["pages_replaced"] += 1
            else:
                counts["pages_added"] += 1
            storage.setting_pages.put(page)
            have.add(title_key(page.title))
        texts = {" ".join(f.text.split()).casefold() for f in storage.setting_facts.list(setting_id)}
        for fact in facts:
            text = " ".join(fact.text.split()).casefold()
            if text in texts:
                counts["facts_kept"] += 1
                continue
            storage.setting_facts.add(fact)
            texts.add(text)
            counts["facts_added"] += 1
        names = {m.name for m in storage.setting_maps.list(setting_id)}
        for world_map, picture_file, _mime in maps:
            if world_map.name in names:
                if keep:
                    counts["maps_kept"] += 1
                    continue
                counts["maps_replaced"] += 1
            else:
                counts["maps_added"] += 1
            picture = stored_pictures.get(picture_file) if picture_file else None
            storage.setting_maps.put(setting_id, replace(world_map, picture=picture))
            names.add(world_map.name)
    return Imported(**counts)


# ----- reading the file -----


def _read(data: bytes) -> tuple[dict[str, Any], dict[str, bytes]]:
    """The file's document and its other files' bytes, by name; `PlayError` for anything that isn't the file."""
    not_one = PlayError("This isn't a file of a setting's additions.", "Export one from a setting's page in Settings.")
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise not_one from None
    with archive:
        entries = [info for info in archive.infolist() if not info.is_dir()]
        if len(entries) > MAX_FILES or sum(info.file_size for info in entries) > MAX_UNPACKED:
            raise PlayError("The file is too large to import.")
        files: dict[str, bytes] = {}
        for info in entries:
            path = PurePosixPath(info.filename)
            if "\\" in info.filename or path.is_absolute() or ".." in path.parts:
                raise PlayError(f"{info.filename} is outside the file.")
            if info.filename != DATA_NAME and not info.filename.startswith(PICTURES):
                continue
            try:
                files[info.filename] = archive.read(info)
            except (zipfile.BadZipFile, ValueError, OSError):
                raise not_one from None
    raw = files.pop(DATA_NAME, None)
    if raw is None:
        raise not_one
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise not_one from None
    if not isinstance(document, dict) or document.get("format") != FORMAT:
        raise not_one
    if document.get("version") != VERSION:
        raise PlayError(
            f"This file is of version {document.get('version')} of the additions; this Delve reads version {VERSION}.",
            "Update Delve, or export the file again from a Delve of this version.",
        )
    return document, files


def _list(document: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = document.get(key, [])
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise PlayError(f"The file's {key} aren't a list.")
    return value


def _text(raw: dict[str, Any], key: str, what: str, *, required: bool = False) -> str:
    value = raw.get(key, "")
    if not isinstance(value, str) or (required and not value.strip()):
        raise PlayError(f"A {what} in the file has no {key}." if required else f"A {what}'s {key} isn't text.")
    return value


def _flag(raw: dict[str, Any], what: str) -> bool:
    value = raw.get("dm_only", False)
    if not isinstance(value, bool):
        raise PlayError(f"A {what}'s dm_only isn't true or false.")
    return value


def _page(setting_id: str, raw: dict[str, Any]) -> SettingAddition:
    fields = raw.get("fields", {})
    if not isinstance(fields, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in fields.items()):
        raise PlayError("A page's fields aren't names and texts.")
    return SettingAddition(
        setting=setting_id,
        title=_text(raw, "title", "page", required=True).strip(),
        kind=_text(raw, "kind", "page"),
        fields=dict(fields),
        text=_text(raw, "text", "page"),
        dm_only=_flag(raw, "page"),
    )


def _fact(setting_id: str, raw: dict[str, Any]) -> SettingFact:
    return SettingFact(
        id=0,
        setting=setting_id,
        text=_text(raw, "text", "fact", required=True).strip(),
        category=_text(raw, "category", "fact"),
        dm_only=_flag(raw, "fact"),
    )


def _map(raw: dict[str, Any], files: dict[str, bytes]) -> tuple[WorldMapSource, str | None, str]:
    """The map, the file of its picture (None for none) and the picture's type."""
    name = _text(raw, "name", "map", required=True).strip()
    geo = raw.get("geo")
    if not isinstance(geo, dict):
        raise PlayError(f"The map '{name}' has no GeoJSON.")
    status = raw.get("status", "ready")
    if status not in STATUSES:
        raise PlayError(f"The map '{name}' has an unknown status '{status}'.")
    reading = raw.get("reading")
    if reading is not None and not isinstance(reading, dict):
        raise PlayError(f"The map '{name}''s reading isn't an object.")
    picture = raw.get("picture")
    picture_file, mime = None, ""
    if picture is not None:
        if not isinstance(picture, dict) or not isinstance(picture.get("file"), str) or picture["file"] not in files:
            raise PlayError(f"The map '{name}''s picture isn't in the file.")
        if picture.get("mime") not in PICTURE_TYPES:
            raise PlayError(f"The map '{name}''s picture is of a type Delve doesn't read.")
        picture_file, mime = picture["file"], picture["mime"]
    title = raw.get("title") or name
    if not isinstance(title, str):
        raise PlayError(f"The map '{name}''s title isn't text.")
    world_map = WorldMapSource(name=name, title=title, dsl="", geo=geo, status=status, reading=reading)
    return world_map, picture_file, mime
