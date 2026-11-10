"""`play.house_rules`: the seed import from ttrpg2, a campaign's effective set, and the rules each phase hands the DM.

Delve's own seeds are ttrpg2's general rules; the homebrew races, classes and items are AD&D 2e's, in its pack, whose
tests import them. Here the homebrew a test needs is made in the library (`tests.fixtures.homebrew`)."""

import shutil
from dataclasses import replace
from pathlib import Path

import pytest

from delve.packs.loader import load_packs
from delve.play import characters
from delve.play import house_rules as hr
from delve.play.context import PlayError
from tests.fixtures.homebrew import HOMEBREW, seed_with_homebrew

SEED = hr.SEED_DIR
PACK_FIXTURES = Path(__file__).parent.parent / "fixtures" / "packs"
SEED_BUNDLE = "My table (from ttrpg2)"


def titles(rules) -> list[str]:
    return [r.title for r in rules]


def choose(storage, campaign, *, bundles=(), rules=()):
    hr.set_campaign_house_rules(
        storage, campaign.id, bundle_ids=[b.id for b in bundles], rule_ids=[r.id for r in rules]
    )


# --- the seed import -----------------------------------------------------------------------------------------------


def test_seed_import_splits_general_by_heading(storage):
    """ttrpg2's `general.md` has two headings with two bullets each: one rule per bullet, the heading its phase."""
    bundle = hr.import_house_rules(storage, SEED)
    general = [r for r in storage.house_rules.list() if r.kind == "general"]
    assert [(r.title, sorted(r.phases)) for r in general] == [
        ("Roll 4D6 for abilities", ["character-creation"]),
        ("Characters start at maximum HP for level 1", ["character-creation"]),
        ("Players can opt to reroll HP once", ["level-up"]),
        ("Ignore level caps", ["level-up"]),
    ]
    assert general[0].body_md == "Roll 4D6 for abilities, drop lowest. Repeat 3x and present to the player for selection."
    assert general[3].body_md == "Ignore level caps"
    assert all(r.subject is None and r.ruleset is None and r.setting is None and r.enabled for r in general)

    everything = storage.house_rules.list()
    assert [r.kind for r in everything] == ["general"] * 4  # the homebrew is a pack's
    assert bundle.title == SEED_BUNDLE and bundle.rule_ids == tuple(r.id for r in everything)
    assert storage.house_rule_bundles.list() == [bundle]


def test_general_other_heading_is_always(storage, tmp_path):
    (tmp_path / "general.md").write_text(
        "Intro text, not a rule.\n\n# Character creation\n\n- Max HP\n\n# Table manners\n\n"
        "- Describe the smell of every room,\n  and the sound.\n* Never kill a PC off-screen\n"
    )
    hr.import_house_rules(storage, tmp_path)
    assert [(r.title, sorted(r.phases), r.body_md) for r in storage.house_rules.list()] == [
        ("Max HP", ["character-creation"], "Max HP"),
        ("Describe the smell of every room", ["always"], "Describe the smell of every room, and the sound."),
        ("Never kill a PC off-screen", ["always"], "Never kill a PC off-screen"),
    ]


def test_seed_runs_once_and_is_idempotent(storage):
    seeded = hr.seed_house_rules(storage, SEED)
    assert seeded is not None and len(seeded.rule_ids) == 4
    assert hr.seed_house_rules(storage, SEED) is None  # the library isn't empty: nothing to do

    # Importing the same files again matches by kind, subject and title: nothing is added, and edits are kept.
    first = storage.house_rules.list()
    edited = storage.house_rules.save(replace(first[0], body_md="Roll 3d6 in order.", enabled=False))
    again = hr.import_house_rules(storage, SEED)
    assert again == seeded
    assert storage.house_rules.list() == [edited, *first[1:]]
    assert len(storage.house_rule_bundles.list()) == 1

    # A rule taken out of the bundle comes back into it; one deleted is imported anew, at the end.
    storage.house_rule_bundles.save(replace(seeded, rule_ids=seeded.rule_ids[1:]))
    storage.house_rules.delete(first[1].id)
    restored = hr.import_house_rules(storage, SEED)
    assert len(storage.house_rules.list()) == 4 and len(restored.rule_ids) == 4
    assert restored.rule_ids[0] == seeded.rule_ids[2] and edited.id in restored.rule_ids


