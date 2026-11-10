"""Item weights and encumbrance, ported from ttrpg2 `tools/item_weights.py`; the weights and bands are the ruleset's
(`EncumbranceTables`).

`resolve_weight` turns a free-form item name into pounds, in ttrpg2's order:
  1. strip a trailing parenthetical descriptor and a leading count;
  2. normalize the spelling ('armour' -> 'armor', no apostrophes);
  3. the ruleset's item aliases, exact then prefix, redirect campaign phrasing to its item name;
  4. an exact, case-insensitive item name in the reference, so 'plate mail' is Plate Mail (50 lb), not Bronze Plate
     Mail (45 lb);
  5. a name containing it, with plural-to-singular and trailing-'armor' fallbacks;
  6. the ruleset's own weights for items the reference lacks (shields, bedroll, spellbook…).

`compute` puts a character's load in one of ttrpg2's bands for its Strength, each with a movement penalty.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from delve.domain.reference import RulesetReference

_WEIGHT_NUM_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)")
_INV_QTY_SUFFIX_RE = re.compile(r"\s*[x×]\s*(\d+)\s*$", re.IGNORECASE)

# The reference rows searched for each name; enough that an exact name is never cut off by commoner items
# containing it ("dagger").
_SEARCH_LIMIT = 1000


@dataclass(frozen=True)
class EncumbranceTables:
    """A ruleset's item weights and Strength bands."""

    item_aliases: Mapping[str, str]
    """Campaign phrasing (normalized: lowercase, 'armor', no apostrophes) onto the ruleset's item name."""
    item_weights: Mapping[str, float]
    """Weights in pounds of items the reference lacks."""
    str_bands: Mapping[int, tuple[int, int, int, int]]
    """(light, moderate, heavy, severe) upper bounds in pounds, by the lowest Strength of each row."""
    str_pct_allowance: tuple[tuple[int, int], ...]
    """Exceptional Strength (18/xx) as (percentile ceiling, allowance); 18/00 is 100. Its bands step by `pct_stride`."""
    pct_stride: int
    band_penalties: Mapping[str, int]
    """The movement penalty of each band: light, moderate, heavy, severe, overloaded."""
    band_fractions: Mapping[str, float] | None = None
    """Instead of a penalty, the share of the movement rate each band keeps (overloaded 0: no movement); None for
    the penalties."""


def parse_weight(raw: Any) -> float:
    """A numeric pound value from item weight strings like '5 lbs.', '0.5 lbs.', '1 lb.', '5 lbs. (full)', or bare
    '7'. 0 for placeholders ('*', '**', '_ lbs.') or missing values."""
    if not raw:
        return 0.0
    m = _WEIGHT_NUM_RE.match(str(raw))
    if not m:
        return 0.0
    try:
        return float(m.group(1))
    except ValueError:
        return 0.0


def split_inventory_qty(raw: str) -> tuple[str, int]:
    """Split a trailing quantity suffix off an inventory string. 'Hand axe x2' -> ('Hand axe', 2). 'Spear' ->
    ('Spear', 1)."""
    s = (raw or "").strip()
    m = _INV_QTY_SUFFIX_RE.search(s)
    if not m:
        return s, 1
    qty = max(1, int(m.group(1)))
    return s[: m.start()].rstrip(" ,"), qty


def item_key(name: str) -> str:
    """How two item names are compared: case- and whitespace-insensitive."""
    return " ".join(name.lower().split())


def collapse_inventory(items: Iterable[Any] | None) -> list[str]:
    """Collapse repeated inventory entries into 'Name x N' form.

    ['Arrow'] * 24 -> ['Arrow x24']; existing suffixes are folded in, so ['Torch x2', 'Torch'] -> ['Torch x3'].
    First-appearance order and the first spelling of each item are preserved; singletons keep no suffix. Matching is
    case- and whitespace-insensitive on the base name."""
    order: list[str] = []
    names: dict[str, str] = {}
    counts: dict[str, int] = {}
    for raw in items or []:
        base, qty = split_inventory_qty(str(raw))
        if not base:
            continue
        key = item_key(base)
        if key not in counts:
            order.append(key)
            names[key] = base
            counts[key] = 0
        counts[key] += qty
    return [names[k] if counts[k] == 1 else f"{names[k]} x{counts[k]}" for k in order]


def _reference_row(reference: RulesetReference, name: str) -> dict | None:
    """The reference item named exactly `name` (ignoring case), else the first whose name contains it."""
    rows = reference.item(name, limit=_SEARCH_LIMIT)
    exact = next((row for row in rows if row["name"].lower() == name.lower()), None)
    return exact if exact is not None else (rows[0] if rows else None)


