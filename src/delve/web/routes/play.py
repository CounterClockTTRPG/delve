"""The play API (spec §7.1, §7.3, §7.6): Act, Ask the DM and table talk, the story, the state of the table, the campaign's table
options, and the DM view's log. Playing and reading are for the seats at the table (`TableSeat`; acting is not for
observers); go, cancel and the beat timer are the host's; the DM's table options, the marching order and the DM log stay the
organiser's.

An act or a pass is the seat's submission to the beat (`play.beats.submit`), and answers 202 at once. When the beat
closes (everyone present has submitted, the host says go, or the timer runs out), the DM answers it in a background
task (`play.table.start_beat`), and the reply arrives as `story` events; the beat's changes are `beat` events, with
who has submitted but never what. Typing is a `typing` event to the table, never stored. Everything here reaches the
player's screen except the DM log, which is the DM view's: the story is built only through `player_view`, and the
state leaves out what the characters can't see, such as the enemies' hit points. The images the DM shows are served
by the campaign's image route, which answers only for the pinned revision's player images; the pictures it paints
(plan 6) by the pictures route, for the seats the picture's audience lets see it. The campaign's banner is everyone's
at the table, and painted again by an organiser.

The table's session state (`play.table_session`, DEL-199) is the host's and the co-hosts' to move: start the session,
take a break, back to the story, end the session. While the table gathers an act or a pass is refused (409), unless
the table is solo, and on a break go too. Any seat raises its own hand, and lowers it; the host and co-hosts lower
anyone's. Each change is a `table` event, with the table as the play state shows it.

An act, a question, a line of talk and a scene's hint have a length, and a seat's acts, questions, talk and scenes a
rate (`delve.web.play_limits`, DEL-154): past them, 422 or 429 before anything reaches Claude.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Annotated, Any, Literal

import anyio.from_thread
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, StrictBool, StrictInt
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse, Response

from delve.dm.claude_cli import account
from delve.domain.campaigns import COINS, Character, Seat, StoryKind
from delve.domain.settings import BackendChoice, Effort, Job
from delve.modules.source import pinned_source
from delve.play import (
    banners,
    beats,
    days,
    hotseat,
    images,
    schedule,
    seats,
    sessions,
    table_session,
    timeline,
    weather,
)
from delve.play import characters as play_characters
from delve.play.ask import AskFailed, ask
from delve.play.campaign_log import campaign_log
from delve.play.context import NotFound, PlayError, context_for, missing_pack
from delve.play.seats import NotAllowed
from delve.play.table import (
    AppServices,
    BeatRunning,
    beat_json,
    cancel_beat,
    current_beat,
    deadline,
    dm_log,
    entry_json,
    play_settings,
    running_beat,
    set_play_settings,
    story,
    tool_call_of,
)
from delve.play.talk import NotAllowed as PictureNotAllowed
from delve.play.talk import NotYours, may_paste, paste_picture, picture_of, share, take_down, talk
from delve.play.talk_pictures import TALK_PICTURE_LIMIT, TalkPictureRefused, talk_picture
from delve.rules.ruleset import NO_LOOKUPS
from delve.storage import Storage
from delve.web.auth import Organiser, current_principal
from delve.web.play_limits import ACT_CHARS, ASK_CHARS, HINT_CHARS, TALK_CHARS, check_length, seat_throttle
from delve.web.refusals import refusal
from delve.web.routes.assets import BannerSize, attachment_response, banner_picture
from delve.web.routes.campaigns import get_campaign, setting_title
from delve.web.routes.characters import catalogs_of, characters_changed
from delve.web.routes.internal_tools import tool_host
from delve.web.routes.preferences import RETIRED_MODELS, current_preferences, image_paid
from delve.web.seats import ActorSeat, HostSeat, TableSeat

router = APIRouter()
log = logging.getLogger(__name__)

STORY_LIMIT = 200


def table(request: Request) -> AppServices:
    """The app's table services, made on first use: its storage and reference, the tool specs, the DM's provider
    and choice per campaign, its event stream with who is present, and its clock."""
    return table_of(request.app)


def table_of(app) -> AppServices:
    services = getattr(app.state, "table", None)
    if services is None:
        request = Request({"type": "http", "app": app})  # the app's helpers read only `request.app`
        services = AppServices(
            storage=app.state.storage,
            spec_lookup=tool_host(request).spec,
            dm=lambda campaign_id: _choice(app, campaign_id, Job.DM),
            side=lambda campaign_id: _choice(app, campaign_id, Job.SIDE),
            translation=lambda campaign_id: _choice(app, campaign_id, Job.TRANSLATION),
            images=lambda job: _image_choice(app, job),
            image_paid=lambda job: image_paid(app, job),
            publish=app.state.events.publish,
            clock=app.state.clock,
            present=app.state.events.present,
            catalogs=app.state.registries.catalogs,
        )
        app.state.table = services
    return services


def recheck_beat(request: Request, campaign_id: str) -> None:
    """The seats changed: close the open beat if it no longer waits for anyone. From a sync route's worker thread
    too, since the DM answers in a task of the event loop."""
    services = table(request)
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        anyio.from_thread.run_sync(beats.recheck, services, campaign_id)
    else:
        beats.recheck(services, campaign_id)


def presence_changed(app, campaign_id: str | None) -> None:
    """A seat came or went (None: the owner, at every table): an open beat no longer waits for one that went away."""
    services = table_of(app)
    if campaign_id is not None:
        beats.recheck(services, campaign_id)
        return
    for campaign in app.state.storage.campaigns.list():
        beat = current_beat(app.state.storage, campaign.id)
        if beat is not None and beat.status == "open":
            app.state.events.publish("seats", {"campaign_id": campaign.id}, scope="table", campaign_id=campaign.id)
            beats.recheck(services, campaign.id)


def _choice(app, campaign_id: str, job: Job) -> tuple[Any, BackendChoice]:
    """The provider and choice of `job`: Preferences' choice, with the campaign's own model and effort for the DM (a
    retired model, `RETIRED_MODELS`, as no model)."""
    choice = current_preferences(app).choices.get(job)
    if choice is None:
        raise PlayError(f"No provider does the {job} job.", "Choose one under Preferences.")
    if job is Job.DM:
        own = play_settings(app.state.storage, campaign_id)
        caps = _caps(app, choice.provider)
        if (choice.provider, own["model"]) in RETIRED_MODELS:
            model = None  # claude-cli's "default", stored before it was retired, is the CLI's own: no model
        else:
            model = own["model"] if own["model"] in caps.models else choice.model
        effort = Effort(own["effort"]) if own["effort"] in caps.efforts else choice.effort
        choice = BackendChoice(choice.provider, model, effort)
    return app.state.registries.dm.get(choice.provider), choice


def _image_choice(app, job: Job) -> tuple[Any, BackendChoice]:
    """The image provider and choice of an image job: Preferences'."""
    choice = current_preferences(app).choices.get(job)
    if choice is None:
        raise PlayError(f"No provider does the {job} job.", "Choose one under Preferences.")
    return app.state.registries.images.get(choice.provider), choice


