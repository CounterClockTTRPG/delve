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
from delve.rules.classic.combat import CLEAVE, NONLETHAL, AttackBlock, Combatant, CombatError, HitDie
from delve.rules.classic.life import with_condition
from delve.rules.d20 import Initiative, Swing
from delve_srd35.engine import attack_line, class_features, companions, defences, features, items, numbers, progress
from delve_srd35.reference import entry_refusal, family_refusal

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
"""Core's mark on a charger (as classic sets it): under 3.5, -2 AC until its next turn. Core clears it at the
charger's next turn under a d20 engine (`run_round`), so the mark alone says the penalty holds. The swing also keeps
the charge's round in the charger's `stance["charged"]`."""
NO_BONUS = {
    "rear": "3.5: no rear bonus — flanking needs an ally opposite",
    "fleeing": "3.5: a fleeing foe provokes — use provoke",
}
"""Core's attack conditions that give nothing under 3.5, and why."""
LAUNCHED = ("bow", "crossbow")
"""What a ranged weapon's id has when it fires ammunition rather than being thrown (a sling is the halflings' own)."""
HALFLING_THROWN = 1
"""The halflings' racial bonus on attack rolls with thrown weapons and slings."""
MOST_DODGE = 4
"""The most dodge bonus a flat-footed touch AC takes off besides Dex (see `_armour_class`)."""
EFFORT = ("light", "one-handed", "two-handed")
"""A melee weapon's effort, a step for each size of difference between it and its wielder."""


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


POOL_SPELL = "pool_spell"
"""The key in a party combatant's `d20` naming the spell it declared from its spells a day and has not yet cast: one
declared in setup_combat (round 1's action), or one of a round or more that carries over (`tools._combat_round`)."""

CLEAVED = "cleaved"
"""The key in a combatant's `d20` holding the round it last cleaved (Cleave is once a round)."""
KEPT = ("smite", POOL_SPELL, CLEAVED, class_features.RAGE_FATIGUE, NONLETHAL)
"""What a combatant made again keeps of its numbers besides its stance: a smite waiting for its swing, a pool spell
declared and not yet cast, the round of its last cleave, the mark of a rage's fatigue, its nonlethal damage."""


def _stance(old: Combatant) -> dict[str, Any]:
    """The stance and attacks of opportunity the combatant has in the fight already, or fresh ones, and what else it
    keeps (`KEPT`)."""
    kept = old.d20 or {}
    return {
        "stance": dict(kept.get("stance") or {"power_attack": 0, "defensive": False}),
        "aoo": dict(kept.get("aoo") or {"round": 0, "used": 0}),
        **{key: kept[key] for key in KEPT if key in kept},
    }


def _armed(combatant: Combatant, forms: list[dict[str, Any]], groups: list[int] | None = None) -> Combatant:
    """The combatant with its forms as attack blocks, still holding the one of the name it held (else the first).
    With `groups` (each form's full attack, `full_attack_groups`) a block's rate is its full attack's attacks, every
    form's count in it; without, its own form's count."""
    if not forms:
        return combatant
    held = combatant.attacks[combatant.weapon].name if 0 <= combatant.weapon < len(combatant.attacks) else ""
    counts = [int(f["count"]) for f in forms]
    rates = (
        [sum(n for n, g in zip(counts, groups, strict=True) if g == group) for group in groups] if groups else counts
    )
    blocks = tuple(
        AttackBlock(f["name"], f["damage"], f["damage"], rate=float(r)) for f, r in zip(forms, rates, strict=True)
    )
    index = next((i for i, b in enumerate(blocks) if b.name == held), 0)
    return replace(combatant, attacks=blocks, weapon=index)


def full_attack_groups(row: Mapping[str, Any] | None, forms: list[dict[str, Any]]) -> list[int] | None:
    """Each of the row's forms' full attack (`attack_line.alternatives` of `line_of`): the SRD's Full Attack, "all
    the creature's natural weapons (and any manufactured weapon it wields) ... in the order given"; None without a row
    or where the line's forms aren't `forms`' (a character's own)."""
    if row is None:
        return None
    groups = attack_line.alternatives(line_of(row))
    return groups if len(groups) == len(forms) else None


def full_attack(attacker: Combatant, mine: Mapping[str, Any]) -> list[tuple[dict[str, Any], int]]:
    """The attacker's full attack, each attack as (its form, which of the form's attacks it is: 1 for the first): the
    held form's attacks, then for a monster (a companion's or a wild shape's row too) the rest of its full attack's
    forms in the line's order (`full_attack_groups`)."""
    held = _form(attacker, dict(mine))
    forms = list(mine.get("attacks") or ())
    shape = mine.get("shape")
    row = class_features.monster_row(attacker) or (companions.monster(str(shape)) if shape else None)
    groups = full_attack_groups(row, forms) if held in forms else None
    order = [held]
    if groups is not None:
        at = forms.index(held)
        order += [f for i, f in enumerate(forms) if groups[i] == groups[at] and i != at]
    return [(form, k) for form in order for k in range(1, int(form.get("count", 1)) + 1)]


_SNEAK = re.compile(r"(?i)\bsneak attack\s*\+?\s*(\d+d\d+)")
"""A monster's sneak attack dice in its Special Attacks ("Sneak attack +2d6": the babau's)."""


def combatant_from_monster(row: Mapping[str, Any], combatant: Combatant, overrides: Mapping[str, Any]) -> Combatant:
    """The combatant core made from the row, with the row's 3.5 numbers and the row's id as `monster`. An `ac`
    override is its AC, a `dmg` override its first form's damage and a `size` override its size. Its sneak attack
    dice are its Special Attacks' ("Sneak attack +2d6", `_SNEAK`), none without. A family's parent
    row ("Red Dragon", "Fire Elemental") is refused, naming its variants (`reference.family_refusal`). A monster whose
    attack is "—" (the bat), and a template's or race entry's row (Ghost, Drow), which has no attack line, have no
    forms: their `no_attack` says why their swing is refused until the DM gives them an attack (update_combatant), a
    template's naming the monsters built on it (`reference.entry_refusal`)."""
    if (refusal := family_refusal(dict(row))) is not None:
        raise CombatError(refusal, hint="Name one variant, as in 'Young Red Dragon' or 'Large Fire Elemental'.")
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
    forms, unread = attack_line.read(line_of(row))
    if forms and overrides.get("dmg") is not None:
        forms[0] = {**forms[0], "damage": str(overrides["dmg"])}
    if forms and overrides.get("attacks_per_round") is not None:  # the held form's (`_armed` keeps it, else the first)
        held = combatant.attacks[combatant.weapon].name if 0 <= combatant.weapon < len(combatant.attacks) else ""
        at = next((i for i, f in enumerate(forms) if f["name"] == held), 0)
        forms[at] = {**forms[at], "count": max(1, int(float(overrides["attacks_per_round"])))}
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
        "sneak": sneak.group(1) if (sneak := _SNEAK.search(str(row.get("special_attacks") or ""))) else "",
        **_stance(combatant),
    }
    if "uncanny dodge" in str(row.get("special_qualities") or "").lower():
        d20["uncanny_dodge"] = True
    if "precise shot" in str(row.get("feats") or "").lower():
        d20["precise_shot"] = True
    if cleave := _cleave(str(row.get("feats") or "").lower()):
        d20["cleave"] = cleave
    if unread:
        d20["warnings"] = unread
    if not forms and not unread:
        d20["no_attack"] = (
            entry_refusal(dict(row))
            or f"{row.get('name')} has no attack (its full attack is {row.get('full_attack') or '—'!r})."
        )
    if (cr := progress.cr_for(dict(row))) is not None:
        d20["cr"] = cr
    if row.get("id"):
        d20["monster"] = str(row["id"])  # its row, whatever label it fights under (`class_features.monster_row`)
    d20.update(defences.of_row(row))  # DR, SR, regeneration, fast healing, resistances, immunities (DEL-389)
    size = combatant.size if overrides.get("size") is not None else SIZE_CODES[creature_size(row)]
    return replace(_armed(combatant, forms, full_attack_groups(row, forms)), ac=ac, size=size, d20=d20)


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


