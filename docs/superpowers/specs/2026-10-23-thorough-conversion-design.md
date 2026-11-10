# Thorough conversion: a PDF module as good as a hand QA pass, from the GUI

Date: 2026-10-23. Status: design. A project of its own, on master (c438368 and later).

## Intent

A PDF module converted in the GUI is poor: **the maps are invented and the text is jumbled** (owner, 2026-10-23). The
same module is very good after a QA pass done by hand in a Claude session, as done for Dark Clouds Gather, Reptile God,
Puppets and Greyhawk Ruins (2026-10-22/23). The owner wants the GUI to convert to that quality **by default**, and
accepts that it is much slower and much more expensive.

Why the two differ today:

- The GUI (`conversions/runner._convert_pdf`, `modules/books/convert.convert_book`) converts each chunk of the PDF's
  **text layer** in one Claude call with no tools. It never looks at the page images while converting text, and
  nothing checks the result against the book. A room's text runs into the next room, level or text, and OCR errors
  stay. A text with no matching map page gets a map **sketched from its room key** (`_sketch_maps`, invented), and
  the book-map drafts (`dungeon_maps.draw_book_maps`) are single-shot vision drafts the organiser must keep by hand.
- The hand QA ran **agents with tools** in a work folder. They treated the page images as the truth, re-ran a checker
  until each flag was explained, traced every map from its scan with a rotate / tile / trace / render / compare loop
  (at least two compare rounds), joined the levels by their stairs, and described the pictures. A lead agent sorted
  room keys into levels first and applied everything at the end. The Greyhawk Ruins QA is the reference:
  `/home/raf/claude/qc/greyhawk-ruins/` (briefs in `gr/brief/README.md` and `gr/text/README.md`, the agents' prompts
  and reports in `notes/`, the tools in `gr/scripts/`, `gr/text/textcheck.py`, `gr/join_exits.py`,
  `gr/apply_texts.py`, `gr/apply_all.py`). Those tools are written for that one book (W/P/Z keys, its page ranges, its
  paths) and must be made general.

The new mode turns that QA pass into a conversion Delve runs itself.

## Owner decisions (2026-10-23)

1. **Thorough is the default** for a PDF upload. It is slower and more expensive, "but necessary".
2. **It runs straight through.** It never stops to ask. Its doubts go in a **list** shown at the end.
3. **No spending limit.** It finishes whatever it costs, and **shows the cost at the end**.
4. **It can be resumed.** A long module takes hours, so the job must survive a Delve restart, a reboot or the usage
   limit and pick up where it stopped.
5. **Only new uploads.** No "redo properly" action on modules already converted.
6. **Its own Preferences entry**, "Thorough conversion" (job `conversion.thorough`, named like `image.portrait`), **default Opus at high effort**.
   The owner thinks the model may be a big part of why the in-CLI QA is better than the GUI (which runs `conversion`,
   default Sonnet at medium). It is a Claude CLI choice only; its cost is the job's `cost_usd`.
7. **Play gets no priority.** A thorough job runs at its full number of agents even while a campaign is played; the
   owner accepts that it shares the Claude usage limit with the DM.
8. The owner accepted the playbacks: text complete, in the book's order, in the right level and text, with OCR fixed,
   the page images being the truth; maps traced from the book wherever it prints one; the doubts list naming pages;
   resume at the first unfinished piece, never redoing finished work.

## Goals

- **The PDF form** gets a choice of conversion: **Thorough** (default, ticked) or **Quick** (today's conversion,
  unchanged). The hint under Thorough says it takes long (hours for a big book) and costs much more, and that it
  needs the Claude CLI provider. When the Claude CLI isn't available for the `conversion.thorough` entry
  (Preferences), Thorough is shown disabled with that reason and Quick is chosen. Draft / ready mode and the book-maps checkbox stay; with
  Thorough the book-maps checkbox is hidden, because tracing the book's maps is part of it.
