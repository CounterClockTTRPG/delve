"""The 3.5 engine's own DM tools (DEL-388), seen only in srd35 campaigns: `set_build`, `set_stance` and `provoke`, and
core's `saving_throw`, `skill_check`, `update_combatant`, `setup_combat` and `add_combatant` with 3.5's numbers (a
fight set up without a surprise roll), and `surprise_check`, `morale_check`, `reaction` and `council` refused with why.
Each keeps the core tool's params and adds its own, and goes through core's play layer as core's tools do
(`PACK_TOOL_IMPORTS`): characters change through `characters.update` (a build as the engine's `d20_build`, never the
DM's sheet patch), and attacks through `combat.resolve_attack`, which swings by the engine and applies the damage. A
combatant's 3.5 numbers (`Combatant.d20`) are engine-owned and written to the live fight directly, as core's rearm
writes a combatant."""

from __future__ import annotations

import dataclasses
import difflib
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import replace
from functools import cache
from typing import Any

from delve.dice import Dice
from delve.dm.tools.host import all_specs
from delve.dm.tools.schema import ToolSpec, array, boolean, integer, obj, params, plain, string, strings
from delve.domain.characters import Sheet
from delve.domain.data import DataError
from delve.play import characters, combat
from delve.rules.classic import checks as classic_checks
from delve.rules.classic import combat as rules
from delve.rules.classic.checks import CheckError
from delve.rules.classic.combat import NONLETHAL
from delve_srd35 import treasure
from delve_srd35.data import load
from delve_srd35.engine import (
    attack_line,
    class_features,
    companions,
    defences,
    features,
    magic,
    numbers,
    progress,
)
from delve_srd35.engine import combat as combat_rules
from delve_srd35.engine import items as item_rules

Context = Any
"""A `delve.play.context.CampaignContext`: the tools' context, which a pack names only by what it uses."""

RULESET = "srd35"
FATIGUED = "fatigued"
BUILD = ("skills", "feats", "domains", "weapon", "armor", "shield", "favoured_class", "choices", "known", "items",
         "advances")  # fmt: skip
CHOICES = {"weapon-focus": "weapon", "greater-weapon-focus": "weapon", "weapon-specialization": "weapon",
           "greater-weapon-specialization": "weapon", "improved-critical": "weapon", "skill-focus": "skill",
           "spell-focus": "school", "greater-spell-focus": "school"}  # fmt: skip
"""The slice's feats taken for one thing, and what that is."""
SHIELDS = ("shield-", "buckler")
OVERRIDES = ("ac", "touch_ac", "flat_footed_ac", "attack_bonus", "damage", "critical", "saves", "init", "bab", "attack")
"""The 3.5 numbers `update_combatant` and `setup_combat`'s groups take (`setup_combat` and `add_combatant` also take `attacks_per_round`)."""
NO_SURPRISE = (
    "3.5 has no surprise roll: a side that hasn't noticed the other is flat-footed until it acts. Put the condition "
    "flat-footed on each unaware combatant (add_condition); in a surprise round only the aware act."
)
NO_MORALE = "3.5 has no morale check: a foe flees or surrenders as you rule it, or by its save against a fear effect."
NO_REACTION = (
    "3.5 has no reaction roll: an NPC starts at the attitude you judge (hostile, unfriendly, indifferent, friendly, "
    "helpful), and a character shifts it with a Diplomacy check (skill_check with skill diplomacy; an NPC, a Charisma "
    "check) read against the attitude table (rules_lookup 'diplomacy'). Keep the outcome with set_disposition."
)
_CRITICAL = re.compile(r"^\s*(?:(\d+)\s*[-–]\s*20)?\s*/?\s*(?:[x×](\d+))?\s*$", re.IGNORECASE)

OVERRIDE_PROPS = {
    "ac": integer("Its AC (3.5's: higher is harder to hit)."),
    "touch_ac": integer("Its touch AC."),
    "flat_footed_ac": integer("Its flat-footed AC."),
    "attack_bonus": integer("The attack bonus of the attack it holds."),
    "damage": string("That attack's damage: '1d8+3'."),
    "critical": string("That attack's critical: '19–20/×2', '×3'."),
    "saves": obj('Its saves: {"fort": 3, "ref": 1, "will": 0}; any of them.'),
}


def _core(name: str) -> ToolSpec:
    return next(spec for spec in all_specs() if spec.name == name)


def _scoped(
    core: ToolSpec, description: str, extra: Mapping[str, Any], fn: Callable, required: Iterable[str] | None = None
) -> ToolSpec:
    """The core tool `core` for srd35 campaigns: its params and `extra`, its flags, and `fn`."""
    schema = {**core.params, "properties": {**core.params["properties"], **extra}}
    if required is not None:
        schema["required"] = list(required)
    return ToolSpec(
        core.name,
        description,
        schema,
        fn,
        core.mutates,
        core.player_visible,
        core.dm_only_keys,
        core.areas,
        (RULESET,),
    )


def _who(character: Any) -> dict[str, Any]:
    return {"character_id": character.id, "character": character.name}


# --- set_build ---------------------------------------------------------------------------------------------------


def _key(name: str, keys: Iterable[str]) -> str | None:
    """The table key for a name as written ("chain mail" is chainmail, "heavy steel shield" is "shield-heavy-steel",
    "short sword" is "sword-short"): the name, or its last word first, with or without its hyphens."""
    words = numbers.slug(name).split("-")
    compact = {key.replace("-", ""): key for key in keys}
    for tried in ("-".join(words), "-".join(words[-1:] + words[:-1])):
        if tried in compact.values():
            return tried
        if tried.replace("-", "") in compact:
            return compact[tried.replace("-", "")]
    return None


def _weapon(name: str) -> str | None:
    """The weapon as the build keeps it: the table's name ("sword, short"), or the name as given for one that ends in
    a weapon of the table ("+1 longsword"); None for an unknown one."""
    table = {row["id"]: row for row in load("weapons")}
    key = _key(name, table)
    if key is not None:
        return str(table[key]["name"]).lower()
    return name.strip().lower() if attack_line.weapon(name) is not None else None


def _armour(name: str, shield: bool) -> str | None:
    table = numbers.armour_table()
    key = _key(name, table)
    if key is None or key.startswith(SHIELDS) != shield:
        return None
    return str(table[key]["name"]).lower()


# --- items (DEL-389 part 3) ---

MATERIALS = {"cold-iron": "cold iron", "alchemical-silver": "silver", "silvered": "silver", "silver": "silver",
             "adamantine": "adamantine", "mithral": "mithral", "masterwork": "masterwork"}  # fmt: skip
"""A magic weapon's or armour's material by its words ("cold iron longsword"), as the build keeps it."""
TITLED = ("ring", "rod", "staff")
"""The item types whose `items.json` names leave the kind out ("Protection" is the ring of protection)."""
_BONUS = re.compile(r"(?:^|\s)\(?\+(\d+)\)?(?=\s|$)")


def _display(row: Mapping[str, Any]) -> str:
    """An item's name as the SRD calls it: a ring's "Ring of Protection", a wondrous item's own."""
    name, kind = str(row["name"]), str(row["item_type"])
    return f"{kind.title()} of {name}" if kind in TITLED and kind not in name.lower() else name


@cache
def _item_index() -> dict[str, dict[str, Any]]:
    """`items.json`'s rows by id, by name, and by "ring-of-<id>" for a ring (rod, staff)."""
    index: dict[str, dict[str, Any]] = {}
    for row in load("items"):
        for key in (row["id"], numbers.slug(row["name"]), numbers.slug(_display(row))):
            index.setdefault(key, row)
    return index


def _said(bonuses: list[int]) -> str:
    signs = [f"+{b}" for b in bonuses]
    return signs[0] if len(signs) == 1 else f"{', '.join(signs[:-1])} or {signs[-1]}"


def _near(text: str) -> str:
    """The names near `text` of the items, weapons and armour the SRD has, for a refusal."""
    names = {_display(row).lower(): _display(row) for row in load("items")}
    names |= {str(row["name"]).lower(): str(row["name"]) for row in load("weapons")}
    found = difflib.get_close_matches(text.lower(), list(names), n=3, cutoff=0.6)
    return f" Did you mean {' or '.join(names[f] for f in found)}?" if found else ""


def _base(words: list[str]) -> tuple[int, str, str, str] | None:
    """Where the weapon or armour of a magic one's words starts, its kind (weapon, armor, shield), its id and its
    name in the table ("+1 flaming longsword" is longsword at word 2); None for words that end in none."""
    weapons = {row["id"]: row for row in load("weapons")}
    armour = numbers.armour_table()
    for at in range(len(words)):
        tail = "-".join(words[at:])
        if (key := _key(tail, armour)) is not None:
            return at, "shield" if key.startswith(SHIELDS) else "armor", key, str(armour[key]["name"]).lower()
        if (key := _key(tail, weapons)) is not None:
            return at, "weapon", key, str(weapons[key]["name"]).lower()
    return None


SPECIFIC = {"mithral shirt": "mithral chain shirt", "elven chain": "mithral chainmail",
            "dwarven plate": "adamantine full plate", "dragonhide plate": "masterwork full plate",
            "mithral heavy shield": "mithral heavy steel shield", "darkwood shield": "masterwork heavy wooden shield",
            "darkwood buckler": "masterwork light wooden shield"}  # fmt: skip
"""The specific armours and shields the random tables name that `items.json` lacks (they have no aura), as the SRD
describes each: "This extremely light chain shirt is made of very fine mithral links", "This full plate is made of
adamantine", "otherwise identical to masterwork full plate", "This nonmagical heavy wooden shield is made out of
darkwood" (darkwood's lighter check penalty is the DM's)."""
CONSUMABLE = re.compile(r"^(?:potion|oil|scroll|wand)\b")
"""A potion, oil, scroll or wand: used up, not worn, so a note of the build that belongs in the inventory."""
AMMUNITION = re.compile(r"^(?:\+\d+ )?(?:arrows|bolts|bullets)\b")
_STR_RATING = re.compile(r"^\+(\d+) str bonus$")
_COUNT = re.compile(r"^\d+$")


def _parens(words: str) -> tuple[str, list[str]]:
    """The words before their trailing parentheses, and each parenthesis's inside in order ("+2 composite longbow (+2
    str bonus) (seeking)"), a parenthesis inside one kept whole ("(spell resistance (13); wild)")."""
    groups: list[str] = []
    while words.endswith(")"):
        depth, at = 0, len(words) - 1
        for at in range(len(words) - 1, -1, -1):
            depth += {")": 1, "(": -1}.get(words[at], 0)
            if depth == 0:
                break
        if depth:
            break
        groups.insert(0, words[at + 1 : -1].strip())
        words = words[:at].rstrip()
    return words, groups


def _ability_key(phrase: str, on: str, table: Mapping[str, Any], whole: bool = True) -> str | None:
    """The effects table's key for a special ability's words on a weapon or armour: its own ("ghost-touch-weapon" for
    a weapon's ghost touch, the armour's being "ghost-touch"), else the words; else, for words read from a
    parenthesis (`whole` false), the words less their variant ("fortification, moderate", "spell resistance (13)")."""
    tried = [f"{phrase}-{on}", phrase]
    if not whole:
        words = phrase.split("-")
        tried += ["-".join(words[:n]) for n in range(len(words) - 1, 0, -1)]
    for key in tried:
        if table.get(key, {}).get("type") == "ability" and table[key]["on"] == on:
            return key
    return next((key for key in tried if table.get(key, {}).get("type") == "ability"), None)


def _magic_piece(text: str, words: list[str], bonus: int | None, problems: list[str],
                 named: Iterable[str] = ()) -> dict[str, Any] | None:  # fmt: skip
    """A magic weapon, armour or shield by its words ("+1 flaming longsword", "+2 mithral chain shirt", "cold iron
    longsword, masterwork"), with the special abilities a treasure roll names in a parenthesis (`named`: "+1 longsword
    (flaming; keen)"): its enhancement (+1 to +5), special abilities and material, checked by the SRD: a special
    ability needs at least +1, and the enhancement and the abilities' bonus equivalents come to no more than +10."""
    found = _base(words)
    if found is None:
        problems.append(f"Unknown item '{text}'.{_near(' '.join(words))}")
        return None
    at, kind, key, _ = found
    on = "weapon" if kind == "weapon" else "armor"
    table = item_rules.effects()
    abilities, material, masterwork, said = [], None, False, []
    prefix = words[:at]
    while prefix:
        for size in range(len(prefix), 0, -1):
            phrase = "-".join(prefix[:size])
            ability = _ability_key(phrase, on, table)
            if phrase == "masterwork":
                masterwork = True
            elif phrase in MATERIALS:
                material = MATERIALS[phrase]
            elif ability is not None and table[ability]["on"] == on:
                abilities.append(ability)
            elif ability is not None:
                problems.append(f"{phrase.replace('-', ' ').title()} is an {table[ability]['on']} special ability, "
                                f"not {on}'s.")  # fmt: skip
            else:
                continue
            said.append(phrase.replace("-", " "))
            prefix = prefix[size:]
            break
        else:
            problems.append(f"Unknown item '{text}': no {on} special ability or material '{prefix[0]}'.")
            return None
    rolled = []
    for words_said in named:
        ability = _ability_key(numbers.slug(words_said), on, table, whole=False)
        if ability is None:
            problems.append(f"Unknown item '{text}': no {on} special ability '{words_said}'.")
            return None
        if table[ability]["on"] != on:
            problems.append(f"{words_said.title()} is an {table[ability]['on']} special ability, not {on}'s.")
            continue
        abilities.append(ability)
        rolled.append(words_said)
    plus = bonus or 0
    base = " ".join(words[at:])
    name = " ".join(([f"+{plus}"] if plus else []) + said + [base]) + (f" ({'; '.join(rolled)})" if rolled else "")
    most = table[on if on == "weapon" else key]
    if plus > most["bonuses"][-1]:
        problems.append(f"{name}: an enhancement bonus is +1 to +{most['bonuses'][-1]}.")
    if abilities and plus < 1:
        problems.append(f"{name}: a {on} with a special ability must have at least a +1 enhancement bonus.")
    if (total := plus + sum(int(table[a]["price"]) for a in abilities)) > most["total"]:
        problems.append(f"{name}: +{total} in all; a {on} can't have an effective bonus higher than +{most['total']}.")
    entry: dict[str, Any] = {"id": key, "kind": kind, "name": name, "bonus": plus}
    if abilities:
        entry["abilities"] = abilities
    if material:
        entry["material"] = material
        if masterwork and material not in item_rules.MASTERWORK:
            entry["masterwork"] = True
    elif masterwork:
        entry["material"] = "masterwork"
    return entry


