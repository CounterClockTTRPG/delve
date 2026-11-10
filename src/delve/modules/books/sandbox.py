"""Generating an open sandbox in steps (DEL-349): a region with a home base, places to go in any order, factions on
clocks, rumours (some false), secrets the party may never find, and ground left open for the DM to add to.

A request scoped as a `sandbox` (`campaign.scope_request`) is written like a campaign, in calls each well under a
conversion's limit (`generate_sandbox`):

1. **The outline** (`generate-sandbox-outline.md`): title, summary, party, the region's size in miles, its terrain
   areas and rivers, 6 to `MAX_SITES` sites (a letter, a kind, a point on the map, how many rooms), the routes between
   them (way, miles, danger), the factions and their clocks, the NPCs and where they are, 12 rumours with their truth,
   the secrets and their clues by site, the open ground and the road's wandering table.
2. **One call per site** (`generate-site.md`), `concurrency` at once, with its people, the clues to plant in it and
   the rumours about it: its keyed rooms (`B1`, `B2`…), a wandering table where something roams, and encounters. A
   site that can't be read twice is left out with a `site-not-written` warning; the others stand.
3. **The region's text** is written by Delve from the outline (`region_text`): how travel and the clocks work, the
   routes, the rumour table, the factions, the secrets (marked as never needed), the open ground and how to add a
   place to it, and the road's wandering monsters.
4. **The maps**: the region map, `region`, the module's default, is drawn by Delve from the outline's coordinates
   (`region_map`, miles to the square: terrain areas, rivers, roads and paths, a marker per site, the open ground
   outlined); then one sketched floor plan per site, `site-<letter>`, each site's text linked to its own. An exit at
   each site's marker leads to its first room, and one there leads back (`join_sites`).

The factions become `faction` records with their clock, the NPCs `npc` records, and each wandering table an
`encounter` record for its map (`where`), as a level's are. The progress steps are `planning`, `sites` (n of N) and
`maps` (n of N). An outline that can't be read twice fails the job with `GenerationError`.
"""

from __future__ import annotations

import asyncio
import itertools
import math
import re
from dataclasses import dataclass, field, replace
from typing import Any

from shapely.geometry import Point, Polygon

from delve.dice import Rng, SystemRng
from delve.domain.modules import ModuleMap
from delve.maps.dsl import walk
from delve.maps.dsl.geometry import node_centroid, room_polygon
from delve.maps.sources import parse_source
from delve.modules.books.campaign import (
    MAX_QUESTIONS,
    _anchored,
    _asked,
    _names,
    _numbered,
    _object,
    _quoted,
    _wandering,
    each_at_once,
    lettered,
)
from delve.modules.books.convert import Complete, Converted, Progress, Question, take_questions, text_id
from delve.modules.books.generate import GenerationError, Room, Unreadable, party_of, plan_entities, read_room, section
from delve.modules.books.repair import repair_refs
from delve.modules.books.sketch import GAME, design_map, fill, map_error, prompt, room_name
from delve.modules.source import ModuleSource, TextDoc, Warning
from delve.modules.text import unique

MAX_SITES = 10
"""The most sites an outline may give; more are left out."""
MAX_ROOMS = 12
"""The most rooms a site is asked for."""
CONCURRENCY = 3
"""How many sites, and maps, are written at once."""
REGION_MAP = "region"
"""The region map's name, the module's default."""

SANDBOX_KINDS = (("npcs", "npc"), ("factions", "faction"))
SITE_KINDS = (("encounters", "encounter"),)

_LETTER = re.compile(r"^[A-Z]$")
_ID = re.compile(r"^[a-z0-9][a-z0-9-]*$")

TERRAIN: dict[str, tuple[str | None, str]] = {
    "forest": (None, "#c9dbb5"),
    "hills": (None, "#e6d8b4"),
    "marsh": ("swamp", "#c3cdb0"),
    "water": ("water", "#a9c4d6"),
    "fields": (None, "#eef0d2"),
    "moor": (None, "#ddd3c4"),
    "mountains": (None, "#cfc7bb"),
}
"""Each terrain kind's area `kind` (None for a plain fill) and fill colour on the region map."""

PACE = {"road": 3.0, "track": 2.5, "path": 2.0, "none": 1.5}
"""Miles an hour on foot by the kind of way; a day's march is `DAY_HOURS`."""
DAY_HOURS = 8

WAYS = {"road": "road", "track": "track", "path": "path", "none": "cross-country"}


@dataclass(frozen=True)
class Site:
    letter: str
    name: str
    kind: str
    at: tuple[float, float]
    rooms: int
    summary: str
    home: bool = False

    @property
    def map_name(self) -> str:
        return f"site-{self.letter.lower()}"

    @property
    def title(self) -> str:
        return f"{self.letter}. {self.name}"


@dataclass(frozen=True)
class Route:
    start: str
    end: str
    way: str
    miles: float
    danger: int
    note: str


