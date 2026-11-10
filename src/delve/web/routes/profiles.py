"""Profiles (players and tavern Task D3): an account reads and changes its own profile and uploads an avatar; others
read a profile as `delve.play.profiles.card` allows them, which is the one privacy check.

Anyone who may read none of a profile gets 404 "No such player.", the answer for an account that doesn't exist, so a
stranger can't tell one from the other. No route here lists accounts.

The avatar's upload is the fifth raw-body exception to the JSON rule: the guard has let only `AVATAR_TYPES` through,
of at most `AVATAR_LIMIT` bytes as declared; the route counts the bytes too, and `square_avatar` checks them against
the type. An account uploads at most `AVATARS_PER_MINUTE` a minute, refused ones too (429), and at most two avatars
are made at once (503 when a third waits too long). Nothing is stored for a refused upload. Each change publishes `seats` at each table of the account, so the
seat lists, which carry each seat's profile summary, are read again.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from dataclasses import replace
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from starlette.concurrency import run_in_threadpool
from starlette.responses import Response

from delve.domain.accounts import Account
from delve.play import profiles
from delve.play.avatars import AVATAR_LIMIT, AVATAR_TYPES, AvatarRefused, square_avatar
from delve.play.context import PlayError
from delve.play.profiles import ProfileViewer
from delve.web.auth import Principal, current_principal
from delve.web.refusals import refusal
from delve.web.routes.accounts import AccountCaller

router = APIRouter()

NO_SUCH_PLAYER = "No such player."
AVATAR_TYPE = "image/webp"
AVATARS_PER_MINUTE = 10
WINDOW_S = 60.0
TOO_MANY = "Too many avatars: wait a minute."

clock = time.monotonic
_counting = threading.Lock()


def viewer_of(request: Request, principal: Principal) -> ProfileViewer:
    """The caller as a reader of profiles: an account by its seats (an owner account as the owner), the owner token or
    this machine as the owner, a seat token by its one table."""
    storage = request.app.state.storage
    if principal.account is not None:
        return profiles.viewer_of_account(storage, principal.account)
    if principal.owner:
        return profiles.viewer_of_owner(storage)
    if principal.seat is not None:
        return profiles.viewer_of_seat(storage, principal.seat, organiser="organiser" in principal.roles)
    return ProfileViewer(None, frozenset(), frozenset(), "organiser" in principal.roles)


def _own_card(request: Request, account: Account) -> dict[str, Any]:
    storage = request.app.state.storage
    return profiles.card(storage, account.id, profiles.viewer_of_account(storage, account))


def _tell_the_tables(request: Request, account: Account) -> None:
    storage = request.app.state.storage
    # The owner's seats have no account but show the owner's profile (`seats.shown_account`): every table.
    campaign_ids = {seat.campaign_id for seat in storage.seats.of_account(account.id)}
    if account.owner:
        campaign_ids |= {campaign.id for campaign in storage.campaigns.list()}
    for campaign_id in sorted(campaign_ids):
        request.app.state.events.publish("seats", {"campaign_id": campaign_id}, scope="table", campaign_id=campaign_id)


def _saved(request: Request, account: Account, profile) -> dict[str, Any]:
    saved = request.app.state.storage.accounts.save_profile(account.id, profile)
    _tell_the_tables(request, saved)
    return _own_card(request, saved)


def _limit(request: Request, account_id: str) -> None:
    """429 for an account that sent `AVATARS_PER_MINUTE` avatars in the last minute (Clara's final audit, finding 1)."""
    with _counting:
        sent: defaultdict[str, deque[float]] | None = getattr(request.app.state, "avatar_uploads", None)
        if sent is None:
            sent = request.app.state.avatar_uploads = defaultdict(deque)
        now = clock()
        recent = sent[account_id]
        while recent and recent[0] <= now - WINDOW_S:
            recent.popleft()
        if len(recent) >= AVATARS_PER_MINUTE:
            raise HTTPException(status_code=429, detail=TOO_MANY)
        recent.append(now)


def _account(request: Request, principal: Principal) -> Account:
    """The caller's account as stored now, not as its login found it."""
    return request.app.state.storage.accounts.get(principal.account.id)


@router.get("/api/account/profile")
def own_profile(request: Request, principal: AccountCaller) -> dict:
    """The account's own profile, every field."""
    return _own_card(request, _account(request, principal))


@router.put("/api/account/profile")
def change_profile(request: Request, principal: AccountCaller, body: Annotated[Any, Body()]) -> dict:
    """Change some of the profile's fields (`delve.play.profiles.updated`): 422 for one that isn't allowed, and then
    nothing changes."""
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="Send the profile's fields as an object.")
    account = _account(request, principal)
    try:
        profile = profiles.updated(account.profile, body)
    except PlayError as refused:
        raise refusal(refused, 422) from None
    return _saved(request, account, profile)


@router.post("/api/account/avatar")
async def upload_avatar(request: Request, principal: AccountCaller) -> dict:
    """The body is the picture: it becomes the account's avatar, a 256 px square, over its emblem. 400 for bytes that
    aren't their type, 413 past `AVATAR_LIMIT`, 422 for a picture of too many pixels, 429 past
    `AVATARS_PER_MINUTE`, 503 while two others are being made."""
    media_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if media_type not in AVATAR_TYPES:
        raise HTTPException(status_code=415, detail="This kind of file can't be an avatar.")
    _limit(request, principal.account.id)
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > AVATAR_LIMIT:
            raise HTTPException(status_code=413, detail=f"An avatar may be at most {AVATAR_LIMIT} bytes.")
    try:
        avatar = await run_in_threadpool(square_avatar, bytes(data), media_type)
    except AvatarRefused as refused:
        raise refusal(refused, refused.status) from None
    account = _account(request, principal)
    sha = request.app.state.storage.blobs.put(avatar, AVATAR_TYPE)
    return _saved(request, account, replace(account.profile, avatar_sha=sha))


@router.delete("/api/account/avatar")
def remove_avatar(request: Request, principal: AccountCaller) -> dict:
    """Take the uploaded picture away: the emblem shows again."""
    account = _account(request, principal)
    return _saved(request, account, replace(account.profile, avatar_sha=None))


def _card(request: Request, principal: Principal, account_id: str) -> dict[str, Any]:
    found = profiles.card(request.app.state.storage, account_id, viewer_of(request, principal))
    if found is None:
        raise HTTPException(status_code=404, detail=NO_SUCH_PLAYER)
    return found


@router.get("/api/time-zones")
def time_zones(principal: Annotated[Principal, Depends(current_principal)]) -> list[str]:
    """The time zones a profile or a schedule may name (DEL-239), for the pickers."""
    return profiles.time_zones()


@router.get("/api/profiles/{account_id}")
def profile(request: Request, principal: Annotated[Principal, Depends(current_principal)], account_id: str) -> dict:
    """A player's profile as the caller may read it; 404 when they may read none of it."""
    return _card(request, principal, account_id)


@router.get("/api/profiles/{account_id}/avatar")
def avatar(request: Request, principal: Annotated[Principal, Depends(current_principal)], account_id: str) -> Response:
    """A player's uploaded picture, to those who may read the profile; 404 otherwise, or without a picture."""
    _card(request, principal, account_id)
    storage = request.app.state.storage
    account = storage.accounts.get(account_id)
    data = storage.blobs.get(account.profile.avatar_sha) if account.profile.avatar_sha else None
    if data is None:
        raise HTTPException(status_code=404, detail=NO_SUCH_PLAYER)
    headers = {"X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=86400"}
    return Response(data, media_type=AVATAR_TYPE, headers=headers)
