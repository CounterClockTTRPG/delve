# Build Delve plateau 3 (writing modules) exactly as planned in docs/superpowers/plans/2026-10-18-plateau-3-writing-module

# Delve plateau 3: writing modules

All ten tasks of `docs/superpowers/plans/2026-10-18-plateau-3-writing-modules.md` are built and merged into `guild/20261018-99fcebd9/party`. Nothing was delivered to master.

In the integration worktree, after the last merge:
- **`make install && make ci`:** passes.
  - ruff clean, import-linter 6 contracts kept, pytest 1581 passed and 1 skipped (a re-run had no skips), vitest 138 passed in 27 files, build ok.
- **The plateau 3 e2e test** (`tests/e2e/test_write_and_play_a_module.py`): passes.
- **`make e2e-browser`:** 2/2 specs pass, and all five screenshots were written.

No test ran the real `claude`, and nothing touched `~/.local/share/delve`; every agent used a `/tmp` data dir.

## What was delivered, per task

**Task 1, the module source (Mateo, `eaa3554`).**
- `delve.modules.source` holds `TextDoc`, `Attachment`, `ModuleSource`, `Link`, `Warning`, `Derived`, `from_bundle`, `derive`, `load_source` and `save_source`.
- Migration `0006_module_source` adds the `module_sources` table and `module_revisions.source`; the repository is `module_sources_repo`.
- `snapshot` pins the source, and `_same` compares it.
- The importer stores the source and the attachment blobs. The `NOT_UNPACKED` warning is gone.
- A module imported before this plateau gets its source on first read (Review Focus 5).
- A pinned revision keeps a deleted attachment and its blob (Review Focus 2).

**Task 2, `.dscn` version 2 and export (Mateo, `3331142`).**
- `VERSION = 2`; an asset has a `description`, and the validator raises an `asset-description` error when an attachment has none.
- The reader takes v1 and v2.
- `export_module` writes the whole module, mapping `dm` back to `gm`.
- import → export → import gives byte-identical zips for the crypt.
- `scenario-format.md` has a Version 2 note.

**Task 3, the module source API (Bram, `0b05526`).**
- `GET …/source`; text POST, PUT and DELETE; entity PUT and DELETE, validated against the schema's `$defs`.
- `PATCH /api/modules/{id}` now validates `metadata` and refuses structural keys.

**Task 4, attachments (Bram, `aaec5c1`).**
- Upload, describe, delete and bytes routes, with the second raw-body exception in the guard.
- Hostile uploads are refused (400, 415, 413) and nothing is stored (Review Focus 4).
- Served bytes carry `nosniff`, and SVG also gets `CSP: sandbox`, through the shared helper `attachment_response`.
- The export refuses a module with dangling refs (409; see the decisions).

**Task 5, the text editor (Nadia, `c393219`).**
- The seven TipTap packages are pinned at exactly 3.31.4.
- `MarkdownRoundTrip.ts` is its own parser and serialiser, built on the marked lexer that `@tiptap/markdown` ships.
- Every crypt text and `fixtures/everything.md` comes back byte for byte (Review Focus 1). The test checks it three ways: pure, through a real editor, and without the remembered source.
- The toolbar, the read-aloud quote, ref chips, the `KeyChip` room chip or warning chip, the warnings list, Save, the `useBlocker` prompt and the texts list are all in.

**Task 6, forms, attachments and details (Nadia, `9a9e89e`).**
- `EntityForm` covers NPCs, encounters, factions and quests. Server diagnostics show beside their fields.
- `AttachmentsPanel` has a grid, uploads several files at once, and has Insert in text.
- `DetailsForm` sends the metadata with `party`.

**Task 7, a campaign's ruleset and setting (Priya, `121d4f1`).**
- Migration `0007_campaign_world`, re-chained onto 0006 at integration. Existing campaigns get `adnd2e` and `greyhawk`.
- `GreyhawkSetting` and `GET /api/worlds` are added.
- `POST /api/campaigns` takes `ruleset` and `setting`, with defaults from the module's metadata and 422 for an unknown id.
- House rules and `rules_lookup` follow the campaign's own ruleset and setting.
- The campaign form offers both lists.

**Task 8, showing images to players (Lucas, `2cfed15`).**
- `show_image` refuses a DM-only image, a PDF and an unknown id.
- `player_view` lets an `image` through only for `show_image`, and only `{asset, caption}`.
- The story's `image` entry is written after the table checks the pinned revision again, so a forged result can't reach it.
- The primer has `module.images`, and `dm.md` has the rule.
- `GET /api/campaigns/{id}/images/{asset_id}` answers 404 for anything that isn't a player image in the pinned revision, with the owner token too (Review Focus 3).
- `Story.tsx` renders the image. `test_fourth_wall.py` now also covers images.

