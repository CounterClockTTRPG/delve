# Delve: Looks and campaign banners, implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Each browser picks one of three built-in looks (Delve today, Gold and wood, Dark dungeon), and every campaign
gets a painted, wide banner: painted when the campaign is made, or as soon as its paid-images gate opens.

**Architecture:**
- **A look is a set of CSS tokens** under `:root[data-look="…"]`. A small script, `web/public/look.js`, sets the
  attribute from local storage before the first paint. It's a file, not inline, because the CSP allows `'self'`
  only. Delve today sets no attribute, so its CSS stays exactly as it is.
- **A look's fonts and texture load only when it's chosen,** without lazy stylesheets. Both looks' CSS is in the main
  bundle (`main.tsx` imports it), so the colours are there at the first paint and nothing flashes. Browsers fetch an
  `@font-face` file or a `url()` background only when a matching rule uses it. The fonts are self-hosted
  `@fontsource` packages, and the textures ship in `web/src/looks/textures/`.
- **A banner is a `campaign_images` row of the new kind `banner`.** It's painted by `delve.play.images` like a
  scene, with the scene's choice of model (`Job.IMAGE_SCENE`) at the ratio `21:9`.
- **A banner can wait for the gate.** A new status, `waiting`, holds a banner while paid images are off and the
  scene's model costs money. `delve.play.banners.wake` paints the waiting banners when the gate opens: the host
  turning paid images on, Preferences saved, or Delve starting.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy Core over SQLite, React 18 + TypeScript + React Query, vitest,
Playwright. New npm dependencies: `@fontsource/cinzel`, `@fontsource/eb-garamond`, `@fontsource/im-fell-english` and
`@fontsource/im-fell-english-sc`, each at its latest 5.x, all under the SIL Open Font License. No new Python
dependency and no migration: `campaign_images.kind` and `.status` are free text, with no CHECK.

**Spec:** `docs/superpowers/specs/2026-10-19-looks-and-banners-design.md`, all of it. Owner decisions 1–8 and the
"Calls made for the owner" are fixed requirements. This plan settles "Left to the builder" (see "Decisions taken in
this plan"). File references were checked on master 2e69f05, after the portraits and novelization delivery.

**Reference material outside the repo:** `~/claude/refactoring-assets/looks/` holds the owner's chosen mockups
(`three-looks.html`, `gold-wood-textures.html`, `dungeon-stone-textures.html`) and the two chosen textures,
`wood-Wood051.jpg` and `stone-Rock030.jpg`.
- Both textures are ambientCG, CC0, 512×512 JPEG, 32 KB and 70 KB, so they ship as they are.
- Take the looks' colours, gradients, shadows and type sizes from the mockups' CSS, within the spec's descriptions.
- Never copy anything from ttrpg2.

## Global Constraints

- **Earlier plans still apply:** `GUILD.md`, and the Global Constraints of plateaus 0–7, faithful modules, settings,
  portraits and images, and novelization.
- **Every task leaves `make ci` green on its own** once its prerequisites are merged.
- **Delve today is unchanged:** no `data-look` attribute, `styles.css`'s `:root` and its dark set as they are, and no
  new font or texture fetched. Task 8's browser check counts the requests.
- **A look never changes layout or behaviour.** It changes colours, fonts, textures, borders and shadows, nothing
  else. Maps (`web/src/worldmap/`, the `.dmap` preview `SvgPreview.tsx`), printed maps and print views keep their own
  colours and never follow the look. That covers the 14 hard-coded colours in `*.tsx`, which are all map renderers'.
- **No outside calls at page load.** Fonts and textures come from Delve's own build: no Google Fonts, no CDN.
- **Contrast:** text and controls meet WCAG AA. That's 4.5:1 for body text, and 3:1 for large headings, focus rings
  and control borders, measured against their real background. On a texture, the real background is the wash laid
  over the texture's brightest pixel (Task 5's test).
- **The banner's brief never leaks the module.** It's built only from the module's title, its metadata `summary`
  and `description` (player-safe by the schema), the setting's title and the play settings' tone. It never uses
  keyed text, DM notes, entities or the campaign's story.
- **Making a campaign never waits for its banner and never fails because of it.** Asking for the banner happens
  after the campaign's transaction. Any exception there is logged, and the campaign is still answered 201.
- **Words:** **look** (nl "uiterlijk"), **banner** (nl "banier"), and the looks' names: **Delve today** /
  "Delve vandaag", **Gold and wood** / "Goud en hout", **Dark dungeon** / "Donkere kerker". Never "theme" or "skin"
  in the UI.
- **UI strings:** every one is in `en.json` and `nl.json`. Add each task's keys as one block, after these anchors:
  - Task 4: after `preferences.languageHint`;
  - Task 7: after `play.emptyStory`;
  - Task 8: after the last key Task 4 adds.
- **Tests use only fakes.** The fake image backend paints a 1×1 PNG. No test calls Replicate or assetgen.

## Review Focus