def resolve_weight(name: str, reference: RulesetReference, *, rules: EncumbranceTables) -> dict[str, Any]:
    """A free-form item name's weight in pounds: `{"lb", "source"}`, where source is
    'db'         — a match in the reference's items
    'alias'      — matched through the ruleset's item aliases, then the reference
    'phb'        — one of the ruleset's own weights the reference doesn't have
    'negligible' — the reference has it, without a weight ('*', '**', none)
    'unknown'    — no match anywhere
    """
    cleaned = (name or "").strip().lstrip("0123456789x ").strip()
    if not cleaned:
        return {"lb": 0.0, "source": "unknown"}

    # Strip trailing parenthetical descriptors: 'Hide armour (custom-fitted, AC 6)' → 'Hide armour'
    base = re.sub(r"\s*\([^)]*\)\s*$", "", cleaned).strip() or cleaned

    norm = (
        base.lower().replace("armour", "armor").replace("colour", "color").replace("'", "").replace("’", "")
    )  # right single quotation mark

    # 1) Alias resolution — exact match, then prefix-based.
    canonical = rules.item_aliases.get(norm)
    if not canonical:
        for k, v in rules.item_aliases.items():
            if norm == k or norm.startswith(k + " "):
                canonical = v
                break

    candidates: list[tuple[str, str]] = []
    if canonical:
        candidates.append((canonical, "alias"))
    candidates.append((norm, "db"))
    if norm.endswith("ies") and len(norm) > 3:
        candidates.append((norm[:-3] + "y", "db"))
    elif norm.endswith("es") and len(norm) > 2:
        candidates.append((norm[:-2], "db"))
    elif norm.endswith("s") and len(norm) > 1:
        candidates.append((norm[:-1], "db"))
    # Drop trailing 'armor'/'armour'/'mail' so 'studded leather armor' → 'studded leather'.
    stripped = re.sub(r"\s+(armor|armour|mail)\s*$", "", norm).strip()
    if stripped and stripped != norm:
        candidates.append((stripped, "db"))

    # 2) The reference — an exact name first, then a substring.
    for candidate, source in candidates:
        row = _reference_row(reference, candidate)
        if row is None:
            continue
        weight = parse_weight(row.get("weight"))
        if weight > 0:
            return {"lb": weight, "source": source}
        if row.get("weight") is not None:
            return {"lb": 0.0, "source": "negligible"}

    # 3) The ruleset's own weights for items not in the reference
    if norm in rules.item_weights:
        return {"lb": rules.item_weights[norm], "source": "phb"}

    return {"lb": 0.0, "source": "unknown"}


def parse_strength(raw: Any, pct: Any = None) -> tuple[int, int]:
    """A STR score as (score, percentile).

    Accepts a plain number, or the exceptional-strength forms sheets use: "18/00" → (18, 100), "18/76" → (18, 76).
    An explicit `pct` (from an `ability_scores["str_pct"]` field) wins when the score itself carries no percentile."""
    score, parsed_pct = 10, 0
    text = str(raw).strip()
    if "/" in text:
        head, _, tail = text.partition("/")
        try:
            score = int(head)
            parsed_pct = _percentile(tail)
        except ValueError:
            pass
    else:
        try:
            score = int(float(text))
        except ValueError:
            pass
    if not parsed_pct and pct is not None:
        try:
            parsed_pct = _percentile(pct)
        except (TypeError, ValueError):
            parsed_pct = 0
    if score != 18:
        parsed_pct = 0
    return score, parsed_pct


def _percentile(raw: Any) -> int:
    """An exceptional-strength percentile: "00" is the hundredth (18/00), any other number itself. A 0 is a sheet
    saying there is none, not 18/00, so only the written "00" reads as 100."""
    text = str(raw).strip()
    return 100 if text == "00" else int(text)


def str_band_for(strength: int, pct: int = 0, *, rules: EncumbranceTables) -> tuple[int, int, int, int]:
    """(light, moderate, heavy, severe) upper bounds for a STR score.

    `pct` is the exceptional-strength percentile (1–100, where 100 is 18/00); it applies only at STR 18 and
    overrides the whole-score row."""
    if strength == 18 and pct:
        for ceiling, allowance in rules.str_pct_allowance:
            if pct <= ceiling:
                step = rules.pct_stride
                return (allowance, allowance + step, allowance + 2 * step, allowance + 3 * step)
    keys = sorted(rules.str_bands.keys())
    pick = keys[0]
    for k in keys:
        if k <= strength:
            pick = k
        else:
            break
    return rules.str_bands[pick]


def compute(
    items: Iterable[tuple[str, int, float | None]],
    *,
    strength: Any = 10,
    pct: Any = None,
    movement_rate: int = 12,
    rules: EncumbranceTables,
) -> dict[str, Any]:
    """The encumbrance of a load of `(name, qty, weight of one or None)`:

        {total_lb, band, penalty, movement, strength, thresholds, items: [{item, qty, unit_lb, weight_lb}]}

    `band` is light, moderate, heavy, severe or overloaded for the Strength, `penalty` its movement penalty
    (0/-3/-6/-9/-12), and `movement` the movement rate with the penalty, at least 1 (an overloaded character moves 1,
    as the rulesets have it). `strength` is the score, or "18/76" for exceptional strength."""
    score, str_pct = parse_strength(strength, pct)
    rows: list[dict[str, Any]] = []
    total = 0.0
    for name, qty, unit in items:
        unit_lb = unit or 0.0
        rows.append({"item": name, "qty": qty, "unit_lb": unit_lb, "weight_lb": unit_lb * qty})
        total += unit_lb * qty

    light, moderate, heavy, severe = str_band_for(score, str_pct, rules=rules)
    if total <= light:
        band = "light"
    elif total <= moderate:
        band = "moderate"
    elif total <= heavy:
        band = "heavy"
    elif total <= severe:
        band = "severe"
    else:
        band = "overloaded"
    if rules.band_fractions is not None:
        movement = int(movement_rate * rules.band_fractions[band])
        penalty = movement - movement_rate
    else:
        penalty = rules.band_penalties[band]
        movement = 1 if band == "overloaded" else max(1, movement_rate + penalty)
    return {
        "total_lb": round(total, 1),
        "band": band,
        "penalty": penalty,
        "movement": movement,
        "strength": f"{score}/{str_pct % 100:02d}" if str_pct else score,
        "thresholds": {"light": light, "moderate": moderate, "heavy": heavy, "severe": severe},
        "items": rows,
    }
