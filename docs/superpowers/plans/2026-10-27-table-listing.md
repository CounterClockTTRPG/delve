# The table's listing, and removing a player (DEL-204 part A)

DEL-204 and its comments hold the owner's decisions. Branch `feat/table-listing`, worktree
`~/claude/refactoring-table-listing`. Part B (Find a table, sign-up requests) and part C (the schedule) come later;
here `public` is stored and shown, and nothing lists the table yet.

## What a campaign gains

- `visibility`: `private` (only the invite link brings players in: today's tables) or `public` (accounts on this
  Delve will find it and ask to join, part B). Default `private`.
- `description`: Markdown, at most 4000 characters, default "". **For players only**: how the players play together,
  what they expect from each other, whether newcomers are welcome. The DM never reads it (the host puts what the DM
  should follow in the custom tone), so it never goes into a prompt.
- `slots`: the places for players, 1 to 20, or null for no limit. A place is a live seat (not left) that is a `player`
  or a `cohost`; the `host` and `observer`s take none. `taken` is that count.

## API (the contract the web builds against)

- `GET /api/campaigns` and `GET /api/campaigns/{id}`: each campaign gains `visibility`, `description`, `slots`.
- `PUT /api/campaigns/{id}/listing` (Organiser, as the campaign's house rules are) body
  `{"visibility", "description", "slots"}`: 200 with the campaign as `GET /api/campaigns/{id}` answers it. 422 for an
  unknown visibility, a description past 4000 characters (after strip), or slots that aren't null or 1–20. Fewer slots
  than are taken is allowed: nobody is removed, nobody more can join. Publishes `campaigns` (as other campaign
  changes do) and `table_listing` (scope table, `{"campaign_id"}`) so the seats read it again.
- `GET /api/campaigns/{id}/listing` (TableSeat: anyone at the table): `{"visibility", "description", "slots",
  "taken", "house_rules": [{"id", "title", "body_md"}]}`, the house rules being the campaign's effective ones
  (`delve.play.house_rules.effective_rules`), in order.
- `GET /api/join/{join_token}`: `campaign` gains `description`, `slots`, `taken`, `full` (slots set and taken >= slots)
  and `house_rules` (the same shape as above).
- `POST /api/join/{join_token}` and `POST /api/join/{join_token}/account`: a new seat as `player` at a full table is
  refused, 409 `{"detail": "The table is full."}`, and for `/account` before the account is made. An account that
  already has a live seat there gets it back as today (200), full or not. An `observer` always joins.
- `POST /api/campaigns/{id}/seats/{seat_id}/remove` (HostSeat), body `{}`: the seat leaves the table as Leave does
  (`delve.play.seats.leave`: its characters are freed and follow the fallback), 200 `{"seat": seat_json}`. 404 for a
  seat not at this table or already gone; 409 for the host's seat ("Hand the host role over first.") and for the
  caller's own seat ("Leave the table instead."); 403 when a co-host removes another co-host (only the host does).
  Publishes `seats` as Leave does. The removed account can come back through the join link; the host makes a new link
  (Invite, existing) to stop that.

## Server (subagent)

1. Domain and storage: the three fields on `Campaign`, Alembic migration 0029 (columns on `campaigns`, defaults
   `private`, "", NULL), `campaigns.set_listing`, contract tests.
2. Routes: `campaign_json`, the listing routes, the join changes, remove a seat. Tests in `tests/web`.

## Web (me)

1. The campaign page's Table tab: a "Table listing" section (visibility, slots, description with a Markdown preview),
   saved with `PUT …/listing`.
2. The join page: the description, the house rules (folded, each opening), "3 of 4 places taken", and a full table's
   notice (Join as an observer still offered).
3. At the table: the Table tab shows "About this table" (the description and the house rules, folded) and the places
   taken; Host controls give each seat but the host's Remove from the table, confirmed first.
4. i18n in en, nl, fr, de, lv.
