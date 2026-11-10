"""Initiative per combatant or per side, and ongoing actions (table voice and fixes Tasks B1.1 and B1.2), pure.

How it plays:

- **Per side** (`side` mode): one die for the party and its allies, one for the enemies; the lower roll acts first,
  and a tie means both sides act at once. Each combatant adds its own modifier to its side's roll (its casting time,
  its weapon's speed, the item it uses), so a long spell still lands later in the round.
- **Per combatant** (`combatant` mode, Delve's default): every character and monster rolls for itself and adds its
  own modifier.
- **Items** have fixed modifiers (`ITEM_MODIFIERS`): a potion +4, a ring, a wand or another magic item +3, a stave +2,
  a rod +1; a scroll takes its spell's casting time.
- **Spells**: a casting time of a plain number is added to the roll. A spell of one round takes effect at the end of
  the round, after every other action; a longer one carries over and takes effect at the end of its last round. A
  turn is ten rounds.
- **Disruption**: a caster who is hit, or fails a saving throw, before the spell goes off loses it; so does a reader
  of a scroll, which is casting its spell. Nothing in the rules breaks a potion, an item or another action, so the DM
  rules on those with `interrupt`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

from delve.domain.reference import RulesetReference

OngoingKind = Literal["spell", "scroll", "potion", "item", "other"]
OngoingState = Literal["ongoing", "completed", "interrupted"]
Mode = Literal["combatant", "side"]

KINDS: tuple[str, ...] = ("spell", "scroll", "potion", "item", "other")
SPOILT_BY_HARM = ("spell", "scroll")
"""The kinds a hit or a failed saving throw breaks: a spell, and a scroll read."""

ITEM_MODIFIERS = {"potion": 4, "ring": 3, "rod": 1, "stave": 2, "wand": 3, "item": 3}
"""The initiative modifier of each kind of magic item; `item` is any other. A scroll takes its spell's casting time."""

ROUND_END = 10
"""The count of an action that takes effect at the end of the round, after every other: at least 10, the d10's
highest, and moved to the round's last count when initiative is rolled."""

UNKNOWN_CASTING = 5
"""A spell the reference doesn't know casts in 5, as before."""

_UNITS = {"rd": 1, "rds": 1, "rnd": 1, "rnds": 1, "round": 1, "rounds": 1, "turn": 10, "turns": 10}
_UNITS |= {"hr": 60, "hrs": 60, "hour": 60, "hours": 60, "day": 1440, "days": 1440}
_TIME = re.compile(r"^\s*(\d+)\s*([a-z]+)\.?", re.IGNORECASE)


@dataclass(frozen=True)
class Ongoing:
    """A combatant's long action: what, when it started, and when it completes (a count of a round)."""

    kind: OngoingKind
    what: str
    started_round: int
    completes_round: int
    started_count: int = 1
    completes_count: int | None = None
    """None until the round it completes in has its initiative rolled."""
    state: OngoingState = "ongoing"
    reason: str | None = None
    """Why it broke ("Mirela was hit")."""
    modifier: int | None = None
    """Its initiative modifier (`ROUND_END` for one that ends a round); None until it is looked up."""

    @property
    def ends_round(self) -> bool:
        """Takes effect at the end of a round, after every other action: it spans rounds, or takes one."""
        return self.completes_round > self.started_round or (self.modifier or 0) >= ROUND_END

    @property
    def under_way(self) -> bool:
        return self.state == "ongoing"


def ongoing_json(ongoing: Ongoing | None) -> dict[str, Any] | None:
    """The shape the DM's tools and the rounds' records give (B2 reads it)."""
    if ongoing is None:
        return None
    return {
        "kind": ongoing.kind,
        "what": ongoing.what,
        "started_round": ongoing.started_round,
        "started_count": ongoing.started_count,
        "completes_round": ongoing.completes_round,
        "completes_count": ongoing.completes_count,
        "state": ongoing.state,
        "reason": ongoing.reason,
    }


def casting_time(reference: RulesetReference | None, spell: str) -> tuple[str, int, bool]:
    """(casting time, its initiative modifier, found) of a spell: the exact name first, a wizard's spell first, as
    ttrpg2's `_spell_casting_time`. An unknown spell casts in 5."""
    rows = reference.spell(spell) if reference is not None else []
    if rows:
        exact = [r for r in rows if str(r.get("name", "")).casefold() == spell.strip().casefold()] or rows
        row = min(exact, key=lambda r: str(r.get("caster", "")).lower() != "wizard")
        init = row.get("casting_time_init")
        return str(row.get("casting_time") or ""), int(init) if init is not None else UNKNOWN_CASTING, True
    return "unknown", UNKNOWN_CASTING, False


def casting_rounds(text: str) -> int | None:
    """The rounds a casting time spans ("1 round" 1, "3 rds." 3, "1 turn" 10), or None for one in segments ("3")."""
    m = _TIME.match(str(text or ""))
    if not m:
        return None
    unit = _UNITS.get(m.group(2).lower())
    return int(m.group(1)) * unit if unit else None


def duration(kind: str, what: str, reference: RulesetReference | None) -> tuple[int, int]:
    """(the rounds it spans after this one, its count): a casting time of segments completes this round at the roll
    plus those segments; one round at the round's end (`ROUND_END`); N rounds N - 1 rounds later at its end. A potion
    or another item completes this round at the roll plus its item modifier.

    The units of the reference's `casting_time` win over its `casting_time_init`, which gives "2 rounds" as 2."""
    if kind in ("spell", "scroll"):
        spell = re.sub(r"^\s*scroll\s+of\s+", "", what, flags=re.IGNORECASE)
        text, segments, _ = casting_time(reference, spell)
        rounds = casting_rounds(text)
        if rounds is not None and rounds >= 1:
            return rounds - 1, ROUND_END
        return 0, min(segments, ROUND_END)
    if kind in ITEM_MODIFIERS:
        return 0, ITEM_MODIFIERS[kind]
    raise ValueError(f"no duration for {kind!r}")


def side_of(side: str) -> str:
    """The side a combatant rolls with in `side` mode: the party and its allies are one."""
    return "enemy" if side == "enemy" else "party"
