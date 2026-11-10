"""A fight's rounds as the timeline reads them, the campaign's initiative mode, and the rest of backlog Fixes 10 in
play (table voice and fixes Task B1.3)."""

import pytest

from delve.dice import ScriptedRng
from delve.play import characters, combat
from delve.play.context import NotFound, PlayError, context_for
from tests.fixtures.combat import GARREK, PIPPA, CombatReference, setup_fight
from tests.fixtures.rulesets import over


@pytest.fixture
def at(storage, campaign):
    """`at(*dice, beat="beat-1")`: a context on the campaign with scripted dice, as test_combat's."""

    def make(*values: int, beat: str = "beat-1"):
        return context_for(storage, campaign.id, beat, ScriptedRng(values), catalogs=over(CombatReference()))

    return make


@pytest.fixture
def party(at):
    ctx = at()
    return [characters.create(ctx, name="Garrek", sheet=GARREK), characters.create(ctx, name="Pippa", sheet=PIPPA)]


ROW_KEYS = {"id", "name", "side", "character_id", "node", "count", "group", "ongoing"}


def test_setup_records_round_one_unresolved(storage, at, party):
    setup_fight(at, spells=[{"caster": "Pippa", "spell": "sleep"}])
    fight_id = storage.combats.live(party[0].campaign_id)[0]
    row = storage.combat_rounds.get(fight_id, 1)
    assert (row.round, row.mode, row.beat_id, row.outcomes, row.resolved_at, row.released_at) == (
        1,
        "combatant",
        "beat-1",
        None,
        None,
        None,
    )
    assert row.rolled_at
    # Pippa casts on 2 + 1 = 3, first; then Garrek on 4, Goblin 1 on 5 and Goblin 2 on 6.
    assert [(s["name"], s["count"]) for s in row.slots] == [
        ("Pippa", 3),
        ("Garrek", 4),
        ("Goblin 1", 5),
        ("Goblin 2", 6),
    ]
    assert all(set(s) == ROW_KEYS for s in row.slots)
    assert row.slots[0]["ongoing"] == {
        "kind": "spell",
        "what": "sleep",
        "started_round": 1,
        "started_count": 1,
        "completes_round": 1,
        "completes_count": 3,
        "state": "ongoing",
        "reason": None,
    }
    assert row.slots[1]["ongoing"] is None and row.slots[2]["side"] == "enemy"


def test_combat_round_records_the_round(storage, at, party):
    setup_fight(at, spells=[{"caster": "Pippa", "spell": "sleep"}])
    fight_id = storage.combats.live(party[0].campaign_id)[0]
    first = storage.combat_rounds.get(fight_id, 1)
    # Garrek (4) swings at Goblin 1: 19 hits, 8 damage kills it.
    out = combat.combat_round(at(19, 6), [{"attacker": "Garrek", "target": "Goblin 1"}])
    assert out["outcomes"] == {
        "acted": [party[1].id, party[0].id],
        "downed": [],
        "dead": ["mon_1"],
        "fled": [],
        "completed": [{"id": party[1].id, "what": "sleep"}],
        "interrupted": [],
    }
    row = storage.combat_rounds.get(fight_id, 1)
    assert row.outcomes == out["outcomes"] and row.resolved_at and row.released_at is None
    assert row.rolled_at == first.rolled_at and row.slots == first.slots
    assert [r.round for r in storage.combat_rounds.unreleased(party[0].campaign_id)] == [1]
    # Round 2 is rolled and resolved by one call: one row, with its outcomes.
    combat.combat_round(at(1, 1, 1), [])
    second = storage.combat_rounds.get(fight_id, 2)
    assert second.outcomes is not None and [s["count"] for s in second.slots][:3] == [1, 1, 1]


def test_side_mode_from_the_campaign(storage, campaign, at, party):
    storage.campaigns.set_initiative(campaign.id, "side")
    out = setup_fight(at, init_rolls=(3, 6))
    assert out["sides"] == {"party": 3, "enemy": 6}
    assert [(e["name"], e["total"]) for e in out["order"]] == [
        ("Garrek", 3),
        ("Pippa", 3),
        ("Goblin 1", 6),
        ("Goblin 2", 6),
    ]
    fight_id = storage.combats.live(campaign.id)[0]
    row = storage.combat_rounds.get(fight_id, 1)
    assert row.mode == "side" and {s["group"] for s in row.slots} == {"party", "enemy"}
    # Back to per combatant: the next round rolls one d6 each.
    storage.campaigns.set_initiative(campaign.id, "combatant")
    combat.combat_round(at(), [])  # round 1 was rolled per side
    ctx = at(1, 2, 3, 4)
    combat.combat_round(ctx, [])
    assert ctx.dice.rng.calls == [(1, 6)] * 4
    assert storage.combat_rounds.get(fight_id, 2).mode == "combatant"


