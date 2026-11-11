"""OSRIC's numbers for the classic engine (`RuleTables`), from its tables in `data/`.

OSRIC's own ways are the engine's options (DEL-303): monsters save on their own table by Hit Dice, initiative is a d6 a
side without weapon speed, morale a d100 against a percentage, and a load keeps a share of the movement rate.
"""

from __future__ import annotations

from typing import Any

from delve.rules.classic.encumbrance import EncumbranceTables
from delve.rules.classic.overland import TravelRates
from delve.rules.classic.tables import FightRules, Healing, LevelDrain, RuleTables, SaveBands
from delve_osric.data import CLASSES, load, own

SAVE_TYPES = (
    "death_paralysis_poison",
    "petrification_polymorph",
    "aimed_magic_items",
    "breath_weapons",
    "spells",
)
"""OSRIC's five saving throws, in the order its class tables print them."""

SAVE_NAMES = {
    "death_paralysis_poison": "Death, Paralysis, Poison",
    "petrification_polymorph": "Petrification, Polymorph",
    "aimed_magic_items": "Aimed Magic Items",
    "breath_weapons": "Breath Weapons",
    "spells": "Spells",
}

SAVE_ALIASES = {
    **{kind: kind for kind in SAVE_TYPES},
    **dict.fromkeys(("para", "paralysis", "poison", "death", "dpp"), "death_paralysis_poison"),
    **dict.fromkeys(("poly", "polymorph", "petrify", "petrification"), "petrification_polymorph"),
    **dict.fromkeys(("rsw", "rod", "staff", "wand", "aimed", "magic items"), "aimed_magic_items"),
    **dict.fromkeys(("breath", "bw", "breath weapon"), "breath_weapons"),
    **dict.fromkeys(("spell", "magic"), "spells"),
    # A sheet made under AD&D 2e keeps its saves under 2e's names: they are the same five.
    "paralysis_poison_death": "death_paralysis_poison",
    "rod_staff_wand": "aimed_magic_items",
    "petrify_polymorph": "petrification_polymorph",
    "breath_weapon": "breath_weapons",
}

NONPROFICIENT = {
    "assassin": 3,
    "cleric": 3,
    "druid": 4,
    "fighter": 2,
    "illusionist": 5,
    "magic-user": 5,
    "monk": 3,
    "paladin": 2,
    "ranger": 2,
    "thief": 3,
}
"""Each class's to-hit penalty with a weapon it isn't proficient in (Player Guide §1.3, each class's table)."""

CASTER_CLASSES = {
    "illusionist": ("illusionist",),
    "druid": ("druid", "ranger"),
    "cleric": ("cleric", "paladin"),
    "magic-user": ("magic-user", "magic user", "mage", "wizard"),
}
"""Each spell list and the classes that cast from it, a specialist's list first."""

REACTION_BANDS = (
    (5, "very hostile", "The NPC or monster attacks, or refuses outright and means harm."),
    (25, "hostile", "Hostile: it attacks unless plainly outmatched, or turns against the party soon."),
    (45, "unfavourable", "Unfavourable: likely to attack, and inclined against the party."),
    (55, "neutral", "Neutral: undecided; it waits to see what the party does."),
    (75, "favourable", "Favourable: inclined to help, or to let the party be."),
    (95, "friendly", "Friendly: well disposed, and helpful within reason."),
)
"""Player Guide Table 1.6.2.8A's bands of a d100 reaction, in Delve's words."""

TURNING_COLUMNS = ("1", "2", "3", "4", "5", "6", "7", "8", "9-13", "14-18", "19+")
"""The cleric levels of Player Guide Table 1.6.5A."""

LOAD_STEP = 40
"""OSRIC's encumbrance bands (Player Guide Table 1.5.3.3A): each 40 lb over the Strength allowance slows by a step."""


LOAD_FRACTIONS = (1.0, 0.75, 0.5, 0.25, 0.0)
"""The share of the movement rate each load band keeps: full, three-quarters, half, a quarter, none."""


