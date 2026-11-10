"""Play end to end with a fake `claude` (plan 2b Task 10): `delve serve` on a free port, with
`tests/fixtures/fake_claude.py` on `PATH` as `claude`, so the real `claude -p` provider, the real `delve dm-bridge`
and the real tool host play three beats over HTTP: the party is built, it goes into a room, and it fights.

The real `claude` never runs. Every tool call goes from the fake over stdio MCP to the bridge, and from the bridge
over localhost with the per-process secret to Delve.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

from delve.config import Config
from delve.modules.dscn import Bundle
from delve.storage import open_storage
from tests.fixtures import SAMPLES, fake_claude, rulesets

SECRET = "SECRET-XYZZY"
CRYPT = SAMPLES / "scenarios" / "crypt-of-saint-vellis"
FORBIDDEN_PORTS = {5000, 7777, 7790, 7810, 8000}
ISOLATION = ["--strict-mcp-config", "--setting-sources", "--disable-slash-commands", "--tools", "--allowedTools"]

GARREK = {
    "race": "Human",
    "cls": "Fighter",
    "level": 1,
    "hp_max": 10,
    "ac": 4,
    "thac0": 20,
    "ability_scores": {"str": 17, "dex": 12, "con": 15, "int": 9, "wis": 10, "cha": 11},
    "attacks": [
        {"name": "long sword", "speed": 5, "attacks": 1, "thac0": 19, "damage_sm": "1d8+1", "damage_l": "1d12+1"}
    ],
    "movement_rate": 12,
}
PIPPA = {
    "race": "Halfling",
    "cls": "Thief",
    "level": 1,
    "hp_max": 6,
    "ac": 6,
    "thac0": 20,
    "ability_scores": {"str": 10, "dex": 17, "con": 13, "int": 12, "wis": 9, "cha": 14},
    "attacks": [{"name": "short sword", "speed": 3, "attacks": 1, "thac0": 20, "damage_sm": "1d6", "damage_l": "1d8"}],
    "movement_rate": 6,
}

# Three beats, as claude would play them: a pacing line first, then the tools, then the narration.
TURNS = [
    [
        {"text": "Let me roll up your party. "},
        {"tool": "session_primer", "args": {}},
        {"tool": "new_session", "args": {"title": "Into the crypt"}},
        {"tool": "create_character", "args": {"name": "Garrek", "sheet": GARREK}},
        {"tool": "create_character", "args": {"name": "Pippa", "sheet": PIPPA}},
        {"tool": "set_marching_order", "args": {"order": ["Garrek", "Pippa"]}},
        {"text": "Garrek the fighter and Pippa the thief stand at the chapel door."},
    ],
    [
        {"text": "You go down the stairs. "},
        {"tool": "module_lookup", "args": {"query": "purse"}},
        {"tool": "move_party", "args": {"to": "Entry Hall"}},
        {"text": "Dust and old incense. The hall is quiet."},
    ],
    [
        {"text": "A goblin bursts out of the dark! "},
        {"tool": "setup_combat", "args": {"enemies": [{"name": "goblin", "count": 1, "node": "corridor.main_hall"}]}},
        {
            "tool": "combat_round",
            "args": {
                "actions": [
                    {"attacker": "Garrek", "target": "Goblin 1"},
                    {"attacker": "Pippa", "target": "Goblin 1"},
                    {"attacker": "Goblin 1", "target": "Garrek"},
                ]
            },
        },
        {"tool": "end_combat", "args": {}},
        {"text": "The fight is over as quickly as it began."},
    ],
]
ANSWER = "Surprise costs a round: a surprised character can't act for one round."


def free_port() -> int:
    """A free high port on loopback, never one of the owner's."""
    while True:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        if port not in FORBIDDEN_PORTS and port > 10000:
            return port


def planted_bundle() -> bytes:
    """The crypt sample with the secret planted in the keyed text of its vestry."""
    bundle = Bundle.load(CRYPT)
    key = bundle.text_entry("crypt-key")["file"]
    bundle.files[key] = bundle.read(key).replace(b"a purse of 40 gp.", f"a purse of 40 gp. {SECRET}".encode())
    return bundle.to_zip()