_CLEAVES = re.compile(r"\b(great )?cleave\b")


def _cleave(feats: str) -> str | None:
    """"great cleave" or "cleave" when the feats (a row's list, a sheet's ids) name one, Great Cleave first."""
    found = {m.group(0) for m in _CLEAVES.finditer(feats)}
    return "great cleave" if "great cleave" in found else "cleave" if found else None


def _dropped(target: Combatant, damage: int, nonlethal: int = 0) -> bool:
    """The hit makes the target drop: a monster to 0 or below (it dies there), anyone else below 0; or it knocks the
    target out (its nonlethal damage, with the hit's, more than its hit points after the hit, DEL-421), which it didn't
    before: a lethal hit below the nonlethal it had too."""
    floor = 0 if target.side == "enemy" else -1
    if target.hp > floor >= target.hp - damage:
        return True
    had, hp = int((target.d20 or {}).get(NONLETHAL) or 0), target.hp - damage
    return hp > floor and had <= target.hp and had + nonlethal > hp


def nonlethal_state(c: Combatant) -> str | None:
    """"staggered" at nonlethal damage (`d20["nonlethal"]`) equal to the current hit points, "unconscious" above them,
    else None (none, or less than the hit points)."""
    nonlethal = int((c.d20 or {}).get(NONLETHAL) or 0)
    if nonlethal <= 0 or nonlethal < c.hp:
        return None
    return "staggered" if nonlethal == c.hp else "unconscious"


def _feats(sheet: Sheet) -> list[tuple[str, str]]:
    """The sheet's feats as (id, slug of the choice)."""
    return [
        (f["id"], numbers.slug(f.get("choice") or "")) if isinstance(f, dict) else (str(f), "")
        for f in (sheet.d20 or {}).get("feats", ())
    ]


def _with(dice: str, bonus: int) -> str:
    if dice.isdigit():  # a Tiny 1d3's "1"
        return str(int(dice) + bonus)
    return f"{dice}{bonus:+d}" if bonus else dice


def _body(sheet: Sheet, reference: Any) -> tuple[str, str, int, int, int]:
    """The character's race id, its size (a word of `attack_line.SIZES`, "medium" when the race says none), its size
    modifier to attacks (the same as to AC: Large -1, Huge -2, …, the SRD's Table: Size Modifiers), and its Str and
    Dex modifiers."""
    race = numbers.race_named(reference, sheet.race) or {}
    size = str(race.get("size", "")).strip().lower()
    size = size if size in attack_line.SIZES else "medium"
    mods = (numbers.modifier(numbers.ability_score(sheet, a)) for a in ("str", "dex"))
    return str(race.get("id", "")), size, numbers.SIZE.get(size, {}).get("ac", 0), *mods


