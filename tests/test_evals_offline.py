"""The eval harness (`evals/`, plan 2b Task 9), offline: ported from ttrpg2's `tests/test_evals.py`.

Every fixture under `evals/fixtures/` must come out as its name says: `pass*` clean, `violates-<check>*` failing that
check and no other. The fixtures speak Delve's tools, checked against `ToolHost.specs()`. Live mode is never run here:
only its recorder and its opt-in are exercised, and no `claude` is started.
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import jsonschema
import pytest

from delve.config import Config
from delve.dice import SeededRng
from delve.dm.provider import TextDelta, ToolCall, ToolResult, TurnEnd, Usage
from delve.dm.tools import ToolHost, all_specs
from delve.storage import open_storage
from evals import cases as _cases
from evals import runner
from evals.checks import (
    CHECKS,
    COMBAT_OPENERS,
    COMBAT_RESOLVERS,
    ROLL_TOOLS,
    choices,
    run_checks,
)
from evals.live import Recorder, beat_report
from evals.trace import MCP_PREFIX, Beat, Text, Trace, parse_events
from evals.trace import ToolCall as TraceCall
from tests.fixtures import SAMPLES
from tests.fixtures.rulesets import osric_catalogs, srd35_catalogs

ROOT = Path(__file__).resolve().parent.parent
SPECS = {spec.name: spec for spec in all_specs()}
_RULESET_SPECS: dict[str, dict] = {}


def specs_for_ruleset(ruleset: str) -> dict:
    """The tools a campaign of `ruleset` is offered: the core's, and a pack's own (`set_build`...) on its ruleset."""
    if ruleset not in _RULESET_SPECS:
        host = ToolHost(None, lambda: SeededRng(1), catalogs=srd35_catalogs())  # type: ignore[arg-type]
        _RULESET_SPECS[ruleset] = {spec.name: spec for spec in host.specs(ruleset)}
    return _RULESET_SPECS[ruleset]


def specs_for(case_id: str) -> dict:
    return specs_for_ruleset(_cases.load_cases()[case_id].get("ruleset", _cases.RULESET))


def catalogs_for(case: dict):
    return srd35_catalogs() if case.get("ruleset", _cases.RULESET) == "srd35" else osric_catalogs()
ALL_FIXTURES = [(cid, fx) for cid in sorted(_cases.load_cases()) for fx in _cases.fixtures(cid)]


# Fixtures


@pytest.mark.parametrize("case_id, fixture", ALL_FIXTURES, ids=[f"{c}/{f.name}" for c, f in ALL_FIXTURES])
def test_every_fixture_meets_its_expectation(case_id, fixture):
    result = runner.run_fixture(_cases.load_cases()[case_id], fixture)
    assert result.expected in ("pass", "violates")
    assert result.ok, result.summary()


def test_every_check_has_a_passing_and_a_violating_fixture():
    violated, clean = set(), set()
    for cid, case in _cases.load_cases().items():
        for fx in _cases.fixtures(cid):
            kind, check = _cases.expectation(fx)
            if kind == "violates":
                violated.add(check)
            elif kind == "pass":
                clean.update(case.get("checks") or CHECKS)
    assert set(CHECKS) - violated == set(), "checks with no violating fixture"
    assert set(CHECKS) - clean == set(), "checks with no passing fixture"


# Checks of Delve's own, each with its own case: only that case's beats expect what they check.
DELVE_ONLY_CHECKS = {"read_aloud_told"}


@pytest.mark.parametrize("case_id", ["locked_door", "goblin_ambush"])
def test_the_ported_cases_have_a_pass_and_one_violation_per_check(case_id):
    names = {fx.name for fx in _cases.fixtures(case_id)}
    assert names == {"pass.jsonl"} | {f"violates-{check}.jsonl" for check in set(CHECKS) - DELVE_ONLY_CHECKS}


def test_the_cases_are_the_planned_eleven():
    assert set(_cases.load_cases()) == {
        "locked_door",
        "goblin_ambush",
        "split_party_secret",
        "ask_the_dm_rules",
        "tone_and_xp",
        "xp_awards",
        "read_aloud_song",
        "multiclass_level_up",
        "prestige_refused",
        "sorcerer_cast",
        "barbarian_rage",
    }
    for cid in _cases.load_cases():
        assert any(_cases.expectation(fx)[0] == "pass" for fx in _cases.fixtures(cid)), cid


def test_fixture_names_refer_to_real_checks():
    for cid, fx in ALL_FIXTURES:
        kind, check = _cases.expectation(fx)
        if kind == "violates":
            assert check in CHECKS, fx


def _tool_uses(fixture: Path):
    for line in fixture.read_text().splitlines():
        if not line.strip() or line.startswith("//"):
            continue
        record = json.loads(line)
        if record.get("type") != "assistant":
            continue
        for block in record["message"]["content"]:
            if block.get("type") == "tool_use":
                yield block["name"], block.get("input") or {}


@pytest.mark.parametrize("case_id, fixture", ALL_FIXTURES, ids=[f"{c}/{f.name}" for c, f in ALL_FIXTURES])
def test_fixture_calls_are_delves_tools_with_valid_args(case_id, fixture):
    """Every `mcp__delve__` call names a tool of the host and passes its JSON Schema, batch steps too. Only a
    no_state_bypass violation calls anything else."""
    for raw, args in _tool_uses(fixture):
        if not raw.startswith(MCP_PREFIX):
            assert fixture.name.startswith("violates-no_state_bypass"), (fixture.name, raw)
            continue
        name = raw.removeprefix(MCP_PREFIX)
        specs = specs_for(case_id)
        assert name in specs, (fixture.name, name)
        jsonschema.validate(args, specs[name].params)
        if name == "batch":
            for step in args["steps"]:
                assert step["tool"] in specs, (fixture.name, step)
                jsonschema.validate(step.get("args") or {}, specs[step["tool"]].params)


def test_the_check_tool_sets_are_delves_tools():
    assert MCP_PREFIX == "mcp__delve__"
    for names in (ROLL_TOOLS, COMBAT_OPENERS, COMBAT_RESOLVERS):
        assert names <= set(SPECS), names - set(SPECS)
    for case in _cases.load_cases().values():
        for beat in case.get("beats") or []:
            rolls = (beat.get("expect") or {}).get("roll") or []
            for want in rolls if isinstance(rolls, list) else [rolls]:
                assert set(want.get("tools") or []) <= set(SPECS), want


# Cases


def test_packs_for_an_srd35_case_installs_it():
    assert _cases.packs_for({"ruleset": "srd35"}) == [_cases.PACKS_DIR / "osric", _cases.PACKS_DIR / "srd35"]
    assert _cases.packs_for({"ruleset": "osric"}) == [_cases.PACKS_DIR / "osric"]
    assert _cases.packs_for({}) == [_cases.PACKS_DIR / "osric"]
    assert _cases.packs_for({"ruleset": "no-such-pack"}) == [_cases.PACKS_DIR / "osric"]


def test_a_pack_only_tool_is_valid_only_on_its_ruleset():
    assert "set_build" not in specs_for("locked_door")
    assert "set_build" in specs_for_ruleset("srd35")
    assert set(SPECS) <= set(specs_for_ruleset("srd35"))
    params = specs_for_ruleset("srd35")["set_build"].params
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"nonsense": 1}, params)


def test_every_secret_term_is_in_its_secret():
    for cid, case in _cases.load_cases().items():
        for secret in case.get("secrets") or []:
            for term in secret.get("terms") or []:
                assert term.lower() in secret["text"].lower(), (cid, term)


@pytest.mark.slow
@pytest.mark.parametrize("case_id", sorted(_cases.load_cases()))
def test_case_setup_plays_through_the_tool_host(case_id, tmp_path):
    """Live mode sets a case up through the real tools: the module imported, the setup calls and the secrets planted
    with dm_note, none refused."""
    case = _cases.load_cases()[case_id]
    storage = open_storage(Config(data_dir=tmp_path / "data"))
    try:
        host = ToolHost(storage, lambda: SeededRng(1), catalogs=catalogs_for(case))
        campaign = _cases.start_campaign(storage, case, SAMPLES / "scenarios")
        results = _cases.set_up(host, campaign.id, case)
        assert all("error" not in result for result in results), results
        secrets = json.dumps(host.call(campaign.id, _cases.SETUP_BEAT, "dm_secrets", {}))
        for secret in case.get("secrets") or []:
            assert secret["text"] in secrets
    finally:
        storage.close()


# Checks


def _beat(*events, player="go"):
    return Beat(player=player, events=list(events))


def test_choices_extraction():
    assert choices(_beat(Text("It is dark.\n\n(Go left? Or go right?)"))) == "Go left? Or go right?"
    assert choices(_beat(Text("Dark.\n\n- Go left\n- Go right\nWhat now?"))) == "- Go left\n- Go right\nWhat now?"
    assert choices(_beat(Text("It is dark. You wait."))) == ""


def test_dm_only_text_in_choices_is_caught():
    room = TraceCall("room", {}, result={"dm_only": {"notes": "Three guards patrol the east side."}})
    trace = Trace(
        [
            _beat(
                room,
                Text("The wall looms.\n\n(Approach from the east, where three guards patrol the east side? Or wait?)"),
            )
        ]
    )
    found = run_checks({"beats": []}, trace, ["no_hidden_intel"])
    assert any("dm_only" in f.message for f in found), found


def test_a_tools_dm_only_keys_count_as_dm_only():
    moved = TraceCall("move_party", {"to": "vestry"}, result={"room_notes": "The cultist hides behind the brazier."})
    trace = Trace(
        [_beat(moved, Text("Smoke hangs in the air.\n\n(Search the room? Or the cultist hides behind the brazier?)"))]
    )
    assert run_checks({"beats": []}, trace, ["no_hidden_intel"])


def test_a_beats_own_hidden_terms_count():
    trace = Trace([_beat(Text("Bren waits.\n\n(Call out to Pippa? Go after the silver key?)"))])
    case = {"beats": [{"expect": {"hidden_terms": ["silver key"]}}]}
    assert run_checks(case, trace, ["no_hidden_intel"])
    assert run_checks({"beats": [{}]}, trace, ["no_hidden_intel"]) == []


def test_an_ask_answer_is_checked_whole():
    trace = Trace([_beat(Text("Backstab: +4 to hit. The ritualist would make a fine target."), player="Backstab?")])
    case = {"hidden_terms": ["ritualist"], "beats": [{"ask": True}]}
    assert run_checks(case, trace, ["no_hidden_intel"])
    assert run_checks({**case, "beats": [{}]}, trace, ["no_hidden_intel"]) == []


def test_roll_inside_batch_counts():
    batch = TraceCall("batch", {"steps": [{"tool": "advance_time", "args": {}}, {"tool": "skill_check", "args": {}}]})
    trace = Trace([_beat(batch, Text("The lock clicks open."))])
    case = {"beats": [{"expect": {"roll": {"tools": ["skill_check"], "outcome": ["clicks open"]}}}]}
    assert run_checks(case, trace, ["die_first"]) == []


def test_damage_inside_batch_counts_in_a_fight():
    fight = TraceCall("setup_combat", {"enemies": [{"name": "goblin"}]})
    batch = TraceCall(
        "batch",
        {
            "steps": [
                {"tool": "combat_round", "args": {"actions": []}},
                {"tool": "apply_damage", "args": {"character": "mon_1", "amount": 2}},
                {"tool": "apply_damage", "args": {"character": "mon_1", "amount": 2}},
            ]
        },
    )
    found = run_checks({}, Trace([_beat(fight, batch)]), ["combat_pipeline"])
    assert [f.message for f in found] == ["apply_damage in a fight with no roll behind it"]


def test_no_meta_flags_the_dms_planning_in_the_story():
    """DEL-329: barrowmaze beat 29 and beat 15, word for word."""
    trace = Trace(
        [
            _beat(Text("All misses. End combat, award the hoard (they abandoned it) and return the stolen gear.")),
            _beat(Text("I rolled the outcome of your search before writing any of this.")),
            _beat(Text("The combat is over; the goblins flee into the dark.")),
        ]
    )
    found = run_checks({}, trace, ["no_meta"])
    assert [(f.beat, f.message.split(": ", 1)[1]) for f in found] == [
        (0, "'End combat'"),
        (0, "'award the hoard'"),
        (1, "'I rolled'"),
        (1, "'before writing'"),
    ]


def test_ooc_beat_is_exempt_from_no_meta():
    trace = Trace([_beat(Text("skill_check came up 31."), player="(ooc: roll?)")])
    assert run_checks({}, trace, ["no_meta"]) == []


def test_a_read_aloud_is_told_in_its_order():
    """DEL-357: the passage's narration and song in the text, its quotes through say, in the passage's order."""
    case = {
        "beats": [
            {"expect": {"read_aloud": [{"told": "The door glows."}, {"said": "Who goes?"}, {"told": "It sings:"}]}}
        ]
    }

    def said(text):
        return TraceCall("say", {"npc": "Door", "text": text})

    told = _beat(Text("The *door* glows."), said("Who goes?"), Text("It sings: la la."))
    assert run_checks(case, Trace([told]), ["read_aloud_told"]) == []
    late = _beat(said("Who goes?"), Text("The door glows. It sings: la la."))
    assert [f.message for f in run_checks(case, Trace([late]), ["read_aloud_told"])] == [
        "'who goes' comes before 'the door glows', out of the passage's order"
    ]
    lost = _beat(said("The door glows. Who goes?"))
    assert [f.message for f in run_checks(case, Trace([lost]), ["read_aloud_told"])] == [
        "read-aloud not told (only in a say): 'the door glows'",
        "read-aloud not told: 'it sings'",
    ]


def test_a_read_aloud_call_tells_its_narration_and_says_its_lines_in_order():
    """DEL-357: what `read_aloud` posted counts as told and said, at its place in the beat, a batch's step too; a
    `heard` part may be either."""
    case = {
        "beats": [
            {
                "expect": {
                    "read_aloud": [
                        {"told": "The door glows."},
                        {"said": "Who goes?"},
                        {"heard": "Answer"},
                        {"told": "It sings: la la."},
                    ]
                }
            }
        ]
    }
    parts = [
        {"text": "The *door* glows."},
        {"said": {"speaker": {"id": "n1", "name": "Door"}, "mood": "neutral", "text": "Who goes?"}},
        {"text": '"Answer," it says. It sings: la la.'},
    ]
    call = TraceCall("read_aloud", {"room": "T1", "speaker": "Door"}, result={"key": "T1", "read_aloud": parts})
    assert run_checks(case, Trace([_beat(Text("You reach the door."), call)]), ["read_aloud_told"]) == []
    steps = {"steps": [{"tool": "read_aloud", "args": {"room": "T1"}}]}
    batch = TraceCall("batch", steps, result={"results": [{"step": 0, "tool": "read_aloud", "result": call.result}]})
    assert run_checks(case, Trace([_beat(batch)]), ["read_aloud_told"]) == []
    nobody = [parts[0], {"text": "“Who goes?”"}, parts[2]]
    unspoken = TraceCall("read_aloud", {"room": "T1"}, result={"key": "T1", "read_aloud": nobody})
    assert [f.message for f in run_checks(case, Trace([_beat(unspoken)]), ["read_aloud_told"])] == [
        "read-aloud not said (only told, by no speaker): 'who goes'"
    ]
    refused = TraceCall("read_aloud", {"room": "T1"}, result={"error": "T1 has no read-aloud text."})
    assert [f.message for f in run_checks(case, Trace([_beat(refused)]), ["read_aloud_told"])] == [
        "read-aloud not told: 'the door glows'",
        "read-aloud not said: 'who goes'",
        "read-aloud not heard: 'answer'",
        "read-aloud not told: 'it sings la la'",
    ]


def test_no_tool_outside_delve():
    delve = TraceCall("roll", {"notation": "1d20"}, raw_name="mcp__delve__roll")
    other = TraceCall("mcp__ttrpg__roll", {"notation": "1d20"}, raw_name="mcp__ttrpg__roll")
    bash = TraceCall("Bash", {"command": "ls"}, raw_name="Bash")
    assert run_checks({}, Trace([_beat(delve)]), ["no_state_bypass"]) == []
    found = run_checks({}, Trace([_beat(other, bash)]), ["no_state_bypass"])
    assert [f.message for f in found] == [
        "mcp__ttrpg__roll is not one of Delve's tools",
        "Bash is not one of Delve's tools",
    ]


# The trace


def _use(tid, name, mid="m1"):
    return {
        "type": "assistant",
        "message": {"id": mid, "content": [{"type": "tool_use", "id": tid, "name": name, "input": {"a": 1}}]},
    }


def test_result_events_split_beats_and_results_pair():
    records = [
        _use("t1", "mcp__delve__roll"),
        {
            "type": "user",
            "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "content": '{"total": 7}'}]},
        },
        {"type": "assistant", "message": {"id": "m2", "content": [{"type": "text", "text": "Seven."}]}},
        {"type": "result", "result": "Seven."},
        {"type": "assistant", "message": {"id": "m3", "content": [{"type": "text", "text": "Next."}]}},
    ]
    trace = parse_events(records)
    assert len(trace.beats) == 2
    call = trace.beats[0].tool_calls[0]
    assert (call.name, call.raw_name, call.result) == ("roll", "mcp__delve__roll", {"total": 7})


def test_repeated_blocks_are_kept_once():
    text = {"type": "assistant", "message": {"id": "m1", "content": [{"type": "text", "text": "Hello."}]}}
    trace = parse_events([text, text, _use("t1", "x"), _use("t1", "x")])
    assert len(trace.beats[0].events) == 2


def test_session_jsonl_player_messages_open_beats():
    records = [
        {"type": "user", "message": {"content": "I pick the lock."}},
        _use("t1", "mcp__delve__skill_check"),
        {"type": "user", "message": {"content": "I open the door."}},
    ]
    assert [t.player for t in parse_events(records).beats] == ["I pick the lock.", "I open the door."]


# Live mode: inspected, never run


def test_live_play_settings_come_from_the_command_line():
    """--tone and --xp go over the case's own play settings (DEL-315); `none` awards nothing."""
    from evals.__main__ import _settings

    def parsed(**kw):
        return _settings(SimpleNamespace(**{"tone": None, "xp": None, **kw}))

    assert parsed() == {}
    assert parsed(tone="grimdark", xp="gold, abilities") == {"tone": "grimdark", "xp_awards": ["gold", "abilities"]}
    assert parsed(xp="none") == {"xp_awards": []}