@dataclass(frozen=True)
class Outline:
    title: str
    summary: str
    party: dict[str, Any]
    intro: str
    size: tuple[int, int]
    terrain: list[dict[str, Any]]
    rivers: list[dict[str, Any]]
    sites: list[Site]
    routes: list[Route]
    factions: list[dict[str, Any]]
    npcs: list[dict[str, Any]]
    rumours: list[dict[str, Any]]
    secrets: list[dict[str, Any]]
    open_ground: list[dict[str, Any]]
    wandering: dict[str, Any]
    questions: list[Question] = field(default_factory=list)

    @property
    def home(self) -> Site:
        return next((s for s in self.sites if s.home), self.sites[0])

    def site(self, letter: str) -> Site | None:
        return next((s for s in self.sites if s.letter == letter), None)


@dataclass(frozen=True)
class _Written:
    site: Site
    intro: str
    rooms: list[Room]
    wandering: dict[str, Any]
    entities: dict[str, Any]


# ----- reading the outline -----


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _number(value: Any) -> float | None:
    return (
        float(value)
        if isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)
        else None
    )


def _point(raw: Any, size: tuple[int, int]) -> tuple[float, float] | None:
    """A point `[x, y]` inside the region, else None."""
    if not isinstance(raw, list | tuple) or len(raw) != 2:
        return None
    x, y = _number(raw[0]), _number(raw[1])
    if x is None or y is None:
        return None
    return (min(max(x, 0.0), float(size[0])), min(max(y, 0.0), float(size[1])))


def _points(raw: Any, size: tuple[int, int], least: int) -> list[tuple[float, float]]:
    points = [p for p in (_point(item, size) for item in (raw if isinstance(raw, list) else [])) if p is not None]
    return points if len(points) >= least else []


def _size(raw: Any) -> tuple[int, int]:
    region = raw if isinstance(raw, dict) else {}
    width, height = _number(region.get("width")), _number(region.get("height"))
    return (int(min(max(width or 24, 12), 48)), int(min(max(height or 18, 10), 36)))


def _site(raw: Any, size: tuple[int, int]) -> Site:
    if not isinstance(raw, dict):
        raise Unreadable("a site isn't a JSON object")
    letter = _text(raw.get("letter")).upper()
    if not _LETTER.match(letter):
        raise Unreadable(f"the site letter {raw.get('letter')!r} isn't one capital letter")
    name = _text(raw.get("name"))
    if not name:
        raise Unreadable(f"site {letter} has no name")
    at = _point(raw.get("at"), size)
    if at is None:
        raise Unreadable(f"site {letter} has no point on the map")
    rooms = raw.get("rooms")
    count = max(2, min(MAX_ROOMS, rooms)) if isinstance(rooms, int) else 5
    return Site(
        letter, name, _text(raw.get("kind")) or "place", at, count, _text(raw.get("summary")), raw.get("home") is True
    )


def _route(raw: Any, letters: set[str], sites: dict[str, Site]) -> Route | None:
    if not isinstance(raw, dict):
        return None
    start, end = _text(raw.get("from")).upper(), _text(raw.get("to")).upper()
    if start not in letters or end not in letters or start == end:
        return None
    way = _text(raw.get("way")).lower()
    way = way if way in PACE else "path"
    straight = math.dist(sites[start].at, sites[end].at)
    miles = max(_number(raw.get("miles")) or 0.0, round(straight, 1))
    danger = raw.get("danger")
    danger = max(1, min(5, danger)) if isinstance(danger, int) else 2
    return Route(start, end, way, miles, danger, _text(raw.get("note")))


def _records(raw: Any) -> list[dict[str, Any]]:
    return [item for item in (raw if isinstance(raw, list) else []) if isinstance(item, dict)]


GROUND_RADIUS = 1.5
"""The circle open ground is drawn as on the region map, in miles."""


def _clear_ground(
    at: tuple[float, float],
    size: tuple[int, int],
    sites: list[Site],
    rivers: list[dict[str, Any]],
    taken: list[tuple[float, float]],
) -> tuple[float, float]:
    """`at`, or the nearest point to it (in half-mile steps, up to 4 miles off) whose open-ground circle stays inside
    the map and clear of the sites, the rivers and the other open ground; `at` when there is none."""
    water = [
        (a[0] + (b[0] - a[0]) * t / 8, a[1] + (b[1] - a[1]) * t / 8)
        for river in rivers
        for a, b in zip(river["points"], river["points"][1:], strict=False)
        for t in range(9)
    ]

    def clear(point: tuple[float, float]) -> bool:
        x, y = point
        if not (GROUND_RADIUS <= x <= size[0] - GROUND_RADIUS and GROUND_RADIUS <= y <= size[1] - GROUND_RADIUS):
            return False
        return (
            all(math.dist(point, s.at) > GROUND_RADIUS + 1.5 for s in sites)
            and all(math.dist(point, w) > GROUND_RADIUS + 0.4 for w in water)
            and all(math.dist(point, g) > 2 * GROUND_RADIUS for g in taken)
        )

    if clear(at):
        return at
    rings = (
        (at[0] + r * math.cos(math.radians(d)), at[1] + r * math.sin(math.radians(d)))
        for r in (0.5 * n for n in range(1, 9))
        for d in range(0, 360, 30)
    )
    return next((p for p in rings if clear(p)), at)


