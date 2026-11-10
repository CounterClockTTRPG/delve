"""The Players page's API (players and tavern Task C6): an organiser lists the accounts, adds one (with a link that
sets its password), makes a reset link, disables or enables a player's account, and approves or rejects a sign-up
(DEL-156, `delve.web.routes.sign_up`): approved, it logs in; rejected, it is deleted and its username free again.

Only an owner grants or withdraws owner or organiser rights, disables or enables an owner's or an organiser's account,
and makes a reset link for one (the human's ruling of 2026-10-24); the last enabled owner account stays one. Nobody
disables their own account. Disabling ends every login of the account. Each change publishes `accounts` to the
organisers.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Body, HTTPException, Request
from pydantic import BaseModel
from starlette.responses import JSONResponse, Response

from delve.domain.accounts import LINK_HOURS, Account
from delve.mail import outbox, settings
from delve.mail.compose import compose
from delve.play import accounts, logins
from delve.play.context import NotFound, PlayError
from delve.play.seats import NotAllowed
from delve.storage import Storage
from delve.web.auth import Organiser, Principal
from delve.web.refusals import refusal
from delve.web.routes.accounts import text_field
from delve.web.routes.join import LANGUAGE, NAME_LENGTH, link_origin
from delve.web.routes.voice import table_changed

router = APIRouter()

ONLY_THE_OWNER = "Only the owner of this Delve makes organisers."
NOT_YOURSELF = "You can't disable your own account."
NO_ACCOUNT = "There is no such account."


def player_json(storage: Storage, account: Account, now: datetime) -> dict[str, Any]:
    """An account as the Players page lists it: never its password or a hash of it. `reset_asked_at` is when its player
    asked for a new password, while that request is open (DEL-268). `has_email` says only whether it has a confirmed
    address (DEL-314), so an organiser knows a reset email can reach it; the address itself stays the account's."""
    return {
        "id": account.id,
        "username": account.username,
        "display_name": account.profile.display_name,
        "organiser": account.organiser,
        "owner": account.owner,
        "disabled": account.disabled_at is not None,
        "has_password": account.has_password,
        "has_email": account.email is not None,
        "created_at": account.created_at,
        "tables": len(storage.seats.of_account(account.id)),
        "pending": account.pending,
        "request_note": account.request_note,
        "reset_asked_at": accounts.open_reset_request(account, now),
    }


def _changed(request: Request, account: Account) -> None:
    request.app.state.events.publish("accounts", {"id": account.id}, scope="organisers")


def _link(request: Request, principal: Principal, account: Account, kind: str) -> dict[str, str]:
    """403 for an owner's or an organiser's account unless `principal` is an owner."""
    now = request.app.state.clock.now()
    try:
        token = accounts.make_link(request.app.state.storage, account.id, kind, now, by_owner=principal.owner)
    except NotAllowed as refused:
        raise refusal(refused, 403) from None
    expires_at = (now + timedelta(hours=LINK_HOURS)).isoformat()
    return {"url": f"{link_origin(request)}/account/link/{token}", "expires_at": expires_at}


def _account(request: Request, account_id: str) -> Account:
    account = request.app.state.storage.accounts.get(account_id)
    if account is None:
        raise HTTPException(status_code=404, detail=NO_ACCOUNT)
    return account


@router.get("/api/accounts")
def list_accounts(request: Request, principal: Organiser) -> list[dict]:
    """Every account, the oldest first."""
    storage = request.app.state.storage
    now = request.app.state.clock.now()
    return [player_json(storage, account, now) for account in storage.accounts.list()]


@router.post("/api/accounts", status_code=201)
def add_account(request: Request, principal: Organiser, body: Annotated[dict[str, Any], Body()]) -> JSONResponse:
    """A new account without a password, and the set-password link to hand its player (valid 24 hours, used once).
    409 for a username that is taken."""
    username = text_field(body, "username")
    display_name = text_field(body, "display_name", optional=True)
    language = (text_field(body, "language", optional=True) or "en").strip().lower()
    if display_name is not None and not 1 <= len(display_name.strip()) <= NAME_LENGTH:
        raise HTTPException(status_code=422, detail=f"A name has 1 to {NAME_LENGTH} characters.")
    if not LANGUAGE.fullmatch(language):
        raise HTTPException(status_code=422, detail="A language is a code of 2 or 3 letters, such as en or nl.")
    storage = request.app.state.storage
    try:
        account = accounts.create_account(
            storage, username, None, display_name=display_name.strip() if display_name else None, language=language
        )
    except accounts.AccountConflict as refused:
        raise refusal(refused, 409) from None
    except PlayError as refused:
        raise refusal(refused, 422) from None
    link = _link(request, principal, account, "set-password")
    _changed(request, account)
    return JSONResponse(
        {"account": player_json(storage, account, request.app.state.clock.now()), "link": link}, status_code=201
    )


