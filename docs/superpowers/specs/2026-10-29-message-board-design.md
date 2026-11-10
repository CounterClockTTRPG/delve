# The message board (DEL-297)

A bulletin-board-style message board in Delve: zones the owner sets up as they go, topics in them, and forum posts with
formatting and quotes, where players ask questions and chat between sessions. Settled with the owner on 2026-10-29;
the decisions are also on DEL-297 in Tasker.

## Why

Today every conversation in Delve belongs to one table: table talk, Ask the DM, join requests. There is nowhere to ask
about the engine, talk rules for a ruleset, discuss a setting, or for a group to talk about where their campaign stands
between sessions. The owner wants one place for all of that, run like a small forum, with each zone open or closed
as fits.

## Goals

- **Zones the owner sets up organically.** No zone is built in. The owner (and organisers) create, rename, describe,
  reorder and remove zones as they go. The owner's first zones will likely be the engine, one per ruleset (AD&D 2nd
  Edition, OSRIC, …), settings, and group tables, but those are data, not code.
- **Read and write rights per zone, set separately.** Each zone has a *read* level and a *write* level, each one of,
  widest first:
  1. `everybody`: anyone, including visitors who aren't logged in (read only; see below);
  2. `accounts`: every account that can log in;
  3. `members`: the accounts let into this zone by hand;
  4. `table`: the seated people of the campaign the zone is tied to.

  Write is never wider than read; the server refuses a zone where it is. Writing needs an account, so `everybody`
  is a read level only: "everybody reads, log in to write" is read `everybody`, write `accounts`.
- **Always in.** Organisers (`Principal.roles` has `organiser`, which the owner also has) read and write every zone. A
  campaign's hosts and co-hosts read and write the zone tied to their campaign. A zone's moderators read and write
  their zone.
- **Moderators per zone**, named by the owner or an organiser: any accounts. A moderator, in their zone: lets accounts
  in as members and takes them out (for a `members` zone), deletes any post or topic, pins and unpins topics, locks
  and unlocks them. Organisers can do all of that in every zone, and a campaign's hosts and co-hosts in their
  campaign's zone.
- **Topics:** anyone who can write in a zone can start a topic in it (a title and a first post) and reply in it.
- **Forum posts**, not chat lines: formatting (bold, italic, headings, bulleted and numbered lists, links, quotes)
  through buttons above the box, stored as Markdown. Quote on a post puts `> **Ana wrote:**` and the quoted words into
  the reply box. Authors edit their own posts; an edited post says "edited". Authors delete their own posts;
  moderators and organisers delete any. A deleted post keeps its place and reads "removed" (by the author, or by a
  moderator), so replies still make sense; its words are gone from storage.
- **Pictures, per zone:** each zone has an on/off `pictures` option (off by default), set by whoever manages the
  zone's settings. While it is on, anyone who can write there may paste or pick a picture into a post, as table
  talk's pictures work (DEL-294): checked against its type, re-encoded as a clean WebP, served to whoever may read the
  zone. A picture goes with its post when the post is deleted.
- **New marks.** On the board and in a zone, a topic with posts the account hasn't read is marked new, and the zone
  shows how many of its topics are new. Opening a topic reads it up to its newest post. Visitors who aren't logged in
  see no marks.
- **Topic layout B, the modern thread** (chosen on the mockup; it reads better on a phone): each post has the
  author's face and name above it, with their role (organiser, moderator, host) and the time, and the text uses the
  full width. Profiles and avatars as table talk shows them.
