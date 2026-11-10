"""A thorough conversion's job folder (thorough conversion Task 4): `<data dir>/conversions/<conversion id>/`, never
/tmp, and `state.json` in it, Delve's record of every finished stage and piece, so a resume starts at the first
unfinished piece and never redoes or pays twice for finished work.

The folder holds what the agents work on and with: the book as `book.pdf` and the reference material the briefs cite
in `ref/` (the map language's docs and three finished maps). The `qa` wrapper, `delve qa` and the only command an
agent's Bash may run, is `<data dir>/bin/qa` (`qa_path`), outside every job folder, so no agent can rewrite it into
another command (review finding 1); each agent session's runner installs it for the Delve that runs it
(`install_qa`). `state.json`:

    {"stages": {stage: "done"},
     "pieces": {piece: {"status": "done" | "skipped" | "failed" | "paused", "attempts": n, "cost_usd": x,
                        "outputs": [...], "error": "...", "tokens": n}},
     "paused": {"reason": "...", "resets_at": "..." | null} | null,
     "options": {"mode": "ready" | "draft", "title": "..."},
     "stopped": [{"piece": "...", "tokens": n | null}],
     "running": ["<piece>", ...]}

A piece's `tokens` are those of its sessions that ended, beside their cost; `stopped` lists the sessions that were
stopped before their end (timed out, cancelled), which sent no cost, with the tokens their stream showed (review
finding 7). `running` lists the pieces whose session began and ended no attempt: one Delve stopped (or a pause
cancelled) halfway, or one that met the usage limit. Such a piece starts from a clean slate when it runs again: the
files its stopped session left are cleared first (`pieces.run_piece`, DEL-92).

It is written whole to a file beside it and renamed over it, so a stop mid-write leaves the last state. A piece whose
attempt was stopped halfway isn't in it as done, and is started over."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

import delve

PieceStatus = Literal["done", "skipped", "failed", "paused"]
"""A piece is `done` or `skipped` once finished (`skipped` after its last failed attempt), `failed` while it has
attempts left, and `paused` while it has only met the usage limit, no attempt used (DEL-91)."""
FINISHED: tuple[PieceStatus, ...] = ("done", "skipped")

STATE = "state.json"
BOOK = "book.pdf"
QA = "qa"
BIN = "bin"
"""`<data dir>/bin/`, where the `qa` wrapper is."""
REF = "ref"
DOUBTS = "doubts"
WORK = "work"
"""`work/<piece>/`, a piece's own scratch folder (`prompts/thorough/common.md`)."""

# What the stages write (thorough conversion Task 6), as the briefs name it (`prompts/thorough/common.md`).
PAGES = "pages"
"""`p-NNN.png` at 150 dpi and `ocr-NNN.txt`, every page (reading)."""
SCAN = "scan"
"""`p-NNN.png` at 200 dpi, the pages with pictures (reading)."""
PICTURES = "pictures"
"""The pictures the reading found, `p-NNN-K.png`, which `book.json` lists (reading)."""
BOOK_JSON = "book.json"
"""The book as read and classified, its pictures as files in `pictures/`: Delve's, so a resume needn't read again."""
CLASSES = "classes.json"
"""What the classifier took each page for, for the agents (classifying)."""
DRAFT = "draft"
"""The converter's drafts, `NN-<text id>.md` in the book's order (drafting); after the sort, `<part id>.md`."""
DRAFTED = "drafted"
"""Delve's copy of the drafts as the drafting wrote them; each attempt at the sort starts from it."""
CLEANED = "cleaned"
"""Delve's copy of `clean/` as the cleaning pieces left it, before `sort-orphans` edits their files: a restarted
`sort-orphans` starts from it (DEL-92)."""
ORIGINAL = "original.md"
PARTS = "parts.json"
"""The book's parts and maps (the sort): `{"parts": [...], "pictures": [page…]}`."""
KEYS = "keys"
CLEAN = "clean"
"""`<part id>.md`, the cleaned texts (cleaning)."""
MAPS = "maps"
"""`<name>.dmap` and `<name>.exits.json`, traced or sketched (tracing)."""
SKETCHES = "sketches.json"
"""The maps sketched from a part's room key, `{name: {"part", "reason"}}` (tracing)."""
JOINED = "joined"
"""The maps with their exits joined, and `join-doubts.json` (joining)."""
ART = "art"
"""The pictures offered to the describing agent, `pNNN-K.png`, and its `descriptions.json` (describing)."""
ENTITIES = "entities.json"
"""`{"entities", "renamed", "origins"}` from the cleaned texts (entities)."""
WARNINGS = "warnings.json"
"""The warnings of the code stages, `{stage: [warning…]}`."""
RECORDS = (STATE, f"{STATE}.partial", BOOK, BOOK_JSON, WARNINGS, f"{DRAFTED}/**", f"{CLEANED}/**")
"""Delve's own files in the folder, as `agent_settings`' `records`: the agents may read them, never change them, so
a resume never meets a state an agent broke (review finding 8)."""
DELVE_STOPPED = "Delve stopped"
"""The pause's reason for a job left running by a Delve that stopped; Delve resumes these when it starts."""
PAUSED_BY_ORGANISER = "paused by the organiser"
"""The pause's reason for a job the organiser paused by hand (`thorough.pause`); it waits for a resume by hand."""

