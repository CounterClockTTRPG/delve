"""The message board's API (DEL-297): the board's zones, the topics in a zone, the posts in a topic, pictures in posts,
and the moderators and members of a zone.

Anyone may call it: visitors too, who read the zones open to everybody, the authors' names and faces with them. Every
decision is `delve.play.board`'s, by the zone's rights (`delve.play.board_rights`): the routes find the caller
(`board_caller`), shape the JSON and publish. A zone, topic or post the caller may not read is 404, the same as one
that doesn't exist, the picture and avatar routes too, and such a zone is not in `/api/board` at all. Read marks and
the first visit are kept for accounts only (the owner by token as the owner's account, when there is one).

A post's picture is the sixth raw-body exception to the JSON rule: the guard lets only `TALK_PICTURE_TYPES` through
(`BOARD_PICTURE_PATH`), of at most `TALK_PICTURE_LIMIT` bytes as declared; the route counts the bytes too. An account
writes at most `POSTS_PER_MINUTE` topics, replies, edits and pictures a minute, refused ones too (429).

Each write publishes `board` with the `zone_id` (and the `topic_id` for a topic's or a post's change), to whoever may
read the zone; a change to a zone itself, or its deletion, publishes the `zone_id` alone, on which everyone reads
`/api/board` again. Posts are for people only: the DM never reads them, so they go into no prompt.

An account who may read a topic may follow it (DEL-314); a reply queues its followers' emails
(`delve.mail.board_mail`) and the sender delivers them later.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from collections import defaultdict, deque
from typing import Annotated, Any

from fastapi import APIRouter, Body, HTTPException, Query, Request
from starlette.concurrency import run_in_threadpool
from starlette.responses import Response

from delve.domain.accounts import Account
from delve.domain.board import Post, Topic, Zone
from delve.mail import board_mail
from delve.play import board, profiles
from delve.play.board_rights import VISITOR, Caller, badges, caller_of, rights
from delve.play.context import PlayError
from delve.play.talk_pictures import TALK_PICTURE_LIMIT, talk_picture
from delve.storage import Storage
from delve.web.auth import identify
from delve.web.refusals import refusal
from delve.web.routes.assets import attachment_response
from delve.web.routes.campaigns import now_of
from delve.web.routes.profiles import AVATAR_TYPE

router = APIRouter()
log = logging.getLogger(__name__)

POST_PAGE = 30
POSTS_PER_MINUTE = 6
WINDOW_S = 60.0
TOO_MANY = "Too many posts: wait a minute."
NO_PICTURE = "No such picture."
NO_AVATAR = "No such avatar."
NO_CACHE = "private, no-cache"

clock = time.monotonic
_counting = threading.Lock()


def board_caller(request: Request) -> Caller:
    """The caller as the board's rights see them: an account with its organiser and owner flags, the owner token or
    this machine as the owner, an organiser's seat as an organiser, and anyone else, or nobody, as a visitor."""
    principal = identify(request)
    if principal is None:
        return VISITOR
    return caller_of(principal.account, "organiser" in principal.roles, principal.owner)


def _storage(request: Request) -> Storage:
    return request.app.state.storage


def _changed(request: Request, zone_id: str, topic_id: str | None = None) -> None:
    """Tell whoever may read the zone that it, or one of its topics, changed."""
    data = {"zone_id": zone_id} if topic_id is None else {"zone_id": zone_id, "topic_id": topic_id}
    request.app.state.events.publish("board", data, scope="board", zone_id=zone_id)


def _limit(request: Request, caller: Caller) -> None:
    """429 for who wrote `POSTS_PER_MINUTE` topics, replies, edits and pictures in the last minute. Who has no author
    writes nothing, so isn't counted: the rules refuse them."""
    writer = board.author_of(_storage(request), caller) or ("owner" if caller.owner else None)
    if writer is None:
        return
    with _counting:
        sent: defaultdict[str, deque[float]] | None = getattr(request.app.state, "board_posts", None)
        if sent is None:
            sent = request.app.state.board_posts = defaultdict(deque)
        now = clock()
        recent = sent[writer]
        while recent and recent[0] <= now - WINDOW_S:
            recent.popleft()
        if len(recent) >= POSTS_PER_MINUTE:
            raise HTTPException(status_code=429, detail=TOO_MANY)
        recent.append(now)


