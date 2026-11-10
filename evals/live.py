"""Live mode (opt-in, never in tests): play a case through Delve's real `claude -p` provider and record a fixture.

It never touches real play. Everything runs in a temp data dir:
- OSRIC is installed from `packs/osric` (a case of another ruleset or a setting pack needs that pack installed too);
- the case's sample module is imported and a campaign started on it with the seeded house rules;
- the setup calls and the secrets go through the tool host;
- a Delve serves the internal tool endpoint on a free loopback port, for `delve dm-bridge`;
- the DM is `delve.dm.claude_cli.ClaudeCliProvider`, isolated as in play (`--strict-mcp-config`, no file tools), in
  `<temp data dir>/dm/<campaign>/`.

Each beat's DMEvents are written as stream-json records (`Recorder`), so the offline checks read the recording as
they read a hand-written fixture. Per beat it reports the time to the first `TextDelta`, the total time and the tool
count. `--compare-ttrpg2` plays the same player lines through ttrpg2's own live mode (its `evals` runner, read only)
and sets the two side by side.

The provider, the web app and the beat runner are imported inside `run_live`, so the offline harness never needs
them.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Self

from evals import cases as _cases
from evals.trace import MCP_PREFIX, read_records

TTRPG2 = Path.home() / "claude" / "ttrpg2"
# Ports in use on the owner's machine, and Delve's own default: never the eval server's.
FORBIDDEN_PORTS = {5000, 7777, 7790, 8000, 7810}
PROVIDER = "claude-cli"


def _delve_tool_names() -> frozenset[str]:
    from delve.dm.tools import all_specs

    return frozenset(spec.name for spec in all_specs())


class Recorder:
    """Writes a live run as a fixture: the meta line, then per beat its marker, the DM's text, tool calls and results
    as stream-json records, the `result`, and an `eval_turn_end` with the beat's timings.

    The provider strips `mcp__delve__` from Delve's tools; the recorder puts it back on them, so a call to anything
    else keeps its own name and no_state_bypass sees it.
    """

    def __init__(self, path: Path, meta: dict[str, Any], clock: Callable[[], float] = time.monotonic) -> None:
        self.path = Path(path)
        self.meta = meta
        self.clock = clock
        self._file = None
        self._delve = _delve_tool_names()

    def __enter__(self) -> Self:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self.path.open("w", encoding="utf-8")
        self._write({"type": "eval_meta", **self.meta})
        return self

    def __exit__(self, *exc) -> None:
        self._file.close()

    def _write(self, record: dict[str, Any]) -> None:
        self._file.write(json.dumps(record) + "\n")
        self._file.flush()

    def start_beat(self, index: int, player: str, *, ask: bool = False) -> None:
        self.index, self.started, self.first_text, self.tools, self.reason = index, self.clock(), None, 0, None
        self._text: list[str] = []
        self._messages = 0
        self._usage: dict[str, Any] = {}
        self._write({"type": "eval_turn", "index": index, "player": player, **({"ask": True} if ask else {})})

    def _assistant(self, block: dict[str, Any]) -> None:
        self._messages += 1
        self._write(
            {
                "type": "assistant",
                "message": {"id": f"msg_{self.index}_{self._messages}", "role": "assistant", "content": [block]},
            }
        )

    def _flush_text(self) -> None:
        text = "".join(self._text).strip()
        self._text = []
        if text:
            self._assistant({"type": "text", "text": text})

    def event(self, event: Any) -> None:
        """One DMEvent of the beat's reply."""
        kind = type(event).__name__
        if kind == "TextDelta":
            if self.first_text is None:
                self.first_text = self.clock()
            self._text.append(event.text)
        elif kind == "ToolCall":
            self._flush_text()
            self.tools += 1
            name = MCP_PREFIX + event.name if event.name in self._delve else event.name
            self._assistant({"type": "tool_use", "id": event.id, "name": name, "input": event.args})
        elif kind == "ToolResult":
            content = event.content if isinstance(event.content, str) else json.dumps(event.content)
            self._write(
                {
                    "type": "user",
                    "message": {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": event.id,
                                "content": content,
                                "is_error": not event.ok,
                            }
                        ],
                    },
                }
            )
        elif kind == "Usage":
            self._usage = {
                "input_tokens": event.input_tokens,
                "output_tokens": event.output_tokens,
                "cost_usd": event.cost_usd,
            }
        elif kind == "DMError":
            self._flush_text()
            self._write({"type": "eval_dm_error", "message": event.message, "detail": getattr(event, "detail", "")})
        elif kind == "TurnEnd":
            self._flush_text()
            self.reason = event.reason
            self._write(
                {"type": "result", "subtype": event.reason, "is_error": event.reason != "done", "usage": self._usage}
            )

    def answer(self, text: str) -> None:
        """An Ask the DM answer: one text, no tools."""
        self.first_text = self.clock()
        self._text = [text]
        self._flush_text()
        self.reason = "done"
        self._write({"type": "result", "subtype": "done", "is_error": False})

    def end_beat(self) -> dict[str, Any]:
        """Close the beat; its timings, as written."""
        self._flush_text()
        now = self.clock()
        timing = {
            "type": "eval_turn_end",
            "index": self.index,
            "first_text_s": None if self.first_text is None else round(self.first_text - self.started, 2),
            "seconds": round(now - self.started, 2),
            "tools": self.tools,
            "reason": self.reason or "error",
        }
        self._write(timing)
        return timing


