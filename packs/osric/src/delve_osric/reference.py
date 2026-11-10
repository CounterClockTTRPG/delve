"""OSRIC's `RulesetReference` over its data in `data/`: monsters, spells, equipment, classes, ability tables, turning.

Each lookup answers rows shaped as AD&D 2e's reference does, so the classic engine reads either: a class's levels
carry `xp_required`, `hit_dice` and `thac0`; an ability's values carry the columns the engine reads (`hit_prob`,
`dmg_adj` and `weight_allow` for Strength, `missile_adj` for Dexterity, `hp_adj`, `sys_shock` and `res_surv` for
Constitution); a turning row carries `undead_type`, `aliases` and `results` by the cleric-level columns.

A monster carries the columns the classic engine's combat reads (`armor_class`, `hit_dice`, `thac0` by OSRIC's
monster to-hit table, `no_of_attacks` and `damage_attack` from the guide's attack line), and its text as the guide
prints it. The rules text is Delve's own summary (`delve_osric.text`); the encounter tables are the ruleset's own way
(`delve_osric.encounters`), so `encounter_tables` finds nothing.
"""

from __future__ import annotations

import re
from typing import Any

from delve_osric import text
from delve_osric.classes import ANCESTRY_CLASSES, LEVEL_LIMITS, Limit, features
from delve_osric.data import CLASSES, load, own
from delve_osric.tables import NONPROFICIENT, SAVE_TYPES, TURNING_COLUMNS, spell_list, strength_row

SOURCE = "OSRIC 3.0"
MOST = 10

ABILITIES = {
    "str": "strength",
    "dex": "dexterity",
    "con": "constitution",
    "int": "intelligence",
    "wis": "wisdom",
    "cha": "charisma",
}

HEADLINES = {
    "strength": "Physical power: to hit and damage in melee, and how much a character carries.",
    "dexterity": "Speed and coordination: missile attacks, surprise, initiative and Armour Class.",
    "constitution": "Health and stamina: hit points, and surviving system shock and resurrection.",
    "intelligence": "Reasoning and memory: languages, and a magic-user's spells.",
    "wisdom": "Judgement and willpower: saves against mental attacks, and a cleric's spells.",
    "charisma": "Presence and charm: henchmen, their loyalty, and how others react.",
}
"""Each ability as Delve describes it."""

COLUMNS = {
    "strength": (("hit_prob", "To hit"), ("dmg_adj", "Damage"), ("weight_allow", "Weight allowance (lb)"),
                 ("open_doors", "Open doors (d6)"), ("bend_bars", "Bend bars / lift gates (%)")),
    "dexterity": (("surprise", "Surprise"), ("missile_adj", "Missile to hit"), ("initiative", "Initiative"),
                  ("def_adj", "AC adjustment")),
    "constitution": (("hp_adj", "Hit points per die (warriors)"), ("sys_shock", "System shock"),
                     ("res_surv", "Resurrection survival")),
    "intelligence": (("languages", "Additional languages"),),
    "wisdom": (("mental_save", "Mental save"),),
    "charisma": (("henchmen", "Henchmen"), ("loyalty", "Loyalty"), ("reaction", "Reaction")),
}  # fmt: skip

UNDEAD = (
    "skeleton",
    "zombie",
    "ghoul",
    "shadow",
    "wight",
    "ghast",
    "wraith",
    "mummy",
    "spectre",
    "vampire",
    "ghost",
    "lich",
    "fiend",
)
"""Player Guide Table 1.6.5A's undead, Type 1 to Type 13."""


def _signed(value: Any) -> str:
    number = int(value)
    return f"{number:+d}" if number else "0"


def _pct(value: Any) -> str:
    return f"{int(value)}%"


