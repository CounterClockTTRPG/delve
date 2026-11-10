"""The campaign's log, from its first entry to its last, in pages to browse or print (DEL-324).

The log is the story as the viewing seat saw it (`audience.can_see`): the acts, the DM's words, the lines said, the
pictures, the recaps and the seat's own questions to the DM, with the dice as the players read them (`story_dice` as
a player's seat, whatever the viewer's role: the log is the table's, not the DM's screen). Table talk, the DM's errors
and tool rows without dice for the players are left out.

Pages follow the sessions: each session's beats, cut into even parts of at most about `PAGE_ENTRIES` entries, a beat never split.
A beat belongs to the session its last entry fell in; entries from before the first session (setting up the party)
are the log's opening pages, with no session.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import asdict, dataclass, replace
from typing import Any

from delve.domain.campaigns import Seat, Session, StoryEntry
from delve.play.audience import can_see, seat_controls
from delve.play.context import NotFound
from delve.play.table import seat_dice
from delve.storage.interfaces import Storage

__all__ = ["LOGGED_KINDS", "PAGE_ENTRIES", "campaign_log"]

PAGE_ENTRIES = 60
"""About the most entries a page holds: a session takes as few pages as this allows, each of about the same size, and
a page closes before the beat that would take it well past that size."""

LOGGED_KINDS = frozenset({"player_act", "dm_text", "say", "image", "scene", "recap", "ask", "answer", "tool"})
"""The kinds of entry the log keeps; a tool row only with dice the players read."""


@dataclass(frozen=True)
class _Page:
    session: Session | None
    entries: list[StoryEntry]
    part: int = 1
    parts: int = 1


def campaign_log(
    storage: Storage, campaign_id: str, seat: Seat, page: int = 1, language: str | None = None
) -> dict[str, Any]:
    """`{"campaign", "pages", "page", "entries", "names"}`: the index of the log's pages (each its number, session
    number and title, part of its session, first and last time, and how many entries), page `page`'s entries as the
    story sends them (with a `translation` into `language` where there is one), and the names of the characters the
    acts were for. A log with no entries has no pages; `NotFound` for a page past the last."""
    campaign = storage.campaigns.get(campaign_id)
    if campaign is None:
        raise NotFound(f"No campaign '{campaign_id}'.", [])
    pages = _pages(storage, campaign_id, _logged(storage, campaign_id, seat))
    if pages and not 1 <= page <= len(pages):
        raise NotFound(f"The log has pages 1 to {len(pages)}, not {page}.", [])
    entries = [asdict(entry) for entry in pages[page - 1].entries] if pages else []
    if language is not None and entries:
        found = storage.translations.for_entries([e["id"] for e in entries], language)
        for entry in entries:
            translation = found.get(entry["id"])
            if translation is not None:
                entry["translation"] = {k: getattr(translation, k) for k in ("language", "text", "status")}
    return {
        "campaign": {"id": campaign.id, "name": campaign.name},
        "pages": [_page_json(n, p) for n, p in enumerate(pages, start=1)],
        "page": page if pages else 0,
        "entries": entries,
        "names": {c.id: c.name for c in storage.characters.list(campaign_id)},
    }


def _logged(storage: Storage, campaign_id: str, seat: Seat) -> list[StoryEntry]:
    """The entries the log keeps for `seat`, oldest first; a tool row as its dice."""
    controls = seat_controls(storage, seat)
    dice = seat_dice(storage, campaign_id, "player")
    kept = []
    for entry in storage.story.list(campaign_id):
        if entry.kind not in LOGGED_KINDS or not can_see(seat, entry.audience, controls):
            continue
        if entry.kind == "tool":
            row = dice.row(entry.payload)
            lines = [
                *(row or {}).get("dice", []),
                *(d for s in (row or {}).get("steps", []) for d in s.get("dice", [])),
            ]
            if not lines:
                continue
            entry = replace(entry, payload={"dice": lines})
        kept.append(entry)
    return kept


def _pages(storage: Storage, campaign_id: str, entries: list[StoryEntry]) -> list[_Page]:
    sessions = storage.sessions.list(campaign_id)
    starts = [s.started_at for s in sessions]
    beats: list[list[StoryEntry]] = []
    for entry in entries:
        if beats and entry.beat_id is not None and beats[-1][-1].beat_id == entry.beat_id:
            beats[-1].append(entry)
        else:
            beats.append([entry])
    by_session: list[tuple[Session | None, list[list[StoryEntry]]]] = []
    for beat in beats:
        at = bisect_right(starts, beat[-1].at)
        session = sessions[at - 1] if at > 0 else None
        if by_session and by_session[-1][0] == session:
            by_session[-1][1].append(beat)
        else:
            by_session.append((session, [beat]))
    pages: list[_Page] = []
    for session, its_beats in by_session:
        # As few parts as `PAGE_ENTRIES` allows, of about the same size: no last page of a handful.
        total = sum(len(beat) for beat in its_beats)
        size = -(-total // -(-total // PAGE_ENTRIES))
        parts: list[list[StoryEntry]] = [[]]
        for beat in its_beats:
            if parts[-1] and len(parts[-1]) + len(beat) > size and len(parts[-1]) + len(beat) / 2 > size:
                parts.append([])
            parts[-1].extend(beat)
        pages += [_Page(session, part, n, len(parts)) for n, part in enumerate(parts, start=1)]
    return pages


def _page_json(number: int, page: _Page) -> dict[str, Any]:
    return {
        "page": number,
        "session": page.session.number if page.session else None,
        "title": page.session.title if page.session else "",
        "part": page.part,
        "parts": page.parts,
        "from": page.entries[0].at,
        "to": page.entries[-1].at,
        "entries": len(page.entries),
    }
