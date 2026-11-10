"""The message board's rules (DEL-297): making and arranging zones, starting topics, replying, editing and removing
posts, pictures in posts, moderators and members, and the read marks that say what is new.

Every function decides through `board_rights.rights`, nothing else. A zone, topic or post the caller may not read is
`NotFound` (404), the same as one that doesn't exist, so its existence doesn't leak; only what the caller may read can
be refused with `BoardRefused` (403), or `NeedsAccount` (401) for a visitor where posting needs an account.

Organisers make, reorder and delete zones, and set any levels. A campaign's host (not a co-host) makes their
campaign's one zone and manages it, but changes its levels only to `table` or `members` and doesn't untie it: opening a
zone wider is the organisers'. Who manages a zone names its moderators; who moderates lets members in and out, pins,
locks and deletes topics and removes any post. A locked topic takes replies only from who moderates. Authors edit and
remove their own posts. A removed post keeps its place in the topic, its words and picture gone; deleting a topic or
a zone erases it. The owner by token posts as the owner's account, or with no author when there is none.

Titles and posts are stored stripped and as written: nothing here renders them, translates them or puts them into any
prompt. Refusals are `PlayError`s: `BoardRefused` (403), `BoardConflict` (409) for the state (a locked topic, a
removed post, a campaign that has its zone), `NotFound` (404), a plain `PlayError` (422) for bad input.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Any

from delve.domain.board import LEVELS, Level, Post, Topic, Zone
from delve.play.board_rights import Caller, Rights, rights, valid_levels
from delve.play.context import NotFound, PlayError
from delve.play.talk_pictures import TalkPicture
from delve.storage import Storage

NAME_CHARS = 80
DESCRIPTION_CHARS = 500
TITLE_CHARS = 120
POST_CHARS = 20_000

HOST_LEVELS: tuple[Level, ...] = ("table", "members")
"""The levels a campaign's host may set on their zone; wider ones are the organisers'."""
ZONE_FIELDS = ("name", "description", "read", "write", "pictures", "campaign_id")
NO_USERNAME = "No account has that username."
NO_ZONE = "No such zone."
NO_TOPIC = "No such topic."
NO_POST = "No such post."


class BoardRefused(PlayError):
    """The caller may read this but not do that (403)."""


class NeedsAccount(BoardRefused):
    """A visitor where an account is needed (401)."""


class BoardConflict(PlayError):
    """The state refuses it: a locked topic, a removed post, a campaign that has its zone already (409)."""


def readable_zone(storage: Storage, caller: Caller, zone_id: str) -> Zone:
    """The zone, when the caller may read it; `NotFound` otherwise."""
    zone = storage.board.get_zone(zone_id)
    if zone is None or not rights(storage, caller, zone).read:
        raise NotFound(NO_ZONE)
    return zone


def readable_topic(storage: Storage, caller: Caller, topic_id: str) -> tuple[Zone, Topic]:
    """The topic and its zone, when the caller may read the zone; `NotFound` otherwise."""
    topic = storage.board.get_topic(topic_id)
    zone = None if topic is None else storage.board.get_zone(topic.zone_id)
    if topic is None or zone is None or not rights(storage, caller, zone).read:
        raise NotFound(NO_TOPIC)
    return zone, topic


def readable_post(storage: Storage, caller: Caller, post_id: str) -> tuple[Zone, Topic, Post]:
    """The post, its topic and its zone, when the caller may read the zone; `NotFound` otherwise."""
    post = storage.board.get_post(post_id)
    if post is None:
        raise NotFound(NO_POST)
    try:
        zone, topic = readable_topic(storage, caller, post.topic_id)
    except NotFound:
        raise NotFound(NO_POST) from None
    return zone, topic, post


def author_of(storage: Storage, caller: Caller) -> str | None:
    """Who the caller posts as: their account's id; for the owner by token, the first owner account's, else None."""
    if caller.account is not None and caller.account.disabled_at is None:
        return caller.account.id
    if caller.owner:
        return next((account.id for account in storage.accounts.list() if account.owner), None)
    return None


def _anonymous(caller: Caller) -> bool:
    account = caller.account
    return (account is None or account.disabled_at is not None) and not caller.owner


def _refuse(caller: Caller, message: str, hint: str = "") -> BoardRefused:
    """`NeedsAccount` for a visitor, else `BoardRefused` with `message`."""
    if _anonymous(caller):
        return NeedsAccount("Sign in to do that.", "Sign in or make an account.")
    return BoardRefused(message, hint)


def _organisers(storage: Storage, caller: Caller) -> Rights:
    """The caller's rights in a zone of nobody's: what every zone grants them, which is what organisers have."""
    return rights(storage, caller, Zone("", ""))


def _text(raw: Any, most: int, what: str) -> str:
    """`raw` stripped, of 1 to `most` characters; a `PlayError` otherwise."""
    text = raw.strip() if isinstance(raw, str) else ""
    if not text or len(text) > most:
        raise PlayError(f"{what} has 1 to {most} characters.")
    return text


def _level(raw: Any, which: str) -> Level:
    if raw not in LEVELS:
        raise PlayError(f"The {which} level is one of {', '.join(LEVELS)}.")
    return raw


def _campaign(storage: Storage, campaign_id: Any) -> str | None:
    """The campaign id, checked to name a campaign; None for none."""
    if campaign_id is None:
        return None
    if not isinstance(campaign_id, str) or storage.campaigns.get(campaign_id) is None:
        raise PlayError("No such campaign.")
    return campaign_id


def _zone_fields(storage: Storage, zone: Zone, fields: dict[str, Any]) -> Zone:
    """The zone with `fields` checked and applied; `PlayError` for a field that isn't allowed."""
    unknown = sorted(set(fields) - set(ZONE_FIELDS))
    if unknown:
        raise PlayError(f"A zone has no field {', '.join(unknown)}.")
    changed = {}
    if "name" in fields:
        changed["name"] = _text(fields["name"], NAME_CHARS, "A zone's name")
    if "description" in fields:
        description = fields["description"]
        description = description.strip() if isinstance(description, str) else None
        if description is None or len(description) > DESCRIPTION_CHARS:
            raise PlayError(f"A zone's description has at most {DESCRIPTION_CHARS} characters.")
        changed["description"] = description
    for which in ("read", "write"):
        if which in fields:
            changed[which] = _level(fields[which], which)
    if "pictures" in fields:
        if not isinstance(fields["pictures"], bool):
            raise PlayError("Pictures are on (true) or off (false).")
        changed["pictures"] = fields["pictures"]
    if "campaign_id" in fields:
        changed["campaign_id"] = _campaign(storage, fields["campaign_id"])
    zone = replace(zone, **changed)
    refused = valid_levels(zone.read, zone.write, zone.campaign_id)
    if refused is not None:
        raise PlayError(refused)
    return zone


