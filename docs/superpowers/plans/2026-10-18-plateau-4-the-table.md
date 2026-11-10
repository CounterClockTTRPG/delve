# Delve plateau 4: the table, implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Play with friends. A host invites players with a join link or a QR code. Each player picks a name and a
language, takes over characters, and acts in the same beat as the others. The beat closes when everyone has acted, the
host says go, or the timer runs out. The DM can tell one character or one group something the others don't hear.
Players talk at the table, ask the DM privately, and read everything in their own language. It works on a phone too.

**Architecture:**
- **Identity:** a **seat** is a person at one campaign's table, with a role (host, co-host, player, observer), a
  display name, a language and a device token. The owner gets a seat in every campaign and starts as its host. The
  existing `Identity` seam (`delve/web/auth.py`) resolves the owner token, or a seat token, to a `Principal`.
- **Who sees what is decided on the server, per seat.**
  - A story entry has an audience: everyone, some characters, or some seats.
  - The event bus delivers an event only to the subscribers allowed to see it, and so does its replay buffer.
  - Player routes redact what only the DM may see.
- **Beats** collect one submission per seat (an act or a pass) and close by the spec's three rules. Seats that didn't
  act get the host's fallback. The DM gets every submission at once, in English.
- **Translation** is a side pass with its own Settings job: player input into English, and DM output out of English,
  paragraph by paragraph as it streams.

**Tech Stack:**
- **New web dependencies, exact versions:**
  - `@radix-ui/react-alert-dialog` 1.1.23 and `@radix-ui/react-dialog` 1.1.23 (MIT);
  - `qrcode` 1.5.4, with `@types/qrcode` 1.5.6 as a dev dependency (MIT).
- No new Python dependency.

**Spec:**
- `docs/superpowers/specs/2026-10-17-unified-app-design.md`:
  - §7.1 (beats, the typing indicator, the beat timer);
  - §7.2 (players, joining and leaving, the host, observers, seeing other characters);
  - §7.3 (three ways to speak);
  - §7.4 (a split party);
  - §7.5 (the fourth wall);
  - §7.6 (the play screen, the phone);
  - §7.7 (translation);
  - §11 (security and identity, roles);
  - §14.
- `docs/progress.md`: "Carried into plateau 4".
- `docs/backlog.md`: the Radix dialogs item.
- `docs/glossary.md` and `docs/data-dictionary.md`.

## Global Constraints

- **Earlier plateaus still apply:** `GUILD.md` and the Global Constraints of plateaus 0 to 3 and 5.
- **The fourth wall, per seat.**
  - Nothing a seat may not see reaches its browser: not in a route, not in an event, not in the replay buffer, not in a
    translation.
  - The host's play screen is the host's seat, a player's view. Only the DM view (the DM log, the DM map view, the
    module routes) shows everything, and it needs the organiser role.
- **Tests never run the real `claude`.** Use `FakeDM` and the fake `claude` executable. Translation tests use the fake's
  side handler.
- **No passwords and no accounts** (spec §11, "don't build that yet").
  - Seat tokens are random (`secrets.token_urlsafe(32)`), stored only as a SHA-256 hash, and sent in the cookie
    `delve_seat`. The owner's `delve_token` is unchanged.
  - A seat token gives rights in its own campaign only.
- **Single-player play pays nothing.** With one seat present, a submission closes the beat at once, as today.
- **Stored state stays English** (spec §7.7). Submissions, table talk and questions keep their original words beside
  the English.
- **Migrations:** Task 1 adds `0010_seats`, Task 3 `0011_story_audience`, and Task 7 `0012_translations`, chained in
  that order.
