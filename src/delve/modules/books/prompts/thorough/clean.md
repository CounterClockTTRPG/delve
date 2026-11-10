PIECE: {piece}

# Cleaning the texts: the shared brief

The book was converted from its PDF into Markdown by an automatic converter. It lost text, put text in the wrong rooms,
levels and texts, left OCR errors, and wrote room keys inconsistently. The lead agent has already re-sorted every room
key into its part and normalised the headings: those drafts are your starting point. Your job is to make each of your
files **the book's text, complete, in the book's order, in the right file**.

Your parts (each a file; `parts.json` has every part of the book, its pages and its key pattern):

{parts}

- The drafts: `draft/<id>.md`. **Copy each of your files to `clean/<id>.md` and edit only the copy.**
- The book's pages as images: `pages/p-NNN.png`. They are the truth. A book often prints two or three columns per
  page; a key's text can run onto the next column or page.
- The book's text layer, one file per page: `pages/ocr-NNN.txt` (good for copying text, but it has OCR errors;
  correct them).
- The checker: `{qa} textcheck parts.json clean/<id>.md …` lists, per file, the keys the book has for the file's part
  but the file lacks, the sections whose words cover less than 85% of the book's entry (text lost), the sections with
  over 25% of words not in the book's entry (text from elsewhere), and headings in the wrong form. A low score can be
  the text layer's fault (it missed the next key's number and ran on): check the page image before you change
  anything.
- The book's entries for a part, by key: `{qa} keys pages --pattern '<the part's key pattern>' --first N --last M
  --out work/{piece}/keys-<id>.json`, then Read that file.
- The original (pre-sort) Markdown of the whole module, for finding where a lost paragraph went: `original.md`
  (`<<<TEXT <name>>>>` lines start each original text).

## The form of a text

```
# <the part's title, exactly as in parts.json>

The part's introduction: every paragraph the book prints under its title, before its first key.

## 12. Kitchen {#12}

> The first paragraph of the key: what the players see (the book prints it first, often in its own font or a box).

The rest of the key: the DM's text, stat lines, tables, as the book has them.

## 13. (locked) {#13}
...
```

- Every room key is a level-2 heading `## <KEY>. <optional title> {#<key in lower case>}`: `## 12. Kitchen {#12}`,
  `## 33a. DM's Note {#33a}`, `## W103. (locked) {#w103}`. Keys keep the book's spelling and match the part's key
  pattern. Fix OCR'd keys (`l2` → `12`, `PlO8` → `P108`, `2103` where the book prints `Z103`).
- **Read-aloud**: the key's first paragraph, the book's player description, is a `>` blockquote, as in the drafts.
  If the book's first paragraph is a DM's note (no description), there's no blockquote.
- **One heading per key, in the book's order.** Where the book gives several rooms one entry:
  - "20-23. These rooms are empty." → one heading per key, each with the text ("This room is empty.").
  - "18 and 19. <text>" → `## 18.` with the text, then `## 19.` with "As 18." (so both rooms link).
  - An area note over a range whose rooms then get their own keys ("11-17. DM's Note. The Laboratory Area" then 11,
    12, …) → an **unkeyed** heading `## The Laboratory Area (11–17)` with the note, then the keys.
- Sub-headings inside a key or an introduction (`### The Great Risk`, a table's title) are level 3 or 4.
- Keep the drafts' Markdown (bold NPC names, `***italic***` spells and magic items, tables) where it is right: it is
  the converter's careful work. Fix what is wrong: lost or cut sentences, sentences from another room, stat lines
  whose numbers differ from the page (check every number in stat lines and tables against the page image), stray
  fragments ("have a small"), joined words, OCR errors.
- Text that belongs in **another of your files** goes there. Text that belongs in **a file of another agent** (a part
  not listed above) goes into `clean/{piece}-orphans.md`, each piece under a line
  `=== goes to <part id>, after <key or heading>` so the lead agent can place it. Don't drop anything that is in the
  book.
- Don't add anything that isn't in the book. Don't reword.
- An unkeyed part (a chapter, the front matter, an appendix) has no key headings: give it the book's own headings, at
  level 2 and below, in the book's order.

## How to work

1. Read this brief, then your drafts. Run the checker on your copies to see the worst places.
2. Go **page by page through your pages** in the book (every page, not only the flagged keys): Read the page image
   and compare it with your files, key by key, in order. Restore what's missing, move what's misplaced, fix what's
   wrong. Missing keys often sit, unrecognised, inside the previous key's text.
3. Run the checker again until each remaining flag is one you have checked against the page and is the text layer's
   fault. Write each flag you leave in your doubts file, kind `checker-flag`, with why.
4. A key the book's numbering (or its map) has but the book gives no text for is a doubt of kind `missing-text`.

## What to report back

Per file: what you restored, moved, fixed; the keys still missing (if the book has no entry for them); the checker
flags you left and why. Keep it short. Your doubts go in `doubts/{piece}.json` (see below).