def test_live_needs_an_explicit_opt_in(monkeypatch):
    monkeypatch.delenv("DELVE_EVAL_LIVE", raising=False)
    assert runner.live_opted_in(False) is False
    assert runner.live_opted_in(True) is True
    monkeypatch.setenv("DELVE_EVAL_LIVE", "1")
    assert runner.live_opted_in(False) is True


def test_the_offline_evals_ignore_recordings(tmp_path):
    """A live recording is a measurement: `recorded-*.jsonl` is never a fixture, even inside `evals/fixtures/`."""
    case_dir = tmp_path / "locked_door"
    case_dir.mkdir()
    for name in ("pass.jsonl", "violates-die_first.jsonl", "recorded-20261018-101500.jsonl"):
        (case_dir / name).write_text("")
    assert [fx.name for fx in _cases.fixtures("locked_door", tmp_path)] == ["pass.jsonl", "violates-die_first.jsonl"]


def test_live_recordings_go_to_evals_recordings_never_to_fixtures(tmp_path):
    from evals import live

    out = live.recording_path("locked_door", "20261018-101500")
    assert out == ROOT / "evals" / "recordings" / "delve" / "locked_door" / "recorded-20261018-101500.jsonl"
    assert _cases.FIXTURES_DIR not in out.parents
    assert _cases.recording_dir("locked_door", "ttrpg2") == ROOT / "evals" / "recordings" / "ttrpg2" / "locked_door"
    assert live.recording_path("locked_door", "x", tmp_path) == tmp_path / "recorded-x.jsonl"


