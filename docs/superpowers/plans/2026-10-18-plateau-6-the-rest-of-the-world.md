# Delve plateau 6: the rest of the world, implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The party can leave the dungeon. Days pass on a real calendar with its weather. The party travels across a
world map, meets encounters on the way, owns possessions (a mount, a house, a ship), deals with factions and takes on
quests. The DM looks up the setting's lore and runs a magic merchant. Characters, possessions and scenes get pictures:
free portraits with portraitgen, paid images with Replicate when the host allows it. This is feature parity with
ttrpg2's kept list.

**Architecture:**
- **One place where days pass.** `play/days.py` runs every new-day hook (clocks, weather) once per day crossed,
  whoever moved the clock: `advance_time` past midnight, `advance_days`, a whole-party `rest`, or `travel`.
- **The setting answers the world.** The Greyhawk setting gets its data injected (the reference store: the wiki,
  the lore facts, the calendar, a region map), like `Adnd2eRuleset(reference)`. The DM's tools reach it through
  `CampaignContext.setting`.
- **A campaign owns its world.** Its world maps (copied from the module and the setting at creation, then editable),
  its factions, clocks, quests, possessions, merchants, facts and generated images live in campaign tables, all added by
  one migration.
- **World maps are ttrpg2's `.map` DSL** (what `.dscn` `worldmaps` already carry), ported as `delve.maps.world`. The
  server compiles it and renders an SVG, redacted per seat like the dungeon map.
- **Images never hold up a beat.** A paid image is painted in the background and lands in the story when done. A
  portraitgen portrait is only a description and a seed; the browser draws it.

**Tech Stack:**
- **No new Python dependency.** Replicate is called with `httpx` (already a dependency).
- **portraitgen** is vendored: `web/vendor/portraitgen/` is a copy of `/home/raf/claude/portraitgen/src` at commit
  `e6a94a33e96bfafaca60427ba91d8e0da1e16e86`, with its `LICENSE` and a `COMMIT` file holding that hash. No npm
  dependency is added, so a fresh clone builds without the owner's Gitea.

**Spec:**
- `docs/superpowers/specs/2026-10-17-unified-app-design.md`: §4 (what carries over), §5.2 (image provider, portraitgen,
  Settings per image kind), §7.5 (the fourth wall), §7.9 (possessions), §10 (rulesets and settings, world maps), §12
  (storage), §14 (plateau 6).
- `docs/review/feature-review.md` (possessions, setting lookup, `pre_turn_check`).
- `docs/glossary.md` and `docs/data-dictionary.md`.
- The ttrpg2 sources this ports, read-only: `/home/raf/claude/ttrpg2/tools/{weather,travel,factions,quests,lore,
  lore_facts,greyhawk,merchant,holdings,images,world_map}.py`, `/home/raf/claude/ttrpg2/WORLD-MAP-PLAN.md`.

## Decisions taken for the owner

The owner left plateau 6's open points to the designer (2026-10-18). Task 13 copies these into the spec (§7.9, §10 and
a new §10.1) and the glossary.

1. **`pre_turn_check` is not ported.** Its checklist is already in `dm.md`. Its NPC-reaction diff and position come back
   from `party_status`, `room` and the primer.
2. **The calendar belongs to the setting.** Greyhawk uses the Common Year calendar: 12 months of 28 days and 4 festival
   weeks of 7 days, 364 days. The campaign keeps `day` (an integer, as today) and a start date. The date, the month and
   the season are derived, never set by hand. ttrpg2's `set_season` goes away. A campaign without a setting gets a
   plain calendar ("Day 12", four seasons of 91 days).
3. **Weather is one roll per day and terrain.** It is rolled the first time it is asked for on a day (`weather_check`,
   `travel`, the primer) and kept for that day. ttrpg2's tables move over unchanged. forest, hills, plains and ocean
   use the wilderness table, so every encounter terrain has weather. The weather's pace now really slows travel. A
   blizzard (pace 0) costs the day.
4. **Travel moves the party on the world map**, day by day. A day's miles are 2 × the slowest movement rate (or the
   mounts' or the vehicle's), × the terrain's rate, × the weather's pace. One encounter check is made per day: d6 = 1,
   or d20 = 1 in towns. A triggered encounter stops the journey there, partway along the route.
5. **Possessions are one table.** A mount's stats are used: its movement (and flying movement) sets travel speed.
   ttrpg2's 19 mount species defaults come over. Possessions have no management rules.
6. **Factions and quests come from the module.** They are seeded when a campaign is created. Countdown clocks tick
   with the days. A progress clock (the `.dscn` `segments`/`filled` kind) moves only when the DM advances it. ttrpg2
   treated segments as days; Delve doesn't.
7. **Players see what their characters know:** the date, the weather, known quests with their player-facing notes,
   known factions with a standing word ("Friendly"), the party's possessions, and the world map without hidden places.
   They never see clocks, faction notes, strength, the reputation number, `doc` notes on the map, or a quest not yet
   known.
8. **Lore:** the setting's lore is the Greyhawk wiki (`greyhawk.db`) and ttrpg2's lore facts, except its `campaign`
   facts (those belong to ttrpg2 campaigns, which stay there). A campaign's own facts are a campaign table. While the
   DM thinks, the play screen shows a "Did you know" fact from the setting, never a campaign fact.
9. **The merchant's shelf goes to the DM only.** The DM narrates it. Buying pays from the party's coin.
10. **Images:**
    - **Portraits** default to portraitgen, free and instant. portraitgen draws only people, so possessions and scenes
      need a paid backend.
    - **Paid images are off for each campaign until the host turns them on** (`paid_images`). With them off, a
      portrait falls back to portraitgen, and a scene or a possession's picture is refused with a hint.
    - **The Replicate token** comes from `REPLICATE_API_TOKEN` or `<data dir>/replicate-token` (mode 0600). It is
      never stored in the database and never sent to a browser. Replicate is offered in Settings only when a token
      exists.
    - **The DM writes the painter's brief itself.** For the host's "Paint this scene" button, a side pass writes it
      from the last DM narration.
    - Map tokens keep their initials. Portraits on tokens go to the backlog.
11. **The Flanaess:** no structured Flanaess map exists, only raster images. Greyhawk ships ttrpg2's hand-made
    "Greyhawk region" map as its one world map. A Flanaess backdrop image goes to the backlog.
12. **One quest, thirteen tasks.** Task 2 adds the one migration for every new table, so the feature tasks can run in
    parallel without a migration chain to fight over.

## Global Constraints

- **Earlier plateaus still apply:** `GUILD.md`, and the Global Constraints of plateaus 0–5 and of the walkthrough
  fixes.
