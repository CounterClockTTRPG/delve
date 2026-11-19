"""Combat under 3.5 (DEL-388): combatants from sheets and monster rows, initiative, and the swing, a d20 plus the attack
bonus against AC, with critical hits, sneak attack and flat-footed targets.

A combatant's numbers are in `Combatant.d20` (the plan's shared shape): its BAB, AC, touch and flat-footed AC,
initiative bonus, Dex modifier, attack forms (`attack_line`), saves, creature type, CR and stance. Its `attacks` are
the forms as core's attack blocks, so core picks one by name as it always has; the swing reads the form of that name.

Some monster rows came out of the RTFs mangled ("1st-Level Warrior" rows: the goblin's size is "Goblin", its type
"1st-Level", with "Small" and "Humanoid" in its subtypes): a size that isn't a size is read from the AC's "size"
term, and a type that isn't a type from the subtypes. Undead, constructs, oozes, plants and elementals are immune to
critical hits and to sneak attack (the SRD's type traits)."""

from __future__ import annotations

import re
from dataclasses import replace
from fractions import Fraction
from typing import TYPE_CHECKING, Any

from delve.dice import Roll
from delve.domain.characters import Sheet
from delve.rules.classic.combat import AttackBlock, Combatant, HitDie
from delve.rules.classic.life import with_condition
from delve.rules.d20 import Initiative, Swing
from delve_srd35.engine import attack_line, numbers, progress

if TYPE_CHECKING:
    from collections.abc import Mapping

    from delve.dice import Dice
    from delve.domain.campaigns import Character

CRIT_IMMUNE = frozenset({"undead", "construct", "ooze", "plant", "elemental"})
"""The creature types immune to critical hits, and so to sneak attack."""
TYPES = frozenset({"aberration", "animal", "construct", "dragon", "elemental", "fey", "giant", "humanoid",
                   "magical beast", "monstrous humanoid", "ooze", "outsider", "plant", "undead", "vermin"})  # fmt: skip
SIZE_CODES = {"fine": "T", "diminutive": "T", "tiny": "T", "small": "S", "medium": "M", "m": "M", "large": "L",
              "huge": "H", "gargantuan": "G", "colossal": "G"}  # fmt: skip
"""Each size word as core's size code (its smallest is T, its largest G)."""
SIZE_BY_AC = {8: "fine", 4: "diminutive", 2: "tiny", 1: "small", 0: "medium", -1: "large", -2: "huge",
              -4: "gargantuan", -8: "colossal"}  # fmt: skip
"""The size modifier to AC of each size (the SRD's Table 7-1)."""
FINESSE = frozenset({"rapier", "whip", "chain-spiked"})
"""The weapons Weapon Finesse takes besides the light ones."""
PROFICIENT = {
    "fighter": ({"simple", "martial"}, set()),
    "cleric": ({"simple"}, set()),
    "rogue": ({"simple"}, {"crossbow-hand", "rapier", "sap", "shortbow", "sword-short"}),
    "wizard": (set(), {"club", "dagger", "crossbow-heavy", "crossbow-light", "quarterstaff"}),
}
"""The slice's classes' weapon proficiencies (each class's Weapon and Armor Proficiency): the categories and the
weapons by id. A class not here is taken as proficient with everything (the DM's call)."""
RACE_WEAPONS = {
    "elves": {"longsword", "rapier", "longbow", "longbow-composite", "shortbow", "shortbow-composite"},
}
"""Weapons a race is proficient with whatever its class (the elves' Weapon Proficiency)."""
RACE_MARTIAL = {"dwarves": {"waraxe-dwarven", "urgrosh-dwarven"}, "gnomes": {"hammer-gnome-hooked"}}
"""Exotic weapons a race treats as martial (Weapon Familiarity)."""
FLAT_FOOTED = ("flat-footed", "flat_footed")
FLANKED = ("flanked", "flanking")
IMMOBILIZED = frozenset({"held", "helpless", "paralyzed", "paralysed", "pinned", "bound", "immobilized", "asleep",
                         "unconscious"})  # fmt: skip
