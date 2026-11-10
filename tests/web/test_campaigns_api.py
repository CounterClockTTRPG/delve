"""Campaigns pin a revision of their module; characters belong to a campaign (plateau 1, Task 7)."""

import asyncio
import dataclasses
import threading
import time
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from delve.domain.backends import ModelInfo, ProviderCapabilities
from delve.domain.modules import ModuleMap
from delve.domain.settings import Job
from delve.images.fake import PIXEL_PNG
from delve.images.provider import ImageFile
from delve.modules.dscn import Bundle
from delve.modules.source import ModuleSource, TextDoc, load_source, save_source
from delve.play import banners
from delve.web.seats import SEAT_COOKIE, new_seat_token, token_hash
from tests.fixtures import SAMPLES
from tests.web.conftest import BASE_URL
from tests.web.test_preferences_api import published

CRYPT = (SAMPLES / "crypt.dmap").read_text()
# A room the second version of the crypt adds, and the room it takes away.
ANNEX = '\nroom "annex" {\n  rect 44,14 4 x 6\n  label "Annex"\n}\n'
MAP = "crypt"
ROOMLESS = 'map "Roomless" {\n  grid {\n    cell 32 px\n    bounds 10 x 10\n  }\n}\n'


def crypt_module(local, source: str = CRYPT, title: str = "Crypt") -> dict:
    """A module whose one map, `crypt`, has `source`."""
    module = local.post("/api/modules", json={"title": title}).json()
    response = local.put(f"/api/modules/{module['id']}/maps/map", json={"source": source, "new_name": MAP})
    assert response.status_code == 200, response.json()
    return local.get(f"/api/modules/{module['id']}").json()


def campaign(local, module_id: str, name: str = "Tuesday") -> dict:
    response = local.post("/api/campaigns", json={"name": name, "module_id": module_id})
    assert response.status_code == 201, response.json()
    return response.json()


def character(local, campaign_id: str, name: str) -> dict:
    response = local.post(f"/api/campaigns/{campaign_id}/characters", json={"name": name})
    assert response.status_code == 201, response.json()
    return response.json()


def played(local, source: str = CRYPT, names=("Ana", "Bo")) -> tuple[dict, list[str]]:
    """A campaign on a crypt module, and the ids of its characters."""
    module = crypt_module(local, source)
    started = campaign(local, module["id"])
    return started, [character(local, started["id"], name)["id"] for name in names]


def state_path(campaign_id: str, name: str = MAP) -> str:
    return f"/api/campaigns/{campaign_id}/maps/{name}"


def move(local, campaign_id: str, characters: list[str], to: str):
    return local.post(f"{state_path(campaign_id)}/move", json={"characters": characters, "to": to})


def characters_view(local, campaign_id: str, characters: list[str]):
    return local.get(f"{state_path(campaign_id)}/view", params={"characters": ",".join(characters)})


def test_campaign_pins_revision(local, storage):
    module = crypt_module(local)
    started = campaign(local, module["id"])
    assert started["id"].startswith("cmp_") and len(started["id"]) == 16
    assert started["name"] == "Tuesday"
    assert started["module_id"] == module["id"]
    assert started["revision"] == 1
    assert set(started) == {
        "id", "name", "module_id", "revision", "created_at", "ruleset", "setting", "status", "voice", "initiative", "observers",
        "visibility", "description", "slots", "schedule", "next_sessions", "carried_from", "carried_to",
    }  # fmt: skip
    assert started["status"] == "in_progress"
    assert storage.revisions.get(module["id"], 1).maps[0].source == CRYPT

    again = campaign(local, module["id"], "Friday")
    assert again["revision"] == 1, "an unchanged module reuses its revision"

    detail = local.get(f"/api/campaigns/{started['id']}").json()
    assert set(detail.pop("banner")) == {"image_id", "from_module", "pending", "can_paint", "why_not", "why_not_code"}
    assert detail == {**started, "module_title": "Crypt", "maps": [MAP], "own_maps": [], "upgrade_available": False}
    listed = local.get("/api/campaigns").json()
    assert [{k: c[k] for k in started} for c in listed] == [started, again]


