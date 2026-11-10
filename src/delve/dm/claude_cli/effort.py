"""ttrpg2's `auto` effort: cheap effort for the many routine beats, full effort where the hard rules bite.

Measured in ttrpg2, about 88% of the generated tokens are thinking, and low effort answered in a fifth of the time.
It errs high: a wrongly cheap beat can railroad, a wrongly dear one only costs seconds.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from delve.domain.settings import Effort

# Above this length a message reads as a multi-step plan, not a single action.
PLAN_CHARS = 300

# Delve's own notes to the DM, before the player's words (`delve.play.table.BEGIN_SESSION`): not the player's, so
# not judged. The session start's is ~280 characters, and made every session's first act read as a plan.
HIDDEN_NOTE = re.compile(r"^\s*\[Not from the player[^\]]*\]\s*")

# Words that mark a beat where the procedure matters: staged plans, social manoeuvring, a spell or a save.
HIGH_EFFORT_MARKERS = (
    "ambush", "argue", "bargain", "barter", "bluff", "cast", "convince",
    "council", "deceive", "disguise", "distract", "haggle", "intimidate",
    "lie to", "negotiate", "persuade", "plan", "pretend", "ritual", "sneak",
    "surrender", "threaten", "trap", "trick",
)  # fmt: skip


@dataclass(frozen=True)
class TurnContext:
    """What the effort and the reset need to know of the campaign at a beat: a live fight, and the NPCs' names."""

    in_combat: bool = False
    npc_names: tuple[str, ...] = ()


def _labels(name: str) -> set[str]:
    """How a message may name an NPC: its full name, or its first name when longer than three letters."""
    label = name.strip().lower()
    if not label:
        return set()
    first = label.split()[0]
    return {label, first} if len(first) > 3 else {label}


def auto_effort(message: str, ctx: TurnContext) -> Effort:
    """High in a fight, for a long message or a marker word, or when two or more NPCs are named; low otherwise."""
    if ctx.in_combat:
        return Effort.HIGH
    low = HIDDEN_NOTE.sub("", message or "").lower()
    if len(low) >= PLAN_CHARS or any(marker in low for marker in HIGH_EFFORT_MARKERS):
        return Effort.HIGH
    named = [name for name in ctx.npc_names if any(label in low for label in _labels(name))]
    return Effort.HIGH if len(named) >= 2 else Effort.LOW


def turn_effort(chosen: Effort | None, message: str, ctx: TurnContext) -> Effort | None:
    """The `--effort` of this beat: the Preferences choice, with `auto` decided now. None leaves the CLI's default."""
    return auto_effort(message, ctx) if chosen is Effort.AUTO else chosen