MELEE_RATES = {
    "fighter": ((1, 1.0), (7, 1.5), (13, 2.0)),
    "paladin": ((1, 1.0), (7, 1.5), (13, 2.0)),
    "ranger": ((1, 1.0), (8, 1.5), (15, 2.0)),
}
"""The Melee Attack Combination of each class (Player Guide §1.3: fighter and paladin 3/2 at 7th and 2/1 at 13th,
ranger at 8th and 15th)."""

SPECIALISED_MELEE_RATES = ((1, 1.5), (7, 2.0), (13, 2.5))
"""Player Guide Table 1.3.13A: the melee attacks with a specialised weapon, by the specialist's level."""


def bonus_spells() -> dict[int, dict[int, int]]:
    """Player Guide §1.3.2: a cleric's or druid's extra spells for high Wisdom, cumulative, by score."""
    rows = own(load("spellcasting")["wisdom_bonus_cleric_spells"])
    return {int(score): {int(level): int(n) for level, n in row.items()} for score, row in rows.items()}


def monster_saves(kind: str) -> SaveBands:
    """Gamemaster Guide Table 2.1.3A or B: a monster's saves by Hit Dice, `intelligent` or `non_intelligent`. The
    bands are up to their top; under 1 HD is level 0."""
    rows = load("monster_saves")[f"table_{kind}"]
    return tuple(
        (int(row["hd_max"]) if row["hd_max"] >= 1 else 0, tuple(int(row[save]) for save in SAVE_TYPES)) for row in rows
    )


def class_saves(cls: str) -> SaveBands:
    """A class's saving throws by level, from its table in `classes.json`."""
    rows = load("classes")[cls]["saving_throws"]
    return tuple((int(row["max"]), tuple(int(row[kind]) for kind in SAVE_TYPES)) for row in rows)


def _strength_bands() -> tuple[dict[int, tuple[int, int, int, int]], tuple[tuple[int, int], ...]]:
    """The load caps of each Strength (its allowance, then a band each 40 lb over it), and of exceptional Strength."""
    strength = load("ability_scores")["strength"]
    caps = {
        int(score): _caps(int(row["weight_allowance"])) for score, row in strength["normal"].items() if score.isdigit()
    }
    exceptional = tuple((int(row["pct_max"]), int(row["weight_allowance"])) for row in strength["exceptional"])
    return caps, exceptional


def _caps(allowance: int) -> tuple[int, int, int, int]:
    return (allowance, allowance + LOAD_STEP, allowance + 2 * LOAD_STEP, allowance + 3 * LOAD_STEP)


def _survival(column: str) -> dict[int, int]:
    return {int(score): int(row[column]) for score, row in own(load("ability_scores")["constitution"]).items()}


