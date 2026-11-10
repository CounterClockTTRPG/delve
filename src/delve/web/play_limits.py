"""How long, and how often, a seat may speak at the table (DEL-154, audit finding 7).

Each of Act, Ask the DM and table talk may cost a Claude call: a question is a side pass, and an act or a line in
another language is translated into English. Without limits one seat could drain the owner's Claude usage window, so
the words have a length (`ACT_CHARS`, `ASK_CHARS`, `TALK_CHARS`, and `HINT_CHARS` for Paint this scene's hint),
checked on the trimmed text before anything is sent anywhere (422), and each seat a number of acts, questions, lines
of talk and scenes in a sliding window (`SeatThrottle.LIMITS`), past which it waits (429 with `Retry-After`). The
lengths fit real play: an act of a few paragraphs, a question of one, a chat line with a quote in it. The windows let
a seat ask a run of rules questions, or chat in bursts; only a loop meets them. A refused request never counts. The
counts are in memory, as the login throttle's are (`delve.web.routes.accounts.LoginThrottle`): a restart forgets them.
The web's composer mirrors the lengths (`web/src/play/limits.ts`).
"""

from __future__ import annotations

import math
import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable
from typing import ClassVar, Literal

from fastapi import HTTPException

__all__ = ["ACT_CHARS", "ASK_CHARS", "HINT_CHARS", "TALK_CHARS", "SeatThrottle", "check_length", "seat_throttle"]

ACT_CHARS = 4000
ASK_CHARS = 2000
TALK_CHARS = 1500
HINT_CHARS = 500
FEWER_WORDS = "Say it in fewer words, or in two."

Spoken = Literal["act", "ask", "talk", "scene"]
TOO_FAST: dict[Spoken, str] = {
    "act": "You're acting fast: act again in {wait} seconds.",
    "ask": "You're asking the DM fast: ask again in {wait} seconds.",
    "talk": "You're talking fast: say it again in {wait} seconds.",
    "scene": "You're asking for scenes fast: ask again in {wait} seconds.",
}


def check_length(text: str, limit: int, what: str) -> None:
    """422 when `text` is longer than `limit` characters, saying so in `what`'s words ("An act is")."""
    if len(text) > limit:
        raise HTTPException(status_code=422, detail={"error": f"{what} at most {limit} characters.", "hint": FEWER_WORDS})


class SeatThrottle:
    """Each seat's acts, questions, lines of talk and scenes, in a sliding window per kind: `LIMITS[kind]` is `(how
    many, in how many seconds)`. `clock` is patched in tests."""

    LIMITS: ClassVar[dict[Spoken, tuple[int, int]]] = {
        "act": (20, 5 * 60),
        "ask": (10, 5 * 60),
        "talk": (20, 60),
        "scene": (5, 5 * 60),
    }

    def __init__(self) -> None:
        self.clock: Callable[[], float] = time.monotonic
        self._said: defaultdict[tuple[str, Spoken], deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def take(self, seat_id: str, kind: Spoken) -> None:
        """Count one of `kind` for the seat; 429, uncounted, with how long to wait, while its window is full."""
        count, window = self.LIMITS[kind]
        with self._lock:
            now = self.clock()
            said = self._said[(seat_id, kind)]
            while said and said[0] <= now - window:
                said.popleft()
            if len(said) >= count:
                wait = max(1, math.ceil(said[0] + window - now))
                raise HTTPException(
                    status_code=429,
                    detail={"error": TOO_FAST[kind].format(wait=wait)},
                    headers={"Retry-After": str(wait)},
                )
            said.append(now)


def seat_throttle(app) -> SeatThrottle:
    """The app's seat throttle, made on first use."""
    found = getattr(app.state, "seat_throttle", None)
    if found is None:
        found = app.state.seat_throttle = SeatThrottle()
    return found
