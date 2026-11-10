"""The classic engine's fight (`delve.rules.classic.combat`), in core: initiative, an attack and a round, life and
death by hit points, and what the end of a fight writes back. Each over the fake ruleset's tables and the play tests'
goblin (`tests.fixtures.combat`), with scripted dice, so none needs a pack."""

from dataclasses import replace

import pytest

from delve.dice import Dice, MemoryRollLog, ScriptedRng
from delve.domain.campaigns import Character
from delve.domain.characters import Attack, CharacterState, Sheet
from delve.rules.classic import combat as cb
from delve.rules.classic.life import DEAD_AT
from delve.rules.fake import FAKE_TABLES
from tests.fixtures.combat import CombatReference

REF = CombatReference(goblins=True)


def dice(*values: int) -> Dice:
    return Dice(ScriptedRng(values), MemoryRollLog(), "cmp_1", "beat-1")


def pc(id: str, name: str, hp: int = 30, thac0: int = 18) -> Character:
    """A fighter with a long sword of speed 5, which the fake ruleset leaves out of initiative."""
    sword = Attack("long sword", speed=5, damage_sm="1d8+2")
    sheet = Sheet(cls="Fighter", hp_max=30, thac0=thac0, ac=4, attacks=(sword,))
    return Character(id=id, campaign_id="cmp_1", name=name, kind="pc", sheet=sheet, state=CharacterState(hp=hp))


GARREK = pc("chr_garrek", "Garrek")


def fight_with_goblins(*party: Character, goblins: int = 2, hp: int = 5) -> cb.Combat:
    """The party against `goblins` goblins (AC 6, THAC0 20, 1d6) of `hp` each, before any initiative."""
    fight, _ = cb.start(party or (GARREK,))
    fight, _ = cb.add_monsters(fight, dice(), REF, "goblin", goblins, overrides={"hp": hp})
    return fight


def initiative(fight: cb.Combat, *rolls: int, mode: str = "combatant") -> tuple[cb.Combat, dict]:
    return cb.roll_initiative(fight, dice(*rolls), REF, mode, FAKE_TABLES)


# --- setting up ---------------------------------------------------------------------------------------------------


def test_a_fight_starts_with_the_party_as_it_is():
    hurt = pc("chr_mira", "Mira", hp=12)
    fight, out = cb.start([GARREK, hurt])
    assert out["party_loaded"] == ["Garrek", "Mira"]
    assert fight.combatants["chr_mira"].hp == 12 and fight.combatants["chr_mira"].side == "party"


def test_a_second_fight_is_refused_while_one_is_live():
    fight = fight_with_goblins()
    with pytest.raises(cb.CombatActive):
        cb.start([GARREK], live=fight)
    again, _ = cb.start([GARREK], live=fight, abort=True)
    assert [c.side for c in again.combatants.values()] == ["party"]


def test_monsters_are_numbered_with_their_hit_points():
    fight = fight_with_goblins(goblins=2, hp=5)
    goblins = [c for c in fight.combatants.values() if c.side == "enemy"]
    assert [(c.id, c.name, c.hp) for c in goblins] == [("mon_1", "Goblin 1", 5), ("mon_2", "Goblin 2", 5)]


# --- initiative ---------------------------------------------------------------------------------------------------


def test_initiative_goes_lowest_first():
    _, out = initiative(fight_with_goblins(), 4, 2, 5)  # Garrek, Goblin 1, Goblin 2
    assert [(o["name"], o["total"]) for o in out["order"]] == [("Goblin 1", 2), ("Garrek", 4), ("Goblin 2", 5)]


def test_side_initiative_rolls_once_a_side():
    _, out = initiative(fight_with_goblins(), 3, 1, mode="side")
    assert out["sides"] == {"party": 3, "enemy": 1}
    assert [o["name"] for o in out["order"]] == ["Goblin 1", "Goblin 2", "Garrek"]
    assert len(out["rolls"]) == 2


def test_an_attack_before_initiative_is_refused():
    with pytest.raises(cb.CombatError):
        cb.attack(fight_with_goblins(), dice(15, 3), "chr_garrek", "mon_1")


# --- attacks ------------------------------------------------------------------------------------------------------


def test_an_attack_that_hits_does_its_damage():
    """THAC0 18 against AC 6 needs 12: a 15 hits, and the long sword's 1d8+2 is 3 + 2."""
    fight, _ = initiative(fight_with_goblins(hp=8), 1, 2, 3)
    fight, out = cb.attack(fight, dice(15, 3), "chr_garrek", "mon_1")
    assert (out["hit"], out["damage"], out["hp_after"]) == (True, 5, 3)
    assert fight.combatants["mon_1"].hp == 3


def test_an_attack_that_misses_does_nothing():
    fight, _ = initiative(fight_with_goblins(hp=8), 1, 2, 3)
    fight, out = cb.attack(fight, dice(11), "chr_garrek", "mon_1")
    assert out["hit"] is False and fight.combatants["mon_1"].hp == 8


def test_a_natural_20_always_hits_and_a_natural_1_always_misses():
    weak = pc("chr_weak", "Weakling", thac0=25)  # needs 31 against AC 6
    fight, _ = initiative(fight_with_goblins(weak, hp=8), 1, 2, 3)
    fight, hit = cb.attack(fight, dice(20, 1), "chr_weak", "mon_1")
    assert hit["hit"] is True
    strong = pc("chr_strong", "Strongarm", thac0=1)
    fight, _ = initiative(fight_with_goblins(strong, hp=8), 1, 2, 3)
    _, miss = cb.attack(fight, dice(1), "chr_strong", "mon_1")
    assert miss["hit"] is False