def _object(body: Any) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="Send the fields as an object.")
    return body


def _follow_asked(fields: dict[str, Any]) -> bool:
    """`fields["follow"]`: true or false, absent as false; 422 otherwise."""
    asked = fields.get("follow", False)
    if not isinstance(asked, bool):
        raise HTTPException(status_code=422, detail="Send follow as true or false.")
    return asked


def _strings(body: Any, key: str) -> list[str]:
    """`body[key]`, a list of strings; 422 otherwise."""
    value = _object(body).get(key)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise HTTPException(status_code=422, detail=f"Send {key} as a list of text.")
    return value


class _Readers:
    """What one request shows of the board to its caller: the read marks and first visit (an account's), and each
    author it names, looked up once."""

    def __init__(self, storage: Storage, caller: Caller, now: str, *, note_visit: bool) -> None:
        self.storage = storage
        self.caller = caller
        self.reader = board.author_of(storage, caller)
        self.marks: dict[str, str] = {}
        self.first_visit: str | None = None
        if self.reader is not None:
            self.marks = storage.board.read_marks(self.reader)
            if note_visit:
                storage.board.set_first_visit(self.reader, now)
            self.first_visit = storage.board.first_visit(self.reader)
        self._accounts: dict[str, Account | None] = {}

    def is_new(self, topic: Topic) -> bool:
        return board.is_new(topic, self.marks, self.first_visit)

    def author(self, zone: Zone, account_id: str | None) -> dict[str, Any]:
        """The author as the zone's readers see them: name, face, colour and badges, never the rest of the profile.
        No account (the owner by token) and an account that is gone have no name."""
        if account_id is not None and account_id not in self._accounts:
            self._accounts[account_id] = self.storage.accounts.get(account_id)
        account = None if account_id is None else self._accounts[account_id]
        if account is None:
            return {"account_id": account_id, "display_name": "", "avatar": None, "colour": None, "badges": []}
        summary = profiles.summary(account)
        return {
            "account_id": account.id,
            "display_name": summary["display_name"],
            "avatar": summary["avatar"],
            "colour": summary["colour"],
            "badges": badges(self.storage, zone, account.id),
        }

    def zone_json(self, zone: Zone) -> dict[str, Any]:
        granted = rights(self.storage, self.caller, zone)
        return {
            "id": zone.id,
            "name": zone.name,
            "description": zone.description,
            "position": zone.position,
            "read": zone.read,
            "write": zone.write,
            "pictures": zone.pictures,
            "campaign_id": zone.campaign_id,
            "rights": {
                "read": granted.read,
                "write": granted.write,
                "moderate": granted.moderate,
                "manage": granted.manage,
                "manage_wide": granted.manage_wide,
            },
        }

    def topic_json(self, zone: Zone, topic: Topic) -> dict[str, Any]:
        return {
            "id": topic.id,
            "zone_id": topic.zone_id,
            "title": topic.title,
            "author": self.author(zone, topic.author_id),
            "created_at": topic.created_at,
            "last_post_at": topic.last_post_at,
            "last_author": self.author(zone, topic.last_author_id),
            "posts": topic.posts,
            "pinned": topic.pinned,
            "locked": topic.locked,
            "new": self.is_new(topic),
        }

    def one_topic_json(self, zone: Zone, topic: Topic) -> dict[str, Any]:
        """The topic as its own page shows it: with whether the reader follows it (False for a visitor)."""
        following = self.reader is not None and self.storage.board.following(self.reader, topic.id)
        return {**self.topic_json(zone, topic), "following": following}

    def post_json(self, zone: Zone, post: Post) -> dict[str, Any]:
        shown = post.picture
        return {
            "id": post.id,
            "topic_id": post.topic_id,
            "author": self.author(zone, post.author_id),
            "text": post.text,
            "created_at": post.created_at,
            "edited_at": post.edited_at,
            "removed": post.removed,
            "picture": None if shown is None else {"width": shown["width"], "height": shown["height"]},
            "mine": board.is_author(self.storage, self.caller, post),
        }


