"""Pictures over HTTP (plan 6 Task 10, Review Focus 4): the DM's picture tools answer at once and the painting runs in
the background, so the beat is never held up; a row still painting at start is retried once; the pictures route
answers a seat only what its audience lets it see; the host's "Paint this scene" writes the brief with a side pass;
paid images are the host's to turn on; the Replicate token never reaches a browser."""

import asyncio
import itertools
import json
import threading
import time

import httpx
import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from delve.dice import SeededRng
from delve.dm.bridge import BRIDGE_HEADER
from delve.dm.fake import FAKE_DM_CAPABILITIES, FakeDM
from delve.dm.tools import ToolHost
from delve.domain.backends import ModelInfo, ProviderCapabilities, Registry
from delve.domain.settings import Job
from delve.domain.world import CampaignImage, Possession
from delve.images.fake import PIXEL_PNG
from delve.images.portraitgen import PORTRAITGEN_CAPABILITIES, PortraitgenImages
from delve.images.provider import ImageFile
from delve.images.replicate import REPLICATE_CAPABILITIES, ReplicateImages
from delve.play import seats
from delve.play.audience import for_seats
from delve.play.table import close_beat, open_beat
from delve.web.routes.internal_tools import tool_host
from delve.web.seats import SEAT_COOKIE, new_seat_token, token_hash
from tests.fixtures.play_reference import PlayReference
from tests.fixtures.rulesets import over
from tests.web.conftest import BASE_URL, make_registries
from tests.web.test_campaigns_api import campaign, character, crypt_module
from tests.web.test_preferences_api import published

TOKEN = "r8_SECRET-TOKEN"
SECRET = "SECRET-XYZZY"
SLOW = ProviderCapabilities("slow", "Slow painter", frozenset({Job.IMAGE_SCENE, Job.IMAGE_POSSESSION}))


class SlowPainter:
    """Paints when `gate` is set: a Replicate that takes its time."""

    capabilities = SLOW

    def __init__(self) -> None:
        self.gate = threading.Event()

    async def generate(self, req):
        while not self.gate.is_set():
            await asyncio.sleep(0.01)
        return ImageFile(PIXEL_PNG, "image/png")


@pytest.fixture
def painter():
    return SlowPainter()


BRIEF = "A painter's brief: the bridge at dusk, two figures on it."


@pytest.fixture
def dm():
    return FakeDM([], side_handler=lambda prompt: BRIEF)


@pytest.fixture
def registries(painter, dm):
    registries = make_registries()
    registries.dm = Registry()
    registries.dm.register(FAKE_DM_CAPABILITIES, lambda: dm)
    images = Registry()
    images.register(PORTRAITGEN_CAPABILITIES, PortraitgenImages)
    images.register(SLOW, lambda: painter)
    images.register(REPLICATE_CAPABILITIES, lambda: ReplicateImages(TOKEN, client=httpx.AsyncClient()))
    registries.images = images
    return registries


@pytest.fixture
def host(app, storage):
    seeds = itertools.count(1)
    app.state.tool_host = ToolHost(storage, lambda: SeededRng(next(seeds)), catalogs=over(PlayReference()))
    return app.state.tool_host


@pytest.fixture
def bridge(app):
    with TestClient(app, base_url=BASE_URL, client=("127.0.0.1", 50001)) as client:
        client.headers[BRIDGE_HEADER] = app.state.bridge_secret
        yield client


@pytest.fixture
def table(local, storage, app):
    """A campaign where Ana plays Garrek and Bo plays Pippa, each in a browser of their own; the owner hosts."""
    started = campaign(local, crypt_module(local)["id"])
    cid = started["id"]
    garrek, pippa = (character(local, cid, name)["id"] for name in ("Garrek", "Pippa"))
    people, clients = {}, []
    for name, role, pc in (("Ana", "player", garrek), ("Bo", "player", pippa), ("Cy", "cohost", None)):
        token = new_seat_token()
        seat = storage.seats.create(cid, name, "en", role, token_hash=token_hash(token))
        if pc is not None:
            seats.claim(storage, pc, seat)
        client = TestClient(app, base_url=BASE_URL)
        client.__enter__()
        client.cookies.set(SEAT_COOKIE, token)
        clients.append(client)
        people[name] = client
    yield {"campaign": cid, "garrek": garrek, "pippa": pippa, **people}
    for client in clients:
        client.__exit__(None, None, None)


