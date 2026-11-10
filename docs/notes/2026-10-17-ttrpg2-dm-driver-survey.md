# ttrpg2's DM driver and `/play`: survey for plateau 2b

*From a read-only survey of `/home/raf/claude/ttrpg2` on 2026-10-17. Paths are ttrpg2's.*

## How `claude -p` is driven (`tools/dm_session.py`, 1686 lines)

**The command line** (`_build_args`, 1120-1160):

```
claude -p [--input-format stream-json]
  --output-format stream-json --include-partial-messages --verbose
  --allowedTools "mcp__ttrpg__*,Read,Write,Edit,Bash"
  --fallback-model sonnet --disable-slash-commands
  --exclude-dynamic-system-prompt-sections --system-prompt-snapshot off
  [--effort X] [--append-system-prompt …] [--resume sid]
```

- **Without `--system-prompt-snapshot off`,** a `--resume` replays the first system prompt and silently drops later
  addenda.
- **Not isolated.** There's no `--model`, no `--mcp-config` and no `--strict-mcp-config`. Claude Code's own tools and
  the user-scope MCP server in `~/.claude.json` (ttrpg2's, which points at the live campaigns) are loaded. Delve must
  isolate:
  - `--mcp-config` plus `--strict-mcp-config`;
  - `--tools` / `--disallowedTools`;
  - `--setting-sources ""`;
  - no file tools.

**The resident process** (`_Resident`, 1346-1420):
- **Measured cost:** a cold spawn takes about 3 s (5.81 s wall against 2.74 s of API time). A warm resident's first
  turn takes 4.78 s, and every later turn about 2.18 s, the same as the API time.
- **One turn** is one stdin line, `{"type":"user","message":{"role":"user","content":[{"type":"text","text":…}]}}`.
- **The turn ends** at the first `type=="result"` event.
- **Timeout:** 900 s.
- **Respawned** when the arguments would change (effort, addenda, a new session id) or the process has died.
- **If the browser goes away mid-turn,** the turn is drained to its `result` anyway.
- **One turn at a time,** under a single lock.

**Auto-reset:**
- **When:** the context passes 250k tokens. Measured: about 2.6 s at 42-66k, 3.0 s at 107k, 3.5 s at 150k.
- **Only at a safe boundary:** not during a fight.
- **What happens:**
  1. a hidden handover turn writes `_handover.md`;
  2. the next session starts with a rehydrate addendum ("call session_primer… continue seamlessly") plus that handover.

**Auto effort:**
- **Measured:** default effort took 252/191/124 s on a set of turns, `--effort low` 47/58/36 s. About 88% of the
  generated tokens are thinking.
- **The heuristic:** high effort in a fight, for long messages, for marker words (ambush, bargain, cast, negotiate,
  plan, sneak, trap…), or when two or more NPCs are named. Low otherwise.
- **Caveat:** low effort skipped the combat pipeline once.

**Addenda** (all appended to the system prompt, in this order):
1. rehydrate and handover;
2. tone (classic, grimdark, heroic, horror, comedic, custom);
3. detail level, 0-3 (3, "Open table", is not a fourth-wall override);
4. a violations addendum, off by default, injected once per finding to keep the prompt cache warm.

**Side passes** (`_AUX_ARGS`):
- **Flags:** `--model haiku --tools "" --strict-mcp-config --disable-slash-commands --setting-sources ""`.
- **Where they run:** cwd is the temp directory, with plain text output.
- **Why:** a full-weight call measured a ~72k-token prompt just to produce four suggestion chips.

## Mapping stream-json onto Delve's `DMEvent`

| ttrpg2 event | Keys | Delve event |
|---|---|---|
| `system` (init) | `session_id` | conversation id |
| `stream_event` → `content_block_delta` with `delta.type=="text_delta"` | `delta.text` | `TextDelta` |
| `assistant` → `message.content[]` of type `tool_use` | `id`, `name` (strip `mcp__<server>__`), `input` | `ToolCall` |
| `user` → `message.content[]` of type `tool_result` | `tool_use_id`, `content` (a string or `[{type:text,text}]`), `is_error` | `ToolResult` |
| `result` | `is_error`, `total_cost_usd`, `usage{input_tokens,output_tokens,cache_read_input_tokens,cache_creation_input_tokens}`, `duration_ms` | `Usage`, then `TurnEnd` |
| process EOF or crash | the return code and the stderr tail | `DMError`, then `TurnEnd("error")` |

There are two pitfalls:
- **Text arrives twice:** as deltas, and again as the full `assistant` text block. Skip the full block when deltas were
  seen.
- **Thinking blocks and `input_json_delta`** appear in the stream. Drop them.

## The prompt

- **ttrpg2's `CLAUDE.md`** is 678 lines, about 16k tokens. The DM procedure parts are:
  - Hard Procedural Constraints (6-39);
  - Turn Pacing (49);
  - Composite Tools (61);
  - Hidden State and the Fourth Wall (76-102);
  - Session Start (125);
  - the DM's Role through Lore (139-384);
  - Dice, Saves and XP (385-410);
  - Batching (411-427);
  - Reference Lookups (428+);
  - Narrative Detail (665);
  - Out-of-character (676).
- **Not DM procedure:** the Dashboard, Running the System, the dungml dependency, Tests, and the UI parts of
  Tactical Maps.
- **`session_primer`** carries the party's mechanics, which saves a `get_character` per PC, about 1.8k tokens each. In
  Delve, that's `primer`.

## `/play` (`dashboard.py`)

- **A turn:** `POST /play/turn` answers NDJSON, not SSE, read with `fetch` and `getReader`.
- **Recovery after a reload** goes through `/api/turn_state`, `/api/last_narrative` and `/api/history?before=&limit=`.
- **The redactor** (`_PlayStreamRedactor`, 7311-7460) is an allow-list:
  - Every event type is passed only in part:

    | Event | What passes |
    |---|---|
    | system | type, subtype and session_id |
    | result | its 10 keys |
    | `stream_event` | only text and message events |
    | assistant | text, and `tool_use` with `dm_only` redacted |
    | user | `tool_result`s matched to their tool |

  - **DM-only keys** are removed at any depth: `dm_only`, `secret_exits`, `hidden_annotations`, `secret_map_exits`.
  - **Bodyless tools:** `dm_secrets`, `dm_note`, `dm_secret_update`, `module_lookup` and `get_location` show only
    their name.
  - **A second layer:** the same rules run again in the page's JS.
- **On the page:**
  - the story, revealed per animation frame;
  - tool rows with summaries;
  - a thinking indicator with timer and tool count;
  - rotating lore facts;
  - suggestion chips;
  - cost on hover;
  - text-to-speech;
  - the party sidebar with HP rings and reordering;
  - a fog map dialog;
  - settings for tone, detail and effort.
- **Mobile:** the layout only stacks below 900 px; there is no phone layout.
- **Out-of-band questions:** there's no "Ask the DM". The only way is in-band, `(ooc: …)`.
- **A bug to avoid:** the players' map dialog labels `scope==='gm'` as "GM view" (6527).

## The eval harness (`evals/`, 1097 lines, with a thorough README)

- **Trace parsing** (`trace.py`) reads stream-json plus the markers `eval_meta` and `eval_turn`. It produces
  `Trace.turns[Turn(player, events=[ToolCall | Text])]`, and expands `batch` steps.
- **Checks** (`checks.py`):
  - `die_first`;
  - `combat_pipeline`;
  - `no_hidden_intel` (secret terms, hidden terms, and 4-word runs of `dm_only` strings);
  - `pacing_line`;
  - `no_meta`;
  - `no_state_bypass`.
- **Cases** are `cases/*.json`. Fixtures are `fixtures/<id>/{pass,violates-<check>}*.jsonl`.
- **Live mode** (opt-in) copies the code into a sandbox, writes an MCP config, and passes `--strict-mcp-config`. It
  disallows file tools unless asked, and runs one spawn per turn with `--resume`.
- **Porting to Delve:**
  1. change `MCP_PREFIX` (trace.py:31);
  2. change the hard-coded tool-name sets in `checks.py` (43-56);
  3. change `_touches_state`;
  4. check the batch step keys;
  5. keep `dm_only` as the result key;
  6. swap the sandbox and launcher for Delve's.