1. **Local storage that throws or holds junk** (a private window, blocked site data, a hand-edited value). The page
   is Delve today with no error, and choosing a look still works for that page view. (Tasks 4 and 5.)
2. **Paid images turned on, then off again, before the waiting banner is painted.** It is painted once, at the first
   opening, and never twice. A banner that's already painting isn't asked again. Turning the gate off doesn't cancel
   a painting under way. (Tasks 2 and 3.)
3. **"Paint again" pressed twice, or while one is painting.** The second press is 409. When the new banner lands it
   replaces the old one, and while it paints, the old one stays shown. When it fails, the old one stays and the error
   shows on the campaign's page. (Tasks 2, 3 and 7.)
4. **A seat of another campaign, a player seat, or an observer asks for a banner.**
   - Each seat reads its own campaign's banner only.
   - Only organisers and the owner paint again.
   - The module page's banner route answers organisers only.
   - A waiting or failed banner's prompt and error reach no seat.

   (Task 3.)
5. **A module with no summary and no description, or a 30 KB Markdown description.** The brief has the title and
   the setting, and at most 600 characters of description with its Markdown stripped. (Task 2.)

## Decisions taken in this plan

1. **No Preferences row of its own:** the banner follows the scene's choice of model, `Job.IMAGE_SCENE`, and its paid
   gate. This adds no new `Job`, and `ImageRequest` gets an `aspect` instead.
2. **The ratio is `21:9`.** Replicate's flux models take it. assetgen sends `aspect_ratio` only to models that take it,
   as it does already.
3. **A banner's failure writes no story entry:** the row keeps its error, and the campaign's page shows it.
4. **Painting again keeps the old banner until the new one lands.** Then every older `banner` row of the campaign is
   deleted (their blobs stay in the blob store, as for any deleted row).
5. **The current banner** is the campaign's newest `done` banner row, and the **pending** one is a newer `painting`,
   `waiting` or `failed` row.
6. **No image provider for the scene job:** the banner is still asked, and the painting fails with the provider's
   reason, shown only on the campaign's page.
7. **The e2e uses the fake backend.** It's free, so the e2e campaign's banner is painted at once (owner decision 8's
   last bullet). The waiting path, then painting when the host opens the gate, is tested in pytest and vitest with a
   paid choice.
8. **The look picker is on the play screen for everyone,** in its header, as well as in Preferences, so the owner
   playing can switch too. The Join page follows the look but has no picker.
9. **The editor:** Monaco gets a second theme, `dmap-night`, based on `vs-dark` with the same token rules on light
   colours. Both new looks use it; Delve today keeps `dmap-paper`.
10. **Sizes:**
    - The play screen's empty story shows the banner at full width, at most 18rem tall, with `object-fit: cover`.
    - The campaign's page shows it at the full content width, `aspect-ratio: 21 / 9`.
    - The module's page shows thumbnails 12rem wide, in a wrapping row, each with its campaign's name under it.

---

## File structure

```
src/delve/domain/world.py                 ImageKind + "banner", ImageStatus + "waiting"            (Task 1)
src/delve/images/provider.py              ImageRequest.aspect                                       (Task 1)
src/delve/images/replicate.py, assetgen.py  use req.aspect or ASPECT_RATIOS[req.job]                (Task 1)
src/delve/play/images.py                  banner kind: JOBS, ASPECTS, _landed, _failed, can_see     (Task 1)
src/delve/play/banners.py                 brief, ask, wake, current, pending, paint_again           (Task 2)
src/delve/web/routes/campaigns.py, play.py, preferences.py, modules.py, app.py  hooks and routes    (Tasks 2, 3)
web/public/look.js                        the before-paint script                                   (Task 4)
web/src/looks/looks.ts, LookPicker.tsx     LOOKS, readLook, applyLook, useLook, the picker            (Task 4)
web/src/looks/gold-wood.css, dark-dungeon.css, textures/, NOTICE.md                       (Tasks 5, 6)
web/src/campaign/Banner.tsx, web/src/play/api.ts, routes/CampaignDetail.tsx, ModuleDetail.tsx, play/Story.tsx (Task 7)
web/e2e/looks.spec.ts                     both browser checks                                       (Task 8)
```

---

### Task 1: Banner rows and the wide painting

**Files:**
- Modify:
  - `src/delve/domain/world.py:438-440` (`ImageKind`, `IMAGE_KINDS`, `ImageStatus`);
  - `src/delve/images/provider.py:13-21`;
  - `src/delve/images/replicate.py:132`;
  - `src/delve/images/assetgen.py:191`;
  - `src/delve/play/images.py`;
  - `src/delve/storage/sqlite/` (the campaign images repo: `list(..., status="waiting")` must work; nothing else
    changes).
- Test: `tests/play/test_images.py`, `tests/images/test_replicate.py`, `tests/images/test_assetgen.py`

