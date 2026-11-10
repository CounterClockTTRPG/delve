"""One agent session of a thorough conversion (thorough conversion Task 2): its argv, its permission settings and its
run, with a fake `claude` on `PATH`. The real `claude` never runs here."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

from delve.dm.claude_cli.agent import AGENT_TIMEOUT, AgentRun, AgentStopped, agent_argv, agent_settings, run_agent
from delve.dm.claude_cli.provider import ClaudeCliError
from delve.dm.provider import Usage
from delve.domain.settings import BackendChoice, Effort

CHOICE = BackendChoice("claude-cli", "opus", Effort.HIGH)


@pytest.fixture
def tree(tmp_path):
    """A home with the data dir and the repository in it, and a job folder in the data dir."""
    home = tmp_path / "home"
    data_dir = home / ".local" / "share" / "delve"
    folder = data_dir / "conversions" / "cnv_1"
    repo = home / "claude" / "refactoring"
    for path in (folder, data_dir / "conversions" / "cnv_2", data_dir / "dm", repo / "src", home / ".ssh"):
        path.mkdir(parents=True)
    for path in (data_dir / "delve.db", data_dir / "token", home / ".bashrc", home / ".local" / "notes.txt"):
        path.write_text("secret", encoding="utf-8")
    qa = data_dir / "bin" / "qa"
    qa.parent.mkdir()
    qa.write_text("#!/bin/sh\n", encoding="utf-8")
    return {"home": home, "data_dir": data_dir, "folder": folder, "repo": repo, "qa": qa}


def _settings(tree, folder: Path | None = None, **given) -> dict:
    roots = {"repo": tree["repo"], "data_dir": tree["data_dir"], "home": tree["home"], "qa": tree["qa"]}
    return agent_settings(folder or tree["folder"], **(roots | given))


def _denied(rules: list[str], tool: str, path: Path) -> bool:
    """Whether a deny rule of `tool` covers `path`: `Tool(//p)` covers p, `Tool(//p/**)` p and all below it."""
    target = str(path)
    for rule in rules:
        if not rule.startswith(f"{tool}(//") or not rule.endswith(")"):
            continue
        pattern = rule[len(tool) + 2 : -1]
        if pattern.endswith("/**"):
            root = pattern.removesuffix("/**")
            if target == root or target.startswith(root + "/"):
                return True
        elif target == pattern:
            return True
    return False


def test_agent_argv_confines_tools(tmp_path):
    settings = tmp_path / "settings.json"
    argv = agent_argv(model="opus", effort=Effort.HIGH, settings=settings)

    assert argv[:2] == ["claude", "-p"]
    assert argv[argv.index("--output-format") + 1] == "stream-json"
    assert "--verbose" in argv
    assert argv[argv.index("--tools") + 1] == "Read,Write,Edit,Glob,Grep,Bash"
    assert argv[argv.index("--settings") + 1] == str(settings)
    assert "--strict-mcp-config" in argv
    assert "--mcp-config" not in argv, "no MCP server at all"
    assert argv[argv.index("--setting-sources") + 1] == "", "no user, project or local settings"
    assert "--disable-slash-commands" in argv
    assert "--allowedTools" not in argv and "--dangerously-skip-permissions" not in argv
    assert argv[argv.index("--permission-mode") + 1] == "dontAsk"
    assert argv[argv.index("--model") + 1] == "opus"
    assert argv[argv.index("--effort") + 1] == "high"
    assert not any("prompt" in arg.lower() for arg in argv), "the prompt goes on stdin"


def test_agent_argv_keeps_no_transcript(tmp_path):
    """The CLI keeps no transcript of an agent in the owner's `~/.claude/projects` (Task 9, U1: 13 MB of one job's
    page images and texts, left there after the job ended): the job's work is its folder alone."""
    assert "--no-session-persistence" in agent_argv(model="opus", effort=Effort.HIGH, settings=tmp_path / "s.json")


def test_agent_argv_without_model_or_effort(tmp_path):
    argv = agent_argv(model=None, effort=Effort.AUTO, settings=tmp_path / "s.json")
    assert "--model" not in argv and "--effort" not in argv
    assert "--model" not in agent_argv(model="default", effort=None, settings=tmp_path / "s.json")


