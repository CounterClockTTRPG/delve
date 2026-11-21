"""Make the SRD 3.5 pack's class features table, `data/features.json`, for the 16 base and NPC classes and the 15
prestige classes (DEL-389).

    python -I packs/srd35/scripts/extract_features.py DATA_DIR

DATA_DIR holds `classes.json`, `skills.json` and `feats.json` (packs/srd35/src/delve_srd35/data); `features.json`
is written beside it, the same bytes for the same input. Each entry of a class table's "Special" column becomes a row:
the regular ones ("Rage 2/day", "Sneak attack +3d6", "Damage reduction 1/—", "Bonus feat") by the patterns below, with
their value at each level the table gives. The irregular ones, and what the column doesn't carry (proficiencies, casting, the monk's AC bonus), are
structured rows in `srd35_extract/features_hand.json`:

- `rows`: whole rows, by class; the "Special" entries a row names in `special` are its own and not extracted.
- `extend`: fields laid over an extracted row of that id (its kind, condition, ability and the like); an `extend`
  for a row the script didn't make is an error.
- `requirements`: a prestige class's entry requirements the patterns below don't read, by class and the entry's words,
  each a list of `requires` (one row each); `{"special": …}` for one the engine can't check, which the DM confirms.

A prestige class (DEL-389 part 4) has three kinds of row more, by script:
- a `requirement` row per entry of its "Requirements" section (each skill and feat, the BAB, the alignment, race,
  spells and special), `requires` read by `_regular` or from the hand file, `section` and `name` the entry's;
- a `casting` row for "+1 level of existing … class" (its table's "Spells per Day" column or its "Special" column):
  `advances` the kind of class it raises ("arcane", "divine", "any", or both, `count` 2), `by_level` the levels (the
  hierophant's, whose levels raise only the caster level, is a hand row with `caster_level_only`);
- the dragon disciple's "Bonus Spells" column, a running count by level (`bonus-spells`).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from srd35_extract.common import slug

HAND = Path(__file__).resolve().parent / "srd35_extract" / "features_hand.json"
BASE = ("barbarian", "bard", "cleric", "druid", "fighter", "monk", "paladin", "ranger", "rogue", "sorcerer", "wizard",
        "adept", "aristocrat", "commoner", "expert", "warrior")  # fmt: skip
"""The base and NPC classes."""
PRESTIGE = ("arcane-archer", "arcane-trickster", "archmage", "assassin", "blackguard", "dragon-disciple", "duelist",
            "dwarven-defender", "eldritch-knight", "hierophant", "horizon-walker", "loremaster", "mystic-theurge",
            "shadowdancer", "thaumaturgist")  # fmt: skip
"""The prestige classes (DEL-389 part 4)."""
CLASSES = BASE + PRESTIGE
NONE = {"", "—"}
"""A "Special" cell or entry that names no feature (the rogue's 14th and 20th levels print a dash)."""

PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?P<name>.+?) (?P<value>\d+)/(?P<per>day|week)"), "uses"),
    (re.compile(r"(?P<name>.+?) \+(?P<value>\d+d\d+)"), "dice"),
    (re.compile(r"(?P<name>.+?) \+(?P<value>\d+)"), "note"),
    (re.compile(r"(?P<name>.+?) (?P<value>\d+)/(?:—|--)"), "reduction"),  # the dwarven defender's "3/--"
    (re.compile(r"(?P<name>.+?) (?:(?P<value>\d+) ft\.|(?P<any>any distance))"), "note"),
    (re.compile(r"(?P<name>.+?) \((?P<text>[^)]+)\)"), "note"),
)
"""An entry's name and value: uses a day (or a week), dice, a plus, damage reduction, a distance, a word in brackets.
An entry none of these fits is a plain name, counted when the table gives it at more than one level ("Bonus feat")."""


HEAD = ("id", "name", "level", "kind")
"""A row's first fields; the rest follow by name."""


def _tidy(row: dict[str, Any]) -> dict[str, Any]:
    """The row with its fields in a fixed order and its `by_level` by level, so the file reads down a class table."""
    out = {key: row[key] for key in HEAD} | {key: row[key] for key in sorted(row) if key not in HEAD}
    if "by_level" in out:
        out["by_level"] = dict(sorted(out["by_level"].items(), key=lambda item: int(item[0])))
    return out


