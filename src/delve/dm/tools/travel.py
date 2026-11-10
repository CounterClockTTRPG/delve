"""Travel (ttrpg2 `tools/travel.py`): the party crosses a world map by a mode, a leg at a time, each day passing as
every new day does. Its result's `clocks` are the DM's. `route` shows the way a leg would take, without travelling."""

from __future__ import annotations

from typing import Any

from delve.dm.tools.party import CLOCKS
from delve.dm.tools.schema import ToolSpec, boolean, params, string, strings, tool
from delve.maps.geo.routing import MODES
from delve.play import travel as play_travel
from delve.play.context import CampaignContext

SPECS: list[ToolSpec] = []

_MODE = string(
    "How: foot, horse (on horseback), cart, river (by river boat, along the rivers and lakes) or ship (over the sea "
    "and the large lakes; the mode alone hires passage).",
    enum=list(MODES),
)
_BY = strings(
    "The possessions they travel on, by id or exact name: mounts (for their owners), a vehicle, a boat or a ship "
    "(its stats' mph sets its speed)."
)
_MILES_PER_DAY = {
    "type": "number",
    "description": "A house rule's pace in miles a day, instead of the table's; 0 for the table's. The terrain, the "
    "roads and the weather still apply.",
    "minimum": 0,
    "maximum": 1000,
}


@tool(
    SPECS,
    "travel",
    params(
        to=string(
            "Where to: a place on the party's world map, by id or name, or 'x,y' in km. Empty: on with the journey "
            "under way."
        ),
        mode=_MODE,
        terrain=string(
            "The terrain for the weather and the encounters of every day: road, plains, wilderness, urban, forest, "
            "hills, desert, arctic, swamp, jungle, mountain or ocean (by boat only). Empty: the map's under each day's "
            "start."
        ),
        by=_BY,
        forced_march=boolean("Push on: 1.5 × the miles, on land; call for the Constitution checks yourself."),
        miles_per_day=_MILES_PER_DAY,
    ),
    mutates=True,
    areas=("characters", "world"),
    dm_only_keys=CLOCKS,
)
def travel(
    ctx: CampaignContext,
    to: str = "",
    mode: str = "foot",
    terrain: str = "",
    by: list[str] | None = None,
    forced_march: bool = False,
    miles_per_day: float = 0,
) -> dict[str, Any]:
    """One leg of a journey, by one mode: from the party's place to another by the cheapest route the mode allows
    (the roads on land, the rivers by river boat, the sea by ship), a day at a time. Each day the clocks tick and the
    date moves, the weather is rolled, the party covers the mode's miles × the terrain × the weather's pace, the land
    in sight becomes known, and one encounter is checked. Chain legs for a journey of several modes: ride to the port,
    then sail. An encounter stops the leg partway: narrate it, then go on with travel() and no destination. When a
    house rule changes a speed, pass its miles_per_day. Over 60 days, travel in legs. Answers each day's date,
    terrain, weather, miles and encounter, where the party is, the places that came into sight, the journey left,
    and the clocks that came due."""
    return play_travel.travel(
        ctx, to, mode=mode, terrain=terrain, by=by or (), forced_march=forced_march, miles_per_day=miles_per_day
    )


@tool(
    SPECS,
    "route",
    params("to", to=string("Where to: a place, by id or name, or 'x,y' in km."), mode=_MODE, by=_BY,
           miles_per_day=_MILES_PER_DAY),
    mutates=False,
    player_visible=False,
)  # fmt: skip
def route(
    ctx: CampaignContext, to: str, mode: str = "foot", by: list[str] | None = None, miles_per_day: float = 0
) -> dict[str, Any]:
    """The way one leg would take from the party's place, without travelling: its km and miles, the days at a clear
    day's pace, and its slowest stretches. Compare modes before you choose; a mode that can't get there is refused
    with the reason (an island on foot, an inland town by ship)."""
    return play_travel.route_preview(ctx, to, mode=mode, by=by or (), miles_per_day=miles_per_day)
