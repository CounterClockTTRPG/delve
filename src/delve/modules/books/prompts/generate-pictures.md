You choose the pictures of an adventure module for a tabletop roleplaying game: handouts the DM shows the players, so
that a person or a place looks the same every time. A painter who has not read the module paints them.

## The module

{{module}}

## What to answer

Choose at most {{limit}} pictures, the ones most worth showing: first the key people, then the key places and scenes
the party will surely meet. Fewer is fine for a small module, and a room with nothing to see needs none. Answer with
one JSON object and nothing else:

```json
{
  "pictures": [
    {
      "subject": "Grik",
      "kind": "person",
      "brief": "A wiry kobold chieftain with a chipped snout and a crown of bent copper, seen from the chest up, glaring.",
      "description": "Grik, the kobold chief: show him when the party meets him in the shrine (area C3)."
    }
  ]
}
```

- **`kind`** is `person` for one person or creature seen close up (painted square), and `place` or `scene` for
  anything else (painted wide).
- **`brief`** is for the painter: what anyone looking would see, in plain words: looks, clothes, surroundings, light,
  mood. Every detail is on the page, as the painter knows nothing else. Use no names, as a name means nothing to the
  painter, ask for no words or lettering in the picture, and say nothing of the art style: the painter has its own.
- **`description`** is for the DM, who decides from it alone when to show the picture: who or what it shows, and when
  it fits (the room's key where there is one).
- **The players see the picture, so it gives nothing away.** It shows what the characters would see at that moment: a
  villain in disguise looks like the disguise, a trap looks harmless, a hidden thing stays hidden. Leave out a picture
  that can't be painted without spoiling a twist, and never paint how the story turns out.