def beat_report(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Per beat of a recording: the time to the first text, the total time and the tool count."""
    return [
        {
            "index": r["index"],
            "first_text_s": r.get("first_text_s"),
            "seconds": r.get("seconds"),
            "tools": r.get("tools"),
        }
        for r in records
        if r.get("type") == "eval_turn_end"
    ]


def _free_socket() -> socket.socket:
    """A socket bound on loopback to a free high port the system picks."""
    for _ in range(10):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", 0))
        if sock.getsockname()[1] > 10000 and sock.getsockname()[1] not in FORBIDDEN_PORTS:
            return sock
        sock.close()
    raise RuntimeError("no free high port")



async def _ask(services: SimpleNamespace, campaign_id: str, question: str) -> str:
    """Ask the DM, as the play screen asks it (`delve.play.ask.ask`, plan 2b Task 6)."""
    from delve.play.ask import ask

    answer = ask(services, campaign_id, question)
    if inspect.isawaitable(answer):
        answer = await answer
    if isinstance(answer, dict):
        answer = answer.get("answer") or answer.get("text") or ""
    return str(answer)


def recording_path(case_id: str, stamp: str, out_dir: Path | None = None) -> Path:
    """A live recording's file: `recorded-<stamp>.jsonl` in `out_dir`, by default the case's recording dir, never
    evals/fixtures/."""
    return (out_dir or _cases.recording_dir(case_id)) / f"recorded-{stamp}.jsonl"


def run_live(
    case: dict,
    *,
    model: str | None = None,
    effort: str | None = None,
    out_dir: Path | None = None,
    scenarios_dir: Path = _cases.SCENARIOS_DIR,
    keep_data: bool = False,
    settings: dict[str, Any] | None = None,
) -> Path:
    """Play the case's beats through Delve's `claude -p` provider and record them as
    evals/recordings/delve/<case>/recorded-<timestamp>.jsonl (`recording_path`). Returns its path.

    The campaign plays the case's `play_settings` with `settings` over them (a tone, `xp_awards`), and the DM's prompt
    is built from them as in play."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = recording_path(case["id"], stamp, out_dir)
    root = Path(tempfile.mkdtemp(prefix=f"delve-eval-{case['id']}-"))
    try:
        asyncio.run(
            _play(
                case,
                out,
                root,
                model=model,
                effort=effort,
                scenarios_dir=scenarios_dir,
                stamp=stamp,
                settings={**(case.get("play_settings") or {}), **(settings or {})},
            )
        )
    finally:
        if keep_data:
            print(f"data dir kept at {root / 'data'}", file=sys.stderr)
        else:
            shutil.rmtree(root, ignore_errors=True)
    return out


async def _play(
    case: dict, out: Path, root: Path, *, model, effort, scenarios_dir: Path, stamp: str, settings: dict[str, Any]
) -> None:
    import uvicorn

    from delve.__main__ import build_registries
    from delve.config import Config
    from delve.dice import SystemRng
    from delve.dm.claude_cli import ClaudeCliProvider
    from delve.dm.claude_cli.effort import TurnContext
    from delve.dm.prompt import build_system_prompt
    from delve.dm.provider import ConversationSpec
    from delve.dm.tools import ToolHost
    from delve.domain.settings import BackendChoice, Effort
    from delve.packs.catalogs import Catalogs
    from delve.packs.transit import install_pack
    from delve.play import seats
    from delve.play.context import context_for
    from delve.play.table import close_beat, open_beat, play_settings, quoted, set_play_settings
    from delve.storage import open_storage
    from delve.web.app import create_app

    config = Config(data_dir=root / "data", host="127.0.0.1")
    config.data_dir.mkdir(parents=True)
    install_pack(Path(__file__).resolve().parents[1] / "packs" / "osric", config.packs_dir)
    storage = open_storage(config)
    server = thread = sock = provider = conversation = None
    try:
        campaign = _cases.start_campaign(storage, case, scenarios_dir)
        played = set_play_settings(storage, campaign.id, settings) if settings else play_settings(storage, campaign.id)
        host = ToolHost(storage, SystemRng, catalogs=Catalogs.installed(config))
        for step, result in zip(_cases.setup_calls(case), _cases.set_up(host, campaign.id, case), strict=True):
            if "error" in result:
                raise RuntimeError(f"setup {step['tool']} was refused: {result}")

        static = root / "static"
        static.mkdir()
        (static / "index.html").write_text("<!doctype html><title>Delve eval</title>")
        registries = build_registries(config)
        app = create_app(config, storage, registries, static_dir=static)
        app.state.tool_host = host
        sock = _free_socket()
        server = uvicorn.Server(uvicorn.Config(app, log_level="warning", lifespan="off"))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
        thread.start()
        deadline = time.monotonic() + 10
        while not server.started and time.monotonic() < deadline:
            await asyncio.sleep(0.02)
        if not server.started:
            raise RuntimeError("the eval's Delve didn't start")

        provider = ClaudeCliProvider(
            config.data_dir,
            storage.dm_sessions,
            bridge_url=f"http://127.0.0.1:{sock.getsockname()[1]}",
            bridge_secret=app.state.bridge_secret,
            turn_context=lambda campaign_id: TurnContext(in_combat=storage.combats.live(campaign_id) is not None),
        )
        ctx = context_for(storage, campaign.id, _cases.SETUP_BEAT, catalogs=host.catalogs)
        prompt = "\n\n".join(
            build_system_prompt(
                ctx,
                tone=played["tone"],
                detail=played["detail"],
                custom_tone=played["custom_tone"],
                xp_awards=played["xp_awards"],
            )
        )
        choice = BackendChoice(PROVIDER, model, Effort(effort) if effort else None)
        conversation = await provider.open(ConversationSpec(campaign.id, prompt, choice))
        side_choice = BackendChoice(PROVIDER, None, None)
        services = SimpleNamespace(
            config=config,
            storage=storage,
            registries=registries,
            dm=provider,
            tool_host=host,
            side=lambda campaign_id: (provider, side_choice),
            publish=lambda kind, data: None,
        )

        meta = {
            "case": case["id"],
            "mode": "live",
            "recorded_at": stamp,
            "provider": PROVIDER,
            "model": model or "default",
            "effort": effort or "auto",
            "tone": played["tone"],
            "xp_awards": played["xp_awards"],
        }
        with Recorder(out, meta) as recorder:
            for n, beat in enumerate(case.get("beats") or []):
                recorder.start_beat(n, beat["player"], ask=bool(beat.get("ask")))
                if beat.get("ask"):
                    recorder.answer(await _ask(services, campaign.id, beat["player"]))
                else:
                    opened = open_beat(
                        storage,
                        campaign.id,
                        {"player": seats.owner_seat(storage, campaign.id).id, "character_ids": [], "kind": "act", "text": beat["player"]},
                    )
                    # Quoted as Delve sends a solo act (DEL-154); the recording keeps the player's own line.
                    async for event in conversation.send(quoted(beat["player"])):
                        recorder.event(event)
                    close_beat(storage, opened.id, "done" if recorder.reason == "done" else "failed")
                timing = recorder.end_beat()
                print(f"  beat {n}: {_timing_line(timing)}", file=sys.stderr)
    finally:
        if conversation is not None:
            await conversation.close()
        if provider is not None:
            await provider.close()
        if server is not None:
            server.should_exit = True
            thread.join(timeout=10)
        if sock is not None:
            sock.close()
        storage.close()


def _seconds(value) -> str:
    return "–" if value is None else f"{value:.1f} s"


def _timing_line(timing: dict[str, Any]) -> str:
    return (
        f"first words {_seconds(timing.get('first_text_s'))}, total {_seconds(timing.get('seconds'))}, "
        f"{timing.get('tools')} tool(s)"
    )


# ── ttrpg2, side by side ────────────────────────────────────────────────

# Run inside ttrpg2's checkout, with its own interpreter: its live mode, recording into our directory, then its checks.
_TTRPG2_SCRIPT = """
import json, sys
from pathlib import Path
from evals import runner
case = json.loads(sys.argv[1])
out = runner.run_live(case, out_dir=Path(sys.argv[2]))
print(json.dumps({"fixture": str(out), "findings": [str(f) for f in runner.run_fixture(case, out).findings]}))
"""


def ttrpg2_case(case: dict, ttrpg2: Path = TTRPG2) -> dict | None:
    """ttrpg2's own case of the same id (its campaign files), playing our beats' player lines; None when it has no
    such case or a beat is an Ask the DM question, which ttrpg2 doesn't have."""
    path = ttrpg2 / "evals" / "cases" / f"{case['id']}.json"
    if not path.is_file() or any(b.get("ask") for b in case.get("beats") or []):
        return None
    theirs = json.loads(path.read_text(encoding="utf-8"))
    turns = theirs.get("turns") or []
    theirs["turns"] = [
        {**(turns[n] if n < len(turns) else {}), "player": beat["player"]} for n, beat in enumerate(case["beats"])
    ]
    return theirs


def run_ttrpg2(case: dict, out_dir: Path, ttrpg2: Path = TTRPG2) -> dict | None:
    """The case through ttrpg2's live mode (read only: its recording goes to `out_dir`): `{fixture, findings, beats}`,
    or None when ttrpg2 can't play it."""
    theirs = ttrpg2_case(case, ttrpg2)
    if theirs is None:
        return None
    python = ttrpg2 / ".venv" / "bin" / "python"
    out_dir.mkdir(parents=True, exist_ok=True)
    done = subprocess.run(
        [str(python if python.is_file() else sys.executable), "-c", _TTRPG2_SCRIPT, json.dumps(theirs), str(out_dir)],
        check=False,
        cwd=ttrpg2,
        capture_output=True,
        text=True,
    )
    if done.returncode != 0:
        raise RuntimeError(f"ttrpg2's live mode failed: {done.stderr[-2000:]}")
    found = json.loads(done.stdout.strip().splitlines()[-1])
    found["beats"] = ttrpg2_report(read_records(found["fixture"]))
    return found


def ttrpg2_report(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Per beat of a ttrpg2 recording: its total time and tool count (it doesn't record when the first text came)."""
    beats: dict[int, dict[str, Any]] = {}
    index = None
    for r in records:
        if r.get("type") == "eval_turn":
            index = r["index"]
            beats[index] = {"index": index, "first_text_s": None, "seconds": None, "tools": 0}
        elif r.get("type") == "assistant" and index is not None:
            content = (r.get("message") or {}).get("content") or []
            beats[index]["tools"] += sum(1 for b in content if isinstance(b, dict) and b.get("type") == "tool_use")
        elif r.get("type") == "eval_turn_end" and r.get("index") in beats:
            beats[r["index"]]["seconds"] = r.get("seconds")
    return [beats[i] for i in sorted(beats)]


def side_by_side(delve: list[dict[str, Any]], ttrpg2: list[dict[str, Any]] | None) -> str:
    """The per-beat timings of Delve and, when there is one, of ttrpg2, as a table."""
    lines = ["beat  Delve: first words   total   tools" + ("  |  ttrpg2: total   tools" if ttrpg2 else "")]
    theirs = {b["index"]: b for b in ttrpg2 or []}
    for b in delve:
        line = f"{b['index']:>4}  {_seconds(b['first_text_s']):>18}  {_seconds(b['seconds']):>6}  {b['tools']:>6}"
        if ttrpg2:
            t = theirs.get(b["index"], {})
            line += f"  |  {_seconds(t.get('seconds')):>13}  {t.get('tools', '–'):>6}"
        lines.append(line)
    return "\n".join(lines)