def iterations(bab: int) -> int:
    """A character's attacks a round with a manufactured weapon by its BAB: one to +5, two from +6, three from +11,
    four from +16."""
    return min(4, 1 + (bab - 1) // 5) if bab >= 1 else 1


def _iterative(form: dict[str, Any], bab: int) -> dict[str, Any]:
    """The weapon form with its count by the BAB (`iterations`), marked `iterative` where that is more than one."""
    count = iterations(bab)
    return {**form, "count": count, "iterative": True} if count > 1 else form


def attack_bonuses(form: Mapping[str, Any]) -> list[int]:
    """The form's attack bonus for each of its attacks a round, in the order taken (`iterative_penalty`)."""
    return [int(form["bonus"]) - iterative_penalty(form, n) for n in range(1, int(form.get("count", 1)) + 1)]


def iterative_penalty(form: Mapping[str, Any], n: int) -> int:
    """What comes off the `n`th attack this round on an iterative form: 5 for each attack after the first, the first
    counting once more for each extra attack of a monk's flurry (`flurry_extra`, which are at the full bonus)."""
    if not form.get("iterative"):
        return 0
    return 5 * max(0, n - 1 - int(form.get("flurry_extra", 0)))


def _weapon_form(sheet: Sheet, derived: dict[str, Any], reference: Any) -> tuple[dict[str, Any], list[str]]:
    """The form of the sheet's `weapon` (an unarmed strike without one), and a warning for a weapon the SRD's table
    hasn't. Its count is the attacks its BAB gives a round (`iterations`), `iterative` where that is more than one."""
    name = str((sheet.d20 or {}).get("weapon") or "")
    weapon = attack_line.weapon(name or "unarmed strike")
    race, body, size, strength, dex = _body(sheet, reference)
    bab = int(derived["bab"])
    if weapon is None:
        form = {"name": name.strip().lower(), "bonus": bab + strength + size,
                "damage": _with("1d6", strength), "threat": 20, "mult": 2, "count": 1, "touch": False, "hands": 1,
                "ranged": False}  # fmt: skip
        return _iterative(form, bab), [f"Unknown weapon '{name}': it swings as BAB + Str for 1d6 + Str."]
    feats = _feats(sheet)
    ids = {weapon["id"], numbers.slug(name)}
    # The monk's unarmed strike: its die by level (and size), and it strikes armed, as one proficient.
    monk = _unarmed_die(sheet, body) if weapon["kind"] == "unarmed" else None
    ranged = weapon["kind"] == "ranged"
    # The weapon's size: the one its name says ("large longsword"), else the wielder's own (a centaur's longbow is a
    # Large one). Each size of difference is -2 to hit, and moves a melee weapon's effort a step: light, one-handed,
    # two-handed, beyond which it can't be wielded (the SRD's Inappropriately Sized Weapons).
    made_for = attack_line.size_of(name) or body
    apart = attack_line.SIZES.index(made_for) - attack_line.SIZES.index(body)
    kind = weapon["kind"]
    warnings: list[str] = []
    unwieldable = ""
    if apart and kind in EFFORT:
        at = EFFORT.index(kind) + apart
        if 0 <= at < len(EFFORT):
            kind = EFFORT[at]
        else:
            unwieldable = (f"A {made_for} {weapon['name'].lower()} is too {'big' if apart > 0 else 'small'} for a "
                           f"{body} wielder: it can't be wielded (the SRD's Inappropriately Sized Weapons).")  # fmt: skip
    light = kind in ("light", "unarmed") or weapon["id"] in FINESSE
    finesse = light and not ranged and any(f == "weapon-finesse" for f, _ in feats)
    ability = dex if ranged else max(strength, dex) if finesse else strength
    # The War domain's granted power: proficiency and Weapon Focus with the deity's favoured weapon, which is taken to
    # be the weapon the cleric carries.
    war = "war" in (sheet.d20 or {}).get("domains", ())
    focus = war or any(f == "weapon-focus" and choice in ids for f, choice in feats)
    # Greater Weapon Focus +1 to hit, Weapon Specialization and Greater Weapon Specialization +2 damage each, with the
    # weapon chosen; each stacks with the one before it.
    chosen = {f for f, choice in feats if choice in ids}
    focus_more = int("greater-weapon-focus" in chosen)
    special = 2 * len(chosen & {"weapon-specialization", "greater-weapon-specialization"})
    nonproficient = not war and monk is None and not features.proficient(sheet, weapon, race)
    if "crossbow" in weapon["id"]:
        might = 0
    elif ranged and ("bow" in weapon["id"] or weapon["id"] == "sling"):
        might = min(strength, 0)
    elif kind == "two-handed" and strength > 0:
        might = strength * 3 // 2
    else:
        might = strength
    die, said = (monk, None) if monk else attack_line.sized(weapon, made_for)
    if said:
        warnings.append(said)
    thrown = ranged and (weapon["id"] == "sling" or not any(word in weapon["id"] for word in LAUNCHED))
    racial = HALFLING_THROWN if race == "halflings" and thrown else 0
    # The build's magic weapon of this kind (DEL-389 part 3): its enhancement to hit and damage ("They apply these
    # bonuses to both attack and damage rolls"), a masterwork one's +1 to hit "does not stack with their enhancement
    # bonus", alchemical silver's -1 damage; its materials, alignment and energies for the swing (`items`). A
    # launcher's are its ammunition's: "Ammunition fired from a projectile weapon with an enhancement bonus of +1 or
    # higher is treated as a magic weapon ... with an alignment gains the alignment of that projectile weapon".
    piece = items.piece(sheet, "weapon", weapon["id"])
    magic = items.weapon_numbers(piece, name, int(weapon["mult"]))
    plus = int(magic.get("enhancement", 0))
    # The arcane archer's enhance arrow: "every nonmagical arrow an arcane archer nocks and lets fly becomes magical,
    # gaining a +1 enhancement bonus" (+2 at 3rd … +5 at 9th). A launcher's enhancement and its ammunition's don't
    # stack: the higher counts.
    if (arrows := enhance_arrow(sheet, weapon)) > plus:
        plus = arrows
        magic = {**magic, "enhancement": arrows}
    # A composite bow's Strength rating: "you add your Strength bonus to damage, up to the maximum bonus indicated
    # for the bow", and "If your Strength bonus is less than the strength rating of the composite bow, you can't
    # effectively use it, so you take a -2 penalty on attacks with it."
    rating = (piece or {}).get("str_rating")
    unrated = 0
    if rating is not None and weapon["id"].endswith("-composite"):
        might = min(strength, int(rating))
        unrated = 2 * int(strength < int(rating))
    threat = int(weapon["threat"])
    # Keen "doesn't stack with any other effect that expands the threat range of a weapon (such as ... the Improved
    # Critical feat)": either doubles it, once.
    if magic.get("keen") or any(f == "improved-critical" and choice in ids for f, choice in feats):
        threat = 21 - 2 * (21 - threat)
    form = {
        "name": (name or "unarmed strike").strip().lower(),
        "bonus": bab + ability + size + int(focus) + focus_more - 4 * int(nonproficient) + racial - 2 * abs(apart)
        + (plus or int(bool(magic.get("masterwork")))) + int(numbers.shield_use(sheet, reference)["attack"]) - unrated,
        "damage": _with(die, might + special + plus - int(bool(magic.get("silver")))),
        "threat": threat,
        "mult": int(weapon["mult"]),
        "count": 1,
        "touch": False,
        "hands": 2 if kind == "two-handed" else 1,
        "ranged": ranged,
    }
    form |= {key: magic[key] for key in ("enhancement", "materials", "aligned", "plus", "burst", "against") if key in magic}
    if precise := precise_strike(sheet, weapon, kind):
        form["precise"] = precise
    if monk is not None:
        form["armed"] = True  # "A monk's attacks may be with either fist ... she is considered armed"
        if bypasses := _ki_strike(sheet):
            form["bypasses"] = bypasses
    if unwieldable:
        form["unwieldable"] = unwieldable  # its swing is refused, saying this (`swing`)
        warnings.append(unwieldable)
    return _iterative(form, bab), warnings


ARROWS = ("longbow", "shortbow")
"""The weapons whose ammunition is arrows (with their composite kinds), which enhance arrow makes magic."""


def enhance_arrow(sheet: Sheet, weapon: Mapping[str, Any]) -> int:
    """The arcane archer's enhance arrow at her level on a bow's arrows (`ARROWS`), its row's `by_level`; 0 for another
    weapon or without it."""
    if not str(weapon["id"]).startswith(ARROWS):
        return 0
    found = next((f for f in features.granted(sheet) if f["id"] == "enhance-arrow"), None)
    return int(found["value"] or 0) if found else 0


def precise_strike(sheet: Sheet, weapon: Mapping[str, Any], kind: str) -> str:
    """The duelist's precise strike dice on the weapon's form ("+1d6 ... with a light or one-handed piercing weapon",
    its row's `weapon`), when she uses no shield ("When making a precise strike, a duelist cannot attack with a weapon
    in her other hand or use a shield": the forms hold one weapon, so only the shield is known); "" otherwise."""
    found = next((f for f in features.granted(sheet) if f["id"] == "precise-strike"), None)
    if found is None or (sheet.d20 or {}).get("shield"):
        return ""
    wanted = next(r for r in features.rows(found["class"]) if r["id"] == "precise-strike").get("weapon") or {}
    piercing = str(wanted.get("type", "piercing")) in str(weapon.get("type", "")).lower()
    return str(found["value"] or "") if kind in wanted.get("kinds", ("light", "one-handed")) and piercing else ""


def natural_forms(sheet: Sheet, reference: Any, bab: int, size: int, strength: int) -> list[dict[str, Any]]:
    """A monster race's natural attacks (its row's line, `line_of`; a centaur's "2 hooves"), as the character's forms
    beside its weapon: its BAB + Str + size to hit, the row's die + its share of Str (`SHARES`: a sole attack 1½, a
    secondary one ½). Wielding a weapon makes them all secondary (the SRD: -5, -2 with Multiattack). None for a core
    race, and each natural weapon once."""
    race = numbers.race_named(reference, sheet.race) or {}
    row = companions.monster(str(race.get("id") or "")) if race.get("monster") else None
    if row is None:
        return []
    line = line_of(row)
    held = attack_line.weapon(str((sheet.d20 or {}).get("weapon") or ""))
    armed = held is not None and held["kind"] != "unarmed"
    penalty = 2 if "multiattack" in numbers.feat_ids(sheet) else 5
    out, seen = [], set()
    for f, role in zip(attack_line.parse(line), attack_line.roles(line), strict=True):
        die = re.match(r"\d+d\d+|\d+", str(f["damage"]))
        if not attack_line.natural(f) or f["name"] in seen or die is None or f["damage"] == "0":
            continue
        seen.add(f["name"])
        role = "secondary" if armed else role
        bonus = bab + strength + size - penalty * (role == "secondary")
        out.append({**f, "bonus": bonus, "damage": _with(die.group(), _share(strength, SHARES.get(role, Fraction(1))))})
    return out


def _unarmed_die(sheet: Sheet, size: str) -> str | None:
    """The die of the sheet's `unarmed-strike` feature (the monk's) at its level, for its size; None without one."""
    found = next((f for f in features.granted(sheet) if f["id"] == "unarmed-strike"), None)
    if found is None:
        return None
    row = next(r for r in features.rows(found["class"]) if r["id"] == "unarmed-strike")
    by_size = (row.get("by_size") or {}).get(size)
    level = sheet.levels.get(found["class"], 0)
    return str((features.at_level(by_size, level) if by_size else None) or found["value"])


def _ki_strike(sheet: Sheet) -> list[str]:
    """What the monk's unarmed strike counts as against damage reduction (ki strike): magic from 4th, lawful too from
    10th, adamantine too from 16th, the row's `bypasses`; none without it. Read by a monster's DR (part 3)."""
    found = next((f for f in features.granted(sheet) if f["id"] == "ki-strike"), None)
    if found is None:
        return []
    row = next(r for r in features.rows(found["class"]) if r["id"] == "ki-strike")
    return list(features.at_level(row.get("bypasses") or {}, sheet.levels.get(found["class"], 0)) or ())


def combatant_from_sheet(character: Character, combatant: Combatant, reference: Any) -> Combatant:
    """The combatant core made from the character, with the sheet's derived numbers. Its forms are its weapon's, and a
    caster's (`features.casters`) `touch` and `ranged touch` for its spells; a monk's flurry of blows on them while its
    stance flurries (`class_features.flurried`). Each negative level takes 1 off each save here and off each attack
    roll in the swing. A raging character (`CharacterState.d20["rage"]`) is marked `raging`, with its rage's bonuses
    by its level (`rage_bonus`: greater rage's from 11th). A fatigued one (on its
    state or its combatant) has 2 off its Str and Dex scores (an exhausted one 6) before any number is made (`class_features.tired`)."""
    sheet = character.sheet
    if (companion := companion_combatant(sheet, combatant)) is not None:
        return companion
    if penalty := class_features.penalty_of((*character.state.conditions, *combatant.conditions)):
        sheet = class_features.tired(sheet, penalty)
        character = replace(character, sheet=sheet)
    if class_features.WINDED in combatant.conditions:  # after a defensive stance, for the encounter
        sheet = class_features.winded(sheet)
        character = replace(character, sheet=sheet)
    derived = numbers.stored(sheet, reference)
    negative = int((sheet.d20 or {}).get("negative_levels", 0))
    form, warnings = _weapon_form(sheet, derived, reference)
    forms = [form]
    _, body, size, strength, dex = _body(sheet, reference)
    forms += natural_forms(sheet, reference, int(derived["bab"]), size, strength)
    named = features.casting(numbers.slug(sheet.cls))  # a sheet's class by its name casts from 1st, as its levels do
    if features.casters(sheet) or (named is not None and named["level"] == 1):
        bab = int(derived["bab"])
        spell = {"damage": "0", "threat": 20, "mult": 2, "count": 1, "touch": True, "hands": 1}
        forms += [{"name": "touch", "bonus": bab + strength + size, **spell, "ranged": False},
                  {"name": "ranged touch", "bonus": bab + dex + size, **spell, "ranged": True}]  # fmt: skip
    kept = _stance(combatant)
    if combatant.d20 is None and (carried := int((character.state.d20 or {}).get(NONLETHAL) or 0)):
        kept[NONLETHAL] = carried  # into the fight with its state's (DEL-421); made again in it, its own (`KEPT`)
    if kept["stance"].get("flurry"):
        forms = class_features.flurried(sheet, forms)
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
        **kept,
    }
    if derived.get("uncanny_dodge"):
        d20["uncanny_dodge"] = True
    if derived.get("improved_uncanny_dodge"):
        d20["improved_uncanny_dodge"] = int(derived["improved_uncanny_dodge"])
    if d20["sneak"] and (rogue := numbers.sneak_level(sheet, features.granted(sheet))):
        d20["sneak_level"] = rogue  # its rogue level against improved uncanny dodge
    if alignment := alignment_words(sheet.alignment):
        d20["alignment"] = alignment  # what smite evil and a holy weapon read (`class_features.evil`, `_against`)
    if (character.state.d20 or {}).get("rage"):
        d20["raging"] = True
        d20["rage_bonus"] = class_features.rage_numbers(sheet)
    if (character.state.d20 or {}).get("defending"):
        d20["defending"] = True
    if reduction := numbers.reduction(derived.get("dr")):
        d20["dr"] = reduction  # the list shape a monster row's has: "2/—" is [{"value": 2, "bypass": ["—"]}]
    if derived.get("favoured_enemy"):
        d20["favoured_enemy"] = dict(derived["favoured_enemy"])
    if any(f == "precise-shot" for f, _ in _feats(sheet)):
        d20["precise_shot"] = True
    if cleave := _cleave(" ".join(f.replace("-", " ") for f, _ in _feats(sheet))):
        d20["cleave"] = cleave
    if negative:
        d20["negative_levels"] = negative
    if warnings:
        d20["warnings"] = warnings
    code = combatant.size if body == "medium" else SIZE_CODES[body]
    made = replace(_armed(combatant, forms), ac=derived["ac"], size=code, d20=d20)
    return shaped(character, made, size)


