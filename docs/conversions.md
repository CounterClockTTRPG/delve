# Converting a PDF

A module's PDF becomes a module in the background, from New module's **From a PDF**. There are two ways
(design: `docs/superpowers/specs/2026-10-23-thorough-conversion-design.md`; plan:
`docs/superpowers/plans/2026-10-23-thorough-conversion.md`).

- **Thorough** (the default): agents on the Claude CLI work in a lasting job folder, `<data dir>/conversions/<id>/`.
  They sort the book into its parts, clean every text against the page images, trace every map from the book, join
  the levels and describe the pictures. The run ends with a list of doubts and the cost. It takes hours for a big book
  and costs much more than Quick. It runs on Preferences' **Thorough conversion** job (`conversion.thorough`, Opus at
  high effort by default), which must be the Claude CLI.
- **Quick**: today's conversion, unchanged. The text is converted in one pass, and the maps are sketched from the room
  keys, then drawn again from the book's map pages as drafts when **Draw each map from the book's map page** is
  ticked.

## How a thorough conversion works

The job runs ten stages in order (`delve.conversions.thorough.pipeline`). Each stage, and each piece of a stage, is
recorded in the job folder's `state.json` when it is finished, so a resume skips it:

1. **Reading**: the PDF's pages and text layer, rendered into `pages/` at 150 dpi, and the map and picture pages into
   `scan/` at 200 dpi.
2. **Classifying**: map, picture and text pages (`classes.json`), as Quick does.
3. **Drafting**: Quick's text conversion, one draft per text in `draft/`.
4. **Sorting** (one agent, piece `sort`): the book's parts (levels, areas, chapters) and their key patterns and maps in
   `parts.json`; one draft and one keys file per part.
5. **Cleaning** (piece `clean-<n>` per group of parts with at most 25 pages of text): every text checked against the
   page images, with the checker, into `clean/`. Text that belongs to another group's parts goes to an orphans file,
   and the `sort-orphans` piece places it.
6. **Tracing** (piece `trace-<map>` per map in `parts.json`): each map traced from its scan into `maps/<map>.dmap`,
   rendered and compared with the scan, with an exits file. A part with keyed rooms and no map in the book gets a
   sketch, which is a doubt.
7. **Joining**: the exits joined into `exit` statements (`delve qa join`); a guessed landing is a doubt.
8. **Describing** (piece `describe`): the book's pictures, cut whole from their pages, described with when to show
   them, and their audience.
9. **Entities**: Quick's entity step, on the cleaned texts.
10. **Making**: the module, in one transaction; then the folder is removed.

At most four agents run at once. A piece gets three attempts in all, counted across resumes. A piece that still fails
is skipped and becomes a doubt: a skipped clean keeps its sorted draft, a skipped trace gets a sketch. An agent's doubts
are `doubts/<piece>.json`, gathered by code.

**The folder** `<data dir>/conversions/<id>/` holds `book.pdf`, `pages/`, `scan/`, `draft/`, `clean/`, `maps/`,
`joined/`, `art/`, `ref/` (the map language's docs and three reference maps), `doubts/`, `work/<piece>/` (each agent's
scratch) and Delve's own records (`state.json`, `book.json`, `warnings.json`, `drafted/`), which the agents may read
but not change.

**The tools** are `delve qa` (`delve.conversions.qa`): `pages`, `keys` (with `--out` for a long answer), `textcheck`,
`rotate`, `tile`, `mapcheck` (parse, validate, SVG and a PNG drawn without a browser) and `join`. The agents run them
through the wrapper `<data dir>/bin/qa`, which is outside every job folder and is written afresh for the running Delve's
Python before each session. Every path they are given must be inside the folder, or the command exits with code 2.

**Confinement** is the Claude CLI's own permission rules (`delve.dm.claude_cli.agent.agent_settings`), not an OS
sandbox:

- each agent runs with the job folder as its working directory, the tools Read, Write, Edit, Glob, Grep and Bash, no
  MCP server, no slash commands, no user settings and no session transcript (`--no-session-persistence`);
- Write and Edit are allowed in the folder only, and never on Delve's records;
- Read is denied on the data directory beside the folder, the repository, the home directory and the system
  directories;
- Bash runs the `qa` wrapper and nothing else;
- WebFetch and WebSearch are denied.

The agents can't delete files, so the briefs have them empty a file instead (an emptied orphans file counts as
placed). A long command output is kept by the CLI outside the folder, where the agent can't read it, so the briefs
send long answers to a file (`qa keys --out`).

The first real run, U1 *The Sinister Secret of Saltmarsh* (38 pages, 7 maps), is reviewed in
`docs/review/2026-10-23-thorough-conversion-u1.md`. It took 55 minutes of running, spread over three usage-limit
windows, and cost $23.24 measured, about $34 with the sessions its test stops cut short.

## The form

- **How thorough**: *Thorough (default)* or *Quick*, each with its hint.
- When a thorough conversion can't run, *Thorough* is disabled with the reason, and *Quick* is chosen. That happens
  when `claude` isn't installed, or when Preferences chose another provider for Thorough conversion.
- The book-maps checkbox is shown for Quick only, because tracing the book's maps is part of Thorough.
- *Ready to play* / *A draft to work on* is offered for both.

## Progress, pause and resume

- **Progress** shows the stage ("Step 5 of 10 · Cleaning the texts against the pages") and the pieces done in it (12 of
  34 batches of texts, 9 of 26 maps). It also shows the time since the start and the cost so far.
- **Paused.** A thorough job is never `failed`. In these cases it is `paused`, its folder kept:
  - Delve stopped while it ran.
  - The Claude usage limit was reached. It resumes by itself a minute after the limit resets.
  - An error outside a piece. The error is shown, so it can be resumed after a fix.

  The paused job shows its stage, the reason, the cost so far and **Resume**. A resume starts at the first unfinished
  piece. Finished pieces are never run or paid for again.
