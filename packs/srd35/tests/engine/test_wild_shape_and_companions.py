"""Wild shape, animal companions and the paladin's special mount (DEL-389): `use_feature(wild-shape)` and
`add_companion`. Each number is worked by hand in its comment from the SRD rows (monsters.json) and the companion and
mount tables (features.json)."""

from __future__ import annotations

import pytest

from delve.rules.classic import combat as rules

SCORES = {"str": 14, "dex": 12, "con": 12, "int": 10, "wis": 12, "cha": 10}


class Table:
    """Characters made with the tools on the srd35 campaign, a fight against enemies set up with setup_combat, and the
    stored characters and combatants."""

    def __init__(self, call, storage, campaign):
        self.call, self.storage, self.campaign = call, storage, campaign

    def character(self, name: str, cls: str, level: int, **build) -> dict:
        sheet = {"cls": cls, "level": level, "race": "Human", "hp_max": 8 * level, "ability_scores": dict(SCORES)}
        out = self.call("create_character", name=name, sheet=sheet)
        assert "error" not in out, out
        if build:
            assert "error" not in (built := self.call("set_build", character=name, **build)), built
        return out

    def get(self, name: str):
        return next(c for c in self.storage.characters.list(self.campaign.id) if c.name == name)

    def enemies(self, *names: str) -> None:
        out = self.call("setup_combat", enemies=[{"name": n, "count": 1, "hp": 30} for n in names], surprise=False)
        assert "error" not in out, out

    def combatant(self, name: str) -> rules.Combatant:
        fight = rules.from_json(self.storage.combats.live(self.campaign.id)[1])
        return next(c for c in fight.combatants.values() if c.name == name)


@pytest.fixture
def table(srd35_call, srd35_storage, srd35_campaign):
    return Table(srd35_call, srd35_storage, srd35_campaign)


# --- wild shape --------------------------------------------------------------------------------------------------


def test_druid_5_becomes_a_wolf_not_a_brown_bear(srd35_call, table):
    table.character("Ash", "Druid", 5)
    out = srd35_call("use_feature", character="Ash", feature="wild-shape", target="wolf")
    assert out["shape"] == "wolf", out
    assert table.get("Ash").state.d20["shape"]["monster"] == "wolf"
    refused = srd35_call("use_feature", character="Ash", feature="wild-shape", target="brown bear")
    assert "Small or Medium" in refused["error"]


def test_wild_shape_takes_animals_only_and_counts_its_uses(srd35_call, table):
    table.character("Ash", "Druid", 5)
    refused = srd35_call("use_feature", character="Ash", feature="wild shape", target="ogre")
    assert "animal" in refused["error"]
    assert "Unknown" in srd35_call("use_feature", character="Ash", feature="wild-shape", target="snark")["error"]
    assert "error" not in srd35_call("use_feature", character="Ash", feature="wild-shape", target="wolf")
    back = srd35_call("use_feature", character="Ash", feature="wild-shape", target="")
    assert back["shape"] is None and "shape" not in table.get("Ash").state.d20
    refused = srd35_call("use_feature", character="Ash", feature="wild-shape", target="wolf")
    assert "Wild shape: 1 a day at this level, used 1." in refused["error"]
    # Not a druid of 5th level: no wild shape.
    table.character("Bryn", "Druid", 4)
    refused = srd35_call("use_feature", character="Bryn", feature="wild-shape", target="wolf")
    assert "hasn't Wild shape" in refused["error"]


def test_a_druid_8_may_be_large_but_not_above_her_level_in_hit_dice(srd35_call, table):
    table.character("Ash", "Druid", 8)
    assert "error" not in srd35_call("use_feature", character="Ash", feature="wild-shape", target="brown bear")
    # A dire bear is Large too, but has 12 Hit Dice.
    srd35_call("rest", character="Ash", days=1)
    refused = srd35_call("use_feature", character="Ash", feature="wild-shape", target="dire bear")
    assert "12 Hit Dice" in refused["error"]


def test_a_wolf_shaped_druid_bites_as_a_wolf_and_keeps_its_hp(table):
    # Druid 5: BAB +3, Fort 4 + Con 1, Ref 1 + Dex 1, Will 4 + Wis 1. The wolf: Str 13, Dex 15, Con 15, bite +3 (1d6+1)
    # = its BAB +1, Str +1 and its Weapon Focus (bite) +1; AC 14 (+2 Dex, +2 natural), Medium.
    table.character("Ash", "Druid", 5)
    table.enemies("orc")
    before = table.combatant("Ash")
    out = table.call("use_feature", character="Ash", feature="wild-shape", target="wolf")
    assert "error" not in out, out
    wolf = table.combatant("Ash")
    bite = wolf.d20["attacks"][0]
    # The wolf's bite at the druid's BAB, without the wolf's Weapon Focus: BAB 3 + the wolf's Str 1 = +4; its damage.
    assert (bite["name"], bite["bonus"], bite["damage"]) == ("bite", 4, "1d6+1")
    assert [b.name for b in wolf.attacks] == ["bite"]
    assert (wolf.ac, wolf.d20["ac"], wolf.d20["touch"], wolf.d20["flat_footed"]) == (14, 14, 12, 12)
    assert wolf.size == "M" and wolf.d20["dex"] == 2 and wolf.d20["bab"] == 3
    # Her own hit points, her own base saves, with the wolf's Con (+2) and Dex (+2): Fort 6, Ref 3, Will 5.
    assert (wolf.hp, wolf.hp_max) == (before.hp, before.hp_max)
    assert wolf.d20["saves"] == {"fort": 6, "ref": 3, "will": 5}
    assert wolf.d20["shape"] == "wolf"
    # Back in her own shape: her own numbers again.
    table.call("use_feature", character="Ash", feature="wild-shape", target="")
    assert table.combatant("Ash").d20["attacks"] == before.d20["attacks"]
    assert table.combatant("Ash").d20["saves"] == before.d20["saves"]


