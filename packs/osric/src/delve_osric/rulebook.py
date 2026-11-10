"""OSRIC's book for the Rulesets area (DEL-305): its spells, monsters, equipment, classes and races as lists of
entries, its ability and turning tables, and its rules in Delve's own words (`text`), over its data in `data/`.

Entries are keyed by slug. Each list section's rows carry the section's `columns`; a filter is one of its `facets` or
`q`, part of the name.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable
from functools import cached_property
from typing import Any

from delve.domain.reference import Entry, Facet, RowsPage, Section
from delve.rules.classic.rulebook import rank
from delve_osric import text
from delve_osric.reference import ABILITIES, OsricReference
from delve_osric.tables import TURNING_COLUMNS

COLUMNS = {
    "spells": ("caster", "level", "school"),
    "monsters": ("size", "alignment", "hit_dice", "xp_value"),
    "items": ("item_type", "cost", "weight"),
    "classes": ("hit_die", "prime_requisite"),
    "races": ("size", "move"),
    "rules": ("source", "chapter"),
}
FACETS = {
    "spells": ("caster", "level", "school"),
    "monsters": ("size", "alignment"),
    "items": ("item_type",),
    "rules": ("source",),
}


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        return ", ".join(f"{k.replace('_', ' ')} {_text(v)}" for k, v in value.items() if not str(k).startswith("_"))
    if isinstance(value, list | tuple):
        return ", ".join(_text(v) for v in value)
    return str(value)


def _fields(row: dict[str, Any], keys: tuple[str, ...]) -> dict[str, str]:
    return {key: _text(row[key]) for key in keys if _text(row.get(key))}


class OsricRulebook:
    def __init__(self, reference: OsricReference) -> None:
        self.ref = reference
        self._lists: dict[str, Callable[[], list[dict[str, Any]]]] = {
            "spells": lambda: self._spells,
            "monsters": lambda: self._monsters,
            "items": lambda: self._items,
            "classes": lambda: self._classes,
            "races": lambda: self._races,
            "rules": lambda: self._rules,
        }

    # The entries of each list, as rows with their id, name, columns and the whole entry.

    @cached_property
    def _spells(self) -> list[dict[str, Any]]:
        from delve_osric.data import load

        rows = []
        for spell in load("spells")["spells"]:
            row = self.ref._spell(spell)
            rows.append(
                {**row, "id": spell["slug"], "caster": spell["class"], "school": (spell.get("school") or "").lower()}
            )
        return sorted(rows, key=lambda r: (r["name"].lower(), r["id"]))

    @cached_property
    def _monsters(self) -> list[dict[str, Any]]:
        from delve_osric.data import load

        rows = []
        for m in load("monsters")["monsters"]:
            row = self.ref._monster(m)
            rows.append({**row, "id": m["slug"], "size": (row["size"].split() or [""])[0], "move": m.get("move", "")})
        return sorted(rows, key=lambda r: (r["name"].lower(), r["id"]))

    @cached_property
    def _items(self) -> list[dict[str, Any]]:
        return sorted(({**i, "id": _slug(i["name"])} for i in self.ref._items()), key=lambda r: r["name"].lower())

    @cached_property
    def _classes(self) -> list[dict[str, Any]]:
        from delve_osric.data import CLASSES

        return [{**self.ref.char_class(c), "id": c} for c in CLASSES]  # type: ignore[dict-item]

    @cached_property
    def _races(self) -> list[dict[str, Any]]:
        from delve_osric.classes import ANCESTRY_CLASSES

        rows = [self.ref.race(a) for a in ANCESTRY_CLASSES]
        return [{**r, "id": _slug(r["name"]), "move": f"{r['movement_ft']}ft"} for r in rows if r]

    @cached_property
    def _rules(self) -> list[dict[str, Any]]:
        return [
            {"id": s.slug, "name": s.title, "source": text.SOURCES.get(s.source, s.source), "chapter": s.number,
             "body": s.body}
            for s in text.sections()
        ]  # fmt: skip

    # The book.

    def columns(self, section: str) -> tuple[str, ...]:
        return COLUMNS.get(section, ())

    def sections(self) -> list[Section]:
        found = [Section(key, "list", len(rows())) for key, rows in self._lists.items()]
        found += [
            Section("abilities", "table", len(ABILITIES)),
            Section("turning", "table", len(self.ref.turning_undead())),
        ]
        return [s for s in found if s.count]

    def facets(self, section: str) -> list[Facet]:
        rows = self._list(section)
        out = []
        for key in FACETS.get(section, ()):
            counts = Counter(_text(r.get(key)) for r in rows if _text(r.get(key)))
            out.append(Facet(key, tuple(sorted(counts.items(), key=lambda kv: _sort_key(kv[0])))))
        return out

    def rows(self, section: str, filters: dict[str, str], offset: int, limit: int) -> RowsPage:
        rows = self._list(section)
        q = filters.get("q", "").strip().lower()
        found = [
            r
            for r in rows
            if (not q or q in r["name"].lower())
            and all(_text(r.get(k)) == v for k, v in filters.items() if k != "q" and k in FACETS.get(section, ()) and v)
        ]
        offset = max(0, int(offset))
        page = found[offset : offset + limit] if limit else []
        return RowsPage([self._row(section, r) for r in page], len(found), offset)

    def entry(self, section: str, id: str) -> Entry | None:
        if section in ("abilities", "turning"):
            return None
        row = next((r for r in self._list(section) if r["id"] == id), None)
        if row is None:
            return None
        if section == "spells":
            keys = ("caster", "level", "school", "range", "duration", "aoe", "components", "casting_time", "save")
            return Entry(section, id, row["name"], _fields(row, keys), row["description"], None)
        if section == "monsters":
            keys = ("frequency", "no_appearing", "size", "alignment", "move", "armor_class", "hit_dice", "thac0",
                    "attacks", "senses", "magic_resistance", "pct_in_lair", "intelligence", "morale",
                    "treasure_type", "xp_value", "source")  # fmt: skip
            body = "\n\n".join([row["description"], *(f"**{k}.** {v}" for k, v in row["sections"].items())])
            return Entry(section, id, row["name"], _fields(row, keys), body.strip(), None)
        if section == "items":
            keys = ("item_type", "cost", "weight", "damage_sm", "damage_l", "speed", "ac")
            return Entry(section, id, row["name"], _fields(row, keys), "", None)
        if section == "classes":
            keys = ("hit_die", "prime_requisite", "xp_bonus", "minimum_scores", "armour_allowed", "weapons_allowed",
                    "nonproficiency_penalty", "initial_gold", "ancestries", "multi_class")  # fmt: skip
            abilities = "\n".join(f"- **{f['name']}** ({f['level']}): {f['summary']}" for f in row["special_abilities"])
            table = [{k: _text(v) for k, v in level.items()} for level in self.ref.class_levels(id)]
            return Entry(section, id, row["name"], _fields(row, keys), abilities, table)
        if section == "races":
            keys = ("size", "move", "infravision_ft", "ability_adjustments", "ability_ranges", "classes")
            features = "\n".join(f"- {feature}" for feature in row["features"])
            table = [{"class": cls, "level": limit} for cls, limit in row["level_limits"].items()]
            return Entry(section, id, row["name"], _fields(row, keys), features, table or None)
        if section == "rules":
            return Entry(section, id, row["name"], _fields(row, ("source", "chapter")), row["body"], None)
        return None

    def table(self, section: str) -> list[dict]:
        if section == "abilities":
            tables = []
            for name in ABILITIES.values():
                found = self.ref.ability(name, "")
                rows = [{k: str(v) for k, v in r.items()} for r in found.get("rows", [])]
                tables.append({"key": name, "note": found.get("headline", ""), "rows": rows})
            return tables
        if section == "turning":
            rows = [
                {"undead_type": r["undead_type"], **dict(zip(TURNING_COLUMNS, r["results"], strict=True))}
                for r in self.ref.turning_undead()
            ]
            return [{"key": "turning", "note": "d20 at or above the number; T turned, D destroyed.", "rows": rows}]
        raise KeyError(section)

    def search(self, q: str, limit: int) -> list[tuple[str, str, str]]:
        wanted = (q or "").strip().lower()
        if not wanted or limit <= 0:
            return []
        hits = [
            (section, r["id"], r["name"])
            for section in self._lists
            for r in self._list(section)
            if wanted in r["name"].lower()
        ]
        return sorted(hits, key=lambda hit: rank(wanted, hit))[:limit]

    def _list(self, section: str) -> list[dict[str, Any]]:
        if section not in self._lists:
            raise KeyError(section)
        return self._lists[section]()

    def _row(self, section: str, found: dict[str, Any]) -> dict:
        row = {"id": found["id"], "name": found["name"]}
        row.update({column: _text(found.get(column)) for column in COLUMNS[section]})
        row["house_rule"] = False
        return row


def _sort_key(value: str) -> tuple[int, str]:
    return (int(value), "") if value.isdigit() else (10**6, value.lower())
