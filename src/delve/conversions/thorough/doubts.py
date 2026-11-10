"""A thorough conversion's doubts (thorough conversion Task 6): every guess the run made, for the organiser.

Each piece's agent writes `doubts/<piece>.json` (`prompts/thorough/common.md`), and Delve writes its own beside them
(a skipped piece, a text kept as its draft, a sketched map, the joiner's guessed landings). A doubt is
`{"part", "pages", "kind", "text"}`; `gather` reads them all, by stage, then by name, each with the `piece` its file
is named after. A file that isn't a list of doubts is one doubt itself (`UNREADABLE`): a doubt is never lost
silently. A kind the briefs don't name is `other`."""

from __future__ import annotations

import json
from typing import Any

from delve.conversions.thorough.workspace import DOUBTS, Workspace

KINDS = (
    "missing-text",
    "missing-room",
    "checker-flag",
    "left-out",
    "guessed-landing",
    "picture-unsure",
    "crop-refused",
    "sketched-map",
    "other",
)
"""The kinds of doubt: the agents' (`common.md`), and Delve's `sketched-map`, for a map sketched from a room key, and
`crop-refused`, for a picture attached whole because the cut `describe` proposed can't be made."""
UNREADABLE = "The agent's doubts file was unreadable."
ORDER = ("sort", "clean", "sort-orphans", "trace", "sketch", "join", "describe")
"""The pieces' order in the list: the stages'."""


def gather(ws: Workspace) -> list[dict[str, Any]]:
    """Every doubt in `doubts/`, `{"piece", "part", "pages", "kind", "text"}`, in the stages' order."""
    found = []
    for path in sorted((ws.root / DOUBTS).glob("*.json"), key=lambda p: (_rank(_piece(p.stem)), p.stem)):
        piece = _piece(path.stem)
        try:
            listed = json.loads(path.read_text("utf-8"))
        except (OSError, UnicodeDecodeError, ValueError):
            listed = None
        if not isinstance(listed, list) or not all(isinstance(entry, dict) for entry in listed):
            found.append({"piece": piece, "part": piece, "pages": [], "kind": "other", "text": UNREADABLE})
            continue
        found += [_doubt(piece, entry) for entry in listed]
    return found


def _piece(stem: str) -> str:
    """The piece a doubts file is named after: `clean-1.skipped` is `clean-1`'s."""
    return stem.split(".", 1)[0]


def _rank(piece: str) -> int:
    if piece in ORDER:
        return ORDER.index(piece)
    return next((n for n, name in enumerate(ORDER) if piece.startswith(f"{name}-")), len(ORDER))


def _doubt(piece: str, entry: dict[str, Any]) -> dict[str, Any]:
    pages = entry.get("pages")
    kind = entry.get("kind")
    return {
        "piece": piece,
        "part": str(entry.get("part") or piece),
        "pages": [p for p in pages if isinstance(p, int) and not isinstance(p, bool)]
        if isinstance(pages, list)
        else [],
        "kind": kind if kind in KINDS else "other",
        "text": str(entry.get("text") or ""),
    }
