"""The character's derived numbers under 3.5 (DEL-388): BAB, the three saves, AC, initiative, skill totals, spell slots
and DCs, from the class table, the race's traits, the SRD's armour table and the ability table. They read a reference
only, never `Ruleset.tables` or storage.

Race adjustments are already in the scores the DM writes, so they are not added again. Numbers in the data come with
typographic signs ("+3", "–2") or plain ones ("3", "-1"); `signed` reads both."""

from __future__ import annotations

import re
from collections.abc import Iterable
from functools import cache
from importlib import resources
from typing import Any

from delve.domain.characters import Sheet
from delve.rules.classic.checks import CheckError
from delve_srd35.tables import slowed

CASTERS = {"cleric": "wis", "wizard": "int"}
"""The slice's casting classes and their key ability."""
ARCANE = frozenset({"wizard"})
"""The classes armour can make fail."""
SIZE = {"small": {"ac": 1, "hide": 4}, "large": {"ac": -1, "hide": -4}}
"""Size's modifiers to AC and Hide (the SRD's Small and Large); Medium has none."""
UNCANNY_DODGE = 4
"""The rogue level that gives uncanny dodge: Dex (and dodge) kept to AC when flat-footed (DEL-396)."""
SAVE_FEATS = {"fort": "great-fortitude", "ref": "lightning-reflexes", "will": "iron-will"}
SAVE_ABILITY = {"fort": "con", "ref": "dex", "will": "wis"}
CLASSIC_SKILLS = {"pick-locks": "open-lock", "open-locks": "open-lock", "pick-pockets": "sleight-of-hand",
                  "hide-in-shadows": "hide", "find-traps": "search", "remove-traps": "disable-device",
                  "climb-walls": "climb", "hear-noise": "listen", "read-languages": "decipher-script"}  # fmt: skip
"""The classic thief skills by the 3.5 skill that does their job, so the classic wording finds one ("pick")."""

_SIGNED = re.compile(r"[+-]?\d+")
_DASHES = str.maketrans({"–": "-", "−": "-", "—": " "})  # en dash and minus sign are signs; an em dash is "none"


def modifier(score: int) -> int:
    return (score - 10) // 2


def signed(text: Any) -> int | None:
    """The first number in `text` with its sign: "+6/+1" is 6, "–2" is -2, "18–20" is 18; None for "—" or ""."""
    if isinstance(text, int):
        return text
    found = _SIGNED.search(str(text).translate(_DASHES))
    return int(found.group()) if found else None


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def class_row(reference: Any, cls: str, level: int) -> dict[str, Any]:
    """The class table's row at `level`, with its BAB and base saves as numbers (the first attack of "+6/+1")."""
    found = reference.char_class(cls)
    if found is None or found["id"] != slug(cls):
        raise ValueError(f"Unknown class '{cls}'.")
    row = next((r for r in found["levels"] if r["level"] == level), None)
    if row is None:
        raise ValueError(f"The {found['name'].lower()} table has no level {level}.")
    return {**row, **{key: signed(row[key]) or 0 for key in ("bab", "fort", "ref", "will")}}


@cache
def armour_table() -> dict[str, dict[str, Any]]:
    """The SRD's table of armour and shields, by slug ("scale-mail", "shield-heavy-steel"): the armour or shield bonus,
    the maximum Dex bonus (None for a shield without one), the armour check penalty, the arcane spell failure %, its
    group (`category`: light, medium, heavy or shield) and the speed in it by unencumbered speed (`speed`, {30: 20,
    20: 15} for medium armour; empty for a shield). Read from the pack's own copy of the SRD's armour section, where
    the table's numbers are: the rows of its Table: Armor and Shields from "Light armor" to "Extras" (name, cost,
    bonus, maximum Dex, check penalty, failure, speed (30 ft.), speed (20 ft.), …) under their group's heading."""
    text = resources.files("delve_srd35").joinpath("rules", "08-03-armor.md").read_text("utf-8")
    lines = text.split("| Light armor |", 1)[1].split("| Extras |", 1)[0].splitlines()
    table = {}
    category = "light"
    for line in lines:
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if heading := re.fullmatch(r"(Medium|Heavy) armor|Shields", cells[0]):
            category = (heading.group(1) or "shield").lower()
            continue
        if len(cells) < 8 or not re.fullmatch(r"\+\d+\D?", cells[2]) or not (fail := re.fullmatch(r"(\d+)%", cells[5])):
            continue
        name = cells[0]
        speeds = {base: found for base, cell in zip((30, 20), cells[6:8], strict=True) if (found := signed(cell))}
        table[slug(name)] = {"name": name, "bonus": signed(cells[2]), "max_dex": signed(cells[3]),
                             "acp": signed(cells[4]), "failure": int(fail.group(1)), "category": category,
                             "speed": speeds}  # fmt: skip
    return table


