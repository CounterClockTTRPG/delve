"""Pictures (plan 6 Task 10, Review Focus 4): free portraits at once, and paid portraits, possessions' pictures and
scenes painted in the background by `delve.play.images`. The DM's picture tools answer at once; `paint` runs the
provider later and lands its result: the subject's portrait, or a `scene` entry for the row's audience. Paid images are
off until the host turns them on; a failed painting leaves a notice for the host, and a portrait falls back to
portraitgen. Paid pictures stop at the campaign's limit for a day, and the DM's at its limits for a beat (DEL-153).
Never a real Replicate call: `FakeImages` and fakes of its kind."""

import asyncio
import itertools
import json
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

import pytest

from delve.dice import SeededRng
from delve.dm.fake import FakeDM
from delve.dm.tools import ToolHost, all_specs
from delve.domain import new_id
from delve.domain.backends import ModelInfo, ProviderCapabilities, Registry
from delve.domain.characters import Sheet
from delve.domain.settings import BackendChoice, Job
from delve.domain.world import CampaignImage, ImagePortrait, Possession, TraitsPortrait
from delve.images.fake import FAKE_IMAGES_CAPABILITIES, PIXEL_PNG, FakeImages
from delve.images.portraitgen import PORTRAITGEN, PORTRAITGEN_CAPABILITIES, PortraitgenImages
from delve.images.provider import ImageFile, ProviderJob
from delve.images.replicate import REPLICATE_CAPABILITIES
from delve.play import banners, images, seats
from delve.play.audience import for_seats
from delve.play.context import PlayError
from delve.play.table import PAID_PER_DAY, AppServices, set_play_settings, story
from tests.fixtures.play_reference import PlayReference
from tests.fixtures.rulesets import over
from tests.play.conftest import crypt_campaign

SECRET = "SECRET-XYZZY"
SPECS = {spec.name: spec for spec in all_specs()}


class Painter:
    """An image provider that paints every job as a PNG, and remembers what it was asked."""

    def __init__(self) -> None:
        self.requests = []

    async def generate(self, req):
        self.requests.append(req)
        return ImageFile(PIXEL_PNG, "image/png")


class Broken:
    async def generate(self, req):
        raise RuntimeError("Replicate failed: the model is down")


@pytest.fixture
def providers():
    """The image provider each job gets: `providers[job] = provider`; portraitgen for portraits by default."""
    return {Job.IMAGE_PORTRAIT: PortraitgenImages(), Job.IMAGE_SCENE: Painter(), Job.IMAGE_POSSESSION: Painter()}


@pytest.fixture
def events():
    return []


@pytest.fixture
def services(storage, providers, events):
    def choice(job):
        if job not in providers:
            raise PlayError(f"No provider does the {job} job.", "Choose one under Settings.")
        return providers[job], BackendChoice(type(providers[job]).__name__)

    return AppServices(
        storage=storage,
        catalogs=over(PlayReference()),
        spec_lookup=SPECS.get,
        dm=lambda campaign_id: (None, BackendChoice("fake")),
        side=lambda campaign_id: (None, BackendChoice("fake")),
        publish=lambda kind, data, **where: events.append((kind, data, where)),
        images=choice,
    )


@pytest.fixture
def call(storage, campaign):
    seeds = itertools.count(1)
    host = ToolHost(storage, lambda: SeededRng(next(seeds)), catalogs=over(PlayReference()))

    def run(tool, /, **args):
        return host.call(campaign.id, "beat-1", tool, args)

    return run


@pytest.fixture
def garrek(storage, campaign):
    sheet = Sheet(race="Dwarf", gender="male", cls="Fighter", levels={"fighter": 3})
    return storage.characters.create(campaign.id, "Garrek", sheet=sheet)


@pytest.fixture
def cog(storage, campaign):
    return storage.possessions.put(Possession(campaign.id, "pos_cog", "The Grey Cog", "ship", notes_md=SECRET))


def paid(storage, campaign, on=True):
    set_play_settings(storage, campaign.id, {"paid_images": on})


def portrait_job(storage, provider):
    storage.settings.save({"choices": {"image.portrait": {"provider": provider, "model": None, "effort": None}}})


def paint(services, image_id):
    return asyncio.run(images.paint(services, image_id))


# ----- free portraits -----


def test_paid_images_are_off_by_default(storage, campaign):
    assert images.paid_images(storage, campaign.id) is False
    paid(storage, campaign)
    assert images.paid_images(storage, campaign.id) is True
    with pytest.raises(PlayError):
        set_play_settings(storage, campaign.id, {"paid_images": "yes"})


def test_a_portraitgen_portrait_is_instant_and_only_a_description_and_a_seed(storage, campaign, call, garrek):
    built = call("portrait", of="Garrek")
    assert built["portrait"] == {"kind": "traits", "describe": "a male dwarf fighter", "seed": garrek.id}
    assert storage.characters.get(garrek.id).sheet.portrait == TraitsPortrait("a male dwarf fighter", garrek.id)
    assert storage.campaign_images.list(campaign.id) == [], "nothing is painted"

    given = call("portrait", of=garrek.id, description="a stout old dwarf with a braided red beard")
    assert given["portrait"]["describe"] == "a stout old dwarf with a braided red beard"
    assert storage.characters.get(garrek.id).sheet.portrait.to_dict() == {
        "kind": "traits",
        "describe": "a stout old dwarf with a braided red beard",
        "seed": garrek.id,
    }


def test_with_paid_images_off_a_portrait_falls_back_to_portraitgen(storage, campaign, call, garrek):
    portrait_job(storage, "replicate")
    assert call("portrait", of="Garrek")["portrait"]["kind"] == "traits"
    assert storage.campaign_images.list(campaign.id) == []


