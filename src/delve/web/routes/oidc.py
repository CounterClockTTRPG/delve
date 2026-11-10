"""Logging in, signing up and linking with an outside account (DEL-206), over OpenID Connect (`delve.web.oidc`).

`GET /api/auth/providers` names the providers this browser may use: the owner set the provider's client up
(Connections), and the browser came over https or to this machine as localhost, the only addresses a provider sends a
browser back to. `GET /api/auth/{provider}/start?mode=…` seals the flow in the `delve_oidc` cookie and sends the
browser to the provider; `GET /api/auth/{provider}/callback` checks it and sends the browser back to Delve's page:

- `login`: a known identity logs in (to `next`, a path on Delve, else `/`); otherwise `/login?oidc=<code>`.
- `link`: only for an account logged in, still the same at the callback, with a ticket from
  `POST /api/auth/{provider}/link`, which asks for the account's password when it has one (a session alone doesn't
  add a way in); to `/preferences?tab=profile&oidc=<code>`.
- `signup`: only while sign-up is open; the username, name, note and language come with `start`, and the account it
  asks for waits for approval as every sign-up does (DEL-156), with the identity and no password; to
  `/sign-up?oidc=<code>`. An identity linked already logs in instead.

The codes, which the pages say in the reader's language: `cancelled`, `failed`, `expired`, `not-offered`,
`not-logged-in`, `elsewhere` (another site sent the browser to `start`), `unknown`, `pending`, `disabled`, `closed`, `taken`, `invalid`, `busy`, `waiting`, `linked`,
`conflict`, `has-one`. The callback ends the
flow cookie whatever it answers. A signed-up identity counts against the sign-up throttle (`sign_up.throttle`).

`GET /api/account/identities` lists the account's identities, `DELETE /api/account/identities/{provider}` unlinks one
(refused for the account's last way to log in).
"""

from __future__ import annotations

import logging
import re
import secrets
from typing import Annotated, Any
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Body, HTTPException, Query, Request
from starlette.responses import RedirectResponse, Response

from delve.domain.accounts import PASSWORD_MAX, Account
from delve.play import accounts, identities
from delve.play.context import PlayError
from delve.play.profiles import NAME_LENGTH
from delve.web import guard, oidc
from delve.web.auth import current_principal, flow_cookie
from delve.web.routes import sign_up
from delve.web.routes.accounts import AccountCaller, log_in_on, text_field
from delve.web.routes.accounts import throttle as login_throttle
from delve.web.routes.join import LANGUAGE

router = APIRouter()
log = logging.getLogger(__name__)

MODES = ("login", "link", "signup")
PAGES = {"login": "/login", "link": "/preferences?tab=profile", "signup": "/sign-up"}
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
WRONG_PASSWORD = "That isn't your password."
NEXT_MAX = 500
# A local path: "/" then anything but a second "/" or "\" (which a browser reads as another host).
LOCAL_PATH = re.compile(r"^/(?![/\\])[^\s\\]*$")


def providers(request: Request) -> dict[str, oidc.ProviderSpec]:
    return getattr(request.app.state, "oidc_providers", None) or oidc.PROVIDERS


def oidc_client(request: Request) -> oidc.OidcClient:
    found = getattr(request.app.state, "oidc", None)
    if found is None:
        found = request.app.state.oidc = oidc.OidcClient(httpx.AsyncClient())
    return found


def offered_here(request: Request) -> bool:
    """Whether a provider sends this browser back: over https, or to this machine by a loopback name."""
    return guard.came_over_https(request) or guard.host_of(request.headers.get("host", "")) in LOCAL_HOSTS


def callback_uri(request: Request, provider: str) -> str:
    scheme = "https" if guard.came_over_https(request) else "http"
    return f"{scheme}://{request.headers.get('host', '')}/api/auth/{provider}/callback"


def redirect_uris(request: Request, provider: str) -> list[str]:
    """The callback addresses the owner registers with the provider: each name Delve answers on over its tunnel, and
    this machine's localhost."""
    port = request.app.state.config.port
    names = sorted(guard.allowed_hosts())
    return [f"https://{name}/api/auth/{provider}/callback" for name in names] + [
        f"http://localhost:{port}/api/auth/{provider}/callback"
    ]


def _usable(request: Request, provider: str) -> tuple[oidc.ProviderSpec, oidc.ClientConfig] | None:
    spec = providers(request).get(provider)
    client = oidc.load_client(request.app.state.config.data_dir, provider) if spec is not None else None
    if spec is None or client is None or not offered_here(request):
        return None
    return spec, client


@router.get("/api/auth/providers")
def list_providers(request: Request) -> list[dict[str, str]]:
    """The providers this browser may log in with; open to all, as the login page asks before anyone logs in."""
    return [{"id": spec.id, "title": spec.title} for spec in providers(request).values() if _usable(request, spec.id)]