def settle(storage, image_id: str, timeout: float = 5.0) -> CampaignImage:
    """The image once it is no longer painting."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        row = storage.campaign_images.get(image_id)
        if row.status != "painting":
            return row
        time.sleep(0.01)
    raise AssertionError(f"{image_id} is still painting")


def turn_on(local, cid):
    response = local.put(f"/api/campaigns/{cid}/play/options", json={"paid_images": True})
    assert response.status_code == 200, response.json()
    assert response.json()["paid_images"] is True


def call(bridge, cid, name, **args):
    response = bridge.post(f"/internal/dm/{cid}/call", json={"name": name, "args": args})
    assert response.status_code == 200
    return response.json()


def act(storage, cid) -> dict:
    return {"player": seats.owner_seat(storage, cid).id, "character_ids": [], "kind": "act", "text": "We look."}


def test_paid_images_are_off_until_the_host_turns_them_on(local, table, storage, painter):
    cid = table["campaign"]
    [banner] = storage.campaign_images.list(cid, kind="banner")
    assert banner.status == "waiting", "the slow painter costs money"
    assert local.get(f"/api/campaigns/{cid}/play/options").json()["paid_images"] is False
    refused = table["Cy"].put(f"/api/campaigns/{cid}/play/options", json={"paid_images": True})
    assert refused.status_code == 403, "credits are the host's to spend"
    assert table["Ana"].put(f"/api/campaigns/{cid}/play/options", json={"paid_images": True}).status_code == 403
    turn_on(local, cid)
    assert local.put(f"/api/campaigns/{cid}/play/options", json={"paid_images": "on"}).status_code == 422
    painter.gate.set()
    assert settle(storage, banner.id).status == "done", "turning them on painted the waiting banner"


def test_the_paid_limit_is_the_hosts_to_set_beside_the_switch(local, table):
    """DEL-153: who may turn paid images on may say how many a day; a co-host and a player may not."""
    cid = table["campaign"]
    path = f"/api/campaigns/{cid}/play/options"
    assert local.get(path).json()["paid_images_per_day"] == 20
    for seat in ("Cy", "Ana"):
        assert table[seat].put(path, json={"paid_images_per_day": 100}).status_code == 403, seat
    for wrong in (0, 501, "10", True):
        assert local.put(path, json={"paid_images_per_day": wrong}).status_code == 422, wrong
    set_to = local.put(path, json={"paid_images_per_day": 5})
    assert set_to.status_code == 200 and set_to.json()["paid_images_per_day"] == 5
    assert local.put(path, json={"paid_images_per_day": None}).json()["paid_images_per_day"] == 5, "null: unchanged"


def test_paint_this_scene_past_the_limit_is_429_with_the_reason(local, table, storage, dm):
    """DEL-153, audit finding 6: a seat pressing Paint this scene in a loop stops at the campaign's limit."""
    cid = table["campaign"]
    turn_on(local, cid)
    assert local.put(f"/api/campaigns/{cid}/play/options", json={"paid_images_per_day": 2}).status_code == 200
    storage.story.append(cid, None, "dm_text", {"text": "Rain on the bridge."})
    for _ in range(2):
        assert table["Ana"].post(f"/api/campaigns/{cid}/scene", json={}).status_code == 202
    refused = table["Ana"].post(f"/api/campaigns/{cid}/scene", json={})
    assert refused.status_code == 429
    assert refused.json()["error"] == "This campaign's 2 paid pictures for the last 24 hours are used up."
    assert "raise the limit" in refused.json()["hint"]
    assert len(dm.side_prompts) == 2, "no brief written past the limit"


