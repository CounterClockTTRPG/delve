"""No portrait, for NPCs (DEL-248): a choice in Preferences that leaves an NPC with its initial. It is never asked
to paint: the portrait tool and an NPC's making read the choice and draw nothing."""

from __future__ import annotations

from delve.domain.backends import ProviderCapabilities
from delve.domain.settings import Job
from delve.images.provider import ImageRequest, ImageResult

NO_PORTRAIT = "none"
NPC_PORTRAITS_OFF = "NPC portraits are off: Preferences give NPCs no portrait."
"""What the DM's portrait tool and the Repaint portrait button (DEL-135) say when NPCs get none."""

NO_PORTRAIT_CAPABILITIES = ProviderCapabilities(
    id=NO_PORTRAIT, title="No portrait", jobs=frozenset({Job.IMAGE_NPC_PORTRAIT})
)


class NoPortraits:
    """Paints nothing: a request that reaches it is a mistake."""

    capabilities = NO_PORTRAIT_CAPABILITIES

    async def generate(self, req: ImageRequest) -> ImageResult:
        raise ValueError("NPC portraits are off: nothing paints them")
