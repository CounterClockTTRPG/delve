# The table's schedule (DEL-204 part C)

DEL-204 holds the owner's decisions; parts A (the listing) and B (Find a table, requests) are live. DEL-198
"Scheduled games" is folded in. Branch `feat/table-schedule`, worktree `~/claude/refactoring-table-schedule`.
Migration 0032.

## The owner's decision

A recurring rule ("we play Saturdays every 2 weeks, Brussels, 20:00–22:00") plus the next date, which the host can
move or skip. Each viewer sees the times in their own time zone. No reminders by mail or push yet.

## The schedule

`Campaign.schedule`: null (no schedule, today's tables) or

```json
{"every_weeks": 2, "first": "2026-11-07", "start": "20:00", "end": "22:00", "time_zone": "Europe/Brussels",
 "changes": [{"on": "2026-11-21", "to": "2026-11-22T19:00"}, {"on": "2026-12-05", "to": null}]}
```

- `every_weeks` 1 to 4; `first` the date of a session on the rule (its weekday is the rule's weekday); `start` and
  `end` local times `HH:MM` in `time_zone` (an IANA name `zoneinfo` knows); `end` after `start`, or before it for a
  session past midnight (it ends the next day).
- `changes`: a session of the rule moved (`to`: a local date-time in the same time zone, keeping the length) or
  skipped (`to`: null). `on` must be a date of the rule. Changes in the past are dropped when the schedule is saved.
- The sessions: `first + k × every_weeks` weeks, k ≥ 0, each with its change applied, as instants (`zoneinfo`, so a
  daylight-saving change keeps 20:00 local).

`next_sessions(schedule, now, n)`: the next `n` sessions not yet ended at `now`, in order:
`[{"on": "2026-11-21", "starts_at": "<UTC ISO>", "ends_at": "<UTC ISO>", "moved": bool}]` (skipped ones left out).

## API (the contract the web builds against)

Errors are `{"error": "…"}`.

- Campaign JSON (`GET /api/campaigns`, `GET /api/campaigns/{id}`) gains `schedule` (as stored, or null) and
  `next_sessions` (3).
- `PUT /api/campaigns/{id}/schedule` (Organiser) body: a schedule (with or without `changes`) or `null` to clear it.
  200 with the campaign. 422 with the reason for a bad field (an unknown time zone, `every_weeks` out of range, a bad
  date or time, a change not on the rule). Publishes `campaigns` and `table_listing`.
- `POST /api/campaigns/{id}/schedule/next` (HostSeat) body `{"skip": true}` or `{"to": "YYYY-MM-DDTHH:MM"}` (local, in
  the schedule's time zone): changes the next session not yet started. 200 with `{"schedule", "next_sessions"}`. 409
  without a schedule; 422 for a bad time, or a `to` in the past. `{"reset": true}` drops the change of the next
  session. Publishes `table_listing`.
- `next_sessions` (3) also in: `GET /api/campaigns/{id}/listing`, each table of `GET /api/tables`, each table of
  `GET /api/account/tables`, the join link's `campaign`, and `play/state` (as `next_sessions`); and the schedule
  itself (`schedule`) in the listing and `/api/tables` so players can read the rule.

## Server (subagent)

1. Domain (`delve/play/schedule.py`: parsing and checking a schedule, `next_sessions`, changing the next session),
   storage (a JSON `schedule` column on `campaigns`, migration 0032), contract tests. Tests for every-2-weeks, a
   moved and a skipped session, past midnight, and a daylight-saving change (Europe/Brussels, last Sunday of October).
2. Routes and the extra fields. Tests in `tests/web`.

## Web (me)

1. The campaign page's Table listing gains "When you play": every N weeks, the first date (its weekday shown), start
   and end, the time zone (the browser's by default), and a preview of the next sessions; Clear.
2. The next session shown in each viewer's own time (the browser's, `Intl`), with the rule: on Find a table, the
   join page, My tables, the Table tab's About this table, and the play header while the table gathers.
3. For the host (Table tab): Move the next session (a date-time) and Skip it, and Undo.
4. i18n in en, nl, fr, de, lv.
