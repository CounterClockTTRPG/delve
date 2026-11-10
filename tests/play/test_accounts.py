"""The accounts service (players and tavern Task B2): usernames, passwords, one-time links, and who may change an
account's rights (owner accounts: the human's ruling of 2026-10-24)."""

from datetime import UTC, datetime, timedelta

import pytest

from delve.domain.accounts import EMBLEMS
from delve.play import accounts
from delve.play.accounts import (
    AccountConflict,
    authenticate,
    change_password,
    check_new_password,
    create_account,
    create_first_owner,
    has_owner_account,
    link_for,
    make_link,
    set_disabled,
    set_organiser,
    set_owner,
    use_link,
    username_of,
)
from delve.play.context import PlayError
from delve.play.seats import NotAllowed

PASSWORD = "correct horse battery"
NOW = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)


def test_username_is_case_folded_everywhere(storage):
    ana = create_account(storage, " Ana ", PASSWORD)
    assert ana.username == "ana" and storage.accounts.by_username("ana") == ana
    with pytest.raises(AccountConflict, match="That username is taken."):
        create_account(storage, "ANA", PASSWORD)
    assert authenticate(storage, "ANA", PASSWORD) == authenticate(storage, " ana", PASSWORD) == ana


def test_username_rules():
    for refused in ("ab", "a" * 33, "an a", "ana!", "émile", "", "   "):
        with pytest.raises(PlayError, match="A username has 3 to 32 characters"):
            username_of(refused)
    assert username_of("a.b_c-1") == "a.b_c-1" and username_of("A" * 32) == "a" * 32


def test_new_account(storage):
    ana = create_account(storage, "ana", PASSWORD, display_name="Ana the Bold", language="nl")
    assert ana.profile.display_name == "Ana the Bold" and ana.profile.language == "nl"
    assert ana.profile.avatar_emblem in EMBLEMS and ana.has_password
    assert not ana.organiser and not ana.owner
    bo = create_account(storage, "bo.b", None, organiser=True)
    assert bo.profile.display_name == "bo.b" and not bo.has_password and bo.organiser
    assert storage.accounts.password_hash(bo.id) is None
    assert create_account(storage, "carla", PASSWORD, owner=True).owner


def test_password_at_least_10(storage):
    with pytest.raises(PlayError, match="A password has at least 10 characters."):
        check_new_password("123456789")
    with pytest.raises(PlayError, match="A password has at most 1024 characters."):
        check_new_password("x" * 1025)
    check_new_password("1234567890")
    check_new_password("x" * 1024)
    with pytest.raises(PlayError, match="at least 10"):
        create_account(storage, "ana", "short")
    assert storage.accounts.list() == [], "nothing is made"


def test_authenticate_refuses(storage):
    ana = create_account(storage, "ana", PASSWORD)
    create_account(storage, "bo.b", None)
    assert authenticate(storage, "ana", PASSWORD) == ana
    assert authenticate(storage, "nobody", PASSWORD) is None
    assert authenticate(storage, "no", PASSWORD) is None, "not even a username"
    assert authenticate(storage, "ana", PASSWORD + "!") is None
    assert authenticate(storage, "bo.b", PASSWORD) is None and authenticate(storage, "bo.b", "") is None
    set_disabled(storage, ana.id, True, NOW, by_owner=False)
    assert authenticate(storage, "ana", PASSWORD) is None
    set_disabled(storage, ana.id, False, NOW, by_owner=False)
    assert authenticate(storage, "ana", PASSWORD) is not None


def test_change_password_needs_the_old(storage):
    ana = create_account(storage, "ana", PASSWORD)
    with pytest.raises(NotAllowed, match="Your current password is wrong."):
        change_password(storage, ana.id, "not the password", "a new password")
    with pytest.raises(PlayError, match="at least 10"):
        change_password(storage, ana.id, PASSWORD, "short")
    change_password(storage, ana.id, PASSWORD, "a new password")
    assert authenticate(storage, "ana", PASSWORD) is None
    assert authenticate(storage, "ana", "a new password") == storage.accounts.get(ana.id)