def _host_limits(caller: Caller, granted: Rights, before: Zone, fields: dict[str, Any]) -> None:
    """A manager who isn't an organiser (a campaign's host) changes levels only to `table` or `members`, and doesn't
    change the campaign. A wider level an organiser set may be sent back unchanged, so the host still saves the
    zone's other settings."""
    if granted.manage_wide:
        return
    for which in ("read", "write"):
        level = fields.get(which)
        if level in LEVELS and level not in HOST_LEVELS and level != getattr(before, which):
            raise _refuse(
                caller,
                "A table's host opens their zone only to the table or its members.",
                "An organiser can open it wider.",
            )
    if "campaign_id" in fields and fields["campaign_id"] != before.campaign_id:
        raise _refuse(caller, "Only an organiser ties a zone to a campaign or unties it.")


def _taken(storage: Storage, zone: Zone) -> None:
    """`BoardConflict` when another zone has the zone's campaign."""
    if zone.campaign_id is None:
        return
    other = storage.board.zone_of_campaign(zone.campaign_id)
    if other is not None and other.id != zone.id:
        raise BoardConflict("That campaign has its zone already.")


def create_zone(storage: Storage, caller: Caller, fields: dict[str, Any], now: datetime) -> Zone:
    """A new zone of `fields` (`name` needed), after the others. Organisers make any (levels `accounts` unless
    given); a campaign's host makes their campaign's, read and written by `table` (unless given) or `members`."""
    campaign_id = _campaign(storage, fields.get("campaign_id"))
    granted = rights(storage, caller, Zone("", "", campaign_id=campaign_id))
    if not granted.manage:
        raise _refuse(caller, "Only an organiser, or a table's host for its zone, makes a zone.")
    level = "accounts" if granted.manage_wide else "table"
    fields = {"name": "", "read": level, "write": level, **fields}
    # A host's new zone starts at the table's levels, so any wider one is a change.
    _host_limits(caller, granted, Zone("", "", read="table", write="table", campaign_id=campaign_id), fields)
    zone = _zone_fields(storage, Zone("", "", created_at=now.isoformat()), fields)
    _taken(storage, zone)
    try:
        return storage.board.create_zone(zone)
    except ValueError:
        raise BoardConflict("That campaign has its zone already.") from None


