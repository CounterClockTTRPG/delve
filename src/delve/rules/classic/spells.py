"""Spell levels and slots: which list a caster draws from, a spell's level, and memorizing within the slots.

Pure: the reference is handed in, nothing is stored. ttrpg2 (`tools/party.py`) resolved a bare spell name's level
against its spell table, by the caster's list first (a priest's Hold Person is 2nd level, a wizard's 3rd); so does
`level_of`.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from delve.domain.characters import MemorizedSpell, Sheet
from delve.domain.reference import RulesetReference
from delve.rules.classic.tables import RuleTables


class UnknownSpell(LookupError):
    """A spell name the reference doesn't have; `candidates` are `{name, level, caster}` of spells it might mean."""

    def __init__(self, name: str, candidates: list[dict[str, Any]]) -> None:
        self.name = name
        self.candidates = candidates
        super().__init__(f"No spell '{name}'.")


class SlotsExceeded(ValueError):
    """More spells of a level than the caster has slots for."""


def caster_kind(cls: str, *, rules: RuleTables) -> str:
    """The spell list the class casts from ('priest', 'wizard'), or '' when the class says nothing useful."""
    low = (cls or "").lower()
    return next((kind for kind, words in rules.caster_classes.items() if any(k in low for k in words)), "")


def _candidate(row: dict[str, Any]) -> dict[str, Any]:
    return {"name": row["name"], "level": row["level"], "caster": row["caster"]}


def lookup(reference: RulesetReference, name: str, kind: str = "") -> dict[str, Any]:
    """The reference's spell named exactly `name` (ignoring case), from the `kind` list ('priest' or 'wizard') when
    it is on it, else from either. Raises `UnknownSpell` with the near names."""
    wanted = name.strip().lower()
    rows = reference.spell(name, caster=kind) if kind else []
    exact = [row for row in rows if row["name"].lower() == wanted]
    if not exact:
        everywhere = reference.spell(name)
        exact = [row for row in everywhere if row["name"].lower() == wanted]
        rows = rows or everywhere
    if not exact or not wanted:
        raise UnknownSpell(name, [_candidate(row) for row in rows])
    return exact[0]


def level_of(reference: RulesetReference, name: str, kind: str = "") -> tuple[str, int]:
    """(the reference's spelling, the level) of the spell `name`."""
    row = lookup(reference, name, kind)
    return row["name"], int(row["level"])


def check_slots(levels: Iterable[int], slots: Mapping[int, int]) -> None:
    """Raise `SlotsExceeded` when the spells of some level (one entry per spell) outnumber that level's slots."""
    counts: dict[int, int] = {}
    for level in levels:
        counts[level] = counts.get(level, 0) + 1
    for level in sorted(counts):
        cap = slots.get(level, 0)
        if counts[level] > cap:
            raise SlotsExceeded(f"Too many level-{level} spells: {counts[level]} given, {cap} slots available.")


def default_memorized(sheet: Sheet) -> tuple[MemorizedSpell, ...]:
    """The sheet's default loadout as freshly memorized spells, lowest level first."""
    default = sheet.spell_loadout.default
    return tuple(MemorizedSpell(name, level) for level in sorted(default) for name in default[level])


def uncast(memorized: Iterable[MemorizedSpell]) -> tuple[MemorizedSpell, ...]:
    """The same spells, none of them cast: what a night's rest gives back."""
    return tuple(MemorizedSpell(s.name, s.level) for s in memorized)


def remaining(memorized: Iterable[MemorizedSpell]) -> dict[int, int]:
    """The uncast spells of each memorized level."""
    out: dict[int, int] = {}
    for spell in memorized:
        out[spell.level] = out.get(spell.level, 0) + (0 if spell.cast else 1)
    return dict(sorted(out.items()))
