# The Message Board Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A bulletin-board message board in Delve (DEL-297): zones the owner sets up, each with its own read and write
rights, topics anyone allowed can start, and forum posts with formatting, quotes and (per zone) pictures.

**Architecture:** One new storage repository (`storage.board`) over five new tables (migration 0042); one rights
function (`delve.play.board_rights.rights`) that every route and the events stream ask; the board's rules in
`delve.play.board`; JSON routes under `/api/board` (`delve.web.routes.board`); a `board` event scope. The web pages
live outside the app shell, like `/help`, so visitors can read open zones.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy Core + Alembic on SQLite, pytest; React 18 + TypeScript, TanStack
Query, react-router, markdown-it, vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-10-29-message-board-design.md` (read it first; this plan argues from it).

## Global Constraints

- Migration is **0042** (`0042_board`, revises `0041_monster_pictures`); re-check the next free number on master
  before merging. Plain `op.create_table` only; no batch rebuild of any existing table.
- Levels, widest first: `everybody`, `accounts`, `members`, `table`. `everybody` is never a write level.
- Write is the read level or narrower: when read is `everybody`, write is `accounts`, `members` or `table`; when read is
  `accounts`, write is `accounts`, `members` or `table`; when read is `members` or `table`, write equals read. `table`
  (as read or write) needs `campaign_id`.
- At most one zone per campaign (`campaign_id` unique).
- A campaign's host (not co-hosts) manages that campaign's zone but may set read and write only to `table` or
  `members`, and may not change `campaign_id`. Opening wider or untying is organisers' alone.
- Posts and topics are never translated and never go into any prompt.
- Visible author data on a post: `display_name`, `avatar` (as `profiles.summary` gives it), `colour`, and role badges.
  Never `about` or `pronouns`. Avatars are served by a board route, never by widening `/api/profiles/{id}/avatar`.
- Refusals: 401 for a visitor where an account is needed, 403 for an account without the right, 404 for anything the
  caller may not read, 409 for state (a locked topic, an edit of a removed post), 422 for bad input, 429 for too many.
- Limits: zone name 1–80, description 0–500, topic title 1–120, post 1–20 000 characters (after stripping), at most
  `POSTS_PER_MINUTE = 6` posts and topics per account a minute, posts paged `POST_PAGE = 30`.
- Pictures go through `delve.play.talk_pictures.talk_picture` (its types and `TALK_PICTURE_LIMIT`).
- Every web string in `web/src/i18n/{en,nl,fr,de,lv}.json`; French uses *vous*.
- No Prettier run over whole files (no config; it rewraps at 80). Match the 120-column style around you.
- Code reads like its neighbours: module docstrings that say what and why, `PlayError` refusals with hints, `*_json`
  helpers in routes.

## Review Focus

1. **A post's Markdown carrying script or off-site loads** (`<script>`, `<img onerror>`, `[x](javascript:…)`,
   `![](https://elsewhere/track.png)`): expected to render as inert text, links only to http(s)/mailto, no images
   from Markdown at all. Pinned in Task 6.
2. **Probing a zone one may not read**: its topics, a topic, a post's picture or avatar, the board's counts, or its
   events. Expected: 404 everywhere, absent from `/api/board`, and no `board` event. Pinned in Tasks 4 and 5.
3. **Losing access while a page is open**: a member removed, a player who leaves the table, an account disabled.
   Expected: the next request is 404 and no further events reach them. Pinned in Tasks 2 and 5.
4. **Acting on something that changed under you**: replying to a topic locked a moment ago, editing a post a moderator
   just removed, quoting a removed post. Expected: 409 with a clear message; the quote button is absent on removed
   posts. Pinned in Tasks 3 and 7.
5. **The owner by token, with no account**: posting must still have an author. Expected: the owner account's id when
   one exists, else `author_id = None` shown as the owner's name (`"Owner"`, translated). Pinned in Task 3.

---

## File Structure

- Create `src/delve/domain/board.py`: `Level`, `LEVELS`, `Zone`, `Topic`, `Post`.
- Modify `src/delve/storage/interfaces.py`: `BoardRepository` protocol; `board: BoardRepository` on `Storage`.
- Modify `src/delve/storage/sqlite/tables.py`: `board_zones`, `board_topics`, `board_posts`, `board_reads`.
- Create `src/delve/storage/migrations/versions/0042_board.py`.
- Create `src/delve/storage/sqlite/board_repo.py`: `SqliteBoardRepository`; wire in `src/delve/storage/sqlite/__init__.py`.
- Create `src/delve/play/board_rights.py`: `Caller`, `Rights`, `rights`, `may_write_levels`.
- Create `src/delve/play/board.py`: the board's rules (zones, people, topics, posts, pictures, new marks).
- Create `src/delve/web/routes/board.py`; modify `src/delve/web/app.py` (router), `src/delve/web/guard.py` (picture
  upload path), `src/delve/web/routes/campaigns.py` (untie on delete), `src/delve/web/events.py` (`board` scope).
- Create `web/src/board/`: `api.ts`, `markdown.ts`, `BoardFrame.tsx`, `BoardIndex.tsx`, `ZonePage.tsx`,
  `TopicPage.tsx`, `PostEditor.tsx`, `ZoneSettings.tsx`, `board.css`, and their tests.
- Modify `web/src/App.tsx`, `web/src/components/Nav.tsx`, `web/src/landing/Landing.tsx`, `web/src/help/HelpPages.tsx`,
  `web/src/play/TablePanel.tsx` (the table's Board link), `web/src/i18n/*.json`.
- Create `web/e2e/yz-board.spec.ts` (sorts after `y-talk-pictures.spec.ts`, before `zz-faithful.spec.ts`).

---

### Task 1: Board storage

**Files:**
- Create: `src/delve/domain/board.py`, `src/delve/storage/sqlite/board_repo.py`,
  `src/delve/storage/migrations/versions/0042_board.py`
- Modify: `src/delve/storage/interfaces.py`, `src/delve/storage/sqlite/tables.py`, `src/delve/storage/sqlite/__init__.py`
- Test: `tests/storage/contract.py` (add to the contract suite), `tests/storage/test_migrations.py` (if it lists heads)

**Interfaces:**
- Produces, in `delve.domain.board`:
  - `Level = Literal["everybody", "accounts", "members", "table"]`, `LEVELS: tuple[Level, ...]` in that order.
  - `Removed = Literal["author", "moderator"]`
  - `@dataclass(frozen=True) Zone(id: str, name: str, description: str = "", position: int = 0, read: Level =
    "accounts", write: Level = "accounts", pictures: bool = False, campaign_id: str | None = None, moderators:
    tuple[str, ...] = (), members: tuple[str, ...] = (), created_at: str = "")` (moderators and members are account ids)
  - `@dataclass(frozen=True) Topic(id: str, zone_id: str, title: str, author_id: str | None, created_at: str,
    last_post_at: str, last_author_id: str | None, posts: int = 1, pinned: bool = False, locked: bool = False)`
  - `@dataclass(frozen=True) Post(id: str, topic_id: str, author_id: str | None, text: str, created_at: str,
    edited_at: str | None = None, removed: Removed | None = None, picture: dict[str, Any] | None = None)`
    (`picture` is `{"blob", "mime", "width", "height"}`)
- Produces `BoardRepository` (on `Storage` as `board`), ids from `new_id("bzn")`, `new_id("btp")`, `new_id("bps")`:
  - `create_zone(zone: Zone) -> Zone` — stores it with a fresh id when `zone.id == ""` and `position` after the last;
    `ValueError` when another zone has its `campaign_id`.
  - `get_zone(id: str) -> Zone | None`, `zones() -> list[Zone]` (by `position`), `zone_of_campaign(campaign_id: str) -> Zone | None`
  - `save_zone(zone: Zone) -> Zone` (`KeyError` unknown, `ValueError` campaign taken), `delete_zone(id: str) -> None`
    (its topics, posts and read marks go too)
  - `add_topic(topic: Topic, first: Post) -> tuple[Topic, Post]` — both stored with fresh ids, in one transaction
  - `get_topic(id: str) -> Topic | None`, `topics(zone_id: str) -> list[Topic]` (pinned first, then `last_post_at`
    newest first), `save_topic(topic: Topic) -> Topic`, `delete_topic(id: str) -> None` (its posts and marks too)
  - `add_post(post: Post) -> Post` — fresh id; the topic's `last_post_at`, `last_author_id` and `posts` follow, in
    the same transaction
  - `get_post(id: str) -> Post | None`, `posts(topic_id: str, offset: int = 0, limit: int = 30) -> list[Post]`
    (oldest first), `post_index(post: Post) -> int` (its 0-based place in its topic), `save_post(post: Post) -> Post`
  - `mark_read(account_id: str, topic_id: str, at: str) -> None` (keeps the later of the stored and `at`),
    `read_marks(account_id: str) -> dict[str, str]` (topic id → newest read post time)
  - `first_visit(account_id: str) -> str | None`, `set_first_visit(account_id: str, at: str) -> None` (only if unset)

- [ ] **Step 1: Write the failing contract tests** in `tests/storage/contract.py`, registered in `CONTRACT` as the
  others are:

```python
def test_board_zones(storage: Storage) -> None:
    a = storage.board.create_zone(Zone("", "The engine", read="everybody", write="accounts", created_at=AT))
    b = storage.board.create_zone(Zone("", "OSRIC", created_at=AT))
    assert a.id.startswith("bzn_") and (a.position, b.position) == (0, 1)
    assert [z.name for z in storage.board.zones()] == ["The engine", "OSRIC"]
    storage.board.save_zone(replace(b, position=-1, moderators=("acc_1",), members=("acc_2",)))
    assert [z.name for z in storage.board.zones()] == ["OSRIC", "The engine"]
    assert storage.board.get_zone(b.id).members == ("acc_2",)

def test_board_one_zone_per_campaign(storage: Storage) -> None:
    campaign = make_campaign(storage)  # the suite's existing helper
    storage.board.create_zone(Zone("", "Our table", read="table", write="table", campaign_id=campaign.id, created_at=AT))
    assert storage.board.zone_of_campaign(campaign.id).name == "Our table"
    with pytest.raises(ValueError):
        storage.board.create_zone(Zone("", "Again", campaign_id=campaign.id, created_at=AT))

def test_board_topics_and_posts(storage: Storage) -> None:
    zone = storage.board.create_zone(Zone("", "The engine", created_at=AT))
    topic, first = storage.board.add_topic(Topic("", zone.id, "Morale", "acc_1", AT, AT, "acc_1"), Post("", "", "acc_1", "Hi", AT))
    assert first.topic_id == topic.id and topic.posts == 1
    storage.board.add_post(Post("", topic.id, "acc_2", "Yes", LATER))
    again = storage.board.get_topic(topic.id)
    assert (again.posts, again.last_post_at, again.last_author_id) == (2, LATER, "acc_2")
    assert [p.text for p in storage.board.posts(topic.id)] == ["Hi", "Yes"]
    pinned, _ = storage.board.add_topic(Topic("", zone.id, "Rules", "acc_1", AT, AT, "acc_1", pinned=True), Post("", "", "acc_1", "x", AT))
    assert [t.title for t in storage.board.topics(zone.id)] == ["Rules", "Morale"]
    storage.board.delete_zone(zone.id)
    assert storage.board.get_topic(topic.id) is None and storage.board.get_post(first.id) is None

def test_board_read_marks(storage: Storage) -> None:
    storage.board.mark_read("acc_1", "btp_x", LATER)
    storage.board.mark_read("acc_1", "btp_x", AT)
    assert storage.board.read_marks("acc_1") == {"btp_x": LATER}
    storage.board.set_first_visit("acc_1", AT)
    storage.board.set_first_visit("acc_1", LATER)
    assert storage.board.first_visit("acc_1") == AT
```

  (`AT`/`LATER` are ISO times; use the suite's own constants if it has them.)

- [ ] **Step 2: Run** `uv run pytest -q tests/storage/test_sqlite.py -k contract` — expect FAIL (`Storage` has no `board`).

- [ ] **Step 3: Implement.** Dataclasses and protocol as above. Tables: `board_zones` (id PK, name, description,
  position Integer, read, write, pictures Boolean, campaign_id nullable FK → `campaigns.id` `ondelete="SET NULL"`,
  moderators JSON, members JSON, created_at; unique index on campaign_id), `board_topics` (FK zone_id → board_zones
  `ondelete="CASCADE"`, index on zone_id), `board_posts` (FK topic_id → board_topics CASCADE, `picture` JSON nullable,
  index on topic_id), `board_reads` (account_id, topic_id, at; PK both; topic_id FK CASCADE) and `board_visits`
  (account_id PK, first_at). No FKs to `accounts` (author ids may outlive accounts). The migration creates the same,
  `down_revision = "0041_monster_pictures"`. Repository after `join_requests_repo.py`'s shape; foreign-key cascades
  need SQLite's `PRAGMA foreign_keys` — check `db.py` turns it on, else delete children explicitly.

- [ ] **Step 4: Run** `uv run pytest -q tests/storage` — expect PASS, including `test_interface_parity.py` (the
  protocol and the repository must match exactly) and the migration tests.

- [ ] **Step 5: Commit** `Board: zones, topics, posts and read marks in storage (DEL-297)`.

---

### Task 2: Who may do what

**Files:**
- Create: `src/delve/play/board_rights.py`
- Test: `tests/play/test_board_rights.py`

**Interfaces:**
- Consumes: `Zone`, `LEVELS` (Task 1); `storage.seats.for_account(account_id, campaign_id) -> Seat | None` (live seat).
- Produces:
  - `@dataclass(frozen=True) Caller(account: Account | None = None, organiser: bool = False, owner: bool = False)`;
    `VISITOR = Caller()`.
  - `@dataclass(frozen=True) Rights(read: bool, write: bool, moderate: bool, manage: bool, manage_wide: bool)` —
    `manage_wide` is levels wider than `table`/`members` and `campaign_id`: organisers only.
  - `rights(storage: Storage, caller: Caller, zone: Zone) -> Rights`
  - `valid_levels(read: Level, write: Level, campaign_id: str | None) -> str | None` — None when allowed, else the
    refusal's message (Global Constraints' rule).
  - `badges(storage: Storage, zone: Zone, account_id: str | None) -> list[str]` — any of `"organiser"`, `"moderator"`,
    `"host"`, `"cohost"`, for a post's author.
  - `caller_of(account: Account | None, organiser: bool, owner: bool) -> Caller` — the one mapping from a principal's
    parts to a `Caller` (a disabled account becomes `VISITOR`); Task 4's `board_caller` and Task 5's events use it.

- [ ] **Step 1: Write the failing tests**, one per row of the spec's "Rights, in one place", for example:

```python
def test_a_visitor_reads_an_everybody_zone_and_writes_nowhere(storage):
    zone = Zone("bzn_1", "Engine", read="everybody", write="accounts")
    assert rights(storage, VISITOR, zone) == Rights(read=True, write=False, moderate=False, manage=False, manage_wide=False)

def test_an_account_writes_an_accounts_zone_but_moderates_nothing(storage, ana): ...
def test_a_members_zone_is_its_members_and_moderators_only(storage, ana, bo): ...
def test_a_table_zone_reads_for_observers_and_writes_for_players_and_hosts(storage, campaign_with_seats): ...
def test_a_player_who_left_the_table_reads_nothing_there(storage, campaign_with_seats): ...
def test_a_disabled_account_is_a_visitor(storage, ana): ...
def test_an_organiser_does_everything_everywhere(storage, organiser): ...
def test_the_host_manages_their_campaigns_zone_but_not_wide(storage, campaign_with_seats):
    r = rights(storage, Caller(host_account), table_zone)
    assert (r.read, r.write, r.moderate, r.manage, r.manage_wide) == (True, True, True, True, False)
def test_a_cohost_moderates_but_does_not_manage(storage, campaign_with_seats): ...

@pytest.mark.parametrize(("read", "write", "campaign", "ok"), [
    ("everybody", "accounts", None, True), ("everybody", "everybody", None, False),
    ("accounts", "members", None, True), ("members", "accounts", None, False),
    ("members", "table", "cmp_1", False), ("table", "table", None, False), ("table", "table", "cmp_1", True),
])
def test_valid_levels(read, write, campaign, ok):
    assert (valid_levels(read, write, campaign) is None) == ok
```

- [ ] **Step 2: Run** `uv run pytest -q tests/play/test_board_rights.py` — expect FAIL (import error).
- [ ] **Step 3: Implement** in `board_rights.py`. A disabled account (`account.disabled_at`) counts as a visitor.
  Hosts are `role == "host"`, co-hosts `"cohost"`, seated players `"player"`, observers `"observer"`; a seat counts
  only while `left_at is None` (`for_account` already gives the live seat). Moderate = organiser, moderator, host or
  co-host of the tied campaign; manage = organiser or that host; manage_wide = organiser. Write needs `caller.account`
  or `caller.owner`.
- [ ] **Step 4: Run** the tests — expect PASS.
- [ ] **Step 5: Commit** `Board: one function says who may read, write, moderate and manage a zone (DEL-297)`.

---

### Task 3: The board's rules

**Files:**
- Create: `src/delve/play/board.py`
- Test: `tests/play/test_board.py`

**Interfaces:**
- Consumes: Tasks 1–2; `delve.play.talk_pictures.TalkPicture`; `delve.play.context.PlayError`, `NotFound`;
  `storage.accounts.by_username`, `storage.blobs.put(data, mime) -> str`.
- Produces (every function takes `storage: Storage, caller: Caller` first, and `now: datetime` where it writes):
  - Errors: `BoardRefused(PlayError)` (→ 403), `BoardConflict(PlayError)` (→ 409), `NotFound` (→ 404), plain
    `PlayError` (→ 422). A caller without an account where one is needed gets `NeedsAccount(BoardRefused)` (→ 401).
  - `readable_zone(storage, caller, zone_id) -> Zone` (NotFound when unknown or unreadable); `readable_topic(...,
    topic_id) -> tuple[Zone, Topic]`; `readable_post(..., post_id) -> tuple[Zone, Topic, Post]`.
  - `create_zone(storage, caller, fields: dict[str, Any], now) -> Zone`; `update_zone(storage, caller, zone_id, fields,
    now) -> Zone` — `fields` may hold `name`, `description`, `read`, `write`, `pictures`, `campaign_id`. Organisers
    create any zone; a host creates only their campaign's, with levels `table`/`members`.
  - `reorder_zones(storage, caller, zone_ids: list[str]) -> list[Zone]` (organisers; ids must be every zone once).
  - `delete_zone(storage, caller, zone_id) -> None` (organisers).
  - `set_moderators(storage, caller, zone_id, usernames: list[str]) -> Zone` (manage); `add_member(storage, caller,
    zone_id, username: str) -> Zone` and `remove_member(storage, caller, zone_id, account_id: str) -> Zone` (moderate).
    Unknown username → `PlayError("No account has that username.")`.
  - `start_topic(storage, caller, zone_id, title: str, text: str, now) -> tuple[Topic, Post]`
  - `reply(storage, caller, topic_id, text: str, now) -> Post` — `BoardConflict` on a locked topic unless moderate.
  - `edit_post(storage, caller, post_id, text: str, now) -> Post` — the author only; `BoardConflict` once removed.
  - `delete_post(storage, caller, post_id, now) -> Post` — the author (`removed="author"`) or who moderates
    (`removed="moderator"`); text becomes `""` and `picture` None.
  - `attach_picture(storage, caller, post_id, picture: TalkPicture) -> Post` — the author, while the zone's
    `pictures` is on and the post isn't removed; replaces any picture. `take_down_picture(storage, caller, post_id)
    -> Post` — the author or who moderates.
  - `set_topic(storage, caller, topic_id, *, pinned: bool | None = None, locked: bool | None = None) -> Topic`
    (moderate); `delete_topic(storage, caller, topic_id) -> None` (moderate).
  - `author_of(storage, caller) -> str | None` — the account's id; for the owner by token, the first owner account's
    id, else None.
  - `is_new(topic: Topic, marks: dict[str, str], first_visit: str | None) -> bool` — new when the topic's
    `last_post_at` is after its mark, or, without a mark, after `first_visit` (no first visit: not new).
  - `visit(storage, caller, now) -> str | None` — records and returns the account's first board visit.
  - `untie_campaign(storage, campaign_id) -> None` — the campaign's zone loses `campaign_id`, and a `table` level
    becomes `members`.
  - Limits as Global Constraints: `NAME_CHARS = 80`, `DESCRIPTION_CHARS = 500`, `TITLE_CHARS = 120`,
    `POST_CHARS = 20_000`.

- [ ] **Step 1: Write the failing tests**, including Review Focus 4 and 5:

```python
def test_anyone_who_may_write_starts_a_topic(storage, ana, engine_zone): ...
def test_a_visitor_may_not_start_one(storage, engine_zone):
    with pytest.raises(NeedsAccount):
        start_topic(storage, VISITOR, engine_zone.id, "Hi", "Hello", NOW)
def test_a_zone_one_may_not_read_is_not_found(storage, bo, members_zone):
    with pytest.raises(NotFound):
        start_topic(storage, Caller(bo), members_zone.id, "Hi", "Hello", NOW)
def test_titles_and_posts_are_stripped_and_bounded(storage, ana, engine_zone):
    for title, text in (("   ", "x"), ("x", " \n "), ("x" * 121, "y"), ("x", "y" * 20_001)):
        with pytest.raises(PlayError):
            start_topic(storage, Caller(ana), engine_zone.id, title, text, NOW)
def test_a_locked_topic_takes_no_reply_but_a_moderators(storage, ana, moderator, topic):
    set_topic(storage, Caller(moderator), topic.id, locked=True)
    with pytest.raises(BoardConflict):
        reply(storage, Caller(ana), topic.id, "late", NOW)
    assert reply(storage, Caller(moderator), topic.id, "closing note", NOW).text == "closing note"
def test_a_removed_post_cannot_be_edited(storage, ana, moderator, topic, anas_post):
    delete_post(storage, Caller(moderator), anas_post.id, NOW)
    with pytest.raises(BoardConflict):
        edit_post(storage, Caller(ana), anas_post.id, "again", NOW)
def test_deleting_keeps_the_place_and_says_by_whom(storage, ana, moderator, anas_post):
    own = delete_post(storage, Caller(ana), anas_post.id, NOW)
    assert (own.text, own.picture, own.removed) == ("", None, "author")
def test_editing_is_the_authors_and_marks_the_time(storage, ana, bo, anas_post): ...
def test_pictures_need_the_zones_option(storage, ana, anas_post, picture): ...
def test_the_owner_by_token_posts_as_the_owner_account_or_none(storage, engine_zone):
    owner = Caller(organiser=True, owner=True)
    assert start_topic(storage, owner, engine_zone.id, "Hi", "x", NOW)[1].author_id is None
    account = make_account(storage, "raf", owner=True)
    assert start_topic(storage, owner, engine_zone.id, "Hi", "x", NOW)[1].author_id == account.id
def test_a_host_makes_their_tables_zone_but_cannot_open_it(storage, host, campaign): ...
def test_new_marks_start_at_the_first_visit(storage, ana, topic): ...
def test_untying_a_deleted_campaigns_zone_makes_it_members(storage, campaign, table_zone): ...
def test_moderators_add_members_by_username(storage, moderator, members_zone, bo): ...
```

- [ ] **Step 2: Run** `uv run pytest -q tests/play/test_board.py` — expect FAIL.
- [ ] **Step 3: Implement** `board.py`, with a module docstring after `join_requests.py`'s. Every function decides
  through `board_rights.rights`; unreadable is always `NotFound`, never `BoardRefused`. Text is stored as given
  (after `.strip()`), never rendered here.
- [ ] **Step 4: Run** the tests — expect PASS.
- [ ] **Step 5: Commit** `Board: zones, topics, posts, moderators and members, by the zone's rights (DEL-297)`.

---

### Task 4: The board's API

**Files:**
- Create: `src/delve/web/routes/board.py`
- Modify: `src/delve/web/app.py` (include the router), `src/delve/web/guard.py` (`BOARD_PICTURE_PATH =
  re.compile(r"/api/board/posts/[^/]+/picture")`, checked with `talk_picture_refusal` for POST),
  `src/delve/web/routes/campaigns.py` (`delete_campaign` calls `board.untie_campaign` before deleting)
- Test: `tests/web/test_board_api.py`

**Interfaces:**
- Consumes: Task 3's functions and errors; `delve.web.auth.identify`; `profiles.summary`; `talk_picture`.
- Produces `board_caller(request: Request) -> Caller` (from `identify`: an account principal → `Caller(account,
  organiser="organiser" in roles, owner=account.owner)`; the owner token or this machine → `Caller(None, True, True)`;
  an organiser seat → `Caller(None, True, False)`; anything else, and nobody → `VISITOR`), and these routes. JSON
  shapes, which Task 6's types copy:
  - `zone_json`: `{id, name, description, position, read, write, pictures, campaign_id, rights: {read, write,
    moderate, manage, manage_wide}}`
  - `topic_json`: `{id, zone_id, title, author, created_at, last_post_at, last_author, posts, pinned, locked, new}`
  - `post_json`: `{id, topic_id, author, text, created_at, edited_at, removed, picture: {width, height} | null,
    mine}` where `author` is `{account_id, display_name, avatar, colour, badges}` (`display_name` `""` and
    `account_id` null for the owner by token: the web shows "Owner"; a deleted account shows "A former member").
  - `GET /api/board` → `{zones: [zone_json + {topics, new_topics}], may_create: bool, signed_in: bool}`
  - `POST /api/board/zones` (201) `{zone}`; `PATCH /api/board/zones/{id}` `{zone}`; `DELETE` (204);
    `PUT /api/board/order` `{zone_ids}` → `{zones}`
  - `GET /api/board/zones/{id}/people` → `{moderators: [person], members: [person]}` (moderate), person `{account_id,
    display_name, username}`; `PUT …/moderators` `{usernames}`; `POST …/members` `{username}`; `DELETE
    …/members/{account_id}`
  - `GET /api/board/zones/{id}` → `{zone, topics: [topic_json]}`; `POST /api/board/zones/{id}/topics` `{title, text}`
    (201) → `{topic, post}`
  - `GET /api/board/topics/{id}?page=N` → `{zone, topic, posts, page, pages, first_unread_page}`; reading marks it
    read up to the newest post on the page given, for an account. Without `page`, the first unread page.
  - `PATCH /api/board/topics/{id}` `{pinned?, locked?}`; `DELETE` (204); `POST …/posts` `{text}` (201) `{post}`
  - `PATCH /api/board/posts/{id}` `{text}`; `DELETE` → `{post}`; `POST …/picture` (raw body) → `{post}`; `DELETE
    …/picture` → `{post}`; `GET …/picture` (image, `Cache-Control: private, no-cache`, ETag the blob, as
    `talk_picture_bytes`); `GET …/avatar` (the author's uploaded avatar; 404 without one, or unreadable)
  - Writes count against `POSTS_PER_MINUTE` per account (topics, replies, edits), 429 past it, in the style of
    `profiles.py`'s avatar throttle.
  - Each write publishes `board` (Task 5): `{"zone_id", "topic_id"?}`; zone changes and deletes publish
    `{"zone_id"}`, which everyone re-reads `/api/board` on.

- [ ] **Step 1: Write the failing tests** with the `tests/web/conftest.py` fixtures (`app`, `local` = owner,
  `make_account`, `log_in`, `session_for`), including Review Focus 2 and 3:

```python
def test_a_visitor_reads_an_open_zone_and_is_told_to_log_in(app, local):
    zone = make_zone(local, read="everybody", write="accounts")
    visitor = TestClient(app, base_url=BASE_URL)  # no login, not this machine
    assert visitor.get(f"/api/board/zones/{zone}").status_code == 200
    assert visitor.post(f"/api/board/zones/{zone}/topics", json={"title": "Hi", "text": "x"}).status_code == 401

def test_nothing_of_a_closed_zone_shows_to_who_may_not_read_it(app, local, storage):
    zone = make_zone(local, read="members", write="members")
    topic, post = start(local, zone, with_picture=True)
    bo = logged_in(app, storage, "bo")
    assert zone not in [z["id"] for z in bo.get("/api/board").json()["zones"]]
    for path in (f"zones/{zone}", f"topics/{topic}", f"posts/{post}/picture", f"posts/{post}/avatar"):
        assert bo.get(f"/api/board/{path}").status_code == 404, path

def test_a_member_taken_out_loses_the_zone_at_once(app, local, storage): ...
def test_a_post_shows_name_face_and_badges_but_not_the_profile(app, local, storage):
    post = ...  # ana has pronouns and about set
    author = bo.get(f"/api/board/topics/{topic}").json()["posts"][0]["author"]
    assert set(author) == {"account_id", "display_name", "avatar", "colour", "badges"}
def test_reading_a_topic_clears_its_new_mark(app, local, storage): ...
def test_a_picture_is_refused_while_the_zone_has_pictures_off(app, local, storage): ...
def test_the_guard_takes_a_board_picture_and_nothing_else_raw(app, local): ...
def test_posting_too_fast_is_429(app, local, storage, monkeypatch): ...
def test_deleting_a_campaign_unties_its_zone(app, local, storage): ...
def test_a_host_cannot_open_their_zone_to_accounts(app, storage): ...  # 403
```

- [ ] **Step 2: Run** `uv run pytest -q tests/web/test_board_api.py` — expect FAIL (404s, no routes).
- [ ] **Step 3: Implement** `routes/board.py` (module docstring as `join_requests.py`'s: who may call, what it
  publishes, that the DM never reads it) and the three modifications. Map errors once, in a `board_refusal(error)`.
- [ ] **Step 4: Run** `uv run pytest -q tests/web/test_board_api.py tests/web/test_guard*.py tests/web/test_campaigns*.py`
  — expect PASS.
- [ ] **Step 5: Commit** `Board: the API, the picture upload path and a deleted campaign's zone (DEL-297)`.

---

### Task 5: Live updates for who may read

**Files:**
- Modify: `src/delve/web/events.py`
- Test: `tests/web/test_events.py` (or the file that tests `may_see`; add there)

**Interfaces:**
- Consumes: `board_rights.rights` and `board_rights.caller_of` (Task 2).
- Produces: `Scope = Literal["organisers", "table", "board"]`; `Event.zone_id: str | None = None`; `publish(...,
  zone_id: str | None = None)` (a `board` event must name its zone); `Tables.may_read_zone(principal: Principal,
  zone_id: str) -> bool` (on `StoredTables` and the batch `_Answers` wrapper, cached per batch like the others).
  `may_see` delivers a `board` event only when `may_read_zone` says so, for accounts (after the login and
  disabled checks already there) and for the owner. A deleted zone's event (`{"zone_id"}` with the zone gone) goes to
  organisers only.

- [ ] **Step 1: Write the failing tests:**

```python
def test_a_board_event_goes_only_to_who_may_read_the_zone(bus, storage): ...
def test_a_member_taken_out_hears_nothing_more(bus, storage): ...
def test_a_board_event_must_name_its_zone(bus):
    with pytest.raises(ValueError):
        bus.publish("board", {}, scope="board")
```

- [ ] **Step 2: Run** them — expect FAIL. **Step 3: Implement.** **Step 4: Run** `uv run pytest -q tests/web` — PASS.
- [ ] **Step 5: Commit** `Board: its events reach only who may read the zone (DEL-297)`.

---

### Task 6: The web's board data and safe Markdown

**Files:**
- Create: `web/src/board/api.ts`, `web/src/board/markdown.ts`
- Test: `web/src/board/markdown.test.ts`, `web/src/board/api.test.ts`

**Interfaces:**
- Consumes: Task 4's JSON shapes; `apiFetch`, `postJson`, `patchJson`, `putJson`, `deleteJson` from `web/src/api.ts`.
- Produces in `api.ts`: types `Level`, `ZoneRights`, `Zone`, `BoardZone` (zone + `topics`, `new_topics`), `Topic`,
  `Author`, `Post`, `TopicPage`; `boardKeys` (`all`, `zone(id)`, `topic(id, page)`, `people(id)`); one function per
  route of Task 4 (`getBoard`, `createZone`, `updateZone`, `deleteZone`, `reorderZones`, `getZonePeople`,
  `setModerators`, `addMember`, `removeMember`, `getZone`, `startTopic`, `getTopic`, `setTopic`, `deleteTopic`,
  `reply`, `editPost`, `deletePost`, `attachPicture(postId, file)`, `takeDownPicture`, `postPictureUrl(postId)`,
  `postAvatarUrl(postId)`).
- Produces in `markdown.ts`: `renderPost(text: string): string` (HTML) and `quoteOf(author: string, text: string):
  string` (`> **Ana wrote:**\n> …` for each line, then a blank line).

- [ ] **Step 1: Write the failing tests** (Review Focus 1):

```ts
it("renders the formatting a post may carry", () => {
  expect(renderPost("**b** *i* `c`\n\n# H\n\n- a\n\n> q")).toContain("<strong>b</strong>");
});
it("leaves raw HTML as text", () => {
  expect(renderPost("<script>alert(1)</script><img src=x onerror=alert(1)>")).not.toMatch(/<script|<img/);
});
it("links only to http(s) and mailto, safely", () => {
  expect(renderPost("[x](javascript:alert(1))")).not.toContain("href=\"javascript");
  expect(renderPost("[x](https://delve.party)")).toContain('rel="noopener noreferrer nofollow"');
});
it("loads no image from Markdown", () => {
  expect(renderPost("![t](https://elsewhere/t.png)")).not.toContain("<img");
});
it("quotes every line under who wrote it", () => {
  expect(quoteOf("Ana", "one\ntwo")).toBe("> **Ana wrote:**\n> one\n> two\n\n");
});
```

- [ ] **Step 2: Run** `cd web && npx vitest run src/board` — expect FAIL.
- [ ] **Step 3: Implement** with `new MarkdownIt({ html: false, linkify: true, breaks: true })`, `md.disable("image")`,
  `validateLink` allowing only `http:`, `https:`, `mailto:`, and a `link_open` rule adding `target="_blank"` and the
  `rel`.
- [ ] **Step 4: Run** — expect PASS. **Step 5: Commit** `Board web: its API and safe Markdown for posts (DEL-297)`.

---

### Task 7: The board's pages

**Files:**
- Create: `web/src/board/BoardFrame.tsx`, `BoardIndex.tsx`, `ZonePage.tsx`, `TopicPage.tsx`, `PostEditor.tsx`,
  `board.css`, and `*.test.tsx` for the last four
- Modify: `web/src/App.tsx` (routes `/board`, `/board/:zoneId`, `/board/:zoneId/:topicId` beside `/help`, outside
  the shell), `web/src/components/Nav.tsx` (a **Board** entry in both navs, before Preferences),
  `web/src/landing/Landing.tsx` and `web/src/help/HelpPages.tsx` (a Board link), `web/src/i18n/*.json`

**Interfaces:**
- Consumes: Task 6; `getMe` (`web/src/account/api.ts`) to know a visitor from an account; `Lightbox`; the event
  subscription (`sharedEvents()` / `EventsContext`) for `board` events, which invalidate `boardKeys.all` and, for
  the zone or topic on screen, its query. Visitors don't subscribe (the stream is 401 for them).
- Produces: `PostEditor({ initial?: string, onSubmit: (text: string, picture: File | null) => void, pictures:
  boolean, busy: boolean, insert?: { text: string, n: number } })` — a textarea with buttons Bold, Italic, Heading,
  Bulleted list, Numbered list, Link, Quote (each wraps the selection in Markdown), a picture button and paste
  (images only, while `pictures`), a preview toggle using `renderPost`, and a character count against 20 000. `insert`
  appends a quote (the Quote button on a post sends `quoteOf`), as table talk's `insert` does.

Behaviour, as the spec and mockup B say:
- **BoardFrame**: Delve's wordmark linking `/home` (account) or `/` (visitor), "Board", and **Log in** for a visitor
  or **Back to Delve** for an account; the language switch as the help's frame has it.
- **BoardIndex**: zones in order; each with name, description, a short label of its levels (e.g. "everybody reads ·
  accounts write", translated), topic count and a "N new" pill; "New zone" for `may_create` (opens Task 8's settings).
- **ZonePage**: crumb `Board › Zone`, topics (pinned first, a pin mark; locked mark), each with title, starter, replies,
  last post by and when, a "new" pill; **New topic** (title + `PostEditor`) for `rights.write`; for a visitor on a
  zone whose write is `accounts`, **Log in to post**.
- **TopicPage**, layout B: each post with face (avatar via `postAvatarUrl`, else emblem, as `TableAvatar` draws them),
  name, badges, time and "edited"; the rendered text; a picture (thumbnail, `Lightbox` to enlarge); a removed post
  reads "Removed by the author" or "Removed by a moderator" and has no actions. Actions: Quote and Reply for who may
  write; Edit and Delete on one's own; Delete and Take picture down for who moderates; Pin/Unpin, Lock/Unlock and
  Delete topic in the topic's header for who moderates. Pages (`pages`), opening at `first_unread_page` with the first
  unread post scrolled to. The reply box at the foot; "Locked" instead when locked and the caller can't moderate;
  "Log in to post" for a visitor. A picture picked or pasted is sent with `attachPicture` right after the post is made.
- On a phone (390 wide) everything fits the width, no horizontal scroll.

- [ ] **Step 1: Write the failing component tests**, e.g.:

```tsx
it("shows each post's author above it, with badges, and a removed post without actions", ...);
it("quotes a post into the reply box under its author", ...);
it("offers Edit and Delete on one's own post only, and moderation to moderators", ...);
it("tells a visitor to log in instead of a reply box", ...);
it("takes a pasted picture only where the zone allows pictures", ...);
it("marks a zone's new topics on the board", ...);
```

- [ ] **Step 2: Run** `cd web && npx vitest run src/board` — expect FAIL.
- [ ] **Step 3: Implement**, with every string in all five i18n files.
- [ ] **Step 4: Run** `cd web && npx tsc -b --noEmit && npx vitest run` — expect PASS (the i18n completeness test too).
- [ ] **Step 5: Commit** `Board web: the board, a zone and a topic, posts as a modern thread (DEL-297)`.

---

### Task 8: Zone settings, and the table's Board link

**Files:**
- Create: `web/src/board/ZoneSettings.tsx`, `ZoneSettings.test.tsx`
- Modify: `web/src/board/BoardIndex.tsx` (reorder: Move up / Move down per zone for organisers), `ZonePage.tsx`
  (a Settings button for `rights.manage`, People for `rights.moderate`), `web/src/play/TablePanel.tsx` (a **Board**
  link to the campaign's zone when one exists; for the host, **Make the table's zone** when none does), i18n

**Interfaces:**
- Consumes: Task 6's `createZone`, `updateZone`, `deleteZone`, `reorderZones`, `getZonePeople`, `setModerators`,
  `addMember`, `removeMember`, `getBoard` (to find the zone whose `campaign_id` is the table's).
- Produces: `ZoneSettings({ zone?: Zone, campaignId?: string, wide: boolean, onDone: () => void })` — a dialog:
  name, description, read and write (selects; write options limited by `valid_levels`' rule; only `table`/`members`
  when `!wide`), pictures (checkbox), the campaign (organisers only, a select of campaigns), moderators (usernames),
  and for an existing zone **Remove zone** (organisers; confirmation naming how many topics go). People (members, for
  `members` zones): add by username, remove each.

- [ ] **Step 1: Write the failing tests:**

```tsx
it("offers a host only the table and members levels", ...);
it("keeps write no wider than read", ...);
it("names how many topics go before a zone is removed", ...);
it("adds a member by username and shows the server's refusal", ...);
```

- [ ] **Step 2: Run** — FAIL. **Step 3: Implement.** **Step 4: Run** `npx tsc -b --noEmit && npx vitest run` — PASS.
- [ ] **Step 5: Commit** `Board web: a zone's settings and people, and the table's Board link (DEL-297)`.

---

### Task 9: In a real browser

**Files:**
- Create: `web/e2e/yz-board.spec.ts`, screenshots `web/e2e/screenshots/board-topic-1280x800.png`,
  `board-topic-390x844.png`

**Interfaces:**
- Consumes: everything above. Plays no beat of the fake DM; creates no campaign; makes its player account as
  `y-talk-pictures.spec.ts` makes Mo (an invite of the crypt campaign, `POST /api/join/{token}/account`), username
  `bo-board`; deletes its zone at the end. Marks the play tour seen in every context, as the other specs now do.

- [ ] **Step 1: Write the spec:** the owner makes "The engine" (read everybody, write accounts, pictures on); Bo logs
  in, starts "Could the DM roll morale in the open?" with **bold** text and a picture (`e2e/avatar-300x200.png`); the
  owner opens it, Quotes Bo's post and replies; Bo's board shows the zone with "1 new"; a fresh context with no login
  opens `/board`, reads the topic and sees "Log in to post"; the owner deletes Bo's post, which reads "Removed by a
  moderator" for Bo; screenshots at 1280x800 and 390x844 (no horizontal scroll: `document.documentElement.scrollWidth
  <= 390`). Finally `DELETE /api/board/zones/{id}`.
- [ ] **Step 2: Build and run:** `cd web && npm run build && DELVE_E2E_PORT=47844 npx playwright test
  e2e/yz-board.spec.ts` — expect PASS. Then run it after the specs before it in name order once (`npx playwright test
  e2e/y-talk-pictures.spec.ts e2e/yz-board.spec.ts`) — expect both to pass.
- [ ] **Step 3: Run the whole check:** `make ci` (or the repo's documented equivalent) — expect PASS.
- [ ] **Step 4: Commit** `Board: a browser check of the board, with screenshots (DEL-297)`.
