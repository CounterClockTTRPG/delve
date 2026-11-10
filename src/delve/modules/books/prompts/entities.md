Below, between `<text>` and `</text>`, is one text of the role-playing adventure module “{{title}}”, in Markdown.
List the people, encounters, factions, quests and pregenerated characters it describes, as drafts for the module's
records. Take only what the text says, in its own words; invent nothing, and leave a field out when the text doesn't
give it.

Answer with one JSON object and nothing else:

```
{
  "npcs": [{"id": "…", "name": "…", "role": "…", "summary": "…", "location": "text:{{text_id}}#<anchor>",
            "stats": {"adnd2e": {"line": "the stat line as printed"}}}],
  "encounters": [{"id": "…", "name": "…", "summary": "…", "kind": "dungeon",
                  "fixed": [{"creature": "monster:<id>", "count": "2d4", "notes": "the stat line as printed"}],
                  "table": [{"roll": "1-2", "result": "…"}], "wandering": true, "where": ["text:{{text_id}}"]}],
  "factions": [{"id": "…", "name": "…", "summary": "…", "goals": ["…"], "members": ["npc:<id>"]}],
  "quests": [{"id": "…", "name": "…", "summary": "…", "giver": "npc:<id>", "stakes": "…"}],
  "pregens": [{"id": "…", "name": "…", "race": "…", "class": "…", "level": 3, "alignment": "…",
               "gear": ["…"], "background": "…", "description": "…",
               "stats": {"adnd2e": {"ability_scores": {"str": "18/76", "int": 15, "wis": 9, "dex": 14, "con": 13,
                                                       "cha": 11},
                                    "hp_max": 17}}}]
}
```

- One record per person, faction or quest, however often the text mentions them.
- An encounter's creatures go in `fixed`, one row per kind of creature, each with its `count` and
  its stat line as printed in `notes` ("AC 7; MV 9; HD 1-1; hp 4 each; #AT 1; D 1-6").
- A stat block in an appendix (or a list of stat blocks) of a person the text names elsewhere is that person's NPC
  record, with the same `name` as printed: give its stat line in `stats`, and make no second person of it.
- Give each record its `location`, as `text:{{text_id}}#<anchor>`, when the text places it in a keyed area.
- A wandering-monster or random-encounter table is an encounter with `"wandering": true` and its `table`. Give it
  `where` when the text says where it is rolled: `["text:{{text_id}}"]` for the whole of this text (a level, a
  region), or `["text:{{text_id}}#<anchor>"]` for one keyed area of it; leave `where` out when it is for the whole
  module. A table of one room's own (a pool, a trap, a throne) isn't wandering: give it that room's `location`.
- A roster of pregenerated characters (a table of characters for the players to take) gives `pregens`, one per row:
  its name, race, class, level and alignment as printed ("½E", "F/M", "3/3", "CG"), the ability scores and hit points
  in `stats.adnd2e` (`ability_scores` with `str`, `int`, `wis`, `dex`, `con` and `cha`, a score such as "18/76" as
  printed, and `hp_max`), and the gear one item per line in `gear`. Put in `background` only what the player who takes it
  may read: who the character is, as the roster tells it to the players. The book's notes meant for the DM about it (a
  secret, a hidden aim, a hook, how to play it) go in `description`, never in `background`.
- A pregenerated character is never an NPC too: characters for the players are not NPCs.
- Every record has an `id` (lowercase letters, digits, `.`, `_` or `-`, starting with a letter or digit) and a `name`.
- A reference is `<kind>:<id>`: `npc:`, `faction:`, `quest:`, `pregen:`, `monster:`, or `text:{{text_id}}#<anchor>` for a place in
  this text, where the anchor is the one in its heading's `{#…}`.
- `stats` is keyed by the game system (`adnd2e` for AD&D 2nd edition), and holds the stat line as printed in `line`.
- A kind the text has none of is an empty list.

<text>
{{text}}
</text>
