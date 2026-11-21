"""The character's derived numbers under 3.5 (DEL-388): BAB, the three saves, AC, initiative, skill totals, spell slots
and DCs, from the class table, the race's traits, the SRD's armour table and the ability table. They read a reference
only, never `Ruleset.tables` or storage.

Race adjustments are already in the scores the DM writes, so they are not added again. Numbers in the data come with
typographic signs ("+3", "–2") or plain ones ("3", "-1"); `signed` reads both."""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from dataclasses import replace
from fractions import Fraction
from functools import cache
from importlib import resources
from itertools import permutations
from typing import Any

from delve.domain.characters import Sheet
from delve.rules.classic.checks import CheckError
from delve_srd35 import data
from delve_srd35.engine import features as class_features
from delve_srd35.engine import items
from delve_srd35.tables import slowed

SIZE = {"fine": {"ac": 8, "hide": 16}, "diminutive": {"ac": 4, "hide": 12}, "tiny": {"ac": 2, "hide": 8},
        "small": {"ac": 1, "hide": 4}, "large": {"ac": -1, "hide": -4}, "huge": {"ac": -2, "hide": -8},
        "gargantuan": {"ac": -4, "hide": -12}, "colossal": {"ac": -8, "hide": -16}}  # fmt: skip
"""Size's modifiers to AC and Hide (the SRD's Table: Creature Sizes); Medium has none."""
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


def reduction(value: Any) -> list[dict[str, Any]]:
    """Damage reduction in the list shape a monster row has (`[{"value": 10, "bypass": ["magic"]}]`, "a or b" as
    `bypass_any`), from that list, from a derived "<value>/<bypass>" ("2/—", "5/cold iron and good", "10/magic or
    silver"), or from a number (a combatant stored when a barbarian's DR was its int: N/—); [] for none."""
    if isinstance(value, list):
        return [dict(entry) for entry in value if isinstance(entry, dict) and int(entry.get("value") or 0) > 0]
    if isinstance(value, int) or (isinstance(value, str) and "/" not in value):
        number = signed(value) or 0
        return [{"value": number, "bypass": ["—"]}] if number > 0 else []
    if not isinstance(value, str):
        return []
    number, _, said = value.partition("/")
    amount = signed(number) or 0
    words = said.translate(_DASHES).replace("-", " ").strip() or "—"
    if amount <= 0:
        return []
    if " or " in words:
        return [{"value": amount, "bypass_any": [w.strip() for w in words.split(" or ")]}]
    return [{"value": amount, "bypass": [w.strip() for w in words.split(" and ")]}]


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
    """The race by its name, singular or plural ("Elf", "elves"): a core race of `races.json`, else a monster that
    can be a character race (`monster_race`)."""
    single = slug(name)
    if not single:
        return None
    for wanted in (single, single[:-1] + "ves" if single.endswith("f") else single + "s"):
        found = reference.race(wanted.replace("-", " "))
        if found is not None and found["id"] == wanted:
            return found
    return monster_race(reference, name)


# --- monsters as characters (DEL-389) ---------------------------------------------------------------------------

TYPE_SKILL_POINTS = {"aberration": 2, "animal": 2, "construct": 2, "dragon": 6, "elemental": 2, "fey": 6, "giant": 2,
                     "humanoid": 2, "magical beast": 2, "monstrous humanoid": 2, "ooze": 2, "outsider": 8, "plant": 2,
                     "undead": 4, "vermin": 2}  # fmt: skip
"""The skill points per racial Hit Die by creature type (the SRD's types: (N + Int modifier) per Hit Die, ×4 on the
first), for a monster whose entry has no "Racial Skills" line."""
_PLAIN_LA = re.compile(r"\+(\d+)")
_DICE = re.compile(r"(\d+(?:/\d+)?)\s*(d\d+)")
_NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8}
_RACIAL_HD = re.compile(
    r"Racial Hit Dice: .*?(\w+) levels? of [\w ]+?, which provide (\d+)(d\d+) Hit Dice, a base attack bonus of "
    r"([+-]?\d+), and base saving throw bonuses of Fort ([+-]?\d+), Ref ([+-]?\d+), and Will ([+-]?\d+)"
)
_RACIAL_SKILLS = re.compile(r"Racial Skills: .*?skill points equal to (\d+) [x×] \((\d+) \+ Int")
_CLASSED = re.compile(r"(?i)^\d+(?:st|nd|rd|th)-level \w+ (.+)$")
"""A stat block's sample character ("4th-level Barbarian Ogre"): the base creature is the rest of its name."""
_FORM = re.compile(r"(?i)^.+? form (.+)$")
"""A lycanthrope's form ("Human Form Werewolf"): the lycanthrope is the rest of its name."""
_RACIAL_FEATS = re.compile(r"Racial Feats: .*? give it (\w+) feats?")
_NATURAL = re.compile(r"\+(\d+) natural")


def monster_row(reference: Any, name: str) -> dict[str, Any] | None:
    """The monster entry named `name` exactly (its id or name, singular or plural: "gnoll", "Gnolls")."""
    wanted = slug(name)
    if not wanted:
        return None
    singular = {wanted, wanted.removesuffix("s"), wanted.removesuffix("es")}
    for query in sorted(singular, key=len, reverse=True):
        for row in reference.monster(query.replace("-", " ")):
            if row.get("id") in singular or slug(row.get("name", "")) in singular:
                return row
    return None


def _not_a_race(row: dict[str, Any]) -> str | None:
    """Why a monster entry isn't a race whatever its level adjustment: a sample character with class levels (its
    numbers include the class's), a lycanthrope's form, or an entry with no stat block of its own (a subrace given
    as text, the drow's)."""
    name = row["name"]
    if classed := _CLASSED.match(name):
        return (f"{name} can't be a character race: it is a sample character with class levels; play the "
                f"{classed.group(1)} and give it the class instead.")  # fmt: skip
    if form := _FORM.match(name):
        return f"{name} can't be a character race: it is one form of the {form.group(1)}, a lycanthrope."
    if not str(row.get("hit_dice") or "").strip() or not row.get("abilities"):
        return f"{name} can't be a character race yet: its entry has no stat block of its own (a subrace)."
    return None


def race_refusal(reference: Any, name: str) -> str | None:
    """Why the monster `name` can't be a character race (`_not_a_race`, or its level adjustment isn't a plain "+N":
    "—", "+3 (cohort)", a dragon's by age); None when it can or when no monster has that name."""
    row = monster_row(reference, name)
    if row is None:
        return None
    if _PLAIN_LA.fullmatch(row.get("level_adjustment", "").strip()):
        return _not_a_race(row)
    if not str(row.get("level_adjustment") or "").strip():
        return f"{row['name']} can't be a character race: its entry gives no level adjustment."
    return f"{row['name']} can't be a character race: its level adjustment is '{row.get('level_adjustment', '')}'."


_SECTION = re.compile(r"(?im)^[^\n.]{1,60}? (?:as )?characters$")


def _as_characters(text: str) -> list[str]:
    """The trait lines of an entry's "… AS CHARACTERS" section ("—Medium size."), without their dashes; the heading
    in any case, with or without "as" ("Jann as Characters", "KOBOLD CHARACTERS")."""
    parts = _SECTION.split(text, maxsplit=1)
    if len(parts) < 2:
        return []
    section = parts[1]
    return [line.strip().lstrip("—").strip() for line in section.splitlines() if line.strip().startswith("—")]