def read_outline(answer: str) -> Outline:
    """The sandbox outline in Claude's answer, with its `questions` block; `Unreadable` with the reason."""
    answer, questions = take_questions(answer)
    raw = _object(answer)
    title = _text(raw.get("title"))
    if not title:
        raise Unreadable("the outline has no title")
    if not isinstance(raw.get("sites"), list) or len(raw["sites"]) < 2:
        raise Unreadable("the outline has fewer than two sites")
    size = _size(raw.get("region"))
    sites = [_site(site, size) for site in raw["sites"][:MAX_SITES]]
    letters = [site.letter for site in sites]
    if len(set(letters)) != len(letters):
        raise Unreadable("two sites have the same letter")
    if sum(site.home for site in sites) > 1:
        first_home = next(s for s in sites if s.home)
        sites = [site if site is first_home else replace(site, home=False) for site in sites]
    by_letter = {site.letter: site for site in sites}
    routes = [r for r in (_route(item, set(letters), by_letter) for item in raw.get("routes") or []) if r is not None]
    terrain = []
    for item in _records(raw.get("terrain")):
        points = _points(item.get("points"), size, 3)
        kind = _text(item.get("kind")).lower()
        if points:
            terrain.append(
                {"kind": kind if kind in TERRAIN else "fields", "name": _text(item.get("name")), "points": points}
            )
    rivers = []
    for item in _records(raw.get("rivers")):
        points = _points(item.get("points"), size, 2)
        if points:
            rivers.append({"name": _text(item.get("name")), "points": points})
    open_ground = []
    for item in _records(raw.get("open_ground")):
        at = _point(item.get("at"), size)
        if at is not None and _text(item.get("name")):
            at = _clear_ground(at, size, sites, rivers, [g["at"] for g in open_ground])
            open_ground.append({"name": _text(item["name"]), "at": at, "idea": _text(item.get("idea"))})
    return Outline(
        title=title,
        summary=_text(raw.get("summary")),
        party=party_of(raw.get("party")),
        intro=_text(raw.get("intro")),
        size=size,
        terrain=terrain,
        rivers=rivers,
        sites=sites,
        routes=routes,
        factions=[f for f in _records(raw.get("factions")) if _text(f.get("name"))],
        npcs=[n for n in _records(raw.get("npcs")) if _text(n.get("name"))],
        rumours=[r for r in _records(raw.get("rumours")) if _text(r.get("text"))],
        secrets=[s for s in _records(raw.get("secrets")) if _text(s.get("truth"))],
        open_ground=open_ground,
        wandering=raw.get("wandering") if isinstance(raw.get("wandering"), dict) else {},
        questions=questions,
    )


# ----- the outline as the site prompts read it -----


def _letters(raw: Any) -> list[str]:
    return [_text(x).upper() for x in (raw if isinstance(raw, list) else []) if _text(x)]


_VERDICT = re.compile(r"^(?:true|false|partly(?: true)?)\s*[.:;,–-]\s*", re.IGNORECASE)


def _really(rumour: dict[str, Any]) -> str:
    """What is so, without a verdict the answer repeats at its start ("True: it needs guards" is "it needs guards")."""
    really = _VERDICT.sub("", _text(rumour.get("really")))
    return really[:1].upper() + really[1:]


def _truth(rumour: dict[str, Any]) -> str:
    truth = _text(rumour.get("truth")).lower()
    return {"true": "True", "false": "False", "partly": "Partly true"}.get(truth, "Partly true")


def _site_line(site: Site) -> str:
    home = ", the home base" if site.home else ""
    return f"- **{site.title}** ({site.kind}{home}, {site.rooms} rooms): {site.summary}"


def _route_line(route: Route) -> str:
    note = f": {route.note}" if route.note else ""
    return f"- {route.start}–{route.end}: {WAYS[route.way]}, {route.miles:g} mi, danger {route.danger}{note}"


def outline_text(outline: Outline) -> str:
    """The outline as the site prompts read it, in Markdown: the places, the ways between them, the factions and
    the people. The secrets and rumours go only to the sites they touch (`_clues_for`, `_rumours_for`)."""
    parts = [f"# {outline.title}", outline.summary, outline.intro]
    parts.append("## The places\n\n" + "\n".join(_site_line(site) for site in outline.sites))
    if outline.routes:
        parts.append("## The ways between them\n\n" + "\n".join(_route_line(r) for r in outline.routes))
    if outline.factions:
        lines = []
        for f in outline.factions:
            steps = " ".join(
                f"({n}) {_text(step)}" for n, step in enumerate(f.get("clock") or [], start=1) if _text(step)
            )
            lines.append(
                f"- **{_text(f.get('name'))}**: wants {_text(f.get('want'))} {_text(f.get('summary'))} "
                f"If nobody stops them: {steps} {_text(f.get('relations'))}".rstrip()
            )
        parts.append("## The factions\n\n" + "\n".join(lines))
    if outline.npcs:
        parts.append("## The people\n\n" + "\n".join(_npc_line(n) for n in outline.npcs))
    return "\n\n".join(p for p in parts if p)