def test_with_paid_images_off_scenes_and_possessions_are_refused_with_a_hint(storage, campaign, call, cog):
    scene = call("paint_scene", brief="The bridge at dusk.")
    assert scene["error"] == images.PAID_OFF and scene["hint"] == images.PAID_HINT
    picture = call("portrait", of="The Grey Cog")
    assert picture["error"] == images.PAID_OFF and picture["hint"] == images.PAID_HINT
    assert storage.campaign_images.list(campaign.id) == []


def test_an_unknown_subject_names_the_characters_and_possessions(call, garrek, cog):
    refused = call("portrait", of="Nobody")
    assert refused["error"] == "No character or possession 'Nobody'."
    assert {c["id"] for c in refused["candidates"]} == {garrek.id, cog.id}


# ----- paid paintings -----


def test_a_paid_portrait_answers_at_once_and_is_painted_later(storage, campaign, call, garrek, services, providers):
    paid(storage, campaign)
    portrait_job(storage, "replicate")
    providers[Job.IMAGE_PORTRAIT] = painter = Painter()
    answered = call("portrait", of="Garrek", description="a stout dwarf")
    assert set(answered) == {"image_id", "status", "of"} and answered["status"] == "painting"
    (row,) = storage.campaign_images.list(campaign.id)
    assert (row.id, row.kind, row.subject_id, row.status, row.prompt) == (
        answered["image_id"], "portrait", garrek.id, "painting", "a stout dwarf",
    )  # fmt: skip
    assert storage.characters.get(garrek.id).sheet.portrait is None, "not before it is painted"

    done = paint(services, row.id)
    assert (done.status, done.mime, done.attempts, done.backend) == ("done", "image/png", 1, "Painter")
    assert storage.blobs.get(done.blob) == PIXEL_PNG
    assert storage.characters.get(garrek.id).sheet.portrait == ImagePortrait(row.id)
    (req,) = painter.requests
    assert (req.job, req.prompt, req.tone) == (Job.IMAGE_PORTRAIT, "a stout dwarf", "classic")
    assert req.style == "", "no image style chosen: the tone's"


def test_a_painting_takes_the_install_s_image_style(storage, campaign, call, garrek, services, providers):
    paid(storage, campaign)
    portrait_job(storage, "replicate")
    storage.settings.save({**storage.settings.load(), "image_style": {"preset": "custom", "custom": "ink and wash"}})
    providers[Job.IMAGE_PORTRAIT] = painter = Painter()
    answered = call("portrait", of="Garrek", description="a stout dwarf")
    paint(services, answered["image_id"])
    (req,) = painter.requests
    assert (req.tone, req.style) == ("classic", "ink and wash")


def test_a_portrait_provider_that_answers_traits_sets_a_free_portrait(
    storage, campaign, call, garrek, services, providers
):
    paid(storage, campaign)
    portrait_job(storage, "fake-images")
    providers[Job.IMAGE_PORTRAIT] = FakeImages()
    row = storage.campaign_images.get(call("portrait", of="Garrek")["image_id"])
    assert paint(services, row.id).status == "done"
    assert storage.characters.get(garrek.id).sheet.portrait == TraitsPortrait("a male dwarf fighter", garrek.id)


def test_a_possessions_picture(storage, campaign, call, cog, services, events):
    paid(storage, campaign)
    answered = call("portrait", of="The Grey Cog", description="a squat grey cog with one mast")
    row = storage.campaign_images.get(answered["image_id"])
    assert (row.kind, row.subject_id) == ("possession", cog.id)
    paint(services, row.id)
    assert storage.possessions.get(campaign.id, cog.id).portrait == ImagePortrait(row.id)
    assert [kind for kind, _, _ in events] == ["world"]


def test_a_scene_lands_in_the_story_for_its_audience(storage, campaign, call, garrek, services, events, owner_seat):
    paid(storage, campaign)
    pippa = storage.characters.create(campaign.id, "Pippa")
    ana = storage.seats.create(campaign.id, "Ana", "en", "player")
    bo = storage.seats.create(campaign.id, "Bo", "en", "player")
    seats.claim(storage, garrek.id, ana)
    seats.claim(storage, pippa.id, bo)
    answered = call("paint_scene", brief=f"{SECRET}: the lich behind the altar.", caption="Behind the altar",
                    characters=["Garrek"])  # fmt: skip
    row = storage.campaign_images.get(answered["image_id"])
    assert row.audience == for_seats([ana.id]) and row.caption == "Behind the altar"
    assert story(storage, campaign.id, ana)["entries"] == [], "nothing until it is painted"

    paint(services, row.id)
    (entry,) = story(storage, campaign.id, ana)["entries"]
    assert (entry.kind, entry.payload, entry.beat_id) == (
        "scene",
        {"image_id": row.id, "caption": "Behind the altar"},
        None,
    )
    assert entry.audience == for_seats([ana.id])
    for other in (bo, owner_seat):
        assert story(storage, campaign.id, other)["entries"] == []
    (kind, data, where), (scenes, _, _) = events
    assert scenes == "scenes", "the placeholder goes"
    assert kind == "story" and where["audience"] == for_seats([ana.id]) and SECRET not in json.dumps(data)
    assert not images.can_see(storage, ana, row), "not while it is painting"
    done = storage.campaign_images.get(row.id)
    assert images.can_see(storage, ana, done) and not images.can_see(storage, bo, done)