def monster_race(reference: Any, name: str) -> dict[str, Any] | None:
    """A race-shaped dict from the monster entry `name` whose level adjustment is a plain "+N" (None otherwise, for
    an entry `_not_a_race` refuses, and
    for a name no monster has): its size and base land speed; its racial Hit Dice (`racial_hd`, {"levels", "die"}),
    their base attack (`racial_bab`) and base saves (`racial_saves`), from its "Racial Hit Dice" line or else its stat
    block (the base attack of "+1/+3"; each save less its ability's modifier and a save feat's +2); its natural armour
    (the AC's "+N natural", or the "+N natural armor bonus" line); its level adjustment (int); its racial skill points
    (`racial_skill_points`: {"per_hd", "times"}, the "Racial Skills" line's "5 x (8 + Int modifier)", else the type's
    points × (Hit Dice + 3)), their class skills and its racial feats (the "Racial Feats" line, else 1 + HD / 3); its
    favoured class and its trait lines. A monster of 1 Hit Die or less trades it for its class levels (the SRD: such
    creatures "exchange the features of their humanoid Hit Die for the class features of a PC or NPC class"): 0
    racial levels, and no racial base attack, saves, skill points or feats."""
    row = monster_row(reference, name)
    if row is None or not (la := _PLAIN_LA.fullmatch(row.get("level_adjustment", "").strip())) or _not_a_race(row):
        return None
    traits = _as_characters(row.get("text", ""))
    lines = "\n".join(traits)
    dice = _DICE.search(str(row.get("hit_dice", "")))
    count, die = (Fraction(dice.group(1)), dice.group(2)) if dice else (Fraction(0), "d8")
    saves = {save: 0 for save in SAVE_ABILITY}
    bab, points, feats = 0, {"per_hd": 0, "times": 0}, 0
    levels = 0
    kind = str(row.get("type", "")).strip().lower()
    if hd := _RACIAL_HD.search(lines):
        levels, die, bab = int(hd.group(2)), hd.group(3), int(hd.group(4))
        saves = dict(zip(SAVE_ABILITY, (int(hd.group(n)) for n in (5, 6, 7)), strict=True))
    elif count > 1:
        levels = int(count)
        bab = signed(str(row.get("base_attack_grapple", "")).split("/")[0]) or 0
        listed = {slug(f.split("(")[0]) for f in str(row.get("feats", "")).split(",")}
        abilities = row.get("abilities") or {}
        for save, ability in SAVE_ABILITY.items():
            score = signed(abilities.get(ability, "10"))
            mod = modifier(score) if score is not None and score > 0 else 0  # a construct's Con "—" reads "-1"
            given = signed((row.get("saves") or {}).get(save, "0")) or 0
            saves[save] = given - mod - 2 * (SAVE_FEATS[save] in listed)
    if levels:
        if skills := _RACIAL_SKILLS.search(lines):
            points = {"per_hd": int(skills.group(2)), "times": int(skills.group(1))}
        else:
            points = {"per_hd": TYPE_SKILL_POINTS.get(kind, 2), "times": levels + 3}
        found = _RACIAL_FEATS.search(lines)
        feats = _NUMBER_WORDS.get(found.group(1).lower(), 1) if found else 1 + levels // 3
    if listed_skills := re.search(r"Racial Skills: .*?class skills are ([^.]+)\.", lines):
        class_skills = [slug(s) for s in re.split(r",\s*(?:and\s+)?|\s+and\s+", listed_skills.group(1))]
    else:
        class_skills = [slug(s) for s in (row.get("skills") or {})]
    natural = _NATURAL.search(lines) or _NATURAL.search(str(row.get("armor_class", "")))
    speed_text = str(row.get("speed", ""))
    speed = re.search(r"base (?:land )?speed (\d+)", speed_text) or re.search(r"(\d+) ft", speed_text)
    favoured = next((slug(found.group(1)) for t in traits if (found := _FAVOURED.match(t))), None)
    return {
        "id": row["id"],
        "name": row["name"],
        "monster": True,
        "type": kind,
        "size": str(row.get("size", "Medium")).strip() or "Medium",
        "speed": int(speed.group(1)) if speed else 30,
        "racial_hd": {"levels": levels, "die": die},
        "racial_bab": bab,
        "racial_saves": saves,
        "racial_skill_points": points,
        "racial_class_skills": class_skills if levels else [],
        "racial_feats": feats,
        "natural_armour": int(natural.group(1)) if natural else 0,
        "level_adjustment": int(la.group(1)),
        "la": int(la.group(1)),
        "favoured_class": favoured,
        "traits": traits,
    }


def racial_levels(race: dict[str, Any] | None) -> int:
    """The race's racial Hit Dice that count as levels (a core race's: none)."""
    return int(((race or {}).get("racial_hd") or {}).get("levels", 0))


def character_level(sheet: Sheet, reference: Any) -> int:
    """The character's Hit Dice, racial and class, without its level adjustment: the level for feats, ability
    increases, skill points and max ranks (the SRD)."""
    return racial_levels(race_named(reference, sheet.race)) + sum(sheet.levels.values())


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


ENGINE_SYNERGIES = frozenset({"turning"})
"""The checks no skill total holds whose synergy the engine adds itself: Knowledge (religion)'s on the turning check
(`magic.turn_undead`)."""


def skill_title(skill: str) -> str:
    """A skill id as the SRD names it: "knowledge-religion" is "Knowledge (religion)", "use-rope" "Use Rope"."""
    head, _, rest = skill.partition("-")
    if head in SPECIALISED and rest:
        return f"{head.title()} ({rest.replace('-', ' ')})"
    return " ".join(word if word in ("of",) else word.title() for word in skill.split("-"))


def _ranks_in(ranks: dict[str, float], skill: str) -> float:
    """The ranks in `skill`; for a specialised skill named without its speciality ("craft": "any Craft skill"), the
    best speciality's."""
    if skill in SPECIALISED:
        return max((float(v) for k, v in ranks.items() if k == skill or k.startswith(skill + "-")), default=0.0)
    return float(ranks.get(skill, 0))


def synergies(ranks: dict[str, float], target: str) -> list[dict[str, Any]]:
    """The synergy rows on `target` (a skill id or a check, `data/synergies.json`) whose skill has its ranks (5)."""
    rows = data.load("synergies")
    return [row for row in rows if row["to"] == target and _ranks_in(ranks, row["from"]) >= row["ranks"]]


def synergy_bonus(ranks: dict[str, float], target: str) -> int:
    """The unconditional synergy bonuses on `target`: +2 a skill with 5 ranks that gives one ("If you have 5 or more
    ranks in Tumble, you get a +2 bonus on Jump checks"); bonuses from several skills add up (the SRD lists each)."""
    return sum(row["bonus"] for row in synergies(ranks, target) if row["condition"] is None)