- **Words** (glossary): host, co-host, player, observer, seat, table talk, beat, beat timer, hold back, in character.
  Never "owner" for the person running the table (the owner is the install's), "turn" or "round" for a beat, or "chat".
  Stored values go in `docs/data-dictionary.md`.

## Review Focus

1. **A private message leaks to another player.** A planted `SECRET-XYZZY` in a `tell` to one character, in an Ask the
   DM answer, in an NPC's notes, or in a DM-only map node never reaches a second seat's browser: not through
   `GET …/story`, the event stream and its replay (`since=0`), a translation, `GET …/characters`, or the map view.
   (Task 3 test, extended in Tasks 5–7.)
2. **A seat token is used where it doesn't belong.** It is used on another campaign, on an organiser route (modules,
   house rules, settings, the DM log, the DM map view), or after the seat has left. Each answers 403 (or 401 for an
   unknown token), and the join link stops working once the host makes a new one. (Task 1 and Task 2 tests.)
3. **Players come and go in the middle of a beat.** A player who leaves, or loses their connection, no longer holds
   the beat up. Their characters get the fallback, and the beat closes with the others' submissions. A second
   submission from the same seat replaces the first. (Task 4 test.)
4. **The timer runs out while the host is away.** The beat still closes on time, and the fallback applies to every
   seat that hasn't submitted. A Delve restart during an open beat closes it on start with the submissions it has.
   (Task 4 test.)
5. **Translation fails or is slow.** The English original shows at once, marked as translating. A failed translation
   leaves the original with a notice and never blocks the beat. (Task 7 test.)

---

## File structure

```
src/delve/web/seats.py                 the seat identity: tokens, Principal with seat, campaign access dependencies
src/delve/play/seats.py                seats, roles, characters' controllers, presence
src/delve/play/audience.py             Audience and who may see it
src/delve/play/beats.py                submissions, closing rules, fallback, the DM message
src/delve/play/talk.py                 table talk
src/delve/play/translate.py            translation passes and the glossary
src/delve/i18n/glossary/nl.yaml        game terms for Dutch (the first non-English language)
src/delve/dm/tools/tell.py             tell: narration for some characters
src/delve/web/routes/{seats,join}.py
src/delve/storage/migrations/versions/{0010_seats,0011_story_audience,0012_translations}.py
web/src/routes/Join.tsx, web/src/play/{InvitePanel,TablePanel,SeatIndicators,BeatTimer,TalkPanel,HostControls}.tsx
web/src/components/dialogs.tsx         useConfirm, usePrompt (Radix)
```

---

### Task 1: Seats and roles

**Files:**
- Create: `src/delve/web/seats.py`, `src/delve/play/seats.py`, `src/delve/storage/migrations/versions/0010_seats.py`,
  `tests/web/test_seats_identity.py`, `tests/play/test_seats.py`
