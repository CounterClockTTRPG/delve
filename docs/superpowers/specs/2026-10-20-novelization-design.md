# Novelization: a module or a campaign told as a story

Date: 2026-10-20. Status: design. This is a project of its own, beside portraits and images, built after the settings
quest is delivered. It uses the post-settings names: **Preferences** is the install's options page, and "Settings"
means game worlds.

## Intent

The owner wants to turn a module or a campaign into a story to read. They choose its length and its tone, and can give
the writer instructions ("tell it from Z's point of view", "leave out the fights on level 2"). The story is read in
Delve and exported as a PDF.

- **A campaign** is retold from what was played: the beats, the DM's narration, the NPCs' lines and the players' acts.
- **A module** that nobody has played becomes a tale of a party going through it, along the module's rooms, NPCs and
  events.

The word in Delve is **novel**: the story is the play story already. The action is **Novelize**.

## Owner decisions (2026-10-20)

1. **Two sources:** a module, or a campaign.
2. **A module's novel is a party's run through it**, typically. It is not lore and not a summary of the book.
3. **Three lengths:** a **recap** (a few pages), a **short story**, and a **novella**.
4. **A tone** is chosen for each novel.
5. **Instructions** are free text, given before the novel is written, such as a point of view or something to leave
   out. They are optional.
6. **The novel is read in Delve and exported as a PDF.**
7. **The owner only.** Only the install's owner makes and reads novels, not organiser seats. So a campaign's novel
   may use everything: DM secrets, private acts, what was behind the doors the party never opened.
8. **A campaign novel also reads the module** the campaign plays, the rooms the party never reached included. The
   writer may foreshadow them, or show in an epilogue what the party missed, but invents no outcome for the party.

## Goals

- **Make a novel** from a module's page or a campaign's page (the owner's view only), with **Novelize**. The form has:
  - **Length:** recap, short story or novella.
  - **Tone:** Delve's tones (`delve.dm.prompt.TONES`). A campaign's novel defaults to the campaign's tone. A module's
    defaults to `classic`.
  - **Instructions:** a free-text box, optional.
  - **For a campaign, which sessions:** all of them by default, or a range of sessions.
  - **For a module, which revision:** the latest by default.
- **Writing runs as a job,** like a conversion. It shows its progress on the page, can be cancelled, and its Claude
  spend counts in `cost_usd`, as conversions' does. A job that is cut off (Delve stopped, Claude failed) ends as failed,
  with a clear message, and keeps whatever chapters it finished. **Continue** picks such a novel up again from its
  outline and its finished chapters (my call).
- **A source can have several novels**, for example a short grimdark one and a long heroic one. Each is listed under
  its source with its length, tone, the start of its instructions, its date and its status. A novel can be renamed and
  deleted. "Write again" makes a new novel with the same choices, filled into the form.
- **Reading:** a novel page with its title, its chapters and a table of contents. It is made to read well: a book-like
  measure and type, not the app's dense layout.
- **The PDF:** a print view of the novel (a title page, the chapters, page breaks between them), printed or saved as a
  PDF from the browser, as **Print the module** does. Delve gets no PDF library.
- **A campaign novel is faithful to the record.** Who was there, what they did, who lived and who died, and what was
  found are as they were played. The writer may compress, reorder for the telling, give thoughts and dialogue, and
  leave out what the instructions say to leave out. It invents no outcome the record contradicts. Dice and game terms
  (hit points, THAC0, rounds) don't appear in the prose.
- **A module novel follows the module.** The party comes from the module's pregens when it has some (`.dscn` version
  3). Otherwise the writer invents a party fitting the module's party size and levels from its details. The
  instructions can name the party instead ("Tenser, Robilar and Otis"). The places, NPCs, monsters and treasure are the
  module's own. The writer decides what happens.
- **Its language** is the owner's UI language (en or nl) by default, with a choice on the form.
- **Docs.** The glossary gets **novel** and **Novelize**. The data dictionary gets the new table. The README gets a
  paragraph.

## Non-goals

- Illustrations. A novel is text. Portraits and scene pictures in a novel are a later backlog item, once the portraits
  work is in.
