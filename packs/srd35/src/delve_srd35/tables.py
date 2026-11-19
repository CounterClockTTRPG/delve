"""SRD 3.5's `RuleTables`. Campaigns play the pack (DEL-388) through its 3.5 engine (`Ruleset.d20`), which replaces
the classic maths (saves, initiative, turning, spells by class); core still reads the rest of these tables. Its saves
are 3.5's three, Fortitude, Reflex and Will; its fights roll initiative once, highest first (`fight`, which core's
round order reads); a load is the SRD's Table: Carrying Capacity (`encumbrance`, which the session primer, the
character pages and the encumbrance tool weigh against, times the engine's size multiplier, and which slows a speed
by the SRD's reduced speeds); everything else is the engine's plain default."""

from __future__ import annotations

from delve.rules.classic.encumbrance import EncumbranceTables
from delve.rules.classic.overland import TravelRates
from delve.rules.classic.tables import FightRules, RuleTables
from delve_srd35.data import load

SAVES = ("fort", "ref", "will")
STRONGEST = 45
"""The highest Strength given a load: the ability table's last score."""


def _loads() -> dict[int, tuple[int, int, int, int]]:
    """The heaviest light, medium and heavy load by Strength (Table: Carrying Capacity, `data/carrying.json`), and
    the most lifted off the ground, double the heavy load (Lifting and Dragging: the character only staggers with it).
    Above the table, Tremendous Strength: the row of 20–29 with the same ones digit, ×4 per ten points above it."""
    carrying = load("carrying")
    table = {row["strength"]: (row["light"], row["medium"], row["heavy"]) for row in carrying["loads"]}
    for score in range(max(table) + 1, STRONGEST + 1):
        base = 20 + score % 10
        table[score] = tuple(lb * carrying["tremendous"] ** ((score - base) // 10) for lb in table[base])
    return {score: (light, medium, heavy, 2 * heavy) for score, (light, medium, heavy) in sorted(table.items())}


STAGGER = 5
"""Lifting and Dragging: a character lifting more than its heavy load off the ground moves only 5 ft. a round."""


def slowed(band: str, speed: int) -> int:
    """The speed under a load (core's `EncumbranceTables.band_movement`, DEL-399). Table: Carrying Loads and Armor and
    Encumbrance for Other Base Speeds: a medium load (core's "moderate" band) or a heavy one takes 20 ft. to 15 ft.,
    30 ft. to 20 ft. and so on to 100 ft. (`data/carrying.json`); a speed off the table keeps two thirds, rounded
    down. One only lifted off the ground staggers 5 ft. a round; more can't be lifted."""
    if band == "light":
        return speed
    if band in ("moderate", "heavy"):
        reduced = {row["base"]: row["reduced"] for row in load("carrying")["reduced_speeds"]}
        return reduced.get(speed, speed * 2 // 3)
    return min(STAGGER, speed) if band == "severe" else 0

TABLES = RuleTables(
    save_types=SAVES,
    save_names={"fort": "Fortitude", "ref": "Reflex", "will": "Will"},
    save_aliases={"fort": "fort", "ref": "ref", "will": "will", "fortitude": "fort", "reflex": "ref"},
    save_short=SAVES,
    saves_by_group={"any": ((99, (10, 10, 10)),)},
    class_groups={},
    saves_source="SRD 3.5 (a reference: its saves are rolled d20 + bonus, not on a table)",
    monster_save_group="any",
    monster_saves=None,
    shock={},
    shock_default=0,
    resurrect={},
    resurrect_default=0,
    morale_roll="",
    initiative_die=20,
    weapon_speed_in_initiative=False,
    reaction_roll="",
    reaction_bands=(),
    reaction_top=("indifferent", ""),
    disposition_step=50,
    reputation_step=50,
    surprise_die=0,
    surprise_on=0,
    encounter_checks={},
    encounter_check_default={"die": 20, "threshold": 0, "interval_minutes": 60},
    turning_level_columns=(),
    class_aliases={},
    travel=TravelRates(12, 10, 2, 1, 8, 3, 10, sheet_speed_scale=0.4),  # speed in feet (DEL-404)
    caster_classes={},
    encumbrance=EncumbranceTables(
        item_aliases={},
        item_weights={},
        str_bands=_loads(),
        str_pct_allowance=(),
        pct_stride=0,
        band_penalties={},
        band_movement=slowed,
    ),
    nonproficient={},
    mounts={},
    mount_fly={},
    # The SRD's Initiative Checks: "Characters act in order, counting down from highest result to lowest. In every
    # round that follows, the characters act in the same order".
    fight=FightRules(initiative_once=True, highest_first=True),
)