def _npc_line(npc: dict[str, Any]) -> str:
    where = _text(npc.get("site")).upper()
    at = f", at {where}" if where else ""
    return f"- **{_text(npc.get('name'))}** ({_text(npc.get('role'))}{at}): {_text(npc.get('summary'))}"


def _people_for(site: Site, outline: Outline) -> str:
    lines = [_npc_line(n) for n in outline.npcs if _text(n.get("site")).upper() == site.letter]
    return "\n".join(lines) or "- (nobody named: the outline puts no NPC here)"


def _clues_for(site: Site, outline: Outline) -> str:
    lines = []
    for secret in outline.secrets:
        for clue in _records(secret.get("clues")):
            if _text(clue.get("site")).upper() == site.letter and _text(clue.get("clue")):
                lines.append(f"- {_text(clue['clue'])} (it belongs to this secret: {_text(secret.get('truth'))})")
    return "\n".join(lines) or "- (none here)"


def _rumours_for(site: Site, outline: Outline) -> str:
    lines = [
        f"- “{_text(r.get('text'))}” {_truth(r)}: {_really(r)}".rstrip(": ")
        for r in outline.rumours
        if site.letter in _letters(r.get("points"))
    ]
    return "\n".join(lines) or "- (none)"


# ----- the sites -----


def _read_site(site: Site) -> Any:
    def read(answer: str) -> _Written:
        raw = _object(answer)
        if not isinstance(raw.get("rooms"), list) or not raw["rooms"]:
            raise Unreadable("the site has no rooms")
        rooms = [read_room(lettered(room, site.letter)) for room in raw["rooms"]]
        keys = [room.key for room in rooms]
        if len(set(keys)) != len(keys):
            raise Unreadable("two rooms have the same key")
        if any(not key.startswith(site.letter) for key in keys):
            raise Unreadable(f"a room's key doesn't start with the site's letter {site.letter}")
        wandering = raw.get("wandering") if isinstance(raw.get("wandering"), dict) else {}
        return _Written(site, _text(raw.get("intro")), rooms, wandering, {"encounters": raw.get("encounters")})

    return read


class _Level:
    """What `campaign._wandering` reads of a level: its map and its title."""

    def __init__(self, map_name: str, title: str) -> None:
        self.map_name, self.title = map_name, title


def _site_text(written: _Written, outline: Outline, used: set[str]) -> tuple[TextDoc, list[str], dict[str, Any] | None]:
    """The site's text, linked to its map; its rooms' sections, in order; and its wandering record."""
    site = written.site
    ways = [r for r in outline.routes if site.letter in (r.start, r.end)]
    lines = [
        f"- To **{other.title}**: {WAYS[r.way]}, {r.miles:g} mi ({_hours(r)} on foot), danger {r.danger}."
        for r in ways
        if (other := outline.site(r.end if r.start == site.letter else r.start)) is not None
    ]
    head = f"# {site.title}"
    getting = "**Ways from here:**\n\n" + "\n".join(lines) if lines else ""
    sections = [section(room) for room in written.rooms]
    wandering, record = _wandering(_Level(site.map_name, site.title), written.wandering)  # type: ignore[arg-type]
    parts = [head, written.intro, getting, *sections, wandering]
    markdown = _anchored("\n\n".join(p for p in parts if p))
    return (
        TextDoc(unique(text_id(f"{site.letter} {site.name}"), used), site.title, "gm", site.map_name, markdown),
        sections,
        record,
    )


# ----- the region's text -----


def _hours(route: Route) -> str:
    hours = route.miles / PACE[route.way]
    if hours > DAY_HOURS * 1.25:
        days = math.ceil(hours / DAY_HOURS)
        return f"{days} days"
    if hours > DAY_HOURS * 0.75:
        return "a day"
    rounded = max(1, round(hours))
    return f"{rounded} hour" + ("s" if rounded != 1 else "")


def _clock_rule(factions: list[dict[str, Any]]) -> str:
    """Which faction moves on each roll: every second dawn, a d6 (or a d4 for four) picks one."""
    names = [_text(f.get("name")) for f in factions]
    if not names:
        return ""
    if len(names) == 1:
        picks = f"{names[0]} takes its next step"
    else:
        die = 4 if len(names) == 4 else 6
        share = die // len(names)
        spans = []
        for n, name in enumerate(names):
            low, high = n * share + 1, die if n == len(names) - 1 else (n + 1) * share
            spans.append(f"{low}–{high} {name}" if low != high else f"{low} {name}")
        picks = f"roll a d{die}: " + ", ".join(spans) + "; that faction takes its next step"
    return (
        f"**The clocks.** Every second dawn the party spends in the region, {picks}. If the party has already changed "
        "that step, the faction adapts it rather than skipping it. A faction whose last step has come stops; the region "
        "has changed for good."
    )