"""Conditions under which uncanny dodge doesn't keep the Dex bonus to AC (the SRD: "if immobilized")."""
INTO_MELEE = "into_melee"
"""The condition of a ranged attack (shot or thrown) at a foe engaged in melee: -4, none with Precise Shot (DEL-397)."""
CHARGED = "charging_ac_penalty"
"""Core's mark on a charger (as classic sets it): under 3.5, -2 AC until its next turn. Core clears it only at the
fight's end, so the swing also keeps the charge's round in the charger's `stance["charged"]`, and the penalty counts
only in that round (ruling R12)."""
NO_BONUS = {
    "rear": "3.5: no rear bonus — flanking needs an ally opposite",
    "fleeing": "3.5: a fleeing foe provokes — use provoke",
}
"""Core's attack conditions that give nothing under 3.5, and why."""
SPELL_FORMS = ("cleric", "wizard")
"""The classes that get the touch and ranged touch forms for their spells."""
LAUNCHED = ("bow", "crossbow")
"""What a ranged weapon's id has when it fires ammunition rather than being thrown (a sling is the halflings' own)."""
HALFLING_THROWN = 1
"""The halflings' racial bonus on attack rolls with thrown weapons and slings."""
MOST_DODGE = 4
"""The most dodge bonus a flat-footed touch AC takes off besides Dex (see `_armour_class`)."""


def _plain(text: Any) -> str:
    return str(text or "").translate(str.maketrans({"–": "-", "−": "-"}))


def _terms(armor_class: str) -> dict[str, int]:
    """The AC breakdown's size, Dex, deflection and dodge terms: "15 (+1 size, +1 Dex, …)" is {"size": 1, "dex": 1}."""
    found: dict[str, int] = {}
    for number, name in re.findall(r"([+-]\d+)\s+(size|dex|deflection|dodge)\b", _plain(armor_class), re.IGNORECASE):
        found[name.lower()] = found.get(name.lower(), 0) + int(number)
    return found


def touch_from_breakdown(armor_class: str) -> int:
    """The touch AC of an AC line: 10 + size + Dex + deflection + dodge."""
    return 10 + sum(_terms(armor_class).values())


def creature_type(row: Mapping[str, Any]) -> str:
    """The row's creature type, lower case: its `type` when that is one, else the first of its subtypes that is one,
    else one named in its `type` ("Black Dragon(Adult)" is a dragon); "" when none is."""
    raw = str(row.get("type") or "").strip().lower()
    if raw in TYPES:
        return raw
    for sub in row.get("subtypes") or ():
        if str(sub).strip().lower() in TYPES:
            return str(sub).strip().lower()
    return next((t for t in sorted(TYPES, key=len, reverse=True) if re.search(rf"\b{t}\b", raw)), "")


def creature_size(row: Mapping[str, Any]) -> str:
    """The row's size word, lower case: its `size` when that is one, else the size its AC's "size" term gives, else
    a size among its subtypes; "medium" when none says."""
    raw = str(row.get("size") or "").strip().lower()
    if raw in SIZE_CODES:
        return "medium" if raw == "m" else raw
    by_ac = _terms(str(row.get("armor_class") or "")).get("size")
    if by_ac in SIZE_BY_AC:
        return SIZE_BY_AC[by_ac]
    return next((str(s).lower() for s in row.get("subtypes") or () if str(s).lower() in SIZE_CODES), "medium")


def _stance(old: Combatant) -> dict[str, Any]:
    """The stance and attacks of opportunity the combatant has in the fight already, or fresh ones."""
    kept = old.d20 or {}
    return {
        "stance": dict(kept.get("stance") or {"power_attack": 0, "defensive": False}),
        "aoo": dict(kept.get("aoo") or {"round": 0, "used": 0}),
    }


def _armed(combatant: Combatant, forms: list[dict[str, Any]]) -> Combatant:
    """The combatant with its forms as attack blocks, still holding the one of the name it held (else the first)."""
    if not forms:
        return combatant
    held = combatant.attacks[combatant.weapon].name if 0 <= combatant.weapon < len(combatant.attacks) else ""
    blocks = tuple(AttackBlock(f["name"], f["damage"], f["damage"], rate=float(f["count"])) for f in forms)
    index = next((i for i, b in enumerate(blocks) if b.name == held), 0)
    return replace(combatant, attacks=blocks, weapon=index)


