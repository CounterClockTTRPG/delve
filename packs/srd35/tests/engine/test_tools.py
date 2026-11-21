"""The pack's DM tools (DEL-388), through the tool host on an srd35 campaign: set_build, set_stance and provoke, and
core's saving_throw, skill_check, update_combatant and setup_combat with 3.5's numbers. An OSRIC campaign on the same
host sees none of them."""

from __future__ import annotations

import dataclasses

import pytest

from delve.dm.tools.host import all_specs
from delve.rules.classic import combat as rules

OWN = {"set_build", "set_stance", "use_feature", "provoke"}
DWARF = {"str": 16, "dex": 12, "con": 14, "int": 13, "wis": 10, "cha": 8}


def _fighter(srd35_call, name="Thorin", race="Dwarf", hp_max=12, **scores):
    sheet = {"cls": "Fighter", "level": 1, "race": race, "hp_max": hp_max, "ability_scores": {**DWARF, **scores}}
    out = srd35_call("create_character", name=name, sheet=sheet)
    assert "error" not in out, out
    return out


def _orc(srd35_call, **over):
    out = srd35_call("setup_combat", enemies=[{"name": "orc", "count": 1, "hp": 30, **over}], surprise=False)
    assert "error" not in out, out
    return out


def _fight(srd35_storage, campaign):
    return rules.from_json(srd35_storage.combats.live(campaign.id)[1])


def test_set_build_refuses_too_many_ranks(srd35_call):
    _fighter(srd35_call)
    # A fighter 1 takes at most 4 ranks in a class skill (Climb) and 2 cross-class (Hide); each problem is named.
    out = srd35_call("set_build", character="Thorin", skills={"climb": 5, "hide": 3})
    assert "Climb 5 ranks: at most 4 (a class skill, level 1)." in out["error"]
    assert "Hide 3 ranks: at most 2 (cross-class, level 1)." in out["error"]


def test_set_build_refuses_more_points_than_it_has(srd35_call):
    # (2 + Int 1) × 4 = 12 points at 1st level; 4 + 4 + 4 in class skills is 12, and 2 cross-class ranks are 4 more.
    _fighter(srd35_call)
    fine = srd35_call("set_build", character="Thorin", skills={"climb": 4, "jump": 4, "intimidate": 4})
    assert fine["skill_points"] == {"spent": 12, "total": 12}
    out = srd35_call("set_build", character="Thorin", skills={"climb": 4, "jump": 4, "intimidate": 4, "spot": 2})
    assert "16 skill points spent; Thorin has 12 so far." in out["error"]


def test_set_build_then_the_sheet_has_derived_numbers(srd35_call):
    _fighter(srd35_call)
    out = srd35_call(
        "set_build",
        character="Thorin",
        skills={"climb": 4, "intimidate": 4},
        feats=["power attack", {"id": "weapon focus", "choice": "warhammer"}],
        weapon="warhammer",
        armor="scale mail",
        shield="heavy steel shield",
    )
    assert "error" not in out, out
    assert out["build"] == {
        "skills": {"climb": 4, "intimidate": 4},
        "feats": [{"id": "power-attack"}, {"id": "weapon-focus", "choice": "warhammer"}],
        "weapon": "warhammer",
        "armor": "scale mail",
        "shield": "shield, heavy steel",
    }
    d = out["derived"]
    # AC 10 + scale mail 4 + heavy steel shield 2 + Dex 1 = 17; armour check penalty -4 - 2 = -6; Climb 4 + Str 3 - 6
    # = 1, Intimidate 4 + Cha -1 = 3; BAB +1.
    assert (d["ac"], d["touch"], d["flat_footed"], d["acp"], d["bab"]) == (17, 11, 16, -6, 1)
    assert d["skills"] == {"climb": 1, "intimidate": 3}
    assert "warnings" not in d
    # A call with nothing in it keeps the build and its numbers.
    assert srd35_call("set_build", character="Thorin")["derived"] == d


def test_natural_armour_names_resolve(srd35_call):
    _fighter(srd35_call)
    out = srd35_call(
        "set_build", character="Thorin", armor="chain mail", shield="light wooden shield", weapon="short sword"
    )
    assert (out["build"]["armor"], out["build"]["shield"], out["build"]["weapon"]) == (
        "chainmail",
        "shield, light wooden",
        "sword, short",
    )
    refused = srd35_call("set_build", character="Thorin", armor="mithral pyjamas", shield="chainmail")
    assert "Unknown armor 'mithral pyjamas'" in refused["error"] and "Unknown shield 'chainmail'" in refused["error"]