**Interfaces:**
- Produces:
  - `ImageKind = Literal["portrait", "scene", "possession", "banner"]`.
  - `ImageStatus = Literal["waiting", "painting", "done", "failed"]`. `waiting` means asked, and held back by the
    paid gate. `campaign_images.painting()` never returns a waiting row, so `resume` doesn't paint it.
  - `ImageRequest.aspect: str = ""`. Empty means `ASPECT_RATIOS[req.job]`.
  - In `delve.play.images`:
    - `BANNER = "banner"`;
    - `JOBS["banner"] = Job.IMAGE_SCENE`;
    - `ASPECTS: dict[ImageKind, str] = {"banner": "21:9"}`. `paint` passes `aspect=ASPECTS.get(image.kind, "")`.
  - A banner landing (`_landed`, kind `banner`) does these things:
    - it stores the row `done`;
    - in the same transaction, it deletes every other `banner` row of the campaign with an older `created_at`
      (`waiting` ones included);
    - it publishes `banner` `{campaign_id, image_id}` with `scope="table"`, and `campaigns` `{id: campaign_id}` with
      the default organisers scope.
  - A banner failing (`_failed`, kind `banner`) stores the row `failed` with its error. It adds no story entry and
    publishes the same two events.
  - `can_see` lets a `done` banner be seen by every seat of its campaign, like a portrait.

- [ ] **Step 1: Write the failing tests:**
  - `test_a_banner_is_painted_wide_with_the_scenes_choice`. A `banner` row painted with a recording fake provider
    gets `req.job is Job.IMAGE_SCENE` and `req.aspect == "21:9"`. The row is `done` with a blob, and the events
    `banner` and `campaigns` were published.
  - `test_a_landed_banner_replaces_the_older_ones`. With banners A (`done`) and B (`painting`, newer): painting B
    leaves only B.
  - `test_a_failed_banner_keeps_the_old_one_and_tells_no_seat`. With A `done` and B failing (the provider raises): A
    stays `done`, B is `failed` with the error, and `storage.story.list(cid)` has no new entry.
  - `test_resume_leaves_waiting_rows_alone`. A `waiting` banner stays `waiting` after `resume`, and nothing is
    scheduled.
  - `test_every_seat_sees_a_done_banner`: `can_see` is true for a player seat and an observer seat of the campaign,
    and false for a seat of another campaign.
  - In `test_replicate.py` and `test_assetgen.py`: a request with `aspect="21:9"` sends `"aspect_ratio": "21:9"`; one
    without it still sends `"16:9"` for a scene.
- [ ] **Step 2: Run them to see them fail:** `uv run pytest tests/play/test_images.py tests/images -k "banner or
  aspect or waiting" -v`. Expected: FAIL (no `banner` kind, no `aspect`).
- [ ] **Step 3: Make them pass:**
  - Add the kind, the status and `aspect`.
  - In both providers, `"aspect_ratio": req.aspect or ASPECT_RATIOS[req.job]`.
  - Add the `banner` branches in `paint`, `_landed`, `_failed` and `can_see`. `request` still refuses an unknown
    kind; banners aren't asked through it (Task 2 has `banners.ask`).
- [ ] **Step 4: Run them to see them pass,** then `make ci`.
- [ ] **Step 5: Commit:** `git commit -m "Banner pictures: a wide campaign_images kind, painted with the scene's choice"`

### Task 2: Asking for a banner, and painting it when the gate opens

**Files:**
- Create: `src/delve/play/banners.py`
- Modify:
  - `src/delve/web/routes/campaigns.py` (`create_campaign`);
  - `src/delve/web/routes/play.py` (`put_table_options`);
  - `src/delve/web/routes/preferences.py` (`put_preferences`);
  - `src/delve/web/app.py:105` (startup, after `images.resume`).
- Test: `tests/play/test_banners.py`, `tests/web/test_campaigns_api.py`, `tests/web/test_play_api.py`,
  `tests/web/test_preferences_api.py`

**Interfaces:**
- Consumes: Task 1's `BANNER`, `ASPECTS`, `schedule`, `paid_images`, `PAID_OFF`, `PAID_HINT`, and `AppServices`'
  `image_paid`.
- Produces, in `delve.play.banners`:
  - `DESCRIPTION_CHARS = 600`
  - `brief(title: str, summary: str, description: str, setting: str, hint: str = "") -> str` returns the painter's
    brief. Its form:
    `"A wide cinematic landscape painting of the world of {title}, in {setting}. {summary} {description}. No
    characters in the foreground, no text, no lettering."`, then `" Emphasis: {hint}."` when there is a hint.
    - The description is cut to `DESCRIPTION_CHARS` with its Markdown stripped (headings, emphasis, links to their
      text, lists to sentences).
    - Empty parts and their punctuation are dropped.
  - `gate_open(services: AppServices, campaign_id: str) -> bool` is `paid_images(...) or not
    services.image_paid(Job.IMAGE_SCENE)`.
  - `ask(services, campaign_id: str, setting_title: str, hint: str = "") -> CampaignImage` makes a new banner row:
    - `painting` and scheduled when `gate_open`, else `waiting`;
    - its prompt is the brief, built from the campaign's module (`storage.modules.get(campaign.module_id)`: its
      `title` and `metadata["summary"]` and `metadata["description"]` when they're strings);
    - it first deletes the campaign's other `waiting` banner rows.
  - `paint_again(services, campaign_id, setting_title, hint="") -> CampaignImage` checks before it asks:
    - while the gate is closed, `PlayError(PAID_OFF, PAID_HINT)`;
    - while a banner of the campaign is `painting`, `PlayError("A banner is being painted already.")` (Task 3 maps it
      to 409);
    - otherwise, `ask`.
  - `wake(services, campaign_id: str | None = None) -> list[str]` handles the waiting banners, of one campaign or of
    all:
    - each one whose `gate_open` is now true becomes `painting` and is scheduled;
    - it returns the ids it scheduled;
    - it's safe to call again: a row that's no longer `waiting` is left alone.
  - `current(storage, campaign_id) -> CampaignImage | None` is the newest `done` banner.
  - `pending(storage, campaign_id) -> CampaignImage | None` is the newest banner row newer than `current` that isn't
    `done`.
