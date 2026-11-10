"""What a history's writer reads (carry-the-party-on plan Task 4): the old campaign's record as a novel's writer
reads it, without the module (the design's call: the history keeps to what was played), and four parts more: the
standing with the factions, the quests, what the party carries (the carried PCs' inventories, the party's coin and
loot pile, and the possessions of the carried PCs and of the party) and the party's earlier history, so that
histories stack.

The DM's material holds everything. The table's holds only what the whole table was told: `campaign_material`'s
`table` audience, the known factions with a word for the standing instead of the number, the known quests without
their notes and with only their known log lines, the possessions without their notes, and the earlier history's
table text, never the DM's. Leaving
DM-only material out is done here, not by the prompt.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from typing import Literal

from delve.domain.campaigns import COINS
from delve.domain.characters import Item
from delve.domain.world import Faction, Possession, Quest
from delve.novels.material import Material, Part, campaign_material
from delve.storage import Storage

__all__ = [
    "CARRIES_HEADING",
    "EARLIER_HEADING",
    "FACTIONS_HEADING",
    "QUESTS_HEADING",
    "history_material",
    "standing",
]

FACTIONS_HEADING = "Standing with the factions"
QUESTS_HEADING = "Quests"
CARRIES_HEADING = "What the party carries"
EARLIER_HEADING = "The party's earlier history"

# The table's words for a reputation, from the most negative: the highest reputation of each band and its word.
_STANDING = ((-50, "hostile"), (-10, "unfriendly"), (9, "neutral"), (49, "friendly"))


def standing(reputation: int) -> str:
    """The party's standing with a faction in a word, for the table: hostile ≤ −50 < unfriendly ≤ −10 < neutral < 10
    ≤ friendly < 50 ≤ allied."""
    return next((word for ceiling, word in _STANDING if reputation <= ceiling), "allied")


def history_material(
    storage: Storage, campaign_id: str, audience: Literal["dm", "table"], carried: Sequence[str] | None = None
) -> Material:
    """The campaign's record for its history, every session of it, for the DM or the table. `carried` names the PCs
    carried on (the old campaign's ids; None: every PC), whose inventories and possessions go in. The earlier history
    is read whenever it has the audience's text, whatever its status: a Write again that failed keeps its texts.
    `KeyError` for no such campaign."""
    table = audience == "table"
    material = campaign_material(storage, campaign_id, None, audience="table" if table else "all", with_module=False)
    factions = storage.factions.list(campaign_id, known=True if table else None)
    quests = storage.quests.list(campaign_id, known=True if table else None)
    parts = [
        *material.parts,
        Part(FACTIONS_HEADING, _factions(factions, table), None),
        Part(QUESTS_HEADING, _quests(quests, table), None),
        Part(CARRIES_HEADING, _carries(storage, campaign_id, carried, table), None),
    ]
    earlier = storage.histories.get(campaign_id)
    if earlier is not None:
        text = (earlier.table_md if table else earlier.dm_md).strip()
        if text:
            parts.append(Part(EARLIER_HEADING, text, None))
    return replace(material, parts=parts)


def _factions(factions: Sequence[Faction], table: bool) -> str:
    lines = []
    for faction in factions:
        if table:
            lines.append(f"- {faction.name}: {standing(faction.reputation)}")
            continue
        known = "known to the party" if faction.known else "unknown to the party"
        facts = [f"reputation {faction.reputation}", f"strength {faction.strength}", known]
        goals = f" Goals: {faction.goals.strip()}." if faction.goals.strip() else ""
        notes = f" Notes: {faction.notes_md.strip()}" if faction.notes_md.strip() else ""
        lines.append(f"- {faction.name} ({', '.join(facts)}).{goals}{notes}")
    return "\n".join(lines) if lines else "(no factions)"


def _quests(quests: Sequence[Quest], table: bool) -> str:
    lines = []
    for quest in quests:
        facts = [quest.status]
        if quest.giver:
            facts.append(f"given by {quest.giver}")
        if not table:
            facts.append("known to the party" if quest.known else "unknown to the party")
        stakes = f" Stakes: {quest.stakes.strip()}." if quest.stakes.strip() else ""
        lines.append(f"- {quest.title} ({', '.join(facts)}).{stakes}")
        lines += [f"  - Day {note.day}: {note.text}" for note in quest.log if note.known or not table]
        if not table and quest.notes_md.strip():
            lines.append(f"  - Notes: {quest.notes_md.strip()}")
    return "\n".join(lines) if lines else "(no quests)"


def _carries(storage: Storage, campaign_id: str, carried: Sequence[str] | None, table: bool) -> str:
    """The carried PCs' inventories, the party's coin and loot pile, and the possessions of the carried PCs and of
    the party, as carrying on copies them; for the table without a possession's `notes_md`, the DM's."""
    pcs = [c for c in storage.characters.list(campaign_id) if c.kind == "pc"]
    pcs = [c for c in pcs if carried is None or c.id in carried]
    names = {c.id: c.name for c in pcs}
    lines = []
    for pc in pcs:
        items = [_item(item) for item in pc.state.inventory]
        if items:
            lines.append(f"- {pc.name}: {', '.join(items)}")
    state = storage.campaign_states.get(campaign_id)
    if state is not None:
        coin = [f"{state.coin[name]} {name}" for name in COINS if state.coin.get(name)]
        if coin:
            lines.append(f"- The party's coin: {', '.join(coin)}")
        for loot in state.loot:
            facts = [loot.kind, *([f"{loot.value_gp:g} gp"] if loot.value_gp else [])]
            qty = f"{loot.qty} × " if loot.qty != 1 else ""
            lines.append(f"- In the loot pile: {qty}{loot.description} ({', '.join(facts)})")
    for possession in storage.possessions.list(campaign_id):
        if possession.owner_id is not None and possession.owner_id not in names:
            continue
        lines.append(f"- {_possession(possession, names, table)}")
    return "\n".join(lines) if lines else "(nothing)"


def _item(item: Item) -> str:
    label = f"{item.qty} × {item.name}" if item.qty != 1 else item.name
    return f"{label} ({item.notes.strip()})" if item.notes.strip() else label


def _possession(possession: Possession, names: dict[str, str], table: bool) -> str:
    owner = f"{names[possession.owner_id]}'s" if possession.owner_id is not None else "the party's"
    facts = [possession.kind, owner]
    if possession.location.strip():
        facts.append(f"at {possession.location.strip()}")
    if possession.value_gp:
        facts.append(f"worth {possession.value_gp} gp")
    line = f"{possession.name} ({', '.join(facts)})."
    if possession.description.strip():
        line += f" {possession.description.strip()}"
    if possession.inventory:
        line += f" Holds: {', '.join(possession.inventory)}."
    if not table and possession.notes_md.strip():
        line += f" Notes: {possession.notes_md.strip()}"
    return line
