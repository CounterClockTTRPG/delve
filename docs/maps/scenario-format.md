> Ported from dungml (commit a66a1bb).

# Portable scenario format (`.dscn`) — design spec

Status: **v3, implemented** (in Delve: `delve.modules.dscn`). Library and CLI: `packages/scenario` (`dungml_scenario`, `dscn`).
Schema: [`scenario.schema.json`](../packages/scenario/src/dungml_scenario/scenario.schema.json).
Sample: [`samples/scenarios/crypt-of-saint-vellis/`](../samples/scenarios/crypt-of-saint-vellis/).

A `.dscn` file is one portable unit holding everything needed to run a
scenario: dungml maps, module text (keyed room descriptions, read-aloud
text, GM notes), structured entities (NPCs, factions, quests, rumors,
secrets, encounters), world/region maps and attachments (images, PDFs).
It can be exported from and imported into both **dungml** and **ttrpg2**.

> **Version 2** (Delve plateau 3) adds one thing: every asset has a
> `description`, which says what it shows and when it fits (§9.1). A
> version 2 bundle needs it on every asset whose `role` is `attachment`,
> and a missing one is the error `asset-description`. Readers take
> versions 1 and 2. A version 1 asset has only its `caption`, which an
> importer takes as the description; `caption` stays allowed beside it.
> Writers write version 3.
>
> **Version 3** (Delve faithful modules) adds the `pregens` entity kind
> (§7.1). Readers take versions 1 to 3; an older reader refuses a version 3
> bundle outright instead of meeting `pregens` as an unknown field. Delve
> also reads a version 2 bundle that has pregens (it wrote those for a day).

---

## 1. Requirements (decided)

