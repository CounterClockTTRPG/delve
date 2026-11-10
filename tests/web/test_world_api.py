"""The world for the seats and the organisers (plan 6 Task 8, Decision 7): `GET …/world` and the seats' world-map
view leave out what the characters don't know, a hidden place first of all, until the DM reveals it; the DM view and
the maps' text are the organisers'. The module's maps are copied into the campaign when it is made."""

import json
import math
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from delve.domain.modules import ModuleMap
from delve.domain.world import CampaignWorldMap, Faction, Quest, QuestNote, WorldMapSource
from delve.maps.geo import pictures
from delve.maps.geo.geojson import to_geojson
from delve.maps.geo.model import Frame, GeoFeature, GeoMap, Grid, PictureRef
from delve.modules.source import ModuleSource
from delve.play import factions, possessions, world_maps
from delve.play.context import context_for
from delve.web.seats import SEAT_COOKIE, new_seat_token, token_hash
from tests.fixtures.play_reference import PlayReference
from tests.fixtures.rulesets import over
from tests.maps.geo.test_tiles import halves
from tests.play.test_travel import SECRET, VALE, VALE_MAP
from tests.web.conftest import BASE_URL


def vale_module(storage, worldmaps=(VALE_MAP,)):
    module = storage.modules.create("The Vale")
    storage.modules.put_map(module.id, ModuleMap("crypt", "map", "map crypt {}\n", is_default=True))
    storage.module_sources.put(module.id, ModuleSource(worldmaps=tuple(worldmaps)))
    return module


def made(local, module_id: str, **body) -> str:
    response = local.post("/api/campaigns", json={"name": "Tuesday", "module_id": module_id, **body})
    assert response.status_code == 201, response.json()
    return response.json()["id"]


@pytest.fixture
def cid(local, storage):
    """A campaign of the vale without a setting, its party at Oakton, a known quest and an unknown one, a known
    faction and an unknown one, and the party's ship, each with a planted secret where the players may not look."""
    campaign_id = made(local, vale_module(storage).id, setting=None)
    ctx = context_for(storage, campaign_id, "beat-1", catalogs=over(PlayReference()))
    world_maps.place_party(ctx, "oakton")
    storage.quests.put(
        Quest(
            campaign_id,
            "relic",
            "Find the relic",
            status="active",
            known=True,
            giver="the abbot",
            stakes="The ward fails.",
            log=(QuestNote(1, "The abbot sent us.", True), QuestNote(1, f"{SECRET}: the abbot lied.", False)),
            notes_md=f"{SECRET}: the relic is fake.",
        )
    )
    storage.quests.put(Quest(campaign_id, "plot", f"{SECRET}: the coup", status="available", known=False))
    storage.factions.put(Faction(campaign_id, "watch", "The Watch", known=True, reputation=30, notes_md=SECRET))
    storage.factions.put(Faction(campaign_id, "cult", f"{SECRET} cult", known=False))
    factions.add_clock(ctx, "The eye wakes", days=3, faction="watch", on_complete=SECRET)
    possessions.add(ctx, "The Gull", "ship", notes=f"{SECRET}: smuggles for the cult.", stats={"mv": 12})
    return campaign_id


@pytest.fixture
def ana(app, storage, cid):
    """A player's browser on the LAN, seated at the campaign."""
    token = new_seat_token()
    storage.seats.create(cid, "Ana", "en", "player", token_hash=token_hash(token))
    with TestClient(app, base_url=BASE_URL) as client:
        client.cookies.set(SEAT_COOKIE, token)
        yield client


def path(cid: str, rest: str) -> str:
    return f"/api/campaigns/{cid}/{rest}"


def test_the_seats_world_leaves_out_what_the_characters_dont_know(ana, cid):
    response = ana.get(path(cid, "world"))
    assert response.status_code == 200, response.text
    world = response.json()
    assert SECRET not in response.text
    assert set(world) == {"date", "weather", "position", "quests", "factions", "possessions"}
    assert world["date"] == "Day 1" and world["weather"] is None
    assert world["position"] == {"map": "vale", "at_label": "Oakton"}
    [quest] = world["quests"]
    assert quest["title"] == "Find the relic" and quest["log"] == [{"day": 1, "text": "The abbot sent us."}]
    assert world["factions"] == [{"id": "watch", "name": "The Watch", "standing": "Friendly"}]
    [gull] = world["possessions"]
    assert gull["name"] == "The Gull" and "notes_md" not in gull


