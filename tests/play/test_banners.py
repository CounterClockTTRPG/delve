"""A campaign's banner (looks and banners plan Task 2): asked for when the campaign is made, painted at once when the
paid gate is open, else `waiting` until it opens (`wake`), once. Its brief is built only from what any player may know:
the module's title, summary and description, and the setting. Never a real painter: `FakeImages` and fakes of its
kind."""

import asyncio

import pytest

from delve.dm.tools import all_specs
from delve.domain import new_id
from delve.domain.settings import BackendChoice, Job
from delve.domain.world import CampaignImage
from delve.images.fake import FakeImages
from delve.modules.source import ModuleSource, TextDoc, save_source
from delve.play import banners, images
from delve.play.context import PlayError
from delve.play.table import AppServices, set_play_settings
from tests.fixtures.play_reference import PlayReference
from tests.fixtures.rulesets import over
from tests.play.conftest import crypt_campaign

SECRET = "SECRET-XYZZY"
SPECS = {spec.name: spec for spec in all_specs()}


@pytest.fixture
def paid():
    """Whether the scene's chosen model costs money: `paid["scene"] = True` makes it a paid choice."""
    return {"scene": False}


@pytest.fixture
def services(storage, paid):
    return AppServices(
        storage=storage,
        catalogs=over(PlayReference()),
        spec_lookup=SPECS.get,
        dm=lambda campaign_id: (None, BackendChoice("fake")),
        side=lambda campaign_id: (None, BackendChoice("fake")),
        images=lambda job: (FakeImages(), BackendChoice("fake-images")),
        image_paid=lambda job: paid["scene"] and job is Job.IMAGE_SCENE,
    )


def banner(storage, campaign, status, **fields):
    return storage.campaign_images.put(CampaignImage(new_id("img"), campaign.id, "banner", status=status, **fields))


def settle(services):
    """Await every painting under way."""

    async def wait():
        while services.painting:
            await asyncio.gather(*services.painting.values(), return_exceptions=True)

    asyncio.run(wait())


def in_loop(call, *args, **kwargs):
    """Call `call` in a running event loop, as the routes do, without awaiting what it schedules."""

    async def run():
        return call(*args, **kwargs)

    return asyncio.run(run())


# ----- the brief -----


def test_the_brief_holds_only_what_players_may_know(storage, services):
    module = storage.modules.create("The Barrow Downs", {"summary": "Barrows in the fog", "setting": "Greyhawk"})
    keyed = f"# The Barrow\n\n## 1. Tomb\n\nThe wight waits here. {SECRET}\n"
    entities = {"npcs": [{"id": "npc_wight", "name": "The Wight", "notes": f"DM notes: {SECRET}"}]}
    save_source(
        storage,
        module.id,
        ModuleSource(texts=[TextDoc("barrow", "The Barrow", "gm", None, keyed)], entities=entities),
    )
    campaign = storage.campaigns.create(
        "Tuesday", module.id, storage.revisions.snapshot(module.id).number, ruleset="osric", setting="greyhawk"
    )
    storage.story.append(campaign.id, None, "dm_text", {"text": f"The story so far: {SECRET}"})

    image = in_loop(banners.ask, services, campaign.id, "Greyhawk")

    assert "The Barrow Downs" in image.prompt
    assert "Barrows in the fog" in image.prompt
    assert "Greyhawk" in image.prompt
    assert SECRET not in image.prompt


def test_the_briefs_form():
    assert banners.brief("The Crypt", "A crypt.", "Old bones", "Greyhawk", "mist") == (
        "A wide cinematic landscape painting of the world of The Crypt, in Greyhawk. A crypt. Old bones. "
        "No characters in the foreground, no text, no lettering. Emphasis: mist."
    )
    assert banners.brief("The Crypt", "", "", "") == (
        "A wide cinematic landscape painting of the world of The Crypt. "
        "No characters in the foreground, no text, no lettering."
    )


def test_a_long_markdown_description_is_cut_and_plain():
    description = "# Intro\n**Bold** [link](x)\n\n- one item\n- two\n\n" + "Lorem ipsum dolor sit amet. " * 1100
    assert len(description) > 30_000

    made = banners.brief("The Crypt", "", description, "Greyhawk")

    assert "Intro Bold link" in made
    assert "one item. two." in made, "a list's items are sentences"
    for mark in ("#", "*", "[", "(x)"):
        assert mark not in made, mark
    frame = len(banners.brief("The Crypt", "", "", "Greyhawk"))
    assert len(made) - frame <= banners.DESCRIPTION_CHARS + 2, "the description, its full stop and its space"


# ----- asking and waking -----


def test_with_the_gate_open_a_banner_is_painted_at_once(storage, campaign, services):
    async def run():
        image = banners.ask(services, campaign.id, "Greyhawk")
        assert image.status == "painting"
        await services.painting[image.id]
        return image

    image = asyncio.run(run())

    done = storage.campaign_images.get(image.id)
    assert done.status == "done" and done.blob is not None


def test_deciding_later_reads_the_gate_off_the_loop(storage, campaign, services):
    async def run():
        image = banners.ask(services, campaign.id, "Greyhawk", decide_later=True)
        assert image.status == "waiting" and services.painting == {}, "the gate isn't read in the loop"
        for _ in range(500):  # the task reads the gate in a thread, then paints
            if storage.campaign_images.get(image.id).status == "done":
                break
            await asyncio.sleep(0.01)
        return image

    image = asyncio.run(run())

    assert storage.campaign_images.get(image.id).status == "done"