def test_link_valid_24_hours_used_once(storage):
    ana = create_account(storage, "ana", None)
    token = make_link(storage, ana.id, "set-password", NOW, by_owner=False)
    assert len(token) >= 43 and storage.account_links.get(token) is None, "stored only as its hash"
    found = link_for(storage, token, NOW + timedelta(hours=23, minutes=59))
    assert found is not None and found[0] == ana and found[1].kind == "set-password"
    assert found[1].expires_at == (NOW + timedelta(hours=24)).isoformat()
    assert link_for(storage, token, NOW + timedelta(hours=24)) is None
    assert link_for(storage, "no-such-token", NOW) is None
    with pytest.raises(PlayError, match="expired"):
        use_link(storage, token, "a new password", NOW + timedelta(hours=24))

    used = use_link(storage, token, "a new password", NOW + timedelta(hours=1))
    assert used.id == ana.id and used.has_password
    assert authenticate(storage, "ana", "a new password") is not None
    assert link_for(storage, token, NOW + timedelta(hours=2)) is None
    with pytest.raises(PlayError, match="This link has been used: ask for a new one."):
        use_link(storage, token, "another password", NOW + timedelta(hours=2))
    assert authenticate(storage, "ana", "a new password") is not None, "the second use changed nothing"


def test_link_refusals(storage):
    ana = create_account(storage, "ana", None)
    with pytest.raises(PlayError):
        make_link(storage, ana.id, "log-in", NOW, by_owner=False)
    with pytest.raises(PlayError):
        make_link(storage, "acc_000000000000", "set-password", NOW, by_owner=False)
    with pytest.raises(PlayError, match="isn't known"):
        use_link(storage, "no-such-token", "a new password", NOW)
    token = make_link(storage, ana.id, "reset-password", NOW, by_owner=False)
    with pytest.raises(PlayError, match="at least 10"):
        use_link(storage, token, "short", NOW)
    assert link_for(storage, token, NOW) is not None, "a refused password doesn't use the link"
    set_disabled(storage, ana.id, True, NOW, by_owner=True)
    assert link_for(storage, token, NOW) is None
    with pytest.raises(PlayError):
        use_link(storage, token, "a new password", NOW)


def test_only_an_owner_makes_a_link_for_an_owner_or_an_organiser(storage):
    boss = create_account(storage, "boss", PASSWORD, owner=True)
    orga = create_account(storage, "orga", PASSWORD, organiser=True)
    ana = create_account(storage, "ana", PASSWORD)
    pending = make_link(storage, orga.id, "set-password", NOW, by_owner=True)
    for account in (boss, orga):
        for kind in ("set-password", "reset-password"):
            with pytest.raises(NotAllowed, match="Only an owner can do that."):
                make_link(storage, account.id, kind, NOW, by_owner=False)
    assert link_for(storage, pending, NOW) is not None, "a refused link drops no other"
    assert link_for(storage, make_link(storage, ana.id, "reset-password", NOW, by_owner=False), NOW) is not None
    assert link_for(storage, make_link(storage, orga.id, "reset-password", NOW, by_owner=True), NOW) is not None
    assert link_for(storage, make_link(storage, boss.id, "reset-password", NOW, by_owner=True), NOW) is not None


def test_new_link_drops_the_old(storage):
    ana = create_account(storage, "ana", None)
    first = make_link(storage, ana.id, "set-password", NOW, by_owner=False)
    second = make_link(storage, ana.id, "reset-password", NOW, by_owner=False)
    assert link_for(storage, first, NOW) is None and link_for(storage, second, NOW) is not None


