"""The DM's proposals to the setting (settings plan Task 8): proposed and merged, edited, accepted into the install's
additions and facts, or rejected and kept for their campaign. Greyhawk over the tiny reference."""

import pytest

from delve.domain.setting_content import SettingAddition, SettingFact
from delve.play import proposals
from delve.play.proposals import ProposalRefused
from delve.play.setting_layer import SettingLayer
from delve.storage import open_storage
from tests.fixtures.rulesets import setting
from tests.play.conftest import crypt_campaign


@pytest.fixture
def storage(reference_config):
    """The storage in the data dir of the tiny reference."""
    opened = open_storage(reference_config)
    yield opened
    opened.close()


@pytest.fixture
def greyhawk():
    return setting("greyhawk")


@pytest.fixture
def campaigns(storage):
    return crypt_campaign(storage, setting="greyhawk"), crypt_campaign(storage, setting="greyhawk")


def dms(storage, greyhawk, campaign) -> SettingLayer:
    """The DM's layer of `campaign`."""
    return SettingLayer(greyhawk, storage, campaign_id=campaign.id, dm=True)


def organisers(storage, greyhawk) -> SettingLayer:
    return SettingLayer(greyhawk, storage, dm=True)


def test_propose_page_is_an_edit_of_a_page_that_exists(storage, greyhawk, campaigns):
    a, _ = campaigns
    edit = proposals.propose_page(storage, dms(storage, greyhawk, a), a.id, "  hardby ", "The Despotrix fell.")
    assert (edit.kind, edit.title, edit.mode, edit.status, edit.setting) == (
        "edit",
        "Hardby",
        "append",
        "pending",
        "greyhawk",
    )
    new = proposals.propose_page(storage, dms(storage, greyhawk, a), a.id, "Saltmarsh", "A town.", kind="place")
    assert (new.kind, new.title, new.page_kind) == ("page", "Saltmarsh", "place")


def test_proposals_of_the_same_page_merge(storage, greyhawk, campaigns):
    a, b = campaigns
    layer = dms(storage, greyhawk, a)
    first = proposals.propose_page(storage, layer, a.id, "Hardby", "The Despotrix fell.")
    second = proposals.propose_page(storage, layer, a.id, "HARDBY", "A new tower stands.", dm_only=True)
    assert second.id == first.id and second.text == "The Despotrix fell.\n\nA new tower stands." and second.dm_only
    replaced = proposals.propose_page(storage, layer, a.id, "Hardby", "Ash and ruin.", mode="replace")
    assert (replaced.id, replaced.text, replaced.mode) == (first.id, "Ash and ruin.", "replace")
    # A new page proposed twice is one page; its text is the latest.
    page = proposals.propose_page(storage, layer, a.id, "Saltmarsh", "A town.")
    again = proposals.propose_page(storage, layer, a.id, "saltmarsh", "A fishing town.")
    assert (again.id, again.kind, again.text) == (page.id, "page", "A fishing town.")
    # Another campaign's proposal, and facts, never merge.
    other = proposals.propose_page(storage, dms(storage, greyhawk, b), b.id, "Hardby", "Quiet.")
    assert other.id != first.id
    facts = [proposals.propose_fact(storage, layer, a.id, "Iuz stirs.") for _ in range(2)]
    assert facts[0].id != facts[1].id and facts[0].kind == "fact"
    assert len(storage.proposals.list("greyhawk", campaign_id=a.id)) == 4