@cache
def _rolled_names() -> dict[str, str]:
    """The names the random magic item tables give a ring, rod, staff, wondrous item or specific weapon, armour or
    shield, as the treasure rolls them ("Ring of energy resistance, minor", "Feather token, tree", "Ring of wizardry
    (I)"), slugged without a bonus: the `items.json` id each names, or "" for one it has no entry for."""
    tables = treasure.magic_tables()
    out: dict[str, str] = {}
    for kind in ("rings", "rods", "staffs", "wondrous", "specific_armors", "specific_shields", "specific_weapons"):
        for rows in tables[kind].values():
            for row in rows:
                said = treasure._titled(kind, row) if kind in treasure.TITLES else str(row["name"])
                key = numbers.slug(_BONUS.sub(" ", said.lower().replace("’", "'")))
                out.setdefault(key, str(row["item"]) if row.get("ref") == "items" else "")
    return out


def _note(text: str, row: Mapping[str, Any] | None, bonus: int | None) -> dict[str, Any]:
    """An item the engine has no numbers for, kept by its name as given ("Ring of energy resistance, minor")."""
    id = str(row["id"]) if row else numbers.slug(text)
    return {"id": id, "kind": "note", "name": text.strip(), **({"bonus": bonus} if bonus else {})}


def _item(asked: Any, problems: list[str]) -> dict[str, Any] | None:
    """One item of `set_build(items=...)` as the build keeps it (`items`' shape), by its name with its bonus ("ring of
    protection +2", "+1 flaming longsword", "bag of holding"), as a treasure roll names it ("+1 longsword (flaming;
    keen)", "+2 composite longbow (+2 Str bonus)", "Feather token, tree", "Potion of cure light wounds"), or as
    `{"name" or "id", "bonus"}`: a worn item of the effects table with a bonus it comes in, a magic weapon, armour or
    shield (a composite bow's `str_rating`), or a note for an item the engine has no numbers for (a potion, scroll or
    wand among them). A problem named for an unknown one, with the names near it."""
    text = str(asked.get("name") or asked.get("id") or "") if isinstance(asked, Mapping) else str(asked)
    bonus = asked.get("bonus") if isinstance(asked, Mapping) else None
    words = " ".join(text.strip().lower().replace("’", "'").split())
    if CONSUMABLE.match(words) or AMMUNITION.match(words):
        return _note(text, None, None)
    words = SPECIFIC.get(words, words)
    head, groups = _parens(words)
    rating = next((int(m.group(1)) for g in groups if (m := _STR_RATING.match(g))), None)
    if bonus is None and (plus := next((g for g in groups if re.fullmatch(r"\+\d+", g)), None)):
        bonus = int(plus)  # "Cloak of resistance (+2)"
    named = [part.strip() for g in groups if not _STR_RATING.match(g) and not _COUNT.match(g)
             and not re.fullmatch(r"\+\d+", g) for part in g.split(";") if part.strip()]  # fmt: skip
    if head.endswith(", masterwork"):  # "Cold iron longsword, masterwork"
        head = f"masterwork {head.removesuffix(', masterwork')}"
    if found := _BONUS.search(head):
        bonus = int(found.group(1)) if bonus is None else bonus
        head = f"{head[: found.start()]} {head[found.end() :]}".strip()
    bonus = None if bonus is None else int(bonus)
    key = numbers.slug(head)
    if not key:
        problems.append(f"Name the item: '{text}'.")
        return None
    if _base(key.split("-")) is not None and (named or rating is not None):
        entry = _magic_piece(text, key.split("-"), bonus, problems, named)
        if entry is not None and rating is not None and entry["id"].endswith("-composite"):
            entry["str_rating"] = rating
            entry["name"] = f"{entry['name']} (+{rating} Str bonus)"
        return entry
    row = _item_index().get(key)
    effect = item_rules.effects().get(row["id"], {}) if row else {}
    if row is None or effect.get("target") in ("armor", "shield"):
        refused: list[str] = []
        entry = _magic_piece(text, key.split("-"), bonus, refused)
        rolled = numbers.slug(_BONUS.sub(" ", words))
        if refused and row is None and rolled in _rolled_names():  # a table's ring, wondrous or specific item
            return _note(text, _item_index().get(_rolled_names()[rolled]), bonus)
        problems += refused
        return entry
    name = _display(row)
    if effect.get("type") == "ability":
        example = "longsword" if effect["on"] == "weapon" else "chain shirt"
        problems.append(f"{name} is {'an armor' if effect['on'] == 'armor' else 'a weapon'} special ability: name it "
                        f"with its {effect['on']} ('+1 {name.lower()} {example}').")  # fmt: skip
        return None
    if not effect:
        return _note(text if groups else name, row, bonus)
    bonuses = list(effect["bonuses"])
    if bonus is None and len(bonuses) > 1:
        problems.append(f"{name}: name its bonus, {_said(bonuses)}.")
        return None
    bonus = bonuses[0] if bonus is None else bonus
    if bonus not in bonuses:
        problems.append(f"{name} comes as {_said(bonuses)}, not +{bonus}.")
        return None
    return {"id": row["id"], "kind": "worn", "name": f"{name} +{bonus}" if effect["by_bonus"] else name, "bonus": bonus}


def _items(asked: list[Any], problems: list[str]) -> list[dict[str, Any]]:
    return [found for one in asked if (found := _item(one, problems)) is not None]


def _hp_by_con(who: Any, after: Sheet, reference: Any) -> int:
    """The hit points an item's change of Constitution moves: its modifier's change a Hit Die (an amulet of health's
    bonus counts while worn)."""
    before = who.sheet
    change = numbers.modifier(numbers.ability_score(after, "con")) - numbers.modifier(
        numbers.ability_score(before, "con")
    )
    return change * numbers.character_level(after, reference)


_FEAT_HP = re.compile(r"You gain \+(\d+) hit points")


def feat_hp(reference: Any, sheet: Sheet) -> int:
    """The hit points the sheet's feats give, read from each feat's benefit ("Toughness: You gain +3 hit points", taken
    again "Its effects stack"): 3 for each Toughness."""
    total = 0
    for feat in numbers.feat_ids(sheet):
        row = numbers.feat_row(reference, feat)
        if row is not None and (found := _FEAT_HP.search(str(row.get("benefit") or ""))):
            total += int(found.group(1))
    return total


def _hp_patch(who: Any, after: Sheet, reference: Any, *, items: bool, feats: bool) -> dict[str, int]:
    """What the build's change moves in hit points, as `update`'s patch on `hp_max` and `hp` both: the items' change of
    Constitution (`_hp_by_con`) and the feats' hit points (`feat_hp`, Toughness taken or given up, DEL-456); {} when
    nothing moves. The maximum stays at least 1."""
    rise = (_hp_by_con(who, after, reference) if items else 0) + (
        feat_hp(reference, after) - feat_hp(reference, who.sheet) if feats else 0
    )
    return {"hp_max": max(1, who.sheet.hp_max + rise), "hp": who.state.hp + rise} if rise else {}


def _feats(reference: Any, asked: list[Any], problems: list[str]) -> list[dict[str, Any]]:
    """The feats as the build keeps them, `{"id", "choice"?}`, each by its id or name; a weapon or skill choice in the
    table's words."""
    out = []
    for item in asked:
        name, choice = (
            (item.get("id") or item.get("name") or "", item.get("choice")) if isinstance(item, dict) else (item, None)
        )
        row = numbers.feat_row(reference, str(name))
        if row is None:
            problems.append(f"Unknown feat '{name}'.")
            continue
        feat: dict[str, Any] = {"id": row["id"]}
        kind = CHOICES.get(row["id"])
        if kind is not None and not choice:
            problems.append(f"{row['name']} is taken for one {kind}: give its choice.")
        elif kind == "weapon":
            found = _weapon(str(choice))
            if found is None:
                problems.append(f"{row['name']}: unknown weapon '{choice}'.")
            feat["choice"] = numbers.slug(found or str(choice))
        elif kind == "skill":
            try:
                feat["choice"] = numbers.skill_named(reference, str(choice))
            except CheckError as error:
                problems.append(f"{row['name']}: {error}")
        elif choice:
            feat["choice"] = str(choice).strip().lower()
        out.append(feat)
    return out


def _skill_problems(sheet: Any, reference: Any, ranks: Mapping[str, float]) -> tuple[list[str], dict[str, Any]]:
    """What the ranks break: the skill points spent against the total so far ((class points + Int) × 4 at 1st level,
    then per level, at least 1 a level, a human's 4 + 1 a level more; a cross-class rank costs 2), and the most ranks
    a skill takes (level + 3, half that cross-class). The level is the character's Hit Dice: a monster race's racial
    Hit Dice give their own points first ("Racial Skills", `numbers.monster_race`), with the first Hit Die's ×4, and
    their class skills. The points as well."""
    problems = []
    race = numbers.race_named(reference, sheet.race) or {}
    level = numbers.character_level(sheet, reference) or 1
    int_mod = numbers.modifier(numbers.skill_point_score(sheet, "int"))
    human = race.get("id") == "humans"
    class_skills: set[str] = set(race.get("racial_class_skills") or ())
    total = 0
    first = not numbers.racial_levels(race)
    if not first:
        racial = race["racial_skill_points"]
        total += racial["times"] * max(1, racial["per_hd"] + int_mod)
    for cls, count in sheet.levels.items():
        row = reference.char_class(cls) or {}
        class_skills |= set(row.get("class_skills") or ())
        found = re.match(r"\s*(\d+)", str(row.get("skill_points") or "0"))
        per = max(1, (int(found.group(1)) if found else 0) + int_mod) + int(human)
        total += per * (count + 3 * first) if count else 0
        first = first and not count
    spent = 0.0
    for skill, rank in ranks.items():
        own = any(skill == c or skill.startswith(c + "-") for c in class_skills)
        spent += rank * (1 if own else 2)
        most = level + 3 if own else (level + 3) / 2
        if rank > most:
            kind = "a class skill" if own else "cross-class"
            problems.append(
                f"{skill.replace('-', ' ').title()} {rank:g} ranks: at most {most:g} ({kind}, level {level})."
            )
    if spent > total:
        problems.append(f"{spent:g} skill points spent; {sheet.label or 'the character'} has {total} so far.")
    return problems, {"spent": spent, "total": total}


def _domains(sheet: Any, asked: list[str], problems: list[str]) -> list[str]:
    table = {row["id"]: row for row in load("domains")}
    out = []
    for name in asked:
        key = numbers.slug(name)
        if key in table:
            out.append(key)
        else:
            problems.append(f"Unknown domain '{name}': one of {', '.join(sorted(table))}.")
    if not sheet.levels.get("cleric"):
        problems.append("Only a cleric has domains.")
    named = {numbers.slug(name) for name in asked}  # "War" and "war" are one domain
    if len(named) != 2:
        problems.append(f"A cleric takes two domains, not {len(named)}.")
    return out


def _favoured_class(asked: str, problems: list[str]) -> str:
    """The favoured class a name means: a class of the pack's table, or "any" (the human's and half-elf's highest)."""
    key = numbers.slug(asked)
    if key != "any" and not features.rows(key):
        problems.append(f"Unknown favoured class '{asked}': a class of the SRD, or 'any'.")
    return key


ORDINAL = {1: "1st", 2: "2nd", 3: "3rd"}


def _choices(sheet: Any, asked: Mapping[str, Any], problems: list[str]) -> dict[str, Any]:
    """The class choices asked, checked: favoured enemies from Table: Ranger Favored Enemies, as many as the ranger's
    level allows (a name again is a +2 raise of it, one with each enemy past the first); a neutral cleric's energy;
    the special requirements of a prestige class the DM confirms (`_requirements`)."""
    out: dict[str, Any] = {}
    for key, value in asked.items():
        if key == "energy":
            out[key] = _energy(sheet, value, problems)
            continue
        if key == "requirements":
            out[key] = _requirements(sheet, value, problems)
            continue
        if key != "favoured_enemy":
            problems.append(f"Unknown choice '{key}': favoured_enemy, energy or requirements.")
            continue
        chosen = []
        for name in [value] if isinstance(value, str) else list(value or ()):
            if (found := features.favoured_enemy(name)) is None:
                problems.append(f"Unknown favoured enemy '{name}': a type or subtype of the ranger's table "
                                "('undead', 'humanoid (orc)', 'outsider (evil)').")  # fmt: skip
            else:
                chosen.append(found)
        count = features.favoured_count(sheet)
        level = sheet.levels.get("ranger", 0)
        if not count:
            problems.append("Only a ranger has favoured enemies.")
        else:
            ordinal = ORDINAL.get(level, f"{level}th")
            distinct, raised = len(set(chosen)), len(chosen) - len(set(chosen))
            if distinct > count:
                what = "favoured enemy" if count == 1 else "favoured enemies"
                problems.append(f"A {ordinal}-level ranger has {count} {what}, not {distinct}.")
            if raised > count - 1:
                what = "raise" if count - 1 == 1 else "raises"
                problems.append(f"A {ordinal}-level ranger has {count - 1} {what} of a favoured enemy, not {raised}.")
        out[key] = chosen
    return out


def _requirements(sheet: Any, asked: Any, problems: list[str]) -> dict[str, list[str]]:
    """The special requirements of prestige classes the DM confirms were met in play, by class: each names one of the
    class's `special` requirements (matched loosely: case and punctuation aside), kept in the class's words. A class's
    list replaces the one it had; the other classes' stay."""
    out = dict(((sheet.d20 or {}).get("choices") or {}).get("requirements") or {})
    if not isinstance(asked, Mapping):
        problems.append('The requirements confirmed are by class: {"assassin": ["<its words>"]}.')
        return out
    for name, said in asked.items():
        cls = numbers.slug(str(name))
        specials = [row["requires"]["special"] for row in numbers.requirement_rows(cls)
                    if "special" in row["requires"]]  # fmt: skip
        if not specials:
            problems.append(f"The {cls.replace('-', ' ')} has no special requirements to confirm.")
            continue
        chosen = []
        for words in [said] if isinstance(said, str) else list(said or ()):
            found = next((s for s in specials if numbers.loose(s) == numbers.loose(words)), None)
            if found is None:
                problems.append(f"'{words}' is no special requirement of the {cls.replace('-', ' ')}: "
                                f"{'; '.join(specials)}.")  # fmt: skip
            elif found not in chosen:
                chosen.append(found)
        out[cls] = chosen
    return out