def test_campaign_maps_lists_only_maps_not_libraries(local, storage):
    module = crypt_module(local)
    storage.modules.put_map(module["id"], ModuleMap("lib", "library", 'feature_def "x" {\n}\n', False))
    started = campaign(local, module["id"])
    assert local.get(f"/api/campaigns/{started['id']}").json()["maps"] == [MAP]
    response = local.get(f"{state_path(started['id'], 'lib')}/state")
    assert response.status_code == 404
    assert response.json() == {"error": "No such map."}


def test_create_campaign_unknown_module_404_and_needs_a_name(local):
    response = local.post("/api/campaigns", json={"name": "x", "module_id": "mod_000000000000"})
    assert response.status_code == 404
    assert "error" in response.json()
    module = crypt_module(local)
    assert local.post("/api/campaigns", json={"name": " ", "module_id": module["id"]}).status_code == 422


def test_an_empty_module_starts_no_campaign(local, storage):
    empty = local.post("/api/modules", json={"title": "Nothing yet"}).json()
    assert empty["empty"] is True
    assert [m["empty"] for m in local.get("/api/modules").json()] == [True]
    response = local.post("/api/campaigns", json={"name": "Tuesday", "module_id": empty["id"]})
    assert response.status_code == 409
    assert response.json() == {"error": "This module is empty: write or import something first."}
    assert storage.campaigns.list() == []


def test_a_module_with_rooms_texts_or_entities_isnt_empty(local, storage):
    assert crypt_module(local)["empty"] is False
    texts = local.post("/api/modules", json={"title": "Texts"}).json()
    save_source(storage, texts["id"], ModuleSource(texts=[TextDoc("intro", "Intro", "gm", None, "Once.")]))
    entities = local.post("/api/modules", json={"title": "Entities"}).json()
    save_source(storage, entities["id"], ModuleSource(entities={"npcs": [{"id": "bo", "name": "Bo"}]}))
    roomless = local.post("/api/modules", json={"title": "Roomless"}).json()
    response = local.put(f"/api/modules/{roomless['id']}/maps/map", json={"source": ROOMLESS})
    assert response.status_code == 200, response.json()
    listed = {m["title"]: m["empty"] for m in local.get("/api/modules").json()}
    assert listed == {"Crypt": False, "Texts": False, "Entities": False, "Roomless": True}
    for module in (texts, entities):
        assert local.post("/api/campaigns", json={"name": "x", "module_id": module["id"]}).status_code == 201


def test_a_campaign_on_a_module_emptied_since_keeps_working(local, storage):
    module = crypt_module(local)
    started = campaign(local, module["id"])
    assert local.put(f"/api/modules/{module['id']}/maps/{MAP}", json={"source": ROOMLESS}).status_code == 200
    assert local.get(f"/api/modules/{module['id']}").json()["empty"] is True
    assert local.get(f"/api/campaigns/{started['id']}").status_code == 200
    assert local.post(f"/api/campaigns/{started['id']}/characters", json={"name": "Ana"}).status_code == 201


def test_unknown_campaign_404(local):
    for method, path in (
        ("GET", "/api/campaigns/cmp_000000000000"),
        ("GET", "/api/campaigns/cmp_000000000000/characters"),
        ("GET", f"{state_path('cmp_000000000000')}/state"),
        ("GET", f"{state_path('cmp_000000000000')}/dm-view"),
    ):
        response = local.request(method, path)
        assert response.status_code == 404, path
        assert "error" in response.json()
    assert local.post("/api/campaigns/cmp_000000000000/upgrade", json={}).status_code == 404


def test_delete_campaign(local):
    module = crypt_module(local)
    started = campaign(local, module["id"])
    response = local.request("DELETE", f"/api/campaigns/{started['id']}", json={})
    assert response.status_code == 204
    assert local.get(f"/api/campaigns/{started['id']}").status_code == 404
    assert local.request("DELETE", f"/api/modules/{module['id']}", json={}).status_code == 204