def test_set_build_checks_feat_prerequisites_and_domains(srd35_call):
    _fighter(srd35_call, str=12)
    out = srd35_call("set_build", character="Thorin", feats=["cleave"], domains=["war", "sunshine"])
    for problem in (
        "Cleave needs Str 13 (it is 12).",
        "Cleave needs Power Attack.",
        "Unknown domain 'sunshine'",
        "Only a cleric has domains.",
    ):
        assert problem in out["error"]


def test_weapon_specialization_is_taken_for_one_weapon(srd35_call):
    # Weapon Specialization, like Weapon Focus, names its weapon; the build keeps it in the table's words. A fighter
    # 4 (its prerequisite) with Weapon Focus.
    sheet = {"cls": "Fighter", "level": 4, "race": "Dwarf", "hp_max": 30, "ability_scores": DWARF}
    assert "error" not in srd35_call("create_character", name="Thorin", sheet=sheet)
    out = srd35_call("set_build", character="Thorin", feats=["weapon specialization"])
    assert "Weapon Specialization is taken for one weapon: give its choice." in out["error"], out
    focus = {"id": "weapon focus", "choice": "Longsword"}
    special = {"id": "weapon specialization", "choice": "Longsword"}
    built = srd35_call("set_build", character="Thorin", feats=[focus, special])
    assert built["build"]["feats"][1] == {"id": "weapon-specialization", "choice": "longsword"}, built


def test_a_later_int_drop_warns_not_refuses(srd35_call):  # Review Focus 3
    _fighter(srd35_call)
    built = srd35_call("set_build", character="Thorin", feats=["combat expertise"])
    assert "error" not in built and "warnings" not in built["derived"]
    out = srd35_call("update_character", ref="Thorin", patch={"ability_scores": {**DWARF, "int": 11}})
    assert "error" not in out, out
    d20 = out["sheet"]["d20"]
    assert d20["feats"] == [{"id": "combat-expertise"}]
    assert d20["derived"]["warnings"] == ["Combat Expertise needs Int 13 (it is 11)."]


def test_the_dms_patch_cant_write_the_build(srd35_call):
    _fighter(srd35_call)
    out = srd35_call("update_character", ref="Thorin", patch={"d20": {"feats": ["dodge"]}})
    assert "Can't change 'd20'" in out["error"]


def test_skill_check_takes_part_of_a_name(srd35_call):
    sheet = {"cls": "Rogue", "level": 1, "race": "Halfling", "hp_max": 6, "ability_scores": {**DWARF, "dex": 16}}
    srd35_call("create_character", name="Pip", sheet=sheet)
    srd35_call("set_build", character="Pip", skills={"open lock": 4})
    # "pick" is a classic thief skill's word for two skills; Pip has ranks only in Open Lock.
    out = srd35_call("skill_check", character="Pip", skill="pick", dc=10, modifier=2)
    assert "error" not in out, out
    assert (out["skill"], out["bonus"], out["modifier"], out["dc"]) == ("Open Lock", 7, 2, 10)
    _fighter(srd35_call)
    unsure = srd35_call("skill_check", character="Thorin", skill="pick")
    assert unsure["error"] == "Skill 'pick' could be Open Lock, Sleight of Hand."
    built = srd35_call("set_build", character="Pip", skills={"pick": 4})
    assert "Skill 'pick' could be" in built["error"]


def test_classic_skill_names_are_their_3_5_skill(srd35_call):
    from delve_srd35.engine import numbers
    from delve_srd35.reference import Srd35Reference

    reference = Srd35Reference()
    assert numbers.skill_named(reference, "hide in shadows") == "hide"
    assert numbers.skill_named(reference, "climb walls") == "climb"
    assert numbers.skill_named(reference, "knowledge (arcana)") == "knowledge-arcana"
    _fighter(srd35_call)
    out = srd35_call("set_build", character="Thorin", skills={"climb": 4, "climb walls": 4})
    assert "'climb walls' is Climb again." in out["error"]


def test_saving_throw_with_dc(srd35_call):
    _fighter(srd35_call)
    out = srd35_call("saving_throw", character="Thorin", save_type="Fortitude", dc=12, modifier=1)
    assert "error" not in out, out
    # Fort: fighter 1's +2 and Con 14's +2.
    assert (out["save_type"], out["base"], out["modifier"], out["dc"]) == ("fort", 4, 1, 12)
    roll = out["roll"]["total"]
    assert out["total"] == roll + 5
    assert out["success"] == (roll != 1 and (roll == 20 or roll + 5 >= 12))