def _caps(app, provider_id: str):
    return next(caps for caps in app.state.registries.dm.capabilities() if caps.id == provider_id)


# ----- playing -----


class ActIn(BaseModel):
    text: str
    characters: list[str] | None = None
    private: StrictBool = False
    player: str | None = None
    """A hotseat player at the host's screen (DEL-365): the act is theirs, for their characters by default."""


@router.post("/api/campaigns/{campaign_id}/act", status_code=202)
async def act(request: Request, seat: ActorSeat, campaign_id: str, body: ActIn) -> dict:
    """Act: the seat's submission to the beat, for its characters (by id; none given: all of its own), opening the
    beat when none is open. When it closes the beat (with one seat present, at once), the DM answers it. A `private`
    act is for the DM alone: no other seat sees it, pending or in the story. `player` makes it a hotseat player's
    (DEL-365): only the host's screen sends one, never private (422). 202 with the beat; 409 while the DM is
    answering; 422 past `ACT_CHARS`, 429 past the seat's acts for a while (DEL-154)."""
    get_campaign(request, campaign_id)
    text = body.text.strip()
    if not text:
        raise HTTPException(status_code=422, detail="Say what you do.")
    check_length(text, ACT_CHARS, "An act is")
    seat_throttle(request.app).take(seat.id, "act")
    return await _submitted(
        request, campaign_id, seat, "act", text, body.characters, private=body.private, player=body.player
    )


class PassIn(BaseModel):
    characters: list[str] | None = None
    private: StrictBool = False
    player: str | None = None


@router.post("/api/campaigns/{campaign_id}/pass", status_code=202)
async def pass_beat(request: Request, seat: ActorSeat, campaign_id: str, body: PassIn) -> dict:
    """Pass: the seat's characters do nothing this beat. As an act, it may close the beat. A pass can't be private
    (422)."""
    get_campaign(request, campaign_id)
    return await _submitted(
        request, campaign_id, seat, "pass", "", body.characters, private=body.private, player=body.player
    )


async def _submitted(
    request: Request,
    campaign_id: str,
    seat,
    kind,
    text: str,
    characters: list[str] | None,
    *,
    private: bool = False,
    player: str | None = None,
) -> dict:
    """The submission, with an act put into English first when the seat writes another language."""
    services = table(request)
    try:
        beat = await beats.submit_in_english(
            services, campaign_id, seat, kind, text, characters, private=private, player=player
        )
    except (BeatRunning, table_session.SessionRefused) as refused:
        raise refusal(refused, 409) from None
    except NotAllowed as refused:
        raise refusal(refused, 403) from None
    except PlayError as refused:
        raise refusal(refused) from None
    return {"beat": beat_json(beat, deadline=deadline(services.storage, beat))}


@router.post("/api/campaigns/{campaign_id}/go", status_code=202)
async def go(request: Request, seat: HostSeat, campaign_id: str) -> dict:
    """Go: the host or a co-host closes the open beat with the submissions it has, and the DM answers it. 409 when
    no beat is open, while the DM is answering, or on a break."""
    get_campaign(request, campaign_id)
    try:
        beat = beats.go(table(request), campaign_id, seat)
    except (BeatRunning, beats.NoOpenBeat, table_session.OnABreak) as refused:
        raise refusal(refused, 409) from None
    return {"beat": beat_json(beat)}


@router.get("/api/campaigns/{campaign_id}/beat/pending")
def pending_acts(request: Request, seat: TableSeat, campaign_id: str) -> dict:
    """The open beat's acts and passes so far, as the seat may see them (`beats.pending`): its own first, the others'
    that aren't private; none for an observer. The browser reads it again on each `beat` event."""
    get_campaign(request, campaign_id)
    return {"pending": beats.pending(request.app.state.storage, campaign_id, seat)}


class TypingIn(BaseModel):
    state: Literal["idle", "typing"]


@router.post("/api/campaigns/{campaign_id}/typing", status_code=204)
def typing(request: Request, seat: TableSeat, campaign_id: str, body: TypingIn) -> Response:
    """Whether the seat is typing, for the others' indicators (spec §7.1). Published to the table, never stored."""
    get_campaign(request, campaign_id)
    data = {"campaign_id": campaign_id, "seat_id": seat.id, "state": body.state}
    request.app.state.events.publish("typing", data, scope="table", campaign_id=campaign_id)
    return Response(status_code=204)


class AskIn(BaseModel):
    question: str


@router.post("/api/campaigns/{campaign_id}/ask")
async def ask_the_dm(request: Request, seat: TableSeat, campaign_id: str, body: AskIn) -> dict:
    """Ask the DM, out of band: the answer, for the asker only. 502 when the side pass gives none; 422 past
    `ASK_CHARS`, 429 past the seat's questions for a while (DEL-154)."""
    get_campaign(request, campaign_id)
    check_length(body.question.strip(), ASK_CHARS, "A question is")
    seat_throttle(request.app).take(seat.id, "ask")
    try:
        return {"answer": await ask(table(request), campaign_id, body.question, asker=seat.id)}
    except AskFailed as failed:
        raise refusal(failed, 502) from None
    except PlayError as refused:
        raise refusal(refused) from None


