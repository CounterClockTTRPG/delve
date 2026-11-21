"""The SRD 3.5 pack's DM prompt (DEL-388): under its cap, naming each of the engine's own tools, and the pack playable
without being the ruleset a new campaign takes by default."""

from __future__ import annotations

import re
import shutil
from importlib import resources
from pathlib import Path

from delve.domain.campaigns import default_ruleset
from delve.packs import loader

PACK = Path(__file__).resolve().parents[1]
PROMPT = resources.files("delve_srd35").joinpath("prompt.md").read_text("utf-8")


def test_prompt_cap():
    assert len(PROMPT.split()) <= 1500


def test_prompt_names_every_scoped_tool():
    from delve_srd35.engine import Srd35Engine
    from delve_srd35.reference import Srd35Reference

    names = {spec.name for spec in Srd35Engine(Srd35Reference()).tools()}
    assert names >= {"set_build", "set_stance", "provoke", "saving_throw", "skill_check", "setup_combat"}
    named = set(re.findall(r"`([a-z_]+)`", PROMPT))
    assert names - named == set()


def test_prompt_reads_the_procedure_in_3_5_terms():
    from delve_srd35.engine import PROMPT_TERMS

    for term in PROMPT_TERMS.values():
        assert term in PROMPT
    for said in ("3.5 has no morale check", "THAC0", "`turning_undead`", "`lost`", "`spells_spent`", '`d20["level_up"]`', "4d6"):
        assert said in PROMPT, said


def test_srd35_is_playable_and_not_preferred(tmp_path):
    shutil.copytree(PACK, tmp_path / "srd35", ignore=shutil.ignore_patterns("tests", "scripts", "__pycache__"))
    loader.reset()
    try:
        (loaded,), _ = loader.load_packs(tmp_path)
        assert (loaded.manifest.playable, loaded.manifest.preferred) == (True, False)
    finally:
        loader.reset()
    from tests.fixtures.rulesets import srd35_catalogs

    playable = [e for e in srd35_catalogs().rulesets if e.playable]
    preferred = {e.id for e in playable if e.preferred}
    srd35_first = ["srd35", *(e.id for e in playable if e.id != "srd35")]
    assert "srd35" in {e.id for e in playable}
    assert "srd35" not in preferred
    # Offered first, srd35 is still not the default: OSRIC (preferred) is.
    assert default_ruleset(srd35_first, preferred) == "osric"


def test_prompt_names_the_class_features_tools_and_casting():
    """DEL-389: the 16 classes play: their features' tools, who prepares spells, and how a sorcerer or bard casts (its
    spells `known`, `cast_spell`), and a cleric's or druid's `convert_spell`; the part 1 refusal is gone."""
    for said in ("`use_feature`", "flurry", "`add_companion`", "druid", "paladin", "ranger", "adept", "sorcerer",
                 "bard", "sorcerers and bards memorize nothing", "`known`", "`convert_spell`"):  # fmt: skip
        assert said in PROMPT.lower(), said
    assert "doesn't cast sorcerers'" not in PROMPT.lower()
    assert "part 2" not in PROMPT.lower() and "DEL-" not in PROMPT


def test_prompt_says_a_move_or_charge_is_one_attack_and_converting_in_a_fight():  # DEL-389
    assert "`charging`: one attack" in PROMPT and '`"single": true`' in PROMPT and "full attack" in PROMPT
    assert "A cleric converting in a fight uses\n`convert_spell`: leave that spell out of the round." in PROMPT


def test_the_round_swings_the_whole_full_attack():
    # combat_round swings every form of a monster's full attack (final review): the prompt no longer has the DM add
    # the other forms with resolve_attack, which would give an owlbear its claws and bite twice.
    assert "`combat_round` swings a monster's whole full attack" in PROMPT
    assert "add no\n  `resolve_attack` for its other forms" in PROMPT
    assert "makes each other form" not in PROMPT and "a round swings the attack form a monster holds" not in PROMPT
    assert 'Forms joined by "or" are alternatives: `weapon` picks one.' in PROMPT


def test_prompt_says_how_a_prestige_class_is_entered_and_advances():  # DEL-389 part 4
    lowered = " ".join(PROMPT.lower().split())
    assert "prestige class" in lowered
    assert "requirements" in lowered and "`choices`" in PROMPT and "`advances`" in PROMPT
    assert "refused" in lowered


def test_prompt_says_the_round_spoils_no_one_action_spell_and_rage_waits_for_his_turn():
    # Final review: core's "damage before they act spoils the spell" is not 3.5's (the spell is cast on the caster's
    # turn), and a live DM raged before round 1, so a foe acting first hit a raging barbarian.
    lowered = " ".join(PROMPT.lower().split())
    assert "damage before the caster acts spoils no one-action spell" in lowered
    assert "rage (on his turn in a round;" in lowered
    assert "`destroy_up_to_hd`" in PROMPT and "twice its hit dice in levels" not in lowered
    assert "with one `resolve_attack`" in lowered and "fit the party" not in lowered
    assert all(len(line) <= 120 for line in PROMPT.splitlines())