def test_deciding_paints_only_when_the_gate_is_open(storage, campaign, services, paid):
    paid["scene"] = True
    waiting = banner(storage, campaign, "waiting", prompt="A wide painting.")
    assert asyncio.run(banners.decide(services, campaign.id)) == []
    assert storage.campaign_images.get(waiting.id).status == "waiting", "a paid model waits for the host"

    paid["scene"] = False

    async def run():
        woken = await banners.decide(services, campaign.id)
        await asyncio.gather(*services.painting.values())
        return woken

    assert asyncio.run(run()) == [waiting.id]
    assert storage.campaign_images.get(waiting.id).status == "done"


def test_with_the_gate_closed_a_banner_waits(storage, campaign, services, paid):
    paid["scene"] = True

    image = in_loop(banners.ask, services, campaign.id, "Greyhawk")

    assert image.status == "waiting"
    assert services.painting == {}
    assert storage.campaign_images.get(image.id).status == "waiting"


def test_asking_again_replaces_a_waiting_banner(storage, campaign, services, paid):
    paid["scene"] = True
    first = in_loop(banners.ask, services, campaign.id, "Greyhawk")
    second = in_loop(banners.ask, services, campaign.id, "Greyhawk", hint="mist")

    assert [i.id for i in storage.campaign_images.list(campaign.id, kind="banner")] == [second.id]
    assert first.id != second.id and "Emphasis: mist." in second.prompt


def test_opening_the_gate_paints_a_waiting_banner_once(storage, campaign, services, paid):
    paid["scene"] = True
    image = in_loop(banners.ask, services, campaign.id, "Greyhawk")
    assert in_loop(banners.wake, services, campaign.id) == [], "the gate is still closed"

    async def run():
        set_play_settings(storage, campaign.id, {"paid_images": True})
        woken = banners.wake(services, campaign.id)
        assert woken == [image.id]
        assert storage.campaign_images.get(image.id).status == "painting"
        assert banners.wake(services, campaign.id) == [], "nothing more is scheduled"
        assert banners.wake(services) == []
        set_play_settings(storage, campaign.id, {"paid_images": False})
        set_play_settings(storage, campaign.id, {"paid_images": True})
        assert banners.wake(services, campaign.id) == []
        assert list(services.painting) == [image.id], "still one painting"
        await services.painting[image.id]

    asyncio.run(run())

    rows = storage.campaign_images.list(campaign.id, kind="banner")
    assert [(r.id, r.status, r.attempts) for r in rows] == [(image.id, "done", 1)]


def test_waking_every_campaign_paints_only_those_whose_gate_opened(storage, campaign, services, paid):
    paid["scene"] = True
    other = crypt_campaign(storage)
    here = in_loop(banners.ask, services, campaign.id, "Greyhawk")
    there = in_loop(banners.ask, services, other.id, "Greyhawk")
    set_play_settings(storage, other.id, {"paid_images": True})

    async def run():
        assert banners.wake(services) == [there.id]
        await asyncio.gather(*services.painting.values())

    asyncio.run(run())

    assert storage.campaign_images.get(here.id).status == "waiting"
    assert storage.campaign_images.get(there.id).status == "done"


def test_turning_the_gate_off_doesnt_cancel_a_painting(storage, campaign, services, paid):
    async def run():
        image = banners.ask(services, campaign.id, "Greyhawk")
        paid["scene"] = True
        await services.painting[image.id]
        return image

    image = asyncio.run(run())

    assert storage.campaign_images.get(image.id).status == "done"


def test_paint_again_obeys_the_gate_and_refuses_a_second_painting(storage, campaign, services, paid):
    paid["scene"] = True
    with pytest.raises(PlayError) as closed:
        in_loop(banners.paint_again, services, campaign.id, "Greyhawk")
    assert (closed.value.message, closed.value.hint) == (images.PAID_OFF, images.PAID_HINT)
    assert storage.campaign_images.list(campaign.id, kind="banner") == [], "nothing is asked"

    paid["scene"] = False

    async def run():
        first = banners.paint_again(services, campaign.id, "Greyhawk", hint="mist")
        assert first.status == "painting"
        with pytest.raises(PlayError) as twice:
            banners.paint_again(services, campaign.id, "Greyhawk")
        assert "being painted" in twice.value.message
        await services.painting[first.id]

    asyncio.run(run())


def test_current_and_pending(storage, campaign):
    assert banners.current(storage, campaign.id) is None
    assert banners.pending(storage, campaign.id) is None

    waiting = banner(storage, campaign, "waiting")
    assert banners.current(storage, campaign.id) is None
    assert banners.pending(storage, campaign.id).id == waiting.id, "no current yet: the newest that isn't done"

    storage.campaign_images.delete(waiting.id)
    old = banner(storage, campaign, "done", blob="a" * 64, mime="image/png")
    new = banner(storage, campaign, "done", blob="b" * 64, mime="image/png")
    assert banners.current(storage, campaign.id).id == new.id, "the newest done"
    assert banners.pending(storage, campaign.id) is None

    failed = banner(storage, campaign, "failed", error="The model is down")
    assert banners.current(storage, campaign.id).id == new.id
    assert banners.pending(storage, campaign.id).id == failed.id

    painting = banner(storage, campaign, "painting")
    assert banners.pending(storage, campaign.id).id == painting.id, "the newest of those newer than the current"
    assert old.id != new.id
