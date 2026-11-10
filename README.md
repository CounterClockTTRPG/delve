# Delve

Delve is one application for playing tabletop role-playing games at home, alone or with friends on the LAN, with
Claude always as the DM. It brings together the DM system of ttrpg2 and the maps of dungml (their language, renderer,
fog of war and editor), keeps their principles and tested behaviour, drops their historical cruft, and adds
multiplayer, translation, a module editor, house rules, and PDF import and export. One person installs it; it runs as
one process on one port on that person's machine.

## Install

See **[INSTALL.md](INSTALL.md)**: what Delve needs, installing it, the first start, and running it as a service. In
short, with Python 3.12 or newer, [uv](https://docs.astral.sh/uv/), Node.js and Claude Code:

    make install
    make run

This installs OSRIC, the ruleset in this repository (`packs/osric`), beside Aun, Delve's own setting.

## Rulesets and settings are packs

A ruleset or a setting is a pack: a folder under `<data dir>/packs/<id>/` with its `pack.toml`, its code and its
data, and a `pack.db` that its install builds. Delve has no ruleset built in; it plays the ones its packs bring, and
a campaign whose pack isn't installed says so and doesn't play. Only the owner installs packs, from the command line:

    uv run delve pack install packs/osric                     # a pack folder
    uv run delve pack install osric-1.0.0.delvepack           # a pack file, from `delve pack build`
    uv run delve pack install <git URL>#adnd2e                # a folder of a git repository of packs
    uv run delve pack list                                    # what is installed, and what was left out and why
    uv run delve pack rebuild adnd2e                          # build its pack.db again
    uv run delve pack remove adnd2e

Restart Delve after installing or removing one (the owner can also do both under Preferences → **Packs**). This
repository ships OSRIC and Aun only. Other rulesets and settings, such as the ids `adnd2e`, `greyhawk` and
`forgotten-realms` the code and its tests name, are packs you make or get yourself; none of their content is here.

## Run

    make run

This builds the web app and starts Delve on port 7810 (`uv run delve serve --port <other>` to change it, `--host` to
change the address it listens on). If the port is in use, Delve says so and exits.

On this machine, open <http://localhost:7810/>; until there is an owner account, a browser on the same machine needs
no login. Make the owner account (`uv run delve account add <username> --owner`) before you open a tunnel to Delve.

As a systemd user service, give it a socket unit, so a restart refuses no one: systemd holds the port while Delve
restarts, and a request that comes meanwhile waits for the new server instead of getting a 502 from the proxy. Delve
takes the socket it is passed (`LISTEN_FDS`, also under `uv run`), and ends its event streams as it stops, so the old
server is gone in a moment; browsers reconnect by themselves.

    # ~/.config/systemd/user/delve.socket
    [Socket]
    ListenStream=0.0.0.0:7810

    [Install]
    WantedBy=sockets.target

`delve.service` then runs `uv run delve serve --port 7810` with `Requires=delve.socket` and `After=delve.socket`;
enable the socket (`systemctl --user enable --now delve.socket`) with the service stopped, since both want the port.

## The token link

Another device of yours on your network can use the owner token instead of logging in (friends join a table by its
join link instead: see "Playing with friends"). `delve token` prints a link for each of the machine's network
addresses, such as `http://192.168.1.20:7810/#token=…`. Open it once on the other device: the page takes it out of
the address bar and hands it to Delve, which keeps it in a cookie the page's scripts can't read. Without it, the page
asks you to log in.

    uv run delve token       # prints the links
    uv run delve token --new # a new owner token: the old one and its links stop working at once

The owner token never expires, so if a link got out, make a new one: with `delve token --new`, or with **Make a new
owner token** under Preferences, which shows the new links once. A running Delve takes the new one at once, with no
restart. Over the internet (a tunnel or a proxy on this machine, such as cloudflared) the owner token is refused: log
in with your owner account there.

## Maps

Under **Modules**, make a module or import a `.dscn` file (dungml's scenario package, such as the Crypt of Saint
Vellis sample; see "Getting a module" below); each map opens in the editor, with a live preview and a print
view. Under **Campaigns**, start a
campaign from a module (its characters are made in play, with the DM): the campaign keeps the module's revision of
that moment until you press "Upgrade to the latest revision". The map-state panel moves characters (they can split up and meet again, sharing what
they found) and shows the characters' view or, separately, the DM view. The map language and the `.dscn` format are
described in `docs/maps/`.

## Getting a module

Under **Modules**, **New module** offers four ways:
- **An empty module**, from a title, to write in the editor.
- **Import a .dscn**, such as the Crypt of Saint Vellis sample.
- **From a PDF:** a module's PDF becomes its texts, its NPCs and encounters, its images, the book's own map pages and
  sketched maps. Choose
  **Ready to play**, or **A draft to work on** when you want to go over it first. The texts keep the book's own words,
  as Markdown: a chapter becomes a text, a keyed area (`12. The Well Room`) a keyed heading, boxed text a read-aloud
  quote. A picture page whose first line is a short title, with little else on it (a chapter's title page), starts a
  new text; a running header or the module's own title never does. The book's numbers, die rolls
  and table rows are kept as the book has them. NPCs, factions, quests and encounters with the same name become one
  record, and an encounter or NPC that the book places in a keyed area ("in area 4") is keyed to that room. Claude does
  the conversion ("Module conversion" under Settings: `claude` with model `sonnet` by default), a few pages at a time,
  so a 300-page book takes a while. The screen shows "Step 2 of 4", the pages done (also during OCR) and the time
  taken, survives a reload, and Cancel stops it, also while the PDF is still being read, without leaving half a
  module. A running conversion also shows at the top of **Modules** and as a dot on Modules in the menu, and when it
  ends, a notice on any screen links to the module.
- **Describe the module you want**, such as "a dungeon with kobolds, no plot": Claude writes a small module with a
  keyed text, its NPCs and encounters and a sketched map, ready to play.

**Drafts:** a draft can't start a campaign; the campaign form doesn't offer it. On its page, **Mark as ready** makes it
a module like any other (a module can't become a draft again).

**The warnings** a conversion leaves are shown on the module's page, folded into one line ("17 warnings"); open it to
see them grouped by kind, each linked to its text, attachment, map or room. The module's own warnings (such as a keyed
heading with no room) are listed with them. They say what to check:
- `book-map`: a page of the book that is a map (OCR finds its legend or its room numbers) is kept whole as the
  attachment `map-page-<n>`, "Page n: a map from the book", with the map's title when OCR reads one.
- `map-sketched`: a text with three or more keyed rooms gets a schematic map that Claude drew from the room key (its
  keyed headings link to its rooms by themselves). Its layout is **invented**: the map's source starts with
  `# Sketched from the room key: an invented layout.` and names the book's map page, and the Maps tab and the map
  editor say so, with **Show the book's map**. It is named after the book's map title. Compare it with the book's
  map. Unless **Draw each map from the book's map page** was unticked on the PDF form, each sketch that names a map
  page is then drawn again from that page, one job after another, as a draft on the Maps tab, kept only on Keep;
  **Draw it from the book's map** on the sketch does the same by hand. `map-not-drawn`: the sketch didn't parse twice, or the text's keys repeat (as when several levels are numbered
  from 1 in one chapter), so there is no map for that text; draw it by hand.
- `numbers-changed`: Claude's Markdown for those pages holds some of the book's numbers fewer times than the book
  (a renumbered table, a lost row); the warning lists them. A page's first and last line (its header and footer)
  are not counted. Check the table against the book.
- `image-to-describe`: each picture of the book is an attachment (DM only) described only by its page. Say what it
  shows and when it fits, and show it to the players if they should see it.
- `conversion-short`: Claude's Markdown for those pages left words out, so the text read from the PDF is kept instead,
  without headings. `entities-not-read` and `entity-dropped`: NPCs or encounters to add by hand.
- `audience-player`: a text, NPC or encounter the conversion marked for the players. Everything else is DM only;
  check that this one really is for the players.
- `page-too-large`: a page too large to render in full was rendered at a lower resolution; compare its image with the
  book.
- A scanned page is text only when OCR reads at least 150 real words on it; any other scanned page (a map, a
  handout, a title page) is kept as an image, and what OCR read on it goes into no text.
- `page-text-as-picture`: a scanned page with some text (40 to 149 real words) was kept as a picture, so its text is
  in no text; check the page and copy what matters.
- `page-not-read`: a scanned page, with no text to read. OCR needs the optional
  [tesseract](https://github.com/tesseract-ocr/tesseract) program (`apt install tesseract-ocr`); without it the page
  is kept as an image, and nothing is lost. A page drawn in lines (such as a map) is kept as an image too, with its
  own text. The original PDF is kept with the module, but isn't exported.

**Print:** on a module's page, **Print the module** opens the whole module for print: a title page, each text, each
map with its key (the DM view), the NPCs and encounters, and the images. DM-only material is included. Print it, or
save it as a PDF, from the browser's print dialog.

**Checking a conversion on a real book** (opt-in, spends tokens on your subscription, never part of `make ci`):

    make convert-live PDF=book.pdf TITLE="The Sunken Shrine"

It converts the book with the real `claude` into a temporary data dir (your own data is never opened), prints the time
of every Claude call, the warnings and the word coverage (the module's words out of the words read from the PDF), and
leaves the module as a `.dscn` in `evals/recordings/conversions/`, to import with "Import a .dscn".

## Writing modules

The Modules list can be a table or **cards** (each module's banner, or its first letter), and groups modules under
**categories** once you make some (**Categories** keeps the list; each module has one or none, set on its page).
A module's page has a **Banner**: paint one, upload a picture, or use one of the module's own pictures (a converted
book's cover, say), with a crop position for the 21:9 band. Its campaigns show it until they paint their own.

A module's page has tabs:
- **Text:** a light word processor for the module's texts, each for the DM only or for the players. A heading such as
  "## 2. The Hall" is a keyed heading: it links itself to the room of that name or label on the text's map, and shows
  the room beside it. A quote straight after a heading is read-aloud text. A heading with no room, a room with no text,
  and a reference to something that isn't there are listed as warnings. Save with the button or Ctrl+S.
- **NPCs, Encounters, Factions, Quests:** forms, with the 2e stats of an NPC and the monsters of an encounter. An NPC
  and an encounter each have a **Where**, one of the module's keyed rooms.
- **Attachments:** upload images and PDFs, describe each one (the DM reads the description to know what it shows and
  when it fits), say who sees it, and insert it in a text.
- **Who sees what, many at once:** the lists of texts, entities and attachments have a tick on each item and **Select
  all**; with items chosen, **DM only** or **Players** sets all their audiences in one save (all or nothing: a secret
  is always DM only). A converted book's texts start DM only, so this is how to open its handouts to the players.
- **Maps** (as before; renaming a map keeps the texts and keys that use it) and **Details:** the title, authors, party levels and size, setting, system, tags, content
  warnings and cover.
- **Novels** (the install's owner only): **Novelize** turns the module into a story of a party's run through it, in the
  background, and lists the novels written. See **Novels** below.

**Export .dscn** writes the whole module (texts, entities, attachments, maps and details) as a `.dscn` version 3 file,
which imports back as the same module, here or on another install. A module that refers to a missing attachment or
entity doesn't export until that is fixed (the warnings say where). A campaign plays the module's revision of the day it
started, so edits reach it only when the host upgrades it.

A new campaign names its **ruleset** and **setting** (or no setting); they default to what the module's details say. In
play, the DM shows the module's player images in the story when the characters see what they show. A DM-only image
never reaches a player.

Every campaign gets a **banner**, a wide painting of its module's world, asked for when the campaign is made and
painted with the scenes' choice of model in Preferences. With paid images off and a paid model chosen, it waits, and
it is painted as soon as the host turns paid images on (or Preferences choose a free model). It opens the empty
story, heads the campaign's page, and shows as a thumbnail on the module's page for each of its campaigns. On the
campaign's page, organisers can **Paint again**, with a hint; the old banner stays until the new one is painted. Its
brief holds only the module's title, summary and description, the setting and the tone, never the DM's text.

A campaign keeps its one module. To take its party into another one, use **Carry the party on** on the campaign's page
(or in its row's menu on Campaigns): choose a module that isn't a draft, a name, the ruleset, setting and house rules
(the old campaign's, by default) and who goes (the living PCs are ticked; the dead are listed). The new campaign gets a
copy of each character, their possessions and the party's coin and loot pile; the old one is kept, set to complete,
and both pages link to each other. Claude then writes the party's **history** from the old campaign, as a job, in two
versions: the DM's, which the DM reads every session, and the table's, which holds only what the whole table was told.
Its **History** section on the new campaign's page shows both to the host, who can edit them or **Write again**; the
players read the table's version under the play screen's **History** tab.

## The game engine

Everything a session needs except Claude:
- **The game:**
  - the rules of the campaign's ruleset (a pack's), with logged dice (no re-rolls within a beat), checks and saving
    throws;
  - combat on the map in play, with its tokens;
  - characters and NPCs, the party and its marching order;
  - inventory and encumbrance, spell loadouts, treasure and experience;
  - notes, secrets, sessions and the clock.
- **House rules:** under **House rules**, edit rules and bundles. A fresh install starts with none: **Import the
  example rules** on that page adds Delve's example bundle (its general rules, and the homebrew of the installed
  packs, each tagged with its pack), or `delve house-rules import` does. A library already in
  use is never changed by it, and an install that has rules keeps them. A new campaign picks its bundles and single
  rules, and the DM gets each rule when it applies.
- **The language switch:** the sidebar's **EN / NL** switch (for organisers) changes the interface's language for the
  install, without touching Preferences' other choices. Races, classes, genders and alignments, and Preferences'
  warnings, are shown in that language; item, weapon and spell names stay as written.
- **Rulesets:** the nav's **Rulesets** (and `g b`, or the palette) opens the book of each installed ruleset: its
  spells, items, classes, ability scores and tables, each entry on a page of its own that you can share. Monsters
  are for the owner and organisers only. A campaign's homebrew items, classes and races stand beside the book's; a house rule's **DM Notes**
  section is for organisers and is cut for everyone else. A seat at a table reaches it from the **Rulesets** link in
  the play header, which opens a new tab.
- **The DM's tools:** about 70 tools (`delve.dm.tools`), with ttrpg2's `batch`, served to Claude by `delve dm-bridge`.
  `tests/e2e/test_tool_timing.py` plays a first session through them, without Claude.
- **The reference data:** a ruleset's rules, monsters, spells and items, and a setting's wiki and lore facts, are its
  pack's (`delve pack install`, which builds the pack's `pack.db`). Delve ships OSRIC and its own setting, Aun; other
  rulesets and settings are packs you install.

## Play

Delve's DM is Claude, through the `claude` command line (Claude Code) on your own subscription: install it and log in
first, so `claude` is on the `PATH` of the shell that starts Delve. Without it, `/api/health` says the DM is
unavailable and Settings say why.

1. Under **Campaigns**, start a campaign from a module (the Crypt of Saint Vellis sample is a good first one).
2. Under **Play**, pick it. Write what you do and press **Act** (Enter): the DM answers in the story. The host and
   co-hosts also see the tools it used, folded into one line each; the other seats see only the story. A note the DM writes for the host alone (a
   paragraph starting `(ooc, for the host:`) reaches only the host's seat. While it thinks, the screen shows the time and the tool calls so far; **Cancel**
   stops it. The first act of a session starts the session, so "Make us a party of four" is a fine first act.
3. **Ask the DM** (Ctrl-Enter) asks a question out of band, such as "what does surprise do?". It is answered from the
   rules, what your characters carry and what they saw lately, never from the module, and only you see the answer, in
   your language.
4. The side column shows the party first, then the map, then the table, then the host's controls (folded). The
   party shows hit points and conditions, and its arrows (or a drag, on a desktop) change the marching order; a tap
   on a card opens the sheet. The map shows what your characters have found. **Table settings** set the tone, the detail level and the
   DM's effort for this campaign.
5. To end the evening, say so ("let's end the session here"): the DM writes a recap, which opens the next session.

**Look:** Delve comes in three looks: **Delve today**, **Gold and wood** (dark oak, gold and Cinzel) and **Dark
dungeon** (cave rock, torch orange and IM Fell). Pick one in **Preferences**, or with the swatch in the play screen's
header; it holds for this browser only, so each player at a table picks their own. A look changes colours, fonts and
textures, never where things are, and maps and printed pages keep their own colours. Its fonts and textures are part
of Delve: nothing loads from outside.

**On a desktop:** from 900 px wide the story and the side column, a module's list and its editor, and the map
editor's code and drawing are split by a divider. Drag it, move it with the arrow keys once it has the focus, or
double-click it to reset it; each browser remembers the widths. **Ctrl K** (⌘ K on a Mac) opens a palette that goes
to any area, campaign, module or setting, and makes a new module or campaign or switches the look. **?** lists the
shortcuts: **/** puts the cursor in the story's input box, and **g** then a letter goes to an area (**g c**
campaigns, **g m** modules, …). An organiser can drag a party card to its place in the marching order. A right-click
on a story entry copies it, or shares an answer from the DM with the table. A campaign or module row's actions are
in its **…** menu. A PDF or `.dscn` file dropped on **New module** is converted or imported. When a conversion ends
on another screen, a notification in the corner says so.

### The character sheet

A sheet shows the abilities (exceptional strength as `18/76`), hit points, AC, THAC0, XP and move; gender, size and
any AC bonus against larger attackers; the saving throws; the attacks, each with its own THAC0 (a specialised weapon's
differs) and the weapon in prose under them; weapon and nonweapon proficiencies, thief skills in %, natural abilities;
the inventory with its load; the spells; and the background. On the campaign page the organiser also sees each NPC's
sheet with its story and its disposition towards the party, which no seat at the table ever gets. The campaign page's
**DM log** lists each beat's tool calls, tokens and cost, with the campaign's total.

The DM runs in `<data dir>/dm/<campaign>/`, with only Delve's own tools: no file access, and none of your other MCP
servers. Modules imported before plateau 2b have no module text for the DM; import them again to add it.

## Playing with friends

Friends play on their own devices on the same network, phones included: no account and no password. You are the
**host** of every campaign you start.

1. **Invite.** On the play screen, open **Invite** (it starts open while you are alone at the table). Show the QR
   code, or copy the link and send it. **New link** makes the old link stop working. The link uses the address your
   browser is on; when that is `localhost`, open Delve on the LAN address that `delve serve` prints instead, or
   other devices can't reach it.
2. **Join.** On the link, each person writes a name, picks a language (English, Nederlands, or another language's
   code) and chooses **Play** or **Watch**. A player then picks free characters, or asks the DM to make one; a player
   with no character has **Choose your character** on the play screen. Their
   device keeps a seat at this one table: it can't open modules, house rules, Settings or another campaign.
3. **The beat.** Everyone who plays writes an **Act** (or **Pass**), and can change it until the beat closes. The DM
   answers once everyone present has acted, when you press **Go**, or when the **beat timer** (if you set one) runs
   out. Characters nobody acted for then **hold back**, or, if you choose so, the DM plays them **in character**,
   cautiously. The names under the story show who is typing and who has acted. The DM gets each act quoted under
   the name of who wrote it, so an act can't pass itself off as another player's, or as a note from Delve or the
   host.
4. **Three ways to speak:** **Act** goes to the DM; **Table talk** is for the people at the table only; **Ask the DM**
   is a private question, whose answer you can share with the table. An act takes up to 4,000 characters (a few
   paragraphs), a question 2,000 and a line of table talk 1,500; the box counts down near the end. Each seat may
   act 20 times and ask 10 questions in five minutes, say 20 lines of table talk a minute and ask for 5 scenes in
   five minutes; past that it is told how long to wait, while the others go on.
5. **Who sees what:** what the DM tells only some characters is marked **Only you**, and only their players see it.
   Observers see the story and table talk, and never act.
6. **Languages:** each person writes and reads in their own language. Delve keeps the story in English, and the
   **Translation** job in Settings (Claude's `haiku` by default) translates what people write into English and the DM's words
   out of it, paragraph by paragraph, as they come. Until a paragraph is translated it shows in English, marked
   "translating…".
7. **Seats:** under **The host's controls** you make someone a co-host (with the host's controls), an observer or a
   player, hand over the host, and give any character to anyone. A player can **Leave the table**; their characters
   become free.

**Asking for an account (sign-up).** Besides an invite and **Add a player**, people may ask for an account
themselves while sign-up is open: on the Players page (Preferences → Players), tick **Let people ask for an
account**; it is off until you do. The login page then offers **No account? Ask for one**, at `/sign-up`: a username,
a display name, a password and a line saying who they are. The account **waits for approval**: it can't log in
(with its right password it is told it waits), it is listed under **Waiting for approval** on the Players page, and
the menu counts the waiting ones on Preferences. The owner or an organiser **Lets it in**, or **Turns it away**, which
deletes it and frees its username. Someone waiting who logs in on a table's join link is let in by it, since the host
shared that link. Each address may ask 3 times an hour, and at most 20 sign-ups wait at once.

**Logging in with Google.** Once the owner sets it up, the login page offers **Continue with Google**, the sign-up
page **Sign up with Google instead of a password** (with the username and note from the form; the account still
waits for approval), and Profile **Link your Google account** (with the account's password, when it has one), with
Unlink. A Google account is matched by its own id, never by its email, so it reaches a Delve account only once that
account linked it, or signed up with it; an account's last way to log in can't be unlinked, and a password reset
link from the owner unlinks every Google account of that account. To set it up:

1. In Google Cloud's console, make a project, configure its OAuth consent screen (the scopes `openid`, `email`
   and `profile`, which need no review by Google) and add an OAuth client of the type **Web application**.
2. Give it the **authorised redirect URIs** that Preferences → Connections → Google login lists: one per name Delve
   answers on over https (`DELVE_ALLOWED_HOSTS`, such as its tunnel's), and this machine's localhost.
3. Paste the client ID and secret there and Save. The secret is kept in `<data dir>/oidc-google.json` (mode 0600)
   and never shown again.

Google sends a browser back only to https addresses and localhost, so the buttons show there, not on the LAN
addresses (`http://192.168.…`), where players use their passwords.

On a phone the play screen shows the story and the composer, with Map, Party and Table one tap away; the map opens
fitted to what the characters know. The module's page, the map editor (Code and Drawing as two tabs), House rules
(a rule opens as its own view) and the print pages fit a phone's width too.

## Novels

The install's owner can turn a campaign or a module into a novel. On a campaign's page, **Novelize** reads everything
that happened (the story, the recaps, the characters and their fates, the NPCs met, the DM's secret and room notes and
the module's rooms, reached or not); under a module's **Novels** tab it tells a party's run through the module's
latest or a chosen revision. Choose a length (**Recap**: one chapter; **Short story**: 3 to 5; **Novella**: 8 to 14), a
tone (the DM's tones, or your own), a language (English or Dutch), optional instructions, and for a campaign the
sessions to tell. Claude writes the outline first, then each chapter, in the background; the list shows "n of m
chapters", and a novel that failed or was cancelled keeps what it has and can **Continue**. Read it in Delve, with a
table of contents, or open **Print the novel** and print it to PDF. Rename it with **Rename**.

A novel may tell every secret, so it is the owner's alone: no seat sees it, an organiser seat included (403). Only the
owner's Preferences choose which Claude writes it (the `novel` job).

## Out in the world

The party can leave the dungeon. Days pass on the setting's calendar (in Greyhawk the Common Year, "4 Planting 576
CY"), each with its weather; the play screen's head shows the date and the weather beside the session.

1. **The World panel**, beside the map (on a phone, the fourth screen, **World**), shows the world map as the party
   knows it: the land it has seen or heard of, under a fog everywhere else, with its places, roads and rivers, the
   party's marker and its journey, and the known places listed beside it. It also shows the quests the characters
   know with what they know of them, the factions they know with their standing ("Friendly"), and the party's
   possessions: mounts, boats, ships, houses. A place the DM hides, or one in land the party doesn't know, is never
   sent to a player's device.
2. **Travel.** Say where you go ("we ride the south-coast road to Hardby", "we take a boat down the Selintan"): the DM
   travels a leg at a time, by one way of going (on foot, on horseback, by cart, by river boat or by ship), day by
   day along the roads, the rivers or the sea, at the pace of the slowest traveller, the terrain and the weather. A
   horse speeds it up; a blizzard costs the day. The land along the way becomes known, and the places that come into
   sight show on the map. An encounter on the road stops the journey where it happens.
3. **Factions, clocks and quests** come from the module when the campaign starts. The DM moves them in play; on the
   campaign page an organiser edits them under **Factions and clocks**, **Quests** and **Possessions**, and the
   campaign's world maps under **World maps** (below).
4. **The setting:** the DM looks up Greyhawk's places, realms, deities and people in the setting's wiki, and while it
   thinks the play screen shows a **Did you know?** fact from it.
5. **Pictures:** portraits are drawn for free by portraitgen, in the browser.
   - **Portrait style:** an organiser chooses one of seven styles per campaign on the campaign's page (illustrated,
     realistic, painterly, inkwash, engraving, anime, pixel); every portrait of that campaign is drawn in it.
   - **Emotes:** when an NPC speaks, the DM's `say` tool shows the line beside the NPC's portrait, which talks while
     the line appears and then shows its mood. A character sheet's portrait shows its state (hurt, frightened, down).
   - **Paid pictures** (painted scenes, and pictures of possessions) are off until the host turns on **Paid images**
     under the host's controls; then **Paint this scene** paints the last narration, in the background. A campaign
     paints at most **Paid pictures a day** of them in any 24 hours (20 unless the host chooses 5, 10, 40 or 100),
     the seats' scenes and the DM's pictures together, a failed one included; within a beat the DM paints at most two
     scenes and one picture of each character or possession. Past the limit, Paint this scene says so, and the DM
     tells the scene in words. Free pictures (portraitgen, a free model) and the organiser's banners are never
     counted.
   - **Connections:** the install's owner joins the picture backends under **Connections** at the top of Preferences,
     with no restart: Replicate's token (or `REPLICATE_API_TOKEN` in the environment, which wins) and the URL of
     **assetgen**, your own picture server (`assetgen serve --port 8765`; its models are read from it live). Tokens
     are kept in files of the data dir (`replicate-token`, `assetgen.json`, mode 0600); they are never stored in the
     database or sent to a browser, which only learns whether one is set.
6. **Merchants:** a magic-item merchant's shelf is rolled once per merchant and kept; the DM shows it in character,
   and buying pays from the party's coin.

### World maps

A world map belongs to a module (under its **Maps** tab, **World maps**) or to a campaign (on its page, **World
maps**). A new campaign copies its module's maps, then its setting's.

- **Import a world map** takes a GeoJSON file (from QGIS, or Azgaar's Fantasy Map Generator), or a **picture of a map
  with its key**: the grid (hexes, squares or none), and what one cell is ("1 hex = 30 miles"), or two points
  clicked on the picture and their distance. Reading a picture runs in the background, as a book's conversion does
  (a large map takes a minute or two). It finds the grid, the terrain colours, the sea, lakes and rivers, the towns
  and their names, and the roads; Claude names what OCR can't read (the optional `tesseract` helps).
- **The review:** a map read from a picture stays **In review** until you accept it, and no player sees it until
  then. The review lists what is doubtful (a colour with no terrain yet, a place whose kind is guessed, a river whose
  flow is a guess, a cell of two colours), each with its choices, and **Decide all of this kind**; then the colours,
  each with Claude's suggestion, and **Outside the map** for a frame's colours. **Accept the map** waits until every
  colour has a terrain.
- **The editor** (**Edit**) draws places, roads, rivers, regions, lakes and seas over the picture, and paints terrain
  with a brush; **Export (GeoJSON)** writes the map for QGIS, and **Download the picture** gives the picture back.
- **What the party knows at the start:** everything, nothing, some regions, or an area drawn on the map. From then on
  the party learns the land it travels through, and the DM can reveal a place, a road or an area (a map bought, a
  tale heard), or hide one again.
- **The setting's map:** a module's ready world map can be **used as the setting's map on this install** (such as
  Greyhawk's), so every new campaign of that setting copies it instead of the built-in one.

Plateau 6's maps, written in ttrpg2's map language, are converted the first time they are read, and keep their
places, the party's position and what was revealed. The formats are in `docs/maps/world-maps.md`.

## Storage

The install's owner sets two stores under **Storage** in Preferences, each on its own: Azure Blob Storage (a
container's SAS URL), Cloudflare R2 or another S3-compatible store (endpoint, bucket, access key id and secret).
**Test** shows what a store's credential may do. The backup store and the library must be separate containers or
buckets; Delve refuses to save one in the other's place.

- **The backup store** is yours alone. Every day at the time you set (04:00 by default, or when Delve next starts if
  it was off then) Delve copies the modules, campaigns and settings that changed, the latest copy of each; **Back up
  now** runs it at once. A run where something failed says so and tries that item again next time. **Restore** lists
  the backups of this install or another one: tick what to bring back (a campaign brings its module along), and Delve
  asks before it replaces anything already here. A backup needs read, list, create, write and delete.
- **The library store** is shared with friends: **Library** on the Modules page lists its modules, with their author
  and dates. Download one to play it; when someone publishes a newer version, the module shows **Update**. Publishing
  never overwrites: each version is new. What an install may do there is its credential's **right**: **read**
  (browse and download), **publish** (add modules, and new versions of its own), or **manage** (also new versions of
  anyone's, and delete).

**An Azure SAS:** in the Azure portal, open the storage account's container, then **Shared access tokens**; choose the
permissions, an expiry date, and **Generate SAS token and URL**, and paste the **Blob SAS URL**. The permissions are:
- **Read** and **List**: library read.
- **Read**, **List** and **Create**: library publish (Azure's create can't overwrite or delete).
- **Read**, **List**, **Create**, **Write** and **Delete**: library manage, and the backup store.

The Storage section shows when a SAS expires. A publish SAS can't delete, so each **Test** of it leaves one small
object under `.delve-probe/` in the container; the library ignores it, and it is safe to delete by hand.

**A Cloudflare R2 token:** in the Cloudflare dashboard, **R2**, then **Manage R2 API Tokens** and **Create API
token**; choose the permission, apply it to **specific buckets only** (the one bucket), and paste the access key id
and secret into Delve with your account id and the bucket's name.
- **Object Read only**: library read.
- **Object Read & Write**: the backup store, or a library you write to. R2 can't tell publish from manage, so for a
  library you choose which in the Storage section; Delve keeps to it, but other tools with that token need not.

The credentials stay in files of the data dir (below); no browser, log or backup ever gets them.

## The DM's evals

    make evals                                             # offline: the recorded fixtures, as in make ci
    make evals-live                                        # opt-in: plays the cases through the real claude -p
    make evals-live EVAL_ARGS="--compare-ttrpg2"           # the same scripted lines through ttrpg2's own evals too

The live mode spends tokens on your subscription and is never part of `make ci`. Per beat it reports the time to the
DM's first words, the total time and the tool count, and with `--compare-ttrpg2` it puts ttrpg2's results beside
Delve's: that comparison is the gate that shows removing the DM's file tools doesn't hurt play. See `evals/README.md`.

## Timeouts

Each is read when Delve starts, in seconds:
- `DELVE_DM_TURN_TIMEOUT` (default 900): one reply of the DM at the table.
- `DELVE_CALL_TIMEOUT` (default 600): one Claude call of a conversion, a novel or a history. Raise it when a book's
  chunks or a long novel's chapters time out.

## Where data lives

In `~/.local/share/delve`, or in the directory named by `DELVE_DATA_DIR`, which Delve keeps mode 0700:
- `delve.db`, the SQLite database. Delve migrates it to the current schema at start (`uv run delve migrate` does
  only that). A database from a newer Delve is refused, with both schema revisions named. It, its `-wal` and `-shm`,
  and any copy of it named `delve.db.<something>` (or `reference.db.<something>`) are kept mode 0600; `delve serve`
  names those copies at start, since each holds all the database did. Remove them once you no longer need them:
  Delve never does.
- `packs/`, the installed packs, each with its `pack.db` (`delve pack install`).
- `token`, the owner token (mode 0600). `delve token --new` (or Preferences' **Make a new owner token**) replaces it;
  the old links stop working at once, also in a running Delve.
- `device-secret` (mode 0600), what the device cookies are signed with: a browser that logged in to an account
  before isn't locked out when strangers try that username's password too often. Delete it, and restart Delve, to
  end every device cookie.
- `backup-store.json` and `library-store.json`, the two stores and their credentials (mode 0600), and `install-id`,
  the name this install's backups go under.
- `blobs/`, stored files by their sha256, such as the original of every imported `.dscn` and every module's
  attachments (never deleted, so a campaign's revision always finds its images).

## Development

    make ci                  # ruff, import-linter, pytest, then the web typecheck, tests and build
    make e2e-browser         # the play screen, a table of three, the module editor, New module, the print page
                             # and the screens at phone width, in Chromium against a fake claude (not in ci);
                             # screenshots in web/e2e/screenshots/
    cd web && npm run dev    # the web app with hot reload, using the API of a running delve serve on port 7810

The design is in `docs/superpowers/specs/`, the plans in `docs/superpowers/plans/`, and the words we use in
`docs/glossary.md`.

## Licence

Delve is free software under the **GNU Affero General Public License, version 3** ([LICENSE](LICENSE)): you may use,
change and share it, and if you run a changed Delve for others over a network, you must offer them its source.

The OSRIC pack's game content keeps its own terms, set out in `packs/osric/src/delve_osric/data/NOTICE.md`: Delve is
an independent product published under the OSRIC 3.0 Third-Party License and is not affiliated with Mythmere Games
LLC. "OSRIC" is a trademark of Matthew Finch and Stuart Marshall; "OSRIC 3" is a trademark of Mythmere Games. It
includes material from the System Reference Document 5.1 by Wizards of the Coast LLC, under CC BY 4.0.
`web/vendor/portraitgen` keeps its own licence. Aun, Delve's own setting (`src/delve/setting/data/aun`,
`docs/settings/aun-bible.md`), is part of Delve and under its licence.

Product names named in the code (AD&D, Greyhawk, Forgotten Realms and the modules of TSR) are trademarks of their
owners, named only to describe what one can install or convert; Delve is not affiliated with them.
