"""Showing the module's images to the players (plan 3 Task 8, spec §7.5): `show_image` puts a player image of the
revision the campaign pinned in the story, after its tool row. It is the one tool whose output passes the players'
allow-list (`redact.player_view`), and only for an image whose attachment is for the players: a DM-only attachment, a
PDF or an id the revision doesn't hold is refused, and the players' image route answers 404 for them."""

from __future__ import annotations

from typing import Any

from delve.dm.tools.redact import SHOW_IMAGE
from delve.dm.tools.schema import ToolSpec, params, string, tool
from delve.modules.source import ModuleSource, pinned_source
from delve.play.context import CampaignContext, NotFound, PlayError

SPECS: list[ToolSpec] = []

DM_ONLY = "That image is for the DM only."
NAME_ONE = "Name one of module.images by its id."


def _pinned(ctx: CampaignContext) -> ModuleSource:
    """The source of the revision the campaign pinned."""
    campaign = ctx.storage.campaigns.get(ctx.campaign_id)
    source = pinned_source(ctx.storage, campaign.module_id, campaign.revision) if campaign else None
    return source if source is not None else ModuleSource()


def image_list(source: ModuleSource) -> list[dict[str, str]]:
    """The player images as the DM is shown them: `{id, description}`."""
    return [{"id": a.id, "description": a.description} for a in source.player_images()]


@tool(
    SPECS,
    SHOW_IMAGE,
    params(
        "asset",
        asset=string("The image's id, as session_primer's module.images lists them."),
        caption=string("A line under the image, in the characters' words; none by default."),
    ),
    mutates=True,
    areas=(),
)
def show_image(ctx: CampaignContext, asset: str, caption: str = "") -> dict[str, Any]:
    """Show the players one of the module's player images (session_primer lists them in module.images, each with a
    description of what it shows and when it fits), in the story after your narration. Show it when the characters
    see what it shows, once, at that moment. DM-only images and PDFs can't be shown: never describe what a DM-only
    image shows."""
    source = _pinned(ctx)
    found = source.attachment(asset)
    if found is None:
        raise NotFound(f"No image '{asset}' in this module.", image_list(source), hint=NAME_ONE)
    if found.audience != "player":
        raise PlayError(DM_ONLY)
    if not found.is_image:
        raise PlayError("That attachment is a PDF, not an image.", NAME_ONE)
    ctx.log("image_shown", asset=found.id, caption=caption)
    return {"image": {"asset": found.id, "caption": caption}}
