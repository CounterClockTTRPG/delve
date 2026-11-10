"""The dice a tool row shows, for each seat (DEL-270).

A tool row keeps the ids of the rolls its call made (`table._with_dice`; a batch's steps each their own), and a
check the DM marked `secret`. The story turns them into what a seat may read of them, here, on the server: never the
ids, a modifier, a target number or a DC (they would give away an AC or a THAC0), only who rolled, what for, the dice
and the faces, and their total without the modifier.

- The host sees every roll of every row.
- Every other seat sees the party's own rolls: those of a PC of the campaign, of the party's side (`side:party`) and
  the party's surprise. Never a roll of the DM's bookkeeping (`BOOKKEEPING`: the weather, wandering encounters,
  treasure, the merchant's stock, hit points), whoever rolled it, nor a `secret` check's. The enemies' dice, any
  other actor's (a monster `mon_<n>`, the enemy side, an NPC, or none: the DM's own free roll), are behind the screen
  unless the table's `enemy_dice` option is `open`. With the table's `show_dice` off (DEL-280), none: the story is
  in words alone for every seat but the host's.
- A player or an observer, who sees no tool rows (walkthrough fixes Task 5), sees a row that has dice it may read, and
  of a batch only those steps: the row is where the dice show. A refused row stays the host's.

A row from before this has no ids and shows no dice. An id whose roll was rolled back with its call shows nothing.
"""

from __future__ import annotations

import re
from typing import Any

from delve.dice import BadNotation, Roll, parse
from delve.dm.tools.redact import player_row
from delve.domain.campaigns import SeatRole
from delve.play.audience import roles_for
from delve.storage.interfaces import Storage

__all__ = ["BOOKKEEPING", "ENEMY_DICE", "SeatDice", "bookkeeping"]

ENEMY_DICE = ("screen", "open")
"""The table option `enemy_dice`: the enemies' dice behind the screen (the default) or in the open."""

BOOKKEEPING = re.compile(r"^(weather:|encounter:|treasure:|merchant |hp$)")
"""The purposes of the DM's own bookkeeping, which no seat but the host's sees, whoever rolled them."""

FREE_ROLL = "roll"
"""The DM's free roll, whose purpose is the DM's own words."""

# Delve's own purposes, as the word a seat reads (`dice.what.<word>` in the web app) and, after a colon, a detail.
_WORDS = {
    "attack": "attack",
    "damage": "damage",
    "initiative": "initiative",
    "save": "save",
    "ability": "ability",
    "skill": "skill",
    "system_shock": "system_shock",
    "resurrection": "resurrection",
    "reaction": "reaction",
    "morale": "morale",
    "surprise": "surprise",
    "turn": "turning",
    "weather": "weather",
    "encounter": "encounter",
    "treasure": "treasure",
    "merchant": "merchant",
    "hp": "hp",
}
_PARTY_SIDE = "side:party"
_ENEMY_SIDE = "side:enemy"


def bookkeeping(purpose: str) -> bool:
    return BOOKKEEPING.match(purpose) is not None


