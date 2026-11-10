"""The DM's notes: hidden secrets it may recall but must not narrate, and the public chronicle (ttrpg2
`tools/secrets.py` and `log_note`).

Secrets are hidden NPC motives, foreshadowed truths, rolls the players shouldn't see. They are no events, so the story
log never carries them, until one is revealed: then its text becomes the public event `secret_revealed`. The DM's
notes on a room are in `play.moves.note_room`.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace
from typing import Any

from delve.domain.campaigns import Note
from delve.domain.data import to_dict
from delve.play.context import CampaignContext, NotFound, PlayError

__all__ = ["dm_note", "dm_secret_update", "dm_secrets", "log_note"]


def _session(ctx: CampaignContext) -> int:
    return ctx.storage.campaign_states.get(ctx.campaign_id).session


def _text(text: str) -> str:
    if not text.strip():
        raise PlayError("A note needs text.")
    return text.strip()


def dm_note(ctx: CampaignContext, text: str, tags: Iterable[str] = (), related_to: str = "") -> dict[str, Any]:
    """Record a hidden, DM-only note: never narrated. `tags` are free-form ('motive', 'rumour', 'foreshadow',
    'plot'); `related_to` names the NPC, place or quest it concerns."""
    note = ctx.storage.notes.create(
        ctx.campaign_id,
        "secret",
        _text(text),
        tags=[str(t) for t in tags],
        related_to=related_to.strip(),
        session=_session(ctx),
    )
    return {"id": note.id, "stored": True}


def _secret(note: Note) -> dict[str, Any]:
    raw = to_dict(note)
    for key in ("campaign_id", "kind", "map_name", "node"):
        raw.pop(key)
    return raw


def dm_secrets(ctx: CampaignContext, tag: str = "", related_to: str = "", contains: str = "") -> dict[str, Any]:
    """The hidden notes, filtered (all filters together; none gives every one): `tag` matches part of any of a note's
    tags, `related_to` its whole slug, `contains` part of its text, ignoring case."""
    tag_l, rel_l, sub_l = tag.lower().strip(), related_to.lower().strip(), contains.lower().strip()
    found = [
        note
        for note in ctx.storage.notes.list(ctx.campaign_id, kind="secret")
        if (not tag_l or any(tag_l in t.lower() for t in note.tags))
        and (not rel_l or note.related_to.lower() == rel_l)
        and (not sub_l or sub_l in note.text.lower())
    ]
    return {"count": len(found), "secrets": [_secret(n) for n in found]}


def dm_secret_update(
    ctx: CampaignContext,
    id: str,
    text: str | None = None,
    tags: Iterable[str] | None = None,
    related_to: str | None = None,
    revealed: bool | None = None,
) -> dict[str, Any]:
    """Edit a hidden note, or reveal it (`revealed=True`): then its text is a public event, `secret_revealed`. Only
    the fields given change."""
    note = ctx.storage.notes.get(id)
    if note is None or note.campaign_id != ctx.campaign_id or note.kind != "secret":
        raise NotFound(f"No secret with id {id}.", hint="dm_secrets lists them.")
    changed = replace(
        note,
        text=_text(text) if text is not None else note.text,
        tags=tuple(str(t) for t in tags) if tags is not None else note.tags,
        related_to=related_to.strip() if related_to is not None else note.related_to,
        revealed=revealed if revealed is not None else note.revealed,
    )
    with ctx.storage.transaction():
        saved = ctx.storage.notes.save(changed)
        if saved.revealed and not note.revealed:
            ctx.log("secret_revealed", id=saved.id, slug=saved.related_to, notes=saved.text)
    return {"id": saved.id, "updated": True, "revealed": saved.revealed}


def log_note(ctx: CampaignContext, text: str) -> dict[str, Any]:
    """A public line of the session's chronicle."""
    with ctx.storage.transaction():
        note = ctx.storage.notes.create(ctx.campaign_id, "log", _text(text), session=_session(ctx))
        ctx.log("log_note", id=note.id, text=note.text)
    return {"id": note.id, "text": note.text, "session": note.session}