def synergy_said(row: dict[str, Any]) -> str:
    """A synergy as the sheet notes it: "+2 on Escape Artist checks when escaping from rope bonds (Use Rope 5+ ranks)",
    "+2 on bardic knowledge checks (Knowledge (history) 5+ ranks)"."""
    on = skill_title(row["to"]) if skill_row_id(row["to"]) else row["to"].replace("-", " ")
    when = f" {row['condition']}" if row["condition"] else ""
    return f"+{row['bonus']} on {on} checks{when} ({skill_title(row['from'])} {row['ranks']}+ ranks)"


def skill_notes(ranks: dict[str, float]) -> dict[str, list[str]]:
    """The synergies no skill total adds, by the skill or check they are on: the conditional ones (Use Rope's on
    "Escape Artist checks when escaping from rope bonds") and those on a check that is no skill (Knowledge (history)'s
    on bardic knowledge, Handle Animal's on wild empathy), but those the engine adds itself (`ENGINE_SYNERGIES`)."""
    out: dict[str, list[str]] = {}
    for row in data.load("synergies"):
        if row["to"] in ENGINE_SYNERGIES or _ranks_in(ranks, row["from"]) < row["ranks"]:
            continue
        if row["condition"] is not None or skill_row_id(row["to"]) is None:
            out.setdefault(row["to"], []).append(synergy_said(row))
    return out


def skill_row_id(target: str) -> str | None:
    """`target` when it is a skill of `data/skills.json` (a speciality of a `SPECIALISED` one too), else None."""
    ids = {row["id"] for row in data.load("skills")}
    return target if target in ids or target.split("-")[0] in SPECIALISED & ids else None


JUMP_SPEED, JUMP_STEP, JUMP_SLOWER, JUMP_FASTER = 30, 10, -6, 4
"""Jump's speed modifier: "If your speed is less than 30 feet, you take a -6 penalty for every 10 feet of speed less
than 30 feet. If your speed is greater than 30 feet, you gain a +4 bonus for every 10 feet beyond 30 feet." """


def jump_speed_modifier(speed: int | None) -> int:
    """Jump's modifier for the character's speed in feet: -6 per full 10 ft. below 30, +4 per full 10 ft. above."""
    if not speed:
        return 0
    if speed < JUMP_SPEED:
        return JUMP_SLOWER * ((JUMP_SPEED - speed) // JUMP_STEP)
    return JUMP_FASTER * ((speed - JUMP_SPEED) // JUMP_STEP)


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
        level = character_level(sheet, reference) if cls == "character" else sheet.levels.get(cls, 0)
        return None if level >= least else f"{cls} level {least}"
    if kind == "caster_level":  # each class's own caster level, the highest of them (a paladin's is half its level)
        level = max((caster_level(sheet, c) for c in class_features.casters(sheet)), default=0)
        return None if level >= least else f"caster level {least}"
    return None


def caster_level(sheet: Sheet, cls: str) -> int:
    """The class's caster level: its class level with the levels prestige classes advance it by (`advanced`: the
    spellcasting levels and the hierophant's caster levels), half that for a paladin or ranger (its casting row's
    `caster_level` "half": "his caster level is one-half his paladin level")."""
    spells, only, _ = advanced(sheet)
    level = sheet.levels.get(cls, 0) + spells.get(slug(cls), 0) + only.get(slug(cls), 0)
    return level // 2 if (class_features.casting(cls) or {}).get("caster_level") == "half" else level


ARTICLE = {"arcane": "an arcane", "divine": "a divine", "any": "a"}


def _advance_kinds(row: dict[str, Any]) -> str:
    """The classes a prestige casting row advances, in words: "an arcane casting class", "one arcane and one divine
    casting class"."""
    kinds = class_features.kinds(row)
    if len(kinds) == 1:
        return f"{ARTICLE[kinds[0]]} casting class"
    if len(set(kinds)) == 1:
        return f"{len(kinds)} {'' if kinds[0] == 'any' else kinds[0] + ' '}casting classes"
    return f"one {' and one '.join(kinds)} casting class"


def _advance_candidates(sheet: Sheet, row: dict[str, Any]) -> str:
    """The sheet's casting classes a prestige casting row can advance, in the sheet's order: "wizard, sorcerer", or by
    kind for a row of two kinds ("arcane: wizard; divine: cleric"); "none"."""
    kinds = list(dict.fromkeys(class_features.kinds(row)))
    by_kind = {kind: [slug(c) for c in class_features.casters(sheet) if _of_kind(c, kind)] for kind in kinds}
    if len(kinds) == 1:
        return ", ".join(by_kind[kinds[0]]) or "none"
    return "; ".join(f"{kind}: {', '.join(found) or 'none'}" for kind, found in by_kind.items())


def _of_kind(cls: str, kind: str) -> bool:
    return kind == "any" or (class_features.casting(cls) or {}).get("type") == kind


def advance_problem(sheet: Sheet, prestige: str, chosen: list[str]) -> str | None:
    """What is wrong with `chosen` (class ids) as the classes the prestige class's casting row advances
    (`Sheet.d20["advances"]`): the sheet has to have the prestige class, the row, as many classes as its `count`, each a
    casting class of the sheet, one for each of the row's kinds (the mystic theurge's arcane and divine), not twice;
    None when they hold."""
    name = slug(prestige).replace("-", " ")
    row = class_features.advancing(prestige)
    if row is None:
        return f"The {name} advances no class's spellcasting."
    if not any(slug(c) == slug(prestige) and n for c, n in sheet.levels.items()):
        return f"{sheet.label or 'The character'} has no {name} levels."
    kinds = class_features.kinds(row)
    if len(chosen) != len(kinds):
        return f"The {name} advances {len(kinds)} class{'' if len(kinds) == 1 else 'es'}, not {len(chosen)}."
    casters = {slug(c): c for c in class_features.casters(sheet)}
    fits = len(set(chosen)) == len(chosen) and all(c in casters for c in chosen) and any(
        all(_of_kind(casters[c], kind) for c, kind in zip(order, kinds, strict=True))
        for order in permutations(chosen)
    )  # fmt: skip
    if fits:
        return None
    return (f"The {name} advances {_advance_kinds(row)} ({_advance_candidates(sheet, row)}), not "
            f"{' and '.join(chosen)}.")  # fmt: skip


def advanced(sheet: Sheet) -> tuple[dict[str, int], dict[str, int], list[str]]:
    """The levels the sheet's prestige classes advance its casting classes by, worked out from its levels and
    `Sheet.d20["advances"]` (no history: set later, the earlier prestige levels count too): by class id, the levels of
    spellcasting (spells a day, spells known and caster level, as if the class had them: "+1 level of existing arcane
    spellcasting class") and the levels of caster level only (the hierophant's); and a warning for each prestige class
    whose levels advance nothing, because `advances` names no class for it or names one that doesn't hold
    (`advance_problem`)."""
    spells: dict[str, int] = {}
    only: dict[str, int] = {}
    warnings: list[str] = []
    for cls, row, gained, named in _advances(sheet, warnings):
        into = only if row.get("caster_level_only") else spells
        for target in named:
            into[target] = into.get(target, 0) + gained
    return spells, only, warnings


def advanced_by(sheet: Sheet) -> dict[str, dict[str, int]]:
    """By casting class id, the caster levels each prestige class adds to it (`advanced`'s, spells or caster level
    only): {"wizard": {"eldritch-knight": 2}}, for the sheet to say where a caster level comes from."""
    out: dict[str, dict[str, int]] = {}
    for cls, _row, gained, named in _advances(sheet, []):
        for target in named:
            out.setdefault(target, {})[slug(cls)] = gained
    return out


def _advances(sheet: Sheet, warnings: list[str]) -> Iterator[tuple[str, dict[str, Any], int, list[str]]]:
    """Each prestige class whose levels advance a casting class, with its casting row, the levels it gains and the
    classes `Sheet.d20["advances"]` names for it; a warning in `warnings` for one that advances nothing."""
    chosen = (sheet.d20 or {}).get("advances") or {}
    for cls, level in sheet.levels.items():
        row = class_features.advancing(cls)
        if row is None or not (gained := class_features.advance_levels(row, level)):
            continue
        name = slug(cls).replace("-", " ")
        said = f"the {name}'s {gained} caster level{' advances' if gained == 1 else 's advance'} no class"
        named = chosen.get(slug(cls))
        if not named:
            warnings.append(f"{said}: name it with set_build's advances ({_advance_kinds(row)}: "
                            f"{_advance_candidates(sheet, row)}).")  # fmt: skip
            continue
        if problem := advance_problem(sheet, cls, list(named)):
            warnings.append(f"{said}: {problem}")
            continue
        yield cls, row, gained, list(named)


def base_score(sheet: Sheet, ability: str) -> int:
    """The ability score the sheet has, without its items."""
    raw = sheet.ability_scores.get(ability, 10)
    return signed(raw) if signed(raw) is not None else 10


def ability_score(sheet: Sheet, ability: str) -> int:
    """The ability score with the worn items' enhancement bonus to it (the highest: a belt of giant strength +4 and
    gauntlets of ogre power are +4): "When an ability score changes, all attributes associated with that score change
    accordingly" (DEL-389 part 3)."""
    boost = class_features.ability_boost(sheet, ability)  # the dragon disciple's, "as if through level advancement"
    return base_score(sheet, ability) + items.ability_bonus(sheet, ability) + boost


def skill_point_score(sheet: Sheet, ability: str) -> int:
    """The score skill points are counted from: a headband of intellect's bonus "does not earn the wearer extra skill
    points when a new level is attained; use the unenhanced Intelligence bonus". A class's ability boost (the dragon
    disciple's) is "gained as if through level advancement": it counts."""
    return (base_score(sheet, ability) + items.skill_point_bonus(sheet, ability)
            + class_features.ability_boost(sheet, ability))  # fmt: skip


MULTICLASS_STEP = 20
"""The SRD's multiclass XP penalty, in percent, for each class not within one level of the highest-level class."""
_FAVOURED = re.compile(r"Favou?red Class: (\w[\w-]*)", re.IGNORECASE)


def ecl(sheet: Sheet, reference: Any) -> int:
    """The character's effective character level, for XP and the level cap: its class levels, plus a monster race's
    racial Hit Dice and level adjustment (`monster_race`; a core race has neither). A companion has no class levels
    and no race: 0 (it takes no XP, `progress.award_xp`; its Hit Dice are `companions.rest_level`'s)."""
    race = race_named(reference, sheet.race) or {}
    return sum(sheet.levels.values()) + racial_levels(race) + int(race.get("level_adjustment", 0))


def favoured_class(sheet: Sheet, reference: Any) -> str | None:
    """The favoured class: the build's (`set_build`), else the race's trait ("Favored Class: Fighter"); "any" for a
    human or half-elf, whose highest-level class it is. None for a race without one."""
    if asked := (sheet.d20 or {}).get("favoured_class"):
        return slug(asked)
    race = race_named(reference, sheet.race) or {}
    for trait in race.get("traits", ()):
        if found := _FAVOURED.match(trait):
            return slug(found.group(1))
    return None


def xp_penalty(sheet: Sheet, reference: Any) -> int:
    """The multiclass XP penalty in percent (0, 20, 40 ...): 20 for each class not within one level of the highest,
    the favoured class not counting at all (for "any", the highest-level class), and no prestige class counting. NPC classes count as any class does."""
    levels = {
        slug(cls): level
        for cls, level in sheet.levels.items()
        if level > 0 and (reference.char_class(slug(cls)) or {}).get("type") != "prestige"
    }  # a prestige class does not count against the character (SRD), nor as the highest the others are measured by
    favoured = favoured_class(sheet, reference)
    if favoured == "any" and levels:
        favoured = max(levels, key=levels.__getitem__)
    counted = [level for cls, level in levels.items() if cls != favoured]
    if not counted:
        return 0
    top = max(counted)
    return MULTICLASS_STEP * sum(1 for level in counted if level < top - 1)


# --- entering a prestige class (DEL-389 part 4) -------------------------------------------------------------------


def loose(text: Any) -> str:
    """Words to match loosely: lower case, the punctuation gone ("Kill someone, for …!" is "kill someone for …")."""
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(text).lower()).split())