@router.post("/api/campaigns/{campaign_id}/ask/{answer_id}/share", status_code=201)
async def share_answer(request: Request, seat: TableSeat, campaign_id: str, answer_id: str) -> dict:
    """Share an Ask the DM answer and its question with the table, as table talk: the `talk` entry. Only who asked
    may (403); 404 for anything but an answer of this campaign."""
    get_campaign(request, campaign_id)
    try:
        return {"entry": entry_json(share(table(request), campaign_id, seat, answer_id))}
    except NotFound as missing:
        raise refusal(missing, 404) from None
    except NotYours as refused:
        raise refusal(refused, 403) from None


class TalkIn(BaseModel):
    text: str


@router.post("/api/campaigns/{campaign_id}/talk", status_code=201)
async def talk_at_the_table(request: Request, seat: TableSeat, campaign_id: str, body: TalkIn) -> dict:
    """Table talk, for everyone at the table, observers included: the `talk` entry. It is never part of a beat or
    the DM's message. 422 past `TALK_CHARS`, 429 past the seat's lines for a while (DEL-154)."""
    get_campaign(request, campaign_id)
    check_length(body.text.strip(), TALK_CHARS, "Table talk is")
    seat_throttle(request.app).take(seat.id, "talk")
    try:
        return {"entry": entry_json(await talk(table(request), campaign_id, seat, body.text))}
    except PlayError as refused:
        raise refusal(refused) from None


@router.post("/api/campaigns/{campaign_id}/talk/picture", status_code=201)
async def paste_a_picture(request: Request, seat: TableSeat, campaign_id: str) -> dict:
    """A picture pasted into table talk (DEL-294): the body is the picture, one of `TALK_PICTURE_TYPES` (the guard
    refuses others with 415) of at most `TALK_PICTURE_LIMIT` bytes (413). 403 while the campaign's `talk_pictures`
    option is off and for an observer, 400 for bytes that aren't the type sent, 422 past its pixels, 429 past the
    seat's lines for a while: a picture is a line of talk."""
    get_campaign(request, campaign_id)
    seat_throttle(request.app).take(seat.id, "talk")
    media_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > TALK_PICTURE_LIMIT:
            raise HTTPException(status_code=413, detail=f"A picture may be at most {TALK_PICTURE_LIMIT} bytes.")
    services = table(request)
    try:
        # Who may paste is checked before the picture is decoded: a refused seat costs nothing.
        may_paste(services, campaign_id, seat)
    except PictureNotAllowed as refused:
        raise refusal(refused, 403) from None
    try:
        picture = await run_in_threadpool(talk_picture, bytes(data), media_type)
    except TalkPictureRefused as refused:
        raise HTTPException(status_code=refused.status, detail=str(refused)) from None
    try:
        return {"entry": entry_json(paste_picture(services, campaign_id, seat, picture))}
    except PictureNotAllowed as refused:
        raise refusal(refused, 403) from None


@router.get("/api/campaigns/{campaign_id}/talk/pictures/{entry_id}")
def talk_picture_bytes(request: Request, seat: TableSeat, campaign_id: str, entry_id: str) -> Response:
    """A picture in table talk, for everyone at the table; 404 for none, or one taken down. Read again on every view
    (no-cache), so a picture taken down is gone at once, but its ETag answers 304 to a browser that has it."""
    get_campaign(request, campaign_id)
    picture = picture_of(table(request), campaign_id, entry_id)
    data = request.app.state.storage.blobs.get(picture["blob"]) if picture is not None else None
    if picture is None or data is None:
        raise HTTPException(status_code=404, detail="No such picture.")
    tag = f'"{picture["blob"]}"'
    if tag in {t.strip() for t in request.headers.get("if-none-match", "").split(",")}:
        return Response(status_code=304, headers={"ETag": tag, "Cache-Control": "private, no-cache"})
    response = attachment_response(data, picture.get("mime") or "image/webp")
    response.headers["Cache-Control"] = "private, no-cache"
    response.headers["ETag"] = tag
    return response


@router.delete("/api/campaigns/{campaign_id}/talk/pictures/{entry_id}")
def take_a_picture_down(request: Request, seat: TableSeat, campaign_id: str, entry_id: str) -> dict:
    """Take a picture out of table talk: the host, a co-host or who pasted it (403 for anyone else); 404 for none."""
    get_campaign(request, campaign_id)
    try:
        return {"entry": entry_json(take_down(table(request), campaign_id, seat, entry_id))}
    except NotFound as missing:
        raise refusal(missing, 404) from None
    except PictureNotAllowed as refused:
        raise refusal(refused, 403) from None


@router.post("/api/campaigns/{campaign_id}/cancel")
async def cancel(request: Request, seat: HostSeat, campaign_id: str) -> dict:
    """The host or a co-host stops the DM's answer to the running beat; `cancelled` is false when none was
    running."""
    get_campaign(request, campaign_id)
    return {"cancelled": await cancel_beat(table(request), campaign_id)}


# ----- the session -----


class SessionStartIn(BaseModel):
    absent: dict[str, str] = {}


@router.post("/api/campaigns/{campaign_id}/session/start", status_code=202)
async def start_the_session(
    request: Request, seat: HostSeat, campaign_id: str, body: SessionStartIn | None = None
) -> dict:
    """Start the session: the host or a co-host, while the table gathers, with a choice for each absent PC (`absent`,
    character id to `in_character`, `hold_back` or `out`). The table plays, and the DM opens the scene in a beat that
    runs at once. 202 with the table and the beat; 409 unless the table gathers with no beat open or running; 422 for
    an unknown character or choice."""
    get_campaign(request, campaign_id)
    services = table(request)
    absent = body.absent if body is not None else {}
    beat = _moved(lambda: table_session.start_session(services, campaign_id, seat, absent))[1]
    return {"table": table_session.table_json(services.storage, campaign_id), "beat": beat_json(beat)}


