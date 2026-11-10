"""Repaint a character's portrait (DEL-135): who may press it, the paid gate it shares with the DM's portrait tool
(said, never portraitgen's after all), No portrait for NPCs, the painting state on the sheet while it runs, and a
failed portrait's Try again."""

import asyncio
import threading
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from delve.domain.backends import ProviderCapabilities, Registry
from delve.domain.settings import Job
from delve.domain.world import ImagePortrait, TraitsPortrait
from delve.images.fake import PIXEL_PNG
from delve.images.portraitgen import PORTRAITGEN_CAPABILITIES, PortraitgenImages
from delve.images.provider import ImageFile
from delve.play import images
from delve.web.seats import SEAT_COOKIE, new_seat_token, token_hash
from tests.web.conftest import BASE_URL, make_account, make_registries, session_for
from tests.web.test_pictures_api import settle, table, turn_on  # noqa: F401 (the fixture `table`)
from tests.web.test_preferences_api import published

PAINTER = ProviderCapabilities("brush", "Brush", frozenset({Job.IMAGE_PORTRAIT, Job.IMAGE_NPC_PORTRAIT}))


class Brush:
    """A painter that costs money (it says nothing of its models) and paints when `gate` is set, or fails with
    `fail`."""

    capabilities = PAINTER

    def __init__(self) -> None:
        self.gate = threading.Event()
        self.fail = False
        self.asked: list[str] = []

    async def generate(self, req):
        self.asked.append(req.prompt)
        while not self.gate.is_set():
            await asyncio.sleep(0.01)
        if self.fail:
            raise RuntimeError("the painter fell over")
        return ImageFile(PIXEL_PNG, "image/png")


@pytest.fixture
def brush():
    return Brush()


@pytest.fixture
def registries(brush):
    registries = make_registries()
    painters = Registry()
    painters.register(PORTRAITGEN_CAPABILITIES, PortraitgenImages)
    painters.register(PAINTER, lambda: brush)
    registries.images = painters
    return registries


def choose(storage, job: Job, provider: str) -> None:
    choices = storage.settings.load().get("choices") or {}
    storage.settings.save({"choices": {**choices, str(job): {"provider": provider, "model": None, "effort": None}}})


def repaint(client, cid, character_id):
    return client.post(f"/api/campaigns/{cid}/characters/{character_id}/portrait/repaint", json={})


def sheet(client, cid, character_id):
    return next(c for c in client.get(f"/api/campaigns/{cid}/characters").json() if c["id"] == character_id)


@pytest.fixture
def npc(storage, table):  # noqa: F811
    return storage.characters.create(table["campaign"], "Old Tam", kind="npc").id


def test_portraitgen_repaints_at_once_from_the_sheet(local, table, storage, app):  # noqa: F811
    cid, garrek = table["campaign"], table["garrek"]
    character = storage.characters.get(garrek)
    storage.characters.save(replace(character, sheet=replace(character.sheet, portrait_prompt="a scarred old dwarf")))
    answered = repaint(table["Ana"], cid, garrek)
    assert answered.status_code == 200, answered.json()
    assert answered.json() == {"portrait": {"kind": "traits", "describe": "a scarred old dwarf", "seed": garrek}}
    assert sheet(table["Ana"], cid, garrek)["sheet"]["portrait"]["describe"] == "a scarred old dwarf"
    assert ("characters", {"campaign_id": cid}) in [(e.type, e.data) for e in published(app)]


def test_who_may_repaint(local, app, table, storage, npc):  # noqa: F811
    """The owner's choice: the host, a co-host and an organiser for any character; a player for their own PC."""
    cid, garrek, pippa = table["campaign"], table["garrek"], table["pippa"]
    assert repaint(local, cid, pippa).status_code == 200, "the owner hosts"
    assert repaint(table["Cy"], cid, npc).status_code == 200, "a co-host runs the table"
    assert repaint(table["Ana"], cid, garrek).status_code == 200, "her own PC"
    refused = repaint(table["Ana"], cid, pippa)
    assert refused.status_code == 403 and refused.json()["error"] == "Only the host, an organiser or the " \
        "character's player repaints its portrait."  # fmt: skip
    assert repaint(table["Ana"], cid, npc).status_code == 403, "an NPC is the DM's"

    token = new_seat_token()
    watcher = storage.seats.create(cid, "Dee", "en", "observer", token_hash=token_hash(token))
    with TestClient(app, base_url=BASE_URL) as observer:
        observer.cookies.set(SEAT_COOKIE, token)
        assert repaint(observer, cid, garrek).status_code == 403, f"{watcher.name} only watches"

    make_account(storage, "orla", organiser=True)
    with TestClient(app, base_url=BASE_URL) as organiser, TestClient(app, base_url=BASE_URL) as stranger:
        session_for(storage, storage.accounts.by_username("orla"), organiser)
        assert repaint(organiser, cid, npc).status_code == 200, "an organiser, without a seat"
        session_for(storage, make_account(storage, "sam"), stranger)
        assert repaint(stranger, cid, garrek).status_code == 403, "no seat at this table"
        assert repaint(TestClient(app, base_url=BASE_URL), cid, garrek).status_code == 401
    assert repaint(local, cid, "chr_nobody").status_code == 404


