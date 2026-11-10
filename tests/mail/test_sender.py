"""The sender (DEL-314): one pass hands each due message to the provider with the address the account has now, paced,
retried with a growing wait, dropped when nobody should get it. Emailit is an `httpx.MockTransport`."""

import asyncio
import json
from datetime import timedelta

import httpx
import pytest

from delve.mail import outbox, sender, settings
from delve.mail.sender import PACE_S, RETRY_S, send_due, sender_loop
from delve.mail.settings import MailSettings
from delve.play.clock import FakeClock
from tests.mail.conftest import NOW, composed, with_address

PUBLIC = "https://d.example.org"


class Emailit:
    """Emailit answering `status`, keeping each request's body and headers."""

    def __init__(self, status=200, body=None):
        self.status, self.body, self.seen = status, body or {"id": "em_1"}, []

    def __call__(self, request):
        self.seen.append(request)
        return httpx.Response(self.status, json=self.body)

    @property
    def bodies(self):
        return [json.loads(request.content) for request in self.seen]


@pytest.fixture
def emailit(app, tmp_path):
    """Emailit enabled, answering 200 until a test changes `status`."""
    remote = Emailit()
    settings.save(tmp_path, MailSettings(provider="emailit", sender="Delve <delve@example.org>", public_url=PUBLIC))
    settings.save_key(tmp_path, "k")
    app.state.mail_transport = httpx.MockTransport(remote)
    return remote


@pytest.fixture(autouse=True)
def no_pause(monkeypatch):
    paces = []

    async def pace():
        paces.append(PACE_S)

    monkeypatch.setattr(sender, "_pace", pace)
    return paces


def run(coroutine):
    return asyncio.run(coroutine)


def test_a_due_message_goes_to_the_accounts_address_and_is_marked_sent(app, storage, emailit):
    ana = with_address(storage, "ana")
    id = outbox.queue(storage, ana, "test", composed(), NOW)
    assert run(send_due(app, NOW)) == 1
    [body] = emailit.bodies
    assert body["to"] == "ana@example.org" and body["from"] == "Delve <delve@example.org>"
    assert body["subject"] == "A word" and body["text"] == "Hello\n" and body["html"] == "<p>Hello</p>"
    assert "headers" not in body and "reply_to" not in body
    assert emailit.seen[0].headers["Idempotency-Key"] == id
    assert storage.mail.due(outbox.iso(NOW), 10) == [] and storage.mail.sent_since(outbox.iso(NOW)) == 1


def test_a_switchable_message_carries_one_click_unsubscribe_headers(app, storage, emailit):
    ana = with_address(storage, "ana")
    token = outbox.off_token(app.state.config.data_dir, ana.id, "board")
    outbox.queue(storage, ana, "board", composed(), NOW, unsubscribe=token)
    run(send_due(app, NOW))
    assert emailit.bodies[0]["headers"] == {
        "List-Unsubscribe": f"<{PUBLIC}/api/mail/off/{token}>",
        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
    }


def test_a_hosts_reply_to_goes_with_the_message_and_is_cleared_once_sent(app, storage, emailit):
    ana = with_address(storage, "ana")
    outbox.queue(storage, ana, "host", composed(), NOW, reply_to="host@example.org")
    run(send_due(app, NOW))
    assert emailit.bodies[0]["reply_to"] == "host@example.org"
    assert storage.mail.recent_failures(5) == []


def test_line_breaks_in_a_subject_become_one_space(app, storage, emailit):
    ana = with_address(storage, "ana")
    outbox.queue(storage, ana, "test", composed("Hello\r\nBcc: x@example.org\nthere"), NOW)
    run(send_due(app, NOW))
    assert emailit.bodies[0]["subject"] == "Hello Bcc: x@example.org there"


def test_a_message_to_an_address_removed_since_is_dropped(app, storage, emailit):
    ana = with_address(storage, "ana")
    outbox.queue(storage, ana, "board", composed(), NOW)
    storage.accounts.set_email(ana.id, email=None, email_pending=None)
    assert run(send_due(app, NOW)) == 0
    assert storage.mail.due(outbox.iso(NOW), 10) == [] and storage.mail.recent_failures(5)[0].failure == "dropped"


def test_a_switched_off_kind_is_dropped_at_send(app, storage, emailit):
    ana = with_address(storage, "ana")
    outbox.queue(storage, ana, "host", composed(), NOW)
    storage.accounts.set_mail_switches(ana.id, mail_host=False, mail_board=True)
    assert run(send_due(app, NOW)) == 0
    assert emailit.seen == [] and storage.mail.recent_failures(5)[0].failure == "dropped"