@pytest.mark.parametrize("mode", ["append", "replace"])
def test_an_edit_of_a_dm_only_page_is_dm_only(storage, greyhawk, campaigns, mode):
    a, _ = campaigns
    storage.setting_pages.put(SettingAddition("greyhawk", "Hidden Keep", kind="place", text="A keep.", dm_only=True))
    layer = dms(storage, greyhawk, a)
    edit = proposals.propose_page(storage, layer, a.id, "Hidden Keep", "Its gate is open.", mode=mode)
    assert (edit.kind, edit.dm_only) == ("edit", True)
    lair = proposals.propose_page(storage, layer, a.id, "Lair", "The cult's lair.", dm_only=True)
    proposals.reject(storage, lair.id)  # a rejected page stays its campaign's: an edit of it is no new page
    edit = proposals.propose_page(storage, layer, a.id, "Lair", "Bones.", mode=mode)
    assert (edit.kind, edit.dm_only) == ("edit", True)


def test_accept_a_fact(storage, greyhawk, campaigns):
    a, _ = campaigns
    p = proposals.propose_fact(
        storage, dms(storage, greyhawk, a), a.id, "Iuz stirs.", category="greyhawk", dm_only=True
    )
    fact = proposals.accept(storage, organisers(storage, greyhawk), p.id)
    assert isinstance(fact, SettingFact)
    assert (fact.setting, fact.text, fact.category, fact.dm_only) == ("greyhawk", "Iuz stirs.", "greyhawk", True)
    accepted = storage.proposals.get(p.id)
    assert accepted.status == "accepted" and accepted.decided_at


def test_accept_a_page(storage, greyhawk, campaigns):
    a, b = campaigns
    p = proposals.propose_page(storage, dms(storage, greyhawk, a), a.id, "Saltmarsh", "A town.", kind="place")
    assert SettingLayer(greyhawk, storage, campaign_id=b.id).page("Saltmarsh") is None
    added = proposals.accept(storage, organisers(storage, greyhawk), p.id)
    assert isinstance(added, SettingAddition)
    assert (added.title, added.kind, added.text, added.dm_only) == ("Saltmarsh", "place", "A town.", False)
    page = SettingLayer(greyhawk, storage, campaign_id=b.id).page("Saltmarsh")
    assert (page.origin, page.text) == ("addition", "A town."), "every campaign reads it now"


def test_accept_an_edit_of_the_shipped_page_makes_an_override(storage, greyhawk, campaigns):
    a, _ = campaigns
    p = proposals.propose_page(storage, dms(storage, greyhawk, a), a.id, "Hardby", "The Despotrix fell.", dm_only=True)
    added = proposals.accept(storage, organisers(storage, greyhawk), p.id)
    assert added.title == "Hardby" and not added.dm_only
    assert added.text.startswith("**Hardby** is a port") and added.text.endswith("::: dm\nThe Despotrix fell.\n:::")
    assert added.fields == greyhawk.page("Hardby").fields
    seat = SettingLayer(greyhawk, storage).page("Hardby")
    assert seat.origin == "override" and "Despotrix" not in seat.text


def test_accept_an_edit_appends_to_the_override(storage, greyhawk, campaigns):
    a, _ = campaigns
    p = proposals.propose_page(storage, dms(storage, greyhawk, a), a.id, "Mordy", "He retired.")
    assert p.title == "Mordenkainen"
    storage.setting_pages.put(SettingAddition("greyhawk", "Mordenkainen", text="An archmage, overridden."))
    added = proposals.accept(storage, organisers(storage, greyhawk), p.id)
    assert (added.title, added.text) == ("Mordenkainen", "An archmage, overridden.\n\nHe retired.")


def test_accept_a_replace_edit_and_one_whose_page_is_gone(storage, greyhawk, campaigns):
    a, _ = campaigns
    layer = dms(storage, greyhawk, a)
    replaced = proposals.propose_page(storage, layer, a.id, "Hardby", "Ash and ruin.", mode="replace")
    assert proposals.accept(storage, organisers(storage, greyhawk), replaced.id).text == "Ash and ruin."
    storage.setting_pages.put(SettingAddition("greyhawk", "Saltmarsh", text="A town."))
    gone = proposals.propose_page(storage, layer, a.id, "Saltmarsh", "It burned.")
    assert gone.kind == "edit"
    storage.setting_pages.delete("greyhawk", "Saltmarsh")
    assert proposals.accept(storage, organisers(storage, greyhawk), gone.id).text == "It burned."