def test_interrupt_records_in_the_rounds_outcomes(storage, at, party):
    setup_fight(at, spells=[{"caster": "Pippa", "spell": "sleep"}])
    out = combat.interrupt(at(), "Pippa", "Pippa was hit")
    assert out == {"id": party[1].id, "name": "Pippa", "kind": "spell", "perceived": "Pippa was hit; sleep is lost",
                   "dm_only": {}}  # fmt: skip
    status = combat.combat_status(at())
    assert next(c for c in status["combatants"] if c["name"] == "Pippa")["ongoing"]["state"] == "interrupted"
    result = combat.combat_round(at(), [])
    assert result["outcomes"]["interrupted"] == [{"id": party[1].id, "what": "sleep", "reason": "Pippa was hit"}]
    # The round's slots still show the spell under way: how it ended waits in the outcomes for the narration.
    fight_id = storage.combats.live(party[0].campaign_id)[0]
    assert storage.combat_rounds.get(fight_id, 1).slots[0]["ongoing"]["state"] == "ongoing"


def test_adjudicate_outside_a_fight(storage, at, party):
    """Backlog Fixes 10: adjudicate was refused outside a fight."""
    out = combat.adjudicate(
        at(),
        "Garrek drinks from the black pool",
        [{"target": "Garrek", "name": "chilled", "duration": 3, "to_hit": -1}],
    )
    assert out == {
        "note": "Garrek drinks from the black pool",
        "effects": [
            {"target": "Garrek", "target_id": party[0].id, "effect": {"name": "chilled", "duration": 3, "to_hit": -1}}
        ],
    }
    garrek = storage.characters.get(party[0].id)
    assert [(e.name, e.duration, e.to_hit) for e in garrek.state.effects] == [("chilled", 3, -1)]
    assert combat.adjudicate(at(), "The bridge holds.") == {"note": "The bridge holds.", "effects": []}
    with pytest.raises(NotFound):
        combat.adjudicate(at(), "Nobody", [{"target": "Zed", "name": "x", "duration": 1}])


def test_add_combatant_hp_max(storage, at, party):
    """Backlog Fixes 10: add_combatant took no hp_max."""
    setup_fight(at)
    group = combat.add_combatant(at(), "ogre", stats={"hp": 9, "hp_max": 30, "ac": 5})
    assert group["individuals"] == [{"id": "mon_3", "name": "Ogre", "hp": 9}]
    ogre = next(c for c in combat.combat_status(at())["combatants"] if c["name"] == "Ogre")
    assert (ogre["hp"], ogre["hp_max"]) == (9, 30)
    combat.add_combatant(at(), "ogre", stats={"hp": 12, "ac": 5})
    second = next(c for c in combat.combat_status(at())["combatants"] if c["id"] == "mon_4")
    assert (second["hp"], second["hp_max"]) == (12, 12)


def test_setup_notes_hold_stated_differences(storage, at, party, monkeypatch):
    seen = []

    def stated(storage_, campaign_id, monster, reference_row):
        seen.append((campaign_id, monster, reference_row))
        return [
            f"The module gives {monster.title()} AC 5 (the reference says 6): pass ac=5 in setup_combat's monsters."
        ]

    monkeypatch.setattr(combat, "stated_differences", stated)
    out = setup_fight(at)
    assert (
        out["notes"][-1] == "The module gives Goblin AC 5 (the reference says 6): pass ac=5 in setup_combat's monsters."
    )
    assert seen == [(party[0].campaign_id, "goblin", None)]


def test_characters_untouched_by_a_ruling_in_a_fight(storage, at, party):
    setup_fight(at)
    combat.adjudicate(at(), "Held", [{"target": "Goblin 1", "name": "held", "duration": 2}])
    assert characters.get(at(), "Garrek").state.effects == ()