def test_the_prompt_never_reaches_the_story(storage, campaign, call, services, owner_seat):
    paid(storage, campaign)
    row = call("paint_scene", brief=f"{SECRET}: the cult's altar.")
    paint(services, row["image_id"])
    assert SECRET not in json.dumps([e.payload for e in story(storage, campaign.id, owner_seat)["entries"]])


# ----- Review Focus 4: paid images go wrong -----


def test_a_failed_scene_leaves_a_notice_for_the_host(storage, campaign, call, services, providers, owner_seat, events):
    paid(storage, campaign)
    providers[Job.IMAGE_SCENE] = Broken()
    row = call("paint_scene", brief="The bridge at dusk.")
    failed = paint(services, row["image_id"])
    assert (failed.status, failed.error, failed.blob) == ("failed", "Replicate failed: the model is down", None)
    (notice,) = story(storage, campaign.id, owner_seat)["entries"]
    assert (notice.kind, notice.payload) == ("dm_error", {"message": images.SCENE_FAILED})
    assert notice.audience == for_seats([owner_seat.id]), "the host's notice"
    player = storage.seats.create(campaign.id, "Ana", "en", "player")
    assert story(storage, campaign.id, player)["entries"] == []
    assert [kind for kind, _, _ in events] == ["story", "scenes"], "the placeholder goes"


def test_a_failed_portrait_falls_back_to_portraitgen(storage, campaign, call, garrek, services, providers, owner_seat):
    paid(storage, campaign)
    portrait_job(storage, "replicate")
    providers[Job.IMAGE_PORTRAIT] = Broken()
    row = call("portrait", of="Garrek", description="a stout dwarf")
    assert paint(services, row["image_id"]).status == "failed"
    assert storage.characters.get(garrek.id).sheet.portrait == TraitsPortrait("a stout dwarf", garrek.id)
    (notice,) = story(storage, campaign.id, owner_seat)["entries"]
    assert notice.payload == {"message": images.PORTRAIT_FAILED.format(name="Garrek")}


def test_a_failed_portrait_keeps_a_painted_one(storage, campaign, call, garrek, services, providers):
    paid(storage, campaign)
    portrait_job(storage, "replicate")
    providers[Job.IMAGE_PORTRAIT] = Painter()
    first = call("portrait", of="Garrek")["image_id"]
    paint(services, first)
    providers[Job.IMAGE_PORTRAIT] = Broken()
    paint(services, dm_in(storage, campaign, "beat-2")("portrait", of="Garrek")["image_id"])  # a beat paints it once
    assert storage.characters.get(garrek.id).sheet.portrait == ImagePortrait(first)


def test_no_provider_for_the_job_is_a_failure_not_an_exception(storage, campaign, call, services, providers):
    """No Replicate token: nothing paints scenes (development's fake aside)."""
    paid(storage, campaign)
    del providers[Job.IMAGE_SCENE]
    row = call("paint_scene", brief="The bridge.")
    failed = paint(services, row["image_id"])
    assert failed.status == "failed" and "image.scene" in failed.error


def test_a_slow_painting_never_holds_up_the_caller(storage, campaign, call, services, providers):
    """The tool answers at once; the painting runs in its own task, and a second request doesn't wait for it."""
    paid(storage, campaign)

    class Slow:
        def __init__(self):
            self.gate = asyncio.Event()

        async def generate(self, req):
            await self.gate.wait()
            return ImageFile(PIXEL_PNG, "image/png")

    async def run():
        providers[Job.IMAGE_SCENE] = slow = Slow()
        first = call("paint_scene", brief="One.")["image_id"]
        assert images.schedule_waiting(services, campaign.id) == [first]
        await asyncio.sleep(0)
        second = call("paint_scene", brief="Two.")["image_id"]
        assert images.schedule_waiting(services, campaign.id) == [second], "the first is under way already"
        await asyncio.sleep(0.01)
        assert {r.status for r in storage.campaign_images.list(campaign.id)} == {"painting"}
        slow.gate.set()
        await asyncio.gather(*services.painting.values())
        return first, second

    first, second = asyncio.run(run())
    assert [storage.campaign_images.get(i).status for i in (first, second)] == ["done", "done"]
    assert services.painting == {}


def test_a_painting_cut_short_by_a_restart_is_retried_once(storage, campaign, call, services, owner_seat):
    paid(storage, campaign)
    once = storage.campaign_images.get(call("paint_scene", brief="Cut short once.")["image_id"])
    twice = storage.campaign_images.get(call("paint_scene", brief="Cut short twice.")["image_id"])
    storage.campaign_images.put(replace(once, attempts=1))
    storage.campaign_images.put(replace(twice, attempts=2))

    async def run():
        images.resume(services)
        await asyncio.gather(*services.painting.values())

    asyncio.run(run())
    retried, given_up = storage.campaign_images.get(once.id), storage.campaign_images.get(twice.id)
    assert (retried.status, retried.attempts) == ("done", 2)
    assert (given_up.status, given_up.error) == ("failed", images.INTERRUPTED)
    kinds = [(e.kind, e.payload) for e in story(storage, campaign.id, owner_seat)["entries"]]
    assert ("dm_error", {"message": images.SCENE_FAILED}) in kinds and (
        "scene",
        {"image_id": once.id, "caption": ""},
    ) in kinds


class Queued:
    """A provider with a queue of its own, as assetgen is: it tells the watch its job and its place, and paints once
    `gate` is set."""

    def __init__(self, *places):
        self.places = places
        self.gate = asyncio.Event()
        self.requests = []

    async def generate(self, req):
        self.requests.append(req)
        for place in self.places:
            req.watch(ProviderJob(req.follow or "j-1", place))
            await asyncio.sleep(0)
        req.watch(ProviderJob(req.follow or "j-1"))
        await self.gate.wait()
        return ImageFile(PIXEL_PNG, "image/png")