def requirement_rows(cls: str) -> list[dict[str, Any]]:
    """The prestige class's requirement rows in the class's order: by the "### " sections of its Requirements text
    and where each entry stands in its section; none for a base class."""
    found = [row for row in class_features.rows(slug(cls)) if row["kind"] == "requirement"]
    entry = next((row for row in data.load("classes") if row["id"] == slug(cls)), {})
    text = str(entry.get("text", "")).split("Requirements", 1)[-1].split("### Class Skills", 1)[0]

    def place(pair: tuple[int, dict[str, Any]]) -> tuple[int, int, int, int]:
        index, row = pair
        head = text.find(f"### {row['section']}")
        at = text.find(row["name"], head) if head >= 0 else -1
        need = row["requires"]
        word = need["cast"]["kind"] if "cast" in need else need["spell"].split("-")[0] if "spell" in need else ""
        within = row["name"].lower().find(word) if word else len(row["name"]) if "special" in need else 0
        return (head if head >= 0 else len(text), at if at >= 0 else len(text), within, index)

    return [row for _, row in sorted(enumerate(found), key=place)]


def class_feats(sheet: Sheet) -> list[str]:
    """The feats the sheet's class features give it by name, at their levels: a ranger's Endurance from 3rd, a
    wizard's Scribe Scroll, a monk's Improved Unarmed Strike. A bonus feat is a feat the character has: it meets a
    prestige class's requirement ("A ranger gains Endurance as a bonus feat at 3rd level")."""
    return [f["feat"] for f in class_features.granted(sheet) if f["kind"] == "feat" and f.get("feat")]


def _has_feat(build: dict[str, Any], feat: str, choice: str | None, given: Iterable[str] = ()) -> bool:
    """Whether the build took the feat (with the choice, if one is asked), or a class feature gives it (`given`, the
    sheet's `class_feats`: none of them has a choice)."""
    if choice is None and feat in given:
        return True
    for taken in build.get("feats", ()):
        fid, chosen = (taken.get("id"), taken.get("choice")) if isinstance(taken, dict) else (str(taken), None)
        if fid == feat and (choice is None or slug(str(chosen or "")) == slug(choice)):
            return True
    return False


