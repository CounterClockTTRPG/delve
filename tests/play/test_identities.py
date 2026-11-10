"""Outside identities (DEL-206): logging in with one, linking it, signing up with it, unlinking it; matched by the
provider's subject, never by email."""

from datetime import UTC, datetime

import pytest

from delve.domain.accounts import Identity
from delve.play import accounts, identities
from delve.play.context import PlayError
from delve.play.identities import Claims, IdentityConflict, UnknownIdentity

NOW = datetime(2026, 10, 27, 10, 0, tzinfo=UTC)
PASSWORD = "correct horse battery"
ANA_GOOGLE = Claims("google", "1083", "ana@example.org", "Ana Lind")


def test_a_linked_identity_logs_in_and_a_stranger_doesn_t(storage):
    ana = accounts.create_account(storage, "ana", PASSWORD)
    identities.link(storage, ana.id, ANA_GOOGLE, NOW)
    assert identities.log_in(storage, ANA_GOOGLE).id == ana.id
    with pytest.raises(UnknownIdentity):
        identities.log_in(storage, Claims("google", "9999", "ana@example.org"))
    with pytest.raises(UnknownIdentity, match="sign up"):
        identities.log_in(storage, Claims("other", "1083"))


def test_an_email_is_never_matched(storage):
    """Ana's address on another Google account (or one Google never checked) doesn't log in to Ana's account."""
    ana = accounts.create_account(storage, "ana", PASSWORD)
    identities.link(storage, ana.id, ANA_GOOGLE, NOW)
    with pytest.raises(UnknownIdentity):
        identities.log_in(storage, Claims("google", "666", "ana@example.org", "Ana Lind"))


def test_a_disabled_or_pending_account_doesn_t_log_in(
    storage,
):
    ana = accounts.create_account(storage, "ana", PASSWORD)
    identities.link(storage, ana.id, ANA_GOOGLE, NOW)
    storage.accounts.set_disabled(ana.id, NOW.isoformat())
    with pytest.raises(PlayError, match="disabled"):
        identities.log_in(storage, ANA_GOOGLE)
    cy = identities.sign_up(storage, Claims("google", "2"), "cyra", NOW)
    with pytest.raises(accounts.AccountPending):
        identities.log_in(storage, Claims("google", "2"))
    accounts.approve(storage, cy.id)
    assert identities.log_in(storage, Claims("google", "2")).id == cy.id


def test_linking_is_one_identity_per_account_per_provider(storage):
    ana = accounts.create_account(storage, "ana", PASSWORD)
    bo = accounts.create_account(storage, "bors", PASSWORD)
    linked = identities.link(storage, ana.id, ANA_GOOGLE, NOW)
    assert linked == Identity("google", "1083", ana.id, "ana@example.org", NOW.isoformat())
    assert identities.link(storage, ana.id, ANA_GOOGLE, NOW) == linked, "linking it again changes nothing"
    with pytest.raises(IdentityConflict, match="another Delve account"):
        identities.link(storage, bo.id, ANA_GOOGLE, NOW)
    with pytest.raises(IdentityConflict, match="unlink it first"):
        identities.link(storage, ana.id, Claims("google", "5555"), NOW)
    assert storage.account_identities.list(bo.id) == []


def test_a_sign_up_with_an_identity_has_no_password_and_waits(storage):
    cy = identities.sign_up(
        storage, Claims("google", "42", "cy@example.org", "Cyra Moss"), " Cyra ", NOW, note="Bo's friend"
    )
    assert (cy.username, cy.profile.display_name, cy.pending, cy.has_password) == ("cyra", "Cyra Moss", True, False)
    assert cy.request_note == "Bo's friend"
    assert storage.account_identities.get("google", "42").account_id == cy.id
    named = identities.sign_up(storage, Claims("google", "43", "", "Dee"), "dee", NOW, display_name="Deedee")
    assert named.profile.display_name == "Deedee", "the name they typed wins over the provider's"
    nameless = identities.sign_up(storage, Claims("google", "44"), "eli", NOW)
    assert nameless.profile.display_name == "eli"