def region_text(outline: Outline) -> str:
    """The region's text: what it is, how travel and the clocks work, the routes, the rumours, the factions, the
    secrets, the open ground and the road's wandering monsters."""
    home = outline.home
    parts = [f"# {outline.title}", outline.summary, outline.intro]
    places = "\n".join(_site_line(site) for site in outline.sites)
    parts.append(
        f"## The places\n\nThe home base is **{home.title}**. Each place has its own text and map.\n\n{places}"
    )

    travel = [
        "## Travel",
        (
            "Distances are along the way; off the ways, travel is at half speed. On foot a party makes about 3 miles an "
            "hour on a road, 2½ on a track, 2 on a path and 1½ cross-country, and marches 8 hours a day."
        ),
    ]
    if outline.routes:
        rows = "\n".join(
            f"| {r.start}–{r.end} | {WAYS[r.way]} | {r.miles:g} mi | {_hours(r)} | {r.danger} | {r.note} |"
            for r in outline.routes
        )
        travel.append(
            "| Way | Kind | Distance | On foot | Danger | On the way |\n| --- | --- | --- | --- | --- | --- |\n" + rows
        )
    parts.append("\n\n".join(travel))

    if outline.rumours:
        rows = "\n".join(
            f"| {n} | {_text(r.get('text'))} | {_truth(r)}. {_really(r)} | {', '.join(_letters(r.get('points')))} |"
            for n, r in enumerate(outline.rumours[:12], start=1)
        )
        die = "d12" if len(outline.rumours) >= 12 else f"d{len(outline.rumours)}"
        parts.append(
            f"## Rumours\n\nRoll {die} when the party listens at {home.name}, or give one for a drink bought. Not every "
            f"rumour is true.\n\n| {die} | What they say | What is so | Points to |\n| --- | --- | --- | --- |\n{rows}"
        )

    if outline.factions:
        blocks = [_clock_rule(outline.factions)]
        for f in outline.factions:
            steps = "\n".join(
                f"{n}. {_text(step)}" for n, step in enumerate(f.get("clock") or [], start=1) if _text(step)
            )
            lines = [f"### {_text(f.get('name'))}", f"**Wants:** {_text(f.get('want'))}", _text(f.get("summary"))]
            if _text(f.get("relations")):
                lines.append(_text(f.get("relations")))
            if steps:
                lines.append("If nobody stops them:\n\n" + steps)
            blocks.append("\n\n".join(x for x in lines if x))
        parts.append("## The factions\n\n" + "\n\n".join(blocks))

    if outline.secrets:
        blocks = [
            (
                "These are true whether or not the party finds them. Nothing in the region needs them found; a party may "
                "play the whole region and never learn one."
            )
        ]
        for secret in outline.secrets:
            clues = "\n".join(
                f"- At {_text(c.get('site')).upper()}: {_text(c.get('clue'))}"
                for c in _records(secret.get("clues"))
                if _text(c.get("clue"))
            )
            lines = [f"### {_text(secret.get('name')) or 'A secret'}", _text(secret.get("truth"))]
            if clues:
                lines.append("**Clues:**\n\n" + clues)
            if _text(secret.get("unfound")):
                lines.append(f"**If nobody finds it:** {_text(secret['unfound'])}")
            blocks.append("\n\n".join(x for x in lines if x))
        parts.append("## Secrets\n\n" + "\n\n".join(blocks))

    grow = [
        "## Room to grow",
        "These stretches are left unwritten on purpose; they are outlined on the region map.",
    ]
    if outline.open_ground:
        grow.append("\n".join(f"- **{g['name']}**: {g['idea']}".rstrip(": ") for g in outline.open_ground))
    free = _next_letter(outline)
    grow.append(
        f"When the party goes somewhere unwritten, make it a place: give it the next free letter ({free}), a few rooms, "
        "one thing that someone there wants and one secret; add a rumour that points to it, add its way to the travel "
        "table, and note what it changes in the factions' clocks."
    )
    parts.append("\n\n".join(grow))
    return "\n\n".join(p for p in parts if p)