def combatant_from_monster(row: Mapping[str, Any], combatant: Combatant, overrides: Mapping[str, Any]) -> Combatant:
    """The combatant core made from the row, with the row's 3.5 numbers. An `ac` override is its AC, a `dmg` override
    its first form's damage and a `size` override its size."""
    dex_score = numbers.signed(dict(row.get("abilities") or {}).get("dex"))
    dex = numbers.modifier(dex_score) if dex_score is not None else 0
    armor_class = str(row.get("armor_class") or "")
    ac = numbers.signed(armor_class)
    ac = 10 + dex if ac is None else ac
    if overrides.get("ac") is not None:
        ac = int(overrides["ac"])
    touch = numbers.signed(row.get("touch"))
    flat = numbers.signed(row.get("flat_footed"))
    terms = _terms(armor_class)
    kind = creature_type(row)
    forms, unread = attack_line.read(row.get("full_attack") or "")
    if not forms:
        forms, unread = attack_line.read(row.get("attack") or "")
    if forms and overrides.get("dmg") is not None:
        forms[0] = {**forms[0], "damage": str(overrides["dmg"])}
    saves = dict(row.get("saves") or {})
    d20: dict[str, Any] = {
        "bab": numbers.signed(row.get("base_attack_grapple")) or 0,
        "ac": ac,
        "touch": touch if touch is not None else touch_from_breakdown(armor_class),
        "flat_footed": flat if flat is not None else ac - max(terms.get("dex", dex), 0) - terms.get("dodge", 0),
        "init_bonus": numbers.signed(row.get("initiative")) or 0,
        "dex": dex,
        "attacks": forms,
        "saves": {save: numbers.signed(saves.get(save)) or 0 for save in ("fort", "ref", "will")},
        "type": kind,
        "crit_immune": kind in CRIT_IMMUNE,
        "sneak": "",
        **_stance(combatant),
    }
    if "uncanny dodge" in str(row.get("special_qualities") or "").lower():
        d20["uncanny_dodge"] = True
    if "precise shot" in str(row.get("feats") or "").lower():
        d20["precise_shot"] = True
    if unread:
        d20["warnings"] = unread
    if (cr := progress.cr_for(dict(row))) is not None:
        d20["cr"] = cr
    size = combatant.size if overrides.get("size") is not None else SIZE_CODES[creature_size(row)]
    return replace(_armed(combatant, forms), ac=ac, size=size, d20=d20)


_HD_TERM = re.compile(r"\s*([+-])?\s*(?:(?:(\d+)\s*/\s*(\d+)\s*d\s*(\d+))|(?:(\d+)\s*d\s*(\d+))|(\d+))\s*")
"""One term of a Hit Dice line: a fraction of a die ("1/2 d8"), dice ("4d12") or a bonus ("+16"), with its sign."""


def read_hit_dice(line: str) -> tuple[HitDie, ...] | None:
    """A Hit Dice line as its parts (DEL-402): "1d8+1", a template's "4d8+19 plus 4d12+16" and "8d10 + 7d8 + 75" (the
    dice of each, each bonus with the dice before it), and the small creatures' fraction of a die, "1/2 d6+1". None for
    a line that is not all of these ("Varies", "2 hp", a template row's empty one): core reads it."""
    text = str(line or "").replace("–", "-").replace("−", "-").replace(" plus ", " + ")
    parts: list[HitDie] = []
    at = 0
    while at < len(text):
        found = _HD_TERM.match(text, at)
        if found is None or found.end() == at:
            return None
        sign, num, den, frac_sides, count, sides, bonus = found.groups()
        at = found.end()
        if bonus is not None:
            if not parts:
                return None
            last = parts[-1]
            parts[-1] = replace(last, mod=last.mod + int(bonus) * (-1 if sign == "-" else 1))
        elif sign == "-" or (parts and sign is None):
            return None
        elif num is not None:
            parts.append(HitDie(1, int(frac_sides), share=Fraction(int(num), int(den))))
        else:
            parts.append(HitDie(int(count), int(sides)))
    return tuple(parts) or None


def _feats(sheet: Sheet) -> list[tuple[str, str]]:
    """The sheet's feats as (id, slug of the choice)."""
    return [
        (f["id"], numbers.slug(f.get("choice") or "")) if isinstance(f, dict) else (str(f), "")
        for f in (sheet.d20 or {}).get("feats", ())
    ]


