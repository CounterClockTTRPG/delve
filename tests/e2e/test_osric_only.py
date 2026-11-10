"""Delve with OSRIC alone (DEL-307): `delve serve` over a data dir whose only pack is OSRIC offers OSRIC and Delve's own
setting, makes a campaign with no setting (no pack says it is preferred), and plays a beat with the fake `claude`."""

from pathlib import Path

import pytest

from delve.packs.transit import install_pack
from tests.e2e.test_play_with_fake_claude import Delve, planted_bundle

OSRIC = Path(__file__).resolve().parents[2] / "packs" / "osric"


@pytest.fixture
def delve(tmp_path):
    packs = tmp_path / "osric-only"
    install_pack(OSRIC, packs)
    server = Delve(tmp_path / "root", packs=packs)
    yield server
    server.stop()


def test_osric_alone_makes_a_campaign_with_no_setting_and_plays_a_beat(delve):
    http = delve.http
    worlds = http.get("/api/worlds").json()
    assert [r["id"] for r in worlds["rulesets"]] == ["osric"]
    assert [s["id"] for s in worlds["settings"]] == ["aun"]

    module = http.post("/api/modules/import", content=planted_bundle(), headers={"Content-Type": "application/zip"})
    assert module.status_code == 201, module.text
    created = http.post("/api/campaigns", json={"name": "Vellis", "module_id": module.json()["id"]})
    assert created.status_code == 201, created.text
    campaign = created.json()
    assert (campaign["ruleset"], campaign["setting"]) == ("osric", "")

    assert (
        http.post(f"/api/campaigns/{campaign['id']}/act", json={"text": "Make us a fighter and a thief."}).status_code
        == 202
    )
    state = delve.settle(campaign["id"])
    assert [pc["name"] for pc in state["party"]] == ["Garrek", "Pippa"]