def _back(mode: str, code: str, *, extra: dict[str, str] | None = None) -> RedirectResponse:
    page = PAGES[mode]
    query = urlencode({"oidc": code, **(extra or {})})
    return RedirectResponse(f"{page}{'&' if '?' in page else '?'}{query}", status_code=303)


def _ended(response: Response) -> Response:
    response.delete_cookie(oidc.FLOW_COOKIE, path="/api/auth", httponly=True, samesite="lax")
    return response


@router.get("/api/auth/{provider}/start")
async def start(
    request: Request,
    provider: str,
    mode: Annotated[str, Query()] = "login",
    next: Annotated[str, Query(max_length=NEXT_MAX)] = "/",
    username: Annotated[str, Query(max_length=64)] = "",
    display_name: Annotated[str, Query(max_length=NAME_LENGTH)] = "",
    note: Annotated[str, Query(max_length=accounts.NOTE_MAX)] = "",
    language: Annotated[str, Query(max_length=3)] = "en",
    ticket_value: Annotated[str, Query(alias="ticket", max_length=1024)] = "",
) -> Response:
    """Send the browser to the provider, the flow sealed in its cookie; back to Delve's page with a code when it
    can't start."""
    if mode not in MODES:
        raise HTTPException(status_code=422, detail=f"The mode is one of {', '.join(MODES)}.")
    if request.headers.get("sec-fetch-site", "same-origin") not in ("same-origin", "none"):
        return _back(mode, "elsewhere")  # another site sent the browser here: nobody here asked for it
    usable = _usable(request, provider)
    if usable is None:
        return _back(mode, "not-offered")
    spec, client = usable
    flow: dict[str, str] = {"provider": provider, "mode": mode, "next": next if LOCAL_PATH.match(next) else "/"}
    if mode == "link":
        account = _account_logged_in(request)
        if account is None:
            return _back("login", "not-logged-in")
        ticket = oidc.unseal(request.app.state.device_secret, ticket_value)
        if ticket is None or ticket.get("purpose") != "link" or ticket.get("account") != account.id:
            return _back(mode, "expired")
        flow["account"] = account.id
    if mode == "signup":
        if not sign_up.is_open(request):
            return _back(mode, "closed")
        language = language.strip().lower() or "en"
        try:
            accounts.username_of(username)
        except PlayError:
            return _back(mode, "invalid")
        if not LANGUAGE.fullmatch(language):
            return _back(mode, "invalid")
        if request.app.state.storage.accounts.by_username(accounts.username_of(username)) is not None:
            return _back(mode, "taken")
        flow |= {"username": username, "display_name": display_name, "note": note, "language": language}
    verifier, challenge = oidc.pkce_pair()
    state, nonce = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    redirect = callback_uri(request, provider)
    try:
        url = await oidc_client(request).authorize_url(spec, client, redirect, state, nonce, challenge)
    except oidc.OidcFailed as failed:
        log.warning("%s login can't start: %s", provider, failed)
        return _back(mode, "failed")
    flow |= {"state": state, "nonce": nonce, "verifier": verifier, "redirect": redirect}
    response = RedirectResponse(url, status_code=303)
    response.set_cookie(
        oidc.FLOW_COOKIE,
        oidc.seal(request.app.state.device_secret, flow),
        max_age=oidc.FLOW_MINUTES * 60,
        path="/api/auth",
        httponly=True,
        samesite="lax",
        secure=guard.came_over_https(request),
    )
    return response


@router.get("/api/auth/{provider}/callback")
async def callback(
    request: Request,
    provider: str,
    code: Annotated[str, Query(max_length=2048)] = "",
    state: Annotated[str, Query(max_length=256)] = "",
    error: Annotated[str, Query(max_length=256)] = "",
) -> Response:
    """Back from the provider: the flow checked, and the browser sent to Delve's page (`mode`'s), logged in when it
    logged in."""
    flow = oidc.unseal(request.app.state.device_secret, flow_cookie(request, oidc.FLOW_COOKIE))
    if flow is None or flow.get("provider") != provider or not secrets.compare_digest(str(flow.get("state")), state):
        return _ended(_back("login", "expired"))
    mode = flow["mode"]
    if error or not code:
        return _ended(_back(mode, "cancelled"))
    usable = _usable(request, provider)
    if usable is None:
        return _ended(_back(mode, "not-offered"))
    spec, client = usable
    try:
        claims = await oidc_client(request).claims(
            spec, client, code, flow["redirect"], flow["verifier"], flow["nonce"]
        )
    except oidc.OidcFailed as failed:
        log.warning("%s login failed: %s", provider, failed)
        return _ended(_back(mode, "failed"))
    if mode == "link":
        return _ended(_linked(request, flow, claims))
    if mode == "signup":
        return _ended(_signed_up(request, flow, claims))
    return _ended(_logged_in(request, flow, claims))


