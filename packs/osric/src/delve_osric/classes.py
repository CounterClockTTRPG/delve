"""What OSRIC's classes can do and who may take them, in Delve's own words (DEL-304): each class's abilities by the
level it gains them (`FEATURES`, with `class_features.json`'s for the fighter, cleric, magic-user and thief), and each
ancestry's classes, multi-classes and level limits (`ANCESTRY_CLASSES`, `LEVEL_LIMITS`), after Player Guide
chapters 2 and 3. The numbers are the guide's; the words are ours.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from delve_osric.data import load, own

Feature = dict[str, Any]


def _f(level: int, name: str, summary: str) -> Feature:
    return {"level": level, "name": name, "summary": summary}


OWN_FEATURES: dict[str, list[Feature]] = {
    "assassin": [
        _f(1, "Assassination", "Against a surprised foe with vital parts: d100 at or under 50% + 5% per assassin level "
           "- 5% per 2 of the target's levels or HD kills it outright; a miss still deals weapon damage. Not against "
           "oozes, elementals, golems, zombies or the mightiest powers."),
        _f(1, "Backstab", "From right behind an unaware foe with a thief's melee weapon: +4 to hit and the damage die "
           "multiplied by level (before bonuses)."),
        _f(1, "Disguise", "Changes apparent height, build, ancestry and gender; onlookers get a small chance to see "
           "through it, more for a familiar face or a different ancestry."),
        _f(1, "Thief Skills", "Uses the assassin's own thief-skill table."),
        _f(4, "Hire Assassins", "May take assassins as henchmen and followers."),
        _f(8, "Hire Thieves", "May take thieves as well."),
        _f(9, "Special Languages", "With Intelligence 15+, one secret tongue (another alignment's, druids' or thieves' "
           "cant) per point above 14."),
        _f(9, "Brew Poison", "Makes its own poisons."),
        _f(12, "Hire Anyone", "May take any henchmen."),
        _f(12, "Read Scrolls", "Casts from scrolls: 1 on a d4 fails (the scroll survives); a cast spell has a 5% "
           "chance to go wrong, and the scroll is used up."),
        _f(14, "Guildmaster", "Leads a guild, after killing its guildmaster; many of its members leave."),
        _f(15, "Lord of Assassins", "Reached only by killing one of the lords of the profession."),
    ],
    "druid": [
        _f(1, "Druidic Spells", "Memorizes any druidic spell its slots allow, with extra slots for Wisdom 13+; no "
           "spellbook."),
        _f(1, "Druids' Cant", "Speaks the druids' secret tongue."),
        _f(1, "Fire and Lightning", "+2 on saves against fire and lightning."),
        _f(3, "Druid's Knowledge", "Knows any plant, animal or bird it sees, whose tracks it finds, and whether "
           "water, fruit or roots are safe."),
        _f(3, "Wilderness Movement", "Moves through undergrowth at full speed, leaving no trail if it wishes."),
        _f(7, "Fey Charm Immunity", "Fey creatures can't charm it."),
        _f(7, "Shapeshift", "Three times a day, into a natural animal or bird from mouse-size to twice its weight, "
           "keeping its own hit points and healing (3d10 at 7th, up to 7d10 at 14th); no spells while changed; in a "
           "fight it takes the round, like a spell of 0 segments."),
        _f(7, "Druidic Craft", "Brews healing and extra-healing potions on the calendar's ten brewing days, and writes "
           "scrolls of spells it can cast (a day and 50 gp per spell level, 20% to fail)."),
        _f(13, "Druidic Power", "May try to make permanent magic items, as the DM allows."),
    ],
    "illusionist": [
        _f(1, "Phantasmal Spells", "Learns phantasmal spells into a spellbook and memorizes them, as a magic-user does "
           "arcane ones."),
        _f(7, "Phantasmal Craft", "Brews potions (a laboratory, an alchemist, half the potion's value, a day per 50 gp), "
           "writes scrolls of spells it knows (a day and 50 gp per spell level, 20% to fail; 40% past 30 days a "
           "year) and recharges rods, staves and wands."),
        _f(14, "Phantasmal Power", "Knowing alter reality, may try to make magic items."),
    ],
    "monk": [
        _f(1, "Unarmoured Defence", "Wears no armour; its Armour Class improves with level (its level table)."),
        _f(1, "Weaponless Attack", "Strikes with its hands, more often and harder with level (its level table)."),
        _f(1, "Deadly Strike", "An unmodified roll 5 over the number needed stuns for 1d6 rounds, with a 5% chance to "
           "kill a foe of no more than 1 HD above the monk."),
        _f(1, "Thief Skills", "Uses the monk's own thief-skill table."),
        _f(1, "Deflect Missiles", "A save vs petrification turns aside a non-magical missile."),
        _f(1, "Evasion", "With Constitution 11+, a successful save against damage means no damage at all."),
        _f(2, "Weapon Damage", "+1 with weapons (Strength 15+; none below), rising by 1 every even level to +8 at 16th "
           "(+7 below Strength 15)."),
        _f(3, "Speak with Animals", "With Wisdom 15+ (at 5th otherwise)."),
        _f(4, "Controlled Fall", "Within reach of a wall a fall hurts 20ft less (10ft below Dexterity 15); 30ft at 6th; "
           "none at all at 13th within 10ft of a wall."),
        _f(4, "Mind-Shield", "Blocks mind reading 70% of the time (50% below Wisdom 15), 2% more each level."),
        _f(5, "Disease Immunity", "With Constitution 11+ (at 6th otherwise)."),
        _f(5, "Own Time", "Slow and haste don't affect it."),
        _f(6, "Catalepsy", "Once a day seems dead for 2 turns per level, poisons held off."),
        _f(7, "Heal Self", "Once a day 1d4+1 hp, one more each level after."),
        _f(8, "Speak with Plants", "Once a day, with Wisdom 15+ (at 9th otherwise)."),
        _f(9, "Mind Control Resistance", "50% to shake off charm, suggestion, geas and the like (40% below Wisdom 15), "
           "5% more each level; still a save after."),
        _f(11, "Poison Immunity", "With Constitution 11+; +2 on poison saves otherwise."),
        _f(11, "Monastery", "May found a monastery."),
        _f(12, "Geas and Quest Immunity", "Wholly immune to those two spells."),
        _f(13, "Harmonic Touch", "Once a week, with Wisdom 15+: a weaponless hit lets it end the life of a living "
           "creature of no more HD within a day per level; not undead, golems or those only magic weapons hurt."),
    ],
    "paladin": [
        _f(1, "Favoured Saves", "Saves on the paladin's own, kinder table."),
        _f(1, "Disease Immunity", "Never falls ill."),
        _f(1, "Curing Touch", "Cure disease by touch once a week (twice at 5th, thrice at 10th)."),
        _f(1, "Detect Evil", "At will, as the spell."),
        _f(1, "Protection from Evil", "Always about it in 10ft; it returns each round if dispelled."),
        _f(1, "Lay on Hands", "Once a day heals 2 hp per paladin level, itself included."),
        _f(2, "Heroic Assault", "Acts on segment 1 and attacks one foe per level that couldn't have 8+ hp from its "
           "Hit Dice, instead of its normal attacks."),
        _f(3, "Turn Undead", "As a good cleric two levels lower."),
        _f(4, "Holy Steed", "Summons a warhorse with double hit points and 2 better AC, once in ten years."),
        _f(7, "Melee Attack Combination (3/2)", "Three attacks over two rounds (segments 1 and 10 of the first); 2/1 "
           "with a specialised weapon."),
        _f(8, "Mighty Blow", "A to-hit need below zero adds that much to the damage."),
        _f(9, "Divine Spells", "Casts as a 1st-level cleric, a level more each paladin level to 8th at 16th; no "
           "Wisdom bonus slots."),
        _f(13, "Melee Attack Combination (2/1)", "Two attacks a round, in segments 1 and 10; 5/2 with a specialised "
           "weapon."),
    ],
    "ranger": [
        _f(1, "Alert and Stealthy", "-1 on its own surprise roll against others, +1 on theirs against it."),
        _f(1, "Tracker", "Follows a trail 90% of the time outdoors, 65% in towns and dungeons, as the DM adjusts."),
        _f(1, "Fell Handed", "+1 damage per level in melee against evil humanoids and giants."),
        _f(2, "Heroic Assault", "Acts on segment 1 and attacks one foe per level that couldn't have 8+ hp from its "
           "Hit Dice, instead of its normal attacks."),
        _f(8, "Melee Attack Combination (3/2)", "Three attacks over two rounds (segments 1 and 10 of the first)."),
        _f(8, "Mighty Blow", "A to-hit need below zero adds that much to the damage."),
        _f(8, "Druidic Spells", "Casts as a 1st-level druid, a level more every two ranger levels to 6th at 18th; no "
           "Wisdom bonus slots."),
        _f(9, "Arcane Spells", "Casts magic-user spells at its druid casting level, from a spellbook its mentor gives."),
        _f(15, "Melee Attack Combination (2/1)", "Two attacks a round, in segments 1 and 10."),
    ],
}  # fmt: skip


FEATURES_OWN_CLASSES = tuple(OWN_FEATURES)
"""The classes whose abilities are written here; `class_features.json` has the others'."""


