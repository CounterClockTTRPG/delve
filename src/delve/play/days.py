"""Days pass in one place (plan 6 Task 4, spec §7.9): `pass_days` moves the campaign's day and runs every new-day
hook once per day crossed, whoever moved the clock: `advance_time` past midnight, `advance_days`, a whole-party
`rest`, or `travel`. `set_time` never changes the day.

A new-day hook is `hook(ctx, day) -> dict`, called with the new day's number after the day has moved, inside the
same transaction. A module registers its hooks with `register` when it is imported, and names itself in
`HOOK_MODULES`, so `pass_days` imports it before the first day passes. The results of each hook are merged over the
days under its name: lists add up, dicts merge the same way, and any other value is the last day's. A hook that
reports nothing is left out.

The date is derived from the day by the setting's calendar (the plain one without a setting), from the campaign's
start date: its calendar's default until a day first passes, which stores it.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable
from dataclasses import replace
from typing import Any

from delve.domain.campaigns import CampaignState
from delve.domain.world import PLAIN_CALENDAR, Calendar, GameDate, StartDate
from delve.play.context import CampaignContext, PlayError

__all__ = [
    "HOOKS",
    "HOOK_MODULES",
    "MAX_DAYS",
    "NewDayHook",
    "answer",
    "calendar",
    "pass_days",
    "register",
    "start_date",
    "today",
]

NewDayHook = Callable[[CampaignContext, int], dict[str, Any]]

HOOKS: dict[str, NewDayHook] = {}
"""The new-day hooks by name, in the order they run."""

HOOK_MODULES = ("delve.play.weather", "delve.play.factions")
"""The modules that register new-day hooks, imported before a day first passes."""

MAX_DAYS = 3650
"""The most days that pass at once: ten years."""


def register(name: str, hook: NewDayHook) -> None:
    """Run `hook` on every new day; its merged results come back from `pass_days` under `name`."""
    HOOKS[name] = hook


def calendar(ctx: CampaignContext) -> Calendar:
    """The campaign's calendar: its setting's, else the plain calendar."""
    return ctx.setting.calendar() if ctx.setting is not None else PLAIN_CALENDAR


def start_date(ctx: CampaignContext, state: CampaignState | None = None) -> StartDate:
    """The date of the campaign's day 1: the stored one, else its calendar's default."""
    state = state or ctx.storage.campaign_states.get(ctx.campaign_id)
    if state.start_date is not None:
        return state.start_date
    return StartDate(*calendar(ctx).default_start)


def today(ctx: CampaignContext) -> GameDate:
    """Today's date. Reading it never writes: a campaign without a start date reads its calendar's default."""
    state = ctx.storage.campaign_states.get(ctx.campaign_id)
    return calendar(ctx).date(start_date(ctx, state).as_tuple(), state.day)


def pass_days(ctx: CampaignContext, days: int, reason: str = "") -> dict[str, Any]:
    """Move the day on by `days`, keeping the time of day, and run every new-day hook once for each new day, in one
    transaction. `{days_passed, date, <hook name>: its merged results}`, `date` being the new day's `GameDate`."""
    days = int(days)
    if days < 0:
        raise PlayError(f"Days can't pass backwards ({days}).", "Pass a number of days from 0.")
    if days > MAX_DAYS:
        raise PlayError(f"At most {MAX_DAYS} days pass at once ({days}).", "Let the years pass in steps.")
    for module in HOOK_MODULES:
        importlib.import_module(module)
    results: dict[str, dict[str, Any]] = {name: {} for name in HOOKS}
    with ctx.storage.transaction():
        for _ in range(days):
            state = ctx.storage.campaign_states.get(ctx.campaign_id)
            moved = replace(state, day=state.day + 1, start_date=start_date(ctx, state))
            ctx.storage.campaign_states.put(moved)
            for name, hook in list(HOOKS.items()):
                _merge(results.setdefault(name, {}), hook(ctx, moved.day) or {})
        state = ctx.storage.campaign_states.get(ctx.campaign_id)
        date = calendar(ctx).date(start_date(ctx, state).as_tuple(), state.day)
        if days:
            ctx.log("days", days=days, day=state.day, date=date.label, reason=reason)
    return {"days_passed": days, "date": date, **{name: merged for name, merged in results.items() if merged}}


def answer(passed: dict[str, Any]) -> dict[str, Any]:
    """`pass_days`'s result as a tool answers it, the date as its label."""
    return {**passed, "date": passed["date"].label}


def _merge(into: dict[str, Any], day: dict[str, Any]) -> None:
    for key, value in day.items():
        old = into.get(key)
        if isinstance(value, list):
            into[key] = (old if isinstance(old, list) else []) + value
        elif isinstance(value, dict):
            into[key] = old if isinstance(old, dict) else {}
            _merge(into[key], value)
        else:
            into[key] = value
