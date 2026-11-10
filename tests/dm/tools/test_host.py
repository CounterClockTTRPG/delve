"""The tool host (plan 2a Task 11): valid specs, arguments checked against them, one transaction per call, and every
refusal answered as `{"error", "hint"?, "candidates"?}`, never raised."""

import json
import re

import pytest

from delve.dice import SeededRng
from delve.dm.tools import ToolHost, ToolSpec
from delve.dm.tools.host import NO_LOOKUPS_ERROR
from delve.dm.tools.schema import AREAS, check_schema, params, tool
from delve.domain.characters import Sheet
from delve.play import characters
from delve.play.context import PlayError
from tests.fixtures.rulesets import osric_catalogs, over


def test_every_mutating_tool_names_the_areas_it_changes(host):
    """So a call tells the table only what it may have changed (DEL-168): every mutating tool names its areas, none
    unknown; `batch` alone leaves them out, as its steps name theirs; a read changes none."""
    for spec in host.specs():
        if spec.name == "batch":
            assert spec.areas is None
        elif spec.mutates:
            assert spec.areas is not None, spec.name
            assert set(spec.areas) <= set(AREAS), spec.name
        else:
            assert not spec.areas, spec.name
    by_name = {spec.name: spec for spec in host.specs()}
    assert by_name["roll"].areas == ()
    assert by_name["move_party"].areas == ("map_state",)
    assert set(by_name["apply_damage"].areas) == {"characters", "combat"}
    with pytest.raises(ValueError, match="unknown areas"):
        tool([], "odd", params(), mutates=True, areas=("weather",))


def test_every_spec_has_valid_schema_and_description(host):
    """Every tool has a unique snake_case name, a one-paragraph description for the DM, and an object schema that
    names its required arguments and refuses unknown ones; every argument is described."""
    specs = host.specs()
    names = [spec.name for spec in specs]
    assert len(names) == len(set(names))
    for spec in specs:
        assert re.fullmatch(r"[a-z][a-z_]*", spec.name), spec.name
        assert spec.description and "\n" not in spec.description and len(spec.description) >= 20, spec.name
        check_schema(spec.params)
        assert spec.params["type"] == "object" and spec.params["additionalProperties"] is False, spec.name
        assert set(spec.params["required"]) <= set(spec.params["properties"]), spec.name
        for arg, schema in spec.params["properties"].items():
            assert schema.get("description"), f"{spec.name}.{arg}"
        assert isinstance(spec.mutates, bool) and isinstance(spec.player_visible, bool)


def test_bad_args_error_not_raise(call, party):
    """A call whose arguments don't fit the schema answers `{"error", "hint"}` with the tool's usage, and runs
    nothing."""
    for name, args in (
        ("apply_damage", {"character": "Garrek"}),  # amount missing
        ("apply_damage", {"character": "Garrek", "amount": "3"}),  # a string, not a number
        ("apply_damage", {"character": "Garrek", "amount": True}),  # a boolean is no number
        ("apply_damage", {"character": "Garrek", "amount": 3, "crit": True}),  # unknown argument
        ("set_time", {"hour": 25}),
    ):
        out = call(name, **args)
        assert set(out) == {"error", "hint"}, (name, args, out)
        assert out["error"].startswith(f"Bad arguments for {name}") and out["hint"].startswith(f"Call it as {name}(")
    assert call("get_character", ref="Garrek", brief=True)["hp"] == 10
    assert call("nosuch")["error"] == "Unknown tool 'nosuch'."


def test_args_must_be_an_object(host, campaign):
    out = host.call(campaign.id, "beat-1", "party_status", ["not", "an", "object"])  # type: ignore[arg-type]
    assert out == {"error": "args must be an object", "hint": "Call it as party_status()."}


