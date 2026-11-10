"""OpenID Connect (DEL-206): the flow cookie, the ID token's checks, and the owner's client file; over a fake
provider (`tests.fixtures.oidc`)."""

import asyncio
import os
import time

import pytest

from delve.play.identities import Claims
from delve.web import oidc
from delve.web.oidc import OidcFailed, pkce_pair, seal, unseal
from tests.fixtures.oidc import CLIENT, ISSUER, SPEC, FakeProvider, new_key, public_jwk

SECRET = "ab" * 32
REDIRECT = "https://delve.example/api/auth/google/callback"


def run(coroutine):
    return asyncio.run(coroutine)


def login(provider: FakeProvider, nonce: str = "n-1", code: str = "code-1") -> Claims:
    verifier, challenge = pkce_pair()
    provider.give_code(code, redirect_uri=REDIRECT, challenge=challenge, nonce=nonce)
    return run(provider.client().claims(SPEC, CLIENT, code, REDIRECT, verifier, nonce))


def check(provider: FakeProvider, token: str, nonce: str = "n-1") -> Claims:
    return run(provider.client().check(SPEC, CLIENT, token, nonce))


# ----- the flow cookie -----


def test_a_sealed_flow_unseals_until_it_expires_and_never_when_touched():
    now = time.time()
    value = seal(SECRET, {"state": "s", "mode": "login"}, now)
    assert unseal(SECRET, value, now) == {"state": "s", "mode": "login", "exp": int(now) + 600}
    assert unseal(SECRET, value, now + 601) is None, "past its ten minutes"
    assert unseal("cd" * 32, value, now) is None, "another install's key"
    body, mac = value.split(".")
    assert unseal(SECRET, f"{body}x.{mac}", now) is None
    assert unseal(SECRET, f"{body}.{mac[:-2]}AA", now) is None
    assert unseal(SECRET, None) is None and unseal(SECRET, "") is None and unseal(SECRET, "no-dot") is None


def test_the_pkce_challenge_is_the_verifier_s_s256():
    verifier, challenge = pkce_pair()
    assert len(verifier) >= 43 and "=" not in challenge and challenge != verifier
    assert pkce_pair()[0] != verifier


# ----- the ID token -----


def test_a_login_s_claims():
    provider = FakeProvider()
    assert login(provider) == Claims("google", "1083", "ana@example.org", "Ana Lind")
    (token,) = [request for request in provider.requests if request.url.path == "/token"]
    assert b"s3cret-XYZZY" in token.content, "the secret goes to the provider's token endpoint"
    assert all(b"s3cret" not in r.content and "s3cret" not in str(r.url) for r in provider.requests if r is not token)


def test_an_email_the_provider_didn_t_check_isn_t_taken():
    provider = FakeProvider(claims={"email_verified": False})
    assert login(provider).email == ""
    assert login(FakeProvider(claims={"email_verified": None}), code="c2").email == ""


@pytest.mark.parametrize(
    ("overrides", "why"),
    [
        ({"aud": "someone-else"}, "InvalidAudience"),
        ({"iss": "https://evil.example"}, "InvalidIssuer"),
        ({"exp": int(time.time()) - 3600}, "ExpiredSignature"),
        ({"exp": None}, "MissingRequiredClaim"),
        ({"sub": None}, "MissingRequiredClaim"),
        ({"nonce": "another"}, "isn't this login's"),
        ({"nonce": None}, "isn't this login's"),
    ],
)
def test_an_id_token_that_doesn_t_check_is_refused(overrides, why):
    provider = FakeProvider()
    with pytest.raises(OidcFailed, match=why):
        check(provider, provider.id_token("n-1", **overrides))


def test_a_token_signed_by_another_key_or_unsigned_is_refused():
    provider = FakeProvider()
    impostor = FakeProvider()  # the same key id, another key
    with pytest.raises(OidcFailed, match="InvalidSignature"):
        check(provider, impostor.id_token("n-1"))
    unsigned = provider.id_token("n-1").rsplit(".", 1)[0] + "."
    with pytest.raises(OidcFailed):
        check(provider, unsigned)
    with pytest.raises(OidcFailed, match="doesn't read"):
        check(provider, "not a token")


