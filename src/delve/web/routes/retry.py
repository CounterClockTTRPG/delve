"""Retry a failed beat with the same acts (table voice and fixes Task D1): whether the latest beat may be retried, for
the asking seat, and the retry itself (`delve.play.table.retry_beat`).

- `GET /api/campaigns/{campaign_id}/retry` (`TableSeat`) → `{"beat_id", "may_retry", "resets_at"}` for the latest beat.
- `POST /api/campaigns/{campaign_id}/beats/{beat_id}/retry` (`TableSeat`, body `{}`) → 202 `{"beat"}`; 404 for no such
  beat at this table, 409 while a beat is open or runs or for a beat that isn't retryable, 403 for a seat that is
  neither the host, a co-host nor one that acted in the beat.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from delve.play.seats import NotAllowed
from delve.play.table import BeatRunning, NotRetryable, beat_json, retry_beat, retry_state, running_beat
from delve.web.refusals import refusal
from delve.web.routes.campaigns import get_campaign
from delve.web.routes.play import table
from delve.web.seats import TableSeat

router = APIRouter()


class RetryIn(BaseModel):
    model_config = ConfigDict(extra="forbid")


@router.get("/api/campaigns/{campaign_id}/retry")
def may_retry(request: Request, seat: TableSeat, campaign_id: str) -> dict:
    """Whether the seat may retry the campaign's latest beat now, and when the usage limit that stopped it ends."""
    get_campaign(request, campaign_id)
    return retry_state(table(request), campaign_id, seat)


@router.post("/api/campaigns/{campaign_id}/beats/{beat_id}/retry", status_code=202)
async def retry(request: Request, seat: TableSeat, campaign_id: str, beat_id: str, body: RetryIn) -> dict:
    """Play the failed beat again with the same acts; the DM is told what its first attempt applied."""
    get_campaign(request, campaign_id)
    services = table(request)
    try:
        beat = retry_beat(services, campaign_id, beat_id, seat)
    except KeyError:
        raise HTTPException(status_code=404, detail={"error": "no such beat"}) from None
    except (BeatRunning, NotRetryable) as refused:
        raise refusal(refused, 409) from None
    except NotAllowed as refused:
        raise refusal(refused, 403) from None
    # As the play screen shows it: the DM's time counts from the retry.
    return {"beat": running_beat(services, campaign_id) or beat_json(beat)}
