"""Reading a world map's picture (plan 7 Task 12): a conversion job of kind `worldmap` that makes no module, but a world
map in review, of a module, a campaign or a setting (`target`).

The job owns the uploaded picture from its start and removes it when it ends. Its first step, `tiles`, puts the
original in the blob store (streamed from its file) and cuts its tiles (`pictures.store_blob`); then
`read_picture`'s steps read it with the organiser's scale key, the picture OCR and Claude's vision calls. At the end,
in one transaction with the job's end, the map is put with `status` `review`, its geo document over the picture, and
its `reading`: into the module's working source, the campaign's `world_maps` or the setting's `setting_maps`. A job
that is cancelled or fails leaves no map; the picture's blobs it wrote stay unlinked, as an upload's do.

A map in review is never played on, listed to a seat, copied into a campaign or exported, until the organiser accepts
it (`delve.web.routes.world_import`).
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from delve.conversions.runner import ConversionServices, _Live, finish, look_for, progress_for, start_job
from delve.domain.conversions import Conversion
from delve.domain.world import CampaignWorldMap, WorldKnowledge, WorldMapSource
from delve.maps.geo import pictures, tiles
from delve.maps.geo.geojson import to_geojson
from delve.maps.geo.model import PictureRef
from delve.maps.geo.reading.read import ReadStopped as ReadingStopped
from delve.maps.geo.reading.read import read_picture
from delve.maps.geo.reading.scale import ScaleKey
from delve.modules.books.pdf import ReadStopped
from delve.modules.source import load_source, save_source
from delve.modules.worldmaps import put_world_map
from delve.setting.catalog import CATALOG, SettingEntry, entry
from delve.storage.interfaces import Storage

__all__ = ["MapNameTaken", "check_worldmap", "start_worldmap"]

OWNERS = ("module_id", "campaign_id", "setting_id")


class MapNameTaken(ValueError):
    """The owner has a world map of that name already."""


def check_worldmap(
    storage: Storage, key: ScaleKey, target: dict[str, Any], settings: Sequence[SettingEntry] = CATALOG
) -> dict[str, Any]:
    """The target as the job keeps it, `{module_id | campaign_id | setting_id, name, title}`, its title the name when it has none.
    `ValueError` for a key or a target that doesn't check, `KeyError` for an owner there isn't, `MapNameTaken` for a
    name the owner has already (an include fragment's too). A campaign's maps must have been seeded first."""
    key.check()
    owners = [k for k in OWNERS if target.get(k)]
    if len(owners) != 1:
        raise ValueError("Name the module, the campaign or the setting the world map is for, not two.")
    owner = owners[0]
    owner_id = str(target[owner])
    name = str(target.get("name") or "").strip()
    if not name:
        raise ValueError("A world map needs a name.")
    title = str(target.get("title") or "").strip() or name
    if owner == "module_id":
        if storage.modules.get(owner_id) is None:
            raise KeyError(owner_id)
        taken = any(w.name == name for w in load_source(storage, owner_id).worldmaps)
    elif owner == "setting_id":
        if entry(owner_id, settings) is None:
            raise KeyError(owner_id)
        taken = storage.setting_maps.get(owner_id, name) is not None
    else:
        if storage.campaigns.get(owner_id) is None:
            raise KeyError(owner_id)
        taken = storage.world_maps.get(owner_id, name) is not None
    if taken:
        raise MapNameTaken(f"There is a world map named '{name}' already.")
    return {owner: owner_id, "name": name, "title": title}


async def start_worldmap(
    services: ConversionServices, path: Path, mime: str, key: ScaleKey, target: dict[str, Any]
) -> Conversion:
    """Start reading the picture at `path` (of type `mime`) with its scale `key` into a world map in review of the
    module, campaign or setting `target` names. The job owns `path` from here, and removes it when it ends or at once when the
    start is refused: `ValueError`, `KeyError` or `MapNameTaken` as `check_worldmap` says, `ConversionRunning` while
    another job runs."""
    cleanup = lambda: path.unlink(missing_ok=True)
    try:
        target = check_worldmap(services.storage, key, target, services.settings)
    except BaseException:
        cleanup()
        raise

    async def work(live: _Live) -> None:
        await _read(services, live, path, mime, key, target)

    conversion = await start_job(services, "worldmap", target["title"], work, target=target, cleanup=cleanup)
    services.live[conversion.id].upload = path
    return conversion


async def _read(
    services: ConversionServices, live: _Live, path: Path, mime: str, key: ScaleKey, target: dict[str, Any]
) -> None:
    storage = services.storage
    progress = progress_for(services, live)
    progress("tiles", 0, 0)
    sha = await asyncio.to_thread(storage.blobs.put_file, path, mime)
    picture = await asyncio.to_thread(pictures.store_blob, storage, sha, mime)
    image = await asyncio.to_thread(tiles.open_picture, path, mime)
    try:
        reading = await read_picture(
            image,
            key,
            ocr=services.picture_ocr,
            look=look_for(services, live),
            progress=progress,
            should_stop=live.stop.is_set,
        )
    except ReadingStopped as error:
        raise ReadStopped(str(error)) from None
    except asyncio.CancelledError:
        live.stop.set()  # Delve is stopping: the reading's thread stops at its next step too
        raise
    km_per_px = reading.geo.frame.width_km / picture.width_px
    geo = replace(reading.geo, picture=PictureRef(picture.id, picture.width_px, picture.height_px, km_per_px))
    document = to_geojson(geo)
    name, title = target["name"], target["title"]
    result = {**target, "picture": picture.id, "doubts": len(reading.doubts)}
    with storage.transaction():
        check_worldmap(storage, key, target, services.settings)  # the name may have been taken while it read
        if "module_id" in target:
            module_id = target["module_id"]
            world_map = WorldMapSource(
                name, title, "", geo=document, picture=picture.id, status="review", reading=reading.to_dict()
            )
            save_source(storage, module_id, put_world_map(load_source(storage, module_id), world_map))
        elif "setting_id" in target:
            world_map = WorldMapSource(
                name, title, "", geo=document, picture=picture.id, status="review", reading=reading.to_dict()
            )
            storage.setting_maps.put(target["setting_id"], world_map)
        else:
            storage.world_maps.put(
                CampaignWorldMap(
                    target["campaign_id"],
                    name,
                    title,
                    "campaign",
                    "",
                    geo=document,
                    picture=picture.id,
                    status="review",
                    reading=reading.to_dict(),
                    knowledge=WorldKnowledge(),
                )
            )
        finish(services, live, result=result)
    if "module_id" in target:
        services.publish("modules", {"id": target["module_id"]})
    elif "setting_id" in target:
        services.publish("setting", {"id": target["setting_id"]})
