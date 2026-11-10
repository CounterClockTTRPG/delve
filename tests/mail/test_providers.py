"""The log and Emailit providers (DEL-314), and the Email connection's settings. Emailit is an
`httpx.MockTransport`; never a real call."""

import asyncio
import json
import logging
import stat

import httpx
import pytest

from delve.mail import settings
from delve.mail.providers import Accepted, EmailitProvider, Envelope, Failed, LogProvider, Retry, provider_for
from delve.mail.settings import KEY_ENV, KEY_FILE, MailSettings


def envelope(**fields):
    values = {
        "id": "m1",
        "to": "ana@example.org",
        "sender": "Delve <delve@example.org>",
        "subject": "A word",
        "text": "Hello\n",
        "html": "<p>Hello</p>",
        "reply_to": None,
        "headers": {},
        "kind": "board",
        "account_id": "acc_1",
    }
    return Envelope(**{**values, **fields})


def answering(status, body=None, seen=None, **headers):
    def handle(request):
        if seen is not None:
            seen.append(request)
        return httpx.Response(status, json=body if body is not None else {}, headers=headers)

    return httpx.AsyncClient(transport=httpx.MockTransport(handle))


def send(client, env=None):
    async def go():
        async with client:
            return await EmailitProvider("k", client).send(env or envelope())

    return asyncio.run(go())


def test_emailit_gets_one_recipient_an_idempotency_key_and_no_tracking():
    seen = []
    result = send(answering(200, {"id": "em_1"}, seen), envelope(id="m1", to="ana@example.org"))
    assert isinstance(result, Accepted)
    request = seen[0]
    body = json.loads(request.content)
    assert str(request.url) == "https://api.emailit.com/v2/emails" and request.method == "POST"
    assert request.headers["Authorization"] == "Bearer k" and request.headers["Idempotency-Key"] == "m1"
    assert body["to"] == "ana@example.org" and body["tracking"] is False and "cc" not in body and "bcc" not in body
    assert body["meta"] == {"delve_id": "m1"} and "reply_to" not in body and "headers" not in body


def test_emailit_gets_reply_to_and_headers_when_there_are_some():
    seen = []
    env = envelope(reply_to="host@example.org", headers={"List-Unsubscribe": "<https://d/x>"})
    send(answering(200, {}, seen), env)
    body = json.loads(seen[0].content)
    assert body["reply_to"] == "host@example.org" and body["headers"] == {"List-Unsubscribe": "<https://d/x>"}


def test_emailit_rate_limit_is_retried_after_its_wait():
    result = send(answering(429, {"retry_after": 3}))
    assert isinstance(result, Retry) and result.after_s == 3 and result.rate_limited


def test_emailit_rate_limit_without_a_wait_is_retried_after_a_second():
    result = send(answering(429, {}))
    assert isinstance(result, Retry) and result.after_s == 1


@pytest.mark.parametrize("status", [500, 502, 503])
def test_emailit_down_is_retried_in_a_minute(status):
    result = send(answering(status, {"error": "remote words"}))
    assert isinstance(result, Retry) and result.after_s == 60 and "remote words" not in result.reason
    assert not result.rate_limited


@pytest.mark.parametrize("error", [httpx.ConnectTimeout("t"), httpx.ConnectError("c"), httpx.ReadTimeout("r")])
def test_emailit_unreachable_is_retried_in_a_minute(error):
    def handle(request):
        raise error

    result = send(httpx.AsyncClient(transport=httpx.MockTransport(handle)))
    assert isinstance(result, Retry) and result.after_s == 60


def test_emailit_sandbox_is_a_failure_in_delves_words():
    result = send(answering(403, {"code": "unverified_workspace_recipient", "message": "REMOTE TEXT k"}))
    assert result == Failed("Emailit's workspace is still in sandbox")


def test_emailit_domain_not_authorized_is_its_own_failure():
    result = send(answering(403, {"error": "Domain not authorized", "message": "REMOTE TEXT d.example"}))
    assert result == Failed("Emailit's key may not send from this sender's domain")
    assert result != Failed("Emailit hasn't verified the sending domain")


@pytest.mark.parametrize(
    ("status", "reason"),
    [
        (402, "Emailit has no credits left"),
        (401, "Emailit refused the API key"),
        (403, "Emailit's key may not send from this sender's domain"),
        (422, "Emailit hasn't verified the sending domain"),
        (400, "Emailit refused the message (HTTP 400)"),
        (413, "Emailit refused the message (HTTP 413)"),
    ],
)
def test_emailit_refusals_are_failures_in_delves_words(status, reason):
    result = send(answering(status, {"message": "REMOTE TEXT"}))
    assert result == Failed(reason)