def test_a_message_whose_account_is_gone_is_dropped(app, storage):
    ana = with_address(storage, "ana")
    outbox.queue(storage, ana, "test", composed(), NOW)
    storage.accounts.set_disabled(ana.id, outbox.iso(NOW))
    assert run(send_due(app, NOW)) == 0
    assert storage.mail.recent_failures(5)[0].failure == "dropped"


def test_a_temporary_failure_waits_then_gives_up(app, storage, emailit):
    emailit.status = 503
    ana = with_address(storage, "ana")
    outbox.queue(storage, ana, "test", composed(), NOW)
    at = NOW
    for wait in RETRY_S:
        assert run(send_due(app, at)) == 1
        assert storage.mail.recent_failures(5) == []
        assert run(send_due(app, at + timedelta(seconds=wait - 1))) == 0
        at += timedelta(seconds=wait)
    assert run(send_due(app, at)) == 1
    [failed] = storage.mail.recent_failures(5)
    assert failed.failure == "gave up" and failed.attempts == len(RETRY_S) + 1
    assert len(emailit.seen) == len(RETRY_S) + 1


def test_a_refused_message_fails_in_delves_words(app, storage, emailit):
    emailit.status, emailit.body = 402, {"message": "REMOTE"}
    ana = with_address(storage, "ana")
    outbox.queue(storage, ana, "test", composed(), NOW)
    run(send_due(app, NOW))
    assert storage.mail.recent_failures(5)[0].failure == "Emailit has no credits left"


def test_the_log_provider_marks_mail_sent_without_a_connection(app, storage):
    ana = with_address(storage, "ana")
    outbox.queue(storage, ana, "test", composed(), NOW)
    assert run(send_due(app, NOW)) == 1
    assert storage.mail.sent_since(outbox.iso(NOW)) == 1


def test_sends_are_paced(app, storage, no_pause):
    for name in ("ana", "bob", "cy"):
        outbox.queue(storage, with_address(storage, name), "test", composed(), NOW)
    assert run(send_due(app, NOW)) == 3
    assert no_pause == [PACE_S, PACE_S] and PACE_S == 0.5


def test_a_pass_prunes_mail_sent_over_thirty_days_ago(app, storage):
    ana = with_address(storage, "ana")
    outbox.queue(storage, ana, "test", composed(), NOW)
    run(send_due(app, NOW))
    run(send_due(app, NOW + timedelta(days=29)))
    assert storage.mail.sent_since(outbox.iso(NOW)) == 1
    run(send_due(app, NOW + timedelta(days=30, seconds=1)))
    assert storage.mail.sent_since(outbox.iso(NOW)) == 0


def test_the_loop_sends_by_the_apps_clock_until_cancelled(app, storage):
    app.state.clock = FakeClock(NOW)
    outbox.queue(storage, with_address(storage, "ana"), "test", composed(), NOW)

    async def a_few_ticks():
        loop = asyncio.create_task(sender_loop(app, tick=0.01))
        await asyncio.sleep(0.05)
        loop.cancel()
        await asyncio.gather(loop, return_exceptions=True)

    run(a_few_ticks())
    assert storage.mail.sent_since(outbox.iso(NOW)) == 1


@pytest.mark.parametrize("missing", ["key", "sender", "public_url"])
def test_emailit_chosen_but_not_set_up_holds_the_mail(app, storage, emailit, tmp_path, missing):
    if missing == "key":
        settings.remove_key(tmp_path)
    else:
        full = MailSettings(provider="emailit", sender="Delve <delve@example.org>", public_url=PUBLIC)
        settings.save(tmp_path, MailSettings(**{**full.__dict__, missing: ""}))
    id = outbox.queue(storage, with_address(storage, "ana"), "test", composed(), NOW)
    assert run(send_due(app, NOW)) == 0
    assert [m.id for m in storage.mail.due(outbox.iso(NOW), 10)] == [id]
    assert emailit.seen == [] and storage.mail.sent_since(outbox.iso(NOW)) == 0
    assert storage.mail.recent_failures(5) == []


def test_a_rate_limit_waits_as_asked_and_doesnt_count_but_an_outage_does(app, storage, emailit):
    emailit.status, emailit.body = 429, {"retry_after": 3}
    id = outbox.queue(storage, with_address(storage, "ana"), "test", composed(), NOW)
    assert run(send_due(app, NOW)) == 1
    assert storage.mail.due(outbox.iso(NOW + timedelta(seconds=2)), 10) == []
    [waiting] = storage.mail.due(outbox.iso(NOW + timedelta(seconds=3)), 10)
    assert waiting.id == id and waiting.next_at == outbox.iso(NOW + timedelta(seconds=3)) and waiting.attempts == 0
    emailit.status, emailit.body = 503, {}
    at = NOW + timedelta(seconds=3)
    assert run(send_due(app, at)) == 1
    [again] = storage.mail.due(outbox.iso(at + timedelta(seconds=RETRY_S[0])), 10)
    assert again.attempts == 1 and again.next_at == outbox.iso(at + timedelta(seconds=RETRY_S[0]))


