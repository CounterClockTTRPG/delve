"""Connections: the Replicate token and assetgen's URL and token (portraits plan Task 3), and Google's client for
logging in with Google (DEL-206). The owner's alone (`Owner`): an organiser seat gets 403, since a token spends the
owner's money, assetgen reaches their machine, and a login client decides who may log in.

A token comes in and goes into the data dir's files (`delve.images.connections`); it never comes back out. The
answers say only `set` or `unset`, a refused body is answered without echoing it (so the bodies are read raw, not
through a model whose 422 would quote them), and a Test answers its own words, never what the remote answered.

Saving or removing the Replicate token, or assetgen's URL, registers, replaces or unregisters its provider at once,
without a restart (assetgen's models are then read live); each change publishes `preferences`, so Preferences reloads
its backends.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Annotated, Any
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Body, HTTPException, Request

from delve.domain.accounts import Account
from delve.images import connections
from delve.images.assetgen import register_assetgen
from delve.images.connections import KEEP, Assetgen, CheckResult, Keep
from delve.mail import outbox
from delve.mail import settings as mail_settings
from delve.mail.compose import compose
from delve.play.seats import owner_account
from delve.web import oidc
from delve.web.auth import Owner
from delve.web.routes.oidc import redirect_uris
from delve.web.routes.preferences import current_preferences, preferences_json

router = APIRouter()

TESTS = ("replicate", "assetgen", "email")


@router.get("/api/connections")
def get_connections(request: Request, principal: Owner) -> dict:
    data_dir = request.app.state.config.data_dir
    return {
        "replicate": _replicate_json(data_dir),
        "assetgen": _assetgen_json(connections.load_assetgen(data_dir)),
        "google": _google_json(request),
        "email": _email_json(request),
    }


@router.put("/api/connections/google")
def put_google(request: Request, principal: Owner, raw: Annotated[Any, Body()] = None) -> dict:
    """`{"client_id", "client_secret"?}`: an absent secret keeps the stored one."""
    body = _object(raw, required={"client_id"}, optional={"client_secret"})
    try:
        oidc.save_client(request.app.state.config.data_dir, "google", body["client_id"], body.get("client_secret"))
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    return _google_json(request)


@router.delete("/api/connections/google")
def delete_google(request: Request, principal: Owner) -> dict:
    """Nobody logs in with Google from then on; identities linked already stay, for when it is set up again."""
    oidc.remove_client(request.app.state.config.data_dir, "google")
    return _google_json(request)


@router.put("/api/connections/replicate")
async def put_replicate(request: Request, principal: Owner, raw: Annotated[Any, Body()] = None) -> dict:
    body = _object(raw, required={"token"})
    data_dir = request.app.state.config.data_dir
    try:
        connections.save_replicate(data_dir, body["token"])
    except (TypeError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    await _register_replicate(request)
    return _replicate_json(data_dir)


@router.delete("/api/connections/replicate")
async def delete_replicate(request: Request, principal: Owner) -> dict:
    """Remove the file; Replicate stays registered while `REPLICATE_API_TOKEN` holds a token."""
    data_dir = request.app.state.config.data_dir
    connections.remove_replicate(data_dir)
    await _register_replicate(request)
    return _replicate_json(data_dir)


@router.put("/api/connections/assetgen")
async def put_assetgen(request: Request, principal: Owner, raw: Annotated[Any, Body()] = None) -> dict:
    """`{"url", "token"?}`: an absent token keeps the stored one, `null` removes it."""
    body = _object(raw, required={"url"}, optional={"token"})
    token: str | None | Keep = body.get("token", KEEP)
    try:
        stored = connections.save_assetgen(request.app.state.config.data_dir, body["url"], token)
    except (connections.ConnectionError, TypeError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    await _register_assetgen(request)
    return _assetgen_json(stored)


@router.delete("/api/connections/assetgen")
async def delete_assetgen(request: Request, principal: Owner) -> dict:
    connections.remove_assetgen(request.app.state.config.data_dir)
    await _register_assetgen(request)
    return _assetgen_json(None)


@router.put("/api/connections/email")
def put_email(request: Request, principal: Owner, raw: Annotated[Any, Body()] = None) -> dict:
    """`{"provider", "sender"?, "public_url"?, "key"?}`: an absent field keeps what is stored."""
    body = _object(raw, required={"provider"}, optional={"sender", "public_url", "key"})
    data_dir = request.app.state.config.data_dir
    stored = mail_settings.load(data_dir)
    provider = body["provider"]
    if provider not in mail_settings.PROVIDERS:
        raise HTTPException(status_code=422, detail="The provider is log or emailit.")
    sender = _sender(body["sender"]) if "sender" in body else stored.sender
    public_url = _public_url(body["public_url"]) if "public_url" in body else stored.public_url
    if "key" in body:
        try:
            mail_settings.save_key(data_dir, body["key"])
        except (TypeError, ValueError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from None
    mail_settings.save(data_dir, mail_settings.MailSettings(provider=provider, sender=sender, public_url=public_url))
    return _email_json(request)


@router.delete("/api/connections/email")
def delete_email(request: Request, principal: Owner) -> dict:
    """Back to the log provider, and the saved key removed; the sender and public URL stay for next time."""
    data_dir = request.app.state.config.data_dir
    stored = mail_settings.load(data_dir)
    mail_settings.save(data_dir, mail_settings.MailSettings("log", stored.sender, stored.public_url))
    mail_settings.remove_key(data_dir)
    return _email_json(request)


@router.post("/api/connections/{name}/test")
async def check_connection(request: Request, principal: Owner, name: str) -> dict:
    """Replicate's account endpoint, or assetgen's `GET /api/models`: `{"ok", "message"}`."""
    if name not in TESTS:
        raise HTTPException(status_code=404, detail="unknown connection")
    data_dir = request.app.state.config.data_dir
    if name == "email":
        return _test_email(request, principal.account)
    async with httpx.AsyncClient(transport=getattr(request.app.state, "connections_transport", None)) as client:
        if name == "replicate":
            result: CheckResult = await connections.check_replicate(data_dir, client)
        else:
            result = await connections.check_assetgen(data_dir, client)
    return {"ok": result.ok, "message": result.message}


def _object(raw: Any, *, required: set[str], optional: frozenset[str] | set[str] = frozenset()) -> dict[str, Any]:
    """The body as an object with `required` and maybe `optional` keys; 422 naming no value otherwise."""
    if not isinstance(raw, dict):
        raise HTTPException(status_code=422, detail="Send a JSON object.")
    missing = sorted(required - raw.keys())
    unknown = sorted(raw.keys() - required - set(optional))
    if missing:
        raise HTTPException(status_code=422, detail=f"Missing: {', '.join(missing)}.")
    if unknown:
        raise HTTPException(status_code=422, detail="Unknown fields in the body.")
    return raw


async def _register_replicate(request: Request) -> None:
    app = request.app
    dropped = connections.register_replicate(app.state.registries.images, app.state.config.data_dir)
    await _close(dropped)
    _changed(request)


async def _register_assetgen(request: Request) -> None:
    """Register assetgen from its saved file, replacing it, or drop it once the file is gone."""
    app = request.app
    transport = getattr(app.state, "connections_transport", None)
    await _close(register_assetgen(app.state.registries, app.state.config, transport=transport))
    _changed(request)


async def _close(dropped: object | None) -> None:
    """Close what a replaced or dropped provider had built (its HTTP client)."""
    aclose = getattr(dropped, "aclose", None)
    if aclose is not None:
        await aclose()


def _changed(request: Request) -> None:
    request.app.state.events.publish("preferences", preferences_json(current_preferences(request.app)))


def _replicate_json(data_dir) -> dict[str, str]:
    return {"state": connections.replicate_state(data_dir)}


def _google_json(request: Request) -> dict[str, Any]:
    """The client id (not secret: Google shows it to every browser it sends back), whether a secret is set, and the
    redirect URIs the owner registers with Google."""
    client = oidc.load_client(request.app.state.config.data_dir, "google")
    return {
        "client_id": client.client_id if client else None,
        "secret": "set" if client else "unset",
        "redirect_uris": redirect_uris(request, "google"),
    }


def _assetgen_json(stored: Assetgen | None) -> dict[str, Any]:
    if stored is None:
        return {"url": None, "token": "unset"}
    return {"url": stored.url, "token": "set" if stored.token else "unset"}


SENDER = re.compile(r"^(?:(?P<name>[^<>\"\r\n]*?)\s*<(?P<angle>[^<>\s@,;\"]+@[^<>\s@,;\"]+)>|(?P<bare>[^<>\s@,;\"]+@[^<>\s@,;\"]+))$")
FAILURES_SHOWN = 5


def _sender(value: Any) -> str:
    """`Name <addr>` or `addr`, or empty for none; 422 otherwise, quoting nothing."""
    if not isinstance(value, str) or (value.strip() and not SENDER.match(value.strip())):
        raise HTTPException(status_code=422, detail="The sender is a name and an address, Name <address>, or an address.")
    return value.strip()


def _public_url(value: Any) -> str:
    """An http(s) address with a host, without its trailing slash; empty for none."""
    if not isinstance(value, str):
        raise HTTPException(status_code=422, detail="The public address is an http or https address.")
    value = value.strip().rstrip("/")
    if value:
        try:
            parts = urlsplit(value)
            host = parts.hostname
        except ValueError:
            host = None
        if parts.scheme not in ("http", "https") or not host or any(char.isspace() for char in value):
            raise HTTPException(status_code=422, detail="The public address is an http or https address.")
    return value


def _email_json(request: Request) -> dict[str, Any]:
    """Never an address: the provider, the sender (the install's own), the public URL, whether a key is set, today's
    count, how many wait in the outbox (neither sent nor failed) and the latest failures (their kind, time and reason;
    not the dropped ones, which nobody should have got)."""
    data_dir = request.app.state.config.data_dir
    mail = request.app.state.storage.mail
    stored = mail_settings.load(data_dir)
    today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    return {
        "provider": stored.provider,
        "sender": stored.sender,
        "public_url": stored.public_url,
        "public_url_default": mail_settings.default_public_url(),
        "key": mail_settings.key_state(data_dir),
        "sent_today": mail.sent_since(outbox.iso(today)),
        "waiting": mail.waiting(),
        "failures": [
            {"kind": m.kind, "at": m.failed_at, "failure": m.failure}
            for m in mail.recent_failures(FAILURES_SHOWN, dropped=False)
        ],
    }


def _test_email(request: Request, account: Account | None) -> dict[str, Any]:
    """Queue a test email to the caller's confirmed address (the owner account's for the owner token)."""
    storage = request.app.state.storage
    data_dir = request.app.state.config.data_dir
    account = account or owner_account(storage)
    if account is None or outbox.address_for(account, "test") is None:
        return {"ok": False, "message": "Add and confirm your own address in Preferences first."}
    if mail_settings.load(data_dir).provider != "log" and not mail_settings.mail_enabled(data_dir):
        return {"ok": False, "message": "Choose Emailit and set its key, the sender and the public address first."}
    mail = compose(
        "test",
        account.profile.language,
        {"name": account.profile.display_name},
        link=mail_settings.public_url(data_dir),
        off_link=None,
    )
    outbox.queue(storage, account, "test", mail, datetime.now(UTC))
    return {"ok": True, "message": "A test email is on its way to your confirmed address."}