def test_a_scene_paints_after_the_tool_answered_and_the_beat_goes_on(app, local, host, bridge, table, storage, painter):
    cid = table["campaign"]
    turn_on(local, cid)
    beat = open_beat(storage, cid, act(storage, cid))
    started = time.monotonic()
    answered = call(bridge, cid, "paint_scene", brief=f"{SECRET} the bridge.", caption="The bridge",
                    characters=["Garrek"])  # fmt: skip
    assert time.monotonic() - started < 1 and answered["status"] == "painting"
    assert call(bridge, cid, "roll", notation="1d6", purpose="the beat goes on")["total"] >= 1
    close_beat(storage, beat.id, "done")
    assert storage.campaign_images.get(answered["image_id"]).status == "painting"

    painter.gate.set()
    done = settle(storage, answered["image_id"])
    assert done.status == "done" and done.backend == "slow"
    ana, bo = (table[name].get(f"/api/campaigns/{cid}/story").json()["entries"] for name in ("Ana", "Bo"))
    scenes = [(e["payload"], e["beat_id"]) for e in ana if e["kind"] == "scene"]
    assert scenes == [({"image_id": done.id, "caption": "The bridge"}, None)], "outside the beat"
    assert [e for e in bo if e["kind"] == "scene"] == [], "a scene told to one character reaches only that seat"
    assert SECRET not in json.dumps(ana) + json.dumps(bo)

    path = f"/api/campaigns/{cid}/pictures/{done.id}"
    shown = table["Ana"].get(path)
    assert shown.status_code == 200 and shown.content == PIXEL_PNG
    assert shown.headers["content-type"] == "image/png" and shown.headers["x-content-type-options"] == "nosniff"
    assert table["Bo"].get(path).status_code == 404
    assert local.get(path).status_code == 404, "not the host's either: the owner doesn't play Garrek"


def test_a_portrait_is_everyones_at_the_table(local, host, bridge, table, storage, app, painter):
    cid = table["campaign"]
    turn_on(local, cid)
    storage.settings.save({"choices": {"image.possession": {"provider": "slow", "model": None, "effort": None}}})
    storage.possessions.put(Possession(cid, "pos_cog", "The Grey Cog", "ship"))
    beat = open_beat(storage, cid, act(storage, cid))
    painter.gate.set()
    answered = call(bridge, cid, "portrait", of="The Grey Cog")
    close_beat(storage, beat.id, "done")
    done = settle(storage, answered["image_id"])
    for name in ("Ana", "Bo", "Cy"):
        assert table[name].get(f"/api/campaigns/{cid}/pictures/{done.id}").status_code == 200, name


def test_the_pictures_route_answers_only_a_done_image_of_its_campaign(local, table, storage):
    cid = table["campaign"]
    other = campaign(local, crypt_module(local, title="Other")["id"], name="Other")
    sha = storage.blobs.put(PIXEL_PNG, "image/png")
    painting = storage.campaign_images.put(CampaignImage("img_painting00", cid, "scene"))
    elsewhere = storage.campaign_images.put(
        CampaignImage("img_elsewhere0", other["id"], "scene", status="done", blob=sha, mime="image/png")
    )
    for image_id in (painting.id, elsewhere.id, "img_000000000000"):
        response = local.get(f"/api/campaigns/{cid}/pictures/{image_id}")
        assert response.status_code == 404 and response.json() == {"error": "No such picture."}


def test_paint_this_scene_writes_the_brief_from_the_last_narrations(local, table, storage, dm, painter):
    cid = table["campaign"]
    path = f"/api/campaigns/{cid}/scene"
    refused = local.post(path, json={})
    assert refused.status_code == 422 and refused.json()["error"] == "Paid images are off for this campaign."
    turn_on(local, cid)
    assert local.post(path, json={}).json()["error"] == "There is no narration to paint yet."
    for text in ("The gate creaks.", "Rain on the bridge.", "Two figures cross it."):
        storage.story.append(cid, None, "dm_text", {"text": text})
    storage.story.append(cid, None, "dm_text", {"text": f"{SECRET} for Ana alone."}, for_seats(["seat_x"]))

    painter.gate.set()
    answered = local.post(path, json={"hint": "focus on the figures"})
    assert answered.status_code == 202, answered.json()
    (prompt,) = dm.side_prompts
    assert "Rain on the bridge.\n\nTwo figures cross it." in prompt and "The gate creaks." not in prompt
    assert "focus on the figures" in prompt and SECRET not in prompt, "only what everyone was told"
    assert "60 to 120 words" in prompt
    done = settle(storage, answered.json()["image_id"])
    assert (done.kind, done.prompt, done.audience) == ("scene", BRIEF, None)