def entries(cell: str) -> list[str]:
    """A "Special" cell's entries: split at the commas outside brackets ("Wild shape (6/day, elemental 2/day)" is
    one), without the cells and entries that name nothing."""
    out, depth, start = [], 0, 0
    for at, char in enumerate(cell):
        depth += {"(": 1, ")": -1}.get(char, 0)
        if char == "," and depth == 0:
            out.append(cell[start:at])
            start = at + 1
    out.append(cell[start:])
    return [entry.strip() for entry in out if entry.strip() not in NONE]


def _parse(entry: str) -> tuple[str, str, Any, dict[str, Any]]:
    """An entry's name, kind, value at its level (None for a plain name) and extra fields."""
    for pattern, kind in PATTERNS:
        if match := pattern.fullmatch(entry):
            found = match.groupdict()
            name = found["name"]
            if found.get("any"):
                return name, kind, "any", {}
            if found.get("text"):
                return name, kind, found["text"], {}
            value = found["value"]
            extra = {"per": "week"} if found.get("per") == "week" else {}
            return name, kind, value if kind == "dice" else int(value), extra
    return entry, "note", None, {}


def _extract(cls: dict[str, Any], owned: set[str]) -> dict[str, dict[str, Any]]:
    """The class's rows from its table's "Special" column, by id, leaving out the entries hand-written rows own and
    the "+1 level of existing … class" entries, the casting row's."""
    rows: dict[str, dict[str, Any]] = {}
    for level in cls["levels"]:
        for entry in entries(level["special"]):
            if entry in owned or ADVANCE.search(entry):
                continue
            name, kind, value, extra = _parse(entry)
            name = name[0].upper() + name[1:]
            row = rows.setdefault(slug(name), {"id": slug(name), "name": name, "level": level["level"], "kind": kind,
                                               "special": [], "by_level": {}, **extra})  # fmt: skip
            if row["kind"] != kind:
                raise ValueError(f"{cls['id']}: {entry!r} reads as {kind}, its row as {row['kind']}")
            if entry not in row["special"]:
                row["special"].append(entry)
            row["by_level"][str(level["level"])] = value
    for row in rows.values():
        values = list(row["by_level"].values())
        if values == [None]:
            del row["by_level"]
        elif all(v is None for v in values):
            row["by_level"] = {level: n for n, level in enumerate(row["by_level"], 1)}
        elif None in values:
            raise ValueError(f"{cls['id']}: {row['id']} has a value at some levels only")
    return rows


ADVANCE = re.compile(r"\+1 ?level of existing (?:(arcane|divine) )?(?:spellcasting )?class")
"""A prestige class's caster level, in its "Spells per Day" or "Special" column: of what kind of class (none: any)."""
_ORDINAL = re.compile(r"(\d+)(?:st|nd|rd|th)$")


def table(cls: dict[str, Any]) -> list[dict[str, str]]:
    """The class's level table in its class text (the first pipe table headed "Level | Base Attack Bonus"), a row
    each by the column heads: the columns the level rows don't keep ("Spells per Day", "Bonus Spells", "AC Bonus")."""
    lines = cls["text"].splitlines()
    start = next((at for at, line in enumerate(lines) if line.startswith("| Level | Base Attack Bonus")), None)
    if start is None:
        return []
    heads = [cell.strip() for cell in lines[start].strip("|").split("|")]
    out = []
    for line in lines[start + 2 :]:
        if not line.startswith("| "):
            break
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if _ORDINAL.match(cells[0]):
            out.append(dict(zip(heads, cells, strict=True)))
    return out


def _level(row: dict[str, str]) -> str:
    return _ORDINAL.match(row["Level"]).group(1)  # type: ignore[union-attr]


def _casting(cls: dict[str, Any]) -> dict[str, Any] | None:
    """A prestige class's "+1 level of existing … class" row from its table: at which levels, of what kind of class,
    and how many classes at once (the mystic theurge's arcane and divine); None for a class that adds none."""
    by_level, kinds, special, count = {}, set(), [], 0
    for row in table(cls):
        found = ADVANCE.findall(row.get("Spells per Day", ""))
        for entry in entries(row.get("Special", "")):
            if ADVANCE.search(entry):
                found += ADVANCE.findall(entry)
                special += [entry] * (entry not in special)
        if found:
            by_level[_level(row)] = True
            kinds |= {kind or "any" for kind in found}
            count = max(count, len(found))
    if not by_level:
        return None
    advances: str | list[str] = sorted(kinds) if len(kinds) > 1 else next(iter(kinds))
    return {"id": "casting", "name": "Spells per day", "level": int(next(iter(by_level))), "kind": "casting",
            "advances": advances, "count": count, "by_level": by_level, "special": special}  # fmt: skip