def _castable(casting: dict[str, Any], kind: str, spontaneous: bool = False) -> int | None:
    """The highest spell level the sheet's casting classes of `kind` (arcane, divine, any) cast, from their slots or
    spells a day (`derived["casting"]`); None when none casts. `spontaneous`: only a class that casts without
    preparation (a sorcerer's, a bard's)."""
    levels = []
    for cls, entry in casting.items():
        row = class_features.casting(cls) or {}
        if (kind != "any" and row.get("type") != kind) or (spontaneous and entry.get("prepared", True)):
            continue
        levels += [int(level) for level, count in (entry.get("slots") or entry.get("per_day") or {}).items() if count]
    return max(levels, default=None)


def _spell_words(name: str) -> str:
    """A spell's name as the SRD's prose says it: "Planar Ally, Lesser" is "lesser planar ally"."""
    head, _, tail = name.partition(", ")
    return f"{tail} {head}".strip().lower() if tail else name.lower()


def _casts_spell(sheet: Sheet, casting: dict[str, Any], spell: str) -> bool:
    """Whether one of the sheet's casting classes casts the spell: on its list at a level it casts, and known for one
    that casts without preparation. A wizard's spellbook isn't tracked, so a prepared caster casts any spell of its
    list at a level it casts; a cleric's domain spells don't count. The DM may refuse either."""
    row = next((r for r in data.load("spells") if r["id"] == spell), None)
    if row is None:
        return False
    for cls, entry in casting.items():
        own = (class_features.casting(cls) or {}).get("list", cls)
        at = row["levels"].get(own)
        top = _castable({cls: entry}, "any")
        if at is None or top is None or top < int(at):
            continue
        known = [loose(n) for n in ((sheet.d20 or {}).get("known") or {}).get(cls, ())]
        if entry.get("prepared", True) or loose(row["name"]) in known:
            return True
    return False


def _unmet_requirement(
    row: dict[str, Any], sheet: Sheet, reference: Any, found: dict[str, Any], cls: str
) -> str | None:
    """What the requirement row asks that the sheet lacks, in words; None when it has it."""
    from delve_srd35.engine.combat import alignment_words  # combat reads this module
    from delve_srd35.engine.companions import ordinal  # companions reads this module

    need, name = row["requires"], row["name"]
    build = sheet.d20 or {}
    ranks = build.get("skills") or {}
    if "bab" in need:
        return None if found["bab"] >= need["bab"] else f"base attack bonus +{need['bab']} (it is {found['bab']:+d})"
    if "skill" in need:
        have = ranks.get(need["skill"], 0)
        return None if have >= need["ranks"] else f"{name} (it has {have:g})"
    if "skill_any" in need:
        count = int(need.get("count", 1))
        at = [ranks.get(skill, 0) for skill in need["skill_any"]]
        enough = sum(1 for have in at if have >= need["ranks"])
        if enough >= count:
            return None
        return f"{name} (it has {enough})" if count > 1 else f"{name} (it has {max(at, default=0):g})"
    if "feat" in need:
        return None if _has_feat(build, need["feat"], need.get("choice"), class_feats(sheet)) else name
    if "feat_any" in need:
        count = int(need.get("count", 1))
        given = class_feats(sheet)
        have = sum(1 for one in need["feat_any"] if _has_feat(build, one["feat"], one.get("choice"), given))
        return None if have >= count else f"{name} (it has {have})" if count > 1 else name
    if "cast" in need:
        level, kind, spontaneous = need["cast"]["level"], need["cast"]["kind"], need["cast"].get("spontaneous", False)
        top = _castable(found["casting"], kind, spontaneous)
        if top is not None and top >= level:
            return None
        spells = "spells" if kind == "any" else f"{kind} spells"
        if spontaneous:
            return f"the ability to cast {spells} without preparation"
        now = f"it casts no {spells}" if top is None else f"it casts {spells} up to {_top_level(top, ordinal)}"
        return f"the ability to cast {ordinal(level)}-level {spells} ({now})"
    if "spell" in need:
        if _casts_spell(sheet, found["casting"], need["spell"]):
            return None
        spell = next((r for r in data.load("spells") if r["id"] == need["spell"]), {"name": need["spell"]})
        return f"the ability to cast {_spell_words(spell['name'])}"
    if "proficient" in need:
        rows = [next((r for r in class_features.rows(c) if r["kind"] == "proficiency"), None) for c in sheet.levels]
        return None if any(r and need["proficient"] in r["weapons"] for r in rows) else (
            f"proficiency with all {need['proficient']} weapons")  # fmt: skip
    if "alignment" in need:
        words = set(alignment_words(sheet.alignment).split())
        wanted = need["alignment"]
        ok = not words & set(wanted["not"]) if isinstance(wanted, dict) else bool(words & set(wanted))
        if words and ok:
            return None
        return f"{name} ({f'it is {alignment_words(sheet.alignment)}' if words else 'it has no alignment'})"
    if "race" in need:
        race = race_named(reference, sheet.race) or {}
        names = {race.get("id"), slug(sheet.race), str(race.get("type", "")).lower()} - {None, ""}
        if "half-dragon" in slug(sheet.race):
            names.add("half-dragon")
        wanted = need["race"]
        ok = not names & set(wanted["not"]) if isinstance(wanted, dict) else bool(names & set(wanted))
        return None if ok else f"{name} (it is {str(sheet.race).lower() or 'of no race'})"
    if "sneak" in need:
        have = _dice_count(found.get("sneak"))
        return None if have >= _dice_count(need["sneak"]) else (
            f"sneak attack +{need['sneak']} (it has {'+' + found['sneak'] if have else 'none'})")  # fmt: skip
    if "special" in need:
        confirmed = {loose(said) for said in ((build.get("choices") or {}).get("requirements") or {}).get(cls, ())}
        return None if loose(need["special"]) in confirmed else f"the DM's confirmation: {need['special']}"
    return None


def _top_level(level: int, ordinal: Any) -> str:
    return f"{ordinal(level)} level" if level else "0-level"


def _dice_count(dice: Any) -> int:
    found = re.match(r"\s*\+?(\d+)d", str(dice or ""))
    return int(found.group(1)) if found else 0


def requirement_problems(sheet: Sheet, cls: str, reference: Any) -> list[str]:
    """Each requirement of the prestige class `cls` that the sheet doesn't meet, in words and in the class's order
    (`requirement_rows`); empty when it meets them all, and for a base class. They read the sheet's base attack bonus,
    skill ranks (not totals), feats with their choices, castable spell levels by kind (`derived["casting"]`),
    alignment, race and sneak attack dice; an ability score with a worn item's enhancement counts (`item_notes`). A
    special requirement holds once the DM has confirmed it (`Sheet.d20["choices"]["requirements"]`)."""
    found = derived(sheet, reference, entries=False)
    out = []
    for row in requirement_rows(cls):
        if (missing := _unmet_requirement(row, sheet, reference, found, slug(cls))) is not None:
            out.append(missing)
    return out


