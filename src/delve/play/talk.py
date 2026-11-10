"""Table talk (spec §7.3): what the people at the table say to each other, out of character, while the DM listens to
none of it.

Any seat may talk, observers included. Talk is a `talk` story entry, `{seat_id, name, text, original, language}`,
for everyone at the table, outside any beat. It is never a submission, so it never reaches the DM: the DM's message is
built from the beat's submissions only, and the primer and the system prompt read no story at all. `text` is the
English (`delve.play.translate.to_english`) and `original` the seat's own words; the other seats read it in their own
language (`translate_entry`).

An Ask the DM answer stays with who asked, until the asker shares it: `share` copies the question and its answer into
table talk, as one `talk` entry that also holds the `answer` and the id of the answer it `shared`. The question keeps
the asker's own words.

Pictures (DEL-294), while the campaign's `talk_pictures` option is on: a seated player or a host pastes one
(`delve.play.talk_pictures` makes it a clean WebP); it is a `talk` entry with no words and a `picture`
`{blob, mime, width, height}`, whose blob is kept by being named there. An observer sees it but can't paste. The
host, a co-host or who pasted it takes it down: the entry loses its `picture` and says `picture_removed`, and the
blob, named nowhere else, is pruned in time.
"""

from __future__ import annotations

from dataclasses import replace

from delve.domain.campaigns import Seat, StoryEntry
from delve.play import translate
from delve.play.audience import for_seats
from delve.play.context import NotFound, PlayError
from delve.play.seats import TABLE_RIGHTS
from delve.play.table import AppServices, add_entry, play_settings, told
from delve.play.talk_pictures import TalkPicture

__all__ = ["NotAllowed", "NotYours", "may_paste", "paste_picture", "picture_of", "share", "take_down", "talk"]


class NotYours(PlayError):
    """An answer to someone else's question: only who asked may share it."""


class NotAllowed(PlayError):
    """A picture the seat may not paste or take down."""


def may_paste(services: AppServices, campaign_id: str, seat: Seat) -> None:
    """`NotAllowed` while the campaign's `talk_pictures` option is off, and for an observer."""
    if not play_settings(services.storage, campaign_id)["talk_pictures"]:
        raise NotAllowed("Pictures in table talk aren't allowed at this table.", "The host can allow them.")
    if seat.role == "observer":
        raise NotAllowed("Observers can't paste pictures.")


def paste_picture(services: AppServices, campaign_id: str, seat: Seat, picture: TalkPicture) -> StoryEntry:
    """Put `picture` into table talk, as `seat` (`may_paste`)."""
    may_paste(services, campaign_id, seat)
    blob = services.storage.blobs.put(picture.data, picture.mime)
    shown = {"blob": blob, "mime": picture.mime, "width": picture.width, "height": picture.height}
    return _said(services, campaign_id, {**_words(seat, ""), "picture": shown})


def picture_of(services: AppServices, campaign_id: str, entry_id: str) -> dict | None:
    """The `picture` of the talk entry `entry_id` of this campaign, or None (none, or taken down)."""
    entry = services.storage.story.get(entry_id)
    if entry is None or entry.campaign_id != campaign_id or entry.kind != "talk":
        return None
    picture = entry.payload.get("picture")
    return picture if isinstance(picture, dict) else None


def take_down(services: AppServices, campaign_id: str, seat: Seat, entry_id: str) -> StoryEntry:
    """Take the picture of `entry_id` out of table talk, as `seat` (the host, a co-host or who pasted it):
    `NotFound` for no picture there, `NotAllowed` for anyone else. Everyone at the table hears the changed entry."""
    if picture_of(services, campaign_id, entry_id) is None:
        raise NotFound(f"No picture '{entry_id}' at this table.")
    entry = services.storage.story.get(entry_id)
    assert entry is not None
    if seat.role not in TABLE_RIGHTS and entry.payload.get("seat_id") != seat.id:
        raise NotAllowed("Only the host, a co-host or who pasted it can take it down.")
    payload = {key: value for key, value in entry.payload.items() if key != "picture"}
    entry = services.storage.story.put(replace(entry, payload={**payload, "picture_removed": True}))
    told(services, entry)
    return entry


async def talk(services: AppServices, campaign_id: str, seat: Seat, text: str) -> StoryEntry:
    """Say `text` at the table, as `seat`: the stored `talk` entry, in English with the seat's own words, published
    for everyone at the table and translated for the other languages there."""
    text = text.strip()
    if not text:
        raise PlayError("Say something.")
    english = await translate.to_english(services, campaign_id, text, seat.language)
    words = {**_words(seat, english.text), "original": text}
    if english.failed:
        words["translation"] = "failed"
    entry = _said(services, campaign_id, words)
    translate.translate_entry(services, entry, also=[seat.id])
    return entry


def share(services: AppServices, campaign_id: str, seat: Seat, answer_id: str) -> StoryEntry:
    """Copy the answer `answer_id` and its question into table talk, as the asker `seat`. `NotFound` for anything
    but an answer of this campaign, `NotYours` for an answer to someone else."""
    answer = services.storage.story.get(answer_id)
    if answer is None or answer.campaign_id != campaign_id or answer.kind != "answer":
        raise NotFound(f"No answer '{answer_id}' at this table.")
    if answer.audience != for_seats([seat.id]):
        raise NotYours("Only who asked can share the answer.")
    [asked] = services.storage.story.list(campaign_id, before_seq=answer.seq, limit=1) or [None]
    if asked is None or asked.kind != "ask" or asked.audience != answer.audience:
        raise NotFound(f"No question for the answer '{answer_id}'.")
    words = _words(seat, str(asked.payload.get("text", "")))
    own = {key: asked.payload[key] for key in ("original", "language") if key in asked.payload}
    entry = _said(services, campaign_id, {**words, **own, "answer": answer.payload.get("text", ""), "shared": answer.id})
    translate.translate_entry(services, entry, also=[seat.id])
    return entry


def _words(seat: Seat, text: str) -> dict[str, str]:
    return {"seat_id": seat.id, "name": seat.name, "text": text, "original": text, "language": seat.language}


def _said(services: AppServices, campaign_id: str, payload: dict) -> StoryEntry:
    entry = add_entry(services.storage, campaign_id, None, "talk", payload)
    told(services, entry)
    return entry
