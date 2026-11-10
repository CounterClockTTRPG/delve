"""The DM's lore tools (plan 6 Task 3): the setting's wiki (`setting_lookup`, `setting_search`), read through the setting
layer (settings plan Task 5) with the install's pages and facts and this campaign's proposals, the campaign's own facts
(`add_fact`, `facts`) and a search of what the campaign wrote down (`search_campaign`), on the double of the Greyhawk pack."""

import pytest

from delve.dm.tools.lore import PROPOSAL_APPLIES
from delve.domain.setting_content import Proposal, SettingAddition, SettingFact
from delve.play.context import context_for
from delve.play.setting_layer import SettingLayer
from tests.fixtures.rulesets import osric_catalogs


def test_the_context_names_the_campaigns_setting(storage, campaign):
    ctx = context_for(storage, campaign.id, "beat-1", catalogs=osric_catalogs())
    assert isinstance(ctx.setting, SettingLayer) and (ctx.setting.campaign_id, ctx.setting.dm) == (campaign.id, True)
    assert ctx.setting.shipped.id == "greyhawk" and ctx.setting.shipped.store is not None
    other = storage.campaigns.create("Plain", campaign.module_id, campaign.revision, setting="", ruleset="osric")
    assert context_for(storage, other.id, "beat-1", catalogs=osric_catalogs()).setting is None


def test_setting_lookup_lists_a_kinds_rows(call):
    found = call("setting_lookup", kind="deity", query="")
    assert found["kind"] == "deity" and found["count"] == len(found["results"]) > 1
    assert "page" not in found
    assert all(set(row) == {"title", "text", "origin", "dm_only"} for row in found["results"])
    assert {row["origin"] for row in found["results"]} == {"shipped"}


def test_setting_lookup_of_one_hit_returns_its_page(call, storage):
    found = call("setting_lookup", kind="place", query="Hardby")
    assert [row["title"] for row in found["results"]] == ["Hardby"]
    page = found["page"]
    assert page["title"] == "Hardby" and page["kind"] == "settlements" and page["origin"] == "shipped"
    assert page["fields"]["size"] == "Large town" and not page.get("truncated")
    storage.setting_pages.put(SettingAddition("greyhawk", "Hardby", text="The Gynarchy's own words. " * 400))
    long = call("setting_lookup", kind="place", query="Hardby")["page"]
    assert len(long["text"]) == 4000 and long["truncated"] is True  # a longer page is cut


def test_setting_lookup_refuses_an_unknown_kind_with_the_kinds(call):
    refused = call("setting_lookup", kind="spell", query="sleep")
    assert refused["error"] == "Greyhawk has no kind 'spell'."
    assert "place, realm, deity, character" in refused["hint"]


def test_setting_lookup_finds_nothing(call):
    assert call("setting_lookup", kind="deity", query="Zzyzx") == {
        "kind": "deity",
        "query": "Zzyzx",
        "count": 0,
        "results": [],
    }


def test_lookup_finds_an_addition_with_its_origin(call, storage):
    storage.setting_pages.put(
        SettingAddition("greyhawk", "Zzyzx Hollow", "place", {"size": "Hamlet"}, "A hollow by [[Hardby]].")
    )
    storage.setting_pages.put(SettingAddition("greyhawk", "Hardby", text="The Gynarchy's own words."))
    found = call("setting_lookup", kind="place", query="Zzyzx")
    assert found["results"] == [
        {"title": "Zzyzx Hollow", "text": "size: Hamlet", "origin": "addition", "dm_only": False}
    ]
    assert found["page"]["origin"] == "addition" and found["page"]["text"] == "A hollow by [[Hardby]]."
    hardby = call("setting_lookup", kind="place", query="Hardby")
    assert [(row["title"], row["origin"]) for row in hardby["results"]] == [("Hardby", "override")]
    assert hardby["page"]["origin"] == "override" and hardby["page"]["text"] == "The Gynarchy's own words."


def test_lookup_finds_this_campaigns_proposal(call, storage, campaign):
    storage.proposals.add(
        Proposal(0, "greyhawk", campaign.id, "page", "Zzyzx Hollow", "Where the party camped.", page_kind="place")
    )
    found = call("setting_lookup", kind="place", query="Zzyzx")
    assert [(row["title"], row["origin"]) for row in found["results"]] == [("Zzyzx Hollow", "proposal")]
    assert found["page"]["origin"] == "proposal" and found["page"]["text"] == "Where the party camped."
    storage.proposals.add(
        Proposal(0, "greyhawk", campaign.id, "edit", "Hardby", "The party freed the Gynarch.", mode="replace")
    )
    hardby = call("setting_lookup", kind="place", query="Hardby")["page"]
    assert (hardby["origin"], hardby["text"]) == ("proposal", "The party freed the Gynarch.")


