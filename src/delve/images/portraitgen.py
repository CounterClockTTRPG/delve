"""portraitgen, free portraits (spec §5.2): the server keeps only a description, and the browser draws it."""

from __future__ import annotations

from delve.domain.backends import ModelInfo, ProviderCapabilities
from delve.domain.settings import Job
from delve.images.provider import ImageRequest, ImageResult, PortraitTraits
from delve.play.portraits import PORTRAIT_STYLES

PORTRAITGEN = "portraitgen"

# Its render styles are its models (DEL-252), chosen apart for PCs and NPCs: what Preferences pick draws a campaign's
# portraits unless the campaign chooses a style of its own. `illustrated`, the first, is the look before styles.
PORTRAITGEN_CAPABILITIES = ProviderCapabilities(
    id=PORTRAITGEN,
    title="portraitgen (free)",
    jobs=frozenset({Job.IMAGE_PORTRAIT, Job.IMAGE_NPC_PORTRAIT}),
    models=PORTRAIT_STYLES,
    default_model=PORTRAIT_STYLES[0],
    model_info={style: ModelInfo(style.capitalize(), PORTRAITGEN, None, False) for style in PORTRAIT_STYLES},
)


class PortraitgenImages:
    """Portraits only, since portraitgen draws only people: the request's description, as traits to render."""

    capabilities = PORTRAITGEN_CAPABILITIES

    async def generate(self, req: ImageRequest) -> ImageResult:
        if req.job not in (Job.IMAGE_PORTRAIT, Job.IMAGE_NPC_PORTRAIT):
            raise ValueError("portraitgen draws only portraits")
        return PortraitTraits(req.prompt)