def features(cls: str) -> list[Feature]:
    """A class's abilities by level: Delve's own for six classes, `class_features.json`'s for the other four."""
    return OWN_FEATURES.get(cls) or list(own(load("class_features")).get(cls, []))


ANCESTRY_CLASSES: dict[str, tuple[str, ...]] = {
    "dwarf": ("assassin", "cleric", "fighter", "thief", "fighter/thief"),
    "elf": (
        "assassin", "cleric", "fighter", "magic-user", "thief",
        "fighter/magic-user", "fighter/thief", "magic-user/thief", "fighter/magic-user/thief",
    ),
    "gnome": (
        "assassin", "cleric", "fighter", "illusionist", "thief",
        "fighter/illusionist", "fighter/thief", "illusionist/thief",
    ),
    "half-elf": (
        "assassin", "cleric", "druid", "fighter", "magic-user", "ranger", "thief",
        "cleric/fighter", "cleric/ranger", "cleric/magic-user", "fighter/magic-user", "fighter/thief",
        "cleric/fighter/magic-user", "fighter/magic-user/thief",
    ),
    "halfling": ("druid", "fighter", "thief", "fighter/thief"),
    "half-orc": (
        "assassin", "cleric", "fighter", "thief",
        "cleric/fighter", "cleric/thief", "cleric/assassin", "fighter/thief", "fighter/assassin",
    ),
    "human": ("assassin", "cleric", "druid", "fighter", "illusionist", "magic-user", "monk", "paladin", "ranger", "thief"),
}  # fmt: skip
"""Each ancestry's classes and multi-classes (Player Guide chapter 2). Humans don't multi-class; they may dual-class."""

