"""The world outside the dungeon (plateau 6): the calendar and the date, the day's weather, the party's place on a
world map, factions with their clocks, quests, the campaign's own lore facts, possessions, portraits, world maps,
merchants and the campaign's generated images.

Every record of a campaign table carries its `campaign_id`. A campaign day is a whole number from 1; the date is
derived from it and the campaign's start date by the setting's calendar, never set by hand.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Literal

from delve.domain import data
from delve.domain.reference import LoreFact  # noqa: F401 (re-exported: a setting's fact; a campaign's is CampaignFact)

WorldMapStatus = Literal["ready", "review"]
"""`review` while the organiser hasn't yet accepted what Delve read from a picture; such a map is never played on."""


@dataclass(frozen=True)
class WorldMapSource:
    """A world map, as a module or a setting carries it: in ttrpg2's `.map` language (`dsl`), or (plateau 7) as a
    Delve GeoJSON document (`geo`) over an optional base picture (`picture`, a `WorldPicture` id). `reading` is what
    Delve read from the picture, kept for the review."""

    name: str
    title: str
    dsl: str
    geo: dict[str, Any] | None = None
    picture: str | None = None
    status: WorldMapStatus = "ready"
    reading: dict[str, Any] | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> WorldMapSource:
        return data.from_dict(cls, raw)

    def to_dict(self) -> dict[str, Any]:
        return data.to_dict(self)


class _Record:
    """`from_dict` and `to_dict` for the frozen dataclasses below."""

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Any:
        return data.from_dict(cls, raw)

    def to_dict(self) -> dict[str, Any]:
        return data.to_dict(self)


@dataclass(frozen=True)
class Month(_Record):
    """A month of a calendar, or a festival week (`festival`), with the setting's season and the weather table's
    season (spring, summer, autumn or winter)."""

    name: str
    days: int
    season: str
    weather_season: str
    festival: bool = False


@dataclass(frozen=True)
class GameDate(_Record):
    """A campaign day as a date of its calendar. `label` is how it reads: "4 Planting 576 CY", "Richfest, day 4,
    576 CY", or "Day 12" on the plain calendar."""

    year: int
    day_of_year: int
    month: str
    day_of_month: int
    season: str
    weather_season: str
    festival: bool
    label: str


@dataclass(frozen=True)
class Calendar(_Record):
    """A setting's calendar: its months in order, from the first day of the year. `default_start` is the
    `(year, day_of_year)` a campaign starts on when it was given none. A calendar without an `era` labels a date by
    the campaign day alone ("Day 12")."""

    id: str
    era: str
    months: tuple[Month, ...]
    default_start: tuple[int, int] = (1, 1)

    @property
    def days_in_year(self) -> int:
        return sum(month.days for month in self.months)

    def date(self, start: tuple[int, int], day: int) -> GameDate:
        """The date of campaign day `day` (from 1), campaign day 1 being `start`, `(year, day_of_year)`."""
        year, day_of_year = start
        offset = day_of_year - 1 + day - 1
        year += offset // self.days_in_year
        day_of_year = offset % self.days_in_year + 1
        left = day_of_year
        for month in self.months:
            if left <= month.days:
                break
            left -= month.days
        if not self.era:
            label = f"Day {day}"
        elif month.festival and month.days == 1:
            label = f"{month.name}, {year} {self.era}"
        elif month.festival:
            label = f"{month.name}, day {left}, {year} {self.era}"
        else:
            label = f"{left} {month.name} {year} {self.era}"
        return GameDate(year, day_of_year, month.name, left, month.season, month.weather_season, month.festival, label)


PLAIN_CALENDAR = Calendar(
    id="plain",
    era="",
    months=(
        Month("Spring", 91, "Spring", "spring"),
        Month("Summer", 91, "Summer", "summer"),
        Month("Autumn", 91, "Autumn", "autumn"),
        Month("Winter", 91, "Winter", "winter"),
    ),
)
"""The calendar of a campaign without a setting: four seasons of 91 days, and dates read "Day 12"."""


@dataclass(frozen=True)
class StartDate(_Record):
    """The date a campaign's day 1 is, as `CampaignState.start_date`."""

    year: int
    day_of_year: int

    def as_tuple(self) -> tuple[int, int]:
        return (self.year, self.day_of_year)