def test_refusals_answer_error_hint_candidates(call, party):
    """Known exceptions become answers: an ambiguous or unknown name with its candidates, a rule the state refuses
    with a hint, notation too large."""
    call("create_character", name="Garrek", sheet={"hp_max": 4})
    ambiguous = call("apply_damage", character="Garrek", amount=1)
    assert "ambiguous" in ambiguous["error"] and len(ambiguous["candidates"]) == 2
    assert {c["name"] for c in ambiguous["candidates"]} == {"Garrek"}
    unknown = call("get_character", ref="Gar")
    assert unknown["error"] == "No character 'Gar'." and unknown["hint"]
    refused = call("combat_status")
    assert refused == {"error": "No combat is under way.", "hint": "Start one with setup_combat."}
    assert "Too many dice" in call("roll", notation="999d6", purpose="x")["error"]
    assert call("saving_throw", character="Pippa", save_type="luck")["candidates"] == [
        "para",
        "poly",
        "rsw",
        "breath",
        "spell",
    ]
    assert call("get_character", ref="Pippa", unknown_campaign=True)["error"].startswith("Bad arguments")


def test_unknown_campaign_is_an_answer(host):
    out = host.call("cmp_000000000000", "beat-1", "party_status", {})
    assert out["error"] == "No campaign 'cmp_000000000000'."


def test_tool_call_is_one_transaction(call, party, storage, campaign, monkeypatch):
    """Review Focus 3 through the host: a call whose last write fails leaves nothing of its earlier writes. award_xp
    saves the XP, then logs its event; the event write raises, so the XP isn't saved either."""
    before = len(storage.events.list(campaign.id))

    def broken(*args, **kwargs):
        raise RuntimeError("the disk is full")

    monkeypatch.setattr(storage.events, "append", broken)
    with pytest.raises(RuntimeError):
        call("award_xp", character="Garrek", amount=500)
    monkeypatch.undo()
    assert call("get_character", ref="Garrek", brief=True)["xp"] == 0
    assert len(storage.events.list(campaign.id)) == before


def test_a_refused_call_rolls_back(storage, campaign):
    """A tool that writes and is then refused answers the refusal, and its writes are gone."""

    def half(ctx, args):
        characters.create(ctx, name="Ghost", sheet={"hp_max": 1})
        raise PlayError("Refused after writing.", hint="Nothing was kept.")

    spec = ToolSpec("half", "Writes, then refuses: for this test only.", params(), half, True, True)
    host = ToolHost(storage, lambda: SeededRng(1), specs=[spec], catalogs=osric_catalogs())
    assert host.call(campaign.id, "beat-1", "half", {}) == {
        "error": "Refused after writing.",
        "hint": "Nothing was kept.",
    }
    assert storage.characters.list(campaign.id) == []


def test_rolls_of_a_call_commit_with_it(call, party, storage, campaign):
    """A roll is part of its call: a call refused after rolling leaves no roll in the log."""
    call("roll", notation="1d20", purpose="lever")
    assert len(storage.rolls.list(campaign.id)) == 1
    out = call("skill_check", character="Garrek", skill="climb walls")  # refused before rolling
    assert "not found" in out["error"]
    assert len(storage.rolls.list(campaign.id)) == 1


def test_results_are_json_objects(call, party):
    for name, args in (
        ("party_status", {}),
        ("get_character", {"ref": "Garrek"}),
        ("saving_throw", {"character": "Garrek", "save_type": "spell"}),
        ("surprise_check", {}),
        ("turning_undead", {"level": 3, "undead": "skeleton"}),
    ):
        out = call(name, **args)
        assert isinstance(out, dict) and "error" not in out, (name, out)
        assert json.loads(json.dumps(out)) == out


def test_reference_missing_answers_never_crashes(storage, campaign):
    """Review Focus 5: a pack's ruleset without its lookups (a `pack.db` not built) answers `the ruleset has no
    lookups` from every tool."""
    host = ToolHost(storage, lambda: SeededRng(1), catalogs=over(None))
    for name, args in (
        ("monster_lookup", {"name": "goblin"}),
        ("party_status", {}),
        ("roll", {"notation": "1d6", "purpose": "x"}),
    ):
        out = host.call(campaign.id, "beat-1", name, args)
        assert out == {"error": NO_LOOKUPS_ERROR, "hint": "Run: delve pack rebuild osric"}