- **The fourth wall, per seat.** Nothing a seat may not see reaches its browser: not in a route, an event, an SVG, or
  the replay buffer. When in doubt, a seat sees less.
- **Tests never call Replicate, `claude` or the network.** Use `FakeImages`, `FakeDM`, the fake `claude`, and
  `httpx.MockTransport` for the Replicate client.
- **Single-player play stays as fast as it is.** No new tool runs a side pass inside a beat, and no image is painted
  inside a beat.
- **Migration:** Task 2 adds `0013_world`. If master already has a 0013 when the quest starts, use the next free
  number and keep the name.
- **The dependency rules hold.** `delve.setting`, `delve.rules` and `delve.maps` import no storage, play, dm or web.
  The Greyhawk setting gets its reference handle injected.
- **The tool surface:** every new tool is added to `dm/tools/host.py` `all_specs()`, `test_fourth_wall.py`
  (`DM_ONLY_TOOLS` and the `SESSION` list), and the tool-order test. Parallel tasks each add their own lines there;
  merge them, don't overwrite.
- **Words** (glossary): world map, travel, journey, calendar, date, season, weather, faction, standing, clock, quest,
  lore fact, merchant, possession, portrait, scene. Never "hex", "turn" for a day, or "GM".
- **UI strings** come from `en.json` and `nl.json`, `nl` having every key.

## Review Focus

1. **DM-only world information leaks to a seat.** A planted `SECRET-XYZZY` in a hidden world-map place, a map
   feature's `doc`, a faction's `notes_md`, a clock's `on_complete`, an unknown quest, a possession's `notes_md` or a
   merchant's shelf never reaches a second seat: not through `GET …/world`, the world-map view SVG, the story, or the
   event stream with `since=0`. (Task 12 test, with Task 5, 6 and 8 unit tests.)
2. **Days pass in one place.** `advance_days(30)`, `advance_time` across midnight, a whole-party `rest(days=3)` and a
   five-day `travel` each run the new-day hooks exactly once per day crossed. A countdown clock never ticks twice, and
   the year rolls over (28 Sunsebb 576 → 1 Needfest 577). (Task 4 test.)
3. **Travel at the edges.** An unknown destination is refused with candidates. Without a world map, the refusal names
   `edit_world_map`. Places with no road between them fall back to a straight line, noted. A blizzard day covers 0
   miles and still passes. An encounter stops the party partway, at a position on the route. Ocean without a ship is
   refused. A journey over 60 days is refused ("travel in legs"). (Task 8 test.)
4. **Paid images go wrong.** Paid images are off, there is no token, or Replicate fails, is slow, or Delve restarts
   mid-painting. The beat is never held up. A failed image shows a notice. A portrait falls back to portraitgen. A
   row still `painting` at start is retried once. (Task 10 test.)
5. **World maps survive the trip.** A `.dscn` with `worldmaps` keeps them through import, campaign creation and export
   (round trip). A broken `.map` imports with a `worldmap-unreadable` warning, not a failure. Saving a campaign map
   with invalid DSL is refused with the parser's line and message. (Task 7 test.)

---

## File structure

```
src/delve/storage/reference/              greyhawk, lore facts and OSRIC values join the reference store (Task 1)
src/delve/storage/migrations/versions/0013_world.py   every new table and column (Task 2)
src/delve/domain/world.py                 Calendar, GameDate, Weather, Faction, Clock, Quest, Possession, Portrait,
                                          WorldMapSource, Merchant, CampaignImage, LoreFact (Task 2)
src/delve/setting/greyhawk.py, calendar.py, data/greyhawk-region.map   the Greyhawk setting (Task 3)
src/delve/play/days.py, weather.py        days passing, weather (Task 4)
src/delve/rules/adnd2e/weather_tables.py  ttrpg2's weather tables (Task 4)
src/delve/play/factions.py, quests.py     factions, clocks, quests (Task 5)
src/delve/play/possessions.py, src/delve/rules/adnd2e/mounts.py   possessions, mount defaults (Task 6)
src/delve/maps/world/                     the world-map DSL: parse, compile, distance, render (Task 7)
src/delve/play/travel.py, world_maps.py   campaign world maps, position, travel (Task 8)
src/delve/play/merchant.py                the magic merchant (Task 9)
src/delve/images/replicate.py, src/delve/play/images.py   paid images, the painting worker (Task 10)
src/delve/dm/tools/{world,factions,possessions,travel,merchant,lore,pictures}.py   the DM's new tools
src/delve/web/routes/world.py             the world for seats and organisers
web/vendor/portraitgen/, web/src/components/Portrait.tsx   portraits in the browser (Task 11)
web/src/play/WorldPanel.tsx, web/src/campaign/{WorldMaps,Factions,Quests,Possessions}.tsx   screens (Task 12)
```

---

### Task 1: Greyhawk, lore facts and OSRIC values in the reference store

**Files:**
- Modify: `scripts/snapshot_reference.py` (`DUMPS`), `src/delve/storage/reference/build.py`,
  `src/delve/storage/reference/sqlite_reference.py`, `src/delve/domain/reference.py`, `reference/snapshots/`
  (+`SHA256SUMS`), `tests/fixtures/reference/__init__.py` (tiny greyhawk and lore-fact DBs)
- Test: `tests/storage/test_reference.py`

**Interfaces:**
- Produces:
  - **Snapshots:**
    - `greyhawk.sql.gz` from `/home/raf/claude/ttrpg2/settings/greyhawk/greyhawk.db`: the tables `pages`,
      `categories`, `redirects` and the 13 typed tables, renamed with a `gh_` prefix. Leave out `links` and
      `pages_fts`. The build rebuilds `gh_pages_fts` (fts5 on title, raw_text).
    - `lore_facts.sql.gz` from `/home/raf/claude/ttrpg2/global/lore_facts.db`: `facts` where `enabled = 1 AND
      category != 'campaign'`, as `lore_facts(id, text, category, source)`.
    - `osric_magic_items.json.gz` from `/home/raf/claude/ttrpg2/global/osric_magic_items.json`, stored as one JSON
      row in `osric_magic_items`, like `adnd_encounter_tables`.
  - **`Reference` gains:**
    - `setting_page(setting: str, title: str) -> SettingPage | None`, following up to 5 redirects;
    - `setting_rows(setting: str, kind: str, query: str, limit: int) -> list[SettingPage]`: substring on the typed
      table's `name` and `page`;
    - `setting_search(setting: str, query: str, limit: int) -> list[ReferenceHit]`: FTS with snippets. A query is
      quoted as one phrase per word (ttrpg2 broke phrase queries by doubling quotes);
    - `setting_kinds(setting: str) -> dict[str, int]`: kind → row count;
    - `lore_facts(n: int, category: str = "", seed: int | None = None) -> list[LoreFact]`;
    - `osric_magic_items() -> dict`.
  - `SettingPage(title, kind, fields: dict[str, str], text, categories: tuple[str, ...])`. The setting id is
    `"greyhawk"`; the reference holds one setting today.
