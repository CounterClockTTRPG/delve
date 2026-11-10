"""The campaign's house rules (spec §9): the rules the campaign chose, by phase. The rules of character creation,
level-up and items also come with the tools of those moments, so the DM never has to be reminded."""

from __future__ import annotations

from typing import Any

from delve.dm.tools.schema import ToolSpec, params, string, tool
from delve.domain.house_rules import PHASES
from delve.play import house_rules as play
from delve.play.context import CampaignContext

SPECS: list[ToolSpec] = []


@tool(
    SPECS,
    "house_rules",
    params(
        phase=string(
            "When they apply; without a phase, the ones always in force and those of the party's races and classes.",
            enum=list(PHASES),
        ),
        query=string("Part of a rule's title, subject or text."),
    ),
    mutates=False,
)
def house_rules(ctx: CampaignContext, phase: str = "", query: str = "") -> dict[str, Any]:
    """The campaign's house rules: those of a phase (character-creation, level-up, combat, items, behaviour, always),
    or those always in force. They override the book."""
    rules = play.rules_for(ctx, phase=phase or None)  # type: ignore[arg-type]
    wanted = query.strip().casefold()
    if wanted:
        rules = [r for r in rules if wanted in f"{r.title}\n{r.subject or ''}\n{r.body_md}".casefold()]
    return {"phase": phase or None, "count": len(rules), "rules": [rule.to_dict() for rule in rules]}