def test_a_paid_painter_needs_paid_images_and_says_so(local, table, storage, brush):  # noqa: F811
    """Refused, the button says why rather than drawing portraitgen's after all (the DM's tool does that)."""
    cid, garrek = table["campaign"], table["garrek"]
    choose(storage, Job.IMAGE_PORTRAIT, "brush")
    before = storage.characters.get(garrek).sheet.portrait
    refused = repaint(table["Ana"], cid, garrek)
    assert refused.status_code == 422
    assert refused.json() == {"error": images.PAID_OFF, "hint": images.PAID_HINT}
    assert storage.characters.get(garrek).sheet.portrait == before, "no portraitgen portrait instead"
    assert storage.campaign_images.list(cid, kind="portrait") == []


def test_a_paid_repaint_paints_in_the_background_and_the_old_portrait_stands(local, table, storage, brush):  # noqa: F811
    cid, garrek = table["campaign"], table["garrek"]
    choose(storage, Job.IMAGE_PORTRAIT, "brush")
    turn_on(local, cid)
    old = storage.characters.get(garrek).sheet.portrait
    answered = repaint(table["Ana"], cid, garrek)
    assert answered.status_code == 200 and answered.json()["status"] == "painting"
    shown = sheet(table["Ana"], cid, garrek)
    assert shown["portrait_painting"] is not None, "the sheet says it is painting"
    assert storage.characters.get(garrek).sheet.portrait == old, "the old portrait stays until the new one lands"
    again = repaint(table["Ana"], cid, garrek)
    assert again.status_code == 422 and again.json()["error"] == "Garrek's portrait is being painted already."

    brush.gate.set()
    done = settle(storage, answered.json()["image_id"])
    assert done.status == "done" and brush.asked == ["an adventurer"], "from the sheet"
    assert storage.characters.get(garrek).sheet.portrait == ImagePortrait(done.id)
    assert sheet(table["Ana"], cid, garrek)["portrait_painting"] is None


def test_a_paid_repaint_counts_towards_the_days_limit(local, table, storage, brush):  # noqa: F811
    cid, garrek = table["campaign"], table["garrek"]
    choose(storage, Job.IMAGE_PORTRAIT, "brush")
    turn_on(local, cid)
    assert local.put(f"/api/campaigns/{cid}/play/options", json={"paid_images_per_day": 1}).status_code == 200
    first = repaint(table["Ana"], cid, garrek)
    assert first.status_code == 200
    brush.gate.set()
    settle(storage, first.json()["image_id"])
    refused = repaint(table["Ana"], cid, garrek)
    assert refused.status_code == 429
    assert refused.json()["error"] == "This campaign's 1 paid pictures for the last 24 hours are used up."


def test_an_npcs_repaint_uses_the_npc_painter_and_no_portrait_says_they_are_off(local, table, storage, brush, npc):  # noqa: F811
    cid = table["campaign"]
    turn_on(local, cid)
    choose(storage, Job.IMAGE_NPC_PORTRAIT, "brush")
    answered = repaint(local, cid, npc)
    assert answered.status_code == 200 and answered.json()["status"] == "painting", "an NPC's job, its own painter"
    brush.gate.set()
    settle(storage, answered.json()["image_id"])

    choose(storage, Job.IMAGE_NPC_PORTRAIT, "none")
    refused = repaint(local, cid, npc)
    assert refused.status_code == 422 and refused.json()["error"] == images.NPC_PORTRAITS_OFF
    assert repaint(local, cid, table["garrek"]).status_code == 200, "a PC's job is not the NPCs'"


def test_a_failed_portrait_offers_try_again_until_something_replaces_it(local, table, storage, brush):  # noqa: F811
    cid, garrek = table["campaign"], table["garrek"]
    choose(storage, Job.IMAGE_PORTRAIT, "brush")
    turn_on(local, cid)
    assert sheet(table["Ana"], cid, garrek)["portrait_failed"] is False
    brush.fail = True
    brush.gate.set()
    first = repaint(table["Ana"], cid, garrek)
    assert settle(storage, first.json()["image_id"]).status == "failed"
    assert isinstance(storage.characters.get(garrek).sheet.portrait, TraitsPortrait), "the free one stands in"
    assert sheet(table["Ana"], cid, garrek)["portrait_failed"] is True

    brush.fail = False
    again = repaint(table["Ana"], cid, garrek)  # Try again is the same request
    assert again.status_code == 200
    assert settle(storage, again.json()["image_id"]).status == "done"
    assert sheet(table["Ana"], cid, garrek)["portrait_failed"] is False

    brush.fail = True
    settle(storage, repaint(table["Ana"], cid, garrek).json()["image_id"])
    assert sheet(table["Ana"], cid, garrek)["portrait_failed"] is True
    choose(storage, Job.IMAGE_PORTRAIT, "portraitgen")
    assert repaint(table["Ana"], cid, garrek).status_code == 200
    assert sheet(table["Ana"], cid, garrek)["portrait_failed"] is False, "a free portrait since replaces the stand-in"