Limit = int | str | Mapping[str, Any]
"""A level limit: a level, "unlimited", or a level by an ability: `{"by": "strength", "at": [[18, 9], [17, 8],
[0, 7]]}` is 9 at Strength 18+, 8 at 17 and 7 below."""


def _by(ability: str, *at: tuple[int, int]) -> dict[str, Any]:
    return {"by": ability, "at": [list(step) for step in at]}


LEVEL_LIMITS: dict[str, dict[str, Limit]] = {
    "dwarf": {"assassin": 9, "cleric": 8, "fighter": _by("strength", (18, 9), (17, 8), (0, 7)), "thief": "unlimited"},
    "elf": {
        "assassin": 10, "cleric": 7, "fighter": _by("strength", (18, 7), (17, 6), (0, 5)),
        "magic-user": _by("intelligence", (18, 11), (17, 10), (0, 9)), "thief": "unlimited",
    },
    "gnome": {
        "assassin": 8, "cleric": 7, "fighter": _by("strength", (18, 6), (0, 5)),
        "illusionist": {"by": "intelligence and dexterity", "rule": "7 if together 35+, 6 if both 17+, else 5"},
        "thief": "unlimited",
    },
    "half-elf": {
        "assassin": 11, "cleric": 5, "druid": 14, "fighter": _by("strength", (18, 8), (17, 7), (0, 6)),
        "magic-user": _by("intelligence", (18, 8), (17, 7), (0, 6)),
        "ranger": _by("strength", (18, 8), (17, 7), (0, 6)), "thief": "unlimited",
    },
    "halfling": {"druid": 6, "fighter": 4, "thief": "unlimited"},
    "half-orc": {"assassin": 15, "cleric": 4, "fighter": 10, "thief": _by("dexterity", (17, 7), (0, 6))},
    "human": {"assassin": 15, "druid": 14, "monk": 17},
}  # fmt: skip
"""The highest level an ancestry reaches in each single class; a class not named is unlimited. Assassins, druids and
monks top out for everyone, humans included (Player Guide chapter 2)."""


def level_limit(ancestry: str, cls: str, scores: Mapping[str, Any] | None = None) -> int | None:
    """The highest level `ancestry` reaches as `cls` with `scores` (by ability name or its first three letters); None
    when unlimited. A limit by abilities without their scores is the lowest of its steps."""
    limit = LEVEL_LIMITS.get(ancestry, {}).get(cls, "unlimited")
    if limit == "unlimited":
        return None
    if isinstance(limit, int):
        return limit
    if not isinstance(limit, Mapping):
        return None

    def score(name: str) -> int:
        raw = (scores or {}).get(name, (scores or {}).get(name[:3], 0))
        try:
            return int(str(raw).split("/")[0])
        except ValueError:
            return 0

    if "at" not in limit:  # the gnome illusionist
        intelligence, dexterity = score("intelligence"), score("dexterity")
        if intelligence + dexterity >= 35:
            return 7
        return 6 if intelligence >= 17 and dexterity >= 17 else 5
    have = score(limit["by"])
    return next(level for floor, level in limit["at"] if have >= floor)