def test_a_round_resolves_in_initiative_order_and_the_dead_dont_act():
    """Garrek (count 1) fells Goblin 1 (count 3) before it swings; Goblin 2 (count 5) swings and misses. The counts
    are the rolls alone: the fake ruleset adds no weapon speed, nor does a declaration after the roll."""
    fight, _ = initiative(fight_with_goblins(), 1, 3, 5)
    declared = [
        {"attacker": "Garrek", "target": "Goblin 1"},
        {"attacker": "Goblin 1", "target": "Garrek"},
        {"attacker": "Goblin 2", "target": "Garrek"},
    ]
    fight, result = cb.run_round(fight, dice(15, 3, 2), REF, declared, rules=FAKE_TABLES)
    assert [slot["count"] for slot in result.slots] == [1, 3, 5]
    assert [(a["attacker"], a.get("skipped")) for a in result.actions] == [
        ("Garrek", None),
        ("Goblin 1", "dead — cannot act"),
        ("Goblin 2", None),
    ]
    assert result.outcomes["dead"] == ["mon_1"]
    assert fight.combatants["chr_garrek"].hp == 30
    assert fight.round == 2


def test_a_declaration_after_initiative_adds_weapon_speed_only_where_the_ruleset_does():
    """Round 1's initiative is rolled at setup, before the declarations; a ruleset that leaves weapon speed out of
    initiative (OSRIC, the fake one) keeps the declarer on its roll, one that adds it moves it to roll + speed."""
    fight, _ = initiative(fight_with_goblins(), 1, 3, 5)
    kept, _ = cb.declare(fight, "chr_garrek", {"target": "Goblin 1"}, REF, FAKE_TABLES)
    assert kept.combatants["chr_garrek"].init == 1
    with_speed = replace(FAKE_TABLES, weapon_speed_in_initiative=True)
    fight, _ = initiative(fight_with_goblins(), 1, 3, 5)
    moved, out = cb.declare(fight, "chr_garrek", {"target": "Goblin 1"}, REF, with_speed)
    assert moved.combatants["chr_garrek"].init == 6 and "now acts on 6" in out["hint"]


# --- life and death -----------------------------------------------------------------------------------------------


def test_a_character_is_downed_at_0_and_dead_at_minus_10():
    fight, _ = initiative(fight_with_goblins(), 1, 2, 3)
    fight, out = cb.damage(fight, "chr_garrek", 30)
    assert (out["hp_after"], out["downed"], out["dead"]) == (0, True, False)
    assert cb.status_of(fight.combatants["chr_garrek"]) == "unconscious"
    fight, out = cb.damage(fight, "chr_garrek", 50)
    assert (out["hp_after"], out["dead"]) == (DEAD_AT, True), "no lower than -10"
    assert cb.status_of(fight.combatants["chr_garrek"]) == "dead"


def test_a_monster_is_dead_at_0():
    fight, _ = initiative(fight_with_goblins(), 1, 2, 3)
    fight, out = cb.damage(fight, "mon_1", 5)
    assert out["dead"] is True and cb.status_of(fight.combatants["mon_1"]) == "dead"


def test_healing_brings_the_downed_round_and_stops_at_the_maximum():
    fight, _ = initiative(fight_with_goblins(), 1, 2, 3)
    fight, _ = cb.damage(fight, "chr_garrek", 32)
    fight, out = cb.heal(fight, "chr_garrek", 50)
    assert (out["hp_before"], out["hp_after"], out["healed"]) == (-2, 30, 32)
    assert out["notes"] == ["Garrek regains consciousness."]
    assert "downed" not in fight.combatants["chr_garrek"].conditions


def test_healing_doesnt_raise_the_dead():
    fight, _ = initiative(fight_with_goblins(), 1, 2, 3)
    fight, _ = cb.damage(fight, "chr_garrek", 40)
    with pytest.raises(cb.CombatError, match="healing doesn't raise the dead"):
        cb.heal(fight, "chr_garrek", 5)


def test_a_downed_attacker_cant_attack():
    fight, _ = initiative(fight_with_goblins(), 1, 2, 3)
    fight, _ = cb.damage(fight, "chr_garrek", 30)
    with pytest.raises(cb.CombatError):
        cb.attack(fight, dice(15, 3), "chr_garrek", "mon_1")


def test_the_dying_bleed_at_the_end_of_the_round():
    fight, _ = initiative(fight_with_goblins(), 1, 2, 3)
    fight, _ = cb.damage(fight, "chr_garrek", 32)  # -2: dying
    fight, _ = cb.run_round(fight, dice(), REF, [], rules=FAKE_TABLES)
    assert fight.combatants["chr_garrek"].hp == -3


# --- the end ------------------------------------------------------------------------------------------------------


def test_the_end_writes_back_the_party_and_counts_the_defeated():
    fight, _ = initiative(fight_with_goblins(), 1, 2, 3)
    fight, _ = cb.damage(fight, "chr_garrek", 7)
    fight, _ = cb.damage(fight, "mon_1", 5)
    ended, out = cb.end(fight)
    assert ended.phase == "ended"
    assert out["characters"]["chr_garrek"]["hp"] == 23
    (group,) = out["groups"]
    assert group["defeated"] == 1
