"""`play.days` (plan 6 Task 4, Review Focus 2): days pass in one place. `advance_days`, `advance_time` across
midnight, a whole-party `rest` and travel each run every new-day hook exactly once per day crossed; `set_time` and
one character resting never move the day. The date is derived from the day by the setting's calendar, and the year
rolls over."""

from dataclasses import replace

import pytest

from delve.dice import SeededRng
from delve.dm.tools import ToolHost
from delve.domain.world import StartDate
from delve.play import characters, days, sessions
from delve.play.context import PlayError
from tests.fixtures.play_reference import PlayReference
from tests.fixtures.rulesets import over
from tests.fixtures.settings import GreyhawkSetting
from tests.play.conftest import crypt_campaign


@pytest.fixture
def campaign(storage):
    """A campaign without a setting: the plain calendar's "Day N"."""
    return crypt_campaign(storage, setting="")


@pytest.fixture
def counted(monkeypatch):
    """A new-day hook that records each day it is called with; the days, in order."""
    seen: list[int] = []

    def count(ctx, day):
        seen.append(day)
        return {"days": [day], "last": day}

    monkeypatch.setitem(days.HOOKS, "count", count)
    return seen


@pytest.fixture
def greyhawk(ctx):
    ctx.setting = GreyhawkSetting()
    return ctx


@pytest.fixture
def call(storage, campaign):
    """`call(tool, **args)`: a tool call on the campaign, in one beat."""
    host = ToolHost(storage, lambda: SeededRng(1), catalogs=over(PlayReference()))
    return lambda tool, /, **args: host.call(campaign.id, "beat-1", tool, args)


@pytest.fixture
def party(ctx):
    characters.create(ctx, name="Garrek", sheet={"hp_max": 10})
    characters.create(ctx, name="Pippa", sheet={"hp_max": 6})


def _day(ctx) -> int:
    return ctx.storage.campaign_states.get(ctx.campaign_id).day


def test_advance_days_runs_each_hook_once_per_day(ctx, counted):
    out = days.pass_days(ctx, 30)
    assert counted == list(range(2, 32))
    assert out["days_passed"] == 30 and out["date"].label == "Day 31"
    assert out["count"] == {"days": list(range(2, 32)), "last": 31}  # lists add up, the rest is the last day's
    assert _day(ctx) == 31
    assert days.pass_days(ctx, 0)["days_passed"] == 0 and counted == list(range(2, 32))
    with pytest.raises(PlayError):
        days.pass_days(ctx, -1)


def test_advance_time_across_midnight_runs_the_hooks(ctx, counted):
    """3000 minutes from dawn (06:00) of day 1 is 08:00 of day 3: two midnights, two new days."""
    out = sessions.advance_time(ctx, 3000)
    assert (out["day"], out["time"], out["days_passed"]) == (3, "08:00", 2)
    assert out["date"] == "Day 3"
    assert counted == [2, 3]
    sessions.advance_time(ctx, 60)
    assert counted == [2, 3]
    sessions.set_time(ctx, 2)  # back to 02:00: never a new day
    assert counted == [2, 3] and _day(ctx) == 3
    sessions.advance_time(ctx, 22 * 60)  # 02:00 to midnight exactly
    assert counted == [2, 3, 4] and _day(ctx) == 4


def test_whole_party_rest_passes_its_days_keeping_the_time(ctx, party, counted):
    sessions.set_time(ctx, 21, 30)
    out = characters.rest(ctx, days=3)
    assert counted == [2, 3, 4] and out["days_passed"] == 3 and out["date"] == "Day 4"
    state = ctx.storage.campaign_states.get(ctx.campaign_id)
    assert (state.day, state.hour, state.minute) == (4, 21, 30)

    alone = characters.rest(ctx, "Pippa", days=2)  # one character resting doesn't move the clock
    assert "days_passed" not in alone and counted == [2, 3, 4] and _day(ctx) == 4
    characters.rest(ctx, days=0)  # nor does a party's rest of no days
    assert counted == [2, 3, 4]


