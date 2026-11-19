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