class Delve:
    """`delve serve` in a subprocess, with the fake `claude` first on its `PATH`."""

    def __init__(
        self,
        root: Path,
        turns: list = TURNS,
        side: tuple = (ANSWER,),
        translations: dict[str, str] | None = None,
        clock: bool = False,
        prompts: list[dict] | None = None,
        packs: Path | None = None,
    ) -> None:
        """With `translations`, the fake answers translations into English from them; with `prompts`, it answers side
        calls by their prompt (the fake's `prompts` rules); with `clock`, the table keeps time by `self.clock_file`,
        which `advance` moves."""
        self.data_dir = root / "data"
        self.data_dir.mkdir(parents=True)
        # OSRIC, the ruleset the campaigns play, and the doubles of the setting packs; or the folder `packs`.
        (self.data_dir / "packs").symlink_to(packs or rulesets.osric_packs_dir())
        self.fake = root / "fake"
        self.claude = fake_claude.install(self.fake / "bin")
        self.argv_log = self.fake / "argv.jsonl"
        self.input_log = self.fake / "input.jsonl"
        script = self.script = self.fake / "script.json"
        script.write_text(
            json.dumps(
                {"turns": turns, "side": list(side), "translations": translations or {}, "prompts": prompts or []}
            ),
            encoding="utf-8",
        )
        self.port = free_port()
        self.env = {
            **{k: v for k, v in os.environ.items() if not k.startswith(("DELVE_", "FAKE_CLAUDE_", "REPLICATE_"))},
            "PATH": f"{self.fake / 'bin'}:{os.environ.get('PATH', '/usr/bin:/bin')}",
            "DELVE_DATA_DIR": str(self.data_dir),
            "FAKE_CLAUDE_SCRIPT": str(script),
            "FAKE_CLAUDE_ARGV_LOG": str(self.argv_log),
            "FAKE_CLAUDE_INPUT_LOG": str(self.input_log),
            "DELVE_DM_TURN_TIMEOUT": "60",
            "DELVE_OCR": "off",  # tests never run tesseract
        }
        self.clock_file = root / "clock"
        if clock:
            self.env["DELVE_CLOCK_FILE"] = str(self.clock_file)
        self.log = (root / "serve.log").open("w")
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "delve", "serve", "--host", "127.0.0.1", "--port", str(self.port)],
            env=self.env,
            stdout=self.log,
            stderr=subprocess.STDOUT,
        )
        self.http = httpx.Client(base_url=f"http://127.0.0.1:{self.port}", timeout=30)
        self._wait_up()

    def _wait_up(self) -> None:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                raise AssertionError(f"delve serve exited with {self.proc.returncode}")
            try:
                if self.http.get("/api/health").status_code == 200:
                    return
            except httpx.TransportError:
                pass
            time.sleep(0.1)
        raise AssertionError("delve serve didn't come up")

    def settle(self, campaign_id: str, timeout: float = 60) -> dict:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            state = self.http.get(f"/api/campaigns/{campaign_id}/play/state").json()
            if state["beat"] is None:
                return state
            time.sleep(0.1)
        raise AssertionError("the beat didn't end")

    def advance(self, seconds: float) -> None:
        """Move the table's clock on (`clock=True`)."""
        offset = float(self.clock_file.read_text() or 0) if self.clock_file.exists() else 0.0
        self.clock_file.write_text(str(offset + seconds))

    def go_to_turn(self, index: int) -> None:
        """Make the script's turn `index` the DM's next one: a test whose beats repeat until something happens (an
        arrival) goes on with the turns after them."""
        cursor = self.script.with_name(self.script.name + ".cursor")
        counts = json.loads(cursor.read_text() or "{}") if cursor.exists() else {}
        cursor.write_text(json.dumps({**counts, "turns": index}))

    def lines(self, path: Path) -> list[dict]:
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []

    def stop(self) -> None:
        self.http.close()
        self.proc.terminate()
        try:
            self.proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait()
        self.log.close()


@pytest.fixture
def delve(tmp_path):
    server = Delve(tmp_path)
    yield server
    server.stop()


