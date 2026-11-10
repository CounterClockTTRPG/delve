You plan a campaign-sized adventure for a tabletop roleplaying game: a dungeon of several levels, played over many
sessions. This is the outline only: each level is written afterwards, one at a time, from it, and the campaign's own
texts (history, factions, trade, magic items) too. Keep each part short; the details come later.

## The request

{{request}}

## What to answer

One JSON object and nothing else:

```json
{
  "title": "The Weeping Deep",
  "summary": "Three or four sentences for the DM: what the place is, what is going on, and how the campaign ends.",
  "party": {"size": {"min": 4, "max": 6}, "levels": {"min": 1, "max": 9}},
  "history": "A paragraph: why the place is here, who built it, what happened since.",
  "thread": "A paragraph: the campaign's thread, what drives the party from level to level and how it ends.",
  "factions": [
    {"id": "salt-choir", "name": "The Salt Choir", "summary": "Who they are and what they want.",
     "levels": ["A", "B"], "relations": "Feud with the Delvers; trade with the Lamplighters."}
  ],
  "levels": [
    {"letter": "A", "name": "The Collapsed Gallery", "levels": {"min": 1, "max": 2}, "rooms": 16,
     "summary": "Two or three sentences: what this level is, who holds it, what the party finds or learns here."}
  ],
  "connections": [{"from": "A14", "to": "B1", "how": "A cracked shaft, climbable with a rope."}]
}
```

- **Levels**: between 2 and {{max_levels}}, in the order the party meets them, each with a capital `letter` (A, B,
  C…), its character level range (`levels`), and how many keyed rooms it gets (`rooms`, 8 to {{max_rooms}}).
- **Connections** join the levels: each from a room of one level to a room of another, by key (the level's letter and
  a number: `A14`, `B1`). Every level can be reached from the first. A level's rooms are numbered from 1.
- **`party`** is the party the request asks for: `size` and `levels`, each a number or `{"min": …, "max": …}`, and
  `notes`. Give only what the request says or the outline needs.
- **Names:** every person (NPCs, and anyone the texts name) is named from these lists, rolled for this campaign, by
  their race. Use each name as it is.

{{names}}
- Answer with the JSON only. Only when something is still open that the DM should decide, add after the JSON at most
  5 questions, each with what you assumed, in one fenced `questions` block:

  ```questions
  [{"text": "Should the Salt Choir be open to bargaining?", "default": "Assumed they bargain for salt."}]
  ```
