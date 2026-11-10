# Crop, rotate and split a module's pictures (DEL-40) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An organiser crops, turns (90° steps) or splits a module's picture on the Attachments panel, keeping the
original; the thorough conversion proposes the same cuts for the organiser to review.

**Architecture:** An attachment gets an optional `cut`: its original's blob, the turn and the box. The attachment's
own `sha256`, `type` and `size` stay what everyone is shown (the cut picture), so players, the DM's `show_image`,
banners, thumbnails and the export need no change. Every cut is made from the original, never from an earlier cut.
A split is one cut per piece over the same original: the first piece keeps the attachment's id, the others are new
attachments.

**Tech Stack:** Python 3.12, FastAPI, Pillow 13 (as `delve.play.module_banners`); React 18, TanStack Query, Radix
Dialog; Vitest; Playwright.

**Spec:** DEL-40 in Tasker, with the owner's choices in its comment of 2026-10-28 (scope: by hand plus conversions;
re-editable crop over the kept original; the first piece of a split keeps the id; 90° steps only).

## Global Constraints

- The original is never shown to players: only the organiser's routes serve it.
- Rotation is 0, 90, 180 or 270 degrees clockwise; nothing else is taken (422).
- A box is `[x, y, w, h]` as fractions (0–1) of the *turned* original; it must lie inside it and be at least 8 px a
  side once scaled (422).
- Pictures only: PNG, JPEG, WebP and a still GIF are cut (a GIF's cut is a PNG). SVG and PDF are refused (422).
- A cut keeps the original's format (PNG→PNG, JPEG→JPEG at quality 92, WebP→WebP at 90) and no metadata.
- The original's blob is linked to the module (`blobs.link(module_id, ATTACHMENT, sha)`), so pruning never takes it.
- Strings in all five languages (en, nl, fr, de, lv); Delve's prose style (docs/style-guide.md).

## Review Focus

- Cutting a picture that is already cut: the new cut is taken from the original, so cuts don't compound.
- A split's new ids collide with an attachment that exists: each new id is made unique (`-2`, `-3`…, as uploads are).
- Reset on a split's first piece: that id shows the whole original again; the other pieces stay as they are.
- The card shows the new picture at once after a cut or a reset, though the URL's id is the same (the `src` carries
  the sha).
- An original past `BANNER_MAX_PIXELS` (40 M) is refused before it is decoded (422), not cut slowly.

---

### Task 1: The cut on an attachment, and cutting the bytes

**Files:**
- Modify: `src/delve/modules/source.py` (`Attachment`, `ModuleSource.from_json`)
- Create: `src/delve/modules/cuts.py`
- Test: `tests/modules/test_cuts.py`

**Interfaces:**
- Produces: `@dataclass(frozen=True) class Cut: original: str; original_type: str; original_size: int; rotate: int = 0;
  box: tuple[float, float, float, float] | None = None; proposed: bool = False` in `source.py`, and
  `Attachment.cut: Cut | None = None` (last field). `from_json` rebuilds it from its dict (a list `box` becomes a
  tuple); sources without `cut` load as before.
- Produces: `cuts.cut_picture(data: bytes, media_type: str, rotate: int, box: tuple[float, float, float, float] | None)
  -> tuple[bytes, str]` (the bytes and their type), raising `cuts.CutRefused(message)` (a `ValueError`).
- Produces: `cuts.ROTATIONS = (0, 90, 180, 270)`, `cuts.MIN_SIDE = 8`, `cuts.CUTTABLE = {"image/png", "image/jpeg",
  "image/webp", "image/gif"}`.

- [ ] **Step 1: Write the failing tests** (`tests/modules/test_cuts.py`), on a 200×100 PNG made with Pillow whose left
  half is red and right half blue:
  - `test_a_box_cuts_that_part`: box `(0.5, 0, 0.5, 1)` gives a 100×100 PNG, all blue.
  - `test_a_turn_comes_before_the_box`: rotate 90 gives 100×200; box `(0, 0, 1, 0.5)` of it is the red half.
  - `test_formats_are_kept_and_a_gif_becomes_a_png`: JPEG in → `image/jpeg` out; GIF in → `image/png` out.
  - `test_refusals`: rotate 45; box `(0.9, 0, 0.2, 1)` (outside); box `(0, 0, 0.01, 1)` (2 px wide); `image/svg+xml`;
    a PNG header claiming 10000×10000 (past 40 M pixels) — each raises `CutRefused`.
  - `test_an_attachment_with_a_cut_round_trips`: `ModuleSource(attachments=[Attachment(..., cut=Cut("abc",
    "image/png", 10, 90, (0, 0, 1, 0.5), True))])` survives `to_json` → `from_json`; one without a cut loads with
    `cut is None`.

