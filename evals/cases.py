"""Eval cases: a scripted scenario (a sample module, the party set up through Delve's tools, and the player's beats)
and the fixtures recorded or written against it.

A case is evals/cases/<id>.json:

    {"id": "locked_door",
     "description": "...",
     "module": "crypt-of-saint-vellis",   a sample module under tests/fixtures/samples/scenarios/
     "ruleset": "osric",                  optional; the campaign's ruleset (default `RULESET`), a pack's id
     "setup": [{"tool": "create_character", "args": {...}}, ...],   run through the tool host before play
     "secrets": [{"text": "...", "tags": [...], "related_to": "...", "terms": ["needle"]}],   planted with dm_note
     "hidden_terms": ["..."],             words the player-facing choices must not use
     "checks": ["die_first", ...],        optional; default every registered check
     "beats": [{"player": "...", "ask": false, "expect": {...}}]}

A beat with "ask": true is a question to Ask the DM, answered without tools and without module canon.

Its fixtures are evals/fixtures/<id>/*.jsonl. The file name says what the checks must make of it:

    pass*.jsonl               no findings at all
    violates-<check>*.jsonl   findings from <check>, and from no other check
    anything else             reported only

A live run's recordings go to evals/recordings/delve/<id>/recorded-*.jsonl (ttrpg2's to evals/recordings/ttrpg2/),
out of git and never fixtures: a `recorded-*.jsonl` is ignored even inside evals/fixtures/.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from delve.dm.tools import ToolHost
    from delve.domain.campaigns import Campaign
    from delve.storage.interfaces import Storage

EVALS_DIR = Path(__file__).resolve().parent
CASES_DIR = EVALS_DIR / "cases"
FIXTURES_DIR = EVALS_DIR / "fixtures"
RECORDINGS_DIR = EVALS_DIR / "recordings"
SCENARIOS_DIR = EVALS_DIR.parent / "tests" / "fixtures" / "samples" / "scenarios"
# The beat the setup calls run in, before the first beat of play.
SETUP_BEAT = "eval-setup"


def load_case(path: str | Path) -> dict:
    case = json.loads(Path(path).read_text(encoding="utf-8"))
    case.setdefault("id", Path(path).stem)
    return case


def load_cases(cases_dir: Path = CASES_DIR) -> dict[str, dict]:
    return {c["id"]: c for c in map(load_case, sorted(cases_dir.glob("*.json")))}


def fixtures(case_id: str, fixtures_dir: Path = FIXTURES_DIR) -> list[Path]:
    """The case's fixtures, without live recordings (`recorded-*.jsonl`)."""
    return sorted(p for p in (fixtures_dir / case_id).glob("*.jsonl") if not p.name.startswith("recorded-"))


def recording_dir(case_id: str, app: str = "delve") -> Path:
    """Where a live run of `app` (delve or ttrpg2) records the case: evals/recordings/<app>/<case>/."""
    return RECORDINGS_DIR / app / case_id


def expectation(fixture: Path) -> tuple[str, str | None]:
    """("pass", None), ("violates", check) or ("report", None)."""
    stem = fixture.stem
    if stem.startswith("pass"):
        return "pass", None
    if stem.startswith("violates-"):
        return "violates", stem[len("violates-") :].split(".")[0]
    return "report", None


RULESET = "osric"
"""The ruleset a case plays unless it names one: OSRIC, the one Delve's repository holds (`packs/osric`)."""


def start_campaign(storage: Storage, case: dict, scenarios_dir: Path = SCENARIOS_DIR) -> Campaign:
    """A new campaign of the case's sample module, imported as a `.dscn`, playing the case's ruleset and the seeded
    house-rule bundle."""
    from delve.modules.dscn import Bundle
    from delve.modules.importer import import_bundle
    from delve.play.house_rules import seed_house_rules, set_campaign_house_rules

    module_id = import_bundle(storage, Bundle.load(scenarios_dir / case["module"]).to_zip()).module.id
    bundle = next(iter(storage.house_rule_bundles.list()), None) or seed_house_rules(storage)
    revision = storage.revisions.latest(module_id) or storage.revisions.snapshot(module_id)
    campaign = storage.campaigns.create(
        case.get("name", f"Eval: {case['id']}"),
        module_id,
        revision.number,
        ruleset=case.get("ruleset", RULESET),
        setting="greyhawk",
    )
    set_campaign_house_rules(storage, campaign.id, bundle_ids=[bundle.id], rule_ids=[])
    return campaign


def setup_calls(case: dict) -> list[dict[str, Any]]:
    """The case's setup calls, then a dm_note per secret, so play sees them through dm_secrets."""
    notes = [
        {
            "tool": "dm_note",
            "args": {"text": s["text"], "tags": list(s.get("tags") or []), "related_to": s.get("related_to", "")},
        }
        for s in case.get("secrets") or []
    ]
    return list(case.get("setup") or []) + notes


def set_up(host: ToolHost, campaign_id: str, case: dict) -> list[dict[str, Any]]:
    """Run the setup calls in the setup beat; their results, in order."""
    return [host.call(campaign_id, SETUP_BEAT, step["tool"], step.get("args") or {}) for step in setup_calls(case)]
