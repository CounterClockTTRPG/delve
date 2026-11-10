import json
import stat
from pathlib import Path

from delve.dm.claude_cli.argv import AUX_ARGS, build_argv, side_argv, write_mcp_config, write_system_prompt
from delve.domain.settings import Effort

MCP = Path("/data/dm/cmp_1/mcp.json")
PROMPT = Path("/data/dm/cmp_1/system-prompt-0123456789abcdef.md")


def test_argv_is_isolated():
    argv = build_argv(
        mcp_config=MCP, model="opus", effort=Effort.LOW, system_prompt=PROMPT, resume="sess-1", resident=True
    )
    assert argv == [
        "claude", "-p",
        "--input-format", "stream-json",
        "--output-format", "stream-json",
        "--include-partial-messages",
        "--verbose",
        "--mcp-config", str(MCP),
        "--strict-mcp-config",
        "--tools", "",
        "--allowedTools", "mcp__delve__*",
        "--setting-sources", "",
        "--disable-slash-commands",
        "--fallback-model", "sonnet",
        "--exclude-dynamic-system-prompt-sections",
        "--system-prompt-snapshot", "off",
        "--model", "opus",
        "--effort", "low",
        "--append-system-prompt-file", str(PROMPT),
        "--resume", "sess-1",
    ]  # fmt: skip
    for forbidden in ("Read", "Write", "Edit", "Bash", "--dangerously-skip-permissions", "--add-dir"):
        assert not any(forbidden in arg for arg in argv)


def test_argv_leaves_out_what_is_not_chosen():
    argv = build_argv(mcp_config=MCP, model="default", effort=None, system_prompt=None, resume=None, resident=False)
    assert "--input-format" not in argv
    for flag in ("--model", "--effort", "--append-system-prompt-file", "--resume"):
        assert flag not in argv
    assert argv[argv.index("--strict-mcp-config") - 1] == str(MCP)


def test_sonnet_has_no_sonnet_fallback():
    argv = build_argv(mcp_config=MCP, model="sonnet", effort=None, system_prompt=None, resume=None, resident=True)
    assert "--fallback-model" not in argv
    assert argv[argv.index("--model") + 1] == "sonnet"


def test_mcp_config_names_only_the_bridge(tmp_path):
    path = write_mcp_config(
        tmp_path / "dm" / "cmp_1" / "mcp.json",
        command=["/venv/bin/python", "-m", "delve"],
        url="http://127.0.0.1:7810",
        campaign_id="cmp_1",
        secret="s3cret",
    )
    assert json.loads(path.read_text()) == {
        "mcpServers": {
            "delve": {
                "type": "stdio",
                "command": "/venv/bin/python",
                "args": ["-m", "delve", "dm-bridge", "--url", "http://127.0.0.1:7810", "--campaign", "cmp_1"],
                "env": {"DELVE_BRIDGE_SECRET": "s3cret"},
            }
        }
    }
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_side_argv_uses_aux_args():
    assert AUX_ARGS == [
        "--tools", "", "--strict-mcp-config", "--disable-slash-commands", "--setting-sources", "", "--no-session-persistence",
    ]  # fmt: skip
    assert side_argv(model=None) == ["claude", "-p", "--model", "haiku", *AUX_ARGS]
    assert side_argv(model="sonnet")[2:4] == ["--model", "sonnet"]
    assert side_argv(model="default")[2:4] == ["--model", "haiku"]
    assert side_argv(model=None, effort=Effort.LOW)[-2:] == ["--effort", "low"]
    assert side_argv(model=None, effort=Effort.AUTO) == side_argv(model=None)


def test_the_system_prompt_is_a_file_named_by_what_it_says(tmp_path):
    """Not an argument, which Linux caps at 128 KB (DEL-160): a file, the owner's only, one per prompt, the newest
    three kept."""
    assert write_system_prompt(tmp_path, []) is None
    big = "House rule. " * 20_000  # 240 KB, past the argument cap
    first = write_system_prompt(tmp_path, ["You are the DM.", big])
    assert first.read_text() == "You are the DM.\n\n" + big
    assert stat.S_IMODE(first.stat().st_mode) == 0o600
    assert write_system_prompt(tmp_path, ["You are the DM.", big]) == first, "the same prompt, the same file"
    others = [write_system_prompt(tmp_path, [f"Prompt {n}."]) for n in range(3)]
    assert len(set(others)) == 3 and first not in others
    assert sorted(tmp_path.glob("system-prompt-*.md")) == sorted(others), "the oldest went"
