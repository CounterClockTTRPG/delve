# Delve plateau 2a: the game engine


Plateau 2a is built: all 14 tasks of `docs/superpowers/plans/2026-10-17-plateau-2a-game-engine.md`, one commit each with the plan's message, merged on `guild/20261017-7822addf/party`. Delve can now run a whole session without Claude.

## Verification
I ran `make install && make ci` in the integration worktree after the last merge, and it passes. `make install` builds `reference.db` from the committed snapshots.
- **Python checks:** ruff clean; lint-imports 5 contracts kept, 0 broken.
- **pytest:** 1342 passed, 1 skipped. The skip is `test_wheel`, which needs the built web app. Run after the build, it passes: `tests/e2e` plus `test_wheel` gave 6 passed.
- **Web:** typecheck, 72 tests and the build pass.
- **Scripted session:** matches its golden file.
- **Tool timing:** p95 is about 8 ms against the 50 ms budget. The heaviest calls are `setup_combat` (about 11 ms), `combat_round` (about 8 ms) and `move_party` (about 3 ms).

## What each task delivered
- **Task 1, the reference store (Pieter):**
  - `scripts/snapshot_reference.py` dumps ttrpg2's DBs, opened read-only. Running it twice gives byte-identical snapshots.
  - `build_reference` checks the checksums, builds FTS5 and writes to a temp file before renaming it into place. `open_reference` raises `ReferenceMissing` or `ReferenceStale`, and `delve serve` turns either into exit code 4 with `Run: delve reference build`.
  - There are `delve reference build|check` commands, and `make install` builds the reference.
  - `test_real_snapshot_builds` is marked slow and runs in `make ci`.
- **Task 2, dice (Omar):**
  - Notation limits, `RollKey` and `Roll`, a `RollLog` stored in the `rolls` table, and `SystemRng`, `SeededRng` and `ScriptedRng`.
  - No re-roll within a beat.
  - A test checks that only `dice.py` imports `random`.
- **Task 3, checks and saves (Omar):** saves, skill and ability checks, reaction, morale, surprise, system shock, resurrection, turning undead and encounter checks, with the tables in `tables.py`.
- **Task 4, characters and transactions (Omar):**
  - Domain types, `class_xp` and `names`.
  - Migration `0003_play_state`, which creates every table the later tasks needed.
  - `Storage.transaction()`; inside it, every repository write joins one SQLite transaction.
  - `CampaignContext`, and `play.characters`, where a character is found by an exact name or not at all, with candidates when the name is ambiguous.
- **Task 5, inventory and spells (Mateo):** one inventory, encumbrance ported from ttrpg2's `item_weights.py`, and structured spell loadouts. `rest` clears the cast flags and can memorize the default again.
- **Task 6, treasure (Mateo):**
  - The tables are copied unchanged; a script confirmed they match ttrpg2's.
  - `generate` returns data, and its rolls are logged.
  - `award_treasure` runs in one transaction, and a mutation test shows that a write failing halfway leaves nothing.
  - The loot pile and claiming from it.
- **Task 7, combat (Bram):**
  - A pure combat state machine.
  - `maps/tokens.py` adds fog-safe combat tokens, and the map view routes draw the live fight's tokens.
  - `play.combat` stores the fight in a `combats` repository, one live fight per campaign. The changes in a fight are written through to the character sheets as they happen.
- **Task 8, the map, notes and sessions (Mateo):**
  - Moves go through `maps.state`, and `room_context` is split into `perceived` and `dm_only`.
  - Doors, notes and secrets, sessions and time.
  - `primer`, without strongholds, light or weather.
- **Task 9, house rules (Lucas):**
  - The 42 seed files are copied and become 45 rules (4 general, 15 races, 3 classes, 23 items) in the bundle "My table (from ttrpg2)".
  - The seed import runs automatically on first start, and on demand with `delve house-rules import`. Importing again changes nothing.
  - `rules_for` picks rules by phase. There is an organiser API for rules, bundles and a campaign's choice, and `POST /api/campaigns` accepts `bundle_ids` and `rule_ids`.