def _proficient(sheet: Sheet, weapon: dict[str, Any], race: str) -> bool:
    classes = [c for c in sheet.levels if sheet.levels[c] > 0] or [numbers.slug(sheet.cls)]
    if any(c not in PROFICIENT for c in classes):
        return True
    if weapon["id"] in RACE_WEAPONS.get(race, set()):
        return True
    category = "martial" if weapon["id"] in RACE_MARTIAL.get(race, set()) else weapon["category"]
    return any(category in PROFICIENT[c][0] or weapon["id"] in PROFICIENT[c][1] for c in classes)


def _with(dice: str, bonus: int) -> str:
    return f"{dice}{bonus:+d}" if bonus else dice


def _body(sheet: Sheet, reference: Any) -> tuple[str, bool, int, int, int]:
    """The character's race id, whether it is Small, its size modifier to attacks (the same as to AC), and its Str and
    Dex modifiers."""
    race = numbers.race_named(reference, sheet.race) or {}
    small = str(race.get("size", "")).lower() == "small"
    size = numbers.SIZE["small"]["ac"] if small else 0
    mods = (numbers.modifier(numbers.ability_score(sheet, a)) for a in ("str", "dex"))
    return str(race.get("id", "")), small, size, *mods


def _weapon_form(sheet: Sheet, derived: dict[str, Any], reference: Any) -> tuple[dict[str, Any], list[str]]:
    """The form of the sheet's `weapon` (an unarmed strike without one), and a warning for a weapon the SRD's table
    hasn't."""
    name = str((sheet.d20 or {}).get("weapon") or "")
    weapon = attack_line.weapon(name or "unarmed strike")
    race, small, size, strength, dex = _body(sheet, reference)
    bab = int(derived["bab"])
    if weapon is None:
        form = {"name": name.strip().lower(), "bonus": bab + strength + size,
                "damage": _with("1d6", strength), "threat": 20, "mult": 2, "count": 1, "touch": False, "hands": 1,
                "ranged": False}  # fmt: skip
        return form, [f"Unknown weapon '{name}': it swings as BAB + Str for 1d6 + Str."]
    feats = _feats(sheet)
    ids = {weapon["id"], numbers.slug(name)}
    ranged = weapon["kind"] == "ranged"
    light = weapon["kind"] in ("light", "unarmed") or weapon["id"] in FINESSE
    finesse = light and not ranged and any(f == "weapon-finesse" for f, _ in feats)
    ability = dex if ranged else max(strength, dex) if finesse else strength
    # The War domain's granted power: proficiency and Weapon Focus with the deity's favoured weapon, which is taken to
    # be the weapon the cleric carries.
    war = "war" in (sheet.d20 or {}).get("domains", ())
    focus = war or any(f == "weapon-focus" and choice in ids for f, choice in feats)
    nonproficient = not war and not _proficient(sheet, weapon, race)
    if "crossbow" in weapon["id"]:
        might = 0
    elif ranged and ("bow" in weapon["id"] or weapon["id"] == "sling"):
        might = min(strength, 0)
    elif weapon["kind"] == "two-handed" and strength > 0:
        might = strength * 3 // 2
    else:
        might = strength
    die = str(weapon["damage_s" if small else "damage_m"]).split("/")[0]
    thrown = ranged and (weapon["id"] == "sling" or not any(word in weapon["id"] for word in LAUNCHED))
    racial = HALFLING_THROWN if race == "halflings" and thrown else 0
    threat = int(weapon["threat"])
    if any(f == "improved-critical" and choice in ids for f, choice in feats):
        threat = 21 - 2 * (21 - threat)
    form = {
        "name": (name or "unarmed strike").strip().lower(),
        "bonus": bab + ability + size + int(focus) - 4 * int(nonproficient) + racial,
        "damage": _with(die, might),
        "threat": threat,
        "mult": int(weapon["mult"]),
        "count": 1,
        "touch": False,
        "hands": 2 if weapon["kind"] == "two-handed" else 1,
        "ranged": ranged,
    }
    return form, []