def test_a_combatants_save_with_dc_in_the_fight(srd35_call):
    _fighter(srd35_call)
    _orc(srd35_call)
    out = srd35_call("saving_throw", character="Orc", save_type="will", dc=10)
    assert "error" not in out, out
    # The orc's Will is -2 (its row).
    assert (out["name"], out["base"], out["dc"], out["round"]) == ("Orc", -2, 10, 1)
    assert out["total"] == out["roll"]["total"] - 2


def test_provoke_once_per_round(srd35_call, srd35_storage, srd35_campaign):
    _fighter(srd35_call)
    _orc(srd35_call)
    srd35_call("update_combatant", id="Orc", attack_bonus=40)  # a hit on any face but a natural 1
    _acted(srd35_storage, srd35_campaign, "Orc")
    first = srd35_call("provoke", provoker="Thorin", threatened_by=["Orc"])
    assert "error" not in first, first
    (swing,) = first["attacks"]
    assert swing["attack_of_opportunity"] is True and swing["attacker"] == "Orc" and swing["hit"] is True
    assert swing["rolls"][0]["purpose"] == "attack#aoo"
    fight = _fight(srd35_storage, srd35_campaign)
    orc = next(c for c in fight.combatants.values() if c.name == "Orc")
    thorin = next(c for c in fight.combatants.values() if c.name == "Thorin")
    assert orc.attacks_used == 0 and orc.d20["aoo"] == {"round": 1, "used": 1}
    # Applied through core's path: the tracker and the character's state.
    assert thorin.hp == swing["hp_after"] == 12 - swing["damage"]
    assert srd35_storage.characters.get(thorin.character_id).state.hp == swing["hp_after"]
    again = srd35_call("provoke", provoker="Thorin", threatened_by=["Orc"])
    assert again["attacks"] == [
        {"id": orc.id, "name": "Orc", "refused": "already used its attack of opportunity this round"}
    ]


def _acted(storage, campaign, name, init=None):
    """The fight with `name` past its turn in round 1 (its initiative above everyone's), so it isn't flat-footed."""
    id, raw = storage.combats.live(campaign.id)
    fight = rules.from_json(raw)
    c = next(c for c in fight.combatants.values() if c.name == name)
    top = max((o.init or 0) for o in fight.combatants.values()) + 1
    fight = dataclasses.replace(fight, combatants={**fight.combatants, c.id: dataclasses.replace(c, init=init or top)})
    storage.combats.save(id, fight.phase, rules.to_json(fight))


def test_a_flat_footed_foe_gets_no_attack_of_opportunity(srd35_call, srd35_storage, srd35_campaign):
    _fighter(srd35_call)
    _orc(srd35_call)
    # Round 1, and the orc hasn't acted yet: Thorin's initiative is above its own.
    _acted(srd35_storage, srd35_campaign, "Thorin")
    out = srd35_call("provoke", provoker="Thorin", threatened_by=["Orc"])
    assert out["attacks"] == [{"id": "mon_1", "name": "Orc", "refused": "is flat-footed: no attack of opportunity"}]
    _acted(srd35_storage, srd35_campaign, "Orc")
    srd35_call("add_condition", name="Orc", condition="flat-footed")
    out = srd35_call("provoke", provoker="Thorin", threatened_by=["Orc"])
    assert out["attacks"][0]["refused"] == "is flat-footed: no attack of opportunity"
    orc = next(c for c in _fight(srd35_storage, srd35_campaign).combatants.values() if c.name == "Orc")
    assert orc.d20["aoo"] == {"round": 0, "used": 0}  # a refusal spends nothing


def test_provoke_refuses_a_removed_provoker(srd35_call):
    _fighter(srd35_call)
    _orc(srd35_call)
    srd35_call("remove_combatant", id="Thorin", reason="fled the map")
    assert "removed" in srd35_call("provoke", provoker="Thorin", threatened_by=["Orc"])["error"]