def test_the_seats_map_leaves_out_a_hidden_place_until_it_is_revealed(ana, local, storage, cid):
    assert ana.get(path(cid, "world-maps")).json() == [{"name": "vale", "title": "The Vale"}]
    view = ana.get(path(cid, "world-maps/vale/view"))
    assert view.status_code == 200, view.text
    seen = view.json()
    assert "Drowned Tower" not in view.text and SECRET not in view.text and "dm_notes" not in view.text
    assert "Oakton" in {f["name"] for f in seen["features"]} and seen["party"] is not None
    assert seen["picture"] is None and seen["tiles_version"]
    dm = local.get(path(cid, "world-maps/vale/dm-view"))
    assert dm.status_code == 200, dm.text
    tower = next(f for f in dm.json()["features"] if f["id"] == "old-tower")
    assert (tower["name"], tower["hidden"], tower["known"]) == ("The Drowned Tower", True, False)
    assert tower["dm_notes"].startswith(SECRET) and not tower["description"]

    world_maps.reveal(context_for(storage, cid, "beat-2", catalogs=over(PlayReference())), "old-tower")
    view = ana.get(path(cid, "world-maps/vale/view"))
    assert "The Drowned Tower" in view.text and SECRET not in view.text


def test_the_party_at_a_hidden_place_shows_no_name(ana, storage, cid):
    world_maps.place_party(context_for(storage, cid, "beat-2", catalogs=over(PlayReference())), "old-tower")
    assert ana.get(path(cid, "world")).json()["position"] == {"map": "vale", "at_label": None}


def test_a_seat_gets_404_for_a_map_it_may_not_see(ana, local, cid):
    assert ana.get(path(cid, "world-maps/nowhere/view")).status_code == 404
    assert ana.get(path(cid, "world-maps/nowhere/tiles/0/0/0")).status_code == 404
    # A map the party knows nothing of is not there for a seat, by its list, its view or its tiles.
    assert local.put(path(cid, "world-maps/isles"), json={"title": "The Isles", "geo": isles_doc()}).status_code == 200
    assert [m["name"] for m in ana.get(path(cid, "world-maps")).json()] == ["vale"]
    assert ana.get(path(cid, "world-maps/isles/view")).status_code == 404
    assert ana.get(path(cid, "world-maps/isles/tiles/0/0/0")).status_code == 404
    assert local.get(path(cid, "world-maps/nowhere/view")).status_code == 404
    assert local.get(path(cid, "world-maps/nowhere/dm-view")).status_code == 404


ORGANISER_ONLY = [
    ("GET", "organiser/world-maps"),
    ("GET", "world-maps/vale/dm-view"),
    ("GET", "world-maps/vale"),
    ("PUT", "world-maps/vale"),
    ("DELETE", "world-maps/vale"),
    ("PUT", "world-maps/vale/knowledge"),
    ("POST", "world-maps/geojson"),
    ("GET", "world-maps/vale/export.geojson"),
    ("GET", "world-maps/vale/picture"),
]


@pytest.mark.parametrize(("method", "rest"), ORGANISER_ONLY)
def test_the_organisers_world_map_routes_refuse_a_seat(ana, cid, method, rest):
    body = {"json": {}} if method != "GET" else {}
    assert ana.request(method, path(cid, rest), **body).status_code == 403


def isles_doc(**picture) -> dict:
    """A small Delve document of its own: 100 × 50 km in squares of 10, one port."""
    geo = GeoMap(
        Frame(100.0, 50.0),
        Grid("square", 10.0, 10, 5),
        "w" * 50,
        (GeoFeature("skerry", "places", "port", "Skerry", {"type": "Point", "coordinates": [55.0, 25.0]}),),
        picture.get("picture"),
    )
    return to_geojson(geo)


