"""A carried party's history (carry-the-party-on plan Task 5), at the new campaign's table. The host reads the whole
history, both texts, and edits them; every other seat, a co-host too, reads its status and the table's text alone,
never the DM's (as for a tool reply, owner 2026-10-22). Write again starts the history's job anew from the campaign the party was carried on from: it is 409 while the
history is written or another job runs, and asks for `overwrite` before replacing the host's edit.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from delve.conversions import ConversionRunning
from delve.domain.campaigns import Seat
from delve.domain.histories import History
from delve.histories.jobs import EDITED, HistoryEdited, close_orphan_histories, history_changed, start_history
from delve.histories.writer import HISTORY_MAX_CHARS
from delve.play.seats import ONLY_THE_HOST
from delve.web.routes.conversions import _running
from delve.web.routes.novels import novels
from delve.web.seats import TableSeat

router = APIRouter()

NO_HISTORY = "This campaign has no history."
NOT_CARRIED = "This campaign wasn't carried on from another."
ORIGIN_GONE = "The campaign the party was carried on from was deleted."
STILL_WRITING = "The history is being written."
TOO_LONG = f"A history's text has at most {HISTORY_MAX_CHARS} characters."


def history_json(history: History) -> dict[str, Any]:
    return history.to_dict()


def _the_host(seat: Seat) -> None:
    """The DM's history is the host's alone: a co-host could otherwise replace the DM's text unread."""
    if seat.role != "host":
        raise HTTPException(status_code=403, detail=ONLY_THE_HOST)


def _history(request: Request, campaign_id: str) -> History:
    history = request.app.state.storage.histories.get(campaign_id)
    if history is None:
        raise HTTPException(status_code=404, detail=NO_HISTORY)
    return history


@router.get("/api/campaigns/{campaign_id}/history")
def get_history(request: Request, seat: TableSeat, campaign_id: str) -> dict | None:
    """The whole history for the host; its status and the table's text for every other seat; null for a campaign
    with none (DEL-86: most have none, and a 404 for each filled the log)."""
    history = request.app.state.storage.histories.get(campaign_id)
    if history is None:
        return None
    if seat.role == "host":
        return history_json(history)
    return {"status": history.status, "table_md": history.table_md}


class HistoryIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dm_md: str
    table_md: str


@router.put("/api/campaigns/{campaign_id}/history")
def put_history(request: Request, seat: TableSeat, campaign_id: str, body: HistoryIn) -> dict:
    """Replace both texts by hand, the host alone: the history is `done` and `edited`. 422 for a text over the cap,
    409 while it is written."""
    _the_host(seat)
    history = _history(request, campaign_id)
    if history.status == "writing":
        raise HTTPException(status_code=409, detail=STILL_WRITING)
    if len(body.dm_md) > HISTORY_MAX_CHARS or len(body.table_md) > HISTORY_MAX_CHARS:
        raise HTTPException(status_code=422, detail=TOO_LONG)
    edited = replace(history, dm_md=body.dm_md, table_md=body.table_md, status="done", error=None, edited=True)
    stored = request.app.state.storage.histories.put(edited)
    history_changed(novels(request.app), campaign_id)  # the table's text, as the seats read it (DEL-172)
    return history_json(stored)


class WriteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    overwrite: bool = False


@router.post("/api/campaigns/{campaign_id}/history/write", status_code=202)
async def write_history_again(request: Request, seat: TableSeat, campaign_id: str, body: WriteIn) -> dict:
    """Write the history again from the campaign the party was carried on from, the host alone: 404 when it wasn't carried on or
    that campaign was deleted, 409 while the history is written or another job runs, and 409 `EDITED` for an edited
    history without `overwrite`."""
    _the_host(seat)
    storage = request.app.state.storage
    origin = storage.carries.origin(campaign_id)
    if origin is None:
        raise HTTPException(status_code=404, detail=NOT_CARRIED)
    if origin.from_campaign_id is None or storage.campaigns.get(origin.from_campaign_id) is None:
        raise HTTPException(status_code=404, detail=ORIGIN_GONE)
    close_orphan_histories(storage)
    current = storage.histories.get(campaign_id)
    if current is not None and current.status == "writing":
        raise HTTPException(status_code=409, detail=STILL_WRITING)
    services = novels(request.app)
    running = next(iter(services.conversions.live.values()), None)
    if running is not None:  # refused here, so a history that is done stays done
        raise _running(ConversionRunning(storage.conversions.get(running.conversion.id)))
    try:
        history = await start_history(services, campaign_id, origin.from_campaign_id, overwrite=body.overwrite)
    except HistoryEdited:
        raise HTTPException(status_code=409, detail=EDITED) from None
    return history_json(history)