def _values(ability: str, row: dict[str, Any]) -> dict[str, str]:
    """A row of OSRIC's table under the engine's column names."""
    if ability == "strength":
        return {
            "hit_prob": _signed(row["to_hit"]),
            "dmg_adj": _signed(row["damage"]),
            "weight_allow": str(row["weight_allowance"]),
            "open_doors": str(row["open_doors"]),
            "bend_bars": _pct(row["bend_bars_pct"]),
        }
    if ability == "dexterity":
        return {
            "surprise": _signed(row["surprise"]),
            "missile_adj": _signed(row["missile_to_hit"]),
            "initiative": _signed(row["initiative"]),
            "def_adj": _signed(row["ac_adj_descending"]),
        }
    if ability == "constitution":
        hp, warrior = _signed(row["hp_mod"]), _signed(row["hp_mod_warrior"])
        return {
            "hp_adj": hp if hp == warrior else f"{hp} ({warrior})",
            "sys_shock": _pct(row["system_shock_pct"]),
            "res_surv": _pct(row["resurrection_pct"]),
        }
    if ability == "intelligence":
        return {"languages": str(row.get("max_additional_languages", 0))}
    if ability == "wisdom":
        return {"mental_save": _signed(row.get("mental_save", 0))}
    return {
        "henchmen": str(row["henchmen_max"]),
        "loyalty": _signed(row["loyalty"]),
        "reaction": _signed(row["reaction"]),
    }


def _ranked(rows: list[dict[str, Any]], name: str) -> list[dict[str, Any]]:
    """The rows whose name holds `name`: the exact name, then names starting with it, then the rest; shorter first."""
    wanted = name.strip().lower()
    found = [row for row in rows if wanted in row["name"].lower()]
    return sorted(
        found,
        key=lambda row: (
            0 if row["name"].lower() == wanted else 1 if row["name"].lower().startswith(wanted) else 2,
            len(row["name"]),
            row["name"].lower(),
        ),
    )


DICE = re.compile(r"\d*d\d+(?:\s*[+-]\s*\d+)?")
ATTACK = re.compile(r"(\d+)?\s*[^(),\d]*?\(([^)]*)\)")
DEFENCES = ("Immunities and Resistances", "Special Defences", "Special Defenses")


def hit_dice_number(text: str) -> float:
    """A monster's Hit Dice as a number for the to-hit table: "3+1" is just over 3, "1-1" under 1, "1d4 hp" and
    "½" a fraction of one, "9 to 11" 9; 0 for none."""
    low = text.lower().replace("–", "-")
    if "½" in low or "1/2" in low or re.match(r"^[\d\-d ]+\s*h(p|it\s*point)", low):
        return 0.5
    found = re.match(r"\s*(\d+)\s*([+-])\s*(\d+)", low)
    if found:
        whole = int(found.group(1))
        return whole + 0.5 if found.group(2) == "+" else whole - 0.1
    number = re.search(r"\d+", low)
    return float(number.group()) if number else 0.0


def monster_thac0(hit_dice: str) -> int:
    """Gamemaster Guide Table 2.1.2A: a monster's THAC0 by its Hit Dice."""
    hd = hit_dice_number(hit_dice)
    rows = load("combat")["monster_to_hit_by_hd"]["table"]
    return next(int(row["thac0"]) for row in rows if hd <= row["hd_max"])


def attacks(line: str) -> tuple[str, str]:
    """`(no_of_attacks, damage_attack)` of the guide's attack line: "3 (1d8/1d8/3d10)" is 3 and 1d8/1d8/3d10;
    "2 claws (1d3), 1 bite (1d6)" is 3 and 1d3/1d3/1d6; "1d12 or by weapon" is 1 and itself."""
    text = line.strip()
    whole = re.match(r"^(\d+)\s*\(([^)]*)\)\s*$", text)
    if whole:
        return whole.group(1), whole.group(2).strip()
    parts = ATTACK.findall(text)
    if parts:
        damage = []
        for count, inside in parts:
            dice = DICE.search(inside)
            damage += [dice.group().replace(" ", "") if dice else inside.strip()] * int(count or 1)
        return str(len(damage)), "/".join(damage)
    count = re.match(r"^(\d+)\b(?!d)", text)
    return (count.group(1) if count else "1"), text