def test_organisers_read_write_and_delete_a_map(local, cid):
    read = local.get(path(cid, "world-maps/vale"))
    assert read.status_code == 200, read.text
    vale = read.json()
    assert set(vale) == {"name", "title", "source", "status", "geo", "picture", "knowledge", "reading"}
    assert (vale["name"], vale["title"], vale["source"], vale["status"]) == ("vale", "The Vale", "module", "ready")
    assert vale["geo"]["delve"]["frame"]["units"] == "miles" and vale["picture"] is None
    assert vale["knowledge"]["everything"] is False and vale["knowledge"]["cells"]  # around Oakton

    vale["geo"]["features"] = [f for f in vale["geo"]["features"] if f["id"] != "east-glade"]
    put = local.put(path(cid, "world-maps/vale"), json={"title": "The Green Vale", "geo": vale["geo"]})
    assert put.status_code == 200, put.text
    assert put.json()["title"] == "The Green Vale" and put.json()["knowledge"] == vale["knowledge"]
    assert "east-glade" not in {f["id"] for f in local.get(path(cid, "world-maps/vale")).json()["geo"]["features"]}

    broken = {**vale["geo"], "delve": {**vale["geo"]["delve"], "terrain": "p"}}
    bad = local.put(path(cid, "world-maps/vale"), json={"title": "x", "geo": broken})
    assert bad.status_code == 422, bad.text
    assert bad.json()["error"] and bad.json()["problems"]
    assert local.put(path(cid, "world-maps/vale"), json={"title": "x", "geo": {"type": "x"}}).status_code == 422

    new = local.put(path(cid, "world-maps/isles"), json={"title": "The Isles", "geo": isles_doc()})
    assert new.status_code == 200 and new.json()["source"] == "campaign"
    assert new.json()["knowledge"] == {"everything": False, "cells": [], "features": [], "forgotten": []}
    assert local.request("DELETE", path(cid, "world-maps/isles"), json={}).status_code == 204
    assert local.get(path(cid, "world-maps/isles")).status_code == 404
    assert local.request("DELETE", path(cid, "world-maps/isles"), json={}).status_code == 404


def test_a_put_keeps_a_map_in_review_in_review(local, storage, cid):
    local.put(path(cid, "world-maps/isles"), json={"title": "The Isles", "geo": isles_doc()})
    storage.world_maps.put(replace(storage.world_maps.get(cid, "isles"), status="review"))
    put = local.put(path(cid, "world-maps/isles"), json={"title": "The Isles", "geo": isles_doc()})
    assert put.status_code == 200 and put.json()["status"] == "review"


def test_the_organisers_list_has_every_map_with_its_status(local, storage, cid):
    local.put(path(cid, "world-maps/isles"), json={"title": "The Isles", "geo": isles_doc()})
    storage.world_maps.put(replace(storage.world_maps.get(cid, "isles"), status="review"))
    storage.world_maps.put(CampaignWorldMap(cid, "towns", "towns", "campaign", "city northby { at 0,50 }\n"))
    listed = local.get(path(cid, "organiser/world-maps"))
    assert listed.status_code == 200, listed.text
    assert listed.json() == [
        {"name": "vale", "title": "The Vale", "status": "ready", "source": "module", "picture": False},
        {"name": "isles", "title": "The Isles", "status": "review", "source": "campaign", "picture": False},
    ]


def test_what_the_party_knows_at_the_start(ana, local, cid):
    everything = local.put(path(cid, "world-maps/vale/knowledge"), json={"how": "everything"})
    assert everything.status_code == 200, everything.text
    assert everything.json()["everything"] is True
    assert ana.get(path(cid, "world-maps/vale/view")).json()["known"]["all"] is True
    nothing = local.put(path(cid, "world-maps/vale/knowledge"), json={"how": "nothing"})
    assert nothing.json() == {"everything": False, "cells": [], "features": [], "forgotten": []}
    ring = [[0, 0], [400, 0], [400, 300], [0, 300]]
    area = local.put(path(cid, "world-maps/vale/knowledge"), json={"how": "area", "ring": ring})
    assert area.status_code == 200 and area.json()["cells"]
    unknown = local.put(path(cid, "world-maps/vale/knowledge"), json={"how": "regions", "regions": ["atlantis"]})
    assert unknown.status_code == 422 and unknown.json()["error"]
    assert local.put(path(cid, "world-maps/vale/knowledge"), json={"how": "most"}).status_code == 422
    assert local.put(path(cid, "world-maps/nowhere/knowledge"), json={"how": "nothing"}).status_code == 404


HAND = json.loads((Path(__file__).parents[1] / "maps/geo/fixtures/hand.geojson").read_text())
HAND_MAPPING = {"kind": "type", "name": "label", "values": {"settlement": "town", "highway": "road", "mere": "lake"}}