def combatant_from_sheet(character: Character, combatant: Combatant, reference: Any) -> Combatant:
    """The combatant core made from the character, with the sheet's derived numbers. Its forms are its weapon's, and a
    cleric's or wizard's `touch` and `ranged touch` for its spells. Each negative level takes 1 off each save here and
    off each attack roll in the swing."""
    sheet = character.sheet
    derived = (sheet.d20 or {}).get("derived") or numbers.derived(sheet, reference)
    negative = int((sheet.d20 or {}).get("negative_levels", 0))
    form, warnings = _weapon_form(sheet, derived, reference)
    forms = [form]
    _, small, size, strength, dex = _body(sheet, reference)
    if any(sheet.levels.get(c, 0) > 0 for c in SPELL_FORMS) or numbers.slug(sheet.cls) in SPELL_FORMS:
        bab = int(derived["bab"])
        spell = {"damage": "0", "threat": 20, "mult": 2, "count": 1, "touch": True, "hands": 1}
        forms += [{"name": "touch", "bonus": bab + strength + size, **spell, "ranged": False},
                  {"name": "ranged touch", "bonus": bab + dex + size, **spell, "ranged": True}]  # fmt: skip
    max_dex = derived.get("max_dex")
    d20: dict[str, Any] = {
        "bab": derived["bab"],
        "ac": derived["ac"],
        "touch": derived["touch"],
        "flat_footed": derived["flat_footed"],
        "init_bonus": derived["init"],
        "dex": dex if max_dex is None else min(dex, max_dex),
        "attacks": forms,
        "saves": {save: int(derived[save]) - negative for save in ("fort", "ref", "will")},
        "type": "humanoid",
        "crit_immune": False,
        "sneak": derived.get("sneak", ""),
        **_stance(combatant),
    }
    if derived.get("uncanny_dodge"):
        d20["uncanny_dodge"] = True
    if any(f == "precise-shot" for f, _ in _feats(sheet)):
        d20["precise_shot"] = True
    if negative:
        d20["negative_levels"] = negative
    if warnings:
        d20["warnings"] = warnings
    return replace(_armed(combatant, forms), ac=derived["ac"], size="S" if small else combatant.size, d20=d20)


def initiative(combatant: Combatant, dice: Dice, combat_round: int) -> Initiative:
    """A d20 plus the initiative bonus (Dex, and +4 with Improved Initiative)."""
    bonus = int(_numbers(combatant).get("init_bonus", 0))
    roll = dice.d(20, purpose="initiative", actor=combatant.id, combat_round=combat_round)
    return Initiative(roll.total, roll.total + bonus, (roll,))


def _numbers(combatant: Combatant) -> dict[str, Any]:
    if combatant.d20 is None:
        raise ValueError(f"{combatant.name} has no 3.5 numbers: it wasn't made by the 3.5 engine.")
    return combatant.d20


def _form(attacker: Combatant, mine: dict[str, Any]) -> dict[str, Any]:
    """The form of the attack block the attacker holds; for a block that has none (a thrown flask), the block's damage
    at the attacker's BAB."""
    forms = list(mine.get("attacks") or ())
    if 0 <= attacker.weapon < len(attacker.attacks):
        block = attacker.attacks[attacker.weapon]
        named = next((f for f in forms if f["name"] == block.name), None)
        if named is not None:
            return named
        return {"name": block.name, "bonus": int(mine.get("bab", 0)), "damage": block.damage_sm, "threat": 20,
                "mult": 2, "count": 1, "touch": False, "hands": 1, "ranged": False}  # fmt: skip
    if forms:
        return forms[0]
    raise ValueError(f"{attacker.name} has no attack to make.")


def flat_footed(attacker: Combatant, target: Combatant, combat_round: int) -> bool:
    """Flat-footed: in round 1 before it has acted (no initiative yet, or a lower one than the attacker's), or with the
    `flat-footed` condition."""
    if any(c in target.conditions for c in FLAT_FOOTED):
        return True
    if combat_round != 1:
        return False
    return target.init is None or (attacker.init is not None and attacker.init > target.init)