def test_characters_crud(local):
    started, (ana, bo) = played(local)
    listed = local.get(f"/api/campaigns/{started['id']}/characters").json()
    assert [c["name"] for c in listed] == ["Ana", "Bo"]
    assert listed[0]["id"] == ana and ana.startswith("chr_") and len(ana) == 16
    assert set(listed[0]) == {
        "id", "campaign_id", "name", "kind", "sheet", "state", "emote", "order", "encumbrance", "xp_progress", "created_at",
        "departure", "departed_at", "portrait_painting", "portrait_failed", "portrait_editable",
    }  # fmt: skip
    assert listed[0]["campaign_id"] == started["id"] and listed[0]["portrait_painting"] is None
    assert [(c["kind"], c["order"]) for c in listed] == [("pc", 0), ("pc", 1)]

    renamed = local.patch(f"/api/campaigns/{started['id']}/characters/{bo}", json={"name": "Bodil"})
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Bodil"
    assert local.post(f"/api/campaigns/{started['id']}/characters", json={"name": ""}).status_code == 422

    assert local.request("DELETE", f"/api/campaigns/{started['id']}/characters/{ana}", json={}).status_code == 204
    assert [c["id"] for c in local.get(f"/api/campaigns/{started['id']}/characters").json()] == [bo]


def test_character_of_another_campaign_404(local):
    first, (ana, _) = played(local)
    other = campaign(local, first["module_id"], "Other")
    path = f"/api/campaigns/{other['id']}/characters/{ana}"
    assert local.patch(path, json={"name": "x"}).status_code == 404
    assert local.request("DELETE", path, json={}).status_code == 404
    assert local.get(f"/api/campaigns/{first['id']}/characters").json()[0]["id"] == ana


def test_module_edit_does_not_change_campaign_view(local):
    started, (ana, _) = played(local)
    assert move(local, started["id"], [ana], "room.entry_hall").status_code == 200
    view = characters_view(local, started["id"], [ana]).json()["svg"]
    dm = local.get(f"{state_path(started['id'])}/dm-view").json()["svg"]

    edited = local.put(f"/api/modules/{started['module_id']}/maps/{MAP}", json={"source": CRYPT + ANNEX})
    assert edited.status_code == 200

    assert characters_view(local, started["id"], [ana]).json()["svg"] == view
    assert local.get(f"{state_path(started['id'])}/dm-view").json()["svg"] == dm
    assert "Annex" not in dm
    detail = local.get(f"/api/campaigns/{started['id']}").json()
    assert detail["revision"] == 1
    assert detail["upgrade_available"] is True


def test_upgrade_moves_to_new_revision_and_keeps_discovery(local, storage):
    started, (ana, bo) = played(local)
    cid = started["id"]
    move(local, cid, [ana, bo], "room.entry_hall")
    move(local, cid, [bo], "corridor.main_hall")
    move(local, cid, [bo], "room.throne_chamber")
    move(local, cid, [ana], "room.vestry_alcove")

    # The new version adds the annex and drops the throne room, where Bo stands.
    edited = CRYPT.replace('room "throne_chamber"', 'room "throne_room"') + ANNEX
    assert local.put(f"/api/modules/{started['module_id']}/maps/{MAP}", json={"source": edited}).status_code == 200

    upgraded = local.post(f"/api/campaigns/{cid}/upgrade", json={})
    assert upgraded.status_code == 200
    assert upgraded.json() == {**started, "revision": 2}
    detail = local.get(f"/api/campaigns/{cid}").json()
    assert detail["revision"] == 2
    assert detail["upgrade_available"] is False

    state = local.get(f"{state_path(cid)}/state").json()
    assert state["characters"][ana]["location"] == "room.vestry_alcove"
    assert "room.vestry_alcove" in state["characters"][ana]["nodes"]
    assert "room.entry_hall" in state["characters"][ana]["nodes"]
    assert state["characters"][bo]["location"] is None
    assert "room.throne_chamber" not in state["characters"][bo]["nodes"]
    assert set(state["characters"][bo]["nodes"]) == {"room.entry_hall", "corridor.main_hall"}
    assert storage.map_states.get(cid, MAP) == {k: v for k, v in state.items() if k != "groups"}

    assert "Annex" in local.get(f"{state_path(cid)}/dm-view").json()["svg"]
    again = local.post(f"/api/campaigns/{cid}/upgrade", json={})
    assert again.json()["revision"] == 2, "an unchanged module upgrades to the same revision"


