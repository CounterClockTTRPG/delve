"""The module's pregenerated characters at party creation (faithful modules Task 19): the pinned revision's pregens
for the players, which the host's picker offers. Only the host and the co-hosts read them (`HostSeat`): a pregen
reaches the players once it is a character, and one the module keeps for the DM (`gm`) never leaves the DM's
`module_pregens` tool."""

from __future__ import annotations

from fastapi import APIRouter, Request

from delve.modules.source import pinned_source
from delve.web.routes.campaigns import get_campaign
from delve.web.seats import HostSeat

router = APIRouter()

FIELDS = ("id", "name", "race", "class", "level", "alignment", "gear", "background", "stats")
"""What the picker shows of a pregen: never its `summary` or `description`, which are the module's prose."""


@router.get("/api/campaigns/{campaign_id}/pregens")
def list_pregens(request: Request, seat: HostSeat, campaign_id: str) -> dict:
    """`{"pregens": [...]}`: the pinned revision's pregens whose audience is `player`, in the module's order."""
    campaign = get_campaign(request, campaign_id)
    source = pinned_source(request.app.state.storage, campaign.module_id, campaign.revision)
    records = source.entities.get("pregens", []) if source is not None else []
    return {
        "pregens": [
            {field: record[field] for field in FIELDS if field in record}
            for record in records
            if record.get("audience") == "player"
        ]
    }
