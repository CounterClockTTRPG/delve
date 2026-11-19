"""A ruleset that is only a reference (DEL-384, `playable = false`): the Rulesets area reads it, and no campaign is
made, carried into or played with it. A module that names it takes the preferred ruleset instead."""

from __future__ import annotations

from dataclasses import replace

import pytest

from delve.domain.backends import ProviderCapabilities
from delve.domain.campaigns import MissingPack
from delve.play.context import missing_pack
from delve.rules.catalog import RulesetEntry
from delve.rules.fake import FakeRuleset
from tests.web.test_campaigns_api import crypt_module
from tests.web.test_carry_api import carry, old_party

REFUSED = "Reference test is a reference: campaigns can't be played with it yet."


class ReferenceRuleset(FakeRuleset):
    id = "reference"
    title = "Reference test"


@pytest.fixture
def with_reference(registries):
    """The web tests' catalogs with an unplayable ruleset `reference` beside OSRIC, registered as the app registers
    every ruleset of its catalogs."""
    entry = RulesetEntry("reference", "Reference test", "reference_pack", ReferenceRuleset, playable=False)
    registries.catalogs = replace(registries.catalogs, rulesets=(*registries.catalogs.rulesets, entry))
    registries.rulesets.register(ProviderCapabilities("reference", "Reference test", frozenset()), ReferenceRuleset)
    return registries


def test_a_campaign_with_an_unplayable_ruleset_is_refused(local, with_reference):
    module = crypt_module(local)
    response = local.post("/api/campaigns", json={"name": "Tuesday", "module_id": module["id"], "ruleset": "reference"})
    assert response.status_code == 409
    assert response.json()["error"] == REFUSED


def test_carry_into_an_unplayable_ruleset_is_refused(local, with_reference):
    old, ids = old_party(local)
    response = carry(local, old["id"], crypt_module(local, title="Next")["id"], ids, ruleset="reference")
    assert response.status_code == 409
    assert response.json()["error"] == REFUSED


def test_a_module_naming_an_unplayable_ruleset_takes_the_preferred_one(local, with_reference):
    module = crypt_module(local)
    patched = local.patch(f"/api/modules/{module['id']}", json={"metadata": {"system": "reference"}})
    assert patched.status_code == 200, patched.json()
    response = local.post("/api/campaigns", json={"name": "Tuesday", "module_id": module["id"]})
    assert response.status_code == 201, response.json()
    assert response.json()["ruleset"] == "osric"


def test_worlds_leaves_out_unplayable_rulesets(local, with_reference):
    offered = [r["id"] for r in local.get("/api/worlds").json()["rulesets"]]
    assert "reference" not in offered


def test_an_unplayable_campaign_reads_as_missing_its_ruleset(local, storage, with_reference):
    module = crypt_module(local)
    stored = storage.campaigns.create(
        "Old", module["id"], storage.revisions.snapshot(module["id"]).number, ruleset="reference", setting=""
    )
    missing = missing_pack(with_reference.catalogs, stored)
    assert isinstance(missing, MissingPack) and (missing.kind, missing.id) == ("ruleset", "reference")
    assert missing.message == "This campaign's ruleset, reference, is only a reference: it can't be played."
    state = local.get(f"/api/campaigns/{stored.id}/play/state")
    assert state.status_code == 200, state.text
    assert state.json()["missing_pack"] == {"kind": "ruleset", "id": "reference", "reference": True}
