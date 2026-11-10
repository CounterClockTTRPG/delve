PIECE: {piece}

# Describing the book's pictures

You write the descriptions of the book's illustrations for Delve, an app where an AI dungeon master reads each image's
description to decide when to show the picture to the players.

- The pictures: every `.png` in `art/`, cut whole from the book's pages. A file's name starts with `pNNN`, NNN the PDF
  page it was printed on. The pages that `parts.json` lists under `pictures` (the book's world, region and overland
  maps) are among them, whole.
- The book's pages: `pages/p-NNN.png`, and their text layer: `pages/ocr-NNN.txt`. `parts.json` says which pages hold
  which part, and each keyed part's key pattern; the texts are in `clean/<part id>.md`.

For every `.png` in `art/`, look at the image and at its page (and the pages either side), and work out what scene it
shows: which room key (the illustrations sit near the room they depict, but not always on the same page: match the
picture's content — monsters, objects, the room's features — against the key texts), which monster, or which map.

Then write `art/descriptions.json`: a list of `{"file": "<png name>", "id": "<a short slug id, e.g. r12-kitchen-ghost,
troll, cover>", "part": "<the part id it belongs to, or null>", "key": "<the room key it shows, or null>", "audience":
"player" or "gm", "description": "<one or two sentences: what the picture shows, as a player would see it, then 'Show
it when …' naming the room key and the moment (e.g. 'Show it when the party enters room 12, the kitchen.')>"}`.

- Ids are unique, lower case, digits and `-`.
- Players see the picture as it is: crop it when it shows what they shouldn't, or more than one thing. Add `"crop": [x,
  y, w, h]`, the part to keep, as fractions (0 to 1) of the picture's width and height from its top left corner (`[0,
  0, 0.5, 1]` is the left half). Crop off a room key, a room number, a map's legend or the page's text printed on the
  picture. A plate of several scenes, or of several NPCs who each deserve their own portrait, is listed once per piece:
  the same `file` in several entries, each with its own `crop`, `id`, `key` and `description`. Leave `crop` out when the
  whole picture is right.
- A plate printed sideways gets `"rotate": 90` (or `180`, `270`: degrees clockwise, to stand it upright); a `crop` is
  then fractions of the turned picture.
- Delve keeps the uncut picture for the organiser, who checks each crop: when a crop can't be made, the picture is
  attached whole.
- Use audience `gm` only if the picture gives away a secret the players shouldn't see before the moment (say why in the
  description); the cover and the book's maps of the world or region are `player`.
- For drawings in a monster appendix say which monster and "Show it when the party first meets a <monster>."
- If you can't place a picture confidently, say so in the description ("Probably room 14 …"), and write a doubt of kind
  `picture-unsure`.
- A file that isn't an illustration (a strip of text, a page border, a blank, half a picture) is left out of
  `descriptions.json`, with a doubt of kind `left-out` naming the file. Delve attaches only the pictures you describe.

## What to report back

The table of file → id → key, and your doubts, kept short. Your doubts go in `doubts/{piece}.json` (see below).
