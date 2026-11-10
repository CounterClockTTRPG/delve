"""The "Did you know" facts the play screen shows while the DM thinks (plan 6 Task 3): the campaign's setting's lore
facts, for any seat at its table, read through the setting layer as a seat reads it (settings plan Task 5): with the
install's facts and this campaign's proposed ones, never a DM-only one. Never the campaign's own facts, which are the
DM's."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, Request

from delve.play.setting_layer import layer_for
from delve.web.seats import TableSeat

router = APIRouter()


@router.get("/api/campaigns/{campaign_id}/lore/random")
def random_lore(
    request: Request, seat: TableSeat, campaign_id: str, n: Annotated[int, Query(ge=1, le=100)] = 20
) -> dict:
    """`{"facts": [{text, category}]}`: up to `n` of the setting's facts at random; none without a setting."""
    storage = request.app.state.storage
    campaign = storage.campaigns.get(campaign_id)
    try:
        shipped = request.app.state.registries.settings_.get(campaign.setting) if campaign.setting else None
    except KeyError:
        shipped = None
    layer = layer_for(storage, shipped, campaign_id=campaign_id, dm=False)
    facts = layer.lore_facts(n) if layer is not None else []
    return {"facts": [{"text": fact.text, "category": fact.category} for fact in facts]}