- Modify:
  - `src/delve/web/auth.py` (`Principal`; the identity resolves seat tokens too);
  - `src/delve/web/app.py`;
  - storage (a `seats` repository; the campaign and character columns);
  - `src/delve/web/routes/campaigns.py` (the owner's seat at creation);
  - every route module's `Organiser` alias (unchanged in meaning).

**Interfaces:**
- Produces:
  - **The seat:** `Seat(id, campaign_id, name, language, role: Literal["host","cohost","player","observer"],
    organiser: bool, owner: bool, joined_at, left_at)`.
  - **Migration 0010:**
    - `seats(id, campaign_id FK CASCADE, name, language, role, organiser, owner, token_hash UNIQUE NULL, joined_at,
      left_at NULL)`;
    - `campaigns.join_token TEXT`;
    - `characters.controller_id NULL FK seats ON DELETE SET NULL`.
    - Every existing campaign gets an owner seat ("Host", language `en`, role `host`, `owner`, no token) and a join
      token. Its PCs get that seat as their controller.
  - **The principal:** `Principal` gains `seat: Seat | None`. The owner (loopback or the owner token) is
    `Principal("owner", {"organiser"}, None)`. A seat token resolves to `Principal("seat:<id>", roles, seat)`, where
    `roles` holds `organiser` when the seat has it.
  - **Campaign access:**
    - `TableSeat = Annotated[Seat, Depends(table_seat)]`: for the route's `campaign_id`, the owner gets their owner
      seat, and a seat token gets its own seat only when it is of that campaign and hasn't left. Otherwise 403 "This
      seat is for another table." or "You have left this table."
    - `HostSeat`: the same, and its role is `host` or `cohost` (403 "Only the host can do that.").
    - `ActorSeat`: role is not `observer` (403 "Observers don't act.").
  - **Seat services:** `play.seats`:
    - `create_owner_seat(storage, campaign_id) -> Seat`;
    - `controls(storage, seat_id) -> set[str]` (character ids);
    - `set_role(storage, campaign_id, seat_id, role, by: Seat)`: exactly one host; handing over makes the old host a
      co-host;
    - `claim(storage, character_id, seat: Seat, *, for_seat: str | None = None)`: a player claims a free character;
      the host can give any character to any seat, itself included;
    - `release(...)`;
    - `leave(storage, seat)`: frees its characters and sets `left_at`; a host can't leave without handing over first
      (409).
  - **Existing routes:** `/api/campaigns/{id}/act`, `ask`, `cancel`, `story`, `play/state`, `images/{asset}`, `GET
    …/characters` and the characters view of a map take `TableSeat` instead of `Organiser`. The rest stay organiser-only.

- [ ] **Step 1: Write the failing tests:**
  - the migration gives existing campaigns an owner seat, a join token and controllers;
  - the owner resolves to their seat in each campaign;
  - a seat token works on its own campaign and gets 403 on another;
  - Review Focus 2 (organiser routes refuse a seat; a seat granted `organiser` can open them; a left seat gets 403);
  - one host at a time, and the handover;
  - claim, give and release, and leaving frees characters.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.** Change the tests that hard-code `"player": "owner"` to the owner seat's id.
- [ ] **Step 4: Run the tests and `make ci`.**
- [ ] **Step 5: Commit.** `git commit -m "Seats: the people at a table, their roles, and the characters they play"`

---

### Task 2: Joining, and the host's controls

**Files:**
- Create: `src/delve/web/routes/join.py`, `src/delve/web/routes/seats.py`, `tests/web/test_join_api.py`
- Modify: `src/delve/web/app.py`, `src/delve/__main__.py` (share the LAN address logic of `delve token`)

**Interfaces:**
- Consumes: Task 1.
- Produces:

| Method | Path | Who | Body | Answer |
|---|---|---|---|---|
| GET | `/api/join/{join_token}` | anyone | | `{campaign: {name, module_title}, languages: ["en","nl"]}`; 404 for an unknown or replaced token |
| POST | `/api/join/{join_token}` | anyone | `{name, language, role: "player"\|"observer"}` | 201 `{seat, campaign_id}`, and sets `delve_seat` (`HttpOnly; SameSite=Strict; Path=/; Max-Age=1y`) |
| GET | `/api/campaigns/{id}/invite` | host | | `{url, join_token}`: the URL uses the request's host, or the first LAN address when the request is from loopback |
| POST | `/api/campaigns/{id}/invite` | host | `{}` | a new join token; the old link stops working |
| GET | `/api/campaigns/{id}/seats` | seat | | `[{id, name, language, role, present, characters: [ids]}]` |
| PUT | `/api/campaigns/{id}/seats/{seat_id}` | host | `{role?, organiser?}` | the seat; 409 for no host left; `organiser` only from the owner (spec §11: the owner makes others organisers), 403 otherwise |
| POST | `/api/campaigns/{id}/characters/{cid}/claim` | actor | `{seat?}` | the character; `seat` is for the host only; 409 when another seat plays it |
| POST | `/api/campaigns/{id}/characters/{cid}/release` | its controller or the host | `{}` | the character |
| POST | `/api/campaigns/{id}/leave` | seat | `{}` | 204, and clears the cookie |
| GET | `/api/me` | anyone with a principal | | `{principal, seat?}` |

- **Join requests** are rate-limited to 10 per minute per address (429).
- **Names** are 1–40 characters, trimmed. The same name twice in a campaign gets " (2)".
- **Languages:** a language is any BCP-47 primary tag of 2–3 letters. The interface uses it when it is `en` or `nl`,
  and English otherwise.
- **Each change publishes `seats`** with `{campaign_id}`.

- [ ] **Step 1: Write the failing tests:** each route's answers; a replaced join token gives 404; a joined seat's
  cookie opens the play routes; a duplicate name gets " (2)"; the rate limit.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests and `make ci`.**
- [ ] **Step 5: Commit.** `git commit -m "Joining a table with a link, and the host's controls"`

---

### Task 3: Who sees what

**Files:**
- Create: `src/delve/play/audience.py`, `src/delve/storage/migrations/versions/0011_story_audience.py`,
  `tests/play/test_audience.py`, `tests/web/test_fourth_wall_per_seat.py`
- Modify:
  - `src/delve/web/events.py`;
  - every publish call site (the table in the survey: `beat`, `story`, `combat`, `characters`, `map_state`,
    `house_rules`, `settings`, `modules`, `conversion`);
  - `src/delve/play/table.py` (`story` takes the viewer);
  - `src/delve/web/routes/characters.py` and `play.py` (redaction);
  - `src/delve/web/routes/map_state.py` (the characters view);
  - `src/delve/dm/tools/redact.py` (now used for player routes).

**Interfaces:**
- Consumes: Task 1.
- Produces:
  - **The audience:** `Audience = None | {"characters": list[str]} | {"seats": list[str]}`. None is everyone at the
    table; `characters` is the seats that control any of them; `seats` is those seats.
  - `can_see(seat: Seat, audience: Audience, controls: set[str]) -> bool`. Observers see only `None`.
  - **Migration 0011:** `story.audience JSON NULL`. `StoryEntry` gains `audience`. `ask` and `answer` entries made
    before it get `{"seats": [the owner seat]}`.
  - **The bus:** `EventBus.publish(type, data, *, scope: Literal["organisers","table"] = "organisers", campaign_id:
    str | None = None, audience: Audience = None) -> int`. A subscriber is `Viewer(principal, seat)`.
    - `organisers` events (`modules`, `conversion`, `settings`, `house_rules`) go to organisers only.
    - `table` events go to the campaign's seats that may see them, and to organisers who aren't seated there.
    - The replay buffer keeps each event's scope and audience and filters the same way.
  - **The story route:** `story(storage, campaign_id, viewer_seat, before_seq, limit)` leaves out entries the seat may
    not see, and pages by what it sees.
  - **Player routes:**
    - `GET …/characters` for a seat drops NPC `notes_md` and every `DM_ONLY_KEYS` key, using
      `redact.strip_for_players`, kept and renamed from the former `_strip`.
    - The characters view of a map answers only for the seat's own characters (403 otherwise), except for the host,
      who may view any group (spec §7.4, single-player switcher).
    - `characters`, `map_state` and `combat` events carry ids only, as today, so each browser refetches through its own
      routes.

- [ ] **Step 1: Write the failing tests:** `can_see` for every role and audience; Review Focus 1, through two seats'
  test clients:
  - the story, with `ask` and `answer` addressed to their asker;
  - the event stream with `since=0`;
  - the characters route, for an NPC's notes;
  - the map view of another seat's character.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.** Ask the DM now stores `ask` and `answer` with `{"seats": [the asker]}` (finished in
  Task 6).