def test_a_rate_limit_waits_at_least_a_second(app, storage, emailit):
    emailit.status, emailit.body = 429, {"retry_after": 0.1}
    outbox.queue(storage, with_address(storage, "ana"), "test", composed(), NOW)
    run(send_due(app, NOW))
    [waiting] = storage.mail.due(outbox.iso(NOW + timedelta(seconds=1)), 10)
    assert waiting.next_at == outbox.iso(NOW + timedelta(seconds=1)) and waiting.attempts == 0


def test_a_message_that_breaks_backs_off_and_the_next_one_still_goes(app, storage, emailit, caplog):
    first = outbox.queue(storage, with_address(storage, "ana"), "test", composed(), NOW)
    second = outbox.queue(storage, with_address(storage, "bob"), "test", composed(), NOW + timedelta(seconds=1))
    calls = []

    def handle(request):
        calls.append(request)
        if len(calls) == 1:
            raise httpx.DecodingError("broken")
        return httpx.Response(200, json={"id": "em_2"})

    app.state.mail_transport = httpx.MockTransport(handle)
    later = NOW + timedelta(seconds=1)
    assert run(send_due(app, later)) == 2
    assert [json.loads(r.content)["to"] for r in calls] == ["ana@example.org", "bob@example.org"]
    assert storage.mail.sent_since(outbox.iso(NOW)) == 1
    [backed_off] = storage.mail.due(outbox.iso(later + timedelta(seconds=RETRY_S[0])), 10)
    assert backed_off.id == first and backed_off.attempts == 1
    assert backed_off.next_at == outbox.iso(later + timedelta(seconds=RETRY_S[0]))
    assert second != first and "example.org" not in caplog.text


@pytest.mark.parametrize("asked", [1e300, "inf", "Infinity", -5])
def test_a_rate_limit_asking_too_much_is_clamped(app, storage, emailit, asked):
    emailit.status, emailit.body = 429, {"retry_after": asked}
    id = outbox.queue(storage, with_address(storage, "ana"), "test", composed(), NOW)
    assert run(send_due(app, NOW)) == 1
    [waiting] = storage.mail.due(outbox.iso(NOW + timedelta(hours=1)), 10)
    assert waiting.id == id and waiting.attempts == 0 and waiting.next_at <= outbox.iso(NOW + timedelta(hours=1))


def test_with_email_switched_off_waiting_mail_fails_and_a_test_still_goes_to_the_log(app, storage, emailit, tmp_path):
    """Stop sending email or Log only: mail queued, held or backing off is not sent, and not marked sent either."""
    emailit.status = 503
    backing_off = outbox.queue(storage, with_address(storage, "ana"), "reset", composed(), NOW)
    run(send_due(app, NOW))
    assert storage.mail.due(outbox.iso(NOW + timedelta(hours=1)), 10)[0].attempts == 1
    settings.remove_key(tmp_path)
    held = outbox.queue(storage, with_address(storage, "bob"), "approved", composed(), NOW)
    run(send_due(app, NOW))
    settings.save(tmp_path, MailSettings(provider="log", sender="", public_url=""))
    test = outbox.queue(storage, with_address(storage, "cy"), "test", composed(), NOW)
    assert run(send_due(app, NOW + timedelta(hours=1))) == 1, "the test alone"
    assert storage.mail.sent_since(outbox.iso(NOW)) == 1
    assert storage.mail.due(outbox.iso(NOW + timedelta(days=1)), 10) == []
    failures = {m.id: m.failure for m in storage.mail.recent_failures(5)}
    assert failures == {backing_off: sender.SWITCHED_OFF, held: sender.SWITCHED_OFF}
    assert sender.SWITCHED_OFF == "not sent: email was switched off"
    assert test not in failures


def test_sent_mail_is_pruned_at_most_once_an_hour(app, storage, monkeypatch):
    pruned = []
    monkeypatch.setattr(storage.mail, "prune_sent", pruned.append)
    for seconds in (0, 2, 4, 3599, 3600, 3602, 7300):
        run(send_due(app, NOW + timedelta(seconds=seconds)))
    assert len(pruned) == 3