def test_a_shape_with_weapon_finesse_attacks_by_her_strength(table):
    # The badger (Small): Str 8 (-1), Dex 17 (+3), Weapon Finesse; claws +4 = BAB 0 + Dex 3 + size 1. A druid 5 without
    # the feat claws by the badger's Str: 4 - 0 + 3 + (-1 - 3) = +3.
    table.character("Ash", "Druid", 5)
    table.enemies("orc")
    table.call("use_feature", character="Ash", feature="wild-shape", target="badger")
    claw = next(f for f in table.combatant("Ash").d20["attacks"] if f["name"] == "claw")
    assert claw["bonus"] == 3


def test_changing_shape_heals_as_a_nights_rest(table):
    # A night's rest heals the character level in hit points: 5 for a druid 5.
    table.character("Ash", "Druid", 5)
    table.call("update_character", ref="Ash", patch={"hp": 30})
    out = table.call("use_feature", character="Ash", feature="wild-shape", target="wolf")
    assert out["healed"] == 5 and table.get("Ash").state.hp == 35


# --- companions --------------------------------------------------------------------------------------------------


def test_a_druid_1_companion_wolf(srd35_call, table):
    ash = table.character("Ash", "Druid", 1)
    out = srd35_call("add_companion", master="Ash", animal="wolf", name="Grey")
    assert "error" not in out, out
    grey = table.get("Grey")
    assert grey.kind == "pc" and grey.sheet.d20["companion_of"] == ash["id"]
    # Druid level 1-2: no bonus HD, no adjustments; the wolf's 2d8+4 = 13 hp, its scores.
    assert grey.sheet.hp_max == 13 and grey.state.hp == 13
    assert grey.sheet.ability_scores["str"] == 13 and grey.sheet.ability_scores["dex"] == 15
    derived = grey.sheet.d20["derived"]
    assert (derived["bab"], derived["ac"], derived["fort"], derived["ref"], derived["will"]) == (1, 14, 5, 5, 1)
    assert out["companion"]["tricks"] == 1 and "link" in out["companion"]["special"]
    # It fights as the wolf it is.
    table.enemies("orc")
    c = table.combatant("Grey")
    assert (c.d20["attacks"][0]["bonus"], c.d20["attacks"][0]["damage"], c.ac, c.hp) == (3, "1d6+1", 14, 13)


def test_a_druid_3_companion_has_its_bonus_hit_dice(srd35_call, table):
    # Druid 3: +2 HD, +2 natural armour, +1 Str and Dex. The wolf of 4 HD: hp 4 × 4.5 = 18 + 4 × Con 2 = 26; BAB 3
    # (+2); Str 14 (+2, one more), Dex 16 (+3, one more); bite +3 + 2 + 1 = +6 for 1d6 + 1½ × 2 = 1d6+3 (its only natural
    # attack: the SRD's 1d6+1 is 1½ × 1, rounded down; part 3); AC 14 + 2 + 1 = 17; Fort and
    # Ref good at 4 HD (4, one more than 2 HD's 3), Ref one more for Dex: Fort 6, Ref 7; Will poor (1, one more): 2.
    table.character("Ash", "Druid", 3)
    srd35_call("add_companion", master="Ash", animal="wolf", name="Grey")
    grey = table.get("Grey")
    assert grey.sheet.hp_max == 26
    assert (grey.sheet.ability_scores["str"], grey.sheet.ability_scores["dex"]) == (14, 16)
    derived = grey.sheet.d20["derived"]
    assert (derived["bab"], derived["ac"], derived["fort"], derived["ref"], derived["will"]) == (3, 17, 6, 7, 2)
    table.enemies("orc")
    c = table.combatant("Grey")
    assert (c.d20["attacks"][0]["bonus"], c.d20["attacks"][0]["damage"], c.ac, c.d20["touch"]) == (6, "1d6+3", 17, 13)


def test_the_companion_grows_when_its_druid_levels_up(srd35_call, table):
    table.character("Ash", "Druid", 1)
    srd35_call("add_companion", master="Ash", animal="wolf", name="Grey")
    out = srd35_call("update_character", ref="Ash", patch={"level": 3})
    assert "error" not in out, out
    grey = table.get("Grey")
    assert (grey.sheet.hp_max, grey.state.hp) == (26, 26)
    assert grey.sheet.d20["derived"]["ac"] == 17
    assert grey.sheet.d20["companion"]["bonus_hd"] == 2