def test_recorder_writes_a_fixture_that_parses_back(tmp_path):
    """A beat's DMEvents become stream-json records: text, a prefixed tool call and its result, the beat's timings."""
    clock = iter([10.0, 11.5, 20.0])  # the beat starts, the first words, the end
    recorder = Recorder(tmp_path / "recorded.jsonl", {"case": "locked_door"}, clock=lambda: next(clock))
    with recorder:
        recorder.start_beat(0, "Pippa picks the lock.")
        for event in [
            TextDelta("Pippa kneels "),
            TextDelta("at the door."),
            ToolCall("t1", "skill_check", {"character": "Pippa", "skill": "open locks"}),
            ToolResult("t1", True, {"roll": 31, "success": True}),
            ToolCall("t2", "Bash", {"command": "ls"}),
            ToolResult("t2", False, "denied"),
            Usage(10, 20, 0.01),
            TextDelta("The bolt draws back."),
            TurnEnd("done"),
        ]:
            recorder.event(event)
        recorder.end_beat()
    records = [json.loads(line) for line in (tmp_path / "recorded.jsonl").read_text().splitlines()]
    assert records[0] == {"type": "eval_meta", "case": "locked_door"}
    (timing,) = [r for r in records if r["type"] == "eval_turn_end"]
    assert timing == {
        "type": "eval_turn_end",
        "index": 0,
        "first_text_s": 1.5,
        "seconds": 10.0,
        "tools": 2,
        "reason": "done",
    }

    trace = parse_events(records)
    (beat,) = trace.beats
    assert beat.player == "Pippa picks the lock."
    assert [type(e).__name__ for e in beat.events] == ["Text", "ToolCall", "ToolCall", "Text"]
    assert beat.events[0].text == "Pippa kneels at the door."
    first, second = beat.tool_calls
    assert (first.raw_name, first.result) == ("mcp__delve__skill_check", {"roll": 31, "success": True})
    assert (second.raw_name, second.is_error) == ("Bash", True)
    assert beat_report(records) == [{"index": 0, "first_text_s": 1.5, "seconds": 10.0, "tools": 2}]


