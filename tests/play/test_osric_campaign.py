"""An OSRIC campaign plays on OSRIC's lookups (DEL-302): through the DM's tools, without `reference.db`, its monsters,
spells, saves and fights are OSRIC's. OSRIC comes from the pack of this repo, installed once for the run."""

import pytest

from delve.dice import SeededRng
from delve.dm.tools import ToolHost
from delve.rules.classic import combat as rules
from tests.play.conftest import crypt_campaign

FIGHTER = {"race": "Human", "cls": "Fighter", "levels": {"fighter": 1}, "hp_max": 9, "ac": 5}


@pytest.fixture
def host(storage, osric_catalogs):
    return ToolHost(storage, lambda: SeededRng(7), catalogs=osric_catalogs)  # no reference.db


def call(host, campaign, tool, **args):
    out = host.call(campaign.id, "beat-1", tool, args)
    assert "error" not in out, out
    return out


def test_an_osric_campaign_looks_up_osrics_monsters_and_spells(storage, host):
    campaign = crypt_campaign(storage, ruleset="osric", setting=None)
    (bugbear,) = call(host, campaign, "monster_lookup", name="bugbear")["monsters"]
    assert (bugbear["armor_class"], bugbear["thac0"], bugbear["source"]) == (
        "5 [15]",
        16,
        "OSRIC 3.0 Gamemaster Guide, p. 108",
    )
    spell = call(host, campaign, "spell_lookup", name="magic missile")["spells"][0]
    assert (spell["caster"], spell["source"]) == ("magic-user", "OSRIC 3.0")
    assert call(host, campaign, "class_lookup", class_name="ranger")["class"]["hit_die"] == "d8"


def test_an_osric_campaigns_saves_and_fights(storage, host):
    campaign = crypt_campaign(storage, ruleset="osric", setting=None)
    made = call(host, campaign, "create_character", name="Garrek", sheet=FIGHTER)
    # The sheet's saves are filled from OSRIC's fighter table, under OSRIC's five names.
    saves = storage.characters.get(made["id"]).sheet.saves
    assert saves == {
        "death_paralysis_poison": 14,
        "petrification_polymorph": 15,
        "aimed_magic_items": 16,
        "breath_weapons": 17,
        "spells": 17,
    }
    save = call(host, campaign, "saving_throw", character="Garrek", save_type="rsw")
    assert (save["name"], save["base"]) == ("Aimed Magic Items", 16)
    fight = call(host, campaign, "setup_combat", enemies=[{"name": "bugbear", "count": 1}], surprise=False)
    (enemy,) = [c for c in fight["combat"]["combatants"] if c["side"] == "enemy"]
    assert (enemy["name"], enemy["ac"], enemy["thac0"]) == ("Bugbear", 5, 16)
    assert all(1 <= entry["roll"] <= 6 and entry["speed"] == 0 for entry in fight["order"])  # a d6, no weapon speed
    morale = call(host, campaign, "morale_check", rating=65, group="the bugbear")
    assert morale["roll"]["notation"] == "1d100"


def test_a_2e_campaign_without_its_pack_is_refused(storage, host):
    """AD&D 2e is a pack (DEL-307): with only OSRIC installed, a 2e campaign's tools say so."""
    campaign = crypt_campaign(storage, ruleset="adnd2e", setting=None)
    out = host.call(campaign.id, "beat-1", "monster_lookup", {"name": "bugbear"})
    assert out["error"] == "This campaign's ruleset, adnd2e, isn't installed."
    assert out["hint"] == "Install its pack, or play another campaign."


def test_an_osric_character_takes_its_thac0_and_race_from_osric(storage, host):
    campaign = crypt_campaign(storage, ruleset="osric", setting=None)
    elf = call(host, campaign, "race_lookup", race="elf")["race"]
    assert elf["level_limits"]["fighter"] == "7 (strength 18+), 6 (strength 17+), 5"
    made = call(host, campaign, "create_character", name="Corwin", sheet={**FIGHTER, "levels": {"fighter": 3}})
    assert storage.characters.get(made["id"]).sheet.thac0 == 18  # OSRIC's fighter at 3rd level
    given = call(host, campaign, "create_character", name="Brand", sheet={**FIGHTER, "thac0": 15})
    assert storage.characters.get(given["id"]).sheet.thac0 == 15  # a THAC0 the sheet gives stays


def test_an_osric_campaigns_treasure_merchant_and_encounters(storage, host):
    campaign = crypt_campaign(storage, ruleset="osric", setting=None)
    refused = host.call(campaign.id, "beat-1", "generate_treasure", {"treasure_types": "Hoard 2"})
    assert "a lair's hoard (a Hoard)" in refused["error"]
    hoard = call(
        host, campaign, "generate_treasure", treasure_types="Hoard 2", in_lair=True, monster="bugbear", source="cave"
    )
    assert hoard["rolled"] == ["hoard 2"]
    carried = call(host, campaign, "generate_treasure", treasure_types="Individual 3", source="the bugbear")
    assert carried["rolled"] == ["individual 3"]
    shelf = call(host, campaign, "magic_merchant", merchant="ostler", settlement="city", cost="moderate")
    assert shelf["items"] and all(item["price_source"] == "osric" for item in shelf["items"])
    found = call(host, campaign, "encounter_check", terrain="forest", level=2)
    assert found["terrain"] == "forest"
    if found["triggered"]:
        assert found["tier"].startswith("forest: ")


def test_an_osric_drain_rolls_the_level_off_and_drops_to_its_lowest_xp_in_a_fight(storage, host):
    """OSRIC Player's Guide §1.6.7 (DEL-320): the level's hit die off the maximum, the XP down to the new level's
    lowest, THAC0 and saves from OSRIC's tables, and a fight's tracker takes them; drained below 1st level, dead."""
    campaign = crypt_campaign(storage, ruleset="osric", setting=None)
    made = call(
        host, campaign, "create_character", name="Garrek", sheet={**FIGHTER, "levels": {"fighter": 3}, "hp_max": 24}
    )
    call(host, campaign, "update_character", ref="Garrek", patch={"xp": 5000})
    call(host, campaign, "setup_combat", enemies=[{"name": "wight", "count": 1}], surprise=False)
    out = call(host, campaign, "drain_level", character="Garrek", reason="wight's touch")
    assert out["levels_after"] == {"fighter": 2} and out["xp_after"] == 2000  # OSRIC's fighter at 2nd level
    assert 13 <= out["hp_max_after"] <= 22 and out["thac0"] == 19
    assert out["saves"]["death_paralysis_poison"] == 14
    me = rules.from_json(storage.combats.live(campaign.id)[1]).combatants[made["id"]]
    assert (me.hp_max, me.thac0) == (out["hp_max_after"], 19)
    slain = call(host, campaign, "drain_level", character="Garrek", levels=2, reason="spectre")
    assert slain["slain"] and storage.characters.get(made["id"]).state.hp == -10
