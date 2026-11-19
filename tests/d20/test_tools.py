"""A ruleset's own DM tools (DEL-387): listed and callable only in its campaigns."""

import json
from pathlib import Path

from delve.dice import SeededRng
from delve.dm.bridge import BRIDGE_HEADER, DelveClient
from delve.dm.tools import ToolHost
from delve.domain.modules import ModuleMap
from delve.packs.catalogs import Catalogs
from delve.rules.catalog import RulesetEntry
from tests.dm.tools.conftest import CRYPT
from tests.fixtures.d20 import FAKE_D20, d20_catalogs, fake_ruleset
from tests.fixtures.rulesets import osric

SNAPSHOT = Path(__file__).parent.parent / "dm" / "snapshots" / "tool_specs.json"


def test_the_unscoped_list_is_todays(d20_host):
    names = [spec["name"] for spec in json.loads(SNAPSHOT.read_text())]
    assert [s.name for s in d20_host.specs()] == names


def test_a_d20_campaign_sees_its_tools(d20_host):
    core = d20_host.specs()
    scoped = d20_host.specs(FAKE_D20)
    assert scoped[-1].name == "fake_flourish"
    index = [s.name for s in core].index("saving_throw")
    assert scoped[index].name == "saving_throw"
    assert "dc" in scoped[index].params["properties"]
    assert set(core[index].params["properties"]) <= set(scoped[index].params["properties"])
    assert "dc" not in core[index].params["properties"]
    assert len(scoped) == len(core) + 1


def test_an_osric_campaign_cannot_call_them(d20_storage, d20_campaign, d20_call, d20_host):
    module = d20_storage.modules.create("Other")
    d20_storage.modules.put_map(module.id, ModuleMap("crypt", "map", CRYPT, is_default=True))
    revision = d20_storage.revisions.snapshot(module.id)
    osric = d20_storage.campaigns.create("Wed", module.id, revision.number, ruleset="osric", setting="greyhawk")
    out = d20_host.call(osric.id, "beat-1", "fake_flourish", {})
    assert out["error"] == "Unknown tool 'fake_flourish'."
    assert d20_call("fake_flourish") == {"flourish": True}
    batch = d20_host.call(osric.id, "beat-1", "batch", {"steps": [{"tool": "fake_flourish", "args": {}}]})
    assert batch["results"][0]["error"] == "unknown tool"
    own = d20_host.call(d20_campaign.id, "beat-2", "batch", {"steps": [{"tool": "fake_flourish", "args": {}}]})
    assert own["results"][0]["result"] == {"flourish": True}


def _campaign(storage, ruleset):
    module = storage.modules.create(f"M {ruleset}")
    storage.modules.put_map(module.id, ModuleMap("crypt", "map", CRYPT, is_default=True))
    revision = storage.revisions.snapshot(module.id)
    return storage.campaigns.create(f"C {ruleset}", module.id, revision.number, ruleset=ruleset, setting="greyhawk")


def test_a_mis_scoped_ruleset_breaks_only_its_own_campaign(d20_storage, d20_campaign, d20_host, monkeypatch):
    from dataclasses import replace

    engine = fake_ruleset().d20
    real = engine.tools()
    monkeypatch.setattr(engine, "tools", lambda: [replace(real[0], rulesets=None)])
    osric = _campaign(d20_storage, "osric")
    assert [s.name for s in d20_host.specs("osric")] == [s.name for s in d20_host.specs()]
    assert d20_host.call(osric.id, "beat-1", "roll", {"notation": "1d20", "purpose": "x"})["total"]
    assert [s.name for s in d20_host.specs(FAKE_D20)] == [s.name for s in d20_host.specs()]
    out = d20_host.call(d20_campaign.id, "beat-1", "roll", {"notation": "1d20", "purpose": "x"})
    assert "scoped" in out["error"]
    again = d20_host.call(d20_campaign.id, "beat-2", "fake_flourish", {})
    assert "scoped" in again["error"]


def test_duplicate_scoped_names_answer_an_error(d20_campaign, d20_host, monkeypatch, caplog):
    engine = fake_ruleset().d20
    real = engine.tools()
    monkeypatch.setattr(engine, "tools", lambda: [real[1], real[1]])
    assert [s.name for s in d20_host.specs(FAKE_D20)] == [s.name for s in d20_host.specs()]
    for beat in ("beat-1", "beat-2"):
        out = d20_host.call(d20_campaign.id, beat, "fake_flourish", {})
        assert "two tools" in out["error"]
    assert caplog.text.count("two tools") == 1


def test_a_ruleset_that_fails_to_make_is_skipped(d20_storage, caplog):
    def broken():
        raise RuntimeError("no")

    base = d20_catalogs()
    catalogs = Catalogs((*base.rulesets, RulesetEntry("broken", "Broken", "tests", broken)), base.settings, base.packs)
    host = ToolHost(d20_storage, lambda: SeededRng(1), catalogs=catalogs)
    assert [s.name for s in host.specs("broken")] == [s.name for s in host.specs()]
    assert host.specs(FAKE_D20)[-1].name == "fake_flourish"
    assert "broken" in caplog.text


def test_no_ruleset_is_made_until_a_lookup_asks(d20_storage):
    made = []
    base = d20_catalogs()

    def counting():
        made.append(1)
        return osric()

    entry = RulesetEntry("counted", "Counted", "tests", counting)
    host = ToolHost(
        d20_storage, lambda: SeededRng(1), catalogs=Catalogs((*base.rulesets, entry), base.settings, base.packs)
    )
    host.specs()
    host.specs("osric")
    assert made == []
    host.specs("counted")
    host.specs("counted")
    assert made == [1]


def test_the_endpoint_lists_by_campaign(d20_web, d20_campaign):
    d20_web.headers[BRIDGE_HEADER] = d20_web.app.state.bridge_secret
    plain = [t["name"] for t in d20_web.get("/internal/dm/tools").json()]
    scoped = [t["name"] for t in d20_web.get(f"/internal/dm/tools?campaign={d20_campaign.id}").json()]
    assert "fake_flourish" not in plain
    assert scoped[-1] == "fake_flourish"
    assert len(scoped) == len(plain) + 1


def test_the_bridge_asks_for_its_campaign(monkeypatch):
    import asyncio

    client = DelveClient("http://x", "cmp_1", "secret")
    seen = []

    def request(method, path, payload=None):
        seen.append((method, path))
        return 200, []

    monkeypatch.setattr(client, "_request", request)
    asyncio.run(client.tools())
    assert seen == [("GET", "/internal/dm/tools?campaign=cmp_1")]