- Hooks, all after their transaction, and never failing the request:
  - **`create_campaign`** calls `banners.ask(table(request), campaign.id, <setting title>)`. The setting title comes
    from `registries.settings_.capabilities()` by the campaign's `setting` id, falling back to the id.
  - **`put_table_options`** calls `banners.wake(table(request), campaign_id)` when `raw.get("paid_images") is True`.
  - **`put_preferences`** calls `banners.wake(play.table_of(request.app))`.
  - **Startup** calls `banners.wake(...)` once, after `images.resume`.
  - Each hook wraps the banner call in `try`/`except Exception: log.exception(...)`.

- [ ] **Step 1: Write the failing tests** (`FakeImages`, with `image_paid` switched by a fixture):
  - `test_the_brief_holds_only_what_players_may_know`:
    - the module has a keyed text and an NPC whose DM notes hold `SECRET-XYZZY`, and the metadata summary is
      "Barrows in the fog";
    - the brief contains the title, "Barrows in the fog" and "Greyhawk", and not `SECRET-XYZZY`.
  - `test_a_long_markdown_description_is_cut_and_plain`: a 30 KB description beginning `# Intro\n**Bold** [link](x)`
    gives a brief with "Intro Bold link", no `#`, `*`, `[` or `(x)`, and no more than `DESCRIPTION_CHARS` of its
    text.
  - `test_with_the_gate_open_a_banner_is_painted_at_once`: with a free choice, `ask` gives `painting`, and after
    awaiting the scheduled task it's `done`.
  - `test_with_the_gate_closed_a_banner_waits`: with a paid choice and paid images off, `ask` gives `waiting`, and
    nothing is scheduled.
  - `test_opening_the_gate_paints_a_waiting_banner_once`:
    - `set_play_settings(paid_images=True)` and `wake`: the banner is `painting`;
    - `wake` again: nothing more is scheduled;
    - the gate is off again, then on, then `wake`: still one painting, and the banner ends `done` once.
  - `test_paint_again_obeys_the_gate_and_refuses_a_second_painting`:
    - with the gate closed, `PlayError` with `PAID_HINT`;
    - with it open and one painting, `PlayError` "being painted".
  - `test_current_and_pending` covers decision 5's order.
  - In `test_campaigns_api.py`:
    - `test_making_a_campaign_asks_for_its_banner`: after POST `/api/campaigns`, one `banner` row exists.
    - `test_a_failing_banner_never_fails_the_campaign`: `banners.ask` is monkeypatched to raise, and the POST is
      still 201.
  - `test_play_api.py`, `test_the_host_turning_paid_images_on_wakes_the_banner`: PUT play options
    `{"paid_images": true}` turns the waiting row `painting`.
  - `test_preferences_api.py`, `test_saving_preferences_wakes_banners_whose_gate_opened`: a waiting banner, then
    Preferences choosing the free fake for `image.scene`. The row is `painting`.
- [ ] **Step 2: Run them to see them fail:** `uv run pytest tests/play/test_banners.py tests/web -k banner -v`.
  Expected: FAIL (no module `delve.play.banners`).
- [ ] **Step 3: Write `delve/play/banners.py` and the four hooks.** `ask` and `wake` take the storage's transaction
  around their writes, and call `images.schedule` after it, as `paint_this_scene` does.
- [ ] **Step 4: Run them to see them pass,** then `make ci` (import-linter: `delve.play.banners` imports nothing
  from `delve.web`).
- [ ] **Step 5: Commit:** `git commit -m "A campaign asks for its banner when it is made, and paints it when the gate opens"`

### Task 3: The banner's routes and fields

**Files:**
- Modify:
  - `src/delve/web/routes/play.py` (`_table_state` and the new routes);
  - `src/delve/web/routes/campaigns.py` (`read_campaign`);
  - `src/delve/web/routes/modules.py`.
- Test: `tests/web/test_play_api.py`, `tests/web/test_campaigns_api.py`, `tests/web/test_modules_api.py`,
  `tests/web/test_fourth_wall_per_seat.py`

