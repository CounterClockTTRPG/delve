"""Narration for some characters (plan 4 Task 5, spec §7.2, §7.4): `tell` tells some player characters what the others
don't perceive. Its `told` is the one tool output besides `show_image`'s image that passes the players' allow-list
(`redact.player_view`), and the table puts it in the story after the tool's row, as a `dm_text` entry only the seats
that play those characters see."""

from __future__ import annotations

from typing import Any

from delve.dm.tools.redact import TELL
from delve.dm.tools.schema import ToolSpec, array, params, string, tool
from delve.play import characters as roster
from delve.play.context import CampaignContext, PlayError

SPECS: list[ToolSpec] = []


@tool(
    SPECS,
    TELL,
    params(
        "characters",
        "text",
        characters=array(
            "The player characters who perceive it, by id or exact name.",
            {"type": "string"},
            minItems=1,
        ),
        text=string("What they alone perceive, narrated to them as you narrate a reply.", minLength=1),
    ),
    mutates=False,
)
def tell(ctx: CampaignContext, characters: list[str], text: str) -> dict[str, Any]:
    """Tell some player characters what only they perceive: a private vision, what one character alone overhears, a
    split group's scene. Only the players of those characters read it, in the story after your narration so far; the
    others never learn it was said. Your reply's text is what every character at the table perceives, so never put
    there what you tell, and never tell everyone's characters: say it in the reply."""
    ids: list[str] = []
    for ref in characters:
        character = roster.get(ctx, ref)
        if character.kind != "pc":
            raise PlayError(f"{character.name} is not a player character.", "Tell only the party's characters.")
        if character.id not in ids:
            ids.append(character.id)
    return {"told": {"characters": ids, "text": text}}