def test_a_companion_heals_by_its_hit_dice_and_shows_its_master(srd35_call, table):
    # A night's rest heals 1 hp per Hit Die: the wolf of 2 HD heals 2, of 4 HD (druid 3) 4.
    ash = table.character("Ash", "Druid", 3)
    srd35_call("add_companion", master="Ash", animal="wolf", name="Grey")
    srd35_call("update_character", ref="Grey", patch={"hp": 10})
    srd35_call("rest", character="Grey", days=1)
    assert table.get("Grey").state.hp == 14
    brief = srd35_call("get_character", ref="Grey", brief=True)
    assert (brief["d20"]["companion_of"], brief["d20"]["animal"], brief["d20"]["hit_dice"]) == (ash["id"], "wolf", 4)
    assert "companion_of" not in srd35_call("get_character", ref="Ash", brief=True)["d20"]


def test_a_level_lost_leaves_a_standing_companion_at_1_hp_at_least(srd35_call, table):
    # Druid 3 to 1: the wolf loses its 2 bonus HD, 26 - 13 = 13 hp off its maximum; at 5 hp it stays up, at 1.
    table.character("Ash", "Druid", 3)
    srd35_call("add_companion", master="Ash", animal="wolf", name="Grey")
    srd35_call("update_character", ref="Grey", patch={"hp": 5})
    assert "error" not in (out := srd35_call("update_character", ref="Ash", patch={"level": 1})), out
    grey = table.get("Grey")
    assert (grey.sheet.hp_max, grey.state.hp) == (13, 1)


def test_a_second_companion_refuses(srd35_call, table):
    table.character("Ash", "Druid", 1)
    srd35_call("add_companion", master="Ash", animal="wolf", name="Grey")
    refused = srd35_call("add_companion", master="Ash", animal="badger", name="Nip")
    assert "already" in refused["error"] and "Grey" in refused["error"]


def test_a_fighter_has_no_companion(srd35_call, table):
    table.character("Bram", "Fighter", 5)
    refused = srd35_call("add_companion", master="Bram", animal="wolf", name="Grey")
    assert "no animal companion or special mount" in refused["error"]


def test_a_druid_1_cant_have_a_brown_bear(srd35_call, table):
    table.character("Ash", "Druid", 1)
    refused = srd35_call("add_companion", master="Ash", animal="brown bear", name="Bruin")
    assert "7th" in refused["error"]
    # At 7th, from the alternative list, as a druid of 1st (7 - 6): no bonus HD.
    table.character("Oak", "Druid", 7)
    out = srd35_call("add_companion", master="Oak", animal="brown bear", name="Bruin")
    assert "error" not in out, out
    assert out["companion"]["level"] == 1 and table.get("Bruin").sheet.hp_max == 51


def test_a_ranger_4_companion_is_a_druid_2s(srd35_call, table):
    table.character("Rook", "Ranger", 4)
    out = srd35_call("add_companion", master="Rook", animal="wolf", name="Grey")
    assert out["companion"]["level"] == 2 and table.get("Grey").sheet.hp_max == 13
    table.character("Wren", "Ranger", 3)
    assert "error" in srd35_call("add_companion", master="Wren", animal="wolf", name="Fang")


def test_a_paladin_5_special_mount(srd35_call, table):
    # Paladin 5: +2 HD, +4 natural armour, +1 Str, Int 6. The heavy warhorse of 6 HD: hp 30 + (27 - 18) + 2 × Con 3 =
    # 45; Str 19 (+4, no change); AC 14 + 4 = 18; BAB 4 (+1) on its hooves: +6 + 1 = +7.
    pal = table.character("Sir Hal", "Paladin", 5)
    out = srd35_call("add_companion", master="Sir Hal", animal="heavy warhorse", name="Dawn")
    assert "error" not in out, out
    dawn = table.get("Dawn")
    assert dawn.kind == "pc" and dawn.sheet.d20["companion_of"] == pal["id"]
    assert dawn.sheet.hp_max == 45
    assert (dawn.sheet.ability_scores["str"], dawn.sheet.ability_scores["int"]) == (19, 6)
    assert dawn.sheet.d20["derived"]["ac"] == 18
    table.enemies("orc")
    assert table.combatant("Dawn").d20["attacks"][0]["bonus"] == 7
    table.character("Sir Kay", "Paladin", 4)
    assert "error" in srd35_call("add_companion", master="Sir Kay", animal="heavy warhorse", name="Dusk")


def test_the_companion_is_played_by_its_masters_seat(srd35_call, table, srd35_storage, srd35_campaign):
    ash = table.character("Ash", "Druid", 1)
    seat = srd35_storage.seats.create(srd35_campaign.id, "Ana", "en", "player")
    srd35_storage.seats.set_controller(ash["id"], seat.id)
    srd35_call("add_companion", master="Ash", animal="wolf", name="Grey")
    assert table.get("Grey").controller_id == seat.id
