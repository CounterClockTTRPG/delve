"""A generated module's pictures, in the job (DEL-347): an option, within a limit, never in the module's way."""

import asyncio
import json

from delve.conversions.runner import start_generate, wait
from delve.domain.settings import BackendChoice, Job
from delve.images.fake import PIXEL_PNG, FakeImages
from delve.images.provider import ImageFile
from delve.modules.books.pictures import PICTURE_NOT_PAINTED
from delve.modules.source import load_source
from tests.conversions.test_generate_in_steps import CampaignClaude
from tests.conversions.test_runner import Claude, _services, storage  # noqa: F401 (the fixture)

GRIK = {"subject": "Grik", "kind": "person", "brief": "A wiry kobold.", "description": "Grik: when met."}
CAVES = {"subject": "The caves", "kind": "place", "brief": "A dark cave mouth.", "description": "The caves: at first."}


class PictureClaude(Claude):
    def __call__(self, prompt: str) -> str:
        if prompt.startswith("You choose the pictures"):
            self.seen.append("pictures")
            return json.dumps({"pictures": [GRIK, CAVES]})
        return super().__call__(prompt)


class Painter(FakeImages):
    def __init__(self, fail: bool = False) -> None:
        self.asked = []
        self.fail = fail

    async def generate(self, req):
        self.asked.append(req)
        if self.fail:
            raise RuntimeError("no credit")
        return ImageFile(PIXEL_PNG, "image/png")


def _set_up(storage, painter=None, *, paid=False):  # noqa: F811
    claude = PictureClaude()
    services, _, events = _services(storage, claude)
    painter = painter or Painter()
    services.images = lambda job: (painter, BackendChoice("fake-images", None))
    services.image_paid = lambda job: paid
    return services, claude, painter, events


def _run(services, **options):
    async def scenario():
        started = await start_generate(services, "Kobolds.", "ready", scale="module", **options)
        return await wait(services, started.id)

    return asyncio.run(scenario())


def test_the_pictures_are_the_modules_handouts(storage):  # noqa: F811
    services, _, painter, events = _set_up(storage)
    done = _run(services, pictures=4, owner=True)
    assert done.status == "done", done.error
    source = load_source(storage, done.module_id)
    assert [(a.id, a.audience, a.description) for a in source.player_images()] == [
        ("grik", "player", GRIK["description"]),
        ("the-caves", "player", CAVES["description"]),
    ]
    assert storage.blobs.get(source.attachments[0].sha256) == PIXEL_PNG
    assert sorted((r.job, r.prompt, r.aspect) for r in painter.asked) == [
        (Job.IMAGE_SCENE, "A dark cave mouth.", ""),
        (Job.IMAGE_SCENE, "A wiry kobold.", "1:1"),
    ]
    steps = [d["steps"] for k, d in events if k == "conversion" and d["step"] == "painting"]
    assert steps and all(s == {"index": 3, "count": 3} for s in steps)


def test_without_the_option_nothing_is_chosen_or_painted(storage):  # noqa: F811
    services, claude, painter, events = _set_up(storage)
    done = _run(services)
    assert done.status == "done", done.error
    assert "pictures" not in claude.seen and painter.asked == []
    assert load_source(storage, done.module_id).attachments == []
    assert done.target == {"scale": "module"}
    assert [d["steps"]["count"] for k, d in events if k == "conversion"][-1] == 2


def test_a_paid_model_is_the_owners_even_when_it_became_paid_in_the_queue(storage):  # noqa: F811
    services, claude, painter, _ = _set_up(storage, paid=True)
    done = _run(services, pictures=4, owner=False)
    assert done.status == "done", done.error
    assert painter.asked == [] and "pictures" not in claude.seen
    assert [w["code"] for w in done.warnings if w["code"] == PICTURE_NOT_PAINTED] == [PICTURE_NOT_PAINTED]


def test_the_owner_may_paint_with_a_paid_model(storage):  # noqa: F811
    services, _, painter, _ = _set_up(storage, paid=True)
    assert _run(services, pictures=4, owner=True).status == "done"
    assert len(painter.asked) == 2


def test_a_painter_that_fails_costs_only_the_pictures(storage):  # noqa: F811
    services, _, _, _ = _set_up(storage, Painter(fail=True))
    done = _run(services, pictures=4, owner=True)
    assert done.status == "done", done.error
    assert load_source(storage, done.module_id).attachments == []
    failed = [w for w in done.warnings if w["code"] == PICTURE_NOT_PAINTED]
    assert len(failed) == 2 and "no credit" in failed[0]["message"]


def test_a_queued_request_keeps_its_pictures(storage):  # noqa: F811
    services, _, _, _ = _set_up(storage)
    storage.conversions.set_queue_paused(True)
    queued = asyncio.run(start_generate(services, "Kobolds.", "ready", scale="module", pictures=5, owner=True))
    assert queued.status == "queued"
    assert (queued.target["pictures"], queued.target["owner"]) == (5, True)


def test_too_many_pictures_are_refused(storage):  # noqa: F811
    services, _, _, _ = _set_up(storage)
    try:
        asyncio.run(start_generate(services, "Kobolds.", "ready", pictures=13))
    except ValueError as error:
        assert "at most 12" in str(error)
    else:
        raise AssertionError("13 pictures started")


def test_a_campaign_gets_its_pictures_too(storage):  # noqa: F811
    class Campaign(CampaignClaude):
        def __call__(self, prompt: str) -> str:
            if prompt.startswith("You choose the pictures"):
                return json.dumps({"pictures": [GRIK]})
            return super().__call__(prompt)

    services, _, events = _services(storage, Campaign())
    painter = Painter()
    services.images = lambda job: (painter, BackendChoice("fake-images", None))
    services.image_paid = lambda job: False

    async def scenario():
        started = await start_generate(services, "A vast dungeon.", "ready", scale="campaign", pictures=2)
        return await wait(services, started.id)

    done = asyncio.run(scenario())
    assert done.status == "done", done.error
    assert [a.id for a in load_source(storage, done.module_id).player_images()] == ["grik"]
    assert {"index": 6, "count": 6} in [d["steps"] for k, d in events if k == "conversion" and d["step"] == "painting"]