class SeatDice:
    """The tool rows of one campaign as a seat of `role` sees them, with their dice. It reads the rolls, the
    characters and the fights it needs once each."""

    def __init__(
        self, storage: Storage, campaign_id: str, role: SeatRole, enemy_dice: str = "screen", *, show_dice: bool = True
    ) -> None:
        self.storage = storage
        self.campaign_id = campaign_id
        self.role = role
        self.host = role == "host"
        self.enemies_open = enemy_dice == "open"
        self.show_dice = show_dice
        self._characters: dict[str, tuple[str, bool]] | None = None
        self._fights: dict[str, dict[str, str]] = {}

    def row(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        """The tool row as this seat sees it (`player_row`, with `dice` on the row and on each step that has some);
        None when the seat doesn't see it at all."""
        shown = player_row(payload)
        roles = roles_for("tool", payload) or ()
        rolls = self._rolls(payload)
        dice = self._lines(payload, FREE_ROLL if payload.get("name") == FREE_ROLL else None, rolls)
        if dice:
            shown["dice"] = dice
        steps = payload.get("steps")
        if isinstance(steps, list) and "steps" in shown:
            out = []
            for step, seen in zip([s for s in steps if isinstance(s, dict)], shown["steps"], strict=False):
                lines = self._lines(step, step.get("name"), rolls)
                if self.role not in roles and not lines:
                    continue  # a player's or observer's row shows only the steps it reads dice of
                out.append({**seen, **({"dice": lines} if lines else {})})
            shown["steps"] = out
            if not out:
                del shown["steps"]
        if self.role in roles:
            return shown
        if "failed" in shown or not (shown.get("dice") or shown.get("steps")):
            return None
        return shown

    def _rolls(self, payload: dict[str, Any]) -> dict[str, Roll]:
        ids = [*_ids(payload)]
        for step in payload.get("steps") or []:
            if isinstance(step, dict):
                ids += _ids(step)
        return self.storage.rolls.get_many(self.campaign_id, ids) if ids else {}

    def _lines(self, part: dict[str, Any], tool: str | None, rolls: dict[str, Roll]) -> list[dict[str, Any]]:
        secret = part.get("secret") is True
        lines = []
        for id in _ids(part):
            roll = rolls.get(id)
            if roll is None:
                continue
            if not self.host and not self._shown(roll, secret):
                continue
            lines.append(self._line(roll, tool == FREE_ROLL))
        return lines

    def _shown(self, roll: Roll, secret: bool) -> bool:
        """Whether a seat other than the host's reads this roll."""
        if not self.show_dice or secret or bookkeeping(roll.key.purpose):
            return False
        return self._party(roll) or self.enemies_open

    def _party(self, roll: Roll) -> bool:
        actor = roll.key.actor
        if actor == _PARTY_SIDE or (actor is None and roll.key.purpose == "surprise:party"):
            return True
        found = self.characters().get(actor or "")
        return found is not None and found[1]

    def _line(self, roll: Roll, free: bool) -> dict[str, Any]:
        """`{who, side, what, detail, dice, faces, total}`: who rolled (a name, else `side`: party, enemies or enemy),
        what for (a word of Delve's, or the DM's own words as `detail`), the dice without their modifier, every face
        rolled, and the total of those kept, also without it."""
        who, side = self._who(roll)
        what, detail = (None, roll.key.purpose) if free else _what(roll.key.purpose)
        return {
            "who": who,
            "side": side,
            "what": what,
            "detail": detail,
            "dice": _dice(roll),
            "faces": list(roll.faces),
            "total": sum(roll.kept),
        }

    def _who(self, roll: Roll) -> tuple[str | None, str | None]:
        actor = roll.key.actor
        if actor is None:
            if roll.key.purpose == "surprise:party":
                return None, "party"
            return (None, "enemies") if roll.key.purpose.startswith("surprise:") else (None, None)
        if actor == _PARTY_SIDE:
            return None, "party"
        if actor == _ENEMY_SIDE:
            return None, "enemies"
        found = self.characters().get(actor)
        if found is not None:
            return found[0], None
        if re.fullmatch(r"mon_\d+", actor):
            name = self._fight(roll.key.beat).get(actor)
            return (name, None) if name else (None, "enemy")
        if re.fullmatch(r"[a-z]+_[0-9a-f]{12}", actor):
            return None, "enemy"  # an id of something no longer there
        return actor, None  # the DM's own words, such as a morale check's group

    def characters(self) -> dict[str, tuple[str, bool]]:
        """The campaign's characters by id: their name, and whether it is a PC."""
        if self._characters is None:
            self._characters = {c.id: (c.name, c.kind == "pc") for c in self.storage.characters.list(self.campaign_id)}
        return self._characters

    def _fight(self, beat: str) -> dict[str, str]:
        """The combatants' names of the fight a roll's beat names (`<beat>/<combat id>`)."""
        _, _, fight = beat.partition("/")
        if not fight:
            return {}
        if fight not in self._fights:
            state = self.storage.combats.get(fight) or {}
            combatants = state.get("combatants") if isinstance(state, dict) else None
            self._fights[fight] = {
                id: str(c.get("name") or "")
                for id, c in (combatants.items() if isinstance(combatants, dict) else ())
                if isinstance(c, dict)
            }
        return self._fights[fight]


def _ids(part: dict[str, Any]) -> list[str]:
    rolls = part.get("rolls")
    return [id for id in rolls if isinstance(id, str)] if isinstance(rolls, list) else []


def _what(purpose: str) -> tuple[str | None, str | None]:
    """A purpose of Delve's as a word and a detail: `attack#2` is an attack, `save:paralysis_poison_death` a save
    (paralysis poison death), `skill:move_silently#the hall` a skill (move silently; the occasion is the DM's and
    stays out), `surprise:party` a surprise. One Delve doesn't know is its own words."""
    head = re.split(r"[:# ]", purpose, maxsplit=1)[0]
    word = _WORDS.get(head)
    if word is None:
        return None, purpose
    detail = None
    if head in ("save", "ability", "skill") and ":" in purpose:
        detail = purpose.split(":", 1)[1].split("#", 1)[0].replace("_", " ") or None
    return word, detail


def _dice(roll: Roll) -> str:
    """The roll's dice without their modifier: `d20`, `3d6`, `4d6dl1`."""
    try:
        notation = parse(roll.notation)
    except BadNotation:
        return f"{len(roll.faces)}d?" if len(roll.faces) > 1 else "d?"
    dice = f"{notation.count if notation.count > 1 else ''}d{notation.sides}"
    if notation.drop_lowest:
        dice += f"dl{notation.drop_lowest}"
    elif notation.keep_highest:
        dice += f"kh{notation.keep_highest}"
    return dice
