"""Painting a module's banner (DEL-123), without the web: it lands, fails with the provider's reason, is dropped when
the banner went meanwhile, needs the owner for a paid model, and a painting a stopped Delve cut short fails at start."""

import asyncio
from dataclasses import dataclass, field

import pytest

from delve.config import Config
from delve.domain.settings import BackendChoice
from delve.images.provider import ImageFile
from delve.play import module_banners
from delve.play.context import PlayError
from delve.storage import open_storage


@pytest.fixture
def storage(tmp_path):
    opened = open_storage(Config(data_dir=tmp_path))
    yield opened
    opened.close()


class Painter:
    def __init__(self, answer=None, error=None):
        self.answer, self.error, self.asked = answer, error, []

    async def generate(self, request):
        self.asked.append(request)
        if self.error:
            raise self.error
        return self.answer


@dataclass
class Services:
    storage: object
    painter: Painter
    paid: bool = False
    published: list = field(default_factory=list)

    def images(self, job):
        return self.painter, BackendChoice("fake")

    def image_paid(self, job):
        return self.paid

    def publish(self, kind, data, **where):
        self.published.append((kind, data))


def module(storage):
    made = storage.modules.create("The Crypt", {"summary": "A crypt under the chapel.", "setting": "Greyhawk"})
    return made.id


def test_a_painted_banner_lands_at_21_9_from_a_player_safe_brief(storage):
    mid = module(storage)
    services = Services(storage, Painter(ImageFile(b"\x89PNG painted", "image/png")))
    prompt = module_banners.module_brief(storage.modules.get(mid), "at dusk")
    assert "The Crypt" in prompt and "Greyhawk" in prompt and "A crypt under the chapel." in prompt and "dusk" in prompt
    storage.modules.banner_painting(mid, prompt)
    landed = asyncio.run(module_banners.painted(services, mid, prompt))
    assert landed.banner.source == "painted" and landed.banner.status is None
    assert services.painter.asked[0].aspect == "21:9"
    assert services.painter.asked[0].style == "", "no image style chosen"


def test_a_banner_takes_the_install_s_image_style(storage):
    mid = module(storage)
    storage.settings.save({"image_style": {"preset": "woodcut"}})
    services = Services(storage, Painter(ImageFile(b"\x89PNG painted", "image/png")))
    prompt = module_banners.module_brief(storage.modules.get(mid), "")
    storage.modules.banner_painting(mid, prompt)
    asyncio.run(module_banners.painted(services, mid, prompt))
    assert services.painter.asked[0].style.startswith("High-contrast black-ink woodcut engraving")
    assert services.published == [("modules", {"id": mid})]


def test_a_failed_painting_keeps_the_reason_and_the_old_picture(storage):
    mid = module(storage)
    sha = storage.blobs.put(b"old", "image/webp")
    storage.modules.set_banner(mid, sha, "image/webp", "uploaded")
    storage.modules.banner_painting(mid, "brief")
    failed = asyncio.run(module_banners.painted(Services(storage, Painter(error=RuntimeError("out of credit"))), mid, "brief"))
    assert failed.banner.status == "failed" and failed.banner.error == "out of credit" and failed.banner.blob == sha


def test_a_banner_removed_meanwhile_stays_removed(storage):
    mid = module(storage)
    storage.modules.banner_painting(mid, "brief")
    storage.modules.clear_banner(mid)
    ended = asyncio.run(module_banners.painted(Services(storage, Painter(ImageFile(b"x", "image/png"))), mid, "brief"))
    assert ended.banner is None


def test_a_paid_model_paints_for_the_owner_only(storage):
    mid = module(storage)
    services = Services(storage, Painter(ImageFile(b"x", "image/png")), paid=True)
    with pytest.raises(PlayError, match="Only the owner"):
        module_banners.paint(services, mid, owner=False)


def test_a_painting_cut_short_fails_at_the_next_start(storage):
    mid = module(storage)
    storage.modules.banner_painting(mid, "brief")
    assert module_banners.interrupted(storage) == [mid]
    assert storage.modules.get(mid).banner.status == "failed"
