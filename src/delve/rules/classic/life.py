"""Life and death by hit points, one definition for the fight's tracker (`delve.rules.classic.combat`) and the
characters' own state (`delve.play.characters`), so the two never disagree on when a character is down or dead."""

from __future__ import annotations

__all__ = ["DEAD_AT", "life_conditions", "with_condition"]

DEAD_AT = -10
"""Characters are unconscious at 0 (disabled under `FightRules.disabled_at_zero`), dying at -1 to -9 and dead at -10.
Monsters die at 0."""


def with_condition(conditions: tuple[str, ...], condition: str, present: bool) -> tuple[str, ...]:
    """`conditions` with `condition` added once when `present`, else without it."""
    if present:
        return conditions if condition in conditions else (*conditions, condition)
    return tuple(c for c in conditions if c != condition)


def life_conditions(conditions: tuple[str, ...], hp: int, disabled_at_zero: bool = False) -> tuple[str, ...]:
    """`conditions` with what the hit points say: `downed` at 0 or below, `dead` at -10 or below; above them,
    neither. With `disabled_at_zero` (`FightRules.disabled_at_zero`, 3.5) exactly 0 is `disabled`, not `downed`, and
    any other hp takes `disabled` off; at 0 or more `stable` comes off too, as one is no longer dying (the fight's
    `heal` does the same); without it `disabled` and `stable` are left as they are."""
    if disabled_at_zero:
        conditions = with_condition(conditions, "disabled", hp == 0)
        if hp >= 0:
            conditions = with_condition(conditions, "stable", False)
        down = hp < 0
    else:
        down = hp <= 0
    return with_condition(with_condition(conditions, "downed", down), "dead", hp <= DEAD_AT)
