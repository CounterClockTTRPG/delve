# Delve: one application for ttrpg2 and dungml

*Delve is the product's name (owner).*

*2026-10-17. Written from a conversation with the project's owner. Words in **bold** on first use are defined in
[`docs/glossary.md`](../../glossary.md); the glossary wins when this document and it disagree.*

Each decision is marked:
- **(owner)**: the owner decided it.
- **(call)**: the designer's call, open to correction.

Anything not marked here is left to the builder.

---

## 1. Intent

ttrpg2 (an AD&D 2e DM server with a Flask dashboard) and dungml (a map language, renderer, fog of war and editor)
both work well. ttrpg2 keeps the fourth wall and is fast. But they grew organically:
- two products with two authorization systems and a contract between them that drifts;
- a 12k-line dashboard;
- 190 tools;
- rules that live partly in prose.

The goal is **one new application**, built from scratch in this repository, that:
- keeps their principles and their tested behaviour;
- drops the historical cruft;
- gives a clean foundation for future features.

It also adds a few features: multiplayer, translation, a module editor, house rules, and PDF import and export. **(owner)**

It is a **personal product**. One person installs it and plays at home, alone or with friends on the LAN. Claude is always the
**DM**. **(owner)**

### Why the last rewrite failed, and what that means here

ttrpg3 (`/home/raf/roleplaying/ttrpg3`) was an earlier rewrite that stalled after two weeks:
- infrastructure ahead of play: Keycloak, Redis, Postgres, multi-tenancy, friends;
- an architecture staked on an untested idea, a firewalled narrator, which was reversed after a week;
- event sourcing that made play feel like a computer RPG;
- latency.

ttrpg2 already solves the problems ttrpg3 was meant to solve. **This design does not take over ttrpg3's complications.**
It takes over only one idea: separating the module from the campaign. **(owner)**

## 2. Goals, non-goals, anti-goals

**Goals**
1. One install, one process, one version. The game, the maps and the editors ship together. **(owner)**
2. A structure with clear internal boundaries. Four layers can be swapped (§5.2):
   - the DM provider;
   - the image provider;
   - storage;
   - rulesets and settings.

   **(owner)**
3. Play at least as fast as ttrpg2's `/play` today (§6.4). **(owner: speed is a hard requirement)**
4. The fourth wall is kept at least as well as ttrpg2 keeps it, with the step-1 fixes of 2026-10-17 built in from the start.
5. Multiplayer in **beats** with several screens. Players join and leave freely. The **host** can always continue alone. **(owner)**
6. Each player plays in their own language. **English is the base language** of everything stored. **(owner)**
7. A friendly **module** editor (§8), a **house rule** editor (§9), and campaign creation from a module. **(owner)**
8. Import and export modules (`.dscn`). A guided PDF import. Export a whole module to PDF. **(owner)**
9. Good on laptop and tablet. Usable on a phone, with a reduced screen. The editors are desktop only. **(owner)**

**Non-goals (for now)**
- Real identity management or online hosting. LAN only, but the design must not rule hosting out (§11). **(owner)**
- Rulesets other than AD&D 2e, and settings other than Greyhawk. Only the interfaces are built (§10). **(owner)**
- Terminal play, or MCP tools for a human. Play is web only. **(owner)**
- Migrating ttrpg2 campaigns. They finish in ttrpg2. Modules are converted one by one, by Claude, when wanted. **(owner)**
- A separate narrator, an auditor model, event sourcing, Keycloak, Redis, Postgres, plugin rule systems. **(owner)**

**Anti-goals: failure even if it works**
- It feels like a computer RPG: forms and menus where ttrpg2 had a permissive conversation. Character creation in
  particular stays conversational (§7.8). **(owner)**
- It is slower than ttrpg2.
- It leaks DM-only information to a player's screen.
- It rebuilds ttrpg3: infrastructure and abstraction ahead of play.

## 3. Who uses it, and how

- **The host** installs it on a laptop or desktop at home. Usually they play alone, running a whole party of several
  **characters**.
- **Friends** occasionally join from their own devices on the same Wi-Fi.
- **Devices:**
  - Laptop or tablet is the main way to play.
  - A phone is used now and then, with a reduced screen.
  - The module, map and house-rule editors are computer work. **(owner)**

A typical evening:
1. The host opens the app and picks a campaign, or creates one from a module. A new campaign gets a ruleset (AD&D 2e),
   a setting (Greyhawk), and house rules or bundles.
2. They ask in plain words for a party: "build me a 4-character party, include a mage with a pseudodragon familiar".
3. They play beats. Each beat, they type what the party does and Claude rolls, updates the map and narrates.
4. A friend may join halfway through: they scan a code, pick a name and a language, and take over a character.
5. The **session** ends with a recap.

## 4. What carries over, what is cut

The full review is [`docs/review/feature-review.md`](../../review/feature-review.md): the owner went through every ttrpg2 tool,
dashboard page and dungml tool.

**Cut:**
- strongholds;
- rations and torch bookkeeping;
- hirelings;
- rumors;
- `audit_session`;
- the separate combat map.

**Changed:**
- **Possessions:** one category for strongholds, houses, mounts, airships, domains and the like.
- **Setting and rules lookups** take a setting or ruleset parameter.
- **Spell loadouts** are structured.
- **Combat** happens on the map already in play.

**Must not regress:**
- the composite `batch` tool (speed);
- map updates, which must become reliable.