def test_a_failed_swing_leaves_no_aoo_mark(srd35_call, srd35_host, srd35_storage, srd35_campaign, monkeypatch):
    from delve_srd35.engine import tools

    from delve.play import combat as play_combat
    from delve.play.context import PlayError, context_for

    _fighter(srd35_call)
    _orc(srd35_call)
    _acted(srd35_storage, srd35_campaign, "Orc")

    def broken(*args, **kwargs):
        raise PlayError("the swing broke")

    monkeypatch.setattr(play_combat, "resolve_attack", broken)
    ctx = context_for(srd35_storage, srd35_campaign.id, "beat-1", catalogs=srd35_host.catalogs)
    with pytest.raises(PlayError, match="the swing broke"):
        tools.provoke(ctx, "Thorin", ["Orc"])
    orc = next(c for c in _fight(srd35_storage, srd35_campaign).combatants.values() if c.name == "Orc")
    assert orc.d20["aoo"] == {"round": 0, "used": 0}


def test_set_build_mid_fight_keeps_stance_and_a_used_aoo(srd35_call, srd35_storage, srd35_campaign):
    _fighter(srd35_call)
    _orc(srd35_call)
    srd35_call("set_build", character="Thorin", feats=["power attack"])
    srd35_call("set_stance", combatant="Thorin", power_attack=1, defensive=True)
    _acted(srd35_storage, srd35_campaign, "Thorin")
    assert "refused" not in srd35_call("provoke", provoker="Orc", threatened_by=["Thorin"])["attacks"][0]
    srd35_call("set_build", character="Thorin", weapon="warhammer")  # core's rearm rebuilds the combatant
    thorin = next(c for c in _fight(srd35_storage, srd35_campaign).combatants.values() if c.name == "Thorin")
    assert thorin.d20["stance"] == {"power_attack": 1, "defensive": True}
    assert thorin.d20["aoo"] == {"round": 1, "used": 1}
    assert thorin.d20["attacks"][0]["name"] == "warhammer"


def test_set_stance_takes_power_attack_up_to_bab(srd35_call, srd35_storage, srd35_campaign):
    _fighter(srd35_call)
    _orc(srd35_call)
    assert "hasn't the Power Attack feat" in srd35_call("set_stance", combatant="Thorin", power_attack=1)["error"]
    srd35_call("set_build", character="Thorin", feats=["power attack"])
    assert "0 to 1" in srd35_call("set_stance", combatant="Thorin", power_attack=2)["error"]
    out = srd35_call("set_stance", combatant="Thorin", power_attack=1, defensive=True)
    assert out["stance"] == {"power_attack": 1, "defensive": True}
    thorin = next(c for c in _fight(srd35_storage, srd35_campaign).combatants.values() if c.name == "Thorin")
    assert thorin.d20["stance"] == {"power_attack": 1, "defensive": True}


def test_update_combatant_takes_d20_overrides(srd35_call, srd35_storage, srd35_campaign):
    _fighter(srd35_call)
    _orc(srd35_call)
    out = srd35_call(
        "update_combatant",
        id="Orc",
        ac=18,
        touch_ac=12,
        flat_footed_ac=16,
        attack_bonus=7,
        damage="1d12+4",
        critical="19–20/×3",
        saves={"fort": 5},
        stats={"hp": 20},
    )
    assert "error" not in out, out
    orc = next(c for c in _fight(srd35_storage, srd35_campaign).combatants.values() if c.name == "Orc")
    assert (orc.hp, orc.ac, orc.d20["ac"], orc.d20["touch"], orc.d20["flat_footed"]) == (20, 18, 18, 12, 16)
    held = next(f for f in orc.d20["attacks"] if f["name"] == orc.attacks[orc.weapon].name)
    assert (held["bonus"], held["damage"], held["threat"], held["mult"]) == (7, "1d12+4", 19, 3)
    assert orc.d20["saves"]["fort"] == 5


def test_setup_combat_takes_d20_overrides_per_group(srd35_call, srd35_storage, srd35_campaign):
    _fighter(srd35_call)
    _orc(srd35_call, touch_ac=9, critical="×4")
    orc = next(c for c in _fight(srd35_storage, srd35_campaign).combatants.values() if c.name == "Orc")
    assert orc.d20["touch"] == 9
    assert orc.d20["attacks"][orc.weapon]["mult"] == 4


def test_osric_campaign_doesnt_see_these_tools(call, srd35_host):
    core = [spec.name for spec in all_specs()]
    assert [spec.name for spec in srd35_host.specs("osric")] == core
    own = ["set_build", "convert_spell", "set_stance", "use_feature", "add_companion", "spell_resistance", "provoke"]
    assert [spec.name for spec in srd35_host.specs("srd35")] == [*core, *own]
    assert call("set_build", character="Garrek")["error"] == "Unknown tool 'set_build'."


