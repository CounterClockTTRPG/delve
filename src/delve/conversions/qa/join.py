"""Joining the levels (thorough conversion Task 3), from the WGR1 QA's `join_exits.py`: each traced map's
exits (`maps/<name>.exits.json`, written by its trace agent) become `exit` statements to the other end.

An exit names the map it leads to (`to_map`), so no level code is read from its text. Its landing there is, in order:
an exit on `to_map` with the same label that leads back to this map (`S4` ↔ `S4`); one with the same label; the centre
of the room `to_room` names; else `to_map`'s party start, which is a guess and a doubt. An exit with no `to_map` (off
the module, a dead end, a stair the book doesn't follow), or to a map that isn't there, is left out, and is a doubt.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import NotRequired, TypedDict

from delve.maps.dsl import DungeonMap
from delve.maps.dsl.geometry import node_centroid, party_start_point
from delve.maps.sources import parse_source

DOUBTS_FILE = "join-doubts.json"
LABEL_CHARS = 24


class Exit(TypedDict):
    label: str
    at: list[float]
    room: str | None
    to_map: NotRequired[str | None]
    to_room: NotRequired[str | None]
    text: str
    page: NotRequired[int]
    """The map's page in the book, when the trace agent wrote it."""


class Doubt(TypedDict):
    """One entry of a doubts file (`doubts/<piece>.json`)."""

    part: str
    pages: list[int]
    kind: str
    text: str


@dataclass(frozen=True)
class MapModel:
    """A traced map: its source, and the source parsed."""

    source: str
    dmap: DungeonMap


def _quoted(text: str) -> str:
    return text.replace("\\", "/").replace('"', "'").replace("\n", " ")


def _room_centre(dmap: DungeonMap, room: str) -> tuple[float, float] | None:
    for name in (room, room.lower(), f"r{room.lower()}"):
        if name in dmap.rooms:
            return node_centroid(dmap, f"room.{name}")
    return None


def _landing(
    name: str, exit_: Exit, maps: dict[str, MapModel], exits: dict[str, list[Exit]]
) -> tuple[tuple[float, float] | None, str]:
    """Where `exit_` of map `name` lands on its `to_map`, and how that was found ("" for a guess)."""
    target = exit_.get("to_map") or ""
    there = [e for e in exits.get(target, []) if e is not exit_ and e.get("label") == exit_["label"]]
    back = [e for e in there if e.get("to_map") == name]
    if back or there:
        at = (back or there)[0]["at"]
        return (float(at[0]), float(at[1])), f"its {exit_['label']}"
    if room := exit_.get("to_room"):
        centre = _room_centre(maps[target].dmap, str(room))
        if centre is not None:
            return (round(centre[0], 1), round(centre[1], 1)), f"room {room}"
    start = party_start_point(maps[target].dmap)
    return ((round(start[0], 1), round(start[1], 1)) if start else None), ""


def join_exits(maps: dict[str, MapModel], exits: dict[str, list[Exit]]) -> tuple[dict[str, str], list[Doubt]]:
    """Each map's source with its exits written as `exit` statements, and the doubts: the guessed landings and the
    exits left out."""
    out: dict[str, str] = {}
    doubts: list[Doubt] = []
    for name, model in maps.items():
        statements: list[str] = []
        for exit_ in exits.get(name, []):
            label = exit_.get("label") or "exit"
            about = exit_.get("text", "")
            pages = [exit_["page"]] if "page" in exit_ else []
            target = exit_.get("to_map")
            if not target or target not in maps:
                why = "it names no map it leads to" if not target else f'there is no map "{target}"'
                doubts.append(
                    Doubt(part=name, pages=pages, kind="other", text=f"Exit {label} isn't joined: {why}. {about}")
                )
                continue
            land, how = _landing(name, exit_, maps, exits)
            if land is None:
                doubts.append(
                    Doubt(
                        part=name,
                        pages=pages,
                        kind="guessed-landing",
                        text=f'Exit {label} to "{target}" isn\'t joined: it has no landing there and the map no party '
                        f"start. {about}",
                    )
                )
                continue
            if not how:
                doubts.append(
                    Doubt(
                        part=name,
                        pages=pages,
                        kind="guessed-landing",
                        text=f'Exit {label} lands on "{target}" at its party start, a guess. {about}',
                    )
                )
            x, y = exit_["at"]
            statements.append(
                f"exit at {x},{y} {{\n"
                f'  to "{_quoted(target)}" at {land[0]},{land[1]}\n'
                f'  label "{_quoted(label)[:LABEL_CHARS]}" size 0.5\n'
                f'  description "{_quoted(about)}"\n'
                "}"
            )
        out[name] = (
            model.source.rstrip() + "\n\n# Exits to the other maps (delve qa join).\n" + "\n".join(statements) + "\n"
            if statements
            else model.source
        )
    return out, doubts


def join_folder(maps_dir: Path, out_dir: Path) -> tuple[dict[str, str], list[Doubt]]:
    """`join_exits` over the maps in `maps_dir` (`<name>.dmap`, `<name>.exits.json` beside it when it has exits), the
    joined maps written to `out_dir` with the doubts in `join-doubts.json`."""
    paths = sorted(maps_dir.glob("*.dmap"))
    libraries = {p.name: p.read_text() for p in paths}
    maps: dict[str, MapModel] = {}
    exits: dict[str, list[Exit]] = {}
    for path in paths:
        source = libraries[path.name]
        maps[path.stem] = MapModel(source, parse_source(source, libraries))
        listed = path.with_name(f"{path.stem}.exits.json")
        exits[path.stem] = json.loads(listed.read_text()) if listed.exists() else []
    joined, doubts = join_exits(maps, exits)
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, source in joined.items():
        (out_dir / f"{name}.dmap").write_text(source)
    (out_dir / DOUBTS_FILE).write_text(json.dumps(doubts, indent=2) + "\n")
    return joined, doubts