- **Authors are shown to every reader of the zone** (owner's decision): a post shows its author's display name and
  avatar to anyone who may read the zone, visitors included. Only those two: not the profile card's `about` or
  pronouns. This is a deliberate, narrow exception to the profile rule that hides an account from anyone who shares
  no table with it (`delve.play.profiles.card`). Serve the author's name with the post, and the avatar through a board
  route that checks the board's rights (e.g. `/api/board/posts/{id}/avatar` or by author within a readable zone),
  leaving `card` and `/api/profiles/{id}/avatar` unchanged.
- **Visitors can read open zones**: the board is reachable without logging in, from the public front page (`/`) and
  the help, like `/help`; the reply box reads "Log in to post" there.

## Non-goals

- **No translation.** Posts are read as written, unlike table talk (owner's decision).
- **The DM never reads the board.** No post goes into any prompt; it is for people only, like table talk.
- **No email yet.** An optional email per topic for new replies is DEL-298, blocked by email support (DEL-214).
  Nothing in this work should make it hard to add: keep "who follows a topic" derivable (who posted in it, who read
  it) or add a follow flag later.
- No private messages between accounts, reactions, polls, signatures, ranks, or search. They can be filed later.
- No moderation queue: posts appear at once. Deleting is the moderation.

## Anti-goals

- A structure the owner can't reshape: hard-coded zones, kinds of zone, or a fixed hierarchy.
- A visitor or an account reading anything in a zone it may not read, including through a picture's URL, a topic
  count, the newest post's title on the board, or the events stream. Zones a caller can't read are not listed for
  them at all.
- Markdown that runs script or loads off-site content. Rendered posts must be safe (no raw HTML).
- Breaking the front page or the help for visitors.

## Constraints and what Delve already has

- **Storage** is repositories behind `delve.storage.interfaces` protocols, SQLite in `delve.storage.sqlite`, with
  Alembic migrations; the next free number on master is **0042** (check again before merging: other branches add
  migrations). Use plain `CREATE TABLE`; no batch rebuild of a table that `campaigns` or `accounts` reference (see
  the 0037 incident: a batch rebuild cascaded away characters).
- **Who is calling**: `delve.web.auth.current_principal` and `identify` (None for a visitor). A principal may be the
  owner by token with no account (`Principal.id == "owner"`), an account, or an old seat-token seat with no account.
  Posting needs an author: an account, or the owner. For the owner by token, author the post as the owner's account
  if one exists, else as "the owner" (builder's call how, see below). Seat-only principals read and write only as
  far as their seat's campaign zone allows, if at all (builder's call; accounts are what joins require today).
- **Campaign roles**: seats with `role` `host`, `cohost`, `player`, `observer` per campaign
  (`delve.storage.interfaces.SeatRepository`); an account's seats are how `table` access is decided. Observers of a
  campaign read its `table` zone; whether they write follows the zone's write level, where `table` means seated
  players, hosts and co-hosts (not observers), matching "observers see the pictures but can't post" in table talk.
- **Pictures**: `delve.play.talk_pictures` (type check, size and pixel limits, WebP) and the blob store
  (`storage.blobs`) with pruning of blobs named nowhere; the request guard (`delve.web.guard`) refuses non-JSON
  writes except the upload paths it lists, so a board picture upload needs its own entry there, as
  `TALK_PICTURE_PATH` has.
- **Live updates**: `request.app.state.events.publish` with scopes `organisers` and `table`. The board needs its own
  scope (`board`, with the zone id), delivered only to listeners who may read that zone. Visitors don't get the
  stream; they see what was there when they loaded.
- **Markdown**: the web already has `markdown-it` (help topics) and a tiptap editor with Markdown
  (`web/src/module/TextEditor.tsx`). Render posts with `markdown-it` with `html: false` and safe links (no
  `javascript:`; links open with `rel="noopener noreferrer nofollow"`). The editor may reuse the tiptap setup's
  buttons, or be a plain textarea with buttons that insert Markdown; builder's call, as long as the buttons above
  the box cover bold, italic, headings, lists, links and quotes, and the box takes pasted pictures where allowed.
- **Throttles and limits**: as table talk's `seat_throttle` and `play_limits`, per account: a sensible cap on posts a
  minute, title and post lengths (builder's call; e.g. 120 characters for a title, 20 000 for a post).
- **i18n**: every string in `web/src/i18n/{en,nl,fr,de,lv}.json`, as everywhere in Delve. The French uses *vous*.
- **Tests**: server tests under `tests/` (domain and API), web unit tests (vitest), and a browser spec under
  `web/e2e/` with a screenshot of a topic at 1280x800 and 390x844. The e2e fake DM plays turns in order; the board
  spec plays none.

## The pieces

### Data

**One zone per campaign** at most (my call): `campaign_id` is unique among zones.

- **Zone**: id, name, description, position (order on the board), `read` level, `write` level, `pictures` on/off,
  `campaign_id` (for a zone tied to a campaign, else none), created by and when. Moderators and members are lists of
  account ids per zone. A zone tied to a campaign stays when the campaign is deleted? Builder's call: deleting the
  campaign should not leave a zone nobody but organisers can open; turning it into a `members` zone with no members,
  or deleting it with the campaign, are both fine if the owner is told in the campaign's delete confirmation.
- **Topic**: id, zone, title, author, created, last post time and author (for the lists), pinned, locked.
  Deleting a topic (my call): who may moderate the zone deletes it; it vanishes from the zone's list, and its posts'
  words and pictures are erased (the blobs are then named nowhere and pruned). An author can't delete their own
  topic, only its posts; deleting the first post leaves the topic with a removed first post.
- **Removing a zone** (my call): organisers only, after a confirmation that says how many topics go with it;
  everything in it is erased.
- **Post**: id, topic, author, Markdown text, picture `{blob, mime, width, height}` or none, created, edited time or
  none, removed (by whom: `author` or `moderator`) or not.
- **Read marks**: per account and topic, the newest post read. New marks start (my call) from the account's first
  visit to the board: a topic whose last post is older than that visit, and which the account never opened, is not
  new. So store each account's first board visit.
- **Adding members** (my call): moderators, the campaign's host and organisers add an account by its exact username.
  This reveals no more than sign-up does, which already says when a username is taken. Members are listed by display
  name and username to who manages them.

### Where it lives in the app

- `/board`: the zones the caller may read, in the owner's order, each with its description, its read/write levels
  as a short label, its topic count and new count. Organisers see "New zone" and each zone's settings.
- `/board/:zoneId`: the zone's topics, pinned first, then by last post; "New topic" for who may write.
- `/board/:zoneId/:topicId`: the topic in layout B, paged when long, opening at the first unread post; the reply box at
  the foot for who may write, "Log in to post" for a visitor, nothing for a locked topic but "Locked".
- A **Board** entry in the app's side nav for every account, and a link from the public front page and the help.
- A campaign's zone is reachable from its play screen and campaign page (a "Board" link) once the zone exists.
  Creating a zone tied to a campaign: an organiser picks the campaign in the zone's settings; a campaign's host may
  also create their campaign's zone from the campaign page (builder's call whether in this work).
- Zone settings (organisers; a campaign's hosts for their zone): name, description, read and write levels, pictures,
  moderators, and for `members` zones its members (moderators manage members too). Reorder zones on the board.

### Rights, in one place

One server function decides, for a caller and a zone: may read, may write, may moderate, may manage settings. Every
route and the events stream use it; nothing else decides. Rules:

- read: organiser, or moderator, or the campaign's host/co-host (tied zone), or the read level admits the caller
  (`everybody`: anyone; `accounts`: any account; `members`: a member; `table`: a seat at the campaign that hasn't
  left, observers included).
- write: needs an account (or the owner); organiser, moderator or the campaign's host/co-host; or the write level
  admits the caller (`accounts`, `members`, or `table`: a seated player, host or co-host). Locked topics take no
  posts except from who may moderate.
- moderate: organiser, the zone's moderators, the campaign's host/co-host (tied zone).
- manage settings: organiser; the campaign's host for a tied zone (not co-hosts, as with table options). The host
  (owner's decision) names the zone's moderators and members and turns pictures on or off, and may set the read and
  write levels only to `table` or `members`: opening the zone to `accounts` or `everybody`, or untying it from the
  campaign, is the organisers' alone.

Refusals: 401 for a visitor where an account is needed, 403 for an account without the right, 404 for a zone, topic,
post or picture the caller may not read (so its existence doesn't leak).

## The calls made in writing this up

Marked "my call" above, for the owner to check while reading: one zone per campaign; how deleting a topic and removing
a zone work; new marks starting from the first board visit; adding members by exact username.

## What's left to the builder

The visual details within layout B and the Delve look; the editor's implementation; paging size; the exact limits; how
the owner-by-token authors posts; whether seat-only principals reach the board; what happens to a campaign's zone when
the campaign is deleted (within the rule above); whether hosts create their campaign's zone in this first piece; the
names of tables, routes and components, following Delve's conventions.