- Editing a novel's text in Delve. The owner can rename or delete it, and write it again with other instructions.
- Showing novels to player seats, or sharing them at the table.
- EPUB, Markdown or other export formats.
- Novelizing a single session from the play screen while playing.

## Anti-goals

- **A novel reaching a seat.** Novels are DM-only material (owner decision 7). No seat route, no event a seat
  receives, no `.dscn` export, and no DM context carries one.
- **A novel changing the game.** Writing a novel reads the campaign or the module and never writes them: not the story,
  the characters, the DM's notes, nor the module.
- **A campaign novel that rewrites what happened.** A character who died in play is not alive in the novel.
- **A novel that reads like a session log:** "Beat 14. The party rolls initiative." It is prose.
- **A slow table.** A novel job never runs inside a beat, and never blocks play or the DM.

## Constraints

- Tests never run the real `claude` or the network: `FakeDM`'s `side_handler`, and the fake `claude` for the e2e.
- `make ci` green. The browser e2e makes a novel of a campaign with the fake writer, reads it, and opens its print
  view.
- Every novel route is owner only, for reads too: an organiser seat gets 403. This uses the `Owner` dependency that
  the portraits plan adds (`require_owner`: `principal.seat is None`), or adds it if novels are built first. A
  planted secret in `tests/web/test_fourth_wall_per_seat.py` shows that no seat, an organiser seat included, reaches
  a novel.
- Every UI string is in `en.json` and `nl.json`.

## How it is made (my calls, to confirm or overrule)

- **It is a job kind of the conversion runner** (`delve.conversions.runner`), kind `novel`, with its own steps. It
  inherits progress events, cancel, `cost_usd`, `close_orphans` and the rule of one job at a time. The UI says so when
  a conversion is running. The runner's module boundary may need loosening, since a campaign novel reads play data: the
  builder settles where the code lives so the import contracts hold.
- **Its Claude choice is a new Preferences job, `novel`.** Its default is the `claude-cli` provider at `sonnet`, like
  `conversion`.
- **It is written in steps:** an outline of chapters first, then each chapter with the outline and a running summary of
  the chapters before it. A novella is too long for a single call. The outline and each finished chapter are stored as
  they come, so a cut-off job keeps them.
- **Rough lengths:** a recap about 1,500 words in one chapter; a short story about 6,000 words; a novella about 25,000
  words. These are targets for the writer, not limits that are checked.
- **Its input for a campaign:**
  - the whole story of the chosen sessions, every audience included (private acts, `tell`s, the DM's narration);
  - the session recaps;
  - the characters and their fates;
  - the NPCs met;
  - the DM's secrets and notes;
  - the module revision the campaign plays (owner decision 8), the rooms never reached included.

  It doesn't use the raw `dm_log` tool stream. The builder decides how a long campaign is cut to fit, for example a
  summary per session first.
- **Continue** (for a failed or cancelled novel) starts a new job on the same novel: it keeps the outline and the
  finished chapters, rebuilds the running summary from them, and writes the rest. A novel is `writing`, `done`,
  `failed` or `cancelled`; the reader shows a partial novel with a note that it is unfinished.
- **Its input for a module:** the chosen revision's texts, key, NPCs, encounters, factions and pregens
  (`pinned_source`), with the read-aloud boxes.
- **Storage:** a new `novels` table (a migration, the next free number), with:
  - the source: a campaign or a module, its revision, and the session range;
  - the choices: length, tone, language and instructions;
  - the title;
  - the outline and the chapters, as Markdown;
  - the status, the job's id, `cost_usd` and the dates.

  Deleting a campaign or a module deletes its novels.
- **Where it shows:**
  - a **Novels** section on a campaign's page and on a module's page, with Novelize;
  - the reader at `/novels/:id`;
  - its print view at `/novels/:id/print`, outside the nav shell like `ModulePrint`.

## Left to the builder

- The prompts: the outline's and the chapters'. `dm.md` is not used; the writer gets its own prompt file, with
  the tone's text from `TONES`.
- How a long campaign or module is condensed to fit the writer's context.
- The steps' names and the chapter counts per length.
- The reader's and the print view's typography.
- How the title is chosen (the writer proposes one in the outline; the owner can rename it).
