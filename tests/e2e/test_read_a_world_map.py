"""A world map read from a picture and travelled, end to end (plan 7 Task 21): `delve serve` with the fake `claude`,
whose vision calls are answered from the synthetic picture's truth (`tests/e2e/fake_play_server.py`), and
`DELVE_OCR=off`, so tesseract never runs and the labels come from the vision calls.

The organiser uploads `hex_map`'s PNG with its key, 1 hex = 30 miles, to the crypt module. The job ends with the map in
review and its doubts; the organiser maps the colours, decides the doubts and accepts it. A campaign of the module
copies it; the party starts knowing the land around Brask, where the DM places it. The DM adds a place in the land the
party doesn't know (`SECRET-XYZZY`), and the party walks the road to Corvel, then to Arden, the town on the river, and
goes by river boat down the river to Port Wyn at its mouth. Each leg's places come into sight, and the seat's known
places grow.

`delve serve` rolls with the system's dice, so an encounter may stop a leg where it happens: each next beat goes on
(`travel()`) until the party arrives, and the script then goes on with the next leg. A second seat's view, tiles, list
and event stream never show the planted place, nor the land the party doesn't know.

The synthetic picture has no region label, so the start knowledge is an area drawn around Brask, not a region.
"""

from __future__ import annotations

import json
import sys
import threading
import time

import httpx
import pytest

from delve.maps.geo.geojson import from_geojson
from delve.maps.geo.grid import cell_at
from delve.modules.dscn import Bundle
from tests.e2e.fake_play_server import ROOT, picture_png
from tests.e2e.test_play_with_fake_claude import CRYPT, GARREK, PIPPA, SECRET, Delve
from tests.web.conftest import PASSWORD

WORLDMAP = "/api/conversions/worldmap"
KEY = {"cell": "hex", "distance": "30", "units": "miles"}
GO_ON = [{"tool": "travel", "args": {}}, {"text": "You go on."}]
REPEATS = 12  # beats per leg; an encounter stops one about once in six days


def ok(response: httpx.Response, status: int = 200):
    assert response.status_code == status, response.text
    return response.json() if response.content else None


def ended(http: httpx.Client, conversion_id: str, timeout: float = 120) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        now = ok(http.get(f"/api/conversions/{conversion_id}"))
        if now["status"] != "running":
            return now
        time.sleep(0.2)
    raise AssertionError(f"conversion {conversion_id} still running")


def leg(to: str, mode: str, text: str) -> list[dict]:
    return [{"tool": "travel", "args": {"to": to, "mode": mode}}, {"text": text}]


def script(secret_at: str) -> tuple[list, dict[str, int]]:
    """The DM's turns: the setup and the first leg, then each next leg, each followed by beats that go on; and the
    index of each leg's first turn."""
    setup = [
        {"text": "Dawn in Brask. "},
        {"tool": "session_primer", "args": {}},
        {"tool": "new_session", "args": {"title": "Down the river"}},
        {"tool": "create_character", "args": {"name": "Garrek", "sheet": GARREK}},
        {"tool": "create_character", "args": {"name": "Pippa", "sheet": PIPPA}},
        {"tool": "place_party", "args": {"at": "Brask"}},
        {
            "tool": "add_place",
            "args": {"name": f"{SECRET} Lair", "kind": "ruin", "at": secret_at, "notes": f"{SECRET}: the wyrm."},
        },
        *leg("Corvel", "foot", "The road runs east to Corvel."),
    ]
    turns: list = [setup, *[GO_ON] * REPEATS]
    starts = {"Corvel": 0}
    for to, mode, text in (("Arden", "foot", "North to the river."), ("Port Wyn", "river", "Down the river.")):
        starts[to] = len(turns)
        turns += [leg(to, mode, text), *[GO_ON] * REPEATS]
    return turns, starts


@pytest.fixture
def delve(tmp_path):
    server = Delve(tmp_path, turns=[], side=())
    # `claude` is the browser checks': the vision calls are answered from the picture's truth, the rest by the fake.
    server.claude.write_text(
        f'#!/bin/sh\nPYTHONPATH="{ROOT}" exec "{sys.executable}" -m tests.e2e.fake_play_server --claude "$@"\n',
        encoding="utf-8",
    )
    yield server
    server.stop()


