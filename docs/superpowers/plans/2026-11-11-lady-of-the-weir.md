# The Lady of the Weir: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `.dscn` sample module, *The Lady of the Weir*, for OSRIC in Aun, shipped in the repo and the public export.

**Architecture:** A directory-form scenario bundle (`docs/maps/scenario-format.md`) at `samples/lady-of-the-weir/`:
`scenario.json`, three DungML maps, keyed Markdown text, YAML entities and PNG pictures. A test loads it with
`delve.modules.dscn.Bundle` and imports it with `delve.modules.importer.import_bundle`. The public export zips it.

**Tech Stack:** DungML (`delve.maps.dsl`: `parse`, `validate`, `render`), resvg-py for PNG previews, YAML, Replicate
(FLUX.1 [schnell]) for pictures, pytest.

**Spec:** `docs/superpowers/specs/2026-11-11-lady-of-the-weir-design.md`

## Global Constraints

- `system: osric`, `setting: aun`, `license: {spdx: CC-BY-4.0, name: "Creative Commons Attribution 4.0"}`, `language: en`.
- Party 4–6 characters of levels 1–2; one session of 3–4 hours.
- No underwater or flooded map, room or level; water only as outdoor scenery.
- Nothing from a published setting, module or novel; no verbatim OSRIC guide prose; the Aun bible's **Never** list and
  **Tone and writing** hold.
- Organic maps: `rect` only for built rooms; caves, banks and yards as `polygon`/`boundary` with `line_style organic`.
- Every NPC who may fight has an `osric` stats block; every keyed area has player text and `::: dm` text.
- Pictures only from a model whose terms allow publishing the output under CC BY 4.0 (checked and recorded).
- The OSRIC notice (`OsricRuleset.notice`) and the picture credit appear in the bundle's text.

## Review Focus

- **An import into a Delve without the Aun pack** must still import (setting falls back), as the Crypt does: covered
  by the import test's metadata check, not a pack check.
- **Every key's `node` resolves to a room of its map**, or the DM's room lookups fail at the table: Task 1's test.
- **Encounter `creature` refs that OSRIC's bestiary doesn't know** (a typo, a 2e name) leave the DM without stats:
  Task 5's test looks each `monster:` ref up in the OSRIC reference.
- **Maps whose labels overlap or rooms overlap** look broken to players: each map task validates with no errors and
  renders a PNG that is looked at.
- **A bundle zipped with a stray file** (`.DS_Store`, a preview PNG) is refused or bloats: previews go to the
  scratchpad, never into the bundle; Task 1's test checks the asset list equals the files under `assets/`.

---

### Task 1: The bundle and its test