def test_an_upgrade_that_fails_part_way_changes_nothing(local, storage, monkeypatch):
    """The new revision, the world it seeds and the upgraded map states are one transaction: a failure in the middle
    leaves the campaign on its old revision, not on the new one with half its world."""
    started, (ana, _) = played(local)
    move(local, started["id"], [ana], "room.entry_hall")
    edited = CRYPT + ANNEX
    assert local.put(f"/api/modules/{started['module_id']}/maps/{MAP}", json={"source": edited}).status_code == 200
    before = storage.map_states.get(started["id"], MAP)

    def broken(*_args, **_kwargs):
        raise RuntimeError("the world didn't seed")

    monkeypatch.setattr("delve.web.routes.campaigns.seed_world", broken)
    with pytest.raises(RuntimeError):
        local.post(f"/api/campaigns/{started['id']}/upgrade", json={})
    assert storage.campaigns.get(started["id"]).revision == 1
    assert storage.map_states.get(started["id"], MAP) == before


def test_a_campaign_whose_delete_fails_keeps_its_board_zone(local, storage, monkeypatch):
    """Untying the board zone and deleting the campaign are one transaction: if the delete fails, the zone is still the
    campaign's."""
    started = campaign(local, crypt_module(local)["id"])
    fields = {"name": "Tuesday's table", "campaign_id": started["id"], "read": "table", "write": "table"}
    assert local.post("/api/board/zones", json=fields).status_code == 201
    zone = storage.board.zone_of_campaign(started["id"])

    def broken(_campaign_id):
        raise RuntimeError("the delete failed")

    monkeypatch.setattr(storage.campaigns, "delete", broken)
    with pytest.raises(RuntimeError):
        local.request("DELETE", f"/api/campaigns/{started['id']}", json={})
    assert storage.board.zone_of_campaign(started["id"]) == zone


def test_upgrade_leaves_a_map_that_no_longer_parses_alone(local, storage):
    started, (ana, _) = played(local)
    move(local, started["id"], [ana], "room.entry_hall")
    before = storage.map_states.get(started["id"], MAP)
    storage.modules.put_map(started["module_id"], ModuleMap(MAP, "map", "map {", True))
    assert local.post(f"/api/campaigns/{started['id']}/upgrade", json={}).status_code == 200
    assert storage.map_states.get(started["id"], MAP) == before
    assert local.get(f"{state_path(started['id'])}/dm-view").json() == {"error": "map offline"}


def test_a_character_whose_delete_fails_part_way_stays(local, storage, monkeypatch):
    """The character's delete and its leaving the map states are one transaction: a failure on the way keeps it."""
    started, (ana, bo) = played(local)
    cid = started["id"]
    move(local, cid, [ana, bo], "room.entry_hall")

    def broken(*_args):
        raise RuntimeError("the map state wasn't saved")

    monkeypatch.setattr(storage.map_states, "put", broken)
    with pytest.raises(RuntimeError):
        local.request("DELETE", f"/api/campaigns/{cid}/characters/{ana}", json={})
    assert storage.characters.get(ana) is not None


def test_delete_character_cleans_map_states(local, storage, app):
    started, (ana, bo) = played(local)
    cid = started["id"]
    move(local, cid, [ana, bo], "room.entry_hall")
    storage.map_states.put(cid, "elsewhere", {"characters": {ana: {"location": None, "nodes": [], "doors": []}}})

    assert local.request("DELETE", f"/api/campaigns/{cid}/characters/{ana}", json={}).status_code == 204

    assert set(storage.map_states.get(cid, MAP)["characters"]) == {bo}
    assert storage.map_states.get(cid, "elsewhere")["characters"] == {}
    assert ana not in local.get(f"{state_path(cid)}/state").json()["characters"]
    changes = [e.data for e in published(app) if e.type == "map_state"]
    assert {"campaign_id": cid, "map": MAP} in changes
    assert {"campaign_id": cid, "map": "elsewhere"} in changes