def test_no_password_in_errors(storage):
    ana = create_account(storage, "ana", PASSWORD)
    token = make_link(storage, ana.id, "reset-password", NOW, by_owner=False)
    tries = [
        lambda: create_account(storage, "bo.b", "pw-short"),
        lambda: create_account(storage, "ana", "pw-taken-12345"),
        lambda: create_account(storage, "émile", "pw-badname-12345"),
        lambda: change_password(storage, ana.id, "pw-wrong-old-123", "pw-new-12345"),
        lambda: change_password(storage, ana.id, PASSWORD, "pw-short"),
        lambda: use_link(storage, token, "pw-s-2", NOW),
        lambda: use_link(storage, "no-such-token", "pw-unknown-link-1", NOW),
        lambda: check_new_password("pw-x" * 300),
    ]
    for attempt in tries:
        with pytest.raises(PlayError) as caught:
            attempt()
        said = f"{caught.value.message} {caught.value.hint} {caught.value!r}"
        assert "pw-" not in said and PASSWORD not in said, said


def test_only_an_owner_changes_rights(storage):
    owner = create_account(storage, "olga", PASSWORD, owner=True)
    ana = create_account(storage, "ana", PASSWORD)
    for change in (
        lambda: set_organiser(storage, ana.id, True, by_owner=False),
        lambda: set_owner(storage, ana.id, True, by_owner=False),
        lambda: set_owner(storage, owner.id, False, by_owner=False),
    ):
        with pytest.raises(NotAllowed):
            change()
    assert not storage.accounts.get(ana.id).organiser and not storage.accounts.get(ana.id).owner

    assert set_organiser(storage, ana.id, True, by_owner=True).organiser
    with pytest.raises(NotAllowed, match="Only an owner"):
        set_disabled(storage, ana.id, True, NOW, by_owner=False)  # an organiser's account is the owner's to disable
    assert set_disabled(storage, ana.id, True, NOW, by_owner=True).disabled_at == NOW.isoformat()
    with pytest.raises(NotAllowed):
        set_disabled(storage, ana.id, False, NOW, by_owner=False)
    assert set_disabled(storage, ana.id, False, NOW, by_owner=True).disabled_at is None
    assert not set_organiser(storage, ana.id, False, by_owner=True).organiser

    bo = create_account(storage, "bo.b", PASSWORD)
    assert set_disabled(storage, bo.id, True, NOW, by_owner=False).disabled_at, "an organiser disables a player"
    assert set_owner(storage, bo.id, True, by_owner=True).owner
    with pytest.raises(PlayError):
        set_organiser(storage, "acc_000000000000", True, by_owner=True)


def test_the_last_enabled_owner_stays(storage):
    olga = create_account(storage, "olga", PASSWORD, owner=True)
    with pytest.raises(AccountConflict, match="last owner"):
        set_owner(storage, olga.id, False, by_owner=True)
    with pytest.raises(AccountConflict, match="last owner"):
        set_disabled(storage, olga.id, True, NOW, by_owner=True)
    assert storage.accounts.get(olga.id).owner and storage.accounts.get(olga.id).disabled_at is None

    pia = create_account(storage, "pia", PASSWORD, owner=True)
    set_disabled(storage, pia.id, True, NOW, by_owner=True)
    with pytest.raises(AccountConflict, match="last owner"):
        set_owner(storage, olga.id, False, by_owner=True)  # a disabled owner doesn't count
    set_disabled(storage, pia.id, False, NOW, by_owner=True)
    assert not set_owner(storage, olga.id, False, by_owner=True).owner
    with pytest.raises(AccountConflict, match="last owner"):
        set_disabled(storage, pia.id, True, NOW, by_owner=True)


def test_the_first_owner_account(storage):
    assert not has_owner_account(storage)
    create_account(storage, "ana", PASSWORD, organiser=True)
    assert not has_owner_account(storage)
    with pytest.raises(PlayError, match="at least 10"):
        accounts.create_first_owner(storage, "olga", "short")
    olga = create_first_owner(storage, " Olga ", PASSWORD)
    assert olga.username == "olga" and olga.owner and olga.has_password and has_owner_account(storage)
    with pytest.raises(AccountConflict, match="owner account"):
        create_first_owner(storage, "pia", PASSWORD)
    assert storage.accounts.by_username("pia") is None


