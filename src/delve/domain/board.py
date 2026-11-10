"""The message board (DEL-297): zones (a table's own, or the site's), topics in them, and posts in a topic. A zone's
`read` and `write` levels say who may see and post: everybody, any account, the zone's members, or the campaign's
table."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

Level = Literal["everybody", "accounts", "members", "table"]
LEVELS: tuple[Level, ...] = ("everybody", "accounts", "members", "table")
Removed = Literal["author", "moderator"]


@dataclass(frozen=True)
class Zone:
    """A board zone. `moderators` and `members` are account ids; `campaign_id` ties it to a table (one zone each)."""

    id: str
    name: str
    description: str = ""
    position: int = 0
    read: Level = "accounts"
    write: Level = "accounts"
    pictures: bool = False
    campaign_id: str | None = None
    moderators: tuple[str, ...] = ()
    members: tuple[str, ...] = ()
    created_at: str = ""


@dataclass(frozen=True)
class Topic:
    """A thread in a zone. `last_post_at`, `last_author_id` and `posts` follow the posts. The author may be gone."""

    id: str
    zone_id: str
    title: str
    author_id: str | None
    created_at: str
    last_post_at: str
    last_author_id: str | None
    posts: int = 1
    pinned: bool = False
    locked: bool = False


@dataclass(frozen=True)
class Post:
    """A post in a topic. `picture` is `{"blob", "mime", "width", "height"}`; `removed` says who took it down."""

    id: str
    topic_id: str
    author_id: str | None
    text: str
    created_at: str
    edited_at: str | None = None
    removed: Removed | None = None
    picture: dict[str, Any] | None = None