def _readers(request: Request, caller: Caller, *, note_visit: bool = False) -> _Readers:
    return _Readers(_storage(request), caller, now_of(request).isoformat(), note_visit=note_visit)


def _zone_of(request: Request, zone_id: str) -> Zone:
    found = _storage(request).board.get_zone(zone_id)
    if found is None:
        raise HTTPException(status_code=404, detail=board.NO_ZONE)
    return found


# ----- the board and its zones -----


@router.get("/api/board")
def the_board(request: Request) -> dict:
    """The zones the caller may read, in order, each with how many topics it has, how many of them are new and the one
    written in last (its title, when and by whom, or None); whether the caller may make a zone, and whether they are
    signed in. Notes an account's first visit."""
    storage = _storage(request)
    caller = board_caller(request)
    readers = _readers(request, caller, note_visit=True)
    zones = []
    for found in storage.board.zones():
        if not rights(storage, caller, found).read:
            continue
        topics = storage.board.topics(found.id)
        new = sum(1 for listed in topics if readers.is_new(listed))
        newest = max(topics, key=lambda listed: listed.last_post_at, default=None)
        latest = None
        if newest is not None:
            latest = {
                "topic_id": newest.id,
                "title": newest.title,
                "at": newest.last_post_at,
                "author": readers.author(found, newest.last_author_id),
            }
        zones.append({**readers.zone_json(found), "topics": len(topics), "new_topics": new, "latest": latest})
    return {
        "zones": zones,
        "may_create": rights(storage, caller, Zone("", "")).manage_wide,
        "signed_in": caller.account is not None or caller.owner,
    }


@router.post("/api/board/zones", status_code=201)
def make_zone(request: Request, body: Annotated[Any, Body()]) -> dict:
    """A new zone, after the others: organisers make any, a campaign's host their campaign's."""
    caller = board_caller(request)
    try:
        made = board.create_zone(_storage(request), caller, _object(body), now_of(request))
    except PlayError as refused:
        raise refusal(refused) from None
    _changed(request, made.id)
    return {"zone": _readers(request, caller).zone_json(made)}


@router.patch("/api/board/zones/{zone_id}")
def change_zone(request: Request, zone_id: str, body: Annotated[Any, Body()]) -> dict:
    """Change some of the zone's fields, by who manages it."""
    caller = board_caller(request)
    try:
        changed = board.update_zone(_storage(request), caller, zone_id, _object(body), now_of(request))
    except PlayError as refused:
        raise refusal(refused) from None
    _changed(request, changed.id)
    return {"zone": _readers(request, caller).zone_json(changed)}


@router.delete("/api/board/zones/{zone_id}", status_code=204)
def delete_zone(request: Request, zone_id: str) -> Response:
    """Erase the zone with everything in it (organisers)."""
    try:
        board.delete_zone(_storage(request), board_caller(request), zone_id)
    except PlayError as refused:
        raise refusal(refused) from None
    _changed(request, zone_id)
    return Response(status_code=204)


@router.put("/api/board/order")
def order_zones(request: Request, body: Annotated[Any, Body()]) -> dict:
    """The zones in the order given, which names each once (organisers)."""
    zone_ids = _strings(body, "zone_ids")
    caller = board_caller(request)
    try:
        zones = board.reorder_zones(_storage(request), caller, zone_ids)
    except PlayError as refused:
        raise refusal(refused) from None
    for found in zones:
        _changed(request, found.id)
    readers = _readers(request, caller)
    return {"zones": [readers.zone_json(found) for found in zones]}