def travel_results(http: httpx.Client, play: str) -> list[dict]:
    """Every `travel` answer in the DM log, oldest first."""
    raws = [entry["raw"] for entry in ok(http.get(f"{play}/dm/log"))["entries"]]
    return [
        raw["content"]
        for raw in raws
        if raw.get("type") == "tool_result"
        and raw.get("ok")
        and isinstance(raw.get("content"), dict)
        and "legs" in raw["content"]
    ]


class Listener:
    """A seat's event stream, read in a thread until `stop`."""

    def __init__(self, client: httpx.Client, url: str) -> None:
        self.text: list[str] = []
        self._stop = threading.Event()
        self._client = client
        self._url = url
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        try:
            with self._client.stream("GET", self._url, timeout=None) as response:
                for line in response.iter_lines():
                    self.text.append(line)
                    if self._stop.is_set():
                        return
        except httpx.HTTPError:
            return

    def stop(self) -> str:
        self._stop.set()
        self._thread.join(timeout=5)
        return "\n".join(self.text)


def test_a_world_map_read_from_a_picture_reviewed_accepted_and_travelled(delve):
    http = delve.http
    module = ok(
        http.post(
            "/api/modules/import",
            content=Bundle.load(CRYPT).to_zip(),
            headers={"Content-Type": "application/zip"},
        ),
        201,
    )
    mid = module["id"]

    # 1–2. The picture with its key; the job ends with the map in review, and its doubts.
    started = ok(
        http.post(
            WORLDMAP,
            params={**KEY, "module_id": mid, "name": "westmarch", "title": "The Westmarch"},
            content=picture_png(),
            headers={"Content-Type": "image/png"},
        ),
        202,
    )
    done = ended(http, started["id"])
    assert done["status"] == "done", done["error"]
    path = f"/api/modules/{mid}/world-maps/westmarch"
    doc = ok(http.get(path))
    assert doc["status"] == "review"
    doubts = doc["reading"]["doubts"]
    assert {"cluster-unmapped", "kind-guessed", "cell-mixed"} <= {d["kind"] for d in doubts}
    names = {f["properties"].get("name") for f in doc["geo"]["features"]}
    assert {"Arden", "Brask", "Corvel", "Port Wyn"} <= names, "the labels came from the vision calls"

    # 3. The colours as Claude suggested them, the doubts decided, and the accept.
    clusters = {str(c["id"]): c["suggestion"] for c in doc["reading"]["clusters"] if c["terrain"] is None}
    assert all(clusters.values())
    ok(http.post(f"{path}/review", json={"clusters": clusters}))
    port = next(d for d in doubts if d["kind"] == "kind-guessed")
    open_kinds = {d["kind"] for d in doubts if not d["resolved"] and d["kind"] != "cluster-unmapped"} - {port["kind"]}
    ok(
        http.post(
            f"{path}/review", json={"decisions": {port["id"]: "port"}, "kinds": dict.fromkeys(open_kinds, "keep")}
        )
    )
    accepted = ok(http.post(f"{path}/accept", json={}))
    assert accepted["status"] == "ready"
    geo = from_geojson(accepted["geo"]).geo

    # 4. A campaign copies it; the party starts knowing the land around Brask.
    campaign = ok(http.post("/api/campaigns", json={"name": "Westmarch", "module_id": mid}), 201)["id"]
    play = f"/api/campaigns/{campaign}"
    assert "westmarch" in {m["name"] for m in ok(http.get(f"{play}/organiser/world-maps"))}
    brask = feature_point(accepted["geo"], "Brask")
    x, y = brask
    ring = [[x - 60, y - 60], [x + 60, y - 60], [x + 60, y + 60], [x - 60, y + 60], [x - 60, y - 60]]
    ok(http.put(f"{play}/world-maps/westmarch/knowledge", json={"how": "area", "ring": ring}))

    # The planted place goes in the top right, far from the way: land the party never comes to know.
    far = (geo.frame.width_km - 1.5 * geo.grid.size_km, 1.5 * geo.grid.size_km)
    secret_cell = cell_at(geo.grid, *far)
    turns, starts = script(f"{far[0]:.1f},{far[1]:.1f}")
    delve.script.write_text(json.dumps({"turns": turns, "side": [], "translations": {}}), encoding="utf-8")

    # A second seat, Ana, listening from the start.
    token = ok(http.get(f"{play}/invite"))["join_token"]
    ana = httpx.Client(base_url=str(http.base_url), timeout=30)
    ok(
        ana.post(
            f"/api/join/{token}/account",
            json={"username": "ana", "password": PASSWORD, "display_name": "Ana", "language": "en", "role": "player"},
        ),
        201,
    )
    stream = Listener(ana, f"/api/events?campaign={campaign}")
    assert seat_places(ana, play) == {"Brask"}, "the start: the land around Brask"

    # 5. The beats: the host starts the session (DEL-199), whose beat is the DM's setup, placed at Brask with the road
    # to Corvel begun; on to Corvel, to Arden, down the river to Port Wyn.
    ok(http.post(f"{play}/session/start", json={}), 202)
    delve.settle(campaign)
    seen: list[set[str]] = []
    for to in ("Corvel", "Arden", "Port Wyn"):
        if starts[to] > 0:  # the first leg's turn was the session's start
            delve.go_to_turn(starts[to])
        for _ in range(REPEATS + 1):
            if ok(http.get(f"{play}/world"))["position"]["at_label"] == to:
                break
            ok(http.post(f"{play}/act", json={"text": f"We make for {to}."}), 202)
            delve.settle(campaign)
        assert ok(http.get(f"{play}/world"))["position"] == {"map": "westmarch", "at_label": to}
        seen.append(seat_places(ana, play))

    entries = ok(http.get(f"{play}/story", params={"limit": 200}))["entries"]
    assert not [e for e in entries if e["kind"] == "dm_error"]
    assert [e["payload"] for e in entries if e["kind"] == "tool" and e["payload"].get("failed")] == []

    journeys = travel_results(http, play)
    first = journeys[0]
    assert first["mode"] == "foot" and first["via_roads"] is True, "Brask to Corvel by the road"
    river = [j for j in journeys if j["mode"] == "river"]
    assert river and river[-1]["arrived"]
    sighted = {name for j in journeys for name in j["came_into_sight"]}
    assert {"Corvel", "Arden", "Port Wyn"} <= sighted
    assert seen[0] < seen[1] <= seen[2] and {"Brask", "Corvel"} <= seen[0] and "Port Wyn" in seen[2]

    # 6. Ana sees only what the party knows: never the planted place, its cell, nor anything of it.
    view = ok(ana.get(f"{play}/world-maps/westmarch/view"))
    assert view["party"] is not None and not view["known"]["all"]
    assert secret_cell not in known_cells(view["known"]["cells"])
    tile = ana.get(f"{play}/world-maps/westmarch/tiles/0/0/0", params={"v": view["tiles_version"]})
    assert tile.status_code == 200 and tile.headers["content-type"] == "image/jpeg"
    dm = ok(http.get(f"{play}/world-maps/westmarch/dm-view"))
    assert SECRET in json.dumps(dm), "the DM's view has the place"
    for what in (
        view,
        ok(ana.get(f"{play}/world-maps")),
        ok(ana.get(f"{play}/world")),
        ok(ana.get(f"{play}/story", params={"limit": 200})),
    ):
        assert SECRET not in json.dumps(what) and "Lair" not in json.dumps(what)
    events = stream.stop()
    replay = Listener(ana, f"/api/events?since=0&campaign={campaign}")
    time.sleep(2)
    replayed = replay.stop()
    ana.close()
    assert events and replayed, "Ana's stream got the beats"
    for frames in (events, replayed):
        assert SECRET not in frames and "Lair" not in frames


def feature_point(document: dict, name: str) -> tuple[float, float]:
    [feature] = [f for f in document["features"] if f["properties"].get("name") == name]
    x, y = feature["geometry"]["coordinates"]
    return float(x), float(y)


def known_cells(runs: list[list[int]]) -> set[int]:
    """The cells of the runs `[[start, stop), …]`."""
    return {i for start, stop in runs for i in range(start, stop)}


def seat_places(seat: httpx.Client, play: str) -> set[str]:
    """The places the seat's view of the map holds; none when the map isn't the seat's yet."""
    response = seat.get(f"{play}/world-maps/westmarch/view")
    if response.status_code == 404:
        return set()
    return {f["name"] for f in ok(response)["features"] if f["layer"] == "places"}
