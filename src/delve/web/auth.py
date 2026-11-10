"""Who is asking: the one place that decides it (spec §11), and the one module of the web that reads a request's
cookies. `app.state.identity` is a chain (players and tavern Task C2, `docs/identity.md`); the first identity that
knows the caller wins:

1. the owner token, as a bearer or in the `delve_token` cookie (plateau 0): the owner, except through a proxy on this
   machine (DEL-154, audit finding 9): a tunnel's visitor logs in with the owner account;
2. an account's login session, in the `delve_session` cookie (`delve.play.logins`): that account, the owner when it
   holds the owner's rights (the human's ruling of 2026-10-24);
3. a seat's token, in the `delve_seat` cookie (plateau 4, `delve.web.seats`): that seat;
4. this machine, not through a proxy on it (`guard.is_this_machine`), while there is no owner account: the owner.

A seat token comes before this machine, since a browser here that joined a table is that seat (a seat token only ever
gives less). An unknown session or seat token is nobody, except from this machine."""

from __future__ import annotations

import hashlib
import os
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Protocol

from fastapi import Depends, HTTPException, Request
from starlette.requests import HTTPConnection

from delve.config import Config, private_data_dir
from delve.domain.accounts import Account, LoginSession
from delve.domain.campaigns import Seat
from delve.play import logins
from delve.play.accounts import has_owner_account
from delve.play.clock import Clock
from delve.storage import Storage
from delve.web.guard import from_a_proxy_here, is_this_machine, lan_origins

TOKEN_COOKIE = "delve_token"
SEAT_COOKIE = "delve_seat"
SESSION_COOKIE = "delve_session"
DEVICE_COOKIE = "delve_device"
NEEDS_LOGIN = "Log in to go on."
OWNER_TOKEN_NOT_HERE = (
    "The owner token works only on this machine and its network: over the internet, log in with your owner account."
)


@dataclass(frozen=True)
class Principal:
    """`seat` is the seat whose token was presented, and `account` the account whose login session was (with
    `login_hash`, that session's token's SHA-256, for the event stream). The owner has neither here, and has a seat at
    every table instead (`delve.web.seats.table_seat`)."""

    id: str
    roles: frozenset[str]
    seat: Seat | None = None
    account: Account | None = None
    login_hash: str | None = None

    @property
    def owner(self) -> bool:
        """Whether this is the install's owner: the owner token, this machine, or an owner account."""
        return self.id == "owner" or (self.account is not None and self.account.owner)


OWNER = Principal(id="owner", roles=frozenset({"organiser"}), seat=None)


def seat_principal(seat: Seat) -> Principal:
    """`seat:<id>`, with the organiser role when the seat was granted it and hasn't left."""
    roles = frozenset({"organiser"}) if seat.organiser and seat.left_at is None else frozenset()
    return Principal(id=f"seat:{seat.id}", roles=roles, seat=seat)


def account_principal(account: Account, login: LoginSession, login_hash: str | None = None) -> Principal:
    """`account:<id>`, with the organiser role for an organiser or an owner account."""
    roles = frozenset({"organiser"}) if account.organiser or account.owner else frozenset()
    return Principal(id=f"account:{account.id}", roles=roles, account=account, login_hash=login_hash)


def session_token(request: HTTPConnection) -> str | None:
    """The login session's token the request presents, if any."""
    return request.cookies.get(SESSION_COOKIE) or None


def device_cookie(request: HTTPConnection) -> str | None:
    """The device cookie the request presents, if any (`delve.web.devices`)."""
    return request.cookies.get(DEVICE_COOKIE) or None


def flow_cookie(request: HTTPConnection, name: str) -> str | None:
    """An outside login's sealed flow cookie (`delve.web.oidc.FLOW_COOKIE`, DEL-206), if the request presents it."""
    return request.cookies.get(name) or None


def seat_token(request: HTTPConnection) -> str | None:
    """The seat's token the request presents, if any."""
    return request.cookies.get(SEAT_COOKIE) or None


class Identity(Protocol):
    def resolve(self, request: HTTPConnection) -> Principal | None:
        """The principal making `request` (an HTTP request or a WebSocket's handshake), or None when this identity
        doesn't know them."""
        ...


class OwnerTokenIdentity:
    """The install's owner presents the owner token: as a bearer, or in the `delve_token` cookie. Never through a proxy
    on this machine (`guard.from_a_proxy_here`, DEL-154, audit finding 9): the token never expires and opens
    everything, so it isn't taken from the internet, where the owner logs in with their owner account instead; on the
    LAN and this machine it works as ever.

    With `path`, the token follows that file: once the file changed (`new_token`, from `delve token --new` or the
    owner's Preferences), the next request is checked against the new token, and the old one is refused, without a
    restart. A file that is gone or empty keeps the token it had."""

    def __init__(self, token: str, path: Path | None = None) -> None:
        self._token = token
        self._path = path
        self._seen = _file_state(path) if path is not None else None

    def resolve(self, request: HTTPConnection) -> Principal | None:
        presented = presented_owner_token(request)
        if presented and secrets.compare_digest(presented.encode(), self.token().encode()):
            return None if from_a_proxy_here(request) else OWNER
        return None

    def token(self) -> str:
        """The owner token now: the file's, read again when it changed."""
        if self._path is None:
            return self._token
        state = _file_state(self._path)
        if state is not None and state != self._seen:
            try:
                text = self._path.read_text().strip()
            except OSError:
                return self._token
            if text:
                self._token, self._seen = text, state
        return self._token


def _file_state(path: Path) -> tuple[int, int, int] | None:
    """What tells that a file changed: its inode (`os.replace` makes a new one), its time and its size."""
    try:
        found = path.stat()
    except OSError:
        return None
    return found.st_ino, found.st_mtime_ns, found.st_size


