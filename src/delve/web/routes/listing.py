"""The table's listing (DEL-204 part A): who finds the table, its players' description and its places for players.

An organiser sets it, as they choose the campaign's house rules; everyone at the table reads it, with those house
rules, and the join link shows it too (`delve.web.routes.join`). The description is the players' alone: the DM never
reads it, so it goes into no prompt. A change publishes `campaigns`, for the organisers' lists, and `table_listing`
to the table, so that each seat reads it again.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, StrictInt, StrictStr

from delve.domain.campaigns import Visibility
from delve.play import house_rules as play_house_rules
from delve.play import schedule, seats
from delve.storage import Storage
from delve.web.auth import Organiser
from delve.web.routes.campaigns import campaign_page, campaigns_changed, get_campaign, now_of
from delve.web.seats import TableSeat

router = APIRouter()


def house_rules_json(storage: Storage, campaign_id: str) -> list[dict[str, Any]]:
    """The campaign's house rules as its players read them: its effective ones (`effective_rules`), in order, each
    with its id, title and body."""
    return [
        {"id": rule.id, "title": rule.title, "body_md": rule.body_md}
        for rule in play_house_rules.effective_rules(storage, campaign_id)
    ]


class ListingIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    visibility: Visibility
    description: StrictStr
    slots: StrictInt | None
    """Required, null for no limit: a listing left without it would quietly lift the limit."""


@router.put("/api/campaigns/{campaign_id}/listing")
async def put_listing(request: Request, principal: Organiser, campaign_id: str, body: ListingIn) -> dict:
    """An organiser sets the table's visibility (`private` or `public`), its description (Markdown, stripped, at most
    4000 characters) and its places for players (1 to 20, or null for no limit); every key is needed, and a value
    outside those is 422. Fewer places than are taken is allowed: nobody is removed, and nobody more joins. Answers
    the campaign as its page reads it."""
    get_campaign(request, campaign_id)
    storage = request.app.state.storage
    try:
        campaign = storage.campaigns.set_listing(campaign_id, body.visibility, body.description.strip(), body.slots)
    except ValueError as refused:
        raise HTTPException(status_code=422, detail=str(refused)) from None
    campaigns_changed(request, campaign_id)
    request.app.state.events.publish(
        "table_listing", {"campaign_id": campaign_id}, scope="table", campaign_id=campaign_id
    )
    return await campaign_page(request, campaign)


@router.get("/api/campaigns/{campaign_id}/listing")
def read_listing(request: Request, seat: TableSeat, campaign_id: str) -> dict:
    """The table's listing as everyone at it reads it: its visibility, description, places and how many are taken
    (`seats.taken`), its house rules (`house_rules_json`), and its schedule with its next sessions
    (`schedule.next_sessions`)."""
    storage = request.app.state.storage
    campaign = get_campaign(request, campaign_id)
    return {
        "visibility": campaign.visibility,
        "description": campaign.description,
        "slots": campaign.slots,
        "taken": seats.taken(storage, campaign_id),
        "house_rules": house_rules_json(storage, campaign_id),
        "schedule": campaign.schedule,
        "next_sessions": schedule.next_sessions(campaign.schedule, now_of(request)),
    }
