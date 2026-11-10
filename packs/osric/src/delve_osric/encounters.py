"""OSRIC's random encounters (DEL-306), by its tables in `encounters.json`, the classic engine's `Encounters`:

- **underground**: a d20 on the dungeon level's row of the matrix (Gamemaster Guide Table 2.7.3.1A) gives the monster
  level, and a d100 on that level's table the monster and how many wander; a dragon goes on to its sub-table, an
  adventuring party is the DM's to make;
- **outdoors**: a d100 on the terrain's table (Table 2.9.1) gives the kind of creature, and a roll on the terrain's
  table of that kind the creature;
- **in town**: a d100 on the day's or the night's table (Tables 2.8.1A and B) gives who is met, as its name and the
  number when the table gives one.
"""

from __future__ import annotations

import re
from typing import Any

from delve.dice import Dice, Roll
from delve.rules.classic.encounters import Encounter
from delve_osric.data import load

TERRAINS = {
    "mountain": "mountains",
    "swamp": "wetlands",
    "ocean": "marine",
    "wilderness": "plains",
    "road": "rural",
}
"""Delve's terrain words onto OSRIC's outdoor tables, where they differ."""

UNDERGROUND = frozenset({"dungeon"})
TOWN = frozenset({"urban"})


def _pick(rows: list[dict[str, Any]], roll: int, key: str) -> dict[str, Any]:
    return next((row for row in rows if row[key][0] <= roll <= row[key][1]), rows[-1])


def _night(occasion: str) -> bool:
    """Whether the game time of the check ("day 3 22:10") is night: 20:00 to 06:00."""
    found = re.search(r"(\d{1,2}):\d{2}", occasion)
    return found is not None and not 6 <= int(found.group(1)) < 20


class OsricEncounters:
    def determine(
        self, dice: Dice, *, terrain: str, party_level: int, dungeon_level: int, occasion: str
    ) -> Encounter | None:
        tables = load("encounters")
        if terrain in UNDERGROUND:
            return self._underground(dice, tables["dungeon"], dungeon_level or party_level, occasion)
        if terrain in TOWN:
            return self._town(dice, tables["urban"], occasion)
        key = TERRAINS.get(terrain, terrain)
        if key not in tables["wilderness_main"]["terrains"]:
            return None
        return self._outdoors(dice, tables, key, occasion)

    @staticmethod
    def _purpose(step: str, occasion: str) -> str:
        return f"encounter:{step}@{occasion}" if occasion else f"encounter:{step}"

    def _underground(self, dice: Dice, dungeon: dict[str, Any], depth: int, occasion: str) -> Encounter:
        bands = dungeon["matrix"]["bands"]
        band = next((b for b in bands if b["dungeon_levels"][0] <= depth <= b["dungeon_levels"][1]), bands[-1])
        matrix = dice.d(20, purpose=self._purpose("matrix", occasion))
        level = _pick(band["rows"], matrix.total, "d20")["monster_level"]
        table = dice.d(100, purpose=self._purpose("table", occasion))
        row = _pick(dungeon["monster_levels"][str(level)]["rows"], table.total, "d100")
        rolls: tuple[Roll, ...] = (matrix, table)
        tier = f"dungeon level {depth}, monster level {level}"
        if row.get("kind") == "dragon":
            sub = dice.d(100, purpose=self._purpose("dragon", occasion))
            dragon = _pick(dungeon["dragon_subtables"][str(row["dragon_subtable"])]["rows"], sub.total, "d100")
            return Encounter(
                f"Dragon, {dragon['type'].lower()} ({dragon['age'].lower()})",
                tier=tier,
                category="dragon",
                monster=dragon.get("slug") or "",
                number=row.get("wandering") or "1",
                note=f"{dragon['hp_per_hd']} hp per Hit Die, by its age.",
                rolls=(*rolls, sub),
            )
        if row.get("kind") == "npc_party":
            return Encounter(
                "An adventuring party",
                tier=tier,
                category="npc_party",
                note="Make the party yourself: its size, classes and levels by the dungeon level.",
                rolls=rolls,
            )
        return Encounter(
            row["result"],
            tier=tier,
            category="monster",
            monster=row.get("slug") or "",
            number=row.get("wandering") or "",
            rolls=rolls,
        )

    def _outdoors(self, dice: Dice, tables: dict[str, Any], terrain: str, occasion: str) -> Encounter:
        kinds = tables["wilderness_main"]["terrains"][terrain]
        first = dice.d(100, purpose=self._purpose("kind", occasion))
        kind = _pick(kinds, first.total, "d100")["result"]
        word = kind.split("/")[0].strip().lower()
        entries = [e for e in tables["wilderness"].get(terrain, []) if e["category"].lower().startswith(word)]
        if not entries:
            return Encounter(kind, tier=f"{terrain}: {kind}", category=kind, rolls=(first,))
        second = dice.d(max(e["roll"][1] for e in entries), purpose=self._purpose("creature", occasion))
        entry = _pick(entries, second.total, "roll")
        return Encounter(entry["result"], tier=f"{terrain}: {kind}", category=kind, rolls=(first, second))

    def _town(self, dice: Dice, urban: dict[str, Any], occasion: str) -> Encounter:
        when = "nighttime" if _night(occasion) else "daytime"
        roll = dice.d(100, purpose=self._purpose("town", occasion))
        row = _pick(urban[when], roll.total, "d100")
        rolls: tuple[Roll, ...] = (roll,)
        if row.get("subrolls"):
            choice = dice.d(row["die"], purpose=self._purpose("town choice", occasion))
            row, rolls = _pick(row["subrolls"], choice.total, "roll"), (roll, choice)
        return Encounter(
            row["result"], tier=f"town by {when[:-4]}", category="town", number=row.get("number", ""), rolls=rolls
        )


ENCOUNTERS = OsricEncounters()
