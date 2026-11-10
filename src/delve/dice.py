"""Dice: notation with limits, logged rolls, and no re-rolls within a beat (spec §6.5).

Every roll in Delve goes through `Dice`, and this is the only module that may import `random`. A roll is logged with
its notation, faces, total and key (beat, actor, purpose, target, combat round). Asking for a roll whose key is already
in the log returns the stored roll: within one beat the same roll is never made twice. The combat round is part of the
key, so a beat that covers several rounds still rolls fresh each round.

`watching()` collects every roll that any `Dice` returns while it is open, new or stored (DEL-270): the tool host
watches each call, so the story can show the dice a tool row rolled, a roll asked again within the beat included.
"""

from __future__ import annotations

import random
import re
import secrets
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal, Protocol, overload, runtime_checkable

from delve.domain import new_id

MAX_DICE = 100
MAX_SIDES = 1000
MAX_TIMES = 20
MAX_TABLE = 1_000_000

NOTATION_HINT = "Use NdX with an optional dlK (drop the lowest K), khK (keep the highest K) and ±M, e.g. 4d6dl or d%."


class BadNotation(ValueError):
    """Dice notation that can't be parsed or rolled; `hint` says what would be."""

    def __init__(self, message: str, hint: str = NOTATION_HINT) -> None:
        self.hint = hint
        super().__init__(message)


class NotationTooLarge(BadNotation):
    """More than 100 dice, more than 1000 sides, or a roll repeated more than 20 times."""

    def __init__(self, message: str) -> None:
        super().__init__(message, f"At most {MAX_DICE} dice of at most {MAX_SIDES} sides, {MAX_TIMES} times.")


@dataclass(frozen=True)
class Notation:
    text: str
    count: int
    sides: int
    drop_lowest: int = 0
    keep_highest: int = 0
    modifier: int = 0


_NOTATION = re.compile(r"^(\d*)d(\d+|%)(?:dl(\d*)|kh(\d*))?((?:[+-]\d+)*)$")


def parse(notation: str) -> Notation:
    """`NdX`, `dX` (one die), `NdXdlK` (drop the lowest K, `dl` alone is one), `NdXkhK`, `d%`, and any `±M`.

    Case and spaces don't matter; `text` keeps the notation as given, stripped."""
    text = notation.strip()
    match = _NOTATION.match(text.lower().replace(" ", ""))
    if not match:
        raise BadNotation(f"Cannot parse dice notation: {text}")
    count_text, sides_text, drop_text, keep_text, modifier_text = match.groups()
    if len(count_text) > 6 or len(sides_text) > 6:
        raise NotationTooLarge(f"Too many dice or sides: {text}")
    count = int(count_text) if count_text else 1
    sides = 100 if sides_text == "%" else int(sides_text)
    if count > MAX_DICE or sides > MAX_SIDES:
        raise NotationTooLarge(f"Too many dice or sides: {text}")
    if sides < 1:
        raise BadNotation(f"A die needs at least one side: {text}")
    drop = (int(drop_text) if drop_text else 1) if drop_text is not None else 0
    keep = (int(keep_text) if keep_text else 1) if keep_text is not None else 0
    if drop and drop >= count > 1 or drop > count:
        raise BadNotation(f"Can't drop {drop} of {count} dice: {text}")
    if keep > count:
        raise BadNotation(f"Can't keep {keep} of {count} dice: {text}")
    modifier = sum(int(part) for part in re.findall(r"[+-]\d+", modifier_text))
    return Notation(text, count, sides, drop, keep, modifier)


@dataclass(frozen=True)
class RollKey:
    """What makes a roll the same roll: one beat, one actor, one purpose, one target, one combat round."""

    beat: str
    actor: str | None
    purpose: str
    target: str | None = None
    combat_round: int | None = None


@dataclass(frozen=True)
class Roll:
    id: str
    key: RollKey
    notation: str
    faces: tuple[int, ...]
    """Every die rolled, in order, the dropped ones included."""
    kept: tuple[int, ...]
    modifier: int
    total: int
    at: str

    @property
    def dropped(self) -> tuple[int, ...]:
        rest = list(self.kept)
        dropped = []
        for face in self.faces:
            if face in rest:
                rest.remove(face)
            else:
                dropped.append(face)
        return tuple(dropped)


@runtime_checkable
class RollLog(Protocol):
    """The dice log of every campaign. Storage implements it; `MemoryRollLog` is for pure code and tests."""

    def find(self, campaign_id: str, key: RollKey) -> Roll | None: ...

    def record(self, campaign_id: str, roll: Roll) -> None: ...


@dataclass
class MemoryRollLog:
    rolls: list[tuple[str, Roll]] = field(default_factory=list)

    def find(self, campaign_id: str, key: RollKey) -> Roll | None:
        return next((roll for cid, roll in self.rolls if cid == campaign_id and roll.key == key), None)

    def record(self, campaign_id: str, roll: Roll) -> None:
        self.rolls.append((campaign_id, roll))


class Rng(Protocol):
    def randint(self, a: int, b: int) -> int:
        """A whole number from `a` to `b`, both included."""
        ...


class SystemRng:
    """The operating system's randomness, for play."""

    def randint(self, a: int, b: int) -> int:
        return a + secrets.randbelow(b - a + 1)


class SeededRng:
    """Deterministic, for scripted sessions and tests."""

    def __init__(self, seed: int) -> None:
        self._random = random.Random(seed)

    def randint(self, a: int, b: int) -> int:
        return self._random.randint(a, b)


class ScriptExhausted(AssertionError):
    """A `ScriptedRng` was asked for a die it has no value for, or one its next value doesn't fit."""