@router.post("/api/campaigns/{campaign_id}/session/break")
def take_a_break(request: Request, seat: HostSeat, campaign_id: str) -> dict:
    """Take a break: acts, passes and go wait, and an open beat's timer stops. 409 unless the table plays."""
    get_campaign(request, campaign_id)
    services = table(request)
    _moved(lambda: table_session.take_break(services, campaign_id, seat))
    return {"table": table_session.table_json(services.storage, campaign_id)}


@router.post("/api/campaigns/{campaign_id}/session/resume")
async def back_to_the_story(request: Request, seat: HostSeat, campaign_id: str) -> dict:
    """Back to the story: the table plays, and an open beat's deadline moves on by the length of the break. 409
    unless the table is on a break."""
    get_campaign(request, campaign_id)
    services = table(request)
    _moved(lambda: table_session.back_to_story(services, campaign_id, seat))
    return {"table": table_session.table_json(services.storage, campaign_id)}


@router.post("/api/campaigns/{campaign_id}/session/end", status_code=202)
async def end_the_session(request: Request, seat: HostSeat, campaign_id: str) -> dict:
    """End the session: the table gathers at once, and the DM brings the scene to a pause and makes the recap in a
    beat that runs at once. 202 with the table and the beat; 409 while the table gathers, or a beat is open or
    running."""
    get_campaign(request, campaign_id)
    services = table(request)
    beat = _moved(lambda: table_session.end_session(services, campaign_id, seat))[1]
    return {"table": table_session.table_json(services.storage, campaign_id), "beat": beat_json(beat)}


class HandIn(BaseModel):
    point: str | None = None


@router.post("/api/campaigns/{campaign_id}/hand")
def raise_hand(request: Request, seat: TableSeat, campaign_id: str, body: HandIn | None = None) -> dict:
    """The seat raises its hand, with an optional point; raising it again replaces the point. 422 past
    `table_session.POINT_CHARS`."""
    get_campaign(request, campaign_id)
    services = table(request)
    point = body.point if body is not None else None
    _moved(lambda: table_session.raise_hand(services, campaign_id, seat, point))
    return {"table": table_session.table_json(services.storage, campaign_id)}


@router.delete("/api/campaigns/{campaign_id}/hand/{seat_id}")
def lower_hand(request: Request, seat: TableSeat, campaign_id: str, seat_id: str) -> dict:
    """Lower a hand: the seat's own, or anyone's for the host and co-hosts (403 otherwise). One that isn't up is
    fine."""
    get_campaign(request, campaign_id)
    services = table(request)
    _moved(lambda: table_session.lower_hand(services, campaign_id, seat, seat_id))
    return {"table": table_session.table_json(services.storage, campaign_id)}


class AwayIn(BaseModel):
    seat_id: str | None = None
    part: str | None = None


@router.post("/api/campaigns/{campaign_id}/away")
async def step_away(request: Request, seat: TableSeat, campaign_id: str, body: AwayIn | None = None) -> dict:
    """A seat steps away mid-session (DEL-224): the seat's own, or `seat_id` for the host and co-hosts (403 for
    anyone else), with the `part` its PCs take meanwhile (`in_character`, `hold_back`, `out`, or none for the table's
    fallback). Beats stop waiting for it. 409 unless the session is under way; 422 for a seat or part that won't do."""
    get_campaign(request, campaign_id)
    services = table(request)
    seat_id = (body.seat_id if body is not None else None) or seat.id
    part = body.part if body is not None else None
    _moved(lambda: table_session.step_away(services, campaign_id, seat, seat_id, part))
    return {"table": table_session.table_json(services.storage, campaign_id)}


@router.delete("/api/campaigns/{campaign_id}/away/{seat_id}")
def come_back(request: Request, seat: TableSeat, campaign_id: str, seat_id: str) -> dict:
    """A seat is back: the seat's own, or anyone's for the host and co-hosts (403 otherwise). One that isn't away is
    fine."""
    get_campaign(request, campaign_id)
    services = table(request)
    _moved(lambda: table_session.come_back(services, campaign_id, seat, seat_id))
    return {"table": table_session.table_json(services.storage, campaign_id)}


class PartIn(BaseModel):
    part: str | None = None


@router.put("/api/campaigns/{campaign_id}/parts/{character_id}")
def set_part(request: Request, seat: HostSeat, campaign_id: str, character_id: str, body: PartIn) -> dict:
    """The host or a co-host sets the part a PC takes while its player doesn't act, for the rest of the session
    (DEL-224): `in_character`, `hold_back`, `out`, or none to leave it to its player again. 409 unless the session is
    under way; 422 for an unknown PC or part."""
    get_campaign(request, campaign_id)
    services = table(request)
    _moved(lambda: table_session.set_part(services, campaign_id, seat, character_id, body.part))
    return {"table": table_session.table_json(services.storage, campaign_id)}


def _moved(move: Callable[[], Any]) -> Any:
    """What a move of the table's session state answers, its refusals as statuses: 409 for the state or a beat in the
    way, 403 for a seat it isn't for, 422 for what it was given."""
    try:
        return move()
    except (BeatRunning, table_session.SessionRefused) as refused:
        raise refusal(refused, 409) from None
    except NotAllowed as refused:
        raise refusal(refused, 403) from None
    except PlayError as refused:
        raise refusal(refused) from None


# ----- reading -----


@router.get("/api/campaigns/{campaign_id}/story")
def get_story(
    request: Request,
    seat: TableSeat,
    campaign_id: str,
    before: Annotated[int | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=STORY_LIMIT)] = 50,
    language: Annotated[str | None, Query(max_length=16)] = None,
    kind: Annotated[StoryKind | None, Query()] = None,
) -> dict:
    """A page of the story as the seat may see it, oldest first: the last `limit` of its entries before the seq
    `before`, and `has_more`; with `kind` (`talk`, the talk panel's, DEL-219) only entries of that kind. With `language`, each entry that has a translation into it carries it, `{language,
    text, status}`, and a shared answer's `answer`: only of the entries the seat sees."""
    get_campaign(request, campaign_id)
    storage = request.app.state.storage
    page = story(storage, campaign_id, seat, before_seq=before, limit=limit, kind=kind)
    entries = [entry_json(e) for e in page["entries"]]
    if language is not None:
        found = storage.translations.for_entries([e["id"] for e in entries], language)
        for entry in entries:
            translation = found.get(entry["id"])
            if translation is not None:
                entry["translation"] = {k: getattr(translation, k) for k in ("language", "text", "status")}
                if translation.answer is not None:  # a shared answer's (plan 7 Task 18)
                    entry["translation"]["answer"] = translation.answer
    return {"entries": entries, "has_more": page["has_more"]}


