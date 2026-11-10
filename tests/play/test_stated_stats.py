"""Table voice and fixes Task E2: a module's stated stats against the reference's. The tracker had zombies at AC 8
where the module says 5 (backlog Fixes 10): `stated_differences` finds the module's stat line for the monster, in its
encounter records and its texts, and says what differs, so `setup_combat` tells the DM to pass the module's numbers."""

from __future__ import annotations

from delve.dm.prompt import DM_PROCEDURE
from delve.modules.source import ModuleSource, TextDoc, save_source
from delve.play.stated_stats import stated_differences

ZOMBIE = {"name": "zombie", "armor_class": "8", "hit_dice": "2", "thac0": 19, "move": "6", "damage_attack": "1-8"}
GIANT_RAT = {
    "name": "rat, giant",
    "armor_class": "7",
    "hit_dice": "½",
    "thac0": 20,
    "move": "12, Sw 6",
    "damage_attack": "1-3",
}


def campaign_of(storage, *markdown: str, encounters: list[dict] | None = None):
    """A campaign pinned to a module whose keyed texts are `markdown` and whose encounter records are `encounters`."""
    module = storage.modules.create("The Crypt")
    texts = [TextDoc(f"t{i}", f"Text {i}", "gm", None, md) for i, md in enumerate(markdown)]
    save_source(storage, module.id, ModuleSource(texts=texts, entities={"encounters": encounters or []}))
    return storage.campaigns.create(
        "Tuesday", module.id, storage.revisions.snapshot(module.id).number, ruleset="osric", setting="greyhawk"
    )


def test_zombie_ac_differs(storage):
    campaign = campaign_of(storage, "# Crypt\n\n## 3. Ossuary {#3}\n\nZombies (4): AC 5, HD 2. They shamble.\n")
    assert stated_differences(storage, campaign.id, "zombie", ZOMBIE) == [
        "The module gives Zombie AC 5 (the reference says 8): pass ac=5 in setup_combat's enemies."
    ]


def test_same_stats_say_nothing(storage):
    line = "Zombies (4): AC 8; MV 6; HD 2; THAC0 19; #AT 1; Dmg 1d8."
    campaign = campaign_of(storage, f"## 3. Ossuary\n\n{line}\n")
    assert stated_differences(storage, campaign.id, "Zombie", ZOMBIE) == []


def test_no_stat_line_says_nothing(storage):
    campaign = campaign_of(storage, "## 3. Ossuary\n\nFour zombies shamble here, AC unknown to the party.\n")
    assert stated_differences(storage, campaign.id, "zombie", ZOMBIE) == []
    assert stated_differences(storage, campaign_of(storage).id, "zombie", ZOMBIE) == []
    assert stated_differences(storage, "cmp_nope", "zombie", ZOMBIE) == []


def test_another_monsters_stats_are_not_its(storage):
    campaign = campaign_of(storage, "## 3. Ossuary\n\nGhouls (2): AC 6; HD 2. Zombies (4): HD 2; THAC0 19.\n")
    assert stated_differences(storage, campaign.id, "zombie", ZOMBIE) == []


def test_every_stat_that_differs(storage):
    line = "4 zombies: AC 5; MV 9; HD 3; hp 12 each; THAC0 17; #AT 1; D 2-8"
    campaign = campaign_of(storage, f"## 3. Ossuary\n\n{line}\n")
    assert stated_differences(storage, campaign.id, "zombie", ZOMBIE) == [
        "The module gives Zombie AC 5 (the reference says 8): pass ac=5 in setup_combat's enemies.",
        "The module gives Zombie HD 3 (the reference says 2): pass hp for HD 3 in setup_combat's enemies.",
        "The module gives Zombie hp 12 (the reference gives none): pass hp=12 in setup_combat's enemies.",
        "The module gives Zombie THAC0 17 (the reference says 19): pass thac0=17 in setup_combat's enemies.",
        "The module gives Zombie MV 9 (the reference says 6): it moves as the module says.",
        "The module gives Zombie Dmg 2-8 (the reference says 1-8): pass dmg=2-8 in setup_combat's enemies.",
    ]


def test_an_inverted_and_plural_name(storage):
    campaign = campaign_of(storage, "Giant rats (6): AC 6; HD ½; hp 3 each; D 1-3.\n")
    assert stated_differences(storage, campaign.id, "rat, giant", GIANT_RAT) == [
        "The module gives Rat, giant AC 6 (the reference says 7): pass ac=6 in setup_combat's enemies.",
        "The module gives Rat, giant hp 3 (the reference gives none): pass hp=3 in setup_combat's enemies.",
    ]


def test_an_encounter_records_line_for_its_creature(storage):
    encounters = [
        {
            "id": "c3",
            "name": "The ossuary",
            "fixed": [{"count": 4, "creature": "monster:zombie", "notes": "AC 5; MV 6; HD 2; hp 9 each"}],
        },
        {"id": "c4", "name": "Rats", "fixed": [{"count": 6, "creature": "monster:giant-rat", "notes": "AC 2"}]},
    ]
    campaign = campaign_of(storage, encounters=encounters)
    assert stated_differences(storage, campaign.id, "zombie", ZOMBIE) == [
        "The module gives Zombie AC 5 (the reference says 8): pass ac=5 in setup_combat's enemies.",
        "The module gives Zombie hp 9 (the reference gives none): pass hp=9 in setup_combat's enemies.",
    ]
    assert stated_differences(storage, campaign.id, "giant rat", GIANT_RAT)[0].startswith(
        "The module gives Giant rat AC 2"
    )


def test_without_a_reference_row_every_stated_stat(storage):
    campaign = campaign_of(storage, "Zombies (4): AC 5, HD 2.\n")
    assert stated_differences(storage, campaign.id, "zombie", None) == [
        "The module gives Zombie AC 5 (the reference gives none): pass ac=5 in setup_combat's enemies.",
        "The module gives Zombie HD 2 (the reference gives none): pass hp for HD 2 in setup_combat's enemies.",
    ]


def test_the_pinned_revision_not_the_working_copy(storage):
    campaign = campaign_of(storage, "Zombies (4): AC 5.\n")
    texts = [TextDoc("t0", "Text 0", "gm", None, "Zombies (4): AC 3.\n")]
    save_source(storage, campaign.module_id, ModuleSource(texts=texts))
    assert stated_differences(storage, campaign.id, "zombie", ZOMBIE)[0].startswith("The module gives Zombie AC 5 ")


def test_dm_md_asks_for_the_modules_numbers():
    rule = " ".join(DM_PROCEDURE[DM_PROCEDURE.index("**The module's stat line wins:**") :][:700].split())
    assert "the module's numbers win over the reference's" in rule
    assert "pass them as the group's overrides in `setup_combat`" in rule


def test_hp_for_each_one(storage):
    """A line that gives each creature its own hp is a group for each, not the first one's hp for all."""
    campaign = campaign_of(storage, "Skeletons (3): AC 7; MV 12; HD 1; hp 5, 4, 3; #AT 1; D 1-6.\n")
    skeleton = {
        "name": "skeleton",
        "armor_class": "7",
        "hit_dice": "1",
        "thac0": 19,
        "move": "12",
        "damage_attack": "1-6 (weapon)",
    }
    each = "set up a group of one for each, with its own hp, in setup_combat's enemies."
    assert stated_differences(storage, campaign.id, "skeleton", skeleton) == [
        f"The module gives Skeleton hp 5, 4, 3 (the reference gives none): {each}"
    ]