**Task 9, what the first session found (Priya, one commit per item).**
- `e93d186`: the play screen uses one event stream.
- `4197dfb`: saves are stored under their long names.
- `0299ce5`: the Campaigns page says "Import or make a module first" and links to Modules.
- `3cfb1d9`: the character form is gone from the campaign page; a line says characters are made in play, with a link to Play.
- `8472ba2`: live eval recordings go to `evals/recordings/delve/<case>/`, and the offline evals ignore `recorded-*.jsonl`.

**Task 10, end to end and the docs (Aisha, `52f9a9a`).**
- The e2e test runs through `delve serve`, the fake `claude` and the real bridge. It writes a module and exports and re-imports it. It then plays it: the story has exactly one `image` entry, and the DM-only image is refused and answers 404.
- `web/e2e/module-editor.spec.ts` types a keyed heading, saves, reloads, and opens the NPC form.
- README has a "Writing modules" section, GUILD.md has the plateau 3 rules, and `docs/progress.md` records plateau 3 and has a "Carried into plateau 4" section.
- There is also an integration commit (`df446e6`) and an exporter fix (`defc30d`); both are listed below.

## Test counts per area (pytest, from Aisha's final run)

| Area | Tests |
|---|---|
| maps | 671 |
| rules | 209 |
| web | 190 |
| play | 115 |
| dm | 102 |
| modules | 100 |
| storage | 73 |
| evals offline | 67 |
| domain | 24 |
| e2e | 7 |
| images | 5 |
| serve | 5 |
| setting | 4 |
| cli | 4 |
| boundaries | 2 |
| config | 2 |
| no_random | 1 |
| wheel | 1 |

The total is 1582. Vitest has 138 tests in 27 files. Playwright passed 2 specs.

Some of the tests new in this plateau:
- source 9 and module_sources 8;
- export round-trip 7;
- source API 18 and assets API 16;
- worlds 11 and images 7;
- round-trip 21, EntityForm 8, AttachmentsPanel 6, TextEditor 6, ModuleDetail 7 and DetailsForm 3.

## Deviations from the plan
1. **`VERSION` is in `dscn/container.py`.** The plan names `format.py`, which doesn't exist. One copied test changed: the "too new" case now uses version 3.
2. **Two helpers in `delve.modules.text` became public** (`sections_of`, `key_of`), so that `derive` builds exactly what `unpack` builds.
3. **`ModuleSourceRepository.pin_legacy`.** An old module's revisions get the source built from their bundle, so old modules don't look changed and offer a needless upgrade. `SOURCE_BUNDLE` moved to `source.py`, which avoids an import cycle.
4. **Headings also match a room by its label** when `match_node` finds nothing. Without this, the plan's own "Throne Room" → `throne_chamber` test could not pass.
5. **PATCH metadata refuses the importer's whole `STRUCTURAL` list.** That is the plan's seven keys plus `title`, `worldmaps` and `start`.
6. **The guard no longer duplicates headers a route has already set.** The CSP is always added, so an SVG gets both the app's CSP and `sandbox`.
7. **The schema-check helpers live in `routes/modules.py`,** which avoids an import cycle.
8. **Migration 0007 uses plain `ALTER TABLE`, not a batch.** A batch rebuild with foreign keys on would cascade-delete the play state.
9. **`web/src/api.ts` holds the shared event stream** (Task 9 item 1), which avoids an App↔Play import cycle.
10. **The new link on the campaign page reads "Play this campaign",** because the nav already has a link named "Play".
11. **Image helpers are in `modules/source.py`** (`is_image`, `player_images`, `pinned_source`), which avoids a `play.sessions → dm.tools` cycle.
12. **The editor:**
    - Each block remembers its Markdown source, and only an edited block is rewritten in the house style.
    - TextEditor has extra props (`warnings`, `entities`, `maps`, `onDirtyChange`, a ref).
    - Its heading node is its own, so it can carry the anchor and the chip.
    - Insert in text puts a PDF in as a link, not as `![…]`.
    - The module title moved into the Details tab.
13. **The exporter writes the headings that link themselves as `keys[]`** (`defc30d`). The e2e test found that a module written in Delve exported refs that our own import refused (`dangling-ref`), because `keys[]` is the format's only source of truth (§5.3).
14. **The integration fixed one test:** a worlds test sent `system: "OSRIC"`, which the new metadata validation refuses. It now sends `"osric"`.

## Decisions taken without the human
1. **Does a text's `markdown` include its front matter?** (Mateo)
   - **Answer:** yes, the whole file. The editor keeps it byte for byte and never shows it.
   - **Why:** the plan's test says the markdown equals the bundle's text files, and import and export stay lossless.
