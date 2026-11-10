You write a small adventure module for a tabletop roleplaying game, for the DM to play at once. Write what the request
below asks for: as many rooms, as much story and as much treasure as it asks, and no more. "No plot" means a place
to explore and fight in, with no story to follow. Treasure is what the request asks for, written out (the DM rolls
nothing from tables for it).

## The request

{{request}}

## What to answer

A plan for the module, as one JSON object and nothing else:

```json
{
  "title": "The Kobold Caves",
  "summary": "Two or three sentences for the DM: what the place is and what is going on in it.",
  "party": {"size": {"min": 4, "max": 6}, "levels": {"min": 1, "max": 3}, "notes": "needs a cleric"},
  "rooms": [
    {
      "key": "1",
      "name": "Entrance",
      "read_aloud": "What the characters see and hear when they come in, read aloud to the players.",
      "dm_text": "What only the DM knows: what is here, what happens, and the ways out (\"a door east to area 2\").",
      "monsters": "6 kobolds (AC 7, HD 1/2, hp 3 each, short swords)",
      "treasure": "A pouch of 40 sp under the altar."
    }
  ],
  "npcs": [{"id": "grik", "name": "Grik", "role": "kobold chief", "summary": "Cowardly, greedy, bargains for his life."}],
  "encounters": [{"id": "hall-guards", "name": "Hall guards", "summary": "The kobolds who guard the hall."}]
}
```

- **Keys** are short and have a digit: `1`, `2`, `3`, or `A1`, `B2` for a second level. No two rooms share a key.
- **Every room's `dm_text` names its ways out** by key, so the map can be drawn from it. Every room can be reached.
- `monsters` and `treasure` are text, or a list of texts; leave them `""` when there are none.
- `npcs` and `encounters` may be empty lists. An `id` is lowercase letters, digits and `-`.
- **`party`** is the party the request asks for: `size` (the number of characters) and `levels`, each a number or
  `{"min": …, "max": …}`, and `notes`. Give only what the request says, and `{}` when it says nothing about the party.
- **Names:** every person in the module (NPCs, and anyone the texts name) is named from these lists, rolled for this
  module, by their race. Use each name as it is.

{{names}}
- Answer with the JSON only. Only when the request leaves something open that the DM should decide (who the
  villain is, how dangerous the place is), add after the JSON at most 5 questions, each with what you assumed, in one
  fenced `questions` block:

  ```questions
  [{"text": "Should Grik bargain or fight to the end?", "default": "Assumed he bargains for his life."}]
  ```

## The map language

The map is drawn afterwards from the rooms' texts, in this language; plan rooms that can be laid out on a grid.

{{reference}}