def test_a_rounds_result_is_lean(storage, at, party):
    """DEL-79: a round's result was 14–17 KB. Its rolls are in its actions, not in a list beside them, and its status
    has who stands how, not the fixed stats `combat_status` gives."""
    setup_fight(at)
    out = combat.combat_round(at(19, 6), [{"attacker": "Garrek", "target": "Goblin 1"}])
    assert "rolls" not in out
    swing = next(a for a in out["actions"] if a.get("attacker") == "Garrek")
    assert swing["roll"] == 19 and swing["hit"] is True
    entries = {entry["name"]: entry for entry in out["status"]["combatants"]}
    assert set(entries["Garrek"]) >= {"id", "name", "side", "hp", "hp_max", "status"}
    assert not set(entries["Garrek"]) & {"ac", "thac0", "size", "damage_sm", "damage_l", "weapon", "morale", "init"}
    assert entries["Goblin 1"]["status"] == "dead"
    assert "effects" not in entries["Pippa"] and "ongoing" not in entries["Pippa"], "an empty field is left out"
    full = {entry["name"]: entry for entry in combat.combat_status(at())["combatants"]}
    assert full["Garrek"]["ac"] is not None, "combat_status still has the fixed stats"


def memorize_sleep(at):
    """Pippa as a caster who keeps her memorized spells: one 1st-level slot, Sleep in it."""
    characters.update(at(), "Pippa", {"spell_slots": {1: 1}, "memorized": [{"name": "Sleep", "level": 1}]})


def test_a_spell_declared_in_a_fight_spends_its_memorized_copy(storage, at, party):
    """DEL-326: the fight spends the copy when the spell is begun (it is lost if spoiled too), so the DM doesn't
    cast_spell it after; one already spent, or never memorized, is refused before the round resolves anything."""
    memorize_sleep(at)
    out = setup_fight(at, spells=[{"caster": "Pippa", "spell": "sleep"}])
    assert out["spells_spent"] == [{"caster": "Pippa", "spell": "Sleep", "remaining": {"1": 0}}]
    assert [s.cast for s in characters.get(at(), "Pippa").state.memorized] == [True]

    before = storage.combats.live(party[0].campaign_id)[1]["round"]
    with pytest.raises(PlayError, match="already cast every memorized sleep"):
        combat.combat_round(at(), [{"caster": "Pippa", "spell": "sleep"}])
    with pytest.raises(PlayError, match="not memorized magic missile"):
        combat.combat_round(at(), [{"caster": "Pippa", "spell": "magic missile"}])
    assert storage.combats.live(party[0].campaign_id)[1]["round"] == before, "nothing of the round was resolved"


def test_a_spell_not_memorized_refuses_setup_and_leaves_no_fight(storage, at, party):
    characters.update(at(), "Pippa", {"spell_slots": {1: 1}, "memorized": []})
    with pytest.raises(PlayError, match="not memorized sleep"):
        combat.setup_combat(
            at(), enemies=[{"name": "goblin", "count": 1, "hp": 5}], spells=[{"caster": "Pippa", "spell": "sleep"}]
        )
    assert storage.combats.live(party[0].campaign_id) is None


def test_a_caster_without_spell_slots_casts_as_before(storage, at, party):
    out = setup_fight(at, spells=[{"caster": "Pippa", "spell": "sleep"}])
    assert "spells_spent" not in out


def test_a_weapon_changed_mid_fight_is_the_one_the_tracker_rolls(storage, at, party):
    """DEL-332: Thrarryn handed Dimble her +1 axe; his sheet's attacks were patched and the round still rolled
    1d8+7, the old axe."""
    setup_fight(at)
    axe = {"name": "Battle axe +1", "thac0": 17, "damage_sm": "1d8+8", "damage_l": "1d8+8", "speed": 7}
    characters.update(at(), "Garrek", {"attacks": [axe]})
    fight = storage.combats.live(party[0].campaign_id)[1]
    blocks = fight["combatants"][party[0].id]["attacks"]
    assert [(b["name"], b["damage_sm"], b["thac0"]) for b in blocks] == [("Battle axe +1", "1d8+8", 17)]


