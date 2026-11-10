"""A journey end to end (plan 6 Task 13, plan 7 Task 21): `delve serve` with the fake `claude` on `PATH`, from the
Free City of Greyhawk to Hardby on a horse, then by river boat down the Selintan, on the region map converted.

The module is the crypt with the Greyhawk region map (plus a hidden smugglers' cove), a faction with a 3-day clock
and a quest, in a campaign on the Greyhawk setting: the module's map wins the name clash with the setting's. The fake
DM places the party in Greyhawk, gives Pippa a riding horse, draws Garrek's portrait with portraitgen, paints the
scene (paid images on, `FakeImages`), takes on the quest with a note the characters don't know, and rides for Hardby
by road.

`delve serve` rolls with the system's dice, and an encounter on the road stops the journey where it happens. So, as a
DM runs the encounter and rides on, each next beat travels on to Hardby, until the party arrives. The clock completes
on the way, the date moves, and the party stands in Hardby. Back in the Free City (`place_party`), the party takes a
river boat down the Selintan to Selintan Mouth, a landing on the Nyr Dyv this test adds to the module's map: it
comes into sight on the way, and the seats' known places grow. A player's `GET …/world` and world-map view show the
route's places, and never the hidden cove, the faction's notes or the quest's secret note.

The real `claude` never runs, nor Replicate: the environment has no Replicate token.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import httpx
import pytest
import yaml

from delve.modules.dscn import Bundle
from delve.play import travel, weather
from delve.rules.classic import overland
from tests.e2e.test_play_with_fake_claude import CRYPT, GARREK, PIPPA, SECRET, Delve
from tests.web.conftest import PASSWORD

REGION = (Path(__file__).resolve().parents[1] / "fixtures" / "packs" / "greyhawk" / "src" / "delve_fixture_greyhawk" / "greyhawk-region.map").read_text(
    encoding="utf-8"
)
HARDBY = "        city hardby {"
LANDING = '        city selintan-mouth { at 471,558; label "Selintan Mouth"; pop 300; tags [village] }\n'
COVE = (
    f'        poi smugglers-cove {{ at 600,420; label "{SECRET} Cove"; description "{SECRET}: the Brotherhood\'s '
    f'landing."; doc "{SECRET}"; tags [hidden] }}\n'
)
FACTIONS = [
    {
        "id": "scarlet-brotherhood",
        "name": "The Scarlet Brotherhood",
        "alignment": "LE",
        "scope": "regional",
        "goals": ["Stop the letter"],
        "description": f"{SECRET}: Dard Lorne is one of them.",
        "clocks": [{"name": "The Brotherhood's ship sails", "days": 3, "on_complete": f"{SECRET}: the ship is gone."}],
    }
]
LORNE = {"id": "dard-lorne", "name": "Dard Lorne", "audience": "gm", "summary": "A Greyhawk merchant with a letter."}
QUESTS = [
    {
        "id": "letter-to-hardby",
        "name": "Carry the letter to Hardby",
        "giver": "npc:dard-lorne",
        "scope": "local",
        "stakes": "The Despotrix must have it before the new moon.",
        "description": f"{SECRET}: the letter is forged.",
    }
]
SETUP = [
    {"text": "Dawn over the Free City. "},
    {"tool": "session_primer", "args": {}},
    {"tool": "new_session", "args": {"title": "The road to Hardby"}},
    {"tool": "create_character", "args": {"name": "Garrek", "sheet": GARREK}},
    {"tool": "create_character", "args": {"name": "Pippa", "sheet": PIPPA}},
    {"tool": "place_party", "args": {"at": "greyhawk"}},
    {
        "tool": "add_possession",
        # OSRIC has no mount defaults: the horse's stats are given.
        "args": {
            "name": "Bramble",
            "kind": "mount",
            "owner": "Pippa",
            "species": "riding horse",
            "stats": {"hp_max": 18, "thac0": 19, "mv": 24},
        },
    },
    {"tool": "portrait", "args": {"of": "Garrek", "description": "a broad human fighter, black beard, scarred"}},
    {
        "tool": "paint_scene",
        "args": {"brief": "Two riders leave the Free City's south gate at dawn.", "caption": "Dawn"},
    },
    {
        "tool": "update_quest",
        "args": {"id": "letter-to-hardby", "status": "active", "note": "Lorne gave you the letter."},
    },
    {
        "tool": "update_quest",
        "args": {"id": "letter-to-hardby", "note": f"{SECRET}: the seal is false.", "note_known": False},
    },
    {"tool": "travel", "args": {"to": "hardby", "by": ["Bramble"]}},
    {"text": "The south-coast road climbs into the Cairn Hills."},
]
RIDE_ON = [
    {"tool": "travel", "args": {"to": "hardby", "by": ["Bramble"]}},
    {"text": "You ride on toward Hardby."},
]
LEGS = 20  # each beat after the first rides on; an encounter stops one about once in six days
DOWNSTREAM = [
    {"tool": "place_party", "args": {"at": "greyhawk"}},
    {"tool": "travel", "args": {"to": "selintan-mouth", "mode": "river"}},
    {"text": "A river boat takes you down the Selintan."},
]
GO_ON = [{"tool": "travel", "args": {}}, {"text": "The boat goes on."}]
RIVER_BEATS = 4


def journey_bundle() -> bytes:
    """The crypt with the region map, a hidden cove and a landing at the Selintan's mouth on it, the Brotherhood with
    its clock, and the quest."""
    assert HARDBY in REGION
    bundle = Bundle.load(CRYPT)
    bundle.add_worldmap("greyhawk-region", REGION.replace(HARDBY, COVE + LANDING + HARDBY), title="The Greyhawk region")
    bundle.set_entities("factions", FACTIONS)
    bundle.set_entities("quests", QUESTS)
    bundle.set_entities("npcs", [*bundle_npcs(bundle), LORNE])
    return bundle.to_zip()


def bundle_npcs(bundle: Bundle) -> list[dict]:
    """The crypt's own NPCs."""
    path = (bundle.manifest.get("entities") or {}).get("npcs")
    return list(yaml.safe_load(bundle.read(path))) if path else []


