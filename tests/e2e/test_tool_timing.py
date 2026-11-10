"""The server's share of the speed budget (spec §6.4; plan 2a Task 14): the scripted first session, replayed 5 times on a
warm process, each on a fresh campaign of the one imported module, as campaigns share a module's revision.

A tool call's time is all of the host's work for it: checking the arguments, reading and writing the state in one
transaction, the rules, and the map, parsed or taken from the cache. The 95th percentile must stay under 50 ms, and
the heaviest calls are reported by name."""

import statistics

import pytest

from delve.config import Config
from delve.storage import open_storage
from tests.e2e.scripted import import_module, load, play, start_campaign
from tests.fixtures.rulesets import osric_catalogs
from tests.timing import budget

pytestmark = pytest.mark.slow

REPLAYS = 5
P95_BUDGET_MS = 50.0
HEAVIEST = ("setup_combat", "combat_round", "move_party")


@pytest.fixture(scope="module")
def timings(tmp_path_factory):
    config = Config(data_dir=tmp_path_factory.mktemp("timing") / "data")
    storage = open_storage(config)
    catalogs = osric_catalogs()
    script = load("first_session")
    module_id = import_module(storage, script)

    def replay():
        return play(storage, script, start_campaign(storage, script, module_id), catalogs)[1]

    replay()  # warm the process: imports, the parsed map, SQLite pages
    calls = [call for _ in range(REPLAYS) for call in replay()]
    yield calls
    storage.close()


def _p95(values: list[float]) -> float:
    return statistics.quantiles(values, n=100, method="inclusive")[94]


def test_tool_call_p95_under_50_ms(timings, capsys):
    milliseconds = [call.seconds * 1000 for call in timings]
    p95 = _p95(milliseconds)
    by_tool: dict[str, list[float]] = {}
    for call in timings:
        by_tool.setdefault(call.tool, []).append(call.seconds * 1000)
    heaviest = sorted(by_tool.items(), key=lambda item: -max(item[1]))[:6]
    lines = [f"tool calls: {len(milliseconds)}, p95 {p95:.1f} ms, median {statistics.median(milliseconds):.1f} ms"]
    lines += [f"  {name:<18} max {max(ms):5.1f} ms  median {statistics.median(ms):5.1f} ms" for name, ms in heaviest]
    lines += [
        f"  {name:<18} p95 {_p95(by_tool[name]) if len(by_tool[name]) > 1 else by_tool[name][0]:5.1f} ms"
        for name in HEAVIEST
    ]
    with capsys.disabled():
        print("\n" + "\n".join(lines))
    assert len(milliseconds) == REPLAYS * sum(len(beat["calls"]) for beat in load("first_session")["beats"])
    assert p95 < budget(P95_BUDGET_MS), "\n".join(lines)