| # | Decision |
|---|---|
| R1 | **Clean scenarios only.** No play state: no fog, party position, door states, calendar, event log or session history. Sharing a campaign in progress is out of scope for v1. |
| R2 | **Room ↔ module key join lives in a manifest `keys[]` table.** No DSL change in v1; a DSL `key` attribute may come later and generate the table on export. |
| R3 | **ttrpg2 world maps** (`.map`, ttrpg2's own DSL) are bundled as **opaque typed files**. dungml ignores them. |
| R4 | **Split ownership with a shared spec.** dungml handles maps, libraries, keys and assets; ttrpg2 handles entities, text and world maps. A shared package defines the format. |
| R5 | **ttrpg2 can import a whole bundle.** It sets up the dungml side by **uploading the entire `.dscn`** to one new dungml endpoint, which creates the project, maps and assets and links the campaign. |
| R6 | **Two forms, one layout:** a zip file (`.dscn`) and an unpacked directory (git-friendly authoring). `pack`/`unpack` convert between them losslessly. |
| R7 | **Visibility defaults to GM.** Content is only player-visible if explicitly marked `audience: player`. |
| R8 | **Published-module sources** (PDFs, raw text) are allowed but **opt-in on export**. The manifest records a `license`. |
| R9 | **Re-import updates in place and keeps fog.** It matches on the scenario `id`, then on map name and entity id. Map sources are replaced the same way `PUT /source` replaces them, so discovery survives. |
| R10 | **dungml stores assets on the filesystem, content-addressed** (sha256), with metadata in a new `assets` table. |
| R11 | **Entities have a neutral core plus a system block.** Common fields are shared; game stats sit under a block named for the system (e.g. `adnd2e`). Monsters may be references (`monster:orc`) rather than inline stats. |
| R12 | **Keyed text uses Markdown heading anchors:** `## W101. Dwarven Guard Post {#w101}`. |
| R13 | **Read-aloud text is a leading blockquote** inside a keyed section; everything else in the section is GM text. |
| R14 | Name: **`.dscn`**, format id **`dungml-scenario`**. |
| R15 | Spec, schema, validator and converters live in a new **`packages/scenario`** in this repo. ttrpg2 depends on it. |
| R16 | **Link first, then import.** The GM links the campaign to a project once, with their own user login, as `link` works today. After that, service-scoped scenario imports can only create or update that **linked** project. A service principal never owns a project, and the existing contract rules are unchanged. |
| R17 | **A ttrpg2 import goes to a new campaign by default; merging is allowed.** When importing into an existing campaign, records whose id already exists are reported and skipped unless `--overwrite` is passed. |
| R18 | **Player-facing read-aloud is off by default, per campaign.** A GM setting on each campaign turns it on. Players never see text unless the GM opted in. |
| R19 | **Stats blocks are free-form in v1.** Only their overall shape is checked (an object keyed by system, with an optional `ref`). Per-system schemas can come later. |

---

## 2. Container

### 2.1 Layout

```
<root>/
├── scenario.json            # manifest — REQUIRED, the only fixed name
├── maps/
│   ├── level-1.dmap
│   ├── level-2.dmap
│   └── lib/
│       ├── core.dmap        # vendored include libraries (§4.2)
│       └── crypt.dmap
├── text/
│   ├── intro.md
│   ├── background.md
│   └── keyed/
│       ├── level-1.md
│       └── level-2.md
├── entities/
│   ├── npcs.yaml
│   ├── factions.yaml
│   ├── quests.yaml
│   ├── rumors.yaml
│   ├── secrets.yaml
│   └── encounters.yaml
├── worldmaps/
│   └── region.map
└── assets/
    ├── img/…
    └── src/…                # opt-in published sources (R8)
```

The only file name the format fixes is `scenario.json`. Every other path is
whatever the manifest says, and the tree above is a convention that writers
SHOULD follow. Readers MUST go through the manifest and MUST NOT find files
by globbing.

### 2.2 Zip form

- A normal zip archive with the extension `.dscn` and media type `application/vnd.dungml.scenario+zip`.
- `scenario.json` sits at the archive root.
- Paths use `/` separators and UTF-8 names. They are relative, with no `..`, no leading `/` and no symlinks.
- Entries are DEFLATE-compressed. Already-compressed assets such as images and PDFs MAY be STORED instead.
- **Packing is deterministic:** entries are sorted by path and every timestamp is fixed at 1980-01-01. Packing the same directory twice gives byte-identical files, so a `.dscn` diffs and hashes cleanly.

### 2.3 Directory form

The directory form is the same tree on disk: the folder that contains
`scenario.json`. It is the authoring form and is meant to be committed to git.
`dscn pack DIR → FILE.dscn` and `dscn unpack FILE.dscn → DIR` are inverses.

### 2.4 Relationship to `.dmapproj`

The existing `GET /api/projects/{id}/export` writes a zip with the manifest
`{format: "dungml-project", version: 1, name, maps:[{name, file}]}`.
**dungml's importer keeps accepting that format.** `dscn` can upgrade one:
`dscn upgrade x.dmapproj` gives a scenario that has maps only and a freshly
generated `id`. `.dmapproj` stays the plain project backup, and `.dscn` is
the portable scenario.

---

## 3. Manifest (`scenario.json`)

```jsonc
{
  "format": "dungml-scenario",
  "version": 2,
  "id": "6f1d2c1e-6c4b-4f1f-9a51-2b1f7f0d3c2a",   // stable UUID, generated once, never changes
  "title": "Greyhawk Ruins — Level 1",             // metadata: see §3.1
  "summary": "A dwarven outpost fallen to …",
  "authors": [{ "name": "…", "role": "author" }],
  "release": { "version": "1.2.0", "date": "2026-10-17" },
  "created": "2026-09-01T10:00:00Z", "updated": "2026-10-17T15:30:00+02:00",
  "system": "adnd2e", "system_name": "AD&D 2nd Edition", "setting": "greyhawk",
  "party": { "size": { "min": 4, "max": 6, "recommended": 5 }, "levels": { "min": 3, "max": 5 } },
  "license": "Personal use only — contains excerpts of WGR1 (TSR 1990)",
  "requires": { "dungml": ">=0.9" },              // informational; checked as a warning

  "maps": [
    { "name": "level-1", "file": "maps/level-1.dmap", "default": true, "title": "Level 1 — Guard Posts" },
    { "name": "level-2", "file": "maps/level-2.dmap" },
    { "name": "core.dmap", "file": "maps/lib/core.dmap", "role": "library" }
  ],
  "worldmaps": [
    { "name": "region", "file": "worldmaps/region.map", "type": "ttrpg2-worldmap" }
  ],
  "text": [
    { "id": "intro",    "file": "text/intro.md",          "audience": "gm", "title": "Introduction" },
    { "id": "keyed-l1", "file": "text/keyed/level-1.md",  "map": "level-1" },
    { "id": "handout-1","file": "text/handout-letter.md", "audience": "player" }
  ],
  "entities": {
    "npcs":       "entities/npcs.yaml",
    "factions":   "entities/factions.yaml",
    "quests":     "entities/quests.yaml",
    "rumors":     "entities/rumors.yaml",
    "secrets":    "entities/secrets.yaml",
    "encounters": "entities/encounters.yaml"
  },
  "assets": [
    { "id": "guard-post-art", "file": "assets/img/w101-guard-post.webp",
      "type": "image/webp", "sha256": "…", "size": 48211,
      "audience": "player", "caption": "The guard post, from the stair",
      "description": "The guard post seen from the stair. Show it when the party comes down into W101." },
    { "id": "wgr1-pdf", "file": "assets/src/WGR1.pdf", "type": "application/pdf",
      "sha256": "…", "size": 9123456, "role": "source" }
  ],
  "keys": [
    { "key": "W101", "title": "Dwarven Guard Post",
      "node": "map:level-1#room.guard-post",
      "text": "text:keyed-l1#w101",
      "assets": ["asset:guard-post-art"],
      "npcs": ["npc:dwarf-sergeant"],
      "encounter": "encounter:w101-guards" }
  ],
  "start": { "map": "level-1", "node": "room.entrance", "text": "text:intro" }
}
```

Field rules:

- **`id`** — a UUID that identifies *this scenario across versions*. Re-import matches on it (§8). Forks MUST generate a new one.
- **`maps[].name`** — the dungml `Map.name`. It is what `include "…"` and `exit … to "…"` resolve against, so it is the map's identity, and names MUST be unique within a bundle. `role` is `map` (the default) or `library`. A library's name is its include name, e.g. `core.dmap`. Exactly one non-library map MAY be `default`.
- **`text[].map`** — optional. It names the map a keyed text file describes and is used only to scope the auto-generated keys (§5.3).
- **`audience`** — `gm` (the default) or `player`. Allowed on text, assets, entities and individual entity records (§7).
- **`assets[].sha256`/`size`** — required. Readers verify them. A mismatch is an error.
- **`assets[].description`** — what the asset shows and when it fits; required on every `attachment` asset from version 2 (§9.1). `caption` is a short display line beside it.
- **`assets[].role`** — `attachment` (the default) or `source`, which marks an opt-in published source (R8). Exporters leave `source` assets out unless asked.
- **`start`** — optional hint for where play begins. ttrpg2 can use it to place the party; dungml ignores it.
- Unknown top-level and record fields whose names begin with `x-` are **extensions**. Readers MUST keep them on round-trip and MUST ignore them otherwise. Any other unknown field is a validation warning.

### 3.1 Metadata

Descriptive fields for listing, choosing and crediting a scenario. They are
all optional except `title`, and all player-safe: a catalogue or a player can
see them, so GM background belongs in a `text` entry. The JSON Schema
(`scenario.schema.json`) fixes their shapes; the validator then checks what a
schema can't (marked ✱ below).

| Field | Type | Notes |
|---|---|---|
| `title` | string, 1–200 | required |
| `subtitle` | string, ≤ 200 | |
| `summary` | string, ≤ 300 | one line, for lists and cards |
| `description` | Markdown | the back-of-the-box blurb |
| `authors` | list (≥ 1) of *person* | a person is a name, or `{name, role?, email?, url?}`; `role` is one of `author` (default), `editor`, `cartographer`, `artist`, `playtester`, `translator`, `contributor` |
| `publisher` | `{name, url?}` | |
| `release` | `{version, date?, notes?}` | `version` is [semver](https://semver.org) of the *content* (`1.2.0`), distinct from the format's `version`; `date` is a calendar date ✱; `notes` is a Markdown changelog |
| `created`, `updated` | timestamp ✱ | RFC 3339 with an explicit offset (`2026-10-17T15:30:00Z`, `…+02:00`) or a plain date. It must be a real date, and `updated` must not be earlier than `created` (compared in UTC). A timestamp more than a day in the future is a warning |
| `system` | id | the game-system tag that keys entity stat blocks (`adnd2e`) |
| `system_name` | string | display name (`AD&D 2nd Edition`) |
| `setting` | string | |
| `language` | BCP 47 tag | `en`, `en-GB`, `nl-BE` |
| `party.size` | *range* of integers ≥ 1 | suggested number of player characters |
| `party.levels` | *range* of integers ≥ 1 | suggested character levels |
| `party.notes` | string | e.g. "a cleric helps" |
| `duration.sessions` | *range* of integers ≥ 1 | |
| `duration.hours` | *range* of numbers > 0 | |
| `tags`, `content_warnings` | list of unique strings | |
| `license` | string, or `{spdx?, name?, url?, attribution?}` with `spdx` or `name` | e.g. `{ "spdx": "CC-BY-4.0" }` |
| `homepage` | `http(s)` URL | |
| `cover` | `asset:<id>` ✱ | must be an image asset; a GM-only cover is a warning |

A *range* is a single value (`4`) or `{min, max, recommended?}`. The
validator requires min ≤ recommended ≤ max ✱.

`dungml_scenario.normalise_metadata(manifest)` (and `dscn info --json`)
returns the canonical form: every author as an object, every range as
`{min, max, recommended?}`, the licence as an object. An earlier draft's
`levels` (free text) and `revision` (integer) are now `party.levels` and
`release.version`; the validator flags them with a pointer.

---

## 4. Maps

### 4.1 Sources

Map files are ordinary `.dmap` sources and are stored verbatim, as dungml
stores them. A bundle MAY contain several maps. Exits between maps
(`exit at X,Y { to "level-2" at TX,TY }`) refer to the other map by its
`maps[].name`, so they resolve inside the bundle.

### 4.2 Vendored libraries

**Every include a map uses MUST be in the bundle** as a `role: "library"`
map, even when dungml also ships it (`core.dmap`, `crypt.dmap`, …). This
makes renders reproducible: a scenario exported today must not change when
the importer's `core.dmap` is edited. It also matches how the backend already
works, where `project_include_sources` resolves includes by `Map.name` among
sibling maps.

- Include names resolve **only** within the bundle. The validator does not fall back to dungml's bundled `includes/` directory. If it finds a dangling include, it reports an error and points to `dscn vendor`, which copies the missing libraries in.
- On import into dungml, a bundled library **replaces** the project's same-named library. This includes the seeded `core.dmap` copy.

### 4.3 Node references

Keys and refs point at dungml **graph node ids**: `room.<name>` and
`corridor.<name>` (see `graph.py`). These are stable for as long as the
author keeps the room or corridor name. Doors, which are keyed by position,
can't be referenced in v1.

---

## 5. Text

### 5.1 Files

Text files are CommonMark with GitHub extensions (tables, strikethrough), and
may start with optional YAML front matter:

```markdown
---
title: Level 1 — keyed encounters
audience: gm          # overrides the manifest default for the whole file
---
```

The manifest's `audience` wins over front matter when both are present. Writers
SHOULD set it in the manifest only.

### 5.2 Keyed sections (R12, R13)

```markdown
## W101. Dwarven Guard Post {#w101}

> Two stone benches flank a narrow arrow slit. The air smells of old
> pipe smoke and something worse.

The sergeant ([[npc:dwarf-sergeant]]) has been dead for a decade; his
ghost ([[monster:ghost]]) manifests if the benches are disturbed.

![](asset:guard-post-art)

**Treasure:** 40 gp in a loose stone (search, 1-in-6).
```

- **Section.** A section starts at a heading and runs to the next heading of the same or a higher level. Any heading level works.
- **Key and anchor.** The key is the heading text before the first `. ` or `: ` (here `W101`), but only on a heading of level 2 or deeper (a `#` heading is a document title) and only when that prefix looks like a key: no spaces, at most 12 characters, and at least one digit. That keeps `Dr. Who's lair` and `Note: …` from becoming keys. The explicit `{#anchor}` attribute is preferred; without it the anchor is the key lowercased and slugged (`w101`). An explicit anchor on any heading makes it a `text:` ref target. A heading with neither is an ordinary heading.
- **Read-aloud.** The blockquote(s) that come straight after the heading, with nothing in between, are the read-aloud (boxed) text. They count as `player`-safe even when the file is `gm`, because the GM reads them out. Everything else in the section is GM text. A blockquote further down is just a quote.
- **Duplicate anchors** within one text file are a validation error.

### 5.3 Auto-generated keys

When a text file has `map` set, every keyed section in it MAY be matched to a
node by name. In order:

1. a `keys[]` entry for that key, which always wins;
2. a node whose name equals the anchor (`room.w101`);
3. a node whose label or name equals the heading title, case- and punctuation-insensitive (`room.dwarven-guard-post`).

`dscn keys --suggest` prints the matches it finds as `keys[]` entries for the
author to review and commit. The validator never invents keys: in the bundle,
`keys[]` is the only source of truth.

### 5.4 References inside text

The ref syntax (§6) appears in two forms:

- links: `[the sergeant](npc:dwarf-sergeant)`, `![](asset:guard-post-art)`;
- the bare shorthand `[[npc:dwarf-sergeant]]`, which renders as the entity's name.

Ordinary `https:` links are allowed and left alone. Relative file links
(`../x.md`) are **not** allowed. Use `text:` refs instead.

---

## 6. References

Every cross-reference uses one syntax: `<kind>:<id>[#<fragment>]`.

| Kind | Resolves to | Fragment |
|---|---|---|
| `map:` | `maps[].name` | graph node id, e.g. `map:level-1#room.guard-post` |
| `text:` | `text[].id` | a section anchor, e.g. `text:keyed-l1#w101` |
| `key:` | `keys[].key` | — |
| `asset:` | `assets[].id` | — |
| `npc:` `faction:` `quest:` `rumor:` `secret:` `encounter:` `pregen:` | an entity id | — |
| `worldmap:` | `worldmaps[].name` | a feature path, e.g. `worldmap:region#orlane.temple` (opaque to dungml) |
| `monster:` `item:` `spell:` | **external**: a slug in the consuming system's reference DB (ttrpg2's `monsters.db`, …) | — |

- Ids are `^[a-z0-9][a-z0-9._-]*$` (ttrpg2's slug rule plus `.`). Keys such as `W101` are free text, up to 32 chars.
- Internal refs MUST resolve, and a dangling one is an error. External refs are not checked by the format validator. ttrpg2's importer checks them and reports unknown ones as warnings.

---

## 7. Entities (R11)

Each entity file is YAML (loaded with `safe_load` only) holding a **list** of
records. Every record has a shared core:

```yaml
- id: dwarf-sergeant           # REQUIRED, unique within its kind
  name: Sergeant Brokk Ironhew # REQUIRED
  audience: gm                 # optional, default gm
  summary: Dead guard captain, now a ghost bound to W101
  description: |               # Markdown; refs allowed
    …
  portrait: asset:brokk-portrait
  tags: [undead, dwarf]
  x-anything: …                # extension, preserved
```

Additional fields by kind:

| Kind | Extra fields |
|---|---|
| `npcs` | `role`, `faction` (ref), `location` (`key:`/`map:`/`text:` ref), `disposition` (initial; an integer such as ttrpg2's −100…100, or a label), `stats` |
| `factions` | `alignment`, `scope`, `goals` (a string or a list), `members` (refs), `clocks: [{name, segments?, filled?, days?, on_complete?}]` (initial values; `days` is ttrpg2's countdown) |
| `quests` | `giver` (ref), `scope`, `stakes`, `related: [refs]` |
| `rumors` | `text`, `truth` (`true`\|`partly_true`\|`false`\|`fabrication`), `source` (ref), `location` (ref) |
| `secrets` | `text`, `related: [refs]`. Secrets are always `gm`, and a `player` audience is an error. |
| `encounters` | `key` (ref), `kind` (`dungeon`, `road`, …), `table: [{roll, count, creature \| result, category, notes}]` or `fixed: [{count, creature, notes}]`, where `creature` is a `monster:` or `npc:` ref, `result` is free text for rows with no single creature, and `count` is a dice expression |
| `pregens` | `race`, `class`, `alignment`, `background` (strings), `level` (an integer, or a string such as `"3/3"`), `gear` (strings), `stats`. See §7.1. |

**Stats** sit in a block keyed by system. The key can be left out when it
equals the manifest `system`:

```yaml
  stats:
    adnd2e: { ac: 4, hd: 3, thac0: 17, hp: 18, attacks: "1d8", morale: 12, xp: 120 }
    # or simply:
    ref: monster:dwarf          # take the stats from the consumer's reference DB
    adnd2e: { hp: 22 }          # …with overrides
```

### 7.1 Pregens

`pregens` (in `entities/pregens.yaml`, refs `pregen:<id>`) are the module's pregenerated characters, which a party may
be made from. Delve added the kind in its faithful-modules work, as version 3 of the format. A pregen's race and
class are the book's words as printed (`½E`, `fighter/mage`), and its `stats.adnd2e` holds the sheet fields a character
is made with: `ability_scores`, `hp_max`, `ac`, `cls`, `levels`, `race`, `alignment`, `weapon_profs`, `nwps`, `skills`
and `spell_slots`. A pregen without an `audience` is for the players (Delve gives it `player` on import and on save);
a `gm` one is kept from the table.

```yaml
- id: ned
  name: Ned Shakeshaft
  race: human
  class: thief
  level: 3
  alignment: CN
  gear: [leather armour, short sword, thieves' picks]
  background: A young rogue from Saltmarsh.
  stats:
    adnd2e: { ability_scores: { str: 11, dex: 17, con: 12, int: 13, wis: 9, cha: 14 }, hp_max: 12, ac: 6 }
```

**An older reader** (a version 2 reader, such as dungml's at `a66a1bb`) refuses a version 3 bundle by its version:
"unsupported version 3". To give it one, drop `entities/pregens.yaml` and its manifest line and set `version` to 2.

**Authored values only.** Entities describe a scenario's *starting* state,
for example a faction clock's initial `filled` value or an NPC's initial
`disposition`. ttrpg2's exporter MUST drop accumulated play state (`notes_log`,
`started_day`, `revealed`, loyalty drift, and so on), as R1 requires.

---

## 8. Import and export flows

### 8.1 dungml (user-facing)

- **Export:** `GET /api/projects/{id}/export?format=dscn[&scenario_id=…][&include_sources=true]`. It writes every project map (libraries as `role: library`), vendors any bundled library a map still needs, adds the project's assets (sources only on request, R8), and puts back the text, entities, world maps and keys an imported scenario brought (§8.4). The id is the project's first scenario record, or a new one minted and saved on the first export, so repeated exports keep one id.
- **Import:** `POST /api/projects/import` also accepts `.dscn`. It works as follows:
  - It validates the whole bundle first and refuses with `422` and the diagnostics on any error; a broken container is `400`.
  - It creates a project, or updates the user's project that already holds this scenario id (§8.3).
  - It stores maps by name, libraries included.
  - It stores assets content-addressed.
  - It **keeps** text, entities, worldmaps and keys as opaque blobs, so a dungml round-trip is lossless even though dungml doesn't use them yet.

### 8.2 ttrpg2 import (R5)

`import_scenario(path, campaign_slug=None, overwrite=False)` in ttrpg2 takes
these steps. With no `campaign_slug`, it creates a new campaign named after
the scenario `title` (R17).

0. **Link (once per campaign, R16).** The GM links the campaign to a project with their own user login (`POST /campaigns/{external_id}/link`, user-authorized as today). If the upload answers `409` and `DUNGML_USER_TOKEN` (the GM's token; `dev-user` in static mode) is set, ttrpg2 creates a project with it, links it, and retries. Without that token it imports the local half and reports how to link.
1. **Validate** the bundle with `dungml_scenario.validate()`. It fails on errors and reports warnings.
2. **Upload** the whole `.dscn` to dungml at `POST /campaigns/{external_id}/scenario` (new, service-scoped). dungml:
   - rejects the upload with `409` if the campaign is not linked. It never creates a project for a service principal;
   - imports into the **linked** project and stores its maps and assets. If the linked project already has a different `scenario_id`, the new maps are added alongside, so one project can hold several scenarios; otherwise re-import rules apply (§8.3);
   - returns `{project_id, scenario_id, maps: {name: map_id}, default_map_id, created, updated, kept, warnings}`.
   - ttrpg2 then points the `/map` tab at `default_map_id` and, on a first import only, moves the party to `start.node`.
3. **Unpack** the local side into `campaigns/<slug>/`:

   | Bundle | ttrpg2 |
   |---|---|
   | `text/*` | `reference/<scenario-slug>/<same path>` (DM-only canon); text with `x-ttrpg2: {location: area/loc}` goes to `locations/area/loc.md` |
   | `keys[]` + `start` | `reference/<scenario-slug>/keys.json`, with each key's read-aloud and GM text pre-split and the uploaded map ids (§8.5) |
   | manifest, entity files | `reference/<scenario-slug>/scenario.json` and `entities/*.yaml`, verbatim — the canon re-import and export work from |
   | `entities/npcs` | `campaign.json` `npcs` (`label`, `slug`, the `stats.adnd2e` block flattened in, `stats_ref`) + `characters/<id>.md` |
   | `entities/factions`, `quests`, `rumors` | `campaign.json` + `state.json` (`faction_state`, initial `faction_clocks`). Quests arrive `paused` — a hook, not yet taken up |
   | `entities/secrets` | `secrets.json` (`revealed: false`, tagged `scenario`) |
   | `entities/encounters` | `table` ones → `campaign.json` `encounter_tables`; `fixed` (keyed) ones → their key in `keys.json` |
   | `worldmaps/*` | `maps/<name>.map` |
   | `assets` (image) | `images/` + `images/index.json` entries (`type: scene\|portrait`, `slug`) |
   | `assets` (`role: source`, non-image) | `reference/<scenario-slug>/<same path>` |
   | `maps` | not copied. Write `state.json["dungml"] = {source: "campaign", map_id: default_map_id, …}` |

   Every record ttrpg2 creates carries `scenario: <id>` (list records also `scenario_ref`), which is how a re-import recognises its own records.

4. **Merging into an existing campaign (R17):** a record whose id already exists in the campaign is
   reported and skipped, unless `--overwrite` is passed. It is never merged
   silently. Re-importing the *same* scenario (matching `id`) is not a
   collision; it follows §8.3.

### 8.3 Re-import (R9)

There are two levels of matching:

1. **The scenario `id`** is matched against `scenarios.scenario_id` in dungml (a new table, unique per project, so `create_all` makes it and no `ensure_columns` entry is needed) and, on the ttrpg2 side, against `reference/*/scenario.json`.
2. **Within the scenario,** maps match by `name`, assets by `id` (the project's asset key), and entities and text by `id`.

| Item | On re-import |
|---|---|
| Map in both | `source` replaced in place. **The Map row and its PlaySessions are kept, so discovery survives.** This is the same invariant `test_source_preserves_discovery` pins for the contract. |
| Map only in the new bundle | created |
| Map only in the old one | **kept**, with a warning. It is never deleted automatically. |
| Discovered nodes that no longer exist | left in the session, where they do no harm. |
| Assets | upserted by key. New bytes for a key replace the old ones; a file on disk is deleted only when no project references its hash. Project assets the bundle doesn't mention are kept. |
| Entities / text (ttrpg2) | Authored fields are updated. Play state is kept: NPC dispositions, character-sheet notes, running faction clocks, and a quest's status and log. The start node is applied on the first import only. |

### 8.4 Where keys and text live in dungml

dungml stores the bundle's manifest and its uninterpreted files (text,
entities, world maps) on a `scenarios` / `scenario_files` record, so it can
round-trip them (§8.1). It reads `keys[]` for two routes:

- `GET /campaigns/{ext}/maps/{map_id}/keyed?node=…` — service-scoped, the full keyed text (read-aloud and GM) for the referee.
- `GET /campaigns/{ext}/maps/{map_id}/read-aloud?token=…` — render-token authorized like `/render`, for the players' widget (below).

Showing boxed text in the editor when a room is clicked is a follow-up.

**Player-facing read-aloud (R18).** The embeddable widget's campaign mode
takes a `readAloudUrl` and shows the party room's read-aloud text under the
map, as plain text, **only** when the campaign's `show_read_aloud` setting is
on. The setting lives on the campaign link (`campaign_links.show_read_aloud`,
default `false`, added through `ensure_columns`). The GM sets it with
`PUT /campaigns/{ext}/settings` (user-authorized; the service can only read it
with `GET`).
Only the read-aloud blockquote (§5.2) is ever sent, never GM text. It is
sent only for nodes the session has discovered.

### 8.5 ttrpg2 using keys

`keys.json` lets ttrpg2 close the gap the survey found: nothing links
dungml rooms to module text today.

- `dungml_party_at(room)` returns a `keyed` block when the room is keyed: `{key, title, read_aloud, gm_text, npcs, encounter}`. It looks in `keys.json` first, then asks dungml's `/keyed` route (which covers scenarios imported straight into dungml).
- `module_key("W101")` (or a node id) returns the same block plus the node and map.
- `scenario_import` / `scenario_export` are the MCP tools; `python3 -m tools.scenario import|export|info` is the CLI.
- ttrpg2 finds `dungml_scenario` installed or at `DUNGML_SCENARIO_SRC` (default: the sibling `../dungml/packages/scenario/src`). Its interpreter has no dungml, so local validation skips the map checks (`maps-unchecked`) and dmap-server re-checks them on upload.

---

## 9. Assets (R10)

### 9.1 In the bundle

- **Allowed types:** `image/png`, `image/jpeg`, `image/webp`, `image/gif`, `image/svg+xml`, `application/pdf`, `text/plain`, `text/markdown`, `audio/mpeg`, `audio/ogg`. Readers reject anything else.
- **Type check:** the declared `type` must match the file's magic bytes.
- **Description (version 2):** every `attachment` asset has a `description`: what it shows and when it fits, for whoever runs the game to decide when to show it. It may be empty, but it must be there (`asset-description`). A version 1 asset has none; read its `caption` as the description.
- **SVG** with active content (script, `foreignObject`, `iframe`/`embed`/`object`, event handlers, `javascript:` or other non-image `data:` links, external `href`s, a `<use>` of anything but a `#fragment`, CSS `@import` or an external `url()`, a `DOCTYPE` that declares anything, such as an entity; a plain one naming the SVG DTD passes) is **rejected**, not sanitised. The picture is parsed as XML and every element and attribute read whatever its case or namespace prefix; one that isn't well-formed XML is rejected too. Scenario art never needs any of it, and a rejection can't be bypassed the way a sanitiser can.

### 9.2 In dungml

- **Table** `assets(id, project_id fk, asset_key, sha256, mime, size, original_name, audience, role, caption, created_at)`. It is a new table, so `create_all` handles it, and `(project_id, asset_key)` is unique.
- **Files** are stored at `$DUNGML_ASSET_DIR/<sha256[:2]>/<sha256>`. The default directory is `./dungml_assets`, relative to the CWD like `DUNGML_DB_URL`. Files are deduplicated across projects and removed only once no row references them.
- **Routes:** `GET /api/projects/{id}/assets` (list), `POST` (multipart upload: `file`, `key`, `audience`, `caption`, `role`; the type comes from the magic bytes), `GET …/{asset_key}` (bytes, `nosniff`) and `DELETE …/{asset_key}`. Uploads are capped by `DUNGML_MAX_UPLOAD` (default 512 MiB).
- **Render hook:** `marker … image "asset:<key>"` resolves to the project asset. In SVG renders the asset is **inlined as a data URI**. This keeps `GET …/render?token=…` self-contained, so a plain `<img>` still works with no extra auth. Fogged (player) renders only inline `player`-audience assets. A `gm` asset is left out of the fogged view, following the CLAUDE.md rule that GM-only content goes through `fog_of_war`.

---

## 10. Validation

`dscn validate PATH` and `dungml_scenario.validate()` report diagnostics
with severity `error` or `warning`, the same model as `dmap validate`.

**Errors:**
- the manifest or an entity file fails `scenario.schema.json` (an unknown field is only a warning);
- a manifest file is missing, or a path is unsafe;
- a sha256 or size doesn't match;
- in a version 2 bundle, an `attachment` asset has no `description` (`asset-description`);
- a map has a dungml *error* diagnostic, when parsed with includes resolved only within the bundle;
- an include is dangling;
- a `keys[].node` is not a node in the parsed map graph;
- an internal ref is dangling;
- an id is duplicated within a kind, or an anchor is duplicated within a file;
- a secret is marked `player`;
- an asset type is disallowed or doesn't match its magic bytes, or an SVG has active content.

Without dungml installed, the map checks (parse, includes, node ids) are skipped with a `maps-unchecked` warning.

**Warnings:**
- a map has dungml warnings;
- a file is in the container but not in the manifest;
- a `player`-audience text or asset references a `gm` asset or entity, so it would leak or show a broken image to players;
- a keyed text section has no `keys[]` entry;
- there is an unknown non-`x-` field;
- `requires.dungml` isn't satisfied by the local version.

---

## 11. Security on import

- **Zip-slip:** paths with `..`, absolute paths, drive letters and symlink entries are rejected.
- **Limits:** a cap on total uncompressed size (default 512 MiB), on per-file size (default 64 MiB) and on entry count (default 5000). A compression-ratio check guards against zip bombs.
- **Parsing:** YAML only through `safe_load` and JSON through the standard parser. Nothing in a bundle is ever executed.
- **SVG and MIME:** checked as in §9.1.
- **Bundle origin:** the bundle's `audience` markings are trusted to drive player visibility. Importers must still apply the GM default (R7) to anything left unmarked.

---

## 12. `packages/scenario` (R15)

- **Distribution and module:** `dungml-scenario`, module `dungml_scenario`.
- **Dependencies:** pure Python: `dungml` (the DSL, for parsing and the graph), `pyyaml`, `jsonschema` and `markdown-it-py`. It does **not** depend on the backend. The core (container, validation without maps, keyed text, refs) imports neither dungml nor markdown-it, so a consumer with only PyYAML and jsonschema can use it.

```
dscn new DIR --title T          # start a scenario directory
dscn info PATH                  # summary
dscn pack DIR OUT.dscn          # deterministic zip; refuses an invalid scenario (--force),
                                # drops role=source assets unless --include-sources
dscn unpack IN.dscn DIR
dscn validate PATH              # dir or zip
dscn vendor PATH                # copy missing include libraries into maps/lib/
dscn keys PATH [--apply]        # §5.3 candidate keys[] entries (--apply appends them)
dscn convert-module MODULE.md -o DIR [--id ID] [--map NAME] [--title T]
                                # ttrpg2 reference/*-module.md → keyed text: anchors on
                                # key headings, "(read aloud)" sections → blockquotes
dscn render PATH -o out.html    # like `dmap render-scenario`: each map + its keyed text
dscn upgrade X.dmapproj OUT.dscn
```

The Python API: `Bundle.load(path | bytes)` / `Bundle.new(title)`, with
`to_zip()`, `write_dir()` and mutators (`add_map`, `add_text`, `add_asset`,
`add_worldmap`, `set_entities`, `set_keys`); `validate(bundle)` /
`check(bundle) → Report`; `parse_text(md) → TextDoc` whose `sections` carry
`key, anchor, title, read_aloud, gm_md`; `keyed_texts(bundle)`; `vendor`,
`suggest`, `render_html`, `upgrade_dmapproj`; and `inline_marker_images`
for the `asset:` render hook.

---

## 13. Out of scope for v1

- play state and campaign snapshots (R1);
- references to doors, which have positional ids;
- a DSL `key` attribute (R2, planned);
- converting ttrpg2 world maps into the dungml DSL (R3);
- signing and encryption;
- localisation (multiple text languages);
- a module marketplace, remote URLs or streaming assets.

---

## 14. Milestones

Milestones 1–6 are done; 7 is open.

1. **Spec + schema.** This document.
2. **`packages/scenario` core:** schema, load, pack/unpack, validate and vendor, plus tests built on a sample bundle in `samples/`.
3. **Text tooling:** `convert-module` (run on `WGR1-module.md`), `keys --suggest` and `render`.
4. **dungml storage:**
   - the `assets` table and storage, the `scenarios` tables, and `campaign_links.show_read_aloud` in `ensure_columns`;
   - `.dscn` import and export on the user routes, with re-import semantics;
   - the `asset:` render hook.
5. **Service endpoint:** `POST /campaigns/{external_id}/scenario`. This is a new public contract route, so the ttrpg2 side lands together with it.
6. **ttrpg2:** `import_scenario`, `export_scenario` (from a campaign, with play state stripped), `keys.json` and the key-aware tools (§8.5).
7. **Later:** the DSL `key` attribute, the editor's key/text panel, and a read-aloud panel on ttrpg2's own `/map` tab (the dungml widget has one).

---

## 15. Open questions

None outstanding. The four questions from the first draft are now decided as
R16 (link first, then import), R17 (a new campaign by default, merging
allowed), R18 (read-aloud off by default, per campaign) and R19 (free-form
stats in v1).
