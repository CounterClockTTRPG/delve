You write one place of an open sandbox for a tabletop roleplaying game, for the DM to play: its keyed rooms or spots,
and what goes on there. The outline below is agreed; the other places are written separately, so keep to what the
outline says of them, and of the people, the factions, the rumours and the secrets.

## The request

{{request}}

## The outline

{{outline}}

## This place

{{site}}

### Who is found here

{{people}}

### Clues to plant here

These belong to the region's secrets. Put each one into a room's `dm_text` (or what the party can see or be told
there), plainly enough for the DM to notice, and without saying it is a clue or giving the secret away:

{{clues}}

### Rumours about this place

What the villagers say. Where a rumour is false or partly true, this place shows how it is wrong:

{{rumours}}

## What to answer

One JSON object and nothing else:

```json
{
  "intro": "A paragraph for the DM: what the place is like, who holds it, how they react to strangers, what changes when the factions move.",
  "rooms": [
    {
      "key": "{{letter}}1",
      "name": "The Landing",
      "read_aloud": "What the characters see and hear when they come in, read aloud to the players.",
      "dm_text": "What only the DM knows: who and what is here, what they want, what happens, and the ways out (\"a door north to {{letter}}2\"; the first room also names the way back to the region).",
      "monsters": "2 ferry-hounds (AC 7, HD 1+1, hp 7 each, bite 1d6)",
      "treasure": "A strongbox of 40 sp under the boards."
    }
  ],
  "wandering": {
    "check": "1 in 6 every hour",
    "table": [{"roll": "1", "result": "…"}, {"roll": "2", "result": "…"}]
  },
  "encounters": [{"id": "{{slug}}-dogs", "name": "The ferry dogs", "summary": "…"}]
}
```

- **Rooms**: about {{rooms}}, keyed `{{letter}}1`, `{{letter}}2`… in order, no two the same. In a settlement a room
  is a building or a yard; outdoors, a spot. `{{letter}}1` is where the party arrives. **Every room's `dm_text`
  names its ways out** by key, so the map can be drawn from it, and every room can be reached.
- The people listed above are here, as the outline says; anyone else is named from the outline or these names, by
  their race, used as they are:

{{names}}
- Monsters, traps and treasure fit the party's levels. Write monsters with their key stats (for {{game}}, unless
  the request names another game); `monsters` and `treasure` are text, or a list of texts, `""` when there are none.
  Not every room has a monster: some have people to talk to, something to find, or nothing at all.
- **`wandering`**: only for a place where something roams (a lair, a ruin, a wood): how often to check, and a table
  of 4 to 8 entries; `{}` for a settlement or a quiet place.
- `encounters` may be empty. An `id` is lowercase letters, digits and `-`.
- Keep to the outline's tone. No stock filler (rats in the cellar, a chest that is a mimic, a skeleton that rattles
  for no reason): what is here is here for a reason the DM can see.
- Write nothing about how the module was made, and no notes to the DM about the outline.

## The map

The place's map is drawn afterwards from its rooms' texts: plan rooms that can be laid out on a grid of 10-foot
squares (a village's buildings and lanes too), and give their sizes where it matters.
