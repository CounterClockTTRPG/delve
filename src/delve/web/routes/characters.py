"""A campaign's characters, PCs and NPCs, with their sheets and state (spec §7.8). Every seat at the table reads them;
making, renaming and deleting them is the organiser's.

Creating, renaming and deleting a character publish the event `characters` with the `campaign_id`. Deleting one takes
it out of every map state, and publishes `map_state` for each. So does a PC's leaving the party, or coming back
(`PUT …/departure`, table voice and fixes Task C2).
"""

from __future__ import annotations

from dataclasses import asdict, replace
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse, Response

from delve.dm.tools.redact import strip_for_players
from delve.domain.campaigns import Character, Departure
from delve.maps import state as map_state
from delve.packs.catalogs import Catalogs
from delve.play import beats, departures, images, inventory
from delve.play.context import CampaignContext, PlayError, context_for
from delve.play.portraits import sheet_emote
from delve.rules.classic import class_xp
from delve.rules.classic.thac0 import attack_thac0
from delve.rules.ruleset import NO_LOOKUPS
from delve.storage import Storage
from delve.web.auth import Organiser
from delve.web.routes.campaigns import get_campaign, map_state_changed, name_of
from delve.web.seats import TableSeat

router = APIRouter()


ENCUMBRANCE = ("total_lb", "band", "movement", "penalty")
# All a seat reads of an NPC: who it is. Its sheet, state and portrait prompt are the DM's.
NPC_FOR_SEATS = ("id", "name", "kind")
# The sheet keys that are the DM's even on a PC: an NPC's story and its disposition.
SHEET_FOR_THE_DM = ("notes_md", "disposition")


def catalogs_of(request: Request) -> Catalogs:
    """The rulesets and settings a campaign can name: the installed packs' beside the built-in ones."""
    return request.app.state.registries.catalogs


def sheet_context(request: Request, campaign_id: str) -> CampaignContext | None:
    """A context to read the campaign's characters with, for what the server computes on their sheets; None when its
    ruleset has nothing to look them up in."""
    ctx = context_for(request.app.state.storage, campaign_id, "sheet", catalogs=catalogs_of(request))
    return None if ctx.lookups is NO_LOOKUPS else ctx


def character_json(
    character: Character, ctx: CampaignContext | None = None, storage: Storage | None = None
) -> dict[str, Any]:
    """The character with its `kind`, `sheet`, `state`, the `emote` its sheet's portrait shows of that state
    (`portraits.sheet_emote`), marching `order` (None for NPCs) and `encumbrance`.

    `encumbrance` is `{total_lb, band, movement, penalty}` from `play.inventory.weigh`, computed on the server with
    the ruleset's lookups (`ctx`); null without them. With it, each of the sheet's attacks has `thac0_worked`,
    `{value, parts}` from `thac0.attack_thac0`: the THAC0 the fight rolls against. `xp_progress` is
    `class_xp.progress` on the XP total, one row per class with its share and the share its next level needs (backlog
    25); null without the reference. `departure` is why a PC left the party (`died`, `retired`, `left`) and
    `departed_at` when; both null while it is in it. `portrait_painting` is its portrait's `images.waiting`,
    `{provider, queue}`, while one is being painted (DEL-138), so the sheet says so rather than looking stuck; null
    otherwise, and without `storage`. `portrait_failed` is whether its newest portrait failed and still stands in
    (`images.portrait_failed`), for the sheet's Try again (DEL-135); false without `storage`. `portrait_editable` is
    whether the sheet edits its portrait in portraitgen's editor rather than repainting it (`images.editable`,
    DEL-238); false without `storage`."""
    weighed = inventory.weigh(ctx, character) if ctx is not None else None
    sheet = character.sheet.to_dict()
    if ctx is not None:
        sheet["attacks"] = [
            {**raw, "thac0_worked": asdict(attack_thac0(character.sheet, attack, ctx.lookups, rules=ctx.rules))}
            for raw, attack in zip(sheet["attacks"], character.sheet.attacks, strict=True)
        ]
    return {
        "id": character.id,
        "campaign_id": character.campaign_id,
        "name": character.name,
        "kind": character.kind,
        "sheet": sheet,
        "state": character.state.to_dict(),
        "emote": sheet_emote(character.state.hp, character.sheet.hp_max, character.state.conditions),
        "order": character.order,
        "encumbrance": {k: weighed[k] for k in ENCUMBRANCE} if weighed is not None else None,
        "xp_progress": class_xp.progress(character.sheet, character.state.xp, ctx.lookups, rules=ctx.rules) if ctx is not None else None,
        "created_at": character.created_at,
        "departure": character.departure,
        "departed_at": character.departed_at,
        "portrait_painting": images.painting_portrait(storage, character) if storage is not None else None,
        "portrait_failed": images.portrait_failed(storage, character) if storage is not None else False,
        "portrait_editable": images.editable(storage, character) if storage is not None else False,
    }


def characters_changed(request: Request, campaign_id: str) -> None:
    """The table's: ids only, so that each browser reads its characters again through its own route."""
    request.app.state.events.publish("characters", {"campaign_id": campaign_id}, scope="table", campaign_id=campaign_id)


