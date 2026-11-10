"""The players' view of a tool call (spec §7.5): an allow-list, for plateau 2b's feed.

The feed shows a tool by its name, and whether it was refused. Nothing else of a call is allowed: its inputs are the
DM's words ("level drain wight"), its result carries what the characters don't know (a monster's stat block, a room's
notes, an NPC's story), its rolls are labelled by the DM and some are hidden checks, and a refusal's message echoes the
DM's input. The narration tells the players what their characters perceive. The tools whose `player_visible` is off
don't appear at all. The dice a call rolled are not in its row's view here: the table shows each seat those it may
read (`delve.play.story_dice`, DEL-270).

The two exceptions are `show_image`'s `image`, `{asset, caption}`: the image the DM shows, which the story shows after
the tool's row. The tool answers it only for a player image of the campaign's pinned revision, and the table checks
that again before the story gets it. And `tell`'s `told`, `{characters, text}` (plan 4): what the DM tells some
characters, which the story shows after the tool's row to the seats that play them only, its row too. And `say`'s
`said`, `{speaker: {id, name, portrait}, mood, text}` (portraits plan Task 7): an NPC's line, for everyone, which the
table rebuilds from the campaign's own NPC before the story gets it.

A painted scene (plan 6) is not a tool output: `paint_scene` answers the DM `{image_id, status}`, and its row shows
only its name. The `scene` entry the painting makes later is `scene_view`'s `{image_id, caption}`, never the brief.

`DM_ONLY_KEYS` and `ToolSpec.dm_only_keys` name the keys that are DM-only wherever results are shown: the feed shows
none, and the DM view shows all. The routes a seat reads (plateau 4) leave them out with `strip_for_players`.
"""

from __future__ import annotations

from typing import Any

from delve.dm.tools.say import MOODS, SAY
from delve.dm.tools.schema import ToolSpec
from delve.domain.portrait_traits import TraitsError, checked

__all__ = ["DM_ONLY_KEYS", "SAY", "player_row", "player_view", "scene_view", "strip_for_players"]

DM_ONLY_KEYS = ("dm_only", "secret_exits", "hidden_annotations", "secret_map_exits", "dm_notes")
SHOW_IMAGE = "show_image"
TELL = "tell"


def player_view(spec: ToolSpec, args: dict[str, Any], result: dict[str, Any]) -> dict[str, Any] | None:
    """What the players' feed may show of the call of `spec` with `args` that answered `result`: `{}`, or
    `{"failed": True}` for a refusal, `{"image": {asset, caption}}` for an image shown, `{"told": {characters, text}}`
    for a tell, `{"said": {speaker, mood, text}}` for an NPC's line; None for a DM-only tool."""
    if not spec.player_visible:
        return None
    if "error" in result:
        return {"failed": True}
    if spec.name == TELL:
        told = told_text(result)
        return {"told": told} if told is not None else {}
    if spec.name == SAY:
        said = said_text(result)
        return {"said": said} if said is not None else {}
    image = shown_image(result) if spec.name == SHOW_IMAGE else None
    return {"image": image} if image is not None else {}


def shown_image(result: dict[str, Any]) -> dict[str, str] | None:
    """`show_image`'s `{asset, caption}`, both strings and nothing else; None for anything other."""
    image = result.get("image")
    if not isinstance(image, dict):
        return None
    asset, caption = image.get("asset"), image.get("caption", "")
    if not isinstance(asset, str) or not asset or not isinstance(caption, str):
        return None
    return {"asset": asset, "caption": caption}


def told_text(result: dict[str, Any]) -> dict[str, Any] | None:
    """`tell`'s `{characters, text}`: some character ids and a text, and nothing else; None for anything other."""
    told = result.get("told")
    if not isinstance(told, dict):
        return None
    ids, text = told.get("characters"), told.get("text")
    if not isinstance(ids, list) or not ids or not all(isinstance(i, str) and i for i in ids):
        return None
    if not isinstance(text, str) or not text:
        return None
    return {"characters": list(ids), "text": text}


def said_text(result: dict[str, Any]) -> dict[str, Any] | None:
    """`say`'s `{speaker: {id, name, portrait}, mood, text}`: a speaker with an id and a name, a portrait or None, a
    mood of `MOODS` (`neutral` for any other) and a text, and nothing else; None for anything other."""
    said = result.get("said")
    if not isinstance(said, dict) or not isinstance(said.get("speaker"), dict):
        return None
    speaker, text = said["speaker"], said.get("text")
    sid, name = speaker.get("id"), speaker.get("name")
    if not isinstance(sid, str) or not sid or not isinstance(name, str) or not name:
        return None
    if not isinstance(text, str) or not text:
        return None
    portrait = speaker.get("portrait")
    shown = portrait_view(portrait) if portrait is not None else None
    if portrait is not None and shown is None:
        return None
    mood = said.get("mood")
    return {
        "speaker": {"id": sid, "name": name, "portrait": shown},
        "mood": mood if mood in MOODS else MOODS[0],
        "text": text,
    }


def portrait_view(portrait: Any) -> dict[str, Any] | None:
    """A portrait's own keys: `{kind: "traits", describe, seed}`, with an edited one's `traits` when portraitgen wrote
    them (`portrait_traits.checked`, DEL-238), or `{kind: "image", image_id}`; None for anything other."""
    if not isinstance(portrait, dict):
        return None
    kind = portrait.get("kind")
    keys = ("describe", "seed") if kind == "traits" else ("image_id",) if kind == "image" else None
    if keys is None or not all(isinstance(portrait.get(k), str) for k in keys):
        return None
    view: dict[str, Any] = {"kind": portrait["kind"], **{k: portrait[k] for k in keys}}
    if kind == "traits" and portrait.get("traits") is not None:
        try:
            view["traits"] = checked(portrait["traits"])
        except TraitsError:
            pass  # drawn from its description and seed instead
    return view


def scene_view(image_id: str, caption: str) -> dict[str, str]:
    """A painted scene's story entry: the image's id and its caption, and nothing else of the painting."""
    return {"image_id": str(image_id), "caption": str(caption)}


def player_row(payload: dict[str, Any]) -> dict[str, Any]:
    """A stored tool row as the allow-list shows it. Rows stored before the allow-list carried the call's inputs and
    result, and a refusal's message; a row's `call_id` (DEL-172) is the host's look at the call's."""
    failed = payload.get("failed") is True or "error" in payload
    row: dict[str, Any] = {"name": payload.get("name"), **({"failed": True} if failed else {})}
    steps = payload.get("steps")
    if isinstance(steps, list) and steps:
        # A batch's steps (`table._batch_steps`): each one's index, tool and refusal, nothing more.
        row["steps"] = [
            {"step": step.get("step"), "name": step.get("name"), **({"failed": True} if step.get("failed") else {})}
            for step in steps
            if isinstance(step, dict)
        ]
    return row


def strip_for_players(value: Any, keys: tuple[str, ...] = ()) -> Any:
    """`value` without `DM_ONLY_KEYS` and `keys`, at any depth: what a player route may answer of it."""
    hidden = (*DM_ONLY_KEYS, *keys)
    if isinstance(value, dict):
        return {k: strip_for_players(v, keys) for k, v in value.items() if k not in hidden}
    if isinstance(value, list | tuple):
        return [strip_for_players(v, keys) for v in value]
    return value