@router.get("/api/campaigns/{campaign_id}/log")
def get_campaign_log(
    request: Request,
    seat: TableSeat,
    campaign_id: str,
    page: Annotated[int, Query(ge=1)] = 1,
    language: Annotated[str | None, Query(max_length=16)] = None,
) -> dict:
    """The campaign's log from start to end, to browse or print (DEL-324): the index of its pages, by session, and
    page `page`'s entries as the seat saw them, with the dice the players read (`play.campaign_log`). 404 for a page
    past the last."""
    get_campaign(request, campaign_id)
    try:
        return campaign_log(request.app.state.storage, campaign_id, seat, page, language)
    except NotFound as missing:
        raise refusal(missing, 404) from None


@router.get("/api/campaigns/{campaign_id}/play/state")
async def play_state(request: Request, seat: TableSeat, campaign_id: str) -> dict:
    """The table as the players see it: the running beat (with its elapsed time; the tool count is the host's
    `beat_tools` event), the party in
    marching order and the PCs who left it apart (`departed`, `{id, name, departure}`), where each group is, the
    fight as the seat's initiative timeline shows it (`combat`, `delve.play.timeline.timeline_for`'s `fight`: no
    enemy the party hasn't seen, no outcome the DM hasn't told), the session, the time, the date,
    and today's weather once the DM has asked for it, the campaign's portrait style, which every seat draws in, the
    party's purse, the campaign's ruleset (for the play header's Rulesets link: a seat can't read the campaign),
    whether a scene can be painted now (`scene_painting`, which a `play_options` event says to read again), the
    scenes still painting that this seat will see (`painting_scenes`, read again on a `scenes` event), and
    the table's session state (`table`, `table_session.table_json`: gathering, playing or on a break, whether the
    table is solo, the absent PCs' choices and the raised hands; read again, or taken from, a `table` event), and the
    table's next sessions (`schedule.next_sessions`, read again on a `table_listing` event).

    The host and co-hosts get every group, for the single-player switcher. A player gets only the groups its
    characters are in, and the fight only when one of them fights in it; an observer gets neither."""
    get_campaign(request, campaign_id)
    beat = running_beat(table(request), campaign_id)
    try:
        state = await run_in_threadpool(_table_state, request, campaign_id, seat)
    except Exception:
        get_campaign(request, campaign_id)  # deleted while it was read, from a tab still open: a 404, not a 500
        raise
    return {"beat": beat, **state}


PARTY_KEYS = ("id", "name", "race", "cls", "levels", "hp", "hp_max", "ac", "conditions", "spells", "encumbrance")


def _table_state(request: Request, campaign_id: str, seat: Seat) -> dict[str, Any]:
    storage = request.app.state.storage
    campaign = storage.campaigns.get(campaign_id)
    missing = missing_pack(catalogs_of(request), campaign) if campaign is not None else None
    ctx = context_for(
        storage, campaign_id, "state", catalogs=catalogs_of(request), allow_missing=True
    )
    seen = None if seat.role in seats.TABLE_RIGHTS else seats.controls(storage, seat.id)  # None: every group
    if ctx.lookups is not NO_LOOKUPS:
        primer = sessions.primer(ctx, roll_weather=False)  # a seat's read never rolls the weather
        party = [{key: pc[key] for key in PARTY_KEYS} for pc in primer["party"]]
        positions = primer["positions"] if seen is None else sessions.positions(ctx, seen)
        session, time = primer["session"]["number"], f"{primer['time']} ({primer['period']})"
    else:  # a ruleset with nothing to look up in: the sheets as stored, without encumbrance
        party = [_digest(c) for c in play_characters.party(ctx)]
        positions = []
        state = storage.campaign_states.get(campaign_id)
        session = state.session if state else None
        time = f"{state.hour:02d}:{state.minute:02d} ({sessions.period(state.hour)})" if state else None
    forecast = weather.current(ctx)
    campaign = storage.campaigns.get(campaign_id)
    return {
        "party": party,
        "marching_order": [pc["id"] for pc in party],
        # The PCs who left the party, apart from it (table voice and fixes Task C2).
        "departed": [
            {"id": c.id, "name": c.name, "departure": c.departure}
            for c in storage.characters.list(campaign_id)
            if c.kind == "pc" and c.departure is not None
        ],
        "positions": positions,
        "combat": timeline.timeline_for(storage, campaign_id, seat)["fight"],
        "session_number": session,
        # The session is over (its recap written) and the next hasn't begun: the header says so (DEL-182).
        "session_over": _session_over(storage, campaign_id, session),
        # The party's level outside the module's levels, for the host (DEL-187); null when it fits.
        "level_fit": sessions.level_fit(ctx),
        "time_of_day": time,
        "date": days.today(ctx).label,
        "weather": {"label": forecast.label, "effect": forecast.effect} if forecast is not None else None,
        # The styles its portraits are drawn in, a PC's and an NPC's: the campaign's own, else Preferences' (DEL-252).
        "portrait_style": images.portrait_style(storage, campaign_id, Job.IMAGE_PORTRAIT),
        "npc_portrait_style": images.portrait_style(storage, campaign_id, Job.IMAGE_NPC_PORTRAIT),
        "banner": _banner_id(storage, campaign_id),
        "coin": _purse(storage, campaign_id),
        "ruleset": campaign.ruleset,
        # The ruleset or setting the campaign needs that isn't installed, which the screen says and stops acting for.
        "missing_pack": {"kind": missing.kind, "id": missing.id} if missing is not None else None,
        # Whether the table may talk in voice, and how its fights roll initiative (table voice and fixes Task 0).
        "voice": campaign.voice,
        "initiative": campaign.initiative,
        # Whether a seat's "Paint this scene" can paint now: paid images are on, or the scene's model is free.
        "scene_painting": images.paid_images(storage, campaign_id) or not table(request).image_paid(Job.IMAGE_SCENE),
        # Whether a scene costs the host money, which Paint this scene says before it paints (DEL-258).
        "scene_paid": table(request).image_paid(Job.IMAGE_SCENE),
        # Whether the seated players and the hosts may paste pictures into table talk (DEL-294).
        "talk_pictures": play_settings(storage, campaign_id)["talk_pictures"],
        # Several players at the host's screen, and who they play (DEL-365).
        "hotseat": hotseat.state(storage, campaign_id),
        "painting_scenes": images.painting_scenes(storage, seat),
        "table": table_session.table_json(storage, campaign_id),
        # The table's next sessions (DEL-204 part C), for the play header while the table gathers.
        "next_sessions": schedule.next_sessions(campaign.schedule, request.app.state.clock.now()),
    }


