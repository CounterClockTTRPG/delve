"""A fake OpenID Connect provider (DEL-206) over `httpx.MockTransport`: its discovery document, its keys and its token
endpoint, which checks the code, the redirect URI, the client's secret and the PKCE verifier as Google's does, and
answers an ID token signed with its own RSA key. A test sets who logs in (`next_login`) and can spoil the token."""

from __future__ import annotations

import base64
import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

from delve.web.oidc import ClientConfig, OidcClient, ProviderSpec

ISSUER = "https://idp.example"
SPEC = ProviderSpec("google", "Google", ISSUER, frozenset({ISSUER}))
CLIENT = ClientConfig("delve-client", "s3cret-XYZZY")


def new_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def public_jwk(key: rsa.RSAPrivateKey, kid: str) -> dict[str, Any]:
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    return {**jwk, "kid": kid, "use": "sig", "alg": "RS256"}


@dataclass
class FakeProvider:
    key: rsa.RSAPrivateKey = field(default_factory=new_key)
    kid: str = "key-1"
    published: list[dict[str, Any]] = field(default_factory=list)
    codes: dict[str, dict[str, Any]] = field(default_factory=dict)
    claims: dict[str, Any] = field(default_factory=dict)
    requests: list[httpx.Request] = field(default_factory=list)
    token_status: int = 200

    def __post_init__(self) -> None:
        if not self.published:
            self.published = [public_jwk(self.key, self.kid)]

    def id_token(self, login_nonce: str, **overrides: Any) -> str:
        now = int(time.time())
        claims = {
            "iss": ISSUER,
            "aud": CLIENT.client_id,
            "sub": "1083",
            "email": "ana@example.org",
            "email_verified": True,
            "name": "Ana Lind",
            "iat": now,
            "exp": now + 3600,
            "nonce": login_nonce,
            **self.claims,
            **overrides,
        }
        claims = {name: value for name, value in claims.items() if value is not None}
        return jwt.encode(claims, self.key, algorithm="RS256", headers={"kid": self.kid})

    def give_code(self, code: str, *, redirect_uri: str, challenge: str, nonce: str) -> None:
        """What the provider would remember when it sends the browser back with `code`."""
        self.codes[code] = {"redirect_uri": redirect_uri, "challenge": challenge, "nonce": nonce}

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path == "/.well-known/openid-configuration":
            return httpx.Response(
                200,
                json={
                    "issuer": ISSUER,
                    "authorization_endpoint": f"{ISSUER}/authorize",
                    "token_endpoint": f"{ISSUER}/token",
                    "jwks_uri": f"{ISSUER}/keys",
                },
            )
        if path == "/keys":
            return httpx.Response(200, json={"keys": self.published})
        if path == "/token":
            form = {name: values[0] for name, values in parse_qs(request.content.decode()).items()}
            given = self.codes.pop(form.get("code", ""), None)
            if self.token_status != 200 or given is None:
                return httpx.Response(
                    self.token_status if self.token_status != 200 else 400, json={"error": "invalid_grant"}
                )
            challenge = base64.urlsafe_b64encode(hashlib.sha256(form["code_verifier"].encode()).digest()).rstrip(b"=")
            if (
                form.get("client_id") != CLIENT.client_id
                or form.get("client_secret") != CLIENT.client_secret
                or form.get("redirect_uri") != given["redirect_uri"]
                or challenge.decode() != given["challenge"]
            ):
                return httpx.Response(400, json={"error": "invalid_grant"})
            return httpx.Response(200, json={"id_token": self.id_token(given["nonce"]), "token_type": "Bearer"})
        return httpx.Response(404)

    def client(self) -> OidcClient:
        return OidcClient(httpx.AsyncClient(transport=httpx.MockTransport(self.handler)))