def test_a_painting_waiting_in_the_providers_queue_shows_its_place(
    storage, campaign, call, services, providers, events
):
    paid(storage, campaign)
    providers[Job.IMAGE_SCENE] = queued = Queued(3, 2)

    async def run():
        image_id = call("paint_scene", brief="A queue.")["image_id"]
        images.schedule_waiting(services, campaign.id)
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        seen = storage.campaign_images.get(image_id)
        places.append((seen.provider_job, seen.queue))
        await asyncio.sleep(0.01)
        seen = storage.campaign_images.get(image_id)
        places.append((seen.provider_job, seen.queue))
        queued.gate.set()
        await asyncio.gather(*services.painting.values())
        return image_id

    places = []
    image_id = asyncio.run(run())
    assert places[0] in {("j-1", 3), ("j-1", 2)} and places[1] == ("j-1", None)
    done = storage.campaign_images.get(image_id)
    assert (done.status, done.queue, done.provider_job, done.attempts) == ("done", None, "j-1", 1)
    assert sum(kind == "scenes" for kind, _, _ in events) >= 4, "each place is told to the table"


def test_a_restart_follows_the_providers_job_and_isnt_counted(storage, campaign, call, services, providers):
    """Two restarts while assetgen painted (DEL-138): the same job is followed, no copy is sent, nothing fails."""
    paid(storage, campaign)
    providers[Job.IMAGE_SCENE] = queued = Queued()
    queued.gate.set()
    row = storage.campaign_images.get(call("paint_scene", brief="Cut short twice.")["image_id"])
    storage.campaign_images.put(replace(row, attempts=2, backend="Queued", provider_job="j-9", queue=4))

    async def run():
        images.resume(services)
        await asyncio.gather(*services.painting.values())

    asyncio.run(run())
    done = storage.campaign_images.get(row.id)
    assert (done.status, done.attempts, done.provider_job) == ("done", 2, "j-9")
    assert [r.follow for r in queued.requests] == ["j-9"]


def test_another_providers_job_is_not_followed(storage, campaign, call, services, providers):
    paid(storage, campaign)
    providers[Job.IMAGE_SCENE] = queued = Queued()
    queued.gate.set()
    row = storage.campaign_images.get(call("paint_scene", brief="Moved to another painter.")["image_id"])
    storage.campaign_images.put(replace(row, attempts=1, backend="assetgen", provider_job="j-9"))

    async def run():
        images.resume(services)
        await asyncio.gather(*services.painting.values())

    asyncio.run(run())
    done = storage.campaign_images.get(row.id)
    assert (done.status, done.attempts, done.provider_job) == ("done", 2, "j-1")
    assert [r.follow for r in queued.requests] == [""]


def test_stop_keeps_the_providers_job_for_the_next_start(storage, campaign, call, services, providers):
    paid(storage, campaign)
    providers[Job.IMAGE_SCENE] = Queued(5)

    async def run_and_stop():
        image_id = call("paint_scene", brief="Waiting its turn.")["image_id"]
        images.schedule_waiting(services, campaign.id)
        await asyncio.sleep(0.01)
        await asyncio.gather(*images.stop(services), return_exceptions=True)
        return image_id

    row = storage.campaign_images.get(asyncio.run(run_and_stop()))
    assert (row.status, row.provider_job, row.attempts) == ("painting", "j-1", 1)


def test_stop_cancels_the_paintings_and_leaves_them_painting(storage, campaign, call, services, providers):
    paid(storage, campaign)

    class Never:
        async def generate(self, req):
            await asyncio.Event().wait()

    providers[Job.IMAGE_SCENE] = Never()

    async def run_and_stop():
        image_id = call("paint_scene", brief="Forever.")["image_id"]
        images.schedule_waiting(services, campaign.id)
        await asyncio.sleep(0.01)
        await asyncio.gather(*images.stop(services), return_exceptions=True)
        return image_id

    image_id = asyncio.run(run_and_stop())
    row = storage.campaign_images.get(image_id)
    assert (row.status, row.attempts) == ("painting", 1), "the next start retries it"


def test_stop_leaves_another_event_loops_paintings_alone(storage, campaign, services):
    """Two test clients on one app run two loops: the one stopping gathers only its own paintings."""
    other = asyncio.new_event_loop()
    try:
        elsewhere = other.create_task(asyncio.sleep(3600))
        services.painting["img_elsewhere"] = elsewhere

        async def stop_here():
            await asyncio.gather(*images.stop(services), return_exceptions=True)

        asyncio.run(stop_here())
        assert not elsewhere.cancelled() and services.painting == {"img_elsewhere": elsewhere}
    finally:
        elsewhere.cancel()
        other.run_until_complete(asyncio.gather(elsewhere, return_exceptions=True))
        other.close()
        services.painting.clear()


def test_the_portrait_job_on_portraitgen(storage):
    assert images.portrait_provider(storage) == PORTRAITGEN
    portrait_job(storage, "replicate")
    assert images.portrait_provider(storage) == "replicate"


# ----- the paid gate, per model (portraits plan Task 4) -----

LOCAL = ProviderCapabilities(
    "local-painter",
    "A local painter",
    frozenset({Job.IMAGE_PORTRAIT, Job.IMAGE_SCENE, Job.IMAGE_POSSESSION}),
    models=("sdxl-local", "flux-schnell", "odd"),
    model_info={
        "sdxl-local": ModelInfo("SDXL", "local", "free (local CPU)", paid=False),
        "flux-schnell": ModelInfo("FLUX schnell", "replicate", "~$0.003 / image", paid=True),
    },
    default_model="sdxl-local",
    live=True,
)


