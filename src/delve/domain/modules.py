"""Modules: the maps that make one up, and the revisions campaigns pin (spec §8.1)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

LibraryOrigin = Literal["published", "downloaded"]
"""How a module came to have a library entry: this install published it, or downloaded it from the library."""


HOMEBREW = "homebrew"
"""The tag (in the metadata's DungML `tags`) of a module made here rather than from a published book (DEL-226): a new
blank one and one generated from a prompt have it, a converted PDF hasn't, an import keeps its own tags. The
organisers may add or remove it."""


def homebrew(metadata: dict[str, Any] | None) -> dict[str, Any]:
    """The metadata with the `HOMEBREW` tag among its tags."""
    metadata = dict(metadata or {})
    tags = [str(tag) for tag in metadata.get("tags") or []]
    if not any(tag.casefold() == HOMEBREW for tag in tags):
        metadata["tags"] = [*tags, HOMEBREW]
    return metadata


BannerSource = str
"""Where a module's banner came from (DEL-123): `painted`, `uploaded`, or `picture:<attachment id>`, one of its own."""

BannerStatus = Literal["painting", "failed"]
"""A module banner being painted, or whose painting failed; None once it lands (or when none was asked for)."""


@dataclass(frozen=True)
class ModuleCategory:
    """One of the organisers' categories of modules (DEL-114), in their order (`position`). A module has one or none."""

    id: str
    name: str
    position: int


@dataclass(frozen=True)
class ModuleBanner:
    """A module's banner (DEL-123): the picture shown (`blob`, `mime`, `source`; None before the first lands), and a
    painting under way or failed (`status`, `error`), whose brief (`prompt`) is never sent to players."""

    blob: str | None = None
    mime: str | None = None
    source: BannerSource | None = None
    status: BannerStatus | None = None
    error: str | None = None
    prompt: str | None = None


@dataclass(frozen=True)
class ModuleHead:
    """What a list of campaigns needs of a module: its title and its banner (DEL-172)."""

    title: str
    banner: ModuleBanner | None


@dataclass(frozen=True)
class ModuleMap:
    """One map entry of a module: a playable `map`, or a `library` other maps include."""

    name: str
    role: Literal["map", "library"]
    source: str
    is_default: bool


@dataclass(frozen=True)
class Module:
    """A module's working copy, edited in place. `head_revision` is its newest revision, None before the first. A
    `draft` (a conversion's, plan 5) can't start a campaign until it is marked ready. The `library_*` fields are its
    entry in the shared library (DEL-110), None until it is published or downloaded: the entry's key, the version it
    is at, that version's `.dscn` hash, how it got there, and who published it. `category_id` and `banner` are this
install's own: setting them is no edit."""

    id: str
    title: str
    metadata: dict[str, Any]
    maps: tuple[ModuleMap, ...]
    head_revision: int | None
    updated_at: str
    draft: bool = False
    library_key: str | None = None
    library_version: int | None = None
    library_hash: str | None = None
    library_origin: LibraryOrigin | None = None
    library_author: str | None = None
    category_id: str | None = None
    """Its category (DEL-114), None for none. Not part of the module's content: no revision, no "edited"."""
    banner: ModuleBanner | None = None
    """Its banner (DEL-123), None for none. Not part of the module's content either."""


@dataclass(frozen=True)
class Revision:
    """An immutable snapshot of a module, numbered from 1, made when a campaign starts or upgrades on a changed module."""

    module_id: str
    number: int
    title: str
    metadata: dict[str, Any]
    maps: tuple[ModuleMap, ...]
    created_at: str


CommentStatus = Literal["open", "working", "review", "kept", "rejected", "failed", "closed"]
COMMENT_STATUSES: tuple[CommentStatus, ...] = ("open", "working", "review", "kept", "rejected", "failed", "closed")
"""A fix-it comment's status (table voice and fixes Task 0): `open` until its job takes it, `working` while it runs,
`review` ("ready to review") once it proposes a change, then `kept` or `rejected`; `failed` with its reason; `closed`
without running."""


@dataclass(frozen=True)
class ModuleComment:
    """A fix-it comment on a module: what an organiser asks to be fixed, in plain words ("exit X is not yet in
    place, fix it"), optionally tied to a part of it (`anchor`: `{"kind": "map", "map"}`, `{"kind": "room", "map",
    "node"}`, `{"kind": "text", "text_id"}` or `{"kind": "entity", "entity_kind", "entity_id"}`). `conversion_id` is
    the job that acts on it, from the module's `revision`; `error` is why it failed."""

    id: str
    module_id: str
    text: str
    anchor: dict[str, Any] | None = None
    status: CommentStatus = "open"
    conversion_id: str | None = None
    revision: int | None = None
    error: str | None = None
    author: str = ""
    created_at: str = ""
    updated_at: str = ""
