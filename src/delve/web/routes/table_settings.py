"""A campaign's table settings, set by its host (table voice and fixes, workstream S): voice allowed or off, the
initiative mode, and who may watch (DEL-215).

Task 0 made this module and registered its router; S fills it (table voice and fixes Task S1)."""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict

from delve.domain.campaigns import InitiativeMode, ObserverRule, VoiceSetting
from delve.web.routes import voice as voice_routes
from delve.web.routes.campaigns import campaign_json, campaigns_changed, get_campaign, now_of
from delve.web.seats import HostSeat

router = APIRouter()


class TableSettingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    voice: VoiceSetting = "allowed"
    initiative: InitiativeMode = "combatant"
    observers: ObserverRule = "anyone"


@router.put("/api/campaigns/{campaign_id}/table-settings")
async def put_table_settings(request: Request, seat: HostSeat, campaign_id: str, body: TableSettingsIn) -> dict:
    """The host or a co-host sets voice (`allowed` or `off`) and the initiative mode (`combatant` or `side`); a key left
    out stays as it is, another value is 422. Switching voice off disconnects everyone in voice at once. The initiative
    mode applies from the fight's next round. `observers` is who may watch: `anyone` with the link, those a host lets
    in (`approved`), or `nobody`; the observers seated already stay. Every seat is told to read `play/state` again
    (`play_options`)."""
    get_campaign(request, campaign_id)
    storage = request.app.state.storage
    raw = body.model_dump(exclude_unset=True)
    campaign = storage.campaigns.get(campaign_id)
    if "voice" in raw:
        campaign = storage.campaigns.set_voice(campaign_id, raw["voice"])
    if "initiative" in raw:
        campaign = storage.campaigns.set_initiative(campaign_id, raw["initiative"])
    if "observers" in raw:
        campaign = storage.campaigns.set_observers(campaign_id, raw["observers"])
    if raw.get("voice") == "off":
        await voice_routes.disconnect_campaign(request.app, campaign_id)
    campaigns_changed(request, campaign_id)
    request.app.state.events.publish(
        "play_options", {"campaign_id": campaign_id}, scope="table", campaign_id=campaign_id
    )
    return campaign_json(campaign, storage, now_of(request))
