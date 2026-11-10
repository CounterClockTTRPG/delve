"""The DM's pictures (plan 6 Task 10, spec §5.2): a portrait of a character or a possession, and a painted scene.

A portrait with Preferences' portrait job on portraitgen, or with paid images off and a model that costs money, is
portraitgen's: a description and a seed, set at once. Anything else is a painting: the tool answers `{image_id,
status: "painting"}` at once, and the picture is painted in the background after the call (`delve.play.images`), so
the beat never waits for it. A scene lands in the story when it is done; with `characters`, only their players see
it. The brief is the DM's and never reaches the players: the story gets the image and its caption. A paid picture is
held to the campaign's limit for a day and to the DM's for a beat (`delve.play.images`, DEL-153); the refusal is the
tool's error, with a hint to narrate around it.
"""

from __future__ import annotations

from typing import Any

from delve.dm.tools.schema import ToolSpec, array, params, string, tool
from delve.domain.settings import Job
from delve.domain.world import Possession
from delve.images.none import NPC_PORTRAITS_OFF
from delve.images.portraitgen import PORTRAITGEN
from delve.play import characters as roster
from delve.play import images
from delve.play.audience import for_characters
from delve.play.context import CampaignContext, PlayError

SPECS: list[ToolSpec] = []

PORTRAIT = "portrait"
PAINT_SCENE = "paint_scene"


@tool(
    SPECS,
    PORTRAIT,
    params(
        "of",
        of=string("The character or possession, by id or exact name."),
        description=string(
            'What it looks like, in plain words ("a stout old male dwarf with a braided red beard"); by default, '
            "from the sheet: gender, race and class."
        ),
    ),
    mutates=True,
    areas=("characters",),
)
def portrait(ctx: CampaignContext, of: str, description: str = "") -> dict[str, Any]:
    """Give a character a portrait, or a possession (a mount, a ship, a house) its picture, for the party sidebar
    and the sheets. A character's portrait is free and instant (portraitgen) unless another painter is chosen for
    portraits, and either it is free or the host turned paid images on; then it is painted in the background and this
    answers at once with its image_id. A possession's picture needs paid images, unless its painter is free.
    Describe only what anyone looking at it would see."""
    subject = images.find_subject(ctx, of)
    described = description.strip() or images.describe(subject)
    named = {"id": subject.id, "name": subject.name}
    if isinstance(subject, Possession):
        image = images.request(ctx, "possession", subject.id, described, None)
        return {"image_id": image.id, "status": image.status, "of": named}
    if subject.kind == "npc":  # NPCs have a painter of their own, or none (DEL-248)
        drawn = images.npc_portrait(ctx, subject, described)
        if drawn is None:
            raise PlayError(NPC_PORTRAITS_OFF, "Describe them in words.")
        return {**drawn, "of": named}
    may_paint = images.paid_images(ctx.storage, ctx.campaign_id) or not ctx.image_paid(Job.IMAGE_PORTRAIT)
    if images.portrait_provider(ctx.storage) == PORTRAITGEN or not may_paint:
        return {"portrait": images.free_portrait(ctx, subject, described).to_dict(), "of": named}
    image = images.request(ctx, "portrait", subject.id, described, None)
    return {"image_id": image.id, "status": image.status, "of": named}


@tool(
    SPECS,
    PAINT_SCENE,
    params(
        "brief",
        brief=string(
            "The painter's brief: one paragraph of 60 to 120 words of what the picture shows (subjects, action, "
            "setting, light, mood), with nothing the characters don't see.",
            minLength=1,
        ),
        caption=string("A line under the picture, in the characters' words; none by default."),
        characters=array(
            "The player characters who see it, by id or exact name; everyone by default.", {"type": "string"}
        ),
    ),
    mutates=True,
    areas=(),
)
def paint_scene(ctx: CampaignContext, brief: str, caption: str = "", characters: list[str] = ()) -> dict[str, Any]:
    """Paint a scene: a picture of a moment worth keeping (a vista, a first sight of the dragon), shown in the story
    when it is done, after a while. It needs paid images, which the host turns on; it costs money, so paint rarely:
    at most two a beat, and the campaign has a limit for a day. Refused, tell the scene in words and go on. It answers
    at once with its image_id: go on narrating, never wait for it. With characters, only their players see it."""
    if not brief.strip():
        raise PlayError("Write the painter's brief.")
    ids: list[str] = []
    for ref in characters:
        character = roster.get(ctx, ref)
        if character.kind != "pc":
            raise PlayError(f"{character.name} is not a player character.", "Name the party's characters who see it.")
        if character.id not in ids:
            ids.append(character.id)
    image = images.request(ctx, "scene", None, brief, for_characters(ids) if ids else None, caption)
    return {"image_id": image.id, "status": image.status}