**Interfaces:**
- Consumes: Task 2's `current`, `pending`, `paint_again`, `gate_open`.
- Produces:
  - **`GET /api/campaigns/{id}/play/state`** gets `"banner": "<image id>" | null`, the current banner, for every seat.
  - **`GET /api/campaigns/{id}/banner`** (`TableSeat`) answers the current banner's bytes, else 404.
    `Cache-Control: no-cache`.
  - **`POST /api/campaigns/{id}/banner`** (`Organiser`), with body `{hint: str = ""}`:
    - 202 with `{image_id, status}`;
    - 422 with `PAID_HINT` while the gate is closed;
    - 409 while one is painting.
  - **`GET /api/campaigns/{id}`** gets a `"banner"` field with these keys:
    - `image_id`, the current banner, or null;
    - `pending`: `{status, error}` or null. `error` is set only for `failed`;
    - `can_paint: bool`, which is `gate_open`;
    - `why_not: str | null`: `PAID_HINT` when `can_paint` is false.
  - **`GET /api/modules/{id}/banners`** (`Organiser`) answers `[{campaign_id, name, image_id}]`. It covers the
    module's campaigns that have a current banner, in the campaigns' list order.
  - **`GET /api/modules/{id}/banners/{campaign_id}`** (`Organiser`) answers that banner's bytes. It's 404 when the
    campaign isn't the module's or has no banner.

- [ ] **Step 1: Write the failing tests:**
  - `test_every_seat_reads_its_own_campaigns_banner`:
    - a player seat and an observer of campaign A get the bytes from `/api/campaigns/A/banner`;
    - a seat of campaign B gets 403 there;
    - `play/state`'s `banner` is the id.
  - `test_only_organisers_paint_again`:
    - a player seat's POST is 403;
    - with the gate closed, the owner's POST is 422, with the hint in the body;
    - with the gate open, 202; a second POST at once is 409.
  - `test_the_campaign_shows_a_pending_failure`: a failed newer banner gives `pending.status == "failed"` and its
    error, and `image_id` is still the old banner.
  - `test_the_module_page_lists_its_campaigns_banners`:
    - two campaigns of module M, one with a done banner: the list has that one;
    - the bytes route answers 200, and 404 for the other campaign and for a campaign of another module;
    - a player seat's token gets 403 on both routes.
  - In `test_fourth_wall_per_seat.py`: plant `SECRET-XYZZY` in a waiting banner's prompt and a failed one's error.
    No seat route or event carries it.
- [ ] **Step 2: Run them to see them fail:** `uv run pytest tests/web -k "banner" -v`.
- [ ] **Step 3: Add the routes and fields.** Serve bytes with `attachment_response(data, image.mime or
  "image/png")`, as `picture` does.
- [ ] **Step 4: Run them to see them pass,** then `make ci`.
- [ ] **Step 5: Commit:** `git commit -m "The banner's routes: for every seat, painted again by organisers, listed on the module"`

### Task 4: The look switch and the picker

**Files:**
- Create:
  - `web/public/look.js`;
  - `web/src/looks/looks.ts`, `web/src/looks/LookPicker.tsx`;
  - `web/src/looks/looks.test.ts`, `web/src/looks/LookPicker.test.tsx`.
- Modify:
  - `web/index.html`: `<script src="/look.js"></script>` in `<head>`, before any stylesheet;
  - `web/src/main.tsx`: call `applyLook(readLook())` before rendering;
  - `web/src/routes/Preferences.tsx`: a "Look" section after the language row;
  - `web/src/routes/Play.tsx:329-343`: `<LookPicker compact />` in `header.play-head`;
  - `web/src/editor/lib/dmapLanguage.ts`: `defineNightTheme`;
  - `web/src/editor/MonacoEditor.tsx:98-99`;
  - `en.json`, `nl.json`.

**Interfaces:**
- Produces:
  - `export const LOOKS = ["delve", "gold-wood", "dark-dungeon"] as const; export type Look = (typeof LOOKS)[number];`
  - `export const LOOK_KEY = "delve.look";`
  - `readLook(): Look` reads the stored value, or `"delve"` for no value, an unknown value, or storage that throws.
  - `applyLook(look: Look): void` sets or clears the attribute, synchronously:
    - `document.documentElement.dataset.look = look` for a new look;
    - the attribute removed for `"delve"`.

    The looks' CSS sets `color-scheme: dark` itself. `main.tsx` imports `./looks/gold-wood.css` and
    `./looks/dark-dungeon.css` after `./styles.css` (Tasks 5 and 6 create them; Task 4 creates them empty).
  - `useLook(): [Look, (look: Look) => void]` stores the choice (in a `try`/`catch`), applies it, and re-renders.
    Other tabs follow through the `storage` event.
  - `<LookPicker compact? />` is a `<select>` labelled "Look", with each look's name and a swatch (a 0.8rem square
    of its `--accent`).
  - `look.js` is about 6 lines, in plain ES5: read `localStorage["delve.look"]` in a `try`; if it's one of the two
    new looks, set `document.documentElement.dataset.look`.
  - `editorTheme(look: Look): "dmap-paper" | "dmap-night"`.
  - i18n keys: `look.title` "Look", `look.hint` "For this browser only.", `look.delve` "Delve today",
    `look.goldWood` "Gold and wood", `look.darkDungeon` "Dark dungeon". The nl values are in Global Constraints;
    `look.hint` in nl is "Alleen voor deze browser."

