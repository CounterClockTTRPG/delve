"""The image provider interface: an image from a prompt, as a file or as portrait traits to render (spec §5.2)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from delve.domain.backends import ProviderCapabilities
from delve.domain.settings import BackendChoice, Job


@dataclass(frozen=True)
class ProviderJob:
    """A painting as the provider queues it (DEL-138): its job's id, and its place in the provider's queue while it
    waits there (1 is next; None once it runs, or when the provider doesn't say)."""

    id: str
    position: int | None = None


@dataclass(frozen=True)
class ImageRequest:
    """`job` is one of the IMAGE_* jobs. `tone` is the campaign's tone (a play setting, or a custom tone's own words),
    for the provider's style; `style` is the install's image style (`delve.domain.image_styles.style_text`), which
    replaces the tone's when it isn't empty. `aspect` is the ratio wanted ("21:9"); empty is the job's own
    (`replicate.ASPECT_RATIOS`).

    A provider with a queue of its own (assetgen) tells `watch` its job as soon as it has one, and again whenever its
    place in the queue changes; given `follow`, the id of a job from an earlier start, it follows that job instead of
    asking for the picture again. A provider without a queue leaves both alone."""

    job: Job
    prompt: str
    choice: BackendChoice
    tone: str = ""
    style: str = ""
    aspect: str = ""
    follow: str = ""
    watch: Callable[[ProviderJob], None] | None = field(default=None, compare=False, repr=False)


@dataclass(frozen=True)
class ImageFile:
    data: bytes
    mime: str


@dataclass(frozen=True)
class PortraitTraits:
    """A portrait the browser renders with portraitgen: its plain-language request."""

    describe: str


ImageResult = ImageFile | PortraitTraits


class ImageProvider(Protocol):
    capabilities: ProviderCapabilities

    async def generate(self, req: ImageRequest) -> ImageResult: ...