**Taken from ttrpg2**
- Reference data, rebuilt into the new app's reference store: `2e.db`, `rules.db`, `monsters.db`, `greyhawk.db`,
  `lore_facts.db`, encounter tables, OSRIC magic items, rules text.
- Domain code: `treasure.py`, `names.py`, multi-class XP.
- The fourth-wall discipline: the Hard Constraints in `CLAUDE.md` become the DM's system prompt and tests.
- The speed techniques of `tools/dm_session.py` (§6.4).
- The tests and the eval harness from 2026-10-17 (§13).
- The existing house rules in `global/house-rules/`. These are `general.md`, 23 homebrew items, races and classes, and they become tagged
  house rules (§9).

**Taken from dungml**
- The DSL, its parser, the renderer and its themes.
- Fog of war, `room_context`, `walk`, keyed doors and secrets, with their tests.
- The `.dscn` scenario package and its JSON Schema.
- The React map editor.
- The print view.
- The extraction tooling (PDF to map).

**Not taken from dungml:**
- projects;
- OIDC;
- multi-user accounts;
- the backend's own persistence;
- the root-mounted contract routes (`/maps/{external_id}/…`, `/campaigns/{external_id}/…`).

The new app owns its maps, so there is no cross-service contract left.

**How the code comes over (call):** the dungml `dsl` and `scenario` packages are copied into this repository, keeping their tests,
and become internal packages. There is no dependency on the dungml repo. dungml and ttrpg3 can carry on independently. The
new app has no compatibility duty towards them, except importing `.dscn` files.

## 5. Architecture

### 5.1 Shape

**One Python process** serves the API, the event streams, the built single-page app and the DM's tools, on one port. **(call:
FastAPI, as dungml uses)**

The **frontend** is one React + Vite + TypeScript app with these areas:
- **Play**;
- **Campaigns** (create, choose, players);
- **Modules** (library, editor, import, export, print);
- **Maps** (editor);
- **House rules**;
- **Settings**.

**(owner: the stack was agreed)**

