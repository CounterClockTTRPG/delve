"""The fake `claude` on `PATH`, its script and logs, and a provider whose bridge is the tiny `echo_mcp` server."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from delve.dm.claude_cli.provider import ClaudeCliProvider, MemorySessions
from tests.fixtures import fake_claude

ECHO_MCP = Path(__file__).with_name("echo_mcp.py")


class FakeClaude:
    def __init__(self, root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.root = root
        self.argv_log = root / "argv.jsonl"
        self.input_log = root / "input.jsonl"
        self.mcp_log = root / "mcp.jsonl"
        self.vision_log = root / "vision.jsonl"
        self._monkeypatch = monkeypatch
        fake_claude.install(root / "bin")
        monkeypatch.setenv("PATH", f"{root / 'bin'}:/usr/bin:/bin")
        monkeypatch.setenv("FAKE_CLAUDE_ARGV_LOG", str(self.argv_log))
        monkeypatch.setenv("FAKE_CLAUDE_INPUT_LOG", str(self.input_log))
        monkeypatch.setenv("ECHO_MCP_LOG", str(self.mcp_log))
        monkeypatch.setenv("FAKE_CLAUDE_VISION_LOG", str(self.vision_log))
        self.script([])

    def script(
        self, turns: list, side: list[str] | None = None, vision: list[str] | None = None, side_cost: float = 0.0
    ) -> None:
        path = self.root / "script.json"
        script = {"turns": turns, "side": side or [], "vision": vision or [], "side_cost": side_cost}
        path.write_text(json.dumps(script), encoding="utf-8")
        path.with_name("script.json.cursor").unlink(missing_ok=True)
        self._monkeypatch.setenv("FAKE_CLAUDE_SCRIPT", str(path))

    @staticmethod
    def _lines(path: Path) -> list[dict]:
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    def spawns(self) -> list[dict]:
        return self._lines(self.argv_log)

    def inputs(self) -> list[dict]:
        return self._lines(self.input_log)

    def mcp_calls(self) -> list[dict]:
        return self._lines(self.mcp_log)

    def vision_calls(self) -> list[dict]:
        return self._lines(self.vision_log)


@pytest.fixture
def claude(tmp_path, monkeypatch):
    monkeypatch.delenv("DELVE_DM_TURN_TIMEOUT", raising=False)
    monkeypatch.delenv("DELVE_DM_RESET_TOKENS", raising=False)
    return FakeClaude(tmp_path / "fake", monkeypatch)


@pytest.fixture
def data_dir(tmp_path):
    return tmp_path / "data"


@pytest.fixture
def sessions():
    return MemorySessions()


@pytest.fixture
def provider(claude, data_dir, sessions):
    return ClaudeCliProvider(
        data_dir,
        sessions,
        bridge_url="http://127.0.0.1:7811",
        bridge_secret="s3cret",
        bridge_command=[sys.executable, str(ECHO_MCP)],
    )