@router.get("/api/board/zones/{zone_id}")
def zone(request: Request, zone_id: str) -> dict:
    """The zone and its topics, pinned first, then the most recently written."""
    storage = _storage(request)
    caller = board_caller(request)
    try:
        found = board.readable_zone(storage, caller, zone_id)
    except PlayError as refused:
        raise refusal(refused) from None
    readers = _readers(request, caller, note_visit=True)
    topics = [readers.topic_json(found, listed) for listed in storage.board.topics(found.id)]
    return {"zone": readers.zone_json(found), "topics": topics}


# ----- moderators and members -----


def _person(storage: Storage, account_id: str) -> dict[str, Any]:
    account = storage.accounts.get(account_id)
    if account is None:
        return {"account_id": account_id, "display_name": "", "username": ""}
    return {"account_id": account.id, "display_name": account.profile.display_name, "username": account.username}


def _people(storage: Storage, found: Zone) -> dict[str, Any]:
    return {
        "moderators": [_person(storage, account_id) for account_id in found.moderators],
        "members": [_person(storage, account_id) for account_id in found.members],
    }


@router.get("/api/board/zones/{zone_id}/people")
def zone_people(request: Request, zone_id: str) -> dict:
    """The zone's moderators and members, by name and username, to who moderates it."""
    storage = _storage(request)
    caller = board_caller(request)
    try:
        found = board.readable_zone(storage, caller, zone_id)
    except PlayError as refused:
        raise refusal(refused) from None
    if not rights(storage, caller, found).moderate:
        status = 401 if caller.account is None and not caller.owner else 403
        raise HTTPException(status_code=status, detail="Only who moderates this zone sees who is in it.")
    return _people(storage, found)


@router.put("/api/board/zones/{zone_id}/moderators")
def name_moderators(request: Request, zone_id: str, body: Annotated[Any, Body()]) -> dict:
    """The accounts of these usernames as the zone's moderators (who manages it)."""
    usernames = _strings(body, "usernames")
    storage = _storage(request)
    try:
        changed = board.set_moderators(storage, board_caller(request), zone_id, usernames)
    except PlayError as refused:
        raise refusal(refused) from None
    _changed(request, changed.id)
    return _people(storage, changed)


@router.post("/api/board/zones/{zone_id}/members")
def let_in(request: Request, zone_id: str, body: Annotated[Any, Body()]) -> dict:
    """The account of this username among the zone's members (who moderates it)."""
    storage = _storage(request)
    try:
        changed = board.add_member(storage, board_caller(request), zone_id, _object(body).get("username"))
    except PlayError as refused:
        raise refusal(refused) from None
    _changed(request, changed.id)
    return _people(storage, changed)


@router.delete("/api/board/zones/{zone_id}/members/{account_id}")
def take_out(request: Request, zone_id: str, account_id: str) -> dict:
    """The account out of the zone's members (who moderates it): its next request there is 404."""
    storage = _storage(request)
    try:
        changed = board.remove_member(storage, board_caller(request), zone_id, account_id)
    except PlayError as refused:
        raise refusal(refused) from None
    _changed(request, changed.id)
    return _people(storage, changed)


# ----- topics -----


@router.post("/api/board/zones/{zone_id}/topics", status_code=201)
def start_topic(request: Request, zone_id: str, body: Annotated[Any, Body()]) -> dict:
    """A new topic in the zone, with its first post (who may write there)."""
    fields = _object(body)
    follow = _follow_asked(fields)
    storage = _storage(request)
    caller = board_caller(request)
    try:
        found = board.readable_zone(storage, caller, zone_id)
        _limit(request, caller)
        started, first = board.start_topic(
            storage, caller, zone_id, fields.get("title"), fields.get("text"), now_of(request)
        )
    except PlayError as refused:
        raise refusal(refused) from None
    if follow and first.author_id is not None:
        storage.board.follow(first.author_id, started.id)
    _changed(request, found.id, started.id)
    readers = _readers(request, caller)
    return {"topic": readers.one_topic_json(found, started), "post": readers.post_json(found, first)}