- **Task 10, the 2e ruleset (Pieter):** `Adnd2eRuleset` over the reference store, registered when the reference exists. `ReferenceHit` moved to `delve.domain`.
- **Task 11, the DM's tools (Tariq):**
  - 73 tools under ttrpg2's names, in `ToolHost`. Each call is checked against its JSON Schema and runs in one transaction. Errors are `{error, hint, candidates?}`, and a missing reference answers `{"error": "reference data missing"}`.
  - `batch` ports ttrpg2's code line for line, with its 9 tests, and each step is its own transaction.
  - `scout` and `council`, as ttrpg2's.
  - A coverage test places all 190 of ttrpg2's tools as in 2a, in the app, deferred or cut, and checks that no cut tool came back.
- **Task 12, the fourth wall (Tariq):**
  - `redact.player_view` is an allow-list. It removes `dm_only`, ttrpg2's `_DM_ONLY_KEYS` and each tool's `dm_only_keys` at any depth, and redacts a batch step by step.
  - The planted `SECRET-XYZZY` test runs every player-visible tool. Tariq checked that it fails when either protection is removed.
- **Task 13, the frontend (Lucas):** the house rules page (rule list, rule editor with a Markdown preview, bundle editor with arrows), the house-rule picker in "New campaign" and on the campaign page, and a read-only character sheet. All strings are in EN and NL.
- **Task 14, the session end to end (Tariq):**
  - A scripted session through `ToolHost` with seed 237, plus its golden file, reviewed by hand against the rules; the reasoning is in the test's docstring.
  - The timing test.
  - Parsed maps and their graphs are cached by `(module_id, revision, map_name)`, and the cache also covers drawing tokens.
  - `GUILD.md` has a "Game engine" section, and `README.md` is updated.

## Snapshot sizes
| File | Bytes |
|---|---|
| adnd2e.sql.gz | 2,257,372 |
| monsters.sql.gz | 5,542,621 |
| rules.sql.gz | 1,622,762 |
| encounter_tables.json.gz | 132,508 |
| SHA256SUMS | 332 |
| **Total** | **9,555,595 (about 9.6 MB; the plan estimated 15 MB)** |

- **Row counts:** spells 887, items 5653, classes 9, class_levels 180, rules 2362. There are 3826 monsters: 3848 minus 22 soft-deleted rows.
- **Built database:** `reference.db` is 52 MB and builds in under a second.

## Test counts per area
| Area | Tests |
|---|---|
| rules | 209 |
| play | 93 |
| storage | 57 |
| dm/tools | 39 (plus 8 for the fake DM) |
| maps | 671 |
| modules | 78 |
| web (Python) | 135 |
| e2e | 5 |
| domain, setting, images and top-level | 48 |
| frontend (vitest) | 72 |

## The 27 known-bug fixes (ttrpg2 name → rule)
**Combat (15, Bram):**
- start_combat_wipes_a_live_fight → PHB ch. 9; spec §6.5 (a live fight refuses a new start)
- initiative_not_rerolled_each_round → PHB ch. 9, Initiative
- duplicate_names_collide_in_initiative_sort → PHB ch. 9; ids keep combatants apart
- attack_is_allowed_before_initiative → PHB ch. 9, The Combat Round
- fleeing_auto_hits_and_reports_a_made_up_roll_of_10 → PHB ch. 9, Retreat, and Table 51 (a rear attack is +2, with a real roll)
- attack_rolls_are_not_logged → spec §6.5
- dead_attacker_can_still_swing_via_resolve_attack → PHB ch. 9, Hit Points; DMG ch. 9, Death's Door
- targets_match_by_prefix → Review Focus 1 (an exact name, or candidates)
- half_attack_per_round_still_swings_every_round → PHB ch. 9, Multiple Attacks, Table 15
- allies_never_bleed_out → DMG ch. 9, Death's Door
- heal_revives_the_dead → PHB ch. 9; DMG ch. 9
- combat_status_raises_with_no_combatants → spec §6.5
- surprise_is_reported_but_never_applied → PHB ch. 9, Surprise (a surprised side loses the first round)
- end_combat_drops_conditions_and_effects → PHB ch. 9; DMG ch. 9
- damage_outside_the_tracker_is_lost_on_end_combat → PHB ch. 9, Hit Points; spec §6.5