def update_zone(storage: Storage, caller: Caller, zone_id: str, fields: dict[str, Any], now: datetime) -> Zone:
    """The zone with `fields` changed, by who manages it (a campaign's host within `HOST_LEVELS`). `now` is unused:
    a zone keeps no time of change."""
    zone = readable_zone(storage, caller, zone_id)
    granted = rights(storage, caller, zone)
    if not granted.manage:
        raise _refuse(caller, "Only who manages this zone changes it.")
    _host_limits(caller, granted, zone, fields)
    changed = _zone_fields(storage, zone, fields)
    _taken(storage, changed)
    try:
        return storage.board.save_zone(changed)
    except ValueError:
        raise BoardConflict("That campaign has its zone already.") from None


def reorder_zones(storage: Storage, caller: Caller, zone_ids: list[str]) -> list[Zone]:
    """The zones in the order of `zone_ids`, which names every zone once (organisers)."""
    if not _organisers(storage, caller).manage_wide:
        raise _refuse(caller, "Only an organiser orders the zones.")
    zones = {zone.id: zone for zone in storage.board.zones()}
    if len(zone_ids) != len(zones) or set(zone_ids) != set(zones):
        raise PlayError("Name every zone once.")
    for position, zone_id in enumerate(zone_ids):
        if zones[zone_id].position != position:
            storage.board.save_zone(replace(zones[zone_id], position=position))
    return storage.board.zones()


def delete_zone(storage: Storage, caller: Caller, zone_id: str) -> None:
    """Erase the zone with its topics and posts (organisers)."""
    zone = readable_zone(storage, caller, zone_id)
    if not rights(storage, caller, zone).manage_wide:
        raise _refuse(caller, "Only an organiser deletes a zone.")
    storage.board.delete_zone(zone.id)


def _account_named(storage: Storage, username: str) -> str:
    """The id of the account of `username`, as a sign-in reads it (stripped, any case)."""
    account = storage.accounts.by_username(username.strip().casefold()) if isinstance(username, str) else None
    if account is None:
        raise PlayError(NO_USERNAME)
    return account.id


def set_moderators(storage: Storage, caller: Caller, zone_id: str, usernames: list[str]) -> Zone:
    """The zone with the accounts of `usernames` as its moderators (who manages it)."""
    zone = readable_zone(storage, caller, zone_id)
    if not rights(storage, caller, zone).manage:
        raise _refuse(caller, "Only who manages this zone names its moderators.")
    ids = dict.fromkeys(_account_named(storage, username) for username in usernames)
    return storage.board.save_zone(replace(zone, moderators=tuple(ids)))


