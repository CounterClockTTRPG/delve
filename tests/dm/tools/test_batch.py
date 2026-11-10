"""`batch`, with ttrpg2's semantics (plan 2a Task 11). The first nine tests are ttrpg2's `BatchTests`
(`tests/test_composites.py:167-222`), one for one, with ttrpg2's fake tools `ok`, `fails` and `raises` as tool specs
of the host; the last checks what Delve adds: each step is its own transaction."""

import pytest

from delve.dice import SeededRng
from delve.dm.tools import ToolHost, ToolSpec, all_specs, composites
from tests.fixtures.rulesets import osric_catalogs

OPEN = {"type": "object"}
"""ttrpg2's fake tools took any keyword arguments."""


@pytest.fixture
def fake(storage, campaign):
    """A host with ttrpg2's fake tools besides `batch`, recording each call as ttrpg2's `_FakeToolManager` did."""
    calls: list[tuple[str, dict]] = []

    def fake_tool(name, fn):
        def run(ctx, args):
            calls.append((name, dict(args)))
            return fn(**args)

        return ToolSpec(name, f"ttrpg2's fake tool {name}.", OPEN, run, False, True)

    def raises(**kw):
        raise RuntimeError("boom")

    batch = next(spec for spec in all_specs() if spec.name == composites.BATCH)
    host = ToolHost(
        storage,
        lambda: SeededRng(1),
        specs=[
            fake_tool("ok", lambda **kw: {"echo": kw}),
            fake_tool("fails", lambda **kw: {"error": "nope"}),
            fake_tool("raises", raises),
            batch,
        ],
        catalogs=osric_catalogs(),
    )

    def run_batch(**kw):
        return host.call(campaign.id, "beat-1", "batch", kw)

    run_batch.calls = calls
    return run_batch


def test_runs_steps_in_order(fake):
    out = fake(
        steps=[
            {"tool": "ok", "args": {"n": 1}},
            {"tool": "ok", "args": {"n": 2}},
            {"tool": "ok", "args": {"n": 3}},
        ]
    )
    assert out["ran"] == 3
    assert not out["stopped_early"]
    assert [c[1]["n"] for c in fake.calls] == [1, 2, 3]


def test_step_args_may_include_name(fake):
    # apply_effect, add_condition, add_combatant … all take `name`; it must reach the tool, not collide with the
    # dispatcher's own arguments.
    out = fake(steps=[{"tool": "ok", "args": {"name": "Ruk", "amount": 3}}])
    assert out["results"][0].get("result") == {"echo": {"name": "Ruk", "amount": 3}}


def test_empty_and_oversized_are_rejected(fake):
    assert "error" in fake(steps=[])
    too_many = [{"tool": "ok", "args": {}}] * (composites._MAX_STEPS + 1)
    assert "error" in fake(steps=too_many)


def test_stops_on_error_result_by_default(fake):
    out = fake(
        steps=[
            {"tool": "ok", "args": {}},
            {"tool": "fails", "args": {}},
            {"tool": "ok", "args": {"never": True}},
        ]
    )
    assert out["stopped_early"]
    assert out["ran"] == 2
    assert len(fake.calls) == 2
    # Said outright, with what never ran (DEL-334: a stopped batch read as done, and its XP awards were lost).
    assert out["not_run"] == ["ok"]
    assert out["stopped"].startswith("Step 1 (fails) failed: ") and out["stopped"].endswith("did not run: ok.")


def test_continues_past_errors_when_asked(fake):
    out = fake(
        stop_on_error=False,
        steps=[
            {"tool": "fails", "args": {}},
            {"tool": "ok", "args": {}},
        ],
    )
    assert not out["stopped_early"]
    assert out["ran"] == 2


def test_raised_exception_becomes_a_step_error(fake):
    out = fake(steps=[{"tool": "raises", "args": {}}])
    assert "boom" in out["results"][0]["error"]