def test_agent_settings_deny_outside_folder(tree):
    settings = _settings(tree)
    permissions = settings["permissions"]
    allow, deny = permissions["allow"], permissions["deny"]

    assert permissions["defaultMode"] == "dontAsk"
    qa = f"Bash({tree['qa'].resolve()}:*)"
    assert allow == ["Read(./**)", "Write(./**)", "Edit(./**)", qa], "Glob and Grep go by the Read rules"
    assert [rule for rule in allow if rule.startswith("Bash")] == [qa], "no other Bash, and no ./qa"
    assert "WebFetch" in deny and "WebSearch" in deny

    data_dir, home, repo, folder = tree["data_dir"], tree["home"], tree["repo"], tree["folder"]
    outside = [
        data_dir / "delve.db",
        data_dir / "token",
        data_dir / "dm" / "cmp_1" / "mcp.json",
        data_dir / "conversions" / "cnv_2" / "state.json",
        repo,
        repo / "src" / "delve" / "__main__.py",
        home / ".bashrc",
        home / ".ssh" / "id_ed25519",
        home / ".local" / "notes.txt",
    ]
    for tool in ("Read", "Edit"):
        for path in outside:
            assert _denied(deny, tool, path), f"{tool} of {path} is not denied"
        for path in (folder, folder / "pages" / "p-001.png", folder / "parts.json"):
            assert not _denied(deny, tool, path), f"{tool} of {path} in the job folder is denied"
    assert all(rule.startswith(("Read(//", "Edit(//")) or rule in ("WebFetch", "WebSearch") for rule in deny)


def test_agent_settings_deny_what_glob_and_grep_reached(tree):
    """Review finding 6: with no bare Glob or Grep allow, those tools go by the Read rules. The deny list is a
    snapshot of what is there when the session starts, so the data dir's database files (a WAL made later) and token
    are denied by pattern too, and /proc and /etc whole."""
    deny = _settings(tree)["permissions"]["deny"]
    data_dir = tree["data_dir"].resolve()
    for tool in ("Read", "Edit"):
        assert f"{tool}(/{data_dir}/*.db*)" in deny and f"{tool}(/{data_dir}/token)" in deny
        assert f"{tool}(//proc/**)" in deny and f"{tool}(//etc/**)" in deny
    assert _denied(deny, "Read", Path("/proc/1/environ")) and _denied(deny, "Read", Path("/etc/passwd"))


def test_agent_settings_deny_a_repo_outside_home(tmp_path, tree):
    repo = tmp_path / "elsewhere" / "repo"
    repo.mkdir(parents=True)
    deny = _settings(tree, repo=repo)["permissions"]["deny"]
    assert f"Read(/{repo}/**)" in deny and f"Edit(/{repo}/**)" in deny


def test_agent_settings_refuse_a_folder_that_is_a_root(tree):
    with pytest.raises(ValueError, match="job folder"):
        _settings(tree, tree["data_dir"])


def test_agent_settings_keep_the_qa_wrapper_out_of_reach(tree, tmp_path):
    """Review finding 1: the one command Bash may run is outside the folder, and no agent may change it, so editing
    it into another command and running it is refused. A wrapper inside the folder is refused outright."""
    deny = _settings(tree)["permissions"]["deny"]
    assert _denied(deny, "Edit", tree["qa"].resolve()), "the wrapper can't be changed from inside the folder"
    elsewhere = tmp_path / "opt" / "delve-bin" / "qa"
    assert _denied(_settings(tree, qa=elsewhere)["permissions"]["deny"], "Edit", elsewhere)
    with pytest.raises(ValueError, match="qa"):
        _settings(tree, qa=tree["folder"] / "qa")


