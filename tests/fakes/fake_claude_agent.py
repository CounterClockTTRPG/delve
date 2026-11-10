"""A fake `claude` that plays the agents of a thorough conversion (thorough conversion Task 6). Never the real one.

It reads the prompt from stdin, knows its piece by the `PIECE: <id>` first line every brief starts with, writes the
piece's canned outputs for the tiny fixture book into its working directory (the job folder), and prints a stream-json
`result` with a cost, as `claude -p --output-format stream-json` does. The book (`BOOK`, built by the tests from
`HOUSE` and `SHIP`) has two parts whose rooms are both keyed 1, 2, 3, and one map page, page 3, the house's.

`FAKE_AGENT_CONFIG` names a JSON file:

- `plan`: `{piece: [step, …]}`, what the piece's sessions do in turn (`ok` once the list runs out):
  - `ok` writes the piece's outputs;
  - `empty` writes nothing;
  - `crash` exits 1 with an error on stderr;
  - `limit` meets the usage limit;
  - `bad-doubts` writes the outputs and a doubts file that isn't JSON;
  - `slow` waits `slow_seconds` (default `SLOW`) first, then does as `ok` (a session a pause stops halfway);
  - `stall` says one message, with its usage, then waits `slow_seconds` and ends with no `result` (a session that
    times out);
  - `partial` writes the piece's outputs, its doubts and `work/<piece>/trial.txt`, then stalls (a session Delve
    stops halfway, its files left behind, DEL-92);
- `maps`: false for a book whose sort finds no map (default true);
- `cost`: what each session costs (default `COST`);
- `resets`: when the usage limit's notice says it resets (default `RESETS`);
- `log`: a file each session appends `{"piece", "step", "cwd", "seen"}` to, `seen` the files in the folder as the
  session began, `{path: size}`, but the pages, scans and reference maps.

The steps used so far are kept in `<config>.used`, so a plan holds across sessions.

`install(bin_dir, config)` writes the config beside `bin_dir` and `bin_dir/claude`; put `bin_dir` first on `PATH`.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

COST = 0.5
"""What one agent session costs, by default."""
SLOW = 30.0
"""Seconds a `slow` session waits before it works."""
RESETS = "2026-10-23T09:00:00+00:00"
"""When the usage limit resets, by default, as the limit's notice says it."""

HOUSE = [
    "# The Haunted House",
    "## 1. Hall",
    "Dust lies thick on the floor of the hall.",
    "## 2. Kitchen",
    "A cold hearth, and a table laid for six.",
    "## 3. Cellar",
    "Stairs lead down into the dark of the cellar.",
]
SHIP = [
    "# The Sea Ghost",
    "## 1. Deck",
    "The deck is wet with spray.",
    "## 2. Cabin",
    "The captain's cabin, its charts in order.",
    "## 3. Hold",
    "Crates of contraband fill the hold.",
]
ORPHAN = "A rat scurries between the crates."
"""What the first cleaning piece finds of the ship's hold in its pages, for `sort-orphans` to place."""

MAP = """\
map "{title}" {{
  grid {{ cell 32 px  units feet 10  bounds 30 x 20 }}
  room_numbers off
}}

room "r1" {{ rect 1,1 6 x 5  label "1. {first}" }}
room "r2" {{ rect 7,1 8 x 5  label "2. {second}" }}
room "r3" {{ rect 7,6 8 x 6  label "3. {third}" }}

door between room.r1 and room.r2 {{ }}
door between room.r2 and room.r3 {{ }}
"""

_KEYED = re.compile(r"^## (\d+)\. (.*)$")


def markdown(lines: list[str]) -> str:
    """A part's text in the sorted form: `## 1. Hall {#1}`."""
    out = []
    for line in lines:
        keyed = _KEYED.match(line)
        out.append(f"{line} {{#{keyed[1]}}}" if keyed else line)
    return "\n\n".join(out) + "\n"


def traced(title: str, lines: list[str]) -> str:
    """The map the trace agent draws for a part: its three rooms, named `r1`, `r2`, `r3`."""
    names = [m[2] for line in lines if (m := _KEYED.match(line))]
    return MAP.format(title=title, first=names[0], second=names[1], third=names[2])


