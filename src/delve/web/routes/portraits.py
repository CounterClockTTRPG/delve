"""Repaint a character's portrait (DEL-135): the Repaint portrait button on the party sidebar and the sheet, and a
failed portrait's Try again, which is the same request. While Preferences draw PCs' portraits with portraitgen, a PC's
sheet has Edit portrait instead (DEL-238), which saves the traits made in portraitgen's editor.

It paints with the painter Preferences choose now (`delve.play.images.repaint`) and is held by the DM's tool's gate:
a painter that costs money needs the campaign's paid images and counts towards its pictures for a day; refused, it
says why rather than falling back to portraitgen. Who may press it is the owner's choice: the host (and a co-host) or
an organiser for any character, a player for a PC their seat plays; anyone else is 403.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from delve.domain.campaigns import Character
from delve.play import images, seats
from delve.play.context import PlayError, context_for
from delve.web.auth import current_principal
from delve.web.refusals import refusal
from delve.web.routes.campaigns import get_campaign
from delve.web.routes.characters import characters_changed
from delve.web.routes.play import table
from delve.web.seats import table_seat

router = APIRouter()

NOT_YOURS = "Only the host, an organiser or the character's player repaints its portrait."


def may_repaint(request: Request, campaign_id: str, character: Character) -> bool:
    """Whether the caller may repaint the character's portrait: an organiser (the owner too) or a seat that runs the
    table, for any character; a player, for a PC their seat plays. 401 for nobody known, 403 for no seat there."""
    if "organiser" in current_principal(request).roles:
        return True
    seat = table_seat(request, campaign_id)
    if seat.role in seats.TABLE_RIGHTS:
        return True
    played = seats.controls(request.app.state.storage, seat.id)
    return seat.role == "player" and character.kind == "pc" and character.id in played


@router.post("/api/campaigns/{campaign_id}/characters/{character_id}/portrait/repaint")
async def repaint_portrait(request: Request, campaign_id: str, character_id: str) -> dict[str, Any]:
    """Paint the character's portrait again (`images.repaint`): `{"portrait"}` for portraitgen's, set at once, or
    `{"image_id", "status": "painting"}` for a painting, scheduled now, the old portrait standing until it lands.
    Either way the table reads its characters again (`characters`). 404 for a character not of the campaign; 403 for
    one the caller may not repaint (`may_repaint`); 422 while paid images are off and the painter costs money, for an
    NPC with No portrait, and while one is being painted; 429 past the campaign's paid pictures for 24 hours."""
    get_campaign(request, campaign_id)
    storage = request.app.state.storage
    character = storage.characters.get(character_id)
    if character is None or character.campaign_id != campaign_id:
        raise HTTPException(status_code=404, detail="No such character in this campaign.")
    if not may_repaint(request, campaign_id, character):
        raise HTTPException(status_code=403, detail=NOT_YOURS)
    services = table(request)
    ctx = context_for(storage, campaign_id, "portrait", image_paid=services.image_paid, catalogs=services.catalogs)
    try:
        with storage.transaction():
            answer = images.repaint(ctx, character)
    except images.PaidUsedUp as used_up:
        raise refusal(used_up, 429) from None
    except PlayError as refused:
        raise refusal(refused) from None
    if "image_id" in answer:
        images.schedule(services, answer["image_id"])
    characters_changed(request, campaign_id)
    return answer


class EditedPortrait(BaseModel):
    """portraitgen's traits, as its editor keeps them; `images.edit` checks every key."""

    traits: dict[str, Any]


@router.put("/api/campaigns/{campaign_id}/characters/{character_id}/portrait")
def edit_portrait(request: Request, campaign_id: str, character_id: str, body: EditedPortrait) -> dict[str, Any]:
    """Set a PC's portrait to the traits made in portraitgen's editor (`images.edit`): `{"portrait"}`, and the table
    reads its characters again. Who may is who may repaint it (`may_repaint`). 404 for a character not of the campaign;
    403 for one the caller may not edit; 422 for an NPC, while Preferences paint PCs' portraits with another painter,
    while one is being painted, and for traits portraitgen didn't write."""
    get_campaign(request, campaign_id)
    storage = request.app.state.storage
    character = storage.characters.get(character_id)
    if character is None or character.campaign_id != campaign_id:
        raise HTTPException(status_code=404, detail="No such character in this campaign.")
    if not may_repaint(request, campaign_id, character):
        raise HTTPException(status_code=403, detail=NOT_YOURS)
    services = table(request)
    ctx = context_for(storage, campaign_id, "portrait", image_paid=services.image_paid, catalogs=services.catalogs)
    try:
        with storage.transaction():
            portrait = images.edit(ctx, character, body.traits)
    except PlayError as refused:
        raise refusal(refused) from None
    characters_changed(request, campaign_id)
    return {"portrait": portrait.to_dict()}