def test_a_geojson_import_without_a_size_asks_for_one(local, cid):
    body = {"name": "hand", "title": "Hand", "document": HAND, "mapping": HAND_MAPPING}
    asked = local.post(path(cid, "world-maps/geojson"), json=body)
    assert asked.status_code == 422, asked.text
    assert asked.json() == {
        "error": "The map needs its size.",
        "needs": "scale",
        "properties": ["description", "label", "type"],
        "kinds": ["beacon", "highway", "mere", "settlement", "woods"],
    }
    assert local.get(path(cid, "world-maps/hand")).status_code == 404


def test_a_geojson_import_by_its_width_or_a_known_distance(local, cid):
    body = {"name": "hand", "title": "Hand", "document": HAND, "mapping": HAND_MAPPING, "width_km": 200}
    made = local.post(path(cid, "world-maps/geojson"), json=body)
    assert made.status_code == 201, made.text
    assert made.json()["name"] == "hand" and made.json()["source"] == "campaign"
    assert made.json()["geo"]["delve"]["frame"]["width_km"] == pytest.approx(200)
    assert any("woods" in w for w in made.json()["warnings"])  # no mapping for it: dropped, with a warning
    assert local.post(path(cid, "world-maps/geojson"), json=body).status_code == 409

    known = {"from": "Oakvale", "to": "Rivermouth", "distance": 90, "units": "miles"}
    body = {"name": "hand2", "document": HAND, "mapping": HAND_MAPPING, "known": known}
    by_miles = local.post(path(cid, "world-maps/geojson"), json=body)
    assert by_miles.status_code == 201, by_miles.text
    assert by_miles.json()["title"] == "hand2"
    places = {f["properties"]["name"]: f["geometry"]["coordinates"] for f in by_miles.json()["geo"]["features"]}
    assert math.dist(places["Oakvale"], places["Rivermouth"]) == pytest.approx(90 * 1.609344)  # miles made km
    wrong = {**body, "name": "hand3", "known": {**known, "to": "Atlantis"}}
    assert local.post(path(cid, "world-maps/geojson"), json=wrong).status_code == 422


def test_the_export_is_the_delve_document_with_terrain_cells(local, cid):
    export = local.get(path(cid, "world-maps/vale/export.geojson"))
    assert export.status_code == 200, export.text
    assert export.headers["content-disposition"] == 'attachment; filename="vale.geojson"'
    assert export.headers["content-type"].startswith("application/geo+json")
    doc = export.json()
    assert doc["delve"]["version"] == 1
    assert sum(1 for f in doc["features"] if f["properties"]["layer"] == "terrain") == 200 * 42
    assert "old-tower" in {f["id"] for f in doc["features"]}


def pictured_isles(local, storage, cid) -> str:
    """The isles over a picture of 512 × 256 px, 1 km a px, its right half magenta; the party knows its left half."""
    stored = pictures.store(storage, halves(), "image/png")
    ref = PictureRef(stored.id, 512, 256, km_per_px=1.0)
    geo = GeoMap(Frame(512.0, 256.0), Grid("square", 32.0, 16, 8), "p" * 128, (), ref)
    assert local.put(path(cid, "world-maps/isles"), json={"title": "Isles", "geo": to_geojson(geo)}).status_code == 200
    ring = [[0, 0], [256, 0], [256, 256], [0, 256]]
    assert local.put(path(cid, "world-maps/isles/knowledge"), json={"how": "area", "ring": ring}).status_code == 200
    return stored.id


def test_a_seats_tiles_are_fogged_and_never_where_nothing_is_known(ana, local, storage, cid):
    picture_id = pictured_isles(local, storage, cid)
    view = ana.get(path(cid, "world-maps/isles/view")).json()
    assert view["picture"] == {"width_px": 512, "height_px": 256, "km_per_px": 1.0, "max_zoom": 1}
    assert picture_id not in json.dumps(view)
    raw = ana.get(path(cid, "world-maps/isles/tiles/1/0/0"))
    assert raw.status_code == 200 and raw.content == pictures.tile(storage, picture_id, 1, 0, 0)
    assert raw.headers["content-type"] == "image/jpeg"
    assert raw.headers["x-content-type-options"] == "nosniff"
    assert raw.headers["cache-control"] == "private, max-age=3600"
    unknown = ana.get(path(cid, "world-maps/isles/tiles/1/1/0"))
    assert unknown.status_code == 404 and unknown.json() == {"error": "unknown"}
    fogged = ana.get(path(cid, "world-maps/isles/tiles/0/0/0"))
    assert fogged.status_code == 200 and fogged.content != pictures.tile(storage, picture_id, 0, 0, 0)
    assert ana.get(path(cid, "world-maps/isles/tiles/7/0/0")).status_code == 404
    dm = local.get(path(cid, "world-maps/isles/dm-view")).json()
    assert dm["picture"]["id"] == picture_id and dm["picture"]["max_zoom"] == 1

    before = view["tiles_version"]
    local.put(path(cid, "world-maps/isles/knowledge"), json={"how": "everything"})
    assert ana.get(path(cid, "world-maps/isles/view")).json()["tiles_version"] != before
    assert ana.get(path(cid, "world-maps/isles/tiles/1/1/0")).status_code == 200