def test_campaigns_need_organiser(lan):
    calls = [
        ("GET", "/api/campaigns", None),
        ("POST", "/api/campaigns", {"name": "x", "module_id": "mod_000000000000"}),
        ("GET", "/api/campaigns/cmp_000000000000", None),
        ("DELETE", "/api/campaigns/cmp_000000000000", None),
        ("POST", "/api/campaigns/cmp_000000000000/upgrade", {}),
        ("GET", "/api/campaigns/cmp_000000000000/characters", None),
        ("POST", "/api/campaigns/cmp_000000000000/characters", {"name": "x"}),
        ("PATCH", "/api/campaigns/cmp_000000000000/characters/chr_000000000000", {"name": "x"}),
        ("DELETE", "/api/campaigns/cmp_000000000000/characters/chr_000000000000", None),
        ("GET", f"{state_path('cmp_000000000000')}/state", None),
        ("POST", f"{state_path('cmp_000000000000')}/start", {"characters": []}),
        ("POST", f"{state_path('cmp_000000000000')}/move", {"characters": [], "to": "x"}),
        ("POST", f"{state_path('cmp_000000000000')}/reveal", {"characters": [], "node": "x"}),
        ("POST", f"{state_path('cmp_000000000000')}/door", {"door": "1,1", "state": "open"}),
        ("POST", f"{state_path('cmp_000000000000')}/secret", {"key": "x"}),
        ("GET", f"{state_path('cmp_000000000000')}/view?characters=chr_000000000000", None),
        ("GET", f"{state_path('cmp_000000000000')}/dm-view", None),
        ("GET", f"{state_path('cmp_000000000000')}/doors-and-secrets", None),
    ]
    for method, path, body in calls:
        response = lan.request(method, path, json=body if body is not None else {})
        assert response.status_code == 401, (method, path)
        assert "error" in response.json()


def test_a_campaign_is_seeded_with_the_modules_factions_and_quests(local, storage):
    """Plan 6 Task 5: a .dscn's factions, their clocks and its quests come with a new campaign; an upgrade adds the
    module's new ones and keeps the campaign's play state."""
    bundle = Bundle.load(SAMPLES / "scenarios" / "crypt-of-saint-vellis")
    cult = {
        "id": "cult",
        "name": "Cult of the Elder Eye",
        "clocks": [{"name": "The eye wakes", "days": 10}, {"name": "The abbey falls", "segments": 6, "filled": 2}],
    }
    bundle.set_entities("factions", [cult])
    bundle.set_entities("quests", [{"id": "find-the-relic", "name": "Find the relic", "stakes": "The ward fails."}])
    imported = local.post("/api/modules/import", content=bundle.to_zip(), headers={"Content-Type": "application/zip"})
    assert imported.status_code == 201, imported.json()
    module_id = imported.json()["id"]
    cid = campaign(local, module_id)["id"]
    assert [(f.id, f.known, f.reputation) for f in storage.factions.list(cid)] == [("cult", False, 0)]
    assert [(c.label, c.kind) for c in storage.clocks.list(cid)] == [
        ("The eye wakes", "countdown"),
        ("The abbey falls", "progress"),
    ]
    assert [(q.id, q.status, q.known) for q in storage.quests.list(cid)] == [("find-the-relic", "available", False)]

    storage.factions.put(replace(storage.factions.get(cid, "cult"), reputation=40))
    source = load_source(storage, module_id)
    grown = {**source.entities, "factions": [cult, {"id": "guard", "name": "The Abbey Guard"}]}
    save_source(storage, module_id, replace(source, entities=grown))
    assert local.post(f"/api/campaigns/{cid}/upgrade", json={}).status_code == 200
    assert [(f.id, f.reputation) for f in storage.factions.list(cid)] == [("cult", 40), ("guard", 0)]
    assert len(storage.clocks.list(cid)) == 2


def seat_browser(app, storage, campaign_id: str, role: str, name: str = "Ana"):
    """A browser on the LAN that holds the token of a new seat at that table."""
    token = new_seat_token()
    storage.seats.create(campaign_id, name, "nl", role, token_hash=token_hash(token))
    browser = TestClient(app, base_url=BASE_URL)
    browser.cookies.set(SEAT_COOKIE, token)
    return browser


