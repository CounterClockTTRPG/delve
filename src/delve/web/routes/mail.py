"""Email (DEL-314): whether Delve sends it, a flag for anyone, so the pages can offer addresses only when mail goes; the
account's own address, its confirmation and its mail switches; and the one-click off links in the emails.

The address is the account's alone: only its own session reads it (`GET /api/account/email`), and no other answer
names it. Asking for a confirmation link is limited to `LINKS_PER_HOUR` an hour per account. The confirmation and
the off links need no login: the link is all they need. An off link's `POST` is also what a mail program sends for
`List-Unsubscribe-Post: List-Unsubscribe=One-Click`, its body form-encoded (`delve.web.guard` lets it through).

A host or co-host writes to the table, or some of it: one email to each reachable account at the table
(`delve.mail.table_mail`), in its own language, the host's words as written. A reply reaches the host's own confirmed
address only when the host asks for it (`reply_to_me`). A table sends at most `MESSAGES_PER_DAY` a day.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Body, HTTPException, Request
from starlette.responses import Response

from delve.domain.accounts import Account
from delve.mail import addresses, outbox, settings
from delve.mail.compose import compose
from delve.mail.settings import mail_enabled
from delve.mail.table_mail import recipients
from delve.play import seats
from delve.play.context import PlayError
from delve.web.refusals import refusal
from delve.web.routes.accounts import AccountCaller, text_field
from delve.web.routes.campaigns import get_campaign
from delve.web.routes.sign_up import SignUpThrottle
from delve.web.seats import HostSeat

router = APIRouter()

LINKS_PER_HOUR = 5
NO_SUCH_LINK = "This link doesn't work."
NOT_A_SWITCH = "A switch is true or false."
MESSAGES_PER_DAY = 10
DAY_S = 24 * 60 * 60
SUBJECT_LIMIT = 120
MESSAGE_LIMIT = 5000
BAD_SUBJECT = f"A subject is 1 to {SUBJECT_LIMIT} characters."
BAD_MESSAGE = f"A message is 1 to {MESSAGE_LIMIT} characters."
BAD_SEATS = "Seats are a list of the table's seat ids, or left out for everyone."
BAD_REPLY = "reply_to_me is true or false."
NO_OWN_ADDRESS = "Add and confirm your own address first."
TOO_MANY = f"This table has sent its {MESSAGES_PER_DAY} messages for today: write again tomorrow."


def throttle(request: Request) -> SignUpThrottle:
    """The app's one limit on confirmation links, counted per account."""
    found = getattr(request.app.state, "email_link_throttle", None)
    if found is None:
        found = request.app.state.email_link_throttle = SignUpThrottle(
            LINKS_PER_HOUR, "You've asked for confirmation links often"
        )
    return found


def table_throttle(request: Request) -> SignUpThrottle:
    """The app's one limit on a table's messages, counted per campaign over a day."""
    found = getattr(request.app.state, "table_mail_throttle", None)
    if found is None:
        found = request.app.state.table_mail_throttle = SignUpThrottle(MESSAGES_PER_DAY, window_s=DAY_S)
    return found


def _now(request: Request):
    return request.app.state.clock.now()


def _has_email_changed(request: Request, account_id: str) -> None:
    """The Players page's `has_email` mark may have changed: organisers hear of the account, never its address."""
    request.app.state.events.publish("accounts", {"id": account_id}, scope="organisers")


def email_json(account: Account) -> dict[str, Any]:
    """The account's own address, the one waiting for its link, and its switches: for the account alone."""
    return {
        "email": account.email,
        "pending": account.email_pending,
        "mail_host": account.mail_host,
        "mail_board": account.mail_board,
    }


@router.get("/api/mail/status")
def mail_status(request: Request) -> dict[str, bool]:
    return {"enabled": mail_enabled(request.app.state.config.data_dir)}