def test_a_link_stops_working_when_its_account_is_promoted(storage):
    """An organiser's link for a player can't be used to take the account over once it is an organiser's or an
    owner's (DEL-150, audit finding 2): promoting drops its unused links, and a link only an owner's hand made
    works for such an account."""
    for promote in (lambda a: set_organiser(storage, a.id, True, by_owner=True), lambda a: set_owner(storage, a.id, True, by_owner=True)):
        alice = create_account(storage, f"alice{len(storage.accounts.list())}", None)
        made = make_link(storage, alice.id, "set-password", NOW, by_owner=False)
        promote(alice)
        assert link_for(storage, made, NOW) is None
        with pytest.raises(PlayError):
            use_link(storage, made, "a new password", NOW)
        assert link_for(storage, make_link(storage, alice.id, "set-password", NOW, by_owner=True), NOW) is not None


def test_a_link_an_organiser_made_never_works_for_an_organiser(storage):
    """Even one that outlives the promotion (made in the same moment, or put there by an older install)."""
    alice = create_account(storage, "alice", None)
    made = make_link(storage, alice.id, "reset-password", NOW, by_owner=False)
    storage.accounts.set_organiser(alice.id, True)  # past the service, so the link stays
    with pytest.raises(PlayError, match="This link no longer works: ask an owner for a new one."):
        use_link(storage, made, "a new password", NOW)
    storage.accounts.set_organiser(alice.id, False)
    assert link_for(storage, made, NOW) is not None, "a player's again: the link is as it was"


def test_a_sign_up_waits_for_approval(storage):
    """A sign-up (DEL-156) is a player's account, pending, with its note; it can't log in until approved, and is told
    so only once its password is right."""
    cy = accounts.request_account(storage, " Cyra ", PASSWORD, display_name="Cyra", note="  Bo's friend.  ")
    assert (cy.username, cy.pending, cy.request_note, cy.organiser, cy.owner) == ("cyra", True, "Bo's friend.", False, False)
    assert cy.has_password and cy.profile.display_name == "Cyra"
    assert authenticate(storage, "cyra", "a wrong password") is None, "a wrong password learns nothing"
    with pytest.raises(accounts.AccountPending, match="waits for approval"):
        authenticate(storage, "cyra", PASSWORD)

    approved = accounts.approve(storage, cy.id)
    assert not approved.pending and authenticate(storage, "cyra", PASSWORD) == approved
    with pytest.raises(AccountConflict, match="isn't waiting"):
        accounts.approve(storage, cy.id)
    with pytest.raises(AccountConflict, match="isn't waiting"):
        accounts.reject(storage, cy.id)


def test_a_rejected_sign_up_is_deleted_and_its_name_free(storage):
    dee = accounts.request_account(storage, "dee", PASSWORD)
    accounts.reject(storage, dee.id)
    assert storage.accounts.get(dee.id) is None
    assert accounts.request_account(storage, "dee", PASSWORD).pending
    with pytest.raises(accounts.NotFound):
        accounts.reject(storage, "acc_000000000000")


def test_sign_up_refusals(storage):
    create_account(storage, "ana", PASSWORD)
    with pytest.raises(AccountConflict, match="taken"):
        accounts.request_account(storage, "ANA", PASSWORD)
    with pytest.raises(PlayError, match="at least 10"):
        accounts.request_account(storage, "bora", "short")
    with pytest.raises(PlayError, match="at most 300"):
        accounts.request_account(storage, "bora", PASSWORD, note="x" * 301)
    with pytest.raises(PlayError, match="A name has"):
        accounts.request_account(storage, "bora", PASSWORD, display_name=" ")
    assert storage.accounts.by_username("bora") is None


def test_at_most_so_many_sign_ups_wait(storage, monkeypatch):
    monkeypatch.setattr(accounts, "PENDING_MAX", 2)
    accounts.request_account(storage, "one", PASSWORD)
    accounts.request_account(storage, "two", PASSWORD)
    with pytest.raises(accounts.SignUpsFull):
        accounts.request_account(storage, "three", PASSWORD)
    accounts.approve(storage, storage.accounts.by_username("one").id)
    assert accounts.request_account(storage, "three", PASSWORD).pending, "an approved one no longer waits"