def test_three_beats_through_the_real_bridge(delve):
    http = delve.http
    assert http.get("/api/health").json()["dm"] == "available"
    assert http.get("/api/preferences").json()["choices"]["dm"]["provider"] == "claude-cli"

    module = http.post("/api/modules/import", content=planted_bundle(), headers={"Content-Type": "application/zip"})
    assert module.status_code == 201, module.text
    assert http.get("/api/house-rule-bundles").json() == []  # a fresh install has no house rules
    bundle = http.post("/api/house-rules/import-example", json={}).json()
    created = http.post(
        "/api/campaigns", json={"name": "Vellis", "module_id": module.json()["id"], "bundle_ids": [bundle["id"]]}
    )
    assert created.status_code == 201, created.text
    campaign = created.json()["id"]
    play = f"/api/campaigns/{campaign}"

    # 1. The party is built: the fake calls create_character through the real bridge.
    assert http.post(f"{play}/act", json={"text": "Make us a fighter and a thief."}).status_code == 202
    state = delve.settle(campaign)
    assert [pc["name"] for pc in state["party"]] == ["Garrek", "Pippa"]
    assert state["session_number"] == 1

    # 2. Into a room: the map state moves.
    assert http.post(f"{play}/act", json={"text": "We go down into the crypt."}).status_code == 202
    state = delve.settle(campaign)
    assert [(p["map"], p["label"]) for p in state["positions"]] == [("crypt", "Entry Hall")]
    map_state = http.get(f"{play}/maps/crypt/state").json()
    assert len(map_state["characters"]) == 2
    for seen in map_state["characters"].values():
        assert seen["location"] == "room.entry_hall" and "room.entry_hall" in seen["nodes"]

    # 3. A short fight.
    assert http.post(f"{play}/act", json={"text": "We fight!"}).status_code == 202
    state = delve.settle(campaign)
    assert state["combat"] is None

    # Ask the DM: a side pass with no tools.
    assert http.post(f"{play}/ask", json={"question": "What does surprise do?"}).json() == {"answer": ANSWER}

    # The story: each beat's act, the DM's text and the player-safe tool rows.
    entries = http.get(f"{play}/story", params={"limit": 200}).json()["entries"]
    kinds = [e["kind"] for e in entries]
    assert kinds.count("player_act") == 3 and kinds[-2:] == ["ask", "answer"]
    tools = [e["payload"]["name"] for e in entries if e["kind"] == "tool"]
    assert tools == [
        "new_session",
        "create_character",
        "create_character",
        "set_marching_order",
        "move_party",
        "setup_combat",
        "combat_round",
        "end_combat",
    ]  # session_primer and module_lookup are the DM's own
    narration = "".join(e["payload"]["text"] for e in entries if e["kind"] == "dm_text")
    assert "Let me roll up your party." in narration and "The fight is over" in narration
    assert not [e for e in entries if e["kind"] == "dm_error"]

    # The feed never shows the secret planted in the module, though the DM read it (the DM log has it).
    assert SECRET not in json.dumps(entries)
    assert SECRET in json.dumps(http.get(f"{play}/dm/log").json())

    # The DM was started isolated, in its own directory, and the first beat began the session.
    spawns = delve.lines(delve.argv_log)
    residents = [s for s in spawns if "--input-format" in s["argv"]]
    # The session start is a long message, so auto effort makes it high; the next beats' low effort respawns the
    # resident once, resuming the same conversation, as ttrpg2 does when its arguments change.
    assert 1 <= len(residents) <= 2
    first_id = None
    for resident in residents:
        argv = resident["argv"]
        for flag in ISOLATION:
            assert flag in argv, flag
        assert argv[argv.index("--tools") + 1] == "" and argv[argv.index("--setting-sources") + 1] == ""
        assert argv[argv.index("--allowedTools") + 1] == "mcp__delve__*"
        for tool in ("Read", "Write", "Edit", "Bash"):
            assert tool not in argv
        config = json.loads(Path(argv[argv.index("--mcp-config") + 1]).read_text())
        assert list(config["mcpServers"]) == ["delve"]
        bridge = config["mcpServers"]["delve"]
        assert bridge["args"][-5:] == ["dm-bridge", "--url", f"http://127.0.0.1:{delve.port}", "--campaign", campaign]
        assert bridge["env"]["DELVE_BRIDGE_SECRET"] not in json.dumps(argv)
        assert Path(resident["cwd"]) == delve.data_dir / "dm" / campaign
        if first_id is None:
            assert "--resume" not in argv
            first_id = True
        else:
            assert argv[argv.index("--resume") + 1].startswith("fake-")
    side = [s for s in spawns if "--input-format" not in s["argv"]]
    assert len(side) == 1 and "--strict-mcp-config" in side[0]["argv"] and SECRET not in json.dumps(side)
    inputs = [line["text"] for line in delve.lines(delve.input_log)]
    assert "session_primer" in inputs[0] and inputs[1] == "> We go down into the crypt."

    delve.stop()
    storage = open_storage(Config(data_dir=delve.data_dir))
    try:
        # Every roll is logged, keyed by the beat it was rolled in (a fight's as `<beat>/<combat id>`).
        beats = [storage.beats.get(e["beat_id"]) for e in entries if e["kind"] == "player_act"]
        assert [(b.number, b.status) for b in beats] == [(1, "done"), (2, "done"), (3, "done")]
        rolls = storage.rolls.list(campaign)
        # The first beat's session_primer rolls the day's weather (plan 6 Task 4); every other roll is the fight's.
        weather = [roll for roll in rolls if roll.key.purpose.startswith("weather:")]
        assert [(roll.key.beat, roll.key.purpose) for roll in weather] == [(beats[0].id, "weather:wilderness:day 1")]
        rolls = [roll for roll in rolls if roll not in weather]
        assert rolls and all(roll.key.beat.split("/")[0] == beats[2].id for roll in rolls)
        assert all(roll.faces and roll.notation for roll in rolls)
        fight = [entry for entry in entries if entry["kind"] == "tool" and entry["beat_id"] == beats[2].id]
        logged = json.dumps([e.raw_event_json for e in storage.dm_log.list(campaign, beats[2].id)])
        assert len(fight) == 3 and all(str(roll.total) in logged for roll in rolls)
    finally:
        storage.close()