def item_notes(sheet: Sheet, reference: Any) -> list[str]:
    """A note for each feat whose ability prerequisite only a worn item's enhancement meets: it counts while the item
    is worn (the SRD), and the DM is told so."""
    out = []
    for feat in feat_ids(sheet):
        row = feat_row(reference, feat) or {"prerequisites": ()}
        for need in row["prerequisites"]:
            if need["kind"] != "ability":
                continue
            least, ability = int(need.get("min", 0)), need["ability"]
            if base_score(sheet, ability) < least <= ability_score(sheet, ability):
                out.append(f"{row['name']}'s {ability.title()} {least} is met by a worn item's enhancement "
                           f"({base_score(sheet, ability)} without it): it holds while the item is worn.")  # fmt: skip
    return out


CURRENT = ("features", "ecl", "xp_penalty", "casting", "skill_notes")
"""Keys every derived dict has had since DEL-389 (`skill_notes` since DEL-456's synergies and Jump's speed): a stored
one without one of them predates it (a sheet Phase 2's engine filled, as the live party's), and `stored` works the
numbers again."""


def stored(sheet: Sheet, reference: Any) -> dict[str, Any]:
    """The sheet's stored `d20["derived"]`, or the numbers worked again (`derived`) when it has none or it predates
    `CURRENT`'s keys. Nothing is saved: the stored copy is the next `fill_derived`'s to replace."""
    found = (sheet.d20 or {}).get("derived")
    if found and all(key in found for key in CURRENT):
        return found
    return derived(sheet, reference)


def derived(sheet: Sheet, reference: Any, *, entries: bool = True) -> dict[str, Any]:
    """`Sheet.d20["derived"]`: the numbers the build gives. With `entries`, its `warnings` say of each prestige class
    the sheet has what it entered it without (`entry_warnings`)."""
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
        warnings.append(race_refusal(reference, sheet.race) or f"Unknown race '{sheet.race}'.")
    racial_base = (race or {}).get("racial_saves") or {}
    carried = items.carried(sheet)
    # An amulet of natural armor's "enhancement bonus to his natural armor bonus" adds to the race's (from +0).
    natural = int((race or {}).get("natural_armour", 0)) + items.worn_bonus(carried, "natural", "ac")
    deflection = items.worn_bonus(carried, "deflection", "ac")
    size = SIZE.get((race or {}).get("size", "").lower(), {})
    racial_skills, racial_saves = _racial(race)

    worn = []
    for slot in ("armor", "shield"):
        if name := build.get(slot):
            if (piece := armour_table().get(slug(name))) is None:
                warnings.append(f"Unknown armour '{name}'.")
            else:
                worn.append(items.armour_piece(piece, items.piece(sheet, slot, slug(name))))
    caps = [p["max_dex"] for p in worn if p["max_dex"] is not None]
    max_dex = min(caps) if caps else None
    acp = sum(p["acp"] for p in worn)
    dex = mods["dex"] if max_dex is None else min(mods["dex"], max_dex)
    dodge = int("dodge" in feats)
    # Bracers of armor's armor bonus doesn't stack with the armour's: the higher counts. A shield's is another type.
    armour = max([p["bonus"] for p in worn if p["category"] != "shield"] + [items.worn_bonus(carried, "armor", "ac")])
    if shield_use(sheet, reference)["counts"]:  # a two-handed weapon's wielder gets no shield's AC
        armour += sum(p["bonus"] for p in worn if p["category"] == "shield")

    body = next((p for p in worn if p["category"] != "shield"), None)  # "Shields do not affect a character's speed."
    granted = class_features.granted(sheet)
    held = holding(worn)
    # A feature that its armour stops (the barbarian's fast movement in heavy armour) gives nothing.
    applying = [f for f in granted if not _armour_stops(f, body)]

    def feature_bonus(target: str) -> int:
        return class_features.bonus(applying, target, held, mods)

    natural += feature_bonus("natural_armour")  # the dragon disciple's natural armor increase

    resistance = items.worn_bonus(carried, "resistance", "saves")  # a cloak of resistance's, on all three
    saves = {
        save: sum(r[save] for r in rows.values()) + racial_base.get(save, 0) + mods[SAVE_ABILITY[save]]
        + 2 * (SAVE_FEATS[save] in feats) + racial_saves + feature_bonus(save) + resistance
        for save in SAVE_ABILITY
    }  # fmt: skip
    speed = None
    if race is not None and race.get("speed"):
        # The race's base land speed in feet in the armour worn, the sheet's `movement_rate` (DEL-404, DEL-407). Fast
        # movement comes before the armour: "apply this bonus before modifying ... because of any load carried or
        # armor worn".
        base = race["speed"] + feature_bonus("speed")
        speed = armoured_speed(body, race, base)
        if build.get("exhausted"):  # `class_features.tired` at 6: "an exhausted character moves at half normal speed"
            speed //= 2
    ranked = build.get("skills", {})
    skills = {}
    for skill, ranks in ranked.items():
        row = skill_row(reference, skill)
        if row is None:
            warnings.append(f"Unknown skill '{skill}'.")
            skills[skill] = ranks
            continue
        penalty = acp * (2 if row["id"] == "swim" else 1) if row["armor_check"] else 0
        key = mods.get(row["key_ability"], 0)
        small = size.get("hide", 0) if row["id"] == "hide" else 0
        # Jump is "modified by your speed"; a synergy of 5 ranks in another skill on every check of this one adds +2
        jumping = jump_speed_modifier(speed) if row["id"] == "jump" else 0
        skills[skill] = (ranks + key + 3 * (skill in focus) + penalty + racial_skills.get(skill, 0) + small
                         + feature_bonus(f"skill:{skill}") + jumping + synergy_bonus(ranked, skill))  # fmt: skip

    bab = sum(r["bab"] for r in rows.values()) + int((race or {}).get("racial_bab", 0))
    # A feat whose prerequisite a later change broke (Int lowered under Combat Expertise's 13) stays, with a warning.
    warnings += feat_problems(sheet, reference, bab)
    casting = _casting(rows, mods, sheet, reference)
    # The first casting class's, where Phase 2 reads them: none when it casts spontaneously (its pool is `per_day`).
    first = next(iter(casting.values()), {})
    slots, dc = (first["slots"], first["dc"]) if first.get("prepared") else ({}, {})
    # Extra Turning: 4 more turnings a day, in the turn-undead feature's own uses.
    more = {"turn-undead": 4 * feats.count("extra-turning")}
    for feature in granted:
        if feature["kind"] == "uses":
            feature["per_day"] = class_features.per_day(feature, mods, more.get(feature["id"], 0))
    # Sneak attack from several classes (rogue, assassin, arcane trickster, blackguard): "the bonuses on damage stack".
    sneak = class_features.dice_sum([f["value"] for f in granted if f["id"] == "sneak-attack"])
    # Turning from two classes is one pool: the higher of their uses (the blackguard's command undead among them).
    turns = max((f["per_day"] for f in granted if f["id"] in TURNING), default=0)
    uncanny = any(f.get("feat") == "uncanny-dodge" for f in granted)
    # A dodge bonus a class gives (the dwarven defender's) is lost flat-footed, as the Dodge feat's; the monk's counts
    # "even against touch attacks or when the monk is flat-footed".
    dodging = [f for f in applying if _row_of(f).get("type") == "dodge"]
    dodge += class_features.bonus(dodging, "ac", held, mods)
    ac_more = class_features.bonus([f for f in applying if f not in dodging], "ac", held, mods)
    canny = canny_defense(sheet, granted, held, mods)  # with the Dex bonus, and lost with it
    out = {
        "bab": bab,
        **saves,
        "ac": 10 + armour + natural + dex + canny + size.get("ac", 0) + dodge + ac_more + deflection,
        "touch": 10 + dex + canny + size.get("ac", 0) + dodge + ac_more + deflection,
        "flat_footed": 10 + armour + natural + (dex + canny + dodge if uncanny else min(dex, 0)) + size.get("ac", 0)
        + ac_more + deflection,
        "init": mods["dex"] + 4 * ("improved-initiative" in feats) + feature_bonus("init"),
        "acp": acp,
        "max_dex": max_dex,
        "spell_failure": sum(p["failure"] for p in worn) if class_features.arcane(sheet) else 0,
        "skills": skills,
        "skill_notes": skill_notes(ranked),
        "slots": slots,
        "dc": dc,
        "casting": casting,
        "sneak": sneak,
        "turning_per_day": turns,
        "features": granted,
        "ecl": ecl(sheet, reference),
        "xp_penalty": xp_penalty(sheet, reference),
    }
    if speed is not None:
        out["speed"] = speed  # the unarmoured one beside it when the armour slows, for a load to slow no more than it
        if speed != base:  # (`loaded_speed`)
            out["base_speed"] = base
    reductions = [f for f in granted if f["kind"] == "reduction" and f["value"]]
    if body is not None and body.get("dr"):  # adamantine armour's; DR from two sources doesn't stack: the best counts
        reductions.append({"value": body["dr"], "bypass": "—"})
    if reductions:  # "<value>/<bypass>": the barbarian's "5/—", which nothing bypasses (`reduction` reads it)
        best = max(reductions, key=lambda f: f["value"])
        out["dr"] = f"{best['value']}/{best.get('bypass', '—')}"
    if favoured := class_features.favoured_bonuses(sheet):
        out["favoured_enemy"] = favoured
    if body is not None and body["category"] == "heavy":
        out["run_multiplier"] = RUN_IN_HEAVY  # for the DM: nothing in core runs
    if uncanny:
        out["uncanny_dodge"] = True
    if (flank := improved_uncanny_dodge(sheet, granted)) is not None:
        out["improved_uncanny_dodge"] = flank
    if evaded := evasion(granted, held):
        out["evasion"] = evaded
    if carried:
        held_weapon = held_weapon_id(build.get("weapon"))
        out["items"] = items.shown(sheet, held_weapon, slug(build.get("armor") or ""), slug(build.get("shield") or ""))
    changed = {a: ability_score(sheet, a) for a in mods
               if items.ability_bonus(sheet, a) or class_features.ability_boost(sheet, a)}  # fmt: skip
    if changed:
        out["abilities"] = changed  # the scores with the items' enhancement and the class's boosts, for the sheet
    warnings += advanced(sheet)[2]
    if entries:
        warnings += entry_warnings(sheet, reference)
    if warnings:
        out["warnings"] = warnings
    return out