- [ ] **Step 4: Run the tests and `make ci`.**
- [ ] **Step 5: Commit.** `git commit -m "Who sees what: story audiences, a per-seat event stream, player routes redacted"`

---

### Task 4: Beats for a table

**Files:**
- Create: `src/delve/play/beats.py`, `tests/play/test_beats.py`
- Modify: `src/delve/play/table.py` (open, close, run), `src/delve/web/routes/play.py`,
  `src/delve/web/events.py` (presence), `tests/play/test_table.py`, `tests/web/test_play_api.py`

**Interfaces:**
- Consumes: Tasks 1 and 3.
- Produces:
  - **A submission** (in `beats.submissions`): `{seat_id, kind: "act"|"pass"|"fallback", characters: [ids],
    text (English), original, language, at}`.
  - **The beat's life:** a beat is `open` from its first submission and becomes `running` when it closes. One beat per
    campaign is open or running (the existing partial index).
  - **`submit(services, campaign_id, seat, kind, text, characters) -> Beat`:**
    - `characters` defaults to the seat's own and must be among them (422), except for the host;
    - a second submission from a seat replaces its first;
    - a submission to a running beat is 409 "the DM is still answering";
    - an observer gets 403.
  - **The closing rules (spec §7.1):** a beat closes when the first of these happens:
    - every *present* seat that controls a character has submitted;
    - the host or a co-host calls `go`;
    - the beat timer runs out.
    - With one such seat present, a submission closes the beat at once.
  - **Presence:** a seat is present while it has an event-stream connection, or had one in the last 30 s. The bus
    exposes `present(campaign_id) -> set[seat_id]` and publishes `seats` when it changes.
  - **The timer:** play settings gain `beat_timer_s: int | None` (None, or 30–1800) and `fallback: "hold_back" |
    "in_character"` (default `hold_back`). The deadline is `opened_at + beat_timer_s`. On expiry, the beat closes. A
    Delve that starts with an open beat past its deadline closes it at once.
  - **The fallback:** at closing, each character of a seat that didn't submit, and each PC with no controller, gets a
    `fallback` submission.
  - **The DM message (`dm_message`):** one line per submission, in English:
    - `<seat name> (playing <character names>): <text>`;
    - `<seat name> passes.`;
    - for `hold_back`: `(<names> hold back this beat: they do nothing.)`;
    - for `in_character`: `(Nobody is playing <names> this beat: play a cautious action for them — keep watch or
      follow the party; spend no spell or charge, and start no fight.)`.
  - **Typing:** `POST /api/campaigns/{id}/typing {state: "idle"|"typing"}` publishes a `typing` event `{campaign_id,
    seat_id, state}` to the table and stores nothing. "Submitted" comes from the beat.
  - **Routes:**
    - `POST …/act {text, characters?}` becomes a submission;
    - `POST …/pass {}`;
    - `POST …/go {}` (host);
    - `PUT …/play/settings` takes `beat_timer_s` and `fallback` (host).
    - The `beat` event carries `{beat_id, status, submitted: [seat ids], deadline}`, without the texts.

