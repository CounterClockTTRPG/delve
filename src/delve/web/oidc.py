"""OpenID Connect for logging in with an outside account (DEL-206): Google first, through its discovery document, so
another provider is its `ProviderSpec` and the owner's client.

The flow is the authorization code flow with PKCE (`S256`), a `state` and a `nonce`, all three random and kept in the
browser's `delve_oidc` cookie, sealed (`seal`, an HMAC under a key of its own derived from the device secret) and
good for `FLOW_MINUTES`. The ID token the code is exchanged for is checked here: its signature against the
provider's published keys (`jwks_uri`, fetched again for a key id it doesn't have), RS256 only, its issuer, its
audience (the owner's client id), its expiry and issue time, and the nonce. Its `email` is taken only when the
provider says it checked it (`email_verified`), and only to show.

The owner's client, its id and secret, is a file under the data dir at mode 0600 (`oidc-<provider>.json`,
`delve.images.connections.write_secret`), as the Replicate token is; the secret is never answered, logged or put in
an error. The provider's endpoints must be https; nothing a browser sends picks a URL Delve fetches.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlsplit

import httpx
import jwt

from delve.images.connections import write_secret
from delve.play.identities import Claims

SCOPE = "openid email profile"
FLOW_COOKIE = "delve_oidc"
FLOW_MINUTES = 10
CACHE_S = 60 * 60
LEEWAY_S = 60
TIMEOUT_S = 10.0
ALGORITHMS = ("RS256",)


@dataclass(frozen=True)
class ProviderSpec:
    """An OpenID Connect provider: its id in Delve, its name, its issuer (whose discovery document Delve reads), and
    the issuers its ID tokens may name."""

    id: str
    title: str
    issuer: str
    issuers: frozenset[str]


GOOGLE = ProviderSpec(
    "google", "Google", "https://accounts.google.com", frozenset({"https://accounts.google.com", "accounts.google.com"})
)
PROVIDERS: dict[str, ProviderSpec] = {GOOGLE.id: GOOGLE}


@dataclass(frozen=True)
class ClientConfig:
    """The owner's client at the provider: its id and secret (never in a repr)."""

    client_id: str
    client_secret: str = field(repr=False)


class OidcFailed(Exception):
    """The provider's answer won't do: unreachable, refused, or an ID token that doesn't check. The message names no
    secret and no token."""


# --- the owner's client ------------------------------------------------------------------------------------------


def client_path(data_dir: Path, provider: str) -> Path:
    return data_dir / f"oidc-{provider}.json"


