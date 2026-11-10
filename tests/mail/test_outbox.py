"""The outbox (DEL-314): who gets a message of a kind, what a queued message keeps, and the off tokens."""

from delve.domain.accounts import Profile
from delve.mail import outbox
from delve.mail.settings import MailSettings, save
from tests.mail.conftest import NOW, composed, with_address


def test_a_queued_message_is_due_in_the_accounts_language(storage):
    ana = with_address(storage, "ana")
    ana = storage.accounts.save_profile(ana.id, Profile("Ana", language="nl"))
    id = outbox.queue(storage, ana, "board", composed(), NOW, unsubscribe="tok")
    [due] = storage.mail.due(outbox.iso(NOW), 10)
    assert due.id == id and due.kind == "board" and due.account_id == ana.id
    assert due.language == "nl" and due.unsubscribe == "tok" and due.subject == "A word"


def test_queue_refuses_an_unconfirmed_address_except_for_its_confirmation(storage):
    typed = with_address(storage, "typed", pending="typed@example.org", confirmed=False)
    assert outbox.queue(storage, typed, "board", composed(), NOW) is None
    assert outbox.queue(storage, typed, "reset", composed(), NOW) is None
    assert outbox.address_for(typed, "confirm") == "typed@example.org"
    assert outbox.queue(storage, typed, "confirm", composed(), NOW) is not None
    assert [m.kind for m in storage.mail.due(outbox.iso(NOW), 10)] == ["confirm"]


def test_the_confirmation_goes_to_the_new_address_not_the_confirmed_one(storage):
    ana = with_address(storage, "ana", pending="new@example.org")
    assert outbox.address_for(ana, "confirm") == "new@example.org"
    assert outbox.address_for(ana, "reset") == "ana@example.org"


def test_a_switched_off_kind_has_no_address(storage):
    ana = with_address(storage, "ana")
    storage.accounts.set_mail_switches(ana.id, mail_host=False, mail_board=True)
    ana = storage.accounts.get(ana.id)
    assert outbox.address_for(ana, "host") is None and outbox.address_for(ana, "schedule") is None
    assert outbox.address_for(ana, "board") == "ana@example.org"
    assert outbox.address_for(ana, "test") == "ana@example.org"


def test_a_disabled_account_gets_nothing(storage):
    ana = with_address(storage, "ana", pending="new@example.org")
    ana = storage.accounts.set_disabled(ana.id, outbox.iso(NOW))
    assert all(outbox.address_for(ana, kind) is None for kind in ("confirm", "reset", "test", "board"))


def test_a_pending_account_gets_only_its_confirmation(storage):
    account = storage.accounts.create("waits", Profile("Waits"), pending=True)
    storage.accounts.set_email(account.id, email="w@example.org", email_pending="w2@example.org")
    account = storage.accounts.get(account.id)
    assert outbox.address_for(account, "confirm") == "w2@example.org"
    assert all(outbox.address_for(account, kind) is None for kind in ("reset", "approved", "test", "board", "host"))


def test_the_outbox_stores_no_recipient_address(storage):
    ana = with_address(storage, "ana", pending="next@example.org")
    outbox.queue(storage, ana, "board", composed(), NOW, unsubscribe="tok")
    outbox.queue(storage, ana, "confirm", composed(), NOW)
    rows = storage.mail.due(outbox.iso(NOW), 10)
    assert len(rows) == 2
    for row in rows:
        assert not any("@example.org" in str(value) for value in row.__dict__.values())


def test_an_off_token_names_its_account_and_group_and_a_forged_one_nothing(tmp_path):
    token = outbox.off_token(tmp_path, "acc_1", "host")
    assert outbox.read_off_token(tmp_path, token) == ("acc_1", "host")
    assert outbox.off_token(tmp_path, "acc_1", "host") == token
    assert outbox.read_off_token(tmp_path, outbox.off_token(tmp_path, "acc_1", "board")) == ("acc_1", "board")
    account, group, signature = token.split(".")
    assert outbox.read_off_token(tmp_path, f"acc_2.{group}.{signature}") is None
    assert outbox.read_off_token(tmp_path, f"{account}.board.{signature}") is None
    assert outbox.read_off_token(tmp_path, f"{account}.mail.{signature}") is None
    assert outbox.read_off_token(tmp_path, "nonsense") is None
    assert outbox.read_off_token(tmp_path, "") is None


def test_the_off_secret_is_private_and_another_install_reads_no_token(tmp_path):
    token = outbox.off_token(tmp_path / "a", "acc_1", "host")
    assert (tmp_path / "a" / "mail-secret").stat().st_mode & 0o777 == 0o600
    assert outbox.read_off_token(tmp_path / "b", token) is None


def test_an_off_link_needs_a_public_url(tmp_path):
    assert outbox.off_link(tmp_path, "acc_1", "board") is None
    save(tmp_path, MailSettings(public_url="https://d.example.org"))
    token, link = outbox.off_link(tmp_path, "acc_1", "board")
    assert link == f"https://d.example.org/mail/off/{token}"
    assert outbox.read_off_token(tmp_path, token) == ("acc_1", "board")


def test_two_first_calls_at_once_make_one_secret(tmp_path, monkeypatch):
    """A request thread and the sender asking for the first off token at once: one secret, kept, for both (DEL-314)."""
    import secrets
    import threading

    together = threading.Barrier(2)
    token_hex = secrets.token_hex

    def at_once(n):
        try:
            together.wait(timeout=2)  # both have found no secret yet
        except threading.BrokenBarrierError:
            pass
        return token_hex(n)

    monkeypatch.setattr(outbox.secrets, "token_hex", at_once)
    tokens = []
    threads = [
        threading.Thread(target=lambda: tokens.append(outbox.off_token(tmp_path, "acc_1", "host"))) for _ in range(2)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    monkeypatch.setattr(outbox.secrets, "token_hex", token_hex)
    assert len(tokens) == 2 and tokens[0] == tokens[1]
    assert outbox.off_token(tmp_path, "acc_1", "host") == tokens[0], "the secret kept is the one both used"
    assert (tmp_path / "mail-secret").stat().st_mode & 0o777 == 0o600