def test_same_roll_in_a_beat_is_the_stored_one(call, party, storage, campaign):
    """Spec §6.5 through the host: the same save in the same beat is the stored roll, though each call has fresh
    dice; the next beat rolls fresh."""
    first = call("saving_throw", character="Garrek", save_type="spell")
    again = call("saving_throw", character="Garrek", save_type="spell")
    assert again["roll"] == first["roll"]
    later = call("saving_throw", beat="beat-2", character="Garrek", save_type="spell")
    assert later["roll"]["id"] != first["roll"]["id"]
    assert len(storage.rolls.list(campaign.id)) == 2


def test_sheet_errors_are_answers(call):
    out = call("create_character", name="Bad", sheet={"hp_max": "lots"})
    assert out["error"].startswith("Bad sheet: hp_max") and "sheet's fields" in out["hint"]
    assert Sheet  # the sheet's fields are those of delve.domain.characters.Sheet


def test_the_sheet_schema_describes_every_sheet_field(host):
    """The DM learns a sheet's shape only from the tool list. In the first real session it put weapon proficiencies
    under `skills` (percentages) and passed `skills` as a list, because the schema didn't say what they hold."""
    from dataclasses import fields

    for name in ("create_character", "update_character"):
        spec = host.spec(name)
        schema = spec.params["properties"]["sheet" if name == "create_character" else "patch"]
        described = set(schema["properties"]) | {word.strip("(),.:;'") for word in schema["description"].split()}
        missing = {f.name for f in fields(Sheet)} - {"kind", "label"} - described
        assert not missing, f"{name} doesn't describe {sorted(missing)}"
        assert schema["properties"]["skills"]["additionalProperties"] == {"type": "integer"}
        assert schema["properties"]["weapon_profs"]["items"] == {"type": "string"}


def test_a_list_of_skills_is_refused_naming_the_field(call):
    out = call("create_character", name="Hesh", sheet={"skills": ["footman's mace", "sling"]})
    assert "sheet.skills" in out["error"]
    made = call("create_character", name="Hesh", sheet={"weapon_profs": ["footman's mace", "sling"], "skills": {}})
    assert made["sheet"]["weapon_profs"] == ["footman's mace", "sling"]


def test_encounter_checks_an_hour_apart_roll_fresh(call, party, storage, campaign):
    """Review D-b: three hourly encounter checks in one beat roll three times, keyed by the game time; two checks at
    the same time are the stored roll."""
    first = call("encounter_check", terrain="dungeon")
    assert call("encounter_check", terrain="dungeon")["check"]["id"] == first["check"]["id"]
    for _ in range(2):
        call("advance_time", minutes=60)
        call("encounter_check", terrain="dungeon")
    checks = [r.key.purpose for r in storage.rolls.list(campaign.id) if r.key.purpose.startswith("encounter:check")]
    assert checks == ["encounter:check#day 1 06:00", "encounter:check#day 1 07:00", "encounter:check#day 1 08:00"]


def test_checks_take_an_occasion(call, party, storage, campaign):
    """The jump and the knot: two ability checks with their occasions roll twice."""
    jump = call("ability_check", character="Garrek", ability="dex", occasion="jump the gap")
    knot = call("ability_check", character="Garrek", ability="dex", occasion="tie the knot")
    assert jump["roll"]["id"] != knot["roll"]["id"]
    again = call("ability_check", character="Garrek", ability="dex", occasion="jump the gap")
    assert again["roll"]["id"] == jump["roll"]["id"]
    call("skill_check", character="Pippa", skill="move silently", occasion="past the guard", hidden=True)
    purposes = [r.key.purpose for r in storage.rolls.list(campaign.id)]
    assert purposes[-3:] == [
        "ability:dex#jump the gap",
        "ability:dex#tie the knot",
        "skill:move_silently#past the guard",
    ]
