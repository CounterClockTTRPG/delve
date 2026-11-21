"""The keys Phase 3 adds to `Sheet.d20["derived"]` (DEL-389), which Phase 2's goldens and saved numbers predate.
Their comparisons drop these keys from every `derived` dict, and only these: every other key and number must still
match. Each task that adds a derived key appends it here. Likewise `PHASE3_COMBATANT_KEYS`, the keys Phase 3 adds to
a combatant's `d20` (each `d20` of a fight's `combatants`), and only those."""

from __future__ import annotations

from typing import Any

PHASE3_KEYS = ("features", "dr", "favoured_enemy", "companion", "hit_dice", "ecl", "xp_penalty", "casting", "evasion",
               "improved_uncanny_dodge", "skill_notes")  # fmt: skip
PHASE3_COMBATANT_KEYS = ("monster", "sneak_level", "improved_uncanny_dodge")
"""A monster combatant's row id (`combat.combatant_from_monster`), read by smite evil and favoured enemy; a character's
rogue level for flanking and its improved uncanny dodge's flanking level (part 4)."""


def without_phase3(value: Any) -> Any:
    """`value` with the `PHASE3_KEYS` dropped from each dict under a `derived` key, and the `PHASE3_COMBATANT_KEYS`
    from each combatant's `d20` (a dict in a `combatants` list), at any depth."""
    if isinstance(value, dict):
        return {key: (_derived(item) if key == "derived" else _combatants(item) if key == "combatants"
                      else without_phase3(item)) for key, item in value.items()}  # fmt: skip
    if isinstance(value, list):
        return [without_phase3(item) for item in value]
    return value


def _derived(item: Any) -> Any:
    if not isinstance(item, dict):
        return without_phase3(item)
    return {key: without_phase3(v) for key, v in item.items() if key not in PHASE3_KEYS}


def _combatants(item: Any) -> Any:
    if not isinstance(item, list):
        return without_phase3(item)
    out = []
    for c in item:
        if isinstance(c, dict) and isinstance(c.get("d20"), dict):
            d20 = {key: v for key, v in c["d20"].items() if key not in PHASE3_COMBATANT_KEYS}
            c = {**c, "d20": d20}
        out.append(without_phase3(c))
    return out
