"""`delve qa join` (thorough conversion Task 3): each map's exits become `exit` statements to the map they name; a
landing is a matching label, then the named room, then the party start, which is a doubt, as an exit that names no map
is."""

import json
from pathlib import Path

import pytest

from delve.__main__ import main
from delve.conversions.qa.join import MapModel, join_exits
from delve.maps.sources import parse_source


def dmap(title: str, start: str) -> str:
    return (
        f'map "{title}" {{\n  grid {{\n    cell 32 px\n    bounds 20 x 10\n  }}\n  party_start "{start}"\n}}\n'
        'room "r1" { rect 1,1 4 x 4 }\n'
        'room "r2" { rect 6,1 4 x 4 }\n'
        'room "r3" { rect 11,1 4 x 6 }\n'
    )


HOUSE = [
    {"label": "S1", "at": [2, 2], "room": "r1", "to_map": "cellar", "text": "Stairs down to the cellar."},
    {"label": "Trapdoor", "at": [7, 2], "room": "r2", "to_map": "cellar", "to_room": "r3", "text": "A trapdoor."},
    {"label": "Chute", "at": [8, 4], "room": "r2", "to_map": "cellar", "text": "A coal chute.", "page": 4},
    {"label": "Well", "at": [12, 2], "room": "r3", "text": "The well goes down to who knows where."},
    {"label": "Tunnel", "at": [13, 4], "room": "r3", "to_map": "sea-cave", "text": "A tunnel to the sea."},
]
CELLAR = [
    {"label": "S1", "at": [3, 3], "room": "r1", "to_map": "attic", "text": "Another S1, to elsewhere."},
    {"label": "S1", "at": [5, 4], "room": "r2", "to_map": "house", "text": "Stairs up to the house."},
]


def models() -> dict[str, MapModel]:
    sources = {"house": dmap("The house", "r1"), "cellar": dmap("The cellar", "r2")}
    return {name: MapModel(source, parse_source(source)) for name, source in sources.items()}


def test_join_matches_labels_and_guesses_with_doubt() -> None:
    joined, doubts = join_exits(models(), {"house": HOUSE, "cellar": CELLAR})
    house = parse_source(joined["house"])
    landings = {(e.position, e.target_map): e.target_position for e in house.exits}
    assert landings[((2, 2), "cellar")] == (5, 4)  # its S1 that leads back, not the first S1
    assert landings[((7, 2), "cellar")] == pytest.approx((13.0, 4.0), abs=0.6)  # the centre of room r3
    assert landings[((8, 4), "cellar")] == pytest.approx((8.0, 3.0), abs=0.6)  # the cellar's party start, r2
    assert len(house.exits) == 3
    cellar = parse_source(joined["cellar"])
    by_position = {e.position: e for e in cellar.exits}
    assert set(by_position) == {(5, 4)}  # the S1 to "attic" isn't joined: there is no such map
    assert by_position[(5, 4)].target_map == "house" and by_position[(5, 4)].target_position == (2, 2)
    assert [(d["part"], d["kind"], d["pages"]) for d in doubts] == [
        ("house", "guessed-landing", [4]),
        ("house", "other", []),
        ("house", "other", []),
        ("cellar", "other", []),
    ]
    assert "Chute" in doubts[0]["text"] and "Well" in doubts[1]["text"] and "sea-cave" in doubts[2]["text"]


def test_join_leaves_a_map_with_no_exits_as_it_is() -> None:
    joined, doubts = join_exits(models(), {})
    assert joined["house"] == models()["house"].source and doubts == []


def test_join_command_writes_maps_and_doubts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    maps = tmp_path / "maps"
    maps.mkdir()
    (maps / "house.dmap").write_text(dmap("The house", "r1"))
    (maps / "cellar.dmap").write_text(dmap("The cellar", "r2"))
    (maps / "house.exits.json").write_text(json.dumps(HOUSE))
    (maps / "cellar.exits.json").write_text(json.dumps(CELLAR))
    monkeypatch.chdir(tmp_path)
    assert main(["qa", "join", "maps", "joined"]) == 0
    assert sorted(p.name for p in (tmp_path / "joined").iterdir()) == ["cellar.dmap", "house.dmap", "join-doubts.json"]
    assert len(parse_source((tmp_path / "joined" / "house.dmap").read_text()).exits) == 3
    assert len(json.loads((tmp_path / "joined" / "join-doubts.json").read_text())) == 4