def test_search_finds_this_campaigns_proposal(call, host, storage, campaign):
    storage.proposals.add(
        Proposal(0, "greyhawk", campaign.id, "page", "Zzyzx Hollow", "Where the Zzyzx sleeps.", page_kind="place")
    )
    storage.proposals.add(Proposal(0, "greyhawk", campaign.id, "fact", text="The Zzyzx owes the party a boon."))
    storage.setting_facts.add(SettingFact(0, "greyhawk", "Zzyzx bells ring at dusk in Hardby."))
    found = call("setting_search", query="zzyzx")
    hits = [(hit["title"], hit["kind"], hit["origin"]) for hit in found["results"]]
    assert hits[0] == ("Zzyzx Hollow", "place", "proposal")
    assert sorted(hits[1:]) == [
        ("The Zzyzx owes the party a boon.", "fact", "fact"),
        ("Zzyzx bells ring at dusk in Hardby.", "fact", "fact"),
    ]
    assert "<<zzyzx>>" in found["results"][0]["excerpt"].casefold()
    other = storage.campaigns.create(
        "Wednesday", campaign.module_id, campaign.revision, setting="greyhawk", ruleset="osric"
    )
    elsewhere = host.call(other.id, "beat-1", "setting_search", {"query": "zzyzx"})
    assert [hit["title"] for hit in elsewhere["results"]] == ["Zzyzx bells ring at dusk in Hardby."]


def test_dm_only_pages_and_facts_are_marked_for_the_dm(call, storage, campaign):
    storage.setting_pages.put(SettingAddition("greyhawk", "Zzyzx Keep", "place", text="The cult's keep.", dm_only=True))
    storage.setting_facts.add(SettingFact(0, "greyhawk", "Zzyzx bells ring for the cult.", dm_only=True))
    storage.setting_facts.add(SettingFact(0, "greyhawk", "Zzyzx bells ring at dusk."))
    found = call("setting_lookup", kind="place", query="Zzyzx")
    assert found["results"][0]["dm_only"] is True and found["page"]["dm_only"] is True
    assert call("setting_lookup", kind="place", query="Hardby")["page"]["dm_only"] is False
    hits = {hit["title"]: hit["dm_only"] for hit in call("setting_search", query="zzyzx")["results"]}
    assert hits == {"Zzyzx Keep": True, "Zzyzx bells ring for the cult.": True, "Zzyzx bells ring at dusk.": False}


def test_setting_search(call):
    found = call("setting_search", query="Circle of Eight", limit=5)
    assert found["count"] == len(found["results"]) <= 5
    assert "Circle of Eight" in [hit["title"] for hit in found["results"]]
    assert all("<<" in hit["excerpt"] for hit in found["results"])
    assert {hit["origin"] for hit in found["results"]} == {"shipped"}


@pytest.mark.parametrize(
    ("tool", "args"),
    [("setting_lookup", {"kind": "place", "query": "Hardby"}), ("setting_search", {"query": "Hardby"})],
)
def test_lookups_without_a_setting_are_refused_with_a_hint(host, storage, campaign, tool, args):
    plain = storage.campaigns.create("Plain", campaign.module_id, campaign.revision, setting="", ruleset="osric")
    refused = host.call(plain.id, "beat-1", tool, args)
    assert refused["error"] == "This campaign has no setting."
    assert "rules_lookup" in refused["hint"]


def test_propose_fact_applies_to_this_campaign_at_once(call, host, storage, campaign):
    proposed = call("propose_fact", text="The Zzyzx of Hardby is slain.", category="history")
    assert proposed["applies"] == PROPOSAL_APPLIES
    assert proposed["proposal"] == {
        "id": proposed["proposal"]["id"],
        "kind": "fact",
        "title": "",
        "status": "pending",
        "dm_only": False,
    }
    stored = storage.proposals.get(proposed["proposal"]["id"])
    assert (stored.campaign_id, stored.category) == (campaign.id, "history")
    found = call("setting_search", query="zzyzx")
    assert [(hit["title"], hit["kind"]) for hit in found["results"]] == [("The Zzyzx of Hardby is slain.", "fact")]
    other = storage.campaigns.create(
        "Wednesday", campaign.module_id, campaign.revision, setting="greyhawk", ruleset="osric"
    )
    assert host.call(other.id, "beat-1", "setting_search", {"query": "zzyzx"})["results"] == []


def test_propose_page_on_an_existing_page_is_an_edit(call, storage):
    edit = call("propose_page", title="hardby", text="The party freed the Gynarch.", dm_only=True)
    assert {key: edit["proposal"][key] for key in ("kind", "title", "status", "dm_only")} == {
        "kind": "edit",
        "title": "Hardby",
        "status": "pending",
        "dm_only": True,
    }
    assert storage.proposals.get(edit["proposal"]["id"]).mode == "append"
    page = call("propose_page", title="Zzyzx Hollow", text="Where the party camped.", kind="place")
    assert (page["proposal"]["kind"], page["proposal"]["title"]) == ("page", "Zzyzx Hollow")
    assert storage.proposals.get(page["proposal"]["id"]).page_kind == "place"
    assert call("setting_lookup", kind="place", query="Zzyzx")["page"]["text"] == "Where the party camped."
    refused = call("propose_page", title="Zzyzx Glen", text="A glen.", kind="spell")
    assert refused["error"] == "Greyhawk has no kind 'spell'." and "place, realm" in refused["hint"]
    assert call("propose_page", title="Hardby", text=" ")["error"] == "A proposal needs its text."
    assert call("propose_fact", text="")["error"] == "A proposal needs its text."
    assert "error" in call("propose_page", title="Hardby", text="x", mode="overwrite")