@pytest.mark.parametrize(
    "name", ["saving_throw", "skill_check", "update_combatant", "setup_combat", "resolve_attack", "combat_round"]
)
def test_the_scoped_tools_keep_core_params(srd35_host, name):
    core = next(spec for spec in all_specs() if spec.name == name)
    mine = srd35_host.spec(name, "srd35")
    assert mine is not core and mine.rulesets == ("srd35",)
    assert set(core.params["properties"]) <= set(mine.params["properties"])


def test_resolve_attack_names_the_3_5_conditions(srd35_host):
    condition = srd35_host.spec("resolve_attack", "srd35").params["properties"]["condition"]["description"]
    for said in ("flanked", "charging", "set_vs_charge", "into_melee", "Precise Shot"):
        assert said in condition, said


def test_combat_round_says_a_charge_or_single_is_one_attack(srd35_host):  # DEL-389
    actions = srd35_host.spec("combat_round", "srd35").params["properties"]["actions"]["description"]
    assert '"single": true' in actions and "full attack" in actions and "charging" in actions


def test_initiative_is_rolled_once_highest_first(srd35_call, srd35_storage, srd35_campaign):
    # The SRD's Initiative Checks: highest result first, rolled once at the start of the battle, the same order after.
    _fighter(srd35_call)
    out = srd35_call("setup_combat", enemies=[{"name": "orc", "count": 3, "hp": 30}], surprise=False)
    assert "error" not in out, out
    totals = [entry["total"] for entry in out["order"]]
    assert totals == sorted(totals, reverse=True)
    first = _fight(srd35_storage, srd35_campaign).order
    ended = srd35_call("combat_round", beat="beat-2", actions=[])
    assert "error" not in ended, ended
    fight = _fight(srd35_storage, srd35_campaign)
    assert fight.round == 2 and fight.order == first
    rolls = [r for r in srd35_storage.rolls.list(srd35_campaign.id) if r.key.purpose == "initiative"]
    assert {r.key.combat_round for r in rolls} == {1}
    # Round 2 has its order, so a provoke there needs no initiative rolled again.
    assert "error" not in srd35_call("provoke", beat="beat-3", provoker="Orc 1", threatened_by=["Thorin"])


CLASSIC_FIGHT_KEYS = {"thac0", "damage", "damage_sm", "damage_l", "speed"}


def test_setup_combat_answers_3_5_numbers(srd35_call):  # R17b
    _fighter(srd35_call)
    srd35_call("set_build", character="Thorin", weapon="warhammer", armor="scale mail")
    out = _orc(srd35_call)
    (group,) = out["enemies"]
    assert not CLASSIC_FIGHT_KEYS & set(group)
    # The orc's row: AC 13 (studded leather), touch 10, flat-footed 13; falchion +4 (2d4+4/18–20), javelin +1
    # (1d6+3); Fort +3, Ref +0, Will −2.
    assert (group["ac"], group["touch"], group["flat_footed"]) == (13, 10, 13)
    assert group["attacks"] == [
        {"name": "falchion", "bonus": 4, "damage": "2d4+4", "critical": "18–20/×2"},
        {"name": "javelin", "bonus": 1, "damage": "1d6+3", "critical": "×2"},
    ]
    assert group["saves"] == {"fort": 3, "ref": 0, "will": -2}
    # Thorin: AC 10 + scale mail 4 + Dex 1 = 15; warhammer BAB 1 + Str 3 = +4, 1d8+3, ×3; Fort 2 + Con 2 = 4.
    thorin = out["party_attacks"]["Thorin"]
    assert not CLASSIC_FIGHT_KEYS & set(thorin)
    assert (thorin["ac"], thorin["touch"], thorin["flat_footed"]) == (15, 11, 14)
    assert thorin["attacks"] == [{"name": "warhammer", "bonus": 4, "damage": "1d8+3", "critical": "×3"}]
    assert thorin["saves"] == {"fort": 4, "ref": 1, "will": 0}
    # The order gives each initiative's bonus, not a weapon speed.
    for entry in out["order"]:
        assert "speed" not in entry and entry["total"] == entry["roll"] + entry["bonus"]


