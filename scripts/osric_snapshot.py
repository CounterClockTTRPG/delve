"""Copy OSRIC 3.0's rules tables from the owner's OSRIC engine into `packs/osric/src/delve_osric/data/` (DEL-299).

    uv run python scripts/osric_snapshot.py ~/roleplaying/osric.tgz

The engine (MIT, the owner's) keeps OSRIC's tables as JSON in `osric/data/`, each citing its OSRIC section. The OSRIC
3.0 Third-Party License lets a product use the rules, the mechanics and the names, and print verbatim only monsters,
spells and magic items: so the copy keeps the tables, the spells and the magic items, and leaves out every passage of
the guides' own prose (the `PROSE` keys below, found by matching the data against the guides' text). A town
encounter's entry is such prose, so it keeps only its name and the number met (`urban`); the bestiary is
`scripts/osric_bestiary.py`'s.
"""

from __future__ import annotations

import json
import re
import sys
import tarfile
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "packs" / "osric" / "src" / "delve_osric" / "data"

TABLES = (
    "ability_scores",
    "ancestry",
    "class_features",
    "classes",
    "combat",
    "encounters",
    "encumbrance",
    "equipment",
    "loot_classes",
    "magic_items",
    "monster_saves",
    "monster_xp",
    "overland",
    "social",
    "spellcasting",
    "spells",
    "treasure_valuation",
    "turning",
)

PROSE: dict[str, tuple[tuple[str, ...], ...]] = {
    "turning": (("_legend",), ("_paladin_note",)),
    "monster_xp": (("_notes", "caveat"), ("_notes", "defeating_monsters")),
}
"""Keys whose text is the guides' own, verbatim: left out of the copy."""

FOOTNOTE = re.compile(r"[⁰¹²³⁴⁵⁶⁷⁸⁹]+")
"""The guide's footnote marks on item names ("Bracers of Armour⁵")."""
PAGE_HEADER = re.compile(r"\s*\bP?ART TWO:(?: HOW TO PLAY\b)?\s*")
"""The Player Guide's running page header, which the PDF's text left inside some spells."""


def clean(value: object) -> object:
    """Every string in `value` without the page header."""
    if isinstance(value, str):
        return FOOTNOTE.sub("", PAGE_HEADER.sub(" ", value)).strip()
    if isinstance(value, list):
        return [clean(item) for item in value]
    if isinstance(value, dict):
        return {key: clean(item) for key, item in value.items()}
    return value


URBAN_NUMBER = re.compile(r"^\s*(\d*d\d+(?:\s*[+-]\s*\d+)?)\b")


CHOICE = re.compile(r"\((\d+)(?:\s*[–-]\s*(\d+))?\)\s*(\d*d\d+(?:\s*[+-]\s*\d+)?|\d+)?\s*([^,(]+)")


def urban(entry: dict) -> dict:
    """A town encounter's entry as its name and, when the entry starts with one, the dice of how many are met: "Bandits.
    3d4 plus a Leader" is Bandits, 3d4. The rest is the guide's prose. An entry that is a choice ("Roll 1d10: (1–3) 2d4
    Ghasts, (4–10) 4d4 Ghouls") keeps its die and each choice's range, name and number."""
    text = entry.get("result", "")
    choice = re.match(r"\s*Roll\s+1?d(\d+)\s*:", text)
    if choice:
        out = {key: value for key, value in entry.items() if key != "result"}
        subrolls = [
            {"roll": [int(low), int(high or low)], "result": name.strip().rstrip("."), **({"number": n} if n else {})}
            for low, high, n, name in CHOICE.findall(text[choice.end() :])
        ]
        return {**out, "result": " or ".join(s["result"] for s in subrolls), "die": int(choice.group(1)), "subrolls": subrolls}
    name = re.split(r"[.:*(,]", text, maxsplit=1)[0].strip()
    rest = text[len(name) :].lstrip(".:*, ")
    number = URBAN_NUMBER.match(rest)
    out = {key: value for key, value in entry.items() if key != "result"}
    return {**out, "result": name, **({"number": number.group(1).replace(" ", "")} if number else {})}


def scrub(name: str, data: dict) -> dict:
    if name == "encounters":
        for when in ("daytime", "nighttime"):
            data["urban"][when] = [urban(entry) for entry in data["urban"][when]]
    for path in PROSE.get(name, ()):
        holder = data
        for key in path[:-1]:
            holder = holder[key]
        del holder[path[-1]]
    return data


def main(archive: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with tarfile.open(Path(archive).expanduser()) as tar:
        for name in TABLES:
            member = tar.extractfile(f"osric/data/{name}.json")
            if member is None:
                raise SystemExit(f"{archive} has no osric/data/{name}.json")
            data = clean(scrub(name, json.load(member)))
            (OUT / f"{name}.json").write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
            print(f"  {name}.json")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "~/roleplaying/osric.tgz")
