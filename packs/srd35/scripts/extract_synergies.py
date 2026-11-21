"""Make the SRD 3.5 pack's table of skill synergies, `data/synergies.json` (DEL-456).

    python -I packs/srd35/scripts/extract_synergies.py DATA_DIR

DATA_DIR holds `skills.json` (packs/srd35/src/delve_srd35/data); `synergies.json` is written beside it, the same bytes
for the same input. Each sentence of a skill's "Synergy" section of the form "If you have 5 (or more) ranks in <skill>,
you get a +2 bonus on <checks>." is a row per skill named on each side ("Bluff, Knowledge (nobility and royalty), or
Sense Motive" is three rows; "Balance and Jump checks" and "Ride checks and wild empathy checks" two):

- `from`: the skill whose ranks give it, by id ("knowledge-arcana"; "craft" for "any Craft skill");
- `to`: the skill the bonus is on, by id, or a check that is no skill ("turning", "bardic-knowledge", "wild-empathy");
- `ranks` and `bonus`: the 5 ranks and the +2;
- `condition`: the words after "checks" when the bonus is on some checks only ("when escaping from rope bonds"), else
  null: the engine adds an unconditional row to the skill's total and lists a conditional one.

The SRD gives most synergies twice, in each skill's section: a row is kept once, by its two skills, with the words of
the section of the skill the bonus is on (else of the first section that gives it). A sentence that names no skill the
bonus is on ("a +2 bonus on checks made to bind someone", in Use Rope's section) is on its section's skill. A sentence
the pattern doesn't read, or a skill it doesn't know, is an error.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

CHECKS = {"turning": "turning", "bardic knowledge": "bardic-knowledge", "wild empathy": "wild-empathy"}
"""The checks a synergy is on that are no skill: Turn Undead's turning check, the bard's bardic knowledge, the druid's
and ranger's wild empathy."""
_SECTION = re.compile(r"### Synergy\s*\n(.*?)(?=\n#{2,4} |\Z)", re.DOTALL)
_SENTENCE = re.compile(r"If you have 5 (?:or more )?ranks in (?P<from>.+?), you (?:get|gain) a \+(?P<bonus>\d+) bonus "
                       r"(?:on|to) (?P<on>.+?)\.(?:\s|$)")  # fmt: skip
_ON = re.compile(r"^(?P<to>.*?)\s*checks\b\s*(?P<condition>.*)$")
_BOTH = re.compile(r" checks and (?=[^,]*? checks\b)")
_LIST = re.compile(r",\s*(?:and\s+|or\s+)?|\s+(?:and|or)\s+")


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower().replace("'", "")).strip("-")


def _names(text: str) -> list[str]:
    """The names of a list ("Bluff, Knowledge (nobility and royalty), or Sense Motive"), split outside brackets."""
    out, depth, start = [], 0, 0
    for i, ch in enumerate(text):
        depth += (ch == "(") - (ch == ")")
        if depth == 0 and (found := _LIST.match(text, i)) and found.start() == i:
            out.append(text[start:i])
            start = found.end()
    out.append(text[start:])
    return [name.strip() for name in out if name.strip()]


def _skill(name: str, known: set[str]) -> str | None:
    words = name.lower().removeprefix("any ").removeprefix("a ")
    words = re.sub(r"\s+skill$", "", words)
    if words in CHECKS:
        return CHECKS[words]
    found = slug(words)
    if found in known or found.split("-")[0] in {"knowledge", "craft"} and found.split("-")[0] in known:
        return found
    return None


def synergies(skills: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    """The rows, by `from` and `to` in the order the skills first give them, and the problems."""
    known = {row["id"] for row in skills}
    rows: dict[tuple[str, str], dict[str, Any]] = {}
    problems: list[str] = []
    for skill in skills:
        section = _SECTION.search(skill.get("text") or "")
        if section is None:
            continue
        paragraphs = [p.strip() for p in section.group(1).split("\n\n") if p.strip().startswith("If you have 5")]
        for paragraph in paragraphs:
            found = _SENTENCE.match(paragraph)
            if found is None:
                problems.append(f"{skill['id']}: unread synergy '{paragraph[:80]}'")
                continue
            sources = [_skill(n, known) for n in _names(found.group("from"))]
            on_text = _BOTH.sub(" and ", found.group("on"))  # "Ride checks and wild empathy checks"
            for part in re.split(r",\s*as well as on\s+", on_text):
                on = _ON.match(part)
                if on is None or None in sources:
                    problems.append(f"{skill['id']}: unread synergy '{paragraph[:80]}'")
                    continue
                targets = [_skill(n, known) for n in _names(on.group("to"))] or [skill["id"]]
                if None in targets:
                    problems.append(f"{skill['id']}: unknown skill in '{on.group('to')}'")
                    continue
                condition = on.group("condition").strip() or None
                for source in sources:
                    for target in targets:
                        row = {"from": source, "to": target, "ranks": 5, "bonus": int(found.group("bonus")),
                               "condition": condition}  # fmt: skip
                        key = (source, target)
                        if key in rows and (rows[key]["condition"] is None) != (condition is None):
                            problems.append(f"{source} → {target}: conditional in one section, not in another")
                        if key not in rows or (target == skill["id"] and rows[key]["_in"] != target):
                            rows[key] = {**row, "_in": skill["id"]}
    return [{k: v for k, v in row.items() if k != "_in"} for row in rows.values()], problems


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    folder = Path(argv[1])
    skills = json.loads((folder / "skills.json").read_text(encoding="utf-8"))
    table, problems = synergies(skills)
    if problems:
        print("extract_synergies: " + "; ".join(problems), file=sys.stderr)
        return 1
    text = json.dumps(table, ensure_ascii=False, indent=1)
    (folder / "synergies.json").write_text(text + "\n", encoding="utf-8")
    print(f"synergies: {len(table)} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