- [ ] **Step 1: Write the failing tests:**
  - a solo submission closes at once (no extra latency);
  - two seats: the first submission waits, the second closes;
  - `go`;
  - the timer, with a fake clock;
  - Review Focus 3 (a seat leaves or goes away mid-beat; a replaced submission);
  - Review Focus 4 (the timer while the host is away, and the restart);
  - the fallback lines in the DM message;
  - an observer can't act;
  - typing events reach the table and are never stored.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests and `make ci`.**
- [ ] **Step 5: Commit.** `git commit -m "Beats for a table: everyone acts, the host can say go, the timer and its fallback"`

---

### Task 5: Narration for some characters

**Files:**
- Create: `src/delve/dm/tools/tell.py`, `tests/dm/tools/test_tell.py`
- Modify: `src/delve/dm/tools/host.py`, `src/delve/dm/tools/redact.py`, `src/delve/play/table.py` (the entry),
  `src/delve/dm/prompt/dm.md`, the tool coverage test, `tests/dm/tools/test_fourth_wall.py`

**Interfaces:**
- Consumes: Task 3.
- Produces:
  - **The tool:** `tell(characters: list[str], text: str)`, player-visible, not mutating the game. It answers `{"told":
    {"characters": [ids], "text": text}}` for known characters of the campaign; unknown names are refused with
    candidates.
  - **The entry:** the table makes a `dm_text` entry with that text and the audience `{"characters": [ids]}`, after
    the tool row, the way `show_image` makes its `image` entry. `player_view` lets `told` through only for `tell`.
  - **The rules in `dm.md`:**
    - What only some characters perceive (a private vision, what a character alone overhears, a split group's scene)
      goes through `tell`, never into the reply's text.
    - The reply's text is what every character at the table perceives.
    - In a split party, narrate each group with `tell` to its characters, then say in the reply only what everyone
      knows.
    - `tell` everyone's characters is never needed.

- [ ] **Step 1: Write the failing tests:** a `tell` to one character makes an entry only that character's seat sees
  (two seats); a split party of two groups gets two addressed entries; Review Focus 1's planted secret in a `tell`.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests and `make ci`.**
- [ ] **Step 5: Commit.** `git commit -m "The DM can tell some characters what the others don't hear"`

---

### Task 6: Table talk, and private questions

**Files:**
- Create: `src/delve/play/talk.py`, `tests/play/test_talk.py`
- Modify: `src/delve/play/ask.py`, `src/delve/web/routes/play.py`, the `StoryKind` list (`talk`)

**Interfaces:**
- Consumes: Tasks 1 and 3.
- Produces:
  - `POST /api/campaigns/{id}/talk {text}`: any seat, observers included. It makes a `talk` entry `{seat_id, name,
    text (English), original, language}`, audience None, and is never part of a beat or the DM's message.
  - `POST …/ask {question}`: the `ask` and `answer` entries have the asker's seat as their audience. The question is
    translated to English and the answer back (Task 7). Ask's prompt sees only the asker's own characters (spec §7.3).
  - `POST …/ask/{answer_id}/share {}`: copies the question and its answer into table talk. Only the asker may.
  - `GET …/story` hides `talk` from the DM's context: `dm_message` and the primer never include it (test).

- [ ] **Step 1: Write the failing tests:** talk reaches every seat and never the DM; an answer reaches its asker only;
  sharing; Ask's prompt holds only the asker's characters.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests and `make ci`.**
- [ ] **Step 5: Commit.** `git commit -m "Table talk, and questions to the DM that stay with who asked"`

---

### Task 7: Translation

**Files:**
- Create: `src/delve/play/translate.py`, `src/delve/i18n/glossary/nl.yaml`,
  `src/delve/storage/migrations/versions/0012_translations.py`, `tests/play/test_translate.py`
- Modify: `src/delve/domain/settings.py` (`Job.TRANSLATION`), `src/delve/web/defaults.py`, `src/delve/play/beats.py`,
  `talk.py`, `ask.py`, `src/delve/play/table.py` (the stream), `src/delve/web/routes/play.py`

**Interfaces:**
- Consumes: Tasks 3, 4, 6.
- Produces:
  - **The job:** `Job.TRANSLATION = "translation"`, by default `claude-cli` with model `haiku` and effort `low`,
    `TRANSLATION_TIMEOUT = 60` s.
  - **Migration 0012:** `translations(entry_id FK story CASCADE, language, text, status
    'translating'|'done'|'failed', updated_at, PK (entry_id, language))`.
  - `to_english(services, text, language) -> str`: for submissions, talk and questions. It returns `text` unchanged for
    `en`. On failure it returns the original with `failed`: the submission still joins the beat, marked "(not
    translated)".
  - **Out of English:** for each language of a present seat other than English, each finished paragraph of a
    `dm_text`, a `talk`, an `answer` or a `recap` entry is translated in order.
    - **Paragraphs:** a paragraph ends at a blank line, or at the end of the reply.
    - **Events:** a `translation` event `{campaign_id, entry_id, language, text, status}` carries the entry's
      translation so far. It has the entry's audience and goes only to seats of that language.
    - **Streaming:** the English stays the stored entry, and readers of English get it with no delay.
  - **The glossary:** `glossary/<language>.yaml` lists game terms with their translation or "keep" (THAC0, AC, HP,
    hit dice, saving throw; for Dutch: "saving throw" → "reddingsworp", the rest kept). The prompt also lists the names
    of the campaign's characters, the module's NPCs and its keyed places as "never translate".
  - **Reading back:** `GET …/story?language=<lang>` adds each entry's `translation` for that language when there is
    one, and the browser asks with the seat's language.