@pytest.fixture
def registries():
    painters = Registry()
    for caps in (PORTRAITGEN_CAPABILITIES, FAKE_IMAGES_CAPABILITIES, REPLICATE_CAPABILITIES, LOCAL):
        painters.register(caps, Painter)
    return SimpleNamespace(images=painters)


def choose(storage, job, provider, model=None):
    choices = storage.settings.load().get("choices", {})
    choices[str(job)] = {"provider": provider, "model": model, "effort": None}
    storage.settings.save({"choices": choices})


def chosen_is_paid(storage, registries):
    """`image_paid` as the app wires it: Preferences' stored choice for the job, judged by `is_paid`."""

    def paid(job):
        raw = storage.settings.load().get("choices", {}).get(str(job))
        return raw is None or images.is_paid(registries, job, BackendChoice(raw["provider"], raw["model"]))

    return paid


@pytest.fixture
def gated(storage, campaign, registries):
    """The tools, with the paid gate asking the chosen model."""
    host = ToolHost(storage, lambda: SeededRng(1), image_paid=chosen_is_paid(storage, registries), catalogs=over(PlayReference()))

    def run(tool, /, **args):
        return host.call(campaign.id, "beat-1", tool, args)

    return run


def test_is_paid_asks_the_chosen_model(registries):
    def paid(provider, model=None, job=Job.IMAGE_SCENE):
        return images.is_paid(registries, job, BackendChoice(provider, model))

    assert paid(PORTRAITGEN, job=Job.IMAGE_PORTRAIT) is False, "portraitgen is free"
    assert paid("fake-images") is False, "and so is the fake"
    assert paid("replicate") is True and paid("replicate", "black-forest-labs/flux-schnell") is True
    assert paid("local-painter", "sdxl-local") is False, "a free model"
    assert paid("local-painter") is False, "no model is the provider's default"
    assert paid("local-painter", "flux-schnell") is True, "the model decides, not the provider"
    assert paid("local-painter", "odd") is True, "a model it says nothing about counts as paid"
    assert paid("local-painter", "gone") is True, "an unknown model counts as paid"
    assert paid("nobody") is True, "an unknown provider counts as paid"


def test_with_paid_images_off_a_free_model_paints_a_scene(storage, campaign, gated):
    choose(storage, Job.IMAGE_SCENE, "local-painter", "sdxl-local")
    painted = gated("paint_scene", brief="The bridge at dusk.")
    assert painted["status"] == "painting", painted
    assert [i.kind for i in storage.campaign_images.list(campaign.id)] == ["scene"]


def test_with_paid_images_off_a_paid_model_is_refused_with_the_hint(storage, campaign, gated, cog):
    for provider, model in (("replicate", None), ("local-painter", "flux-schnell"), ("local-painter", "gone")):
        choose(storage, Job.IMAGE_SCENE, provider, model)
        refused = gated("paint_scene", brief="The bridge at dusk.")
        assert (refused["error"], refused["hint"]) == (images.PAID_OFF, images.PAID_HINT), (provider, model)
    assert "costs money" in images.PAID_HINT
    choose(storage, Job.IMAGE_POSSESSION, "replicate")
    assert gated("portrait", of="The Grey Cog")["error"] == images.PAID_OFF
    choose(storage, Job.IMAGE_POSSESSION, "local-painter", "sdxl-local")
    assert gated("portrait", of="The Grey Cog")["status"] == "painting"
    paid(storage, campaign)
    choose(storage, Job.IMAGE_SCENE, "replicate")
    assert gated("paint_scene", brief="The bridge at dusk.")["status"] == "painting", "paid images on: painted"


def test_with_paid_images_off_a_free_model_paints_a_portrait(storage, campaign, gated, garrek):
    choose(storage, Job.IMAGE_PORTRAIT, "local-painter", "sdxl-local")
    assert gated("portrait", of="Garrek")["status"] == "painting"
    choose(storage, Job.IMAGE_PORTRAIT, "replicate")
    assert gated("portrait", of="Garrek")["portrait"]["kind"] == "traits", "a paid one falls back to portraitgen"


def test_without_the_gate_wired_every_painting_counts_as_paid(storage, campaign, call):
    choose(storage, Job.IMAGE_SCENE, "local-painter", "sdxl-local")
    assert call("paint_scene", brief="The bridge at dusk.")["error"] == images.PAID_OFF


def test_paint_this_scene_asks_the_chosen_model(storage, campaign, services, registries):
    storage.story.append(campaign.id, None, "dm_text", {"text": "Rain on the bridge."})
    services.side = lambda campaign_id: (FakeDM([], side_handler=lambda prompt: "A brief."), BackendChoice("fake"))
    services.image_paid = chosen_is_paid(storage, registries)
    choose(storage, Job.IMAGE_SCENE, "replicate")
    with pytest.raises(PlayError) as refused:
        asyncio.run(images.paint_this_scene(services, campaign.id))
    assert (refused.value.message, refused.value.hint) == (images.PAID_OFF, images.PAID_HINT)

    choose(storage, Job.IMAGE_SCENE, "local-painter", "sdxl-local")
    image = asyncio.run(images.paint_this_scene(services, campaign.id))
    assert (image.kind, image.prompt) == ("scene", "A brief.")


# ----- banners (looks and banners plan Task 1) -----