def shaped(character: Character, made: Combatant, size: int) -> Combatant:
    """The character's combatant `made` in its wild shape (`CharacterState.d20["shape"]`), as it is without one. The
    form's attacks at the character's own BAB (each form's bonus less the monster's BAB, plus hers), its AC, touch and
    flat-footed AC (natural armour, size, its Dex: her armour melds into the form), size, Dex and type, all read from
    the monster row as `combatant_from_monster` reads them, less the monster's feats (`_without_feats`); her own hit
    points, BAB, base saves and Int, Wis and Cha. The form's Con and Dex move her Fortitude and Reflex saves and her
    initiative by the change in their modifiers."""
    shape = (character.state.d20 or {}).get("shape")
    row = companions.monster(str((shape or {}).get("monster") or ""))
    if not shape or row is None:
        return made
    mine = dict(made.d20 or {})
    form = combatant_from_monster(row, made, {})
    theirs = form.d20 or {}
    taken = companions.scores(row)
    con, dex = (numbers.modifier(taken[a]) - numbers.modifier(numbers.ability_score(character.sheet, a))
                for a in ("con", "dex"))  # fmt: skip
    rebased = int(mine["bab"]) - int(theirs["bab"])
    roles = _roles(row, theirs["attacks"])
    forms = [{**f, "bonus": f["bonus"] + rebased + _without_feats(row, f, character.sheet, role),
              "damage": _without_natural_attack(row, f, theirs["attacks"])}
             if f.get("bonus") is not None else f for f, role in zip(theirs["attacks"], roles, strict=True)]  # fmt: skip
    saves = dict(mine["saves"])
    saves["fort"] += con
    saves["ref"] += dex
    # Her own bonuses to AC that aren't armour, natural armour, Dex or size (`size`, her own size modifier): deflection,
    # insight, luck, sacred, dodge, a monk's, what her touch AC has besides 10, her Dex and her size. Flat-footed, less
    # what flat-footed loses beyond her Dex (her dodge).
    kept = int(mine["touch"]) - 10 - int(mine["dex"]) - size
    lost = int(mine["ac"]) - int(mine["flat_footed"])  # what flat-footed loses: Dex and dodge
    kept_flat = kept - (lost - max(int(mine["dex"]), 0)) if lost > 0 else kept
    d20 = {**mine, "attacks": forms, "ac": theirs["ac"] + kept, "touch": theirs["touch"] + kept,
           "flat_footed": theirs["flat_footed"] + kept_flat,
           "dex": theirs["dex"], "init_bonus": int(mine["init_bonus"]) + dex, "saves": saves, "type": theirs["type"],
           "crit_immune": theirs["crit_immune"], "shape": str(row["name"]).lower()}  # fmt: skip
    if theirs.get("warnings"):
        d20["warnings"] = [*mine.get("warnings", ()), *theirs["warnings"]]
    return replace(_armed(made, forms, full_attack_groups(row, forms)), ac=d20["ac"], size=form.size, d20=d20)