Internal packages (names are the builder's; boundaries are the point):

| Package | Owns |
|---|---|
| `domain` | Plain data types for modules, campaigns, characters, beats and so on. No I/O. |
| `storage` | The repositories, behind interfaces. The only package that knows SQL (§12). |
| `rules` | The ruleset interface and AD&D 2e: dice, checks, saves, combat, treasure, XP, spells, encumbrance. |
| `setting` | The setting interface and Greyhawk: gazetteer, lore. |
| `maps` | The DSL, renderer, fog of war and map state (from dungml). |
| `modules` | The module format (`.dscn`), validation, import, export, PDF import, print. |
| `play` | Campaigns in play: beats, players, the DM turn loop, redaction of what each player sees. |
| `dm` | The DM provider interface and its `claude -p` implementation. The DM's tool surface. |
| `images` | The image provider interface and its implementations. |
| `i18n` | Translation of player input and DM output (§7.7). |
| `web` | HTTP routes, the event streams, auth (§11), serving the SPA. |

**Rule: dependencies point inward.**
- `web`, `dm` and `play` may use everything below them.
- `domain` uses nothing.
- `rules`, `setting`, `maps` and `modules` don't know about HTTP, Claude or SQL.

The builder should enforce this with an import-linter rule or a test.

### 5.2 The swappable layers (owner)

Each layer has one interface, one first implementation, and tests written against the interface.

| Layer | Interface (sketch) | First implementation | Later |
|---|---|---|---|
| DM provider | Start or resume a DM conversation for a campaign. Send a beat. Stream back text, tool calls and usage. Stateless side calls (translation, suggestions). | `claude -p` resident process, on the owner's subscription | the Anthropic API |
| Image provider | Generate an image (portrait, scene, possession) from a prompt and optional references, and return either a file or a portrait description to render. | Replicate, as ttrpg2 does today, and portraitgen for free portraits (below) | other services |
| Storage | One repository per area (§12). | SQLite through SQLAlchemy Core | Postgres, when hosted online |
| Ruleset, setting | Lookups and mechanics (§10). | AD&D 2e; Greyhawk | OSRIC, Forgotten Realms… |

**Choosing backends in Settings (owner).**

Settings choose the backend for each layer, and for the DM, the model per job. A campaign can override them.

| Job | Chosen in Settings |
|---|---|
| **DM:** the main narration and rules turn | provider (`claude -p` today), model, thinking effort (including ttrpg2's "auto" effort) |
| **Side passes:** translation, Ask the DM, action suggestions, image-prompt rewrites | provider, model (default: the small, fast one), effort |
| **Module conversion:** PDF to module, generated dungeons | provider, model, effort |
| **Images:** portraits, scenes, possessions | backend (portraitgen or a paid service), per image kind |

- A change takes effect at the next beat. For `claude -p`, that respawns the resident process, as ttrpg2 does when its
  arguments change.
- Each provider declares the models and effort levels it supports, so Settings only offers valid choices.

**portraitgen (owner: use it when credits shouldn't be spent).**
- **What it is:** `~/claude/portraitgen` (Gitea `raf/portraitgen`), a dependency-free JavaScript library that makes
  deterministic SVG portraits from plain-language requests ("a stout old male dwarf"). It has themes and render styles,
  and animated emotes including lip-sync.
- **How it's used (call):**
  - Portraits are rendered **in the browser** with its web component.
  - The server only stores the portrait's traits JSON.
  - So no Node is needed on the server at runtime, and portraits re-render at any size.
- **Choosing the backend:** the host picks per campaign, or per request, between portraitgen (free) and a paid service.
- **How it ships:** pinned to a commit of the Gitea repo, and bundled into the SPA build.
- **Later:** emotes, for example an NPC portrait that talks while the DM narrates its line.

## 6. The DM

### 6.1 How Claude is driven (owner: `claude -p`, behind the DM layer)

The `claude -p` implementation keeps what makes ttrpg2's `/play` fast (`tools/dm_session.py`):
- **One resident process per active campaign,** fed over `--input-format stream-json`. A cold spawn costs about 3 s.
  A warm process adds nothing beyond API time (measured in ttrpg2: about 2.2 s per turn).
- **A stable system prompt,** so the prompt cache stays warm. Addenda are injected only when they change.
- **Automatic reset at a safe boundary** (not mid-combat) when the context grows too large. The session is rebuilt from
  stored state via a primer.
- **Side passes run on a small, fast model with no tools:** translation, action suggestions, image-prompt rewrites.

### 6.2 What the DM can touch (call)

- **Tools:** the DM's only tools are the app's own, served to `claude -p` as an MCP server by the app process. The endpoint
  is localhost only and uses a per-process secret.
- **No file tools:** no `Read`, `Write`, `Edit` or `Bash`. ttrpg2 grants them today (`dm_session.py:630`) so the DM can read
  character files and maps. In the new app all state is in storage and reachable through tools, so the DM has no way
  around them.
  - **Risk:** this is a behaviour change. The eval harness (§13) must show it doesn't hurt play before plateau 2 ships.
  - **The gate (call):** a fixed set of recorded beats (exploration, a fight, a puzzle, character creation) is played live
    on both ttrpg2 and the new app, and the eval checks are compared. The new app must have no more violations.
  - **The fallback (call):** if play suffers, the fix is more read tools, not file access. The DM keeps its free-form notes
    through the kept note tools (`dm_note`, `note_room`, secrets), which are part of plateau 2.
- **Isolation:** `--strict-mcp-config`, so the owner's user-level MCP servers (for example ttrpg2's) are never loaded.

### 6.3 The tool surface

The feature review lists the capabilities to keep. The tool count goes down by merging, not by losing capabilities.
- **A guess, not a target to force:** around 40 tools.
- **Ids:** every result uses typed, stable ids.
- **Visibility:** results separate `perceived` (what the characters notice) from `dm_only`. That's ttrpg2's `room_context` pattern.
- **The composite `batch` tool stays,** with the same semantics as ttrpg2's. It is the main reason ttrpg2 is fast.
  **(owner: must not regress)**
- **Map updates are reliable** **(owner)**:
  - Moving the party, opening a door or revealing a secret goes through the same tool that updates the map state, so
    the DM can't forget to update the map.
  - Combat tokens are placed on the map in play when combat starts and removed when it ends.
- **The pre-turn check:** `pre_turn_check` is kept only if the evals show it helps. **(owner: unsure)**

### 6.4 Speed budget

**The owner's guideline:**
- The first words of the DM's reply appear on the screen **within 30 seconds** of a beat closing, and sooner is better.
- Beyond 30 seconds is danger territory.
- The only exceptions are very complex requests, such as "build me a complete 6-character party". Even then the screen
  shows progress: the typing indicator, tool activity, and the DM's one-line opener before its tool calls (ttrpg2's
  pacing line).

Measured on the owner's machine, against a recorded baseline of ttrpg2's `/play` on the same beats:
- **Time to first narrated token** on a simple beat (a move into a described room, no rolls): no worse than ttrpg2, and
  within the 30 s guideline on every beat of the eval set except the ones marked complex.
- **Total time** on a combat round with three combatants: no worse than ttrpg2.
- **Server-side work per tool call** (state read and write, redaction, map render) under 50 ms at the 95th percentile.

The builder adds a small benchmark that replays recorded beats against a fake DM, to keep the server side honest.

### 6.5 Hard rules, kept light (call)

ttrpg2's Hard Constraints, such as die-first, no re-rolls, combat through the pipeline, and the fourth wall, stay. Code enforces
them where that's cheap, and nowhere does it make play feel mechanical:

- **Dice:**
  - Every roll goes through the app's dice and is **logged** (notation, faces, purpose, actor, beat).
  - The RNG is seedable for tests.
  - Notation has limits, so `999999999d6` is refused.
- **No re-rolls in a beat:** a repeat of the same roll (same actor, purpose, target and combat round) within the same beat
  returns the stored result. The round is part of the key, so a beat that covers several rounds still rolls fresh each round.
- **Beats and combat rounds (call):**
  - Playing alone, a beat may cover several combat rounds when the player asks for it ("we fight until they're down").
  - With several players, each combat beat is one round, because everyone declares before initiative.
- **Combat** is a small state machine:
  - surprise (applied with correct odds);
  - initiative re-rolled every round;
  - attacks;
  - saving throws for anyone, monsters included;
  - morale;
  - end of combat.

  The DM has an "adjudicate" escape hatch for anything unusual (grapples, called shots, rulings). It is logged, not refused.
  The `test_known_bug_*` tests from ttrpg2 become tests of the correct behaviour.
- **Not taken over** from this morning's redesign: mandatory "receipts" on state changes, and the event log. Both are more
  structure than play needs.

## 7. Play

### 7.1 Beats (owner)

A **beat** is one go of the table:
1. The beat opens.
2. Each player present writes an action for any of their characters, or passes.
3. The beat closes when one of these happens first:
   - every present player has submitted;
   - the host or a co-host presses "go";
   - the **beat timer** runs out.
4. The DM gets every submission at once, in English, and resolves them together in one reply.

**Single-player play is a beat with one player:** submitting closes the beat at once, so there is no extra latency.

**Typing indicator (owner):** while a player types, the others see a per-player progress indicator. The states are
idle, typing and submitted.

**Beat timer (owner):**
- Optional, set by the host (for example 3 minutes). The time left is visible to everyone.
- When it runs out for a player, the host's chosen fallback applies:
  - **hold back:** the character does nothing this beat; or
  - **in character:** the DM plays a *cautious* action for them (keeps watch, follows the party; spends no spell or charge
    and starts no fight).

### 7.2 Players, joining and leaving (owner)

- **Joining:** the host's screen shows a join link and a QR code. A joining player picks a display name and a language, then
  takes over one or more characters or asks the DM to make one.
- **Leaving:** a player can leave at any time. Their characters then follow the host's fallback until someone takes them over.
- **The host:**
  - starts as whoever created or imported the campaign, and can hand the role to another player **(owner)**;
  - can always carry on alone;
  - can take over any character;
  - can make another player a **co-host** with the same table rights.
- **Observers (owner):** an **observer** sees the table and can talk in table talk (§7.3), but takes no actions and has
  no characters.
- **Seeing other players' characters (call):** every player sees the whole party's sheets.
  - Information a character found out on their own, such as a private vision, is shown only to that character's player.
  - The DM marks such output as addressed to one character.

### 7.3 Three ways to speak (owner)

The input box has three send buttons:

| Button | Goes to | Effect on the world |
|---|---|---|
| **Act** | the beat | The action is resolved by the DM in the beat. |
| **Table talk** | the other players and observers, like a chat | None. The DM doesn't act on it. |
| **Ask the DM** | the DM, out of band | None. Questions such as "what's a kobold?", "who was Gruumsh again?", "which level is fireball?". |

How **Ask the DM** works (call):
- It is answered by a side pass, not inside the beat, so it doesn't hold up the table.
- It answers from the rules, the setting, and what the asking player's characters know. It never draws on module canon
  or other DM-only state.
- It can't change state: its tool set is read-only.
- The answer goes only to the player who asked, unless they share it into table talk.

Table talk and questions are stored with the session, translated like everything else, and never sent to the DM as
actions.

### 7.4 A split party (owner: yes, if it's not too costly)

Characters can be in different places, for example one who fell down a chute in Stonehell.

**The map state (call):**
- It holds a **position per character** rather than one party position, and **discovery per character**.
- A player's map shows what their own characters have discovered.
- When characters meet again in the same place, their discoveries merge: they tell each other.
- While the party is together, this behaves exactly like a single party position, so solo play doesn't pay for it.

**Beats in a split party (call):**
- The DM resolves each group in turn within the beat, and narration addressed to one group goes only to the players whose
  characters are in it. This uses the same addressing as private information (§7.2).
- In single-player play, one player controls both groups and sees both maps, one at a time, with a switcher.

**Why from plateau 1:** this layout goes in from the start, because changing it after the first sessions would mean moving
stored map states and redoing the fourth-wall tests.

### 7.5 The fourth wall

What a player's screen receives is built on the server from an **allow-list**. That's the approach of the 2026-10-17 `/play`
redactor:
- no thinking;
- no tool inputs;
- no DM-only tool results;
- no `dm_only` fields;
- no hidden rooms or markers.

The rest of the fourth-wall design:
- **No DM view of a player's screen.** A player view can never be switched into a DM view through a parameter.
- **The map for players** is always rendered from the fog view of the campaign's map state:
  - markers that aren't in a discovered room are dropped;
  - when there is no map state, the screen says "map offline" and never falls back to the full map.
- **The DM view:**
  - It is a separate area for the host, for setup and fixing things, not for running the table.
  - It shows everything. Only the host can open it. A co-host gets it only when the host grants it explicitly **(call)**,
    because it shows every secret.
  - Even for the host it is a deliberate step: the host is also a player, and playing with the DM view open would spoil
    the game.

### 7.6 The play screen

- **Laptop and tablet:**
  - the story stream;
  - the input box with its three send buttons (§7.3), the players' indicators and the beat timer;
  - table talk and answers to questions in a side panel;
  - the map with fog, pan and zoom by touch, character portrait tokens and monster tokens in combat;
  - the party sidebar with marching order, changed with up and down arrows **(owner)**;
  - character sheets with HP, inventory, encumbrance and spell loadout (memorized and cast);
  - the images the DM has shown.
- **Phone:** reduced **(owner)**. The story and the input box, with the map and the party one tap away. No side-by-side
  panels. *(The exact layout is the builder's, within this.)*
- **Showing images:** the DM shows a module image (a handout, a puzzle) when it decides the moment is right, using the
  image's description. The image appears in the story and in an image gallery for the campaign.

### 7.7 Translation (owner)

- **Stored state stays English.** Modules, campaigns, rules, logs and the DM's own output are all in English.
- **Player input:** a player's input in another language is translated to English (a side pass) before it joins the beat.
- **DM output:**
  - The DM writes English.
  - For each language present other than English, a side pass translates the narration as it streams, and each player
    receives their own language.
  - Players reading English get the original with no delay.
  - **(call)** Narrating directly in the players' language was considered and rejected: it breaks "stored state is
    English" and gets messy with mixed languages.
- **The interface** (buttons, labels) is localisable. Its first languages are **English and Dutch** **(owner)**.
- **Glossary terms per language:** names from the module and game terms such as "saving throw" or "THAC0" follow a short
  per-language glossary, so translations stay consistent.

### 7.8 Characters (owner)

- **Creation stays a conversation.** The player asks in plain words, and the DM builds the characters (names, spells,
  equipment), permissively. There is no creation wizard and no form-driven limits.
- **House rules apply automatically:** the campaign's house rules tagged *character creation* (§9) reach the DM at that
  moment. The player doesn't have to repeat them.
- **Real rolls:** ability scores and HP are still rolled through the app's dice, so they are real and logged.
- **Level-up** works the same way, with the *level-up* house rules.
- **Structured data:** characters have structured inventory, encumbrance (computed from inventory), and a spell loadout:
  the default memorized spells, which are memorized now, and which have been cast. **(owner)**

### 7.9 Possessions (owner)

One category for things larger than an item: a stronghold, a house, a mount, an airship, a domain.
- They are owned by a character or the party.
- They all have the same create, read, update and delete operations, plus a generated portrait.
- They carry no management rules: stronghold management stays cut.
- **(plateau 6) One table:** `possessions`, with the kinds `mount`, `vehicle`, `ship`, `house`, `stronghold`, `domain`
  and `other`. A possession whose owner is deleted goes to the party.
- **(plateau 6) A mount's stats are used:** `{species, hp, hp_max, ac, mv, fly, thac0, attacks, morale}`, with ttrpg2's
  19 species' defaults (and the flying movement of the pegasus, hippogriff, griffon, giant eagle and giant owl). Its
  movement, or its flying movement, sets the pace of `travel` for its rider; a vehicle's or a ship's carries everyone.
- **(plateau 6) Portraits:** portraitgen draws only people, so a possession's picture needs paid images (§10.1).
- **(plateau 6) The fourth wall:** the players see the party's possessions, never their DM notes (`notes_md`).

## 8. Modules and the editor

### 8.1 What a module is

A module is written content: an imported published adventure, or one written in the editor. **(owner)**

The `.dscn` format (dungml `docs/scenario-format.md`, `scenario.schema.json`) already covers most of it:
- the metadata;
- Markdown text with keyed headings;
- maps;
- entities (NPCs, factions, quests, encounters…);
- keys that link rooms to text;
- assets with an audience.

**It is the module format of the new app (call).** It gets a version bump for these changes:

- **Attachments.** Any asset (an image, a reference PDF) gets a `description`: what it shows and when it fits. The DM
  reads it to decide when to show an image. There are no handout or puzzle kinds. **(owner)**
- **References from text:** Markdown refers to attachments and maps by id, for example `![…](asset:crypt-riddle)`.
- **Forms:** NPCs, encounters, factions and quests are structured entities edited as forms. Everything else is prose.
  **(owner)**
- **No house rules in a module.** House rules are separate (§9), but a bundle can be exported and imported on its own.
- **A module can be only a map.** **(owner)**

A module is canon: play never changes it. A **campaign** pins a **revision** of its module.
- Editing a module creates a new revision.
- A campaign moves to a newer revision only when the host asks.

(call; keeps play stable while the owner keeps editing)

### 8.2 The editor (owner: a light word processor)

- **Text:**
  - A toolbar for headings, bold, italic, lists, quotes (quotes are read-aloud text), links and tables.
  - The text looks finished while editing. Markdown is the storage format, and the owner never needs to see it.
  - **(call)** TipTap, with a Markdown round-trip that is tested on real modules.
- **Attachments:** an upload button adds a file with its description and places a reference at the cursor. An attachment
  panel lists them all.
- **Forms:**
  - NPC cards: name, race, class and level or HD, AC, HP, disposition, notes, portrait.
  - Encounters: monsters, numbers, where, conditions.
  - Factions.
  - Quests.

  Each form validates against the module schema.
- **Room links:**
  - **(call)** A heading like "12. The Crypt" links to room `12` on the module's map automatically. A small map chip
    shows the link.
  - Rooms on the map with no text, and text keys with no room, are listed as warnings.
  - No anchors to type.
- **Maps:** they open in the map editor (dungml's React editor, a screen of its own). **(owner)**
- **Metadata:** a form for the descriptive metadata of `scenario.schema.json`: title, authors, levels, party size,
  setting, system, tags, content warnings, cover.
- **Desktop only.** **(owner)**

### 8.3 Getting a module (owner)

A module bundles its text and its maps, so getting one is a single step, not "text here, maps there". There are three
ways in, all reached from "New module":

1. **Use a complete module as it is.**
   - It can be a `.dscn` file, or a PDF that is converted whole: text, maps when the module has them, images,
     NPCs, encounters, factions and quests.
   - Some scenarios have no maps, and that's fine.
   - The result is ready to start a campaign from. The owner can still open it in the editor later.
2. **Convert a PDF into a draft to work on.**
   - It goes through the same conversion, but lands in the editor as a draft revision.
   - The owner tweaks the story and the maps (in the map editor) before playing.
3. **Generate one from a request.** For example: "give me a dungeon; I don't care about plot, I just want to kill some
   kobolds".
   - The DM layer writes a small module: a map in the DSL, keyed rooms, encounters, treasure, and as much or as little
     story as was asked for.
   - The result validates like any module. It can be played at once or edited first.

**The PDF conversion** behind 1 and 2 is one pipeline, running in the background and showing its progress:
1. **Text extraction** with layout-aware reading order and an OCR fallback for scanned pages. ttrpg3's
   `modules/ingest.py` has a good version of this.
2. **Conversion to Markdown** through the DM layer, in chunks with stable anchors so a large book isn't truncated. This
   replaces what the owner does in a session today.
3. **Maps,** from the module's map pages, through the extraction tooling (dungml's `extract` work). Rooms are linked to
   their keyed text. Extraction also stays a tool that can be run on its own, for hard maps.
4. **Drafts** of NPCs, encounters, factions and quests.
5. **Images:** the pages or pictures that become attachments (handouts, illustrations), each with a description.

Where a step is unsure (a map that didn't extract cleanly, a room without text), the module carries a warning that the
editor lists.

**What "done" means for maps (owner):** imported maps are expected to need some work. Map extraction isn't hands-free:
it reads label sheets, needs corrections, and only works on gridded maps with a style kit. Plateau 5 is done when:
- a module without complex maps can be played straight after import;
- a module with complex maps arrives with clear warnings, and is fixed in the map editor.

Players can start as it is, or refine first.

**Other import and export:**
- **`.dscn`** import and export, validated against the schema. Assets are checked for type and size, and active SVG is
  refused. dungml's rules carry over.
- **One-off conversions:** existing dungml projects and Markdown modules are converted by Claude when wanted. There is no
  general importer for ttrpg2 data.
- **PDF export of a whole module:**
  - A print view in the style of dungml's map print page: text, maps, NPC and encounter blocks, images.
  - The PDF comes from the browser's print dialog. **(call)** A server-side PDF can come later if wanted.
  - DM-only material is included, since this is the module itself.

## 9. House rules (owner)

- **A house rule** is text plus tags.
  - **When it applies:** `character-creation`, `level-up`, `combat`, `items`, `behaviour`, `always`.
  - **What it's tied to:** a ruleset (for example OSRIC-only) or a setting (for example a tressym familiar is
    Forgotten Realms).
- **A bundle** is a named group of rules, for example "my usual table".
- **Choosing them:** the house rules and bundles are chosen when the campaign is created, and can be changed later by the host.
- **How they reach the DM (call):**
  - `behaviour` and `always` rules sit in the system prompt, which stays stable so the cache works.
  - Phase rules come back in the result of the tool for that moment. Creating a character returns the creation rules; a level-up
    returns the level-up rules.
  - A rule tied to another setting or ruleset is left out.
  - The DM never has to be reminded.
- **Custom items and races:** house rules that define an item or a race keep a text body. The DM treats them as reference
  data for the campaign.
- **Migration:** ttrpg2's `global/house-rules/` (general rules, 23 items, races, classes) is converted into this form once,
  as the owner's first bundle.
- **Editing:** a simple editor (desktop): a text box, tag chips, and bundle membership.

## 10. Rulesets and settings (owner)

- **Rulesets:** the game asks a **ruleset** interface for lookups and mechanics: classes, races, saves, THAC0, XP tables,
  spells, monsters, items, treasure tables, and rules text.
  - Rules lookups take the ruleset as a parameter.
  - AD&D 2e is the only implementation, built on ttrpg2's reference data.
- **Settings:** a **setting** interface answers places, deities, factions and lore. Greyhawk is the only implementation,
  from `greyhawk.db` and the lore facts.
  - **(plateau 6)** The Greyhawk wiki and ttrpg2's lore facts (without its `campaign` facts, which belong to ttrpg2's
    campaigns) are in the reference store. The setting gets its reference handle injected, as the ruleset does, and
    answers `setting_lookup` (by kind: place, realm, deity, character, organization, creature, item, plane, holiday,
    building, archfiend) and `setting_search`.
  - **(plateau 6)** The setting owns the calendar (§10.1).
- **World maps (call):**
  - A setting's world map is setting data. **(plateau 6)** No structured Flanaess map exists, only raster images, so
    Greyhawk ships ttrpg2's hand-made "Greyhawk region" map (`delve/setting/data/greyhawk-region.map`) as its one
    world map. A Flanaess backdrop image is in the backlog.
  - A module may bring its own world map; `.dscn` already has `worldmaps`.
  - The campaign holds the party's position and travel state on it.
  - **(plateau 6)** World maps are ttrpg2's `.map` language (`delve.maps.world`, `docs/maps/world-maps.md`). At campaign
    creation the module's world maps and then the setting's are copied into the campaign (the module's wins a name
    clash); after that the campaign owns them, and an organiser edits them on the campaign page. A module's map that
    doesn't read imports with the warning `worldmap-unreadable`.
- **Choosing them:** a campaign names its ruleset and setting. A module may name the setting it was written for, as the
  default.
- **Not now:** faithful OSRIC, Pathfinder, Ravenloft or Forgotten Realms implementations. The interfaces only need to
  make them possible.

### 10.1 The world in play (plateau 6; the designer, for the owner, 2026-10-18)

The owner left plateau 6's open points to the designer. These are the decisions taken
(`docs/superpowers/plans/2026-10-18-plateau-6-the-rest-of-the-world.md`, "Decisions taken for the owner"):

1. **`pre_turn_check` is not ported.** Its checklist is already in the DM's prompt. Its NPC-reaction diff and position
   come back from `party_status`, `room` and the primer.
2. **The calendar belongs to the setting.** Greyhawk uses the Common Year calendar: 12 months of 28 days and 4
   festival weeks of 7 days, 364 days ("4 Planting 576 CY"; a festival day reads "Richfest, day 4, 576 CY"). The
   campaign keeps `day` (an integer) and a start date (default 1 Planting 576). The date, the month and the season are
   derived, never set by hand: ttrpg2's `set_season` goes away. A campaign without a setting gets a plain calendar
   ("Day 12", four seasons of 91 days).
3. **Weather is one roll per day and terrain.** It is rolled the first time it is asked for on a day (`weather_check`,
   `travel`, the primer) and kept for that day. ttrpg2's tables move over unchanged; forest, hills, plains and ocean
   use the wilderness table, so every encounter terrain has weather. The weather's pace really slows travel, and a
   blizzard (pace 0) costs the day.
4. **Travel moves the party on the world map, day by day.** A day's miles are 2 × the slowest movement rate (or the
   mounts', or the vehicle's), × the terrain's rate, × the weather's pace. One encounter check is made per day: d6 = 1,
   or d20 = 1 in towns. A triggered encounter stops the journey there, partway along the route. Days pass in one place
   (`play/days.py`): `advance_time` past midnight, `advance_days`, a whole-party `rest` and `travel` each run the
   new-day hooks once per day crossed.
