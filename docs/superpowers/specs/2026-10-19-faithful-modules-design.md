# Faithful modules: fixes from the Saltmarsh playthrough

*Design brief, 2026-10-19. Source: `docs/review/2026-10-19-saltmarsh-playthrough.md` (finding ids S, C, F, E, P, D, T and "the ten changes"). Built on master 6279536.*

## Goal

A module converted from a published PDF (U1 is the test case) can be played faithfully: every map page becomes an editable map drawn from its picture, every keyed area is reachable and linked, the records are clean enough to export, and the DM neither invents layout nor leaks hidden rolls.

## Owner decisions (2026-10-19)

1. **Map generation from the book's pictures is high priority**, next to the blockers. Without it module import is close to blocked.
2. **Pregenerated characters** become an optional module section in the schema: per character a name, stats, gear and background. The converter fills it from the book's roster; party creation can offer them.
3. **Late joiners** see the earlier story and can browse through the history (paged or scrolled back), not only the recent entries.
4. **Players see each other's sheets**, for now. No change; record it in the glossary or data dictionary as the current rule.
5. **Converters follow the book's contradictions and errata** as printed (e.g. the gnolls "in area 30", Oceanus NG/CG). No correction and no question is needed for them.

## Work, in priority order

### A. Blockers
- **A1 Export never fails on a converted module** (C-a). After extraction, rewrite or drop every reference to a missing entity and warn; the 409 on `npc:bosun` must not happen.
- **A2 Detect every map page** (C-b). Classify picture pages by plate titles ("Haunted House", "cellar", "floor", "deck", "level", "map") and, when OCR is inconclusive, by a vision call. `POST …/map-drafts/from-book` accepts any full-page picture attachment, so the DM can draft a page the detector missed.
- **A3 Keep refuses a mismatched draft** (C-c). `_on_map`/`_rooms` take only the texts of that map's part; Keep refuses (or warns and asks) when the draft's labels don't match the map's own keys.