def banner(storage, campaign, status="painting", **fields):
    return storage.campaign_images.put(
        CampaignImage(new_id("img"), campaign.id, images.BANNER, status=status, prompt="The barrows in mist.", **fields)
    )


def test_a_banner_is_painted_wide_with_the_scenes_choice(storage, campaign, services, providers, events):
    row = banner(storage, campaign)
    done = paint(services, row.id)
    (req,) = providers[Job.IMAGE_SCENE].requests
    assert req.job is Job.IMAGE_SCENE and req.aspect == "21:9"
    assert (done.status, done.blob) == ("done", storage.blobs.put(PIXEL_PNG, "image/png"))
    assert events == [
        ("banner", {"campaign_id": campaign.id, "image_id": row.id}, {"scope": "table", "campaign_id": campaign.id}),
        ("campaigns", {"id": campaign.id}, {}),
    ]


def test_a_landed_banner_replaces_the_older_ones(storage, campaign, services):
    old = banner(storage, campaign, status="done", blob="a" * 64, mime="image/png")
    stale = banner(storage, campaign, status="waiting")
    new = banner(storage, campaign)
    scene = storage.campaign_images.put(CampaignImage(new_id("img"), campaign.id, "scene", status="done"))
    paint(services, new.id)
    assert [i.id for i in storage.campaign_images.list(campaign.id, kind="banner")] == [new.id]
    assert storage.campaign_images.get(old.id) is None and storage.campaign_images.get(stale.id) is None
    assert storage.campaign_images.get(scene.id) is not None, "only banners go"


def test_a_failed_banner_keeps_the_old_one_and_tells_no_seat(storage, campaign, services, providers, events):
    old = banner(storage, campaign, status="done", blob="a" * 64, mime="image/png")
    new = banner(storage, campaign)
    providers[Job.IMAGE_SCENE] = Broken()
    before = storage.story.list(campaign.id)
    failed = paint(services, new.id)
    assert (failed.status, failed.error) == ("failed", "Replicate failed: the model is down")
    assert storage.campaign_images.get(old.id).status == "done"
    assert storage.story.list(campaign.id) == before, "no story entry"
    assert events == [("campaigns", {"id": campaign.id}, {})], "only the organisers hear of it"


def test_no_table_event_reaches_a_seat_when_a_banner_fails(storage, campaign, services, providers, events):
    providers[Job.IMAGE_SCENE] = Broken()
    paint(services, banner(storage, campaign).id)
    banner(storage, campaign, attempts=2)
    images.resume(services)  # a banner started twice already fails at start
    assert len(storage.campaign_images.list(campaign.id, kind="banner", status="failed")) == 2
    assert [kind for kind, _, where in events if where.get("scope") == "table"] == []


def test_resume_leaves_waiting_rows_alone(storage, campaign, services):
    row = banner(storage, campaign, status="waiting")
    assert storage.campaign_images.list(campaign.id, status="waiting") == [row]
    assert storage.campaign_images.painting() == []

    async def run():
        images.resume(services)
        return dict(services.painting)

    assert asyncio.run(run()) == {}, "nothing is scheduled"
    assert storage.campaign_images.get(row.id).status == "waiting"


def test_every_seat_sees_a_done_banner(storage, campaign):
    done = banner(storage, campaign, status="done", blob="a" * 64, mime="image/png")
    player = storage.seats.create(campaign.id, "Ana", "en", "player")
    observer = storage.seats.create(campaign.id, "Bo", "en", "observer")
    other = crypt_campaign(storage)
    stranger = storage.seats.create(other.id, "Cy", "en", "player")
    assert images.can_see(storage, player, done) and images.can_see(storage, observer, done)
    assert not images.can_see(storage, stranger, done)
    for status in ("waiting", "painting", "failed"):
        assert not images.can_see(storage, player, replace(done, status=status)), status


# ----- the paid limit (DEL-153, audit finding 6) -----


def dm_in(storage, campaign, beat):
    """The DM's tools in the beat `beat`, the gate wired as `call`'s: every painting costs money."""
    host = ToolHost(storage, lambda: SeededRng(1), catalogs=over(PlayReference()))
    return lambda tool, /, **args: host.call(campaign.id, beat, tool, args)


def test_the_paid_limit_defaults_and_is_checked(storage, campaign):
    assert images.paid_limit(storage, campaign.id) == PAID_PER_DAY == 20
    set_play_settings(storage, campaign.id, {"paid_images_per_day": 5})
    assert images.paid_limit(storage, campaign.id) == 5
    for wrong in (0, 501, True, "5", 2.5):
        with pytest.raises(PlayError):
            set_play_settings(storage, campaign.id, {"paid_images_per_day": wrong})


def test_paid_pictures_stop_at_the_campaigns_limit_for_a_day(storage, campaign, cog, monkeypatch):
    paid(storage, campaign)
    set_play_settings(storage, campaign.id, {"paid_images_per_day": 3})
    assert dm_in(storage, campaign, "beat-1")("paint_scene", brief="The bridge.")["status"] == "painting"
    assert dm_in(storage, campaign, "beat-2")("portrait", of="The Grey Cog")["status"] == "painting"
    assert dm_in(storage, campaign, "beat-3")("paint_scene", brief="The gate.")["status"] == "painting"

    refused = dm_in(storage, campaign, "beat-4")("paint_scene", brief="The tower.")
    assert refused["error"] == images.PAID_USED_UP.format(limit=3), refused
    assert refused["hint"] == images.PAID_USED_UP_HINT, "the DM narrates around it"
    assert len(storage.campaign_images.list(campaign.id)) == 3, "nothing asked of the painter"

    later = images.now() + timedelta(hours=24, minutes=1)
    monkeypatch.setattr(images, "now", lambda: later)
    assert dm_in(storage, campaign, "beat-5")("paint_scene", brief="The tower.")["status"] == "painting", "a day on"