def test_the_picture_download_is_the_original(local, storage, cid):
    picture_id = pictured_isles(local, storage, cid)
    got = local.get(path(cid, "world-maps/isles/picture"))
    assert got.status_code == 200
    assert got.content == halves() and pictures.original(storage, picture_id) == (got.content, "image/png")
    assert got.headers["content-type"] == "image/png"
    assert got.headers["x-content-type-options"] == "nosniff"
    assert got.headers["content-disposition"] == 'attachment; filename="isles.png"'
    none = local.get(path(cid, "world-maps/vale/picture"))
    assert none.status_code == 404 and none.json() == {"error": "no picture"}


def test_a_map_that_doesnt_read_is_offline(local, storage, cid):
    stored = storage.world_maps.get(cid, "vale")
    storage.world_maps.put(type(stored)(cid, "vale", "The Vale", "module", "workspace vale { model { city } }"))
    for view in ("view", "dm-view"):
        response = local.get(path(cid, f"world-maps/vale/{view}"))
        assert response.status_code == 409 and response.json() == {"error": "map offline"}


def test_a_change_publishes_world_with_no_map_name(local, app, cid):
    seq = app.state.events._seq
    local.put(path(cid, "world-maps/isles"), json={"title": "The Isles", "geo": isles_doc()})
    local.put(path(cid, "world-maps/isles/knowledge"), json={"how": "everything"})
    local.post(path(cid, "world-maps/geojson"), json={"name": "hand", "document": HAND, "mapping": HAND_MAPPING, "width_km": 10})
    local.request("DELETE", path(cid, "world-maps/isles"), json={})
    published = [e for e in app.state.events._buffer if e.seq > seq and e.type == "world"]
    assert [(e.data, e.scope, e.campaign_id) for e in published] == [({"campaign_id": cid}, "table", cid)] * 4


def test_the_modules_map_wins_a_clash_at_creation(local, storage):
    clash = WorldMapSource("greyhawk-region", "Our Greyhawk", VALE)
    campaign_id = made(local, vale_module(storage, [clash]).id, setting="greyhawk")
    [only] = storage.world_maps.list(campaign_id)
    assert (only.name, only.title, only.source) == ("greyhawk-region", "Our Greyhawk", "module")
    both = made(local, vale_module(storage).id, setting="greyhawk")
    assert [(m.name, m.source) for m in storage.world_maps.list(both)] == [
        ("vale", "module"),
        ("greyhawk-region", "setting"),
    ]


# ----- the organisers' factions, clocks, quests and possessions (plan 6 Task 12) -----


def world_events(app, since: int) -> list[tuple[dict, str | None]]:
    return [(e.data, e.scope) for e in app.state.events._buffer if e.seq > since and e.type == "world"]


def test_organisers_read_and_change_the_factions(app, local, cid):
    listed = local.get(path(cid, "factions")).json()
    assert [(f["id"], f["known"], f["standing"]) for f in listed] == [
        ("watch", True, "Friendly"),
        ("cult", False, "Neutral"),
    ]
    assert local.get(path(cid, "factions/watch")).json()["notes_md"] == SECRET

    seq = app.state.events._seq
    put = local.put(
        path(cid, "factions/watch"),
        json={"name": "The City Watch", "known": True, "strength": 60, "reputation": -30, "notes_md": "Bribed."},
    )
    assert put.status_code == 200, put.text
    assert {k: put.json()[k] for k in ("name", "strength", "reputation", "standing", "notes_md")} == {
        "name": "The City Watch",
        "strength": 60,
        "reputation": -30,
        "standing": "Hostile",
        "notes_md": "Bribed.",
    }
    new = local.put(path(cid, "factions/guild"), json={"name": "The Guild", "reputation": 500})
    assert new.status_code == 200 and new.json()["reputation"] == 100 and new.json()["known"] is False
    assert local.put(path(cid, "factions/nameless"), json={}).status_code == 422
    assert local.request("DELETE", path(cid, "factions/guild"), json={}).status_code == 204
    assert local.get(path(cid, "factions/guild")).status_code == 404
    assert local.request("DELETE", path(cid, "factions/guild"), json={}).status_code == 404
    assert world_events(app, seq) == [({"campaign_id": cid}, "table")] * 3