def test_proposals_of_the_same_page_merge(call, storage, campaign):
    first = call("propose_page", title="Hardby", text="The party freed the Gynarch.")
    again = call("propose_page", title="Hardby", text="The Gynarch rewarded them.")
    assert again["proposal"]["id"] == first["proposal"]["id"]
    [pending] = storage.proposals.list("greyhawk", campaign_id=campaign.id, status="pending")
    assert pending.text == "The party freed the Gynarch.\n\nThe Gynarch rewarded them."


@pytest.mark.parametrize(
    ("tool", "args"),
    [("propose_fact", {"text": "A fact."}), ("propose_page", {"title": "Hardby", "text": "A page."})],
)
def test_propose_without_a_setting_is_refused(host, storage, campaign, tool, args):
    plain = storage.campaigns.create("Plain", campaign.module_id, campaign.revision, setting="", ruleset="osric")
    refused = host.call(plain.id, "beat-1", tool, args)
    assert refused["error"] == "This campaign has no setting."
    assert storage.proposals.list("greyhawk") == []


def test_proposal_tools_are_the_dms(host):
    for name in ("propose_page", "propose_fact"):
        spec = host.spec(name)
        assert spec.mutates and not spec.player_visible
        assert "add_fact" in spec.description


def test_campaign_facts_round_trip(call, storage, campaign):
    first = call("add_fact", text="The party slew the ghoul of the crypt.", category="victory")
    assert first["fact"]["text"] == "The party slew the ghoul of the crypt." and first["fact"]["day"] == 1
    call("add_fact", text="Pippa owes the innkeeper ten gold.")
    assert [f["text"] for f in call("facts")["facts"]] == [
        "The party slew the ghoul of the crypt.",
        "Pippa owes the innkeeper ten gold.",
    ]
    assert [f["category"] for f in call("facts", query="GHOUL")["facts"]] == ["victory"]
    assert storage.campaign_facts.list(campaign.id)[0].id == first["fact"]["id"]
    assert call("add_fact", text="  ")["error"] == "A fact needs its text."


def test_search_campaign_finds_the_story_notes_and_events(call, storage, campaign):
    storage.story.append(campaign.id, None, "dm_text", {"text": "Far below, the ghoul gnaws on old bones."})
    call("dm_note", text="The ghoul was once the sexton.")
    call("log_note", text="The party heard the ghoul.")
    found = call("search_campaign", query="GHOUL")
    sources = [hit["source"] for hit in found["results"]]
    assert sources[0].startswith("story #") and any(s.startswith("note ") for s in sources)
    assert any(s.startswith("event #") for s in sources)
    assert "the ghoul gnaws" in found["results"][0]["excerpt"]
    assert all(len(hit["excerpt"]) <= 102 for hit in found["results"])  # 100 characters and two ellipses


def test_search_campaign_caps_its_hits_and_cuts_around_the_match(call, storage, campaign):
    filler = "x" * 200
    for n in range(25):
        storage.story.append(campaign.id, None, "dm_text", {"text": f"{filler} wyvern {n} {filler}"})
    found = call("search_campaign", query="wyvern")
    assert found["count"] == len(found["results"]) == 20
    excerpt = found["results"][0]["excerpt"]
    # Newest first (DEL-172): before, the DM saw only the oldest twenty, story #1-20, of a common word.
    assert excerpt.startswith("…") and excerpt.endswith("…") and "wyvern 24" in excerpt
    assert found["cut"] is True and "more hits" in found["hint"]
    assert call("search_campaign", query=" ")["error"] == "Search for some words."


def test_search_campaign_gives_each_source_its_share(call, storage, campaign):
    """Many story hits don't hide the notes and the events (DEL-172)."""
    for n in range(30):
        storage.story.append(campaign.id, None, "dm_text", {"text": f"The basilisk stares {n}."})
    call("dm_note", text="The basilisk is blind in one eye.")
    call("log_note", text="The party fled the basilisk.")
    found = call("search_campaign", query="basilisk")
    sources = [hit["source"].split()[0] for hit in found["results"]]
    notes, events = sources.count("note"), sources.count("event")
    assert notes == len(storage.notes.list(campaign.id)) >= 1 and events >= 1
    assert found["count"] == 20 and sources.count("story") == 20 - notes - events and found["cut"] is True


def test_search_campaign_says_when_nothing_was_cut(call, storage, campaign):
    storage.story.append(campaign.id, None, "dm_text", {"text": "A 100% chance of rain_fall."})
    storage.story.append(campaign.id, None, "dm_text", {"text": "A 100 chance of rainfall."})
    found = call("search_campaign", query="100% chance of rain_")
    assert [hit["excerpt"] for hit in found["results"]] == ["A 100% chance of rain_fall."]
    assert found["cut"] is False and "hint" not in found