**Dice and checks (10, Omar):**
- dice_count_has_no_upper_bound → spec §6.5 (at most 100 dice, 1000 sides, `times` 20)
- roll_is_not_logged_and_can_be_repeated_freely → spec §6.5 (no re-roll within a beat)
- disposition_uses_floor_division → PHB Table 6 (truncation towards zero)
- surprise_threshold_is_2_not_3 → PHB ch. 9, Surprise (1–3 on a d10)
- surprise_modifier_direction_is_inverted → PHB ch. 9, Surprise
- surprise_event_omits_the_dice → spec §6.5
- missing_saves_fall_back_to_level_zero_values → PHB ch. 9, Table 60
- monsters_cannot_save_through_the_tool → DMG and PHB Table 60 (a monster saves as a fighter of its Hit Dice)
- saves_take_no_modifier_and_ignore_effects → PHB ch. 9, Saving Throw Modifiers
- saving_throw_is_not_logged → spec §6.5

**Treasure (2, Mateo):**
- generate_treasure_neither_logs_nor_applies → DMG ch. 10; spec §6.5
- award_treasure_leaves_the_category_tag_in_magic_descriptions → DMG Tables 88–110

Each fix is a test named for the correct behaviour, and its docstring names the ttrpg2 case and cites the rule. All 27 pass. There are also two fixes outside the 27, both tested:
- **Spell caster case:** 36 spells have their caster as "Priest" or "Wizard", and ttrpg2's `_spell_level` compared case-sensitively, so those spells had no level for a priest or wizard. Matching now ignores case.
- **Gems dropped from awards:** ttrpg2 lost a gem whose value note wasn't "+N%". Structured results can't lose it.

## Deviations from the plan, and why
Every one of these was approved by you at a check-in, except the last group.

**Dice and checks:**
- **`Dice.table(n)`, up to 1,000,000 sides:** it picks an encounter-table entry, and the tables reach 27,136 lines. It is logged and keyed like any roll, and the DM's notation keeps its limits, so `roll("1d27136")` is still refused.
- **`actor` and `combat_round` on `turning_undead`** (and `combat_round` on the other checks), so the no-re-roll key is per actor per round.
- **Surprise segments dropped:** in 2e a surprised side loses one round (PHB ch. 9). Segments are a 1st-edition mechanic.
- **Saves come from PHB Table 60 in `tables.py`.** The reference's `class_levels` save columns are wrong for every class.

**Combat:**
- **Tied initiative is simultaneous** (PHB ch. 9). Each action is rolled against the state at the start of its group, and the damage lands together. This replaces both ttrpg2's rule and the plan's (higher Dex, then lower id); ttrpg2's tie tests are not ported.
- **Dropped:** `combat_round`'s `order="given"`, `setup_combat`'s `initiative=False`, ttrpg2's turn pointer, and the `pipeline` counters (which served the cut `audit_session`). `run_round` resolves a whole round, and `resolve_attack` is one swing inside it.
- **Morale** stays ttrpg2's one-shot `morale_due` notice, which the DM resolves with `morale_check`.
- **Signature additions:**
  - `start(…, live=None, abort=False)`;
  - `add_monsters(…, overrides=None)`;
  - a `map` field on `Combat` and extra fields on `Combatant`;
  - a `combats` repository;
  - the extra `play.combat` functions the tools need.
- **`play.characters` routes changes to a fighting character through the tracker**, using a lazy import, which you allowed.
- **A fight's rolls are keyed under `"<beat>/<combat id>"`.** Tariq found that a second fight in the same beat replayed the first fight's rolls. The test is `test_two_fights_in_one_beat_roll_fresh`.

**Treasure:**
- **Every random call in ttrpg2's treasure code is now a logged Dice roll** with the same odds. ttrpg2's cosmetic second d100 is gone, and the d100 that failed is reported instead.
- **`source` on `generate_treasure` and `award_treasure`:** it is the target in the roll key, and defaults to the types. A second award of the same source in the same beat answers `{error: "already awarded", hint: …}`.
- **`LootItem` gains `qty`** (default 1) and the kind `"item"`.