- [ ] **Step 1: Write the failing tests** on the tiny fixtures: a lookup follows a redirect; a kind's rows; a phrase
  search ("Circle of Eight") finds the page; lore facts never include `campaign`; the OSRIC JSON loads; a stale
  snapshot still raises `ReferenceStale`.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement**, regenerate the snapshots with `uv run python scripts/snapshot_reference.py`, and update
  `SHA256SUMS`.
- [ ] **Step 4: Run the tests and `make ci`.**
- [ ] **Step 5: Commit.** `git commit -m "The reference store gets the Greyhawk wiki, lore facts and OSRIC item values"`

---

### Task 2: World storage

**Files:**
- Create: `src/delve/storage/migrations/versions/0013_world.py`, `src/delve/domain/world.py`,
  `src/delve/storage/sqlite/world_repos.py`
- Modify: `src/delve/storage/interfaces.py`, `src/delve/storage/sqlite/{tables.py,__init__.py}`,
  `src/delve/domain/campaigns.py` (`CampaignState`), `src/delve/domain/characters.py` (`Sheet`),
  `tests/storage/contract.py`, `tests/storage/test_migrations.py`

**Interfaces:**
- Produces:
  - **Migration `0013_world`.** Every table has `campaign_id` (FK campaigns CASCADE) and the primary key shown:

| Table | Columns | PK |
|---|---|---|
| `campaign_state` + | `start_date JSON NULL` (`{year, day_of_year}`), `weather JSON NULL`, `world JSON NULL` | |
| `factions` | `id, name, alignment, goals, scope, known BOOL, strength INT 0–100 (100), reputation INT ±100 (0), notes_md, source_ref NULL` | (campaign_id, id) |
| `clocks` | `id INT autoinc, label, faction_id NULL, kind 'countdown'\|'progress', days_remaining NULL, segments NULL, filled NULL, on_complete, started_day, done_day NULL` | id |
| `quests` | `id, title, giver, scope, stakes, status, known BOOL, started_day NULL, ended_day NULL, related JSON, log JSON, notes_md, source_ref NULL` | (campaign_id, id) |
| `campaign_facts` | `id INT autoinc, text, category, day` | id |
| `possessions` | `id, name, kind, owner_id NULL (FK characters SET NULL; NULL is the party), location, value_gp, description, notes_md, inventory JSON, stats JSON, portrait JSON NULL, created_at, updated_at` | (campaign_id, id) |
| `world_maps` | `name, title, source 'module'\|'setting'\|'campaign', dsl TEXT, revealed JSON, updated_at` | (campaign_id, name) |
| `merchants` | `id, name, npc_id NULL, settlement, cost, seed, rolled_day, items JSON, sold JSON` | (campaign_id, id) |
| `campaign_images` | `id, kind 'portrait'\|'scene'\|'possession', subject_id NULL, status 'painting'\|'done'\|'failed', blob NULL, mime NULL, prompt, backend, audience JSON NULL, error NULL, created_at` | id |

  - **Domain** (`domain/world.py`, frozen dataclasses with `from_dict`/`to_dict` like the others): `Month(name, days,
    season, weather_season, festival)`, `Calendar(id, era, months, default_start)`, `GameDate(year, day_of_year,
    month, day_of_month, season, weather_season, festival, label)`, `Weather(day, terrain, label, effect, pace)`,
    `WorldPosition(map, x, y, at: str | None)`, `Faction`, `Clock`, `Quest`, `QuestNote(day, text, known)`,
    `CampaignFact`, `Possession`, `Portrait`, `WorldMapSource(name, title, dsl)`, `Merchant`, `CampaignImage`,
    `LoreFact`.
    - `Portrait = {"kind": "traits", "describe": str, "seed": str} | {"kind": "image", "image_id": str}`.
    - `Calendar.date(start: tuple[int, int], day: int) -> GameDate`: campaign day 1 is the start date.
    - `PLAIN_CALENDAR`: four 91-day "seasons", labels "Day 12".
  - **`CampaignState`** gains `start_date`, `weather`, `world`. `Sheet` gains `portrait: Portrait | None = None` and
    `faction: str = ""`.
  - **Storage areas:** `factions`, `clocks`, `quests`, `campaign_facts`, `possessions`, `world_maps`, `merchants`,
    `campaign_images`, each with `get`, `list(campaign_id, …filters)`, `put` (or `add` for autoinc ids) and `delete`.
    `campaign_images.painting()` lists every `painting` row across campaigns.