def _limit_text(limit: Limit) -> str:
    """A level limit as the DM reads it: "9", "unlimited", "9 (strength 18+), 8 (17+), 7"."""
    if isinstance(limit, int | str):
        return str(limit)
    if "rule" in limit:
        return f"by {limit['by']}: {limit['rule']}"
    steps = [f"{level} ({limit['by']} {floor}+)" if floor else str(level) for floor, level in limit["at"]]
    return ", ".join(steps)


def _hit_dice(cls: dict[str, Any], row: dict[str, Any]) -> str:
    """A level's hit dice: "3d10", or "9d10+3" past the class's last die."""
    dice = f"{row['hd_count']}d{cls['hit_die']}"
    return f"{dice}+{row['hp_bonus']}" if row.get("hp_bonus") else dice


def _by_level(rows: list[dict[str, Any]], level: int, key: str) -> Any:
    return next((row[key] for row in rows if row["min"] <= level <= row["max"]), None)


class OsricReference:
    """OSRIC's tables as a `RulesetReference`."""

    def monster(self, name: str) -> list[dict]:
        """Monsters matching `name`, best first, at most 10: the exact name (or the guide's index name), the family's
        ("Badger" finds both badgers), names ending in it ("Cave bear"), names starting with it, names holding it as a word, any substring; when nothing matches, a name
        holding every word of a query of two or more words ("red dragon" finds "Dragon, red")."""
        wanted = name.strip().lower()
        if not wanted:
            return []
        rows = load("monsters")["monsters"]

        def rank(m: dict[str, Any]) -> int | None:
            low = m["name"].lower()
            if low == wanted or (m.get("index_name") or "").lower() == wanted:  # the guide's own name too (DEL-325)
                return 0
            if (m.get("family") or "").lower() == wanted:
                return 1
            # Its kind, said last as a player names it ("Cave bear" for "bear", DEL-325), before a longer word.
            if re.search(rf"\b{re.escape(wanted)}s?(?: \(.*\))?$", low):
                return 2
            if low.startswith(wanted):
                return 3
            if re.search(rf"\b{re.escape(wanted)}\b", low):
                return 4
            return 5 if wanted in low else None

        ranked = sorted(
            ((r, len(m["name"]), m["name"].lower(), m) for m in rows if (r := rank(m)) is not None), key=lambda t: t[:3]
        )
        found = [m for *_, m in ranked]
        words = re.findall(r"[a-z]+", wanted)
        if not found and len(words) > 1:
            found = sorted(
                (m for m in rows if all(w in m["name"].lower() for w in words)), key=lambda m: len(m["name"])
            )
        return [self._monster(m) for m in found[:MOST]]

    @staticmethod
    def _monster(m: dict[str, Any]) -> dict[str, Any]:
        sections = m.get("sections") or {}
        count, damage = attacks(m.get("attacks") or "")
        return {
            "name": m["name"],
            "frequency": m.get("frequency") or "",
            "no_appearing": m.get("no_encountered") or "",
            "armor_class": (m.get("armour_class") or "").replace("–", "-"),
            "move": m.get("move") or "",
            "hit_dice": (m.get("hit_dice") or "").replace("–", "-"),
            "thac0": monster_thac0(m.get("hit_dice") or ""),
            "pct_in_lair": m.get("lair_chance") or "",
            "treasure_type": m.get("loot") or "",
            "no_of_attacks": count,
            "damage_attack": damage,
            "attacks": m.get("attacks") or "",
            "special_attacks": sections.get("Special Attacks", ""),
            "special_defenses": " ".join(sections[k] for k in DEFENCES if k in sections),
            "magic_resistance": m.get("magic_resistance") or "",
            "intelligence": m.get("intelligence") or "",
            "alignment": m.get("alignment") or "",
            "size": m.get("size") or "",
            "senses": m.get("senses") or "",
            "morale": m.get("morale") or "",
            "xp_value": m.get("experience") or "",
            "description": m.get("description") or "",
            "sections": sections,
            "family": m.get("family"),
            "source": f"{SOURCE} Gamemaster Guide, p. {m['page']}",
        }

    def spell(self, name: str, caster: str = "") -> list[dict]:
        rows = [self._spell(s) for s in load("spells")["spells"]]
        if caster.strip():
            wanted = spell_list(caster)
            rows = [row for row in rows if row["caster"] == wanted]
        return _ranked(rows, name)[:MOST]

    @staticmethod
    def _spell(spell: dict[str, Any]) -> dict[str, Any]:
        return {
            "name": spell["name"],
            "level": str(spell["level"]),
            "caster": spell["class"],
            "school": spell.get("school") or "",
            "range": spell.get("range") or "",
            "aoe": spell.get("area_of_effect") or "",
            "components": spell.get("components") or "",
            "casting_time": spell.get("casting_time") or "",
            "duration": spell.get("duration") or "",
            "save": spell.get("saving_throw") or "",
            "reversible": "1" if spell.get("reverse") else "0",
            "description": spell.get("description") or "",
            "source": SOURCE,
        }

    def item(self, name: str, item_type: str = "", max_rarity: int = 100, limit: int = 20) -> list[dict]:
        rows = [row for row in self._items() if item_type.lower() in row["item_type"]]
        return _ranked(rows, name)[:limit]

    @staticmethod
    def _items() -> list[dict[str, Any]]:
        equipment, combat = load("equipment"), load("combat")
        rows = [
            {"name": e["name"], "item_type": kind, "cost": e["cost_raw"], "weight": e.get("weight_lb"), "rarity": 0}
            for kind in ("general", "containers")
            for e in equipment[kind]
        ]
        rows += [
            {"name": e["name"], "item_type": "mount", "cost": e["cost_raw"], "weight": None, "rarity": 0}
            for e in equipment["mounts"]
        ]
        for kind in ("melee_weapons", "missile_weapons"):
            for key, w in own(combat[kind]).items():
                rows.append(
                    {
                        "name": key.replace("_", " ").capitalize(),
                        "item_type": "weapon_melee" if kind == "melee_weapons" else "weapon_missile",
                        "cost": w.get("cost") or "",
                        "weight": w.get("weight"),
                        "rarity": 0,
                        "damage_sm": w.get("damage_vs_medium") or "",
                        "damage_l": w.get("damage_vs_large") or "",
                        "speed": w.get("speed_factor"),
                    }
                )
        for kind in ("armour", "shields"):
            for key, a in own(combat[kind]).items():
                if key != "none":
                    rows.append(
                        {
                            "name": key.replace("_", " ").capitalize(),
                            "item_type": "armor" if kind == "armour" else "shield",
                            "cost": f"{a.get('cost_gp', 0)} gp",
                            "weight": a.get("weight"),
                            "rarity": 0,
                            "ac": a.get("ac_descending"),
                        }
                    )
        return rows

    def char_class(self, name: str) -> dict | None:
        key = re.sub(r"\s+", "-", name.strip().lower())
        found = key if key in CLASSES else next((c for c in CLASSES if key and key in c), None)
        if found is None:
            return None
        cls = load("classes")[found]
        skills = (cls.get("thief_skills") or {}).get("by_level")
        return {
            "name": cls["name"],
            "hit_die": f"d{cls['hit_die']}",
            "prime_requisite": cls.get("prime_requisite") or "",
            "xp_bonus": f"10% XP with {cls['prime_requisite']} {cls['xp_bonus_threshold']}+"
            if cls.get("prime_requisite") and cls.get("xp_bonus_threshold")
            else "",
            "minimum_scores": cls.get("minimum_scores") or {},
            "armour_allowed": cls.get("armour_allowed"),
            "shield_allowed": cls.get("shield_allowed"),
            "weapons_allowed": cls.get("weapons_allowed"),
            "nonproficiency_penalty": -NONPROFICIENT[found],
            "initial_gold": cls.get("initial_gold") or "",
            "spellcaster": own(cls["spellcaster"]) if cls.get("spellcaster") else None,
            "thief_skills": skills,
            "special_abilities": features(found),
            "ancestries": {
                ancestry: _limit_text(LEVEL_LIMITS.get(ancestry, {}).get(found, "unlimited"))
                for ancestry, allowed in ANCESTRY_CLASSES.items()
                if found in allowed
            },
            "multi_class": sorted(
                {c for allowed in ANCESTRY_CLASSES.values() for c in allowed if "/" in c and found in c.split("/")}
            ),
            "description": "",
            "source": SOURCE,
        }

    def race(self, name: str) -> dict | None:
        key = re.sub(r"[\s_]+", "-", name.strip().lower())
        key = {"halfelf": "half-elf", "halforc": "half-orc", "dwarven": "dwarf", "elven": "elf"}.get(key, key)
        rows = own(load("ancestry"))
        if key not in rows:
            return None
        row = rows[key]
        return {
            "name": row["name"],
            "ability_adjustments": row.get("ability_modifiers") or {},
            "ability_ranges": row.get("ability_ranges") or {},
            "size": row.get("size"),
            "movement_ft": row.get("base_movement_ft"),
            "infravision_ft": row.get("infravision_ft"),
            "classes": list(ANCESTRY_CLASSES[key]),
            "level_limits": {cls: _limit_text(limit) for cls, limit in LEVEL_LIMITS.get(key, {}).items()},
            "features": row.get("features") or [],
            "thief_skill_adjustments": row.get("thief_skill_adjustments") or {},
            "source": SOURCE,
        }

    def class_levels(self, name: str) -> list[dict]:
        found = self.char_class(name)
        if found is None:
            return []
        key = re.sub(r"\s+", "-", found["name"].lower())
        cls = load("classes")[key]
        out = []
        for row in cls["levels"]:
            level = int(row["level"])
            saves = {f"save_{kind}": _by_level(cls["saving_throws"], level, kind) for kind in SAVE_TYPES}
            slots = (cls.get("spell_slots") or {}).get(str(level))
            out.append(
                {
                    "level": level,
                    "xp_required": int(row["xp"]),
                    "hit_dice": _hit_dice(cls, row),
                    "thac0": _by_level(cls["thac0_by_level"], level, "thac0"),
                    **saves,
                    "spell_slots": slots,
                }
            )
        return out

    def ability(self, ability: str, score: str) -> dict:
        name = ABILITIES.get(ability.strip().lower()[:3])
        if name is None or not ability.strip().lower().startswith(name[:3]):
            return {"error": f"Unknown ability '{ability}'.", "hint": f"Use one of: {', '.join(ABILITIES.values())}."}
        found: dict[str, Any] = {
            "ability": name,
            "headline": HEADLINES[name],
            "xp_bonus": "",
            "extra": "",
            "columns": [{"name": label, "short_name": short, "note": ""} for short, label in COLUMNS[name]],
        }
        table = load("ability_scores")[name]
        if not score.strip():
            rows = own(table["normal"] if name == "strength" else table)
            found["rows"] = [{"score": s, **_values(name, row)} for s, row in rows.items() if s.isdigit()]
            if name == "strength":
                found["rows"] += [{"score": row["label"], **_values(name, row)} for row in table["exceptional"]]
            return found
        row = strength_row(score) if name == "strength" else table.get(score.strip())
        if row is None:
            return {"error": f"No {name} score '{score}'.", "hint": "Give a score the table has, such as 12 or 18/50."}
        return {**found, "score": row.get("label", score.strip()), "values": _values(name, row)}

    def proficiency(self, name: str = "", group: str = "", ability: str = "") -> list[dict]:
        return []

    def turning_undead(self) -> list[dict]:
        out = []
        for number, row in enumerate(load("turning")["table"], start=1):
            kind = UNDEAD[number - 1]
            out.append(
                {
                    "undead_type": f"{row['example']} (Type {number})",
                    "min_hd": None,
                    "max_hd": None,
                    "results": [row["results"][column]["raw"] for column in TURNING_COLUMNS],
                    "aliases": [kind, f"type {number}"],
                }
            )
        return out

    def rules_search(self, query: str, source: str = "", limit: int = 5) -> list[dict]:
        return text.search(query, source, limit)

    def rules_section(self, source: str, section: str) -> list[dict]:
        return text.section(source, section)

    def encounter_tables(self) -> dict:
        return {}

    def osric_magic_items(self) -> dict:
        return {}