def test_update_combatant_answers_3_5_numbers(srd35_call):  # R17b
    _fighter(srd35_call)
    _orc(srd35_call)
    out = srd35_call("update_combatant", id="Orc", ac=18, attack_bonus=7, critical="19–20/×3")
    assert "error" not in out, out
    numbers = out["numbers"]
    assert (numbers["ac"], numbers["touch"], numbers["flat_footed"]) == (18, 10, 13)
    assert numbers["attacks"][0] == {"name": "falchion", "bonus": 7, "damage": "2d4+4", "critical": "19–20/×3"}
    assert numbers["saves"] == {"fort": 3, "ref": 0, "will": -2}


def test_setup_combat_asks_for_no_classic_damage(srd35_call):  # I1
    # The orc's attacks are the engine's (falchion 2d4+4): core's "pass dmg=" warning would have the DM overwrite them.
    _fighter(srd35_call)
    out = _orc(srd35_call)
    assert not any("dmg=" in note for note in out.get("notes", [])), out.get("notes")


def test_setup_combat_names_the_3_5_override_when_the_engine_has_no_attack(srd35_call):  # I1
    # The SRD's bare "Skeleton" row (the template) has no attack line, so the engine has no attack form to give.
    _fighter(srd35_call)
    out = srd35_call("setup_combat", enemies=[{"name": "skeleton", "count": 1, "hp": 6}], surprise=False)
    assert "error" not in out, out
    notes = out.get("notes", [])
    assert not any("dmg=" in note for note in notes), notes
    assert (
        "'Skeleton' has no attack the 3.5 engine could read: give it one with update_combatant's damage and "
        "attack_bonus before it swings." in notes
    ), notes


def test_setup_combat_rolls_no_surprise_by_default(srd35_call, srd35_storage, srd35_campaign):  # R21
    _fighter(srd35_call)
    out = srd35_call("setup_combat", enemies=[{"name": "orc", "count": 1}])
    assert "error" not in out, out
    assert "surprise" not in out
    assert not [r for r in srd35_storage.rolls.list(srd35_campaign.id) if r.key.purpose.startswith("surprise")]


def test_setup_combat_asked_for_surprise_says_3_5_has_none(srd35_call):  # R21
    _fighter(srd35_call)
    out = srd35_call("setup_combat", enemies=[{"name": "orc", "count": 1}], surprise=True)
    assert "error" not in out, out
    assert "surprise" not in out
    assert any(note.startswith("3.5 has no surprise roll: ") for note in out["notes"]), out.get("notes")


def test_surprise_and_morale_checks_say_why_they_dont_apply(srd35_call):  # R21
    out = srd35_call("surprise_check")
    assert out["error"].startswith("3.5 has no surprise roll: "), out
    assert "flat-footed" in out["error"]
    out = srd35_call("morale_check", rating=8)
    assert out["error"].startswith("3.5 has no morale check: "), out


def test_reaction_and_council_say_why_they_dont_apply(srd35_call):  # DEL-400
    out = srd35_call("reaction")
    assert out["error"].startswith("3.5 has no reaction roll: "), out
    assert "Diplomacy" in out["error"] and "skill_check" in out["error"], out
    out = srd35_call("council", npcs=["Tira"])
    assert out["error"].startswith("3.5 has no reaction roll: "), out
    assert "skill_check" in out["error"], out


def test_a_monsters_full_attack_is_kept_and_told(srd35_call):  # I5
    # The owlbear's full attack is 2 claws +9 (1d6+5) and bite +4 (1d8+2): the round swings the claws it holds, the
    # bite comes by resolve_attack with its weapon; core's "pass dmg= per swing" would overwrite the engine's forms.
    sheet = {"cls": "Fighter", "level": 1, "race": "Dwarf", "hp_max": 80, "ability_scores": DWARF}
    assert "error" not in srd35_call("create_character", name="Thorin", sheet=sheet)
    out = srd35_call("setup_combat", enemies=[{"name": "owlbear", "count": 1}])
    assert "error" not in out, out
    assert not any("dmg=" in note for note in out.get("notes", [])), out.get("notes")
    assert [f["name"] for f in out["enemies"][0]["attacks"]] == ["claw", "bite"]
    round_ = srd35_call("combat_round", beat="beat-2", actions=[{"attacker": "Owlbear", "target": "Thorin"}])
    assert "error" not in round_, round_
    assert {a["weapon"] for a in round_["actions"] if a.get("attacker") == "Owlbear"} == {"claw"}
    bite = srd35_call("resolve_attack", beat="beat-3", attacker="Owlbear", target="Thorin", weapon="bite")
    assert "error" not in bite, bite
    assert bite["weapon"] == "bite"


