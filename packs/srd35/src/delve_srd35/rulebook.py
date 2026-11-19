"""SRD 3.5's book for the Rulesets area (DEL-384): its classes, races, skills, feats, spells, monsters, items and
rules as lists of entries, and its ability table.

Entries are keyed by id (their slug). Each list section's rows carry the section's `columns`; a filter is one of its
`facets` or `q`, part of the name. A spell has a class and a level for each class that casts it, and a filter on
either matches any of them.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable
from functools import cached_property
from typing import Any

from delve.domain.reference import Entry, Facet, RowsPage, Section
from delve.rules.classic.rulebook import rank
from delve_srd35 import text
from delve_srd35.data import load
from delve_srd35.reference import ABILITIES, Srd35Reference

LISTS = ("classes", "races", "skills", "feats", "spells", "monsters", "items")
COLUMNS = {
    "classes": ("hit_die", "skill_points", "type"),
    "races": ("size", "speed", "la"),
    "skills": ("key_ability", "trained_only", "armor_check"),
    "feats": ("type", "prerequisites"),
    "spells": ("school", "level"),
    "monsters": ("size", "type", "cr"),
    "items": ("item_type", "price"),
    "rules": ("source", "chapter"),
}
FACETS = {
    "classes": ("type",),
    "skills": ("key_ability",),
    "feats": ("type",),
    "spells": ("class", "level", "school"),
    "monsters": ("size", "type", "cr"),
    "items": ("item_type",),
    "rules": ("source",),
}
SHORT = {"bard": "Brd", "cleric": "Clr", "druid": "Drd", "paladin": "Pal", "ranger": "Rgr", "adept": "Adp"}
"""The SRD's short names of the classes in a spell's level line; a domain is named in full."""


def spell_level_line(levels: dict[str, int]) -> str:
    """A spell's levels as the SRD prints them: "Sor/Wiz 3, Clr 2", a domain by its name ("Fire 3")."""
    parts = []
    rest = dict(levels)
    if "sorcerer" in rest and rest.get("sorcerer") == rest.get("wizard"):
        parts.append(f"Sor/Wiz {rest.pop('sorcerer')}")
        rest.pop("wizard")
    for name, level in rest.items():
        parts.append(f"{SHORT.get(name, name.replace('-', ' ').title())} {level}")
    return ", ".join(parts)


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, dict):
        return ", ".join(f"{k} {_text(v)}" for k, v in value.items())
    if isinstance(value, list | tuple):
        return ", ".join(_text(v) for v in value)
    return str(value)


def _values(row: dict[str, Any], key: str) -> list[str]:
    """What a facet sees in a row: each of a spell's classes and levels, else the field as text."""
    if key == "class":
        return list(row["levels"])
    if key == "level":
        return sorted({str(level) for level in row["levels"].values()})
    if key == "type" and isinstance(row.get("type"), list):
        return list(row["type"])
    value = _text(row.get(key))
    return [value] if value else []


def _signed(value: Any) -> str:
    """A bonus as the SRD prints it: "+3", "–1" (an en dash), "+0"; anything that isn't a number as it is."""
    text = str(value).strip()
    if re.fullmatch(r"[+-]?\d+", text):
        number = int(text)
        return f"+{number}" if number >= 0 else f"–{-number}"
    return text.replace("-", "–", 1) if re.fullmatch(r"-\d.*", text) else text


def _by_ability(values: dict[str, Any], signed: bool) -> str:
    """Scores or adjustments in the SRD's order of the abilities: "Str 11, Dex 13", "Str +2, Int –2"."""
    order = [key for key in ABILITIES if key in values] + sorted(k for k in values if k not in ABILITIES)
    return ", ".join(f"{k.title()} {_signed(values[k]) if signed else values[k]}" for k in order)


def _titled(name: str) -> str:
    """A skill's name as the SRD prints it: "Move Silently", "Knowledge (arcana)"."""
    head, paren, rest = name.partition("(")
    return f"{head.title()}{paren}{rest}"


def _named(values: dict[str, Any]) -> str:
    """A monster's skills or saves by name, each bonus signed: "Hide +5, Move Silently +5"; "Fort +3"."""
    return ", ".join(f"{_titled(name)} {_signed(bonus)}".strip() for name, bonus in values.items())


DISPLAY: dict[str, Callable[[Any], str]] = {
    "ability_adjustments": lambda v: _by_ability(v, signed=True),
    "abilities": lambda v: _by_ability(v, signed=False),
    "saves": lambda v: _named({k: v[k] for k in ("fort", "ref", "will") if k in v} | v),
    "skills": _named,
    "key_ability": lambda v: str(v).title(),
}
"""How an entry shows a field the data keeps structured: in the SRD's words and order, not the data's keys."""


def _fields(row: dict[str, Any], keys: tuple[str, ...]) -> dict[str, str]:
    shown = {key: DISPLAY[key](row[key]) if key in DISPLAY and row.get(key) else _text(row.get(key)) for key in keys}
    return {key: value for key, value in shown.items() if value}


def _sort_key(value: str) -> tuple[int, float, str]:
    """Numbers first, by value ("1/2" before "1", "10" after "9"), then words, by name."""
    top, _, bottom = value.partition("/")
    try:
        number = float(top) / float(bottom) if bottom else float(top)
    except ValueError:
        return (1, 0.0, value.lower())
    return (0, number, value)