- [ ] **Step 1: Write the failing tests:**
  - a Dutch submission reaches the DM in English, keeping its original;
  - a streamed reply is translated paragraph by paragraph, in order, while English readers get each delta at once;
  - names in the glossary prompt;
  - Review Focus 5 (a failed or slow translation shows the original with its status, and never blocks the beat);
  - a translation of an addressed entry reaches only its audience.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests and `make ci`.**
- [ ] **Step 5: Commit.** `git commit -m "Translation: player input into English, the DM's words out, as they stream"`

---

### Task 8: The play screen for a table, and the phone

**Files:**
- Create:
  - `web/src/routes/Join.tsx` (`/join/:token`);
  - `web/src/play/InvitePanel.tsx`, `TablePanel.tsx`, `SeatIndicators.tsx`, `BeatTimer.tsx`, `TalkPanel.tsx`,
    `HostControls.tsx`;
  - a test file for each.
- Modify: `web/src/routes/Play.tsx`, `web/src/play/Composer.tsx`, `web/src/play/Story.tsx`, `web/src/play/api.ts`,
  `web/src/App.tsx` (the join route; a seat sees only Play), `web/src/styles.css`, `web/package.json` (`qrcode`),
  `en.json`, `nl.json`

**What the screens do:**
- **Join** (no token needed): the campaign's name. Then a name, a language (English, Nederlands, or another code),
  and Play or Watch. The new seat picks its characters among the free ones, or writes "Ask the DM to make one", which
  becomes its first act. A seat's browser shows only the Play screen for its campaign: no nav to modules or settings.