@router.get("/api/account/email")
def account_email(request: Request, principal: AccountCaller) -> dict[str, Any]:
    return email_json(request.app.state.storage.accounts.get(principal.account.id))


@router.put("/api/account/email", status_code=202)
def ask_for_confirmation(
    request: Request, principal: AccountCaller, body: Annotated[dict[str, Any], Body()]
) -> dict[str, Any]:
    """Set the address to confirm and send its link (again): 202, the address in use unchanged until the link is
    used. 422 for one that isn't an address, 409 while Delve sends no mail, 429 past `LINKS_PER_HOUR`."""
    try:
        address = addresses.normalise(text_field(body, "address"))
    except PlayError as refused:
        raise refusal(refused, 422) from None
    storage, data_dir = request.app.state.storage, request.app.state.config.data_dir
    if not mail_enabled(data_dir):  # before the throttle: a refusal doesn't count
        raise HTTPException(status_code=409, detail=addresses.NOT_SET_UP)
    throttle(request).take(principal.account.id)
    try:
        addresses.ask_to_confirm(storage, data_dir, storage.accounts.get(principal.account.id), address, _now(request))
    except addresses.MailNotSetUp as refused:
        raise refusal(refused, 409) from None
    return email_json(storage.accounts.get(principal.account.id))


@router.delete("/api/account/email", status_code=204)
def remove_email(request: Request, principal: AccountCaller) -> Response:
    """Forget the address and the one waiting for its link."""
    addresses.remove(request.app.state.storage, principal.account.id)
    _has_email_changed(request, principal.account.id)
    return Response(status_code=204)


@router.put("/api/account/mail")
def change_switches(request: Request, principal: AccountCaller, body: Annotated[dict[str, Any], Body()]) -> dict:
    """Turn a host's mail (`mail_host`) or the board's (`mail_board`) on or off; a switch left out stays. 422 for one
    that isn't true or false."""
    storage = request.app.state.storage
    account = storage.accounts.get(principal.account.id)
    switches = {"mail_host": account.mail_host, "mail_board": account.mail_board}
    for name in switches:
        if name in body:
            if not isinstance(body[name], bool):
                raise HTTPException(status_code=422, detail=NOT_A_SWITCH)
            switches[name] = body[name]
    storage.accounts.set_mail_switches(account.id, **switches)
    return email_json(storage.accounts.get(account.id))


@router.post("/api/account/email/confirm")
def confirm_email(request: Request, body: Annotated[dict[str, Any], Body()]) -> dict[str, bool]:
    """Confirm an address by the token its email brought, no login needed; 404 for a link that is unknown, used,
    expired or replaced."""
    token = text_field(body, "token")
    try:
        account = addresses.confirm(request.app.state.storage, token, _now(request))
    except PlayError as refused:
        raise refusal(refused, 404) from None
    _has_email_changed(request, account.id)
    return {"confirmed": True}


def _off_target(request: Request, token: str) -> tuple[str, str]:
    found = outbox.read_off_token(request.app.state.config.data_dir, token)
    if found is None or request.app.state.storage.accounts.get(found[0]) is None:
        raise HTTPException(status_code=404, detail=NO_SUCH_LINK)
    return found


@router.get("/api/mail/off/{token}")
def off_link(request: Request, token: str) -> dict[str, str]:
    """Which mail an off link turns off (`host` or `board`), no login needed; 404 for a link Delve didn't make."""
    _, group = _off_target(request, token)
    return {"group": group}


@router.post("/api/mail/off/{token}")
def turn_off(request: Request, token: str) -> dict[str, str]:
    """Turn that mail off for the link's account, no login needed: the off page's button, or a mail program's one
    click. A body, if any, isn't read."""
    account_id, group = _off_target(request, token)
    storage = request.app.state.storage
    account = storage.accounts.get(account_id)
    storage.accounts.set_mail_switches(
        account_id,
        mail_host=False if group == "host" else account.mail_host,
        mail_board=False if group == "board" else account.mail_board,
    )
    return {"group": group}