TURNING = ("turn-undead", "command-undead")
"""The features that turn or rebuke undead: a cleric's and a paladin's turning, a blackguard's command undead."""


def _row_of(feature: dict[str, Any]) -> dict[str, Any]:
    return next((r for r in class_features.rows(feature["class"]) if r["id"] == feature["id"]), {})


def improved_uncanny_dodge(sheet: Sheet, granted: list[dict[str, Any]]) -> int | None:
    """The flanking level of improved uncanny dodge, from a class's row (a rogue's 8th) or from uncanny dodge of two
    classes ("If a character gains uncanny dodge from a second class, the character automatically gains improved
    uncanny dodge"): the levels of the classes that give either, added ("the levels from those classes stack to
    determine the minimum rogue level required to flank the character"). Only a rogue of 4 levels more flanks the
    character (`combat.swing`). None without it."""
    uncanny = {f["class"] for f in granted if f.get("feat") == "uncanny-dodge"}
    improved = {f["class"] for f in granted if f["id"] == "improved-uncanny-dodge"}
    if len(uncanny) < 2 and not improved:
        return None
    return sum(sheet.levels.get(cls, 0) for cls in uncanny | improved)


def sneak_level(sheet: Sheet, granted: list[dict[str, Any]]) -> int:
    """The character's rogue level for flanking a target of improved uncanny dodge: "a rogue at least four levels
    higher" (SRD), its rogue levels only. Class levels stack on the target's side (`improved_uncanny_dodge`), not the
    attacker's; 0 without sneak attack."""
    return sheet.levels.get("rogue", 0) if any(f["id"] == "sneak-attack" for f in granted) else 0


EVASION_ARMOUR = "light_armour"
"""Evasion "can only be used if [she] is wearing light armor or no armor" (the rogue's, the monk's, the
shadowdancer's)."""


def evasion(granted: list[dict[str, Any]], held: set[str]) -> str | None:
    """"improved evasion" or "evasion" when a class gives it and the armour allows (`EVASION_ARMOUR`): on a Reflex save
    for half damage, none on a success (improved: half on a failure too). The DM applies it to the damage: the save is
    rolled as any other. None without it."""
    ids = {f["id"] for f in granted}
    if EVASION_ARMOUR not in held:
        return None
    if "improved-evasion" in ids:
        return "improved evasion"
    return "evasion" if "evasion" in ids else None


def canny_defense(sheet: Sheet, granted: list[dict[str, Any]], held: set[str], mods: dict[str, int]) -> int:
    """The duelist's canny defense: "When not wearing armor or using a shield, a duelist adds 1 point of Intelligence
    bonus (if any) per duelist class level to her Dexterity bonus to modify Armor Class while wielding a melee
    weapon" (the build's weapon, not an unarmed strike); 0 otherwise. Lost with the Dex bonus (flat-footed)."""
    from delve_srd35.engine import attack_line  # attack_line reads numbers' tables

    found = next((f for f in granted if f["id"] == "canny-defense"), None)
    if found is None or found.get("condition", "unarmoured_unencumbered") not in held:
        return 0
    name = str((sheet.d20 or {}).get("weapon") or "")
    weapon = attack_line.weapon(name) if name else None
    if weapon is None or weapon["kind"] in ("ranged", "unarmed"):
        return 0
    return min(max(0, mods.get(found.get("ability", "int"), 0)), sheet.levels.get(found["class"], 0))


def entry_warnings(sheet: Sheet, reference: Any) -> list[str]:
    """For each prestige class the sheet has, the requirements it doesn't meet without that class's levels, as
    "entered <class> without: …": a sheet made with them (a high-level NPC) isn't refused, but the DM is told. A class
    entered by a level-up met them then; one that a later change broke is said too."""
    out = []
    for cls in sheet.levels:
        if not sheet.levels[cls] or not requirement_rows(cls):
            continue
        before = replace(sheet, levels={c: n for c, n in sheet.levels.items() if c != cls})
        if problems := requirement_problems(before, cls, reference):
            out.append(f"entered {slug(cls).replace('-', ' ')} without: {'; '.join(problems)}.")
    return out


