You write one level of a campaign-sized dungeon for a tabletop roleplaying game, for the DM to play: its keyed rooms
and its wandering monsters. The outline and the campaign's texts below are agreed; the other levels are written
separately, so keep to what the outline says of them.

## The request

{{request}}

## The outline

{{outline}}

## This level

{{level}}

## What to answer

One JSON object and nothing else:

```json
{
  "intro": "A paragraph for the DM: what this level is like, who holds it, light, sounds, what changes over time.",
  "rooms": [
    {
      "key": "{{letter}}1",
      "name": "Fallen Stair",
      "read_aloud": "What the characters see and hear when they come in, read aloud to the players.",
      "dm_text": "What only the DM knows: what is here, what happens, and the ways out (\"a door east to {{letter}}2\").",
      "monsters": "4 giant centipedes (AC 9, HD 1/4, hp 2 each, bite 1d1 and poison)",
      "treasure": "A dead adventurer's purse: 30 gp and a silver ring (25 gp)."
    }
  ],
  "wandering": {
    "check": "1 in 6 every two turns",
    "table": [{"roll": "1", "result": "1d4 giant rats"}, {"roll": "2", "result": "Maera Voss and two choristers"}]
  },
  "encounters": [{"id": "{{slug}}-centipede-nest", "name": "Centipede nest", "summary": "…"}]
}
```

- **Rooms**: about {{rooms}}, keyed `{{letter}}1`, `{{letter}}2`… in order, no two the same. **Every room's
  `dm_text` names its ways out** by key, so the map can be drawn from it, and every room can be reached.
- **The ways to the other levels** are these rooms, with these keys; each one's `dm_text` says where it leads:

{{connections}}
- Monsters, traps and treasure fit the level's range of character levels. Write monsters with their key stats
  (for {{game}}, unless the request names another game);
  `monsters` and `treasure` are text, or a list of texts, `""` when there are none.
- **`wandering`**: how often to check, and a table of 6 to 12 entries (`roll` as `"1"`, `"2–3"`…), drawn from the
  level's factions and creatures.
- `encounters` may be empty. An `id` is lowercase letters, digits and `-`.
- Every person is named from the outline or these names, by their race:

{{names}}

## The map

The level's map is drawn afterwards from its rooms' texts: plan rooms that can be laid out on a grid of 10-foot
squares, and give their sizes where it matters.