def test_the_host_sets_the_campaigns_status(local, app, storage):
    started = campaign(local, crypt_module(local)["id"])
    path = f"/api/campaigns/{started['id']}"
    [banner] = storage.campaign_images.list(started["id"], kind="banner")
    settled(storage, banner.id)
    before = len(published(app))  # its banner's events came before
    response = local.patch(path, json={"status": "paused"})
    assert response.status_code == 200, response.json()
    assert response.json() == {**started, "status": "paused"}
    assert storage.campaigns.get(started["id"]).status == "paused"
    events = [e for e in published(app)[before:] if e.type == "campaigns"]
    assert [(e.data, e.scope) for e in events] == [({"id": started["id"]}, "organisers")]

    refused = local.patch(path, json={"status": "abandoned"})
    assert refused.status_code == 422 and "abandoned" in refused.json()["error"]
    assert local.patch("/api/campaigns/cmp_000000000000", json={"status": "paused"}).status_code == 404

    cohost = seat_browser(app, storage, started["id"], "cohost")
    assert cohost.patch(path, json={"status": "complete"}).json()["status"] == "complete"
    player = seat_browser(app, storage, started["id"], "player")
    assert player.patch(path, json={"status": "in_progress"}).status_code == 403
    assert storage.campaigns.get(started["id"]).status == "complete"


def test_the_campaigns_list_shows_module_players_and_activity(local, app, storage):
    started = campaign(local, crypt_module(local, title="The Crypt")["id"])
    seats_of = {"player": "Bo", "observer": "Cy", "cohost": "Di"}
    for role, name in seats_of.items():
        storage.seats.create(started["id"], name, "en", role)
    gone = storage.seats.create(started["id"], "Ed", "en", "player")
    storage.seats.save(dataclasses.replace(gone, left_at="2026-10-18T09:00:00+00:00"))
    storage.sessions.start(started["id"], 1, "Into the crypt")
    beat = storage.beats.open(started["id"], [], status="running")
    storage.beats.save(dataclasses.replace(beat, status="done", closed_at="2099-01-01T00:00:00+00:00"))

    [listed] = local.get("/api/campaigns").json()
    assert listed["status"] == "in_progress" and listed["module_title"] == "The Crypt"
    assert listed["players"] == ["Host", "Bo", "Di"]
    # Who sits at the table, as its card shows them (DEL-230): no observer, no one who left; the places taken.
    assert [(p["name"], p["role"]) for p in listed["people"]] == [("Host", "host"), ("Bo", "player"), ("Di", "cohost")]
    assert listed["slots"] is None and listed["taken"] == 2, "a co-host takes a place too"
    assert listed["last_played"] == "2099-01-01T00:00:00+00:00"
    assert listed["sessions"] == 1 and listed["playtime_s"] > 0


# ----- the banner (looks and banners plan Task 2) -----

DEAR = ProviderCapabilities("dear", "A painter that costs money", frozenset({Job.IMAGE_SCENE}))
FREE_HELD = ProviderCapabilities(
    "free-held",
    "A free painter that takes its time",
    frozenset({Job.IMAGE_SCENE}),
    models=("local",),
    model_info={"local": ModelInfo("Local", "local", None, paid=False)},
)


class HeldPainter:
    """Paints when `gate` is set; raises instead once `broken`."""

    def __init__(self) -> None:
        self.gate = threading.Event()
        self.broken = False

    async def generate(self, req):
        while not self.gate.is_set():
            await asyncio.sleep(0.01)
        if self.broken:
            raise RuntimeError("the model is down")
        return ImageFile(PIXEL_PNG, "image/png")


def banner_painters(registries, storage, painter: HeldPainter, choice: str) -> None:
    """Register the dear and the free held painter, and choose `choice` for the scene."""
    registries.images.register(DEAR, lambda: painter)
    registries.images.register(FREE_HELD, lambda: painter)
    model = "local" if choice == "free-held" else None
    storage.settings.save({"choices": {"image.scene": {"provider": choice, "model": model, "effort": None}}})