def test_a_failed_painting_counts_against_the_limit(storage, campaign, services, providers):
    """The provider may have charged for it, and a loop of failures mustn't be free."""
    paid(storage, campaign)
    set_play_settings(storage, campaign.id, {"paid_images_per_day": 1})
    providers[Job.IMAGE_SCENE] = Broken()
    row = dm_in(storage, campaign, "beat-1")("paint_scene", brief="The bridge.")
    assert paint(services, row["image_id"]).status == "failed"
    assert "error" in dm_in(storage, campaign, "beat-2")("paint_scene", brief="The bridge.")


def test_free_pictures_have_no_limit(storage, campaign, registries, garrek):
    set_play_settings(storage, campaign.id, {"paid_images_per_day": 1})
    choose(storage, Job.IMAGE_SCENE, "local-painter", "sdxl-local")
    host = ToolHost(storage, lambda: SeededRng(1), image_paid=chosen_is_paid(storage, registries), catalogs=over(PlayReference()))
    for beat in ("beat-1", "beat-2", "beat-3"):
        for _ in range(3):
            assert host.call(campaign.id, beat, "paint_scene", {"brief": "The bridge."})["status"] == "painting"
    assert host.call(campaign.id, "beat-4", "portrait", {"of": "Garrek"})["portrait"]["kind"] == "traits"
    paid(storage, campaign)
    choose(storage, Job.IMAGE_SCENE, "replicate")
    assert host.call(campaign.id, "beat-4", "paint_scene", {"brief": "The bridge."})["status"] == "painting"
    assert "error" in host.call(campaign.id, "beat-5", "paint_scene", {"brief": "The bridge."}), "only paid count"


def test_the_dm_paints_at_most_two_paid_scenes_a_beat(storage, campaign):
    paid(storage, campaign)
    in_beat = dm_in(storage, campaign, "beat-1")
    assert in_beat("paint_scene", brief="The bridge.")["status"] == "painting"
    assert in_beat("paint_scene", brief="The gate.")["status"] == "painting"
    refused = in_beat("paint_scene", brief="The tower.")
    assert (refused["error"], refused["hint"]) == (images.BEAT_SCENES.format(n=2), images.BEAT_HINT)
    assert dm_in(storage, campaign, "beat-2")("paint_scene", brief="The tower.")["status"] == "painting"


def test_the_dm_paints_a_subject_once_a_beat(storage, campaign, cog, garrek):
    paid(storage, campaign)
    portrait_job(storage, "replicate")
    in_beat = dm_in(storage, campaign, "beat-1")
    assert in_beat("portrait", of="The Grey Cog")["status"] == "painting"
    refused = in_beat("portrait", of="The Grey Cog", description="the cog again, at sea")
    assert (refused["error"], refused["hint"]) == (images.BEAT_SUBJECT.format(name="The Grey Cog"), images.BEAT_HINT)
    assert in_beat("portrait", of="Garrek")["status"] == "painting", "another subject is its own"
    assert in_beat("paint_scene", brief="The cog at sea.")["status"] == "painting", "and scenes are counted apart"
    assert dm_in(storage, campaign, "beat-2")("portrait", of="The Grey Cog")["status"] == "painting"


def test_a_batch_is_held_to_the_beats_limit_step_by_step(storage, campaign):
    paid(storage, campaign)
    steps = [{"tool": "paint_scene", "args": {"brief": f"Scene {n}."}} for n in range(5)]
    answered = dm_in(storage, campaign, "beat-1")("batch", steps=steps)
    assert len(storage.campaign_images.list(campaign.id, kind="scene")) == 2, answered


def test_paint_this_scene_counts_against_the_limit_and_asks_no_brief_past_it(storage, campaign, services):
    paid(storage, campaign)
    set_play_settings(storage, campaign.id, {"paid_images_per_day": 4})
    storage.story.append(campaign.id, None, "dm_text", {"text": "Rain on the bridge."})
    briefs = []
    side = FakeDM([], side_handler=lambda prompt: briefs.append(prompt) or "A brief.")
    services.side = lambda campaign_id: (side, BackendChoice("fake"))

    async def scene():
        return await images.paint_this_scene(services, campaign.id)

    for _ in range(3):  # a seat's request is held to the day's limit only, never to the DM's for a beat
        assert asyncio.run(scene()).kind == "scene"
    assert dm_in(storage, campaign, "beat-1")("paint_scene", brief="The bridge.")["status"] == "painting"

    with pytest.raises(images.PaidUsedUp) as refused:
        asyncio.run(scene())
    assert (refused.value.message, refused.value.hint) == (images.PAID_USED_UP.format(limit=4), images.PAID_USED_UP_HINT)
    assert len(briefs) == 3, "no side pass for a picture that won't be painted"


def test_banners_are_not_held_to_the_tables_limit(storage, campaign, services):
    """An organiser's banner is painted outside play, one at a time, and never by a seat or the DM."""
    paid(storage, campaign)
    set_play_settings(storage, campaign.id, {"paid_images_per_day": 1})
    assert dm_in(storage, campaign, "beat-1")("paint_scene", brief="The bridge.")["status"] == "painting"

    async def again():
        return banners.paint_again(services, campaign.id, "Greyhawk")

    assert asyncio.run(again()).kind == "banner"


# ----- NPC portraits (DEL-248) -----