def parts(maps: bool) -> dict:
    house_maps = [{"name": "house", "title": "The Haunted House", "page": 3, "level": None}] if maps else []
    return {
        "parts": [
            {"id": "house", "title": "The Haunted House", "kind": "level", "audience": "gm", "pages": [1, 1],
             "key_pattern": "^\\d+$", "map_pages": [3] if maps else [], "maps": house_maps, "order": 1},
            {"id": "ship", "title": "The Sea Ghost", "kind": "level", "audience": "gm", "pages": [2, 2],
             "key_pattern": "^\\d+$", "map_pages": [], "maps": [], "order": 2},
        ],
        "pictures": [],
    }  # fmt: skip


# ----- the pieces -----


def _sort(here: Path, config: dict) -> None:
    drafts = sorted((here / "draft").glob("*.md"))
    (here / "original.md").write_text("".join(f"<<<TEXT {p.stem}>>>\n{p.read_text()}\n" for p in drafts))
    (here / "parts.json").write_text(json.dumps(parts(config.get("maps", True)), indent=2))
    for path in drafts:
        path.unlink()
    (here / "keys").mkdir(exist_ok=True)
    for id, lines in (("house", HOUSE), ("ship", SHIP)):
        (here / "draft" / f"{id}.md").write_text(markdown(lines))
        (here / "keys" / f"{id}.txt").write_text("1\n2\n3\n")


def _clean(here: Path, piece: str, prompt: str) -> list[dict]:
    known = {part["id"] for part in json.loads((here / "parts.json").read_text())["parts"]}
    mine = [id for id in re.findall(r"^- `([a-z0-9-]+)`:", prompt, re.MULTILINE) if id in known]
    (here / "clean").mkdir(exist_ok=True)
    for id in mine:
        (here / "clean" / f"{id}.md").write_text((here / "draft" / f"{id}.md").read_text())
    if piece == "clean-1":
        (here / "clean" / f"{piece}-orphans.md").write_text(f"=== goes to ship, after 3\n\n{ORPHAN}\n")
    return [{"part": mine[-1], "pages": [2], "kind": "checker-flag", "text": "Key 3 covers 80%: the layer runs on."}]


def _sort_orphans(here: Path) -> None:
    for path in sorted((here / "clean").glob("*-orphans.md")):
        target, _, text = path.read_text().partition("\n")
        id = re.match(r"=== goes to ([a-z0-9-]+),", target)[1]
        clean = here / "clean" / f"{id}.md"
        clean.write_text(clean.read_text().rstrip("\n") + "\n\n" + text.strip() + "\n")
        path.write_text("")  # as a real agent can: it may not delete (U1)


def _trace(here: Path, name: str) -> None:
    (here / "maps").mkdir(exist_ok=True)
    (here / "maps" / f"{name}.dmap").write_text(traced("The Haunted House", HOUSE))
    (here / "maps" / f"{name}.exits.json").write_text("[]\n")


def _describe(here: Path) -> list[dict]:
    files = sorted(p.name for p in (here / "art").glob("*.png"))
    described = [
        {"file": name, "id": f"ghost-{n}", "part": "house", "key": "1", "audience": "player",
         "description": "A ghost drifts through a dusty hall. Show it when the party enters room 1, the hall."}
        for n, name in enumerate(files, start=1)
    ]  # fmt: skip
    (here / "art" / "descriptions.json").write_text(json.dumps(described, indent=2))
    return [{"part": "house", "pages": [4], "kind": "picture-unsure", "text": "Probably room 1."}]


def _work(here: Path, piece: str, prompt: str, config: dict) -> list[dict]:
    """Write `piece`'s outputs; its doubts."""
    if piece == "sort":
        _sort(here, config)
    elif piece == "sort-orphans":
        _sort_orphans(here)
    elif piece.startswith("clean-"):
        return _clean(here, piece, prompt)
    elif piece.startswith("trace-"):
        _trace(here, piece.removeprefix("trace-"))
    elif piece == "describe":
        return _describe(here)
    return []


