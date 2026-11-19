"""SRD 3.5's book through the rulesets API (DEL-384), with the pack installed beside OSRIC: listed as playable
(DEL-388), its nine sections, a section's rows by a filter, and an entry."""

from __future__ import annotations

import pytest

from delve.domain.backends import ProviderCapabilities
from delve.rules.catalog import make_ruleset
from tests.fixtures.rulesets import srd35_catalogs
from tests.web.conftest import make_registries

BASE = "/api/rulesets/srd35"


@pytest.fixture
def registries():
    registries = make_registries()
    registries.catalogs = srd35_catalogs()
    for ruleset_id in ("osric", "srd35"):
        ruleset = make_ruleset(ruleset_id, registries.catalogs.rulesets)
        registries.rulesets.register(ProviderCapabilities(ruleset.id, ruleset.title, frozenset()), lambda r=ruleset: r)
    return registries


def test_srd35_is_listed_as_playable(local):
    listed = {r["id"]: r for r in local.get("/api/rulesets").json()}
    assert listed["srd35"] == {"id": "srd35", "title": "SRD 3.5", "playable": True}
    assert listed["osric"]["playable"] is True


def test_srd35_book_through_the_api(local):
    body = local.get(BASE).json()
    assert [s["key"] for s in body["sections"]] == [
        "classes", "races", "skills", "feats", "spells", "monsters", "items", "abilities", "rules"
    ]  # fmt: skip
    assert (body["playable"], body["monster_pictures"]) == (True, "reuse")
    assert "Open Game License" in body["notice"]
    spells = local.get(f"{BASE}/spells?class=wizard&level=3&q=fireball").json()
    assert [r["name"] for r in spells["rows"]] == ["Fireball"] and spells["rows"][0]["level"] == "Sor/Wiz 3"
    fighter = local.get(f"{BASE}/classes/fighter").json()
    # Its level table is the SRD's own, in its text (DEL-394), not a second table under it.
    assert fighter["fields"]["hit_die"] == "d10" and fighter["table"] is None
    assert "| 20th | +20/+15/+10/+5 | +12 | +6 | +6 | Bonus feat |" in fighter["text"]


def test_srd35_can_be_picked_for_a_campaign(local):
    assert "srd35" in [r["id"] for r in local.get("/api/worlds").json()["rulesets"]]