def test_unknown_tool_is_reported_not_called(fake):
    out = fake(steps=[{"tool": "nosuch", "args": {}}])
    assert out["results"][0]["error"] == "unknown tool"
    assert fake.calls == []


def test_nesting_and_pre_turn_check_are_denied(fake):
    for name in ("batch", "pre_turn_check"):
        out = fake(steps=[{"tool": name, "args": {}}])
        assert "cannot run inside batch" in out["results"][0]["error"]
        assert fake.calls == []


def test_bad_args_shape_is_reported(fake):
    out = fake(steps=[{"tool": "ok", "args": "not-a-dict"}])
    assert out["results"][0]["error"] == "args must be an object"


# --- Delve's addition --------------------------------------------------------------------------------------------


def test_batch_steps_commit_separately(call, party, storage, campaign, monkeypatch):
    """Each step is its own transaction: a step that fails halfway leaves nothing of its own, and the steps before it
    stay done. Garrek's damage commits; Pippa's XP write is followed by a failing event write, so her XP is rolled
    back with it; the batch stops there."""
    real_append = storage.events.append

    def append(campaign_id, type, data, **kw):
        if type == "xp_awarded":
            raise RuntimeError("the disk is full")
        return real_append(campaign_id, type, data, **kw)

    monkeypatch.setattr(storage.events, "append", append)
    out = call(
        "batch",
        steps=[
            {"tool": "apply_damage", "args": {"character": "Garrek", "amount": 3}},
            {"tool": "award_xp", "args": {"character": "Pippa", "amount": 100}},
            {"tool": "apply_damage", "args": {"character": "Pippa", "amount": 1}},
        ],
    )
    monkeypatch.undo()
    assert (out["ran"], out["stopped_early"]) == (2, True)
    assert out["results"][0]["result"]["hp_after"] == 7
    assert out["results"][1] == {"step": 1, "tool": "award_xp", "error": "the disk is full"}
    garrek, pippa = (call("get_character", ref=n, brief=True) for n in ("Garrek", "Pippa"))
    assert (garrek["hp"], pippa["xp"], pippa["hp"]) == (7, 0, 6)


def test_a_step_refused_by_its_tool_is_its_result(call, party):
    """A tool's own refusal is the step's result, as ttrpg2's tools answered `{"error"}`; arguments that don't fit
    the tool's schema are the step's error, as ttrpg2's validation raised."""
    out = call(
        "batch",
        stop_on_error=False,
        steps=[
            {"tool": "apply_damage", "args": {"character": "Nobody", "amount": 1}},
            {"tool": "apply_damage", "args": {"character": "Garrek"}},
            {"tool": "roll", "args": {"notation": "1d6", "purpose": "after the errors"}},
        ],
    )
    first, second, third = out["results"]
    assert first["result"]["error"] == "No character 'Nobody'." and first["result"]["candidates"]
    assert second["error"].startswith("Bad arguments for apply_damage") and "result" not in second
    assert third["result"]["total"] in range(1, 7)


def test_a_stray_args_key_inside_a_steps_args_is_forgiven(call, party):
    """The DM nested a null `args` beside a step's own arguments (`{"tool": "log_note", "args": {"args": null,
    "text": …}}`) and the batch stopped at it; a null `args` is dropped and an `args` object is opened, for a tool
    with no `args` of its own."""
    out = call(
        "batch",
        steps=[
            {"tool": "log_note", "args": {"args": None, "text": "Camped at the shrine."}},
            {"tool": "log_note", "args": {"args": {"text": "Broke camp at dawn."}}},
        ],
    )
    assert (out["ran"], out["stopped_early"]) == (2, False), out
    assert all("error" not in r and "error" not in r["result"] for r in out["results"]), out


def test_a_stray_args_key_on_a_direct_call_is_forgiven(call, party):
    out = call("log_note", args=None, text="Camped at the shrine.")
    assert "error" not in out, out