def held_weapon_id(name: Any) -> str:
    """The `weapons.json` id of the weapon a build holds by name ("+1 longsword", "sword, short"); "" for none."""
    from delve_srd35.engine import attack_line  # attack_line reads numbers' tables

    found = attack_line.weapon(str(name or "")) if name else None
    return str(found["id"]) if found else ""


TWO_HANDED_RANGED = ("shortbow", "longbow", "crossbow-light", "crossbow-heavy", "crossbow-repeating")
"""The projectile weapons that take both hands (bows and crossbows, the hand crossbow aside): the SRD's "Most
projectile weapons require two hands to use"; a light crossbow fired one-handed (-2) is the DM's."""
EFFORT = ("light", "one-handed", "two-handed")


def shield_use(sheet: Sheet, reference: Any) -> dict[str, Any]:
    """How the build's shield works with its weapon: `counts` (its AC counts), `attack` (the weapon's penalty to hit)
    and a `note` for the build. A weapon held in both hands — a two-handed one (by its effort at the wielder's size)
    or a bow or crossbow (`TWO_HANDED_RANGED`) — leaves a light, heavy or tower shield's AC out: "you can't use your
    shield hand" for a weapon; the shield is still carried, so its armour check penalty and spell failure stay. A
    buckler: "You can use a bow or crossbow without penalty while carrying it", and helping wield a two-handed weapon
    costs -1 on attack rolls and "you don't get the buckler's AC bonus"."""
    from delve_srd35.engine import attack_line  # attack_line reads numbers' tables

    build = sheet.d20 or {}
    shield, name = slug(build.get("shield") or ""), str(build.get("weapon") or "")
    weapon = attack_line.weapon(name) if name else None
    if not shield or shield not in armour_table() or weapon is None:
        return {"counts": True, "attack": 0, "note": None}
    body = str((race_named(reference, sheet.race) or {}).get("size", "")).strip().lower()
    body = body if body in attack_line.SIZES else "medium"
    kind = str(weapon["kind"])
    made_for = attack_line.size_of(name) or body
    if kind in EFFORT:
        at = EFFORT.index(kind) + attack_line.SIZES.index(made_for) - attack_line.SIZES.index(body)
        kind = EFFORT[min(max(at, 0), len(EFFORT) - 1)]
    projectile = any(str(weapon["id"]).startswith(w) for w in TWO_HANDED_RANGED)
    said = str(armour_table()[shield]["name"]).lower()
    if shield == "buckler":
        if kind == "two-handed":
            return {"counts": False, "attack": -1, "note": f"The {weapon['name'].lower()} takes the buckler arm too: "
                    "-1 on attack rolls with it, and no AC from the buckler."}  # fmt: skip
        return {"counts": True, "attack": 0, "note": None}
    if kind == "two-handed" or projectile:
        return {"counts": False, "attack": 0, "note": f"The {weapon['name'].lower()} takes both hands: the {said} "
                "gives no AC (carried, its armour check penalty still applies)."}  # fmt: skip
    return {"counts": True, "attack": 0, "note": None}


ARMOUR_RANK = {"light": 1, "medium": 2, "heavy": 3}


def holding(worn: list[dict[str, Any]]) -> set[str]:
    """The feature conditions that hold in what is worn (`armour_table` rows), by the build alone: the sheet doesn't
    know the load carried, so the load is taken as light (core weighs it in play, `loaded_speed`)."""
    body = next((p for p in worn if p["category"] != "shield"), None)
    held = {"no_heavy_load"}
    if body is None:
        held.add("unarmoured")
    if body is None or body["category"] == "light":
        held.add("light_armour")
    if not worn:
        held.add("unarmoured_unencumbered")
    return held


def _armour_stops(feature: dict[str, Any], body: dict[str, Any] | None) -> bool:
    """Whether the armour worn is heavier than the feature's row allows (its `armour_max`)."""
    row = next((r for r in class_features.rows(feature["class"]) if r["id"] == feature["id"]), {})
    most = row.get("armour_max")
    return bool(most and body is not None and ARMOUR_RANK.get(body["category"], 0) > ARMOUR_RANK[most])


def _casting(rows: dict[str, dict[str, Any]], mods: dict[str, int], sheet: Sheet, reference: Any) -> dict:
    """`derived["casting"]`: each casting class of the sheet (`features.casters`, by its class order) with its key
    ability and caster level, and for one that prepares its own slots and DCs by spell level ("0", "1" …): a casting
    pool per class (DEL-389). One that casts spontaneously (a sorcerer, a bard) has instead its spells a day
    (`per_day`, the table's and its Charisma's bonus spells, as slots are counted) and the number of spells it knows
    of each level it casts (`known`, its class table's Spells Known), with its DCs. A class a prestige class advances
    (`advanced`) has these and its caster level from its table at the level it casts at."""
    out: dict[str, dict[str, Any]] = {}
    spells = advanced(sheet)[0]
    for cls, ability in class_features.casters(sheet).items():
        if cls not in rows:
            continue
        prepared = (class_features.casting(cls) or {}).get("prepared", True)
        entry: dict[str, Any] = {"ability": ability, "caster_level": caster_level(sheet, cls), "prepared": prepared}
        row = _advanced_row(reference, cls, rows[cls], spells.get(slug(cls), 0))
        pool, dc = _slots(cls, row, ability, mods, sheet, reference)
        if prepared:
            entry["slots"], entry["dc"] = pool, dc
        else:
            # Table: … Spells Known; a level it has no spell a day of is no level it knows spells of (the bard's
            # "provided the bard has a high enough Charisma score to have a bonus spell of this level").
            table = row.get("spells_known", {})
            known = {level: int(count) for level, count in table.items() if pool.get(level)}
            entry |= {"per_day": pool, "known": known, "dc": dc}
        out[cls] = entry
    return out


def _advanced_row(reference: Any, cls: str, row: dict[str, Any], extra: int) -> dict[str, Any]:
    """The class table's row its spells come from: at its level, or with `extra` levels a prestige class advances it
    by, at that level, or the table's last (a wizard 18 / archmage 5 casts as a wizard 20)."""
    if not extra:
        return row
    last = max(r["level"] for r in reference.char_class(cls)["levels"])
    return class_row(reference, cls, min(row["level"] + extra, last))


def _slots(
    cls: str, row: dict[str, Any], ability: str, mods: dict[str, int], sheet: Sheet, reference: Any
) -> tuple[dict, dict]:
    """A prepared class's slots and DCs by spell level ("0", "1" …): the table's spells per day, the key ability's
    bonus spells (none on level 0), and a cleric's domain slot on levels 1 and up. A key ability under 10 + the spell
    level casts none of that level (the SRD's rule)."""
    score = ability_score(sheet, ability)
    by_level = reference.ability(ability, str(score)).get("values", {}).get("bonus_spells", "").split()
    bonus = {str(n): int(b) for n, b in enumerate(by_level, 1)}
    slots, dc = {}, {}
    for level, cell in row["spells_per_day"].items():
        base = signed(cell)
        if base is None or score < 10 + int(level):
            continue
        extra = 0 if level == "0" else bonus.get(level, 0) + (cls == "cleric")
        if base + extra:
            slots[level] = base + extra
            dc[level] = 10 + int(level) + mods[ability]
    return slots, dc
