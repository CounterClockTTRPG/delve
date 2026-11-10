---
title: Making maps
audience: organiser
summary: Draw or write a module's dungeon maps in the map editor, and import or draw world maps.
screens: /maps, /maps/:moduleId, /maps/:moduleId/:mapName, /campaigns/:campaignId/own-maps/:mapName, /world-maps/:owner/:ownerId/:name/*
order: 8
related: modules, settings-and-lore
---
A module's maps are its dungeons and buildings. In play they show the players only what their characters have seen.

## Where maps live

**Maps** lists the modules that have maps; each map opens in the editor. A map a campaign plays also links to its DM
view in that campaign.

On a module's page, the **Maps** tab lists its maps. Give a **New map** a name and a **Role**: **Map** for one to
play, **Library** for shared pieces that other maps include. Choose **Add map**. **Make default** sets the map a
text uses when it names none.

**Generate a map** draws one from a description, as a draft: **Keep** it or **Discard** it.

## The editor

The editor shows the map's code and its drawing side by side; on a phone they are two tabs, **Code** and
**Drawing**. Draw with the tools and the code is written for you, or write the code and watch the drawing follow.
Hover a tool for its name and how it works, such as **Rectangle room**, **Corridor** or **Door**. The editor lists
errors and warnings as you go.

- **Save**, or Ctrl+S. **Print** opens a print view; save first.
- **Exit** leads to another map of the module: stepping on it moves the party there.
- A door can be **Trapped**, and an exit **Secret**: players don't see either.
- **Reference image** loads a picture, such as the book's map, to trace over. It stays in your browser.

<figure><img src="/help/map-editor.webp" alt="The map editor: the map's text on the left, its drawing on the right, the drawing tools above it" width="1280" height="800" loading="lazy"></figure>

## The map language

A map is a short text. This one has two rooms joined by a passage, with a locked door to the well:

```dmap
include "core.dmap"

map "The Old Well" {
  grid { cell 32 px units feet 10 bounds 24 x 12 }
}

room "entrance" {
  rect 1,3 6 x 6
  label "1"
}

corridor "passage" {
  width 1
  segment line from 7,6 to 14,6
}

room "well_room" {
  rect 14,2 8 x 8
  label "2"
  feature well at 18,6
}

door at 7,6 { connects room.entrance, corridor.passage type wooden state closed }
door at 14,6 { connects corridor.passage, room.well_room type wooden state locked }
```

A keyed heading in the module's text, such as `## 2. Well Room`, links itself to the room of the same name, here
`well_room`.

## A campaign's own maps

On a campaign's page, **Maps**, **This campaign's own maps** holds maps made for that table alone, such as a district
the players invented. Give it a **New map's name** and choose **Make the map**. It never changes the module.

## World maps

World maps are for travel: land, places, roads and rivers. They belong to a module, a campaign or a setting, each
under its **World maps** or **Maps**.

1. Choose **Import a world map**: **A GeoJSON file**, or **A picture with its key**, giving its grid and what one
   hex or square is.
2. A map read from a picture stays **In review**, unseen by players, until you choose **Review**, settle its doubts
   and **Accept the map**.
3. **Edit** draws places, roads, rivers, regions, lakes and seas, and paints terrain with the **Terrain brush**.

On a campaign's world map, **What the party knows at the start** sets what the players see at first: **Everything**,
**Nothing**, **Some regions**, or **An area drawn on the map**.