def _moderated(storage: Storage, caller: Caller, zone: Zone, message: str) -> None:
    if not rights(storage, caller, zone).moderate:
        raise _refuse(caller, message)


def add_member(storage: Storage, caller: Caller, zone_id: str, username: str) -> Zone:
    """The zone with the account of `username` among its members (who moderates)."""
    zone = readable_zone(storage, caller, zone_id)
    _moderated(storage, caller, zone, "Only who moderates this zone lets members in.")
    account_id = _account_named(storage, username)
    if account_id in zone.members:
        return zone
    return storage.board.save_zone(replace(zone, members=(*zone.members, account_id)))


def remove_member(storage: Storage, caller: Caller, zone_id: str, account_id: str) -> Zone:
    """The zone without `account_id` among its members (who moderates)."""
    zone = readable_zone(storage, caller, zone_id)
    _moderated(storage, caller, zone, "Only who moderates this zone takes members out.")
    if account_id not in zone.members:
        return zone
    return storage.board.save_zone(replace(zone, members=tuple(m for m in zone.members if m != account_id)))


def _writer(storage: Storage, caller: Caller, zone: Zone) -> Rights:
    """The caller's rights in the zone, refused unless they may write there."""
    granted = rights(storage, caller, zone)
    if not granted.write:
        raise _refuse(caller, "You can read this zone but not write in it.")
    return granted


def start_topic(
    storage: Storage, caller: Caller, zone_id: str, title: str, text: str, now: datetime
) -> tuple[Topic, Post]:
    """A new topic in the zone with its first post (who may write there)."""
    zone = readable_zone(storage, caller, zone_id)
    _writer(storage, caller, zone)
    title = _text(title, TITLE_CHARS, "A title")
    text = _text(text, POST_CHARS, "A post")
    author = author_of(storage, caller)
    at = now.isoformat()
    topic = Topic("", zone.id, title, author, at, at, author)
    return storage.board.add_topic(topic, Post("", "", author, text, at))


def reply(storage: Storage, caller: Caller, topic_id: str, text: str, now: datetime) -> Post:
    """A new post in the topic (who may write there; in a locked topic, who moderates)."""
    zone, topic = readable_topic(storage, caller, topic_id)
    granted = _writer(storage, caller, zone)
    if topic.locked and not granted.moderate:
        raise BoardConflict("This topic is locked.", "A moderator can unlock it.")
    text = _text(text, POST_CHARS, "A post")
    return storage.board.add_post(Post("", topic.id, author_of(storage, caller), text, now.isoformat()))


def is_author(storage: Storage, caller: Caller, post: Post) -> bool:
    """Whether the caller wrote the post; the owner by token, with no owner account, wrote those without an author."""
    if _anonymous(caller):
        return False
    author = author_of(storage, caller)
    return post.author_id == author and (author is not None or caller.owner)


def edit_post(storage: Storage, caller: Caller, post_id: str, text: str, now: datetime) -> Post:
    """The post with new words, marked edited (its author, while they may write there)."""
    zone, _, post = readable_post(storage, caller, post_id)
    if not is_author(storage, caller, post):
        raise _refuse(caller, "Only its author edits a post.")
    _writer(storage, caller, zone)
    if post.removed is not None:
        raise BoardConflict("This post was removed.")
    text = _text(text, POST_CHARS, "A post")
    return storage.board.save_post(replace(post, text=text, edited_at=now.isoformat()))


def delete_post(storage: Storage, caller: Caller, post_id: str, now: datetime) -> Post:
    """The post removed, keeping its place: its words and picture gone, and who removed it (its author, or who
    moderates)."""
    zone, _, post = readable_post(storage, caller, post_id)
    if is_author(storage, caller, post):
        removed = "author"
    elif rights(storage, caller, zone).moderate:
        removed = "moderator"
    else:
        raise _refuse(caller, "Only its author or a moderator removes a post.")
    if post.removed is not None:
        raise BoardConflict("This post was removed already.")
    return storage.board.save_post(replace(post, text="", picture=None, removed=removed))


