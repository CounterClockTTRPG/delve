import asyncio

import pytest

from delve.domain.settings import BackendChoice, Job
from delve.images.fake import FAKE_IMAGES_CAPABILITIES, FakeImages
from delve.images.provider import ImageFile, ImageRequest, PortraitTraits

CHOICE = BackendChoice("fake-images")


def generate(job, prompt="a stout old male dwarf"):
    return asyncio.run(FakeImages().generate(ImageRequest(job=job, prompt=prompt, choice=CHOICE)))


def test_capabilities():
    caps = FakeImages().capabilities
    assert caps is FAKE_IMAGES_CAPABILITIES
    assert caps.id == "fake-images"
    assert caps.jobs == frozenset({Job.IMAGE_PORTRAIT, Job.IMAGE_NPC_PORTRAIT, Job.IMAGE_SCENE, Job.IMAGE_POSSESSION})


def test_fake_images_portrait_returns_traits():
    assert generate(Job.IMAGE_PORTRAIT) == PortraitTraits("a stout old male dwarf")


@pytest.mark.parametrize("job", [Job.IMAGE_SCENE, Job.IMAGE_POSSESSION])
def test_fake_images_scene_returns_png(job):
    result = generate(job, "a torchlit crypt")
    assert isinstance(result, ImageFile)
    assert result.mime == "image/png"
    assert result.data.startswith(b"\x89PNG")


def test_fake_images_refuses_non_image_job():
    with pytest.raises(ValueError, match="dm"):
        generate(Job.DM)
