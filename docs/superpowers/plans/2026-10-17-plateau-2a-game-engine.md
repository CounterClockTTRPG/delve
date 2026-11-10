# Delve plateau 2a: the game engine, implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Everything a session needs except Claude:
- the AD&D 2e reference data in Delve's own reference store;
- logged, seedable dice;
- checks and saves;
- combat on the map, with ttrpg2's 27 pinned bugs fixed;
- characters and NPCs;
- party and marching order;
- inventory and encumbrance;
- spell loadouts;
- treasure and XP;
- notes, secrets and sessions;
- **house rules and bundles**;
- the DM's tool surface (with `batch`), tested end to end without Claude.

**Architecture:**
- **`delve.rules.adnd2e`** holds the 2e rules as pure code. It works through two interfaces it is handed: a dice service, and a reference interface over the reference store.
- **`delve.play`** holds the campaign services. They load state through storage, apply the rules, and save inside one transaction.
- **`delve.dm.tools`** is the DM's tool surface: a transport-neutral tool host that plateau 2b serves over MCP.
- **Reference store:** a read-only `reference.db`, built by `delve reference build` from pinned snapshots committed to the repo.

**Tech Stack:** as plateaus 0 and 1. No new runtime dependencies; the snapshots load with the stdlib `sqlite3` inside `delve.storage`.

**Spec:** `docs/superpowers/specs/2026-10-17-unified-app-design.md`:
- §6.3 tool surface
- §6.5 hard rules
- §7.4 split party
- §7.8 characters
- §9 house rules
- §10 rulesets
- §12 storage
- §14 plateau 2a