@dataclass(frozen=True)
class Weather(_Record):
    """The weather of one campaign day in one terrain, rolled once: its table's `label`, its `effect` in words, and
    `pace`, the multiplier it puts on a day's travel (0 for a blizzard)."""

    day: int
    terrain: str
    label: str
    effect: str = ""
    pace: float = 1.0


@dataclass(frozen=True)
class WorldPosition(_Record):
    """Where the party is on a world map: a point of the map `map`, and the feature it is at, if any. With `km`, `x`
    and `y` are km on the map's geo document; without, a plateau 6 point in the `.map`'s own units."""

    map: str
    x: float
    y: float
    at: str | None = None
    km: bool = False


def _runs(cells: tuple[int, ...]) -> list[list[int]]:
    """Cell numbers as sorted half-open runs: `(1, 2, 3, 7)` is `[[1, 4], [7, 8]]`."""
    runs: list[list[int]] = []
    for cell in sorted(set(cells)):
        if runs and runs[-1][1] == cell:
            runs[-1][1] = cell + 1
        else:
            runs.append([cell, cell + 1])
    return runs


def _cells(runs: Any) -> tuple[int, ...]:
    """The cell numbers of half-open runs, sorted; `DataError` for anything that isn't a list of `[start, stop]`."""
    if isinstance(runs, str | bytes | dict) or not hasattr(runs, "__iter__"):
        raise data.DataError("cells", f"expected a list of [start, stop] runs, got {runs!r}")
    cells: set[int] = set()
    for i, run in enumerate(runs):
        if (
            not isinstance(run, list | tuple)
            or len(run) != 2
            or not all(isinstance(n, int) and not isinstance(n, bool) for n in run)
            or not 0 <= run[0] < run[1]
        ):
            raise data.DataError(f"cells[{i}]", f"expected a run [start, stop) of cell numbers, got {run!r}")
        cells.update(range(run[0], run[1]))
    return tuple(sorted(cells))


@dataclass(frozen=True)
class WorldKnowledge:
    """What the party knows of a world map: everything, or the grid cells it knows (by number, row by row) and the
    features it knows; `forgotten` are the features the DM made it forget. Stored with `cells` as sorted runs."""

    everything: bool = False
    cells: tuple[int, ...] = ()
    features: tuple[str, ...] = ()
    forgotten: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> WorldKnowledge:
        cells = _cells(raw["cells"]) if "cells" in raw else ()
        return data.from_dict(cls, {**raw, "cells": list(cells)})

    def to_dict(self) -> dict[str, Any]:
        return {**data.to_dict(self), "cells": _runs(self.cells)}


@dataclass(frozen=True)
class Journey(_Record):
    """The party's journey on a world map, by `mode`, to the place `to` (`to_label` as the DM named it), along
    `points` (km), `km` long, of which `done_km` is behind it. `by` are the possessions that carry it. `planned_on`
    is the digest of the map's geo document when the route was planned; a leg that goes on is planned again from
    where the party is, so an edited map is followed. `miles_per_day` is the DM's house-rule pace, 0 for the
    table's."""

    map: str
    mode: str
    to: str
    to_label: str | None
    points: tuple[tuple[float, float], ...]
    km: float
    done_km: float = 0.0
    by: tuple[str, ...] = ()
    planned_on: str = ""
    miles_per_day: float = 0.0


TILE_SIZE = 256
"""The side of a picture's tile, in pixels."""


MonsterPictureStatus = Literal["painting", "done", "failed"]


@dataclass(frozen=True)
class MonsterPicture(_Record):
    """A kind of monster's picture, for every campaign of the install (DEL-275): the initiative strip's face for an enemy
    of that kind, and the Rulesets' monster entry's. `slug` is the kind's (`delve.play.monster_pictures.slug`), `name`
    as it was first asked for. `source` is `seeded` (the owner's own paintings, loaded by `delve monster-pictures
    seed`) or `painted` (asked for by an organiser). While `painting`, a repaint, it keeps the `blob` it had, which is
    still shown; `failed` keeps it too, with the `error`. Storage sets `created_at` and `updated_at`."""

    slug: str
    name: str
    status: MonsterPictureStatus = "done"
    blob: str | None = None
    mime: str | None = None
    source: str = "painted"
    prompt: str = ""
    error: str | None = None
    created_at: str = ""
    updated_at: str = ""


