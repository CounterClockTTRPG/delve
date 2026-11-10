"""The module's pregenerated characters, for the DM (faithful modules Task 19): `module_pregens` lists the pinned
revision's pregens, every audience, each with the sheet `create_character` takes. It is DM-only: the players see a
pregen only once it is a character, and the host's picker reads the player pregens through its own route."""

from __future__ import annotations

from dataclasses import fields
from typing import Any

from delve.dm.tools.schema import ToolSpec, params, tool
from delve.domain.characters import Sheet
from delve.modules.source import pinned_source
from delve.play.context import CampaignContext
from delve.rules.classic.class_xp import component_classes

SPECS: list[ToolSpec] = []

NOT_A_PC = {"kind", "label", "portrait", "notes_md", "disposition"}
SHEET_KEYS = {f.name for f in fields(Sheet)} - NOT_A_PC
"""The fields of a PC's sheet a pregen's `stats.adnd2e` may give; anything else there (the printed stat line) stays
out of the sheet."""


def _levels(cls: str, level: Any) -> dict[str, Any]:
    """The book's level as the sheet's: `level` for a whole number, `levels` for "3/3" on a two-class character;
    nothing when it can't be read, so the DM sets it."""
    if isinstance(level, int) and not isinstance(level, bool):
        return {"level": level}
    parts = [p.strip() for p in str(level or "").split("/")]
    if not all(p.isdigit() for p in parts):
        return {}
    classes = component_classes(cls)
    if len(parts) == 1:
        return {"level": int(parts[0])}
    if len(parts) == len(classes):
        return {"levels": {c: int(p) for c, p in zip(classes, parts, strict=True)}}
    return {}


def pregen_sheet(record: dict[str, Any]) -> dict[str, Any]:
    """The sheet a pregen makes: its `stats.adnd2e` sheet fields, then the book's race, class, level, alignment and
    background over them."""
    stats = (record.get("stats") or {}).get("adnd2e") or {}
    sheet = {k: v for k, v in stats.items() if k in SHEET_KEYS or k == "level"}
    for field, key in (("race", "race"), ("class", "cls")):
        if record.get(field):
            sheet[key] = record[field]
    if "levels" not in sheet and record.get("level") is not None:
        sheet.pop("level", None)
        sheet.update(_levels(str(sheet.get("cls", "")), record["level"]))
    for field in ("alignment", "background"):
        if record.get(field):
            sheet[field] = record[field]
    return sheet


@tool(SPECS, "module_pregens", params(), mutates=False, player_visible=False)
def module_pregens(ctx: CampaignContext) -> dict[str, Any]:
    """The module's pregenerated characters, as the book prints them: each pregen's id, name, audience (player, or gm
    for one the DM keeps back), the sheet it makes and its gear. When the players ask for the party from the pregens,
    call create_character with each chosen pregen's name and its sheet as given, the book's race and class included,
    then add_item for each line of its gear. Never tell the players about a pregen they didn't choose."""
    campaign = ctx.storage.campaigns.get(ctx.campaign_id)
    source = pinned_source(ctx.storage, campaign.module_id, campaign.revision) if campaign else None
    records = source.entities.get("pregens", []) if source is not None else []
    return {
        "pregens": [
            {
                "id": r["id"],
                "name": r["name"],
                "audience": "player" if r.get("audience") == "player" else "gm",
                "sheet": pregen_sheet(r),
                "gear": [str(line) for line in r.get("gear") or []],
            }
            for r in records
        ]
    }