def settled(storage, image_id: str, timeout: float = 5.0):
    """The banner once it is painted or failed: no longer waiting for its gate to be read, nor painting."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        row = storage.campaign_images.get(image_id)
        if row.status not in ("waiting", "painting"):
            return row
        time.sleep(0.01)
    raise AssertionError(f"{image_id} is still painting")


def test_making_a_campaign_asks_for_its_banner(local, storage):
    started = campaign(local, crypt_module(local, title="The Crypt")["id"])

    [row] = storage.campaign_images.list(started["id"], kind="banner")
    assert "The Crypt" in row.prompt and "Greyhawk" in row.prompt
    assert settled(storage, row.id).status == "done", "the fake is free: painted at once"


def test_a_failing_banner_never_fails_the_campaign(local, storage, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("the banner broke")

    monkeypatch.setattr(banners, "ask", broken)
    response = local.post("/api/campaigns", json={"name": "Tuesday", "module_id": crypt_module(local)["id"]})

    assert response.status_code == 201, response.json()
    assert storage.campaigns.get(response.json()["id"]) is not None
    assert storage.campaign_images.list(response.json()["id"]) == []


def test_a_banner_that_is_slow_or_fails_never_holds_up_the_campaign(local, storage, registries):
    painter = HeldPainter()
    banner_painters(registries, storage, painter, "free-held")
    module = crypt_module(local)

    started = time.monotonic()
    response = local.post("/api/campaigns", json={"name": "Tuesday", "module_id": module["id"]})
    assert response.status_code == 201 and time.monotonic() - started < 2.0
    [row] = storage.campaign_images.list(response.json()["id"], kind="banner")
    assert storage.campaign_images.get(row.id).status in ("waiting", "painting"), "it paints in the background"
    painter.gate.set()
    assert settled(storage, row.id).status == "done"

    painter.broken = True  # the painting fails: the campaign stands
    failed = campaign(local, module["id"], "Wednesday")
    [row] = storage.campaign_images.list(failed["id"], kind="banner")
    assert settled(storage, row.id).status == "failed"
    assert local.get("/api/campaigns").status_code == 200
    assert local.get(f"/api/campaigns/{failed['id']}").status_code == 200


def test_a_banner_whose_gate_opened_while_delve_was_stopped_is_painted_at_start(app, local, storage, registries):
    painter = HeldPainter()
    painter.gate.set()
    banner_painters(registries, storage, painter, "dear")
    [row] = storage.campaign_images.list(campaign(local, crypt_module(local)["id"])["id"], kind="banner")
    assert row.status == "waiting"
    storage.settings.save({"choices": {"image.scene": {"provider": "free-held", "model": "local", "effort": None}}})

    with TestClient(app, base_url=BASE_URL):  # a second start of the app
        assert settled(storage, row.id).status == "done"


def test_making_a_campaign_never_waits_on_a_slow_painter_list(local, storage, registries):
    """A provider whose capabilities are read over the network (assetgen, 3 s at worst): making the campaign answers
    at once, the event loop serves other requests while the gate is read, and the banner waits for a paid model."""
    painter = HeldPainter()
    banner_painters(registries, storage, painter, "dear")

    def slow_caps():
        time.sleep(2.0)
        return DEAR

    registries.images.register_live("dear", slow_caps, lambda: painter)
    module = crypt_module(local)

    started = time.monotonic()
    response = local.post("/api/campaigns", json={"name": "Tuesday", "module_id": module["id"]})
    assert response.status_code == 201 and time.monotonic() - started < 1.0, "it never waits on the gate"
    started = time.monotonic()
    assert local.get("/api/health").status_code == 200
    assert time.monotonic() - started < 1.0, "the loop is free while the gate is read"

    reading = threading.Thread(target=lambda: local.get(f"/api/campaigns/{response.json()['id']}"))
    reading.start()
    time.sleep(0.2)
    started = time.monotonic()
    assert local.get("/api/health").status_code == 200
    assert time.monotonic() - started < 1.0, "the campaign's page reads its gate off the loop"
    reading.join()

    [row] = storage.campaign_images.list(response.json()["id"], kind="banner")
    end = time.monotonic() + 5.0
    while time.monotonic() < end and banners._deciding:
        time.sleep(0.05)
    assert storage.campaign_images.get(row.id).status == "waiting", "a paid model waits for the host"


# ----- the banner on the campaign's page (looks and banners plan Task 3) -----


def test_the_campaign_shows_a_pending_failure(app, local, storage, registries):
    from delve.play.images import PAID_HINT

    painter = HeldPainter()
    painter.gate.set()
    banner_painters(registries, storage, painter, "free-held")
    started = campaign(local, crypt_module(local)["id"])
    path = f"/api/campaigns/{started['id']}"
    [old] = storage.campaign_images.list(started["id"], kind="banner")
    assert settled(storage, old.id).status == "done"
    assert local.get(path).json()["banner"] == {
        "image_id": old.id,
        "from_module": False,
        "pending": None,
        "can_paint": True,
        "why_not": None,
        "why_not_code": None,
    }

    painter.broken = True
    assert local.post(f"{path}/banner", json={}).status_code == 202
    [_, new] = storage.campaign_images.list(started["id"], kind="banner")
    assert settled(storage, new.id).status == "failed"
    banner = local.get(path).json()["banner"]
    assert banner["image_id"] == old.id, "the old banner stays"
    assert banner["pending"] == {"status": "failed", "error": "the model is down"}

    storage.settings.save({"choices": {"image.scene": {"provider": "dear", "model": None, "effort": None}}})
    storage.campaign_images.put(replace(storage.campaign_images.get(new.id), status="waiting", error="stale"))
    banner = local.get(path).json()["banner"]
    assert banner["pending"] == {"status": "waiting", "error": None}, "an error only for a failed one"
    assert banner["can_paint"] is False and banner["why_not"] == PAID_HINT
    assert banner["why_not_code"] == "paid_images_off"
    player = seat_browser(app, storage, started["id"], "player")
    assert player.get(path).status_code == 403


def test_an_organiser_account_hosts_the_campaign_it_makes(local, lan, storage):
    """An organiser's account is the host of a campaign it makes, in its own name and language, and has it in My
    tables; the owner's seat is made when the owner comes to the table, as an observer there."""
    from dataclasses import replace as replaced

    from tests.web.conftest import make_account, session_for

    otto = make_account(storage, "otto", organiser=True)
    storage.accounts.save_profile(otto.id, replaced(otto.profile, display_name="Otto", language="nl"))
    module = crypt_module(local)
    session_for(storage, storage.accounts.get(otto.id), lan)
    made = campaign(lan, module["id"])
    [host] = storage.seats.list(made["id"])
    assert (host.name, host.language, host.role, host.organiser, host.owner) == ("Otto", "nl", "host", True, False)
    assert host.account_id == otto.id
    assert [t["campaign_id"] for t in lan.get("/api/account/tables").json()] == [made["id"]]
    assert local.get(f"/api/campaigns/{made['id']}/seats").status_code == 200, "the owner comes to the table"
    owner = storage.seats.owner_seat(made["id"])
    assert owner is not None and owner.role == "observer"
    assert [s.role for s in storage.seats.list(made["id"]) if s.role == "host"] == ["host"], "still one host"