def _read_since(readers: _Readers, found: Topic) -> str | None:
    """Up to when the reader has read the topic: its read mark, else their first visit; None for a visitor."""
    return readers.marks.get(found.id, readers.first_visit)


def _first_unread_page(storage: Storage, readers: _Readers, found: Topic, pages: int) -> int:
    """The page of the first post the reader hasn't read; the last page of a topic they have read to its end, and the
    first of one they never opened with nothing new in it."""
    since = _read_since(readers, found)
    if since is not None and found.last_post_at > since:
        read = sum(1 for post in storage.board.posts(found.id, 0, found.posts) if post.created_at <= since)
        return min(read // POST_PAGE + 1, pages)
    return pages if found.id in readers.marks else 1


@router.get("/api/board/topics/{topic_id}")
def topic(request: Request, topic_id: str, page: Annotated[int | None, Query(ge=1)] = None) -> dict:
    """A page of the topic's posts, oldest first (past the last page, the last); without `page`, the first page with
    a post the caller hasn't read, and `first_unread_post` the first such post on the page shown (the page scrolls to
    it). For an account, reading marks the topic read up to the newest post on the page."""
    storage = _storage(request)
    caller = board_caller(request)
    try:
        found_zone, found = board.readable_topic(storage, caller, topic_id)
    except PlayError as refused:
        raise refusal(refused) from None
    readers = _readers(request, caller, note_visit=True)
    pages = max(1, math.ceil(found.posts / POST_PAGE))
    first_unread = _first_unread_page(storage, readers, found, pages)
    shown = min(page or first_unread, pages)
    posts = storage.board.posts(found.id, (shown - 1) * POST_PAGE, POST_PAGE)
    since = _read_since(readers, found)
    unread = next((post.id for post in posts if since is not None and post.created_at > since), None)
    if readers.reader is not None and posts:
        # A topic deleted a moment ago is nothing to mark: storage lets it be.
        storage.board.mark_read(readers.reader, found.id, max(post.created_at for post in posts))
    return {
        "zone": readers.zone_json(found_zone),
        "topic": readers.one_topic_json(found_zone, found),
        "posts": [readers.post_json(found_zone, post) for post in posts],
        "page": shown,
        "pages": pages,
        "first_unread_page": first_unread,
        "first_unread_post": unread,
    }


@router.patch("/api/board/topics/{topic_id}")
def change_topic(request: Request, topic_id: str, body: Annotated[Any, Body()]) -> dict:
    """Pin or unpin, lock or unlock the topic (who moderates)."""
    fields = _object(body)
    for which in ("pinned", "locked"):
        if fields.get(which) is not None and not isinstance(fields[which], bool):
            raise HTTPException(status_code=422, detail=f"Send {which} as true or false.")
    caller = board_caller(request)
    try:
        changed = board.set_topic(
            _storage(request), caller, topic_id, pinned=fields.get("pinned"), locked=fields.get("locked")
        )
    except PlayError as refused:
        raise refusal(refused) from None
    found_zone = _zone_of(request, changed.zone_id)
    _changed(request, found_zone.id, changed.id)
    return {"topic": _readers(request, caller).one_topic_json(found_zone, changed)}


@router.delete("/api/board/topics/{topic_id}", status_code=204)
def delete_topic(request: Request, topic_id: str) -> Response:
    """Erase the topic with its posts (who moderates)."""
    storage = _storage(request)
    caller = board_caller(request)
    try:
        found_zone, _ = board.readable_topic(storage, caller, topic_id)
        board.delete_topic(storage, caller, topic_id)
    except PlayError as refused:
        raise refusal(refused) from None
    _changed(request, found_zone.id, topic_id)
    return Response(status_code=204)


def _set_following(request: Request, topic_id: str, follow: bool) -> dict:
    """Follow the topic or stop: an account (the owner by token as the owner's account) who may read it; 401 for a
    visitor. Following works whether or not Delve sends mail now."""
    storage = _storage(request)
    caller = board_caller(request)
    try:
        board.readable_topic(storage, caller, topic_id)
    except PlayError as refused:
        raise refusal(refused) from None
    reader = board.author_of(storage, caller)
    if reader is None:
        raise HTTPException(status_code=401, detail="Log in to follow a topic.")
    if follow:
        storage.board.follow(reader, topic_id)
    else:
        storage.board.unfollow(reader, topic_id)
    return {"following": storage.board.following(reader, topic_id)}


@router.put("/api/board/topics/{topic_id}/follow")
def follow_topic(request: Request, topic_id: str) -> dict:
    """Follow the topic: an email for a new reply, then none until the reader comes back to it (DEL-314)."""
    return _set_following(request, topic_id, True)


@router.delete("/api/board/topics/{topic_id}/follow")
def unfollow_topic(request: Request, topic_id: str) -> dict:
    """Stop following the topic."""
    return _set_following(request, topic_id, False)


# ----- posts -----


def _post_answer(request: Request, caller: Caller, post: Post) -> dict:
    """`{post}` for a post just written or changed, once the zone's readers are told."""
    found = _storage(request).board.get_topic(post.topic_id)
    if found is None:
        raise HTTPException(status_code=404, detail=board.NO_TOPIC)
    found_zone = _zone_of(request, found.zone_id)
    _changed(request, found_zone.id, found.id)
    return {"post": _readers(request, caller).post_json(found_zone, post)}


@router.post("/api/board/topics/{topic_id}/posts", status_code=201)
def reply(request: Request, topic_id: str, body: Annotated[Any, Body()]) -> dict:
    """A reply in the topic (who may write there; in a locked topic, who moderates); with `"follow": true` its author
    follows the topic. The topic's followers' emails are queued, not sent: the reply doesn't wait on mail."""
    fields = _object(body)
    follow = _follow_asked(fields)
    storage = _storage(request)
    caller = board_caller(request)
    now = now_of(request)
    try:
        _, found = board.readable_topic(storage, caller, topic_id)
        _limit(request, caller)
        post = board.reply(storage, caller, topic_id, fields.get("text"), now)
    except PlayError as refused:
        raise refusal(refused) from None
    if follow and post.author_id is not None:
        storage.board.follow(post.author_id, found.id)
    answer = _post_answer(request, caller, post)
    try:
        board_mail.notify(storage, request.app.state.config.data_dir, found, post, post.author_id, now)
    except Exception:
        # The reply is saved and its readers told: a failure in mail must not turn it into an error to post again.
        log.exception("board mail for %s", post.id)
    return answer


@router.patch("/api/board/posts/{post_id}")
def edit_post(request: Request, post_id: str, body: Annotated[Any, Body()]) -> dict:
    """New words for the post, marked edited (its author)."""
    text = _object(body).get("text")
    storage = _storage(request)
    caller = board_caller(request)
    try:
        board.readable_post(storage, caller, post_id)
        _limit(request, caller)
        post = board.edit_post(storage, caller, post_id, text, now_of(request))
    except PlayError as refused:
        raise refusal(refused) from None
    return _post_answer(request, caller, post)


@router.delete("/api/board/posts/{post_id}")
def delete_post(request: Request, post_id: str) -> dict:
    """The post removed, keeping its place (its author, or who moderates)."""
    caller = board_caller(request)
    try:
        post = board.delete_post(_storage(request), caller, post_id, now_of(request))
    except PlayError as refused:
        raise refusal(refused) from None
    return _post_answer(request, caller, post)


@router.post("/api/board/posts/{post_id}/picture")
async def attach_picture(request: Request, post_id: str) -> dict:
    """The body is the picture, one of `TALK_PICTURE_TYPES` (the guard refuses others with 415) of at most
    `TALK_PICTURE_LIMIT` bytes (413): it goes into the post, in place of any it had (its author, while the zone takes
    pictures: 403 otherwise). 400 for bytes that aren't the type sent, 422 past its pixels, 503 while busy. An upload
    counts as a post against `POSTS_PER_MINUTE`."""
    storage = _storage(request)
    caller = board_caller(request)
    try:
        # Who may not attach a picture here costs no reading and no decoding.
        board.readable_post(storage, caller, post_id)
        _limit(request, caller)
        board.may_attach(storage, caller, post_id)
    except PlayError as refused:
        raise refusal(refused) from None
    media_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > TALK_PICTURE_LIMIT:
            raise HTTPException(status_code=413, detail=f"A picture may be at most {TALK_PICTURE_LIMIT} bytes.")
    try:
        made = await run_in_threadpool(talk_picture, bytes(data), media_type)
        post = await run_in_threadpool(board.attach_picture, storage, caller, post_id, made)
    except PlayError as refused:
        raise refusal(refused) from None
    return _post_answer(request, caller, post)


@router.delete("/api/board/posts/{post_id}/picture")
def take_down_picture(request: Request, post_id: str) -> dict:
    """The post without its picture (its author, or who moderates)."""
    caller = board_caller(request)
    try:
        post = board.take_down_picture(_storage(request), caller, post_id)
    except PlayError as refused:
        raise refusal(refused) from None
    return _post_answer(request, caller, post)


def _has(request: Request, tag: str) -> bool:
    """Whether the browser has the version `tag` names already."""
    return tag in {t.strip() for t in request.headers.get("if-none-match", "").split(",")}


@router.get("/api/board/posts/{post_id}/picture")
def picture(request: Request, post_id: str) -> Response:
    """The post's picture, to whoever may read the zone; 404 for none. Read again on every view (no-cache), so a
    picture taken down, or a zone closed, shows at once, but its ETag answers 304 to a browser that has it."""
    storage = _storage(request)
    try:
        _, _, post = board.readable_post(storage, board_caller(request), post_id)
    except PlayError as refused:
        raise refusal(refused) from None
    shown = post.picture
    data = storage.blobs.get(shown["blob"]) if shown is not None else None
    if shown is None or data is None:
        raise HTTPException(status_code=404, detail=NO_PICTURE)
    tag = f'"{shown["blob"]}"'
    if _has(request, tag):
        return Response(status_code=304, headers={"ETag": tag, "Cache-Control": NO_CACHE})
    response = attachment_response(data, shown.get("mime") or "image/webp")
    response.headers["Cache-Control"] = NO_CACHE
    response.headers["ETag"] = tag
    return response


@router.get("/api/board/posts/{post_id}/avatar")
def avatar(request: Request, post_id: str) -> Response:
    """The uploaded avatar of the post's author, to whoever may read the zone, visitors too (the board's one exception
    to a profile's privacy); 404 without one. No-cache with an ETag, as a post's picture."""
    storage = _storage(request)
    try:
        _, _, post = board.readable_post(storage, board_caller(request), post_id)
    except PlayError as refused:
        raise refusal(refused) from None
    account = storage.accounts.get(post.author_id) if post.author_id is not None else None
    sha = account.profile.avatar_sha if account is not None else None
    data = storage.blobs.get(sha) if sha else None
    if data is None:
        raise HTTPException(status_code=404, detail=NO_AVATAR)
    tag = f'"{sha}"'
    if _has(request, tag):
        return Response(status_code=304, headers={"ETag": tag, "Cache-Control": NO_CACHE})
    headers = {"X-Content-Type-Options": "nosniff", "Cache-Control": NO_CACHE, "ETag": tag}
    return Response(data, media_type=AVATAR_TYPE, headers=headers)
