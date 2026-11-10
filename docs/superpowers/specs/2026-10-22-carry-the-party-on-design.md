# Carry the party on: a campaign's party, and its history, into a new module

Date: 2026-10-22. Status: design. A small project of its own, on master after looks-and-banners (delivered
2026-10-22, 35f8a16).

## Intent

A campaign plays one module, and that never changes (`campaigns.module_id`, pinned to a revision). The owner is
playing Barrowmaze and finding it too deadly for a new party. They want to play a short, gentler module first, then
take the survivors into Barrowmaze. Their history goes with them, so the new campaign remembers who they are.

The owner wants the history to cover **the NPCs they met, their notable deeds, their grudges, and their loot**. The
**DM** is the main reader: it should bring back the innkeeper, the rival or the old grudge without being prompted. The
owner and the players read it too, on the campaign page.

The action is **Carry the party on**, and what travels with the party is its **history**.

## Owner decisions (2026-10-22)

1. **A campaign keeps its one module.** Changing a running campaign's module is not wanted. The party moves to a new
   campaign instead (option 1 of two discussed).
2. **The history is drawn from the old campaign's record**, not written by hand. It covers NPCs met, notable deeds,
   grudges and loot.
3. **Both the DM and the table read it, mostly the DM.**
4. The owner accepted the playback below (carry everything a character owns, keep the old campaign, the DM's version
   holds secrets and the players' doesn't, an editable history, histories that stack).
5. **All the party's wealth goes with it:** the campaign's coin (`CampaignState.coin`), its loot pile
   (`CampaignState.loot`) and the possessions with no owner (`owner_id` NULL). The old campaign keeps only the record.
6. **The table's history holds only what the whole table was told.** Private acts ("(in secret)"), lines told only
   to some seats, DM notes, unrevealed secrets and exact faction reputation numbers are removed from the material
   **before** Claude writes the table's version. Leaving them out is not left to the prompt. One table version per
   campaign, not one per seat.

## Goals

- **Carry the party on** from a campaign's page (host and organiser seats, as for making a campaign). The form asks
  for: the module (a non-draft one, as New campaign does), the new campaign's name, its ruleset, setting and house
  rules (by default the old campaign's, my call), and **which characters go**. All living PCs are ticked by default.
  Dead PCs are listed but not ticked.
- **The new campaign** is made exactly as `POST /api/campaigns` makes one: a snapshot revision of the module, seeded
  with the module's world. It then gets:
  - **A copy of each chosen character:** the sheet and state as they are now (levels, XP, hit points, spells,
    inventory, conditions), with a new id in the new campaign. The old character stays as it was.
  - **Their possessions** (the `possessions` rows owned by those characters, such as a mount or a named weapon), as
    copies (my call), and the party's shared wealth: all its coin, its loot pile and its unowned possessions (owner
    decision 5). The new campaign starts with these, and the module's own starting coin, if it has any, is added.
  - **The history** (below).
  - It does **not** get the old campaign's NPCs as characters, or its factions, quests, clocks, map states, story or
    sessions. Those belong to the old module's world. They reach the new campaign only through the history.
- **The old campaign stays** as it is, read-only in spirit: it is set to `complete` (my call; the host can set it back).
  It links forward to the new campaign, and the new one links back ("Carried on from …").
- **The history** is written by Claude when the party is carried on, as a job (like a novel's or a conversion's), and
  its spend counts in `cost_usd`. It reads what the novel writer reads (`novels/material.campaign_material`): the
  characters and their fates, the session recaps and story, the NPCs met, the DM's notes. It also reads the factions
  with their reputation, the completed and failed quests, and the carried characters' notable items. Its sections are:
  - **The party:** who travelled, who died along the way, and how the survivors stand.
  - **People met:** each NPC that matters, what they are to the party, alive or dead, and where they were last seen.
  - **Deeds:** what the party did that people would talk about.
  - **Grudges and debts:** who wants the party harmed and why, who owes the party, who the party owes.
  - **Loot:** the treasure and items of note they carry out, and where any special item came from.
  - **Loose ends:** quests left open and secrets the party never uncovered (DM only).
