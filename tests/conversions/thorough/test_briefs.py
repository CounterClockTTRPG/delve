"""The thorough conversion's briefs (thorough conversion Task 5): the prompts of the sort, clean, trace and describe
agents and the part they share, `common.md`. They name only paths inside the job folder, and nothing of the one book
they were generalised from; each starts with the `PIECE:` line the fake agent recognises its piece by."""

from __future__ import annotations

import re
from importlib import resources

import pytest

from delve.conversions.qa import build_parser

BRIEFS = ("sort", "clean", "trace", "describe")
PLACEHOLDERS = {"piece", "parts", "maps", "qa"}
QA = "/home/owner/.local/share/delve/bin/qa"


def _brief(name: str) -> str:
    return resources.files("delve.modules.books").joinpath("prompts", "thorough", f"{name}.md").read_text("utf-8")


def _prompt(name: str, **values: str) -> str:
    """A piece's prompt as the pipeline sends it: the brief, then `common.md`, each placeholder filled."""
    text = _brief(name) + "\n\n" + _brief("common")
    for key, value in values.items():
        text = text.replace("{" + key + "}", value)
    return text


@pytest.mark.parametrize("name", (*BRIEFS, "common"))
def test_briefs_name_only_folder_paths(name: str) -> None:
    text = _brief(name)
    for outside in ("/home", "/tmp", "~/", "greyhawk", "W539", ".local/share"):
        assert outside.lower() not in text.lower(), f"{name}.md names {outside}"
    assert "doubts/" in text


@pytest.mark.parametrize("name", BRIEFS)
def test_briefs_start_with_their_piece(name: str) -> None:
    assert _brief(name).splitlines()[0] == "PIECE: {piece}"


@pytest.mark.parametrize("name", (*BRIEFS, "common"))
def test_briefs_have_only_known_placeholders(name: str) -> None:
    assert set(re.findall(r"\{([a-z_]+)\}", _brief(name))) <= PLACEHOLDERS


def test_briefs_fill() -> None:
    parts = "- `house`: The Haunted House, pages 4 to 9, keys `^\\d+$`"
    maps = "- `house-ground-floor`: The House, Ground Floor (part `house`, page 10)"
    clean = _prompt("clean", piece="clean-1", parts=parts, maps=maps, qa=QA)
    trace = _prompt("trace", piece="trace-house-ground-floor", parts=parts, maps=maps, qa=QA)
    sort = _prompt("sort", piece="sort", parts="", maps="", qa=QA)

    assert clean.splitlines()[0] == "PIECE: clean-1"
    assert parts in clean and "doubts/clean-1.json" in clean
    assert maps in trace and "doubts/trace-house-ground-floor.json" in trace
    assert sort.splitlines()[0] == "PIECE: sort"
    for prompt in (clean, trace, sort):
        assert not set(re.findall(r"\{([a-z_]+)\}", prompt)) & PLACEHOLDERS
        assert f"`{QA} textcheck parts.json" in prompt


@pytest.mark.parametrize("name", (*BRIEFS, "common"))
def test_briefs_run_the_tools_by_the_wrappers_path(name: str) -> None:
    """Review finding 1: the wrapper is outside the folder, and the one Bash rule names its absolute path."""
    assert "./qa" not in _brief(name)


@pytest.mark.parametrize("name", (*BRIEFS, "common"))
def test_briefs_name_only_qa_commands_there_are(name: str) -> None:
    commands = build_parser()._subparsers._group_actions[0].choices  # type: ignore[union-attr]
    named = set(re.findall(r"\{qa\} (\w+)", _brief(name)))
    assert named <= set(commands), named - set(commands)


def test_briefs_ask_only_what_the_agents_may_do() -> None:
    """U1: the agents' Bash runs the `qa` wrapper only, and they can't delete; a long output is lost to them."""
    common = _brief("common")
    assert "Bash runs `{qa}` and nothing else" in common and "You can't delete a file: empty it instead" in common
    for name in (*BRIEFS, "common"):
        assert not re.search(r"\bdelete (the|every|each)\b", _brief(name)), name
        for line in re.findall(r"`\{qa\} keys [^`]*`", _brief(name)):
            assert "--out" in line, (name, line)


def test_the_agents_keep_their_tool_output_small() -> None:
    """U1: the CLI saves an output too large to show under `~/.claude`, which the agent may not read."""
    common = _brief("common")
    assert "head_limit" in common and "`offset`" in common


def test_the_trace_brief_gives_the_maps_of_one_page_one_renderer() -> None:
    """U1: the Sea Ghost's four decks, one blue plate, came out as two `classic-bw` and two `oldschool-blue` maps."""
    assert "The page decides it, not the level" in _brief("trace")
