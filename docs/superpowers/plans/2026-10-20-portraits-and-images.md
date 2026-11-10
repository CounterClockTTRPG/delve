# Delve: Portraits and images, implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Portraits get a style per campaign and emotes (NPCs speak with lip-sync and a mood, sheets show a PC's
state); Preferences gets a Connections section for the Replicate token and assetgen; assetgen becomes a picture
backend whose models are read live.

**Architecture:**
- **portraitgen learns to play once** upstream (`~/claude/portraitgen`, branch `play-once`), and the new commit is
  vendored into `web/vendor/portraitgen`. Delve's `Portrait` component takes a style and emotes; a campaign's style
  comes from its play settings through one React context.
- **NPC lines become their own story entries** through a new DM tool, `say`, which returns `{"said": …}` like
  `tell` returns `{"told": …}`; the table turns it into a `say` story entry with the speaker, the mood and the line.
- **Connections** are files under the data dir, mode 0600 (`delve.images.connections`), edited through owner-only
  routes. Saving one registers, replaces or unregisters its provider at run time.
- **The backends registry gets live providers:** assetgen's capabilities are read from `GET /api/models`, cached for
  60 s, with each model's label, backend and price. The paid-images gate asks the chosen model whether it is paid.

**Tech Stack:** Python 3.12, FastAPI, httpx, SQLAlchemy Core over SQLite, React 18 + TypeScript + React Query, vitest,
Playwright; portraitgen's own `node --test`. No new dependency.

