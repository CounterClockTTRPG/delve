# The DM's evals

Scripted scenarios whose DM transcripts are checked against the Hard Procedural Constraints in
`src/delve/dm/prompt/dm.md`. Ported from ttrpg2's `evals/` (plan 2b Task 9): the same trace format, checks and fixture
names, with Delve's tools (`mcp__delve__…`, checked against `ToolHost.specs()`) and Delve's words (a *beat* is one go
of the table: the player's line and the DM's reply).

```
evals/
  trace.py      the Trace model: beats of ordered ToolCall(name, args, result) and Text
  checks.py     one function per rule, registered with @check("name")
  cases.py      case loading, fixture naming, the case's campaign set up through Delve's tools
  runner.py     the offline run over fixtures
  live.py       live recording through Delve's claude -p provider (opt-in)
  cases/<id>.json           scenario: sample module, setup calls, secrets, the player's beats, expectations
  fixtures/<id>/*.jsonl     transcripts of that scenario (stream-json)
```

## Running it

Offline is the default and costs nothing. It runs every fixture of every case and exits non-zero if a fixture doesn't
come out as its name says:

```sh
make evals                                          # all cases: uv run python -m evals
uv run python -m evals --case locked_door           # one case
uv run python -m evals --case locked_door --fixture some-transcript.jsonl
uv run python -m evals --list
```

`tests/test_evals_offline.py` runs the same thing, so `make ci` covers it.

**Live** mode plays a case's beats through the real `claude -p` and records the stream as a new fixture, then reports
the checks on it and, per beat, the time to the DM's first words (the first `TextDelta`), the total time and the tool
count. It spends tokens and takes minutes, so it only runs when asked: `make evals-live`, `--live`, or
`DELVE_EVAL_LIVE=1`. The tests never run it.

```sh
make evals-live                                     # every case
make evals-live EVAL_ARGS="--case locked_door --compare-ttrpg2"
uv run python -m evals --live --case goblin_ambush --model sonnet --effort low
# → evals/recordings/delve/goblin_ambush/recorded-YYYYmmdd-HHMMSS.jsonl
```

What live mode does, so that it never touches real play:

- Makes a temp data dir. `reference.db` is copied from yours (`DELVE_DATA_DIR`, read only) when it is current, or
  built from `reference/snapshots/`.
- Imports the case's sample module from `tests/fixtures/samples/scenarios/`, starts a campaign on it with the seeded
  house rules, runs the case's `setup` calls through the tool host and plants its `secrets` with `dm_note`.
- Serves that Delve on a free loopback port (never 5000, 7777, 7790, 8000 or 7810), for `delve dm-bridge`.
- Plays each beat as the play screen does: it opens a beat, sends the player's line to
  `delve.dm.claude_cli.ClaudeCliProvider`, and records the `DMEvent`s. The DM is isolated as in play:
  `--strict-mcp-config` with only Delve's bridge, no built-in tools, no settings or slash commands, and its working
  directory in `<temp data dir>/dm/<campaign>/`. A beat with `"ask": true` goes to Ask the DM
  (`delve.play.ask.ask`).
- Deletes the temp data dir afterwards (`--keep-data` to inspect it).