_REPOSITORY = Path(__file__).resolve().parents[4]
_PACKAGED_DOCS = Path(delve.__file__).resolve().parent / "docs" / "maps"
MAP_DOCS = _PACKAGED_DOCS if _PACKAGED_DOCS.is_dir() else _REPOSITORY / "docs" / "maps"
"""The map language's docs, `dsl*.md`: in the wheel at `delve/docs/maps`, in the repository under `docs/`."""
REFERENCE_MAPS = Path(__file__).resolve().parent / "ref"
"""Three finished maps the tracing brief points at: a cave system, a built dungeon and a building."""


def qa_wrapper(python: str = sys.executable) -> str:
    """The `qa` script: `delve qa` with this Python, isolated (`-I`), so a `delve/` an agent writes into the folder,
    its working directory, is never imported in place of Delve's."""
    return f'#!/bin/sh\nexec {shlex.quote(python)} -I -m delve qa "$@"\n'


def qa_path(data_dir: Path) -> Path:
    """Where the `qa` wrapper is: `<data dir>/bin/qa`, beside the job folders' `conversions/`, never in one."""
    return data_dir / BIN / QA


def install_qa(data_dir: Path) -> Path:
    """Write the `qa` wrapper for this Delve's Python (mode 0755), whole and renamed over the old one, unless it is
    already that. Answers its path."""
    path = qa_path(data_dir)
    wrapper = qa_wrapper()
    if path.is_file() and path.read_text("utf-8") == wrapper and os.access(path, os.X_OK):
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(f"{QA}.{os.getpid()}.partial")
    partial.write_text(wrapper, "utf-8")
    partial.chmod(0o755)
    os.replace(partial, path)
    return path


@dataclass
class Piece:
    status: PieceStatus
    attempts: int = 0
    cost_usd: float | None = None
    outputs: list[str] = field(default_factory=list)
    error: str | None = None
    tokens: int | None = None


@dataclass
class Pause:
    reason: str
    resets_at: str | None = None


@dataclass
class State:
    stages: dict[str, str] = field(default_factory=dict)
    pieces: dict[str, Piece] = field(default_factory=dict)
    paused: Pause | None = None
    options: dict[str, Any] = field(default_factory=dict)
    stopped: list[dict[str, Any]] = field(default_factory=list)
    running: list[str] = field(default_factory=list)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> State:
        paused = data.get("paused")
        return cls(
            stages=dict(data.get("stages") or {}),
            pieces={piece: Piece(**value) for piece, value in (data.get("pieces") or {}).items()},
            paused=Pause(**paused) if paused else None,
            options=dict(data.get("options") or {}),
            stopped=list(data.get("stopped") or []),
            running=list(data.get("running") or []),
        )