SLOWING = frozenset({"medium", "heavy"})
"""The armour that slows its wearer (the SRD's Speed: "Medium or heavy armor slows the wearer down")."""
RUN_IN_HEAVY = 3
"""Table: Armor and Shields, note 2: "When running in heavy armor, you move only triple your speed, not quadruple"."""


def armoured_speed(armour: dict[str, Any] | None, race: dict[str, Any], base: int) -> int:
    """The speed in feet in `armour` (an `armour_table` row, or None) of a character of `race` whose unencumbered
    speed is `base`: the table's column for 30 ft. or 20 ft. in medium or heavy armour, a speed off the table reduced
    as a load reduces it (Armor and Encumbrance for Other Base Speeds, `tables.slowed`); light armour's is `base`, and
    so is a dwarf's in any armour (DEL-407)."""
    if armour is None or armour["category"] not in SLOWING or unslowed(race):
        return base
    return armour["speed"].get(base) or slowed("heavy", base)


def race_named(reference: Any, name: str) -> dict[str, Any] | None:
    """The race by its name, singular or plural ("Elf", "elves")."""
    single = slug(name)
    if not single:
        return None
    for wanted in (single, single[:-1] + "ves" if single.endswith("f") else single + "s"):
        found = reference.race(wanted.replace("-", " "))
        if found is not None and found["id"] == wanted:
            return found
    return None


UNSLOWED = re.compile(r"move at this speed even when .*carrying a medium or heavy load")
"""The dwarf's trait: "dwarves can move at this speed even when wearing medium or heavy armor or when carrying a medium
or heavy load"."""


def unslowed(race: dict[str, Any] | None) -> bool:
    """Whether the race keeps its speed under a medium or heavy load, read from its traits (DEL-404)."""
    return any(UNSLOWED.search(trait) for trait in (race or {}).get("traits", ()))


def _racial(race: dict[str, Any] | None) -> tuple[dict[str, int], int]:
    """The race's unconditional racial bonuses on skills, by skill id, and on all saves, read from its traits
    ("+2 racial bonus on Listen, Search, and Spot checks."). A bonus with a condition ("on Search checks to notice
    unusual stonework") is the DM's to apply."""
    skills: dict[str, int] = {}
    saves = 0
    for trait in race["traits"] if race else ():
        if found := re.match(r"\+(\d+) racial bonus on all saving throws\.", trait):
            saves += int(found.group(1))
        elif found := re.match(r"\+(\d+) racial bonus on (.+?) checks(?:\.|$)", trait):
            for name in re.split(r",\s*(?:and\s+)?|\s+and\s+", found.group(2)):
                skills[slug(name)] = skills.get(slug(name), 0) + int(found.group(1))
    return skills, saves


SPECIALISED = frozenset({"knowledge", "craft", "profession", "perform"})
"""The skills taken in a speciality ("knowledge-arcana", "craft-weaponsmithing")."""


def skill_row(reference: Any, skill: str) -> dict[str, Any] | None:
    """The skill row for an id, or for a specialised one of `SPECIALISED` ("knowledge-arcana" is Knowledge)."""
    for query in (skill.replace("-", " "), skill.split("-")[0]):
        for row in reference.skill(query):
            if row["id"] == skill or (row["id"] in SPECIALISED and skill.startswith(row["id"] + "-")):
                return row
    return None


def skill_named(reference: Any, name: str, preferred: Iterable[str] = ()) -> str:
    """The skill id for a 3.5 id or name ("open-lock", "Move Silently", "knowledge (arcana)"), a unique part of one
    ("lock", "move"), or a classic thief skill's name or part of it ("pick locks", "pick"). A part that fits several is
    the one of them in `preferred` (the sheet's skills with ranks) when only one is there; else `CheckError` with the
    candidates, as for a name that fits none."""
    wanted = slug(name)
    if not wanted:
        raise CheckError("Name a skill.", hint="Name a skill of the SRD: 'climb', 'open lock', 'spot'.")
    if wanted in CLASSIC_SKILLS:
        return CLASSIC_SKILLS[wanted]
    if skill_row(reference, wanted) is not None:
        return wanted
    found = {row["id"]: row["name"] for row in reference.skill(wanted.replace("-", " "))}
    for alias, skill in CLASSIC_SKILLS.items():
        if wanted in alias and (row := skill_row(reference, skill)) is not None:
            found[skill] = row["name"]
    if len(found) > 1:
        mine = [skill for skill in found if any(p == skill or p.startswith(skill + "-") for p in preferred)]
        if len(mine) == 1:
            return mine[0]
    if len(found) == 1:
        return next(iter(found))
    if found:
        raise CheckError(
            f"Skill '{name}' could be {', '.join(sorted(found.values()))}.",
            hint="Name the skill whole.",
            candidates=sorted(found.values()),
        )
    raise CheckError(f"Unknown skill '{name}'.", hint="Name a skill of the SRD: 'climb', 'open lock', 'spot'.")


