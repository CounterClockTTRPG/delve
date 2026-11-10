"""The stats a module states for a monster against the reference's (table voice and fixes Task E2; backlog Fixes 10:
the tracker had zombies at AC 8 where the module says 5). `setup_combat` puts the differences in its notes, so the DM
passes the module's numbers (the design's *my call*: no new link between fights and module content).

A stat line is what a module prints for a creature, as the conversion keeps it: "Zombies (4): AC 5; MV 6; HD 2; hp 12
each; THAC0 19; #AT 1; Dmg 1d8". It is read from the campaign's pinned revision: an encounter record's line for its
creature (`monster:zombie`, its `notes`), then any line of the encounter records and the texts that names the monster
and goes straight on to its stats. The first value found for each stat wins."""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from typing import Any

from delve.modules.source import pinned_source
from delve.storage.interfaces import Storage

# The stats, in the order the lines give them: the key, the pattern of its value, and how the DM passes it.
STATS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("AC", re.compile(r"\bAC\s*:?\s*(-?\d+)")),
    ("HD", re.compile(r"\bHD\s*:?\s*([0-9½¼]+(?:/2)?(?:\s*[+-]\s*\d+)?)")),
    ("hp", re.compile(r"\b(?:hp|HP)\s*:?\s*(\d+(?:\s*,\s*\d+(?![-d]))*)")),
    ("THAC0", re.compile(r"\bTHAC0\s*:?\s*(\d+)")),
    ("MV", re.compile(r"\bMV\s*:?\s*(\d+)")),
    (
        "Dmg",
        re.compile(
            r"\b(?:Dmg|D)\s*:?\s*(\d+\s*[-d]\s*\d+(?:\s*[+-]\s*\d+)?(?:\s*/\s*\d+\s*[-d]\s*\d+(?:\s*[+-]\s*\d+)?)*)"
        ),
    ),
)
REFERENCE_COLUMNS = {"AC": "armor_class", "HD": "hit_dice", "THAC0": "thac0", "MV": "move", "Dmg": "damage_attack"}
PASS = {
    "AC": "pass ac={} in setup_combat's enemies.",
    "HD": "pass hp for HD {} in setup_combat's enemies.",
    "hp": "pass hp={} in setup_combat's enemies.",
    "THAC0": "pass thac0={} in setup_combat's enemies.",
    "MV": "it moves as the module says.",
    "hp each": "set up a group of one for each, with its own hp, in setup_combat's enemies.",
    "Dmg": "pass dmg={} in setup_combat's enemies.",
}
# How far after the monster's name its first stat may start ("Zombies (4): AC 5"): further, the stats aren't its.
NEAR = 30
# Where another creature's stat line starts on the same line: "Ghouls (2):", "4 zombies:".
NEXT_CREATURE = re.compile(r"(?:\b[A-Z][a-z'-]+(?:,?\s+[a-z'-]+)*|\b\d+\s+[a-z'-]+(?:\s+[a-z'-]+)*)\s*(?:\(\d+\))?:")


def stated_differences(
    storage: Storage, campaign_id: str, monster: str, reference_row: Mapping[str, Any] | None
) -> list[str]:
    """One line per stat the campaign's pinned revision states for `monster` that differs from `reference_row`
    ("The module gives Zombie AC 5 (the reference says 8): pass ac=5 in setup_combat's enemies."); [] when none
    differs or none is stated."""
    campaign = storage.campaigns.get(campaign_id)
    source = pinned_source(storage, campaign.module_id, campaign.revision) if campaign is not None else None
    if source is None or not monster.strip():
        return []
    names = _names(monster, str((reference_row or {}).get("name") or ""))
    stated: dict[str, str] = {}
    for line in _stat_lines(source.entities.get("encounters") or [], [t.markdown for t in source.texts], names):
        for key, pattern in STATS:
            if key not in stated and (found := pattern.search(line)):
                stated[key] = " ".join(found.group(1).split())
    shown = monster.strip()[:1].upper() + monster.strip()[1:]
    lines = []
    for key, _ in STATS:
        if key not in stated:
            continue
        theirs = _reference_value(reference_row, key)
        if theirs is not None and _same(key, stated[key], theirs):
            continue
        says = f"the reference says {theirs}" if theirs is not None else "the reference gives none"
        then = PASS["hp each" if key == "hp" and "," in stated[key] else key]
        lines.append(f"The module gives {shown} {key} {stated[key]} ({says}): {then.format(stated[key])}")
    return lines


