"""The table's schedule (DEL-204 part C): when the table plays, and its next session moved or skipped.

An organiser sets the schedule, as they set the table's listing (`delve.web.routes.listing`), or clears it; the host or
a co-host moves, skips or resets the next session, which is the table's to run (`delve.play.schedule`). Times go out
as UTC instants, so that each viewer's browser shows them in its own time zone. A change to the schedule publishes
`campaigns`, for the organisers' lists, and `table_listing` to the table; a change of the next session publishes
`table_listing` only.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Annotated, Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Body, HTTPException, Request
from starlette.responses import Response

from delve.mail import outbox, settings
from delve.mail.compose import compose
from delve.mail.table_mail import recipients
from delve.modules.dscn import slugify
from delve.play import schedule
from delve.play.calendar_file import CALENDAR_SESSIONS, calendar_file
from delve.play.context import PlayError
from delve.web.auth import Organiser
from delve.web.routes.campaigns import campaign_page, campaigns_changed, get_campaign, now_of
from delve.web.seats import HostSeat, TableSeat

router = APIRouter()

NEXT_CHANGE = (
    'Send {"skip": true}, {"to": "YYYY-MM-DDTHH:MM"} or {"reset": true}, and to tell the players by email add '
    '"email": {"note": "up to 500 characters"}.'
)
NOTE_LIMIT = 500


def listing_changed(request: Request, campaign_id: str) -> None:
    """Tell the table that its listing, the schedule with it, changed."""
    request.app.state.events.publish(
        "table_listing", {"campaign_id": campaign_id}, scope="table", campaign_id=campaign_id
    )


async def _schedule_body(request: Request) -> Any:
    """The body as JSON, read by hand: FastAPI takes a `null` body for none, and `null` here clears the schedule."""
    try:
        return json.loads(await request.body())
    except ValueError:
        raise HTTPException(status_code=422, detail="Send a schedule as JSON, or null to clear it.") from None


@router.put("/api/campaigns/{campaign_id}/schedule")
async def put_schedule(request: Request, principal: Organiser, campaign_id: str) -> dict:
    """An organiser sets when the table plays (`schedule.parse`: every 1 to 4 weeks from a first date, a start and an
    end in a time zone, and the changes to single sessions; those already over are dropped), or clears it with `null`.
    A field that is wrong is 422, with the reason. Answers the campaign as its page reads it."""
    get_campaign(request, campaign_id)
    now = now_of(request)
    try:
        checked = schedule.parse(await _schedule_body(request), now)
    except PlayError as refused:
        raise HTTPException(status_code=422, detail=refused.message) from None
    campaign = request.app.state.storage.campaigns.set_schedule(campaign_id, checked)
    campaigns_changed(request, campaign_id)
    listing_changed(request, campaign_id)
    return await campaign_page(request, campaign)


def _next_change(body: Any) -> tuple[dict[str, Any], str | None]:
    """The change asked for, as `schedule.change_next`'s keywords, and the note to tell the players with (None: tell
    nobody): exactly one of `skip: true`, `to` (a string) or `reset: true`, and optionally `email: {"note": str}` of at
    most `NOTE_LIMIT` characters; a 422 otherwise."""
    if isinstance(body, dict) and 1 <= len(body) <= 2:
        rest = dict(body)
        note = None
        if "email" in rest:
            asked = rest.pop("email")
            if not (isinstance(asked, dict) and set(asked) == {"note"} and isinstance(asked["note"], str)):
                raise HTTPException(status_code=422, detail=NEXT_CHANGE)
            if len(asked["note"]) > NOTE_LIMIT:
                raise HTTPException(status_code=422, detail=f"The note is at most {NOTE_LIMIT} characters.")
            note = asked["note"].strip()
        if len(rest) == 1:
            ((key, value),) = rest.items()
            if key in ("skip", "reset") and value is True:
                return {key: True}, note
            if key == "to" and isinstance(value, str):
                return {"to": value}, note
    raise HTTPException(status_code=422, detail=NEXT_CHANGE)


def _zone(name: str | None, fallback: str) -> ZoneInfo:
    """The named time zone, else the fallback (a name that no longer exists is no zone)."""
    for candidate in (name, fallback):
        try:
            if candidate:
                return ZoneInfo(candidate)
        except (ZoneInfoNotFoundError, ValueError, OSError):
            continue
    return ZoneInfo("UTC")


def _tell_the_players(
    request: Request, seat, campaign, kind: str, old: dict, new: dict | None, note: str, now: datetime
) -> int:
    """Queue the schedule mail for the table's reachable players, each in their own language and time zone (the
    account's, else the schedule's); how many were queued. Nothing queued without mail or a public address."""
    data_dir = request.app.state.config.data_dir
    url = settings.public_url(data_dir)
    if url is None or not settings.mail_enabled(data_dir):
        return 0
    storage = request.app.state.storage
    fallback = campaign.schedule["time_zone"]

    def at(session: dict, zone: ZoneInfo) -> str:
        return datetime.fromisoformat(session["starts_at"]).astimezone(zone).strftime("%Y-%m-%d %H:%M")

    count = 0
    for account in recipients(storage, campaign.id, "schedule", seat_ids=None, sender_seat_id=seat.id):
        zone = _zone(account.profile.time_zone, fallback)
        values = {"change": kind, "table": campaign.name, "old": at(old, zone), "zone": zone.key}
        if new is not None:
            values["new"] = at(new, zone)
        if note:
            values["note"] = note
        off = outbox.off_link(data_dir, account.id, "host")
        mail = compose(
            "schedule",
            account.profile.language,
            values,
            link=f"{url}/play/{campaign.id}",
            off_link=off[1] if off else None,
        )
        queued = outbox.queue(storage, account, "schedule", mail, now, unsubscribe=off[0] if off else None)
        count += queued is not None
    return count


@router.get("/api/campaigns/{campaign_id}/schedule.ics")
def schedule_calendar(request: Request, seat: TableSeat, campaign_id: str) -> Response:
    """The table's next sessions as a calendar file, for anyone at the table to import (DEL-236): an event for each
    of the next `CALENDAR_SESSIONS`, moved or skipped ones as they are, each linking to the play screen. 404 for a
    table without a schedule."""
    from delve.web.routes.join import link_origin  # join imports the campaigns routes, as this module does

    campaign = get_campaign(request, campaign_id)
    if campaign.schedule is None:
        raise HTTPException(status_code=404, detail="This table has no schedule.")
    now = now_of(request)
    sessions = schedule.next_sessions(campaign.schedule, now, CALENDAR_SESSIONS)
    link = f"{link_origin(request)}/play/{campaign.id}"
    text = calendar_file(campaign.id, campaign.name, sessions, now, link)
    filename = f"{slugify(campaign.name)}.ics"
    return Response(
        text,
        media_type="text/calendar; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-cache"},
    )


@router.post("/api/campaigns/{campaign_id}/schedule/next")
def change_next_session(
    request: Request, seat: HostSeat, campaign_id: str, body: Annotated[Any, Body()] = ...
) -> dict:
    """The host or a co-host changes the next session not yet started: `{"skip": true}` skips it, `{"to":
    "YYYY-MM-DDTHH:MM"}` moves it to that local time in the schedule's time zone (keeping its length), `{"reset":
    true}` drops its change. With `"email": {"note": ...}` alongside a skip or a move, the table's reachable players are told
    by email (`emailed` says how many; a reset tells nobody). 409 without a schedule; 422 for another body, a bad time or one in the past. Answers the
    schedule and its next sessions."""
    campaign = get_campaign(request, campaign_id)
    now = now_of(request)
    if campaign.schedule is None:
        raise HTTPException(status_code=409, detail="The table has no schedule: set when you play first.")
    change, note = _next_change(body)
    target = None if change.get("reset") else schedule.next_to_change(campaign.schedule, now)
    try:
        changed = schedule.change_next(campaign.schedule, now, **change)
    except schedule.NoSchedule as refused:  # cleared since it was read
        raise HTTPException(status_code=409, detail=refused.message) from None
    except PlayError as refused:
        raise HTTPException(status_code=422, detail=refused.message) from None
    request.app.state.storage.campaigns.set_schedule(campaign_id, changed)
    listing_changed(request, campaign_id)
    after = schedule.next_sessions(changed, now)
    emailed = 0
    if note is not None and target is not None:
        moved = schedule.session_on(changed, target["on"]) if "to" in change else None
        emailed = _tell_the_players(
            request, seat, campaign, "skipped" if moved is None else "moved", target, moved, note, now
        )
    return {"schedule": changed, "next_sessions": after, "emailed": emailed}
