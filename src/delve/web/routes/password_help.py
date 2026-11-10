"""A forgotten password (DEL-268, by email DEL-314): on the login page a player gives their username or, while Delve
sends mail, their email address.

With mail, an account with a confirmed address gets its reset link by email (`<public URL>/account/link/<token>`,
`accounts.LINK_HOURS`): each account the address is confirmed for, or the username's account. Any other username asks
the owner, as without mail: the request waits on the Players page (`delve.web.routes.players`), where the owner or an
organiser makes the reset link and hands it over as they hand over any link, or dismisses it. An address that matches
nothing does nothing; without mail an address matches nothing at all.

The answer is the same whether the value names an account or not, and comes once the work is queued, so it tells
nobody which usernames or addresses exist; each address asks at most `PER_ADDRESS` times in `sign_up.WINDOW_S`, as
sign-up is throttled, and each account gets at most `MAILS_PER_ACCOUNT` reset emails in that window (in memory, so a
restart forgets them).
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Body, Request

from delve.domain.accounts import Account
from delve.mail import outbox, settings
from delve.mail.compose import compose
from delve.play import accounts
from delve.web import guard
from delve.web.routes.accounts import text_field
from delve.web.routes.sign_up import SignUpThrottle

router = APIRouter()

PER_ADDRESS = 5
MAILS_PER_ACCOUNT = 3


def throttle(request: Request) -> SignUpThrottle:
    found = getattr(request.app.state, "password_help_throttle", None)
    if found is None:
        found = request.app.state.password_help_throttle = SignUpThrottle(
            PER_ADDRESS, "You've asked for a new password often"
        )
    return found


def mail_limit(request: Request) -> SignUpThrottle:
    found = getattr(request.app.state, "password_mail_limit", None)
    if found is None:
        found = request.app.state.password_mail_limit = SignUpThrottle(MAILS_PER_ACCOUNT)
    return found


def _mail_the_link(request: Request, account: Account, public_url: str) -> None:
    """Queue the account's reset link to its confirmed address, unless it had `MAILS_PER_ACCOUNT` lately."""
    if not mail_limit(request).allows(account.id):
        return
    storage, now = request.app.state.storage, request.app.state.clock.now()
    with storage.transaction():
        token = accounts.make_link(storage, account.id, "reset-password", now, by_owner=True)
        values = {"name": account.profile.display_name, "username": account.username}
        mail = compose(
            "reset", account.profile.language, values, link=f"{public_url}/account/link/{token}", off_link=None
        )
        outbox.queue(storage, account, "reset", mail, now)
    if account.reset_asked_at is not None:  # the link answered an open request
        request.app.state.events.publish("accounts", {"id": account.id}, scope="organisers")


@router.post("/api/password-help", status_code=202)
def ask_for_a_new_password(request: Request, body: Annotated[dict[str, Any], Body()]) -> dict[str, bool]:
    """Mail a reset link, or ask the owner for a new password: 202 whatever the username or address, nobody logged
    in; 422 for a missing `username` (which may hold an address), 429 for an address that asked often."""
    value = text_field(body, "username")
    throttle(request).take(guard.client_address(request))
    storage, data_dir = request.app.state.storage, request.app.state.config.data_dir
    public_url = settings.public_url(data_dir) if settings.mail_enabled(data_dir) else None
    targets = accounts.reset_targets(storage, value) if public_url is not None else []
    if targets:
        for account in targets:
            _mail_the_link(request, account, public_url)
        return {"asked": True}
    account = accounts.ask_for_reset(storage, value, request.app.state.clock.now())  # None for an address
    if account is not None:
        request.app.state.events.publish("accounts", {"id": account.id}, scope="organisers")
    return {"asked": True}
