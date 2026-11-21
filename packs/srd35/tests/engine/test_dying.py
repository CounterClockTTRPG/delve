"""Disabled at 0 hp and the dying's roll to stabilise under the srd35 ruleset (DEL-434, DEL-442), through the tools:
the fight's rules switch them on (`tables.TABLES.fight`), and a character's state follows its combatant."""

from __future__ import annotations

from delve_srd35.tables import TABLES

from delve.rules.classic import combat as rules


def _fight(storage, campaign) -> rules.Combat:
    return rules.from_json(storage.combats.live(campaign.id)[1])


def _state(storage, campaign, name: str):
    return next(c for c in storage.characters.list(campaign.id) if c.name == name).state


def test_the_fight_rules_disable_at_zero_and_roll_10_percent():
    assert (TABLES.fight.disabled_at_zero, TABLES.fight.stabilise_chance) == (True, 10)


def test_a_character_at_zero_is_disabled_in_its_state(srd35_call, srd35_storage, srd35_campaign):
    sheet = {"cls": "Fighter", "level": 1, "race": "Human", "hp_max": 10,
             "ability_scores": {"str": 14, "dex": 12, "con": 12, "int": 10, "wis": 10, "cha": 10}}  # fmt: skip
    assert "error" not in srd35_call("create_character", name="Oryn", sheet=sheet)
    assert "error" not in srd35_call("setup_combat", enemies=[{"name": "orc", "count": 1}], surprise=False)
    hp = _fight(srd35_storage, srd35_campaign).combatants
    oryn = next(c for c in hp.values() if c.name == "Oryn")
    out = srd35_call("apply_damage", character="Oryn", amount=oryn.hp)
    assert out["hp_after"] == 0 and out["downed"] is False and out["disabled"] is True, out
    state = _state(srd35_storage, srd35_campaign, "Oryn")
    assert "disabled" in state.conditions and "downed" not in state.conditions
    # One more point: -1, downed and dying, no longer disabled.
    srd35_call("apply_damage", character="Oryn", amount=1)
    state = _state(srd35_storage, srd35_campaign, "Oryn")
    assert state.hp == -1 and "downed" in state.conditions and "disabled" not in state.conditions


def _oryn(srd35_call):
    sheet = {"cls": "Fighter", "level": 1, "race": "Human", "hp_max": 10,
             "ability_scores": {"str": 14, "dex": 12, "con": 12, "int": 10, "wis": 10, "cha": 10}}  # fmt: skip
    assert "error" not in srd35_call("create_character", name="Oryn", sheet=sheet)


def test_out_of_a_fight_zero_is_disabled_too(srd35_call, srd35_storage, srd35_campaign):  # fix round 1
    # Damaged to exactly 0 with no fight on: disabled, not downed; one more: downed.
    _oryn(srd35_call)
    hp = _state(srd35_storage, srd35_campaign, "Oryn").hp
    out = srd35_call("apply_damage", character="Oryn", amount=hp)
    assert (out["hp_after"], out["downed"], out.get("disabled")) == (0, False, True), out
    state = _state(srd35_storage, srd35_campaign, "Oryn")
    assert "disabled" in state.conditions and "downed" not in state.conditions
    srd35_call("apply_damage", character="Oryn", amount=1)
    state = _state(srd35_storage, srd35_campaign, "Oryn")
    assert "downed" in state.conditions and "disabled" not in state.conditions


def test_a_fight_ended_at_zero_heals_out_of_disabled(srd35_call, srd35_storage, srd35_campaign):  # fix round 1
    # Oryn ends the fight at 0, disabled in his state; healed after it, the disabled comes off.
    _oryn(srd35_call)
    srd35_call("setup_combat", enemies=[{"name": "orc", "count": 1}], surprise=False)
    srd35_call("apply_damage", character="Oryn", amount=_state(srd35_storage, srd35_campaign, "Oryn").hp)
    assert "error" not in srd35_call("end_combat")
    assert "disabled" in _state(srd35_storage, srd35_campaign, "Oryn").conditions
    srd35_call("apply_heal", character="Oryn", amount=3)
    state = _state(srd35_storage, srd35_campaign, "Oryn")
    assert state.hp == 3 and not {"disabled", "downed"} & set(state.conditions)