def feat_row(reference: Any, feat: str) -> dict[str, Any] | None:
    """The feat row for an id or a name ("power-attack", "Power Attack")."""
    wanted = slug(feat)
    return next((row for row in reference.feat(wanted.replace("-", " ")) if row["id"] == wanted), None)


def feat_ids(sheet: Sheet) -> list[str]:
    return [f["id"] if isinstance(f, dict) else str(f) for f in (sheet.d20 or {}).get("feats", ())]


def feat_problems(sheet: Sheet, reference: Any, bab: int) -> list[str]:
    """What the build's feats need that the sheet hasn't (`feats.json`'s structured prerequisites: an ability score,
    another feat, a base attack bonus, skill ranks, a class or caster level), one line each; an unknown feat is one."""
    ids = feat_ids(sheet)
    ranks = (sheet.d20 or {}).get("skills", {})
    problems = []
    for feat in ids:
        row = feat_row(reference, feat)
        if row is None:
            problems.append(f"Unknown feat '{feat}'.")
            continue
        for need in row["prerequisites"]:
            if (missing := _unmet(need, sheet, reference, ids, ranks, bab)) is not None:
                problems.append(f"{row['name']} needs {missing}.")
    return problems


def _unmet(
    need: dict[str, Any], sheet: Sheet, reference: Any, feats: list[str], ranks: dict[str, Any], bab: int
) -> str | None:
    """What `need` asks that the sheet lacks, in words; None when the sheet has it."""
    kind, least = need["kind"], int(need.get("min", 0))
    if kind == "ability":
        score = ability_score(sheet, need["ability"])
        return None if score >= least else f"{need['ability'].title()} {least} (it is {score})"
    if kind == "feat":
        if need["feat"] in feats:
            return None
        row = feat_row(reference, need["feat"])
        return row["name"] if row else need["feat"]
    if kind == "bab":
        return None if bab >= least else f"base attack bonus +{least} (it is {bab:+d})"
    if kind == "skill":
        have = sum(v for k, v in ranks.items() if k == need["skill"] or k.startswith(need["skill"] + "-"))
        return None if have >= least else f"{least} ranks in {need['skill'].replace('-', ' ')} (it has {have:g})"
    if kind == "class_level":
        cls = need["class"]
        level = sum(sheet.levels.values()) if cls == "character" else sheet.levels.get(cls, 0)
        return None if level >= least else f"{cls} level {least}"
    if kind == "caster_level":
        level = max((sheet.levels.get(c, 0) for c in CASTERS), default=0)
        return None if level >= least else f"caster level {least}"
    return None


def ability_score(sheet: Sheet, ability: str) -> int:
    raw = sheet.ability_scores.get(ability, 10)
    return signed(raw) if signed(raw) is not None else 10


