"""The SRD 3.5 ruleset: its 3.5 engine (`Srd35Engine`, which campaigns play by, DEL-388), 3.5's three
saves in its tables, its lookups over the extracted SRD data, and its book for the Rulesets area."""

from __future__ import annotations

import re
from collections.abc import Callable
from functools import cached_property
from importlib import resources
from typing import Any

from delve.domain.reference import ReferenceHit
from delve_srd35.engine import Srd35Engine
from delve_srd35.reference import Srd35Reference
from delve_srd35.rulebook import Srd35Rulebook
from delve_srd35.tables import TABLES
from delve_srd35.treasure import TREASURE


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _levels(levels: dict[str, int]) -> str:
    return ", ".join(f"{name} {level}" for name, level in levels.items())


def _weapon_line(w: dict[str, Any]) -> str:
    critical = f"x{w['mult']}" if w["threat"] == 20 else f"{w['threat']}–20/x{w['mult']}"
    return f"{w['category']} {w['kind']}, {w['damage_m']}, {critical}" + (f", {w['cost']}" if w["cost"] else "")


class Srd35Ruleset:
    id = "srd35"
    title = "SRD 3.5"
    tables = TABLES
    notice = resources.files("delve_srd35").joinpath("notice.md").read_text("utf-8").strip()
    prompt = resources.files("delve_srd35").joinpath("prompt.md").read_text("utf-8")
    treasure = TREASURE
    encounters = None

    def __init__(self) -> None:
        self.reference = Srd35Reference()
        self.d20 = Srd35Engine(self.reference)
        self._lookups: dict[str, Callable[[str, int], list[ReferenceHit]]] = {
            "monster": lambda q, n: [self._monster(m) for m in self.reference.monster(q)],
            "spell": lambda q, n: [
                ReferenceHit("spell", s["id"], s["name"], f"{s['school']}; {_levels(s['levels'])}.")
                for s in self.reference.spell(q)
            ],
            "item": lambda q, n: [
                ReferenceHit("item", i["id"], i["name"], ", ".join(v for v in (i["item_type"], i["price"]) if v))
                for i in self.reference.item(q, limit=n)
            ],
            "weapon": lambda q, n: [
                ReferenceHit("weapon", w["id"], w["name"], _weapon_line(w))
                for w in ([self.reference.weapon(q)] if self.reference.weapon(q) else [])
            ],
            "class": lambda q, n: [
                ReferenceHit("class", c["id"], c["name"], f"{c['type']} class, hit die {c['hit_die']}")
                for c in ([self.reference.char_class(q)] if self.reference.char_class(q) else [])
            ],
            "feat": lambda q, n: [
                ReferenceHit("feat", f["id"], f["name"], f["benefit"][:200]) for f in self.reference.feat(q)
            ],
            "skill": lambda q, n: [
                ReferenceHit("skill", s["id"], s["name"], f"key ability {s['key_ability'].upper() or '—'}")
                for s in self.reference.skill(q)
            ],
        }

    @staticmethod
    def _monster(m: dict[str, Any]) -> ReferenceHit:
        line = f"{m['size']} {m['type']}, CR {m['cr']}, HD {m['hit_dice']}, AC {m['armor_class']}."
        return ReferenceHit("monster", m["id"], m["name"], line)

    @cached_property
    def rulebook(self) -> Srd35Rulebook:
        """The book the Rulesets area reads."""
        return Srd35Rulebook(self.reference)

    def kinds(self) -> tuple[str, ...]:
        return tuple(self._lookups)

    def lookup(self, kind: str, query: str, limit: int = 5) -> list[ReferenceHit]:
        if kind not in self._lookups:
            raise ValueError(f"unknown kind '{kind}'; kinds: {', '.join(self._lookups)}")
        return self._lookups[kind](query, limit)[:limit]

    def merchant_catalogue(self) -> tuple[Any, ...]:
        return ()