def test_a_painting_left_by_a_stopped_delve_is_retried_at_start(app, local, table, storage, painter):
    cid = table["campaign"]
    once = storage.campaign_images.put(CampaignImage("img_once000000", cid, "scene", prompt="once", attempts=1))
    twice = storage.campaign_images.put(CampaignImage("img_twice00000", cid, "scene", prompt="twice", attempts=2))
    painter.gate.set()
    storage.settings.save({"choices": {"image.scene": {"provider": "slow", "model": None, "effort": None}}})
    with TestClient(app, base_url=BASE_URL):  # a second start of the app
        assert settle(storage, once.id).status == "done"
        assert settle(storage, twice.id).status == "failed"


def test_a_painting_waiting_in_its_painters_queue_says_its_place(local, table, storage):
    """DEL-138: the sheet and the story say a painting waits its turn rather than looking stuck."""
    cid = table["campaign"]
    ana = next(c for c in local.get(f"/api/campaigns/{cid}/characters").json() if c["kind"] == "pc")
    storage.campaign_images.put(
        CampaignImage("img_portrait00", cid, "portrait", ana["id"], backend="assetgen", provider_job="j-1", queue=3)
    )
    storage.campaign_images.put(CampaignImage("img_scene00000", cid, "scene", backend="assetgen", queue=1))
    for path in (f"/api/campaigns/{cid}/characters", f"/api/campaigns/{cid}/dm/characters"):
        listed = {c["id"]: c["portrait_painting"] for c in local.get(path).json()}
        assert listed[ana["id"]] == {"provider": "assetgen", "queue": 3}, path
        assert [v for k, v in listed.items() if k != ana["id"]] == [None] * (len(listed) - 1), path
    scenes = local.get(f"/api/campaigns/{cid}/play/state").json()["painting_scenes"]
    assert scenes == [{"image_id": "img_scene00000", "caption": "", "provider": "assetgen", "queue": 1}]
    assert "j-1" not in local.get(f"/api/campaigns/{cid}/characters").text, "the provider's job stays on the server"


def test_the_token_never_reaches_a_browser(local, table):
    for path in ("/api/preferences", "/api/backends", f"/api/campaigns/{table['campaign']}/play/options"):
        response = local.get(path)
        assert response.status_code == 200 and TOKEN not in response.text, path
    providers = {p["id"]: p for p in local.get("/api/backends").json()["providers"]}
    assert providers["replicate"]["jobs"] == ["image.portrait", "image.npc_portrait", "image.scene", "image.possession"]
    assert providers["portraitgen"]["jobs"] == ["image.portrait", "image.npc_portrait"]
    assert local.get("/api/preferences").json()["choices"]["image.portrait"]["provider"] == "portraitgen"


FREE = ProviderCapabilities(
    "local-painter",
    "A local painter",
    frozenset({Job.IMAGE_SCENE}),
    models=("sdxl-local",),
    model_info={"sdxl-local": ModelInfo("SDXL", "local", None, paid=False)},
)


def test_with_paid_images_off_a_free_model_paints_through_the_apps_tool_host(
    app, local, bridge, table, storage, registries, painter
):
    """The gate per model, as the app wires it: its tool host and its "Paint this scene" ask Preferences' choice."""
    cid = table["campaign"]
    registries.images.register(FREE, lambda: painter)
    app.state.__dict__.pop("tool_host", None)
    tool_host(Request({"type": "http", "app": app})).catalogs = over(PlayReference())
    storage.settings.save({"choices": {"image.scene": {"provider": "replicate", "model": None, "effort": None}}})
    beat = open_beat(storage, cid, act(storage, cid))
    assert call(bridge, cid, "paint_scene", brief="The bridge.")["error"] == "Paid images are off for this campaign."
    storage.story.append(cid, None, "dm_text", {"text": "Rain on the bridge."})
    assert local.post(f"/api/campaigns/{cid}/scene", json={}).status_code == 422

    storage.settings.save({"choices": {"image.scene": {"provider": "local-painter", "model": "sdxl-local"}}})
    answered = call(bridge, cid, "paint_scene", brief="The bridge.")
    assert answered["status"] == "painting", answered
    close_beat(storage, beat.id, "done")
    assert local.post(f"/api/campaigns/{cid}/scene", json={}).status_code == 202
    painter.gate.set()
    assert settle(storage, answered["image_id"]).status == "done"