def keeps_dex(target: Combatant) -> bool:
    """Whether the target keeps its Dex bonus to AC though flat-footed: uncanny dodge (a rogue of 4th level, or a
    monster whose special qualities name it), unless it is immobilized (DEL-396)."""
    numbers = target.d20 or {}
    return bool(numbers.get("uncanny_dodge")) and not any(c in IMMOBILIZED for c in target.conditions)


def _armour_class(target: Combatant, touch: bool, flat: bool, combat_round: int) -> int:
    """The target's AC against the attack: touch, flat-footed, or both at once (touch less what flat-footed loses, its
    Dex and dodge bonuses); +2 while it fights defensively, -2 in the round it charged. With uncanny dodge its
    flat-footed AC is its AC, so one that has lost its Dex anyway (immobilized) is at its AC less its Dex bonus.

    What flat-footed loses is its AC less its flat-footed AC; where that isn't its Dex bonus and up to `MOST_DODGE`
    more (an `ac` override the flat-footed AC doesn't follow), only the Dex bonus."""
    theirs = target.d20
    if theirs is None:
        return target.ac
    if touch and flat:
        dex = max(int(theirs.get("dex", 0)), 0)
        lost = int(theirs.get("ac", 0)) - int(theirs.get("flat_footed", 0))
        ac = int(theirs["touch"]) - (lost if dex <= lost <= dex + MOST_DODGE else dex)
    elif touch:
        ac = int(theirs["touch"])
    elif flat and theirs.get("uncanny_dodge"):
        ac = min(int(theirs["flat_footed"]), int(theirs["ac"]) - max(int(theirs.get("dex", 0)), 0))
    elif flat:
        ac = int(theirs["flat_footed"])
    else:
        ac = int(theirs["ac"])
    stance = theirs.get("stance") or {}
    charged = CHARGED in target.conditions and stance.get("charged") == combat_round
    return ac + 2 * bool(stance.get("defensive")) - 2 * charged


def _damage(dice: Dice, expression: str, times: int, purpose: str, key: dict[str, Any]) -> tuple[int, list[Roll]]:
    """The damage expression rolled `times` times and summed; a plain number counts `times` over with no roll."""
    if re.fullmatch(r"[+-]?\d+", expression):
        return int(expression) * times, []
    rolled = dice.roll(expression, purpose=purpose, times=times, **key)
    rolls = rolled if isinstance(rolled, list) else [rolled]
    return sum(r.total for r in rolls), rolls


