"""The dice each tool call rolled, from the tool host to the beat runner (DEL-270).

The tool host runs a call; the beat runner writes its story row later, from the DM's event stream, where it sees the
call's name and arguments and its result, never the host's dice. The result goes to the DM, who mustn't pay for a
list of roll ids it doesn't need (DEL-79 took one out of `combat_round`'s). So the host puts the ids of the rolls each
call returned here, keyed by the campaign, the beat, the tool's name and its arguments, and the runner takes them when
it writes the row. Calls alike in all four wait in a queue, in the order they ran. It is in memory and bounded: a
beat's leftovers (calls that make no row, a Delve restarted mid-beat) are forgotten at its end or pushed out by newer
ones; a row whose dice were lost shows none.
"""

from __future__ import annotations

import json
import threading
from collections import OrderedDict, deque
from typing import Any

__all__ = ["ROLLED", "CallDice", "Rolled"]

CallDice = dict[str, Any]
"""`{"rolls": [roll ids]}` for a call, or `{"steps": {step index: [roll ids]}}` for a batch's."""

LIMIT = 2000
"""The most calls kept waiting, over every campaign; the oldest go first."""


def _key(campaign_id: str, beat: str, name: str, args: Any) -> tuple[str, str, str, str]:
    return campaign_id, beat, name, json.dumps(args, sort_keys=True, default=str)


class Rolled:
    """Calls' dice waiting for their rows: thread-safe, as the host runs calls in a thread pool."""

    def __init__(self, limit: int = LIMIT) -> None:
        self._limit = limit
        self._waiting: OrderedDict[tuple[str, str, str, str], deque[CallDice]] = OrderedDict()
        self._count = 0
        self._lock = threading.Lock()

    def put(self, campaign_id: str, beat: str, name: str, args: Any, dice: CallDice) -> None:
        """What the call `name(args)` of the campaign's beat rolled."""
        key = _key(campaign_id, beat, name, args)
        with self._lock:
            self._waiting.setdefault(key, deque()).append(dice)
            self._count += 1
            while self._count > self._limit and self._waiting:
                oldest = next(iter(self._waiting))
                queue = self._waiting[oldest]
                queue.popleft()
                self._count -= 1
                if not queue:
                    del self._waiting[oldest]

    def take(self, campaign_id: str, beat: str, name: str, args: Any) -> CallDice | None:
        """The dice of the earliest call `name(args)` of the beat not taken yet; None when none waits."""
        key = _key(campaign_id, beat, name, args)
        with self._lock:
            queue = self._waiting.get(key)
            if not queue:
                return None
            dice = queue.popleft()
            self._count -= 1
            if not queue:
                del self._waiting[key]
            return dice

    def forget(self, campaign_id: str, beat: str) -> None:
        """Drop what the beat's calls left: it has ended, and no row of it is written any more."""
        with self._lock:
            for key in [k for k in self._waiting if k[0] == campaign_id and k[1] == beat]:
                self._count -= len(self._waiting.pop(key))


ROLLED = Rolled()
"""The app's: one tool host and one table per process."""
