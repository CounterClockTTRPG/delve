# Find a table and ask to join (DEL-204 part B)

DEL-204 and its comments hold the owner's decisions; part A (the listing, Remove) is live. Branch `feat/find-a-table`,
worktree `~/claude/refactoring-find-a-table`. Migration 0030 is Google login's (DEL-206); this one is 0031.

## The owner's decisions

- Public tables are listed for **logged-in accounts** only (an account, not a seat token, not the owner token alone:
  the owner's own account sees them too). Not on a public front page.
- Signing up is a **request** with a short note; the host or a co-host **accepts** (a normal `player` seat) or
  **declines**. Before that, the two can **talk on the request**: a short thread of messages between the player and
  the hosts. Table talk opens once the player has a seat.
- Places (part A): a request to a full table is refused; accepting at a full table is refused. A role change that
  would make an observer a player or a co-host at a full table is refused too (part A left that open).

## Join requests

A `join_requests` row: `id` (`jrq_…`), `campaign_id`, `account_id`, `status` (`pending`, `accepted`, `declined`,
`withdrawn`), `messages` (JSON list of `{"from": "player"|"host", "name", "text", "at"}`, oldest first; the first is the
player's note), `created_at`, `decided_at` (null while pending), `seat_id` (the seat an accept made, else null). One
pending request per account and table. A message is 1 to 1000 characters after strip; a note may be empty (then the
thread starts empty). A thread holds at most 50 messages (409 past them: "Talk at the table once you're seated.").

## API (the contract the web builds against)

Errors are `{"error": "…"}`, as the app answers every error.

- `GET /api/tables` (an account: `AccountCaller`): the public tables not `complete`, the most recently played first:
  `[{"campaign_id", "name", "module_title", "ruleset", "setting", "description", "slots", "taken", "full",
  "house_rules": [{"id", "title", "body_md"}], "host": {"display_name", "profile"}, "seated": bool,
  "request": {"id", "status"} | null}]`. `host` is the host seat's account profile summary (`profiles.summary`), or
  `{"display_name": <seat name>, "profile": null}` without an account. `request` is the account's newest request there.
- `POST /api/tables/{campaign_id}/requests` (account) body `{"note": str}`: 201 `{"request": request_json}`. 404 for a
  campaign that isn't public (or isn't there); 409 when the account has a live seat there ("You're at this table
  already."), a pending request there ("You asked already: wait for the host."), or the table is full ("The table is
  full."); 422 past 1000 characters. Publishes `join_requests` (scope table, roles host and co-host,
  `{"campaign_id"}`).
- `GET /api/account/requests` (account): the account's requests, newest first, each `request_json` plus
  `"campaign": {"id", "name", "module_title"}`.
- `request_json`: `{"id", "campaign_id", "status", "messages", "created_at", "decided_at", "seat_id", "account":
  {"id", "display_name", "profile"}}`.
- `POST /api/requests/{id}/messages` body `{"text"}`: the requesting account (as `player`) or a host/co-host seat of
  its table (as `host`, the seat's name): 201 `{"request"}`. 403 for anyone else; 409 unless pending, or past 50
  messages; 422 for an empty or too long text. Publishes `join_requests`.
- `POST /api/requests/{id}/withdraw` (the requesting account), body `{}`: 200 `{"request"}`; 409 unless pending.
- `GET /api/campaigns/{id}/requests` (HostSeat): the table's pending requests, oldest first, then those decided in the
  last 14 days, newest first.
- `POST /api/campaigns/{id}/requests/{rid}/accept` (HostSeat), body `{}`: the account gets a `player` seat (its name
  the account's display name, made unique as the join route does; its language the profile's), the request is
  `accepted` with `seat_id`. 200 `{"request", "seat"}`. 409 unless pending, at a full table, or when the account has a
  live seat there already (then the request is accepted with that seat, 200). Publishes `seats` and `join_requests`.
- `POST /api/campaigns/{id}/requests/{rid}/decline` (HostSeat) body `{"reason": str}` (may be ""): `declined`; a
  non-empty reason is added to the thread as a `host` message first. 200 `{"request"}`; 409 unless pending.
- `PUT /api/campaigns/{id}/seats/{seat_id}` (existing): making an observer a `player` or `cohost` at a full table is
  409 "The table is full.".

## Server (subagent)

1. Storage: `JoinRequest`, the `join_requests` repository, migration 0031, contract tests.
2. `delve/play/join_requests.py`: asking, messages, withdraw, accept, decline, with `PlayError`s the routes map.
3. Routes and the role-change check. Tests in `tests/web`.

## Web (me)

1. **Find a table** (`/tables`, in the side bar for accounts): a card per table with its name, module, ruleset, host,
   places, description, house rules (folded); Ask to join (a note) or the request's state, or Open (seated).
2. **My tables** gains "Your requests": each with its state and the thread, a reply box and Withdraw while pending;
   read again every 30 seconds and on focus (a player without a seat hears no events).
3. **Host side**: the Table tab's Host controls get "Requests to join" with each pending request (who, their
   profile card, the thread), Reply, Accept and Decline (with an optional reason); a dot on the Table tab when one
   is new (`join_requests` event).
4. i18n in en, nl, fr, de, lv.