def test_seed_import_command(storage, tmp_path, monkeypatch, capsys):
    from delve.__main__ import main

    monkeypatch.setenv("DELVE_DATA_DIR", str(tmp_path / "cli"))
    assert main(["house-rules", "import"]) == 0
    assert "4 house rules" in capsys.readouterr().out
    assert main(["house-rules", "import", str(SEED)]) == 0
    assert "4 house rules" in capsys.readouterr().out
    assert main(["house-rules", "import", str(tmp_path / "nowhere")]) == 1
    assert "nowhere" in capsys.readouterr().err


# --- a campaign's effective set ------------------------------------------------------------------------------------


def test_effective_set_union_minus_disabled_and_mismatched_setting(storage, campaign):
    a = storage.house_rules.create(title="A", phases=["always"])
    b = storage.house_rules.create(title="B", phases=["always"], ruleset="osric", setting="greyhawk")
    off = storage.house_rules.create(title="Off", phases=["always"], enabled=False)
    tressym = storage.house_rules.create(title="Tressym familiar", phases=["always"], setting="forgotten-realms")
    other = storage.house_rules.create(title="Another ruleset's", phases=["always"], ruleset="test-ruleset")
    single = storage.house_rules.create(title="Single", phases=["combat"])
    table = storage.house_rule_bundles.create(title="Table", rule_ids=[b.id, a.id, off.id, tressym.id])
    extra = storage.house_rule_bundles.create(title="Extra", rule_ids=[other.id, a.id])

    assert hr.campaign_house_rules(storage, campaign.id) == {"bundle_ids": [], "rule_ids": []}
    assert hr.effective_rules(storage, campaign.id) == []
    choose(storage, campaign, bundles=[table, extra], rules=[single, b])
    assert hr.campaign_house_rules(storage, campaign.id) == {
        "bundle_ids": [table.id, extra.id],
        "rule_ids": [single.id, b.id],
    }
    # Bundles in order with their rules in order, then the single rules; each rule once.
    assert titles(hr.effective_rules(storage, campaign.id)) == ["B", "A", "Single"]
    assert (campaign.ruleset, campaign.setting) == ("osric", "greyhawk")


def test_a_campaign_without_a_setting_gets_no_greyhawk_only_rule(storage, campaign):
    """The campaign's own ruleset and setting choose its rules: with `setting` None, a Greyhawk rule is left out."""
    general = storage.house_rules.create(title="General", phases=["always"])
    greyhawk = storage.house_rules.create(title="Greyhawk only", phases=["always"], setting="greyhawk")
    other = storage.house_rules.create(title="Test ruleset only", phases=["always"], ruleset="test-ruleset")
    nowhere = storage.campaigns.create("Nowhere", campaign.module_id, campaign.revision, setting="", ruleset="osric")
    on_other = storage.campaigns.create(
        "Other", campaign.module_id, campaign.revision, ruleset="test-ruleset", setting="greyhawk"
    )
    for started in (campaign, nowhere, on_other):
        choose(storage, started, rules=[general, greyhawk, other])
    assert titles(hr.effective_rules(storage, campaign.id)) == ["General", "Greyhawk only"]
    assert titles(hr.effective_rules(storage, nowhere.id)) == ["General"]
    assert titles(hr.effective_rules(storage, on_other.id)) == ["General", "Greyhawk only", "Test ruleset only"]