class Workspace:
    """The job folder at `root`. Every change to the state reads it, changes it and writes it back at once."""

    def __init__(self, root: Path) -> None:
        self.root = root

    @classmethod
    def create(
        cls, conversion_id: str, data_dir: Path, pdf: Path, *, options: dict[str, Any] | None = None
    ) -> Workspace:
        """The folder of the job `conversion_id`, made afresh: the PDF copied in as `book.pdf`, the map docs and
        reference maps in `ref/`, and a state with `options` and nothing done; and the `qa` wrapper installed."""
        workspace = cls(data_dir / "conversions" / conversion_id)
        root = workspace.root
        root.mkdir(parents=True)
        shutil.copyfile(pdf, root / BOOK)
        install_qa(data_dir)
        (root / REF).mkdir()
        for source in [*sorted(MAP_DOCS.glob("dsl*.md")), *sorted(REFERENCE_MAPS.glob("*.dmap"))]:
            shutil.copyfile(source, root / REF / source.name)
        (root / DOUBTS).mkdir()
        workspace._write(State(options=dict(options or {})))
        return workspace

    def exists(self) -> bool:
        return (self.root / STATE).is_file()

    def state(self) -> State:
        return State.from_json(json.loads((self.root / STATE).read_text("utf-8")))

    def _write(self, state: State) -> None:
        path = self.root / STATE
        partial = path.with_name(f"{STATE}.partial")
        partial.write_text(json.dumps(asdict(state), indent=2, ensure_ascii=False), "utf-8")
        os.replace(partial, path)

    def _piece(self, state: State, piece: str) -> Piece:
        if piece in state.running:  # an attempt ended: the piece's files are no stopped session's (DEL-92)
            state.running.remove(piece)
        return state.pieces.setdefault(piece, Piece("failed"))

    def began(self, piece: str) -> None:
        """A session of `piece` begins: until an attempt ends (`done`, `failed`, `skipped`), the piece is `running`,
        and a run that finds it so knows its last session was stopped halfway (DEL-92)."""
        state = self.state()
        if piece not in state.running:
            state.running.append(piece)
            self._write(state)

    def was_stopped(self, piece: str) -> bool:
        """Whether `piece`'s last session began and ended no attempt (stopped halfway, or at the usage limit)."""
        return piece in self.state().running

    def done(self, piece: str, cost: float | None, outputs: list[str], *, tokens: int | None = None) -> None:
        """`piece`'s last attempt succeeded, costing `cost` for `tokens`, with `outputs` (paths in the folder)."""
        state = self.state()
        record = self._piece(state, piece)
        record.status, record.attempts, record.outputs, record.error = "done", record.attempts + 1, outputs, None
        record.cost_usd, record.tokens = _add(record.cost_usd, cost), _add(record.tokens, tokens)
        self._write(state)

    def failed(self, piece: str, error: str, *, cost: float | None = None, tokens: int | None = None) -> None:
        """An attempt at `piece` ended without its outputs: one attempt more, and its cost."""
        state = self.state()
        record = self._piece(state, piece)
        record.status, record.attempts, record.error = "failed", record.attempts + 1, error
        record.cost_usd, record.tokens = _add(record.cost_usd, cost), _add(record.tokens, tokens)
        self._write(state)

    def spent(self, piece: str, cost: float | None, *, tokens: int | None = None) -> None:
        """An attempt at `piece` cost `cost` and was stopped by the usage limit: it uses no attempt, and a piece with
        none used yet is `paused`, not `failed`. It stays `running`: it ended halfway, and starts over clean."""
        state = self.state()
        record = state.pieces.setdefault(piece, Piece("failed"))
        if record.attempts == 0:
            record.status = "paused"
        record.cost_usd, record.tokens = _add(record.cost_usd, cost), _add(record.tokens, tokens)
        self._write(state)

    def stopped(self, piece: str, tokens: int | None) -> None:
        """A session of `piece` was stopped before its end, so its cost is unknown; its stream showed `tokens`."""
        state = self.state()
        state.stopped.append({"piece": piece, "tokens": tokens})
        self._write(state)

    def skipped(self, piece: str, error: str) -> None:
        """`piece` has no attempts left: it is finished as skipped, with its last error."""
        state = self.state()
        record = self._piece(state, piece)
        record.status, record.error = "skipped", error
        self._write(state)

    def piece(self, piece: str) -> Piece | None:
        return self.state().pieces.get(piece)

    def is_done(self, piece: str) -> bool:
        """Whether `piece` is finished, done or skipped: it is never run again."""
        record = self.piece(piece)
        return record is not None and record.status in FINISHED

    def stage_done(self, stage: str) -> None:
        state = self.state()
        state.stages[stage] = "done"
        self._write(state)

    def is_stage_done(self, stage: str) -> bool:
        return self.state().stages.get(stage) == "done"

    def pause(self, reason: str, resets_at: str | None = None) -> None:
        state = self.state()
        state.paused = Pause(reason, resets_at)
        self._write(state)

    def resumed(self) -> None:
        """The job runs again: no longer paused, and the `qa` wrapper runs this Delve's Python, which may not be the
        one that made the folder (another install, an upgraded venv). A folder made before the wrapper moved out of it
        loses its own `./qa`."""
        state = self.state()
        state.paused = None
        self._write(state)
        (self.root / QA).unlink(missing_ok=True)
        install_qa(self.root.parent.parent)

    def doubt(self, name: str, doubts: list[dict[str, Any]]) -> None:
        """Write `doubts/<name>.json`, as the agents write theirs."""
        self.write_json(f"{DOUBTS}/{name}.json", doubts)

    def read_json(self, name: str, default: Any = None) -> Any:
        """The JSON file `name` (a path in the folder), or `default` when there is none."""
        path = self.root / name
        return json.loads(path.read_text("utf-8")) if path.is_file() else default

    def write_json(self, name: str, value: Any) -> None:
        """Write the JSON file `name` whole or not at all, as the state is: a stop mid-write (Delve stopping, a full
        disk) leaves the file as it was, never half a file the resume can't read."""
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        partial = path.with_name(f"{path.name}.partial")
        partial.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", "utf-8")
        os.replace(partial, path)

    def parts(self) -> list[dict[str, Any]]:
        """The book's parts from `parts.json` (the sort's), in their `order`; a bare list is the parts too."""
        data = self.read_json(PARTS, [])
        listed = data.get("parts", []) if isinstance(data, dict) else data
        return sorted(listed, key=lambda part: part.get("order") or 0)

    def pictures(self) -> list[int]:
        """The pages `parts.json` lists as pictures (world, region and overland maps), attached whole: page numbers,
        or objects with their `page` as the sort sometimes writes them, like its maps."""
        data = self.read_json(PARTS, {})
        listed = data.get("pictures") or [] if isinstance(data, dict) else []
        pages = (entry.get("page") if isinstance(entry, dict) else entry for entry in listed)
        return [page for page in pages if isinstance(page, int) and not isinstance(page, bool)]

    def remove(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)


def _add[N: (int, float)](total: N | None, cost: N | None) -> N | None:
    if cost is None:
        return total
    return (total or 0) + cost