### B. Maps from the book's pictures (owner: high priority)
- **B1 Faithful drafts from the picture.** The vision draft reads the plate: rooms, their numbers, doors, secret doors, stairs, hatches, ladders and the printed scale. One map per level or floor (house ground, upper, cellar and caves; ship decks), joined by exits (stairs, hatches, ladders), named after the plate's title, not an OCR word.
- **B2 Draft every detected map page automatically** during a PDF conversion (6279536's checkbox stays), with progress shown per page instead of "0 of 2 maps" for minutes (C-d).
- **B3 Review before keeping**: show the draft over the page picture, large enough to judge (not the 9-box strip in the card), and keep it editable in the map editor. The renderer's "not connected" warning is shown on the draft.
- **B4 The map editor works for drafted maps** (E-a): the provenance notice is one line; "Show the book's map" shows the page picture beside or under the canvas.
- **B5 A sketch from the room key is a fallback only**, used when a part has no map page; it is labelled as invented.
- Measure on U1 by hand (the owner's check): pages 2, 35 and 37 give the cellar and caves, the ship's decks and the house's two floors.

### C. Keys and structure
- **C1 Keys scoped to their part** (§3.2): text-qualified keys in `_place`, `_on_map`/`_rooms`, `keys[]` and `module_key` (e.g. `module_key("7", part="house")` or `H7`/`S7`). Ambiguous `key:N` is refused with a hint that can be followed; a `keys[]` entry is written for every keyed heading (18, 19, 20, 25, 26 are missing today).
- **C2 Entities placed in their own part**: ship NPCs and encounters no longer land in house rooms 7, 11, 14 and 17; house encounters (snake, spiders, centipedes, stirges, rot grubs, slime) get their key.
- **C3 De-duplicate entities** (§3.4): merge by role, alias and number, not only identical names; rewrite the references.
- **C4 Front matter apart** (C-e, F3): the cover, title page and back-cover ads are not chapters; the DM's opening is the first keyed or introductory text, not the cover.

### D. Text fidelity
- **D1 Every boxed text in a keyed section is read-aloud** (F1), not only the one right after the heading.
- **D2 Handouts** (§3.5): split a handout page into its handouts, link each to its key, and mark it player-showable.
- **D3 Fill text-layer gaps from the page image** (F2, F5): ½ and ¼ Hit Dice, the ½-races; never assume "as printed" for an empty or garbled field.
- **D4 Keep bold and italic** (F4).
- **D5 Small illustrations**: keep them, or warn `image-dropped` (the 15 % share rule today drops 15 of 35 silently).
- **D6 Stat lines visible and editable** in the NPC form and print (`EntityForm.tsx`, `ModulePrint.tsx`); join appendix stat blocks to their people.

### E. Pregenerated characters (owner decision 2)
- Optional `pregens` section in the .dscn schema (name, class/race/level, stats, gear, background, and the system key as for NPC stats), with data-dictionary and glossary entries, import/export and the module editor.
- The converter fills it from a roster table (U1 page 29) instead of a DM-only text.
- Party creation offers a module's pregens; the DM can create the party from them.

### F. The DM and dice
- **F1 Tell the DM when a part has no map** (D-a, P-a): `session_primer` names unmapped parts; `dm.md` says to ask the host rather than invent a layout; the map panel says "this part has no map" instead of "Map offline".
- **F2 A fresh roll per occasion** (D-b): checks get an occasion in their roll key; encounter checks per interval.
- **F3 Surprise kept** when `setup_combat` is corrected (D-c).
- **F4 Hidden rolls fail quietly** (D-d): settle the `dm.md:141`/`:155` contradiction; searches, listening and trap-finding fail as "you find nothing"; wandering-monster checks stay out of the players' story.
- **F5 Ask sees the session** (D-e): the session's notes and recap in the prompt, not only the last 8 entries; no key numbers to players (also P-c).
- **F6 Reference row** (D-f): `centipede, giant` gives the giant centipede, not the megalo-centipede.

### G. Late joiners and small items
- **G1 Story history** (owner decision 3): any seat can scroll or page back through the whole story, loaded on demand.
- **G2 Costs**: record and show the conversion's cost and Ask costs; a per-beat cost that doesn't reset with the DM process (P-e).
- **G3 Small items** where cheap: S1 token hint at first start, S2 first-run guidance, S4 head revision, P-b tool chips tucked away on the host's story, T-a picker labels, E-b a key outline in the text editor, E-c no dead map links, E-d distinct-problem count, `docs/backlog.md:118` stale entry.

## Out of scope
- S3 (the seeded ttrpg2 house rules): leave as is.
- Correcting errata or contradictions (owner decision 5).
- Hiding other players' sheets (owner decision 4).

## Done when
- Every item above is built test-first, or recorded as deferred with a reason in the chronicle.
- `make ci` passes on a fresh clone; `make e2e-browser` passes with screenshots (desktop and phone) of: a book-page draft over its picture, the map editor on a drafted map, the pregens in the module editor and in party creation, a seat scrolling back the story.
- The chronicle lists what the owner should check by hand with the real `claude`: converting U1 again and judging the drafts of pages 2, 35 and 37, exporting it, and a short play through the house with fog and the secret trapdoor in room 4.

## Decided in the plan

The plan (`docs/superpowers/plans/2026-10-19-faithful-modules.md`, "Decisions taken in this plan") settled the
questions this design left open, by the quest's rules: the owner's decisions stand, the fourth wall wins, the book is
followed as printed, single-player play stays as fast, and the smallest change. Its table has the reason for each. The
plan review's amendments and the build's own decisions are in the quest's chronicle. Where the built code differs
from the design's examples:

- Keys two parts share are scoped by a slug of the part's title, at most 19 characters (`haunted-house-7`, not `H7`
  or `house-7`); a key unique in the module stays as printed.
- One text may span several maps (a house's floors): Keep writes each room's `keys[]` entry with its own level's node,
  and levels are joined by the map language's `exit … to "<map>"`.
- `pregens` is a seventh entity kind and the format stays at version 2; a reader of the version-2 schema without the
  kind refuses a bundle that has pregens.
- The pregens list (`GET /api/campaigns/{id}/pregens`) is for the host, co-hosts and the owner only.
- Front matter is set apart only in books of 8 pages or more.