- [ ] **Step 1: Write the failing tests:**
  - `test("an unknown or unreadable choice is Delve today")`: `"neon"`, nothing stored, and a `localStorage.getItem`
    that throws all give `readLook() === "delve"`.
  - `test("choosing a look sets the attribute and remembers it")`: `useLook` set to `"gold-wood"` gives
    `dataset.look === "gold-wood"` and the stored value.
  - `test("Delve today sets no attribute")`: `applyLook("gold-wood")` then `applyLook("delve")` leaves no `data-look`.
  - `test("a storage that throws on write still switches the page")`.
  - `LookPicker.test.tsx`: three options with their names, and changing to "Dark dungeon" calls the setter.
  - `test("look.js sets the attribute before the app loads")`: evaluate the file's text in a fresh jsdom, with a
    stored `"dark-dungeon"`, and with junk. It sets the attribute only for the first.
  - `test("the editor goes dark in the new looks")`: `editorTheme("gold-wood") === "dmap-night"`.
- [ ] **Step 2: Run them to see them fail:** `cd web && npx vitest run src/looks`.
- [ ] **Step 3: Write the switch, the picker and the night theme,** with `gold-wood.css` and `dark-dungeon.css` created
  empty and imported in `main.tsx`.
- [ ] **Step 4: Run them to see them pass,** then `make ci`.
- [ ] **Step 5: Commit:** `git commit -m "Looks: a per-browser choice, applied before the first paint, in Preferences and on the play screen"`

### Task 5: The Gold and wood look

**Files:**
- Create:
  - `web/src/looks/gold-wood.css`;
  - `web/src/looks/textures/wood-Wood051.jpg` (copied from `~/claude/refactoring-assets/looks/`);
  - `web/src/looks/textures/NOTICE.md`, with the source, the ambientCG URL, CC0 and the date;
  - `web/src/looks/contrast.ts`, `web/src/looks/contrast.test.ts`.
- Modify: `web/package.json` (`@fontsource/cinzel`,
  `@fontsource/eb-garamond`), `styles.css` only to add new tokens to `:root`, left empty (see below).

**Interfaces:**
- Produces:
  - The new tokens, defined empty or as Delve today's values in `:root`, so Delve today is unchanged:
    - `--display` (the display font: headings, the menu, buttons);
    - `--page-texture` and `--page-wash`;
    - `--nav-bg`, `--nav-texture`, `--nav-edge`;
    - `--nav-current-bg`, `--nav-current-ink`;
    - `--button-bg` (a colour or a gradient);
    - `--card-edge`.

    `styles.css` uses them where it now uses `--surface`, `--accent` or `--serif` for those elements, with today's
    values as fallbacks.
  - `contrast.ts` holds the contrast check:
    - `ratio(fg: string, bg: string): number` (WCAG relative luminance, hex colours);
    - `over(wash: string, alpha: number, below: [number, number, number]): string`;
    - `TEXTURE_MAX = { wood: [93, 80, 72], rock: [176, 173, 166] }`, the brightest pixel of each texture.
- The look, under `:root[data-look="gold-wood"]`, follows the spec's colour list:
  - the page is `#17110b`, with a warm radial glow at the top left;
  - `--ink` `#ecdcb8` and headings `#f0d79e`;
  - `--button-bg` is `linear-gradient(#f0d196, #b8904f)`, with `--accent-ink` near-black;
  - cards are a shade warmer than the page, with `--card-edge` a thin brown border and a gold top highlight;
  - `--display` is Cinzel and the body is EB Garamond;
  - the nav is the wood texture under a dark wash, with a gold right edge and an inset shadow, and
    `--nav-current-bg` is gold with dark ink;
  - `--focus` is a gold that meets 3:1 on both the page and the nav.

  The fonts are imported at the top of `gold-wood.css` (`@import "@fontsource/cinzel/600.css"` and the EB Garamond
  weights in use). Their files are fetched only once an element uses the family, so only with the look.

- [ ] **Step 1: Write the failing test** `contrast.test.ts`. It reads `gold-wood.css`'s token values (a small
  regex over the file, as text) and checks these pairs:
  - `--ink` on `--bg` ≥ 4.5;
  - `--ink` on `--surface` ≥ 4.5;
  - `--muted` on `--surface` ≥ 4.5;
  - `--accent-ink` on both ends of the button gradient ≥ 4.5;
  - `--nav-current-ink` on `--nav-current-bg` ≥ 4.5;
  - the nav's text on `over(nav wash, alpha, TEXTURE_MAX.wood)` ≥ 4.5;
  - `--focus` on `--bg` and on the nav's real background ≥ 3.