@dataclass(frozen=True)
class WorldPicture(_Record):
    """A world map's base picture, cut into tiles: `id` is the original's sha256, `tiles` the blob sha of each tile
    by `"z/x/y"`, from zoom 0 to `max_zoom`. Storage sets `created_at`."""

    id: str
    mime: str
    width_px: int
    height_px: int
    max_zoom: int
    tiles: dict[str, str]
    created_at: str = ""


@dataclass(frozen=True)
class TraitsPortrait(_Record):
    """A portraitgen portrait: a description and a seed, which the browser draws. Free and instant. One a player
    edited in portraitgen's editor (DEL-238) also has its `traits`, checked (`portrait_traits.checked`), which the
    browser draws instead; `describe` stays the sheet's, for a painter. Without them, the dict has no `traits` key."""

    describe: str
    seed: str
    kind: Literal["traits"] = "traits"
    traits: dict[str, Any] | None = field(default=None, metadata={data.OMIT_IF_NONE: True})


@dataclass(frozen=True)
class ImagePortrait(_Record):
    """A painted portrait: the campaign image that holds it."""

    image_id: str
    kind: Literal["image"] = "image"


Portrait = TraitsPortrait | ImagePortrait
"""`{"kind": "traits", "describe", "seed", "traits"?}` or `{"kind": "image", "image_id"}`."""


@dataclass(frozen=True)
class Faction(_Record):
    """A faction of the campaign. `strength` is 0–100, `reputation` the party's standing with it, −100 … 100.
    `notes_md`, the strength and the reputation number are DM-only; players see a known faction's standing word.
    `source_ref` is the module entity it was seeded from (`faction:<id>`)."""

    campaign_id: str
    id: str
    name: str
    alignment: str = ""
    goals: str = ""
    scope: str = ""
    known: bool = False
    strength: int = 100
    reputation: int = 0
    notes_md: str = ""
    source_ref: str | None = None


ClockKind = Literal["countdown", "progress"]
CLOCK_KINDS: tuple[ClockKind, ...] = ("countdown", "progress")


@dataclass(frozen=True)
class Clock(_Record):
    """A clock, DM-only. A `countdown` loses a day with each day that passes (`days_remaining`); a `progress` clock
    fills its `segments` only when the DM advances it. `done_day` is the day it completed; a clock without one is
    running. `id` is given by storage (0 before it is added)."""

    id: int
    campaign_id: str
    label: str
    kind: ClockKind
    faction_id: str | None = None
    days_remaining: int | None = None
    segments: int | None = None
    filled: int | None = None
    on_complete: str = ""
    started_day: int = 1
    done_day: int | None = None


QuestStatus = Literal["available", "active", "paused", "complete", "failed"]
QUEST_STATUSES: tuple[QuestStatus, ...] = ("available", "active", "paused", "complete", "failed")


@dataclass(frozen=True)
class QuestNote(_Record):
    """A line of a quest's log; players see it only when `known`."""

    day: int
    text: str
    known: bool = True


@dataclass(frozen=True)
class Quest(_Record):
    """A quest. Players see it only once it is `known`, and then its title, status, giver, stakes and known notes;
    `notes_md` is DM-only. `related` are entity refs (`npc:miller`)."""

    campaign_id: str
    id: str
    title: str
    giver: str = ""
    scope: str = "local"
    stakes: str = ""
    status: QuestStatus = "available"
    known: bool = False
    started_day: int | None = None
    ended_day: int | None = None
    related: tuple[str, ...] = ()
    log: tuple[QuestNote, ...] = ()
    notes_md: str = ""
    source_ref: str | None = None


@dataclass(frozen=True)
class CampaignFact(_Record):
    """A lore fact of the campaign's own, written by the DM on campaign day `day`. DM-only. `id` is given by storage
    (0 before it is added)."""

    id: int
    campaign_id: str
    text: str
    category: str = ""
    day: int = 1


PossessionKind = Literal["mount", "vehicle", "ship", "house", "stronghold", "domain", "other"]
POSSESSION_KINDS: tuple[PossessionKind, ...] = ("mount", "vehicle", "ship", "house", "stronghold", "domain", "other")