_FOCUS = re.compile(r"weapon focus\s*\(([^)]+)\)", re.IGNORECASE)
_IMPROVED = re.compile(r"improved natural (?:attack|weapon)(?:\s*\(([^)]+)\))?", re.IGNORECASE)
"""Improved Natural Attack, with its natural weapon or none (the tiger's rows write "Improved Natural Weapon")."""
MULTIATTACK = 3
"""What Multiattack gives a secondary natural attack: -2 instead of -5."""


def line_of(row: Mapping[str, Any]) -> str:
    """The attack line a monster row's forms are read from: its full attack, else (none read from it) its attack."""
    full = str(row.get("full_attack") or "")
    return full if attack_line.parse(full) else str(row.get("attack") or "")


def _roles(row: Mapping[str, Any], forms: list[dict[str, Any]]) -> list[str]:
    """The row's forms' parts in its full attack (`attack_line.roles` of `line_of`), one for each form ("primary" past
    the line's)."""
    roles = attack_line.roles(line_of(row))
    return [roles[at] if at < len(roles) else "primary" for at in range(len(forms))]


def _without_natural_attack(row: Mapping[str, Any], form: Mapping[str, Any], forms: list[dict[str, Any]]) -> str:
    """The form's damage without the monster's Improved Natural Attack, which a druid in its shape hasn't: one step
    less by Table: Increased Damage By Size, backwards (the rhinoceros's 2d6 gore is 1d8). The feat names its natural
    weapon ("Improved Natural Attack (gore)"); one without a name is the form's when the row has one natural weapon, or
    one of each when the row has it as often as it has natural weapons. A die the table doesn't reach stays."""
    feats = str(row.get("feats") or "")
    taken = [attack_line.singular(c.strip().lower()) if c else "" for c in _IMPROVED.findall(feats)]
    natural = {str(f["name"]) for f in forms if attack_line.weapon(str(f["name"])) is None and not f.get("touch")}
    name = attack_line.singular(str(form.get("name") or "").lower())
    uncovered = natural - set(taken)
    if name not in taken and not (name in uncovered and taken.count("") >= len(uncovered)):
        return str(form["damage"])
    found = re.fullmatch(r"(\d+d\d+)([+-]\d+)?", str(form["damage"]))
    if found is None or found.group(1) not in attack_line.STEP_DOWN:
        return str(form["damage"])
    return attack_line.STEP_DOWN[found.group(1)] + (found.group(2) or "")


def _without_feats(row: Mapping[str, Any], form: Mapping[str, Any], sheet: Sheet, role: str = "primary") -> int:
    """What comes off a form's attack bonus for the monster's feats, which a druid in its shape hasn't (polymorph
    gives the form's body, not its feats): -1 for its Weapon Focus with that attack; -3 on a secondary attack for its
    Multiattack (-5, not -2) unless she has the feat; and, when it has Weapon Finesse and she hasn't, its Dex modifier
    back to its Str one on a melee attack. Power Attack is no fixed number in a stat block's line: nothing to take."""
    feats = str(row.get("feats") or "")
    name = attack_line.singular(str(form.get("name") or "").lower())
    focused = {attack_line.singular(f.strip().lower()) for f in _FOCUS.findall(feats)}
    off = -1 if name in focused else 0
    mine = numbers.feat_ids(sheet)
    if role == "secondary" and re.search(r"(?i)\bmultiattack\b", feats) and "multiattack" not in mine:
        off -= MULTIATTACK
    if "weapon finesse" in feats.lower() and not form.get("ranged") and "weapon-finesse" not in mine:
        taken = companions.scores(row)
        strength, dex = numbers.modifier(taken["str"]), numbers.modifier(taken["dex"])
        off += strength - max(strength, dex)
    return off