- **The composer** has three buttons (spec §7.3):
  - **Act** (Enter), with a character picker when the seat plays more than one;
  - **Table talk**;
  - **Ask the DM** (Ctrl-Enter).
  - A seat with an act in the open beat sees it and can change it, or Pass.
- **Seat indicators:** each seat's name with idle, typing or submitted (spec §7.1), from `typing` and `beat` events.
  The composer sends `typing` at most every 3 s while text changes, and `idle` after 5 s without.
- **The beat timer** shows the time left to everyone.
- **The host's controls:** Go; the timer and its fallback; the invite (a link with a copy button, a QR code drawn
  with `qrcode` to a canvas, and "New link"); the seats with their roles (make co-host, hand over the host, make
  observer); giving any character to any seat.
- **The story** shows addressed entries marked "Only you"; table talk in the table panel; images in a gallery strip
  (spec §7.6); and each entry in the seat's language when translated, else the English marked "translating…".
- **The phone (under 600 px):** the story and the composer only. A bottom bar opens Map, Party and Table as full
  screens. No side-by-side panels. Above 600 px, today's layouts stay, with the table panel added beside the story at
  900 px and over.

- [ ] **Step 1: Write the failing tests:** joining sends name, language and role, and lands on Play; the three buttons
  call their routes; a submitted indicator from a `beat` event; the timer counts down from `deadline`; host controls
  are shown only to the host and co-hosts; an addressed entry is marked; a translated entry shows its translation; the
  phone layout's bottom bar (a `matchMedia` stub).
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests and `make ci`.**
- [ ] **Step 5: Commit.** `git commit -m "The play screen for a table: joining, three ways to speak, the host's controls, the phone"`

---

### Task 9: Delve's own dialogs