Options: `--model`, `--effort` (`auto` by default, ttrpg2's heuristic), `--keep-data`, and the campaign's play settings: `--tone`
(one of the tones, `classic` by default) and `--xp` (what earns XP, comma-separated, `none` for nothing), over the
case's own `play_settings`. The DM's prompt is built from them as in play, so the same case played twice with
different settings shows what a setting changes (DEL-315: `tone_and_xp`, `xp_awards`):

```sh
uv run python -m evals --live --case tone_and_xp --tone grimdark --xp gold
uv run python -m evals --live --case xp_awards --xp milestones
```

**`--compare-ttrpg2`** is the eval gate of spec §6.2. It also plays the same player lines through ttrpg2's own live
mode, on ttrpg2's case of the same id (`locked_door`, `goblin_ambush`), with ttrpg2's interpreter, inside its checkout
(`--ttrpg2 PATH`, default `~/claude/ttrpg2`). ttrpg2 is only read: its recording goes to `evals/recordings/ttrpg2/`
(not in git), its own checks report on it, and the two runs' timings are printed side by side. Cases ttrpg2 doesn't
have, and Ask the DM beats, are Delve only.

## Fixtures

A fixture is the stream-json `claude -p --output-format stream-json` emits, one JSON object per line, with two
eval-only marker records. They keep ttrpg2's names, so its recordings parse too:

```json
{"type": "eval_meta", "case": "locked_door", "mode": "hand-written", "note": "..."}
{"type": "eval_turn", "index": 0, "player": "Pippa picks the lock."}
{"type": "assistant", "message": {"id": "m1", "content": [{"type": "text", "text": "Pippa kneels at the door."}]}}
{"type": "assistant", "message": {"id": "m2", "content": [{"type": "tool_use", "id": "t1", "name": "mcp__delve__skill_check", "input": {"character": "Pippa", "skill": "open locks"}}]}}
{"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "content": "{\"success\": true, \"needed\": 47}"}]}}
{"type": "assistant", "message": {"id": "m3", "content": [{"type": "text", "text": "The bolt draws back.\n\n(Look inside? Or fetch the others?)"}]}}
{"type": "result", "result": "..."}
```

Lines starting with `//` are ignored. A recording adds `eval_turn_end` (the beat's timings) and `eval_dm_error`
records, which the checks skip. Without `eval_turn` markers each `result` record closes a beat, and a Claude Code
session JSONL parses too (its player messages open the beats), so a real session can be checked with `--fixture`.

The file name is the expectation:

| Name | Must produce |
|---|---|
| `pass*.jsonl` | no findings |
| `violates-<check>*.jsonl` | findings from `<check>` and from no other check |
| anything else | reported, never failed |

A live recording goes to `evals/recordings/delve/<case>/` (not in git), never into `evals/fixtures/`, and a
`recorded-*.jsonl` is ignored even if it lands there. A recording is a measurement, not a gate. Once you have read one
and agree with what the checks say, copy it into `evals/fixtures/<case>/` as `pass-<what>.jsonl` (or
`violates-<check>-<what>.jsonl`) to make it a regression fixture.

## The cases

| Case | What it tests | Fixtures |
|---|---|---|
| `locked_door` | Pippa picks the lock of the crypt's warded iron door: die-first on `skill_check`; the ward's seal and what lies beyond stay out of the choices | `pass` and one `violates-<check>` per check |
| `goblin_ambush` | Bren fights three goblins through `setup_combat` → `combat_round` → `end_combat`, the loot through `award_treasure` | `pass` and one `violates-<check>` per check |
| `split_party_secret` | Pippa alone sees the vestry; Bren's choices name nothing only she has seen | `pass`, `violates-no_hidden_intel` |
| `ask_the_dm_rules` | Rules questions to Ask the DM, answered from the rules and the sheet: no module canon, no tool names | `pass`, `violates-no_hidden_intel`, `violates-no_meta` |

All four play "The Crypt of Saint Vellis", the sample module of the scripted session.

## The checks

| Check | Rule | Fails when |
|---|---|---|
| `die_first` | HC #1, #2, #4; treasure in #8 | a beat with `expect.roll` has no call to one of its `tools`, or one of its `outcome` regexes matches narration emitted before that call |
| `combat_pipeline` | HC #8, Combat Procedure | `combat_round`/`resolve_attack` with no `setup_combat`; an `hp` patch through `update_character` while a fight is live; `apply_damage` in a fight with no roll since the last one; a fight ended with zero resolutions; an `expect.combat` beat with no resolution; an `expect.combat_ends` beat that leaves the fight live |
| `no_hidden_intel` | HC #5, "leaking through the choice menu" | the end-of-beat choices (trailing `(…?)`, a trailing option list, or a closing question) contain a case secret's `terms`, the case's `hidden_terms` or the beat's `expect.hidden_terms`, a 4-word run of any DM-only string seen in a tool result (under `dm_only`, the other keys the players' filter always drops, or the tool's `dm_only_keys`), or a "hidden door"-style phrase. For an Ask the DM beat the whole answer is checked |
| `pacing_line` | Pacing a Beat | the text before the first tool call is more than one line, more than two sentences or 300 chars, or names dice or tools (a missing opener is not flagged) |
| `no_meta` | the fourth wall | in-fiction narration mentions `mcp__`, system reminders, task tools, tool calls, `pre_turn_check` or a snake_case tool name; `(ooc…` beats are exempt |
| `no_state_bypass` | Module canon, Session Start | a call to any tool outside `mcp__delve__` (Delve's DM has no file tools, so Read, Bash or another MCP server is a bypass) |

Calls inside `batch` count as calls in their own right.

These are cheap rules, not a judge. `die_first` only knows the outcome phrases the case lists; `no_hidden_intel` only
knows the terms the case lists and the DM-only text the tools returned.

## Adding a case

1. Write `cases/<id>.json`:

   ```jsonc
   {"id": "council_vote",
    "description": "Three NPCs with conflicting interests vote on the party's plan.",
    "module": "crypt-of-saint-vellis",                 // under tests/fixtures/samples/scenarios/
    "setup": [{"tool": "create_character", "args": {...}},
              {"tool": "move_party", "args": {"to": "entry_hall"}}],
    "secrets": [{"text": "...", "tags": ["motive"], "related_to": "...", "terms": ["bribe"]}],
    "hidden_terms": ["..."],
    "checks": ["die_first", "no_hidden_intel"],       // optional; default: all
    "beats": [{"player": "I put the plan to the council.",
               "expect": {"roll": {"tools": ["council", "reaction"],
                                   "outcome": ["\\b(?:agree|approve|vote yes)\\b"]},
                          "hidden_terms": ["..."]}},
              {"player": "What does a reaction roll depend on?", "ask": true}]}
   ```

   `secrets` are planted with `dm_note`, so live play sees them through `dm_secrets`. Every `term` must occur in its
   secret's text, and every setup call must pass the tool host (the tests check both). `expect.roll` may be a list
   when a beat owes several rolls.
2. Add at least `fixtures/<id>/pass.jsonl`. Hand-write it with Delve's tool names and real result shapes, or record
   one with `--live` and rename it after reading it. The tests check every `mcp__delve__` call against the tool's JSON
   Schema.
3. Run `uv run python -m evals --case <id>` and `uv run pytest tests/test_evals_offline.py`.

## Adding a check

1. In `checks.py`:

   ```python
   @check("no_pre_roll_odds")
   def no_pre_roll_odds(case, trace):
       """HC #7: no success chances quoted before the roll."""
       out = []
       for i, beat in enumerate(trace.beats):
           ...
               out.append(Finding("no_pre_roll_odds", i, "quoted odds before rolling"))
       return out
   ```

   Read per-beat expectations with `_expects(case, i)`; walk `beat.events` (in order) or `beat.tool_calls`;
   `call.steps()` expands a `batch`.
2. Add `fixtures/<case>/violates-<check>.jsonl` that breaks only this rule, and make sure some `pass*.jsonl`
   exercises it cleanly. `tests/test_evals_offline.py` fails until every registered check has both, and until
   `locked_door` and `goblin_ambush` each have a `violates-<check>.jsonl`.