def ok(response: httpx.Response, status: int = 200):
    assert response.status_code == status, response.text
    return response.json() if response.content else None


@pytest.fixture
def delve(tmp_path, monkeypatch):
    monkeypatch.delenv("REPLICATE_API_TOKEN", raising=False)
    turns = [SETUP] + [RIDE_ON] * LEGS + [DOWNSTREAM] + [GO_ON] * RIVER_BEATS
    server = Delve(tmp_path, turns=turns, side=())
    yield server
    server.stop()


def test_a_journey_from_greyhawk_to_hardby(delve):
    http = delve.http
    module = ok(
        http.post("/api/modules/import", content=journey_bundle(), headers={"Content-Type": "application/zip"}), 201
    )
    campaign = ok(
        http.post("/api/campaigns", json={"name": "Hardby", "module_id": module["id"], "setting": "greyhawk"}), 201
    )["id"]
    play = f"/api/campaigns/{campaign}"

    # 1. The campaign has the module's map (it wins the clash with the setting's), the faction, its clock and the
    # quest, none known yet.
    assert ok(http.get(f"{play}/world-maps/greyhawk-region"))["source"] == "module"
    [brotherhood] = ok(http.get(f"{play}/factions"))
    assert (brotherhood["id"], brotherhood["known"]) == ("scarlet-brotherhood", False)
    [clock] = ok(http.get(f"{play}/clocks"))
    assert (clock["kind"], clock["days_remaining"], clock["done_day"]) == ("countdown", 3, None)
    assert [(q["id"], q["known"]) for q in ok(http.get(f"{play}/quests"))] == [("letter-to-hardby", False)]

    # Paid images on, the scene painted by FakeImages.
    ok(http.put("/api/preferences", json={"choices": {"image.scene": {"provider": "fake-images"}}}))
    assert ok(http.put(f"{play}/play/options", json={"paid_images": True}))["paid_images"] is True
    start = ok(http.get(f"{play}/world"))["date"]
    assert start == "1 Planting 576 CY"

    # 2. The first beat: the party, the horse, the portrait, the scene, the quest, and the road.
    ok(http.post(f"{play}/act", json={"text": "We take Lorne's letter and ride for Hardby."}), 202)
    delve.settle(campaign)
    entries = ok(http.get(f"{play}/story", params={"limit": 200}))["entries"]
    assert not [e for e in entries if e["kind"] == "dm_error"]
    failed = [e["payload"] for e in entries if e["kind"] == "tool" and e["payload"].get("failed")]
    assert failed == []

    # 3. The journey: a beat per leg until the party is in Hardby.
    for _ in range(LEGS):
        if ok(http.get(f"{play}/world"))["position"]["at_label"] == "Hardby":
            break
        ok(http.post(f"{play}/act", json={"text": "We ride on."}), 202)
        delve.settle(campaign)
    world = ok(http.get(f"{play}/world"))
    assert world["position"] == {"map": "greyhawk-region", "at_label": "Hardby"}
    assert world["date"] != start and world["weather"]["label"]

    # The clock completed once on the way; the date moved past it.
    [clock] = ok(http.get(f"{play}/clocks"))
    assert (clock["days_remaining"], clock["done_day"]) == (0, 4)
    state = ok(http.get(f"{play}/play/state"))
    assert state["date"] == world["date"]

    # Each day's miles are the slowest rider's: Garrek walks 12, Pippa rides at 24 (walking, she would make 6), × the
    # terrain's rate × the weather's pace. The horse doubles every day but the last, whatever the dice rolled.
    journeys = [j for j in travel_results(http, play) if j["mode"] == "foot"]
    assert journeys[0]["via_roads"] is True and journeys[-1]["arrived"] is True
    assert all(j["arrived"] or j["legs"][-1]["encounter"] for j in journeys), "a journey stops only at an encounter"
    assert sum(j["days"] for j in journeys) >= 4  # the clock's three days, and more
    for journey in journeys:
        assert len(journey["legs"]) == journey["days"] and journey["mode"] == "foot"
        assert (journey["journey"] is None) == journey["arrived"], "a stopped leg keeps the journey"
        full = journey["legs"][:-1] if journey["arrived"] else journey["legs"]  # the day of arrival ends early
        for leg in full:
            rate, sky = travel.TERRAIN_RATES[leg["terrain"]], weather.pace(leg["weather"])
            assert leg["miles"] == round(2 * 12 * rate * sky, 1), leg
            assert abs(leg["km"] - leg["miles"] * overland.MILES_TO_KM) <= 0.2, leg
            assert sky == 0 or leg["miles"] > round(2 * 6 * rate * sky, 1), "on foot, Pippa would have been slower"

    # 4. Back in Greyhawk, by river boat down the Selintan: the landing comes into sight, and the known places grow.
    view = f"{play}/world-maps/greyhawk-region/view"
    before = {f["name"] for f in ok(http.get(view))["features"] if f["layer"] == "places"}
    assert "Selintan Mouth" not in before
    delve.go_to_turn(1 + LEGS)
    for _ in range(1 + RIVER_BEATS):
        ok(http.post(f"{play}/act", json={"text": "We take a boat down the river."}), 202)
        delve.settle(campaign)
        if ok(http.get(f"{play}/world"))["position"]["at_label"] == "Selintan Mouth":
            break
    assert ok(http.get(f"{play}/world"))["position"] == {"map": "greyhawk-region", "at_label": "Selintan Mouth"}
    river = [j for j in travel_results(http, play) if j["mode"] == "river"]
    # An encounter can stop the first leg out of sight of the landing (10 km), so it comes into sight on some leg.
    assert [place for j in river for place in j["came_into_sight"]] == ["Selintan Mouth"] and river[-1]["arrived"]
    after = {f["name"] for f in ok(http.get(view))["features"] if f["layer"] == "places"}
    assert before | {"Selintan Mouth"} <= after

    # 5. A player at the table sees the route's places, the quest and its known note, and nothing DM-only.
    token = ok(http.get(f"{play}/invite"))["join_token"]
    with httpx.Client(base_url=str(http.base_url), timeout=30) as ana:
        ok(
            ana.post(
                f"/api/join/{token}/account",
                json={
                    "username": "ana",
                    "password": PASSWORD,
                    "display_name": "Ana",
                    "language": "en",
                    "role": "player",
                },
            ),
            201,
        )
        seen = ok(ana.get(f"{play}/world"))
        assert [(q["id"], q["status"], [n["text"] for n in q["log"]]) for q in seen["quests"]] == [
            ("letter-to-hardby", "active", ["Lorne gave you the letter."])
        ]
        assert [p["name"] for p in seen["possessions"]] == ["Bramble"]
        assert seen["factions"] == []
        assert [m["name"] for m in ok(ana.get(f"{play}/world-maps"))] == ["greyhawk-region"]
        view = ok(ana.get(f"{play}/world-maps/greyhawk-region/view"))
        assert {"Greyhawk", "Hardby"} <= {f["name"] for f in view["features"]}
        assert view["party"] is not None
        assert ana.get(f"{play}/world-maps/greyhawk-region/dm-view").status_code == 403
        story = ok(ana.get(f"{play}/story", params={"limit": 200}))
        for what in (seen, view, story):
            text = what if isinstance(what, str) else json.dumps(what)
            assert SECRET not in text and "smugglers-cove" not in text
    # The DM's view has the cove.
    assert SECRET in http.get(f"{play}/world-maps/greyhawk-region/dm-view").text

    # 6. Garrek's portrait is portraitgen's: a description and a seed, no picture.
    garrek = next(c for c in ok(http.get(f"{play}/characters")) if c["name"] == "Garrek")
    assert garrek["sheet"]["portrait"] == {
        "kind": "traits",
        "describe": "a broad human fighter, black beard, scarred",
        "seed": garrek["id"],
    }

    # 7. The scene was painted in the background, and landed in the story for everyone.
    scene = wait_for_scene(http, play)
    assert scene["payload"]["caption"] == "Dawn" and scene["audience"] is None
    picture = http.get(f"{play}/pictures/{scene['payload']['image_id']}")
    assert picture.status_code == 200 and picture.headers["content-type"].startswith("image/")


def travel_results(http: httpx.Client, play: str) -> list[dict]:
    """Every `travel` answer in the DM log, oldest first: the tool results that carry `legs`."""
    raws = [entry["raw"] for entry in ok(http.get(f"{play}/dm/log"))["entries"]]
    return [
        raw["content"]
        for raw in raws
        if raw.get("type") == "tool_result"
        and raw.get("ok")
        and isinstance(raw.get("content"), dict)
        and "legs" in raw["content"]
    ]


def wait_for_scene(http: httpx.Client, play: str, timeout: float = 30) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        entries = ok(http.get(f"{play}/story", params={"limit": 200}))["entries"]
        scenes = [e for e in entries if e["kind"] == "scene"]
        if scenes:
            return scenes[0]
        time.sleep(0.1)
    raise AssertionError("the scene wasn't painted")