def companion_combatant(sheet: Sheet, combatant: Combatant) -> Combatant | None:
    """A companion's combatant (`companions`): its monster row's, with its block's bonus Hit Dice, natural armour and
    Str and Dex on the numbers (`companions.deltas`); each attack's bonus moves by the BAB and the Str modifier (the
    Dex one for a ranged attack or with Weapon Finesse), its melee damage by its share of the Str modifier (the SRD's
    natural attacks: a sole one 1½ ×, a secondary one ½ ×, `strength_share`). The row's line has the secondary
    attack's -5 already. A mount counts as a magical beast. None for a sheet that isn't a companion's."""
    found = companions.of(sheet)
    if found is None:
        return None
    row, held = found
    made = combatant_from_monster(row, combatant, {})
    d = companions.deltas(row, held)
    d20 = {key: value for key, value in (made.d20 or {}).items() if key != "cr"}
    finesse = "weapon finesse" in str(row.get("feats") or "").lower()
    before, after = (numbers.modifier(companions.scores(row)["str"]),
                     numbers.modifier(companions.companion_scores(row, held)["str"]))  # fmt: skip
    roles = _roles(row, d20["attacks"])
    forms = []
    for at, f in enumerate(d20["attacks"]):
        ability = d["dex"] if f.get("ranged") or finesse else d["str"]
        bonus = None if f.get("bonus") is None else f["bonus"] + d["bab"] + ability
        share = strength_share(f, roles[at], before)
        more = _share(after, share) - _share(before, share)
        damage = f["damage"] if f.get("ranged") else companions.plus(f["damage"], more)
        forms.append({**f, "bonus": bonus, "damage": damage})
    d20.update(
        attacks=forms,
        bab=int(d20["bab"]) + d["bab"],
        ac=int(d20["ac"]) + d["ac"],
        touch=int(d20["touch"]) + d["touch"],
        flat_footed=int(d20["flat_footed"]) + d["flat_footed"],
        init_bonus=int(d20["init_bonus"]) + d["init"],
        dex=int(d20["dex"]) + d["dex"],
        saves={save: int(value) + d[save] for save, value in d20["saves"].items()},
        companion=held["feature"],
    )
    if held["feature"] == "special-mount":
        d20["type"] = companions.table_row("special-mount").get("kind_as", d20["type"])
    return replace(_armed(made, forms, full_attack_groups(row, forms)), ac=d20["ac"], d20=d20)


SHARES = {"sole": Fraction(3, 2), "secondary": Fraction(1, 2)}
"""A natural attack's share of the Str bonus on damage by its part (`attack_line.roles`); 1 for the others."""


def _share(modifier: int, share: Fraction) -> int:
    """The Str modifier's share, rounded down; a penalty counts whole (the SRD halves and multiplies a bonus)."""
    return int(modifier * share // 1) if modifier > 0 else modifier


def strength_share(form: Mapping[str, Any], role: str, modifier: int) -> Fraction:
    """The share of the Str modifier on the form's damage: its part's (`SHARES`), unless the line's damage bonus says
    another (the light horse's lone "2 hooves –2 melee (1d4+1)" with Str +2 is secondary: ½)."""
    found = re.fullmatch(r"\d+d\d+([+-]\d+)?", str(form.get("damage") or ""))
    wanted = SHARES.get(role, Fraction(1))
    if found is None:
        return wanted
    said = int(found.group(1) or 0)
    fits = [share for share in (wanted, Fraction(1), Fraction(3, 2), Fraction(1, 2)) if _share(modifier, share) == said]
    return fits[0] if fits else wanted


def companion_derived(sheet: Sheet, reference: Any) -> dict[str, Any] | None:
    """A companion's `Sheet.d20["derived"]`: the sheet's own (skills from its ranks) with the BAB, saves, AC, touch
    and flat-footed AC and initiative its combatant has, its speed from its row, and its block as `companion`. None
    for a sheet that isn't a companion's."""
    found = companions.of(sheet)
    if found is None:
        return None
    row, held = found
    made = companion_combatant(sheet, Combatant("companion", sheet.label or "", "party"))
    assert made is not None and made.d20 is not None
    d20 = made.d20
    out = numbers.derived(replace(sheet, race=""), reference)
    out.update({save: d20["saves"][save] for save in ("fort", "ref", "will")})
    out.update(bab=d20["bab"], ac=d20["ac"], touch=d20["touch"], flat_footed=d20["flat_footed"],
               init=d20["init_bonus"], companion=held, hit_dice=companions.deltas(row, held)["hd"])  # fmt: skip
    if (speed := numbers.signed(row.get("speed"))) is not None:
        out["speed"] = speed
    return out


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
        if not forms and mine.get("no_attack") and not block.name:  # core's own block on a monster without attacks
            raise CombatError(str(mine["no_attack"]), hint="Give it one with update_combatant if the DM rules it has.")
        return {"name": block.name, "bonus": int(mine.get("bab", 0)), "damage": block.damage_sm, "threat": 20,
                "mult": 2, "count": 1, "touch": False, "hands": 1, "ranged": False}  # fmt: skip
    if forms:
        return forms[0]
    raise ValueError(f"{attacker.name} has no attack to make.")


def held_form(combatant: Combatant) -> dict[str, Any] | None:
    """The form of the attack the combatant holds; None for one without 3.5 numbers or forms."""
    try:
        return _form(combatant, _numbers(combatant))
    except ValueError:
        return None


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


def _armour_class(target: Combatant, touch: bool, flat: bool) -> int:
    """The target's AC against the attack: touch, flat-footed, or both at once (touch less what flat-footed loses, its
    Dex and dodge bonuses); +2 while it fights defensively, -2 from its charge until its next turn. With uncanny dodge its
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
    charged = CHARGED in target.conditions
    return ac + 2 * bool(stance.get("defensive")) - 2 * charged


def _damage(dice: Dice, expression: str, times: int, purpose: str, key: dict[str, Any]) -> tuple[int, list[Roll]]:
    """The damage expression rolled `times` times and summed; a plain number counts `times` over with no roll."""
    if re.fullmatch(r"[+-]?\d+", expression):
        return int(expression) * times, []
    rolled = dice.roll(expression, purpose=purpose, times=times, **key)
    rolls = rolled if isinstance(rolled, list) else [rolled]
    return sum(r.total for r in rolls), rolls


def _favoured(mine: Mapping[str, Any], target: Combatant) -> int:
    """The attacker's favoured enemy bonus against the target: the highest of those its type or a subtype names (they
    don't stack). A monster's subtypes are its row's (`class_features.monster_row`: by its `monster` id, else by the
    name it was added under)."""
    chosen = mine.get("favoured_enemy") or {}
    if not chosen:
        return 0
    theirs = target.d20 or {}
    kinds = {str(theirs.get("type") or "").lower()}
    if (row := class_features.monster_row(target)) is not None:
        kinds |= {creature_type(row), *(str(sub).strip().lower() for sub in row.get("subtypes") or ())}
    kinds.discard("")
    return max((int(bonus) for enemy, bonus in chosen.items() if enemy in kinds), default=0)


ALIGNMENTS = {"lg": "lawful good", "ln": "lawful neutral", "le": "lawful evil", "ng": "neutral good",
              "n": "neutral", "tn": "neutral", "ne": "neutral evil", "cg": "chaotic good", "cn": "chaotic neutral",
              "ce": "chaotic evil"}  # fmt: skip
"""A sheet's alignment by its letters ("CE"), in the SRD's words."""


def alignment_words(said: str) -> str:
    """A sheet's alignment in words: "CE" is "chaotic evil", "Lawful Good" "lawful good"; "" for none."""
    text = " ".join(str(said or "").lower().split())
    return ALIGNMENTS.get(text.replace(" ", "").replace("-", ""), text)