- [ ] **Step 2: Run** `uv run pytest tests/modules/test_cuts.py -q` — expected: FAIL (no `delve.modules.cuts`).

- [ ] **Step 3: Implement** `Cut`, `Attachment.cut`, `from_json`, and `cut_picture`: check the header's size with
  `Image.open` before `load()` against `delve.play.module_banners.BANNER_MAX_PIXELS`, `ImageOps.exif_transpose`,
  `rotate(-rotate, expand=True)`, crop by rounded pixels, save with no `exif`/`icc_profile`.

- [ ] **Step 4: Run** the tests — expected: PASS.

- [ ] **Step 5: Commit** — `Modules: an attachment's cut (original, turn, box), and cutting a picture's bytes (DEL-40)`

### Task 2: The organiser's routes: cut, split, reset, review, the original

**Files:**
- Modify: `src/delve/web/routes/assets.py`
- Test: `tests/web/test_attachment_cuts_api.py`

**Interfaces:**
- Consumes: Task 1's `Cut`, `cut_picture`, `CutRefused`.
- Produces (all organiser-only, each publishing `modules` as the other attachment routes do):
  - `POST /api/modules/{module_id}/assets/{asset_id}/cut`, body `{"rotate": int, "pieces": [{"box": [x, y, w, h] |
    null, "id"?: str, "description"?: str, "audience"?: "gm" | "player"}]}` (1–12 pieces). Answers `{"attachments":
    [Attachment…]}`: the first piece is `asset_id` (its description and audience kept unless given), the others new
    attachments after it in the list, each id from `_new_id` on the given id or `<asset_id>-2`, `-3`…; each `cut` has
    `proposed: false`. 422 for `CutRefused`, a non-picture, or 0 / more than 12 pieces.
  - `DELETE /api/modules/{module_id}/assets/{asset_id}/cut`: the attachment back to its original's bytes, `cut` null;
    answers the attachment. 404 for one with no cut.
  - `PATCH /api/modules/{module_id}/assets/{asset_id}` takes `reviewed: true` too: the cut's `proposed` becomes false.
  - `GET /api/modules/{module_id}/assets/{asset_id}?original=true`: the original's bytes (the attachment's own when it
    has no cut).
- Attachment JSON gains `cut` (`{original, original_type, original_size, rotate, box, proposed}` or null).

- [ ] **Step 1: Write the failing tests**, with the module fixtures the existing `tests/web/test_assets_api.py` uses:
  - `test_a_crop_keeps_the_original`: upload the 200×100 PNG, cut with `{"rotate": 0, "pieces": [{"box": [0.5, 0, 0.5,
    1]}]}`; the attachment's bytes (GET) are 100×100, `?original=true` gives back the uploaded bytes, `cut.original`
    is the upload's sha, and `storage.blobs.links(module_id)` has `("attachment", <original sha>)`.
  - `test_cutting_again_starts_from_the_original`: a second cut `[0, 0, 0.5, 1]` is the red 100×100, not a cut of the
    blue one.
  - `test_a_split_keeps_the_first_id`: two pieces with descriptions "Cabin A", "Cabin B"; answer ids `[asset_id,
    f"{asset_id}-2"]`, both with the same `cut.original`; with a picture named `{asset_id}-2` already there, the new one
    is `{asset_id}-3`.
  - `test_reset_shows_the_whole_original`: after the split, DELETE on the first gives its sha back to the original's,
    `cut` null; the second piece is unchanged.
  - `test_reviewed_clears_proposed` (a source saved with `proposed: true`), `test_refusals` (rotate 45 → 422; a PDF →
    422; 13 pieces → 422; a non-organiser → 403), and `test_players_never_get_the_original`: the play route that serves
    a campaign's module image serves the cut bytes.

- [ ] **Step 2: Run** `uv run pytest tests/web/test_attachment_cuts_api.py -q` — expected: FAIL (404s).

- [ ] **Step 3: Implement** the routes in `assets.py`, cutting in `run_in_threadpool`; one `storage.transaction()` for
  the blobs, the link and `save_source`.

- [ ] **Step 4: Run** the tests and `tests/web/test_assets_api.py` — expected: PASS.

- [ ] **Step 5: Commit** — `Modules: crop, turn and split a picture, reset it, and its original for the organiser (DEL-40)`

### Task 3: The conversion proposes cuts

**Files:**
- Modify: `src/delve/modules/books/prompts/thorough/describe.md`, `src/delve/conversions/thorough/make.py`
  (`_pictures`)