def _purse(storage, campaign_id: str) -> dict[str, int]:
    """The party's purse, every coin named (0 for none), as every seat may read it."""
    state = storage.campaign_states.get(campaign_id)
    coin = state.coin if state is not None else {}
    return {name: int(coin.get(name, 0)) for name in COINS}


def _session_over(storage: Storage, campaign_id: str, number: int | None) -> bool:
    """Whether session `number` has ended: True from End the session until the next one starts."""
    if number is None:
        return False
    found = storage.sessions.get(campaign_id, number)
    return found is not None and found.ended_at is not None


def _banner_id(storage, campaign_id: str) -> str | None:
    """The banner the table shows (its own, else its module's, DEL-123), by id, for the picture's address."""
    shown = banners.shown(storage, campaign_id)
    return shown.id if shown is not None else None


def _digest(character: Character) -> dict[str, Any]:
    sheet, state = character.sheet, character.state
    return {
        "id": character.id,
        "name": character.name,
        "race": sheet.race,
        "cls": sheet.cls,
        "levels": dict(sheet.levels),
        "hp": state.hp,
        "hp_max": sheet.hp_max,
        "ac": sheet.ac,
        "conditions": list(state.conditions),
        "spells": {
            "memorized": [s.name for s in state.memorized],
            "uncast": [s.name for s in state.memorized if not s.cast],
        },
        "encumbrance": None,
    }


# ----- the campaign's table options -----


class PlaySettingsIn(BaseModel):
    tone: str | None = None
    custom_tone: str | None = None
    """The organiser's own tone, which the DM reads with the tone `custom`."""
    detail: int | None = None
    effort: str | None = None
    model: str | None = None
    beat_timer_s: StrictInt | None = None
    fallback: str | None = None
    paid_images: StrictBool | None = None
    paid_images_per_day: StrictInt | None = None
    portrait_style: str | None = None
    xp_awards: list[str] | None = None
    enemy_dice: str | None = None
    """Whether the story shows the enemies' dice to every seat: `screen` (no) or `open` (DEL-270)."""
    show_dice: StrictBool | None = None
    """Whether the story shows the seats but the host's any dice (DEL-280)."""
    talk_pictures: StrictBool | None = None
    """Whether the seated players and the hosts may paste pictures into table talk (DEL-294)."""
    hotseat: StrictBool | None = None
    """Several players at the host's screen, each acting for their own characters (DEL-365)."""
    hotseat_players: list[dict[str, Any]] | None = None
    """The hotseat players, `{id?, name, characters}` each (`delve.play.hotseat.validated`)."""


# What only an organiser sets; the host sets the beat timer and its fallback.
ORGANISER_OPTIONS = ("tone", "custom_tone", "detail", "effort", "model", "portrait_style", "xp_awards")
# What spends money: the host's alone among the seats, and an organiser's (owner ruling).
PAID_OPTIONS = ("paid_images", "paid_images_per_day")
# What shows every seat more of the DM's side: the host's alone among the seats, and an organiser's, as paid images
# are (DEL-270).
HOST_OPTIONS = ("enemy_dice", "show_dice")
# What lets every seat show the table pictures: the host's alone among the seats, and an organiser's (DEL-294).
PICTURE_OPTIONS = ("talk_pictures",)
# Who plays at the host's own screen: the host's alone among the seats, as the screen is theirs, and an organiser's
# (DEL-365).
HOTSEAT_OPTIONS = ("hotseat", "hotseat_players")


@router.get("/api/campaigns/{campaign_id}/play/options")
def get_table_options(request: Request, seat: HostSeat, campaign_id: str) -> dict:
    get_campaign(request, campaign_id)
    return _options_json(play_settings(request.app.state.storage, campaign_id))