def test_add_combatant_answers_3_5_numbers(srd35_call):  # I6
    _fighter(srd35_call)
    _orc(srd35_call)
    out = srd35_call("add_combatant", name="ghoul", count=1)
    assert "error" not in out, out
    assert not CLASSIC_FIGHT_KEYS & set(out)
    # The ghoul's row: AC 14, touch 12, flat-footed 12; bite +2 (1d6+1), 2 claws +0 (1d3); Fort +0, Ref +2, Will +5.
    assert (out["ac"], out["touch"], out["flat_footed"]) == (14, 12, 12)
    assert [(f["name"], f["bonus"], f["damage"]) for f in out["attacks"]] == [("bite", 2, "1d6+1"), ("claw", 0, "1d3")]
    assert not any("dmg=" in note for note in out.get("notes", [])), out.get("notes")


def test_core_multi_attack_note_is_dropped():  # I5
    # Core's note for a row with several attacks a round asks for dmg= per swing, which would overwrite the forms.
    from delve_srd35.engine.tools import _notes

    note = "'Owlbear' gets 3 attacks/round — every one is resolved in its action. Its damage line is '1d6': if the "
    note += "attacks differ, pass dmg= per swing."
    assert _notes([{"type": "Owlbear", "attacks": [{"name": "claw"}]}], [note, "other"]) == ["other"]


def test_provoke_refuses_before_the_rounds_initiative(srd35_call, srd35_storage, srd35_campaign):
    # A fight whose round has no order yet (its initiative not rolled) has nobody to act in it: provoke says so.
    _fighter(srd35_call)
    _orc(srd35_call)
    id, _ = srd35_storage.combats.live(srd35_campaign.id)
    fight = dataclasses.replace(_fight(srd35_storage, srd35_campaign), order=())
    srd35_storage.combats.save(id, fight.phase, rules.to_json(fight))
    out = srd35_call("provoke", provoker="Orc", threatened_by=["Thorin"])
    assert out == {"error": "Round 1 hasn't started: its initiative isn't rolled yet.",
                   "hint": "combat_round rolls the round's initiative."}  # fmt: skip


def test_two_domains_are_counted_by_name_whatever_the_case(srd35_call):
    sheet = {"cls": "Cleric", "level": 1, "race": "Dwarf", "hp_max": 10, "ability_scores": DWARF}
    srd35_call("create_character", name="Dorna", sheet=sheet)
    out = srd35_call("set_build", character="Dorna", domains=["War", "war"])
    assert "A cleric takes two domains, not 1." in out["error"], out


def test_a_templated_monster_comes_in_with_all_its_hit_dice(srd35_call, srd35_storage, srd35_campaign):  # DEL-402
    # The barbarian ogre's "4d8+19 plus 4d12+16": 8 dice, so 8 + 35 = 43 to 32 + 48 + 35 = 115 hp, where the classic
    # reading of its first number gave 4d8. The grig's "1/2 d6+1" is 1 to 4. Neither answer says to pass hp.
    _fighter(srd35_call)
    out = srd35_call("setup_combat", enemies=[{"name": "4th-level Barbarian Ogre", "count": 1}], surprise=False)
    assert "error" not in out, out
    ogre = _fight(srd35_storage, srd35_campaign).combatants["mon_1"]
    assert 43 <= ogre.hp_max <= 115
    added = srd35_call("add_combatant", name="grig", count=3)
    assert "error" not in added, added
    assert all(1 <= entry["hp"] <= 4 for entry in added["individuals"])
    assert not any("HD reads" in note for note in [*out.get("notes", []), *added.get("notes", [])])


def test_set_build_warns_a_two_handed_weapon_loses_the_shield(srd35_call):
    # A dwarf fighter 1 with a greatsword and a heavy steel shield: the shield's AC is lost, said; with a buckler, its
    # AC lost and -1 to hit, said.
    _fighter(srd35_call)
    out = srd35_call("set_build", character="Thorin", weapon="greatsword", shield="heavy steel shield")
    assert any("both hands" in w for w in out["warnings"]), out
    out = srd35_call("set_build", character="Thorin", weapon="greatsword", shield="buckler")
    assert any("-1" in w for w in out["warnings"]), out