class ScriptedRng:
    """Fixed values, for tests. `calls` records the `(a, b)` of every die asked for, in order."""

    def __init__(self, values: Iterable[int]) -> None:
        self.values = list(values)
        self.calls: list[tuple[int, int]] = []

    def randint(self, a: int, b: int) -> int:
        self.calls.append((a, b))
        if not self.values:
            raise ScriptExhausted(f"no scripted value for randint({a}, {b}), call #{len(self.calls)}")
        if not a <= self.values[0] <= b:
            raise ScriptExhausted(f"scripted {self.values[0]} doesn't fit randint({a}, {b})")
        return self.values.pop(0)

    def assert_done(self) -> None:
        if self.values:
            raise ScriptExhausted(f"unused scripted values: {self.values}")


def _kept(faces: list[int], notation: Notation) -> list[int]:
    if notation.drop_lowest and len(faces) > 1:
        drop = sorted(range(len(faces)), key=lambda i: faces[i])[: notation.drop_lowest]
        return [face for i, face in enumerate(faces) if i not in drop]
    if notation.keep_highest:
        keep = sorted(range(len(faces)), key=lambda i: -faces[i])[: notation.keep_highest]
        return [face for i, face in enumerate(faces) if i in keep]
    return faces


_watched: ContextVar[list[Roll] | None] = ContextVar("delve_watched_rolls", default=None)


@contextmanager
def watching() -> Iterator[list[Roll]]:
    """The rolls every `Dice` returns while this is open, in order, new and stored alike (DEL-270): the fight's own
    `Dice` and those of travel too, as each is made on the same thread. A roll asked twice is listed twice."""
    seen: list[Roll] = []
    token = _watched.set(seen)
    try:
        yield seen
    finally:
        _watched.reset(token)


def _watch(roll: Roll) -> Roll:
    seen = _watched.get()
    if seen is not None:
        seen.append(roll)
    return roll


class Dice:
    """The dice of one campaign in one beat."""

    def __init__(self, rng: Rng, log: RollLog, campaign_id: str, beat: str) -> None:
        self.rng = rng
        self.log = log
        self.campaign_id = campaign_id
        self.beat = beat

    @overload
    def roll(
        self,
        notation: str,
        *,
        purpose: str,
        actor: str | None = None,
        target: str | None = None,
        combat_round: int | None = None,
        times: Literal[1] = 1,
    ) -> Roll: ...

    @overload
    def roll(
        self,
        notation: str,
        *,
        purpose: str,
        actor: str | None = None,
        target: str | None = None,
        combat_round: int | None = None,
        times: int,
    ) -> Roll | list[Roll]: ...

    def roll(
        self,
        notation: str,
        *,
        purpose: str,
        actor: str | None = None,
        target: str | None = None,
        combat_round: int | None = None,
        times: int = 1,
    ) -> Roll | list[Roll]:
        """One roll, or with `times > 1` a list whose keys have the purposes `<purpose>#1` … `#times`.

        A roll whose key is already in the log is the stored roll: nothing is rolled again."""
        parsed = parse(notation)
        if times < 1:
            raise BadNotation(f"times must be >= 1 (got {times})", "Use times from 1 to 20.")
        if times > MAX_TIMES:
            raise NotationTooLarge(f"times must be at most {MAX_TIMES} (got {times})")
        if times == 1:
            return self._one(parsed, RollKey(self.beat, actor, purpose, target, combat_round))
        return [
            self._one(parsed, RollKey(self.beat, actor, f"{purpose}#{i}", target, combat_round))
            for i in range(1, times + 1)
        ]

    def d(
        self,
        sides: int,
        *,
        purpose: str,
        actor: str | None = None,
        target: str | None = None,
        combat_round: int | None = None,
    ) -> Roll:
        """One die of `sides` sides."""
        return self._one(parse(f"1d{sides}"), RollKey(self.beat, actor, purpose, target, combat_round))

    def table(
        self,
        n: int,
        *,
        purpose: str,
        actor: str | None = None,
        target: str | None = None,
        combat_round: int | None = None,
    ) -> Roll:
        """One exact die 1…n to pick an entry of a table, such as an encounter table of 27136 lines.

        The notation limits are for notation the DM asks for; this die is never reachable from it. It is logged and
        keyed like every other roll. At most 1,000,000 sides."""
        if n > MAX_TABLE:
            raise NotationTooLarge(f"A table die has at most {MAX_TABLE} sides (got {n})")
        if n < 1:
            raise BadNotation(f"A die needs at least one side (got {n})")
        return self._one(Notation(f"1d{n}", 1, n), RollKey(self.beat, actor, purpose, target, combat_round))

    def _one(self, notation: Notation, key: RollKey) -> Roll:
        stored = self.log.find(self.campaign_id, key)
        if stored is not None:
            return _watch(stored)
        faces = [self.rng.randint(1, notation.sides) for _ in range(notation.count)]
        kept = _kept(faces, notation)
        roll = Roll(
            id=new_id("roll"),
            key=key,
            notation=notation.text,
            faces=tuple(faces),
            kept=tuple(kept),
            modifier=notation.modifier,
            total=sum(kept) + notation.modifier,
            at=datetime.now(UTC).isoformat(),
        )
        self.log.record(self.campaign_id, roll)
        return _watch(roll)


def roll_json(roll: Roll) -> dict[str, Any]:
    """A roll as the DM's tools and the story answer it."""
    return {
        "id": roll.id,
        "purpose": roll.key.purpose,
        "actor": roll.key.actor,
        "target": roll.key.target,
        "combat_round": roll.key.combat_round,
        "notation": roll.notation,
        "faces": list(roll.faces),
        "total": roll.total,
    }