def _logged_in(request: Request, flow: dict, claims: identities.Claims) -> Response:
    mode = flow["mode"]
    try:
        account = identities.log_in(request.app.state.storage, claims)
    except identities.UnknownIdentity:
        return _back(mode, "unknown")
    except accounts.AccountPending:
        return _back(mode, "pending")
    except PlayError:
        return _back(mode, "disabled")
    return log_in_on(request, account, RedirectResponse(flow["next"], status_code=303))


def _account_logged_in(request: Request) -> Account | None:
    """The account the browser is logged in to; None for none (the owner token and this machine have none)."""
    try:
        return current_principal(request).account
    except HTTPException:
        return None


def _linked(request: Request, flow: dict, claims: identities.Claims) -> Response:
    account = _account_logged_in(request)
    if account is None or account.id != flow.get("account"):
        return _back("link", "expired")
    try:
        identities.link(request.app.state.storage, account.id, claims, request.app.state.clock.now())
    except identities.IdentityConflict as conflict:
        return _back("link", "has-one" if conflict.message == identities.HAS_ONE else "conflict")
    return _back("link", "linked")


def _signed_up(request: Request, flow: dict, claims: identities.Claims) -> Response:
    storage = request.app.state.storage
    if storage.account_identities.get(claims.provider, claims.subject) is not None:
        return _logged_in(request, {**flow, "mode": "login"}, claims)
    if not sign_up.is_open(request):
        return _back("signup", "closed")
    try:
        sign_up.throttle(request).take(guard.client_address(request))
    except HTTPException:
        return _back("signup", "busy")
    try:
        account = identities.sign_up(
            storage,
            claims,
            flow["username"],
            request.app.state.clock.now(),
            display_name=flow.get("display_name") or None,
            language=flow.get("language", "en"),
            note=flow.get("note", ""),
        )
    except accounts.AccountConflict:
        return _back("signup", "taken")
    except accounts.SignUpsFull:
        return _back("signup", "busy")
    except identities.IdentityConflict:
        return _back("signup", "conflict")
    except PlayError:
        return _back("signup", "invalid")
    request.app.state.events.publish("accounts", {"id": account.id}, scope="organisers")
    return _back("signup", "waiting", extra={"username": account.username})


# ----- the account's identities -----


@router.post("/api/auth/{provider}/link")
def link_ticket(
    request: Request, principal: AccountCaller, provider: str, body: Annotated[dict[str, Any], Body()]
) -> dict[str, str]:
    """The start of linking an outside account to the account logged in: `{"url"}`, `start` with a ticket good for
    `oidc.FLOW_MINUTES`. An account with a password gives it (`{"password"}`), so a browser left logged in, or a stolen
    session, can't link another person's way in; it counts against the login throttle as a login does. 401 for a wrong
    password, 429 while the throttle waits."""
    account = principal.account
    if _usable(request, provider) is None:
        raise HTTPException(status_code=422, detail="Logging in with it isn't set up here.")
    if account.has_password:
        password = text_field(body, "password")
        if len(password) > PASSWORD_MAX:
            raise HTTPException(status_code=401, detail=WRONG_PASSWORD)
        limits, address = login_throttle(request), guard.client_address(request)
        at = limits.reserve(account.username, address)
        if accounts.authenticate(request.app.state.storage, account.username, password) is None:
            raise HTTPException(status_code=401, detail=WRONG_PASSWORD)
        limits.succeeded(account.username, address, at)
    ticket = oidc.seal(request.app.state.device_secret, {"purpose": "link", "account": account.id})
    return {"url": f"/api/auth/{provider}/start?{urlencode({'mode': 'link', 'ticket': ticket})}"}


@router.get("/api/account/identities")
def list_identities(request: Request, principal: AccountCaller) -> dict[str, Any]:
    """`{"identities", "has_password"}`: linking asks for the password of an account that has one."""
    specs = providers(request)
    linked = [
        {
            "provider": identity.provider,
            "title": specs[identity.provider].title if identity.provider in specs else identity.provider,
            "email": identity.email,
            "linked_at": identity.linked_at,
        }
        for identity in request.app.state.storage.account_identities.list(principal.account.id)
    ]
    return {"identities": linked, "has_password": principal.account.has_password}


@router.delete("/api/account/identities/{provider}", status_code=204)
def unlink_identity(request: Request, principal: AccountCaller, provider: str) -> Response:
    """Unlink it: 422 when the account has none of that provider, or when it is its only way to log in."""
    try:
        identities.unlink(request.app.state.storage, principal.account.id, provider)
    except PlayError as refused:
        raise HTTPException(status_code=422, detail=refused.message) from None
    return Response(status_code=204)