@router.put("/api/campaigns/{campaign_id}/play/options")
async def put_table_options(request: Request, seat: HostSeat, campaign_id: str, body: PlaySettingsIn) -> dict:
    """The campaign's tone and detail level, its own tone for `custom` (`custom_tone`, at most 2000 characters,
    stripped), its DM model and effort over Preferences' choice (null: as in Preferences), the style its portraits are drawn in (`portrait_style`) and what XP is awarded for (`xp_awards`,
    DEL-113), which only an organiser sets (403). A
    model or effort the DM's provider doesn't offer is refused with 422. It applies from the next beat. The host sets the beat timer (30 to 1800 seconds, or null for none) and its
    fallback (`hold_back` or `in_character`), which apply to the open beat at once. Paid images (`paid_images`)
    cost money: only the host turns them on or off, not a co-host, and says how many may be painted in 24 hours
    (`paid_images_per_day`, 1 to 500; DEL-153). Whether every seat sees the enemies' dice in the story (`enemy_dice`,
    `screen` or `open`; DEL-270), and whether it shows any dice at all (`show_dice`, DEL-280), are the host's too, or an
    organiser's: every seat reads its story again. Hotseat (`hotseat`) and its players (`hotseat_players`, DEL-365)
    are the host's or an organiser's, as the screen they share is the host's; a change rechecks the open beat."""
    get_campaign(request, campaign_id)
    raw = body.model_dump(exclude_unset=True)
    if any(key in raw for key in ORGANISER_OPTIONS) and "organiser" not in current_principal(request).roles:
        raise HTTPException(status_code=403, detail="Only an organiser can change the DM's options.")
    paying = any(key in raw for key in PAID_OPTIONS)
    if paying and seat.role != "host" and "organiser" not in current_principal(request).roles:
        raise HTTPException(status_code=403, detail="Only the host can turn paid images on or off.")
    showing = any(key in raw for key in HOST_OPTIONS)
    if showing and seat.role != "host" and "organiser" not in current_principal(request).roles:
        raise HTTPException(status_code=403, detail="Only the host can show or hide the dice.")
    picturing = any(key in raw for key in PICTURE_OPTIONS)
    if picturing and seat.role != "host" and "organiser" not in current_principal(request).roles:
        raise HTTPException(status_code=403, detail="Only the host can allow pictures in table talk.")
    seating = any(key in raw for key in HOTSEAT_OPTIONS)
    if seating and seat.role != "host" and "organiser" not in current_principal(request).roles:
        raise HTTPException(status_code=403, detail="Only the host can set up the hotseat.")
    for key in (*PAID_OPTIONS, *HOST_OPTIONS, *PICTURE_OPTIONS, *HOTSEAT_OPTIONS):
        if key in raw and raw[key] is None:
            del raw[key]
    if "fallback" in raw and raw["fallback"] is None:
        del raw["fallback"]
    if raw.get("effort") is not None or raw.get("model") is not None:
        caps = _caps(request.app, current_preferences(request.app).choices[Job.DM].provider)
        if raw.get("model") is not None and raw["model"] not in caps.models:
            raise HTTPException(status_code=422, detail=f"The DM's provider doesn't offer the model '{raw['model']}'.")
        if raw.get("effort") is not None and raw["effort"] not in caps.efforts:
            raise HTTPException(status_code=422, detail=f"The DM's provider doesn't offer the effort '{raw['effort']}'.")
    # A null portrait_style is sent: "as in Preferences" (DEL-252).
    for key in ("tone", "custom_tone", "detail", "xp_awards"):
        if key in raw and raw[key] is None:
            del raw[key]
    try:
        stored = set_play_settings(request.app.state.storage, campaign_id, raw)
    except PlayError as refused:
        raise refusal(refused) from None
    if "beat_timer_s" in raw:
        beats.timer_changed(table(request), campaign_id)
    if raw.get("paid_images") is True:
        wake_banners(request.app, campaign_id)
    story = "enemy_dice" in raw or "show_dice" in raw
    if any(key in raw for key in HOTSEAT_OPTIONS):
        # The beat may wait for fewer hotseat players now, or no longer for any.
        beats.recheck(table(request), campaign_id)
    if "paid_images" in raw or story or "talk_pictures" in raw or any(key in raw for key in HOTSEAT_OPTIONS):
        # Every seat's "Paint this scene" shows or hides with paid images; with the enemies' dice, every seat reads
        # its story again (`story`), as the dice it may read changed (DEL-270); every seat's talk box shows or hides
        # its picture button with `talk_pictures` (DEL-294).
        data = {"campaign_id": campaign_id, **({"story": True} if story else {})}
        request.app.state.events.publish("play_options", data, scope="table", campaign_id=campaign_id)
    return _options_json(stored)


def wake_banners(app, campaign_id: str | None = None) -> None:
    """Paint the waiting banners whose gate opened (`banners.wake`), of the campaign or of all; a failure is only
    logged, never the request's."""
    try:
        banners.wake(table_of(app), campaign_id)
    except Exception:
        log.exception("waking the banners failed")


def _options_json(settings: dict[str, Any]) -> dict[str, Any]:
    keys = (*ORGANISER_OPTIONS, "beat_timer_s", "fallback", *PAID_OPTIONS, *HOST_OPTIONS, *PICTURE_OPTIONS, *HOTSEAT_OPTIONS)
    return {key: settings[key] for key in keys}


# ----- the party's marching order -----


class MarchingOrderIn(BaseModel):
    order: list[str]


@router.put("/api/campaigns/{campaign_id}/marching-order")
def put_marching_order(request: Request, principal: Organiser, campaign_id: str, body: MarchingOrderIn) -> dict:
    """Set the PCs' marching order, front first, by id (as the DM's `set_marching_order`)."""
    get_campaign(request, campaign_id)
    storage = request.app.state.storage
    ctx = context_for(storage, campaign_id, "host", catalogs=catalogs_of(request))
    try:
        with storage.transaction():
            ordered = play_characters.set_marching_order(ctx, body.order)
    except PlayError as refused:
        raise refusal(refused) from None
    characters_changed(request, campaign_id)
    return {"order": [c.id for c in ordered]}


# ----- the images the DM shows -----


@router.get("/api/campaigns/{campaign_id}/images/{asset_id}")
def campaign_image(request: Request, seat: TableSeat, campaign_id: str, asset_id: str) -> Response:
    """An image `show_image` may show: the bytes when the campaign's pinned revision holds it for the players, else
    404, whoever asks. The working copy's attachments are the module's route's, never this one's."""
    storage = request.app.state.storage
    campaign = get_campaign(request, campaign_id)
    source = pinned_source(storage, campaign.module_id, campaign.revision)
    found = next((a for a in source.player_images() if a.id == asset_id), None) if source is not None else None
    data = storage.blobs.get(found.sha256) if found is not None else None
    if found is None or data is None:
        raise HTTPException(status_code=404, detail="No such image.")
    return attachment_response(data, found.type)


# ----- pictures -----