5. **Possessions are one table** (§7.9). A mount's stats are used: its movement (and flying movement) sets travel
   speed. ttrpg2's 19 mount species' defaults come over. Possessions have no management rules.
6. **Factions and quests come from the module.** They are seeded when a campaign is created (and for an older
   campaign on first use); a module upgrade adds new ones and never overwrites play state. Countdown clocks tick with
   the days. A progress clock (the `.dscn` `segments`/`filled` kind) moves only when the DM advances it; ttrpg2 treated
   segments as days, Delve doesn't.
7. **Players see what their characters know:** the date, the weather, known quests with their player-facing notes,
   known factions with a standing word ("Friendly"), the party's possessions, and the world map without hidden
   places. They never see clocks, faction notes, strength, the reputation number, `doc` notes on the map, or a quest
   not yet known.
8. **Lore:** the setting's lore is the Greyhawk wiki (`greyhawk.db`) and ttrpg2's lore facts, except its `campaign`
   facts. A campaign's own facts are a campaign table. While the DM thinks, the play screen shows a "Did you know"
   fact from the setting, never a campaign fact.
9. **The merchant's shelf goes to the DM only.** The DM narrates it. Buying pays from the party's coin.
10. **Images:**
    - **Portraits** default to portraitgen, free and instant: a description and a seed, drawn by the browser.
      portraitgen draws only people, so possessions and scenes need a paid backend.
    - **Paid images are off for each campaign until the host turns them on** (the play setting `paid_images`). With
      them off, a portrait falls back to portraitgen, and a scene or a possession's picture is refused with a hint.
    - **The Replicate token** comes from `REPLICATE_API_TOKEN` or `<data dir>/replicate-token` (mode 0600). It is never
      stored in the database and never sent to a browser. Replicate is offered in Settings only when a token exists.
    - **The DM writes the painter's brief itself.** For the host's "Paint this scene" button, a side pass writes it
      from the last DM narration.
    - **A picture never holds up a beat:** it is painted in the background and lands in the story when done.
    - Map tokens keep their initials. Portraits on tokens go to the backlog.
