"""The reference: what a ruleset looks things up in (`RulesetReference`, which each ruleset pack brings), and what a
setting's pages and lore are (`SettingPage`, `ReferenceHit`, `LoreFact`; a wiki setting pack reads them from its
`pack.db` through `delve.setting.wiki`) (spec §10, §12). Every ruleset lookup returns plain dicts: the columns of the
row, with its JSON columns decoded."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable


@dataclass(frozen=True)
class ReferenceHit:
    """One reference entry: a spell, monster or item for a ruleset, a place, deity or faction for a setting. A
    setting's hit says where it comes from (`origin`): the shipped setting, the install's `addition` or `override`, a
    campaign's `proposal`, or a `fact`; `dm_only` marks one for the DM alone."""

    kind: str
    key: str
    title: str
    text: str
    origin: str = "shipped"
    dm_only: bool = False


@dataclass(frozen=True)
class SettingPage:
    """One page of a setting's wiki. `kind` is the typed table holding it ("settlements", "deities"), else the wiki's own page type. `fields` are the typed row's non-empty values, `text`
    the page in wiki markup, `categories` the wiki's tags.

    Through the setting layer (`delve.play.setting_layer`) a page also says where it comes from (`origin`): the shipped
    setting, the install's `addition` (a new page) or `override`, or a campaign's `proposal` (`campaign_id` says
    whose, as it does when a campaign's proposed edits were applied). `dm_only` marks a page for the DM alone, and
    `format` is `wiki` for the shipped markup, else `markdown`."""

    title: str
    kind: str
    fields: dict[str, str]
    text: str
    categories: tuple[str, ...]
    origin: Literal["shipped", "addition", "override", "proposal"] = "shipped"
    dm_only: bool = False
    campaign_id: str | None = None
    format: Literal["wiki", "markdown"] = "wiki"


@dataclass(frozen=True)
class LoreFact:
    """A "Did you know" fact: a setting's lore (the reference's), the install's (`source` "install") or a campaign's
    proposal (`source` "campaign"). `dm_only` marks one for the DM alone."""

    id: int
    text: str
    category: str
    source: str
    dm_only: bool = False


@runtime_checkable
class RulesetReference(Protocol):
    """What a ruleset looks up: its monsters, spells, items, classes, ability tables, turning table, rules text and
    encounter tables. A ruleset pack brings its own, read from its data or its `pack.db`."""

    def monster(self, name: str) -> list[dict]:
        """Monsters matching `name`, best first, ranked as ttrpg2's `lookup.find_monster_rows`: the exact name, the
        family's common entry ("rat, common" or "common rat"), the family ("rat, giant", "giant rat"), names starting with
        it, names with it as a word, any substring; within
        a rank, statted rows first, then shorter names. When nothing matches, every word of a query of two or more
        words must appear ("dragon, red" finds "red dragon"). At most 10."""
        ...

    def spell(self, name: str, caster: str = "") -> list[dict]:
        """Spells matching `name`: exact, then prefix, then contains, shorter names first. `caster` ("wizard",
        "priest", or part of it) filters, ignoring case. At most 10."""
        ...

    def item(self, name: str, item_type: str = "", max_rarity: int = 100, limit: int = 20) -> list[dict]:
        """Items whose name contains `name`, of a type containing `item_type`, no rarer than `max_rarity`
        (0 common … 100 artifact), commonest first, then by name."""
        ...

    def char_class(self, name: str) -> dict | None:
        """The class named `name` (exact, else the shortest name containing it), or None."""
        ...

    def class_levels(self, name: str) -> list[dict]:
        """The level rows of the class `char_class(name)`, by level: XP, hit dice, THAC0, saves, spell slots."""
        ...

    def race(self, name: str) -> dict | None:
        """The race (ancestry) named `name`: its ability adjustments and ranges, its classes and level limits, its
        features; None for one the ruleset doesn't list (or a ruleset that keeps its races in its rules text)."""
        ...

    def ability(self, ability: str, score: str) -> dict:
        """The PHB table for an ability ("strength" or "str"), as ttrpg2's `ability_lookup`: `headline`,
        `xp_bonus`, `extra` and `columns`, then the row for `score` under `score` and `values` ("15", "18/76",
        a range member such as "12" of "12-13"), or every row under `rows` when `score` is empty. An unknown ability
        or score answers with an `error` key."""
        ...

    def proficiency(self, name: str = "", group: str = "", ability: str = "") -> list[dict]:
        """Nonweapon proficiencies (PHB Table 37) filtered by part of the name, a group (general, priest, rogue,
        warrior, wizard) and the relevant ability. An unknown group raises `ValueError`."""
        ...

    def turning_undead(self) -> list[dict]:
        """DMG Table 47, one row per undead type in table order; `results` aligns to the level columns
        1…9, 10-11, 12-13, 14+."""
        ...

    def rules_search(self, query: str, source: str = "", limit: int = 5) -> list[dict]:
        """Full-text search of the rules (FTS5, as ttrpg2's `rules_lookup`), best first: `id`, `source`, `label`,
        `chapter`, `section` and a `snippet` with the hits in `<<…>>`. `limit` is capped at 20. A query FTS5 can't
        parse raises `ValueError`."""
        ...

    def rules_section(self, source: str, section: str) -> list[dict]:
        """The sections of `source` (phb, dmg, mm) whose title contains `section`, with their full `body`: an exact
        title first, then in book order. At most 10."""
        ...

    def encounter_tables(self) -> dict:
        """ttrpg2's `encounter_tables.json`: `meta`, `bands` and `terrains`."""
        ...

    def osric_magic_items(self) -> dict:
        """ttrpg2's `osric_magic_items.json`: the OSRIC magic-item tables, with their gold-piece values."""
        ...


