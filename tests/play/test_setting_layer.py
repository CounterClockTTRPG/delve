"""The setting layer (settings plan Task 4): the install's pages, overrides and facts and a campaign's proposals over the
shipped setting, with DM-only content kept to the DM. Greyhawk over the tiny reference, and the fake setting."""

from dataclasses import replace

import pytest

from delve.domain.reference import LoreFact
from delve.domain.setting_content import Proposal, SettingAddition, SettingFact
from delve.domain.world import WorldMapSource
from delve.play.setting_layer import SettingLayer, layer_for
from delve.setting.fake import FakeSetting
from delve.setting.setting import Setting
from delve.storage import open_storage
from tests.fixtures.rulesets import setting
from tests.play.conftest import crypt_campaign

SECRET = "SECRET-XYZZY"


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


def addition(title, text, **fields):
    return SettingAddition("greyhawk", title, text=text, **fields)


def propose(storage, campaign, kind, **fields):
    return storage.proposals.add(Proposal(0, "greyhawk", campaign.id, kind, **fields))


def test_the_layer_is_a_setting(storage, greyhawk):
    layer = SettingLayer(greyhawk, storage)
    members = ("id", "title", "kinds", "lookup", "calendar", "world_maps", "search", "page", "lore_facts")
    assert all(hasattr(layer, name) for name in members) and all(hasattr(Setting, name) for name in members[2:])
    assert (layer.id, layer.title, layer.kinds(), layer.calendar()) == (
        "greyhawk",
        "Greyhawk",
        greyhawk.kinds(),
        greyhawk.calendar(),
    )
    assert layer_for(storage, None) is None
    seat = layer_for(storage, greyhawk, campaign_id="cmp_x")
    assert isinstance(seat, SettingLayer) and (seat.campaign_id, seat.dm) == ("cmp_x", False)


def test_an_addition_is_a_new_page(storage, greyhawk):
    layer = SettingLayer(greyhawk, storage, dm=True)
    assert layer.page("Saltmarsh") is None
    storage.setting_pages.put(
        addition("Saltmarsh", "A fishing town, see [[Hardby]].", kind="place", fields={"size": "Small"})
    )
    page = layer.page("  saltmarsh ")
    assert (page.title, page.kind, page.fields, page.text) == (
        "Saltmarsh",
        "place",
        {"size": "Small"},
        "A fishing town, see [[Hardby]].",
    )
    assert (page.origin, page.format, page.dm_only, page.campaign_id) == ("addition", "markdown", False, None)
    assert layer.addition("SALTMARSH").title == "Saltmarsh" and layer.shipped_page("Saltmarsh") is None
    storage.setting_pages.delete("greyhawk", "Saltmarsh")
    assert layer.page("Saltmarsh") is None


def test_an_override_replaces_the_shipped_page(storage, greyhawk):
    layer = SettingLayer(greyhawk, storage, dm=True)
    shipped = layer.page("Hardby")
    assert (shipped.origin, shipped.format) == ("shipped", "wiki")
    storage.setting_pages.put(addition("Hardby", "Ruled by the Despotrix.", kind="place", fields={"size": "Town"}))
    page = layer.page("hardby")
    assert (page.title, page.origin, page.format, page.text, page.fields) == (
        "Hardby",
        "override",
        "markdown",
        "Ruled by the Despotrix.",
        {"size": "Town"},
    )
    assert page.categories == shipped.categories
    assert layer.shipped_page("Hardby") == shipped
    storage.setting_pages.delete("greyhawk", "Hardby")
    assert layer.page("Hardby") == shipped


def test_an_override_is_reached_through_a_redirect(storage, greyhawk):
    layer = SettingLayer(greyhawk, storage, dm=True)
    storage.setting_pages.put(addition("Mordenkainen", "The archmage, overridden."))
    page = layer.page("Mordy")  # Mordy → Mordenkainen the Mage → Mordenkainen
    assert (page.title, page.origin, page.text) == ("Mordenkainen", "override", "The archmage, overridden.")
    assert layer.addition("Mordy").title == "Mordenkainen"