def test_the_owner_hosts_the_campaign_it_makes(local, storage):
    module = crypt_module(local)
    made = campaign(local, module["id"])
    [host] = storage.seats.list(made["id"])
    assert (host.role, host.owner, host.account_id) == ("host", True, None)


def test_the_list_reads_each_kind_of_thing_once(local, storage):
    """`GET /api/campaigns` (DEL-172): as many queries for six campaigns as for two, seated, carried on and with a
    banner of their module; it made 111 for two on the live data, most loading every module whole for its title."""
    from sqlalchemy import event

    module = crypt_module(local)
    first = campaign(local, module["id"], "One")
    second = campaign(local, module["id"], "Two")
    storage.seats.create(first["id"], "Ana", "en", "player")
    storage.carries.add(first["id"], second["id"], [])

    def queries() -> int:
        for c in storage.campaigns.list():  # their banners painted, so nothing else runs meanwhile
            for image in storage.campaign_images.list(c.id):
                settled(storage, image.id)
        count = [0]

        def counted(*args):
            count[0] += 1

        event.listen(storage.engine, "before_cursor_execute", counted)
        try:
            assert local.get("/api/campaigns").status_code == 200
        finally:
            event.remove(storage.engine, "before_cursor_execute", counted)
        return count[0]

    two = queries()
    for n in range(4):
        more = campaign(local, module["id"], f"More {n}")
        storage.seats.create(more["id"], f"Bo {n}", "en", "player")
    assert queries() == two
    listed = {c["name"]: c for c in local.get("/api/campaigns").json()}
    assert listed["Two"]["carried_from"] == {"id": first["id"], "name": "One"}
    assert listed["One"]["carried_to"] == [{"id": second["id"], "name": "Two"}]