def swing(attacker: Combatant, target: Combatant, condition: str, dice: Dice, combat_round: int) -> Swing:
    """One attack: a d20 + the form's bonus (−4 fighting defensively, − Power Attack, − 1 per negative level, + the
    attacker's effects' to-hit, +2 flanking, +2 charging, -4 shooting or throwing into melee without Precise Shot)
    against the target's AC (`_armour_class`, less the target's
    effects' classic `ac`). A natural 1 misses and a natural 20 hits. A
    hit on the form's threat range is a critical threat; a second roll against the same AC confirms it, and the damage
    is rolled `mult` times (Power Attack's and the effects' damage too, sneak dice not). A target immune to criticals
    takes the damage once. Power Attack adds its number to melee damage, twice that two-handed, and isn't used with a
    light weapon; only a melee attack flanks; a rogue's sneak dice come once on a flat-footed or flanked target that
    isn't immune (one with uncanny dodge, not immobilized, keeps its Dex and so isn't open to them flat-footed); set against a charge, the damage is doubled; a hit deals at least 1 (a spell's touch form deals none,
    and nothing is added to it). A charger is marked `charging_ac_penalty`; a rear or fleeing attack gets no bonus,
    with a note why."""
    mine = _numbers(attacker)
    theirs = target.d20 or {}
    form = _form(attacker, mine)
    n = attacker.attacks_used + 1
    # An attack of opportunity (`provoke`) rolls under purposes of its own, so the attacker's own attacks this round
    # don't find its rolls.
    step = "aoo" if (mine.get("aoo") or {}).get("swinging") else n
    key = {"actor": attacker.id, "target": target.id, "combat_round": combat_round}
    stance = mine.get("stance") or {}
    charged_in: int | None = None
    melee = not form.get("ranged")
    power = int(stance.get("power_attack", 0)) if melee else 0
    bonus = form["bonus"]
    notes: list[str] = []
    held = attack_line.weapon(str(form.get("name") or ""))
    if power and held is not None and held["kind"] in ("light", "unarmed"):
        power = 0
        notes.append("Power Attack: not with a light weapon")
    rolls: list[Roll] = []
    cond = condition.strip().lower()
    flanking = cond in FLANKED or any(c in target.conditions for c in FLANKED)
    flanked = flanking and melee
    conditions = attacker.conditions
    caught = flat_footed(attacker, target, combat_round)
    flat = caught and not keeps_dex(target)  # flat-footed and without its Dex bonus to AC
    if caught:
        notes.append("flat-footed")
    if caught and not flat:
        notes.append("uncanny dodge: keeps Dex to AC")
    ac = _armour_class(target, bool(form.get("touch")), flat, combat_round)
    # A core effect's `ac` keeps its classic sign (ruling R10): +N is N easier to hit ("held … ac 4"), -1 a ring of
    # protection's 1 harder.
    effect_ac = sum(e.ac for e in target.effects)
    if effect_ac:
        ac -= effect_ac
        notes.append(f"{effect_ac:+d} AC modifier on {target.name} (active effects).")
    situational = 0
    if flanked:
        situational += 2
        notes.append("+2 to hit (flanking).")
    elif flanking:
        notes.append("3.5: only a melee attack flanks")
    if cond == "charging":
        situational += 2
        conditions = with_condition(conditions, CHARGED, True)
        charged_in = combat_round
        notes.append("+2 to hit (charging); -2 AC until its next turn.")
    if cond == INTO_MELEE and melee:
        notes.append("3.5: into_melee is for a ranged attack")
    elif cond == INTO_MELEE and mine.get("precise_shot"):
        notes.append("Precise Shot: no -4 into melee.")
    elif cond == INTO_MELEE:
        situational -= 4
        notes.append("-4 to hit (shooting into melee).")
    if cond in NO_BONUS:
        notes.append(NO_BONUS[cond])
    if bonus is None:  # a swarm's attack hits whoever is in it, with no roll
        hit, face, total = True, 0, 0
    else:
        total = int(bonus) - 4 * bool(stance.get("defensive")) - power - int(mine.get("negative_levels", 0))
        total += sum(e.to_hit for e in attacker.effects) + situational
        roll = dice.d(20, purpose=f"attack#{step}", **key)
        rolls.append(roll)
        face = roll.total
        hit = face != 1 and (face == 20 or face + total >= ac)
    damage, die = 0, None
    if hit:
        die = str(form["damage"])
        immune = bool(theirs.get("crit_immune"))
        times = 1
        if bonus is not None and face >= int(form.get("threat", 20)):
            notes.append("critical threat")
            if immune:
                notes.append("immune to critical hits")
            else:
                confirm = dice.d(20, purpose=f"confirm#{step}", **key)
                rolls.append(confirm)
                if confirm.total != 1 and (confirm.total == 20 or confirm.total + total >= ac):
                    times = int(form.get("mult", 2))
                    notes.append(f"confirmed ×{times}")
        if cond == "set_vs_charge":  # doubled, and a critical's multiple on top (×3 and ×2 is ×4)
            times += 1
            notes.append("set vs. charge: double damage")
        damage, rolled = _damage(dice, die, times, f"damage#{step}", key)
        rolls.extend(rolled)
        if die != "0":  # a spell's touch deals nothing of its own, so nothing is added to it
            damage += (power * (2 if form.get("hands") == 2 else 1) + sum(e.dmg for e in attacker.effects)) * times
        sneak = str(mine.get("sneak") or "")
        if sneak and (flat or flanked):
            if immune:
                notes.append("immune to sneak attack")
            else:
                extra = dice.roll(sneak, purpose=f"sneak#{step}", **key)
                rolls.append(extra)
                damage += extra.total
                notes.append(f"sneak attack +{sneak}")
        if die != "0":
            damage = max(1, damage)
        if form.get("plus"):
            notes.append(f"plus {form['plus']}")
    after = replace(attacker, attacks_used=n, conditions=conditions)
    if charged_in is not None:
        after = replace(after, d20={**mine, "stance": {**stance, "charged": charged_in}})
    return Swing(hit, damage if hit else 0, face, tuple(notes), tuple(rolls), after, die)
