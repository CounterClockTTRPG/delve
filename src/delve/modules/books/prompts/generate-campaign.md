You write the campaign-wide texts of a campaign-sized adventure for a tabletop roleplaying game, for its DM. The
outline below is agreed; its levels are written separately, so write nothing here that belongs to a single room.

## The request

{{request}}

## The outline

{{outline}}

## What to answer

One JSON object and nothing else:

```json
{
  "texts": [
    {"title": "History", "markdown": "The place's history, in Markdown, with `###` headings where it helps."}
  ],
  "npcs": [{"id": "maera-voss", "name": "Maera Voss", "role": "envoy of the Salt Choir", "faction": "faction:salt-choir",
            "summary": "What she wants, what she knows, and how she behaves."}],
  "factions": [{"id": "salt-choir", "name": "The Salt Choir", "summary": "…", "goals": ["…"], "scope": "levels A–B"}],
  "quests": [{"id": "the-way-up", "name": "The way up", "summary": "…", "stakes": "…"}]
}
```

- **Texts**, each a section of the campaign book in Markdown, its headings `###` and deeper: at least the history,
  the factions and how they relate, the campaign's thread (and anything the request makes central, such as an
  intelligent item: its personality, agenda, goals and the powers it unlocks as the party rises), where to buy and
  sell, the magic items placed across the levels (by level, fitting their level range), the surprises, and how the
  campaign ends. Write what the request asks for, in the detail it asks.
- **`npcs`**, **`factions`** and **`quests`** are the campaign's own, with the ids the outline uses. An `id` is
  lowercase letters, digits and `-`; a reference to another is `faction:<id>`, `npc:<id>` or `quest:<id>`.
- Every person is named from the outline or these names, by their race:

{{names}}