Also read `docs/review/feature-review.md` (what's kept and cut) and `docs/glossary.md`.

**Source to port (read only):** `/home/raf/claude/ttrpg2`. The modules are named in each task. Its tests in `tests/test_char_*.py` pin today's behaviour, and their `test_known_bug_*` cases list the bugs to fix.

## Global Constraints

- **Earlier plateaus still apply.** Everything in plateaus 0 and 1's Global Constraints holds: ports, import rules, glossary words, EN/NL, no network or `claude` in tests, fog invariants, and the DM view on its own route.
- **No `random` module.** No module except `delve.rules.adnd2e.dice` may import `random`, and every roll goes through `Dice`. A test greps `src/delve` for `import random` / `from random`.
- **Every roll is logged** with notation, faces, total, purpose, actor, target, the campaign, the beat key and the combat round. (Spec §6.5.)
- **Notation limits:** at most 100 dice, at most 1000 sides, `times` at most 20. Anything more answers `NotationTooLarge`.
- **One transaction per tool call.** A tool call's writes commit together, or not at all.
- **`delve.rules` imports no `delve.play`, `delve.dm`, `delve.web` or `delve.storage`.** The interfaces it needs live in `delve.domain` or `delve.rules` itself.
- **What survives:**
  - Mechanics follow AD&D 2e (PHB and DMG), and the docstring of each fixed bug cites the rule.
  - Behaviour that ttrpg2's characterisation tests pin as *correct* (not `known_bug`) stays as it is.
  - ttrpg2's `batch` semantics are kept exactly (Task 11).
- **Results split what the characters perceive from DM-only material.** Every tool result is a JSON object. What characters perceive goes under `perceived` where it applies, and DM-only material goes under `dm_only`. Errors are `{"error": str, "hint"?: str, "candidates"?: [...]}`.
- **Ids:** characters (PCs and NPCs) keep `chr_<12 hex>`. Combatants get stable ids such as `chr_…` for characters and `mon_<n>` for monsters. Display names may repeat, ids never do.
- **Reference data:**
  - The snapshots are committed under `reference/snapshots/` as gzipped SQL plus `SHA256SUMS`.
  - `reference.db` is built into the data directory and never committed.
  - Greyhawk, lore facts and monster images are out of scope (plateau 6).
- **Cut features** must not come back: strongholds, rations and torches, hirelings, rumors, the separate combat map, `audit_session`.

## Review Focus

1. **Character names.** An attack on "Gob" when there are "Goblin 1" and "Goblin 2", or two monsters both called "Goblin". The target must be named exactly (by id, or by a unique display name). An ambiguous name answers `{"error", "candidates"}`, never a guess. (Task 7 test.)
2. **The same roll twice within one beat.** A save for the same actor, purpose, target and combat round returns the stored roll, and the log has one entry. Across two combat rounds, it rolls fresh. (Task 2 and Task 7 tests.)
3. **A tool call that fails halfway**, for example an `award_treasure` whose loot write raises. No coin, loot or roll log entry is left behind. (Task 4 transaction test, used again in Task 6.)
4. **A planted secret in DM-only data reaching a perceived field.** For every tool that returns `perceived`, a test plants `SECRET-XYZZY` in DM-only data (module text, NPC notes, secrets, hidden rooms) and asserts it never appears under `perceived`. (Task 12 test.)
5. **A missing reference database, or one built from a different snapshot.** `delve serve` refuses with a message telling you to run `delve reference build`. The DM tools answer `{"error": "reference data missing"}`; they never crash. (Task 1 test.)

---

## File structure

```
reference/snapshots/{adnd2e.sql.gz, rules.sql.gz, monsters.sql.gz, encounter_tables.json.gz, SHA256SUMS}
reference/house-rules/…                 ttrpg2's global/house-rules copied (seed data)
src/delve/domain/reference.py           Reference protocol (lookups the 2e ruleset needs)
src/delve/domain/characters.py          Sheet, CharacterState, Item, SpellLoadout, …
src/delve/domain/house_rules.py         HouseRule, Bundle, Phase, Kind
src/delve/storage/reference/…           build + SQLite implementation of Reference
src/delve/storage/sqlite/…              new repositories; migration 0003
src/delve/rules/adnd2e/dice.py          Dice, Roll, RollLog protocol, notation
src/delve/rules/adnd2e/checks.py        saves, skill, reaction, morale, surprise, shock, resurrection, turning, encounters
src/delve/rules/adnd2e/combat.py        the combat state machine (pure)
src/delve/rules/adnd2e/{treasure_tables.py, treasure.py, names.py, class_xp.py, encumbrance.py, spells.py}
src/delve/rules/adnd2e/ruleset.py       Adnd2eRuleset (implements delve.rules.ruleset.Ruleset)
src/delve/maps/tokens.py                combat tokens as DSL markers (fog-safe)
src/delve/play/{context.py, characters.py, inventory.py, spells.py, treasure.py, combat.py, moves.py, notes.py, sessions.py, house_rules.py}
src/delve/dm/tools/{host.py, schema.py, lookups.py, dice.py, party.py, combat.py, map.py, notes.py, house_rules.py, composites.py}
src/delve/web/routes/{house_rules.py, characters.py}
web/src/routes/{HouseRules.tsx, …}, web/src/campaign/{CharacterSheet.tsx, HouseRulePicker.tsx}
```

---

### Task 1: The reference store

**Files:**
- Create:
  - `reference/snapshots/*`
  - `scripts/snapshot_reference.py`, a one-time script that dumps ttrpg2's DBs into the snapshots; keep it for reference;
  - `src/delve/domain/reference.py`;
  - `src/delve/storage/reference/{__init__,build,sqlite_reference}.py`.
- Modify: `src/delve/__main__.py` (`delve reference build|check`), `Makefile` (`install` runs `uv run delve reference build`), `src/delve/config.py` (`reference_path = data_dir / "reference.db"`)
- Test: `tests/storage/test_reference.py`, `tests/fixtures/reference/` (a tiny snapshot set built by the test's own fixture)

**Interfaces:**
- **Snapshots:** made once by `scripts/snapshot_reference.py --from /home/raf/claude/ttrpg2/global`, which:
  - dumps the content tables only (no FTS shadow tables) of `2e.db` (spells, items, classes, class_levels, ability_scores, ability_columns, ability_notes, proficiencies, proficiency_class_crossover, turning_undead), `rules.db` (rules) and `monsters.db` (monsters, skipping soft-deleted rows);
  - gzips `encounter_tables.json`;
  - writes `SHA256SUMS`.

  It's a manual step done once by the Task 1 engineer, who commits the output. The snapshots total about 15 MB gzipped. Report the real size.
- **`build_reference(snapshots_dir: Path, out: Path) -> str`**:
  - verifies the checksums;
  - creates the tables with prefixes `adnd_*`, `rules` and `monsters`;
  - loads the data;
  - builds FTS5 `rules_fts` (`porter unicode61`) and `monsters_fts`;
  - writes `meta(snapshot_sha)`, where `snapshot_sha` is the sha256 of `SHA256SUMS`;
  - writes to a temp file and renames it into place;
  - returns the `snapshot_sha`.
- **`open_reference(config) -> Reference`** opens the database read-only (`mode=ro`). It raises `ReferenceMissing` when the file is absent and `ReferenceStale(db_sha, snapshot_sha)` when it was built from other snapshots. `delve serve` turns either into exit code 4 with the message `Run: delve reference build`.
- **`Reference` (Protocol, in domain), returning plain dicts:**
  - `monster(name) -> list[dict]`, ranked: exact, then prefix, then contains, with the same ranking as ttrpg2 `lookup.find_monster_rows`;
  - `spell(name, caster="") -> list[dict]`, where caster matching ignores case (this fixes ttrpg2's case-sensitive `_spell_level`);
  - `item(name, item_type="", max_rarity=100, limit=20) -> list[dict]`;
  - `char_class(name) -> dict | None` and `class_levels(name) -> list[dict]`;
  - `ability(ability, score) -> dict`;
  - `proficiency(name="", group="", ability="") -> list[dict]`;
  - `turning_undead() -> list[dict]`;
  - `rules_search(query, source="", limit=5) -> list[dict]`, with `snippet` and a cap of 20 (as ttrpg2 `rules.py`);
  - `rules_section(source, section) -> list[dict]`;
  - `encounter_tables() -> dict`;
  - `snapshot_sha: str`.

- [ ] **Step 1: Write failing tests** against a fixture snapshot set built in a pytest fixture from a few rows (a goblin, a magic missile, a long sword, a fighter row, two rules paragraphs):
  - `test_build_and_lookup_each_kind`
  - `test_monster_ranking_exact_prefix_contains`
  - `test_spell_caster_case_insensitive`
  - `test_rules_search_snippet_and_cap`
  - `test_checksum_mismatch_refuses`
  - `test_missing_reference_raises`
  - `test_stale_reference_raises`
  - `test_build_is_atomic`: interrupt it, and no partial `reference.db` exists.
  - `test_serve_exits_4_without_reference`
- [ ] **Step 2: Run, expect failure.**
- [ ] **Step 3: Implement, then make the real snapshots** with the script and commit them. `make install` builds `reference.db`. Add `test_real_snapshot_builds`, marked `slow` but included in `make ci`: it builds from the committed snapshots and checks the row counts (spells 887, items 5653, classes 9, rules 2362, and monsters 3848 minus the soft-deleted rows).
- [ ] **Step 4: Run.** `uv run pytest tests/storage/test_reference.py` and `lint-imports` pass.
- [ ] **Step 5: Commit.** `git commit -m "Reference store: pinned 2e snapshots, a reproducible reference.db"`

### Task 2: Dice and the roll log

**Files:**
- Create: `src/delve/rules/adnd2e/__init__.py`, `src/delve/rules/adnd2e/dice.py`
- Test: `tests/rules/adnd2e/test_dice.py`, `tests/test_no_random.py`

**Interfaces:**
- `parse(notation: str) -> Notation`. It accepts `NdX`, `NdXdlK` (drop the lowest K), `NdXkhK` (keep the highest K), `±M`, and `d%`. It raises `BadNotation(hint)` or `NotationTooLarge` (Global Constraints).
- `@dataclass(frozen=True) class RollKey`:
  - `beat: str`;
  - `actor: str | None`;
  - `purpose: str`;
  - `target: str | None = None`;
  - `combat_round: int | None = None`.
- `@dataclass(frozen=True) class Roll`:
  - `id: str`;
  - `key: RollKey`;
  - `notation: str`;
  - `faces: tuple[int, ...]` (all dice rolled, including dropped ones);
  - `kept: tuple[int, ...]`;
  - `modifier: int`;
  - `total: int`;
  - `at: str`.
- `class RollLog(Protocol)`:
  - `find(campaign_id, key: RollKey) -> Roll | None`;
  - `record(campaign_id, roll: Roll) -> None`.
- `class Rng(Protocol)`: `randint(a, b) -> int`. Implementations:
  - `SystemRng` uses `secrets`;
  - `SeededRng(seed: int)` is deterministic, built on `random.Random`. It's the only place `random` is imported.
  - `ScriptedRng(values)` is for tests, and raises when it runs out.
- `class Dice`:
  - `__init__(rng: Rng, log: RollLog, campaign_id: str, beat: str)`;
  - `roll(notation, *, purpose, actor=None, target=None, combat_round=None, times=1) -> Roll | list[Roll]`. If the log already has a roll for the same key, it returns that roll; this is the no-re-roll rule. With `times > 1`, each roll gets the key suffix `#i`.
  - `d(sides, *, purpose, …) -> Roll`.

- [ ] **Step 1: Write the failing tests.**
  - `test_parse_variants`
  - `test_limits_refused` (101 dice, 1001 sides, times 21)
  - `test_drop_lowest_keeps_faces`
  - `test_same_key_same_beat_returns_stored_roll`, which also checks that the log has one entry
  - `test_new_round_rolls_fresh`
  - `test_new_beat_rolls_fresh`
  - `test_seeded_is_deterministic`
  - `test_scripted_exhaustion_raises`
  - `test_no_random_import_outside_dice`: walk `src/delve` and assert only `rules/adnd2e/dice.py` imports `random`.
- [ ] **Step 2: Run, expect failure.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, expect them to pass.**
- [ ] **Step 5: Commit.** `git commit -m "Dice: notation limits, a roll log, no re-rolls within a beat"`

### Task 3: Checks and saves (pure)

**Files:**
- Create: `src/delve/rules/adnd2e/checks.py`, `src/delve/rules/adnd2e/tables.py` (saves by class group and level, SHOCK and RESURRECT from ttrpg2 `tools/dice.py:501,537`, and the morale and reaction bands)
- Test: `tests/rules/adnd2e/test_checks.py`

**Interfaces:** each function takes a `Dice` (and a `Reference` where needed) and returns a frozen result with the `roll` used. None of them write state.
- **Saving throws:** `saving_throw(dice, *, save_type, base: int, modifier=0, effects=(), actor, target=None, combat_round=None) -> SaveResult(success, needed, roll)`.
  - `save_base_for(sheet_or_monster, save_type, reference) -> int`. PCs use their sheet's saves, or the class-group table by level when it has none. Monsters save as fighters of their HD, so `HD 3+1` saves as fighter 4 (PHB/DMG). A level-0 fallback is used only for 0-level humans, and it's never silent: the result carries `basis`.
  - `effects` with a `save` modifier apply to the roll.
- **Percentile and ability checks:** `skill_check(dice, *, skill, percent, actor) -> CheckResult` and `ability_check(dice, *, ability, score, modifier=0, actor) -> CheckResult`, a d20 roll at or under the score.
- **Reaction:** `reaction(dice, *, modifier=0, disposition=0, reputation=0, actor=None, npc=None) -> ReactionResult(total, band, roll)`. `disposition // 20` becomes a truncation towards zero (this fixes the floor-division bug), and the same goes for the reputation adjustment.
- **Morale:** `morale(dice, *, rating, modifier=0, actor) -> MoraleResult(holds, roll)`. It rolls 2d10 and holds when the roll is at or under the rating.
- **Surprise:**
  - `surprise(dice, *, party_modifier=0, enemy_modifier=0) -> SurpriseResult(party_surprised, enemies_surprised, rolls)`.
  - Each side rolls d10 and is surprised on 1–3, adjusted by **its own** modifier. A positive modifier makes surprise *less* likely. The result names the dice used, and Task 7 applies it.
- **The rest:** `system_shock(...)`, `resurrection(...)`, `turning_undead(dice, reference, *, level, undead="", hd=0, role="priest")` and `encounter_check(dice, reference, *, terrain, level=0, dungeon_level=0) -> EncounterResult` (check and determine in one, using the encounter tables).

- [ ] **Step 1: Write the failing tests.** For each fixed bug, a test named after it, with a docstring citing the rule:
  - `test_surprise_on_1_to_3`
  - `test_surprise_modifier_direction`
  - `test_surprise_result_has_dice`
  - `test_monsters_save_by_hd`
  - `test_save_takes_modifier_and_effects`
  - `test_missing_saves_use_class_table_not_level_zero`
  - `test_disposition_truncates_towards_zero`
  - `test_every_check_logs_its_roll`

  Also port ttrpg2's non-bug characterisation tests for these checks (from `tests/test_char_dice.py`), with `ScriptedRng` replacing `Script`.
- [ ] **Step 2: Run, expect failure.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, expect them to pass.**
- [ ] **Step 5: Commit.** `git commit -m "2e checks and saves, with ttrpg2's dice bugs fixed"`

### Task 4: Characters, the party, and transactions

**Files:**
- Create:
  - `src/delve/domain/characters.py`;
  - `src/delve/rules/adnd2e/{class_xp.py,names.py}`, ported from ttrpg2 `tools/class_xp.py` and `names.py`, as pure code;
  - `src/delve/play/{context.py,characters.py}`;
  - `src/delve/storage/migrations/versions/0003_play_state.py`;
  - repository modules in `src/delve/storage/sqlite/`.
- Modify: `src/delve/storage/interfaces.py` (`Storage.transaction()`, new repos), `src/delve/domain/campaigns.py`
- Test: `tests/play/test_characters.py`, `tests/storage/contract.py` (extend), `tests/rules/adnd2e/test_class_xp.py`, `tests/rules/adnd2e/test_names.py`

**Interfaces:**
- **Domain types:**
  - `Sheet` holds the static fields from ttrpg2's PC record (`campaign_mgmt.py:350-381`). The prose `weapon` stays, but `attacks` is the structured source of truth.

    ```
    kind: "pc" | "npc"
    label
    race, gender
    cls, levels: {class: level}
    hp_max
    ac, thac0
    saves: {type: value}
    ability_scores
    attacks[{name, speed, attacks, thac0, damage_sm, damage_l, range?}]
    weapon_profs, nwps, natural_abilities
    skills
    size, ac_vs_larger, movement_rate, alignment
    background, portrait_prompt
    spell_slots: {level: n}
    notes_md                # NPCs: their story
    disposition: int        # NPCs
    ```
  - `CharacterState`:

    ```
    hp, xp
    conditions[]
    effects[{name, duration, to_hit?, ac?, dmg?, save?, source?}]
    ```

    This fixes the bug where `end_combat` dropped conditions and effects.
  - `Character` grows to `(id, campaign_id, name, kind, sheet: Sheet, state: CharacterState, order: int)`. `order` is the marching order, and NPCs have `None`.
  - `CampaignState(campaign_id, day, hour, minute, session: int, coin: {pp, gp, ep, sp, cp}, loot: [LootItem])`.
- **Migration `0003_play_state`** adds:
  - to characters: `kind`, `sheet` (JSON), `state` (JSON) and `order`;
  - the tables `campaign_state`, `rolls`, `events` (`id, campaign_id, session, beat, type, data, at`), `sessions`, `notes`, `combats` and `house_rules*` (the last for Task 9).
- **Transactions:** `Storage.transaction() -> ContextManager[None]`. Every repository write inside it joins one SQLite transaction, and an exception rolls all of it back. Repositories used outside a transaction keep autocommitting.
- **`CampaignContext`** (dataclass): `storage`, `reference: Reference`, `dice: Dice`, `campaign_id`, `beat: str`, and `log(type, **data)`, which appends an event.
  - `context_for(storage, reference, campaign_id, beat, rng=SystemRng()) -> CampaignContext`.
- **`play.characters`** (each function takes a `CampaignContext` first):
  - `create(ctx, *, name, kind="pc", sheet: dict) -> Character`. It validates and fills the saves from the class table when they're missing, and logs `character_created`.
  - `get(ctx, ref: str) -> Character`. It resolves by id or an **exact, case-insensitive** label. Ambiguous or unknown refs raise `NotFound(candidates)`, never a prefix match. (This fixes `targets_match_by_prefix`.)
  - `update(ctx, ref, patch: dict, reason="") -> Character`.
  - `party(ctx) -> list[Character]`, the PCs in marching order.
  - `set_marching_order(ctx, refs: list[str])`.
  - `apply_damage(ctx, ref, amount)` and `apply_heal(ctx, ref, amount)`. A heal never raises a dead character: HP stays at or below -10, and the call gives an error hint to use a raise.
  - `award_xp(ctx, ref, amount) -> {per_class, level_up_hints}`, using the multi-class split from `class_xp`.
  - `update_coin(ctx, delta: str)`.
  - `rest(ctx, ref="", days=1, bed_rest=False, full=False)`, using PHB natural healing. Spell slots reset in Task 5.
  - `introduce_npc(ctx, *, race, gender="", description="") -> Character`, which names the NPC with `names.generate` through the dice, and `set_disposition(ctx, ref, value, reason="")`.

- [ ] **Step 1: Write the failing tests.**
  - Contract tests:
    - `test_transaction_rolls_back_all_repos` (Review Focus 3);
    - `test_character_sheet_state_roundtrip`;
    - `test_events_append_and_list`.
  - `play.characters` tests:
    - `test_exact_or_ambiguous_never_prefix`;
    - `test_heal_does_not_revive_dead`;
    - `test_award_xp_multiclass_split` (ported from ttrpg2's tests);
    - `test_marching_order`;
    - `test_names_deterministic_with_seeded_rng`;
    - `test_introduce_npc_logs_event`.
- [ ] **Step 2: Run, expect failure.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run.** `uv run pytest` and `lint-imports` pass.
- [ ] **Step 5: Commit.** `git commit -m "Characters, NPCs, the party and one transaction per tool call"`

### Task 5: Inventory, encumbrance and spell loadouts

**Files:**
- Create: `src/delve/rules/adnd2e/{encumbrance.py,spells.py}` (encumbrance ported from ttrpg2 `tools/item_weights.py`), `src/delve/play/{inventory.py,spells.py}`
- Modify: `src/delve/domain/characters.py`
- Test: `tests/rules/adnd2e/test_encumbrance.py`, `tests/play/test_inventory.py`, `tests/play/test_spells.py`

**Interfaces:**
- **Inventory:**
  - `Item(name: str, qty: int = 1, weight_lb: float | None = None, notes: str = "")`.
  - It replaces ttrpg2's two inventories: there is a single `inventory: list[Item]` in `CharacterState`.
  - `add_item(ctx, ref, name, qty=1, notes="")`, `remove_item(ctx, ref, name, qty=1)`, `transfer(ctx, item, qty, source, dest)` (a source or dest may be `"loot"`), and `inventory(ctx, ref="") -> dict`.
  - `encumbrance(ctx, ref) -> {total_lb, band, movement, penalty}`. The bands are light 0, moderate -3, heavy -6, severe -9 and overloaded -12, as in ttrpg2.
  - Weights come from `reference.item` and the ported `INVENTORY_ALIASES`. An unknown item counts as 0 lb, with a warning.
- **Spell loadouts (new):**
  - `SpellLoadout`, part of `Sheet`: `known: {level: [spell]}` and `default: {level: [spell]}`.
  - `memorized: [{name, level, cast: bool}]`, part of `CharacterState`.
  - `set_loadout(ctx, ref, *, known=None, default=None)`. It validates the default against `spell_slots` per level, and refuses unknown spell names with candidates from the reference.
  - `memorize(ctx, ref, spells: list[str] | None = None)`. `None` means "memorize the default". It checks the slot caps per level.
  - `cast(ctx, ref, spell) -> {spell, level, remaining}`, which refuses a spell that isn't memorized or is already cast.
  - `spell_status(ctx, ref)`.
  - `rest` (Task 4) also clears the `cast` flags. With `rememorize=True` it memorizes the default again.

- [ ] **Step 1: Write the failing tests.**
  - `test_one_inventory`;
  - `test_transfer_between_characters_and_loot`;
  - `test_encumbrance_bands` (ported cases);
  - `test_default_loadout_fits_slots`;
  - `test_memorize_default`;
  - `test_cast_marks_once`;
  - `test_rest_clears_cast_and_rememorizes`;
  - `test_unknown_spell_candidates`.
- [ ] **Step 2: Run, expect failure.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, expect them to pass.**
- [ ] **Step 5: Commit.** `git commit -m "One inventory, encumbrance, and structured spell loadouts"`

### Task 6: Treasure and the loot pile

**Files:**
- Create: `src/delve/rules/adnd2e/{treasure_tables.py,treasure.py}` (the tables copied from ttrpg2 `treasure.py`, unchanged), `src/delve/play/treasure.py`
- Test: `tests/rules/adnd2e/test_treasure.py`, `tests/play/test_treasure.py`

**Interfaces:**
- `generate(dice, types: str) -> TreasureResult(coins: dict, gems: list, art: list, magic: list[MagicItem(category, name)], rolls)`.
  - It returns structured data and prints nothing.
  - Its rolls are logged under purpose `treasure:<type>`, so asking again in the same beat returns the same hoard.
- `award_treasure(ctx, types, note="") -> TreasureResult`, in one transaction:
  - coins are added to `CampaignState.coin`;
  - everything else goes to `loot` as `LootItem(kind, description, value_gp, category)`, where the description no longer carries the category tag;
  - it logs `treasure_awarded`.
- `loot_pile(ctx)` and `claim_loot(ctx, index, ref)`.
- `generate_treasure(ctx, types)` returns the hoard without awarding it (for the DM to describe), and is logged. This fixes `generate_treasure_neither_logs_nor_applies`, since the same beat gives the same result.

- [ ] **Step 1: Write the failing tests.**
  - The ported table tests.
  - `test_generate_is_logged_and_stable_within_beat`;
  - `test_award_applies_coins_and_loot_atomically`, where a write failing halfway leaves nothing (Review Focus 3);
  - `test_magic_description_has_no_category_tag`.
- [ ] **Step 2: Run, expect failure.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, expect them to pass.**
- [ ] **Step 5: Commit.** `git commit -m "Treasure as data, logged, awarded atomically"`

### Task 7: Combat, a state machine on the map

**Files:**
- Create: `src/delve/rules/adnd2e/combat.py` (pure), `src/delve/maps/tokens.py`, `src/delve/play/combat.py`
- Test: `tests/rules/adnd2e/test_combat.py`, `tests/maps/test_tokens.py`, `tests/play/test_combat.py`

**Interfaces:**
- **Ported as pure helpers** from ttrpg2 `tools/combat.py:139-710`:
  - `_parse_dice`, size rules, `_attack_rate` and `_attacks_allowed_in_round`;
  - `_normalize_attacks` and `_select_attack`;
  - the monster stat parsers (`_parse_ac`, `_parse_morale`, `_parse_hd`, `_roll_monster_hp`, `_parse_damage`).
- **Types:**
  - `Combatant`:

    ```
    id, name, side: party | ally | enemy
    character_id | None
    hp, hp_max, ac, thac0, attacks, size, ac_vs_larger
    conditions, effects
    init | None
    node | None             # its room on the map
    morale | None
    ```
  - `Combat`:

    ```
    phase: setup | round | ended
    round: int
    order: [combatant ids]
    current: int
    combatants: {id: Combatant}
    surprise: {party, enemies}
    declared: {id: action}
    log
    ```
- **Commands.** Each is pure: `(Combat, Dice, Reference, …) -> (Combat, Result)`.
  - **Starting:**
    - `start(party, *, map_nodes)` refuses with `CombatActive` when a fight is live, unless `abort=True`. (This fixes `start_combat_wipes_a_live_fight`.)
    - `add_monsters(combat, dice, reference, name, count, *, node=None, side="enemy")` gives the ids `mon_1…`. Duplicate names are fine, and ids keep them apart.
  - **Surprise:** `apply_surprise(combat, result)`. A surprised side loses the first round: it gets no actions in round 1 (this fixes `surprise_is_reported_but_never_applied`).
  - **Declarations:** `declare(combat, id, action)` covers spells too, and must come before initiative. An attack before the round has started is refused (this fixes `attack_is_allowed_before_initiative`).
  - **`run_round(combat, dice, reference, declarations)`** does, in order:
    1. initiative is **rolled again each round**, as d10 plus weapon speed or casting time; ties go to the higher dexterity, then to the lower id;
    2. actions resolve in initiative order;
    3. downed or dead combatants are skipped;
    4. fractional attack rates follow the round number (this fixes `half_attack_per_round_still_swings_every_round`);
    5. at the end of the round, bleeding applies to party **and** allies (this fixes `allies_never_bleed_out`), effects tick down, and morale triggers at 50% casualties.

    It returns a `RoundResult` with every roll.
  - **One attack:** `attack(combat, dice, attacker_id, target_id, *, condition="", weapon="")` refuses a dead or downed attacker. Fleeing targets: a rear attack gets +2 to hit (PHB), with a real roll (this fixes `fleeing_auto_hits_and_reports_a_made_up_roll_of_10`). Targets are named by id or by an exact unique name.
  - **Changes during the fight:**
    - `damage(combat, id, amount)` and `heal(combat, id, amount)`; a heal doesn't raise the dead;
    - `add_condition` and `remove_condition`;
    - `apply_effect` and `remove_effect`;
    - `adjudicate(combat, note, effects)`, the DM's logged ruling.
  - **`end(combat)`** returns the outcome:
    - `{hp, conditions, effects}` per character, written back by `play.combat.end`. This fixes `end_combat_drops_conditions_and_effects`.
    - Damage applied to a character outside the tracker during combat goes through the tracker, so nothing is lost (this fixes `damage_outside_the_tracker_is_lost_on_end_combat`).
    - The defeated groups, for XP and treasure.
  - `status(combat)` always answers, even with no combatants (this fixes `combat_status_raises_with_no_combatants`).
- **`maps.tokens.with_tokens(dmap, tokens: list[Token(id, label, node, side, portrait_ref=None)]) -> DungeonMap`** adds DSL `Marker`s anchored with `in <node>`. Fog keeps only the markers in discovered nodes, which is the plateau 1 invariant, so tokens in undiscovered rooms never show. Each token is placed at its node's centroid, with small offsets per token.
- **`play.combat`** persists `Combat` in the `combats` table, one live fight per campaign. It writes the HP back to characters through `play.characters`.
  - `setup_combat(ctx, enemies=[{name, count, node?}], party_modifier=0, enemy_modifier=0, surprise=True, spells=None) -> {combat, surprise, order}` covers start, monster lookup, adding them, surprise, declarations and initiative. It is the composite, as ttrpg2's.
  - `combat_round(ctx, actions)`, `resolve_attack(ctx, attacker, target, …)`, `combat_status(ctx)` and `end_combat(ctx)`.
  - The map view routes from plateau 1 render the tokens of the live combat.

- [ ] **Step 1: Write the failing tests.** One for each combat `known_bug` in ttrpg2 `tests/test_char_combat.py` (15), named after the fixed behaviour with the rule cited. Plus:
  - `test_duplicate_monster_names_have_distinct_ids`;
  - `test_ambiguous_target_candidates` (Review Focus 1);
  - `test_same_save_twice_in_round_returns_stored` and `test_next_round_rolls_fresh` (Review Focus 2);
  - `test_tokens_in_undiscovered_rooms_not_in_fog_view`;
  - `test_end_combat_writes_back_hp_conditions_effects`.

  Port the non-bug characterisation tests.
- [ ] **Step 2: Run, expect failure.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, expect them to pass.**
- [ ] **Step 5: Commit.** `git commit -m "Combat as a state machine on the map, with ttrpg2's combat bugs fixed"`

### Task 8: Moving on the map, notes, secrets, sessions and time

**Files:**
- Create: `src/delve/play/{moves.py,notes.py,sessions.py}`
- Test: `tests/play/test_moves.py`, `tests/play/test_notes.py`, `tests/play/test_sessions.py`

**Interfaces:**
- **Moves:**
  - `move(ctx, *, to, characters: list[str] | None = None, map: str | None = None) -> {perceived, dm_only, room_notes, groups}`. `None` means the whole party.
    - It updates the map state through `delve.maps.state.move`, which plateau 1 stores, so the map can't be forgotten.
    - It logs `moved`.
    - The room's `room_context` is split into `perceived` and `dm_only`.
  - `room(ctx, query="", characters=None)`.
  - `door(ctx, door, state="", found=False)`, which updates `door_states` or reveals the door.
  - `note_room(ctx, text, query="")`, a DM-only note about a room.
- **Notes and secrets:**
  - `dm_note(ctx, text, tags=(), related_to="")` and `dm_secrets(ctx, tag="", related_to="", contains="")`.
  - `dm_secret_update(ctx, id, text=None, tags=None, related_to=None, revealed=None)`.
  - `log_note(ctx, text)`, a public chronicle line.
- **Sessions and time:**
  - `new_session(ctx, title)` raises the session number and logs `session_start`.
  - `end_session(ctx, recap_md)` stores the recap. Plateau 2b's DM writes it.
  - `advance_time(ctx, minutes)` and `set_time(ctx, hour, minute=0)`.
  - `primer(ctx) -> dict`. It's the successor of ttrpg2 `session_primer`, without strongholds, light or weather:
    - the day and time;
    - the session and the last recap;
    - the party with hp, ac, thac0, attacks, levels, conditions, memorized and uncast spells, inventory summary and encumbrance band;
    - the marching order;
    - the position groups;
    - the last 8 events;
    - the live combat summary.

- [ ] **Step 1: Write the failing tests.**
  - `test_move_updates_map_state_and_logs`
  - `test_split_move_only_named_characters`
  - `test_room_context_split`
  - `test_door_states`
  - `test_secrets_filter_and_reveal`
  - `test_session_cycle_and_recap`
  - `test_primer_shape`
- [ ] **Step 2: Run, expect failure.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, expect them to pass.**
- [ ] **Step 5: Commit.** `git commit -m "Moves on the map, notes, secrets, sessions and time"`

### Task 9: House rules and bundles

**Files:**
- Create:
  - `reference/house-rules/`, copied from ttrpg2 `global/house-rules/`: `general.md`, `races/`, `classes/` and `items/`, 42 files;
  - `src/delve/domain/house_rules.py`;
  - `src/delve/play/house_rules.py`;
  - `src/delve/web/routes/house_rules.py`;
  - `scripts/` is not needed. The seed import is part of `delve` (below).
- Modify: storage (repositories; the tables were created in 0003), `src/delve/__main__.py` (`delve house-rules import <dir>`)
- Test: `tests/play/test_house_rules.py`, `tests/web/test_house_rules_api.py`

**Interfaces (spec §9; ttrpg3's model, simplified):**
- **Types:**
  - `HouseRule`:

    ```
    id: hr_<12 hex>
    title
    body_md
    kind: general | race | class | item | behaviour
    phases: frozenset[character-creation | level-up | combat | items | behaviour | always]
    ruleset: str | None             # "adnd2e", "osric"…; None means any
    setting: str | None             # "greyhawk", "forgotten-realms"…; None means any
    subject: str | None             # the race, class or item a rule is about, e.g. "lizardfolk"
    enabled: bool
    ```

    `kind` groups rules in the list, and `phases` say when a rule applies.
  - `Bundle(id: hb_<12 hex>, title, description_md, rule_ids: tuple[str, ...])`, an ordered list.
- **Choosing rules for a campaign:** `campaign_house_rules(campaign_id) -> {bundle_ids, rule_ids}`. A campaign **points to** rules; it doesn't copy them, so an edit to a rule applies to running campaigns. The effective set is the union of the chosen bundles' rules and the single rules, minus disabled rules, minus rules whose `ruleset` or `setting` doesn't match the campaign. In plateau 2a, a campaign's ruleset is `adnd2e` and its setting is `greyhawk`.
- **When each rule reaches the DM (spec §9):** `rules_for(ctx, *, phase=None, subjects=None) -> list[HouseRule]`.
  - Rules with the `behaviour` or `always` phase are for the system prompt (plateau 2b), and so are race and class rules whose `subject` matches a race or class in the party.
  - `play.characters.create` returns the `character-creation` rules in its result, under the key `house_rules`.
  - `award_xp` returns the `level-up` rules when a level-up hint fires.
  - `reference` item lookups and `add_item` return the `items` rules whose subject matches.
- **Seed import:** `import_house_rules(storage, root: Path) -> Bundle`.
  - `general.md` is split by `#` heading. "Character creation" becomes phase `character-creation`, "Level up" becomes `level-up`, and any other heading becomes `always`. Each bullet becomes one rule, titled from its first words.
  - `races/*.md` become kind `race` rules, with phase `character-creation` and subject from the file name.
  - `classes/*.md` become kind `class` rules, with phases `character-creation` and `level-up`.
  - `items/*.md` become kind `item` rules, with phase `items` and the item as subject.
  - It creates one bundle, "My table (from ttrpg2)", containing every imported rule.
  - It runs once, automatically, on first start when the library is empty, from `reference/house-rules/` shipped in the wheel. `delve house-rules import` runs it on demand. Importing the same files again is idempotent: it matches by kind, subject and title.
- **API (organiser):**
  - CRUD on `/api/house-rules` and `/api/house-rules/{id}`, and on `/api/house-rule-bundles` and `/api/house-rule-bundles/{id}` (including the ordered `rule_ids`);
  - `GET` and `PUT /api/campaigns/{id}/house-rules {bundle_ids, rule_ids}`;
  - `GET /api/campaigns/{id}/house-rules/effective?phase=`.
  - `POST /api/campaigns` (plateau 1) accepts optional `bundle_ids` and `rule_ids`.
  - Event: `house_rules`.

- [ ] **Step 1: Write the failing tests.**
  - `test_seed_import_splits_general_by_heading`: assert the 4 rules from ttrpg2's `general.md` and their phases.
  - `test_race_rule_subject_from_filename`;
  - `test_seed_runs_once_and_is_idempotent`;
  - `test_effective_set_union_minus_disabled_and_mismatched_setting`, where a rule tied to Forgotten Realms is left out of a Greyhawk campaign;
  - `test_creation_rules_returned_by_create`;
  - `test_level_up_rules_returned_on_level_up_hint`;
  - `test_campaign_points_to_rules_edit_applies`;
  - `test_api_crud_and_organiser_only`.
- [ ] **Step 2: Run, expect failure.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, expect them to pass.** Extend `test_wheel` to check that `reference/house-rules/general.md` is in the wheel; use `artifacts` or force-include.
- [ ] **Step 5: Commit.** `git commit -m "House rules and bundles, seeded from ttrpg2, applied by phase"`

### Task 10: The 2e ruleset and lookups

**Files:**
- Create: `src/delve/rules/adnd2e/ruleset.py`
- Modify: `src/delve/__main__.py` / `src/delve/web/defaults.py` (register `Adnd2eRuleset` in place of `FakeRuleset` when the reference exists)
- Test: `tests/rules/adnd2e/test_ruleset.py`

**Interfaces:**
- `Adnd2eRuleset(reference)` implements plateau 0's `Ruleset` with:
  - `id = "adnd2e"` and title "AD&D 2nd edition";
  - kinds `monster`, `spell`, `item`, `class`, `ability`, `proficiency` and `rule`;
  - `lookup(kind, query, limit)` returning `ReferenceHit`s.

  It also has typed helpers that the tools use: `monster(name)`, `spell(name, caster)`, `rules(query, source)`, `rules_section(source, section)` and `turning_undead`.
- **Where `ReferenceHit` lives:** it moves to `delve.domain` (the plateau 0 note). `delve.rules.ruleset` and `delve.setting` import it from there.

- [ ] **Step 1: Write the failing tests:** `test_lookup_each_kind_on_fixture_reference`, `test_unknown_kind_lists_kinds` and `test_ruleset_registered_when_reference_present`.
- [ ] **Step 2: Run, expect failure.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run.** `uv run pytest` and `lint-imports` pass.
- [ ] **Step 5: Commit.** `git commit -m "The AD&D 2e ruleset over the reference store"`

### Task 11: The DM's tool surface and `batch`

**Files:**
- Create: `src/delve/dm/tools/{__init__,host,schema,lookups,dice,party,combat,map,notes,house_rules,composites}.py`
- Test: `tests/dm/tools/test_host.py`, `tests/dm/tools/test_batch.py`, `tests/dm/tools/test_tools.py`

**Interfaces:**
- `@dataclass(frozen=True) class ToolSpec`:
  - `name`;
  - `description` (one paragraph, written for the DM);
  - `params: dict` (JSON Schema);
  - `fn: Callable[[CampaignContext, dict], dict]`;
  - `mutates: bool`;
  - `player_visible: bool`, which says whether the result may appear in the players' feed. It's `False` for DM-only tools such as `dm_secrets`, `dm_note`, `room` details and `module` lookups.
- `class ToolHost`:
  - `__init__(storage, reference, rng_factory)`;
  - `specs() -> list[ToolSpec]`;
  - `call(campaign_id, beat, name, args) -> dict`. It:
    1. validates the args against the schema, and answers `{"error", "hint"}` on a mismatch;
    2. opens a `CampaignContext`;
    3. runs the tool **in one `storage.transaction()`**;
    4. converts known exceptions (`NotFound`, `CombatActive`, `BadNotation`…) into `{"error", "hint", "candidates"?}`;
    5. never raises for a tool error.
- **Tools.** Names follow ttrpg2's where the capability is the same, so plateau 2b's prompt and evals carry over. Each calls the `play` services of Tasks 4–9.
  - **Lookups:** `rules_lookup(query, source?)`, `rules_section`, `monster_lookup`, `spell_lookup(name, caster?)`, `item_lookup`, `class_lookup`, `ability_lookup`, `proficiency_lookup`, `turning_undead`.
  - **Dice and checks:** `roll(notation, purpose)`, `saving_throw(character, save_type, modifier?)` (also takes combatant ids), `skill_check`, `ability_check`, `reaction(npc?, modifier?)`, `morale_check`, `surprise_check`, `encounter_check(terrain, level?, dungeon_level?)`, `system_shock`, `resurrection_check`.
  - **Characters:** `create_character(name, kind?, sheet)`, `get_character(ref, brief?)`, `update_character(ref, patch, reason?)`, `introduce_npc(race, gender?, description?)`, `set_disposition`, `party_status`, `set_marching_order`, `apply_damage`, `apply_heal`, `award_xp`, `update_coin`, `rest`.
  - **Inventory and spells:** `add_item`, `remove_item`, `transfer`, `inventory`, `encumbrance`, `set_spell_loadout`, `memorize_spells`, `cast_spell`, `spell_status`.
  - **Treasure:** `generate_treasure`, `award_treasure`, `loot_pile`, `claim_loot`.
  - **Combat:** `setup_combat`, `combat_round`, `resolve_attack`, `add_combatant`, `remove_combatant(id, reason)`, `apply_effect`, `remove_effect`, `add_condition`, `remove_condition`, `adjudicate`, `combat_status`, `end_combat`.
  - **The map:** `move_party(to, characters?, map?)`, `room(query?)`, `door(door, state?, found?)`, `note_room`.
  - **Notes and time:** `dm_note`, `dm_secrets`, `dm_secret_update`, `log_note`, `new_session`, `end_session(recap)`, `advance_time`, `set_time`, `session_primer`.
  - **House rules:** `house_rules(phase?, query?)`.
  - **Composites:**
    - `batch(steps, stop_on_error=True)` with **ttrpg2's exact semantics** (`tools/composites.py:40-119`):
      - at most 25 steps, run in sequence;
      - a per-step result `{step, tool, result}` or `{step, tool, error}`;
      - `batch` itself is denied as a step;
      - unknown tools, bad args and raises are recorded per step;
      - with `stop_on_error`, it stops after the first error, and that step is included;
      - it returns `{ran, requested, stopped_early, results}`;
      - **each step is its own transaction.**
    - `scout(character, checks?, minutes=10, terrain="dungeon")` and `council(npcs, base_modifier=0)`, as ttrpg2's.
  - `pre_turn_check` is not ported; plateau 2b's evals decide whether it comes back.

- [ ] **Step 1: Write the failing tests.**
  - `test_every_spec_has_valid_schema_and_description`;
  - `test_bad_args_error_not_raise`;
  - `test_tool_call_is_one_transaction`;
  - batch tests ported one for one from ttrpg2 `tests/test_composites.py:167-222` (order, `name` passthrough, empty or over 25 steps, stop vs continue, exceptions, unknown tool, denial, bad args), plus `test_batch_steps_commit_separately`;
  - `test_tool_names_cover_feature_review`, which checks the kept capabilities against `docs/review/feature-review.md`'s kept list, and that none of the cut ones exists.
- [ ] **Step 2: Run, expect failure.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, expect them to pass.**
- [ ] **Step 5: Commit.** `git commit -m "The DM tool surface, with ttrpg2's batch semantics"`

### Task 12: The fourth wall in tool results

**Files:**
- Create: `src/delve/dm/tools/redact.py`
- Test: `tests/dm/tools/test_fourth_wall.py`

**Interfaces:**
- `player_view(spec: ToolSpec, args: dict, result: dict) -> dict | None`. It is the allow-list that plateau 2b's players' feed uses. It returns:
  - `None` for tools whose `player_visible` is `False`;
  - otherwise the result with every `dm_only` key removed at any depth, plus the keys `secret_exits`, `hidden_annotations` and `secret_map_exits` (as ttrpg2's `_DM_ONLY_KEYS`), and any field a tool marks DM-only.

  Rolls stay visible, because they're public.

- [ ] **Step 1: Write the failing test** `test_planted_secret_never_in_player_view_or_perceived`. For every tool that returns `perceived`, or is `player_visible`, run it on a campaign with `SECRET-XYZZY` planted in:
  - a hidden room's label;
  - an NPC's `notes_md`;
  - a DM secret;
  - a `note_room`.

  Assert the string is absent from `result["perceived"]` and from `player_view(...)`. Also `test_dm_only_tools_have_no_player_view`.
- [ ] **Step 2: Run, expect failure.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, expect them to pass.**
- [ ] **Step 5: Commit.** `git commit -m "Player view of tool results: an allow-list with planted-secret tests"`

### Task 13: Frontend for house rules and character sheets

**Files:**
- Create: `web/src/routes/HouseRules.tsx` (replacing the placeholder), `web/src/house-rules/{RuleList,RuleEditor,BundleEditor}.tsx`, `web/src/campaign/{HouseRulePicker,CharacterSheet}.tsx`
- Modify: `web/src/routes/Campaigns.tsx` (house rules in "New campaign"), `web/src/routes/CampaignDetail.tsx` (house rules and sheets), `web/src/i18n/{en,nl}.json`
- Test: `web/src/house-rules/*.test.tsx`, `web/src/campaign/CharacterSheet.test.tsx`

**Interfaces:**
- Consumes: the Task 9 API, `GET /api/campaigns/{id}/characters` (now with `kind`, `sheet`, `state` and `order`), and the SSE events `house_rules` and `characters`.
- Produces:
  - **The house rules page (desktop):**
    - rules grouped by kind, with a filter;
    - the editor has a title, a Markdown text area with a preview, kind, phase chips, ruleset, setting, subject, and enabled;
    - bundles show an ordered list of rules, with add and remove and up/down arrows.
  - **"New campaign"** and the campaign page get a picker for bundles and single rules.
  - **The campaign page** shows a read-only sheet per character: HP, AC, THAC0, saves, attacks, inventory with encumbrance, and the spell loadout with memorized and cast spells. Plateau 2b's play screen builds on these components.

- [ ] **Step 1: Write the failing tests:**
  - the rule editor saves its phases;
  - a bundle reorders with the arrows;
  - the campaign create posts `bundle_ids`;
  - the sheet shows cast spells struck through, and the encumbrance band.
- [ ] **Step 2: Run, expect failure.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run.** `npm test`, `typecheck` and `build` pass.
- [ ] **Step 5: Commit.** `git commit -m "House rules editor, campaign house rules, character sheets"`

### Task 14: An end-to-end session without Claude, and integration

**Files:**
- Create: `tests/e2e/test_scripted_session.py`, `tests/fixtures/scripts/first_session.json`
- Modify: `GUILD.md`, `README.md`
- Test: as above

**Interfaces:**
- **A scripted session through `ToolHost`**, a fixed list of tool calls with a `SeededRng`, on the imported sample module:
  1. create a campaign with the seeded bundle;
  2. `create_character` ×4, whose result includes the creation house rules;
  3. `set_spell_loadout` and `memorize_spells`;
  4. `move_party`;
  5. `setup_combat` with goblins in the next room;
  6. 3× `combat_round`;
  7. `end_combat`, `award_xp` (with the level-up rules) and `award_treasure`;
  8. `rest`;
  9. `end_session(recap)`.

  Assert:
  - the final state matches a golden JSON (`tests/fixtures/scripts/first_session.golden.json`);
  - every roll is in the log;
  - initiative was rolled in each round;
  - the fog view at the end shows only the rooms visited.
- **The server's share of the speed budget (spec §6.4).** `tests/e2e/test_tool_timing.py` replays the scripted session
  5 times on a warm process and records each tool call's time. Its 95th percentile must stay under 50 ms. The heaviest
  calls (`setup_combat`, `combat_round`, `move_party`) are reported by name. Parse each map once per revision and cache
  the parsed map and its graph by `(module_id, revision, map_name)`; plateau 1 parsed on every request.
- `make ci` includes it.
- `GUILD.md` is updated with:
  - the dice rule;
  - transactions;
  - the tool conventions;
  - the reference build;
  - the house-rule phases.

- [ ] **Step 1: Write the test and the golden file.** The golden is generated once from the implementation, then reviewed by hand against the rules, with the reasoning written in the test's docstring.
- [ ] **Step 2: Run, expect failure** until all the tasks are merged.
- [ ] **Step 3: Fix the integration mismatches.**
- [ ] **Step 4: Run `make ci`.** Everything passes. Report the test counts per area, and the number of `known_bug` fixes (27).
- [ ] **Step 5: Commit.** `git commit -m "Plateau 2a: a scripted session end to end, without Claude"`

---

## Order and parallelism

- **Task 1** (reference) and **Task 2** (dice) come first, and can run in parallel.
- **Task 3** needs 1 and 2. **Task 4** needs 2 (and storage). **Task 10** needs 1.
- **Tasks 5, 6, 8 and 9** need 4. **Task 7** needs 3 and 4.
- **Task 11** needs 3 to 10. **Task 12** needs 11.
- **Task 13** can start from the API shapes after Task 4 and Task 9 are specified. In practice it starts with Task 9.
- **Task 14** is last.

## Done when

- `make install && make ci` passes on a fresh clone, including building `reference.db` from the committed snapshots.
- All 27 of ttrpg2's `known_bug` behaviours have tests of the correct rule, and they pass.
- The scripted session runs through the tool host with a fixed seed and matches its golden file, and each tool call's 95th percentile stays under 50 ms.
- In the browser:
  - the house rules page lists the seeded "My table (from ttrpg2)" bundle;
  - a new campaign can take it;
  - a character created through the tool host shows its sheet on the campaign page.