def _next_letter(outline: Outline) -> str:
    used = {site.letter for site in outline.sites}
    return next((c for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" if c not in used), "Z")


def _region_wandering(outline: Outline) -> tuple[str, dict[str, Any] | None]:
    text, record = _wandering(_Level(REGION_MAP, "On the roads"), outline.wandering)  # type: ignore[arg-type]
    if record is not None:
        record["kind"] = "wilderness"
    return text.replace("## Wandering monsters", "## On the roads", 1), record


# ----- the region map -----


def _xy(point: tuple[float, float]) -> str:
    return f"{round(point[0], 2):g},{round(point[1], 2):g}"


def _slug(text: str, n: int) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:24] + f"_{n}"


SITE_RADIUS = 0.6
"""A site's marker on the region map, in miles."""
LABEL_MILES = 0.28
"""About how wide a letter of a label is on the region map, in miles."""


def region_map(outline: Outline) -> str:
    """The region map's source, drawn from the outline's coordinates in miles: its terrain areas, rivers, the ways
    (a road band, or a dashed path), a round marker per site joined by its routes, and the open ground outlined."""
    width, height = outline.size
    cell = max(24, min(48, 1400 // width))
    lines = [
        f'map "{_quoted(outline.title)}" {{',
        f"  grid {{ cell {cell} px  units miles 1  bounds {width} x {height} }}",
        '  renderer "classic-bw"',
        "  theme paper",
        "  room_numbers off",
        "}",
        "",
        "# Drawn by Delve from the sandbox's outline: a mile to the square.",
    ]
    for n, area in enumerate(outline.terrain, start=1):
        kind, colour = TERRAIN[area["kind"]]
        points = " ".join(f"({_xy(p)})" for p in area["points"])
        head = f'area "{_slug(area["name"] or area["kind"], n)}"' + (f" kind {kind}" if kind else "")
        at = _xy(_label_point(area["points"], area["name"], _avoid(outline)))
        label = f'\n  label "{_quoted(area["name"])}" at {at} size 0.7' if area["name"] else ""
        lines += [
            "",
            f"{head} {{",
            f"  polygon {points}",
            f'  background "{colour}"',
            "  line_style organic" + label,
            "}",
        ]
    for n, ground in enumerate(outline.open_ground, start=1):
        x, y = ground["at"]
        lines += [
            "",
            f'area "{_slug(ground["name"], n)}" kind inlay {{',
            f"  circle at {_xy((x, y))} radius {GROUND_RADIUS:g}",
            f'  label "{_quoted(ground["name"])} (open)" size 0.8',
            f'  dm_notes "{_quoted(ground["idea"] or "Left unwritten on purpose.")}"',
            "}",
        ]
    for n, river in enumerate(outline.rivers, start=1):
        segments = [
            f"  segment line from {_xy(a)} to {_xy(b)}"
            for a, b in zip(river["points"], river["points"][1:], strict=False)
        ]
        label = []
        if river["name"]:
            (lx, ly), angle = _river_label(river["points"], river["name"], _avoid(outline, rivers=False))
            label = [f'  label "{_quoted(river["name"])}" at {_xy((lx, ly))} rotate {angle:g} size 0.7']
        lines += [
            "",
            f'slice "{_slug(river["name"] or "river", n)}" {{',
            "  kind river",
            "  width 0.35",
            *segments,
            *label,
            "}",
        ]
    sites = {site.letter: site for site in outline.sites}
    for n, route in enumerate(outline.routes, start=1):
        a, b = sites[route.start].at, sites[route.end].at
        if route.way == "road":
            lines += [
                "",
                f'line_feature "way_{n}" kind road {{',
                f"  point {_xy(a)}",
                f"  point {_xy(b)}",
                "  width 0.3",
                "}",
            ]
        elif route.way in ("track", "path"):
            lines += ["", f'line_feature "way_{n}" kind path {{', f"  point {_xy(a)}", f"  point {_xy(b)}", "}"]
    for site in outline.sites:
        x, y = site.at
        lines += [
            "",
            f'room "{_site_room(site)}" {{',
            f"  circle at {_xy(site.at)} radius {SITE_RADIUS}",
            f'  label "{_quoted(site.title)}" at {_xy((x, min(y + SITE_RADIUS + 0.6, height - 0.3)))} size 0.75',
            f'  dm_notes "{_quoted(site.summary)}"',
            "}",
        ]
    for n, route in enumerate(outline.routes, start=1):
        a, b = sites[route.start].at, sites[route.end].at
        name = f"route_{route.start.lower()}_{route.end.lower()}_{n}"
        lines += [
            "",
            f'corridor "{name}" "{route.start}–{route.end}, {route.miles:g} mi" {{',
            "  width 0",
            "  line_style dotted",
            f"  segment line from {_xy(a)} to {_xy(b)}",
            f'  dm_notes "{_quoted(_route_line(route)[2:])}"',
            "}",
            f"door between room.{_site_room(sites[route.start])} and corridor.{name} {{ type open }}",
            f"door between corridor.{name} and room.{_site_room(sites[route.end])} {{ type open }}",
        ]
    return "\n".join(lines) + "\n"


def _label_point(
    polygon: list[tuple[float, float]], name: str, avoid: list[tuple[float, float, float]]
) -> tuple[float, float]:
    """Where an area's `name` goes: of its centre and the points a third and a half of the way from it to each corner,
    the one whose label (about `LABEL_MILES` a letter wide) keeps farthest from everything in `avoid`, circles
    `(x, y, radius)`: the sites' markers and labels, and the open ground."""
    cx = sum(x for x, _ in polygon) / len(polygon)
    cy = sum(y for _, y in polygon) / len(polygon)
    candidates = [(cx, cy)] + [(cx + (x - cx) * f, cy + (y - cy) * f) for x, y in polygon for f in (0.33, 0.5)]
    half = len(name) * LABEL_MILES / 2

    def clearance(point: tuple[float, float]) -> float:
        samples = [(point[0] + half * f, point[1]) for f in (-1.0, -0.5, 0.0, 0.5, 1.0)]
        return min((math.dist(p, (x, y)) - r for p in samples for x, y, r in avoid), default=99.0)

    return max(candidates, key=clearance)


def _river_label(
    points: list[tuple[float, float]], name: str, avoid: list[tuple[float, float, float]]
) -> tuple[tuple[float, float], float]:
    """Where a river's `name` goes, and its angle: of the points a quarter, half and three quarters along each of its
    lines, the one whose label, laid along the line, keeps farthest from everything in `avoid`."""
    half = len(name) * LABEL_MILES / 2
    best: tuple[float, tuple[float, float], float] | None = None
    for a, b in itertools.pairwise(points):
        length = math.dist(a, b) or 1.0
        ux, uy = (b[0] - a[0]) / length, (b[1] - a[1]) / length
        angle = math.degrees(math.atan2(uy, ux))
        angle = angle - 180 if angle > 90 else angle + 180 if angle < -90 else angle
        for t in (0.25, 0.5, 0.75):
            at = (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
            samples = [(at[0] + ux * half * f, at[1] + uy * half * f) for f in (-1.0, 0.0, 1.0)]
            clear = min((math.dist(p, (x, y)) - r for p in samples for x, y, r in avoid), default=99.0)
            if best is None or clear > best[0]:
                best = (clear, at, round(angle))
    assert best is not None
    return best[1], best[2]


def _avoid(outline: Outline, *, rivers: bool = True) -> list[tuple[float, float, float]]:
    """What an area's name keeps clear of: each site's marker and the label under it, the rivers, and the open
    ground."""
    marks = [(x, y, SITE_RADIUS) for x, y in (site.at for site in outline.sites)]
    labels = [
        (x + dx, y + SITE_RADIUS + 0.6, 0.4)
        for site in outline.sites
        for x, y in [site.at]
        for dx in (-len(site.title) * LABEL_MILES / 2, 0.0, len(site.title) * LABEL_MILES / 2)
    ]
    water = [
        (a[0] + (b[0] - a[0]) * t / 4, a[1] + (b[1] - a[1]) * t / 4, 0.5)
        for river in (outline.rivers if rivers else [])
        for a, b in zip(river["points"], river["points"][1:], strict=False)
        for t in range(5)
    ]
    return marks + labels + water + [(*g["at"], GROUND_RADIUS) for g in outline.open_ground]


def site_kind(site: Site) -> str:
    """What a site's map is told of the place: its kind, whether it lies outdoors, and what the outline says of it."""
    outdoors = site.kind.lower() in OUTDOOR_KINDS
    where = "An outdoor site and its buildings" if outdoors else "A place"
    return f"{where}: {site.title}, a {site.kind}. {site.summary}".strip()


OUTDOOR_KINDS = frozenset(
    {"village", "hamlet", "farmstead", "farm", "inn", "camp", "shrine", "crossing", "ferry", "town", "fort", "quarry"}
)
"""The kinds of site whose map is open ground with buildings on it, not rooms underground."""


def _site_room(site: Site) -> str:
    return f"site_{site.letter.lower()}"


def below_label(dmap: Any, room: str) -> tuple[float, float] | None:
    """Where an exit goes in `room`: inside it, below the label at its centre (a cell and a half below, or halfway to
    its bottom wall in a small room), so the exit's pad doesn't sit on the room's name; its centre when that point is
    outside it."""
    centre = node_centroid(dmap, f"room.{room}")
    found = walk.rooms(dmap).get(room)
    if centre is None or found is None:
        return centre
    shape = Polygon(room_polygon(found)).buffer(0)
    if shape.is_empty:
        return centre
    bottom = shape.bounds[3]
    point = (centre[0], min(centre[1] + 1.5, centre[1] + (bottom - centre[1]) / 2))
    return point if shape.contains(Point(point)) else centre


def join_sites(
    region: str, sites: dict[str, str], firsts: dict[str, tuple[Site, str]]
) -> tuple[str, dict[str, str], list[Warning]]:
    """The region map with an exit at each drawn site's marker to its first room, and each site's map with an exit
    there back to the marker. `firsts` gives, by map name, the site and its first room's key."""
    parsed = parse_source(region)
    joined: dict[str, str] = {}
    exits: list[str] = []
    warnings: list[Warning] = []
    for name, source in sites.items():
        site, key = firsts[name]
        land = below_label(parse_source(source), room_name(key))
        marker = node_centroid(parsed, f"room.{_site_room(site)}")
        if land is None or marker is None:
            message = f"The way between the region map and {site.title} isn't on the maps: {key} wasn't drawn."
            warnings.append(Warning("exit-not-joined", message, f"map:{name}"))
            joined[name] = source
            continue
        exits.append(
            f'exit at {_xy(marker)} {{\n  to "{name}" at {_xy(land)}\n  description "Into {_quoted(site.title)}."\n}}'
        )
        joined[name] = (
            source.rstrip()
            + f'\n\n# The way back to the region map.\nexit at {_xy(land)} {{\n  to "{REGION_MAP}" at {_xy(marker)}\n'
            f'  label "Region" size 0.5\n  description "Back out into the region."\n}}\n'
        )
    if exits:
        region = region.rstrip() + "\n\n# The ways into the places.\n" + "\n".join(exits) + "\n"
    return region, joined, warnings


# ----- the whole -----


def _npc_record(raw: dict[str, Any]) -> dict[str, Any]:
    record = {k: raw[k] for k in ("id", "name", "role", "summary") if _text(raw.get(k))}
    return record


def _faction_record(raw: dict[str, Any]) -> dict[str, Any]:
    steps = [_text(step) for step in raw.get("clock") or [] if _text(step)]
    record: dict[str, Any] = {"name": _text(raw.get("name"))}
    if _text(raw.get("id")) and _ID.match(_text(raw["id"])):
        record["id"] = _text(raw["id"])
    summary = " ".join(x for x in (_text(raw.get("summary")), _text(raw.get("relations"))) if x)
    if steps:
        summary += " If nobody stops them: " + " ".join(f"({n}) {s}" for n, s in enumerate(steps, start=1))
    if summary.strip():
        record["summary"] = summary.strip()
    if _text(raw.get("want")):
        record["goals"] = [_text(raw["want"])]
    if steps:
        record["clocks"] = [
            {"name": f"{record['name']} move", "segments": len(steps), "filled": 0, "on_complete": steps[-1]}
        ]
    return record


async def generate_sandbox(
    request: str,
    complete: Complete,
    progress: Progress,
    *,
    rng: Rng | None = None,
    concurrency: int = CONCURRENCY,
    game: str = "",
) -> Converted:
    """An open sandbox from `request` (with the organiser's answers already in it, `campaign.with_answers`): the
    region's text and map, and a keyed text and a sketched map per site, joined by exits. Raises `GenerationError`
    when the outline can't be read after one retry, or no site can be written."""
    rng = rng or SystemRng()
    names = _names(rng)
    progress("planning", 0, 1)
    first = fill(prompt("generate-sandbox-outline.md"), request=request.strip(), names=names)
    try:
        outline: Outline = await _asked(first, complete, read_outline)
    except Unreadable as unreadable:
        raise GenerationError(f"The sandbox couldn't be outlined: {unreadable}.") from None
    progress("planning", 1, 1)
    agreed = outline_text(outline)
    warnings: list[Warning] = []

    limit = asyncio.Semaphore(concurrency)

    async def write(site: Site) -> _Written | None:
        text = fill(
            prompt("generate-site.md"),
            request=request.strip(),
            game=game or GAME,
            outline=agreed,
            site=_site_line(site),
            people=_people_for(site, outline),
            clues=_clues_for(site, outline),
            rumours=_rumours_for(site, outline),
            letter=site.letter,
            slug=site.map_name,
            rooms=str(site.rooms),
            names=names,
        )
        try:
            return await _asked(text, complete, _read_site(site))
        except Unreadable as unreadable:
            message = f"{site.title} couldn't be written: {unreadable}. It is left out."
            warnings.append(Warning("site-not-written", message, None))
            return None

    written_sites = [w for w in await each_at_once(outline.sites, write, "sites", progress, limit) if w is not None]
    if not written_sites:
        raise GenerationError("The sandbox couldn't be generated: no site could be written.")

    used: set[str] = set()
    on_roads, road_record = _region_wandering(outline)
    region_markdown = region_text(outline) + (f"\n\n{on_roads}" if on_roads else "")
    region_doc = TextDoc(
        unique(text_id(outline.title), used), outline.title, "gm", REGION_MAP, _anchored(region_markdown)
    )
    texts = [region_doc]
    encounters: list[Any] = [road_record] if road_record is not None else []
    keyed_sites: list[tuple[Site, list[tuple[str, str]]]] = []
    for written in sorted(written_sites, key=lambda w: (not w.site.home, w.site.letter)):
        doc, sections, record = _site_text(written, outline, used)
        texts.append(doc)
        keyed_sites.append((written.site, [(room.key, s) for room, s in zip(written.rooms, sections, strict=True)]))
        raw = written.entities.get("encounters")
        encounters.extend(raw if isinstance(raw, list) else [])
        if record is not None:
            encounters.append(record)
    entity_lists: dict[str, list[Any]] = {
        "npcs": [_npc_record(n) for n in outline.npcs],
        "factions": [_faction_record(f) for f in outline.factions],
        "encounters": encounters,
    }
    entities, dropped = plan_entities(entity_lists, (*SANDBOX_KINDS, *SITE_KINDS))

    async def draw(keyed_site: tuple[Site, list[tuple[str, str]]]) -> tuple[str | None, list[Warning]]:
        site, keyed = keyed_site
        return await design_map(site.map_name, keyed, complete, kind=site_kind(site))

    sketches = await each_at_once(keyed_sites, draw, "maps", progress, limit)
    drawn = {site.map_name: s for (site, _), (s, _) in zip(keyed_sites, sketches, strict=True) if s is not None}
    sketched = [w for _, ws in sketches for w in ws]
    firsts = {site.map_name: (site, keyed[0][0]) for site, keyed in keyed_sites}
    region = region_map(outline)
    error = map_error(region)
    if error is not None:
        raise GenerationError(f"The region map couldn't be drawn: {error}.")
    region, drawn, unjoined = join_sites(region, drawn, firsts)
    maps = [ModuleMap(REGION_MAP, "map", region, True)] + [
        ModuleMap(site.map_name, "map", drawn[site.map_name], False)
        for site, _ in keyed_sites
        if site.map_name in drawn
    ]
    module, repaired = repair_refs(ModuleSource(texts=texts, entities=entities), maps=maps)
    return Converted(
        source=module,
        pictures=[],
        warnings=warnings + dropped + sketched + unjoined + repaired,
        maps=maps,
        metadata={"party": outline.party} if outline.party else {},
        questions=_numbered(outline.questions[:MAX_QUESTIONS]),
    )
