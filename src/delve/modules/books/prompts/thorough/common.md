# For every agent of a thorough conversion

Delve is converting a tabletop adventure module, printed as a PDF, into a module its AI dungeon master plays from: the
book's texts in Markdown, its maps traced into Delve's map language (`.dmap`), its pictures described. You are one of
the agents that do it, each with one piece of the work, and your piece is `{piece}`. The book's pages are the truth:
nothing lost, nothing added, nothing invented.

## The folder

You work in the job folder, your working directory. Every path below is relative to it.

- `book.pdf`: the book.
- `pages/p-NNN.png`: each page of the PDF as an image at 150 dpi (`pages/p-027.png` is page 27 of the PDF; Read shows
  it). `pages/ocr-NNN.txt`: the same page's text layer, or its OCR when the PDF has none. The text layer is good for
  copying text, but it has OCR errors (`ld6` for 1d6, `lO` for 10, `THACO` for THAC0, joined or split words): correct
  them. The page images are the truth.
- `scan/p-NNN.png`: the map pages and picture pages again, at 200 dpi (1 inch of the page is 200 px).
- `classes.json`: which pages the page classifier took for maps, pictures and text. A guess, to start from.
- `draft/`: the converter's drafts of the texts; after the sort, one draft per part, `draft/<part id>.md`.
- `original.md`: the converter's drafts as they were before the sort, each starting with a line `<<<TEXT <name>>>>`.
  Look here for a paragraph that went missing.
- `parts.json`: the book's parts (its levels, areas, chapters) and their maps, written by the sort.
- `keys/<part id>.txt`: a part's keys, one per line.
- `clean/`: the cleaned texts, `clean/<part id>.md`.
- `maps/`: the traced maps, `maps/<map name>.dmap` with its `.svg`, `.png` and `.exits.json`.
- `art/`: the book's pictures, cut whole from their pages, and `art/descriptions.json`.
- `ref/`: the map language's documentation (`ref/dsl*.md`) and finished maps from earlier modules (`ref/*.dmap`).
- `work/{piece}/`: your own scratch folder for rotated scans, tiles and trials. Make it when you need it.
- `doubts/`: one file per piece, below.

Write only in this folder, and only the files your brief gives you. Never read or write outside it, never use the
network, never start a server, never touch a database or a git repository.

## The tools

Run them as `{qa} <command> …`, that full path written as it is, from the folder, with paths inside it (a path
outside is refused, exit code 2). Exit code 0 is done, and for `textcheck` and `mapcheck` also nothing found; 1 is
something found, or an input that can't be read.

Bash runs `{qa}` and nothing else: `cat`, `ls`, `cp`, `rm`, `awk`, `python`, loops and redirections (`>`) are refused.
Read files with Read, Grep and Glob, and write them with Write and Edit. You can't delete a file: empty it instead. A
long output is cut off and kept where you can't read it, so keep every output small: give `{qa} keys` an `--out` file
and Read that, give Grep a `head_limit` or a narrow pattern, and Read a long file with `offset` and `limit`.

- `{qa} keys pages --pattern '<key pattern>' [--first N] [--last M] [--stop '<other pattern>']… [--out <file>]`: the
  book's entries by key, as JSON `{"<key>": {"page": n, "text": "…"}}`, read from the text layer of pages N to M; with
  `--out work/{piece}/<name>.json` written there, and one line per key (its page and words) printed. An entry starts on a
  line like `12.`, `W501.`, `Z130-Z133.` or `Z518 and Z519.`; OCR misreadings of a key (`l2`, `PlO8`) are mended.
  `--stop` gives another part's key pattern, which ends an entry but starts none.
- `{qa} textcheck parts.json clean/<part id>.md …`: per file, the keys the book has for the file's part that the file
  lacks (`in the book, not here`), the sections whose words cover less than 85% of the book's entry (text lost), the
  sections with over 25% of their words not in the book's entry (text from elsewhere), the keys the text layer doesn't
  have (`not found in the text layer (check the page)`), and the headings in the wrong form. A file is checked against
  the part whose id is its name.
- `{qa} rotate <in.png> <out.png> <degrees>`: the picture turned counter-clockwise (negative: clockwise) on white.
- `{qa} tile <in.png> <out.png> X0 Y0 X1 Y1 <px> OX OY <width>`: the squares X0..X1 × Y0..Y1 of a grid of `<px>`-pixel
  squares whose square (0,0) starts at pixel (OX,OY), with every grid line numbered (columns red, rows blue, every
  fifth line thicker), scaled to `<width>` px.
- `{qa} mapcheck maps/<name>.dmap [--fix-doors]`: parses and validates the map, prints its errors and warnings and its
  counts (rooms, corridors, doors, exits), and draws `maps/<name>.svg` and `maps/<name>.png` (1200 px wide) beside it.
  `--fix-doors` rewrites, in place, each `door between` whose rooms don't quite share a wall into a placed
  `door at X,Y`.
- `{qa} join maps <out-dir>`: the levels joined by their exits (the sort's and Delve's work, not yours).

## Your doubts

Before you finish, write `doubts/{piece}.json`: a list of everything you weren't sure of or couldn't do, each
`{"part": "<text or map id>", "pages": [<PDF page>, …], "kind": "<kind>", "text": "<what is uncertain, and what you
did>"}`, where kind is one of:

- `missing-text`: a key on the book's map, or in its numbering, with no text in the book;
- `missing-room`: a key in the text with no room on the book's map;
- `checker-flag`: a checker flag you left, with why;
- `left-out`: something in the book you left out (a map detail, a picture that isn't one);
- `guessed-landing`: a stair, chute or shaft whose other end you guessed;
- `picture-unsure`: a picture you placed without confidence;
- `other`: anything else.

Write `[]` when you have none. The file must be valid JSON: Delve gathers every piece's doubts into the list the
organiser reads at the end, so a doubt only in your report is lost.

## Your report

End with a one-paragraph report: what you wrote, what you fixed, and how many doubts you left.