def _names(*names: str) -> list[re.Pattern[str]]:
    """The patterns of the monster's name and of the reference row's, either way round ("rat, giant", "giant rat"),
    singular or plural."""
    patterns = []
    for name in names:
        parts = [p.split() for p in name.lower().split(",") if p.strip()]
        if not parts:
            continue
        orders = [[w for p in parts for w in p], [w for p in reversed(parts) for w in p]]
        for words in orders:
            last = re.escape(words[-1])
            plural = rf"{last[:-1]}(?:y|ies)" if words[-1].endswith("y") else rf"{last}(?:s|es)?"
            body = r"[\s,]+".join([*(re.escape(w) for w in words[:-1]), plural])
            patterns.append(re.compile(rf"(?<![\w-]){body}(?![\w-])", re.IGNORECASE))
    return patterns


def _stat_lines(encounters: list[Any], texts: list[str], names: list[re.Pattern[str]]) -> Iterator[str]:
    """The stat lines of the monster: its encounter records' lines for its creature first, then the lines of the
    records and the texts that name it and go on to stats, each cut where another creature's line starts."""
    for record in encounters:
        yield from _creature_notes(record, names)
    strings = [s for record in encounters for s in _strings(record)] + texts
    for text in strings:
        for line in text.splitlines():
            for name in names:
                for match in name.finditer(line):
                    rest = line[match.end() :]
                    if (cut := NEXT_CREATURE.search(rest, 1)) is not None:
                        rest = rest[: cut.start()]
                    first = min((m.start() for _, p in STATS if (m := p.search(rest))), default=None)
                    if first is not None and first <= NEAR and not re.search(r"[.!?]\s", rest[:first]):
                        yield rest


def _creature_notes(value: Any, names: list[re.Pattern[str]]) -> Iterator[str]:
    """The `notes` of each entry of an encounter record whose `creature` is the monster (`monster:giant-rat`)."""
    if isinstance(value, dict):
        creature = value.get("creature")
        if isinstance(creature, str) and isinstance(value.get("notes"), str):
            spoken = creature.split(":", 1)[-1].replace("-", " ")
            if any(name.fullmatch(spoken) for name in names):
                yield value["notes"]
        for item in value.values():
            yield from _creature_notes(item, names)
    elif isinstance(value, list):
        for item in value:
            yield from _creature_notes(item, names)


def _strings(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def _reference_value(row: Mapping[str, Any] | None, key: str) -> str | None:
    """The reference row's value of the stat, as the module would print it; None when it has none (hp never)."""
    column = REFERENCE_COLUMNS.get(key)
    value = row.get(column) if row is not None and column is not None else None
    if value is None or not str(value).strip():
        return None
    text = " ".join(str(value).split())
    if key in ("AC", "THAC0", "MV"):
        number = re.search(r"-?\d+", text)
        return number.group() if number else None
    return text


def _same(key: str, stated: str, theirs: str) -> bool:
    if key == "HD":
        return _hd(stated) == _hd(theirs)
    if key == "Dmg":
        theirs = re.sub(r"\s*\([^)]*\)", "", theirs)  # "1-6 (weapon)"
        return _ranges(stated) == _ranges(theirs) if _ranges(theirs) else stated == theirs
    return stated == theirs


def _hd(text: str) -> str:
    return re.sub(r"\s+", "", text.lower()).replace("1/2", "½").replace("1/4", "¼")


def _ranges(text: str) -> list[tuple[int, int]]:
    """Each attack's damage as its least and most: "1d8" and "1-8" are both (1, 8), "1d6+1" is (2, 7)."""
    ranges = []
    for part in text.split("/"):
        found = re.fullmatch(r"\s*(\d+)\s*([-d])\s*(\d+)\s*(?:([+-])\s*(\d+))?\s*", part)
        if found is None:
            return []
        a, sep, b = int(found[1]), found[2], int(found[3])
        bonus = (int(found[5]) if found[4] == "+" else -int(found[5])) if found[4] else 0
        low, high = (a, a * b) if sep == "d" else (a, b)
        ranges.append((low + bonus, high + bonus))
    return ranges
