"""A free, offline image provider for tests and development."""

from __future__ import annotations

import base64

from delve.domain.backends import ProviderCapabilities
from delve.domain.settings import Job
from delve.images.provider import ImageFile, ImageRequest, ImageResult, PortraitTraits

FAKE_IMAGES_CAPABILITIES = ProviderCapabilities(
    id="fake-images",
    title="Fake images",
    jobs=frozenset({Job.IMAGE_PORTRAIT, Job.IMAGE_NPC_PORTRAIT, Job.IMAGE_SCENE, Job.IMAGE_POSSESSION}),
)

# A 1×1 PNG of one slate-blue pixel, opaque, so a picture the fake paints shows where it is drawn (a banner fills its
# frame with it in the browser checks).
PIXEL_PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR42mPwis0GAAIHAROip/cGAAAAAElFTkSuQmCC")


class FakeImages:
    """Portraits come back as traits for portraitgen with the prompt as their request; scenes and possessions as a
    1×1 PNG."""

    capabilities = FAKE_IMAGES_CAPABILITIES

    async def generate(self, req: ImageRequest) -> ImageResult:
        if req.job not in self.capabilities.jobs:
            raise ValueError(f"'{req.job}' is not an image job")
        if req.job in (Job.IMAGE_PORTRAIT, Job.IMAGE_NPC_PORTRAIT):
            return PortraitTraits(req.prompt)
        return ImageFile(PIXEL_PNG, "image/png")
