from delve.domain.campaigns import CAMPAIGN_STATUSES, CampaignState
from delve.domain.characters import Sheet
from delve.domain.conversions import Conversion
from delve.domain.world import (
    PLAIN_CALENDAR,
    TILE_SIZE,
    Calendar,
    CampaignWorldMap,
    Clock,
    ImagePortrait,
    Journey,
    Month,
    Possession,
    Quest,
    QuestNote,
    StartDate,
    TraitsPortrait,
    Weather,
    WorldKnowledge,
    WorldMapSource,
    WorldPicture,
    WorldPosition,
)

# The Common Year as Task 3 declares it: 364 days, the festivals 7 days long.
COMMON_YEAR = Calendar(
    id="greyhawk",
    era="CY",
    months=(
        Month("Needfest", 7, "Midwinter", "winter", festival=True),
        Month("Fireseek", 28, "Winter", "winter"),
        Month("Readying", 28, "Spring", "spring"),
        Month("Coldeven", 28, "Spring", "spring"),
        Month("Growfest", 7, "Spring", "spring", festival=True),
        Month("Planting", 28, "Low summer", "summer"),
        Month("Flocktime", 28, "Low summer", "summer"),
        Month("Wealsun", 28, "Low summer", "summer"),
        Month("Richfest", 7, "Midsummer", "summer", festival=True),
        Month("Reaping", 28, "High summer", "summer"),
        Month("Goodmonth", 28, "High summer", "summer"),
        Month("Harvester", 28, "High summer", "summer"),
        Month("Brewfest", 7, "Autumn", "autumn", festival=True),
        Month("Patchwall", 28, "Autumn", "autumn"),
        Month("Ready'reat", 28, "Autumn", "autumn"),
        Month("Sunsebb", 28, "Winter", "winter"),
    ),
    default_start=(576, 99),
)


def test_campaign_day_one_is_the_start_date():
    assert COMMON_YEAR.days_in_year == 364
    first = COMMON_YEAR.date((576, 99), 1)
    assert (first.year, first.day_of_year, first.month, first.day_of_month) == (576, 99, "Planting", 1)
    assert (first.season, first.weather_season, first.festival) == ("Low summer", "summer", False)
    assert first.label == "1 Planting 576 CY"
    assert COMMON_YEAR.date((576, 99), 4).label == "4 Planting 576 CY"


def test_the_year_rolls_over():
    assert COMMON_YEAR.date((576, 99), 266).label == "28 Sunsebb 576 CY"
    new_year = COMMON_YEAR.date((576, 99), 267)
    assert (new_year.year, new_year.day_of_year, new_year.month, new_year.day_of_month) == (577, 1, "Needfest", 1)
    assert new_year.label == "Needfest, day 1, 577 CY", "a festival day reads as the festival"
    assert new_year.festival and new_year.season == "Midwinter"
    assert COMMON_YEAR.date((576, 99), 267 + 364).year == 578


def test_a_festival_day_reads_as_the_festival():
    richfest = COMMON_YEAR.date((576, 99), 1 + 28 * 3 + 3)
    assert richfest.label == "Richfest, day 4, 576 CY" and richfest.festival


def test_the_plain_calendar():
    assert PLAIN_CALENDAR.days_in_year == 364
    day = PLAIN_CALENDAR.date(PLAIN_CALENDAR.default_start, 12)
    assert day.label == "Day 12" and day.season == PLAIN_CALENDAR.months[0].season
    assert PLAIN_CALENDAR.date(PLAIN_CALENDAR.default_start, 92).season == PLAIN_CALENDAR.months[1].season
    assert PLAIN_CALENDAR.date(PLAIN_CALENDAR.default_start, 400).label == "Day 400"
    assert [m.weather_season for m in PLAIN_CALENDAR.months] == ["spring", "summer", "autumn", "winter"]


def test_portraits_keep_their_two_shapes():
    traits = TraitsPortrait(describe="a stern dwarf", seed="chr_000000000001")
    assert traits.to_dict() == {"kind": "traits", "describe": "a stern dwarf", "seed": "chr_000000000001"}
    image = ImagePortrait(image_id="img_000000000001")
    assert image.to_dict() == {"kind": "image", "image_id": "img_000000000001"}

    sheet = Sheet(portrait=traits, faction="circle")
    assert Sheet.from_dict(sheet.to_dict()) == sheet
    assert Sheet.from_dict(Sheet(portrait=image).to_dict()).portrait == image
    assert Sheet().portrait is None and Sheet().faction == ""


