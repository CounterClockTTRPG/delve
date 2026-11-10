PIECE: {piece}

# Sorting the book into its parts: the lead's brief

The book was converted from its PDF into Markdown drafts (`draft/*.md`) by an automatic converter. It lost text, put
text in the wrong rooms, levels and texts, left OCR errors, and wrote room keys inconsistently. You are the lead: you
find the book's parts and their key schemes, and re-sort every keyed section of the drafts into its part, so the
cleaning agents each start from one draft per part. You don't clean the text (that is the next stage): you move it.

Your piece is `sort` or `sort-orphans`. For `sort`, do **The sort** below; for `sort-orphans`, do only **The orphans**.

## The sort

1. **Keep the drafts as they are**: write `original.md`, every file of `draft/` in name order, each starting with a
   line `<<<TEXT <file name without .md>>>>`. The cleaning agents look there for lost paragraphs.
2. **Find the parts.** Read the book: `classes.json`, the map pages (`scan/`), the pages around them, and the text
   layer of every page (`pages/ocr-NNN.txt`; Read the page images where the text layer is thin or odd). A part is one
   text of the module, in the book's order:
   - `level`: a dungeon level or another keyed place with its own map (a house, a ship, a cave system);
   - `area`: a keyed region without its own map, or one that shares another part's map;
   - `chapter`: the book's unkeyed chapters (the introduction, the adventure's background, an encounter chapter);
   - `front`: the front matter (title page, credits, contents), when it holds anything the DM needs;
   - `appendix`: new monsters, magic items, pregenerated characters, tables, at the end.
   Each keyed part has a **key pattern**: a Python regular expression, anchored with `^` and `$`, that matches exactly
   its keys as the book prints them: `^\d+[a-z]?$` (12, 33a), `^[A-Z]\d+$` (A3), `^W[1-9B]\d\d[a-e]?$` (W501, WB05).
   Keys may repeat across parts (rooms 1, 2, 3 of a house and of a ship): give each part the pattern of its own keys,
   and its own pages, so the checker keeps them apart.
3. **Find the maps.** Every map page of a keyed place gives one map per level it shows (a page that prints two levels
   gives two maps). Each map has a name (lower case, digits and `-`, unique in the book: `house-ground-floor`,
   `caves-level-2`), the title the book gives it, its PDF page, and which drawing on the page it is when the page holds
   several (`level`: the words the book prints over it, such as "Upper Floor"; null when it is the page's only map).
   **World, region and overland maps** (a wilderness, a town seen from above, the lands around) are never traced: list
   their pages under `pictures`, as page numbers (`[3]`), and Delve attaches them as pictures.
4. **Write `parts.json`**:

   ```json
   {
     "parts": [
       {"id": "house", "title": "The Haunted House", "kind": "level", "audience": "gm", "pages": [4, 12],
        "key_pattern": "^\\d+[a-z]?$", "map_pages": [10],
        "maps": [{"name": "house-ground-floor", "title": "The House, Ground Floor", "page": 10, "level": "Ground Floor"}],
        "order": 1}
     ],
     "pictures": [3]
   }
   ```

   - `id`: lower case, digits and `-`, unique; it names the part's files (`draft/house.md`, `clean/house.md`).
   - `title`: the text's title, as the book prints it.
   - `audience`: `gm` for the DM's text, `player` for a text the book means for the players (a handout, a players'
     introduction).
   - `pages`: the first and last PDF page of the part's **text**; `map_pages`: the pages of its maps.
   - `key_pattern`: null for an unkeyed part.
   - `order`: the part's place in the book, from 1. Every page of the book's text belongs to some part.
5. **Re-sort the drafts.** For every part, write `draft/<id>.md`:
   - first `# <the part's title>`, then the part's introduction (every paragraph the book prints under its title,
     before its first key);
   - every keyed section of the drafts that belongs to the part (by its key, its page and its content), in the book's
     order, under one heading per key in the form `## <KEY>. <optional title> {#<key in lower case>}`: `## 12. Kitchen
     {#12}`, `## W211. Giant Ant Complex {#w211}`, `## 33a. (locked) {#33a}`. Fix OCR'd keys (`l2` → `12`,
     `PlO8` → `P108`);
   - the unkeyed sections in their place.
   Take every keyed section out of the text it was wrongly in. Move text, don't rewrite it. Then empty every file of
   `draft/` that isn't a part's (Write it with nothing in it: you can't delete files), so only the parts' drafts hold
   text, and no text is lost: what was in the drafts is in some part's draft.
6. **Write `keys/<id>.txt`** for every keyed part: its keys, one per line, in the book's order, gathered from the drafts,
   from `{qa} keys pages --pattern '<the part's key pattern>' --first <first page> --last <last page> --out
   work/{piece}/keys-<id>.json` (with `--stop` for the other parts' patterns when they share pages), and from the
   numbers printed on the part's maps.
   It can hold a stray or miss one; the tracers check it against the map.
7. **Check**: `parts.json` loads, every part has its draft, every keyed part its keys file, and
   `{qa} textcheck parts.json draft/*.md` runs. Its flags are the cleaning agents' work; a flag that shows a section
   in the wrong part is yours: move it.

## The orphans

The cleaning agents put text that belongs to another agent's parts into `clean/<piece>-orphans.md`, each piece under a
line `=== goes to <part id>, after <key or heading>`. Place every piece into `clean/<part id>.md` where it says
(check the place against the page image; the line can be wrong), keeping the heading form, then empty each orphans
file you placed (Write it with nothing in it: you can't delete files). Run
`{qa} textcheck parts.json clean/<part id>.md` on each file you changed. Don't drop anything.

## What to report back

`sort`: the parts (id, kind, pages, key pattern, maps), the pictures, and what you moved between texts. `sort-orphans`:
what you placed where. Your doubts go in `doubts/{piece}.json` (see below).
