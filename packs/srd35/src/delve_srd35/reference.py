"""SRD 3.5's data as a `RulesetReference`: its monsters, spells, items, weapons, classes, races and ability table, and its
rules text. What 3.5 has none of (nonweapon proficiencies, a turning table, the classic engine's encounter tables)
answers empty."""

from __future__ import annotations

import re
from typing import Any

from delve.domain.reference import name_key
from delve_srd35 import text
from delve_srd35.data import load

MOST = 10
ABILITIES = {"str": "Strength", "dex": "Dexterity", "con": "Constitution", "int": "Intelligence", "wis": "Wisdom",
             "cha": "Charisma"}  # fmt: skip


def ranked(rows: list[dict[str, Any]], name: str) -> list[dict[str, Any]]:
    """The rows whose name holds `name`: the exact name, then names starting with it, then names holding it as a
    word, then the rest; shorter names first within each. When nothing holds it, a name holding every word of a
    query of two or more words ("red dragon" finds "Dragon, red"). The apostrophe's shape doesn't matter
    ("Bull's Strength" finds "Bull’s Strength")."""
    wanted = " ".join(name_key(name).split())
    if not wanted:
        return []

    def rank(row: dict[str, Any]) -> int | None:
        low = name_key(row["name"])
        if low == wanted:
            return 0
        if low.startswith(wanted):
            return 1
        if re.search(rf"\b{re.escape(wanted)}\b", low):
            return 2
        return 3 if wanted in low else None

    found = sorted(
        ((r, len(row["name"]), row["name"].lower(), row) for row in rows if (r := rank(row)) is not None),
        key=lambda t: t[:3],
    )
    if found:
        return [row for *_, row in found]
    words = re.findall(r"[a-z]+", wanted)
    if len(words) < 2:
        return []
    return sorted((r for r in rows if all(w in name_key(r["name"]) for w in words)), key=lambda r: len(r["name"]))


def _signed(number: int) -> str:
    return f"+{number}" if number > 0 else str(number)


class Srd35Reference:
    """SRD 3.5's data as a `RulesetReference`."""

    def monster(self, name: str) -> list[dict]:
        return ranked(load("monsters"), name)[:MOST]

    def spell(self, name: str, caster: str = "") -> list[dict]:
        wanted = caster.strip().lower()
        rows = [s for s in load("spells") if not wanted or any(wanted in c for c in s["levels"])]
        return ranked(rows, name)[:MOST]

    def item(self, name: str, item_type: str = "", max_rarity: int = 100, limit: int = 20) -> list[dict]:
        kind = item_type.strip().lower()
        rows = [i for i in load("items") if not kind or kind in (i["item_type"] or "").lower()]
        return ranked(rows, name)[:limit] if name.strip() else sorted(rows, key=lambda i: i["name"].lower())[:limit]

    def weapon(self, name: str) -> dict | None:
        found = ranked(load("weapons"), name)
        return found[0] if found else None

    def char_class(self, name: str) -> dict | None:
        found = ranked(load("classes"), name)
        return found[0] if found else None

    def class_levels(self, name: str) -> list[dict]:
        found = self.char_class(name)
        return list(found["levels"]) if found else []

    def race(self, name: str) -> dict | None:
        found = ranked(load("races"), name)
        return found[0] if found else None

    def ability(self, ability: str, score: str) -> dict:
        key = ability.strip().lower()[:3]
        if key not in ABILITIES or not ABILITIES[key].lower().startswith(ability.strip().lower()):
            return {"error": f"Unknown ability '{ability}'.", "hint": f"Use one of: {', '.join(ABILITIES.values())}."}
        table = load("abilities")
        bonus = {row["score"]: row for row in table["bonus_spells"]}

        def values(row: dict[str, Any]) -> dict[str, str]:
            spells = bonus[row["score"]]
            return {"modifier": _signed(row["modifier"]),
                    "bonus_spells": " ".join(str(spells[str(level)]) for level in range(1, 10))}  # fmt: skip

        found: dict[str, Any] = {
            "ability": ABILITIES[key],
            "headline": "Ability modifier and bonus spells",
            "xp_bonus": "",
            "extra": "",
            "columns": [
                {"name": "Modifier", "short_name": "modifier", "note": ""},
                {"name": "Bonus spells (1st–9th level)", "short_name": "bonus_spells", "note": ""},
            ],
        }
        if not score.strip():
            return {**found, "rows": [{"score": str(row["score"]), **values(row)} for row in table["modifiers"]]}
        row = next((r for r in table["modifiers"] if str(r["score"]) == score.strip()), None)
        if row is None:
            return {"error": f"No {ABILITIES[key].lower()} score '{score}'.", "hint": "Give a score from 1 to 45."}
        return {**found, "score": score.strip(), "values": values(row)}

    def feat(self, name: str) -> list[dict]:
        return ranked(load("feats"), name)[:MOST]

    def skill(self, name: str) -> list[dict]:
        return ranked(load("skills"), name)[:MOST]

    def proficiency(self, name: str = "", group: str = "", ability: str = "") -> list[dict]:
        return []

    def turning_undead(self) -> list[dict]:
        return []

    def rules_search(self, query: str, source: str = "", limit: int = 5) -> list[dict]:
        return text.search(query, source, limit)

    def rules_section(self, source: str, section: str) -> list[dict]:
        return text.section(source, section)

    def encounter_tables(self) -> dict:
        return {}

    def osric_magic_items(self) -> dict:
        return {}
