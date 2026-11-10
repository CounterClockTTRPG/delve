"""The OSRIC ruleset: its tables (`TABLES`) and its reference (`OsricReference`, with the bestiary) for the classic engine."""

from __future__ import annotations

import re
from collections.abc import Callable
from functools import cached_property
from importlib import resources
from typing import Any

from delve.domain.reference import ReferenceHit
from delve_osric import merchant
from delve_osric.encounters import ENCOUNTERS
from delve_osric.reference import OsricReference
from delve_osric.rulebook import OsricRulebook
from delve_osric.tables import TABLES
from delve_osric.treasure import TREASURE


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


class OsricRuleset:
    id = "osric"
    title = "OSRIC 3.0"
    tables = TABLES
    notice = (
        "Delve is an independent product published under the OSRIC 3.0 Third-Party License and is not affiliated with "
        'Mythmere Games LLC. This work includes material taken from the System Reference Document 5.1 ("SRD 5.1") by '
        'Wizards of the Coast LLC, licensed under the Creative Commons Attribution 4.0 International License. "OSRIC" '
        "is a trademark of Matthew Finch and Stuart Marshall."
    )
    prompt = resources.files("delve_osric").joinpath("prompt.md").read_text("utf-8")
    treasure = TREASURE
    encounters = ENCOUNTERS

    def __init__(self) -> None:
        self.reference = OsricReference()
        self._lookups: dict[str, Callable[[str, int], list[ReferenceHit]]] = {
            "monster": self._monsters,
            "spell": self._spells,
            "item": self._items,
            "class": self._classes,
        }

    @cached_property
    def rulebook(self) -> OsricRulebook:
        """The book the Rulesets area reads."""
        return OsricRulebook(self.reference)

    def kinds(self) -> tuple[str, ...]:
        return tuple(self._lookups)

    def lookup(self, kind: str, query: str, limit: int = 5) -> list[ReferenceHit]:
        if kind not in self._lookups:
            raise ValueError(f"unknown kind '{kind}'; kinds: {', '.join(self._lookups)}")
        return self._lookups[kind](query, limit)[:limit]

    def merchant_catalogue(self) -> tuple[Any, ...]:
        return merchant.catalogue()

    def _monsters(self, query: str, limit: int) -> list[ReferenceHit]:
        return [
            ReferenceHit(
                "monster",
                _slug(m["name"]),
                m["name"],
                f"AC {m['armor_class']}, HD {m['hit_dice']}, THAC0 {m['thac0']}, {m['attacks']}. {m['description']}",
            )
            for m in self.reference.monster(query)
        ]

    def _spells(self, query: str, limit: int) -> list[ReferenceHit]:
        return [
            ReferenceHit(
                "spell",
                _slug(f"{s['caster']} {s['name']}"),
                s["name"],
                f"{s['caster']} {s['level']}, {s['school']}. {s['description']}".strip(),
            )
            for s in self.reference.spell(query)
        ]

    def _items(self, query: str, limit: int) -> list[ReferenceHit]:
        return [
            ReferenceHit(
                "item", _slug(i["name"]), i["name"], ", ".join(str(v) for v in (i["item_type"], i["cost"]) if v)
            )
            for i in self.reference.item(query, limit=limit)
        ]

    def _classes(self, query: str, limit: int) -> list[ReferenceHit]:
        found = self.reference.char_class(query)
        if found is None:
            return []
        return [ReferenceHit("class", _slug(found["name"]), found["name"], f"hit die {found['hit_die']}")]