11. **The Flanaess:** no structured Flanaess map exists, only raster images. Greyhawk ships ttrpg2's hand-made
    "Greyhawk region" map as its one world map. A Flanaess backdrop image goes to the backlog.
12. **One quest, thirteen tasks.** One migration (`0013_world`) adds every new table, so the feature tasks could run
    in parallel.

## 11. Security and identity

- **The network:**
  - The app listens on the LAN.
  - The host's browser on the same machine is the host without a token.
  - Every other device needs a token.
- **The host link** printed at start (`http://<ip>:<port>/#token=…`) gives a browser host rights. The page keeps the token
  in a cookie and removes it from the address bar. Guild does the same.
- **Join links** for players carry a campaign-scoped token. Once a player has joined, their device keeps a per-player
  token. There are no passwords.
- **Requests:**
  - POSTs are JSON only.
  - `Origin` and `Host` are checked.
  - Uploads have size limits.
  - Images in SVG are sanitised (active content refused).
  - The DM's MCP endpoint is localhost only, with a per-process secret.
- **Roles (owner: rudimentary):**

  | Role | Scope | Can |
  |---|---|---|
  | **Organiser** | the install | Create and import modules, edit house rules, start campaigns. The install's owner is always one, and can make others organisers. |
  | **Host**, **co-host** | one campaign | Run the table (§7.2). |
  | **Player** | one campaign | Join, control characters, act, talk, ask. |
  | **Observer** | one campaign | See the table, talk and ask. No actions. |

  The editors and module import need the organiser role. A friend who only "tags along" is a player.