@router.get("/api/campaigns/{campaign_id}/pictures/{image_id}")
def picture(request: Request, seat: TableSeat, campaign_id: str, image_id: str) -> Response:
    """A painted picture of the campaign (plan 6 Task 10): a subject's portrait for everyone at the table, a scene
    for its audience; 404 for anything else, and while it is painting."""
    get_campaign(request, campaign_id)
    storage = request.app.state.storage
    image = storage.campaign_images.get(image_id)
    data = storage.blobs.get(image.blob) if image is not None and image.blob is not None else None
    if image is None or image.campaign_id != campaign_id or data is None or not images.can_see(storage, seat, image):
        raise HTTPException(status_code=404, detail="No such picture.")
    return attachment_response(data, image.mime or "image/png")


class SceneIn(BaseModel):
    hint: str = ""


@router.post("/api/campaigns/{campaign_id}/scene", status_code=202)
async def paint_scene(request: Request, seat: ActorSeat, campaign_id: str, body: SceneIn) -> dict:
    """A seat's "Paint this scene" (any seat but an observer's; the host pays, by turning paid images on): a side
    pass writes the painter's brief from the last narrations and the hint,
    and the scene is painted in the background; 202 with `{image_id, status}`. 422 while paid images are off or
    before any narration; 429 past the campaign's paid pictures for 24 hours (DEL-153); 502 when the side pass
    writes no brief. A hint past `HINT_CHARS` is 422, and a seat's scenes past its rate 429 (DEL-154)."""
    get_campaign(request, campaign_id)
    check_length(body.hint.strip(), HINT_CHARS, "A hint is")
    seat_throttle(request.app).take(seat.id, "scene")
    try:
        image = await images.paint_this_scene(table(request), campaign_id, body.hint)
    except images.BriefFailed as failed:
        raise refusal(failed, 502) from None
    except images.PaidUsedUp as used_up:
        raise refusal(used_up, 429) from None
    except PlayError as refused:
        raise refusal(refused) from None
    return {"image_id": image.id, "status": image.status}


# ----- the banner -----


async def banner_response(request: Request, image, size: BannerSize | None = None) -> Response:
    """A banner's picture, or with `size` its card's copy (DEL-234): `assets.banner_picture`. 404 for none."""
    return await banner_picture(
        request, image.blob if image is not None else None, (image.mime if image is not None else None), size
    )


@router.get("/api/campaigns/{campaign_id}/banner")
async def banner(request: Request, seat: TableSeat, campaign_id: str, size: BannerSize | None = None) -> Response:
    """The campaign's banner (`banners.shown`: its own, else its module's), for everyone at its table, or with
    `size=card` its small copy for the cards; 404 while it has none. A waiting, painting or failed one is never
    served."""
    get_campaign(request, campaign_id)
    return await banner_response(request, banners.shown(request.app.state.storage, campaign_id), size)


class BannerIn(BaseModel):
    hint: str = ""


@router.post("/api/campaigns/{campaign_id}/banner", status_code=202)
async def paint_banner_again(request: Request, principal: Organiser, campaign_id: str, body: BannerIn) -> dict:
    """An organiser's "Paint again": a new banner, painted in the background with the hint as its emphasis, while the
    old one stays shown until it lands; 202 with `{image_id, status}`. 422 while the gate is closed, 409 while one is
    being painted."""
    campaign = get_campaign(request, campaign_id)
    try:
        image = banners.paint_again(table(request), campaign_id, setting_title(request, campaign), body.hint)
    except PlayError as refused:
        raise refusal(refused, 409 if refused.message == banners.PAINTING_ALREADY else 422) from None
    return {"image_id": image.id, "status": image.status}


@router.get("/api/campaigns/{campaign_id}/story/{entry_id}/tool")
def get_tool_call(request: Request, seat: TableSeat, campaign_id: str, entry_id: str) -> JSONResponse:
    """A tool row's call and reply, from the DM log: the host's alone (owner, 2026-10-22), since a reply can hold the
    DM's secrets; a co-host sees the row, not this. 404 for an entry that isn't one of the campaign's tool rows."""
    if seat.role != "host":
        raise HTTPException(status_code=403, detail=seats.ONLY_THE_HOST)
    storage = request.app.state.storage
    entry = storage.story.get(entry_id)
    details = (
        tool_call_of(storage, table(request).spec_lookup, entry) if entry and entry.campaign_id == campaign_id else None
    )
    if details is None:
        raise HTTPException(status_code=404, detail="No such tool row.")
    return JSONResponse(details, headers={"Cache-Control": "no-store"})


@router.get("/api/campaigns/{campaign_id}/play/usage")
def account_usage(request: Request, seat: TableSeat, campaign_id: str) -> JSONResponse:
    """The Claude account's usage as the CLI last reported it: each window's share used and its reset, soonest first
    (`delve.dm.claude_cli.account`), or `{"usage": null}` before any. The host's alone: the subscription is theirs."""
    if seat.role != "host":
        raise HTTPException(status_code=403, detail=seats.ONLY_THE_HOST)
    get_campaign(request, campaign_id)
    return JSONResponse({"usage": account.latest()}, headers={"Cache-Control": "no-store"})


# ----- the DM view -----


@router.get("/api/campaigns/{campaign_id}/dm/log")
def get_dm_log(
    request: Request, principal: Organiser, campaign_id: str, beat: Annotated[str | None, Query()] = None
) -> JSONResponse:
    """The DM's raw stream, event by event: the DM view's, never the player's screen."""
    get_campaign(request, campaign_id)
    entries = dm_log(request.app.state.storage, campaign_id, beat)
    body = {"entries": [{"beat_id": e.beat_id, "raw": e.raw_event_json, "at": e.at} for e in entries]}
    return JSONResponse(body, headers={"Cache-Control": "no-store"})


@router.get("/api/campaigns/{campaign_id}/dm/costs")
def get_dm_costs(request: Request, principal: Organiser, campaign_id: str) -> JSONResponse:
    """The DM log summed per beat, for the campaign page (DEL-172): it downloaded the whole log for it, about 3.8 MB
    for 100 beats. `{rows: [{beat, at, ask, tools, input, output, cost}]}`, as `DmLogRepository.costs` sums them."""
    get_campaign(request, campaign_id)
    rows = request.app.state.storage.dm_log.costs(campaign_id)
    return JSONResponse({"rows": rows}, headers={"Cache-Control": "no-store"})