def _seat_ids(value: Any) -> list[str] | None:
    """The chosen seats, None for everyone; 422 for anything but a non-empty list of ids."""
    if value is None:
        return None
    if not isinstance(value, list) or not value or not all(isinstance(item, str) for item in value):
        raise HTTPException(status_code=422, detail=BAD_SEATS)
    return value


@router.get("/api/campaigns/{campaign_id}/mail/count")
def table_mail_count(request: Request, seat: HostSeat, campaign_id: str) -> dict[str, int]:
    """How many accounts a message to the whole table would reach now; 409 while Delve sends no mail. Only the whole
    table: a count of chosen seats would tell, player by player, who has an address (a `seats` parameter is
    ignored)."""
    if not mail_enabled(request.app.state.config.data_dir):
        raise HTTPException(status_code=409, detail=addresses.NOT_SET_UP)
    found = recipients(request.app.state.storage, campaign_id, "host", seat_ids=None, sender_seat_id=seat.id)
    return {"count": len(found)}


@router.post("/api/campaigns/{campaign_id}/mail")
def write_to_the_table(
    request: Request, seat: HostSeat, campaign_id: str, body: Annotated[dict[str, Any], Body()]
) -> dict[str, int | None]:
    """Queue the host's message for each reachable account at the table, or at the chosen `seats`; how many were
    queued for the whole table, None for chosen seats (a number there would tell who has an address). The subject is one line of 1 to `SUBJECT_LIMIT` characters, the message 1 to `MESSAGE_LIMIT`. With
    `reply_to_me` a reply reaches the host's own confirmed address (422 without one), else replies aren't read. 409
    while Delve sends no mail, 429 past `MESSAGES_PER_DAY` for the table."""
    subject = " ".join((text_field(body, "subject") or "").split())
    if not 1 <= len(subject) <= SUBJECT_LIMIT:
        raise HTTPException(status_code=422, detail=BAD_SUBJECT)
    message = text_field(body, "message") or ""
    if not message.strip() or len(message) > MESSAGE_LIMIT:
        raise HTTPException(status_code=422, detail=BAD_MESSAGE)
    chosen = _seat_ids(body.get("seats"))
    reply_to_me = body.get("reply_to_me", False)
    if not isinstance(reply_to_me, bool):
        raise HTTPException(status_code=422, detail=BAD_REPLY)
    storage, data_dir = request.app.state.storage, request.app.state.config.data_dir
    campaign = get_campaign(request, campaign_id)
    reply_to = None
    if reply_to_me:
        mine = seats.shown_account(storage, seat)
        reply_to = mine.email if mine is not None else None
        if not reply_to:
            raise HTTPException(status_code=422, detail=NO_OWN_ADDRESS)
    url = settings.public_url(data_dir)
    if url is None or not mail_enabled(data_dir):  # before the limit: a refusal doesn't count
        raise HTTPException(status_code=409, detail=addresses.NOT_SET_UP)
    if not table_throttle(request).allows(campaign.id):
        raise HTTPException(status_code=429, detail=TOO_MANY)
    values = {
        "host": seat.name,
        "table": campaign.name,
        "subject": subject,
        "message": message,
        "replyable": "1" if reply_to else "",
    }
    now = _now(request)
    sent = 0
    for account in recipients(storage, campaign.id, "host", seat_ids=chosen, sender_seat_id=seat.id):
        off = outbox.off_link(data_dir, account.id, "host")
        mail = compose(
            "host",
            account.profile.language,
            values,
            link=f"{url}/play/{campaign.id}",
            off_link=off[1] if off else None,
        )
        queued = outbox.queue(
            storage, account, "host", mail, now, reply_to=reply_to, unsubscribe=off[0] if off else None
        )
        sent += queued is not None
    return {"sent": sent if chosen is None else None}
