"""A refused request (`PlayError`) as the HTTP error a route raises: one shape and one choice of status for every route.

The body is `{"error", "hint"}`, the hint only when there is one: the app's error handler answers a dict detail as it
is, and the browser reads `error` (and `hint`, where it shows one) from it. The status says what refused it: 401 for a
visitor where an account is needed, 403 without the right, 404 for something unknown, 409 for the state, a talk
picture's own status, and 422 for everything else. A route may still name the status itself, for a refusal that means
more there (429 for a used-up allowance, 502 for a model that failed).
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from delve.play import accounts, board, join_requests, seats
from delve.play.context import NotFound, PlayError
from delve.play.talk_pictures import TalkPictureRefused

STATUSES: tuple[tuple[type[PlayError], int], ...] = (
    (board.NeedsAccount, 401),
    (board.BoardRefused, 403),
    (seats.NotAllowed, 403),
    (NotFound, 404),
    (board.BoardConflict, 409),
    (accounts.AccountConflict, 409),
    (seats.SeatConflict, 409),
    (join_requests.RequestConflict, 409),
)
"""The status of each kind of refusal, the first that matches; `NeedsAccount` is a `BoardRefused`, so it comes first."""


def status_of(error: PlayError) -> int:
    if isinstance(error, TalkPictureRefused):
        return error.status
    return next((status for kind, status in STATUSES if isinstance(error, kind)), 422)


def refusal(error: PlayError, status: int | None = None) -> HTTPException:
    """The HTTP error for `error`: `{"error", "hint"}`, with `status`, or else the one its kind has (`STATUSES`)."""
    detail: dict[str, Any] = {"error": error.message}
    if error.hint:
        detail["hint"] = error.hint
    return HTTPException(status_code=status if status is not None else status_of(error), detail=detail)