@dataclass(frozen=True)
class Possession(_Record):
    """Something a character owns, or the party (`owner_id` None): a mount, a ship, a house. `stats` are a mount's
    `{species, hp, hp_max, ac, mv, fly, thac0, attacks, morale}`, a vehicle's or ship's `{mv, capacity}`, or any
    object. `notes_md` is DM-only. Storage sets `created_at` and `updated_at`."""

    campaign_id: str
    id: str
    name: str
    kind: PossessionKind
    owner_id: str | None = None
    location: str = ""
    value_gp: int = 0
    description: str = ""
    notes_md: str = ""
    inventory: tuple[str, ...] = ()
    stats: dict[str, Any] = field(default_factory=dict)
    portrait: Portrait | None = None
    created_at: str = ""
    updated_at: str = ""


WorldMapOrigin = Literal["module", "setting", "campaign"]


@dataclass(frozen=True)
class CampaignWorldMap(_Record):
    """A campaign's own copy of a world map: copied from its module or its setting (`source`), or made in the
    campaign, and editable from then on. `revealed` names the `hidden` features players may now see. Storage sets
    `updated_at`. Plateau 7 adds `geo`, `picture`, `status` and `reading` as `WorldMapSource` has them, and
    `knowledge`, what the party knows of it (None: a `.map` not yet converted from `dsl`)."""

    campaign_id: str
    name: str
    title: str
    source: WorldMapOrigin
    dsl: str
    revealed: tuple[str, ...] = ()
    updated_at: str = ""
    geo: dict[str, Any] | None = None
    picture: str | None = None
    status: WorldMapStatus = "ready"
    reading: dict[str, Any] | None = None
    knowledge: WorldKnowledge | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> CampaignWorldMap:
        knowledge = raw.get("knowledge")
        world_map = data.from_dict(cls, {**raw, "knowledge": None})
        if knowledge is None:
            return world_map
        if not isinstance(knowledge, dict):
            raise data.DataError("knowledge", f"expected an object, got {knowledge!r}")
        return replace(world_map, knowledge=WorldKnowledge.from_dict(knowledge))

    def to_dict(self) -> dict[str, Any]:
        return {**data.to_dict(self), "knowledge": None if self.knowledge is None else self.knowledge.to_dict()}


@dataclass(frozen=True)
class Merchant(_Record):
    """A magic merchant and the shelf rolled for it on `rolled_day` with `seed`, kept until it is restocked. DM-only.
    `items` and `sold` are the shelf's entries, as the merchant tools write them."""

    campaign_id: str
    id: str
    name: str
    npc_id: str | None = None
    settlement: str = "pedlar"
    cost: str = "moderate"
    seed: int = 0
    rolled_day: int = 1
    items: tuple[dict[str, Any], ...] = ()
    sold: tuple[dict[str, Any], ...] = ()


ImageKind = Literal["portrait", "scene", "possession", "banner"]
ImageStatus = Literal["waiting", "painting", "done", "failed"]


@dataclass(frozen=True)
class CampaignImage(_Record):
    """A paid image of the campaign: a portrait or a possession's picture of `subject_id`, a scene, or the campaign's
    banner. A `waiting` banner is asked for and held back by the paid gate. While `painting` it has no `blob`; once `done`, `blob` is its sha256 in the blob store. `audience` is a story entry's
    (None: everyone). `attempts` counts the times the picture was asked of a provider, so one cut short by a restart is
    asked for again once; `provider_job` is the provider's own job for it (assetgen's), followed again after a
    restart rather than counted, and `queue` its place in the provider's queue while it waits there (DEL-138).
    Storage sets `created_at`."""

    id: str
    campaign_id: str
    kind: ImageKind
    subject_id: str | None = None
    status: ImageStatus = "painting"
    blob: str | None = None
    mime: str | None = None
    prompt: str = ""
    caption: str = ""
    """A scene's line under the image, for its story entry once painted."""
    backend: str = ""
    audience: dict[str, list[str]] | None = None
    error: str | None = None
    attempts: int = 0
    provider_job: str | None = None
    queue: int | None = None
    created_at: str = ""