- [ ] **Step 2: Run it to see it fail:** `cd web && npx vitest run src/looks/contrast.test.ts`.
- [ ] **Step 3: Write the look** and `npm install` the two font packages. Tune the colours (within the spec's
  "about" values) until the test passes.
- [ ] **Step 4: Run it to see it pass,** then `make ci` (the build must bundle the fonts and the texture as assets).
  Then check by hand that no request leaves `localhost` with the look on: the built CSS has no `http`.
- [ ] **Step 5: Commit:** `git commit -m "The Gold and wood look: dark oak, gold and Cinzel"`

### Task 6: The Dark dungeon look

**Files:**
- Create: `web/src/looks/dark-dungeon.css`, `web/src/looks/textures/stone-Rock030.jpg` (with its line in
  `NOTICE.md`)
- Modify: `web/package.json` (`@fontsource/im-fell-english`,
  `@fontsource/im-fell-english-sc`), `web/src/looks/contrast.test.ts`

**Interfaces:**
- Consumes: Task 5's tokens and `contrast.ts`.
- The look, under `:root[data-look="dark-dungeon"]`, follows the spec:
  - the page is `--page-texture` rock under a heavy near-black `--page-wash`, with a faint orange glow at the top
    right;
  - `--ink` is about `#c9ccc8`, and headings are near-white with a faint orange `text-shadow`;
  - `--accent` is about `#e08a3c`, and it's the only bright colour: buttons, the current menu item and links;
  - the nav is near-black;
  - cards are near-black and slightly see-through, with a grey left rule;
  - `--display` is IM Fell English SC, and the body is IM Fell English.
- The texture is fixed to the viewport (`background-attachment: fixed` on `body`). It's left out for print and under
  `prefers-reduced-data`, and it never sits under the story's scrolling list as its own layer (a single body
  background, so scrolling the story stays as fast as it is).

- [ ] **Step 1: Write the failing tests** in `contrast.test.ts`, the dungeon's pairs:
  - `--ink` and links on `over(page wash, alpha, TEXTURE_MAX.rock)` ≥ 4.5;
  - `--ink` on the see-through card over the same ≥ 4.5;
  - `--accent-ink` on `--accent` ≥ 4.5;
  - `--focus` ≥ 3.
- [ ] **Step 2: Run them to see them fail.**
- [ ] **Step 3: Write the look**, install the fonts, and tune the wash until they pass.
- [ ] **Step 4: Run them to see them pass,** then `make ci`.
- [ ] **Step 5: Commit:** `git commit -m "The Dark dungeon look: cave rock, torch orange and IM Fell"`

### Task 7: Banners on the screens

**Files:**
- Create: `web/src/campaign/Banner.tsx`, `web/src/campaign/Banner.test.tsx`
- Modify:
  - `web/src/play/api.ts`: types for `banner` on play state and the campaign; `bannerUrl(campaignId)`,
    `moduleBannerUrl(moduleId, campaignId)`, `paintBannerAgain(campaignId, hint)`, `getModuleBanners(moduleId)`;
  - `web/src/play/Story.tsx:187`;
  - `web/src/routes/CampaignDetail.tsx`: a "Banner" section first, above `campaign.characters`;
  - `web/src/routes/ModuleDetail.tsx`: a "Campaigns" row of thumbnails above `module.maps`;
  - `styles.css`;
  - `en.json`, `nl.json`;
  - `Story.test.tsx`, `CampaignDetail.test.tsx`, `ModuleDetail.test.tsx`.