def test_campaign_state_keeps_its_world():
    state = CampaignState(
        "cmp_000000000001",
        start_date=StartDate(576, 99),
        weather=(Weather(3, "forest", "light rain", "-1 to missiles", 0.75),),
        world=WorldPosition("greyhawk-region", 12.5, 40.0, at="Greyhawk"),
    )
    assert CampaignState.from_dict(state.to_dict()) == state
    assert state.to_dict()["start_date"] == {"year": 576, "day_of_year": 99}
    assert state.start_date.as_tuple() == (576, 99)
    fresh = CampaignState("cmp_000000000001")
    assert (fresh.start_date, fresh.weather, fresh.world) == (None, (), None)


def test_world_records_round_trip():
    quest = Quest(
        "cmp_000000000001",
        "rescue",
        "Rescue the miller",
        log=(QuestNote(2, "The miller was taken north.", known=True), QuestNote(3, "SECRET", known=False)),
        related=("npc:miller",),
    )
    assert Quest.from_dict(quest.to_dict()) == quest
    clock = Clock(0, "cmp_000000000001", "The orcs march", "countdown", days_remaining=3, on_complete="Hardby falls")
    assert Clock.from_dict(clock.to_dict()) == clock
    horse = Possession("cmp_000000000001", "pos_horse", "Bramble", "mount", stats={"species": "riding-horse", "mv": 24})
    assert Possession.from_dict(horse.to_dict()) == horse
    assert WorldMapSource.from_dict({"name": "region", "title": "The region", "dsl": "workspace {}"}).to_dict() == {
        "name": "region",
        "title": "The region",
        "dsl": "workspace {}",
        "geo": None,
        "picture": None,
        "status": "ready",
        "reading": None,
    }


def test_world_knowledge_writes_its_cells_as_runs():
    knowledge = WorldKnowledge(cells=(1, 2, 3, 7), features=("greyhawk",))
    assert knowledge.to_dict() == {
        "everything": False,
        "cells": [[1, 4], [7, 8]],
        "features": ["greyhawk"],
        "forgotten": [],
    }
    assert WorldKnowledge.from_dict(knowledge.to_dict()) == knowledge
    assert WorldKnowledge.from_dict({"cells": [[7, 8], [1, 4]]}).cells == (1, 2, 3, 7), "read back sorted"
    assert WorldKnowledge.from_dict(WorldKnowledge(cells=(3, 1, 2, 2)).to_dict()).cells == (1, 2, 3)
    assert WorldKnowledge().to_dict()["cells"] == [] and WorldKnowledge.from_dict({}) == WorldKnowledge()


def test_a_plateau_6_position_reads_as_map_units():
    old = WorldPosition.from_dict({"map": "greyhawk-region", "x": 12.5, "y": 40.0, "at": "Greyhawk"})
    assert old.km is False and WorldPosition("flanaess", 1.0, 2.0).km is False
    assert WorldPosition.from_dict(WorldPosition("flanaess", 1.0, 2.0, km=True).to_dict()).km is True


def test_campaign_world_map_and_journey_round_trip():
    world_map = CampaignWorldMap(
        "cmp_000000000001",
        "flanaess",
        "The Flanaess",
        "setting",
        "",
        geo={"type": "FeatureCollection", "features": []},
        picture="a" * 64,
        status="review",
        knowledge=WorldKnowledge(cells=(4, 5), features=("hardby",)),
        reading={"doubts": []},
    )
    assert CampaignWorldMap.from_dict(world_map.to_dict()) == world_map
    assert world_map.to_dict()["knowledge"]["cells"] == [[4, 6]]
    assert CampaignWorldMap("cmp_000000000001", "region", "Region", "module", "workspace {}").knowledge is None
    journey = Journey("flanaess", "foot", "hardby", None, ((1.0, 2.0), (3.0, 4.0)), 2.8)
    state = CampaignState("cmp_000000000001", journey=journey)
    assert CampaignState.from_dict(state.to_dict()) == state
    assert (journey.done_km, journey.by, journey.planned_on, journey.miles_per_day) == (0.0, (), "", 0.0)
    picture = WorldPicture("b" * 64, "image/png", 512, 300, 2, {"0/0/0": "c" * 64})
    assert WorldPicture.from_dict(picture.to_dict()) == picture and TILE_SIZE == 256


def test_campaign_statuses_and_a_conversion():
    assert CAMPAIGN_STATUSES == ("in_progress", "paused", "complete")
    conversion = Conversion("cnv_000000000001", "book-map", "The caves", "draft")
    assert (conversion.target, conversion.result, conversion.questions) == (None, None, None)