# ----- the session -----


def _out(obj: dict) -> None:
    print(json.dumps(obj), flush=True)


_UNSEEN = {"pages", "scan", "ref", "chunks", "pictures"}


def _seen(here: Path) -> dict[str, int]:
    return {
        str(path.relative_to(here)): path.stat().st_size
        for path in sorted(here.rglob("*"))
        if path.is_file() and path.relative_to(here).parts[0] not in _UNSEEN
    }


def _step(config_path: Path, config: dict, piece: str) -> str:
    used_path = config_path.with_name(config_path.name + ".used")
    used = json.loads(used_path.read_text()) if used_path.exists() else {}
    steps = (config.get("plan") or {}).get(piece) or []
    n = used.get(piece, 0)
    used[piece] = n + 1
    used_path.write_text(json.dumps(used))
    return steps[n] if n < len(steps) else "ok"


def main() -> int:
    prompt = sys.stdin.read()
    first = prompt.splitlines()[0] if prompt else ""
    piece = first.removeprefix("PIECE:").strip() if first.startswith("PIECE:") else "?"
    config_path = Path(os.environ["FAKE_AGENT_CONFIG"])
    config = json.loads(config_path.read_text())
    step = _step(config_path, config, piece)
    here = Path.cwd()
    if config.get("log"):
        entry = {"piece": piece, "step": step, "cwd": str(here), "seen": _seen(here)}
        with open(config["log"], "a", encoding="utf-8") as log:
            log.write(json.dumps(entry) + "\n")
    cost = config.get("cost", COST)
    session = f"fake-{piece}"
    _out({"type": "system", "subtype": "init", "session_id": session})
    if step == "crash":
        print("overloaded", file=sys.stderr)
        return 1
    if step == "limit":
        notice = f"You've hit your session limit · resets {config.get('resets', RESETS)}"
        _out({"type": "assistant", "message": {"content": [{"type": "text", "text": notice}]}})
        _out({"type": "result", "subtype": "success", "is_error": True, "result": notice, "session_id": session,
              "total_cost_usd": cost, "usage": {"input_tokens": 1, "output_tokens": 1}})  # fmt: skip
        return 1
    if step == "partial":
        _work(here, piece, prompt, config)
        (here / "doubts" / f"{piece}.json").write_text("[not finished")
        (here / "work" / piece).mkdir(parents=True, exist_ok=True)
        (here / "work" / piece / "trial.txt").write_text("a trial")
    if step in ("slow", "stall", "partial"):
        if step != "slow":
            usage = {"input_tokens": 100, "output_tokens": 50}
            _out({"type": "assistant", "message": {"id": "msg_1", "content": [], "usage": usage}})
        time.sleep(float(config.get("slow_seconds", SLOW)))
        if step != "slow":
            return 1
    if step in ("ok", "bad-doubts", "slow"):
        doubts = _work(here, piece, prompt, config)
        (here / "doubts").mkdir(exist_ok=True)
        text = "[not json" if step == "bad-doubts" else json.dumps(doubts)
        (here / "doubts" / f"{piece}.json").write_text(text)
    _out({"type": "assistant", "message": {"content": [{"type": "text", "text": f"Working on {piece}."}]}})
    _out({"type": "result", "subtype": "success", "is_error": False, "result": f"{piece}: done.",
          "session_id": session, "total_cost_usd": cost, "usage": {"input_tokens": 100, "output_tokens": 50}})  # fmt: skip
    return 0


def install(bin_dir: Path, config: dict) -> Path:
    """Write `bin_dir/claude`, which runs this fake with the current Python, and its config beside `bin_dir`; answers
    the config's path, for `FAKE_AGENT_CONFIG`."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    config_path = bin_dir.parent / "fake-agent.json"
    config_path.write_text(json.dumps(config))
    wrapper = bin_dir / "claude"
    wrapper.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{Path(__file__).resolve()}" "$@"\n', encoding="utf-8")
    wrapper.chmod(0o755)
    return config_path


if __name__ == "__main__":
    sys.exit(main())