def _get_character(request: Request, campaign_id: str, character_id: str) -> Character:
    found = next((c for c in request.app.state.storage.characters.list(campaign_id) if c.id == character_id), None)
    if found is None:
        raise HTTPException(status_code=404, detail="No such character in this campaign.")
    return found


class CharacterIn(BaseModel):
    name: str


class DepartureIn(BaseModel):
    departure: Departure | None


@router.get("/api/campaigns/{campaign_id}/characters")
def list_characters(request: Request, seat: TableSeat, campaign_id: str) -> list[dict]:
    """The characters as a seat may see them, the host's included: a PC without the DM-only keys, and an NPC as its
    id, name and kind alone."""
    get_campaign(request, campaign_id)
    ctx = sheet_context(request, campaign_id)
    storage = request.app.state.storage
    return [player_character_json(c, ctx, storage) for c in storage.characters.list(campaign_id)]


def player_character_json(
    character: Character, ctx: CampaignContext | None = None, storage: Storage | None = None
) -> dict[str, Any]:
    """`character_json` for a seat: an NPC is the DM's to know, so a seat gets only its `NPC_FOR_SEATS`; a PC comes
    without the DM-only keys, without `SHEET_FOR_THE_DM` and without its hidden effects (an unidentified item's)."""
    if character.kind == "npc":
        return {key: getattr(character, key) for key in NPC_FOR_SEATS}
    out = strip_for_players(character_json(character, ctx, storage), SHEET_FOR_THE_DM)
    # An unidentified item's effect is the DM's (DEL-335): the seats see neither it nor what it does.
    out["state"]["effects"] = [e for e in out["state"]["effects"] if not e.get("hidden")]
    for effect in out["state"]["effects"]:
        effect.pop("hidden", None)
    return out


@router.get("/api/campaigns/{campaign_id}/dm/characters")
def list_dm_characters(request: Request, principal: Organiser, campaign_id: str) -> JSONResponse:
    """Every character with its whole sheet, an NPC's story (`notes_md`) and disposition too: the organiser's campaign
    page, never a seat's screen."""
    get_campaign(request, campaign_id)
    ctx = sheet_context(request, campaign_id)
    storage = request.app.state.storage
    body = [character_json(c, ctx, storage) for c in storage.characters.list(campaign_id)]
    return JSONResponse(body, headers={"Cache-Control": "no-store"})


@router.post("/api/campaigns/{campaign_id}/characters", status_code=201)
def create_character(request: Request, principal: Organiser, campaign_id: str, body: CharacterIn) -> dict:
    get_campaign(request, campaign_id)
    character = request.app.state.storage.characters.create(campaign_id, name_of(body.name, "character"))
    characters_changed(request, campaign_id)
    return character_json(character, sheet_context(request, campaign_id), request.app.state.storage)


@router.patch("/api/campaigns/{campaign_id}/characters/{character_id}")
def rename_character(
    request: Request, principal: Organiser, campaign_id: str, character_id: str, body: CharacterIn
) -> dict:
    get_campaign(request, campaign_id)
    _get_character(request, campaign_id, character_id)
    character = request.app.state.storage.characters.rename(character_id, name_of(body.name, "character"))
    characters_changed(request, campaign_id)
    return character_json(character, sheet_context(request, campaign_id), request.app.state.storage)


@router.delete("/api/campaigns/{campaign_id}/characters/{character_id}", status_code=204)
def delete_character(request: Request, principal: Organiser, campaign_id: str, character_id: str) -> Response:
    """Delete the character, and take it out of every map state of the campaign."""
    get_campaign(request, campaign_id)
    _get_character(request, campaign_id, character_id)
    storage = request.app.state.storage
    left: list[str] = []
    with storage.transaction():
        storage.characters.delete(character_id)
        for map_name, raw in storage.map_states.list(campaign_id).items():
            state = map_state.from_json(raw)
            if character_id not in state.characters:
                continue
            characters = {cid: c for cid, c in state.characters.items() if cid != character_id}
            storage.map_states.put(campaign_id, map_name, map_state.to_json(replace(state, characters=characters)))
            left.append(map_name)
    for map_name in left:
        map_state_changed(request, campaign_id, map_name)
    characters_changed(request, campaign_id)
    return Response(status_code=204)


@router.put("/api/campaigns/{campaign_id}/characters/{character_id}/departure")
async def set_departure(
    request: Request, principal: Organiser, campaign_id: str, character_id: str, body: DepartureIn
) -> dict:
    """The campaign page's Leave the party (with its reason: `died`, `retired`, `left`) and Return (`null`), through
    `play.departures.set_departure`: leaving during a fight leaves the fight. 409 for an NPC. An open beat that waited
    only for the departed closes."""
    get_campaign(request, campaign_id)
    _get_character(request, campaign_id, character_id)
    storage = request.app.state.storage
    ctx = context_for(storage, campaign_id, "campaign-page", catalogs=catalogs_of(request))
    try:
        character = await run_in_threadpool(departures.set_departure, ctx, character_id, body.departure)
    except PlayError as refused:
        raise HTTPException(status_code=409, detail=str(refused)) from None
    characters_changed(request, campaign_id)
    from delve.web.routes.play import table_of  # it imports this module

    beats.recheck(table_of(request.app), campaign_id)
    return character_json(character, sheet_context(request, campaign_id), request.app.state.storage)