**Maps and house rules:**
- **`maps/sources.py`:** `parse_map`, `parse_source`, `resolve_includes` and `library_sources` moved out of `web/routes/dsl.py`, with no change in behaviour. The map cache lives there too.
- **`play.characters.create` still returns a `Character`.** `creation_rules(ctx, character)` and `item_rules(ctx, names)` are separate helpers, and the tools `create_character`, `add_item` and `item_lookup` put their rules under `house_rules`. The test is renamed `test_creation_rules_for_created_character`. `award_xp` returns `house_rules` when a level-up hint fires.
- **Two signatures take storage:** `campaign_house_rules(storage, campaign_id)` and `set_campaign_house_rules(storage, campaign_id, *, bundle_ids, rule_ids)`.
- **The seed files are in the wheel** at `delve/reference/house-rules/` (by force-include).

**The characters API and the tools:**
- **`encumbrance` per character** in `GET /api/campaigns/{id}/characters`, computed on the server. The browser computes no rules.
- **`ToolSpec.dm_only_keys`** marks DM-only keys (`room_notes`, `notes_md`), and `player_view` removes them.
- **`ToolHost(…, *, specs=None)`**, so the ported batch tests can register fake tools.
- **`room(query?, characters?)`**, so a split party can say whose room is meant.
- **`rules_lookup(…, ruleset="adnd2e")`:** another ruleset answers an error listing the rulesets.
- **`module_lookup` is deferred to 2b**, and the coverage test lists it as deferred.

**Decisions the engineers made where the plan was silent:**
- **Reference API:** `SnapshotCorrupt` (exit code 1 from `delve reference build`), and the reference errors live in `delve.domain`.
- **Engine and characters:**
  - `names.generate` takes the dice's random source but writes no roll-log entries.
  - A new campaign starts at hour 6 in session 1.
  - Room notes keep the session number, not the in-game day and time.
  - `movement` in the encumbrance result is the movement rate plus the band's penalty, at least 1.
- **House rules:** race, class and item house rules get `ruleset="adnd2e"`; the general rules match any ruleset.
- **Tools:**
  - In `batch`, a tool's own refusal is the step's result, and a schema mismatch, an unknown tool or an exception is the step's error.
  - DM-only tools: `dm_note`, `dm_secrets`, `dm_secret_update`, `note_room`, `room`, `generate_treasure` and `session_primer`.
  - `apply_damage`, `apply_heal` and `saving_throw` also take combatant ids.
  - Optional `turning_undead(character?)` and `morale_check(group?)`.
- **The script:** Sleep isn't cast during the fight, because the engine records a spell as cast but applies no effect.
- **Merging:** Tariq had already merged Bram's, Mateo's and Lucas's branches into his own and resolved the conflicts there. I merged his branch, which already held all their work.

No design or balance numbers were changed.

## What plateau 2b should know
- **`module_lookup` and the module text:** 2b must unpack the `.dscn` text and keys, which plateau 1 keeps only in the stored bundle, and add `module_lookup` (and `module_key`). The first real session needs them.
- **The players' feed:** it must call `player_view` on every tool result. Batch steps are redacted per tool, and errors show only their message, because candidates can name hidden rooms.
- **NPC stories in the characters API:** `GET …/characters` returns the whole sheet, `notes_md` included. It's organiser-only today, but player routes (plateau 4) must redact it.
- **Spell effects** are not applied automatically. The DM rules them with `adjudicate`, `add_condition` or `remove_combatant`, and only the `fleeing` condition changes the rolls.
- **THAC0 in the reference is suspect.** Its priest and thief progressions look wrong against the PHB, so check them before using that column.
- **Open rules question:** a monster under 1 HD ("1-2 hp", "½") saves as a 0-level warrior, while "1-1" counts as 1 HD. Decide whether that is right.
- **No `characters` events from tool-host writes.** The web app won't refresh the sheet when the DM changes a character; 2b's play screen needs those events.
- **`pre_turn_check` isn't ported.** Batch still refuses it by name, in case the evals bring it back.
- **Timing:** the timing test replays a script against the host; add recorded beats with the fake DM on top of it.
- **Possible lint noise:** `map_state.py` and `test_map_state_api.py` weren't `ruff format`-clean before this quest. `make ci` doesn't check formatting.
- **CI skip:** in `make ci`, `test_wheel` skips, because pytest runs before the web build; it passes once the web app is built.

