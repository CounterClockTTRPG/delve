You look at page {{number}} of a tabletop adventure, a page that is all picture, and say what kind of page it is. The
converter uses your answer to find the book's maps and to cut out the handouts the players are shown.

## The kinds

- `map`: a map, a plan or a deck plan of a place: rooms, floors, levels, decks or caves, often with numbered areas, a
  scale or a legend. A page with several maps (two floors, a cellar and caves) is one `map` page.
- `handout`: one or more pictures meant for the players: a letter, a note, a parchment, a chart, an illustration
  marked to be shown to them.
- `art`: an illustration, a cover or a decoration that is neither a map nor a handout.
- `blank`: an empty page, or one with only a page number, a running header or a printer's mark.
- `text`: a page of text that was printed as a picture.

## What to answer

One JSON object, and nothing else, such as:
`{"kind": "map", "title": "The Haunted House: ground floor", "handouts": []}`

- `kind`: one of the kinds above.
- `title`: for a `map`, the plate's title as printed ("Haunted House", "The Sea Ghost: main deck"), or null when it
  has none; for another kind, null.
- `handouts`: for a `handout` page, one entry per handout:
  `{"box": [x0, y0, x1, y1], "title": "…", "key": "…" or null, "part": "…" or null}`.
  - `box` is the handout's edges as fractions of the page, from its top left corner: 0 is the left or top edge, 1
    the right or bottom edge.
  - `title` is the handout's caption as printed, or a few words saying what it shows.
  - `key` is the printed key of the area it belongs to, when the page says ("Handout for area 22" is `"22"`).
  - `part` is the part of the adventure it belongs to, when the page says ("the ship", "the house").

  For any other kind, `[]`.
