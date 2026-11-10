# Delve plateau 3: writing modules, implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** You write your own module in Delve and play it. A module's text, attachments, NPCs, encounters, factions
and quests are edited in the app: the text in a light word processor whose keyed headings link to map rooms by
themselves, the entities as forms. The whole module exports as a `.dscn` file and imports back the same. A campaign
names its ruleset and its setting. In play, the DM shows the module's player images in the story.

**Architecture:**
- **One source of truth per module:** a `ModuleSource` (its text documents as Markdown, its entities, its explicit
  keys, its attachments' manifest entries) is the working copy, stored as JSON beside the maps. Everything the DM and
  the search use (`ModuleText`, the index, the keys) is derived from it. A revision pins a copy of it; attachment bytes
  live in the blob store by sha256 and are never deleted, so a pinned revision always finds its images.
- **The format:** `.dscn` version 2 adds a `description` to every asset. Import reads versions 1 and 2. Export writes
  the whole module: text, keys, entities, attachments, maps and metadata.
- **The editor:** the module page gains tabs: Text (TipTap, Markdown round-trip), NPCs, Encounters, Factions,
  Quests (forms), Attachments, Maps (as today) and Details (the metadata form).
- **Images in play:** a `show_image` tool puts an `image` entry in the story, served to the players through a route
  that only answers for the campaign's player images.

**Tech Stack:**
- **New web dependencies, exact versions:** `@tiptap/core`, `@tiptap/pm`, `@tiptap/react`, `@tiptap/starter-kit`,
  `@tiptap/markdown`, `@tiptap/extension-table`, `@tiptap/extension-image`, all `3.31.4` (released 2026-09-30).
- No new Python dependency.

**Spec:**
- `docs/superpowers/specs/2026-10-17-unified-app-design.md` §8.1 (what a module is), §8.2 (the editor), §8.3 ("Other
  import and export": `.dscn` import and export), §10 (rulesets and settings), §7.5 (the fourth wall) and §14
  (plateau 3).
- `docs/maps/scenario-format.md`: the `.dscn` format (text and keyed sections §5, refs §6, entities §7, assets §9,
  import security §11).
- `docs/progress.md`: "Carried into plateau 3", and the first real session's findings.
- `docs/glossary.md`.

**Owner decisions for this plateau:**
- **Showing images to players is in plateau 3** (2026-10-18).
- From the spec: TipTap with a tested Markdown round-trip; no anchors to type; forms for NPCs, encounters, factions
  and quests only; desktop only; no house rules in a module; a module can be only a map.

## Global Constraints

- **Earlier plateaus still apply:** everything in the Global Constraints of plateaus 0 to 2b and in `GUILD.md` holds.
- **The copied `dscn` package changes deliberately in this plateau, and only in Task 2:** the version bump, asset
  `description`, and the v1 reader. Every copied test keeps passing, adjusted only where the version number is
  asserted.
- **Audience words:** the format says `gm` and `player`; Delve's model and UI say `dm` and `player` ("DM only" and
  "Players" in the UI). The mapping happens only at import and export.
- **Uploads:** `POST /api/modules/{id}/assets` is the second raw-body exception to the JSON rule. Its
  `Content-Type` must be one of `image/png`, `image/jpeg`, `image/webp`, `image/gif`, `image/svg+xml`,
  `application/pdf` (anything else is 415; `text/plain` would be CORS-safelisted), at most 64 MB (413). The bytes
  must match the type (`media.type_matches`), and active SVG is refused (`svg_is_active`), with 400.
- **Attachment bytes are served** with `X-Content-Type-Options: nosniff`, and SVG with
  `Content-Security-Policy: sandbox`.
- **The fourth wall:** a player's screen never receives DM-only text, a DM-only attachment, or an entity. The story's
  `image` entry is the one tool output allowed past `player_view`, and only for a player attachment.
- **Migrations:** Task 1 adds `0006_module_source`, Task 7 adds `0007_campaign_world`. They chain in that order.
- **Words:** DM, beat, module, revision, attachment, image (glossary). Never "GM", "handout" as a kind, or "asset" in
  the UI (the format's word; the UI says attachment).
- **UI strings** in `en.json` and `nl.json`, as always.

## Review Focus

1. **A round-trip through the editor loses something.** A heading's `{#anchor}`, a `[[npc:…]]` ref, an
   `![…](asset:…)` image, a read-aloud blockquote or a table changes when a text is opened and saved without edits.
   Saving unchanged text gives the same Markdown, on every text of the crypt sample and the fixture. (Task 5 test.)
2. **A campaign plays a module while it's edited.** An attachment is deleted from the working copy, or a text is
   rewritten. The campaign's pinned revision still serves its image and its old text, until the host upgrades. (Task 1
   and Task 8 tests.)
3. **A DM-only attachment reaches a player.** `show_image` with a DM-only attachment is refused, and the campaign
   image route answers 404 for it and for any id the pinned revision doesn't hold, with the owner token too. (Task 8
   test.)