def test_every_acting_seat_paints_the_scene_and_an_observer_cant(local, app, table, storage, dm, painter):
    cid = table["campaign"]
    path = f"/api/campaigns/{cid}/scene"
    turn_on(local, cid)
    storage.story.append(cid, None, "dm_text", {"text": "Rain on the bridge."})
    token = new_seat_token()
    storage.seats.create(cid, "Di", "en", "observer", token_hash=token_hash(token))
    with TestClient(app, base_url=BASE_URL) as di:
        di.cookies.set(SEAT_COOKIE, token)
        assert di.post(path, json={}).status_code == 403
    painter.gate.set()
    answered = table["Ana"].post(path, json={})
    assert answered.status_code == 202, answered.json()
    settle(storage, answered.json()["image_id"])


def test_the_state_tells_every_seat_whether_a_scene_can_be_painted(local, app, table):
    cid = table["campaign"]
    state = f"/api/campaigns/{cid}/play/state"
    answer = table["Ana"].get(state).json()
    assert answer["scene_painting"] is False, "paid images are off"
    assert answer["scene_paid"] is True, "the scene's painter costs money: Paint this scene says so (DEL-258)"
    before = len(published(app))
    turn_on(local, cid)
    assert table["Ana"].get(state).json()["scene_painting"] is True
    told = [e.data for e in published(app)[before:] if e.type == "play_options"]
    assert told == [{"campaign_id": cid}], "the seats read the state again"


def test_a_scene_still_painting_shows_as_a_placeholder_to_its_audience(
    app, local, host, bridge, table, storage, painter
):
    cid = table["campaign"]
    state = f"/api/campaigns/{cid}/play/state"
    turn_on(local, cid)
    before = len(published(app))
    beat = open_beat(storage, cid, act(storage, cid))
    answered = call(bridge, cid, "paint_scene", brief=f"{SECRET} the bridge.", caption="The bridge",
                    characters=["Garrek"])  # fmt: skip
    close_beat(storage, beat.id, "done")
    placeholder = [{"image_id": answered["image_id"], "caption": "The bridge", "provider": "slow", "queue": None}]
    end = time.monotonic() + 5
    while not [e for e in published(app)[before:] if e.type == "scenes"] and time.monotonic() < end:
        time.sleep(0.01)
    assert [e.data for e in published(app)[before:] if e.type == "scenes"] == [{"campaign_id": cid}], "it began"
    ana = table["Ana"].get(state).json()
    assert ana["painting_scenes"] == placeholder and SECRET not in json.dumps(ana), "never the brief"
    assert table["Bo"].get(state).json()["painting_scenes"] == [], "a scene for Garrek alone"

    painter.gate.set()
    settle(storage, answered["image_id"])
    assert table["Ana"].get(state).json()["painting_scenes"] == []
    told = [e.data for e in published(app)[before:] if e.type == "scenes"]
    assert told == [{"campaign_id": cid}] * 2, "it began, and it landed"


def test_a_failed_scene_takes_its_placeholder_away(app, local, table, storage):
    cid = table["campaign"]
    turn_on(local, cid)
    storage.story.append(cid, None, "dm_text", {"text": "Rain on the bridge."})
    storage.settings.save({"choices": {"image.scene": {"provider": "replicate", "model": None, "effort": None}}})
    before = len(published(app))
    answered = local.post(f"/api/campaigns/{cid}/scene", json={})
    assert answered.status_code == 202, answered.json()
    assert settle(storage, answered.json()["image_id"]).status == "failed"
    assert table["Ana"].get(f"/api/campaigns/{cid}/play/state").json()["painting_scenes"] == []
    assert [e.type for e in published(app)[before:] if e.type == "scenes"] == ["scenes", "scenes"]