def load_client(data_dir: Path, provider: str) -> ClientConfig | None:
    try:
        raw = json.loads(client_path(data_dir, provider).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    client_id, client_secret = raw.get("client_id"), raw.get("client_secret")
    if not isinstance(client_id, str) or not isinstance(client_secret, str) or not client_id or not client_secret:
        return None
    return ClientConfig(client_id, client_secret)


def save_client(data_dir: Path, provider: str, client_id: str, client_secret: str | None) -> ClientConfig:
    """Store the client; a `client_secret` of None keeps the stored one. `ValueError` (naming no secret) for a value
    that isn't one word, or no secret at all."""
    client_id = _word(client_id, "client id")
    if client_secret is None:
        stored = load_client(data_dir, provider)
        if stored is None:
            raise ValueError("Give the client secret too.")
        client_secret = stored.client_secret
    client_secret = _word(client_secret, "client secret")
    write_secret(client_path(data_dir, provider), json.dumps({"client_id": client_id, "client_secret": client_secret}))
    return ClientConfig(client_id, client_secret)


def remove_client(data_dir: Path, provider: str) -> None:
    client_path(data_dir, provider).unlink(missing_ok=True)


def _word(value: Any, what: str) -> str:
    value = value.strip() if isinstance(value, str) else ""
    if not value or len(value) > 512 or not value.isprintable() or any(char.isspace() for char in value):
        raise ValueError(f"The {what} is one word, without spaces or line breaks.")
    return value


# --- PKCE and the flow cookie ----------------------------------------------------------------------------------


def pkce_pair() -> tuple[str, str]:
    """A PKCE verifier and its S256 challenge."""
    verifier = secrets.token_urlsafe(48)
    return verifier, _b64(hashlib.sha256(verifier.encode()).digest())


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _flow_key(device_secret: str) -> bytes:
    return hmac.new(device_secret.encode(), b"delve oidc flow cookie", hashlib.sha256).digest()


def seal(device_secret: str, flow: Mapping[str, Any], now: float | None = None) -> str:
    """The flow as the cookie's value: its JSON with an expiry, and an HMAC over it."""
    now = time.time() if now is None else now
    body = _b64(json.dumps({**flow, "exp": int(now) + FLOW_MINUTES * 60}, separators=(",", ":")).encode())
    mac = _b64(hmac.new(_flow_key(device_secret), body.encode(), hashlib.sha256).digest())
    return f"{body}.{mac}"


def unseal(device_secret: str, value: str | None, now: float | None = None) -> dict[str, Any] | None:
    """The flow the cookie holds; None for none, one tampered with, or one past its expiry."""
    if not value or value.count(".") != 1:
        return None
    body, mac = value.split(".")
    want = _b64(hmac.new(_flow_key(device_secret), body.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(mac, want):
        return None
    try:
        flow = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    except ValueError:
        return None
    now = time.time() if now is None else now
    if not isinstance(flow, dict) or not isinstance(flow.get("exp"), int) or flow["exp"] < now:
        return None
    return flow


# --- the provider ------------------------------------------------------------------------------------------------


class OidcClient:
    """The provider's discovery document and keys, each fetched once an hour (the keys again for a key id they
    lack), and the calls of the flow. `client` is the app's `httpx.AsyncClient`; tests give one over a mock."""

    def __init__(self, client: httpx.AsyncClient, clock=time.monotonic) -> None:
        self._client = client
        self._clock = clock
        self._discovery: dict[str, tuple[float, dict[str, Any]]] = {}
        self._keys: dict[str, tuple[float, list[dict[str, Any]]]] = {}

    async def aclose(self) -> None:
        await self._client.aclose()

    async def discovery(self, spec: ProviderSpec) -> dict[str, Any]:
        cached = self._discovery.get(spec.id)
        if cached is not None and self._clock() - cached[0] < CACHE_S:
            return cached[1]
        document = await self._get_json(f"{spec.issuer}/.well-known/openid-configuration")
        for name in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
            if not _https(document.get(name)):
                raise OidcFailed(f"{spec.title}'s discovery document has no https {name}.")
        if document.get("issuer") not in spec.issuers:
            raise OidcFailed(f"{spec.title}'s discovery document names another issuer.")
        self._discovery[spec.id] = (self._clock(), document)
        return document

    async def authorize_url(
        self, spec: ProviderSpec, client: ClientConfig, redirect_uri: str, state: str, nonce: str, challenge: str
    ) -> str:
        document = await self.discovery(spec)
        query = {
            "response_type": "code",
            "client_id": client.client_id,
            "redirect_uri": redirect_uri,
            "scope": SCOPE,
            "state": state,
            "nonce": nonce,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "prompt": "select_account",
        }
        return f"{document['authorization_endpoint']}?{urlencode(query)}"

    async def claims(
        self, spec: ProviderSpec, client: ClientConfig, code: str, redirect_uri: str, verifier: str, nonce: str
    ) -> Claims:
        """The code exchanged for an ID token, the token checked: what the provider vouched for."""
        document = await self.discovery(spec)
        form = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": client.client_id,
            "client_secret": client.client_secret,
            "code_verifier": verifier,
        }
        try:
            response = await self._client.post(document["token_endpoint"], data=form, timeout=TIMEOUT_S)
        except httpx.HTTPError as error:
            raise OidcFailed(f"{spec.title} can't be reached: {type(error).__name__}") from None
        if response.status_code != 200:
            raise OidcFailed(f"{spec.title} refused the login: HTTP {response.status_code}")
        try:
            token = response.json().get("id_token")
        except ValueError:
            token = None
        if not isinstance(token, str):
            raise OidcFailed(f"{spec.title} answered no ID token.")
        return await self.check(spec, client, token, nonce)

    async def check(self, spec: ProviderSpec, client: ClientConfig, token: str, nonce: str) -> Claims:
        """The ID token's claims, once its signature, issuer, audience, times and nonce check."""
        try:
            header = jwt.get_unverified_header(token)
        except jwt.InvalidTokenError:
            raise OidcFailed("The ID token doesn't read.") from None
        if header.get("alg") not in ALGORITHMS:
            raise OidcFailed("The ID token isn't signed as Delve takes it.")
        key = await self._key(spec, header.get("kid"))
        try:
            claims = jwt.decode(
                token,
                key,
                algorithms=list(ALGORITHMS),
                audience=client.client_id,
                issuer=sorted(spec.issuers),
                leeway=LEEWAY_S,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
        except jwt.InvalidTokenError as error:
            raise OidcFailed(f"The ID token doesn't check: {type(error).__name__}") from None
        if not isinstance(claims.get("nonce"), str) or not hmac.compare_digest(claims["nonce"], nonce):
            raise OidcFailed("The ID token isn't this login's.")
        # A token for several audiences must say it was issued to this client (`azp`); one that names a party says it.
        several = isinstance(claims.get("aud"), list) and len(claims["aud"]) > 1
        if claims.get("azp", client.client_id if not several else None) != client.client_id:
            raise OidcFailed("The ID token was issued to another client.")
        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject or len(subject) > 255:
            raise OidcFailed("The ID token names no account.")
        email = claims.get("email") if claims.get("email_verified") is True else ""
        name = claims.get("name") if isinstance(claims.get("name"), str) else ""
        return Claims(spec.id, subject, email if isinstance(email, str) else "", name[:100])

    async def _key(self, spec: ProviderSpec, kid: Any) -> Any:
        for fresh in (False, True):
            for jwk in await self._jwks(spec, fresh):
                if jwk.get("kid") == kid and jwk.get("kty") == "RSA":
                    try:
                        return jwt.PyJWK(jwk, algorithm="RS256").key
                    except jwt.PyJWKError:
                        break
        raise OidcFailed(f"The ID token is signed with a key {spec.title} doesn't publish.")

    async def _jwks(self, spec: ProviderSpec, fresh: bool) -> list[dict[str, Any]]:
        cached = self._keys.get(spec.id)
        if cached is not None and not fresh and self._clock() - cached[0] < CACHE_S:
            return cached[1]
        document = await self.discovery(spec)
        keys = (await self._get_json(document["jwks_uri"])).get("keys")
        if not isinstance(keys, list):
            raise OidcFailed(f"{spec.title} publishes no keys.")
        keys = [key for key in keys if isinstance(key, dict)]
        self._keys[spec.id] = (self._clock(), keys)
        return keys

    async def _get_json(self, url: str) -> dict[str, Any]:
        try:
            response = await self._client.get(url, timeout=TIMEOUT_S)
        except httpx.HTTPError as error:
            raise OidcFailed(f"{urlsplit(url).hostname} can't be reached: {type(error).__name__}") from None
        if response.status_code != 200:
            raise OidcFailed(f"{urlsplit(url).hostname} answered HTTP {response.status_code}.")
        try:
            answer = response.json()
        except ValueError:
            raise OidcFailed(f"{urlsplit(url).hostname} answered something other than JSON.") from None
        if not isinstance(answer, dict):
            raise OidcFailed(f"{urlsplit(url).hostname} answered something other than JSON.")
        return answer


def _https(url: Any) -> bool:
    return isinstance(url, str) and urlsplit(url).scheme == "https" and bool(urlsplit(url).hostname)