4. **A hostile upload or import.** An SVG with a script, a PNG declared as JPEG, a `text/plain` upload, or a 65 MB file
   is refused with 400, 415 or 413, and nothing is stored. (Task 4 test.)
5. **A module imported before this plateau.** It has no source row. The first read builds the source from its stored
   bundle, and its text, keys and entities are what they were. (Task 1 test.)

---

## File structure

```
src/delve/modules/source.py                ModuleSource; from_bundle, derive (ModuleText, links, warnings)
src/delve/modules/exporter.py              export_module: the whole module as a .dscn v2 Bundle
src/delve/modules/dscn/                    (Task 2 only) version 2, asset description, v1 reader
src/delve/storage/sqlite/module_sources_repo.py
src/delve/storage/migrations/versions/{0006_module_source,0007_campaign_world}.py
src/delve/web/routes/module_source.py      texts, entities, source, links and warnings
src/delve/web/routes/assets.py             attachments: upload, describe, delete, bytes
src/delve/web/routes/worlds.py             GET /api/worlds
src/delve/setting/greyhawk.py              the Greyhawk setting, by name (lookups come in plateau 6)
src/delve/dm/tools/images.py               show_image
web/src/module/{TextEditor,MarkdownRoundTrip,KeyChip,EntityForm,AttachmentsPanel,DetailsForm}.tsx
web/src/routes/ModuleDetail.tsx            the tabs
```

---

### Task 1: The module source

**Files:**
- Create: `src/delve/modules/source.py`, `src/delve/storage/sqlite/module_sources_repo.py`,
  `src/delve/storage/migrations/versions/0006_module_source.py`, `tests/modules/test_source.py`,
  `tests/storage/test_module_sources.py`
- Modify: `src/delve/modules/importer.py`, `src/delve/storage/sqlite/modules_repo.py` (snapshot),
  `src/delve/storage/interfaces.py`, `src/delve/storage/sqlite/tables.py`

**Interfaces:**
- Produces:
  - `TextDoc(id: str, title: str, audience: Literal["dm", "player"], map: str | None, markdown: str)`
  - `Attachment(id: str, type: str, sha256: str, size: int, description: str, audience: Literal["dm", "player"])`
  - `ModuleSource(texts: list[TextDoc], entities: dict[str, list[dict]], keys: list[dict], attachments:
    list[Attachment])` with `to_json()` / `from_json(raw)` and `attachment(id) -> Attachment | None`.
  - `from_bundle(bundle: Bundle) -> ModuleSource`: v1 `caption` becomes `description`; `gm` becomes `dm`.
  - `Link(text_id: str, anchor: str, key: str, map: str, node: str, label: str, explicit: bool)`
  - `Warning(code: str, message: str, ref: str)`, codes `room-without-text`, `key-without-room`,
    `missing-attachment`, `missing-entity`.
  - `derive(source: ModuleSource, maps: Sequence[ModuleMap]) -> Derived(text: ModuleText, links: list[Link],
    warnings: list[Warning])`.
  - `storage.module_sources.get(module_id) -> ModuleSource | None`, `.put(module_id, source)`;
    `storage.module_sources.revision(module_id, number) -> ModuleSource | None`.
  - `load_source(storage, module_id) -> ModuleSource` (builds and stores it from the source bundle when missing).
  - `save_source(storage, module_id, source) -> Derived`: stores the source and the derived text (the existing
    `module_texts.put`) in one transaction.