- Test: `tests/conversions/thorough/test_make.py` (the existing file for `_pictures`, or beside it)

**Interfaces:**
- Consumes: Task 1's `Cut`, `cut_picture`.
- Produces: a `descriptions.json` entry may have `"rotate"` (0/90/180/270) and `"crop": [x, y, w, h]`; one file may be
  listed several times, once per piece. `_pictures` attaches each entry cut (`cut.proposed = True`) and returns the
  originals' bytes among the pictures' bytes, so `_make_module` stores and links them.

- [ ] **Step 1: Write the failing tests:** an `art/` PNG listed twice with crops `[0, 0, 0.5, 1]` and `[0.5, 0, 0.5,
  1]` gives two attachments with distinct ids, each 100×100, each `cut.proposed` and the same `cut.original`, and the
  original's bytes are stored; an entry with `"crop": [2, 0, 1, 1]` (a bad box) is attached uncut with a doubt of kind
  `crop-refused`; an entry with neither key is attached as before, `cut` None.

- [ ] **Step 2: Run** them — expected: FAIL.

- [ ] **Step 3: Implement** `_pictures`' cuts; add to `describe.md` when to crop (a room key or page text printed on
  the picture, a plate of several scenes or several NPCs: one entry per piece, each its own id and description) and
  when to turn (a sideways plate), with the box's meaning.

- [ ] **Step 4: Run** the tests and `uv run pytest tests/conversions -q` — expected: PASS.

- [ ] **Step 5: Commit** — `Thorough conversion: the describe step proposes crops, turns and splits (DEL-40)`

### Task 4: The Attachments panel's cropper

**Files:**
- Create: `web/src/module/CropDialog.tsx`, `web/src/module/CropDialog.test.tsx`
- Modify: `web/src/module/AttachmentsPanel.tsx`, `web/src/api.ts`, `web/src/styles.css`, `web/src/i18n/{en,nl,fr,de,lv}.json`
- Create: `web/e2e/picture-crops.spec.ts`

**Interfaces:**
- Consumes: Task 2's routes and the attachment's `cut`.
- Produces: `api.ts`: `Attachment.cut?: AttachmentCut | null`; `cutAttachment(moduleId, assetId, {rotate, pieces})`,
  `resetCut(moduleId, assetId)`, `originalUrl(moduleId, assetId)`; `attachmentUrl` gains an optional `version`
  (`?v=<first 12 of sha256>`), which the card uses.
- The card: **Crop…** on every cuttable picture; **Reset** while it has a cut; a **Proposed crop** badge and **Looks
  right** (PATCH `reviewed`) while `cut.proposed`. `onChange` gets the whole list back after a split (new pieces
  after the first).
- `CropDialog`: the original (turned by CSS as chosen) with one box per piece over it: drag on empty space draws the
  chosen piece's box, drag inside moves it, a corner resizes it; Turn left / Turn right; Add piece (each extra piece
  with its description and audience fields); Save posts the cut; it opens on the attachment's current cut (or the
  proposed one).

- [ ] **Step 1: Write the failing tests** (`CropDialog.test.tsx`): Crop… opens it on the original; Turn right then
  Save posts `{rotate: 90, pieces: [{box: null}]}`; with a box set by keyboard-free state (the dialog's initial cut)
  and Add piece with "Cabin B", Save posts two pieces; Reset calls DELETE; a proposed cut shows the badge, and Looks
  right PATCHes `{reviewed: true}`; the card's `img` `src` changes with the sha.

- [ ] **Step 2: Run** `cd web && npx vitest run src/module` — expected: FAIL.

- [ ] **Step 3: Implement** the dialog, the card's buttons, the API calls, the CSS and the strings.

- [ ] **Step 4: Run** the Vitest tests, then `npx playwright test e2e/picture-crops.spec.ts`: upload a picture, draw a
  box with the mouse, turn it, save; the card shows the cut; split into two; Reset — expected: PASS, with
  `e2e/screenshots/picture-crop-1280x800.png`.

- [ ] **Step 5: Commit** — `Modules: crop, turn and split pictures on the Attachments panel (DEL-40)`

### Task 5: Docs and the whole branch

**Files:**
- Modify: `docs/data-dictionary.md` (the attachment's `cut`), the organisers' help topic on module pictures if there
  is one (`src/delve/play/help_topics.py` or its texts).

- [ ] **Step 1:** Document `cut` where attachments are described; note that a `.dscn` export carries the cut picture,
  not its original.
- [ ] **Step 2: Run** `make ci` — expected: everything passes.
- [ ] **Step 3: Commit** — `Docs: a module picture's cut (DEL-40)`