def plant_secrets(storage, campaign):
    """A DM-only section of an ordinary page, a DM-only page, a DM-only fact and a DM-only proposal (a fact and a page
    edit), each holding the secret; and their open neighbours."""
    storage.setting_pages.put(
        addition("Saltmarsh", f"A fishing town.\n\n::: dm\nThe smugglers' cove {SECRET} xyzzyword.\n:::\n\nNets dry.")
    )
    storage.setting_pages.put(addition("Hidden Keep", f"The keep of {SECRET}.", kind="place", dm_only=True))
    storage.setting_facts.add(SettingFact(0, "greyhawk", f"The Despotrix is {SECRET}.", "greyhawk", dm_only=True))
    storage.setting_facts.add(SettingFact(0, "greyhawk", "Hardby has eight gates.", "greyhawk"))
    propose(storage, campaign, "fact", text=f"Iuz fears {SECRET}.", dm_only=True)
    propose(storage, campaign, "edit", title="Hardby", text=f"The harbour hides {SECRET}.", dm_only=True)
    propose(
        storage, campaign, "page", title="Cove of Bones", text=f"Bones of {SECRET}.", page_kind="place", dm_only=True
    )


def everything(layer):
    """Every text the layer answers for the planted titles, words and kinds."""
    texts = []
    for title in ("Saltmarsh", "Hidden Keep", "Hardby", "Cove of Bones"):
        page = layer.page(title)
        texts.append(repr(page))
    for query in ("xyzzyword", "SECRET-XYZZY", "keep", "Despotrix", "Iuz", "harbour", "Bones", "fishing"):
        texts.append(repr(layer.search(query, 50)))
    for kind in layer.kinds():
        texts.append(repr(layer.lookup(kind, "", 50)))
    texts.append(repr(layer.facts()))
    for seed in range(20):
        texts.append(repr(layer.lore_facts(100, seed=seed)))
    return "\n".join(texts)


def test_a_seat_never_reads_dm_only(storage, greyhawk, campaigns):
    campaign, _ = campaigns
    plant_secrets(storage, campaign)
    seat = SettingLayer(greyhawk, storage, campaign_id=campaign.id)
    assert SECRET not in everything(seat)
    assert seat.page("Saltmarsh").text == "A fishing town.\n\nNets dry."
    assert seat.page("Hidden Keep") is None and seat.page("Cove of Bones") is None
    assert seat.search("xyzzyword") == []
    (hit,) = seat.search("fishing")
    assert "<<fishing>>" in hit.text and SECRET not in hit.text
    assert [fact.text for fact in seat.facts()] == ["Hardby has eight gates."]
    assert seat.page("Hardby").origin == "shipped"

    dm = SettingLayer(greyhawk, storage, campaign_id=campaign.id, dm=True)
    seen = everything(dm)
    for planted in ("xyzzyword", "The keep of", "The Despotrix is", "Iuz fears", "The harbour hides", "Bones of"):
        assert planted in seen
    assert SECRET in dm.page("Hidden Keep").text and dm.page("Hidden Keep").dm_only
    assert dm.search("xyzzyword")[0].title == "Saltmarsh"
    hardby = dm.page("Hardby")
    assert hardby.format == "markdown" and hardby.text.endswith(f"::: dm\nThe harbour hides {SECRET}.\n:::")
    assert hardby.text.startswith("**Hardby** is a port")  # the wiki as Markdown first