- **The texts** come out as the hand QA left them (the form in `gr/text/README.md`, made general):
  - each level, area or chapter of the book in its own text, in the book's order;
  - every room key a level-2 heading `## <KEY>. <optional title> {#<key lower case>}`, one heading per key, in the
    book's order, with the book's key spelling (OCR'd keys fixed);
  - the first paragraph that the book prints as the players' description is a `>` blockquote;
  - ranges and shared entries split so every room links (`Z130-Z133` → one heading each; `Z518 and Z519` → `Z519`
    says "As Z518."; an area note over a range → an unkeyed heading, then the keys);
  - nothing lost, nothing added, nothing reworded; numbers in stat lines and tables checked against the page image;
    text that belongs elsewhere moved there.
- **The maps**: every map the book prints is traced from its page into a `.dmap` (`docs/maps/dsl*.md`), as the
  tracing brief does (`gr/brief/README.md`, made general): rooms where the book puts them, sizes and shapes, corridors,
  doors and secret doors, stairs, the book's room numbers as room names (`room "w539"`, label as printed), the map's
  scale read from the page, rotated maps straightened, organic caves, renderer chosen to suit the book. Every keyed
  room links to its heading. Each trace is rendered and compared with the scan side by side at least twice, and
  fixed.
  - A page that holds several levels gives one map per level (as `dungeon_maps` already does).
  - **Levels are joined** by their stairs, chutes and shafts (`exit` statements), as `join_exits.py` does, made
    general. A landing it has to guess is a doubt.
  - **No invented map** where the book prints one. A text with keyed rooms and no map in the book gets a sketch as
    today, marked `SKETCHED` as today, and that sketch is a doubt.
  - World or region maps in the book (overland, not dungeon) are attached as pictures, not traced, as today. Tracing
    them is a non-goal here.
- **The pictures**: the book's illustrations are kept as pictures (whole, not cut into strips) with a description that
  says what they show as a player would see it and **when to show them** (the room key or the monster), with audience
  `gm` only when the picture gives away a secret (`notes/prompt-describe-greyhawk-illustrations.txt`). Junk crops (text
  strips, page furniture) are not attached.
- **Entities** (NPCs, monsters, items, pregens) are drawn from the cleaned texts with today's entity step, so they are
  keyed to the right rooms.
- **The doubts list**, at the end, on the conversion and on the module's page where today's questions are: each doubt
  names its part (text or map), its page(s) in the PDF, and what is uncertain. Kinds include: a key on the book's map
  with no text, a key in the text with no room on the map, a checker flag left with the reason, a map detail left out,
  a guessed stair landing, a picture placed without confidence, a sketched map. A doubt never stops the run. The
  doubts reach the DM as today's answered questions do (`MAKING_NOTES`) only if the organiser chooses; by default they
  are for the organiser.
- **Progress** shows the stages and, within a stage, pieces done out of pieces (texts cleaned 12 of 34, maps traced 9
  of 26), as `STEPS` does today, plus the cost so far.
- **The cost** of all runs of the job is added up (`cost_usd`) and shown at the end, next to the doubts.
- **Resumable**:
  - The job's work lives in a lasting folder under Delve's data directory (`<data_dir>/conversions/<id>/`), **never
    /tmp** (the Greyhawk Ruins QA lost a day's work in /tmp to a reboot).
  - Each stage, and each piece of a stage (one text cleaned, one map traced), is recorded as done once finished. A piece
    stopped halfway is started over.
  - A job stopped by a Delve restart, a reboot or the usage limit becomes **paused**, not failed (today
    `close_orphans` fails it). It can be **resumed** from the conversion's page, and resumes by itself when Delve
    starts. Resume starts at the first unfinished piece; finished work is never redone or paid for twice.
  - **Cancel** still exists; it deletes the work folder. A job that ends (done or cancelled) deletes its folder once the
    module is made, keeping only what the module holds.
  - The module is still made in one transaction at the end, as today: a paused or cancelled job leaves no module.
  - **Errors that aren't a stop** (my call, from decisions 2 and 4): an agent session that crashes, times out or
    returns no usable output is retried twice. A piece that still fails is **skipped and becomes a doubt**, and the run
    goes on; a cleaning piece that fails falls back to its sorted draft, a tracing piece to a `SKETCHED` map marked as
    a doubt. An error outside a piece (a bug in a stage, a failed Make transaction) **pauses** the job with the error
    shown, keeping the folder, so it can be resumed after a fix. A thorough job never ends as `failed` with its work
    deleted; only cancel deletes it.

## Non-goals

- Re-running on modules already converted (owner decision 5).
- Stopping to ask the organiser during the run (decision 2).
- A spending cap (decision 3).
- Thorough conversion on providers other than the Claude CLI.
- Tracing world/region maps from the book.
- Changing the Quick conversion.

## Anti-goals (a failure even if it works)

- **A map invented where the book prints one.** This is the owner's first complaint.
- **Text in the wrong room, level or text,** or text lost or added. This is the second.
- **Finished work lost or paid for twice** after a stop.
- An agent that touches anything outside its job's folder: Delve's database, other modules, the git repository, the
  network beyond Claude itself.
- A doubt hidden: every guess the run made is in the list.

## Constraints

- One conversion job runs at a time (`_open`). A thorough job holds that slot for hours, so other jobs (book-map
  drafts, novels, histories, world maps) wait or are refused while it runs; see "Left to the builder".
- The `claude` CLI is the engine. Delve already spawns it (`dm/claude_cli`): side calls with no tools
  (`argv.AUX_ARGS`), and the DM with an allow-list of tools. Thorough agents need file tools (Read, Write, Edit,
  Glob, Grep) and Bash limited to Delve's own tools, in the job's folder, with no MCP servers, no slash commands, no
  user settings (as `AUX_ARGS` does), and no network tools.
- **Confinement** (my call): the CLI's own permission rules, not OS-level isolation. Each agent's working directory
  is its job's folder; Write/Edit are allowed only there; Read/Glob/Grep are denied on Delve's data directory (other
  than the job's folder), the repository and the home directory; Bash is allowed only for Delve's tool commands, which
  check that every path they're given is inside the job's folder. The reference material the briefs cite (the map
  language docs, finished reference maps) is copied into the folder at the start. No WebFetch/WebSearch, no MCP.
- The QA tools become Delve tools, run by the agents: page rendering at 150 dpi and map-page scans at 200 dpi (pdf.py
  already renders), the text checker (keys from the text layer per level; coverage and foreign-word scores per key),
  rotate and grid-tile for tracing, the map check (parse, validate, fixdoors, render SVG), **a PNG render that needs
  no browser** (today `shot.mjs` uses Playwright, which a host install may not have), and the exit joiner. They must
  be general: key schemes differ by book (`W539`, `P309a`, `WB05`, `12`, `A3`, `33a`).
- Costs are reported per agent session by the CLI (`total_cost_usd` in its result) and added with `_spend`.
- Delve's code style and docs conventions (module docstrings that cite the plan, `docs/` updates, i18n keys in
  English and Dutch).

## How it works (decided)

The run follows the hand QA's order. Stages, each made of pieces that can be done and recorded one by one:

1. **Read**: the PDF's pages, text layer and OCR as today (`read_pdf`), and page images rendered into the folder.
2. **Classify**: map pages, picture pages, text pages, as today (`classify_pages`).
3. **Draft**: today's chunk conversion (`convert_book`'s texts step) gives the starting drafts, as it gave the hand QA
   its starting point.
4. **Sort** (one lead agent): finds the book's parts (levels, areas, chapters) and their key scheme from the map pages
   and the text layer; re-sorts every keyed section of the drafts into its part, normalises the headings, writes one
   draft per part and a keys list per part and per map, and the briefs for the stages below.
5. **Clean** (one agent per few parts, a few agents at a time): the text brief, page by page against the page images,
   with the checker, until every flag is explained. Pieces of text that belong to another agent's parts go to an
   orphans file; the lead places them.
6. **Trace** (one agent per one or two maps, a few at a time): the tracing brief, ending with the render-and-compare
   rounds and an exits file per map.
7. **Join**: the exits joined into `exit` statements (code, not an agent); guessed landings become doubts.
8. **Describe** (one agent): the book's pictures, cut whole from their pages, described with when to show them.
9. **Entities**: today's entity step on the cleaned texts.
10. **Make** the module in one transaction: texts, traced and joined maps (each keyed room linked), pictures, entities,
    the original PDF, the doubts.

The agents' final reports feed the doubts list; each agent writes its doubts in a fixed form (a JSON file beside its
output), so the list is gathered by code and not parsed from prose.

