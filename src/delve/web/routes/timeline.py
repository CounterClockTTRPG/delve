"""The initiative timeline of a campaign's live fight, per seat (table voice and fixes Task B2.1):
`GET /api/campaigns/{campaign_id}/timeline`.

The answer is `delve.play.timeline.timeline_for`'s for the asking seat, the fourth wall kept there (the answer's
shape is pinned in `docs/superpowers/plans/2026-10-25-table-voice-and-fixes.md`). The `timeline` events say only that
it changed; each browser reads it again here."""

from __future__ import annotations

from fastapi import APIRouter, Request
from starlette.concurrency import run_in_threadpool

from delve.play.timeline import timeline_for
from delve.web.routes.campaigns import get_campaign
from delve.web.seats import TableSeat

router = APIRouter()


@router.get("/api/campaigns/{campaign_id}/timeline")
async def timeline(request: Request, seat: TableSeat, campaign_id: str) -> dict:
    """The live fight's round, its order along the initiative counts and its ongoing actions as this seat may see
    them, with the round's outcomes once the DM has told them; `{"fight": null}` without a fight, for an observer
    and for a player none of whose characters fights."""
    get_campaign(request, campaign_id)
    return await run_in_threadpool(timeline_for, request.app.state.storage, campaign_id, seat)