**Interfaces:**
- Consumes: Task 3's fields and routes.
- Produces:
  - `<Banner src={string} alt={string} variant="story" | "campaign" | "thumb" />` (decision 10's sizes). The frame
    takes `--card-edge`, so each look frames the banner its own way (call 2).
  - The **story**: when the story is empty and `playState.banner` is set, the banner shows above the empty-story line,
    for every seat. With no banner, it's as today. It refetches on the `banner` event.
  - The **campaign's page**:
    - it shows the banner, or the line "No banner yet.";
    - while it waits: "The banner waits until paid images are on.";
    - while it paints: "The banner is being painted…";
    - when it failed: "The banner couldn't be painted:" and the error;
    - under it, a hint field and **Paint again**, shown only when `can_paint`; otherwise `why_not` is shown in place
      of the button;
    - it refetches on `banner` and `campaigns` events.
  - The **module's page**: when there are any, a heading "Campaigns" and the thumbnails, each a link to
    `/campaigns/<id>` with the campaign's name.
  - i18n:
    - `banner.title` "Banner"
    - `banner.none` "No banner yet."
    - `banner.waiting` "The banner waits until paid images are on."
    - `banner.painting` "The banner is being painted…"
    - `banner.failed` "The banner couldn't be painted:"
    - `banner.hint` "Hint (optional)"
    - `banner.paintAgain` "Paint again"
    - `banner.alt` "{name}'s banner"
    - `module.campaigns` "Campaigns"

    nl: "Banier", "Nog geen banier.", "De banier wacht tot betaalde afbeeldingen aan staan.", "De banier wordt
    geschilderd…", "De banier kon niet geschilderd worden:", "Hint (optioneel)", "Opnieuw schilderen",
    "Banier van {name}", "Campagnes".

- [ ] **Step 1: Write the failing tests:**
  - `Story.test.tsx`, `test("an empty story shows the banner above its first line")`, and the same without a banner:
    no `img`.
  - `CampaignDetail.test.tsx`:
    - `test("a waiting banner says why and offers no Paint again")`, with `can_paint: false` and `why_not`: no
      button, and the hint text is shown;
    - `test("Paint again sends the hint")`;
    - `test("a failed banner shows its error under the old one")`.
  - `ModuleDetail.test.tsx`, `test("the module shows its campaigns' banners as links")`: two thumbnails with their
    names, the `href`s `/campaigns/<id>`, and no section when the list is empty.
- [ ] **Step 2: Run them to see them fail:** `cd web && npx vitest run src/campaign/Banner src/play/Story
  src/routes/CampaignDetail src/routes/ModuleDetail`.
- [ ] **Step 3: Write `Banner` and the three places.**
- [ ] **Step 4: Run them to see them pass,** then `make ci`.
- [ ] **Step 5: Commit:** `git commit -m "Banners on the empty story, the campaign's page and the module's page"`

### Task 8: Browser checks, screenshots and docs

**Files:**
- Create: `web/e2e/looks.spec.ts`
- Modify:
  - `docs/glossary.md` (look, banner);
  - `docs/data-dictionary.md` (image kind `banner`, status `waiting`, the local-storage key `delve.look`);
  - `README.md` (the Play section: the look picker; the Modules section: the campaign banners);
  - `docs/progress.md` (an entry for this plan);
  - `docs/backlog.md` (strike the looks/banners item if it's listed).

**Interfaces:**
- Consumes: everything above.
- The spec runs against `tests.e2e.fake_play_server`, whose fake images are free (decision 7). It has two tests.
  1. `test("switch looks, and the choice survives a reload")`:
     - on `/preferences`, choose each look and screenshot it at 1280×800 (`look-delve-1280x800.png`,
       `look-gold-wood-1280x800.png`, `look-dark-dungeon-1280x800.png`);
     - reload and check that `html[data-look]` is still the choice before any app script runs. Use
       `page.waitForFunction` on `document.documentElement.dataset.look` at `domcontentloaded`;
     - open the play screen and the map editor in Dark dungeon, and screenshot them
       (`look-dark-dungeon-play-1280x800.png`, `look-dark-dungeon-editor-1280x800.png`);
     - check that every request the page made went to the test server's origin;
     - in Delve today, from a fresh page: no `.woff2` and no `/looks/textures/` (or hashed `wood-`/`stone-`) asset was
       requested; in Gold and wood, the Cinzel font and the wood texture were;
     - set the look back to Delve today at the end, so later specs' screenshots don't change.
  2. `test("a new campaign's banner shows on its empty story and on its module")`:
     - make a campaign of the Crypt of Saint Vellis through the API;
     - wait for `GET /api/campaigns/<id>` to report an `image_id`;
     - open its play screen: an `img` in the empty story whose `naturalWidth > 0`;
     - open the module's page: a thumbnail linking to `/campaigns/<id>`;
     - screenshots `banner-campaign-1280x800.png` and `banner-module-1280x800.png`;
     - delete the campaign at the end.
- [ ] **Step 1: Write the spec.** It runs before `x-novels.spec.ts` by file order; check that the later specs' fixed
  screenshots still match their expectations (they set no look, so they're Delve today).
- [ ] **Step 2: Run it:** `DELVE_E2E_PORT=20000 make e2e-browser`. Expected: every spec passes, with the new
  screenshots in `web/e2e/screenshots/`.
- [ ] **Step 3: Write the docs.** In the README's own style: one paragraph under Play ("Look": the three looks, for
  this browser only, in Preferences or the play screen's header) and one under Modules (a campaign's banner, when
  it's painted, and Paint again). The glossary entries are **look** and **banner**.
- [ ] **Step 4: Run `make ci`.**
- [ ] **Step 5: Commit:** `git commit -m "Looks and banners: browser checks, screenshots and docs"`

---

## Order and parallel work

- Tasks 1 → 2 → 3 are one line, and so are 4 → 5 → 6.
- The two lines don't touch the same files, apart from `en.json` and `nl.json`, whose blocks have their own anchors.
- Task 7 needs Task 3, and needs Task 5 for `--card-edge`.
- Task 8 needs everything.

## Owner's hand checks after delivery

- Each look on a real phone and on a large screen: does the texture tile well, and is the story readable?
- A real banner with Replicate:
  1. a new campaign with paid images off: the campaign's page says the banner waits;
  2. turn paid images on: it's painted;
  3. Paint again with a hint.
- An organiser seat's Paint again, and a player seat's empty story with the banner.