RARITY_BANDS: tuple[tuple[str, int | None], ...] = (
    ("common", 5),
    ("uncommon", 20),
    ("rare", 40),
    ("very_rare", 55),
    ("legendary", 70),
    ("artifact", None),
)
"""The rulesets' item rarity bands, after ttrpg2's labels: each band's name and the highest `rarity` it holds (0
common … 100 artifact); the last has no top."""


def rarity_band(rarity: int | None) -> str:
    """The band of `RARITY_BANDS` an item's `rarity` falls in; a missing rarity is common."""
    value = rarity or 0
    return next(name for name, top in RARITY_BANDS if top is None or value <= top)


PAGE_LIMIT = 200
"""The most rows a browse page answers."""


@dataclass(frozen=True)
class Section:
    """One section of a ruleset's book (`spells`, `abilities`): a `list` with a page per entry, or a `table` shown
    whole, and how many entries it holds."""

    key: str
    kind: Literal["list", "table"]
    count: int


@dataclass(frozen=True)
class Facet:
    """One filter of a list section (`school`, `size`): its values as stored, and how many entries have each."""

    key: str
    options: tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class RowsPage:
    """One page of a list section. Each row has `id` and `name`, the section's columns as text (spells: caster,
    level, school; monsters: size, alignment, hit_dice, xp_value; items: item_type, cost, weight, rarity; classes:
    hit_die, prime_requisite), and `house_rule`. `total` counts every match."""

    rows: list[dict]
    total: int
    offset: int


@dataclass(frozen=True)
class Entry:
    """One entry's page. `fields` are its non-empty stats as text, keyed in snake_case (`casting_time`) for the web
    app to label; `text` is Markdown; `table` its rows (a class's progression, an ability's scores), else None."""

    section: str
    id: str
    name: str
    fields: dict[str, str]
    text: str
    table: list[dict] | None
    house_rule: bool = False


@runtime_checkable
class ReferenceBook(RulesetReference, Protocol):
    """A ruleset's reference as the Rulesets area browses it: paged lists of spells, monsters and items with their
    filters, and the tables beside them. Every `*_page` answers `(rows, total)`: the rows of the page, as the lookups'
    dicts, and how many match in all. They are ordered by name (ignoring case), then id; `q` matches part of the name,
    ignoring case, and an empty filter matches everything. `limit` is capped at `PAGE_LIMIT`."""

    def spells_page(
        self, q: str = "", caster: str = "", level: int = 0, school: str = "", offset: int = 0, limit: int = 50
    ) -> tuple[list[dict], int]:
        """Spells by part of the name, caster ("wizard", "priest", ignoring case), level (0 any) and school. A spell
        of a compound school ("Alteration/Necromancy") is under each of its schools."""
        ...

    def spell_by_id(self, id: int) -> dict | None:
        """The spell row `id`, or None."""
        ...

    def spell_schools(self, caster: str = "") -> list[tuple[str, int]]:
        """Each single school and how many spells (of `caster`, if one is given) it has, by school."""
        ...

    def monsters_page(
        self,
        q: str = "",
        size: str = "",
        alignment: str = "",
        terrain: str = "",
        book: str = "",
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[dict], int]:
        """Monsters that aren't soft-deleted, by part of the name and a value of each facet (`monster_facets`),
        ignoring case."""
        ...

    def monster_by_id(self, id: int) -> dict | None:
        """The monster row `id`, or None, also for a soft-deleted row."""
        ...

    def monster_facets(self) -> dict[str, list[tuple[str, int]]]:
        """For each facet (size, alignment, terrain, book), its values and how many monsters have each, the most
        first, then by value."""
        ...

    def items_page(
        self, q: str = "", item_type: str = "", rarity: str = "", offset: int = 0, limit: int = 50
    ) -> tuple[list[dict], int]:
        """Items by part of the name, their type as stored (ignoring case) and a band of `RARITY_BANDS`. An unknown
        band raises `ValueError`."""
        ...

    def item_by_id(self, id: int) -> dict | None:
        """The item row `id`, or None."""
        ...

    def item_types(self) -> list[tuple[str, int]]:
        """Each non-empty item type as stored and how many items have it, by type."""
        ...

    def classes(self) -> list[dict]:
        """Every class row, by name."""
        ...

    def proficiency_crossover(self) -> list[dict]:
        """PHB Table 38: for each class (`class_name`), the proficiency `groups` open to it, by class."""
        ...

    def counts(self) -> dict[str, int]:
        """How many spells, monsters (not soft-deleted), items, classes and proficiencies there are."""
        ...

    def names(self, q: str, limit: int = 20) -> list[tuple[str, int, str]]:
        """Spells, monsters, items and classes whose name contains `q` (ignoring case), as (section, id, name): the
        exact name first, then names starting with it, then the rest, each by name. An empty `q` finds nothing."""
        ...