def test_a_new_signing_key_is_fetched_once_it_is_used():
    provider = FakeProvider()
    client = provider.client()
    run(client.check(SPEC, CLIENT, provider.id_token("n-1"), "n-1"))
    rotated = new_key()
    provider.key, provider.kid = rotated, "key-2"
    provider.published = [public_jwk(rotated, "key-2")]
    assert run(client.check(SPEC, CLIENT, provider.id_token("n-1"), "n-1")).subject == "1083"
    assert [r.url.path for r in provider.requests].count("/keys") == 2
    provider.kid = "key-3"
    with pytest.raises(OidcFailed, match="doesn't publish"):
        run(client.check(SPEC, CLIENT, provider.id_token("n-1"), "n-1"))


def test_a_refused_code_or_a_wrong_verifier_is_refused():
    provider = FakeProvider()
    verifier, challenge = pkce_pair()
    provider.give_code("code-1", redirect_uri=REDIRECT, challenge=challenge, nonce="n-1")
    with pytest.raises(OidcFailed, match="HTTP 400") as refused:
        run(provider.client().claims(SPEC, CLIENT, "code-1", REDIRECT, pkce_pair()[0], "n-1"))
    assert "s3cret" not in str(refused.value)
    with pytest.raises(OidcFailed, match="HTTP 400"):
        run(provider.client().claims(SPEC, CLIENT, "code-1", REDIRECT, verifier, "n-1")), "used once"


def test_a_discovery_document_with_an_http_endpoint_is_refused():
    provider = FakeProvider()
    original = provider.handler

    def plain(request):
        answer = original(request)
        if request.url.path == "/.well-known/openid-configuration":
            body = answer.json() | {"token_endpoint": "http://idp.example/token"}
            return type(answer)(200, json=body)
        return answer

    provider.handler = plain
    with pytest.raises(OidcFailed, match="no https token_endpoint"):
        run(provider.client().discovery(SPEC))


def test_the_authorization_url():
    provider = FakeProvider()
    url = run(provider.client().authorize_url(SPEC, CLIENT, REDIRECT, "st", "no", "ch"))
    assert url.startswith(f"{ISSUER}/authorize?")
    for part in ("response_type=code", "client_id=delve-client", "state=st", "nonce=no", "code_challenge=ch",
                 "code_challenge_method=S256", "scope=openid+email+profile"):  # fmt: skip
        assert part in url
    assert "s3cret" not in url


# ----- the owner's client -----


def test_the_client_is_a_private_file_and_its_secret_is_kept_out_of_sight(tmp_path):
    assert oidc.load_client(tmp_path, "google") is None
    saved = oidc.save_client(tmp_path, "google", " my-client ", "my-secret")
    assert saved == oidc.ClientConfig("my-client", "my-secret") == oidc.load_client(tmp_path, "google")
    assert "my-secret" not in repr(saved)
    assert os.stat(oidc.client_path(tmp_path, "google")).st_mode & 0o777 == 0o600
    assert oidc.save_client(tmp_path, "google", "other-client", None).client_secret == "my-secret", "kept"
    with pytest.raises(ValueError, match="one word") as refused:
        oidc.save_client(tmp_path, "google", "c", "two words")
    assert "two words" not in str(refused.value)
    oidc.remove_client(tmp_path, "google")
    assert oidc.load_client(tmp_path, "google") is None
    with pytest.raises(ValueError, match="secret too"):
        oidc.save_client(tmp_path, "google", "c", None)


def test_a_token_for_several_audiences_must_be_issued_to_delve():
    provider = FakeProvider()
    several = ["delve-client", "another-client"]
    with pytest.raises(OidcFailed, match="another client"):
        check(provider, provider.id_token("n-1", aud=several))
    with pytest.raises(OidcFailed, match="another client"):
        check(provider, provider.id_token("n-1", aud=several, azp="another-client"))
    assert check(provider, provider.id_token("n-1", aud=several, azp="delve-client")).subject == "1083"
    with pytest.raises(OidcFailed, match="another client"):
        check(provider, provider.id_token("n-1", azp="another-client"))