**Files:**
- Create: `web/src/components/dialogs.tsx`, `web/src/components/dialogs.test.tsx`
- Modify: every `window.confirm` and `window.prompt` call site (`ModuleDetail.tsx`, `HouseRules.tsx`,
  `TextEditor.tsx`, `CampaignDetail.tsx`, `MapEditor.tsx`, `editor/SvgPreview.tsx`, `module/EntityForm.tsx`,
  `module/AttachmentsPanel.tsx`, and any Task 8 added), `web/src/main.tsx` (the provider), `web/package.json`,
  `web/src/styles.css`, `en.json`, `nl.json`, `docs/backlog.md` (strike the item)

**Interfaces:**
- Produces:
  - `useConfirm(): (options: {title: string, body?: string, confirm: string, danger?: boolean}) => Promise<boolean>`;
  - `usePrompt(): (options: {title: string, label: string, initial?: string, confirm: string}) => Promise<string |
    null>`;
  - `<DialogsProvider>`.
  - They are built on `@radix-ui/react-alert-dialog` (confirm) and `@radix-ui/react-dialog` (prompt), styled with
    Delve's tokens. A `danger` confirm has a red button. Escape and Cancel answer `false` / `null`.
- **The unsaved-changes guards** (`useBlocker` in the map and text editors) use `useConfirm`. The `beforeunload`
  prompt stays the browser's own, since a page can't replace it.
- **A test** asserts that no `window.confirm` or `window.prompt` is left in `web/src` (outside tests).

- [ ] **Step 1: Write the failing tests:** confirm resolves true and false; prompt resolves its text and null;
  Escape; focus returns to the opener; a delete call site uses a danger confirm; the no-`window.confirm` scan.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement**, and replace every call site.
- [ ] **Step 4: Run the tests and `make ci`.**
- [ ] **Step 5: Commit.** `git commit -m "Delve's own dialogs instead of the browser's confirm and prompt"`

---

### Task 10: End to end, and the docs

**Files:**
- Create: `tests/e2e/test_a_table_of_three.py`, `web/e2e/table.spec.ts`
- Modify: `README.md` ("Playing with friends"), `GUILD.md`, `docs/glossary.md` (seat; table talk and organiser as
  used), `docs/data-dictionary.md` (seat `role`, `audience` of a story entry, submission `kind`, `fallback`,
  translation `status`), `docs/progress.md`

- **The e2e test, through `delve serve` with the fake `claude`:**
  1. The host invites; a Dutch player and an observer join.
  2. The player claims a PC. Both the host and the player act, and the beat closes on the second act. The DM's input
     holds both, with the Dutch act in English.
  3. The fake DM calls `tell` for the player's character with a planted secret, and the host's stream never gets it.
  4. The player's stream gets the reply's Dutch translation.
  5. Table talk reaches all three.
  6. The observer's act is refused.
  7. With a 30 s timer and a fake clock, the host alone acts, and the player's character holds back.
- **The browser check (`make e2e-browser`):** two browser contexts (host and player) and one at 390×844. Screenshots:
  `web/e2e/screenshots/table-host-1280x800.png`, `table-player-1280x800.png`, `table-phone-390x844.png`,
  `join-390x844.png`, `dialog-confirm-1280x800.png`.
- [ ] **Step 1: Write the e2e test and see it fail where parts are missing.**
- [ ] **Step 2: Make it pass, run `make ci` and `make e2e-browser`.**
- [ ] **Step 3: Update the docs.**
- [ ] **Step 4: Commit.** `git commit -m "Plateau 4 end to end: a table of three"`

---

## Done when

- `make ci` passes on a fresh clone, and `make e2e-browser` writes the five screenshots.
- Three seats play one beat, each in their own language, and the planted secret told to one character reaches only
  that character's seat.
- Solo play is unchanged: one seat's act closes its beat at once.
- No `window.confirm` or `window.prompt` is left.
- No task's tests run the real `claude`.