**Links (spec §8.2, "no anchors to type"):** the explicit `keys` come first. Then every keyed heading of a text
(`dscn.text.parse_heading`) without an explicit key links through `dscn.keys.match_node` to a node on the text's
`map`, else the module's default map. A map that doesn't parse links nothing and adds no warning. Warnings:
`room-without-text` for every room of a played map with no link; `key-without-room` for every keyed heading with
none; `missing-attachment` for an `asset:` ref with no attachment; `missing-entity` for an `npc:`, `encounter:`,
`faction:` or `quest:` ref with no record.

- [ ] **Step 1: Write the failing tests**

```python
def test_from_bundle_keeps_text_entities_keys_and_attachments(crypt_bundle): ...
    # source.texts ids and markdown equal the bundle's text files; entities equal; keys equal;
    # every attachment has sha256/size from the manifest, audience "dm" for "gm".
def test_derive_matches_unpack_for_the_crypt(crypt_bundle):
    # derive(from_bundle(b), maps).text == text.unpack(b)  (sections, keys, entities)
def test_a_keyed_heading_links_itself_to_its_room():
    # a text "## 2. Throne Room" on a map with room throne_chamber labelled "Throne Room", no explicit key:
    # one Link(key="2", node="room.throne_chamber", explicit=False); no key-without-room warning
def test_warnings_for_unlinked_rooms_keys_and_refs(): ...  # one of each code, with its ref
def test_snapshot_pins_the_source_and_its_attachments(storage):
    # put source with attachment a1; snapshot -> rev 1; delete a1 from the working source; snapshot -> rev 2;
    # module_sources.revision(id, 1).attachment("a1") is not None; blobs.get(sha) still answers
def test_a_module_imported_before_plateau_3_gets_its_source_on_first_read(storage): ...  # Review Focus 5
```

- [ ] **Step 2: Run them and see them fail.** `uv run pytest tests/modules/test_source.py
  tests/storage/test_module_sources.py -v`
- [ ] **Step 3: Implement.** Migration 0006 adds `module_sources(module_id PK FK CASCADE, source JSON, updated_at)`
  and a nullable `module_revisions.source JSON`. `snapshot` copies the working source, and `_same` compares it too.
  The importer stores the source and puts each asset's bytes in the blob store (`link(module_id, "attachment",
  sha)`), and drops the `NOT_UNPACKED` warning. Only `delve.storage` touches SQL; `delve.modules.source` is pure.
- [ ] **Step 4: Run the tests and `make ci`.**
- [ ] **Step 5: Commit.** `git commit -m "The module source: one editable copy of a module's text, entities, keys and attachments"`

---

### Task 2: `.dscn` version 2 and whole-module export

**Files:**
- Create: `src/delve/modules/exporter.py`, `tests/modules/test_export_round_trip.py`
- Modify: `src/delve/modules/dscn/` (`format.py` `VERSION = 2`, `scenario.schema.json`, the reader), `docs/maps/scenario-format.md`
  (§9: `description`; a "Version 2" note), `src/delve/web/routes/modules.py` (`export.dscn` uses `export_module`)

**Interfaces:**
- Consumes: `load_source`, `ModuleSource`, `from_bundle` (Task 1).
- Produces: `export_module(storage, module_id) -> Bundle`.

**The schema change:** an asset gains `"description": {"type": "string"}`, kept beside `caption`. A v2 bundle
needs a `description` on every asset with role `attachment` (a validation error `asset-description` otherwise). A v1
bundle is read as before; `from_bundle` takes its `caption` as the description.

- [ ] **Step 1: Write the failing tests**

```python
def test_export_is_the_whole_module(storage):
    # import the crypt; export_module(...) -> check(bundle) has no errors; manifest version 2;
    # texts, entities, keys, maps, metadata equal the import; every attachment's bytes are in the zip
def test_import_export_import_is_stable(storage):
    # from_bundle(export(import(crypt))) == from_bundle(export(import(export(import(crypt)))))
