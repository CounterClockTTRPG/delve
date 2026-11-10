"""Playing `tests/fixtures/scripts/*.json` through the tool host: a campaign of the imported sample module, with the
seeded house-rule bundle, and the script's calls beat by beat with one `SeededRng`, timed."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from delve.dice import SeededRng
from delve.dm.tools import ToolHost
from delve.domain.campaigns import Campaign
from delve.modules.dscn import Bundle
from delve.modules.importer import import_bundle
from delve.packs.catalogs import IN_TREE, Catalogs
from delve.play.house_rules import seed_house_rules, set_campaign_house_rules
from tests.fixtures import SAMPLES

SCRIPTS = Path(__file__).resolve().parents[1] / "fixtures" / "scripts"


@dataclass(frozen=True)
class Call:
    beat: str
    tool: str
    args: dict[str, Any]
    result: dict[str, Any]
    seconds: float


def load(name: str) -> dict[str, Any]:
    return json.loads((SCRIPTS / f"{name}.json").read_text())


def import_module(storage, script: dict[str, Any]) -> str:
    """The script's sample module, imported as a `.dscn`: its id."""
    data = Bundle.load(SAMPLES / "scenarios" / script["module"]).to_zip()
    return import_bundle(storage, data).module.id


def start_campaign(
    storage, script: dict[str, Any], module_id: str | None = None, ruleset: str = "osric"
) -> Campaign:
    """A campaign of `ruleset` on the script's sample module (imported, unless `module_id` names it), playing the
    seeded bundle "My table (from ttrpg2)"."""
    module_id = module_id or import_module(storage, script)
    bundle = next((b for b in storage.house_rule_bundles.list()), None) or seed_house_rules(storage)
    revision = storage.revisions.latest(module_id) or storage.revisions.snapshot(module_id)
    campaign = storage.campaigns.create(
        script["title"], module_id, revision.number, ruleset=ruleset, setting="greyhawk"
    )
    set_campaign_house_rules(storage, campaign.id, bundle_ids=[bundle.id], rule_ids=[])
    return campaign


def play(
    storage, script: dict[str, Any], campaign: Campaign | None = None, catalogs: Catalogs = IN_TREE
) -> tuple[Campaign, list[Call]]:
    """Every call of the script, in order, on a new campaign; a call that answers an error stops it."""
    campaign = campaign or start_campaign(storage, script)
    rng = SeededRng(script["seed"])
    host = ToolHost(storage, lambda: rng, catalogs=catalogs)
    calls = []
    for beat in script["beats"]:
        for step in beat["calls"]:
            started = time.perf_counter()
            result = host.call(campaign.id, beat["beat"], step["tool"], step["args"])
            calls.append(Call(beat["beat"], step["tool"], step["args"], result, time.perf_counter() - started))
            if "error" in result:
                raise AssertionError(f"{beat['beat']} {step['tool']}: {result}")
    return campaign, calls