2. **What audience words do entity records store?** (Mateo proposed it; the lead decided it and told Bram and Nadia.)
   - **Answer:** the format's words, `gm` and `player`. Records are validated as sent, so a record with `dm` gets 422. The forms show `gm` as "DM only". Texts and attachments use Delve's `dm`.
   - **Why:** Task 6 says forms are stored "as the schema's records", and the schema knows only `gm`/`player`. This is the smallest change. It does bend the rule "the mapping happens only at import and export" for entities: the model keeps `gm` there. Please review this one.
3. **Can the export carry dangling refs?** (lead)
   - **Answer:** no. `GET …/export.dscn` answers 409 `{"error": "the module refers to missing attachments or entities", "warnings": […]}` when there are `missing-attachment` or `missing-entity` warnings.
   - **Why:** otherwise our own import refuses our own export. A clear refusal is the smallest safe answer.
4. **When does a heading warn `key-without-room`?** (Mateo)
   - **Answer:** only when its map exists and parses.
   - **Why:** the plan says "a map that doesn't parse … adds no warning".
5. **Which headings count as already keyed?** (Mateo)
   - **Answer:** a heading is covered when an explicit key points at its text or has the same key name, as `dscn suggest` does.
   - **Why:** that is how the copied format code already decides it.
6. **What happens to `role: source` assets on import?** (Mateo)
   - **Answer:** they become attachments.
   - **Why:** so their files aren't lost.
7. **Which ids count as known for the campaign's 422?** (Priya)
   - **Answer:** any registered id, fakes included. `ruleset: null` is treated as left out.
   - **Why:** the test app has only the fake ruleset, and the plan allows `null` only for `setting`.
8. **What do the text and entity PUTs answer: the text's own links and warnings, or the module's?** (Bram)
   - **Answer:** the whole module's, the same lists as `GET …/source`. The client filters them per text.
   - **Why:** the client can replace its lists as they are, and a `missing-*` warning can't be pinned to one text anyway.
9. **What happens to a deleted text's explicit keys?** (Bram)
   - **Answer:** they are deleted with it.
   - **Why:** otherwise they point into a missing text and the export fails to re-import.
10. **Who may use the image route before plateau 4?** (Lucas)
    - **Answer:** organisers. The 404 rule holds for the owner too.
    - **Why:** players only arrive in plateau 4.
11. **Does the table trust `show_image`'s result?** (Lucas)
    - **Answer:** no, it checks the pinned revision again before writing the entry.
    - **Why:** the story's safety shouldn't rest only on the tool's refusal.
12. **In what order are the image refusals checked?** (Lucas)
    - **Answer:** unknown id, then DM-only, then not an image.
    - **Why:** a DM-only PDF should answer "for the DM only".
13. **Editor details.** (Nadia)
    - A heading's anchor goes with its text when the heading is split; the first heading with text keeps a duplicated anchor.
    - The form checks the disposition range (−100 to 100), because the schema accepts any integer.
    - "Rooms without text" are listed in the texts list.
14. **How does a written module's self-linked keys survive the export, and what does "compare the sources" mean?** (Aisha)
    - **Answer:** the exporter writes them into `keys[]` (deviation 13). In the round-trip, texts, entities, attachments and warnings are equal; the links are the same but come back `explicit: true`.
    - **Why:** that is the smallest change that keeps to the format's rule.
15. **"Two self-linking keyed texts".** (Aisha)
    - **Answer:** one text with two keyed headings that both link themselves.
    - **Why:** that follows the plan's wording.

## Still open
- **A module with an untouched empty map** exports a bundle that our own import refuses (`map-parse`). Either leave empty maps out of the export, or refuse the export with a warning. This is recorded in `docs/progress.md`.
- **The attachment bytes routes send no cache headers.** If an id is reused after a delete, the browser could show the old bytes from its cache.
- **On a legacy revision, the first image lookup** stores the pinned source through `load_source`. It happens once per module.

## Screenshots (attached)
- `web/e2e/screenshots/module-text-1280x800.png`
- `web/e2e/screenshots/module-npc-1280x800.png`
- `web/e2e/screenshots/play-1280x800.png`, `play-sheet-1280x800.png` and `play-820x1180.png` (regenerated)

## What the owner should check by hand
1. **Write a module from nothing in the editor:**
   - a map, two keyed texts (check their room chips), an NPC and an encounter by form, and an image uploaded, described and inserted;
   - then save, leave and come back.
2. **The round-trip on a real module:**
   - open the crypt or another real module, save every text unchanged, and check that nothing changed;
   - export it to `.dscn`, import it again, and compare.
3. **Show an image in a real session:**
   - start a campaign on a module with a player image and a DM-only image, and play with the real `claude`;
   - check that the DM shows the player image once, at the right moment, and never describes the DM-only one.
4. **Review decision 2** (entity records keep `gm`).