def test_the_log_provider_logs_kind_account_and_subject_but_never_the_address(caplog):
    caplog.set_level(logging.DEBUG)
    result = asyncio.run(LogProvider().send(envelope()))
    assert isinstance(result, Accepted)
    assert "board" in caplog.text and "acc_1" in caplog.text and "A word" in caplog.text
    assert "example.org" not in caplog.text and "Hello" not in caplog.text


def test_settings_round_trip_and_start_as_log(tmp_path):
    assert settings.load(tmp_path) == MailSettings()
    saved = MailSettings(provider="emailit", sender="Delve <d@example.org>", public_url="https://d.example.org")
    settings.save(tmp_path, saved)
    assert settings.load(tmp_path) == saved


def test_a_broken_settings_file_is_the_defaults(tmp_path):
    (tmp_path / "mail.json").write_text("{nope", encoding="utf-8")
    assert settings.load(tmp_path) == MailSettings()
    (tmp_path / "mail.json").write_text('{"provider": "smtp"}', encoding="utf-8")
    assert settings.load(tmp_path).provider == "log"


def test_the_key_file_is_private(tmp_path):
    assert settings.key_state(tmp_path, environ={}) == "unset"
    settings.save_key(tmp_path, " key-1 ")
    assert stat.S_IMODE((tmp_path / KEY_FILE).stat().st_mode) == 0o600
    assert settings.key_state(tmp_path, environ={}) == "set"
    assert settings.load_key(tmp_path, environ={}) == "key-1"
    settings.remove_key(tmp_path)
    assert settings.key_state(tmp_path, environ={}) == "unset" and settings.load_key(tmp_path, environ={}) is None


def test_a_key_is_one_word(tmp_path):
    with pytest.raises(ValueError):
        settings.save_key(tmp_path, "two words")
    with pytest.raises(ValueError):
        settings.save_key(tmp_path, "  ")


def test_the_env_key_wins(tmp_path):
    settings.save_key(tmp_path, "saved")
    assert settings.key_state(tmp_path, environ={KEY_ENV: "x"}) == "environment"
    assert settings.load_key(tmp_path, environ={KEY_ENV: "x"}) == "x"


def test_the_public_url_is_the_saved_one_else_the_one_allowed_host(tmp_path):
    assert settings.public_url(tmp_path, env={}) is None
    assert (
        settings.public_url(tmp_path, env={"DELVE_ALLOWED_HOSTS": "delve.example.org"}) == "https://delve.example.org"
    )
    assert settings.public_url(tmp_path, env={"DELVE_ALLOWED_HOSTS": "a.example.org, b.example.org"}) is None
    settings.save(tmp_path, MailSettings(public_url="https://mine.example.org/"))
    assert settings.public_url(tmp_path, env={"DELVE_ALLOWED_HOSTS": "a.example.org"}) == "https://mine.example.org"


def test_mail_is_enabled_with_emailit_a_key_a_sender_and_a_public_url(tmp_path):
    full = MailSettings(provider="emailit", sender="d@example.org", public_url="https://d.example.org")
    settings.save(tmp_path, full)
    assert not settings.mail_enabled(tmp_path, environ={})
    settings.save_key(tmp_path, "k")
    assert settings.mail_enabled(tmp_path, environ={})
    for missing in ({"provider": "log"}, {"sender": ""}, {"public_url": ""}):
        settings.save(tmp_path, MailSettings(**{**full.__dict__, **missing}))
        assert not settings.mail_enabled(tmp_path, environ={})


def test_the_provider_is_emailit_only_when_mail_is_enabled(app, tmp_path):
    assert isinstance(provider_for(app), LogProvider)
    settings.save(tmp_path, MailSettings(provider="emailit", sender="d@example.org", public_url="https://d.example"))
    assert provider_for(app) is None  # chosen, without a key: nothing sends, nothing is logged as sent
    settings.save(tmp_path, MailSettings(provider="emailit", sender="d@example.org", public_url="https://d.example"))
    settings.save_key(tmp_path, "k")
    provider = provider_for(app)
    assert isinstance(provider, EmailitProvider)
    asyncio.run(provider.aclose())


@pytest.mark.parametrize(("asked", "wait"), [(1e300, 3600), ("inf", 1), ("nan", 1), (0, 1), (7200, 3600), ("2", 2)])
def test_a_rate_limits_wait_is_a_finite_number_of_at_most_an_hour(asked, wait):
    result = send(answering(429, {"retry_after": asked}))
    assert isinstance(result, Retry) and result.after_s == wait
