"""A module's own wandering-monster tables (DEL-321): the `encounters` records with a `table` that a wandering check
rolls on, where each applies, and the die it takes.

A record says it is one with `wandering: true` (or `false`, that it isn't), and where it applies with `where`: refs to
a whole map (`map:upper`), one room of a map (`map:upper#hall`), a keyed room (`key:C2`), a text (`text:key-to-the-
upper-level`) or one section of it (`text:crypt-key#c1`). A record of an older module says neither: it counts as one
when it has no `key` (a room's own table) and its id or name reads as one ("Wandering Monsters", "Random Encounter
Chart"), and its `location` text, when it has one, is where it applies. A table with no place applies anywhere its
`kind` allows. A wandering record with an empty `table` is a place the module says has no wandering monsters
(Saltmarsh's cellar): a check there brings nothing.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

WANDERING_NAME = re.compile(
    r"wander|random (?:monster|encounter)|encounters? (?:table|chart)|random-(?:monster|encounter)"
)
"""What the id or name of an older module's wandering table reads like."""

ANY_KIND = frozenset({"", "random", "wandering"})
"""Kinds that say nothing about the terrain: a table of these kinds is for any."""
WILDERNESS = frozenset({"wilderness", "wilds", "outdoor", "outdoors", "overland"})
"""Kinds for any terrain out of doors: forest, hills, swamp, road… but not a dungeon or a town."""

_RANGE = re.compile(r"^\s*(\d+)\s*(?:[-–—]|to)\s*(\d+)\s*$")
_ONE = re.compile(r"^\s*(\d+)\s*$")
_PERCENT = re.compile(r"(?<!\d)0\d(?!\d)")
_DICE = re.compile(r"^\s*\d*d\d+\s*(?:[+-]\s*\d+)?\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class Row:
    """One line of a table: the rolls it takes (`low` to `high`, None when its roll isn't a number) and what comes."""

    roll: str
    """The roll as the module prints it: "1-3", "01–05", "6"."""
    low: int | None
    high: int | None
    creature: str = ""
    """The creature's ref, `monster:giant-rat` or `npc:…`, when the line is one creature."""
    count: str = ""
    """How many, as written: "1d6", "2-8", "3"."""
    result: str = ""
    """The line's own text, when it is no single creature."""
    category: str = ""
    notes: str = ""


@dataclass(frozen=True)
class WanderingTable:
    id: str
    name: str
    kind: str
    """The terrain it is for, as the module writes it (`dungeon`, `wilderness`…), "" when it says none."""
    where: tuple[str, ...]
    """Where it applies, as refs; () for anywhere."""
    rows: tuple[Row, ...]
    """Its lines; none for a place with no wandering monsters."""
    summary: str = ""

    @property
    def dice(self) -> str | None:
        """The roll that picks a line: "1d6", "1d100", "2d6" for a table of 2 to 12; None when a line's roll isn't a
        number or the lines take no plain roll (`low` above 1 and not a whole number of dice)."""
        if not self.rows or any(row.low is None or row.high is None for row in self.rows):
            return None
        low = min(row.low for row in self.rows if row.low is not None)
        high = max(row.high for row in self.rows if row.high is not None)
        if low <= 1:
            return f"1d{high}"
        return f"{low}d{high // low}" if high % low == 0 else None

    def line(self, total: int) -> Row | None:
        """The line a roll of `total` lands on, the first one when two overlap; None for a roll no line takes."""
        return next((row for row in self.rows if row.low is not None and row.low <= total <= (row.high or 0)), None)

    def to_json(self) -> dict[str, Any]:
        """What the DM is shown of a table it may choose."""
        return {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "where": list(self.where),
            **({"summary": self.summary} if self.summary else {}),
        }


def fits(kind: str, terrain: str) -> bool:
    """Whether a table of `kind` is for a check in `terrain` (a key of the encounter tables: "dungeon", "forest",
    "urban"…)."""
    return kind in ANY_KIND or kind == terrain or (kind in WILDERNESS and terrain not in ("dungeon", "urban"))


def is_wandering(record: Mapping[str, Any]) -> bool:
    """Whether an `encounters` record is a wandering table: `wandering` says so when it is set (with an empty `table`, for
    a place with none); else a record with a table and no room `key` whose id or name reads as one."""
    if not isinstance(record.get("table"), list):
        return False
    if isinstance(record.get("wandering"), bool):
        return record["wandering"]
    if not record["table"] or record.get("key"):
        return False
    return bool(WANDERING_NAME.search(f"{record.get('id', '')} {record.get('name', '')}".casefold()))


def wandering_tables(records: Iterable[Mapping[str, Any]]) -> list[WanderingTable]:
    """The wandering tables among a module's `encounters` records, in the module's order."""
    return [table(record) for record in records if isinstance(record, Mapping) and is_wandering(record)]


def table(record: Mapping[str, Any]) -> WanderingTable:
    """Any `encounters` record with a `table`, as a table to roll on (the DM may name one that isn't a wandering table,
    such as a room's own)."""
    where = record.get("where")
    refs = [ref for ref in where if isinstance(ref, str) and ref.strip()] if isinstance(where, list) else []
    if not refs and isinstance(record.get("location"), str) and record["location"].strip():
        refs = [record["location"]]
    rows = [row for row in record.get("table") or [] if isinstance(row, Mapping)]
    return WanderingTable(
        id=str(record.get("id", "")),
        name=str(record.get("name") or record.get("id", "")),
        kind=str(record.get("kind") or "").strip().casefold(),
        where=tuple(ref.strip() for ref in refs),
        rows=_rows(rows),
        summary=str(record.get("summary") or "").strip(),
    )


def _rows(rows: list[Mapping[str, Any]]) -> tuple[Row, ...]:
    # A table printed "01–05 … 96–00" is a d100's: its 00 is 100, where a d10 table's "9-0" ends on 10.
    hundred = any(_PERCENT.search(str(row.get("roll", ""))) for row in rows)
    out = []
    for row in rows:
        roll = str(row.get("roll", "")).strip()
        low, high = _span(roll, 100 if hundred else 10)
        out.append(
            Row(
                roll=roll,
                low=low,
                high=high,
                creature=str(row.get("creature") or ""),
                count=str(row.get("count") or ""),
                result=str(row.get("result") or ""),
                category=str(row.get("category") or ""),
                notes=str(row.get("notes") or ""),
            )
        )
    return tuple(out)


def _span(roll: str, zero: int) -> tuple[int | None, int | None]:
    """The rolls "1-3", "01–05", "96-00" or "6" take; a 0 or 00 is the die's top face (`zero`: 10, or 100 on a table
    of two-digit rolls)."""
    if m := _RANGE.match(roll):
        low, high = (int(v) or zero for v in m.groups())
        return (low, high) if low <= high else (None, None)
    if m := _ONE.match(roll):
        value = int(m.group(1)) or zero
        return value, value
    return None, None


def countable(count: str) -> bool:
    """Whether `count` is dice to roll ("1d6", "2d4+1") rather than a number or a range as printed."""
    return bool(_DICE.match(count))
