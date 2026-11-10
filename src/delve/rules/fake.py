"""A small in-memory ruleset for tests and development."""

from __future__ import annotations

from delve.domain.reference import ReferenceHit
from delve.rules.classic.encumbrance import EncumbranceTables
from delve.rules.classic.overland import TravelRates
from delve.rules.classic.tables import RuleTables

SAMPLE_HITS: dict[str, list[ReferenceHit]] = {
    "spell": [
        ReferenceHit("spell", "magic-missile", "Magic Missile", "1d4+1 damage per missile; it never misses."),
        ReferenceHit("spell", "sleep", "Sleep", "Puts 2d4 Hit Dice of creatures into a magical slumber."),
    ],
    "monster": [
        ReferenceHit("monster", "kobold", "Kobold", "A small, cowardly, reptilian humanoid. AC 7, HD ½."),
    ],
    "item": [
        ReferenceHit("item", "long-sword", "Long sword", "1d8 against small and medium, 1d12 against large."),
    ],
}


FAKE_TABLES = RuleTables(
    save_types=("body", "mind"),
    save_names={"body": "Body", "mind": "Mind"},
    save_aliases={"body": "body", "mind": "mind", "b": "body", "m": "mind"},
    save_short=("b", "m"),
    saves_by_group={"hero": ((5, (12, 14)), (99, (8, 10)))},
    class_groups={"hero": "hero"},
    saves_source="fake save table",
    monster_save_group="hero",
    monster_saves=None,
    shock={},
    shock_default=80,
    resurrect={},
    resurrect_default=80,
    morale_roll="2d6",
    initiative_die=6,
    weapon_speed_in_initiative=False,
    reaction_roll="2d6",
    reaction_bands=((6, "hostile", "It attacks."),),
    reaction_top=("friendly", "It is friendly."),
    disposition_step=50,
    reputation_step=50,
    surprise_die=6,
    surprise_on=1,
    encounter_checks={},
    encounter_check_default={"die": 6, "threshold": 1, "interval_minutes": 60},
    turning_level_columns=("1", "2+"),
    class_aliases={},
    travel=TravelRates(12, 10, 2, 1, 8, 3, 10),
    caster_classes={"arcane": ("hero",)},
    encumbrance=EncumbranceTables(
        item_aliases={},
        item_weights={},
        str_bands={3: (30, 60, 90, 120)},
        str_pct_allowance=(),
        pct_stride=30,
        band_penalties={"light": 0, "moderate": -2, "heavy": -4, "severe": -6, "overloaded": -8},
    ),
    nonproficient={"hero": 2},
    mounts={"horse": (12, 7, 18, 19, ["1d4 (kick)"], 8)},
    mount_fly={},
)
"""Made-up numbers of no ruleset, so the fake ruleset can be played without any pack."""


class FakeRuleset:
    """A ruleset holding a dict of hits by kind; `lookup` matches the query case-insensitively in the title."""

    id = "fake-rules"
    title = "Fake ruleset"
    reference = None
    tables = FAKE_TABLES
    notice = ""
    prompt = "A made-up ruleset for developing Delve: its numbers are the tools'."
    treasure = None
    encounters = None
    rulebook = None

    def __init__(self, hits: dict[str, list[ReferenceHit]] | None = None) -> None:
        self._hits = dict(SAMPLE_HITS if hits is None else hits)

    def kinds(self) -> tuple[str, ...]:
        return tuple(self._hits)

    def lookup(self, kind: str, query: str, limit: int = 5) -> list[ReferenceHit]:
        if kind not in self._hits:
            raise ValueError(f"unknown kind '{kind}'; kinds: {', '.join(self._hits)}")
        needle = query.casefold()
        return [hit for hit in self._hits[kind] if needle in hit.title.casefold()][:limit]

    def merchant_catalogue(self) -> tuple:
        return ()