def test_accept_a_page_whose_title_was_taken_is_409(storage, greyhawk, campaigns):
    a, _ = campaigns
    p = proposals.propose_page(storage, dms(storage, greyhawk, a), a.id, "Saltmarsh", "A town.")
    storage.setting_pages.put(SettingAddition("greyhawk", "saltmarsh", text="Ours."))
    with pytest.raises(ProposalRefused) as refused:
        proposals.accept(storage, organisers(storage, greyhawk), p.id)
    assert refused.value.status == 409
    assert str(refused.value) == "There is a page titled Saltmarsh already: edit the proposal's title, or reject it."
    assert storage.proposals.get(p.id).status == "pending"
    proposals.edit(storage, p.id, title="Saltmarsh Village")
    assert proposals.accept(storage, organisers(storage, greyhawk), p.id).title == "Saltmarsh Village"


def test_accept_twice_is_409(storage, greyhawk, campaigns):
    a, _ = campaigns
    layer = organisers(storage, greyhawk)
    p = proposals.propose_fact(storage, dms(storage, greyhawk, a), a.id, "Iuz stirs.")
    proposals.accept(storage, layer, p.id)
    for decide in (lambda: proposals.accept(storage, layer, p.id), lambda: proposals.reject(storage, p.id)):
        with pytest.raises(ProposalRefused) as refused:
            decide()
        assert refused.value.status == 409
    assert len(storage.setting_facts.list("greyhawk")) == 1
    with pytest.raises(ProposalRefused) as unknown:
        proposals.accept(storage, layer, 999)
    assert unknown.value.status == 404


def test_reject_keeps_it_for_its_campaign(storage, greyhawk, campaigns):
    a, b = campaigns
    p = proposals.propose_fact(storage, dms(storage, greyhawk, a), a.id, "Iuz stirs.")
    rejected = proposals.reject(storage, p.id)
    assert rejected.status == "rejected" and rejected.decided_at
    assert [f.text for f in SettingLayer(greyhawk, storage, campaign_id=a.id).facts()] == ["Iuz stirs."]
    assert SettingLayer(greyhawk, storage, campaign_id=b.id).facts() == []
    assert storage.setting_facts.list("greyhawk") == []
    with pytest.raises(ProposalRefused) as twice:
        proposals.reject(storage, p.id)
    assert twice.value.status == 409


def test_edit_then_accept(storage, greyhawk, campaigns):
    a, _ = campaigns
    p = proposals.propose_page(storage, dms(storage, greyhawk, a), a.id, "Saltmarsh", "A town.")
    edited = proposals.edit(storage, p.id, title="Saltmarsh", text="A fishing town.", page_kind="place", dm_only=True)
    assert (edited.text, edited.page_kind, edited.dm_only, edited.status) == (
        "A fishing town.",
        "place",
        True,
        "pending",
    )
    added = proposals.accept(storage, organisers(storage, greyhawk), p.id)
    assert (added.text, added.kind, added.dm_only) == ("A fishing town.", "place", True)
    with pytest.raises(ProposalRefused) as refused:
        proposals.edit(storage, p.id, text="Too late.")
    assert refused.value.status == 409
    with pytest.raises(ProposalRefused) as unknown:
        proposals.edit(storage, 999, text="Nobody's.")
    assert unknown.value.status == 404


def test_a_deleted_campaign_takes_its_pending_proposals(storage, greyhawk, campaigns):
    a, b = campaigns
    proposals.propose_fact(storage, dms(storage, greyhawk, a), a.id, "Iuz stirs.")
    kept = proposals.propose_fact(storage, dms(storage, greyhawk, b), b.id, "Vecna stirs.")
    storage.campaigns.delete(a.id)
    assert [p.id for p in storage.proposals.list("greyhawk")] == [kept.id]
