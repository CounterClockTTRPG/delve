"""OSRIC's own ways in the classic engine (DEL-303): monster saves on its tables by Hit Dice, the mindless on theirs;
initiative a d6 a side without weapon speed; morale a d100; a load keeping a share of the movement rate; and the XP of
the monsters defeated, counted at the end of a fight."""

from delve_osric.ruleset import OsricRuleset
from delve_osric.tables import TABLES

from delve.dice import Dice, MemoryRollLog, ScriptedRng
from delve.domain.campaigns import Character
from delve.domain.characters import Attack, CharacterState, Sheet
from delve.rules.classic import checks, encumbrance
from delve.rules.classic import combat as cb

REF = OsricRuleset().reference


def dice(*values: int) -> Dice:
    return Dice(ScriptedRng(values), MemoryRollLog(), "cmp_1", "beat-1")


def test_monsters_save_on_osrics_tables_by_hit_dice():
    """The bugbear (3+1 HD) saves as an intelligent 4: spells 15. The mindless skeleton (1 HD) on its own table."""
    bugbear = checks.save_base_for({"hit_dice": "3+1", "name": "bugbear"}, "spell", REF, rules=TABLES)
    assert (int(bugbear), bugbear.basis) == (TABLES.monster_save(4)["spells"], "monster: HD 3+1 saves as intelligent 4")
    skeleton = checks.save_base_for({"name": "skeleton"}, "poly", REF, rules=TABLES)
    assert skeleton.basis == "monster: HD 1 saves as non-intelligent 1"
    assert int(skeleton) == TABLES.monster_save(1, intelligent=False)["petrification_polymorph"]


def test_morale_is_a_d100_at_or_under_the_percentage():
    held = checks.morale(dice(65), rating=65, actor="bugbears", rules=TABLES)
    assert (held.roll.notation, held.holds) == ("1d100", True)
    assert not checks.morale(dice(66), rating=65, actor="bugbears", rules=TABLES).holds
    assert checks.morale(dice(5, 6), rating=11, actor="orcs").roll.notation == "2d10"  # no ruleset: 2d10


def test_initiative_is_a_d6_a_side_without_weapon_speed():
    garrek = Character(
        id="chr_garrek", campaign_id="cmp_1", name="Garrek", kind="pc",
        sheet=Sheet(cls="Fighter", hp_max=10, attacks=(Attack("long sword", damage_sm="1d8", speed=5),)),
        state=CharacterState(hp=10),
    )  # fmt: skip
    fight, _ = cb.start([garrek])
    fight, _ = cb.add_monsters(fight, dice(5, 5, 5), REF, "bugbear", 1)
    fight, out = cb.roll_initiative(fight, dice(2, 4), REF, "side", TABLES)
    assert out["sides"] == {"party": 2, "enemy": 4}
    assert [(entry["name"], entry["speed"], entry["total"]) for entry in out["order"]] == [
        ("Garrek", 0, 2),
        ("Bugbear", 0, 4),
    ]
    assert [roll["notation"] for roll in out["rolls"]] == ["1d6", "1d6"]


def test_a_load_keeps_a_share_of_the_movement_rate():
    """Strength 12 allows 45 lb: 90 lb is two bands over, half movement; past the last band, none."""
    rules = TABLES.encumbrance
    assert encumbrance.compute([("Sack", 1, 90.0)], strength=12, movement_rate=12, rules=rules)["movement"] == 6
    assert encumbrance.compute([("Anvil", 1, 400.0)], strength=12, movement_rate=12, rules=rules)["movement"] == 0


def test_the_end_of_a_fight_counts_the_xp_of_the_defeated():
    assert [cb.xp_of(x, 13) for x in ("135 +4/hp", "175", "1,600 +10/hp", "175-975", "Varies")] == [
        187,
        175,
        1730,
        None,
        None,
    ]
    garrek = Character(id="chr_garrek", campaign_id="cmp_1", name="Garrek", kind="pc", sheet=Sheet(cls="Fighter"))
    fight, _ = cb.start([garrek])
    fight, _ = cb.add_monsters(fight, dice(5, 6, 1, 4, 2, 3), REF, "bugbear", 2)
    first = next(c for c in fight.combatants.values() if c.side == "enemy")
    fight, _ = cb.damage(fight, first.id, first.hp)
    _, end = cb.end(fight)
    (group,) = [g for g in end["groups"] if g["group"].lower().startswith("bugbear")]
    assert (group["defeated"], group["xp_earned"]) == (1, 135 + 4 * first.hp_max)