def _against(
    dice: Dice, bane: Mapping[str, Any], target: Combatant, purpose: str, key: dict[str, Any]
) -> tuple[Roll | None, str]:
    """A holy (unholy, axiomatic, anarchic) weapon's "extra 2d6 points of damage against all of evil alignment": rolled
    at a target whose alignment has the word (its `d20["alignment"]`, a character's from its sheet, else its monster
    row's: "Always chaotic evil"), and not at one whose hasn't; a note for the DM at a target with none, or with
    "any" alignment (the row's "Any" or "Any alignment"; "Any evil" says enough)."""
    ability, extra, alignment = str(bane["ability"]), str(bane["dice"]), str(bane["alignment"])
    an = f"{'an' if alignment[0] in 'aeiou' else 'a'} {alignment}"
    said = str((target.d20 or {}).get("alignment") or (class_features.monster_row(target) or {}).get("alignment") or "")
    main = said.split("(")[0].strip().lower()
    if not main or re.fullmatch(r"(?:always |usually |often )?any(?: alignment)?", main):
        return None, f"{ability}: +{extra} against {an} target: the DM's (not rolled)"
    if alignment not in re.findall(r"[a-z]+", said.split("(")[0].lower()):
        return None, f"{ability}: no +{extra} ({said.lower() or 'no alignment'})"
    rolled = dice.roll(extra, purpose=purpose, **key)
    return rolled, f"{ability}: +{extra} against {an} target ({rolled.total})"