def test_organisers_add_change_and_remove_clocks(app, local, cid):
    [clock] = local.get(path(cid, "clocks")).json()
    assert (clock["label"], clock["kind"], clock["days_remaining"], clock["faction"]) == (
        "The eye wakes",
        "countdown",
        3,
        "watch",
    )
    seq = app.state.events._seq
    added = local.post(path(cid, "clocks"), json={"label": "The ritual", "kind": "progress", "segments": 6})
    assert added.status_code == 201, added.text
    ritual = added.json()
    assert (ritual["kind"], ritual["segments"], ritual["filled"]) == ("progress", 6, 0)
    changed = local.put(path(cid, f"clocks/{ritual['id']}"), json={**ritual, "filled": 6, "on_complete": "It opens."})
    assert changed.status_code == 200 and changed.json()["filled"] == 6 and changed.json()["on_complete"] == "It opens."
    assert local.post(path(cid, "clocks"), json={"label": "Both", "kind": "countdown"}).status_code == 422
    assert (
        local.post(
            path(cid, "clocks"), json={"label": "x", "kind": "countdown", "days_remaining": 2, "faction": "nobody"}
        ).status_code
        == 404  # an unknown name is 404, as every route's refusal answers it (delve.web.refusals)
    )
    assert local.request("DELETE", path(cid, f"clocks/{ritual['id']}"), json={}).status_code == 204
    assert local.get(path(cid, f"clocks/{ritual['id']}")).status_code == 404
    assert local.get(path(cid, "clocks/not-a-number")).status_code == 404
    assert len(world_events(app, seq)) == 3


def test_organisers_change_the_quests(app, local, cid):
    listed = local.get(path(cid, "quests")).json()
    assert [(q["id"], q["known"]) for q in listed] == [("relic", True), ("plot", False)]
    relic = local.get(path(cid, "quests/relic")).json()
    assert relic["notes_md"].startswith(SECRET) and relic["log"][1]["known"] is False

    put = local.put(
        path(cid, "quests/plot"),
        json={
            "title": "Stop the coup",
            "status": "active",
            "known": True,
            "stakes": "The city falls.",
            "log": [{"day": 2, "text": "A rumour.", "known": True}],
        },
    )
    assert put.status_code == 200, put.text
    assert (put.json()["title"], put.json()["status"], put.json()["known"]) == ("Stop the coup", "active", True)
    assert put.json()["log"] == [{"day": 2, "text": "A rumour.", "known": True}]
    assert local.put(path(cid, "quests/plot"), json={"title": "x", "status": "won"}).status_code == 422
    assert local.put(path(cid, "quests/new-one"), json={"title": "New one"}).json()["status"] == "available"
    assert local.request("DELETE", path(cid, "quests/new-one"), json={}).status_code == 204
    assert local.get(path(cid, "quests/new-one")).status_code == 404


def test_organisers_add_change_and_remove_possessions(app, local, cid):
    [gull] = local.get(path(cid, "possessions")).json()
    assert gull["name"] == "The Gull" and gull["notes_md"].startswith(SECRET) and gull["owner"] is None
    # OSRIC has no mount defaults, so the stats are given.
    stats = {"hp_max": 18, "thac0": 19, "mv": 24}
    added = local.post(
        path(cid, "possessions"), json={"name": "Bess", "kind": "mount", "species": "riding horse", "stats": stats}
    )
    assert added.status_code == 201, added.text
    bess = added.json()
    assert bess["stats"]["mv"] == 24 and bess["kind"] == "mount"
    changed = local.put(path(cid, f"possessions/{bess['id']}"), json={"location": "the stable", "notes_md": "Lame."})
    assert changed.status_code == 200
    assert (changed.json()["location"], changed.json()["notes_md"]) == ("the stable", "Lame.")
    assert local.post(path(cid, "possessions"), json={"name": "x", "kind": "castle"}).status_code == 422
    assert local.request("DELETE", path(cid, f"possessions/{bess['id']}"), json={}).status_code == 204
    assert local.get(path(cid, f"possessions/{bess['id']}")).status_code == 404