def npc_job(storage, provider, pc=None):
    choices = {"image.npc_portrait": {"provider": provider, "model": None, "effort": None}}
    if pc:
        choices["image.portrait"] = {"provider": pc, "model": None, "effort": None}
    storage.settings.save({"choices": choices})


def test_an_npc_is_drawn_when_made_with_portraitgen_by_default(storage, campaign, call):
    """DEL-248: an NPC was drawn only when the DM asked. Introduced or made, it gets portraitgen's portrait at once,
    whatever paints the PCs: their painter isn't the NPCs' default."""
    npc_job(storage, "portraitgen", pc="replicate")
    paid(storage, campaign)
    tira = call("introduce_npc", race="human", gender="female", description="innkeeper")
    assert tira["sheet"]["portrait"]["kind"] == "traits" and "portrait_painting" not in tira
    storage.settings.save({})  # nothing chosen: portraitgen too
    guard = call("create_character", name="Brom", kind="npc", sheet={"race": "Dwarf"})
    assert guard["sheet"]["portrait"]["kind"] == "traits"
    pc = call("create_character", name="Garrek", sheet={"race": "Dwarf", "cls": "Fighter", "hp_max": 9})
    assert pc["sheet"]["portrait"] is None, "a PC is drawn as before: when the DM asks"
    assert storage.campaign_images.list(campaign.id) == [], "nothing painted"


def test_no_portrait_leaves_an_npc_without_one_and_the_tool_says_so(storage, campaign, call):
    npc_job(storage, "none")
    tira = call("introduce_npc", race="human", gender="female")
    assert tira["sheet"]["portrait"] is None
    refused = call("portrait", of=tira["name"], description="a tall woman")
    assert refused["error"] == "NPC portraits are off: Preferences give NPCs no portrait."
    assert storage.characters.get(tira["id"]).sheet.portrait is None


def test_an_npc_painter_of_its_own_paints_npcs_and_never_the_pcs(
    storage, campaign, call, garrek, services, providers
):
    """With a paid painter for NPCs and paid images on, an NPC is painted by the NPC job; the PCs' stays portraitgen."""
    npc_job(storage, "replicate", pc="portraitgen")
    paid(storage, campaign)
    providers[Job.IMAGE_NPC_PORTRAIT] = painter = Painter()
    tira = call("introduce_npc", race="human", gender="female")
    assert tira["portrait_painting"]["status"] == "painting" and tira["sheet"]["portrait"] is None
    (row,) = storage.campaign_images.list(campaign.id)
    assert paint(services, row.id).status == "done"
    assert painter.requests[0].job is Job.IMAGE_NPC_PORTRAIT
    assert storage.characters.get(tira["id"]).sheet.portrait == ImagePortrait(row.id)
    assert call("portrait", of="Garrek")["portrait"]["kind"] == "traits", "the PCs' painter is portraitgen"


def test_a_paid_npc_painter_with_paid_images_off_draws_portraitgen(storage, campaign, call):
    npc_job(storage, "replicate")
    paid(storage, campaign, on=False)
    tira = call("introduce_npc", race="human", gender="female")
    assert tira["sheet"]["portrait"]["kind"] == "traits" and storage.campaign_images.list(campaign.id) == []


def test_an_npcs_portrait_job_is_its_own(storage, campaign, garrek):
    npc = storage.characters.create(campaign.id, "Tira", kind="npc")
    assert images.portrait_job(npc) is Job.IMAGE_NPC_PORTRAIT and images.portrait_job(garrek) is Job.IMAGE_PORTRAIT


# ----- portraitgen's styles in Preferences (DEL-252) -----


def test_portraitgen_offers_its_styles_as_models():
    from delve.play.portraits import PORTRAIT_STYLES

    assert PORTRAITGEN_CAPABILITIES.models == PORTRAIT_STYLES
    assert PORTRAITGEN_CAPABILITIES.default_model == "illustrated"
    assert PORTRAITGEN_CAPABILITIES.model_info["inkwash"].label == "Inkwash"
    assert not any(info.paid for info in PORTRAITGEN_CAPABILITIES.model_info.values())


def test_a_campaigns_style_is_its_own_else_preferences_for_pcs_and_npcs(storage, campaign):
    """DEL-252: Preferences pick portraitgen's style for PCs and for NPCs apart; a campaign that chose a style of its
    own draws both in it; one that chose none (null, the default) follows Preferences; a painter that isn't portraitgen
    leaves its free portraits illustrated."""
    assert images.portrait_style(storage, campaign.id) == "illustrated", "nothing chosen anywhere"
    storage.settings.save({"choices": {
        "image.portrait": {"provider": "portraitgen", "model": "painterly", "effort": None},
        "image.npc_portrait": {"provider": "portraitgen", "model": "inkwash", "effort": None},
    }})  # fmt: skip
    assert images.portrait_style(storage, campaign.id, Job.IMAGE_PORTRAIT) == "painterly"
    assert images.portrait_style(storage, campaign.id, Job.IMAGE_NPC_PORTRAIT) == "inkwash"
    set_play_settings(storage, campaign.id, {"portrait_style": "anime"})
    assert images.portrait_style(storage, campaign.id, Job.IMAGE_NPC_PORTRAIT) == "anime"
    set_play_settings(storage, campaign.id, {"portrait_style": None})
    assert images.portrait_style(storage, campaign.id, Job.IMAGE_PORTRAIT) == "painterly", "back to Preferences"
    storage.settings.save({"choices": {"image.portrait": {"provider": "replicate", "model": "x", "effort": None}}})
    assert images.portrait_style(storage, campaign.id, Job.IMAGE_PORTRAIT) == "illustrated"