- **When Delve starts**, every job that Delve's stop paused goes back in the queue, which starts the oldest unless
  the queue is paused. A job paused at the usage limit gets its resume scheduled again for its reset time; one paused
  on an error or by hand waits for Resume. A job folder that no paused or queued job owns (its job done, cancelled
  or failed, or its row gone) is removed then.
- **The cost** shown is what the sessions measured. A session stopped before its end (timed out, paused, Delve
  stopping) reports no cost, so the doubts then end with "Cost incomplete: N sessions stopped…", their tokens and
  an estimate at the job's own rate (its cost per token so far).
- **Cancel** asks first, because it deletes the job folder and all the work done so far.
- A paused job holds no slot: another conversion may start beside it.

## The queue

One conversion runs at a time (owner addition 2026-10-23: the queue is visible, and conversions can be paused and
run later, at night when nobody plays).

- **A book uploaded while a conversion runs** is `queued`, Thorough or Quick, and starts by itself when the running
  one ends, is cancelled or pauses. The oldest queued conversion starts first. A queued conversion keeps its book in
  `<data dir>/uploads` until it starts, so the queue survives a restart; a thorough one gets its job folder when it
  starts. Other jobs (a request, a novel, a map's draft) are still refused while one runs.
- **Resume** puts a paused conversion back in the queue: it starts at once when nothing runs, else when its turn comes.
- **Pause** (a running thorough conversion only) stops its agents now. The pieces they were working on count neither
  as done nor as a failed attempt and are started over at the resume; nothing finished is paid twice. The job is
  paused "by the organiser", its folder kept, and the next queued conversion starts. A quick conversion can't be
  paused.
- **The queue's switch**, *Pause the queue* / *Unpause the queue*: while the queue is paused no queued conversion
  starts, and no paused one resumes by itself (a job paused at the usage limit, or stopped by Delve, waits in the queue).
  A running conversion runs on unless it is paused by hand. The switch is stored, so it stays as it was after a
  restart.
- **The Conversions panel** on New module lists the running, queued and paused conversions in that order, each with
  its status, step, place in the queue or reason, and cost so far, with Pause, Resume and Cancel (which asks first),
  and the queue's switch.

## Doubts and the cost

When a thorough conversion is done, the module's page shows **Doubts from the conversion** under the questions from
making it. The cost of the job is shown beside the heading. Each doubt gives:

- its part (a text or a map);
- its pages, linked into the original PDF at that page (`…/assets/source-pdf#page=n`);
- its kind (`docs/data-dictionary.md`, `conversions.questions.doubts[].kind`);
- what is uncertain.

The doubts are the organiser's own. **Tell the DM** writes them into the module's DM-only text "Notes from making this
module", under "Doubts from the conversion", which the DM reads with the module.

## The API

Every route below is for organisers.

| Route | Answer |
|---|---|
| `POST /api/conversions/pdf?title=…&mode=ready\|draft&thorough=true\|false&book_maps=…` | 202 with the conversion. `thorough` defaults to `true`. A thorough start that can't run is 409 `{"error": <reason>, "code": "thorough_unavailable"}`, and no book is taken in. `book_maps` is Quick's only. |
| `GET /api/conversions/options` | `{"thorough": {"available": bool, "reason": str \| null}}` |
| `POST /api/conversions/pdf` while a job runs, or with the queue paused | 202 with the job, `queued`. |
| `POST /api/conversions/{id}/resume` (JSON body) | 202 with the job, `running` when nothing ran, else `queued`. 409 for a job that isn't a paused thorough job, or whose folder's state can't be read. 404 for an unknown id. |
| `POST /api/conversions/{id}/pause` (JSON body) | The job, `paused` (`paused.reason` "paused by the organiser"). 409 for any job but a running thorough one. 404 for an unknown id. |
| `GET /api/conversions/queue` | `{"paused": bool, "jobs": [conversion…]}`: the running job, then the queued ones oldest first, then the paused ones. |
| `PUT /api/conversions/queue` `{"paused": bool}` | The queue, as `GET` gives it. Unpausing starts the oldest queued job when nothing runs. A `conversion-queue` event, `{paused}`, tells the other browsers. |
| `POST /api/conversions/{id}/cancel` (JSON body) | The job, `cancelled`. A thorough job's folder is deleted. |
| `POST /api/conversions/{id}/tell-dm` (JSON body) | The job's entry, as `GET /api/modules/{id}/questions` gives it, `told: true`. 404 for a job without doubts, or whose module is gone. |
| `GET /api/modules/{id}/questions` | `[{conversion_id, questions, remarks}]`. A thorough job's entry also has `doubts`, `told` and `cost_usd`. |

The conversion JSON has `thorough` (bool) and `paused`, which is `{reason, resets_at}` for a paused job and null
otherwise. The `conversion` event is `{id, status, step, done, total, steps, cost_usd}`.

## Tests

- `tests/web/test_conversions_api.py`: the API, with the fake agent (`tests/fakes/fake_claude_agent.py`) on `PATH`.
  The app's agent runner (`run_agent`, with the `conversion.thorough` choice) runs it for real in the job folder.
- `tests/conversions/test_queue.py`: the queue's order, the start when the slot frees, the switch across a restart,
  and the pause by hand that spends no attempt and no cost twice.
- `web/e2e/thorough-conversion.spec.ts` (`make e2e-browser`): the form, the pause at the usage limit, Resume, a
  second book queued behind it, the pause by hand, the queue's switch, the
  module with its traced map, its doubts and its cost, and Tell the DM. It runs against the fake play server, whose
  `claude` hands every agent session to the fake agent.
