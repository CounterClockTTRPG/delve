"""`play.weather` (plan 6 Task 4, Decision 3): one roll per day and terrain, on ttrpg2's tables unchanged, rolled the
first time it is asked for and kept for the day. forest, hills, plains and ocean use the wilderness table, so every
encounter terrain has weather, and the weather's pace slows travel: a blizzard is 0."""

from dataclasses import replace

import pytest

from delve.dice import SeededRng
from delve.dm.tools import ToolHost
from delve.domain.world import StartDate
from delve.play import days, sessions, weather
from delve.play.context import PlayError, context_for
from delve.rules.classic import weather_tables
from tests.fixtures.play_reference import PlayReference
from tests.fixtures.rulesets import over
from tests.fixtures.settings import GreyhawkSetting
from tests.play.conftest import crypt_campaign

TERRAINS = (
    "arctic", "desert", "dungeon", "forest", "hills", "jungle", "mountain",
    "ocean", "plains", "road", "swamp", "urban", "wilderness",
)  # fmt: skip


@pytest.fixture
def campaign(storage):
    """A campaign without a setting: the plain calendar's "Day N"."""
    return crypt_campaign(storage, setting="")


def _rolls(ctx) -> list:
    return [roll for roll in ctx.storage.rolls.list(ctx.campaign_id) if roll.key.purpose.startswith("weather")]


def test_ttrpg2_tables_unchanged():
    """A few rows of ttrpg2's tables, its splices and its dungeon table, and the pace list in its order."""
    assert weather_tables.TABLES["spring"]["wilderness"][0] == (5, "clear", "Light wind. No effect.")
    assert weather_tables.TABLES["winter"]["wilderness"][4] == (
        2,
        "blizzard",
        "Travel impossible. Shelter required. Frostbite risk per hour exposed.",
    )
    assert sorted(weather_tables.TABLES["summer"]) == sorted(
        ["wilderness", "desert", "arctic", "swamp", "mountain", "jungle", "urban", "road"]
    )
    assert sum(w for w, _, _ in weather_tables.TABLES["winter"]["arctic"]) == 20
    assert weather_tables.DUNGEON_TABLE[0] == (10, "stale air", "No effect.")
    assert [needle for needle, _ in weather_tables.PACE][:2] == ["blizzard", "thunderstorm"]
    assert sorted(weather_tables.TERRAIN_TABLE) == sorted(TERRAINS)


def test_every_terrain_has_weather(make_ctx):
    for season in weather_tables.SEASONS:
        for terrain in TERRAINS:
            assert weather_tables.table(season, terrain), (season, terrain)
    ctx = make_ctx(seed=3)
    for terrain in TERRAINS:
        rolled = weather.weather(ctx, terrain)
        assert rolled.terrain == terrain and rolled.label and rolled.day == 1
    assert {w.terrain for w in ctx.storage.campaign_states.get(ctx.campaign_id).weather} == set(TERRAINS)


def test_the_same_day_asked_twice_rolls_once(make_ctx):
    first = weather.weather(make_ctx(seed=1, beat="beat-1"), "road")
    again = weather.weather(make_ctx(seed=2, beat="beat-2"), "road")  # another beat, other dice
    assert again == first
    assert len(_rolls(make_ctx())) == 1
    [roll] = _rolls(make_ctx())
    assert roll.notation == "1d20" and roll.key.purpose == "weather:road:day 1"


def test_a_new_day_rolls_anew(make_ctx):
    ctx = make_ctx(seed=5)
    weather.weather(ctx, "plains")
    days.pass_days(ctx, 1)
    state = ctx.storage.campaign_states.get(ctx.campaign_id)
    assert [(w.day, w.terrain) for w in state.weather] == [(1, "plains")]  # yesterday's, kept for its terrain
    today = weather.weather(ctx)  # the terrain defaults to the last one rolled
    assert (today.day, today.terrain) == (2, "plains")
    assert [w.day for w in ctx.storage.campaign_states.get(ctx.campaign_id).weather] == [2]
    assert len(_rolls(ctx)) == 2


