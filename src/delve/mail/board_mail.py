"""Board replies by email (DEL-314): who follows a topic gets an email for a new reply in it, then none until they come
back to the topic, so a lively thread sends one email, not one a post.

A follower is mailed when they may still read the zone (`board_rights.rights`), didn't write the post, and have read
the topic since their last email: their read mark is at or past `notified_at`, or there was no email yet. The email is
in the follower's language, the poster's words as written, Markdown marks dropped. Only the outbox is written: the
sender delivers later.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from delve.domain.board import Post, Topic
from delve.mail import outbox, settings, texts
from delve.mail.compose import compose
from delve.play.board_rights import caller_of, rights

EXCERPT_CHARS = 300

_IMAGE_OR_LINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
_LINE_MARK = re.compile(r"^\s*(?:#{1,6}\s+|>\s?|[-*+]\s+|\d+[.)]\s+)+", re.MULTILINE)
_EMPHASIS = re.compile(r"(?<!\w)[*_~]+|[*_~]+(?!\w)|`+")


def excerpt(text: str) -> str:
    """The post's words without Markdown's marks (headings, quotes, lists, emphasis, code, links as their words), on
    one line, cut on a word to at most `EXCERPT_CHARS` and an ellipsis."""
    plain = _IMAGE_OR_LINK.sub(r"\1", text)
    plain = _LINE_MARK.sub("", plain)
    plain = _EMPHASIS.sub("", plain)
    plain = " ".join(plain.split())
    if len(plain) <= EXCERPT_CHARS:
        return plain
    cut = plain[: EXCERPT_CHARS + 1]
    space = cut.rfind(" ")
    return (cut[:space] if space > 0 else plain[:EXCERPT_CHARS]).rstrip() + "…"


def _came_back(notified_at: str | None, read_at: str | None) -> bool:
    """Whether the follower read the topic since their last email (always, before the first)."""
    if notified_at is None:
        return True
    return read_at is not None and datetime.fromisoformat(read_at) >= datetime.fromisoformat(notified_at)


def notify(storage, data_dir: Path, topic: Topic, post: Post, author_id: str | None, now: datetime) -> int:
    """Queue the `board` email about `post` for the topic's followers who should have it, and note `now` as each one's
    `notified_at`; how many were queued. Nothing without mail set up or a public URL."""
    url = settings.public_url(data_dir)
    if url is None or not settings.mail_enabled(data_dir):
        return 0
    zone = storage.board.get_zone(topic.zone_id)
    if zone is None:
        return 0
    poster = None if author_id is None else storage.accounts.get(author_id)
    words = excerpt(post.text)
    at = now.isoformat()
    count = 0
    for account_id, notified_at in storage.board.followers(topic.id):
        if account_id == author_id:
            continue
        account = storage.accounts.get(account_id)
        if account is None or outbox.address_for(account, "board") is None:
            continue
        if not rights(storage, caller_of(account, account.organiser, account.owner), zone).read:
            continue
        if not _came_back(notified_at, storage.board.read_marks(account_id).get(topic.id)):
            continue
        language = account.profile.language
        name = poster.profile.display_name if poster is not None else texts.text(language, "email.board.owner")
        off = outbox.off_link(data_dir, account.id, "board")
        if off is None:  # every board email carries its off link
            continue
        mail = compose(
            "board",
            language,
            {"name": name, "topic": topic.title, "zone": zone.name, "excerpt": words},
            link=f"{url}/board/{zone.id}/{topic.id}",
            off_link=off[1],
        )
        if outbox.queue(storage, account, "board", mail, now, unsubscribe=off[0]) is not None:
            storage.board.set_notified(account_id, topic.id, at)
            count += 1
    return count
