"""An NPC's line (portraits plan Task 7; design, owner decision 5): `say` gives one quoted line of one NPC, with the
mood it carries. Its `said` passes the players' allow-list (`redact.player_view`), and the table puts it in the story
after the tool's row as a `say` entry for everyone, like narration: the speaker's id, name and portrait, the mood and
the text, and nothing else of the NPC's sheet. What only some characters hear stays `tell`'s."""

from __future__ import annotations

import re
from typing import Any

from delve.dm.tools.schema import ToolSpec, params, string, tool
from delve.domain.campaigns import Character
from delve.domain.settings import Job
from delve.images.none import NO_PORTRAIT
from delve.play import characters as roster
from delve.play.context import CampaignContext, NotFound, PlayError
from delve.play.seats import TABLE_RIGHTS
from delve.storage.interfaces import Storage

SPECS: list[ToolSpec] = []
SAY = "say"
NEUTRAL = "neutral"
MOODS = (
    NEUTRAL,
    "smile",
    "laugh",
    "wink",
    "sneer",
    "angry",
    "afraid",
    "upset",
    "surprised",
    "sigh",
    "thinking",
    "shout",
    "cry",
    "disgusted",
    "nod",
    "shake",
)
"""The moods a line may carry: each a portraitgen emote but `neutral`, which is talk only."""


def mood_of(mood: Any) -> str:
    """`mood` when it is one of `MOODS` (ignoring case and outer spaces); `neutral` for anything else."""
    wanted = mood.strip().casefold() if isinstance(mood, str) else ""
    return wanted if wanted in MOODS else NEUTRAL


def handed_to_dm(storage: Storage, campaign_id: str, beat_id: str, character: Character) -> bool:
    """Whether the DM may give `character`, a PC, its words in this beat (table voice and fixes Task E3): the beat's
    submissions hand it over. An act names it, by its exact name ("you can decide what Garrek says"), and is for it:
    it covers it, or comes from the seat that plays it, or from the host or a co-host for a PC nobody claimed (the host
    plays those). Or an `in_character` fallback covers it. Outside a beat, nobody hands anything: solo play's PCs,
    which nobody claims, still speak for themselves. A fight's beat is `<beat>/<combat id>`."""
    if character.kind != "pc":
        return False
    beat = storage.beats.get(beat_id.split("/", 1)[0])
    if beat is None or beat.campaign_id != campaign_id:
        return False
    named = re.compile(rf"(?<![\w']){re.escape(character.name)}(?![\w'])")
    for submission in beat.submissions:
        covers = character.id in (submission.get("characters") or [])
        kind = submission.get("kind")
        if kind == "act" and named.search(submission.get("text") or ""):
            handed = covers or _plays(storage, submission.get("seat_id"), character)
        else:
            handed = covers and kind == "fallback" and _fallback(storage, campaign_id) == "in_character"
        if handed:
            return True
    return False


def _plays(storage: Storage, seat_id: str | None, character: Character) -> bool:
    """Whether the seat plays the PC: its own, or one nobody claimed when it hosts."""
    if seat_id is None:
        return False
    if character.controller_id is not None:
        return character.controller_id == seat_id
    seat = storage.seats.get(seat_id)
    return seat is not None and seat.campaign_id == character.campaign_id and seat.role in TABLE_RIGHTS


def _fallback(storage: Storage, campaign_id: str) -> str:
    from delve.play.table import play_settings  # the table imports this module

    return play_settings(storage, campaign_id)["fallback"]


def said_line(npc: Character, text: str, mood: str = NEUTRAL) -> dict[str, Any]:
    """The `said` of `npc`'s line: `{speaker: {id, name, portrait}, mood, text}`."""
    portrait = npc.sheet.portrait.to_dict() if npc.sheet.portrait is not None else None
    return {"speaker": {"id": npc.id, "name": npc.name, "portrait": portrait}, "mood": mood_of(mood), "text": text}


@tool(
    SPECS,
    SAY,
    params(
        "npc",
        "text",
        npc=string("The NPC who speaks, by id or exact name."),
        text=string("The line, the NPC's own words, without quotes or narration.", minLength=1),
        mood=string(f"The mood the line carries, one of: {', '.join(MOODS)}. Anything else is neutral."),
    ),
    mutates=False,
)
def say(ctx: CampaignContext, npc: str, text: str, mood: str = NEUTRAL) -> dict[str, Any]:
    """Give one quoted line of an NPC, with the mood it carries: it appears in the story after your narration so far,
    as its own entry beside the NPC's portrait, which talks and then shows the mood. Every character at the table
    hears it. One line per call; narration stays in your reply, and a line only some characters hear is `tell`'s. A
    player character speaks for itself, unless it is yours this beat: its player names it in their act and leaves its
    words to you, or the beat's fallback has you play it in character. An NPC without a portrait gets one the first
    time it speaks: portraitgen's, unless Preferences give NPCs no portrait."""
    if not text.strip():
        raise PlayError("The line is empty.", "Give the NPC's words, one line per call.")
    try:
        speaker = roster.get(ctx, npc)
    except NotFound as unknown:
        npcs = [c for c in unknown.candidates if c.get("kind") == "npc"]
        raise NotFound(
            unknown.message, npcs, "Name an NPC of the campaign by id or exact name, or introduce_npc first."
        ) from unknown
    if speaker.kind != "npc" and not handed_to_dm(ctx.storage, ctx.campaign_id, ctx.beat, speaker):
        raise PlayError(
            f"{speaker.name} is a player character.",
            "say gives an NPC's line; a player character speaks for itself, unless its player names it in their act "
            "and leaves its words to you.",
        )
    if speaker.kind == "npc" and speaker.sheet.portrait is None:
        speaker = _drawn(ctx, speaker)
    return {"said": said_line(speaker, text, mood)}


def _drawn(ctx: CampaignContext, npc: Character) -> Character:
    """The NPC with portraitgen's portrait, free and at once (DEL-41): one made before NPCs were drawn when made
    (DEL-248) spoke beside its initial. Never a painting: `say` changes nothing of the game, so nothing would start
    one; with No portrait for NPCs, the initial stays."""
    # Here, not at the top: delve.play.images reaches the table, whose batch reaches these tools again.
    from delve.play import images

    if images.portrait_provider(ctx.storage, Job.IMAGE_NPC_PORTRAIT) == NO_PORTRAIT:
        return npc
    images.free_portrait(ctx, npc, images.describe(npc))
    return ctx.storage.characters.get(npc.id) or npc