def test_weighted_pick_over_the_table(make_ctx):
    """Spring wilderness weighs 5 clear, 4 overcast, 5 light rain, 3 heavy rain, 1 thunderstorm, 2 morning fog: a 1d20
    of 14 is light rain, of 18 the thunderstorm."""
    assert weather.weather(make_ctx(14), "wilderness").label == "light rain"
    ctx = make_ctx(18, beat="beat-2")
    days.pass_days(ctx, 1)
    storm = weather.weather(ctx, "wilderness")
    assert (storm.label, storm.pace) == ("thunderstorm", 0.0)
    assert storm.effect.startswith("Travel impossible.")


def test_defaults_to_wilderness_and_refuses_an_unknown_terrain(make_ctx):
    ctx = make_ctx(1)
    assert weather.weather(ctx).terrain == "wilderness"
    assert weather.weather(make_ctx(1), "Mountains").terrain == "mountain"  # the encounter tables' aliases
    with pytest.raises(PlayError) as refused:
        weather.weather(make_ctx(), "moon")
    assert "wilderness" in refused.value.hint


def test_pace():
    assert weather.pace("blizzard") == 0.0
    assert weather.pace("sudden blizzard") == 0.0
    assert weather.pace("heavy snow") == 0.5
    assert weather.pace("freezing fog") == 0.7  # before "fog"
    assert weather.pace("dense fog") == 0.85
    assert weather.pace("freezing rain") == 0.9
    assert weather.pace("clear") == 1.0


def test_a_blizzard_has_pace_0(make_ctx):
    """Winter wilderness: 3 clear cold, 3 overcast cold, 4 light snow, 3 heavy snow, 2 blizzard: 14 is a blizzard."""
    ctx = make_ctx(14)
    ctx.setting = GreyhawkSetting()
    state = ctx.storage.campaign_states.get(ctx.campaign_id)
    ctx.storage.campaign_states.put(replace(state, start_date=StartDate(576, 350)))  # in Sunsebb
    blizzard = weather.weather(ctx, "hills")
    assert (blizzard.label, blizzard.pace) == ("blizzard", 0.0)


def test_weather_check_and_calendar_tools(storage, campaign):
    host = ToolHost(storage, lambda: SeededRng(9), catalogs=over(PlayReference()))
    out = host.call(campaign.id, "beat-1", "weather_check", {"terrain": "road"})
    assert set(out) == {"date", "season", "terrain", "weather", "effect", "pace"}
    assert (out["date"], out["season"], out["terrain"]) == ("Day 1", "Spring", "road")
    assert host.call(campaign.id, "beat-2", "weather_check", {}) == out
    assert host.call(campaign.id, "beat-2", "weather_check", {"terrain": "moon"})["error"]
    assert host.spec("weather_check").player_visible and host.spec("weather_check").mutates
    assert host.spec("calendar").player_visible and not host.spec("calendar").mutates
    assert host.spec("advance_days").player_visible and host.spec("advance_days").mutates


def test_primer_has_the_date_and_the_weather(make_ctx):
    ctx = make_ctx(seed=4)
    primer = sessions.primer(ctx)
    assert primer["date"] == days.today(ctx).to_dict()
    assert primer["weather"]["terrain"] == "wilderness" and primer["weather"]["label"]
    assert sessions.primer(ctx)["weather"] == primer["weather"]  # rolled once


def test_no_weather_for_a_campaign_deleted_while_read(storage, campaign):
    """A campaign deleted while its table state is read (the play state's read from a tab still open) has no
    weather, rather than a 500."""
    ctx = context_for(storage, campaign.id, "beat-1", SeededRng(1), catalogs=over(PlayReference()))
    storage.campaigns.delete(campaign.id)
    assert weather.current(ctx) is None