def tables() -> RuleTables:
    """OSRIC's `RuleTables`."""
    str_bands, str_pct = _strength_bands()
    return RuleTables(
        save_types=SAVE_TYPES,
        save_names=SAVE_NAMES,
        save_aliases=SAVE_ALIASES,
        save_short=("para", "poly", "rsw", "breath", "spell"),
        saves_by_group={cls: class_saves(cls) for cls in CLASSES},
        class_groups={**{cls: cls for cls in CLASSES}, "magic user": "magic-user", "mage": "magic-user"},
        saves_source="OSRIC class table",
        monster_save_group="fighter",
        monster_saves={kind: monster_saves(kind) for kind in ("intelligent", "non_intelligent")},
        shock=_survival("system_shock_pct"),
        shock_default=70,
        resurrect=_survival("resurrection_pct"),
        resurrect_default=75,
        morale_roll="1d100",
        initiative_die=6,
        weapon_speed_in_initiative=False,
        reaction_roll="1d100",
        reaction_bands=REACTION_BANDS,
        reaction_top=("very friendly", "Very friendly: eager to help, and may even join the party."),
        disposition_step=4,
        reputation_step=5,
        surprise_die=6,
        surprise_on=2,
        encounter_checks={
            # Gamemaster Guide §2.4: a dungeon is checked every third turn; the wilderness twice a day, and at night.
            "dungeon": {"die": 6, "threshold": 1, "interval_minutes": 30},
            "wilderness": {"die": 12, "threshold": 1, "interval_minutes": 480},
            "road": {"die": 12, "threshold": 1, "interval_minutes": 480},
            "urban": {"die": 12, "threshold": 1, "interval_minutes": 240},
        },
        encounter_check_default={"die": 12, "threshold": 1, "interval_minutes": 480},
        turning_level_columns=TURNING_COLUMNS,
        class_aliases={},
        travel=TravelRates(
            horse_mv=24,  # a riding horse's 240ft, in the movement rate the engine counts in
            cart_miles_per_day=12,
            river_boat_mph=2,
            river_current_mph=1,
            river_hours=10,
            ship_mph=3,
            ship_hours=12,
        ),
        caster_classes=CASTER_CLASSES,
        encumbrance=EncumbranceTables(
            item_aliases={},
            item_weights={},
            str_bands=str_bands,
            str_pct_allowance=str_pct,
            pct_stride=LOAD_STEP,
            band_penalties={"light": 0, "moderate": -3, "heavy": -6, "severe": -9, "overloaded": -12},
            band_fractions=dict(
                zip(("light", "moderate", "heavy", "severe", "overloaded"), LOAD_FRACTIONS, strict=True)
            ),
        ),
        nonproficient=NONPROFICIENT,
        mounts={},
        mount_fly={},
        # Player's Guide §1.6.7: the lowest XP of the new level, a random class of equal highest levels, and death
        # below 1st level.
        level_drain=LevelDrain(xp="floor", tie="random", zero_level=False),
        # Player Guide: a natural 1 or 20 isn't automatic on a to-hit roll, and a natural 20 counts +5 for the
        # table's repeated 20s (1.4.2.4A); a fleeing foe is attacked at +4, even by one who has attacked (1.6.2.3);
        # the unconscious bleed from 0 and die of any more damage (1.6.6).
        fight=FightRules(
            automatic_naturals=False,
            natural_twenty=25,
            fleeing_bonus=4,
            fleeing_attack_free=True,
            bleed_from_zero=True,
            unconscious_slain_by_damage=True,
        ),
        # §1.6.6.1: 1 hp a day; a Constitution penalty delays it, a bonus adds over the second week; 4 weeks heal all.
        healing=Healing(
            per_day=1, bed_rest_per_day=None, con_bonus="second_week", con_penalty_delays=True, full_after_days=28
        ),
        save_natural_one_fails=True,
        # Table 1.6.5A: a D* affects 1d6+6; fiends come one or two at a time.
        turning_counts={"number": ("2d6", None), "T": ("2d6", None), "D": ("2d6", None), "D*": ("1d6+6", None)},
        turning_few={"fiend": "1d2"},
        initiative_mode="side",
        melee_rates=MELEE_RATES,
        specialised_melee_rates=SPECIALISED_MELEE_RATES,
        strength_damage=True,
        bonus_spells=bonus_spells(),
        bonus_spell_classes=("cleric", "druid"),
        xp_bonus=True,
    )


TABLES = tables()


def spell_list(caster_class: str) -> str:
    """The spell list (`classes.json`'s `class` of a spell) a class's word names: 'magic-user' for 'mage'."""
    low = caster_class.strip().lower()
    return next((kind for kind, words in CASTER_CLASSES.items() if any(word in low for word in words)), low)


def strength_row(score: str) -> dict[str, Any] | None:
    """The Strength table's row for "16" or "18/76"; None for a score the table doesn't have."""
    strength = load("ability_scores")["strength"]
    whole, _, pct = score.strip().partition("/")
    if pct:
        percent = int(pct) if pct.isdigit() else -1
        percent = 100 if percent == 0 else percent
        return next((row for row in strength["exceptional"] if row["pct_min"] <= percent <= row["pct_max"]), None)
    return strength["normal"].get(whole)