class Srd35Rulebook:
    def __init__(self, reference: Srd35Reference) -> None:
        self.ref = reference
        self._lists: dict[str, Callable[[], list[dict[str, Any]]]] = {
            **{kind: (lambda kind=kind: self._rows_of(kind)) for kind in LISTS},
            "rules": lambda: self._rules,
        }

    @cached_property
    def _by_kind(self) -> dict[str, list[dict[str, Any]]]:
        # Copies: the rows `load` caches are the engine's too (a feat's structured prerequisites).
        out = {
            kind: sorted((dict(r) for r in load(kind)), key=lambda r: (r["name"].lower(), r["id"])) for kind in LISTS
        }
        for spell in out["spells"]:
            spell["level"] = spell_level_line(spell["levels"])
        for feat in out["feats"]:
            feat["prerequisites"] = feat.get("prerequisites_line", "")
        return out

    def _rows_of(self, kind: str) -> list[dict[str, Any]]:
        return self._by_kind[kind]

    @cached_property
    def _rules(self) -> list[dict[str, Any]]:
        return [
            {"id": s.slug, "name": s.title, "source": s.source, "chapter": s.chapter, "body": s.body}
            for s in text.sections()
        ]

    # The book.

    def columns(self, section: str) -> tuple[str, ...]:
        return COLUMNS.get(section, ())

    def sections(self) -> list[Section]:
        found = [Section(key, "list", len(self._list(key))) for key in LISTS]
        found.append(Section("abilities", "table", len(ABILITIES)))
        found.append(Section("rules", "list", len(self._rules)))
        return [s for s in found if s.count]

    def facets(self, section: str) -> list[Facet]:
        rows = self._list(section)
        out = []
        for key in FACETS.get(section, ()):
            counts = Counter(v for r in rows for v in _values(r, key))
            out.append(Facet(key, tuple(sorted(counts.items(), key=lambda kv: _sort_key(kv[0])))))
        return out

    def rows(self, section: str, filters: dict[str, str], offset: int, limit: int) -> RowsPage:
        rows = self._list(section)
        q = filters.get("q", "").strip().lower()
        wanted = {k: v for k, v in filters.items() if k != "q" and k in FACETS.get(section, ()) and v}
        found = [
            r for r in rows if (not q or q in r["name"].lower()) and all(v in _values(r, k) for k, v in wanted.items())
        ]
        offset = max(0, int(offset))
        page = found[offset : offset + limit] if limit else []
        return RowsPage([self._row(section, r) for r in page], len(found), offset)

    def entry(self, section: str, id: str) -> Entry | None:
        if section not in self._lists:
            return None
        row = next((r for r in self._list(section) if r["id"] == id), None)
        if row is None:
            return None
        if section == "classes":
            # The text has the SRD's own table, with every column; the structured rows only stand in without it.
            levels = [{k: _text(v) for k, v in level.items()} for level in row["levels"]]
            table = None if "\n| --- |" in row["text"] else levels
            skills = {skill["id"]: skill["name"] for skill in self._by_kind["skills"]}
            fields = _fields({**row, "class_skills": [skills.get(s, s) for s in row["class_skills"]]},
                             ("type", "hit_die", "skill_points", "class_skills"))  # fmt: skip
            return Entry(section, id, row["name"], fields, row["text"], table or None)
        if section == "races":
            keys = ("size", "speed", "ability_adjustments", "la", "favored_class")
            return Entry(section, id, row["name"], _fields(row, keys), row["text"], None)
        if section == "skills":
            keys = ("key_ability", "trained_only", "armor_check")
            return Entry(section, id, row["name"], _fields(row, keys), row["text"], None)
        if section == "feats":
            body = "\n\n".join(f"**{label}:** {row[key]}" for key, label in
                               (("benefit", "Benefit"), ("normal", "Normal"), ("special", "Special")) if row[key])  # fmt: skip
            return Entry(section, id, row["name"], _fields(row, ("type", "prerequisites")), body, None)
        if section == "spells":
            keys = ("school", "subschool", "descriptors", "level", "components", "casting_time", "range", "target",
                    "area", "effect", "duration", "saving_throw", "spell_resistance")  # fmt: skip
            return Entry(section, id, row["name"], _fields(row, keys), row["text"], None)
        if section == "monsters":
            keys = ("size", "type", "subtypes", "hit_dice", "initiative", "speed", "armor_class", "base_attack_grapple",
                    "attack", "full_attack", "space_reach", "special_attacks", "special_qualities", "saves",
                    "abilities", "skills", "feats", "environment", "organization", "cr", "treasure", "alignment",
                    "advancement", "level_adjustment")  # fmt: skip
            return Entry(section, id, row["name"], _fields(row, keys), row["text"], None)
        if section == "items":
            keys = ("item_type", "price", "weight", "caster_level")
            return Entry(section, id, row["name"], _fields(row, keys), row["text"], None)
        return Entry(section, id, row["name"], _fields(row, ("source", "chapter")), row["body"], None)

    def table(self, section: str) -> list[dict]:
        if section != "abilities":
            raise KeyError(section)
        found = self.ref.ability("str", "")
        return [{"key": "abilities", "note": found["headline"], "rows": found["rows"]}]

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