def test_v1_caption_becomes_the_description(): ...
def test_v2_asset_without_description_is_refused(): ...  # Diagnostic code "asset-description"
def test_export_maps_dm_audience_back_to_gm(): ...
```

- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement** `export_module` from the stored source, the maps (with `vendor` for libraries, as
  today) and the blob bytes. The text files are `text/<id>.md`, the attachments `assets/<id>.<ext>`.
- [ ] **Step 4: Run the tests, the copied `tests/modules/dscn/` tests, and `make ci`.**
- [ ] **Step 5: Commit.** `git commit -m ".dscn version 2: attachments have a description, and export writes the whole module"`

---

### Task 3: The module source API

**Files:**
- Create: `src/delve/web/routes/module_source.py`, `tests/web/test_module_source_api.py`
- Modify: `src/delve/web/app.py` (include the router), `src/delve/web/routes/modules.py` (PATCH validates metadata)

**Interfaces:**
- Consumes: Task 1.
- Produces (organiser routes; each change publishes `modules` with `{id}`):

| Method | Path | Body | Answer |
|---|---|---|---|
| GET | `/api/modules/{id}/source` | | `{texts, entities, attachments, keys, links, warnings}` |
| POST | `/api/modules/{id}/texts` | `{id, title, audience?, map?}` | 201 the text; 409 a duplicate id; 422 a bad slug |
| PUT | `/api/modules/{id}/texts/{text_id}` | `{title?, audience?, map?, markdown?}` | `{text, links, warnings}` |
| DELETE | `/api/modules/{id}/texts/{text_id}` | | 204 |
| PUT | `/api/modules/{id}/entities/{kind}/{entity_id}` | the record | `{record, warnings}`; 422 `{error, diagnostics}` |
| DELETE | `/api/modules/{id}/entities/{kind}/{entity_id}` | | 204 |

- `kind` is one of `npcs`, `encounters`, `factions`, `quests` (404 otherwise; rumors and secrets stay import-only).
- An entity record validates against the schema's `$defs` for its kind (`npc`, `encounter`, `faction`, `quest`),
  and its `id` must equal `{entity_id}`.
- `PATCH /api/modules/{id}` validates `metadata` against the manifest's descriptive properties (422 with
  diagnostics). The structural keys (`maps`, `text`, `entities`, `assets`, `keys`, `format`, `version`) are refused.

- [ ] **Step 1: Write the failing tests:** each route's success and its refusals as in the table;
  `test_saving_a_text_relinks_its_headings` (PUT a text with "## 3. Vestry" → `links` has the vestry room);
  `test_an_npc_with_a_bad_disposition_is_refused` (422, a diagnostic at `disposition`).
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement** through `load_source` / `save_source`.
- [ ] **Step 4: Run the tests and `make ci`.**
- [ ] **Step 5: Commit.** `git commit -m "The module source API: texts, entities, links and warnings"`

---

### Task 4: Attachments

**Files:**
- Create: `src/delve/web/routes/assets.py`, `tests/web/test_assets_api.py`
- Modify: `src/delve/web/guard.py` (the upload exception), `src/delve/web/app.py`

**Interfaces:**
- Consumes: Task 1; `dscn.media.type_matches`, `svg_is_active`, `ALLOWED_TYPES`.
- Produces:

| Method | Path | Body | Answer |
|---|---|---|---|
| POST | `/api/modules/{id}/assets?name=<file name>` | the bytes | 201 `Attachment`; the id is `slugify(name without extension)`, made unique with `-2`, `-3`… |
| PATCH | `/api/modules/{id}/assets/{asset_id}` | `{description?, audience?}` | the attachment |
| DELETE | `/api/modules/{id}/assets/{asset_id}` | | 204 (refs to it become `missing-attachment` warnings) |
| GET | `/api/modules/{id}/assets/{asset_id}` | | the bytes, with its type |

- [ ] **Step 1: Write the failing tests:** the table's answers; Review Focus 4 (`test_hostile_uploads_are_refused`:
  an SVG with `<script>` 400, PNG bytes sent as `image/jpeg` 400, `text/plain` 415, 65 MB 413, and `GET …/source`
  shows no new attachment after each); `test_served_svg_is_sandboxed` (the CSP and nosniff headers).
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.** A new upload starts with `audience: "dm"` and `description: ""`.
- [ ] **Step 4: Run the tests and `make ci`.**
- [ ] **Step 5: Commit.** `git commit -m "Attachments: upload, describe, and serve a module's files"`

---

### Task 5: The text editor

**Files:**
- Create: `web/src/module/TextEditor.tsx`, `web/src/module/MarkdownRoundTrip.ts`, `web/src/module/KeyChip.tsx`,
  `web/src/module/roundtrip.test.ts`, `web/src/module/TextEditor.test.tsx`,
  `web/src/module/fixtures/everything.md`
- Modify: `web/package.json` (the TipTap packages above), `web/src/routes/ModuleDetail.tsx` (the tabs; Text first),
  `web/src/api.ts`, `en.json`, `nl.json`

**Interfaces:**
- Consumes: Task 3's `GET …/source` and `PUT …/texts/{id}`; Task 4's asset URLs.
- Produces: `toMarkdown(doc) / fromMarkdown(md)` in `MarkdownRoundTrip.ts`, and `<TextEditor moduleId text links
  attachments onSaved />`.

**What the editor does:**
- A toolbar: headings 2–4, bold, italic, bullet and numbered lists, quote (shown as read-aloud), link, table.
- It shows finished text: quotes styled as read-aloud, `![…](asset:id)` as the image (from Task 4's URL), `[[npc:id]]`
  refs as a small chip with the entity's name. The Markdown is never shown.
- A heading with a link shows a `KeyChip` with the room's label; one with a `key-without-room` warning shows the chip
  as a warning. The text's warnings are listed under the editor.
- Save writes the Markdown; leaving with unsaved changes asks first (`useBlocker`, as the map editor does).
- A list of the module's texts beside it, with New text and Delete.

**The round-trip (Review Focus 1):** `fromMarkdown` then `toMarkdown` gives the input back, byte for byte, for every
text of the crypt sample and for `fixtures/everything.md`. The fixture holds headings with `{#anchor}`, a keyed
heading, a read-aloud blockquote and a speech blockquote, bold and italic, nested lists, a numbered list, a link, a
table, an `asset:` image, `[[npc:…]]` and `[[faction:…]]` refs, and a hard line break. Where `@tiptap/markdown`
normalises (list markers, emphasis characters), `toMarkdown` writes the format the fixture uses; the fixture is written
in that format.

- [ ] **Step 1: Write the failing tests:** `roundtrip.test.ts` (each crypt text and the fixture, equal);
  `TextEditor.test.tsx` (the toolbar's quote makes a read-aloud blockquote; a linked heading shows its room chip; Save
  sends the Markdown with `PUT`).
- [ ] **Step 2: Run them and see them fail.** `cd web && npx vitest run src/module`
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests and `make ci`.**
- [ ] **Step 5: Commit.** `git commit -m "The module text editor: TipTap with a tested Markdown round-trip"`

---

### Task 6: Forms, attachments and details

**Files:**
- Create: `web/src/module/EntityForm.tsx`, `web/src/module/AttachmentsPanel.tsx`, `web/src/module/DetailsForm.tsx`,
  and a test file for each
- Modify: `web/src/routes/ModuleDetail.tsx` (the tabs NPCs, Encounters, Factions, Quests, Attachments, Details),
  `web/src/module/TextEditor.tsx` (insert an attachment at the cursor), `en.json`, `nl.json`

**Interfaces:**
- Consumes: Task 3's entity routes and `PATCH /api/modules/{id}`; Task 4's routes.

**The forms (spec §8.2), stored as the schema's records:**
- **NPC:** name, race, class and level or HD, AC, HP, disposition (−100 to 100), notes, portrait (an image
  attachment). Race, class, level, HD, AC and HP go in `stats.adnd2e`; notes in `description`; portrait as
  `asset:<id>`.
- **Encounter:** name, where (a key from the module's links, as `key`), its monsters (`fixed`: creature name or
  `npc:` ref, count as dice or a number, notes), conditions (`description`), kind.
- **Faction:** name, goals, members (`npc:` refs), alignment, scope, notes.
- **Quest:** name, giver (an `npc:` ref), stakes, scope, related refs, notes.
- Every form has the entity's audience (DM only or Players) and a summary. The id is the name's slug on creation and
  never changes. The server's 422 diagnostics show beside their fields.
- **Attachments:** a grid with a thumbnail (a PDF shows its name), the description, the audience, Delete, and
  "Insert in text", which places `![<description>](asset:<id>)` at the text editor's cursor. Upload takes several
  files.
- **Details:** title, authors, levels and party size (`party.levels`, `party.size`), setting, system, tags, content
  warnings, cover (one of the image attachments).

- [ ] **Step 1: Write the failing tests:** a saved NPC form sends the record above; a 422 shows at its field; an
  upload lists the new attachment; Insert in text calls the editor; Details sends `metadata` with `party`.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests and `make ci`.**
- [ ] **Step 5: Commit.** `git commit -m "Module forms: NPCs, encounters, factions, quests, attachments and details"`

---

### Task 7: A campaign's ruleset and setting

**Files:**
- Create: `src/delve/storage/migrations/versions/0007_campaign_world.py`, `src/delve/setting/greyhawk.py`,
  `src/delve/web/routes/worlds.py`, `tests/web/test_worlds_api.py`
- Modify: `src/delve/domain/campaigns.py`, the campaigns repository, `src/delve/web/routes/campaigns.py`,
  `src/delve/__main__.py` (`build_registries` registers Greyhawk), `src/delve/play/house_rules.py` (drop
  `CAMPAIGN_RULESET` and `CAMPAIGN_SETTING`), `src/delve/web/routes/characters.py` (`reference_of`),
  `src/delve/dm/tools/lookups.py`, `web/src/routes/Campaigns.tsx`, `web/src/routes/CampaignDetail.tsx`

**Interfaces:**
- Produces:
  - `Campaign` gains `ruleset: str` and `setting: str | None`.
  - Migration 0007: `campaigns.ruleset TEXT NOT NULL DEFAULT 'adnd2e'`, `campaigns.setting TEXT NULL`; existing
    campaigns get `'greyhawk'` (what they had implicitly).
  - `GreyhawkSetting`: `id = "greyhawk"`, `title = "Greyhawk"`, `kinds() == ()`, `lookup(...) == []`; registered
    always. Its lookups come in plateau 6.
  - `GET /api/worlds` → `{"rulesets": [{id, title}], "settings": [{id, title}]}`, from the registries, fakes
    included only when they are the only one.
  - `POST /api/campaigns` takes `ruleset?` and `setting?`. Unknown ids are 422. When left out: the module's
    `metadata.system` if it is a registered ruleset, else `adnd2e`; the module's `metadata.setting` if it matches a
    setting's id or title (case-insensitive), else `greyhawk`. `setting: null` means no setting.
  - The campaign's own ruleset and setting choose its house rules and its reference lookups.

- [ ] **Step 1: Write the failing tests:** the defaults from a module's metadata; 422 for unknown ids; a campaign
  with `setting: null` doesn't get a Greyhawk-only house rule; the migration gives existing campaigns `adnd2e` and
  `greyhawk`; the campaign form offers both lists and preselects the module's.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests and `make ci`.**
- [ ] **Step 5: Commit.** `git commit -m "A campaign names its ruleset and setting"`

---

### Task 8: Showing images to players

**Files:**
- Create: `src/delve/dm/tools/images.py`, `tests/dm/tools/test_images.py`
- Modify:
  - `src/delve/dm/tools/host.py` (register);
  - `src/delve/dm/tools/redact.py` (the `image` exception);
  - `src/delve/play/table.py` (a `show_image` result makes an `image` story entry after its tool row);
  - `src/delve/play/sessions.py` (the primer's `module` block gains `images`);
  - `src/delve/dm/prompt/dm.md` (the rule);
  - `src/delve/web/routes/play.py` (the image route);
  - `web/src/play/Story.tsx`, `web/src/play/api.ts`;
  - the tool coverage test.

**Interfaces:**
- Consumes: Task 1 (`module_sources.revision`), Task 4 (blob bytes).
- Produces:
  - `show_image(asset: str, caption: str = "")`, mutating, player-visible. It answers
    `{"image": {"asset": id, "caption": caption}}` for an image attachment with audience `player` in the campaign's
    pinned revision. It refuses a DM-only attachment ("That image is for the DM only."), a PDF, and an unknown id
    (candidates: the player images).
  - The primer's `module.images`: `[{id, description}]` for the pinned revision's player images.
  - A story entry `image` with payload `{asset, caption}`.
  - `GET /api/campaigns/{id}/images/{asset_id}`: the bytes when the campaign's pinned revision has that attachment
    with audience `player`; otherwise 404. Same headers as Task 4.
- **The rule in `dm.md`:** an image's description says what it shows and when it fits. Show a player image with
  `show_image` when the characters see what it shows, once, at that moment. Never describe a DM-only image's content
  to the players.

- [ ] **Step 1: Write the failing tests:** Review Focus 3 (`test_a_dm_only_image_never_reaches_a_player`: the tool
  refuses it, the route answers 404 with the owner token, and the story holds no `image` entry);
  `test_a_shown_image_is_in_the_story_and_served`; `test_the_pinned_revision_still_serves_a_deleted_image` (Review
  Focus 2); `test_primer_lists_the_player_images`; `Story.test.tsx` renders an `image` entry as an `<img>` with its
  caption.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests and `make ci`.**
- [ ] **Step 5: Commit.** `git commit -m "The DM shows a module's images to the players"`

---

### Task 9: What the first session found

**Files:** as each item names.

- **One event stream:** the play screen subscribes through the app's stream, not a second `EventSource`
  (`web/src/App.tsx`, `web/src/routes/Play.tsx`). The test: the play screen with the app open creates one
  `EventSource`.
- **Save keys:** `play.characters` stores a sheet's `saves` under the long names (`rules.adnd2e.tables.SAVE_ALIASES`),
  so `para` is written as `paralysis_poison_death`. The test: `create` and `update` with short keys store long ones.
- **The Campaigns page** says "Import or make a module first" with a link to Modules when there is none, and the
  import hint no longer says the text comes later.
- **The campaign page's character form** goes: in its place a line says characters are made in play, with a link to
  Play. Map-state positions keep working.
- **Live eval recordings** go to `evals/recordings/delve/<case>/`, never into `evals/fixtures/`. The test: the offline
  evals ignore `recorded-*.jsonl`.
- [ ] **Steps:** a failing test for each item, the fix, `make ci`, one commit per item:
  `git commit -m "<the item, in words>"`.

---

### Task 10: End to end, and the docs

**Files:**
- Create: `tests/e2e/test_write_and_play_a_module.py`, `web/e2e/module-editor.spec.ts`
- Modify: `README.md` (a "Writing modules" section), `GUILD.md` (the plateau 3 constraints above), `docs/progress.md`

- **The e2e test, through the API with the fake DM:** create a module; add a map with rooms; write a text with
  "## 1. The Gate" and "## 2. The Hall" (both link by themselves); add an NPC and an encounter by form records; upload
  a player image and a DM-only image with descriptions; export the `.dscn`; import it into a fresh data dir and
  compare the sources; start a campaign with `ruleset: adnd2e, setting: null`; the fake DM calls `show_image` for the
  player image, then for the DM-only one; the player's story has one `image` entry and the route serves it; the
  DM-only image is refused and 404.
- **The browser check (outside `make ci`, `make e2e-browser`):** open the crypt module's Text tab, type a keyed
  heading, see its room chip, save, reload, and see the text the same. Screenshots at 1280×800:
  `web/e2e/screenshots/module-text-1280x800.png`, `module-npc-1280x800.png`.
- [ ] **Step 1: Write the e2e test and see it fail where its parts are missing.**
- [ ] **Step 2: Make it pass, run `make ci` and `make e2e-browser`.**
- [ ] **Step 3: Update the docs.**
- [ ] **Step 4: Commit.** `git commit -m "Plateau 3 end to end: write, export, import and play a module"`

---

## Done when

- `make ci` passes on a fresh clone, and `make e2e-browser` writes the two screenshots.
- The crypt sample opens in the editor, saves unchanged, and exports to a `.dscn` that imports back the same.
- A module written from nothing in the editor (a map, two keyed texts, an NPC, a player image) is played with the
  fake DM, and its image shows in the story.
- No task's tests run the real `claude`.