def presented_owner_token(request: HTTPConnection) -> str | None:
    """The owner token the request presents, right or wrong: the bearer, else the `delve_token` cookie."""
    return _bearer(request.headers.get("authorization")) or request.cookies.get(TOKEN_COOKIE) or None


class AccountIdentity:
    """An account presents a live login session's token in the `delve_session` cookie (`logins.resolve`)."""

    def __init__(self, storage: Storage, clock: Clock) -> None:
        self._storage = storage
        self._clock = clock

    def resolve(self, request: HTTPConnection) -> Principal | None:
        token = session_token(request)
        found = logins.resolve(self._storage, token, self._clock.now()) if token else None
        if found is None:
            return None
        account, login = found
        return account_principal(account, login, hashlib.sha256(token.encode()).hexdigest())


class SeatTokenIdentity:
    """A person at a table presents their seat's token in the `delve_seat` cookie, which `seat_for_token` knows. An
    account's seat is never reached by a token: the account logs in (keeping a seat drops its token too)."""

    def __init__(self, seat_for_token: Callable[[str], Seat | None]) -> None:
        self._seat_for_token = seat_for_token

    def resolve(self, request: HTTPConnection) -> Principal | None:
        token = seat_token(request)
        seat = self._seat_for_token(token) if token else None
        return None if seat is None or seat.account_id is not None else seat_principal(seat)


class ThisMachineIdentity:
    """A browser on this machine, not through a proxy on it, is the owner, but only while there is no owner account
    (audit-auth finding 3): a proxy here that adds no headers looks like this machine. Once there is one, the owner
    logs in, or uses the owner token. No owner account is ever deleted, nor the last one demoted, so once there is
    one there always is."""

    def __init__(self, storage: Storage) -> None:
        self._storage = storage
        self._owner_account = False

    def resolve(self, request: HTTPConnection) -> Principal | None:
        if not is_this_machine(request) or self._has_owner_account():
            return None
        return OWNER

    def _has_owner_account(self) -> bool:
        self._owner_account = self._owner_account or has_owner_account(self._storage)
        return self._owner_account


class ChainedIdentity:
    """The first of `identities` that knows the caller."""

    def __init__(self, *identities: Identity) -> None:
        self._identities = identities

    def resolve(self, request: HTTPConnection) -> Principal | None:
        for identity in self._identities:
            principal = identity.resolve(request)
            if principal is not None:
                return principal
        return None


def _bearer(header: str | None) -> str | None:
    if header is None:
        return None
    scheme, _, credentials = header.partition(" ")
    return credentials.strip() if scheme.lower() == "bearer" else None


def load_or_create_token(config: Config) -> str:
    """The owner token from `config.token_path`; a new one (24 random bytes as hex, mode 0600) if there is none."""
    return load_or_create_secret(config.token_path, 24)


def new_token(config: Config) -> str:
    """A new owner token in `config.token_path` (mode 0600), the old one refused from then on (DEL-154, audit finding
    9): written beside it and moved over it, so a running Delve never reads half of it."""
    private_data_dir(config.data_dir)
    token = secrets.token_hex(24)
    part = config.token_path.with_name(f".{config.token_path.name}.{secrets.token_hex(4)}")
    fd = os.open(part, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w") as file:
            file.write(token + "\n")
        os.replace(part, config.token_path)
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    return token


def token_links(port: int, token: str) -> list[str]:
    """The links that open Delve with the owner token from another device on the LAN."""
    return [f"{origin}/#token={token}" for origin in lan_origins(port)]


def load_or_create_secret(path: Path, size: int) -> str:
    """The secret in `path`; a new one (`size` random bytes as hex, mode 0600) if there is none."""
    if path.exists():
        secret = path.read_text().strip()
        if secret:
            path.chmod(0o600)
            return secret
        path.unlink()
    private_data_dir(path.parent)
    secret = secrets.token_hex(size)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as file:
        file.write(secret + "\n")
    return secret


def identify(connection: HTTPConnection) -> Principal | None:
    """The caller of an HTTP request or a WebSocket's handshake (table voice and fixes Task V1.2), through the same
    identity chain; None for nobody."""
    return connection.app.state.identity.resolve(connection)


def current_principal(request: Request) -> Principal:
    """A dependency: the caller, or 401 when Delve doesn't know them; through a proxy on this machine, with the owner
    token, a 401 that says to log in with the owner account."""
    principal = identify(request)
    if principal is None:
        refused = presented_owner_token(request) and from_a_proxy_here(request)
        raise HTTPException(status_code=401, detail=OWNER_TOKEN_NOT_HERE if refused else NEEDS_LOGIN)
    return principal


def require(role: str):
    """A dependency that lets through only a principal with `role`: 401 for nobody, 403 for the wrong role."""

    def dependency(request: Request) -> Principal:
        principal = current_principal(request)
        if role not in principal.roles:
            raise HTTPException(status_code=403, detail=f"This needs the {role} role.")
        return principal

    return dependency


Organiser = Annotated[Principal, Depends(require("organiser"))]
"""The install's organiser rights: the owner, a seat that was granted them (spec §11), or an organiser or owner
account."""

ONLY_THE_OWNER = "Only the install's owner can do this."


def require_owner(request: Request) -> Principal:
    """A dependency that lets through only the install's owner (this machine, the owner token, or an owner account):
    401 for nobody, 403 for any seat or other account, an organiser's too."""
    principal = current_principal(request)
    if not principal.owner:
        raise HTTPException(status_code=403, detail=ONLY_THE_OWNER)
    return principal


Owner = Annotated[Principal, Depends(require_owner)]
"""The install's owner alone: what spends the owner's money or reaches their machine, such as Connections."""