def test_offline_never_imports_the_provider():
    """The live code imports `delve.dm.claude_cli` only inside the live path, so the offline run never needs it."""
    code = (
        "import sys, evals.__main__, evals.live, evals.runner\n"
        "assert evals.__main__.main([]) == 0\n"
        "assert 'delve.dm.claude_cli' not in sys.modules, 'imported'\n"
    )
    env = {**os.environ, "DELVE_EVAL_LIVE": ""}
    done = subprocess.run(
        [sys.executable, "-c", code], check=False, cwd=ROOT, env=env, capture_output=True, text=True, timeout=120
    )
    assert done.returncode == 0, done.stderr
    assert "fixtures as expected" in done.stdout


def test_make_has_the_eval_targets():
    makefile = (ROOT / "Makefile").read_text()
    assert "\nevals:" in makefile and "\nevals-live:" in makefile
    ci = makefile.split("\nci:", 1)[1].split("\n\n", 1)[0]
    assert "evals-live" not in ci and "--live" not in ci


def test_recorder_prefixes_the_case_rulesets_own_tools(tmp_path):
    """A pack's own tool (srd35's `set_build`) is one of Delve's on its ruleset: the recorder puts the prefix back on
    it, as on a core tool; a tool Delve doesn't have keeps its own name (DEL-389 part 5, F1)."""
    tools = specs_for_ruleset("srd35")
    recorder = Recorder(tmp_path / "recorded.jsonl", {"case": "sorcerer_cast"}, clock=lambda: 0.0, tools=tools)
    with recorder:
        recorder.start_beat(0, "Sela takes a level.")
        for event in [
            ToolCall("t1", "set_build", {"character": "Sela"}),
            ToolResult("t1", True, {"ok": True}),
            ToolCall("t2", "roll", {"dice": "1d20"}),
            ToolResult("t2", True, {"total": 12}),
            ToolCall("t3", "Read", {"file_path": "/etc/passwd"}),
            ToolResult("t3", False, "denied"),
            TurnEnd("done"),
        ]:
            recorder.event(event)
        recorder.end_beat()
    records = [json.loads(line) for line in (tmp_path / "recorded.jsonl").read_text().splitlines()]
    (beat,) = parse_events(records).beats
    assert [c.raw_name for c in beat.tool_calls] == ["mcp__delve__set_build", "mcp__delve__roll", "Read"]
    findings = CHECKS["no_state_bypass"]({"id": "sorcerer_cast"}, parse_events(records))
    assert [f.message for f in findings] == ["Read is not one of Delve's tools"]


def test_the_default_recorder_knows_only_the_cores_tools(tmp_path):
    """Without the case's tools the recorder knows the core's: `set_build` stays bare, as the F1 recordings had it."""
    recorder = Recorder(tmp_path / "recorded.jsonl", {"case": "x"}, clock=lambda: 0.0)
    with recorder:
        recorder.start_beat(0, "x")
        recorder.event(ToolCall("t1", "set_build", {}))
        recorder.event(TurnEnd("done"))
        recorder.end_beat()
    records = [json.loads(line) for line in (tmp_path / "recorded.jsonl").read_text().splitlines()]
    (beat,) = parse_events(records).beats
    assert [c.raw_name for c in beat.tool_calls] == ["set_build"]