def _bonus_spells(cls: dict[str, Any]) -> dict[str, Any] | None:
    """The "Bonus Spells" column (the dragon disciple's), as the running count of bonus spells by the level it grows
    at: a bonus spell "can be added to any level of spells the disciple already has the ability to cast"."""
    by_level, total = {}, 0
    for row in table(cls):
        if (gained := int(row.get("Bonus Spells", "0") or 0)) > 0:
            total += gained
            by_level[_level(row)] = total
    if not by_level:
        return None
    return {"id": "bonus-spells", "name": "Bonus spells", "level": int(next(iter(by_level))), "kind": "bonus",
            "target": "bonus_spells", "by_level": by_level, "special": []}  # fmt: skip


SPLIT = ("Skills", "Feats")
"""The "Requirements" sections whose entries are a comma list ("Hide 5 ranks, Knowledge (religion) 2 ranks")."""


def requirement_entries(cls: dict[str, Any]) -> list[tuple[str, str]]:
    """A prestige class's entry requirements as (section, entry), by its "Requirements" section in its class text:
    each `###` part up to "Class Skills", a skill or feat list split at its commas, a trailing full stop dropped, and
    a leading "plus " (the loremaster's "plus Skill Focus (…)", which joins it to the entry before)."""
    text = cls["text"]
    if "### Requirements" not in text:
        return []
    part = text.split("### Requirements", 1)[1].split("### Class Skills", 1)[0]
    out = []
    for section, body in re.findall(r"(?m)^### (.+)\n\n((?:(?!### ).*\n?)+)", part):
        body = " ".join(body.split()).rstrip(".")
        for entry in entries(body) if section in SPLIT else [body]:
            out.append((section, entry.rstrip(".").removeprefix("plus ")))
    return out


def _regular(section: str, entry: str, skills: set[str], feats: set[str]) -> dict[str, Any] | None:
    """`requires` for an entry the patterns read: a BAB, "Hide 8 ranks", a feat with or without its choice, "Any
    nonlawful", "Ability to cast 1st-level arcane spells", "Sneak attack +2d6"; None for one they don't."""
    if section == "Base Attack Bonus" and (m := re.fullmatch(r"\+(\d+)", entry)):
        return {"bab": int(m.group(1))}
    if section == "Skills" and (m := re.fullmatch(r"(.+?) (\d+) ranks?", entry)):
        skill = slug(m.group(1))
        return {"skill": skill, "ranks": int(m.group(2))} if slug(m.group(1).split(" (")[0]) in skills else None
    if section == "Feats" and (m := re.fullmatch(r"([^()]+?)(?: \(([^()]+)\))?", entry)):
        feat, choice = slug(m.group(1)), m.group(2)
        if feat not in feats or (choice and " or " in choice):
            return None
        return {"feat": feat, "choice": slug(choice)} if choice else {"feat": feat}
    if section == "Alignment" and (m := re.fullmatch(r"Any (non)?(\w+)", entry)):
        return {"alignment": {"not": [m.group(2)]} if m.group(1) else [m.group(2)]}
    if section in ("Spells", "Spellcasting") and (
        m := re.fullmatch(r"(?:Ability to|Able to) cast (\d)(?:st|nd|rd|th)-level (arcane|divine) spells", entry)
    ):
        return {"cast": {"level": int(m.group(1)), "kind": m.group(2)}}
    if section == "Special" and (m := re.fullmatch(r"Sneak attack \+(\d+d\d+)", entry)):
        return {"sneak": m.group(1)}
    return None


def _requirement_id(requires: dict[str, Any]) -> str:
    """A requirement row's id by what it asks: "req-bab", "req-skill-hide", "req-feat-weapon-focus-longsword"."""
    kind, value = next(iter(requires.items()))
    if kind == "skill":
        return f"req-skill-{value}"
    if kind == "feat":
        return "-".join(["req-feat", value, *([requires["choice"]] if "choice" in requires else [])])
    if kind == "cast":
        return f"req-cast-{value['kind']}-{value['level']}"
    if kind in ("spell", "proficient"):
        return f"req-{kind}-{value}"
    return f"req-{kind.replace('_', '-')}"