def _energy(sheet: Any, value: Any, problems: list[str]) -> str:
    """A neutral cleric's energy, "positive" or "negative", which turns or rebukes and converts a prepared spell into a
    cure or an inflict spell (Turn or Rebuke Undead: "A neutral cleric of a neutral deity must choose … Once this choice
    is made, it cannot be reversed"; the DM keeps to it). A good cleric channels positive energy and an evil one
    negative: neither chooses, so one that contradicts the alignment is refused."""
    energy = str(value or "").strip().lower()
    if energy not in ("positive", "negative"):
        problems.append(f"Unknown energy '{value}': positive (cure spells) or negative (inflict spells).")
    if not sheet.levels.get("cleric"):
        problems.append("Only a cleric channels energy.")
    elif (fixed := magic.energy_of(sheet)) is not None and energy in ("positive", "negative") and energy != fixed:
        kind = "A good" if fixed == "positive" else "An evil"
        problems.append(f"{kind} cleric channels {fixed} energy: only a neutral cleric chooses.")
    return energy


def _known(sheet: Any, reference: Any, asked: Mapping[str, Any], problems: list[str]) -> dict[str, list[str]]:
    """The spells known asked, by spontaneous class, checked: each on the class's list, and no more of a level than its
    Table: … Spells Known gives at its level (`derived["casting"]`'s `known`; 0-level spells count as the table's own
    column). Each class's list replaces the one it had."""
    casting = numbers.derived(sheet, reference)["casting"]
    out: dict[str, list[str]] = {}
    for name, spells in asked.items():
        cls = numbers.slug(name)
        entry = casting.get(cls)
        if entry is None or entry.get("prepared"):
            problems.append(f"Only a sorcerer or bard knows spells: {sheet.label or 'the character'} has no {name} "
                            "levels that cast spontaneously.")  # fmt: skip
            continue
        if isinstance(spells, str):
            problems.append(f"The {cls}'s spells known are a list of names, not '{spells}'.")
            continue
        names, counts = [], {}
        for spell in spells:
            row = magic.spell_row(str(spell))
            if row is None:
                problems.append(f"Unknown spell '{spell}'.")
            elif (at := row["levels"].get(cls)) is None:
                problems.append(f"{row['name']} is not on the {cls} list.")
            elif row["name"] in names:
                problems.append(f"{row['name']} is known once.")
            else:
                names.append(row["name"])
                counts[at] = counts.get(at, 0) + 1
        level = sheet.levels.get(cls, 0)
        for at, given in sorted(counts.items()):
            most = entry["known"].get(str(at), 0)
            if given > most:
                what = "spell" if most == 1 else "spells"
                problems.append(f"A {ORDINAL.get(level, f'{level}th')}-level {cls} knows {most} level-{at} {what}, "
                                f"not {given}.")  # fmt: skip
        out[cls] = names
    return out


def _advances(sheet: Any, asked: Any, problems: list[str]) -> dict[str, list[str]]:
    """Which casting classes each prestige class advances ("+1 level of existing … class"), by its id or spaced name,
    a class or a list of them: checked by `numbers.advance_problem` (a casting class the sheet has, of the kind the
    prestige class advances, as many as its count). A prestige class's list replaces the one it had; an empty one
    clears it; the others stay."""
    out = dict((sheet.d20 or {}).get("advances") or {})
    if not isinstance(asked, Mapping):
        problems.append('The advances are by prestige class: {"eldritch knight": ["wizard"]}.')
        return out
    for name, said in asked.items():
        prestige = numbers.slug(str(name))
        chosen = [numbers.slug(str(c)) for c in ([said] if isinstance(said, str) else list(said or ()))]
        if not chosen:
            out.pop(prestige, None)
        elif problem := numbers.advance_problem(sheet, prestige, chosen):
            problems.append(problem)
        else:
            out[prestige] = chosen
    return out


