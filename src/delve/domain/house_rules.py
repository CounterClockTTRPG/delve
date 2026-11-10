"""House rules and bundles (spec §9): text plus tags, grouped into named bundles that campaigns point to.

`kind` groups rules in the list; `phases` say when a rule reaches the DM. A rule tied to a ruleset or a setting is left
out of campaigns on another; None means any.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal, get_args

Phase = Literal["character-creation", "level-up", "combat", "items", "behaviour", "always"]
Kind = Literal["general", "race", "class", "item", "behaviour"]

PHASES: tuple[Phase, ...] = get_args(Phase)
KINDS: tuple[Kind, ...] = get_args(Kind)

PROMPT_PHASES: frozenset[Phase] = frozenset({"behaviour", "always"})
"""The phases whose rules sit in the DM's system prompt rather than in a tool result."""


def subject_key(name: str) -> str:
    """A race, class or item name as a rule's subject: lowercase words joined by hyphens, "Pega-taur" → "pega-taur",
    "Caster's Aid" → "casters-aid"."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower().replace("'", "")).strip("-")


@dataclass(frozen=True)
class HouseRule:
    id: str
    """hr_<12 hex>"""
    title: str
    body_md: str = ""
    kind: Kind = "general"
    phases: frozenset[Phase] = field(default_factory=frozenset)
    ruleset: str | None = None
    """A ruleset's id ("osric"); None means any."""
    setting: str | None = None
    """A setting's id ("aun"); None means any."""
    subject: str | None = None
    """The race, class or item the rule is about, as a `subject_key`: "lizardfolk"."""
    enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        """As JSON, with the phases in `PHASES` order."""
        return {
            "id": self.id,
            "title": self.title,
            "body_md": self.body_md,
            "kind": self.kind,
            "phases": [p for p in PHASES if p in self.phases],
            "ruleset": self.ruleset,
            "setting": self.setting,
            "subject": self.subject,
            "enabled": self.enabled,
        }


@dataclass(frozen=True)
class Bundle:
    """A named, ordered group of rules, chosen as one: "my usual table"."""

    id: str
    """hb_<12 hex>"""
    title: str
    description_md: str = ""
    rule_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description_md": self.description_md,
            "rule_ids": list(self.rule_ids),
        }