def _requirements(cls: dict[str, Any], hand: dict[str, list[dict[str, Any]]], skills: set[str],
                  feats: set[str]) -> list[dict[str, Any]]:  # fmt: skip
    """The class's requirement rows: an entry the hand file has (`requirements`) by its rows, else by `_regular`; an
    entry neither reads, or a hand entry the section lacks, is an error."""
    rows: list[dict[str, Any]] = []
    found = requirement_entries(cls)
    if unknown := set(hand) - {entry for _, entry in found}:
        raise ValueError(f"{cls['id']}: hand requirements for entries it hasn't: {sorted(unknown)}")
    for section, entry in found:
        asked = hand.get(entry) or [r for r in [_regular(section, entry, skills, feats)] if r]
        if not asked:
            raise ValueError(f"{cls['id']}: no requirement read from {section}: {entry!r}")
        for requires in asked:
            rid = _requirement_id(requires)
            taken = {row["id"] for row in rows}
            rid = next(f"{rid}-{n}" for n in range(2, 99) if f"{rid}-{n}" not in taken) if rid in taken else rid
            rows.append({"id": rid, "name": entry, "level": 1, "kind": "requirement", "requires": requires,
                         "section": section, "special": []})  # fmt: skip
    return rows


def features(classes: list[dict[str, Any]], hand: dict[str, Any], skills: set[str] = frozenset(),
             feats: set[str] = frozenset()) -> dict[str, list[dict[str, Any]]]:  # fmt: skip
    """The table: each of the 31 classes' rows, extracted and hand-written, by level and id; a prestige class's
    requirements read with the pack's skill and feat ids."""
    by_id = {cls["id"]: cls for cls in classes}
    out: dict[str, list[dict[str, Any]]] = {}
    for cid in CLASSES:
        written = [{"special": [], **row} for row in hand["rows"].get(cid, [])]
        if cid in PRESTIGE:
            written += [row for row in (_casting(by_id[cid]), _bonus_spells(by_id[cid])) if row]
            written += _requirements(by_id[cid], hand["requirements"].get(cid, {}), skills, feats)
        rows = _extract(by_id[cid], {entry for row in written for entry in row["special"]})
        for rid, fields in hand["extend"].get(cid, {}).items():
            if rid not in rows:
                raise ValueError(f"{cid}: no extracted row {rid!r} to extend")
            rows[rid].update(fields)
        for row in written:
            if row["id"] in rows:
                raise ValueError(f"{cid}: {row['id']!r} is both extracted and hand-written")
            rows[row["id"]] = row
        out[cid] = [_tidy(row) for row in sorted(rows.values(), key=lambda row: (row["level"], row["id"]))]
    return out


def unaccounted(classes: list[dict[str, Any]], table: dict[str, list[dict[str, Any]]], ids: list[str]) -> list[str]:
    """The "Special" entries of these classes' tables that no row of the table names ("monk 3: Still mind")."""
    missing = []
    for cls in classes:
        if cls["id"] not in ids:
            continue
        named = {entry for row in table.get(cls["id"], []) for entry in row.get("special", [])}
        missing += [f"{cls['id']} {lvl['level']}: {e}" for lvl in cls["levels"] for e in entries(lvl["special"])
                    if e not in named]  # fmt: skip
    return missing


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    folder = Path(argv[1])
    classes = json.loads((folder / "classes.json").read_text(encoding="utf-8"))
    hand = json.loads(HAND.read_text(encoding="utf-8"))
    ids = {kind: {row["id"] for row in json.loads((folder / f"{kind}.json").read_text(encoding="utf-8"))}
           for kind in ("skills", "feats")}  # fmt: skip
    table = features(classes, hand, ids["skills"], ids["feats"])
    if missing := unaccounted(classes, table, list(CLASSES)):
        print("extract_features: no row for " + "; ".join(missing), file=sys.stderr)
        return 1
    # Not `write_json`: its sorted keys would put level 10 before level 2.
    text = json.dumps(table, ensure_ascii=False, indent=1)
    (folder / "features.json").write_text(text + "\n", encoding="utf-8")
    print(f"features: {sum(len(rows) for rows in table.values())} rows for {len(table)} classes")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