def test_set_campaign_house_rules_refuses_unknown(storage, campaign):
    with pytest.raises(PlayError, match="hb_000000000000"):
        hr.set_campaign_house_rules(storage, campaign.id, bundle_ids=["hb_000000000000"], rule_ids=[])
    with pytest.raises(PlayError, match="hr_000000000000"):
        hr.set_campaign_house_rules(storage, campaign.id, bundle_ids=[], rule_ids=["hr_000000000000"])
    with pytest.raises(PlayError, match="cmp_000000000000"):
        hr.campaign_house_rules(storage, "cmp_000000000000")


def test_campaign_points_to_rules_edit_applies(storage, campaign, ctx):
    """A campaign points to rules and copies nothing: an edit to a rule, or to a bundle, applies to it at once."""
    hp = storage.house_rules.create(title="Max HP", body_md="Max HP at level 1.", phases=["character-creation"])
    table = storage.house_rule_bundles.create(title="Table", rule_ids=[hp.id])
    choose(storage, campaign, bundles=[table])
    [rule] = hr.rules_for(ctx, phase="character-creation")
    assert rule.body_md == "Max HP at level 1."

    storage.house_rules.save(replace(hp, body_md="Max HP at every level."))
    assert [r.body_md for r in hr.rules_for(ctx, phase="character-creation")] == ["Max HP at every level."]
    storage.house_rules.save(replace(hp, setting="forgotten-realms"))
    assert hr.rules_for(ctx, phase="character-creation") == []
    storage.house_rules.save(replace(hp, setting=None))
    later = storage.house_rules.create(title="4d6 drop lowest", phases=["character-creation"])
    storage.house_rule_bundles.save(replace(table, rule_ids=(later.id, hp.id)))
    assert titles(hr.rules_for(ctx, phase="character-creation")) == ["4d6 drop lowest", "Max HP"]


# --- when each rule reaches the DM ---------------------------------------------------------------------------------


@pytest.fixture
def seeded(storage, campaign):
    """Delve's seeds and the homebrew (`tests.fixtures.homebrew`) in the seed bundle, chosen for the campaign."""
    bundle = seed_with_homebrew(storage)
    choose(storage, campaign, bundles=[bundle])
    return bundle


def test_creation_rules_for_created_character(ctx, seeded):
    """Spec §9: creating a character hands the DM the creation rules: the general ones, and the race and class
    rules of that character, never those of other races. Task 11's `create_character` puts them under
    `house_rules`."""
    lizard = characters.create(ctx, name="Sss", sheet={"race": "Lizardfolk", "cls": "Fighter/Witch", "hp_max": 9})
    rules = hr.creation_rules(ctx, lizard)
    assert titles(rules) == ["Roll 4D6 for abilities", "Characters start at maximum HP for level 1", "Lizardfolk", "Witch"]
    human = characters.create(ctx, name="Garrek", sheet={"race": "human", "cls": "Fighter", "hp_max": 9})
    assert titles(hr.creation_rules(ctx, human)) == ["Roll 4D6 for abilities", "Characters start at maximum HP for level 1"]


def test_level_up_rules_returned_on_level_up_hint(ctx, storage, seeded):
    fighter_rule = storage.house_rules.create(
        title="Fighters specialise freely", kind="class", phases=["level-up"], subject="fighter"
    )
    mage_rule = storage.house_rules.create(title="Mages", kind="class", phases=["level-up"], subject="mage")
    choose(storage, storage.campaigns.get(ctx.campaign_id), bundles=[seeded], rules=[fighter_rule, mage_rule])
    characters.create(ctx, name="Ysolde", sheet={"cls": "Fighter", "level": 1, "hp_max": 10})

    quiet = characters.award_xp(ctx, "Ysolde", 100)
    assert quiet["level_up_hints"] == [] and "house_rules" not in quiet
    out = characters.award_xp(ctx, "Ysolde", 1900)
    assert out["level_up_hints"]
    assert [r["title"] for r in out["house_rules"]] == [
        "Players can opt to reroll HP once",
        "Ignore level caps",
        "Fighters specialise freely",
    ]
    assert out["house_rules"][0] == {
        "id": seeded.rule_ids[2],
        "title": "Players can opt to reroll HP once",
        "body_md": "Players can opt to reroll HP once, choosing the better of 2 rolls",
        "kind": "general",
        "phases": ["level-up"],
        "ruleset": None,
        "setting": None,
        "subject": None,
        "enabled": True,
    }