- [ ] **Step 1: Write the failing contract tests** for each area: round trip, cascade on campaign delete, a deleted
  owner leaves a possession to the party; and the migration test (an existing campaign's state keeps its day).
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests and `make ci`.**
- [ ] **Step 5: Commit.** `git commit -m "World storage: factions, clocks, quests, possessions, world maps, merchants and images"`

---

### Task 3: The Greyhawk setting, and lore

**Files:**
- Create: `src/delve/setting/calendar.py`, `src/delve/setting/data/greyhawk-region.map` (a copy of
  `/home/raf/claude/ttrpg2/campaigns/wgr1-greyhawk-ruins/maps/greyhawk-region.map`), `src/delve/dm/tools/lore.py`,
  `tests/setting/test_greyhawk.py`, `tests/dm/tools/test_lore.py`
- Modify: `src/delve/setting/{setting.py,greyhawk.py,fake.py}`, `src/delve/__main__.py` (`build_registries` passes
  the reference to setting factories), `src/delve/play/context.py`, `src/delve/dm/tools/host.py`

**Interfaces:**
- Consumes: Task 1, Task 2.
- Produces:
  - **The `Setting` protocol gains:** `calendar() -> Calendar`; `world_maps() -> tuple[WorldMapSource, ...]`;
    `search(query, limit=10) -> list[ReferenceHit]`; `page(title) -> SettingPage | None`; `lore_facts(n,
    category="") -> list[LoreFact]`. `kinds()` and `lookup()` now answer from the reference store.
  - **Greyhawk kinds:** `place` (settlements and locations), `realm`, `deity`, `character`, `organization`,
    `creature`, `item`, `plane`, `holiday`, `building`, `archfiend`.
  - **The Common Year calendar** (`setting/calendar.py`, `GREYHAWK_CALENDAR`), era "CY", default start 1 Planting
    576. Months in order, with their Greyhawk season and the weather season:

| Month | Days | Season (weather) |
|---|---|---|
| Needfest (festival) | 7 | Midwinter (winter) |
| Fireseek | 28 | Winter (winter) |
| Readying, Coldeven | 28 | Spring (spring) |
| Growfest (festival) | 7 | Spring (spring) |
| Planting, Flocktime, Wealsun | 28 | Low summer (summer) |
| Richfest (festival) | 7 | Midsummer (summer) |
| Reaping, Goodmonth, Harvester | 28 | High summer (summer) |
| Brewfest (festival) | 7 | Autumn (autumn) |
| Patchwall, Ready'reat | 28 | Autumn (autumn) |
| Sunsebb | 28 | Winter (winter) |

    A date's label is `"4 Planting 576 CY"`; a festival day reads `"Richfest, day 4, 576 CY"`.
  - **`CampaignContext`** gains `setting: Setting | None` and `ruleset: Ruleset`, set by `context_for` from the
    campaign's `setting` and `ruleset` columns.
  - **DM tools** (`dm/tools/lore.py`):
    - `setting_lookup(kind, query)`, player-visible: the setting's rows. An unknown kind is refused with the kinds.
      Exactly one hit returns its page text, capped at 4,000 characters.
    - `setting_search(query, limit=10)`, player-visible.
    - `add_fact(text, category="")` (mutates) and `facts(query="")`, `[dm]`: the campaign's own facts.
    - `search_campaign(query)` `[dm]`: substring over the story (English), notes and events, 20 hits of 100
      characters around the match.
  - **Route:** `GET /api/campaigns/{id}/lore/random?n=20`, for a seat: the setting's lore facts, never campaign facts.
- [ ] **Step 1: Write the failing tests:** each kind on the tiny fixture; a redirect; the calendar (day 1 is 1
  Planting 576; day 267 is 1 Needfest 577; every festival label); lookups with no setting are refused with a hint;
  campaign facts round trip; `search_campaign` finds a story entry; the random-facts route never returns a campaign
  fact.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests and `make ci`.**
- [ ] **Step 5: Commit.** `git commit -m "The Greyhawk setting: the wiki, its calendar and region map, lore facts, and the campaign's own facts"`

---

### Task 4: Days pass, and the weather

**Files:**
- Create: `src/delve/play/days.py`, `src/delve/play/weather.py`, `src/delve/rules/adnd2e/weather_tables.py`,
  `tests/play/test_days.py`, `tests/play/test_weather.py`
- Modify: `src/delve/play/sessions.py` (`advance_time`, the primer), `src/delve/play/characters.py` (`rest`),
  `src/delve/dm/tools/notes.py`, `src/delve/dm/tools/party.py`, `src/delve/web/routes/play.py` (`play/state`)

**Interfaces:**
- Consumes: Task 2, Task 3 (`ctx.setting.calendar()`).
- Produces:
  - **`play/days.py`:**
    - `NewDayHook = Callable[[CampaignContext, int], dict[str, Any]]`, called with the new day number;
    - `register(name: str, hook: NewDayHook)`;
    - `pass_days(ctx, days: int) -> dict` moves `CampaignState.day` and runs every hook once per day crossed. It
      returns `{days_passed, date: GameDate, <hook name>: merged results}`, e.g. `clocks: {completed, urgent}`.
    - `today(ctx) -> GameDate`. A campaign with no `start_date` gets its calendar's default on first use.
  - **Who calls `pass_days`:**
    - `advance_time` when the minutes cross midnight;
    - `advance_days(days, reason="")` (new tool, mutates, player-visible), keeping the time of day;
    - `rest` when `character` is empty (the whole party) and `days >= 1`, keeping the time of day;
    - `travel` (Task 8).
    - `set_time` never changes the day.
  - **The weather tables:** `weather_tables.py` holds ttrpg2's `_TABLES` (with the splices) and `_DUNGEON_TABLE`
    verbatim, plus `PACE`, which is ttrpg2's `_WEATHER_PACE` as an ordered tuple of (substring, multiplier).
    `TERRAIN_TABLE` maps the 13 encounter terrains to a table: forest, hills, plains and ocean → wilderness.
  - **`play/weather.py`:** `weather(ctx, terrain: str = "") -> Weather`. It returns today's weather for that terrain,
    rolling with `ctx.dice` (`weighted_pick` over `roll("1d<sum>")`) only when today has none for it. The terrain
    defaults to the last one rolled, else `wilderness`. The roll goes in the dice log and is stored in
    `CampaignState.weather`. `pace(label) -> float`.
  - **Tools:**
    - `weather_check(terrain="")` (mutates, player-visible): `{date, season, terrain, weather, effect, pace}`;
    - `calendar()` (player-visible): `{date, season, festival, day}`.
  - **The primer** gains `date` and `weather`. `play/state` gains `date` (the label) and `weather` (label and
    effect). Players see both.
- [ ] **Step 1: Write the failing tests:**
  - Review Focus 2, with a counting hook: `advance_days(30)`, `advance_time(2000)`, `rest(days=3)`, and a hook run
    exactly once per day;
  - the year rollover;
  - the season derived from the date;
  - the same day asked twice rolls once;
  - every one of the 13 terrains has weather;
  - a blizzard has pace 0;
  - one character resting doesn't move the clock.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests and `make ci`.**
- [ ] **Step 5: Commit.** `git commit -m "Days pass in one place, on the setting's calendar, with a day's weather"`

---

### Task 5: Factions, clocks and quests

**Files:**
- Create: `src/delve/play/factions.py`, `src/delve/play/quests.py`, `src/delve/dm/tools/factions.py`,
  `tests/play/test_factions.py`, `tests/play/test_quests.py`
- Modify: `src/delve/web/routes/campaigns.py` (seeding at creation and upgrade), `src/delve/dm/tools/dice.py`
  (`reaction`), `src/delve/dm/tools/party.py` (`introduce_npc`, `update_character` take `faction`),
  `src/delve/play/sessions.py` (the primer)

**Interfaces:**
- Consumes: Task 2, Task 4 (`days.register`).
- Produces:
  - **Seeding** (`factions.seed(ctx, source: ModuleSource)`) runs at campaign creation, and for older campaigns on
    first use:
    - each `.dscn` faction becomes a `Faction` (`known=False`, strength 100, reputation 0, `source_ref`);
    - each of its clocks becomes a `countdown` clock when it has `days`, else a `progress` clock with its `segments`
      and `filled`;
    - each quest becomes a `Quest` with status `available`, `known=False`.
    - A module upgrade adds new entities and never overwrites play state.
  - **Statuses:** `Quest.status`: `available | active | paused | complete | failed`. `Clock.kind`: `countdown |
    progress`.
  - **Standing words** (`factions.standing(reputation)`): 61+ Devoted, 21+ Friendly, 6+ Cordial, −5+ Neutral, −20+
    Wary, −60+ Hostile, else Sworn enemy (ttrpg2's disposition bands).
  - **The new-day hook `clocks`:** each running countdown clock loses a day. It reports `completed` (just reached 0,
    with its `on_complete`, and `done_day` set) and `urgent` (1–7 days left).
  - **`reaction`** also adds the NPC's faction reputation (`Sheet.faction` → `checks.reputation_modifier`), as the
    rules function already supports.
  - **DM tools:**
    - `factions(known_only=False)` `[dm]`;
    - `update_faction(id, name?, alignment?, goals?, scope?, known?, strength?, reputation_change?, reason?,
      notes?)` (mutates). An unknown id with a `name` creates the faction; without one it is refused with candidates.
      Reputation clamps at ±100 and logs `reputation_change`.
    - `add_clock(label, days?, segments?, faction?, on_complete?)` (exactly one of days and segments),
      `advance_clock(id, segments=1)`, `remove_clock(id)`: mutating, `[dm]`;
    - `clocks()` `[dm]`;
    - `add_quest(id, title, giver="", scope="local", stakes="", related=[])`, `update_quest(id, status?, note?,
      note_known=True, known?)`: mutating, player-visible. A quest becomes `known` when it turns `active`.
    - `quests(status="")` `[dm]`. ttrpg2's scope warnings come over (regional with an average party level under 4,
      continental under 8).
  - **The primer** gains `quests` (active ones) and `clocks` (the five nearest countdowns).
- [ ] **Step 1: Write the failing tests:** seeding from a `.dscn` with a faction, a days clock, a segments clock and a
  quest; an upgrade keeps reputation; a countdown completes once and never again; a progress clock doesn't tick with
  days; reaction with a faction's reputation; standing words at each edge; a quest note marked not known.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests and `make ci`.**
- [ ] **Step 5: Commit.** `git commit -m "Factions, their clocks and standing, and quests, seeded from the module"`

---

### Task 6: Possessions

**Files:**
- Create: `src/delve/play/possessions.py`, `src/delve/rules/adnd2e/mounts.py`, `src/delve/dm/tools/possessions.py`,
  `tests/play/test_possessions.py`
- Modify: `src/delve/play/sessions.py` (the primer's party digest names each character's possessions)

**Interfaces:**
- Consumes: Task 2.
- Produces:
  - **Kinds:** `mount | vehicle | ship | house | stronghold | domain | other`. `owner_id` is a character's id, or
    None for the party.
  - **`stats`** for a mount: `{species, hp, hp_max, ac, mv, fly, thac0, attacks, morale}`. For a vehicle or a ship:
    `{mv, capacity}`. Other kinds take any JSON object.
  - **`mounts.py`:** ttrpg2's `_MOUNT_DEFAULTS` (19 species), plus `fly` for pegasus 48, hippogriff 36, griffon 30,
    giant eagle 48 and giant owl 18 (MM; ttrpg2 stored only their ground movement). An unknown species needs
    `hp_max` and `thac0` (refused otherwise).
  - **DM tools:**
    - `add_possession(name, kind, owner="", species="", location="", value_gp=0, description="", notes="",
      stats={})` (mutates). A mount of a known species gets its defaults, which `stats` overrides.
    - `update_possession(id, …the same fields…, hp_change?)` (mutates); `remove_possession(id)` (mutates);
    - `possessions(owner="")`: everything except `notes_md`, which only `[dm]` `possession(id)` returns.
- [ ] **Step 1: Write the failing tests:** a riding horse's defaults; a griffon flies 30; an unknown species without
  `hp_max` is refused; an owner who dies (is deleted) leaves the horse to the party; `possessions` hides `notes_md`.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests and `make ci`.**
- [ ] **Step 5: Commit.** `git commit -m "Possessions: mounts, ships, houses and the rest, owned by a character or the party"`

---

### Task 7: The world-map language

**Files:**
- Create: `src/delve/maps/world/{__init__.py,parse.py,compile.py,geometry.py,render.py}`, `tests/maps/world/`
  (with the four ttrpg2 maps as fixtures: greyhawk-region, wastes-of-cynidicea, sulm-akar-buildings, cantona)
- Modify: `src/delve/modules/source.py` (`ModuleSource.worldmaps`), `src/delve/modules/importer.py`,
  `src/delve/modules/exporter.py`, `docs/maps/world-maps.md` (new)

**Interfaces:**
- Produces:
  - **The port:** `parse.py` and `compile.py` port ttrpg2's `tools/world_map.py` DSL: `workspace`, `styles`, `model`,
    `views`, `!include`, the 12 feature kinds and their properties. Only the language comes over; ttrpg2 stored it in
    campaign folders, and the port reads none. ttrpg2 has no tests for it, so the four real maps are the fixtures.
    - `parse(text: str, includes: Mapping[str, str] = {}) -> WorldModel`;
    - `WorldMapError(line, message)`;
    - `compile_view(model, view: str | None = None) -> WorldView`, holding features with geometry, `units`
      (default `miles`) and `scale` (miles per map unit, 1 unless the view sets it).
  - **`geometry.py`:**
    - `distance(view, a, b) -> float`: straight line, in miles;
    - `route(view, a, b) -> Route(miles, points, via_roads: bool)`: ttrpg2's Dijkstra over roads with its surface
      multipliers (paved 0.8, stone 0.85, cobble 0.9, dirt 1.0, track 1.2, trail 1.5, rough 1.8). When no road joins
      the two places, it is the straight line with `via_roads=False`.
    - `nearest(view, point, kind="city", n=1)`;
    - `terrain_at(view, x, y) -> str | None` (the `biome` of the terrain polygon there);
    - `point_along(route, miles) -> (x, y)`.
    - `a` and `b` are feature names or `"x,y"`.
  - **`render.py`:** `render_svg(view, *, party: (x, y) | None, hidden: set[str]) -> str`. It draws polygons
    (kingdoms, terrain by biome, lakes), lines (roads by surface, rivers), points with labels (cities, POIs,
    dungeons), the scale bar and the party marker. `hidden` features and their labels are left out entirely. The
    output carries no `doc` text.
  - **Module world maps:**
    - `ModuleSource.worldmaps: tuple[WorldMapSource, ...]`;
    - the importer reads each `ttrpg2-worldmap` file's text and parses it. One that doesn't parse is kept with the
      warning `worldmap-unreadable` (and the parser's line);
    - the exporter writes them back with `container.add_worldmap`.
- [ ] **Step 1: Write the failing tests:**
  - the four fixtures parse and compile;
  - distance and a road route on greyhawk-region (Greyhawk to Hardby uses the road, and its miles are more than the
    straight line);
  - two places with no road fall back to the straight line;
  - `terrain_at` inside the Gnarley Forest;
  - an SVG with a hidden city has no trace of its name;
  - a parse error names its line;
  - Review Focus 5's round trip and broken map.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests and `make ci`.**
- [ ] **Step 5: Commit.** `git commit -m "The world-map language from ttrpg2: parse, distances, roads, and an SVG"`

---

### Task 8: Campaign world maps, and travel

**Files:**
- Create: `src/delve/play/world_maps.py`, `src/delve/play/travel.py`, `src/delve/dm/tools/world.py`,
  `src/delve/dm/tools/travel.py`, `src/delve/web/routes/world.py`, `tests/play/test_travel.py`,
  `tests/web/test_world_api.py`
- Modify: `src/delve/web/routes/campaigns.py` (copy maps at creation), `src/delve/web/app.py`,
  `src/delve/dm/tools/host.py`

**Interfaces:**
- Consumes: Tasks 2, 3, 4, 5 (the `clocks` hook through `pass_days`), 6, 7.
- Produces:
  - **A campaign's world maps:** at creation, and for an older campaign on first use, the module revision's world maps
    (source `module`) and then its setting's (source `setting`) are copied into `world_maps`. On a name clash, the
    module's map wins. After that the campaign owns them. `world_maps.view(ctx, name) -> WorldView`, cached by
    `updated_at`.
  - **The position:** `CampaignState.world = WorldPosition`. The whole party shares one world position (a split party
    is a dungeon-map matter).
  - **Travel** (`travel.travel(ctx, to, *, terrain="", by=(), forced_march=False, map="")`):
    - **The route:** from the position to `to` (a feature or `"x,y"`) on the position's map, through
      `geometry.route`.
    - **Pace:**
      - the base miles a day is 2 × the slowest movement rate among the PCs;
      - with `by`, possession ids: a mount's `fly`, else its `mv`, for its owner; a vehicle's or ship's `mv` for
        everyone;
      - forced march × 1.5.
    - **The terrain** is `terrain`, else `terrain_at` the day's start, else `road` when the route uses roads, else
      `wilderness`. Rates: road, plains, wilderness, urban 1; forest, hills, desert, arctic 1/2; swamp, jungle,
      mountain 1/3; ocean only with a ship (refused otherwise). A flying mount ignores the terrain rate.
    - **Each day:**
      1. `pass_days(ctx, 1)` (clocks tick, the date moves);
      2. the day's weather for the terrain;
      3. miles = base × terrain rate × pace;
      4. an encounter check: `roll("1d6")` = 1, or `1d20` = 1 for urban. A triggered check also calls the ruleset's
         `encounter_check(terrain, level)` for what is met.
      5. On a triggered check, the journey stops. The position is `point_along` the miles done.
    - **The answer:** `{days, arrived, position, legs: [{date, terrain, weather, miles, encounter}], clocks,
      via_roads}`.
    - **Refusals:** an unknown `to` is refused with the nearest names; no world map, with a hint naming
      `edit_world_map`; over 60 days, with "travel in legs".
  - **DM tools:**
    - `travel(to, terrain="", by=[], forced_march=False)` (mutates, player-visible);
    - `place_party(at, map="")` (mutates);
    - `distance(a, b, map="")`;
    - `nearest(kind="city", n=3, map="")`;
    - `world_map(name="", feature="")` `[dm]`: the map's views and features, or one feature with its `doc`;
    - `edit_world_map(name, add="", remove="", title="")` `[dm]`, mutating: creates the map when it is new, adds a DSL
      fragment or removes a feature, refuses a removal that would orphan a reference, and refuses invalid DSL with
      the parser's line;
    - `reveal_place(feature, map="")` (mutates): a `hidden`-tagged feature becomes visible to players.
  - **Routes:**

| Method | Path | Who | Answer |
|---|---|---|---|
| GET | `/api/campaigns/{id}/world` | seat | `{date, weather, position: {map, at_label}, quests, factions, possessions}`, redacted per Decision 7 |
| GET | `/api/campaigns/{id}/world-maps` | seat | `[{name, title}]` |
| GET | `/api/campaigns/{id}/world-maps/{name}/view` | seat | `image/svg+xml`: hidden features left out, the party marker |
| GET | `/api/campaigns/{id}/world-maps/{name}/dm-view` | organiser | every feature, hidden ones dashed |
| GET, PUT, DELETE | `/api/campaigns/{id}/world-maps/{name}` | organiser | `{name, title, source, dsl}`; PUT `{title, dsl}` is 422 with `{line, message}` for invalid DSL |

    - Each change publishes `world` (table scope, ids only), and the browser refetches.
- [ ] **Step 1: Write the failing tests:**
  - Review Focus 3, each case;
  - a five-day road journey arrives, with clocks ticked five times;
  - mounted travel is faster, and a griffon ignores the forest;
  - weather slows a day;
  - the seat's SVG and `GET …/world` leave out a hidden place, then show it after `reveal_place`;
  - the module's map wins a name clash.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests and `make ci`.**
- [ ] **Step 5: Commit.** `git commit -m "Campaign world maps, the party's place on them, and travel day by day"`

---

### Task 9: The magic merchant

**Files:**
- Create: `src/delve/play/merchant.py`, `src/delve/rules/adnd2e/merchant.py`, `src/delve/dm/tools/merchant.py`,
  `tests/play/test_merchant.py`
- Modify: `src/delve/rules/adnd2e/ruleset.py`

**Interfaces:**
- Consumes: Tasks 1, 2.
- Produces:
  - **The catalogue:** `Adnd2eRuleset.merchant_catalogue() -> tuple[CatalogueItem(name, item_type, value_gp, tier,
    price_source)]`, ported from ttrpg2's `tools/merchant.py`:
    - the DMG magic items in `adnd_items` (with ttrpg2's exclusions);
    - each value is the listed cost, else the OSRIC value matched by normalised name, else 5 × XP;
    - plus +1 to +5 armour and weapons;
    - the tiers: up to 2,500 gp common, up to 7,500 less common, up to 20,000 uncommon, above that rare.
  - **Settlements** (stock dice and tier weights, as ttrpg2): hamlet 1d3−1, village 1d3, town 1d4+1, city 2d4,
    capital 2d6, pedlar 1d4+2. Markups: cheap ×1, moderate ×2, expensive ×3.5, very_expensive ×5. Prices round to
    100 from 1,000 gp, and to 10 from 100 gp.
  - **DM tools:**
    - `magic_merchant(merchant, settlement="pedlar", cost="moderate", name="", npc="", restock=False)` (mutates,
      player-visible): rolls the shelf once with `ctx.dice` and keeps it until `restock`. An empty shelf answers
      `{"items": [], "note": "nothing for sale today"}`.
    - `buy_magic_item(merchant, item, character, price_gp=0)` (mutates): pays from the party's coin the way
      `update_coin` converts, and refuses when the party is short ("The party has 340 gp; the price is 2,000 gp").
      The item goes into the character's inventory with its notes, and off the shelf.
- [ ] **Step 1: Write the failing tests:** a seeded shelf for a city; restock; prices round as stated; buying moves
  the item and the coin; too little coin is refused; the shelf never appears in a seat's story (the tool row has no
  body).
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests and `make ci`.**
- [ ] **Step 5: Commit.** `git commit -m "The magic merchant: a shelf by settlement and price, and buying from it"`

---

### Task 10: Pictures: Replicate, the painting worker, and the DM's picture tools

**Files:**
- Create: `src/delve/images/replicate.py`, `src/delve/play/images.py`, `src/delve/dm/tools/pictures.py`,
  `tests/images/test_replicate.py`, `tests/play/test_images.py`
- Modify:
  - `src/delve/__main__.py` (register Replicate when a token exists);
  - `src/delve/web/app.py` (start the worker; resume `painting` rows at start);
  - `src/delve/web/routes/internal_tools.py` (schedule painting after a picture tool);
  - `src/delve/web/routes/play.py` (`GET …/pictures/{image_id}`, `POST …/scene`);
  - `src/delve/domain/campaigns.py` (`StoryKind` gains `scene`), `web/src/play/api.ts`;
  - `src/delve/dm/tools/redact.py` (`player_view` for `scene`);
  - the play settings (`paid_images: bool = False`, host only).

**Interfaces:**
- Consumes: Task 2, Task 6.
- Produces:
  - **`ReplicateImages(token, *, client: httpx.AsyncClient, models=("black-forest-labs/flux-2-pro",
    "black-forest-labs/flux-schnell"))`:**
    - jobs: `image.portrait`, `image.scene`, `image.possession`;
    - `POST https://api.replicate.com/v1/models/{model}/predictions` with `Prefer: wait`, then polls `urls.get` until
      it succeeds, fails, or 120 s pass, and downloads the output;
    - the input is `{prompt, aspect_ratio: "1:1"` for portraits and possessions, `"16:9"` for scenes`,
      output_format: "png", safety_tolerance: 5}`.
    - **The prompt** is ttrpg2's `STYLE_BASE` plus the campaign tone's clause plus the brief. For scenes, "character
      portrait" is dropped from the base (ttrpg2 forced it into every prompt).
  - **`play/images.py`:**
    - `request(ctx, kind, subject_id, prompt, audience) -> CampaignImage` makes a `painting` row, or refuses when paid
      images are off for a scene or a possession;
    - `paint(services, image_id)` (async) runs the provider and stores the blob. On `done`, it sets the subject's
      portrait or makes a `scene` story entry `{image_id, caption}` with the row's audience. On failure it stores
      `failed` with the error. Either way it publishes `characters`, `world` or `story`.
  - **DM tools:**
    - `portrait(of, description="")` (mutates): `of` is a character or a possession.
      - With the portrait job on portraitgen, or paid images off, it sets `Portrait{kind: "traits", describe:
        description or a description built from race, gender, class and age, seed: the subject's id}` at once.
      - Otherwise it requests a painting.
      - A possession needs paid images (refused with a hint otherwise).
    - `paint_scene(brief, caption="", characters=[])` (mutates): needs paid images. With `characters`, the audience is
      those characters.
  - **Routes:**
    - `GET /api/campaigns/{id}/pictures/{image_id}`: for a seat that can see the row's audience; a subject's portrait
      is everyone's at the table.
    - `POST /api/campaigns/{id}/scene {hint?}` (host): a side pass (`Job.SIDE`) writes a painter's brief of 60–120
      words from the last two DM narrations and the hint (ttrpg2's `rewrite_for_image` prompt), then requests a
      scene.
  - **Speed:** the internal tools route schedules `paint` with `asyncio.create_task` after answering. The tool answers
    `{image_id, status: "painting"}` at once.
- [ ] **Step 1: Write the failing tests:**
  - the Replicate client against `httpx.MockTransport`: success, a failure, and a timeout;
  - Review Focus 4, each case, with `FakeImages` and a fake slow provider;
  - a portraitgen portrait is instant and stores only the description and the seed;
  - a scene told to one character reaches only that seat;
  - the token never appears in `GET /api/settings` or `GET /api/backends`.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests and `make ci`.**
- [ ] **Step 5: Commit.** `git commit -m "Pictures: free portraits, paid portraits and scenes painted in the background"`

---

### Task 11: portraitgen in the browser

**Files:**
- Create: `web/vendor/portraitgen/` (the copy, `LICENSE` and `COMMIT`), `web/src/components/Portrait.tsx`,
  `web/src/components/Portrait.test.tsx`
- Modify: `web/src/play/PartySidebar.tsx` (the placeholder), `web/src/campaign/CharacterSheet.tsx`,
  `web/src/play/Story.tsx` (`scene` entries in the story and the gallery strip), `web/src/api.ts` (`Sheet.portrait`),
  `web/tsconfig.json` or `vite.config.ts` (the `portraitgen` alias to the vendored copy)

**Interfaces:**
- Consumes: Task 10's `Portrait` and pictures route.
- Produces:
  - `<Portrait portrait={Portrait | null} name={string} size={number} />`:
    - `traits` → `render(generate({describe, seed}), {size, idPrefix: a unique per-instance prefix})` from the
      vendored `src/index.js`, set as the element's SVG;
    - `image` → `<img src="/api/campaigns/{id}/pictures/{image_id}">`;
    - none → today's initials placeholder.
    - The `alt` is the character's name.
  - Never import `portraitgen/node` (it pulls in resvg).
  - **A test** asserts that the vendored `COMMIT` is `e6a94a33e96bfafaca60427ba91d8e0da1e16e86`, and that the same
    description and seed render the same SVG twice.
- [ ] **Step 1: Write the failing tests:** each portrait kind renders; determinism; the sidebar shows a portrait; a
  `scene` entry shows its image with its caption.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests and `make ci`.**
- [ ] **Step 5: Commit.** `git commit -m "portraitgen portraits in the browser, and scenes in the story"`

---

### Task 12: The world on the play screen and the campaign page

**Files:**
- Create: `web/src/play/WorldPanel.tsx`, `web/src/play/DidYouKnow.tsx`, `web/src/campaign/WorldMaps.tsx`,
  `web/src/campaign/Factions.tsx`, `web/src/campaign/Quests.tsx`, `web/src/campaign/Possessions.tsx`, a test file
  for each, and `tests/web/test_world_fourth_wall.py`
- Modify: `web/src/routes/Play.tsx`, `web/src/play/ThinkingIndicator.tsx`, `web/src/routes/CampaignDetail.tsx`,
  `web/src/play/api.ts` (`PLAY_EVENTS` gains `world`), `src/delve/web/routes/world.py` (organiser CRUD for factions,
  quests and possessions), `web/src/styles.css`, `en.json`, `nl.json`

**What the screens do:**
- **The play head** shows the date and the weather beside the session number ("4 Planting 576 CY · light rain").
- **The World panel:**
  - the world-map SVG with the party marker, and a map picker when there are several;
  - the known quests (title, status, giver, stakes, the player-facing notes);
  - the known factions with their standing word;
  - the party's possessions with their portraits.
  - On desktop it is a tab beside the map panel. On the phone it is a fourth bottom-bar screen, "World".
- **Did you know:** while the DM thinks, the thinking indicator shows a setting lore fact, changing every 8 s. The
  facts come from `GET …/lore/random`.
- **The host's "Paint this scene"** button (only when paid images are on) and the `paid_images` switch in the host
  controls.
- **The campaign page (organisers):**
  - **World maps:** a list, a DSL text area with a live preview through the dm-view, and the parser's error under the
    text area;
  - **Factions and clocks**, **Quests** and **Possessions:** tables with add, edit and delete, using the plateau 4
    dialogs. DM-only fields are marked "DM only".
- **Organiser routes** (all `Organiser`): `GET`, `PUT`, `DELETE /api/campaigns/{id}/factions/{fid}`, `…/clocks/{cid}`,
  `…/quests/{qid}`, `…/possessions/{pid}`, and `GET` on the collections. Each change publishes `world`.

- [ ] **Step 1: Write the failing tests:**
  - Review Focus 1, through two seats' clients and the event stream with `since=0`;
  - the World panel shows quests and possessions from a stubbed `GET …/world`;
  - the phone's fourth screen;
  - the facts rotate (fake timers);
  - the map editor shows a parser error;
  - the organiser tables call their routes;
  - Paint this scene is hidden when paid images are off.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests and `make ci`.**
- [ ] **Step 5: Commit.** `git commit -m "The world on the play screen, and the campaign page's maps, factions, quests and possessions"`

---

### Task 13: The DM's guidance, end to end, and the docs

**Files:**
- Create: `tests/e2e/test_a_journey.py`, `web/e2e/world.spec.ts`
- Modify:
  - `src/delve/dm/prompt/dm.md` (new sections; below);
  - `README.md` ("Out in the world");
  - `GUILD.md` (the new packages);
  - the spec (§7.9, §10, a new §10.1 "The world in play" with the Decisions above, §14 marked delivered at delivery);
  - `docs/glossary.md`, `docs/data-dictionary.md`;
  - `docs/backlog.md` (portraits on map tokens; a Flanaess backdrop image; portraitgen emotes while an NPC speaks);
  - `docs/progress.md`.

**What it covers:**
- **`dm.md` gains "Time and the Calendar", "Weather", "Travel", "Factions and Quests", "Possessions", "The Setting",
  "Pictures" and "Merchants".** Each is short and states:
  - time moves only through `advance_time`, `advance_days`, `rest` and `travel`, and never twice for the same hours
    (`rest` already moves the days);
  - overland journeys go through `travel`, never narrated distances;
  - a triggered encounter on the road is run from the tool's result;
  - what players learn about a faction or quest is set with `known` and `note_known`;
  - setting facts come from `setting_lookup` / `setting_search`, not memory, and the module wins over the setting;
  - a portrait describes what the characters see;
  - scenes are for moments that matter, at most one per scene of play;
  - the shelf is narrated in character, never as a list of numbers unless asked.
- **The e2e test, through `delve serve` with the fake `claude`:**
  1. Create a campaign from a `.dscn` with a world map, a faction with a 3-day clock and a quest.
  2. The fake DM places the party in Greyhawk, gives a PC a riding horse, then calls `travel` to Hardby by road.
  3. The date moves, the clock completes, and the arrival position is Hardby.
  4. A seat's `GET …/world` and SVG show the route's places but not a hidden one.
  5. `portrait` for the PC with portraitgen stores traits.
  6. `paint_scene` with paid images on and `FakeImages` ends in a `scene` entry.
- **The browser check (`make e2e-browser`):** screenshots `web/e2e/screenshots/world-panel-1280x800.png`,
  `world-phone-390x844.png`, `campaign-world-maps-1280x800.png`, `party-portraits-1280x800.png`.
- **The data dictionary** gains:
  - `Quest.status`, `Clock.kind`, the possession `kind`;
  - `campaign_images.status` and `kind`;
  - the standing words, the weather terrains, the `world` event;
  - the `scene` story kind and the `paid_images` play setting;
  - the warning `worldmap-unreadable`.

- [ ] **Step 1: Write the e2e test and see it fail where parts are missing.**
- [ ] **Step 2: Make it pass, and run `make ci` and `make e2e-browser`.**
- [ ] **Step 3: Write the docs.**
- [ ] **Step 4: Commit.** `git commit -m "Plateau 6 end to end: a journey to Hardby, and the docs"`

---

## Order and parallelism

- **Tasks 1, 2 and 7 start at once.** Task 7 touches only `delve.maps.world` and the module source and importer.
- **After Task 2:** Tasks 4, 6 and 10 can start. Task 3 also needs Task 1.
- **After Tasks 2 and 4:** Task 5. **After Tasks 1 and 2:** Task 9.
- **After Tasks 3–7:** Task 8.
- **After Task 10:** Task 11.
- **After Tasks 3–11:** Task 12. **Task 13 is last.**
- **Shared files** that parallel tasks each extend: `dm/tools/host.py`, `test_fourth_wall.py`,
  `play/sessions.py` (the primer), `web/app.py`, `en.json` and `nl.json`. Add your own lines and keep the others'.

## Done when

- `make ci` passes on a fresh clone, and `make e2e-browser` writes the four screenshots.
- A party travels from Greyhawk to Hardby on a real calendar, with weather, a ticking clock and a horse that speeds
  it up. A seat sees the map and its known quests without one DM-only word.
- A portrait is drawn by portraitgen with no paid call. A scene is painted only when the host has turned paid images
  on, and the beat never waits for it.
- No test calls Replicate, `claude` or the network.