@pytest.mark.parametrize("name", ["generate_treasure", "award_treasure"])
def test_the_treasure_tools_describe_3_5_treasure(srd35_host, name):
    # Final review: a 3.5 campaign's treasure tools say the encounter level and rating, not the classic letters.
    core = next(spec for spec in all_specs() if spec.name == name)
    mine = srd35_host.spec(name, "srd35")
    assert mine is not core and mine.rulesets == ("srd35",) and mine.fn is core.fn
    assert set(core.params["properties"]) <= set(mine.params["properties"])
    said = mine.description + " ".join(p["description"] for p in mine.params["properties"].values())
    assert "EL 5, standard" in said and "3.5" in mine.description
    for classic in ("'L,M'", "Qx5", "Types A-I", "J-Z"):
        assert classic not in said, classic


def test_a_3_5_hoard_by_the_described_line(srd35_call):
    out = srd35_call("generate_treasure", treasure_types="EL 3, double standard", source="the hobgoblins")
    assert "error" not in out, out
    assert out["rolled"][0] == "EL 3"


def test_setup_combat_overrides_hold_for_a_two_weapon_hobgoblin(srd35_call, srd35_storage, srd35_campaign):
    _fighter(srd35_call, hp_max=300)
    spec = {"name": "hobgoblin", "count": 1, "hp": 30, "label": "Uth-lar", "attack_bonus": 7, "damage": "1d6+5"}
    spec |= {"attacks_per_round": 2, "init": 3, "bab": 4, "attack": "short sword"}
    out = srd35_call("setup_combat", enemies=[spec], surprise=False)
    assert "error" not in out, out
    group = out["enemies"][0]
    assert (group["attacks_per_round"], group["init_bonus"], group["bab"]) == (2, 3, 4)
    uth = next(c for c in _fight(srd35_storage, srd35_campaign).combatants.values() if c.name == "Uth-lar")
    held = uth.attacks[uth.weapon]
    assert (held.name, held.damage_sm, held.rate) == ("short sword", "1d6+5", 2)
    form = uth.d20["attacks"][uth.weapon]
    assert (form["name"], form["bonus"], form["count"]) == ("short sword", 7, 2)
    assert (uth.d20["init_bonus"], uth.d20["bab"]) == (3, 4)
    rounds = srd35_call("combat_round", actions=[{"attacker": "Uth-lar", "target": "Thorin"}])
    swings = [a for a in rounds["actions"] if a.get("attacker") == "Uth-lar" and "skipped" not in a]
    assert [s["weapon"] for s in swings] == ["short sword", "short sword"], rounds
    assert not any("iterative" in n for s in swings for n in s.get("notes", ()))  # the second is at +7, not +2


def test_add_combatant_stats_hold_the_3_5_overrides(srd35_call, srd35_storage, srd35_campaign):
    _fighter(srd35_call)
    _orc(srd35_call)
    stats = {"attack_bonus": 7, "damage": "1d6+5", "attacks_per_round": 2, "init": 3, "bab": 4, "attack": "short sword"}
    out = srd35_call("add_combatant", name="hobgoblin", count=1, stats={**stats, "label": "Uth-lar"})
    assert "error" not in out, out
    assert (out["attacks_per_round"], out["init_bonus"], out["bab"]) == (2, 3, 4)
    uth = next(c for c in _fight(srd35_storage, srd35_campaign).combatants.values() if c.name == "Uth-lar")
    held = uth.attacks[uth.weapon]
    assert (held.name, held.damage_sm, held.rate) == ("short sword", "1d6+5", 2)
    form = uth.d20["attacks"][uth.weapon]
    assert (form["name"], form["bonus"], form["count"]) == ("short sword", 7, 2)
    assert (uth.d20["init_bonus"], uth.d20["bab"]) == (3, 4)


def test_add_combatant_init_sets_the_newcomers_place_in_a_rolled_order(srd35_call, srd35_storage, srd35_campaign):
    _fighter(srd35_call)
    _orc(srd35_call)
    assert "error" not in srd35_call("combat_round", actions=[{"attacker": "Orc", "target": "Thorin"}])
    out = srd35_call("add_combatant", name="hobgoblin", count=1, stats={"init": 3, "label": "Uth-lar"})
    assert "error" not in out, out
    fight = _fight(srd35_storage, srd35_campaign)
    uth = next(c for c in fight.combatants.values() if c.name == "Uth-lar")
    assert uth.init == uth.init_roll + 3 and out["individuals"][0]["init"] == uth.init and out["init_bonus"] == 3
    inits = [fight.combatants[i].init for i in fight.order]
    assert uth.id in fight.order and inits == sorted(inits, reverse=True)