def test_advance_days_tool(call, campaign, counted):
    out = call("advance_days", days=5, reason="waiting for the caravan")
    assert out["days_passed"] == 5 and out["day"] == 6 and out["date"] == "Day 6" and out["time"] == "06:00"
    assert out["count"]["days"] == [2, 3, 4, 5, 6]
    assert call("advance_days", days=0)["error"].startswith("Bad arguments")
    assert call("calendar") == {"date": "Day 6", "season": "Spring", "festival": False, "day": 6}


def test_rest_tool_passes_the_days(call, party, counted):
    call("rest", days=2)
    assert counted == [2, 3]
    call("rest", character="Garrek", days=2)
    assert counted == [2, 3]


def test_the_year_rolls_over(greyhawk, counted):
    """28 Sunsebb 576 is the last day of the year; the next one is Needfest's first."""
    ctx = greyhawk
    state = ctx.storage.campaign_states.get(ctx.campaign_id)
    ctx.storage.campaign_states.put(replace(state, start_date=StartDate(576, 364)))
    assert days.today(ctx).label == "28 Sunsebb 576 CY"
    out = days.pass_days(ctx, 1)
    assert out["date"].label == "Needfest, day 1, 577 CY"
    assert (out["date"].year, out["date"].day_of_year, out["date"].festival) == (577, 1, True)
    assert days.pass_days(ctx, 364)["date"].label == "Needfest, day 1, 578 CY"
    assert counted == list(range(2, 367))


def test_start_date_defaults_to_the_calendar_and_is_kept(greyhawk):
    ctx = greyhawk
    assert days.today(ctx).label == "1 Planting 576 CY"
    assert ctx.storage.campaign_states.get(ctx.campaign_id).start_date is None  # reading never writes
    days.pass_days(ctx, 3)
    assert ctx.storage.campaign_states.get(ctx.campaign_id).start_date == StartDate(576, 99)
    assert days.today(ctx).label == "4 Planting 576 CY"


def test_season_derived_from_the_date(greyhawk, ctx):
    assert days.today(greyhawk).season == "Low summer" and days.today(greyhawk).weather_season == "summer"
    days.pass_days(greyhawk, 84)  # 1 Planting + 84 days: Richfest, day 1
    today = days.today(greyhawk)
    assert (today.label, today.season, today.festival) == ("Richfest, day 1, 576 CY", "Midsummer", True)
    days.pass_days(greyhawk, 7 + 84)  # past Richfest and the three months of high summer: Brewfest
    assert days.today(greyhawk).season == "Autumn" and days.today(greyhawk).weather_season == "autumn"


def test_plain_calendar_without_a_setting(ctx):
    """A campaign without a setting reads "Day 12", in four seasons of 91 days."""
    assert days.calendar(ctx).id == "plain"
    days.pass_days(ctx, 11)
    assert days.today(ctx).label == "Day 12" and days.today(ctx).season == "Spring"
    days.pass_days(ctx, 91)
    assert days.today(ctx).season == "Summer"


def test_pass_days_is_one_transaction(ctx, monkeypatch):
    """A hook that fails on the third day leaves the day where it was."""

    def failing(ctx, day):
        if day == 4:
            raise PlayError("the clocks jammed")
        return {}

    monkeypatch.setitem(days.HOOKS, "failing", failing)
    with pytest.raises(PlayError):
        days.pass_days(ctx, 5)
    assert _day(ctx) == 1


def test_more_than_ten_years_at_once_is_refused(ctx, call, counted):
    with pytest.raises(PlayError, match="3650"):
        days.pass_days(ctx, days.MAX_DAYS + 1)
    assert _day(ctx) == 1 and counted == []
    for tool, args in (
        ("advance_days", {"days": 3651}),
        ("advance_time", {"minutes": 3650 * 1440 + 1}),
        ("rest", {"days": 3651}),
    ):
        assert call(tool, **args)["error"].startswith("Bad arguments"), tool
    assert call("advance_days", days=3650)["day"] == 3651


def test_days_passed_is_logged(ctx):
    days.pass_days(ctx, 2, reason="the road")
    [event] = [e for e in ctx.storage.events.recent(ctx.campaign_id, 10) if e.type == "days"]
    assert event.data == {"days": 2, "day": 3, "date": "Day 3", "reason": "the road"}