def test_a_dm_only_override_leaves_the_seat_the_shipped_page(storage, greyhawk):
    storage.setting_pages.put(addition("Hardby", f"The DM's Hardby: {SECRET}.", dm_only=True))
    seat = SettingLayer(greyhawk, storage)
    page = seat.page("Hardby")
    assert (page.origin, page.format) == ("shipped", "wiki") and SECRET not in page.text
    assert [hit.origin for hit in seat.search("Hardby")] == ["shipped"]
    assert [(hit.title, hit.origin) for hit in seat.lookup("place", "hard")] == [("Hardby", "shipped")]
    dm = SettingLayer(greyhawk, storage, dm=True)
    assert dm.page("Hardby").origin == "override" and dm.page("Hardby").dm_only
    assert [(hit.title, hit.origin) for hit in dm.lookup("place", "hard")] == [("Hardby", "override")]


@pytest.mark.parametrize("mode", ["append", "replace"])
def test_an_edit_never_makes_a_seat_a_page_it_cant_see(storage, greyhawk, campaigns, mode):
    """An open edit of a DM-only page (an addition, an override, a campaign's new page) leaves a seat no page, or the
    shipped one (plan decision 10); the DM reads the edit on the DM-only page."""
    a, _ = campaigns
    storage.setting_pages.put(addition("Hidden Keep", f"The keep of {SECRET}.", kind="place", dm_only=True))
    storage.setting_pages.put(addition("Hardby", f"The DM's Hardby: {SECRET}.", dm_only=True))
    propose(storage, a, "page", title="Lair", text=f"The lair of {SECRET}.", page_kind="place", dm_only=True)
    for title in ("Hidden Keep", "Hardby", "Lair"):
        propose(storage, a, "edit", title=title, text="Its gate is open.", mode=mode)
    seat = SettingLayer(greyhawk, storage, campaign_id=a.id)
    assert seat.page("Hidden Keep") is None and seat.page("Lair") is None
    hardby = seat.page("Hardby")
    assert (hardby.origin, hardby.format, hardby.campaign_id) == ("shipped", "wiki", None)
    assert "Its gate is open." not in hardby.text and SECRET not in everything(seat)
    dm = SettingLayer(greyhawk, storage, campaign_id=a.id, dm=True)
    for title in ("Hidden Keep", "Hardby", "Lair"):
        assert dm.page(title).text.endswith("Its gate is open."), title


def test_a_seats_fact_query_matches_what_it_reads(storage, greyhawk, campaigns):
    a, _ = campaigns
    propose(storage, a, "fact", text="Hardby has a gate.\n\n::: dm\nxyzzyword\n:::")
    storage.setting_facts.add(SettingFact(0, "greyhawk", "Hardby has a tower.\n\n::: dm\nxyzzyword\n:::"))
    seat = SettingLayer(greyhawk, storage, campaign_id=a.id)
    assert seat.facts("xyzzyword") == []
    assert [fact.text for fact in seat.facts("hardby")] == ["Hardby has a gate.", "Hardby has a tower."]
    dm = SettingLayer(greyhawk, storage, campaign_id=a.id, dm=True)
    assert len(dm.facts("xyzzyword")) == 2


def test_hits_say_which_are_dm_only(storage, greyhawk, campaigns):
    a, _ = campaigns
    plant_secrets(storage, a)
    dm = SettingLayer(greyhawk, storage, campaign_id=a.id, dm=True)
    flags = {hit.title: hit.dm_only for hit in dm.search(SECRET, 50)}
    assert flags["Hidden Keep"] and flags["Cove of Bones"] and not flags["Saltmarsh"]
    assert all(flag for title, flag in flags.items() if title.startswith(("The Despotrix", "Iuz fears")))
    places = {hit.title: hit.dm_only for hit in dm.lookup("place", "", 50)}
    assert places["Hidden Keep"] and places["Cove of Bones"] and not places["Hardby"]


def test_lore_facts_unseeded_draw_from_the_shipped_setting(storage, greyhawk):
    storage.setting_facts.add(SettingFact(0, "greyhawk", "Hardby has eight gates.", "greyhawk"))
    layer = SettingLayer(greyhawk, storage)
    drawn = layer.lore_facts(3)
    assert len(drawn) == 3 and all(isinstance(fact, LoreFact) for fact in drawn)
    assert "Hardby has eight gates." in {fact.text for fact in layer.lore_facts(100)}
    assert len({tuple(fact.text for fact in layer.lore_facts(100)) for _ in range(10)}) > 1  # a fresh draw each time


