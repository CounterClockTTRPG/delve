"""The fake answers of a fix-it job (table voice and fixes Task F2.4), for `web/e2e/u-fixit.spec.ts`: the fake
play server's `claude` asks `fixit_answer` first, by the side call's prompt.

The answer adds the exit the comment names to the prompt's first map: an `exit` in the middle of the room the comment
calls "room <key>" (`r<key>` on the map), up to the place it names after "to the". It is one `put_map` operation, as
`delve.conversions.fixit` asks for, so the review shows the map before and after and nothing else."""

from __future__ import annotations

import json
import re

from delve.conversions.fixit import FIXIT_PROMPT

MAP = re.compile(
    r"^### Map `(?P<name>[^`]+)` \(map[^)]*\)\n\n<map>\n(?P<source>.*?)\n</map>$", re.MULTILINE | re.DOTALL
)
COMMENT = re.compile(r"^1\. (?P<text>.+)$", re.MULTILINE)
ROOM = re.compile(r"\broom (?P<key>\w+)", re.IGNORECASE)
PLACE = re.compile(r"\bto the (?P<place>[\w ]+?)(?: is| isn't|,|\.|$)", re.IGNORECASE)
SUMMARY = "Added the exit from room {key} to the {place}."


def _middle(source: str, node: str) -> tuple[float, float]:
    """The middle of the room `node`'s rect, or the map's first cell."""
    rect = re.search(rf'room "{re.escape(node)}" \{{ rect (\d+),(\d+) (\d+) x (\d+)', source)
    if rect is None:
        return 1.0, 1.0
    x, y, w, h = (int(v) for v in rect.groups())
    return x + w / 2, y + h / 2


def fixit_answer(prompt: str) -> str | None:
    """The fix-it job's answer to `prompt`, or None for a prompt that isn't one of its."""
    if not prompt.startswith(FIXIT_PROMPT):
        return None
    found, comment = MAP.search(prompt), COMMENT.search(prompt)
    if found is None or comment is None:
        return json.dumps({"summary": "Nothing to change.", "operations": []})
    text = comment.group("text")
    room = ROOM.search(text)
    place = PLACE.search(text)
    key = room.group("key") if room else "1"
    where = place.group("place").strip() if place else "surface"
    x, y = _middle(found.group("source"), f"r{key}")
    exit_line = f'exit at {x:g},{y:g} {{ to "{where}" at 1,1  label "Up to the {where}" }}'
    source = found.group("source").rstrip("\n") + f"\n\n{exit_line}\n"
    operation = {"op": "put_map", "name": found.group("name"), "source": source}
    return json.dumps({"summary": SUMMARY.format(key=key, place=where), "operations": [operation]})