def set_build(
    ctx: Context,
    character: str,
    skills: dict[str, float] | None = None,
    feats: list[Any] | None = None,
    domains: list[str] | None = None,
    weapon: str | None = None,
    armor: str | None = None,
    shield: str | None = None,
    favoured_class: str | None = None,
    choices: dict[str, Any] | None = None,
    known: dict[str, list[str]] | None = None,
    items: list[Any] | None = None,
    advances: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Set a 3.5 character's build: skill ranks, feats (with a choice, such as Weapon Focus's weapon), a cleric's two
    domains, the weapon, armour and shield in use, the race's favoured class, class choices (a ranger's favoured
    enemies, a neutral cleric's energy, a prestige class's special requirements met), a sorcerer's or bard's spells
    known, the magic items it has, and which casting class each prestige class advances; what you leave out stays.
    It is checked against the rules (skill points so far, max ranks of level + 3 or half cross-class, feat
    prerequisites, domains, favoured enemies by level, the spells known of each level by the class table, an item's
    bonus, an advanced class of the prestige class's kind) and refused with every problem named;
    accepted, the sheet's numbers (BAB, saves, AC, skill totals, slots) follow. An empty weapon, armor or shield takes
    it off. A later change that breaks a feat's prerequisite keeps the feat, with a warning. Items count by the SRD:
    of one bonus type only the highest (two rings of protection), a magic weapon only in hand and armour only worn
    (one named in the items takes an empty hand or body), an amulet of health's hit points while worn; an item the
    engine has no numbers for is kept as a note. A feat that gives hit points (Toughness's +3) raises the maximum and
    current hit points when taken, and lowers them when given up."""
    who = characters.get(ctx, character)
    reference = ctx.lookups
    problems: list[str] = []
    build: dict[str, Any] = {}
    if skills is not None:
        build["skills"] = {}
        for name, rank in skills.items():
            try:
                skill = numbers.skill_named(reference, name)
            except CheckError as error:
                problems.append(str(error))
                continue
            if skill in build["skills"]:
                problems.append(f"'{name}' is {skill.replace('-', ' ').title()} again.")
            build["skills"][skill] = build["skills"].get(skill, 0) + rank
    if feats is not None:
        build["feats"] = _feats(reference, feats, problems)
    if domains is not None:
        build["domains"] = _domains(who.sheet, domains, problems)
    if favoured_class is not None:
        build["favoured_class"] = _favoured_class(favoured_class, problems)
    if known is not None:
        build["known"] = {**((who.sheet.d20 or {}).get("known") or {}), **_known(who.sheet, reference, known, problems)}
    if advances is not None:
        build["advances"] = _advances(who.sheet, advances, problems)
    if choices is not None:
        build["choices"] = {**((who.sheet.d20 or {}).get("choices") or {}), **_choices(who.sheet, choices, problems)}
    for slot, asked in (("weapon", weapon), ("armor", armor), ("shield", shield)):
        if asked is None:
            continue
        if not asked.strip():
            build[slot] = None
            continue
        found = _weapon(asked) if slot == "weapon" else _armour(asked, slot == "shield")
        if found is None:
            known = "weapons" if slot == "weapon" else "shields" if slot == "shield" else "armour"
            problems.append(f"Unknown {slot} '{asked}': name one of the SRD's {known}.")
        build[slot] = found
    if items is not None:
        build["items"] = _items(items, problems)
        had = who.sheet.d20 or {}
        for item in build["items"]:  # a magic weapon, armour or shield takes an empty hand or body
            slot = item["kind"]
            if slot in ("weapon", "armor", "shield") and slot not in build and not had.get(slot):
                build[slot] = _weapon(item["id"]) if slot == "weapon" else _armour(item["id"], slot == "shield")
    candidate = replace(who.sheet, d20={**(who.sheet.d20 or {}), **build})
    points = None
    if skills is not None:
        found_problems, points = _skill_problems(candidate, reference, build["skills"])
        problems += found_problems
    if feats is not None:
        bab = numbers.derived(candidate, reference)["bab"]
        problems += numbers.feat_problems(candidate, reference, bab)
    if problems:
        raise CheckError(f"{who.name}'s build is refused: {' '.join(problems)}", hint="Fix each and call it again.")
    hp = _hp_patch(who, candidate, reference, items=items is not None, feats=feats is not None)
    saved = characters.update(ctx, who.id, hp, reason="set_build", d20_build=build)
    d20 = saved.sheet.d20 or {}
    out = {**_who(saved), "build": {key: d20.get(key) for key in BUILD if key in d20}, "derived": d20.get("derived")}
    if points is not None:
        out["skill_points"] = points
    race = who.sheet.race
    warnings = []
    if numbers.race_named(reference, race) is None and (refused := numbers.race_refusal(reference, race)):
        warnings.append(refused)  # a monster that can't be a race (DEL-389): the build stands, its race adds nothing
    if feats is not None or items is not None:
        warnings += numbers.item_notes(saved.sheet, reference)  # a feat's score met by a worn item, while it is worn
    if note := numbers.shield_use(saved.sheet, reference)["note"]:
        warnings.append(note)  # a two-handed weapon and a shield: the build stands, the shield's AC doesn't count
    if used_up := [i["name"] for i in build.get("items") or () if i["kind"] == "note" and CONSUMABLE.match(i["id"])]:
        warnings.append(f"{', '.join(used_up)}: used up, not worn, kept as a note; it belongs in the inventory.")
    if warnings:
        out["warnings"] = warnings
    return out


def convert_spell(ctx: Context, character: str, prepared: str, into: str = "") -> dict[str, Any]:
    """Cast a spell in place of a prepared one: a good cleric (or a neutral one channelling positive energy) loses a
    prepared spell of 1st level or higher, not a domain spell, to cast a cure spell of its level or lower (cure light
    wounds 1st … mass cure critical wounds 8th), an evil one an inflict spell; a druid a summon nature's ally of its
    level or lower. Without `into`, the highest. The prepared copy is spent; the answer has the spell's level and the
    copy's (converted_level), and the DC, school and save of the spell cast."""
    who = characters.get(ctx, character)
    state, said = magic.convert(who.sheet, who.state, prepared, into, ctx.lookups)
    if "refusal" in said:
        raise CheckError(said["refusal"], hint="Name an uncast prepared spell of the cleric or druid.")
    ctx.storage.characters.save_state(replace(who, state=state))
    ctx.log("spell_cast", character_id=who.id, name=who.name, spell=said["spell"], level=said["level"])
    spent = said["converted_level"]  # the level the copy was spent from, not the converted spell's
    left = sum(1 for s in state.memorized if s.level == spent and not s.cast)
    return {**_who(who), **said, "remaining": {str(spent): left}}


# --- the fight ---------------------------------------------------------------------------------------------------


def _live(ctx: Context) -> tuple[str, rules.Combat]:
    live = ctx.storage.combats.live(ctx.campaign_id)
    if live is None:
        raise CheckError("No combat is under way.", hint="Start one with setup_combat.")
    return live[0], rules.from_json(live[1])


def _put(ctx: Context, id: str, fight: rules.Combat, *changed: rules.Combatant) -> rules.Combat:
    """The fight with `changed` in it, stored: only engine-owned numbers change, so no state is written through."""
    fight = replace(fight, combatants={**fight.combatants, **{c.id: c for c in changed}})
    ctx.storage.combats.save(id, fight.phase, rules.to_json(fight))
    return fight


def _find(fight: rules.Combat, ref: str) -> rules.Combatant:
    try:
        return rules.find(fight, ref)
    except rules.UnknownCombatant as error:
        raise CheckError(error.message, error.hint, error.candidates) from None


def _numbers(c: rules.Combatant) -> dict[str, Any]:
    if c.d20 is None:
        raise CheckError(f"{c.name} has no 3.5 numbers.", hint="Add it to the fight again.")
    return dict(c.d20)


def set_stance(
    ctx: Context,
    combatant: str,
    power_attack: int | None = None,
    defensive: bool | None = None,
    flurry: bool | None = None,
) -> dict[str, Any]:
    """A combatant's stance in the fight: Power Attack (from 0 up to its base attack bonus: that much off its melee
    attacks, on their damage, twice two-handed), fighting defensively (-4 to attack, +2 AC) and a monk's flurry of
    blows (unarmed or with a special monk weapon, in no armour: one more attack a round, all at -2 to 4th level, -1
    to 8th). It lasts until set again; what you leave out stays."""
    id, fight = _live(ctx)
    c = _find(fight, combatant)
    mine = _numbers(c)
    character = ctx.storage.characters.get(c.character_id) if c.character_id else None
    if flurry:
        refused = (f"{c.name} has no flurry of blows: only a monk flurries." if character is None
                   else class_features.flurry_refusal(character.sheet, combat_rules.held_form(c)))  # fmt: skip
        if refused:
            raise CheckError(refused)
    stance = dict(mine.get("stance") or {"power_attack": 0, "defensive": False})
    if power_attack is not None:
        bab = int(mine.get("bab", 0))
        if not 0 <= power_attack <= bab:
            raise CheckError(f"Power Attack takes 0 to {bab} (its base attack bonus), not {power_attack}.")
        sheet = ctx.storage.characters.get(c.character_id).sheet if c.character_id else None
        if power_attack and sheet is not None and "power-attack" not in numbers.feat_ids(sheet):
            raise CheckError(f"{c.name} hasn't the Power Attack feat.", hint="set_build gives feats.")
        stance["power_attack"] = power_attack
    if defensive is not None:
        stance["defensive"] = defensive
    if flurry is not None:
        stance["flurry"] = flurry
    after = replace(c, d20={**mine, "stance": stance})
    if flurry is not None and character is not None:  # the engine makes its forms again, flurrying or not
        assert ctx.d20 is not None
        after = ctx.d20.combatant_from_sheet(character, after)
    _put(ctx, id, fight, after)
    out = {"id": c.id, "name": c.name, "stance": stance}
    if stance.get("flurry"):
        held = combat_rules.held_form(after) or {}
        bonuses = combat_rules.attack_bonuses(held) if held.get("bonus") is not None else [None]
        out["attacks_this_round"] = [{"name": held.get("name"), "bonus": b} for b in bonuses]
    return out


USE_FEATURE = (
    "A class feature used, counted against its uses a day (they come back with rest). rage: an effect 'Rage' (-2 AC), "
    "and at 1st level (more from greater rage at 11th, mighty at 20th) +2 to hit in melee and +2 damage in melee and "
    "thrown (+3 two-handed) by the swing, +2 on Fort and Will saves, +2 hp per Hit Die, for 3 + the new Con modifier "
    "rounds; when "
    "it ends or the barbarian stops, call use_feature(rage, amount=-1): the hit points go and the barbarian is left "
    "fatigued (a rest ends a rage left on). smite evil: the "
    "paladin's next melee resolve_attack adds Cha to hit and its level to damage if the target is evil (spent either "
    "way; a ranged or touch attack leaves it waiting). inspire courage: the bard's song, +1 to hit and damage (an "
    "effect) on the party in the "
    "fight, and +1 on saves against charm and fear; remove_effect it 5 rounds after the song stops. lay on hands: "
    "heals amount hp of the paladin's level × Cha a day, on target. wild shape: the druid becomes the animal target "
    "names (its attacks, natural armour, size, Str, Dex, Con; her hp, BAB, saves, Int, Wis, Cha), healed as by a "
    "night's rest; target '' changes her back. remove disease: the paladin's, on target, so many a week (a rest of 7 "
    "days gives them back). defensive stance: the dwarven defender's, an effect (+4 AC), +2 Str by the swing, +2 on "
    "saves (+4 Fort), +2 hp per level; amount=-1 ends it and leaves him winded (-2 Str) for the fight. smite good: the "
    "blackguard's smite evil, on a good target. seeker arrow, phase arrow, hail of arrows, ranged legerdemain, "
    "impromptu sneak attack, shadow illusion, defensive roll, breath weapon (its dice and DC): one use spent, what it "
    "does said."
)


ROUND_ONLY = ("attacks_remaining_this_round", "extra_attack", "attacks_per_round")


def provoke(ctx: Context, provoker: str, threatened_by: list[str], weapon: str = "") -> dict[str, Any]:
    """A combatant provokes attacks of opportunity (it moved out of a threatened square, cast, drank, fled…): each
    combatant that threatens it makes one attack at it, if it hasn't used its one attack of opportunity this round.
    A flat-footed one (in round 1 before it has acted, or with the flat-footed condition) makes none. The hits are
    applied at once. weapon picks the threatener's attack by name, as resolve_attack's."""
    id, fight = _live(ctx)
    target = _find(fight, provoker)
    if "removed" in target.conditions:
        raise CheckError(f"{target.name} has been removed from the fight.")
    if not fight.order:
        raise CheckError(
            f"Round {fight.round} hasn't started: its initiative isn't rolled yet.",
            hint="combat_round rolls the round's initiative.",
        )
    answers = []
    for ref in threatened_by:
        c = _find(fight, ref)
        mine = _numbers(c)
        used = dict(mine.get("aoo") or {"round": 0, "used": 0})
        refused = None
        if c.id == target.id:
            refused = "It can't provoke itself."
        elif used.get("round") == fight.round and int(used.get("used", 0)) >= 1:
            refused = "already used its attack of opportunity this round"
        elif c.hp <= 0 or "removed" in c.conditions:
            refused = "It is down or out of the fight."
        elif combat_rules.flat_footed(target, c, fight.round):
            refused = "is flat-footed: no attack of opportunity"
        if refused is not None:
            answers.append({"id": c.id, "name": c.name, "refused": refused})
            continue
        answers.append(_opportunity(ctx, id, fight, c, target, weapon))
        id, fight = _live(ctx)
    return {"provoker": target.name, "provoker_id": target.id, "round": fight.round, "attacks": answers}


def _opportunity(
    ctx: Context, id: str, fight: rules.Combat, c: rules.Combatant, target: rules.Combatant, weapon: str
) -> dict[str, Any]:
    """`c`'s attack of opportunity at `target`, through core's resolve_attack: marked `swinging` for its rolls, and
    afterwards with its own attacks and the weapon it holds as they were and its one attack of opportunity used. On
    any error the mark comes off again."""
    mine = _numbers(c)
    _put(ctx, id, fight, replace(c, d20={**mine, "aoo": {"round": fight.round, "used": 0, "swinging": True}}))
    swung = False
    try:
        swing = combat.resolve_attack(ctx, c.id, target.id, "", weapon)
        swung = True
    finally:
        id, fight = _live(ctx)
        after = fight.combatants[c.id]
        # It isn't one of its own attacks this round: its count and the weapon it holds stay as they were.
        aoo = {"round": fight.round, "used": 1} if swung else mine.get("aoo") or {"round": 0, "used": 0}
        numbers_after = {**_numbers(after), "aoo": aoo}
        _put(ctx, id, fight, replace(after, attacks_used=c.attacks_used, weapon=c.weapon, d20=numbers_after))
    return {k: v for k, v in swing.items() if k not in ROUND_ONLY} | {"attack_of_opportunity": True}


def _critical(text: str) -> tuple[int, int]:
    """The threat and multiplier of "19–20/×2", "18-20", "×3"; 20 and ×2 where it says none."""
    found = _CRITICAL.match(str(text))
    if found is None or not any(found.groups()):
        raise CheckError(f"critical reads '{text}': write it as '19–20/×2' or '×3'.")
    return int(found.group(1) or 20), int(found.group(2) or 2)


def _overridden(c: rules.Combatant, over: Mapping[str, Any]) -> rules.Combatant:
    """The combatant with the 3.5 numbers in `over` (`OVERRIDES`): its AC, touch and flat-footed AC, saves, and the
    bonus, damage, critical and name of the attack it holds, its initiative modifier (`init`) and its BAB."""
    mine = _numbers(c)
    if over.get("init") is not None:
        mine["init_bonus"] = int(over["init"])
    if over.get("bab") is not None:
        mine["bab"] = int(over["bab"])
    if over.get("ac") is not None:
        mine["ac"] = int(over["ac"])
        c = replace(c, ac=int(over["ac"]))
    for key, field in (("touch_ac", "touch"), ("flat_footed_ac", "flat_footed")):
        if over.get(key) is not None:
            mine[field] = int(over[key])
    if over.get("saves"):
        unknown = sorted(set(over["saves"]) - {"fort", "ref", "will"})
        if unknown:
            raise CheckError(f"Unknown save '{unknown[0]}'.", hint="Give fort, ref and will.")
        mine["saves"] = {**(mine.get("saves") or {}), **{k: int(v) for k, v in over["saves"].items()}}
    attack = {k: over[k] for k in ("attack_bonus", "damage", "critical", "attack") if over.get(k) is not None}
    if attack:
        held = c.attacks[c.weapon] if 0 <= c.weapon < len(c.attacks) else None
        forms = list(mine.get("attacks") or ())
        index = next(
            (i for i, f in enumerate(forms) if held is not None and f["name"] == held.name), 0 if forms else None
        )
        form = dict(forms[index]) if index is not None else {"name": held.name if held else "attack", "bonus": int(mine.get("bab", 0)), "damage": held.damage_sm if held else "1d6", "threat": 20, "mult": 2, "count": 1, "touch": False, "hands": 1, "ranged": False}  # fmt: skip
        if "attack_bonus" in attack:
            form["bonus"] = int(attack["attack_bonus"])
        if "damage" in attack:
            form["damage"] = str(attack["damage"]).replace(" ", "")
            if held is not None:
                block = replace(held, damage_sm=form["damage"], damage_l=form["damage"])
                c = replace(c, attacks=(*c.attacks[: c.weapon], block, *c.attacks[c.weapon + 1 :]))
        if "attack" in attack:
            form["name"] = str(attack["attack"]).strip() or form["name"]
            if held is not None:
                c = replace(c, attacks=(*c.attacks[: c.weapon], replace(c.attacks[c.weapon], name=form["name"]), *c.attacks[c.weapon + 1 :]))  # fmt: skip
        if "critical" in attack:
            form["threat"], form["mult"] = _critical(attack["critical"])
        if index is None:
            forms.append(form)
        else:
            forms[index] = form
        mine["attacks"] = forms
    return replace(c, d20=mine)


def _critical_text(form: Mapping[str, Any]) -> str:
    """A form's critical as the SRD writes it, and as `critical` takes it: "18–20/×2", "×3"."""
    threat, mult = int(form.get("threat", 20)), int(form.get("mult", 2))
    return f"×{mult}" if threat == 20 else f"{threat}–20/×{mult}"


def _defences_shown(mine: Mapping[str, Any]) -> dict[str, Any]:
    """A combatant's defences as the DM reads them: DR "10/magic", SR, regeneration "5 (fire or acid)", fast
    healing, resistances and immunities; only those it has."""
    out: dict[str, Any] = {}
    if reductions := numbers.reduction(mine.get("dr")):
        out["dr"] = ", ".join(defences.said(entry) for entry in reductions)
    if mine.get("sr"):
        out["sr"] = f"{mine['sr']} + class levels" if mine.get("sr_plus_class_levels") else mine["sr"]
    if regeneration := mine.get("regeneration"):
        out["regeneration"] = f"{regeneration['value']} ({defences.stoppers(regeneration)} deals lethal damage)"
    for key in ("fast_healing", "resist", "immune"):
        if mine.get(key):
            out[key] = mine[key]
    return out


def shown(c: rules.Combatant) -> dict[str, Any]:
    """The combatant's 3.5 numbers as the setup and update answers give them (ruling R17b): its AC, touch and
    flat-footed AC, its attack forms with their bonus, damage and critical, and its saves; a monster's defences where
    it has any (`_defences_shown`: a character's are on its sheet), its row's for one stored before it had them
    (`defences.of_combatant`)."""
    mine = _numbers(c)
    if c.character_id is None and (guarded := _defences_shown(defences.of_combatant(c))):
        return {**_shown(mine), "defences": guarded}
    return _shown(mine)


def _shown(mine: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "ac": mine["ac"],
        "touch": mine["touch"],
        "flat_footed": mine["flat_footed"],
        "attacks": [
            {"name": f["name"], "bonus": f["bonus"], "damage": f["damage"], "critical": _critical_text(f)}
            for f in mine.get("attacks") or ()
        ],
        "saves": dict(mine.get("saves") or {}),
    }


_DAMAGE_NOTE = re.compile(r"'(.+)' damage reads .* pass dmg=")
"""Core's setup warning for a group whose classic damage line has no dice."""
_MULTI_ATTACK_NOTE = re.compile(r"'(.+)' gets .* attacks/round .* pass dmg= per swing\.")
"""Core's setup note for a group with several attacks a round: under 3.5 its forms are the engine's, each swung by
`resolve_attack` with its `weapon` (the prompt's full attack), so no dmg is passed."""
CLASSIC_GROUP = ("thac0", "damage")
CLASSIC_ATTACK = ("damage_sm", "damage_l", "speed")
"""The classic numbers core's setup answer gives for an enemy group and a character's attack: under 3.5 the
combatant's own (`shown`) take their place."""


def _in_3_5(fight: rules.Combat, out: dict[str, Any]) -> dict[str, Any]:
    """Core's setup answer with each group's and character's classic numbers replaced by the 3.5 ones, and each place
    in the order with its initiative bonus where core says a weapon speed."""
    by_name = {c.name: c for c in fight.combatants.values()}
    groups = [_group_in_3_5(fight, group) for group in out["enemies"]]
    attacks = {
        name: {**{k: v for k, v in entry.items() if k not in CLASSIC_ATTACK}, **shown(by_name[name])}
        if name in by_name
        else entry
        for name, entry in out["party_attacks"].items()
    }
    order = [
        {**{k: v for k, v in entry.items() if k != "speed"}, "bonus": entry.get("speed", 0)} for entry in out["order"]
    ]
    answer = {**out, "enemies": groups, "party_attacks": attacks, "order": order}
    answer.pop("notes", None)
    if notes := _notes(groups, out.get("notes", [])):  # dropped when none is left, as core does
        answer["notes"] = notes
    return answer


def _notes(groups: list[dict[str, Any]], notes: list[str]) -> list[str]:
    """Core's setup notes without its classic "damage reads … pass dmg=" warning: a group whose combatants have the
    engine's attack forms needs no damage from the DM (a dmg would overwrite them), and one without any is told the
    3.5 override instead. Core's "pass dmg= per swing" note for several attacks a round is dropped too."""
    armed = {g["type"]: bool(g.get("attacks")) for g in groups if "type" in g}
    kept = []
    for note in notes:
        if _MULTI_ATTACK_NOTE.match(note):
            continue
        found = _DAMAGE_NOTE.match(note)
        if found is None or found.group(1) not in armed:
            kept.append(note)
        elif not armed[found.group(1)]:
            kept.append(f"'{found.group(1)}' has no attack the 3.5 engine could read: give it one with "
                        "update_combatant's damage and attack_bonus before it swings.")  # fmt: skip
    return kept


def _overrides(raw: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """The 3.5 overrides in `raw`, and the rest."""
    return {k: v for k, v in raw.items() if k in OVERRIDES}, {k: v for k, v in raw.items() if k not in OVERRIDES}


def _update_combatant(core: ToolSpec) -> Callable[[Context, dict[str, Any]], dict[str, Any]]:
    def run(ctx: Context, args: dict[str, Any]) -> dict[str, Any]:
        over, _ = _overrides(args)
        stats = dict(args.get("stats") or {})
        for classic, own in (("ac", "ac"), ("dmg", "damage")):  # core's ac and dmg mean the 3.5 ones here
            if classic in stats and own not in over:
                over[own] = stats[classic]
        if over:
            id, fight = _live(ctx)
            c = _find(fight, args["id"])
            _put(ctx, id, fight, _overridden(c, over))
        out = core.fn(ctx, {"id": args["id"], "stats": stats})
        _, fight = _live(ctx)
        return {**out, **({"d20_set": over} if over else {}), "numbers": shown(_find(fight, out["id"]))}

    return run


def _group_in_3_5(fight: rules.Combat, group: dict[str, Any]) -> dict[str, Any]:
    """An enemy group as core's setup or add answer gives it, its classic numbers replaced by its first combatant's 3.5
    ones (`shown`). Its `attacks_per_round` is the held attack's rate (its first combatant's: the hill giant's
    "+16/+11" is 2; core's group reads a classic row's number of attacks, which a 3.5 row hasn't)."""
    first = fight.combatants[group["individuals"][0]["id"]] if group.get("individuals") else None
    kept = {k: v for k, v in group.items() if k not in CLASSIC_GROUP}
    if first is None:
        return kept
    if "attacks_per_round" in kept and 0 <= first.weapon < len(first.attacks):
        kept["attacks_per_round"] = first.attacks[first.weapon].rate
    return {**kept, **shown(first)}


def _add_combatant(core: ToolSpec) -> Callable[[Context, dict[str, Any]], dict[str, Any]]:
    def run(ctx: Context, args: dict[str, Any]) -> dict[str, Any]:
        over, rest = _overrides(args.get("stats") or {})
        out = core.fn(ctx, {**args, "stats": rest} if over else args)
        if over and "error" not in out:
            id, fight = _live(ctx)
            changed = [_overridden(fight.combatants[one["id"]], over) for one in out["individuals"]]
            if over.get("init") is not None and fight.order:  # joined an order already rolled: its roll plus the init
                changed = [replace(c, init=(c.init_roll or 0) + int(over["init"])) for c in changed]
                for one, c in zip(out["individuals"], changed, strict=True):
                    one["init"] = c.init
            fight = _put(ctx, id, fight, *changed)
            if over.get("init") is not None and fight.order:
                fight = rules._ordered(fight)
                ctx.storage.combats.save(id, fight.phase, rules.to_json(fight))
        group = _group_in_3_5(_live(ctx)[1], out)
        for given, key in (("init", "init_bonus"), ("bab", "bab")):
            if over.get(given) is not None:
                group[key] = int(over[given])
        group.pop("notes", None)
        if notes := _notes([group], out.get("notes", [])):
            group["notes"] = notes
        return group

    return run


def _live_fight(ctx: Context) -> Any:
    return ctx.storage.combats.live(ctx.campaign_id)


def _setup_pool(ctx: Context, spells: Any) -> list[tuple[Any, str]]:
    """setup_combat's spells a party caster casts from its spells a day, checked to be paid for. They are round 1's
    actions: setup spends nothing, but marks each caster (`POOL_SPELL`) for round 1 to spend it when it is cast, or
    to drop it when round 1 lists the caster, whose action there (a spell or not) replaces setup's."""
    party = {c.name.strip().casefold(): c for c in characters.party(ctx)}
    declared = []
    for raw in spells if isinstance(spells, list) else []:
        who = party.get(_actor(raw).strip().casefold())
        if who is not None and (spell := _spell_declared(raw)) is not None:
            declared.append((who, spell))
    pool = _pool_selected(ctx, declared)
    _refuse_unpaid(ctx, pool)
    return pool


def _setup_combat(core: ToolSpec) -> Callable[[Context, dict[str, Any]], dict[str, Any]]:
    """Core's setup_combat with each group's 3.5 numbers; a spell declared for the first round from a caster's spells
    a day is checked to be paid for and left for round 1 to spend (`_setup_pool`)."""

    def run(ctx: Context, args: dict[str, Any]) -> dict[str, Any]:
        wanted, enemies = [], []
        for spec in args["enemies"]:
            over, rest = _overrides(spec) if isinstance(spec, dict) else ({}, spec)
            if isinstance(spec, dict) and str(spec.get("name", "") or "").strip():
                wanted.append(over)  # in the order core adds the groups it doesn't skip
            enemies.append(rest)
        pool = _setup_pool(ctx, args.get("spells")) if _live_fight(ctx) is None else []
        out = core.fn(ctx, {**args, "enemies": enemies, "surprise": False})
        if pool and isinstance(out, dict) and "error" not in out:
            fight = _live(ctx)[1]
            by_character = {c.character_id: c.id for c in fight.combatants.values() if c.character_id is not None}
            _mark(ctx, {by_character[who.id]: spell for who, spell in pool if who.id in by_character})
        if any(wanted):
            id, fight = _live(ctx)
            changed = [
                _overridden(fight.combatants[one["id"]], over)
                for group, over in zip(out["enemies"], wanted, strict=True)
                if over
                for one in group["individuals"]
            ]
            fight = _put(ctx, id, fight, *changed)
            out["combat"] = rules.status(fight, ctx.d20)
        answer = _in_3_5(_live(ctx)[1], out)
        for group, over in zip(answer["enemies"], wanted, strict=True):  # what an override sets, as it is held
            for given, key in (("init", "init_bonus"), ("bab", "bab")):
                if over.get(given) is not None:
                    group[key] = int(over[given])
        if args.get("surprise"):
            answer["notes"] = [*answer.get("notes", []), NO_SURPRISE]
        return answer

    return run


def _not_in_3_5(said: str) -> Callable[[Context, dict[str, Any]], dict[str, Any]]:
    def run(ctx: Context, args: dict[str, Any]) -> dict[str, Any]:
        raise CheckError(said)

    return run


# --- saves and skills --------------------------------------------------------------------------------------------


def _fight_save(ctx: Context, c: rules.Combatant, save_type: str, dc: int, modifier: int) -> dict[str, Any]:
    """A combatant's save against a DC in the current round, keyed as core keys a fight's save; a failed one spoils a
    spell or scroll under way, as core's does."""
    id, fight = _live(ctx)
    character = ctx.storage.characters.get(c.character_id) if c.character_id else None
    dice = Dice(ctx.dice.rng, ctx.storage.rolls, ctx.campaign_id, f"{ctx.beat}/{id}")
    assert ctx.d20 is not None
    if character is not None:  # a combatant's own raging adds in the engine's save; a character's sheet doesn't know
        modifier += class_features.rage_save(c.d20, _save_kind(save_type), c.effects, character.sheet)
        modifier += class_features.stance_save(c.d20, _save_kind(save_type), c.effects, character.sheet)
    subject = (
        c if character is None else _rested_or_tired(character.sheet, (*character.state.conditions, *c.conditions))
    )
    result = ctx.d20.save(
        subject,
        save_type,
        dc,
        modifier + classic_checks.effects_save(c.effects),
        dice,
        actor=c.id,
        combat_round=fight.round,
    )
    said = plain(result)
    save = said.pop("name")
    out = {"id": c.id, "name": c.name, **said, "save": save, "round": fight.round}
    if not result.success and c.ongoing is not None and c.ongoing.under_way and c.ongoing.kind in ("spell", "scroll"):
        combat.interrupt(ctx, c.id, f"{c.name} failed a saving throw")
        out["spell_disrupted"] = True
    return out


def _rested_or_tired(sheet: Sheet, conditions: Iterable[str]) -> Sheet:
    """The sheet a save or a skill check reads: a fatigued character's with 2 off its Str and Dex
    (`class_features.tired`); its stored derived numbers stay the rested ones, as the sheet shows them."""
    penalty = class_features.penalty_of(conditions)
    return class_features.tired(sheet, penalty) if penalty else sheet


def _save_kind(text: str) -> str:
    """The save as fort, ref or will; the text itself where it names none (the save refuses it)."""
    from delve_srd35.engine.checks import save_type

    try:
        return save_type(text)
    except CheckError:
        return text


def _saving_throw(core: ToolSpec) -> Callable[[Context, dict[str, Any]], dict[str, Any]]:
    def run(ctx: Context, args: dict[str, Any]) -> dict[str, Any]:
        modifier, dc = args.get("modifier", 0), args.get("dc")
        fighting = combat.combatant(ctx, args["character"])
        if fighting is not None:
            if dc is None:
                return core.fn(ctx, args)
            return _fight_save(ctx, fighting, args["save_type"], dc, modifier)
        who = characters.get(ctx, args["character"])
        assert ctx.d20 is not None
        modifier += classic_checks.effects_save(who.state.effects)
        modifier += class_features.rage_save(who.state.d20, _save_kind(args["save_type"]), who.state.effects,
                                             who.sheet)  # fmt: skip
        modifier += class_features.stance_save(who.state.d20, _save_kind(args["save_type"]), who.state.effects,
                                               who.sheet)  # fmt: skip
        sheet = _rested_or_tired(who.sheet, who.state.conditions)
        result = ctx.d20.save(sheet, args["save_type"], dc, modifier, ctx.dice, actor=who.id)
        return {**_who(who), **plain(result)}

    return run


def _skill_check(ctx: Context, args: dict[str, Any]) -> dict[str, Any]:
    who = characters.get(ctx, args["character"])
    assert ctx.d20 is not None
    occasion = str(args.get("occasion", "")).strip()
    result = ctx.d20.skill_check(
        _rested_or_tired(who.sheet, who.state.conditions),
        args["skill"],
        args.get("dc"),
        args.get("modifier", 0),
        ctx.dice,
        actor=who.id,
        occasion=occasion,
    )
    return {**_who(who), "skill": result.name, **plain(result)}


def _clear_fatigue(ctx: Context, ids: list[str]) -> list[str]:
    """`fatigued` off each of the characters `ids` that has it, after a rest of a day or more (the SRD: 8 hours of
    complete rest), by `progress.rest`'s rule; core's rest keeps the conditions it had, so it is done here. Their
    names."""
    cleared = []
    for id in ids:
        who = characters.get(ctx, id)
        if {FATIGUED, class_features.EXHAUSTED} & set(who.state.conditions):
            kept = [c for c in who.state.conditions if c not in (FATIGUED, class_features.EXHAUSTED)]
            characters.update(ctx, who.id, {"conditions": kept}, reason="rest clears fatigue")
            cleared.append(who.name)
    return cleared


def _rest(core: ToolSpec) -> Callable[[Context, dict[str, Any]], dict[str, Any]]:
    """Core's rest, with each resting character's rage still on ended first (`class_features.end_rages_at_rest`):
    its hit points off and fatigued, said in `rage_ended`. Both in one transaction: a refused rest ends none. Those a
    rest of a day or more took fatigue off (`progress.rest`) are named in `fatigue_cleared`."""

    def run(ctx: Context, args: dict[str, Any]) -> dict[str, Any]:
        ref = str(args.get("character") or "").strip()
        ids = [characters.get(ctx, ref).id] if ref else [c.id for c in characters.party(ctx)]
        with ctx.storage.transaction():
            ended = class_features.end_rages_at_rest(ctx, (characters, combat), ids)
            out = core.fn(ctx, args)
            cleared = _clear_fatigue(ctx, ids) if int(args.get("days", 1)) >= 1 else []
        if ended:
            out = {**out, "rage_ended": ended}
        if cleared:
            out = {**out, "fatigue_cleared": cleared}
        return out

    return run


def _nonlethal(c: rules.Combatant) -> int:
    return int((c.d20 or {}).get(NONLETHAL) or 0)


def _keep_nonlethal(ctx: Context, character_id: str, nonlethal: int) -> int:
    """The character's state takes the nonlethal damage its combatant had (`CharacterState.d20["nonlethal"]`, none
    without any): it outlasts the fight until a rest clears it (`progress.rest`). The amount kept."""
    who = ctx.storage.characters.get(character_id)
    if who is None:
        return 0
    d20 = {k: v for k, v in (who.state.d20 or {}).items() if k != NONLETHAL}
    if nonlethal > 0:
        d20[NONLETHAL] = nonlethal
    if d20 != (who.state.d20 or {}):
        ctx.storage.characters.save_state(replace(who, state=replace(who.state, d20=d20 or None)))
    return nonlethal


def _end_combat(core: ToolSpec) -> Callable[[Context, dict[str, Any]], dict[str, Any]]:
    """Core's end_combat, with `winded` taken off each character it wrote back: a defensive stance leaves the defender
    winded "for the duration of that encounter", and core keeps a condition that isn't its own combat's. So is
    `fatigued` where the fight's rage left it (`class_features.RAGE_FATIGUE` on the combatant: "for the rest of the
    encounter", DEL-412); a fatigue the DM gave stays. Each character's nonlethal damage is kept on its state
    (`_keep_nonlethal`, DEL-421), its answer's `nonlethal` where it has some. In the same transaction; the answer's
    `characters` follow."""

    def run(ctx: Context, args: dict[str, Any]) -> dict[str, Any]:
        with ctx.storage.transaction():
            live = ctx.storage.combats.live(ctx.campaign_id)
            raged = set()
            fighting = []
            if live is not None:
                fighting = [c for c in rules.from_json(live[1]).combatants.values() if c.character_id]
                raged = {c.character_id for c in fighting if (c.d20 or {}).get(class_features.RAGE_FATIGUE)}
            out = core.fn(ctx, args)
            for c in fighting:
                if (kept := _keep_nonlethal(ctx, str(c.character_id), _nonlethal(c))) and c.character_id in (
                    out.get("characters") or {}
                ):
                    out["characters"][c.character_id] = {**out["characters"][c.character_id], NONLETHAL: kept}
            for id, back in (out.get("characters") or {}).items():
                had = back.get("conditions", ())
                why = {class_features.WINDED: "no longer winded", FATIGUED: "the rage's fatigue passes"}
                ended = [k for k in why if k in had and (k != FATIGUED or id in raged)]
                if ended:
                    kept = [c for c in had if c not in ended]
                    reason = "the encounter ends: " + " and ".join(why[k] for k in ended)
                    characters.update(ctx, id, {"conditions": kept}, reason=reason)
                    out["characters"][id] = {**back, "conditions": kept}
        return out

    return run


NONLETHAL_STATES = {"staggered": "staggered: one attack or action a round", "unconscious": "unconscious and helpless"}
"""What `combat_rules.nonlethal_state` means, as the nonlethal tools' notes say it."""


def _nonlethal_target(ctx: Context, ref: str) -> tuple[Any, rules.Combatant | None]:
    """Who `ref` is (`apply_damage`'s and `apply_heal`'s `character`): a combatant of the live fight by its id or exact
    name, or a character (in the fight, its combatant). (the character or None, the combatant or None)."""
    fighting = combat.combatant(ctx, ref)
    if fighting is not None:
        return (characters.get(ctx, fighting.character_id) if fighting.character_id else None), fighting
    who = characters.get(ctx, ref)
    return who, combat.combatant(ctx, who.id)


def _set_nonlethal(
    ctx: Context, who: Any, fighting: rules.Combatant | None, nonlethal: int, logged: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """The target's nonlethal damage set to `nonlethal` (none kept at 0): its combatant's in a fight, else its
    character's state's, with `logged` in the fight's log. Who it is, its hit points and nonlethal damage, and the state
    it makes (`NONLETHAL_STATES`)."""
    if fighting is not None:
        id, fight = _live(ctx)
        if logged is not None:
            fight = replace(fight, log=(*fight.log, dict(logged)))
        c = fight.combatants[fighting.id]
        d20 = {k: v for k, v in (c.d20 or {}).items() if k != NONLETHAL}
        c = replace(c, d20={**d20, NONLETHAL: nonlethal} if nonlethal else d20)
        _put(ctx, id, fight, c)
        out: dict[str, Any] = {"id": c.id, "name": c.name, "hp": c.hp}
    else:
        who = characters.get(ctx, who.id)
        d20 = {k: v for k, v in (who.state.d20 or {}).items() if k != NONLETHAL}
        d20 = {**d20, NONLETHAL: nonlethal} if nonlethal else d20
        ctx.storage.characters.save_state(replace(who, state=replace(who.state, d20=d20 or None)))
        c = rules.Combatant(who.id, who.name, "party", hp=who.state.hp, d20={NONLETHAL: nonlethal})
        out = {"character_id": who.id, "name": who.name, "hp": who.state.hp}
    out[NONLETHAL] = nonlethal
    if state := combat_rules.nonlethal_state(c):
        out["state"] = state
        out["note"] = f"{c.name} is {NONLETHAL_STATES[state]} (nonlethal {nonlethal}, hp {c.hp})."
    return out


def _apply_damage(core: ToolSpec) -> Callable[[Context, dict[str, Any]], dict[str, Any]]:
    """Core's apply_damage; with `nonlethal`, the amount is nonlethal damage instead (DEL-455): it goes to the target's
    nonlethal total, not off its hit points (`_set_nonlethal`), which staggers it at its hit points and knocks it out
    above them. Read and written in one transaction, logged as damage (`nonlethal`), and refused to the dead and to
    one removed from the fight."""

    def run(ctx: Context, args: dict[str, Any]) -> dict[str, Any]:
        if not args.get("nonlethal"):
            return core.fn(ctx, {k: v for k, v in args.items() if k != "nonlethal"})
        amount = args.get("amount")
        if isinstance(amount, bool) or not isinstance(amount, int) or amount < 0:
            raise CheckError(f"The damage must be a whole number of 0 or more, not {amount!r}.")
        with ctx.storage.transaction():
            who, fighting = _nonlethal_target(ctx, str(args.get("character") or ""))
            name = fighting.name if fighting is not None else who.name
            if fighting is not None and rules.status_of(fighting) in ("dead", "removed"):
                raise CheckError(f"{name} is {rules.status_of(fighting)}: no damage to deal.")
            if fighting is None and who.state.hp <= rules.DEAD_AT:
                raise CheckError(f"{name} is dead: no damage to deal.")
            had = _nonlethal(fighting) if fighting is not None else int((who.state.d20 or {}).get(NONLETHAL) or 0)
            # Logged as the lethal path is: in the fight's log, and a character's in the campaign's.
            fought = {"type": "damage", "id": fighting.id, "amount": amount, NONLETHAL: True} if fighting else None
            out = _set_nonlethal(ctx, who, fighting, had + amount, fought)
            if who is not None:
                ctx.log("damage", character_id=who.id, name=who.name, amount=amount, nonlethal=True,
                        nonlethal_before=had, nonlethal_after=had + amount,
                        **({"in_combat": True} if fighting is not None else {}))  # fmt: skip
        return {**out, "nonlethal_damage": amount}

    return run


def _apply_heal(core: ToolSpec) -> Callable[[Context, dict[str, Any]], dict[str, Any]]:
    """Core's apply_heal, which also heals as much nonlethal damage: "When a spell or a magical power cures hit point
    damage, it also removes an equal amount of nonlethal damage" (DEL-421). The answer's `nonlethal` is what is left,
    `nonlethal_healed` what went, where the target had some."""

    def run(ctx: Context, args: dict[str, Any]) -> dict[str, Any]:
        with ctx.storage.transaction():
            out = core.fn(ctx, args)
            who, fighting = _nonlethal_target(ctx, str(args.get("character") or ""))
            had = _nonlethal(fighting) if fighting is not None else int((who.state.d20 or {}).get(NONLETHAL) or 0)
            if not had:
                return out
            left = max(0, had - int(args.get("amount") or 0))
            said = _set_nonlethal(ctx, who, fighting, left)
        healed = {**out, NONLETHAL: left, "nonlethal_healed": had - left}
        return {**healed, "state": said["state"]} if "state" in said else healed

    return run


COMPANION_NO_XP = "A companion takes no XP: it grows with its master's level."


def _award_xp(core: ToolSpec) -> Callable[[Context, dict[str, Any]], dict[str, Any]]:
    """Core's award_xp, which adds the XP less the multiclass penalty (the engine's `award_xp`); with a penalty, the
    answer says the XP asked (`xp_awarded`), what was added (`xp_gained`) and why (`xp_penalty`). A companion takes
    none, said in `xp_note`; at 20th level the XP adds up, and `xp_note` says 20th level is the top. XP below the
    character's level's floor is raised to it first, said in `xp_note` (`progress.raised`). The character is read in
    the award's transaction, so what was added is against the XP it had just before (or the floor)."""

    def run(ctx: Context, args: dict[str, Any]) -> dict[str, Any]:
        with ctx.storage.transaction():
            who = characters.get(ctx, str(args.get("character") or ""))
            penalty = numbers.xp_penalty(who.sheet, ctx.lookups)
            out = core.fn(ctx, args)
        if "xp_total" not in out:
            return out
        if (who.sheet.d20 or {}).get("companion_of"):
            return {**out, "xp_gained": 0, "xp_note": COMPANION_NO_XP}
        if progress.top(who.sheet, ctx.lookups):
            out = {**out, "xp_note": progress.TOP_NOTE}
        amount = args.get("amount")
        start = who.state.xp
        if isinstance(amount, int) and amount > 0 and (raised := progress.raised(who.sheet, start, ctx.lookups)):
            start, note = raised
            out = {**out, "xp_note": note}
        if not penalty or not isinstance(amount, int) or amount <= 0:
            return out
        return {**out, "xp_gained": out["xp_total"] - start, "xp_awarded": amount,
                "xp_penalty": f"−{penalty}% (multiclass)"}  # fmt: skip

    return run


# --- companions --------------------------------------------------------------------------------------------------

LEVELS = frozenset({"level", "levels", "cls"})
"""The patch fields of update_character that change a character's levels."""
WHAT = {"animal-companion": "animal companion", "special-mount": "special mount"}


def _companions(ctx: Context, master_id: str) -> list[Any]:
    """The master's companions in the party: those whose `companion_of` is its id, not departed and not dead."""
    return [c for c in ctx.storage.characters.list(ctx.campaign_id)
            if (c.sheet.d20 or {}).get("companion_of") == master_id and c.departure is None
            and "dead" not in c.state.conditions]  # fmt: skip


def _which(sheet: Any, animal: str) -> str:
    """The feature the master's companion is under: the one it has; with both, the mount for one of the mount's
    animals, else the animal companion. Refused for a master with neither."""
    have = [fid for fid in companions.FEATURES if companions.feature_level(sheet, fid)]
    if not have:
        raise CheckError(f"{sheet.label or 'It'} has no animal companion or special mount: a druid has a companion "
                         "from 1st level, a ranger from 4th, a paladin her mount from 5th.")  # fmt: skip
    if len(have) == 2:
        mount = companions.table_row("special-mount")
        return "special-mount" if animal in (*mount["animals"], *mount.get("allowed", ())) else "animal-companion"
    return have[0]


def add_companion(ctx: Context, master: str, animal: str, name: str) -> dict[str, Any]:
    """A druid's or ranger's animal companion, or a 5th-level paladin's special mount: a PC of its own in the party,
    played by its master's seat, made from the animal's SRD row with the bonus Hit Dice, natural armour and Str and
    Dex (a mount's Int) its master's level gives; the companion grows when its master gains a level
    (update_character). One of each a master: a dead or departed one can be replaced."""
    who = characters.get(ctx, master)
    row = companions.monster(animal)
    if row is None:
        raise CheckError(f"Unknown animal '{animal}'.",
                         hint="Name an SRD animal: 'wolf', 'riding dog', 'heavy warhorse'.")  # fmt: skip
    kind = combat_rules.creature_type(row)
    if kind != "animal":
        raise CheckError(f"A companion is an animal: a {str(row['name']).lower()} is a {kind or 'creature'}.")
    named = str(row["name"]).lower()
    fid = _which(replace(who.sheet, label=who.name), named)
    level = companions.feature_level(who.sheet, fid)
    held = companions.block(fid, level - companions.offset(fid, named, level))
    if had := [c for c in _companions(ctx, who.id) if c.sheet.d20["companion"]["feature"] == fid]:
        raise CheckError(f"{who.name} already has {had[0].name} as their {WHAT[fid]}.",
                         hint="One at a time: a new one only when it is dead or released.")  # fmt: skip
    if not name.strip():
        raise CheckError("Give the companion a name.")
    sheet = {"cls": "", "race": "", "hp_max": companions.hp_max(row, held),
             "ability_scores": companions.companion_scores(row, held)}  # fmt: skip
    with ctx.storage.transaction():
        made = characters.create(ctx, name=name, kind="pc", sheet=sheet)
        build = {"companion_of": who.id, "animal": named, "companion": held}
        made = characters.update(ctx, made.id, {}, reason=f"{who.name}'s {WHAT[fid]}", d20_build=build)
        if who.controller_id is not None:  # what core's seats.claim stores: the master's seat plays it too
            ctx.storage.seats.set_controller(made.id, who.controller_id)
    played = (f"{made.name} is a PC in the party, played by {who.name}'s player; it fights on the party's side. It "
              "takes no share of XP and gains no levels: it grows with its master's.")  # fmt: skip
    notes = [played]
    if fid == "animal-companion":
        notes.append(f"It knows {held['tricks']} bonus tricks (Handle Animal) its master chooses, besides any taught.")
    else:
        notes.append("Called once a day (a full-round action) for 2 hours per paladin level; it comes back at full "
                     "health each time. Treated as a magical beast.")  # fmt: skip
    return {**_who(made), "master": who.name, "animal": named, "companion": held, "hp_max": made.sheet.hp_max,
            "derived": (made.sheet.d20 or {}).get("derived"), "notes": notes}  # fmt: skip


def grow_companions(ctx: Context, master: Any) -> list[dict[str, Any]]:
    """Each of the master's companions refilled for the master's level now: its block again, and the change in its
    hit points (their maximum and, alive, its current ones), Str, Dex and a mount's Int laid on what it has, so a
    change the DM made stays. A companion whose master's level no longer gives its animal stays as it is."""
    grown = []
    for comp in _companions(ctx, master.id):
        before = dict(comp.sheet.d20["companion"])
        fid, row = before["feature"], companions.monster(comp.sheet.d20.get("animal", ""))
        level = companions.feature_level(master.sheet, fid)
        if row is None or not level:
            continue
        try:
            held = companions.block(fid, level - companions.offset(fid, str(row["name"]).lower(), level))
        except CheckError:
            continue
        if held == before:
            continue
        rise = companions.hp_max(row, held) - companions.hp_max(row, before)
        scores = dict(comp.sheet.ability_scores)
        for ability in ("str", "dex"):
            change = int(held.get(ability, 0)) - int(before.get(ability, 0))
            scores[ability] = numbers.base_score(comp.sheet, ability) + change
        if held.get("int"):
            scores["int"] = held["int"]
        patch: dict[str, Any] = {"hp_max": max(1, comp.sheet.hp_max + rise), "ability_scores": scores}
        if comp.state.hp > 0:  # a lost level's hit points don't drop a standing companion: to 1 at the least
            patch["hp"] = max(1, comp.state.hp + rise)
        elif rise > 0:
            patch["hp"] = comp.state.hp + rise
        saved = characters.update(ctx, comp.id, patch, reason=f"{master.name} gained a level",
                                  d20_build={"companion": held})  # fmt: skip
        grown.append({**_who(saved), "companion": held, "hp_max": saved.sheet.hp_max})
    return grown


def _update_character(core: ToolSpec) -> Callable[[Context, dict[str, Any]], dict[str, Any]]:
    """Core's update_character; a patch that changes the levels then grows the character's companions with it
    (`grow_companions`), in the same transaction, said in `companions_grown`."""

    def run(ctx: Context, args: dict[str, Any]) -> dict[str, Any]:
        args = _by_class_ids(args)
        notes = _entering(ctx, args)
        with ctx.storage.transaction():
            out = core.fn(ctx, args)
            levelled = LEVELS & set(args.get("patch") or {})
            grown = grow_companions(ctx, characters.get(ctx, out["id"])) if levelled else []
        out = {**out, "notes": notes} if notes else out
        return {**out, "companions_grown": grown} if grown else out

    return run


def _by_class_ids(args: dict[str, Any]) -> dict[str, Any]:
    """The update with its patch's classes by their ids: `levels` keyed "eldritch-knight", not "eldritch knight", and
    each part of `cls` hyphenated to match ("Wizard/Eldritch-Knight"), so the sheet keeps the levels under the ids its
    features are kept by. A patch without them is as it was."""
    patch = args.get("patch")
    if not isinstance(patch, Mapping) or not ({"levels", "cls"} & set(patch)):
        return args
    patch = dict(patch)
    if isinstance(patch.get("levels"), Mapping):
        patch["levels"] = {numbers.slug(str(cls)): level for cls, level in patch["levels"].items()}
    if isinstance(patch.get("cls"), str):
        patch["cls"] = "/".join("-".join(part.split()) for part in patch["cls"].split("/"))
    return {**args, "patch": patch}


SHEET_FIELDS = frozenset(f.name for f in dataclasses.fields(Sheet)) - {"d20", "levels"}


def _entering(ctx: Context, args: dict[str, Any]) -> list[str]:
    """A patch whose `levels` give a first level in a prestige class is refused unless the character meets the class's
    requirements (`progress.entry_refusal`), before core's update takes the new class's level-up. They are checked on
    the sheet as the patch leaves it but for the classes entered: one patch can raise wizard 4 to 5 and enter the
    eldritch knight. Met, the notes of a feat's score that a worn item meets (`numbers.item_notes`). A patch core will
    refuse (a level that is no whole number) is left to core."""
    patch = args.get("patch") or {}
    levels = patch.get("levels")
    if not isinstance(levels, Mapping):
        return []
    who = characters.get(ctx, str(args.get("ref", "")))
    fields = {key: value for key, value in patch.items() if key in SHEET_FIELDS}
    try:
        after = Sheet.from_dict({**who.sheet.to_dict(), **fields, "levels": dict(levels)})
    except DataError:
        return []
    had = {numbers.slug(cls): level for cls, level in who.sheet.levels.items()}
    entering = [cls for cls, level in after.levels.items()
                if level >= 1 and not had.get(cls) and numbers.requirement_rows(cls)]  # fmt: skip
    if not entering:
        return []
    others = {cls: level for cls, level in after.levels.items() if cls not in entering}
    sheet = replace(after, label=who.name, levels=others)
    refusals = [refused for cls in entering if (refused := progress.entry_refusal(sheet, cls, ctx.lookups))]
    if refusals:
        raise CheckError(" ".join(refusals), hint=progress.ENTRY_HINT)
    return numbers.item_notes(sheet, ctx.lookups)


# --- the list ----------------------------------------------------------------------------------------------------


# --- spell resistance and the round's healing ----------------------------------------------------------------


_CASTER_LEVEL = re.compile(r"caster level (\d+)", re.IGNORECASE)
"""A monster row's "spells (caster level 9th)" or "Caster level 12th"."""


def _subject(ctx: Context, ref: str) -> tuple[rules.Combatant | None, Any, str, str]:
    """A combatant in the live fight or a character by id or name: (its combatant, its character, its name, its id);
    a character's combatant where it fights."""
    live = ctx.storage.combats.live(ctx.campaign_id)
    fight = rules.from_json(live[1]) if live is not None else None
    if fight is not None:
        try:
            c = rules.find(fight, ref)
        except rules.UnknownCombatant:
            c = None
        if c is not None:
            character = ctx.storage.characters.get(c.character_id) if c.character_id else None
            return c, character, c.name, c.id
    character = characters.get(ctx, ref)
    found = next((c for c in fight.combatants.values() if c.character_id == character.id), None) if fight else None
    return found, character, character.name, character.id


def _caster_level(
    ctx: Context, combatant: rules.Combatant | None, character: Any, row: Mapping[str, Any], cls: str | None
) -> tuple[int, str | None]:
    """The caster's level for the spell, and a note when it was chosen among several: the casting class `cls`'s
    (refused when it isn't one of the caster's or hasn't the spell on its list); without `cls`, that of the first of
    its casting classes, in the sheet's order, that has the spell on its list (a cleric's domains too,
    `magic._levels_of`), named in the note when more than one has it; a monster's row's "caster level Nth"; refused
    without one."""
    if character is not None:
        casting = magic._casting(character.sheet, ctx.lookups)  # a sheet stored before `casting` too
        listed = [c for c in casting if magic._levels_of(character.sheet, dict(row), c)]
        if cls is not None:
            wanted = numbers.slug(cls)
            if wanted not in listed:
                why = "isn't one of its casting classes" if wanted not in casting else f"hasn't {row['name']}"
                raise CheckError(f"{character.name}'s {cls} {why}.",
                                 hint=f"Its classes with {row['name']}: {', '.join(listed) or 'none'}.")  # fmt: skip
            return int(casting[wanted]["caster_level"]), None
        if listed:
            level = int(casting[listed[0]]["caster_level"])
            note = None
            if len(listed) > 1:
                note = (f"{row['name']} is on the {' and '.join(listed)} lists: the {listed[0]}'s caster level {level} "
                        "is used; pass cls for another.")  # fmt: skip
            return level, note
    elif cls is not None:
        raise CheckError("cls is a character's casting class.", hint="Pass caster_level for a monster.")
    monster = class_features.monster_row(combatant) if combatant is not None and character is None else None
    for key in ("special_attacks", "special_qualities"):
        if monster is not None and (found := _CASTER_LEVEL.search(str(monster.get(key) or ""))):
            return int(found.group(1)), None
    who = character.name if character is not None else combatant.name if combatant is not None else "the caster"
    raise CheckError(f"{who} casts {row['name']} at no caster level the engine knows: pass caster_level.",
                     hint="Pass caster_level: the caster's level for this spell.")  # fmt: skip


PENETRATION = ("spell-penetration", "greater-spell-penetration")
"""The feats that add +2 each to the check: Spell Penetration's "+2 bonus on caster level checks (1d20 + caster
level) made to overcome a creature's spell resistance", and Greater Spell Penetration's, which "stacks with the one
from Spell Penetration"."""


def spell_resistance(
    ctx: Context, caster: str, target: str, spell: str, caster_level: int | None = None, cls: str | None = None
) -> dict[str, Any]:
    """A caster's check against a target's spell resistance, before a spell that allows it takes effect on that target:
    d20 + caster level against the SR; it equals or beats it to overcome it. The caster level is the caster's for the
    spell's class, cls naming it where the spell is on several of the caster's lists (without it, the first, which the
    answer names), or a monster's from its entry; caster_level, the DM's, overrides it. A target with SR "+ class
    levels" (a drow's) adds its class levels. A spell whose entry says "Spell Resistance: No" needs no check, and a
    target without SR none."""
    row = magic.spell_row(spell)
    if row is None:
        raise CheckError(f"Unknown spell '{spell}'.", hint="Name an SRD spell: 'magic missile'.")
    by, by_character, by_name, by_id = _subject(ctx, caster)
    on, on_character, on_name, on_id = _subject(ctx, target)
    out: dict[str, Any] = {"caster": by_name, "target": on_name, "spell": row["name"]}
    allows = str(row.get("spell_resistance") or "")
    if allows.lower().startswith("no"):
        return {**out, "overcome": True, "note": f"{row['name']} allows no spell resistance ({allows})."}
    levels = sum(on_character.sheet.levels.values()) if on_character is not None else 0
    # A character's SR is its race's monster entry's ("spell resistance equal to 13 + class levels"): the core races
    # have none.
    race = numbers.monster_row(ctx.lookups, on_character.sheet.race) if on_character is not None else None
    sr = defences.spell_resistance(on, race, levels)
    if not sr:
        return {**out, "overcome": True, "note": f"{on_name} has no spell resistance: the spell works as cast."}
    level, chosen = (int(caster_level), None) if caster_level is not None else _caster_level(ctx, by, by_character,
                                                                                               row, cls)  # fmt: skip
    live = ctx.storage.combats.live(ctx.campaign_id)
    if live is not None:
        dice = Dice(ctx.dice.rng, ctx.storage.rolls, ctx.campaign_id, f"{ctx.beat}/{live[0]}")
        combat_round = rules.from_json(live[1]).round
    else:
        dice, combat_round = ctx.dice, None
    roll = dice.d(20, purpose=f"spell_resistance:{row['id']}", actor=by_id, target=on_id, combat_round=combat_round)
    # The caster's Spell Penetration and Greater Spell Penetration add to the check (`PENETRATION`), said in
    # `spell_penetration`. Not in the docstring: it is the tool's description, frozen in the tool-spec snapshot.
    feats = numbers.feat_ids(by_character.sheet) if by_character is not None else []
    penetration = 2 * sum(feat in feats for feat in PENETRATION)
    total = roll.total + level + penetration
    out.update(caster_level=level, sr=sr, roll=roll.total, total=total, overcome=total >= sr)
    if penetration:
        out["spell_penetration"] = penetration
    notes = [chosen] if chosen else []
    if "harmless" in allows.lower():
        notes.append(f"Spell Resistance: {allows}: a willing target may lower its SR (a standard action) instead.")
    if notes:
        out["note"] = " ".join(notes)
    ctx.log("spell_resistance", caster=by_name, target=on_name, spell=row["name"], roll=roll.total, total=total,
            sr=sr, overcome=total >= sr)  # fmt: skip
    return out


POOL_SPELL = combat_rules.POOL_SPELL


def _pool_selected(ctx: Context, declared: list[tuple[Any, str]]) -> list[tuple[Any, str]]:
    """Of `declared` (`(character, spell)`, in order) the spells a party caster casts from its spells a day (a
    sorcerer's, a bard's, a sorcerer/cleric's sorcerer spell with no uncast copy memorized): those core's round and
    setup leave to `cast_spell` (`combat._memorized_spells`), whose memorized copies they spend themselves."""
    found: list[tuple[Any, str]] = []
    copies: dict[tuple[str, str], int] = {}
    for who, spell in declared:
        if who.sheet.spell_slots:  # its memorized copies first, as core spends them
            key = (who.id, spell.casefold())
            copies[key] = copies.get(key, 0) + 1
            uncast = sum(1 for s in who.state.memorized if not s.cast and s.name.casefold() == spell.casefold())
            if copies[key] <= uncast or not ctx.d20.casts_unprepared(who.sheet, spell):
                continue
        found.append((who, spell))
    return found


def _refuse_unpaid(ctx: Context, casts: list[tuple[Any, str]]) -> None:
    """`CheckError` (as cast_spell refuses it) for the first caster whose spells a day can't pay for its `casts`: a
    dry run, before anything of the round or the setup is resolved; nothing is spent."""
    for who in {w.id: w for w, _ in casts}.values():
        refusal = magic.pool_refusal(who.sheet, who.state, [s for w, s in casts if w.id == who.id], ctx.lookups)
        if refusal is not None:
            raise CheckError(refusal, hint="Declare another spell or action for it; cast_spell refuses it too.")


def _spell_declared(raw: Any) -> str | None:
    """The spell a declaration casts (not a scroll or an item), or None."""
    if not isinstance(raw, dict) or not raw.get("spell") or raw.get("item"):
        return None
    return str(raw["spell"]).strip() if str(raw.get("kind") or "spell") == "spell" else None


def _actor(raw: Any) -> str:
    return str(raw.get("caster") or raw.get("actor") or raw.get("attacker")) if isinstance(raw, dict) else ""


def _round_pool(ctx: Context, actions: Any) -> tuple[dict[str, tuple[Any, str]], set[str]]:
    """The round's casts from a spells a day, by combatant id: those its actions declare, and a marked one
    (`POOL_SPELL`) of a combatant the actions leave alone (setup_combat's declaration, or a spell carrying over),
    each checked to be paid for (`_refuse_unpaid`); and the ids of the combatants the actions list."""
    live = ctx.storage.combats.live(ctx.campaign_id)
    if live is None or not isinstance(actions, list):
        return {}, set()
    fight = rules.from_json(live[1])
    listed: set[str] = set()
    fresh: list[tuple[Any, str, str]] = []
    for raw in actions:
        try:
            c = rules.find(fight, _actor(raw))
        except rules.CombatError:
            continue  # the round refuses an unknown actor itself
        listed.add(c.id)
        who = ctx.storage.characters.get(c.character_id) if c.character_id is not None else None
        if who is not None and (spell := _spell_declared(raw)) is not None:
            fresh.append((who, spell, c.id))
    chosen = _pool_selected(ctx, [(who, spell) for who, spell, _ in fresh])
    pool: dict[str, tuple[Any, str]] = {}
    for who, spell, cid in fresh:
        if (who, spell) in chosen:
            chosen.remove((who, spell))
            pool[cid] = (who, spell)
    for c in fight.combatants.values():
        marked = (c.d20 or {}).get(POOL_SPELL)
        who = ctx.storage.characters.get(c.character_id) if marked and c.character_id is not None else None
        if who is not None and c.id not in listed:
            pool[c.id] = (who, str(marked))
    _refuse_unpaid(ctx, list(pool.values()))
    return pool, listed


def _mark(ctx: Context, marks: Mapping[str, str | None]) -> None:
    """Set (a spell) or clear (None) each combatant's `POOL_SPELL` in the live fight."""
    live = _live_fight(ctx)
    if live is None or not marks:
        return
    id, fight = live[0], rules.from_json(live[1])
    changed = []
    for cid, spell in marks.items():
        c = fight.combatants.get(cid)
        if c is None or (c.d20 or {}).get(POOL_SPELL) == spell:
            continue
        d20 = {k: v for k, v in (c.d20 or {}).items() if k != POOL_SPELL} | ({POOL_SPELL: spell} if spell else {})
        changed.append(replace(c, d20=d20))
    if changed:
        _put(ctx, id, fight, *changed)


def _regenerate(ctx: Context) -> list[str]:
    """The round's end for those who regenerate or heal fast (DEL-421), not dead or removed: regeneration takes its
    value off the combatant's nonlethal damage ("heals nonlethal damage at a fixed rate"), and fast healing gives back
    its value in hit points, up to the maximum, as a heal (`combat.heal`: a character's state follows). The notes."""
    live = ctx.storage.combats.live(ctx.campaign_id)
    if live is None:
        return []
    id, fight = live[0], rules.from_json(live[1])
    notes, regenerated, healing = [], [], []
    for c in fight.combatants.values():
        if rules.status_of(c) in ("dead", "removed"):
            continue
        theirs = defences.of_combatant(c)
        if (regeneration := theirs.get("regeneration")) and (had := _nonlethal(c)):
            left = max(0, had - int(regeneration["value"]))
            notes.append(defences.regeneration_said(c, had, left))
            d20 = {k: v for k, v in (c.d20 or {}).items() if k != NONLETHAL}
            regenerated.append(replace(c, d20={**d20, NONLETHAL: left} if left else d20))
        if (fast := int(theirs.get("fast_healing") or 0)) and c.hp < c.hp_max:
            healing.append((c, min(fast, c.hp_max - c.hp)))
    if regenerated:
        _put(ctx, id, fight, *regenerated)
    for c, amount in healing:
        healed = combat.heal(ctx, c.id, amount)
        notes.append(defences.fast_healing_said(c, healed["hp_before"], healed["hp_after"]))
    return notes


def _combat_round(core: ToolSpec) -> Callable[[Context, dict[str, Any]], dict[str, Any]]:
    """Core's combat_round, and at its end the engine's regeneration and fast healing (`_regenerate`), a note of each
    under `defences` and the status after them. A spell a caster casts from its spells a day is
    spent by the round too, as a memorized copy is, once it is cast (`cast: true`) or lost (`cast: false`, spoilt),
    its report (DC, save, `left_today`, a spell lost to arcane spell failure) in `spells_spent`. A caster that never
    got to act (down, dead, removed) keeps it; one that keeps at it (`continues`) spends it when it is done. The
    round's casts the pool can't pay for refuse the round before it is resolved."""

    def run(ctx: Context, args: dict[str, Any]) -> dict[str, Any]:
        pool, listed = _round_pool(ctx, args.get("actions"))
        out = core.fn(ctx, args)
        if (pool or listed) and isinstance(out, dict) and "error" not in out:
            spent, marks = [], {}
            casters = set(pool) | listed  # a listed caster's new action replaces a spell it was marked for
            for entry in out.get("actions", ()):
                cid = entry.get("caster_id") if isinstance(entry, dict) else None
                if cid not in pool or "spell" not in entry:
                    continue
                who, spell = pool.pop(cid)
                if entry.get("continues"):
                    marks[cid] = spell
                elif "cast" in entry:
                    spent.append(_pool_cast(ctx, who.id, spell))
            # Only a spell still under way keeps its mark: a cast spent, lost or never begun is the round's
            _mark(ctx, {**{cid: None for cid in casters}, **marks})
            if spent:
                out = dict(out)
                status = out.pop("status")  # the status last, as core answers it
                out = {**out, "spells_spent": [*out.get("spells_spent", ()), *spent], "status": status}
        if isinstance(out, dict) and "error" not in out:
            out = _reported(ctx, out)
            if notes := _regenerate(ctx):
                status = out.pop("status", None)  # the status last, as core answers it, after the healing
                out = {**out, "defences": notes}
                if status is not None:
                    out["status"] = combat.round_status(_live(ctx)[1], ctx.d20)
        return out

    return run


def _reported(ctx: Context, out: dict[str, Any]) -> dict[str, Any]:
    """The round's entries with what the DM must not work out itself: a hit's `of_which` (the energy riders' damage,
    by energy, already in its `damage`), and a cast's `dc`, `school` and `save`: the report of the round's matching
    `spells_spent` entry (same caster and spell), else (a spell declared in `setup_combat` was spent at setup) the
    engine's read of the caster's cast, which spends nothing."""
    spent = {(str(e.get("caster")).casefold(), str(e.get("spell")).casefold()): e for e in out.get("spells_spent", ())}
    live = ctx.storage.combats.live(ctx.campaign_id)
    fight = rules.from_json(live[1]) if live is not None else None
    actions = []
    for entry in out.get("actions", ()):
        if not isinstance(entry, dict):
            actions.append(entry)
        elif entry.get("cast") is True and "spell" in entry:
            report = spent.get((str(entry.get("caster")).casefold(), str(entry["spell"]).casefold()))
            if report is None:
                c = fight.combatants.get(str(entry.get("caster_id"))) if fight is not None else None
                who = ctx.storage.characters.get(c.character_id) if c is not None and c.character_id else None
                report = magic.spell_numbers(who.sheet, who.state, str(entry["spell"]), ctx.d20.reference) if who else {}
            actions.append({**entry, **{k: report[k] for k in ("dc", "school", "save") if report.get(k) is not None}})
        elif entry.get("hit") and (riders := defences.of_which(entry.get("notes") or ())):
            actions.append({**entry, "of_which": riders})
        else:
            actions.append(entry)
    return {**out, "actions": actions} if actions != list(out.get("actions", ())) else out


def _pool_cast(ctx: Context, character_id: str, spell: str) -> dict[str, Any]:
    """A declared spell spent from its caster's spells a day, as `cast_spell` spends one (core's `_cast_d20`: the
    engine counts it and rolls arcane spell failure, the state saved, `spell_cast` logged), as a `spells_spent` entry:
    the caster and spell first, then the engine's report. `_round_pool` checked it can be paid for."""
    who = ctx.storage.characters.get(character_id)
    row = magic.spell_row(spell)
    name = row["name"] if row is not None else spell
    state, said = ctx.d20.cast(who.sheet, who.state, name, 0, dice=ctx.dice, actor=who.id, unprepared=True)
    if said.get("cast") is False:  # not after `_round_pool`; refused as cast_spell refuses it
        raise CheckError(str(said.get("refusal") or f"{who.name} can't cast {name}."))
    ctx.storage.characters.save_state(replace(who, state=state))
    ctx.log("spell_cast", character_id=who.id, name=who.name, spell=name, level=said.get("level"))
    return {"caster": who.name, "spell": name, **said}


TREASURE_LINE = string(
    "The encounter's level and treasure: 'EL 5, standard', 'EL 3, double standard', 'EL 2, half standard', 'EL 7, "
    "none', or a monster's line with its level ('EL 4, no coins; 50% goods; 50% items'). Without 'EL n' the source "
    "monster's CR is the level ('standard', source 'Ogre'); a CR below 1 is the 1st level."
)
TREASURE_SOURCE = string(
    "Whose hoard it is ('the goblins', 'the crypt chest'): a monster's name gives the level by its CR when the line "
    "has none; the line when empty."
)
NO_LAIR = "Ignored: 3.5 has no lair types; a hoard is the encounter's, by its level."


def _treasure_tools() -> list[ToolSpec]:
    """Core's generate_treasure and award_treasure described for 3.5's treasure by encounter level (the pack's
    `treasure.TREASURE`), not the classic letters: the same functions, its words."""
    lair = {"in_lair": boolean(NO_LAIR), "monster": string(NO_LAIR), "from_module": boolean(NO_LAIR)}
    line = {"treasure_types": TREASURE_LINE, "source": TREASURE_SOURCE, **lair}
    generating, awarding = _core("generate_treasure"), _core("award_treasure")
    return [
        _scoped(
            generating,
            "Roll a 3.5 hoard without awarding it, to describe what lies there: coins, goods (gems, art) and items by "
            "the encounter level, from the SRD's Table: Treasure and its random magic item tables. The same line and "
            "source in this beat are the same hoard, and so is award_treasure's.",
            line,
            generating.fn,
        ),
        _scoped(
            awarding,
            "Roll a 3.5 hoard and award it in one go: the coins to the party's coin, the gems, art and magic items to "
            "the loot pile. Awarded once: the same source again in this beat is refused. A hoard is the encounter's, "
            "by its level (after a fight, the encounter's EL). 3.5 gives no XP for gold; when the campaign does, "
            "gold_xp says what each living PC was given.",
            line,
            awarding.fn,
        ),
    ]


def specs() -> list[ToolSpec]:
    """The tools, each scoped to srd35."""
    own: list[ToolSpec] = [
        ToolSpec(
            "set_build",
            " ".join((set_build.__doc__ or "").split()),
            params(
                "character",
                character=string("The character."),
                skills=obj(
                    'Ranks by skill, its 3.5 name or id: {"climb": 4, "move silently": 2}. Replaces the ranks it had.',
                    additionalProperties={"type": "number", "minimum": 0},
                ),
                feats=array(
                    'The feats, replacing those it had: ["power attack", {"id": "weapon focus", "choice": "warhammer"}].',
                ),
                domains=strings("A cleric's two domains: ['war', 'good']."),
                weapon=string("The weapon in hand: 'warhammer', 'short sword'."),
                armor=string("The armour worn: 'scale mail', 'chain mail'."),
                shield=string("The shield carried: 'heavy steel shield', 'buckler'."),
                favoured_class=string("The race's favoured class: 'rogue', or 'any' for a human or half-elf."),
                choices=obj(
                    'Class choices: {"favoured_enemy": ["humanoid (orc)", "undead"]}, a ranger\'s, in the order '
                    'taken; a name again is a +2 raise of it. {"energy": "positive"}: a neutral cleric\'s. '
                    '{"requirements": {"assassin": ["kill someone for no other reason than to join"]}}: a prestige '
                    "class's special requirements, confirmed met in play."
                ),
                known=obj(
                    'A sorcerer\'s or bard\'s spells known, by class: {"sorcerer": ["light", "magic missile"]}, '
                    "0-level ones too. Replaces that class's list.",
                    additionalProperties={"type": "array", "items": {"type": "string"}},
                ),
                items=array(
                    "The magic items it has, replacing those it had, each by its name with its bonus: ['ring of "
                    "protection +2', '+1 flaming longsword', '+2 chain shirt', 'cloak of resistance +1', 'bag of "
                    "holding']."
                ),
                advances=obj(
                    'Which casting class a prestige class advances, by prestige class: {"eldritch knight": '
                    '["wizard"]}, {"mystic theurge": ["wizard", "cleric"]}: its spells a day, known and caster level '
                    "rise as if it had the prestige class's levels. Replaces that class's choice; [] clears it."
                ),
            ),
            lambda ctx, args: set_build(ctx, **args),
            True,
            True,
            areas=("characters", "combat"),
        ),
        ToolSpec(
            "convert_spell",
            " ".join((convert_spell.__doc__ or "").split()),
            params(
                "character",
                "prepared",
                character=string("The cleric or druid."),
                prepared=string("The prepared spell given up, uncast: 'bless'."),
                into=string("The spell cast in its place, of the copy's level or lower: 'cure light wounds', "
                            "'summon nature's ally i'. Without it, the highest."),
            ),
            lambda ctx, args: convert_spell(ctx, **args),
            True,
            True,
            areas=("characters", "combat"),
        ),
        ToolSpec(
            "set_stance",
            " ".join((set_stance.__doc__ or "").split()),
            params(
                "combatant",
                combatant=string("A combatant by id (chr_…, mon_1) or exact name."),
                power_attack=integer("Power Attack's number, 0 for none.", minimum=0),
                defensive=boolean("Fighting defensively."),
                flurry=boolean("A monk's flurry of blows."),
            ),
            lambda ctx, args: set_stance(ctx, **args),
            True,
            True,
            areas=("combat",),
        ),
        ToolSpec(
            "use_feature",
            USE_FEATURE,
            params(
                "character",
                "feature",
                character=string("Who uses it."),
                feature=string("rage, smite evil, inspire courage, lay on hands, wild shape, remove disease, "
                               "defensive stance, smite good or a feature used so many times a day (its id or "
                               "name)."),
                target=string("Lay on hands, remove disease: whom it heals (the paladin by default). Wild shape: "
                              "the animal, '' to change back."),
                amount=integer("Lay on hands: the hit points it heals. Rage, defensive stance: -1 ends it."),
            ),
            lambda ctx, args: class_features.use_feature(ctx, (characters, combat), **args),
            True,
            True,
            areas=("characters", "combat"),
        ),
        ToolSpec(
            "add_companion",
            " ".join((add_companion.__doc__ or "").split()),
            params(
                "master",
                "animal",
                "name",
                master=string("The druid, ranger or paladin."),
                animal=string("The animal, by its SRD name: 'wolf', 'riding dog', 'heavy warhorse'."),
                name=string("The companion's name."),
            ),
            lambda ctx, args: add_companion(ctx, **args),
            True,
            True,
            areas=("characters",),
        ),
        ToolSpec(
            "spell_resistance",
            " ".join((spell_resistance.__doc__ or "").split()),
            params(
                "caster",
                "target",
                "spell",
                caster=string("Who casts, a character or a combatant by id or exact name."),
                target=string("The creature the spell targets, by id or exact name."),
                spell=string("The spell: 'magic missile', 'hold person'."),
                caster_level=integer("The caster level, where the caster's sheet or entry doesn't give it; it "
                                     "overrides the sheet's.", minimum=1),
                cls=string("The casting class the spell is cast as, for a multiclass caster: 'cleric'."),
            ),
            lambda ctx, args: spell_resistance(ctx, **args),
            False,
            True,
            areas=("characters", "combat"),
        ),
        ToolSpec(
            "provoke",
            " ".join((provoke.__doc__ or "").split()),
            params(
                "provoker",
                "threatened_by",
                provoker=string("Who provokes, by id or exact name."),
                threatened_by=strings("The combatants threatening it, by id or exact name."),
                weapon=string("Part of the name of the threateners' attack: 'sword'."),
            ),
            lambda ctx, args: provoke(ctx, **args),
            True,
            True,
            areas=("characters", "combat"),
        ),
    ]
    resolve = _core("resolve_attack")
    saving = _core("saving_throw")
    skill = _core("skill_check")
    update = _core("update_combatant")
    setup = _core("setup_combat")
    add = _core("add_combatant")
    resting = _core("rest")
    updating = _core("update_character")
    awarding = _core("award_xp")
    ending = _core("end_combat")
    damaging = _core("apply_damage")
    healing = _core("apply_heal")
    dc = integer("The difficulty class to beat.")
    skill_props = {
        "skill": string(
            "The skill by its 3.5 name or id, or a unique part of one: 'move silently', 'open lock', 'lock'."
        ),
        "modifier": integer("Added to the d20: circumstances, the DM's ruling."),
        "dc": dc,
    }
    setup_enemies = {
        **setup.params["properties"]["enemies"],
        "description": setup.params["properties"]["enemies"]["description"]
        + " Under 3.5 a group also takes ac, touch_ac, flat_footed_ac, attack_bonus, damage, critical ('19–20/×2'),"
        " attack (its name), attacks_per_round, init (initiative modifier), bab and"
        ' saves ({"fort", "ref", "will"}); thac0 means nothing.',
    }
    condition = string(
        "flanked (+2; an ally on the target's far side; melee only), charging (+2, -2 AC until its next turn), "
        "set_vs_charge (double damage), into_melee (a ranged attack, shot or thrown, at a foe engaged in melee: -4, "
        "none with Precise Shot); cleave (the extra attack Cleave or Great Cleave earned, when the round couldn't make "
        "it: with late); rear and fleeing give nothing in 3.5."
    )
    rounds = _core("combat_round")
    round_actions = {
        **rounds.params["properties"]["actions"],
        "description": rounds.params["properties"]["actions"]["description"]
        + " Under 3.5 an attack is a full attack: every attack of its line, iterative and natural (a monster's claws, "
        'bite and the rest); a charge (condition charging) or "single": true (a move and an attack, a standard action, '
        "a character's or a monster's) is one attack at the full bonus.",
    }
    late = boolean(
        "An attack the round just resolved should have made: it is that round's, and leaves the coming round's "
        "attacks and any charge mark alone."
    )
    setup_surprise = boolean("Ignored: 3.5 has no surprise roll. Put flat-footed on the unaware (add_condition).")
    return [
        *(replace(spec, rulesets=(RULESET,)) for spec in own),
        _scoped(
            saving,
            "A Fortitude, Reflex or Will save for anyone: d20 + the save + modifier against the DC; a natural 1 fails "
            "and a natural 20 succeeds. A character from its sheet, a combatant from its numbers; in a fight it is "
            "that round's save, with the combatant's effects.",
            {"save_type": string("fort, ref or will (or Fortitude, Reflex, Will)."), "dc": dc},
            _saving_throw(saving),
        ),
        _scoped(
            skill,
            "A 3.5 skill check from the character's sheet: d20 + the skill's total + modifier against the DC (no DC: "
            "the total, for you to judge). A trained-only skill without ranks can't be tried.",
            skill_props,
            _skill_check,
        ),
        _scoped(
            resolve,
            resolve.description,
            {"condition": condition, "late": late},
            lambda ctx, args: combat.resolve_attack(ctx, **args),
        ),
        _scoped(rounds, rounds.description, {"actions": round_actions}, _combat_round(rounds)),
        _scoped(
            update,
            "Set a combatant's numbers to what the module or your ruling says: hit points and morale in stats, and "
            "its 3.5 numbers (AC, touch and flat-footed AC, the held attack's bonus, damage and critical, saves). A "
            "PC's come from its sheet (set_build).",
            OVERRIDE_PROPS,
            _update_combatant(update),
            required=("id",),
        ),
        _scoped(
            setup, setup.description, {"enemies": setup_enemies, "surprise": setup_surprise}, _setup_combat(setup)
        ),
        _scoped(
            add,
            "Monsters joining the live fight (reinforcements), as setup_combat's enemy groups, each with its 3.5 "
            "numbers from its SRD row. They act from the next initiative.",
            {},
            _add_combatant(add),
        ),
        _scoped(
            resting,
            f"{resting.description} Under 3.5 a rage still on ends first: its hit points go and the barbarian is "
            "fatigued.",
            {},
            _rest(resting),
        ),
        _scoped(
            updating,
            f"{updating.description} Under 3.5 a level gained or lost grows the character's animal companion or "
            "mount with it.",
            {},
            _update_character(updating),
        ),
        _scoped(
            awarding,
            f"{awarding.description} Under 3.5 a multiclass character takes −20% for each class not within one level "
            "of its highest (its race's favoured class doesn't count); the answer says it.",
            {},
            _award_xp(awarding),
        ),
        _scoped(ending, ending.description, {}, _end_combat(ending)),
        _scoped(
            damaging,
            f"{damaging.description} Under 3.5, `nonlethal` makes it nonlethal damage: kept apart from the hit points, "
            "it staggers at them and knocks out above them.",
            {"nonlethal": boolean("Nonlethal damage (a sap, a fist, a blade on a regenerating troll), not off hp.")},
            _apply_damage(damaging),
        ),
        _scoped(
            healing,
            f"{healing.description} Under 3.5 it heals as much nonlethal damage too.",
            {},
            _apply_heal(healing),
        ),
        *_treasure_tools(),
        _scoped(_core("surprise_check"), f"Not in 3.5. {NO_SURPRISE}", {}, _not_in_3_5(NO_SURPRISE)),
        _scoped(_core("morale_check"), f"Not in 3.5. {NO_MORALE}", {}, _not_in_3_5(NO_MORALE)),
        _scoped(_core("reaction"), f"Not in 3.5. {NO_REACTION}", {}, _not_in_3_5(NO_REACTION)),
        _scoped(_core("council"), f"Not in 3.5. {NO_REACTION}", {}, _not_in_3_5(NO_REACTION)),
    ]