## Left to the builder

- The exact process model: agent sessions run by Delve (spawned `claude` with a prompt per piece) versus one lead
  session that runs sub-agents. Whichever is chosen, each piece must be recorded as done by Delve, so resume works
  from Delve's records, not from an agent's memory.
- How many agents run at once (the hand QA ran 3–6), and how pieces are grouped per agent.
- What happens to other jobs while a thorough job runs (queue them, or let some small kinds run beside it).
- Making the QA tools general: the key patterns, levels, scale reading, rotation.
- The no-browser PNG render (a Python SVG rasteriser, or Delve's own renderer to PNG).
- The doubts list's exact shape and where it shows on the module's page.
- How the usage limit is detected (the DM already treats it as a pause: commit 3d84715) and how soon a paused job
  retries by itself.
- Test fixtures: a small PDF (`tests/fixtures/pdfs.py`) and a fake CLI that plays the agents, so the stages, resume
  and cancel are tested without Claude; one real-Claude check on a short module (U1 Sinister Secret of Saltmarsh, used
  before) before delivery.

## Addendum: the queue, pause and resume by hand (owner, 2026-10-23)

The owner added a requirement during the build: **the conversion queue is visible, and conversion can be paused and
unpaused**, for example to run conversions at night when nobody plays. Ruling d1, option A: a pause switch on the
queue, with **no time window**.

- A PDF uploaded while a job runs is no longer refused: it is `queued` (a new status) and starts by itself, oldest
  first, when the running slot frees (a job ends, is cancelled or pauses). There is still one running job at a time.
  Quick jobs queue too; other kinds of job are still refused while one runs. This settles "what happens to other jobs
  while a thorough job runs" (Left to the builder) for books.
- A paused thorough job goes back in the queue when it is resumed (`resume` answers 202, `running` or `queued`).
  The start-up resume of the jobs Delve's stop paused goes through the queue.
- A running thorough job can be **paused by hand**: its agent sessions stop now, the pieces in progress count neither
  as done nor as a failed attempt, nothing finished is paid twice, its folder is kept, it is `paused` with the reason
  "paused by the organiser", and the next queued job starts. Quick jobs can't be paused.
- **The queue's switch** is one stored flag: while it is paused no queued job starts and no paused job resumes by
  itself; a running job runs on unless paused by hand. It survives a restart.
- New module shows a **Conversions panel**: the running, queued and paused jobs in order, with their status, step and
  cost, Pause / Resume per thorough job, Cancel (asking first), and the queue's Pause / Unpause switch.

The routes and values are in `docs/conversions.md` and `docs/data-dictionary.md`.
