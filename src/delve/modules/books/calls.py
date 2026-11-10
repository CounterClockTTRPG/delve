"""What the steps that call Claude share: running calls together, and the error none of them may turn into a warning.

A module of its own so that `dedupe`, `campaign` and `sandbox` can use them without importing `convert`.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any


class Halt(Exception):
    """A failure that stops the whole conversion where it is. The steps that keep a module coming when one call fails
    (classifying a page, reading a text's entities, grouping doubles, reading the metadata) raise it on instead of
    making it a warning: a thorough conversion's pause at the usage limit (`thorough.pieces.Paused`) is one, and a
    stage that swallowed it would be done with a poorer module rather than resumed once the limit resets."""


async def all_of[T](calls: list[Coroutine[Any, Any, T]]) -> list[T]:
    """The calls' results in order. The first that fails cancels the others, and is raised once they have stopped,
    so no call goes on asking Claude, unrecorded, for a job that has already failed."""
    try:
        async with asyncio.TaskGroup() as group:
            tasks = [group.create_task(call) for call in calls]
    except BaseExceptionGroup as failed:
        raise failed.exceptions[0] from None
    return [task.result() for task in tasks]