def may_attach(storage: Storage, caller: Caller, post_id: str) -> Post:
    """The post, when the caller may add a picture to it (its author, while they may write there and the zone takes
    pictures); refused as `attach_picture` refuses. Cheap, so the route asks before it reads and decodes a picture."""
    zone, _, post = readable_post(storage, caller, post_id)
    if not is_author(storage, caller, post):
        raise _refuse(caller, "Only its author adds a picture to a post.")
    _writer(storage, caller, zone)
    if not zone.pictures:
        raise BoardRefused("Pictures aren't allowed in this zone.", "Who manages the zone can allow them.")
    if post.removed is not None:
        raise BoardConflict("This post was removed.")
    return post


def attach_picture(storage: Storage, caller: Caller, post_id: str, picture: TalkPicture) -> Post:
    """The post with `picture`, in place of any it had (its author, while the zone takes pictures)."""
    post = may_attach(storage, caller, post_id)
    blob = storage.blobs.put(picture.data, picture.mime)
    shown = {"blob": blob, "mime": picture.mime, "width": picture.width, "height": picture.height}
    return storage.board.save_post(replace(post, picture=shown))


def take_down_picture(storage: Storage, caller: Caller, post_id: str) -> Post:
    """The post without its picture (its author, or who moderates)."""
    zone, _, post = readable_post(storage, caller, post_id)
    if not is_author(storage, caller, post):
        _moderated(storage, caller, zone, "Only its author or a moderator takes a picture down.")
    if post.picture is None:
        raise NotFound("This post has no picture.")
    return storage.board.save_post(replace(post, picture=None))


def set_topic(
    storage: Storage, caller: Caller, topic_id: str, *, pinned: bool | None = None, locked: bool | None = None
) -> Topic:
    """The topic pinned or unpinned, locked or unlocked (who moderates)."""
    zone, topic = readable_topic(storage, caller, topic_id)
    _moderated(storage, caller, zone, "Only who moderates this zone pins or locks a topic.")
    changed = replace(
        topic,
        pinned=topic.pinned if pinned is None else pinned,
        locked=topic.locked if locked is None else locked,
    )
    return storage.board.save_topic(changed)


def delete_topic(storage: Storage, caller: Caller, topic_id: str) -> None:
    """Erase the topic with its posts (who moderates)."""
    zone, topic = readable_topic(storage, caller, topic_id)
    _moderated(storage, caller, zone, "Only who moderates this zone deletes a topic.")
    storage.board.delete_topic(topic.id)


def is_new(topic: Topic, marks: dict[str, str], first_visit: str | None) -> bool:
    """Whether the topic has posts the reader hasn't read: after their mark on it, or, without one, after their first
    board visit (before any visit, nothing is new)."""
    since = marks.get(topic.id, first_visit)
    return since is not None and topic.last_post_at > since


def visit(storage: Storage, caller: Caller, now: datetime) -> str | None:
    """The account's first board visit, noted now when there was none; None for who has no account."""
    account_id = author_of(storage, caller)
    if account_id is None:
        return None
    storage.board.set_first_visit(account_id, now.isoformat())
    return storage.board.first_visit(account_id)


def untie_campaign(storage: Storage, campaign_id: str) -> None:
    """Untie the campaign's zone from it, before the campaign goes: a `table` level becomes `members`."""
    zone = storage.board.zone_of_campaign(campaign_id)
    if zone is None:
        return
    widened = {which: "members" for which in ("read", "write") if getattr(zone, which) == "table"}
    storage.board.save_zone(replace(zone, campaign_id=None, **widened))