**Files:**
- Create: `samples/lady-of-the-weir/scenario.json`, `samples/lady-of-the-weir/text/intro.md`,
  `samples/lady-of-the-weir/text/credits.md`, `samples/lady-of-the-weir/maps/lib/core.dmap` (copy of the Crypt's)
- Test: `tests/modules/test_sample_module.py`

**Interfaces:**
- Produces: `SAMPLE = REPO / "samples" / "lady-of-the-weir"`; map names `valley` (default), `weirholt`,
  `sluice-house`; text ids `intro`, `credits`, `valley-key`, `weirholt-key`, `sluice-key`; entity files
  `npcs.yaml`, `encounters.yaml`, `quests.yaml`, `rumors.yaml`, `secrets.yaml`.

- [ ] **Step 1: Write the test** `test_the_sample_module_imports_whole` (FakeStore as in `tests/modules/test_importer.py`):
  imports `Bundle.load(SAMPLE).to_zip()`; asserts title "The Lady of the Weir", `metadata["system"] == "osric"`,
  `metadata["setting"] == "aun"`, licence spdx `CC-BY-4.0`, maps `valley` (default), `weirholt`, `sluice-house`,
  `core.dmap` (library); every map parses and `validate` gives no `error`; every key's node names a room of its map;
  the asset ids equal the files under `assets/`.
- [ ] **Step 2: Run it:** `uv run pytest tests/modules/test_sample_module.py -v` → FAIL (no bundle).
- [ ] **Step 3: Write `scenario.json`, `intro.md` (player hook) and `credits.md`** (authors, CC BY 4.0, OSRIC
  notice, picture credit placeholder filled in Task 6); maps, keys and entities listed as later tasks fill them.
- [ ] **Step 4:** the test passes once Tasks 2–6 land; until then mark the map/key parts `xfail` no more than
  necessary, and remove every `xfail` by Task 6.
- [ ] **Step 5: Commit.**

### Task 2: The Ambresleigh valley (outdoor map and its key)

**Files:** Create `samples/lady-of-the-weir/maps/valley.dmap`, `samples/lady-of-the-weir/text/keyed/valley.md`;
modify `scenario.json` (keys V1…).

- [ ] **Step 1:** Draw the valley with `renderer "classic-bw"`, `theme paper`, `room_numbers off`: the Ambre as a
  `slice river` across the map, the weir and its pool (`area water`), the reed marsh (`area swamp`), the road
  (`line_feature road`), the village's buildings as small rooms, the mill on its race, the watchtower ruin, the
  burial mound, the ford, and Weirholt and the Sluice-House entrance as rooms whose keys point to their own maps.
  Paths as `corridor width 0 line_style dotted` with `open` doors. About 1.5 miles across.
- [ ] **Step 2: Validate and look:** `parse` + `validate` (no errors); render to SVG, then PNG with resvg-py into
  the scratchpad, and read the PNG. Redraw until it looks like a valley, not boxes.
- [ ] **Step 3: Key text** for each place (V1 village … V10), player text plus `::: dm` sections, with the
  non-combat meetings at fixed places (the mill, the mound, the pool at dusk).
- [ ] **Step 4:** Task 1's test passes for the valley keys. **Commit.**

### Task 3: Weirholt (indoor map and key)

**Files:** Create `maps/weirholt.dmap`, `text/keyed/weirholt.md`; keys W1–W6.

- [ ] **Step 1:** Draw with `renderer "hatched"`, `theme paper`, 5 ft cells: walled yard (organic or dashed), gatehouse,
  hall (table, hearth), study (locked desk, strongbox), kitchen, guard room, cellar (stairs-down, pumps, the
  unfinished tunnel). Doors where people put them; one locked.
- [ ] **Step 2: Validate and look** as Task 2.
- [ ] **Step 3: Key text:** supper with Odo, the locked desk and strongbox (lock and a needle trap for the thief),
  Odo's scrolls (one 1st-level magic-user spell), the leases, his two men-at-arms.
- [ ] **Step 4:** test passes; **commit.**

### Task 4: The Sluice-House (indoor map and key)

**Files:** Create `maps/sluice-house.dmap`, `text/keyed/sluice.md`; keys S1–S6.

- [ ] **Step 1:** Draw with `renderer "oldschool-blue"` (or `classic-bw` organic where it is cut rock): the dry intake
  channel behind a locked iron grille, the valve gallery (the trap), the labourers' hall (skeletons), the
  inscription chamber, the seal chamber (the Sluice-Warden, zombies of the vanished), a side store. Stone floors; no
  water areas inside.
- [ ] **Step 2: Validate and look** as Task 2.
- [ ] **Step 3: Key text:** the grille (pick or force), the valve trap, the turning fight, the inscription (for a
  magic-user), the Warden fight, *Eelbite* if not given by the Lady, the miller's son among the zombies, Sorrel's
  ring.
- [ ] **Step 4:** test passes; **commit.**

### Task 5: The entities

**Files:** Create `entities/npcs.yaml`, `encounters.yaml`, `quests.yaml`, `rumors.yaml`, `secrets.yaml`.

- [ ] **Step 1: Test** `test_the_sample_modules_monsters_are_osrics`: every `monster:` ref in `encounters.yaml` and
  `npcs.yaml` finds an entry with `OsricRuleset().reference.monster(name)`; every NPC of the design is present; the
  quests carry the design's XP (100, 150, 75, 100, 300, +150).
- [ ] **Step 2: Run it** → FAIL.
- [ ] **Step 3: Write the entities:** the ten NPCs of the design with role, location, disposition and (where they
  may fight) an `osric` stats block; encounter tables `road`, `reeds`, `river path by night` (night-only in its name
  and notes), `sluice-house`, each about a third non-combat, placed by `key`; the six quests; rumours (true, partly
  true, false); the secrets (the Reeve, the Warden, the consort).
- [ ] **Step 4: Run it** → PASS. **Commit.**

### Task 6: The pictures

**Files:** Create `assets/img/cover.png` and portraits `reeve-haldan`, `wenna`, `odo-tesk`, `the-lady`,
`sorrel`, `brother-aldo`, `pim`; modify `scenario.json` (`cover`, `assets` with sha256 and size), `npcs.yaml`
(`portrait`), `credits.md`.

- [ ] **Step 1:** Read the model's licence on Replicate; record the model, its licence and the date in `credits.md`.
- [ ] **Step 2:** Generate one style prompt shared by all eight; portraits square, cover landscape; look at each.
- [ ] **Step 3:** Task 1's test passes with no `xfail` left. **Commit.**

### Task 7: Shipping

**Files:** modify `README.md` (repo), `~/claude/delve-public-tools/INSTALL.md` and `export.sh` (outside the repo).

- [ ] **Step 1:** README and INSTALL point to *The Lady of the Weir* in place of the Crypt; export.sh zips
  `samples/lady-of-the-weir` into `samples/lady-of-the-weir.dscn` in the tree.
- [ ] **Step 2:** run the export into the scratchpad; the zip imports (Task 1's check against the zip).
- [ ] **Step 3: Commit** the repo change; the public push waits for the owner.

### Task 8: Playtest

- [ ] **Step 1:** A scratch Delve with a fresh `DELVE_DATA_DIR` in the scratchpad (never the live data), packs OSRIC
  and Aun, the bundle imported, a campaign OSRIC/Aun, a party of four (fighter, cleric, magic-user, thief).
- [ ] **Step 2:** Play it through with the Claude DM to ending 2 (a new bargain); note every stumble.
- [ ] **Step 3:** Back up the campaign before the finale; replay the finale for endings 1 and 3.
- [ ] **Step 4:** Fix the module where the DM stumbled; rerun the tests; **commit**; comment on DEL-378 and move it
  to `in_review`.