def test_agent_settings_keep_delves_records_out_of_reach(tree):
    """Review finding 8: the files Delve keeps in the folder (its state, the book as read, its warnings, its copy of
    the drafts) can't be changed by an agent, though the folder is open to it."""
    records = ("state.json", "book.json", "warnings.json", "drafted/**")
    deny = _settings(tree, records=records)["permissions"]["deny"]
    folder = tree["folder"].resolve()
    for path in (folder / "state.json", folder / "book.json", folder / "warnings.json", folder / "drafted" / "a.md"):
        assert _denied(deny, "Edit", path), f"Edit of {path} is not denied"
        assert not _denied(deny, "Read", path), "the agents may read them"
    for path in (folder / "parts.json", folder / "clean" / "house.md", folder / "draft" / "a.md"):
        assert not _denied(deny, "Edit", path), f"Edit of {path}, the agents' work, is denied"


def _fake(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: str) -> Path:
    """A `claude` on `PATH` that logs its argv, cwd, stdin and `--settings` file, then runs `body`."""
    bin_dir = tmp_path / "agent-bin"
    bin_dir.mkdir()
    log = tmp_path / "agent-log.json"
    script = bin_dir / "claude"
    script.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys, time\n"
        "argv = sys.argv[1:]\n"
        "settings = json.load(open(argv[argv.index('--settings') + 1]))\n"
        "prompt = sys.stdin.read()\n"
        f"json.dump({{'argv': argv, 'cwd': os.getcwd(), 'prompt': prompt, 'settings': settings}}, open({str(log)!r}, 'w'))\n"
        "def out(obj):\n"
        "    print(json.dumps(obj), flush=True)\n"
        f"{body}\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    return log


def _run(tree, prompt: str = "Clean part 1.", timeout: float = 30.0) -> AgentRun:
    return asyncio.run(
        run_agent(
            prompt, tree["folder"], CHOICE, timeout=timeout, repo=tree["repo"], data_dir=tree["data_dir"], qa=tree["qa"]
        )
    )


def test_run_agent_reads_cost_and_text(tmp_path, monkeypatch, tree):
    log = _fake(
        tmp_path,
        monkeypatch,
        "out({'type': 'system', 'subtype': 'init', 'session_id': 'sess-1'})\n"
        "out({'type': 'assistant', 'message': {'content': [{'type': 'text', 'text': 'Working.'}]}})\n"
        "out({'type': 'result', 'subtype': 'success', 'is_error': False, 'result': 'Part 1 cleaned.',\n"
        "     'session_id': 'sess-1', 'total_cost_usd': 1.25, 'usage': {'input_tokens': 10, 'output_tokens': 7}})\n",
    )

    run = _run(tree)

    assert run == AgentRun("Part 1 cleaned.", Usage(10, 7, 1.25), False, None, "sess-1")
    seen = json.loads(log.read_text(encoding="utf-8"))
    assert Path(seen["cwd"]) == tree["folder"].resolve()
    assert seen["prompt"] == "Clean part 1."
    assert seen["argv"][seen["argv"].index("--tools") + 1] == "Read,Write,Edit,Glob,Grep,Bash"
    assert seen["settings"] == _settings(tree, home=Path.home())
    settings_file = Path(seen["argv"][seen["argv"].index("--settings") + 1])
    assert not settings_file.is_relative_to(tree["folder"].resolve()), "the agent can't rewrite its own rules"
    assert not settings_file.exists(), "the settings file is removed after the run"


def test_run_agent_usage_limit_is_limited_not_error(tmp_path, monkeypatch, tree):
    notice = "You've hit your session limit · resets 2:50pm (UTC)"
    _fake(
        tmp_path,
        monkeypatch,
        "out({'type': 'system', 'subtype': 'init', 'session_id': 'sess-2'})\n"
        f"out({{'type': 'assistant', 'message': {{'content': [{{'type': 'text', 'text': {notice!r}}}]}}}})\n"
        f"out({{'type': 'result', 'subtype': 'success', 'is_error': True, 'result': {notice!r},\n"
        "     'session_id': 'sess-2', 'total_cost_usd': 0.4, 'usage': {'input_tokens': 3, 'output_tokens': 1}})\n"
        "sys.exit(1)\n",
    )

    run = _run(tree)

    assert run.limited is True
    assert run.resets_at == "2:50pm (UTC)"
    assert run.session_id == "sess-2"
    assert run.usage == Usage(3, 1, 0.4), "what the session spent before the limit is still spent"