- **Who someone is** is decided in one place (an identity interface). Real accounts (OIDC) can replace the token
  scheme there when the app goes online. **(owner: don't build that yet)**

## 12. Storage (owner)

- **The only layer that knows SQL:** the `storage` package. Game code calls repository methods such as
  `campaigns.get(id)` and `map_states.save(state)`, and never sees a query.
- **(call) SQLAlchemy Core** (not the ORM) on **SQLite** in WAL mode:
  - one file for the app's data;
  - a separate read-only reference database, built by a script from source data that is **copied into this repository once**
    from ttrpg2's `global/` (call). There is no build-time link to ttrpg2. Fixes made in ttrpg2 later are carried over by hand;
  - attachments stored as files on disk, content-addressed;
  - migrations with Alembic from day one.
- **When to switch to Postgres:** if the app is hosted for many hosts with several writing processes. Until then
  SQLite is simpler and faster.
- **Contract tests:** one suite is written against the repository interfaces and runs against every backend, so a second
  backend proves itself by passing it.
- **What's stored:**
  - modules and their revisions;
  - campaigns;
  - players and their tokens;
  - characters with inventory and spell loadout;
  - possessions;
  - map states;
  - NPC, faction and quest state in a campaign;
  - calendar and weather;
  - sessions and their recaps;
  - the story log;
  - the dice log;
  - house rules and bundles;
  - settings.

## 13. Testing

- **Unit tests** for `rules`, `maps` and `modules`. dungml's DSL and fog tests come over with the code.
- **ttrpg2's characterisation tests** of 2026-10-17 become the reference for porting rules. A pinned bug becomes a
  test of the correct rule.
- **Fourth-wall tests:** for every player-facing route and stream, a test that a planted DM-only value never reaches it.
- **Storage contract tests** (§12).
- **A fake DM provider** that replays scripted tool calls and text. With it, play, beats, multiplayer and redaction
  are tested end to end without Claude.
- **The eval harness** from ttrpg2 (`evals/`), ported:
  - The offline cases run with the suite.
  - The live mode stays opt-in.
  - It gates the change to "no file tools" (§6.2).
- **One command** runs everything, locally and in CI (`make ci`).
- **A few browser tests** for the main flows: create a campaign, play a beat, join as a second player, edit a module.

## 14. Plateaus (owner: the designer defines them; build iteratively)

Each plateau is usable on its own. The beat model and the swappable layers exist from plateau 0, even when only one
implementation is behind them.

| # | Plateau | Usable for |
|---|---|---|
| 0 | **Foundation.** Repo layout and packaging (one command to install and run), the storage layer with migrations, the four interfaces, the SPA shell, auth tokens, `make ci`, the fake DM. | Nothing yet; everything else builds on it. |
| 1 | **Maps.** The DSL, renderer and fog as internal packages. A module made of a map. The map editor screen. A map state per campaign, with positions and discovery per character (§7.4). `.dscn` import of maps. | Drawing and viewing maps. |
| 2a | **The game engine.** Dice with a log, checks, saves, combat on the map (2e bugs fixed), characters, party and marching order, inventory and encumbrance, spell loadouts, NPCs, notes, sessions, reference lookups, the DM's tool surface (with `batch`), all tested with the fake DM. **House rules and bundles** (ttrpg2's migrated as the owner's first bundle) with a simple editor, chosen at campaign creation. | Everything a session needs, without Claude yet. |
| 2b | **Solo play.** The DM through `claude -p` (resident process, system prompt from ttrpg2's hard constraints), the play screen for laptop and tablet with Act and Ask the DM, redaction, recaps, and the eval gate against ttrpg2 (§6.2). | **First real session.** |
| 3 | **Writing modules.** The module editor (text, attachments, forms, room links), `.dscn` export of whole modules, and campaign creation with ruleset and setting. | Writing and playing your own module. |
| 4 | **The table.** Multiplayer beats, join links and QR codes, roles (organiser, player, observer), table talk, a split party across players, the typing indicator, the beat timer and its fallback, co-hosts, translation, the phone layout. | Playing with friends. |
| 5 | **Books and quick dungeons.** The three ways to get a module (§8.3): a complete module from a PDF with its maps, a PDF draft to work on, and a module generated from a request. The whole-module print view and PDF export. | Bringing in, generating and printing modules. |
| 6 | **The rest of the world.** Possessions, world maps and travel, weather and calendar, factions and quests in play, lore and setting lookups, the magic merchant, image providers (portraits, scenes), and portraitgen. | Feature parity with ttrpg2's kept list. |

Plateaus 3 to 6 can be reordered when the owner wants something sooner. **The owner moved plateau 5 before plateau 4 (2026-10-18):** books and quick dungeons come before the table. Plateau 2 is built as two quests, 2a and 2b; house rules moved into 2a at the owner's request (2026-10-17).

**How they're built (owner):** each plateau is an edit-mode Guild quest on this repository, from a written plan, delivered
to the main branch after review.

## 15. Left to the builder

- Package and module names, file layout, the port number (avoiding 5000, 7777, 7790 and 8000, which are in use).
- The exact DM tool list, within §6.3 and the feature review.
- The exact table layout, within §12.
- The phone layout, within §7.6.
- The component library and styling, within the stack.
- How map extraction copes with maps it can't read cleanly (warn and leave them for the map editor is enough).

## 16. Open

- The product's **name**.