def swing(attacker: Combatant, target: Combatant, condition: str, dice: Dice, combat_round: int) -> Swing:
    """One attack: a d20 + the form's bonus (−4 fighting defensively, − Power Attack, − 1 per negative level, + the
    attacker's effects' to-hit, +2 flanking, +2 charging, -4 shooting or throwing into melee without Precise Shot)
    against the target's AC (`_armour_class`, less the target's effects' classic `ac`). A natural 1 misses and a natural
    20 hits. A hit on the form's threat range is a critical threat; a second roll against the same AC confirms it, and
    the damage is rolled `mult` times (Power Attack's and the effects' damage too, sneak dice not). A target immune to
    criticals takes the damage once. Power Attack adds its number to melee damage, twice that two-handed, and isn't used
    with a light weapon; only a melee attack flanks; a rogue's sneak dice come once on a flat-footed or flanked target
    that isn't immune (one with uncanny dodge, not immobilized, keeps its Dex and so isn't open to them flat-footed);
    set against a charge, the damage is doubled; a ranger's favoured enemy bonus (`_favoured`) adds to the damage as
    Power Attack does, and so does a paladin's waiting smite (with its Cha to hit) on an evil target, spent on a melee
    swing either way (`class_features.smite`), and a raging attacker's Str by the attack
    (`class_features.rage_strength`, only while its Rage effect is on: past it, a note to end the rage); a monk's flurry
    is noted; each attack after the first this round on an iterative form is 5 lower than the one before
    (`iterative_penalty`; an attack of opportunity is at the full bonus); a hit deals at least 1 (a spell's touch form
    deals none, and nothing is added to it), then the target's damage reduction takes its number off, to no less than 0,
    unless the form overcomes it (`defences.reduce`). The form's energy dice ("plus 2d6 fire") are rolled once, not
    multiplied, and added after the DR, less the target's resistance to that energy, none if it is immune
    (`defences.resisted`); a target that regenerates takes the hit as nonlethal damage but for what stops its
    regeneration (`defences.regenerated`: `Swing.nonlethal`, not in `damage`, DEL-421), and a note of how.
    A charger is marked `charging_ac_penalty`; a rear or fleeing attack gets no bonus, with a note why. A melee hit
    that drops its target (`_dropped`, by the target's hit points as given) earns an extra attack (`Swing.extra_attack`)
    to an attacker with Cleave, once a round, or Great Cleave. The extra attack is a swing with the condition `cleave`
    (core's `CLEAVE`), with no other condition's bonus: Cleave's is spent on it (its round kept in `d20["cleaved"]`),
    and it is refused to one without Cleave or whose Cleave is spent this round; it is at the attacker's step as given
    (the caller's: the dropping attack's), its rolls under purposes of their own (`attack#<n>:cleave`)."""
    mine = _numbers(attacker)
    theirs = target.d20 or {}
    form = _form(attacker, mine)
    if form.get("unwieldable"):
        raise CombatError(str(form["unwieldable"]), hint="Give the character a weapon of its size with set_build.")
    n = attacker.attacks_used + 1
    # An attack of opportunity (`provoke`) rolls under purposes of its own, so the attacker's own attacks this round
    # don't find its rolls.
    step = "aoo" if (mine.get("aoo") or {}).get("swinging") else n
    # The nth attack of the full attack (an attack of opportunity is the held form's first): its form, and which of
    # that form's attacks it is, for the iterative penalty.
    sequence = full_attack(attacker, mine) if step != "aoo" else []
    form, k = sequence[n - 1] if n <= len(sequence) else (form, n if step != "aoo" else 1)
    key = {"actor": attacker.id, "target": target.id, "combat_round": combat_round}
    stance = mine.get("stance") or {}
    charged_in: int | None = None
    melee = not form.get("ranged")
    power = int(stance.get("power_attack", 0)) if melee else 0
    bonus = form["bonus"]
    notes: list[str] = []
    if form is not _form(attacker, mine):
        notes.append(f"full attack: {form['name']}")
    held = attack_line.weapon(str(form.get("name") or ""))
    if power and held is not None and held["kind"] in ("light", "unarmed"):
        power = 0
        notes.append("Power Attack: not with a light weapon")
    rolls: list[Roll] = []
    cond = condition.strip().lower()
    flanking = cond in FLANKED or any(c in target.conditions for c in FLANKED)
    # Improved uncanny dodge: "can no longer be flanked ... The exception to this defense is that a rogue at least
    # four levels higher than the [target] can flank him", its classes' levels stacked
    # (`numbers.improved_uncanny_dodge`).
    guarded = theirs.get("improved_uncanny_dodge")
    if flanking and guarded is not None and int(mine.get("sneak_level", 0)) < int(guarded) + 4:
        flanking = False
        notes.append(f"improved uncanny dodge: can't be flanked (rogue level {int(mine.get('sneak_level', 0))}, "
                     f"needs {int(guarded) + 4})")  # fmt: skip
    flanked = flanking and melee
    conditions = attacker.conditions
    caught = flat_footed(attacker, target, combat_round)
    flat = caught and not keeps_dex(target)  # flat-footed and without its Dex bonus to AC
    if caught:
        notes.append("flat-footed")
    if caught and not flat:
        notes.append("uncanny dodge: keeps Dex to AC")
    ac = _armour_class(target, bool(form.get("touch")), flat)
    # A core effect's `ac` keeps its classic sign (ruling R10): +N is N easier to hit ("held … ac 4"), -1 a ring of
    # protection's 1 harder.
    # The defensive stance's AC is a dodge bonus, lost with the Dex bonus when flat-footed (SRD).
    effect_ac = sum(e.ac for e in target.effects if not (flat and e.name == class_features.STANCE_EFFECT))
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
    cleave = mine.get("cleave")
    cleaved = mine.get(CLEAVED)
    tag = f"{step}:cleave" if cond == CLEAVE else step  # the dropping attack's step, under rolls of its own
    if cond == CLEAVE:  # the extra attack itself: it spends Cleave's once a round
        if not cleave:
            raise CombatError(f"{attacker.name} has no Cleave.", hint="Leave condition cleave out.")
        if cleave == "cleave" and cleaved == combat_round:
            raise CombatError(f"{attacker.name} has cleaved this round already: Cleave is once a round.")
        cleaved = combat_round if cleave == "cleave" else cleaved
        notes.append(f"{cleave}: the extra attack")
    if form.get("flurry") is not None:
        notes.append(f"flurry of blows ({int(form['flurry']):+d})")
    # An attack of opportunity is at the full bonus: it isn't one of the attacker's attacks this round.
    iterative = 0 if step == "aoo" else iterative_penalty(form, k)
    if iterative:
        situational -= iterative
        notes.append(f"iterative attack (-{iterative})")
    smite_hit, smite_damage, smitten, smite_spent = class_features.smite(mine, form, target)
    raging_hit, raging_damage, raged = class_features.rage_strength(mine, form, attacker.effects)
    standing_hit, standing_damage, stood = class_features.stance_strength(mine, form, attacker.effects)
    situational += smite_hit + raging_hit + standing_hit
    notes += [note for note in (smitten, raged, stood) if note]
    if bonus is None:  # a swarm's attack hits whoever is in it, with no roll
        hit, face, total = True, 0, 0
    else:
        total = int(bonus) - 4 * bool(stance.get("defensive")) - power - int(mine.get("negative_levels", 0))
        total += sum(e.to_hit for e in attacker.effects) + situational
        roll = dice.d(20, purpose=f"attack#{tag}", **key)
        rolls.append(roll)
        face = roll.total
        hit = face != 1 and (face == 20 or face + total >= ac)
    damage, nonlethal, die = 0, 0, None
    if hit:
        die = str(form["damage"])
        immune = bool(theirs.get("crit_immune"))
        times = 1
        critical = False
        if bonus is not None and face >= int(form.get("threat", 20)):
            notes.append("critical threat")
            if immune:
                notes.append("immune to critical hits")
            else:
                confirm = dice.d(20, purpose=f"confirm#{tag}", **key)
                rolls.append(confirm)
                if confirm.total != 1 and (confirm.total == 20 or confirm.total + total >= ac):
                    times = int(form.get("mult", 2))
                    critical = True
                    notes.append(f"confirmed ×{times}")
        if cond == "set_vs_charge":  # doubled, and a critical's multiple on top (×3 and ×2 is ×4)
            times += 1
            notes.append("set vs. charge: double damage")
        damage, rolled = _damage(dice, die, times, f"damage#{tag}", key)
        rolls.extend(rolled)
        favoured = _favoured(mine, target) if die != "0" else 0
        if favoured:
            notes.append(f"+{favoured} favoured enemy")
        if die != "0":  # a spell's touch deals nothing of its own, so nothing is added to it
            added = power * (2 if form.get("hands") == 2 else 1) + sum(e.dmg for e in attacker.effects) + favoured
            added += smite_damage + raging_damage + standing_damage
            damage += added * times
        sneak = str(mine.get("sneak") or "")
        if sneak and (flat or flanked):
            if immune:
                notes.append("immune to sneak attack")
            else:
                extra = dice.roll(sneak, purpose=f"sneak#{tag}", **key)
                rolls.append(extra)
                damage += extra.total
                notes.append(f"sneak attack +{sneak}")
        # The duelist's precise strike: its dice once, not multiplied; "Any creature that is immune to critical hits is
        # not vulnerable to a precise strike".
        if (precise := str(form.get("precise") or "")) and die != "0":
            if immune:
                notes.append("immune to precise strike")
            else:
                extra = dice.roll(precise, purpose=f"precise#{tag}", **key)
                rolls.append(extra)
                damage += extra.total
                notes.append(f"precise strike +{precise}")
        for bane in form.get("against") or () if die != "0" else ():  # a spell's touch has none
            extra, said = _against(dice, bane, target, f"against#{tag}", key)
            if extra is not None:
                rolls.append(extra)
                damage += extra.total
            notes.append(said)
        if die != "0":
            damage = max(1, damage)
            damage, said = defences.reduce(damage, attacker, form, target)
            notes += said
        energies, rest = defences.energy(form)
        dealt: dict[str, int] = {}
        for at, (dice_said, kind) in enumerate(energies):
            amount, rolled = _damage(dice, dice_said, 1, f"energy#{tag}" + (f".{at + 1}" if at else ""), key)
            rolls.extend(rolled)
            taken, how = defences.resisted(kind, amount, target)
            dealt[kind] = dealt.get(kind, 0) + taken
            damage += taken
            notes.append(defences.rider_said(f"plus {dice_said} {kind}", amount, taken, how))
        # A burst weapon's "extra 1d10 points of fire damage on a successful critical hit" (2d10 at x3, 3d10 at x4):
        # once, as the energy is, and less the target's resistance.
        for at, (dice_said, kind) in enumerate(defences.energy({"plus": form.get("burst")})[0] if critical else ()):
            amount, rolled = _damage(dice, dice_said, 1, f"burst#{tag}" + (f".{at + 1}" if at else ""), key)
            rolls.extend(rolled)
            taken, how = defences.resisted(kind, amount, target)
            dealt[kind] = dealt.get(kind, 0) + taken
            damage += taken
            notes.append(defences.rider_said(f"plus {dice_said} {kind} (critical)", amount, taken, how))
        if rest:
            notes.append(f"plus {rest}")
        has = defences.overcomes(attacker, form)
        if str(form.get("name")) == "flask of oil":  # a thrown flask's burning oil is fire (core's `MISSILES`)
            has.add("fire")
        damage, nonlethal, regenerates = defences.regenerated(target, has, dealt, damage)
        if regenerates is not None:
            notes.append(regenerates)
    after = replace(attacker, attacks_used=n, conditions=conditions)
    if charged_in is not None:
        after = replace(after, d20={**mine, "stance": {**stance, "charged": charged_in}})
    if smite_spent:  # on a melee swing, whether it hit and whether the target was evil
        after = replace(after, d20={k: v for k, v in (after.d20 or mine).items() if k != "smite"})
    if cleaved != mine.get(CLEAVED):
        after = replace(after, d20={**(after.d20 or mine), CLEAVED: cleaved})
    # The extra attack it earns; Cleave's is spent when it is made (condition cleave), not when it is offered.
    may = cleave == "great cleave" or (cleave == "cleave" and cleaved != combat_round)
    extra = cleave if hit and melee and may and _dropped(target, damage, nonlethal) else None
    return Swing(hit, damage if hit else 0, face, tuple(notes), tuple(rolls), after, die, extra, nonlethal=nonlethal)