def test_run_agent_error_result_raises(tmp_path, monkeypatch, tree):
    _fake(
        tmp_path,
        monkeypatch,
        "out({'type': 'result', 'subtype': 'error_during_execution', 'is_error': True, 'result': 'boom'})\nsys.exit(1)\n",
    )
    with pytest.raises(ClaudeCliError, match="boom"):
        _run(tree)


def test_run_agent_crash_raises_with_stderr(tmp_path, monkeypatch, tree):
    _fake(tmp_path, monkeypatch, "print('it broke', file=sys.stderr)\nsys.exit(3)\n")
    with pytest.raises(ClaudeCliError, match=r"exit code 3.*it broke"):
        _run(tree)


def test_run_agent_reads_long_lines(tmp_path, monkeypatch, tree):
    """A tool result (a page image read back) is one stream-json line far longer than asyncio's 64 KB default."""
    _fake(
        tmp_path,
        monkeypatch,
        "out({'type': 'user', 'message': {'content': [{'type': 'tool_result', 'content': 'x' * 3_000_000}]}})\n"
        "out({'type': 'result', 'subtype': 'success', 'is_error': False, 'result': 'Done.', 'total_cost_usd': 2})\n",
    )
    run = _run(tree)
    assert run.text == "Done." and run.usage is not None and run.usage.cost_usd == 2.0


def test_run_agent_timeout_kills(tmp_path, monkeypatch, tree):
    marker = tmp_path / "child-alive"
    _fake(
        tmp_path,
        monkeypatch,
        "import subprocess\n"
        f"subprocess.Popen(['sh', '-c', 'sleep 1.5; touch {marker}'])\n"
        "time.sleep(30)\n",
    )
    with pytest.raises(ClaudeCliError, match=r"no answer within 0\.5 s"):
        _run(tree, timeout=0.5)
    asyncio.run(asyncio.sleep(2))
    assert not marker.exists(), "the whole process group is killed"
    assert AGENT_TIMEOUT == 3 * 3600.0


_WORKING = (
    "def said(id, input, output):\n"
    "    usage = {'input_tokens': input, 'cache_read_input_tokens': 1000, 'output_tokens': output}\n"
    "    out({'type': 'assistant', 'message': {'id': id, 'content': [{'type': 'text', 'text': 'x'}], 'usage': usage}})\n"
    "said('msg_1', 10, 5)\n"
    "said('msg_1', 10, 5)\n"  # one message, two content blocks: two lines, one usage
    "said('msg_2', 20, 7)\n"
    "time.sleep(30)\n"
)


def test_a_session_that_times_out_says_what_its_stream_used(tmp_path, monkeypatch, tree):
    """Review finding 7: a killed session sends no `result`, so no cost; the tokens its stream showed are on the
    error (`seen_usage`), each message's usage once, for the job to estimate its cost from."""
    _fake(tmp_path, monkeypatch, _WORKING)
    with pytest.raises(AgentStopped, match=r"no answer within 0\.5 s") as stopped:
        _run(tree, timeout=0.5)
    assert isinstance(stopped.value, ClaudeCliError)
    assert stopped.value.seen_usage == Usage(10 + 1000 + 20 + 1000, 5 + 7, None)


def test_a_session_cancelled_says_what_its_stream_used(tmp_path, monkeypatch, tree):
    """A pause by hand, or Delve stopping, cancels the session: the cancel carries the tokens seen too."""
    _fake(tmp_path, monkeypatch, _WORKING)

    async def scenario():
        task = asyncio.create_task(
            run_agent(
                "Clean.", tree["folder"], CHOICE, timeout=30, repo=tree["repo"], data_dir=tree["data_dir"], qa=tree["qa"]
            )
        )
        await asyncio.sleep(1.0)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError as cancelled:
            return cancelled
        raise AssertionError("not cancelled")

    cancelled = asyncio.run(scenario())
    assert cancelled.seen_usage == Usage(2030, 12, None)


def test_run_agent_missing_claude(monkeypatch, tree):
    monkeypatch.setenv("PATH", "/nonexistent")
    with pytest.raises(ClaudeCliError, match="not installed"):
        _run(tree)