def test_a_proposal_applies_to_its_campaign_only(storage, greyhawk, campaigns):
    a, b = campaigns
    fact = propose(storage, a, "fact", text="Hardby's Despotrix has a twin.", category="greyhawk")
    edit = propose(storage, a, "edit", title="hardby", text="Its harbour silted up.")
    new = propose(storage, a, "page", title="Cove of Bones", text="A cove [[Hardby]] fears.", page_kind="place")
    in_a, in_b = (SettingLayer(greyhawk, storage, campaign_id=c.id) for c in (a, b))

    def shows(layer):
        return (
            "Hardby's Despotrix has a twin." in [f.text for f in layer.facts()],
            layer.page("Hardby").text.endswith("Its harbour silted up."),
            layer.page("Cove of Bones") is not None,
        )

    assert shows(in_a) == (True, True, True) and shows(in_b) == (False, False, False)
    assert in_a.facts()[-1] == LoreFact(fact.id, fact.text, "greyhawk", "campaign")
    page = in_a.page("Cove of Bones")
    assert (page.origin, page.campaign_id, page.kind, page.format) == ("proposal", a.id, "place", "markdown")
    assert in_a.page("Hardby").campaign_id == a.id and in_a.page("Hardby").origin == "shipped"
    assert SettingLayer(greyhawk, storage, dm=True).page("Cove of Bones") is None  # the organisers': no campaign

    for proposal in (fact, edit, new):
        storage.proposals.put(replace(proposal, status="rejected"))
    assert shows(in_a) == (True, True, True) and shows(in_b) == (False, False, False)

    for proposal in (fact, edit, new):
        storage.proposals.put(replace(proposal, status="accepted"))
    assert shows(in_a) == (False, False, False)


def test_a_replace_edit_and_a_dm_only_replace(storage, greyhawk, campaigns):
    a, _ = campaigns
    propose(storage, a, "edit", title="Hardby", text="Hardby is gone.", mode="replace")
    seat = SettingLayer(greyhawk, storage, campaign_id=a.id)
    assert (seat.page("Hardby").text, seat.page("Hardby").format) == ("Hardby is gone.", "markdown")
    propose(storage, a, "edit", title="Hardby", text=f"Hardby is {SECRET}.", mode="replace", dm_only=True)
    assert seat.page("Hardby").text == "Hardby is gone."
    assert SettingLayer(greyhawk, storage, campaign_id=a.id, dm=True).page("Hardby").text == f"Hardby is {SECRET}."


def test_search_order_and_replaced_hits(storage, greyhawk, campaigns):
    a, _ = campaigns
    storage.setting_pages.put(addition("Hardby", "The eight gates of Hardby, overridden."))
    storage.setting_pages.put(addition("Gatehouse", "Eight gates and one house."))
    storage.setting_facts.add(SettingFact(0, "greyhawk", "Eight gates guard every port of the Wild Coast.", "greyhawk"))
    propose(storage, a, "page", title="Eightfold Gate", text="The eight gates' own god.")
    layer = SettingLayer(greyhawk, storage, campaign_id=a.id)
    hits = layer.search("eight gates")
    assert [(hit.title, hit.origin) for hit in hits] == [
        ("Eightfold Gate", "proposal"),
        ("Gatehouse", "addition"),
        ("Hardby", "override"),
        ("Eight gates guard every port of the Wild Coast.", "fact"),
    ]
    assert "<<eight>>" in hits[1].text.casefold() and "<<gates>>" in hits[1].text
    fact = hits[-1]
    assert (fact.kind, fact.key.split(":")[:2]) == ("fact", ["fact", "install"])
    assert [hit.title for hit in layer.search("eight")][-1] == "Eight gates guard every port of the Wild Coast."
    assert "Circle of Eight" in [hit.title for hit in layer.search("eight")]
    assert [hit.origin for hit in layer.search("eight") if hit.title == "Hardby"] == ["override"]
    assert len(layer.search("eight", limit=2)) == 2
    assert len(layer.search("eight", limit=500)) <= 50