def test_a_sign_up_is_refused_as_any_sign_up_is_and_leaves_nothing(storage):
    accounts.create_account(storage, "ana", PASSWORD)
    with pytest.raises(accounts.AccountConflict):
        identities.sign_up(storage, Claims("google", "7"), "ANA", NOW)
    with pytest.raises(PlayError):
        identities.sign_up(storage, Claims("google", "7"), "x", NOW)
    assert storage.account_identities.get("google", "7") is None
    identities.sign_up(storage, Claims("google", "7"), "fen", NOW)
    with pytest.raises(IdentityConflict):
        identities.sign_up(storage, Claims("google", "7"), "fen2", NOW)
    assert storage.accounts.by_username("fen2") is None, "no second account for one identity"


def test_unlinking_keeps_a_way_to_log_in(storage):
    ana = accounts.create_account(storage, "ana", PASSWORD)
    identities.link(storage, ana.id, ANA_GOOGLE, NOW)
    identities.unlink(storage, ana.id, "google")
    assert storage.account_identities.list(ana.id) == []
    with pytest.raises(PlayError, match="none linked"):
        identities.unlink(storage, ana.id, "google")

    cy = identities.sign_up(storage, Claims("google", "42"), "cyra", NOW)
    with pytest.raises(PlayError, match="set a password first"):
        identities.unlink(storage, cy.id, "google")
    assert storage.account_identities.get("google", "42") is not None
    storage.accounts.set_password_hash(cy.id, storage.accounts.password_hash(ana.id))
    identities.unlink(storage, cy.id, "google")
    assert storage.account_identities.list(cy.id) == []


def test_a_password_sign_up_still_needs_its_password(storage):
    with pytest.raises(PlayError):
        accounts.request_account(storage, "gil", None)


def test_a_reset_link_unlinks_and_a_set_password_link_doesn_t(storage):
    ana = accounts.create_account(storage, "ana", PASSWORD)
    identities.link(storage, ana.id, ANA_GOOGLE, NOW)
    first = accounts.make_link(storage, ana.id, "set-password", NOW, by_owner=True)
    accounts.use_link(storage, first, "another long password", NOW)
    assert storage.account_identities.list(ana.id) != [], "setting a first password takes nothing back"
    reset = accounts.make_link(storage, ana.id, "reset-password", NOW, by_owner=True)
    accounts.use_link(storage, reset, "yet another long password", NOW)
    assert storage.account_identities.list(ana.id) == []


def test_linking_google_fills_an_account_without_an_address_confirmed(storage):
    """Google's address is trusted as given (DEL-314), only when the account has none yet."""
    ana = accounts.create_account(storage, "ana", PASSWORD)
    identities.link(storage, ana.id, ANA_GOOGLE, NOW)
    ana = storage.accounts.get(ana.id)
    assert (ana.email, ana.email_pending) == ("ana@example.org", None)


def test_google_leaves_an_address_the_player_set_alone(storage):
    ana = accounts.create_account(storage, "ana", PASSWORD)
    storage.accounts.set_email(ana.id, email="mine@example.org", email_pending=None)
    identities.link(storage, ana.id, ANA_GOOGLE, NOW)
    assert storage.accounts.get(ana.id).email == "mine@example.org"
    storage.accounts.set_email(ana.id, email=None, email_pending="typed@example.org")
    identities.log_in(storage, ANA_GOOGLE)
    ana = storage.accounts.get(ana.id)
    assert (ana.email, ana.email_pending) == (None, "typed@example.org")


def test_a_google_sign_up_has_its_address_confirmed(storage):
    cy = identities.sign_up(storage, Claims("google", "2", "cyra@gmail.com"), "cyra", NOW)
    assert storage.accounts.get(cy.id).email == "cyra@gmail.com"
    unverified = identities.sign_up(storage, Claims("google", "3"), "dax", NOW)
    assert storage.accounts.get(unverified.id).email is None


def test_a_google_login_brings_back_no_address_the_player_removed(storage):
    """Only linking and signing up fill the address: a login leaves a removed one removed (DEL-314)."""
    ana = accounts.create_account(storage, "ana", PASSWORD)
    identities.link(storage, ana.id, ANA_GOOGLE, NOW)
    assert storage.accounts.get(ana.id).email == "ana@example.org"
    storage.accounts.set_email(ana.id, email=None, email_pending=None)  # Remove
    assert identities.log_in(storage, ANA_GOOGLE).email is None
    assert storage.accounts.get(ana.id).email is None
