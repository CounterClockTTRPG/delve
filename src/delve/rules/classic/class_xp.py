"""XP tables and level progress, single- and multi-class, ported from ttrpg2 `tools/class_xp.py` as pure code.

A multi-class character ("Fighter/Thief") keeps one XP total. Every award is split evenly between the classes, so each
class's share is the total divided by the number of classes. Each class then levels on its own table: a Fighter/Thief
with 2,600 XP has 1,300 in each — Thief 2, Fighter 1.

A sheet records the per-class levels in `levels` ({"fighter": 1, "thief": 2}); a sheet without it has every class at
its single `level` (or 1). The XP tables come from the reference's class levels; ttrpg2's homebrew classes aren't
ported.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from delve.domain.reference import RulesetReference
from delve.rules.classic.tables import RuleTables


def _get(sheet: Any, name: str) -> Any:
    if isinstance(sheet, Mapping):
        return sheet.get(name)
    return getattr(sheet, name, None)


def xp_table(cls: str, reference: RulesetReference, *, rules: RuleTables) -> list[int]:
    """[xp_required at L1, L2, …] for ONE class, or [] if unknown.

    The ruleset's classes from the reference, then the kit alias. A multi-class string has no table of its own — use
    `progress`."""
    key = (cls or "").strip().lower()
    if not key or "/" in key:
        return []
    for candidate in (key, rules.class_aliases.get(key, "").lower()):
        if not candidate:
            continue
        found = reference.char_class(candidate)
        if found is not None and found["name"].lower().startswith(candidate):
            return [int(row["xp_required"]) for row in reference.class_levels(found["name"])]
    return []


def component_classes(cls: str) -> list[str]:
    """'Fighter/Thief' → ['fighter', 'thief']; 'Mage' → ['mage']."""
    return [p.strip().lower() for p in re.split(r"/", cls or "") if p.strip()]


def is_multiclass(sheet: Any) -> bool:
    return len(component_classes(_get(sheet, "cls") or "")) > 1


def class_levels(sheet: Any) -> dict[str, int]:
    """Per-class levels, in the order the class string names them (or as `levels` has them, with no class string)."""
    stored = {str(k).strip().lower(): int(v) for k, v in (_get(sheet, "levels") or {}).items()}
    classes = component_classes(_get(sheet, "cls") or "") or list(stored)
    base = int(_get(sheet, "level") or 1)
    return {c: stored.get(c, base) for c in classes}


def progress(sheet: Any, xp_total: int, reference: RulesetReference, *, rules: RuleTables) -> list[dict]:
    """One row per class: its XP share, current level, the share needed for its next level, and — so a caller can
    compare against the single stored total — `total_next`, the XP total at which that class levels.

    `earned_level` is the highest level the share already reaches on that class's table; `ready` is true when it is
    above the recorded level."""
    levels = class_levels(sheet)
    n = max(len(levels), 1)
    share = int(xp_total) // n
    rows = []
    for cls, level in levels.items():
        table = xp_table(cls, reference, rules=rules)
        row: dict = {
            "class": cls.title(),
            "level": level,
            "xp": share,
            "xp_floor": None,
            "xp_next": None,
            "total_next": None,
            "earned_level": None,
            "ready": False,
        }
        if table:
            row["xp_floor"] = table[level - 1] if 1 <= level <= len(table) else None
            if level < len(table):
                row["xp_next"] = table[level]
                row["total_next"] = table[level] * n
            earned = sum(1 for t in table if t <= share)
            row["earned_level"] = earned
            row["ready"] = earned > level
        rows.append(row)
    return rows


def level_up_hints(
    sheet: Any, xp_before: int, xp_after: int, reference: RulesetReference, *, rules: RuleTables
) -> list[str]:
    """One line per class whose share crossed a threshold with this award."""
    label = _get(sheet, "label") or "?"
    multi = is_multiclass(sheet)
    before = {r["class"]: r["earned_level"] for r in progress(sheet, xp_before, reference, rules=rules)}
    hints = []
    for r in progress(sheet, xp_after, reference, rules=rules):
        was, now = before.get(r["class"]), r["earned_level"]
        if was is None or now is None or now <= was or now <= r["level"]:
            continue
        share = f" ({r['xp']:,} XP share)" if multi else ""
        hints.append(f"Level up! {label} is eligible for {r['class']} level {now}{share}.")
    return hints