@router.delete("/api/accounts/{account_id}/reset-request", status_code=204)
def dismiss_reset_request(request: Request, principal: Organiser, account_id: str) -> Response:
    """Dismiss the player's request for a new password (DEL-268) without making a link."""
    account = _account(request, account_id)
    if account.reset_asked_at is not None:
        account = request.app.state.storage.accounts.set_reset_asked(account.id, None)
        _changed(request, account)
    return Response(status_code=204)


@router.post("/api/accounts/{account_id}/approve")
def approve_sign_up(request: Request, principal: Organiser, account_id: str) -> dict:
    """Let a sign-up in: it logs in from now on. 404 for no account, 409 for one that isn't waiting."""
    account = _account(request, account_id)
    try:
        account = accounts.approve(request.app.state.storage, account.id)
    except accounts.AccountConflict as refused:
        raise refusal(refused, 409) from None
    _changed(request, account)
    _say_you_are_in(request, account)
    return player_json(request.app.state.storage, account, request.app.state.clock.now())


def _say_you_are_in(request: Request, account: Account) -> None:
    """Queue "You're in" for an approved sign-up with a confirmed address, in its language (never blocks: only queues)."""
    data_dir = request.app.state.config.data_dir
    url = settings.public_url(data_dir)
    if account.email is None or url is None or not settings.mail_enabled(data_dir):
        return
    mail = compose("approved", account.profile.language, {"username": account.username}, link=f"{url}/login", off_link=None)
    outbox.queue(request.app.state.storage, account, "approved", mail, request.app.state.clock.now())


@router.delete("/api/accounts/{account_id}", status_code=204)
def reject_sign_up(request: Request, principal: Organiser, account_id: str) -> Response:
    """Turn a sign-up away: the account is deleted, its username free again. 404 for no account, 409 for one that
    isn't waiting: no other account is ever deleted (disable it instead)."""
    account = _account(request, account_id)
    try:
        accounts.reject(request.app.state.storage, account.id)
    except accounts.AccountConflict as refused:
        raise refusal(refused, 409) from None
    _changed(request, account)
    return Response(status_code=204)


@router.post("/api/accounts/{account_id}/reset-link")
def reset_link(request: Request, principal: Organiser, account_id: str) -> dict[str, str]:
    """A link that resets the account's password; its older unused link stops working."""
    account = _account(request, account_id)
    link = _link(request, principal, account, "reset-password")
    _changed(request, account)
    return link


class AccountChange(BaseModel):
    disabled: bool | None = None
    organiser: bool | None = None
    owner: bool | None = None


@router.put("/api/accounts/{account_id}")
def change_account(request: Request, principal: Organiser, account_id: str, body: AccountChange) -> dict:
    """Disable or enable the account, or (an owner only) give or take its organiser or owner rights. 403 for a right
    the caller hasn't, 409 for the last owner account, 422 for disabling one's own account. Every change happens, or
    none."""
    storage = request.app.state.storage
    account = _account(request, account_id)
    if (body.organiser is not None or body.owner is not None) and not principal.owner:
        raise HTTPException(status_code=403, detail=ONLY_THE_OWNER)
    if body.disabled and principal.account is not None and principal.account.id == account.id:
        raise HTTPException(status_code=422, detail=NOT_YOURSELF)
    now = request.app.state.clock.now()
    try:
        with storage.transaction():
            if body.owner is not None and body.owner != account.owner:
                account = accounts.set_owner(storage, account.id, body.owner, by_owner=principal.owner)
            if body.organiser is not None and body.organiser != account.organiser:
                account = accounts.set_organiser(storage, account.id, body.organiser, by_owner=principal.owner)
            if body.disabled is not None and body.disabled != (account.disabled_at is not None):
                account = logins.disable(storage, account.id, body.disabled, now, by_owner=principal.owner)
    except NotAllowed as refused:
        raise refusal(refused, 403) from None
    except accounts.AccountConflict as refused:
        raise refusal(refused, 409) from None
    except NotFound as refused:
        raise refusal(refused, 404) from None
    _changed(request, account)
    if body.disabled:
        table_changed(request.app)  # a disabled account's voice goes with its logins
    return player_json(storage, account, request.app.state.clock.now())