**Spec:** `docs/superpowers/specs/2026-10-19-portraits-and-images-design.md`, all of it. The owner's decisions 1–5 and
the "Calls made for the owner" are fixed requirements. This plan settles "Left to the builder" (see "Decisions taken in
this plan"). File references were checked on the settings quest's branch `guild/20261019-54c4380e/party`; build this
plan on master once that quest is delivered.

## Global Constraints

- **Earlier plans still apply:** `GUILD.md`, and the Global Constraints of plateaus 0–7, faithful modules and settings.
- **Every task leaves `make ci` green on its own once its prerequisites are merged.** A task that changes a name changes
  every caller, test and docstring in the same task.
- **A token never leaves the server's files:** not in a response, a log line, an error message, an event, an export,
  the DM's context or a test's snapshot. Every route a task adds that touches a token gets a test asserting the
  planted token `tok-SECRET-XYZZY` is absent from the response body and from `caplog`.
- **Owner-only:** the Connections routes use a new `Owner` dependency (Task 3). An organiser seat gets 403. The rest of
  Preferences stays `Organiser`.
- **Tests never call Replicate or assetgen:** `httpx.MockTransport`, as `tests/images/test_replicate.py` does.
  The e2e uses `FakeImages` and the fake `claude`.
- **The fourth wall:** a `say` entry is for everyone, like narration; a line for some characters only stays `tell`'s.
  `say`'s payload carries only what a seat may see (speaker id, name, portrait, mood, text). The planted-secret test in
  `tests/web/test_fourth_wall_per_seat.py` gets a `say` whose NPC sheet holds `SECRET-XYZZY` in its DM notes.
- **Existing portraits render as before:** a campaign without a stored style renders `illustrated`; stored traits and
  seeds are untouched.
- **Motion:** only `blink` and `breathe` stay on. An emote plays once for a line or a change. `sleep` (0 HP) loops,
  since it is a held state. `prefers-reduced-motion` gives the still portrait and the whole line at once. Lists of
  many portraits (the party sidebar, possessions) show idle only.
- **UI strings:** every one is in `en.json` and `nl.json`. Each web task adds its keys as one block right after its
  anchor and never moves another key:

  | Task | Anchor |
  |---|---|
  | 2 | `play.didYouKnow` |
  | 6 | `preferences.title` |
  | 8 | `story.toolRow` |
  | 9 | `sheet.conditions` |

  (If an anchor's name differs on master, the builder takes the key nearest in meaning and says so in the chronicle.)
- **`src/delve/dm/prompt/dm.md`** is edited by Task 7 only, in "## NPCs".
- **Shared test files:** `tests/e2e/fake_play_server.py`, `web/e2e/*.spec.ts` and `web/e2e/screenshots/` belong to
  Task 10 alone.

## Review Focus

1. **A token in an error.** Replicate answers 401 with a body echoing the `Authorization` header; assetgen answers 500
   with a traceback holding the request. The job fails with "Replicate refused the token" / "assetgen failed (500)",
   and neither the job row, the story notice, the log nor the Test button's answer holds the token. (Tasks 3, 5.)
2. **assetgen comes and goes.** It is down at Delve's start, up a minute later; a model is removed from it while a
   choice points at it; it answers `GET /api/models` with an unknown `backend` or no `price`. Preferences shows
   "can't be used" without refusing the save, the job fails clearly, and an unknown backend counts as paid. (Tasks 4,
   5.)
3. **A `say` that names nobody, or the wrong one.** An unknown NPC ref, a PC's id, an NPC of another campaign, an empty
   line, a mood outside the vocabulary, a line of 5,000 characters. The tool answers a `PlayError` with a hint for the
   first four, `neutral` for an unknown mood, and the line is kept whole. (Task 7.)
4. **Old history and many lines.** A story of 300 entries with 40 `say` lines loads with no emote running but the
   newest line's, and a reload never replays a line already shown. (Task 8.)
5. **The SSRF guard.** `http://169.254.169.254/`, `file:///etc/passwd`, `http://example.com`, `http://[::1]:8765`, a
   hostname resolving to a public address, `http://localhost:8765/../../`: only loopback and private addresses with
   http or https pass, checked at save and again at each connection. (Task 3.)

---

## File structure

```
~/claude/portraitgen: src/emote.js, src/render.js, test/             play once, emote durations (Task 1)
web/vendor/portraitgen/, web/src/portraitgen.d.ts                     the vendored commit and its types (Task 1)
src/delve/play/portraits.py                                           PORTRAIT_STYLES, sheet_emote (Tasks 2, 9)
web/src/components/Portrait.tsx, web/src/components/portraitStyle.tsx style and emotes; the campaign's style (Task 2)
src/delve/web/auth.py                                                 Owner (Task 3)
src/delve/images/connections.py                                       the token files, the URL guard (Task 3)
src/delve/web/routes/connections.py                                   the Connections API (Task 3)
src/delve/domain/backends.py                                          live providers, ModelInfo (Task 4)
src/delve/images/assetgen.py                                          the assetgen backend (Task 5)
web/src/preferences/Connections.tsx                                   the Connections section (Task 6)
src/delve/dm/tools/say.py                                             the say tool (Task 7)
web/src/play/SaidLine.tsx                                             a said line with its talking portrait (Task 8)
```

---

### Task 1: portraitgen plays once

**Files:**
- Modify (in `~/claude/portraitgen`, branch `play-once` from e6a94a3): `src/emote.js`, `src/render.js`, `README.md`
- Test: `~/claude/portraitgen/test/portrait.test.js`
- Then in Delve: `web/vendor/portraitgen/src/` (copied), `web/vendor/portraitgen/COMMIT`, `web/src/portraitgen.d.ts`

**Interfaces:**
- Produces (portraitgen): `render(traits, {size, idPrefix, style, emotes, blink, say, once})`. `once: true` gives
  every emote track an iteration count of 1 with `animation-fill-mode: forwards`, resting on pose 0; `blink`/`breathe`
  keep `infinite`. `emoteDuration(traits, {emotes, say}) -> number` (ms, the longest track, delay included).
- Produces (Delve types): `portraitgen.d.ts` declares `render`'s options above, `emoteDuration`, `RENDER_STYLES:
  string[]` and `EMOTES: Record<string, unknown>`.

- [ ] **Step 1: Write the failing tests** in portraitgen: `once: true` with `emotes: ['laugh']` writes no `infinite` in
  the laugh tracks' CSS and one `forwards`; with `blink: true` the blink track still says `infinite`; without `once`
  the output is byte-identical to e6a94a3's for the README's examples; `emoteDuration(t, {emotes:['talk'], say:'Hello
  there'})` grows with the text and is > 0; `emoteDuration(t, {emotes:[]})` is 0.
- [ ] **Step 2: Run** `node --test` in `~/claude/portraitgen`. Expected: the new tests FAIL.
- [ ] **Step 3: Implement** `once` in `createAnimator(uid, {once})` (`timing` takes the count; `fall` keeps
  `infinite` only without `once`) and `emoteDuration` from `buildTracks`' totals. Document both in the README.
- [ ] **Step 4: Run** `node --test`. Expected: PASS. Commit on `play-once`: `Play emotes once, and export their
  duration`. Don't push: the owner merges it into gitea master.
- [ ] **Step 5: Vendor it** in Delve: `git -C ~/claude/portraitgen archive <commit> src | tar -x -C
  web/vendor/portraitgen`, write the commit to `COMMIT`, extend `portraitgen.d.ts`. `make ci`. Expected: PASS
  (`Portrait.test.tsx` unchanged). Commit: `Vendor portraitgen's play-once commit`.

### Task 2: A campaign's portrait style

**Files:**
- Create: `src/delve/play/portraits.py`, `web/src/components/portraitStyle.tsx`
- Modify: `src/delve/play/table.py` (`DEFAULT_PLAY_SETTINGS`, `set_play_settings`), `src/delve/web/routes/play.py`
  (`PlaySettingsIn`, `ORGANISER_OPTIONS`), `web/src/components/Portrait.tsx`, `web/src/routes/CampaignDetail.tsx`,
  `web/src/routes/Play.tsx`, `web/src/routes/Join.tsx`, `web/src/play/api.ts`, `en.json`, `nl.json`
- Test: `tests/play/test_portraits.py`, `tests/play/test_play_settings.py`, `web/src/components/Portrait.test.tsx`,
  `web/src/routes/CampaignDetail.test.tsx`

**Interfaces:**
- Consumes: Task 1's `render` options.
- Produces: `PORTRAIT_STYLES: tuple[str, ...] = ("illustrated", "realistic", "painterly", "inkwash", "engraving",
  "anime", "pixel")` in `delve.play.portraits`; the play setting `portrait_style` (default `"illustrated"`);
  `PortraitStyleProvider({campaignId, children})` and `usePortraitStyle(): string`; `Portrait`'s new props `style?:
  string` (overrides the context), `emotes?: string[]`, `say?: string`, `once?: boolean`.

- [ ] **Step 1: Write the failing tests:**
  - `test_portrait_style_defaults_to_illustrated`: a new campaign's `play_settings(...)["portrait_style"] ==
    "illustrated"`.
  - `test_portrait_style_rejects_unknown`: `set_play_settings(s, c, {"portrait_style": "cubist"})` raises `PlayError`
    naming the seven styles.
  - `test_portrait_styles_match_portraitgen`: the tuple equals `RENDER_STYLES` read from
    `web/vendor/portraitgen/src/` (the registry plus `src/styles/*.js`), so a vendored update can't drift.
  - Route: `PUT …/play/options {"portrait_style": "inkwash"}` is 200 for an organiser, 403 for a host seat that isn't
    one (it joins `ORGANISER_OPTIONS`).
  - Web: `Portrait` inside `PortraitStyleProvider` with style `inkwash` renders the SVG that `render(..., {style:
    'inkwash'})` gives; a painted (`kind:"image"`) portrait ignores the style; the campaign page's "Portrait style"
    select lists the seven, saves through `PUT …/play/options`, and shows a sample portrait in the chosen style.
- [ ] **Step 2: Run** `uv run pytest tests/play -q` and `npm --prefix web test -- Portrait CampaignDetail`. Expected:
  FAIL.
- [ ] **Step 3: Implement.**
  - Store the style in the play settings, not in a new column: `portrait_style` joins `DEFAULT_PLAY_SETTINGS` and its
    check.
  - `PortraitStyleProvider` reads `GET …/play/options` (the query `api.ts` already has) and wraps the play screen, the
    campaign page and the join page.
  - The campaign page gets a "Portraits" section with the select and the sample.
- [ ] **Step 4: Run** `make ci`. Expected: PASS. Commit: `A campaign chooses its portrait style`.

### Task 3: Connections: the owner's tokens

**Files:**
- Create: `src/delve/images/connections.py`, `src/delve/web/routes/connections.py`
- Modify: `src/delve/web/auth.py`, `src/delve/__main__.py` (`register_replicate` reads through `connections`),
  `src/delve/web/app.py` (include the router), `src/delve/domain/backends.py` (`Registry.unregister`, and `register`
  replacing an id)
- Test: `tests/images/test_connections.py`, `tests/web/test_connections_api.py`, `tests/domain/test_backends.py`

**Interfaces:**
- Produces:
  - `Owner = Annotated[Principal, Depends(require_owner)]` in `auth.py`; `require_owner` passes only when
    `principal.seat is None`.
  - In `delve.images.connections`: `ReplicateState = Literal["unset", "set", "environment"]`;
    `replicate_state(data_dir, environ) -> ReplicateState`; `save_replicate(data_dir, token: str) -> None` (writes
    `replicate-token` at 0600, atomically); `remove_replicate(data_dir) -> None`; `Assetgen(url: str, token: str |
    None)`; `load_assetgen(data_dir) -> Assetgen | None`; `save_assetgen(data_dir, url, token: str | None | Keep)`
    (writes `assetgen.json` at 0600; `KEEP` keeps the stored token, `None` removes it); `remove_assetgen(data_dir)`;
    `check_url(url) -> str` (the normalised URL; `ConnectionError` with a reason otherwise).
  - `Registry.unregister(id) -> None`; `Registry.register` with a known id replaces it.
  - Routes, all `Owner`:
    - `GET /api/connections` → `{"replicate": {"state": …}, "assetgen": {"url": str | null, "token": "set" | "unset"}}`
    - `PUT /api/connections/replicate {"token"}` → the state; registers Replicate at once
    - `DELETE /api/connections/replicate` → unregisters it (unless the environment holds a token)
    - `PUT /api/connections/assetgen {"url", "token"?}` (token absent keeps, `null` removes) → registers assetgen
      (Task 5's factory; until Task 5 lands, the route stores only)
    - `DELETE /api/connections/assetgen`
    - `POST /api/connections/{name}/test` → `{"ok": bool, "message": str}`: Replicate's `GET /v1/account`, assetgen's
      `GET /api/models`
  - Each change publishes a `"preferences"` event, so Preferences reloads its backends.

- [ ] **Step 1: Write the failing tests:**
  - A saved token's file is mode 0o600 and the response holds only `"set"`; `GET` after it gives `"set"`;
    `REPLICATE_API_TOKEN` set gives `"environment"` and `DELETE` leaves Replicate registered.
  - After `PUT …/replicate`, `GET /api/backends` lists `replicate` without a restart; after `DELETE`, it doesn't.
  - An organiser seat gets 403 on every route; the owner gets 200.
  - `tok-SECRET-XYZZY` is absent from every response body and `caplog`, the Test route's failure included (a
    `MockTransport` answering 401 with the header echoed back).
  - `check_url`: the Review Focus 5 list, each accepted or refused as written there; a hostname is resolved, and every
    address it resolves to must be loopback or private.
- [ ] **Step 2: Run** `uv run pytest tests/images/test_connections.py tests/web/test_connections_api.py -q`. Expected:
  FAIL.
- [ ] **Step 3: Implement** as above. Replicate errors are re-raised with a fixed message and the status code only.
- [ ] **Step 4: Run** `make ci`. Expected: PASS. Commit: `Connections: the Replicate token and assetgen, owner only`.

### Task 4: Live providers, model labels and the per-model paid gate

**Files:**
- Modify: `src/delve/domain/backends.py`, `src/delve/domain/settings.py` (`resolve`), `src/delve/play/images.py`
  (`request`, `paint_this_scene`), `src/delve/images/replicate.py` (`REPLICATE_CAPABILITIES` gets its models' info),
  `src/delve/web/routes/preferences.py` (`_capabilities_json`)
- Test: `tests/domain/test_backends.py`, `tests/domain/test_settings.py`, `tests/play/test_images.py`,
  `tests/web/test_preferences_api.py`

**Interfaces:**
- Produces:
  - `ModelInfo(label: str, backend: str, price: str | None, paid: bool)` in `delve.domain.backends`;
    `ProviderCapabilities.model_info: Mapping[str, ModelInfo] = {}` and `problem: str | None = None` (why it can't be
    used now).
  - `Registry.register_live(id, caps: Callable[[], ProviderCapabilities], factory)`: `capabilities()` and `for_job`
    call `caps()` on each read.
  - `resolve(...)`: a stored choice whose provider has a `problem`, or whose model is missing from a live provider, is
    kept, with the warning `"{job}: can't be used: {reason}"`. Static providers behave as today.
  - `is_paid(registries, job, choice) -> bool` in `delve.play.images`: portraitgen and the fake are free; Replicate
    is paid; a model with `ModelInfo.paid` decides; an unknown model or backend is paid.
  - `request` and `paint_this_scene` refuse while paid images are off **only** when `is_paid` is true for the chosen
    choice; the hint says the chosen model costs money.
  - `GET /api/backends` adds each model's `label`, `backend`, `price` and `paid`, and the provider's `problem`.

- [ ] **Step 1: Write the failing tests:** a live provider's model added between two `capabilities()` reads appears
  in the second; a stored choice for a live provider with a `problem` resolves to itself plus the warning; with paid
  images off, a scene with a free model (`ModelInfo(paid=False)`) is painted and with Replicate it is refused with the
  hint; an unknown model counts as paid.
- [ ] **Step 2: Run** the four test files. Expected: FAIL.
- [ ] **Step 3: Implement** as above.
- [ ] **Step 4: Run** `make ci`. Expected: PASS. Commit: `Providers that change at run time, and a paid gate per
  model`.

### Task 5: The assetgen backend

**Files:**
- Create: `src/delve/images/assetgen.py`
- Modify: `src/delve/__main__.py` (`register_assetgen`), `src/delve/web/routes/connections.py` (register on save)
- Test: `tests/images/test_assetgen.py`

**Interfaces:**
- Consumes: `connections.load_assetgen`, `check_url` (Task 3); `register_live`, `ModelInfo`, `problem` (Task 4);
  `full_prompt`, `ASPECT_RATIOS` from `replicate.py`.
- Produces: `ASSETGEN = "assetgen"`; `AssetgenImages(url, token, *, client: httpx.AsyncClient, poll_s=1.0,
  timeout_s=300)` implementing `ImageProvider`; `assetgen_capabilities(url, token, *, client, now) ->
  ProviderCapabilities` (cached 60 s; on failure `models=()` and `problem="assetgen isn't answering at <url>"`);
  `register_assetgen(registries, config)`; `AssetgenFailed`.
- Calls assetgen as its README's REST section says:
  - `GET /api/models?kind=image`: every model becomes a `ModelInfo(label, backend, price, paid=backend != "local")`.
  - `GET /api/projects`: finds the project named `delve`; `POST /api/projects {"name": "delve"}` when it's missing.
  - `POST /api/projects/{pid}/generate {"kind": "image", "model", "prompt": full_prompt(job, tone, brief), "params":
    {"aspect_ratio", "output_format": "png"}, "style": true}`.
  - `GET /api/jobs/{id}` polled until `succeeded`, `failed`, `cancelled` or `interrupted`.
  - `GET /api/assets/{ref}/file/{file}`: the PNG.
  - The token, when set, goes as `Authorization: Bearer`.

- [ ] **Step 1: Write the failing tests** (`MockTransport` playing assetgen):
  - the model list becomes `ModelInfo`s, with `sao-small` (kind `audio`) left out;
  - a second read within 60 s makes no request;
  - the project is created once, then reused;
  - a portrait job returns an `ImageFile` with the PNG's bytes;
  - a `failed` job raises `AssetgenFailed("assetgen failed: <its error>")` without the token;
  - a connection error gives the `problem`;
  - the timeout cancels the job (`DELETE /api/jobs/{id}`).
- [ ] **Step 2: Run** `uv run pytest tests/images/test_assetgen.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** as above. `register_assetgen` runs at start when `assetgen.json` exists, and again on each
  `PUT/DELETE /api/connections/assetgen`.
- [ ] **Step 4: Run** `make ci`. Expected: PASS. Commit: `assetgen paints pictures, with its models read live`.

### Task 6: Preferences: Connections and the model labels

**Files:**
- Create: `web/src/preferences/Connections.tsx`, `web/src/preferences/connections.ts`
- Modify: `web/src/routes/Preferences.tsx`, `en.json`, `nl.json`
- Test: `web/src/preferences/Connections.test.tsx`, `web/src/routes/Preferences.test.tsx`

**Interfaces:**
- Consumes: Task 3's routes and Task 4's `GET /api/backends` fields.

- [ ] **Step 1: Write the failing tests:**
  - The owner sees Connections; an organiser seat doesn't (the section is hidden when `GET /api/connections` is 403).
  - The Replicate state shows "Set", "Not set" or "From the environment". The token field is a password input and is
    empty after saving. Remove asks with `useConfirm`.
  - The assetgen URL field defaults to `http://localhost:8765`, and its token is optional.
  - Test shows the answer's `message`.
  - A job's model list shows "flux-schnell · replicate · $0.003" and "local · free".
  - A choice with a `problem` shows "Can't be used: …" and still saves.
- [ ] **Step 2: Run** `npm --prefix web test -- Connections Preferences`. Expected: FAIL.
- [ ] **Step 3: Implement** as above.
- [ ] **Step 4: Run** `make ci`. Expected: PASS. Commit: `Preferences: Connections, and each model's backend and
  price`.

### Task 7: NPCs speak with `say`

**Files:**
- Create: `src/delve/dm/tools/say.py`
- Modify: `src/delve/dm/tools/host.py` (`all_specs`), `src/delve/dm/tools/redact.py` (`player_view` lets `said`
  through), `src/delve/play/table.py` (a `said` result adds a `say` entry, as `_told` does), `src/delve/domain/campaigns.py`
  (`StoryKind` gets `"say"`), `src/delve/play/translate.py` (`OUT_OF_ENGLISH` gets `"say"`), `src/delve/dm/prompt/dm.md`
  ("## NPCs")
- Test: `tests/dm/tools/test_say.py`, `tests/play/test_table.py`, `tests/play/test_translate.py`,
  `tests/dm/tools/test_fourth_wall.py`, `tests/web/test_fourth_wall_per_seat.py`, `tests/dm/test_prompt.py`

**Interfaces:**
- Produces:
  - The tool `say(npc: str, text: str, mood?: str)`, `player_visible=True`, `mutates=False`. It returns `{"said":
    {"speaker": {"id", "name", "portrait": Portrait | None}, "mood": Mood, "text"}}`.
  - `MOODS = ("neutral", "smile", "laugh", "wink", "sneer", "angry", "afraid", "upset", "surprised", "sigh",
    "thinking", "shout", "cry", "disgusted", "nod", "shake")` in `say.py`. Each is a portraitgen emote but `neutral`,
    which is talk only.
  - The story entry `kind="say"`, `payload = said`, audience everyone. `entryText` for a `say` is `text`.

- [ ] **Step 1: Write the failing tests:**
  - the Review Focus 3 cases;
  - the entry's payload has no key beyond the five above, with the NPC's DM notes holding `SECRET-XYZZY` and absent
    from every seat's story;
  - a beat with narration, a `say` and narration again gives three entries in that order;
  - a `say` is translated like a `dm_text`;
  - `dm.md` names `say`, and `test_prompt_names_only_existing_tools` passes.
- [ ] **Step 2: Run** the test files above. Expected: FAIL.
- [ ] **Step 3: Implement.** `dm.md` gets, in "## NPCs": every quoted NPC line goes through `say`, one line per call,
  with the mood the line carries; narration stays in the text; a line for some characters only is `tell`'s.
- [ ] **Step 4: Run** `make ci`. Expected: PASS. Commit: `NPCs speak through say, each line its own entry`.

### Task 8: A said line in the story, talking

**Files:**
- Create: `web/src/play/SaidLine.tsx`
- Modify: `web/src/play/Story.tsx` (`Entry` renders `say` with `SaidLine`), `web/src/play/useStory.ts` (marks entries
  that arrived live), `en.json`, `nl.json`
- Test: `web/src/play/SaidLine.test.tsx`, `web/src/play/Story.test.tsx`

**Interfaces:**
- Consumes: Task 1's `emoteDuration` and `once`; Task 2's `Portrait` props; Task 7's payload.
- Produces: `SaidLine({entry, live: boolean})`.
  - A live line shows its text growing at the talk animation's pace, with the portrait playing `talk` and `say: text`.
  - Then it plays the mood's emote once (`once: true`), then rests on `blink` and `breathe`.
  - A line from history, or any line under reduced motion, shows whole and still.
  - Only the newest live line animates: a newer one stops the older.

- [ ] **Step 1: Write the failing tests** with fake timers:
  - a live line's text is partial at half its `emoteDuration` and whole after it;
  - the portrait's render options go `talk` → mood → idle;
  - a history line renders whole with idle options;
  - `matchMedia('(prefers-reduced-motion: reduce)')` gives whole and still;
  - a second live line stops the first's animation;
  - a line without a portrait shows the initial.
- [ ] **Step 2: Run** `npm --prefix web test -- SaidLine Story`. Expected: FAIL.
- [ ] **Step 3: Implement** as above.
- [ ] **Step 4: Run** `make ci`. Expected: PASS. Commit: `A said line talks, then shows its mood`.

### Task 9: The sheet shows a PC's state

**Files:**
- Modify: `src/delve/play/portraits.py` (`sheet_emote`), the character API's sheet JSON (where `state` is sent),
  `web/src/campaign/CharacterSheet.tsx`, `en.json`, `nl.json`
- Test: `tests/play/test_portraits.py`, `web/src/campaign/CharacterSheet.test.tsx`

**Interfaces:**
- Produces: `sheet_emote(hp: int, hp_max: int, conditions: list[str]) -> Literal["sleep", "afraid", "upset", "idle"]`,
  checked in this order:
  - `sleep` at hp ≤ 0 or the condition `downed` or `unconscious`;
  - `afraid` for a condition matching `fear|frighten|afraid|scared|terrified` (case-insensitive);
  - `upset` at hp ≤ ⌊hp_max / 3⌋;
  - otherwise `idle`.

  The character JSON gets `"emote"`. The sheet plays `sleep` looping, `afraid` and `upset` once when the emote
  changes, and idle otherwise.

- [ ] **Step 1: Write the failing tests:**
  - the boundaries: 7/21 → upset; 8/21 → idle; 0/21 → sleep; `["Frightened"]` at full HP → afraid; `["downed"]` at
    5/21 → sleep; `hp_max` 0 → no division error, idle;
  - the sheet re-renders with `once` when `emote` changes and loops `sleep`.
- [ ] **Step 2: Run** `uv run pytest tests/play/test_portraits.py -q` and `npm --prefix web test -- CharacterSheet`.
  Expected: FAIL.
- [ ] **Step 3: Implement** as above.
- [ ] **Step 4: Run** `make ci`. Expected: PASS. Commit: `The sheet's portrait shows the character's state`.

### Task 10: End to end, and the browser check

**Files:**
- Modify: `tests/e2e/fake_play_server.py` (a beat with a `say` by an NPC with a portrait; the campaign's style
  `inkwash`), `web/e2e/world.spec.ts`, `web/e2e/play.spec.ts`
- Create: `tests/e2e/test_portraits.py`
- Screenshots: `web/e2e/screenshots/said-line-1280x800.png`, `portrait-style-1280x800.png`,
  `connections-1280x800.png`, and `said-line-390x844.png`

- [ ] **Step 1: Write** `tests/e2e/test_portraits.py`:
  - the fake `claude` plays a beat with narration, `say`, narration;
  - the story has a `say` entry with the NPC's portrait;
  - a `PUT /api/connections/replicate` with a fake token lists Replicate in `/api/backends` without a restart;
  - the token is in no response and no log.
- [ ] **Step 2: Write the browser checks:**
  - the campaign page's style choice re-renders the sample and the party in `inkwash`;
  - a said line's text grows, then is whole;
  - Connections shows "Set" after saving and never the token.
- [ ] **Step 3: Run** `make ci` and `make e2e-browser`. Expected: PASS, with the screenshots written. Commit: `End to
  end: styles, said lines and Connections`.

### Task 11: The docs

**Files:**
- Modify: `docs/glossary.md` (portrait style, emote, said line, Connections), `docs/data-dictionary.md` (the play
  setting `portrait_style`, the story kind `say`, the files `replicate-token` and `assetgen.json`), `docs/backlog.md`
  (strike items 10 and 12; add "a local image model in assetgen", the owner's wish and assetgen's own project),
  `README.md` (Connections, assetgen, portrait styles), `docs/progress.md` (this plan's entry)

- [ ] **Step 1: Write** the entries.
- [ ] **Step 2: Run** `make ci`. Expected: PASS. Commit: `Docs: portraits, emotes, Connections and assetgen`.

---

## Order and parallelism

| Wave | Tasks | Waits for |
|---|---|---|
| 1 | **1**, **3**, **7** | nothing |
| 2 | **2**, **4**, **9** (backend half first) | 2: 1. 4: 3. 9: 1 |
| 3 | **5**, **8** | 5: 3, 4. 8: 1, 2, 7 |
| 4 | **6** | 3, 4, 5 |
| 5 | **10**, **11** | everything; Task 11 can be drafted during wave 3 |

**Shared files:**

| File | Tasks (wave) |
|---|---|
| `src/delve/domain/backends.py` | 3 (1), 4 (2) |
| `src/delve/__main__.py` | 3 (1), 5 (3) |
| `src/delve/web/routes/connections.py` | 3 (1), 5 (3) |
| `src/delve/play/portraits.py` | 2 (2), 9 (2): Task 2 creates it, and Task 9 adds `sheet_emote` after Task 2 merges |
| `src/delve/play/table.py` | 7 (1), 2 (2) |
| `web/src/components/Portrait.tsx` | 2 (2) only |
| `en.json`, `nl.json` | 2, 6, 8, 9, each one block after its anchor |

**If the budget runs short,** defer Task 6's price labels (keep the section), then Task 9's `afraid`. Never defer a
token test or a fourth-wall test.

## Done when

- `make ci` passes after every task's merge, and on a fresh clone at the end; `make e2e-browser` passes and writes
  Task 10's screenshots.
- portraitgen's `play-once` branch passes `node --test`, and its commit is the vendored `COMMIT`.
- No token appears in any response, log, event or export (the planted-token tests).
- The chronicle lists each task's delivery, the test counts, the deviations, the decisions taken without the owner, the
  screenshot paths, and the owner's delivery steps:
  - merge portraitgen's `play-once` into gitea master;
  - enter the Replicate token;
  - start assetgen and save its URL.

## Decisions taken in this plan

| # | Question | Answer | Why |
|---|---|---|---|
| 1 | Where the style is stored (spec: "a migration") | The play setting `portrait_style`, beside `tone` and `paid_images`; no migration. | The campaign's other look-and-feel choices already live there, with their check and route; a column would be a second place for the same kind of value. |
| 2 | The mood vocabulary | `MOODS` (Task 7): 15 portraitgen emotes plus `neutral`. | The emotes a spoken line can carry; idle, sleep and head-only emotes (`lookaround`, `yawn`) don't read as a line's mood. |
| 3 | How a mood is carried | On the `say` entry's payload, from the new tool's argument. | Owner decision 5 makes every NPC line its own entry; the mood belongs to the line. |
| 4 | The hurt threshold | hp ≤ ⌊hp_max / 3⌋ is `upset`. | The spec's "below a third", with whole numbers. |
| 5 | Frightened | A condition matching `fear|frighten|afraid|scared|terrified`. | Conditions are free strings in Delve; the DM writes them in its own words. |
| 6 | Talking without streaming | A `say` arrives whole; the browser reveals it at the talk animation's pace. | A tool's result isn't streamed; the reveal gives the spec's "while a line streams in" to every line. |
| 7 | The secret store | Files under the data dir at 0600: `replicate-token` (as today) and `assetgen.json`. | Delve has no secret store; the Replicate token is already a file, and the spec forbids the `settings` JSON. |
| 8 | How Delve waits on assetgen | Polling `GET /api/jobs/{id}` every second, up to 300 s, then cancel. | The same shape as `ReplicateImages`; no event stream to keep open. |
| 9 | Style doubling | Delve sends `full_prompt` (base, tone, brief) with `"style": true`, to its own project `delve`, created without a style. | Nothing doubles unless the owner gives that project a style in assetgen, which then adds to Delve's on purpose. |
| 10 | An unknown assetgen backend | Counts as paid. | A wrong "free" would spend the owner's money with paid images off. |
| 11 | The SSRF guard | http(s) only; the host's every resolved address loopback or private; checked at save and at each connection. | Covers rebinding between save and use, as the spec's call requires. |
| 12 | The portraitgen change | Made on `~/claude/portraitgen` branch `play-once`, not pushed; vendored from that commit. | The owner's repo; the owner merges it. If the quest can't write that repo, Task 1 stops and asks before anything else. |
| 13 | The Connections layout | A section at the top of Preferences, owner only: Replicate (state, token field, Save, Remove, Test), then assetgen (URL, token, Save, Remove, Test). | Owner-only items first, and one row per connection. |
