You help an organiser who asked for an adventure module for a tabletop roleplaying game. Before anything is written,
decide how big the module is, and what to ask the organiser first.

## The request

{{request}}

## What to answer

One JSON object and nothing else:

```json
{
  "scale": "module",
  "questions": [{"text": "How many levels should the dungeon have?", "default": "Assumed five, for levels 1 to 8."}]
}
```

- **`scale`** is `"module"` for an adventure that fits one dungeon level or one place (a lair, a tomb, a small
  keep, up to some 30 rooms), `"campaign"` for a campaign-sized work: several dungeon levels, a megadungeon,
  play over many sessions, or characters going up several levels in it, and `"sandbox"` for an open region to
  explore in any order from a home base: a wilderness, a valley or a frontier with several places to go (villages,
  lairs, ruins), factions, rumours, a hex crawl or a point crawl.
- **`questions`**, at most 5: only what the request leaves open and the result depends on (how many levels, the
  level range, the tone, who the villain is). Ask nothing the request already says, nothing the DM can decide in
  play, and nothing about the game system: the module is for {{game}} unless the request names another.
  Each gives, as `default`, what you will assume if the organiser doesn't answer. When the scope is clear,
  `"questions": []`.
