You describe a role-playing adventure module for a catalogue of modules. Its whole text, “{{title}}” in Markdown,
is between `<text>` and `</text>` below: its front matter (the cover, the title page, the credits) and its chapters.
Take only what the text says or plainly shows; invent nothing, and leave a field out when the text doesn't give it.

Answer with one JSON object and nothing else:

```
{
  "subtitle": "…",
  "summary": "one line for the players: what the adventure is about, without its secrets",
  "description": "a short paragraph for the players, in your own words, as a back cover would: no spoilers",
  "authors": [{"name": "…", "role": "author"}],
  "publisher": {"name": "…"},
  "system": "adnd2e",
  "system_name": "AD&D 1st Edition",
  "setting": "Greyhawk",
  "language": "en",
  "party": {"levels": {"min": 1, "max": 3}, "size": {"min": 4, "max": 7}, "notes": "…"},
  "duration": {"sessions": {"min": 2, "max": 4}},
  "tags": ["N1", "village", "cult", "AD&D 1e"],
  "content_warnings": ["…"]
}
```

- `authors`: every person the credits name, each with their `role` as the credits give it: `author`, `editor`,
  `artist`, `cartographer`, `contributor` or another single word. A person with two roles is listed twice.
- `system` is `adnd2e` for any edition of (Advanced) Dungeons & Dragons and its clones; `system_name` names the
  edition or game the book says it is for. Leave both out for another game.
- `setting`: the campaign world it is set in, by its usual name (`Greyhawk`, `Forgotten Realms`, `Mystara`…), only
  when the text names or plainly uses it.
- `party`: the character levels and the number of characters the book recommends, as whole numbers (a single level
  is `{"min": 5, "max": 5}`); `notes` for what else it advises, such as the classes it needs.
- `duration`: only when the text says how many sessions or hours it takes.
- `tags`: the module's code when it has one (`S1`, `B2`, `WGR1`), then three to six short words for its kind of
  adventure and its places (`megadungeon`, `wilderness`, `city`, `investigation`), then the edition (`AD&D 1e`,
  `AD&D 2e`, `D&D Basic`).
- `content_warnings`: only for what a player might want to know before playing (`character death`, `body horror`,
  `torture`); none for ordinary fighting.
- Write the `summary` and the `description` in your own words; never copy the book's text.

<text>
{{text}}
</text>