def test_search_takes_any_input(storage, greyhawk):
    storage.setting_pages.put(addition("Ærdy", "The Great Kingdom of Ūrnst and Ærdy."))
    layer = SettingLayer(greyhawk, storage)
    for query in ('"', "*", "AND", "-", "%", "_", "", "'", "eight AND"):
        assert isinstance(layer.search(query), list)
    assert layer.search("%") == [] and layer.search("_") == []
    assert [hit.title for hit in layer.search("ūrnst")] == ["Ærdy"]
    assert [hit.title for hit in layer.search("ærdy")] == ["Ærdy"]


def test_lookup_takes_additions_of_the_kind(storage, greyhawk):
    storage.setting_pages.put(addition("Saltmarsh", "A town.", kind="place", fields={"size": "Small"}))
    storage.setting_pages.put(addition("Hardby", "Overridden.", kind="place"))
    storage.setting_pages.put(addition("St. Kargoth", "A death knight.", kind="character"))
    layer = SettingLayer(greyhawk, storage)
    hits = layer.lookup("place", "")
    assert [(hit.title, hit.origin) for hit in hits] == [
        ("Hardby", "override"),
        ("Nyr Dyv", "shipped"),
        ("Saltmarsh", "addition"),
    ]
    assert hits[2].text == "size: Small"
    assert [hit.title for hit in layer.lookup("place", "SALT")] == ["Saltmarsh"]
    assert len(layer.lookup("place", "", limit=2)) == 2
    with pytest.raises(ValueError, match="unknown kind"):
        layer.lookup("spell", "")


def test_lore_facts_mixes_and_is_seeded(storage, greyhawk):
    storage.setting_facts.add(SettingFact(0, "greyhawk", "Hardby has eight gates.", "greyhawk"))
    layer = SettingLayer(greyhawk, storage)
    assert layer.lore_facts(3, seed=7) == layer.lore_facts(3, seed=7)
    assert len(layer.lore_facts(3, seed=7)) == 3
    drawn = {fact.text for seed in range(30) for fact in layer.lore_facts(2, seed=seed)}
    assert "Hardby has eight gates." in drawn
    assert any(fact.source == "install" for fact in layer.lore_facts(100, seed=1))
    assert {fact.category for fact in layer.lore_facts(100, category="history", seed=1)} == {"history"}


def test_the_fake_setting_is_layered_too(storage):
    layer = SettingLayer(FakeSetting(), storage)
    storage.setting_pages.put(SettingAddition("fake-setting", "Nulb", "place", text="A den of thieves."))
    assert layer.page("Nulb").origin == "addition" and layer.page("Hommlet").origin == "shipped"
    assert [hit.title for hit in layer.lookup("place", "")] == ["Hommlet", "Nulb", "Verbobonc"]
    assert layer.world_maps() == ()


def test_world_maps_fall_back_to_the_shipped_ones(storage, greyhawk):
    layer = SettingLayer(greyhawk, storage)
    assert [m.name for m in layer.world_maps()] == ["greyhawk-region"]
    geo = {"type": "FeatureCollection", "features": []}
    storage.setting_maps.put("greyhawk", WorldMapSource("flanaess", "The Flanaess", "", geo=geo, status="review"))
    assert [m.name for m in layer.world_maps()] == ["greyhawk-region"]
    storage.setting_maps.put("greyhawk", WorldMapSource("oerik", "Oerik", "", geo=geo))
    assert [m.name for m in layer.world_maps()] == ["oerik"]
