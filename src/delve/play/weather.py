"""The day's weather (plan 6 Task 4, Decision 3): one roll per day and terrain on ttrpg2's tables, made the first time
it is asked for (`weather_check`, `travel`, the primer) and kept for the day in `CampaignState.weather`.

The season is the date's weather season. The roll is a `1d<sum of the weights>` in the dice log, so a repeated call
in the beat finds the stored roll; a later beat finds the day's weather in the state. The new-day hook `weather`
drops the days gone by, keeping the last terrain rolled as the default for the next ask.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from delve.domain.world import Weather
from delve.play import days
from delve.play.context import CampaignContext, PlayError
from delve.rules.classic import weather_tables
from delve.rules.classic.terrain import TERRAIN_ALIASES

__all__ = ["current", "pace", "weather", "weighted_pick"]

DEFAULT_TERRAIN = "wilderness"


def pace(label: str) -> float:
    """How the weather `label` slows a day's travel: the first `PACE` entry it contains, else 1.0."""
    lowered = (label or "").lower()
    return next((multiplier for needle, multiplier in weather_tables.PACE if needle in lowered), 1.0)


def weighted_pick(table: list[tuple[int, str, str]], roll: int) -> tuple[str, str]:
    """The `(label, effect)` a roll of 1…sum of the weights lands on, as ttrpg2's `_weighted_pick`."""
    reached = 0
    for weight, label, effect in table:
        reached += weight
        if roll <= reached:
            return label, effect
    return table[-1][1], table[-1][2]


def _terrain(ctx: CampaignContext, terrain: str) -> str:
    """The terrain key: the encounter tables' alias resolved; empty is the last terrain rolled, else wilderness."""
    key = terrain.strip().lower()
    if not key:
        rolled = ctx.storage.campaign_states.get(ctx.campaign_id).weather
        return rolled[-1].terrain if rolled else DEFAULT_TERRAIN
    key = TERRAIN_ALIASES.get(key, key)
    if key not in weather_tables.TERRAIN_TABLE:
        raise PlayError(f"Unknown terrain '{terrain}'.", f"Use one of: {', '.join(sorted(weather_tables.TERRAIN_TABLE))}.")
    return key


def current(ctx: CampaignContext) -> Weather | None:
    """Today's weather last rolled, without rolling: None when none was rolled today, or the campaign was deleted
    while its table was being read."""
    state = ctx.storage.campaign_states.get(ctx.campaign_id)
    if state is None:
        return None
    return next((w for w in reversed(state.weather) if w.day == state.day), None)


def weather(ctx: CampaignContext, terrain: str = "") -> Weather:
    """Today's weather in `terrain`, rolled with the beat's dice when today has none for it."""
    key = _terrain(ctx, terrain)
    with ctx.storage.transaction():
        state = ctx.storage.campaign_states.get(ctx.campaign_id)
        kept = next((w for w in state.weather if w.day == state.day and w.terrain == key), None)
        if kept is not None:
            return kept
        table = weather_tables.table(days.today(ctx).weather_season, key)
        roll = ctx.dice.roll(f"1d{sum(w for w, _, _ in table)}", purpose=f"weather:{key}:day {state.day}")
        label, effect = weighted_pick(table, roll.total)
        rolled = Weather(state.day, key, label, effect, pace(label))
        today = tuple(w for w in state.weather if w.day == state.day and w.terrain != key)
        ctx.storage.campaign_states.put(
            replace(state, weather=(*today, rolled), start_date=days.start_date(ctx, state))
        )
    return rolled


def _new_day(ctx: CampaignContext, day: int) -> dict[str, Any]:
    """The days gone by leave the state; the last terrain rolled stays, as the default of the next ask."""
    state = ctx.storage.campaign_states.get(ctx.campaign_id)
    if len(state.weather) > 1:
        ctx.storage.campaign_states.put(replace(state, weather=state.weather[-1:]))
    return {}


days.register("weather", _new_day)