- **Two versions**, as the story already has two audiences:
  - **The DM's history** may use everything: secrets, notes, what the party never learned.
  - **The table's history** holds only what the whole table was told (owner decision 6). It is written from material
    that has already been filtered.
  Both are written in the same job.
- **The host can read and edit both** on the new campaign's page before or during play. An edit replaces the text and
  marks it edited. **Write again** regenerates it from the old campaign and asks before overwriting an edit.
- **Histories stack.** A campaign that was itself carried on already has a history. When it is carried on again, the
  new history covers both: the earlier history plus what happened since, condensed. The DM always reads one history
  per campaign, not a chain.
- **The DM reads it.** `sessions.primer` gains `history`: the DM's version, in full. It is long-lived context and is
  fetched every session, so it is capped (about 6,000 characters, my call; the job condenses to fit). `dm.md` says
  what it is for: bring back people and consequences from the party's past when it fits, and invent nothing the
  history contradicts. A DM tool such as `history(contains=…)` is the builder's call if the primer gets too heavy.
- **The table reads it.** The campaign page gets a **History** section, near the banner, showing the table's version
  (the host sees the DM's version, with a toggle). Ask the DM may use the table's version.
- **A failed job** leaves the new campaign playable without a history and shows **Write again**. Carrying the party on
  never fails because of the history.

## Calls made after the builder check (mine)

- **The DM's history reads what was played, not the old module's unplayed text.** `campaign_material` ends with the
  whole module revision. The history job leaves that part out. "Loose ends" are open quests and unrevealed DM
  `secret` notes, not rooms the party never reached. This keeps the cost down, keeps the cap realistic, and keeps
  the history to the record.
- **A campaign can be carried on more than once**, for example as a retry or to split the party. The forward links
  are a list, and the old page lists each campaign it was carried on to.
- **Refused while a fight is live** in the old campaign (409, "End the fight first"). Copied state drops what only
  makes sense mid-fight or mid-scene: combat-only conditions and effects with a duration, and lit light sources.
  Hit points, lasting conditions (disease, curses, level drain) and spent spells stay. The job snapshots the old
  campaign as it is when the action is taken.

## Non-goals

- Switching a running campaign to another module.
- Merging two parties, or carrying characters into an existing campaign.
- Moving seats. Players join the new campaign with its join link. The host can then hand each carried character to
  its player's seat, as is done today (my call: Delve gives no automatic seat match).
- Carrying NPC companions as characters. They appear in the history. The DM can bring them in with `introduce_npc`.
- A shared world across campaigns (facts, factions or NPCs that live in more than one campaign).

## Anti-goals

- **A history the DM ignores.** If it only sits on a page, it has failed. The DM must get it every session without
  asking for it.
- **Leaking secrets** to the table's version or to players' routes.
- **Invented history.** The account follows the record: who died, who was met and what was found are as played.
- **Losing the old campaign.** Carrying on copies. It never moves or deletes the old campaign's rows.

## Constraints

- Delve's existing patterns: SQLite with an Alembic migration (next after 0017), jobs as for novels and conversions,
  the audience split the story uses, `cost_usd` for Claude spend, host or organiser seats for the action.
- Modules, rulesets and settings: the new module may use another ruleset. The form allows it, and copied sheets are
  kept as they are. Converting sheets between rulesets is out of scope.
- `make ci` green, tests first, as for the other Delve plans.

## Left to the builder

- The storage shape of the history (a table keyed by campaign, or a column), and how the forward and back links are
  kept.
- How the job condenses long material (`material.condense` exists) and how the cap is enforced.
- The prompt, within the sections above.
- The page layout of the form and the History section, following the looks already in Delve.