def test_a_thrown_flask_of_oil_burns_and_holy_water_spares_the_living(storage, at, party):
    """DEL-333: barrowmaze's mummy fight ran oil and holy water as plain rolls, each with its own target number; a
    throw is an attack roll with the thrower's THAC0, and the missile's damage."""
    setup_fight(at)
    # Pippa (THAC0 20) at Goblin 1 (AC 6) needs 14: 15 hits, the oil's 2d6 is 3 + 4.
    out = combat.throw_missile(at(15, 3, 4), "Pippa", "Goblin 1", "flask of oil")
    assert (out["missile"], out["hit"], out["damage"], out["weapon"]) == ("oil", True, 7, "flask of oil")
    assert out["dead"] and "It burns on for 1d6 more next round." in out["notes"]
    living = combat.throw_missile(at(15, 1, 1), "Garrek", "Goblin 2", "holy water")
    assert living["hit"] and not living["damage"] and any("only the undead" in n for n in living["notes"])
    garrek = storage.combats.live(party[0].campaign_id)[1]["combatants"][party[0].id]
    assert [a["name"] for a in garrek["attacks"]] == ["long sword"], "the thrower's own attacks are back"
    with pytest.raises(PlayError, match="Unknown missile"):
        combat.combat_round(at(), [{"attacker": "Pippa", "target": "Goblin 2", "missile": "acid"}])


def test_update_combatant_sets_the_modules_numbers(storage, at, party):
    """DEL-333: kobolds set up with default damage were patched with an effect (dmg +1); the module's numbers are
    set instead."""
    setup_fight(at)
    out = combat.update_combatant(at(), "Goblin 1", {"ac": 4, "hp": 8, "dmg": "1d4+1"})
    assert out["set"] == {"ac": 4, "hp": 8, "dmg": "1d4+1"}
    goblin = storage.combats.live(party[0].campaign_id)[1]["combatants"]["mon_1"]
    assert (goblin["ac"], goblin["hp"], goblin["hp_max"]) == (4, 8, 8)
    assert (goblin["attacks"][0]["damage_sm"], goblin["attacks"][0]["damage_l"]) == ("1d4+1", "1d4+1")
    with pytest.raises(PlayError, match="Can't set 'speed'"):
        combat.update_combatant(at(), "Goblin 1", {"speed": 3})
    with pytest.raises(PlayError, match="dice notation"):
        combat.update_combatant(at(), "Goblin 1", {"dmg": "lots"})


def test_effects_go_on_and_come_off_a_character_outside_a_fight(storage, at, party):
    """DEL-334: remove_effect after end_combat was refused ("No combat is under way") and the DM patched the sheet's
    effects by hand."""
    combat.apply_effect(at(), "Pippa", "invisible", 60)
    assert [e.name for e in characters.get(at(), "Pippa").state.effects] == ["invisible"]
    out = combat.remove_effect(at(), "Pippa", "Invisible")
    assert out["removed"]["name"] == "invisible" and characters.get(at(), "Pippa").state.effects == ()
    with pytest.raises(PlayError, match="No active effect named 'bless'"):
        combat.remove_effect(at(), "Pippa", "bless")


def test_an_unidentified_items_bonus_applies_unseen_and_lasts(storage, at, party):
    """DEL-335: a "plain silver ring" of protection went onto the sheet as AC 2, which the players see; as a hidden
    effect lasting until removed it counts in the fight, shows to no seat, and doesn't tick away."""
    from delve.web.routes.characters import character_json, player_character_json

    combat.apply_effect(at(), "Garrek", "ring of protection +1", 0, ac=-1, save=1, hidden=True)
    garrek = characters.get(at(), "Garrek")
    assert garrek.sheet.ac == 4, "the sheet's AC stays"
    assert [e["name"] for e in character_json(garrek)["state"]["effects"]] == ["ring of protection +1"]
    assert player_character_json(garrek)["state"]["effects"] == []
    setup_fight(at)
    combat.combat_round(at(1, 1, 1, 1), [])
    combat.combat_round(at(1, 1, 1, 1), [])
    fighting = storage.combats.live(party[0].campaign_id)[1]["combatants"][party[0].id]
    assert [(e["name"], e["duration"], e["hidden"]) for e in fighting["effects"]] == [
        ("ring of protection +1", 0, True)
    ]


def test_a_rest_mid_fight_is_kept_by_the_tracker(storage, at, party):
    """A rest saved a fighting character's hit points beside the tracker, and the fight's next write put the old ones
    back; the tracker takes the rest as it takes `update`."""
    setup_fight(at)
    characters.apply_damage(at(), "Garrek", 5)
    wounded = characters.get(at(), "Garrek").state.hp
    characters.rest(at(), "Garrek", days=2)
    assert characters.get(at(), "Garrek").state.hp == wounded + 2
    combat.add_condition(at(), "Goblin 1", "prone")  # any change to the fight writes its combatants through
    assert characters.get(at(), "Garrek").state.hp == wounded + 2
    assert storage.combats.live(party[0].campaign_id)[1]["combatants"][party[0].id]["hp"] == wounded + 2