def test_level_up_without_house_rules_still_answers(ctx):
    characters.create(ctx, name="Ysolde", sheet={"cls": "Fighter", "level": 1, "hp_max": 10})
    out = characters.award_xp(ctx, "Ysolde", 2000)
    assert out["level_up_hints"] and out["house_rules"] == []


def test_item_rules_match_subject_or_title(ctx, seeded):
    assert titles(hr.item_rules(ctx, ["Shrinking Blade"])) == ["Marten Martialist's Shrinking Blade"]
    assert titles(hr.item_rules(ctx, ["marten martialist's shrinking blade", "Long sword", "Caster's Aid"])) == [
        "Caster's Aid",
        "Marten Martialist's Shrinking Blade",
    ]
    assert hr.item_rules(ctx, ["Long sword", "Blade"]) == []


def test_rules_for_without_phase_is_the_system_prompt_set(ctx, storage, seeded):
    """Spec §9: `behaviour` and `always` rules sit in the system prompt, and so do the race and class rules of the
    party's races and classes."""
    manners = storage.house_rules.create(title="Table manners", kind="behaviour", phases=["behaviour"])
    choose(storage, storage.campaigns.get(ctx.campaign_id), bundles=[seeded], rules=[manners])
    assert titles(hr.rules_for(ctx)) == ["Table manners"]
    characters.create(ctx, name="Sss", sheet={"race": "Lizardfolk", "cls": "Barbarian", "hp_max": 9})
    characters.create(ctx, name="Tira", kind="npc", sheet={"race": "Kobold"})  # not in the party
    assert sorted(titles(hr.rules_for(ctx))) == ["Barbarian", "Lizardfolk", "Table manners"]
    assert titles(hr.rules_for(ctx, phase="items", subjects=["the hawkblade"])) == ["The Hawkblade"]
    assert len(hr.rules_for(ctx, phase="items")) == len([h for h in HOMEBREW if h[1] == "item"])


# --- a pack's house rules ------------------------------------------------------------------------------------------


def test_import_house_rules_tags_seeds_with_their_pack(storage, tmp_path):
    packs = tmp_path / "packs"
    for name in ("test-ruleset", "test-setting"):
        shutil.copytree(PACK_FIXTURES / name, packs / name)
    (packs / "test-ruleset" / "house-rules" / "races").mkdir(parents=True)
    (packs / "test-ruleset" / "house-rules" / "races" / "wisp.md").write_text("# Wisp (Homebrew)\n\nPack dust.\n")
    (packs / "test-setting" / "house-rules").mkdir()
    (packs / "test-setting" / "house-rules" / "general.md").write_text("- Mind the weather\n")
    loaded, _ = load_packs(packs)

    hr.import_house_rules(storage, SEED, loaded)

    by_title = {r.title: r for r in storage.house_rules.list()}
    pixie = by_title["Wisp"]
    assert (pixie.ruleset, pixie.setting, pixie.subject) == ("test-ruleset", None, "wisp")
    assert (by_title["Mind the weather"].ruleset, by_title["Mind the weather"].setting) == (None, "test-setting")
    assert by_title["Roll 4D6 for abilities"].ruleset is None and by_title["Roll 4D6 for abilities"].setting is None
    assert {r.id for r in storage.house_rules.list()} == set(storage.house_rule_bundles.list()[0].rule_ids)
