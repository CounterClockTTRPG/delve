# Table talk in one place, sessions the host runs, raised hands (DEL-199)

Design: the canvas https://claude.ai/artifact/FE23hJciMkWc9EVibTP2mn and the comments on DEL-199. Branch
`feat/table-talk`, worktree `~/claude/refactoring-table-talk`.

## The table's session state

A campaign's table is `gathering`, `playing` or `break`. The host and co-hosts (`HostSeat`) move it:

- **gathering**: before a session, and after one ends. Talk and Ask the DM work; Act and Pass are refused (409, "The
  session hasn't started yet: the host starts it."), except at a *solo* table (at most one seat that isn't an
  observer and hasn't left), where the first act starts the session as today (state becomes `playing`).
- **Start the session** (gathering only, no beat open or running): records the host's choice for each absent PC
  (`absent`: character id to `in_character`, `hold_back` or `out`), becomes `playing`, and opens a beat that runs at
  once with one Delve-written `session` submission: the DM opens the scene (with `BEGIN_SESSION` as `dm_message`
  already adds it when the session hasn't started), told which PCs the DM plays, which stay in the background and which
  sit the session out. That beat gets no fallbacks.
- **playing**: as today. A PC with an `absent` choice that no submission covers gets that choice as its fallback line
  instead of the play settings' `fallback`; an `out` PC gets no line at all.
- **Take a break** (playing only): becomes `break`. Act, Pass and Go are refused (409, "The table is on a break.").
  An open beat's timer stops; `recheck` and the timer close nothing during a break. A running beat finishes.
- **Back to the story** (break only): becomes `playing`; an open beat's `opened_at` moves on by the length of the
  break (so its deadline does too) and its timer is armed again.
- **End the session** (playing or break, no beat open or running): becomes `gathering` at once (absent choices and
  raised hands cleared), and runs a beat with one `session` submission asking the DM to bring the scene to a pause and
  call `end_session(recap)`.
- The DM's own `end_session` (a recap made, `table._make`) also sets `gathering`.
- No stored row yet: `gathering` when `pregame.in_pregame` says so, else `playing` (so tables mid-session keep playing).

Raised hands live with the state: `hands`, seat id to `{at, point}`. Any seat at the table raises its own (`point`: an
optional line, at most 200 characters after strip); it lowers its own, and the host and co-hosts lower anyone's.

## API (the contract the web builds against)

- `GET /api/campaigns/{id}/play/state` gains `table`:
  `{"state": "gathering"|"playing"|"break", "since": iso|null, "solo": bool, "absent": {cid: mode}, "hands": [{"seat_id", "at", "point"}]}`
  (hands oldest first). `pregame` goes.
- `POST /api/campaigns/{id}/session/start` body `{"absent": {cid: mode}}` (default `{}`), HostSeat: 202
  `{"table": …, "beat": beat_json}`; 409 when not gathering or a beat is open or running; 422 for an unknown character
  or mode.
- `POST …/session/break`, HostSeat: 200 `{"table": …}`; 409 unless playing.
- `POST …/session/resume`, HostSeat: 200 `{"table": …}`; 409 unless on a break.
- `POST …/session/end`, HostSeat: 202 `{"table": …, "beat": beat_json}`; 409 when gathering or a beat is open or running.
- `POST …/hand` body `{"point": str|null}`, TableSeat: 200 `{"table": …}`; 422 past 200 characters. Raising again
  replaces the point and keeps `at`.
- `DELETE …/hand/{seat_id}`, TableSeat: 200 `{"table": …}`; 403 unless it is the caller's own seat or the caller is
  the host or a co-host. Lowering a hand that isn't up is fine (200).
- Act and Pass: 409 with the details above. Go: 409 on a break.
- Event `table` (scope table) `{"campaign_id", "table": …}` on every change: state, absent choices, hands.

## Server (subagent)

1. Storage: a `table_sessions` repository (interfaces + SQLite + Alembic migration 0028): one row per campaign,
   `state`, `since`, `absent` (JSON), `hands` (JSON), `break_at`. Tests in `tests/storage`.
2. `delve/play/table_session.py`: the state, its transitions and the hands, with `PlayError` subclasses the routes map
   to 409/403/422. The `session` submission kind in `beats` (no fallbacks for its beat) and in `table.dm_message`
   (its text a Delve line, like a fallback's). Fallbacks per character from `absent`. The guards in `submit`, `go`,
   `recheck`, `_close`/timer. `_make`'s recap sets gathering. Tests in `tests/play`.
3. Routes in `web/routes/play.py`, `table` in the play state (without `pregame`), the `table` event. Tests in
   `tests/web`.
4. `dm.md`: one sentence that a host may start or end a session for the table, in a Delve line.

## Web (me)

1. Talk in one place: `TalkPanel` becomes the talk dock at the foot of the side column (and the phone's Table
   screen), with its own box (Send, emoji, Quote, typing), presence faces, fold to one line with "n new", flat lines,
   one scrolling area, shared answers clipped with Show all. `TablePanel` keeps the seats and Leave. The Composer loses
   Table talk (it speaks to the DM: Act or Ask the DM; an observer asks only); while the DM writes, Act waits.
2. The wide talk: gathering and a break widen the side column; Narrow and Widen switch it by hand. `Tavern`,
   `useTavern` and `tavern.css` go. The banner stays in the story's empty state with the host's Start the session and
   the invite link.
3. Session controls: Start the session dialog (who's here; the three choices for each absent player's PCs), Take a
   break / Back to the story / End the session (with a confirm) in the header for the host and co-hosts, the state's
   line under the title, Act refused with a reason while gathering or on a break.
4. Raise hand: the toggle (with an optional point) in the talk dock's header, the raised-hands strip at the top of the
   side column (and the phone's), Lower (own, or anyone's for the host), Take a break from the strip for the host, the
   line by the Act box.
5. i18n for every new string in en, nl, fr, de, lv.