def derived(sheet: Sheet, reference: Any) -> dict[str, Any]:
    """`Sheet.d20["derived"]`: the numbers the build gives."""
    build = sheet.d20 or {}
    warnings: list[str] = []
    mods = {a: modifier(ability_score(sheet, a)) for a in ("str", "dex", "con", "int", "wis", "cha")}
    feats = [f["id"] if isinstance(f, dict) else f for f in build.get("feats", ())]
    chosen = [f for f in build.get("feats", ()) if isinstance(f, dict) and f.get("id") == "skill-focus"]
    focus = {slug(f.get("choice") or "") for f in chosen}

    rows = {}
    for cls, level in sheet.levels.items():
        try:
            rows[cls] = class_row(reference, cls, level)
        except ValueError as error:
            warnings.append(str(error))
    race = race_named(reference, sheet.race)
    if race is None and sheet.race:
        warnings.append(f"Unknown race '{sheet.race}'.")
    size = SIZE.get((race or {}).get("size", "").lower(), {})
    racial_skills, racial_saves = _racial(race)

    worn = []
    for slot in ("armor", "shield"):
        if name := build.get(slot):
            if (piece := armour_table().get(slug(name))) is None:
                warnings.append(f"Unknown armour '{name}'.")
            else:
                worn.append(piece)
    caps = [p["max_dex"] for p in worn if p["max_dex"] is not None]
    max_dex = min(caps) if caps else None
    acp = sum(p["acp"] for p in worn)
    dex = mods["dex"] if max_dex is None else min(mods["dex"], max_dex)
    dodge = int("dodge" in feats)
    armour = sum(p["bonus"] for p in worn)

    saves = {
        save: sum(r[save] for r in rows.values()) + mods[SAVE_ABILITY[save]] + 2 * (SAVE_FEATS[save] in feats)
        + racial_saves
        for save in SAVE_ABILITY
    }  # fmt: skip
    skills = {}
    for skill, ranks in build.get("skills", {}).items():
        row = skill_row(reference, skill)
        if row is None:
            warnings.append(f"Unknown skill '{skill}'.")
            skills[skill] = ranks
            continue
        penalty = acp * (2 if row["id"] == "swim" else 1) if row["armor_check"] else 0
        key = mods.get(row["key_ability"], 0)
        small = size.get("hide", 0) if row["id"] == "hide" else 0
        skills[skill] = ranks + key + 3 * (skill in focus) + penalty + racial_skills.get(skill, 0) + small

    bab = sum(r["bab"] for r in rows.values())
    # A feat whose prerequisite a later change broke (Int lowered under Combat Expertise's 13) stays, with a warning.
    warnings += feat_problems(sheet, reference, bab)
    slots, dc = _slots(rows, mods, sheet, reference)
    rogue = sheet.levels.get("rogue", 0)
    cleric = "cleric" in rows
    uncanny = rogue >= UNCANNY_DODGE
    out = {
        "bab": bab,
        **saves,
        "ac": 10 + armour + dex + size.get("ac", 0) + dodge,
        "touch": 10 + dex + size.get("ac", 0) + dodge,
        "flat_footed": 10 + armour + (dex + dodge if uncanny else min(dex, 0)) + size.get("ac", 0),
        "init": mods["dex"] + 4 * ("improved-initiative" in feats),
        "acp": acp,
        "max_dex": max_dex,
        "spell_failure": sum(p["failure"] for p in worn) if ARCANE & set(rows) else 0,
        "skills": skills,
        "slots": slots,
        "dc": dc,
        "sneak": f"{(rogue + 1) // 2}d6" if rogue else "",
        "turning_per_day": max(0, 3 + mods["cha"] + 4 * feats.count("extra-turning")) if cleric else 0,
    }
    body = next((p for p in worn if p["category"] != "shield"), None)  # "Shields do not affect a character's speed."
    if race is not None and race.get("speed"):
        # The race's base land speed in feet in the armour worn, the sheet's `movement_rate` (DEL-404, DEL-407); the
        # unarmoured one beside it when the armour slows, for a load to slow no more than it (`loaded_speed`).
        out["speed"] = armoured_speed(body, race, race["speed"])
        if out["speed"] != race["speed"]:
            out["base_speed"] = race["speed"]
    if body is not None and body["category"] == "heavy":
        out["run_multiplier"] = RUN_IN_HEAVY  # for the DM: nothing in core runs
    if uncanny:
        out["uncanny_dodge"] = True
    if warnings:
        out["warnings"] = warnings
    return out


def _slots(rows: dict[str, dict[str, Any]], mods: dict[str, int], sheet: Sheet, reference: Any) -> tuple[dict, dict]:
    """The slots and DCs by spell level ("0", "1" …) of the first casting class: the table's spells per day, the key
    ability's bonus spells (none on level 0), and a cleric's domain slot on levels 1 and up. A key ability under
    10 + the spell level casts none of that level (the SRD's rule)."""
    cls = next((c for c in rows if c in CASTERS), None)
    if cls is None:
        return {}, {}
    ability = CASTERS[cls]
    score = ability_score(sheet, ability)
    by_level = reference.ability(ability, str(score)).get("values", {}).get("bonus_spells", "").split()
    bonus = {str(n): int(b) for n, b in enumerate(by_level, 1)}
    slots, dc = {}, {}
    for level, cell in rows[cls]["spells_per_day"].items():
        base = signed(cell)
        if base is None or score < 10 + int(level):
            continue
        extra = 0 if level == "0" else bonus.get(level, 0) + (cls == "cleric")
        if base + extra:
            slots[level] = base + extra
            dc[level] = 10 + int(level) + mods[ability]
    return slots, dc
