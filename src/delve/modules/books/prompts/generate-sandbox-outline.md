You plan an open sandbox for a tabletop roleplaying game: a region the party explores from a home base, in whatever
order it likes, over many sessions. There is no plot to follow. The region has people who want things, places worth
going, rumours that point several ways (not all true), a few secrets that the party may find or never find, and
ground left open on purpose so the DM can add places later. This is the outline: each place is written afterwards,
one at a time, from it, and the region map is drawn from its coordinates.

## The request

{{request}}

## What to answer

One JSON object and nothing else:

```json
{
  "title": "The Sallow Reach",
  "summary": "Three or four sentences for the DM: what the region is, what is wrong in it, and who is pushing at whom.",
  "party": {"size": {"min": 3, "max": 6}, "levels": {"min": 1, "max": 3}},
  "intro": "Two paragraphs for the DM: the region's look and weather, its history in a few lines, and how it feels to travel.",
  "region": {"width": 24, "height": 18},
  "terrain": [
    {"kind": "forest", "name": "Hollin Wood", "points": [[12, 9], [20, 8], [22, 14], [14, 16]]}
  ],
  "rivers": [{"name": "The Lisk", "points": [[0, 6], [10, 7], [24, 5]]}],
  "sites": [
    {"letter": "A", "name": "Corve", "kind": "village", "at": [4, 4], "rooms": 6, "home": true,
     "summary": "Two or three sentences: what the place is, who is there, what they want, and why the party would go."}
  ],
  "routes": [{"from": "A", "to": "B", "way": "road", "miles": 6, "danger": 1, "note": "Carters, a shrine at the halfway oak."}],
  "factions": [
    {"id": "the-tithe", "name": "The Tithe-house", "want": "What they want, in one sentence.",
     "summary": "Who they are, how many, where (by site letter), what they can do.",
     "clock": ["What they do first if nobody stops them.", "Then.", "Then: how the region has changed."],
     "relations": "How they stand with the other factions."}
  ],
  "npcs": [{"id": "osla-renn", "name": "Osla Renn", "role": "ferrywoman, human", "site": "B",
            "summary": "Wants: one sentence. Secret: one sentence. How she talks or what she does with her hands."}],
  "rumours": [
    {"text": "As a villager says it, in one or two sentences.", "truth": "false",
     "really": "What is actually so.", "points": ["C"]}
  ],
  "secrets": [
    {"id": "the-second-bell", "name": "The second bell", "strange": true,
     "truth": "What it is, in two or three sentences.",
     "clues": [{"site": "B", "clue": "Where and how the party might notice it."}, {"site": "E", "clue": "Another way in."}],
     "unfound": "What happens if nobody ever finds it (often: nothing, and that is fine)."}
  ],
  "open_ground": [{"name": "The Long Meadow", "at": [14, 3], "idea": "Half a day of grass; good for a farmstead or a stone ring."}],
  "wandering": {
    "check": "once per leg of a journey: 1 in 6 on danger 1–2, 2 in 6 on danger 3, 3 in 6 on danger 4–5",
    "table": [{"roll": "1", "result": "…"}, {"roll": "2", "result": "…"}]
  }
}
```

### The region and its map

- **`region`** is the map's size in miles (`width` 16 to 40, `height` 12 to 30); `(0,0)` is the top-left corner,
  `x` grows east and `y` south. Every coordinate below is in those miles.
- **`terrain`**: 3 to 8 areas, each a `kind` (`forest`, `hills`, `marsh`, `water`, `fields`, `moor`, `mountains`), a
  name, and a polygon of 3 to 8 points. Areas may touch; leave some ground between them plain.
- **`rivers`**: 0 to 3, each a line of 2 to 8 points, from one edge of the map or a lake to another.
- **`sites`**: 6 to 9 places, each a capital `letter` (A, B, C…, in no particular order; the home base is usually
  `A`), a `kind` (village, hamlet, farmstead, inn, lair, ruin, tower, barrow, mine, shrine, camp, cave, manor…), its
  point `at`, and how many keyed rooms or spots it gets (`rooms`, 3 to 10). Exactly one is the `home` base, a
  settlement with somewhere to sleep, buy and hear rumours. Places are at least 3 miles apart.
- **`routes`** join the sites: `way` is `road`, `track`, `path` or `none` (cross-country), `miles` is the distance
  along the way (at least the straight line), `danger` 1 (safe) to 5 (deadly), and a `note` on what is on the way.
  Every site can be reached from the home base. The home base has 2 to 4 routes; give the far places more than one
  way in where it makes sense.
- **`open_ground`**: 2 to 4 named stretches left unwritten on purpose, each at a point on the map clear of the
  sites, with one line of what could go there.

### The people

- **`factions`**: 2 to 4 groups, at least one not hostile on sight, each with what it `want`s and a `clock` of 3 or 4
  steps it takes if the party does nothing, the last one changing the region for good. Their wants clash: each one's
  success hurts at least one other.
- **`npcs`**: 8 to 14, each with the `site` letter where they are found, a `role` with their race, and a `summary`
  with what they want, one secret, and one thing that makes them easy to play. Some NPCs belong to no faction.
- **Names:** every person is named from these lists, rolled for this region, by race. Use each name as it is; a
  byname, if anyone needs one, comes from what they did, never from violence or body parts.

{{names}}

### Rumours and secrets

- **`rumours`**: exactly 12, as a villager would say them. `truth` is `true`, `partly` or `false`; 3 or 4 are false
  and 2 or 3 partly true, and each false one is wrong in a way that sends the party somewhere interesting. `really`
  says what is so; `points` lists the site letters it sends the party to. Between them the rumours point to every site.
- **`secrets`**: 3 to 5. Each is true whether or not the party finds it, has 2 or 3 `clues` at different sites, and
  needs none of the others. At least one is `strange`: something uncanny, old or not of this world, kept small
  and specific (a thing that happens, not a world-ending threat). The others may be mundane. Nothing in the region
  depends on a secret being found.
- **`wandering`**: the road and wilderness table, 8 to 12 entries (`roll` as `"1"`, `"2–3"`…), mostly people and
  creatures of this region doing something (a faction step in progress, a traveller with a need, a sign of a
  secret), not just monsters to fight.

### Avoid the stock pieces

The first idea for a sandbox is usually a list of stock pieces: giant rats in the inn's cellar, a corrupt tax
collector, a goblin tribe with a bugbear enforcer, a cult that poisons the wells and sells the cure, an abandoned mine
with giant spiders, bandits in a ruined watchtower, a barrow of skeletons with a ghoul, a hermit wizard in a tower, a
dragon. Use none of these as they stand. For every faction and site, think of the obvious version and then write a
more specific one that comes from this region's own history, trade, weather or land. Keep it grounded: ordinary
people with ordinary motives, monsters with a reason to be where they are. At least two sites are not mainly fights
(a place to bargain, to learn, to trade or to rest). Monsters and danger fit the party's levels; the riskiest places
say so in their summary.

### Questions

- Answer with the JSON only. Only when something is still open that the DM should decide, add after the JSON at
  most 5 questions, each with what you assumed, in one fenced `questions` block:

  ```questions
  [{"text": "Should the Tithe-house be open to bargaining?", "default": "Assumed they bargain for grain."}]
  ```
