"""A generated module's pictures (DEL-347): handouts, so that a person or a place looks the same every time.

One call asks Claude to choose at most the organiser's limit from the finished module, with a brief for the painter and
a description for the DM. Then `paint`, handed in, paints each once, a few at a time, into an attachment for the players,
which `show_image` shows as it does an imported module's. Pictures are a bonus on a module that stands without them: a
choice that can't be read after one retry, a failed call or a failed painting is a `picture-not-painted` warning.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from delve.modules.books.campaign import _asked, _object
from delve.modules.books.convert import Complete, Progress
from delve.modules.books.generate import Unreadable
from delve.modules.books.sketch import fill, prompt
from delve.modules.dscn import sha256, slugify
from delve.modules.source import Attachment, ModuleSource, Warning

MAX_PICTURES = 12
"""The most pictures a module may ask for."""
PICTURE_NOT_PAINTED = "picture-not-painted"
PAINTERS_AT_ONCE = 3
MAX_MODULE_CHARS = 400_000
"""How much of a module the choice is made from: all of any module, and the start of a vast campaign."""
PAINTED_TYPES = frozenset({"image/png", "image/jpeg", "image/webp"})
"""What a painting may be: what any image model answers. Anything else isn't shown to the players."""
PERSON_ASPECT = "1:1"

Paint = Callable[["Planned"], Awaitable[tuple[bytes, str]]]
"""Paints a planned picture: its bytes and their media type."""


@dataclass(frozen=True)
class Planned:
    id: str
    brief: str
    description: str
    aspect: str
    """The ratio it is painted in; empty is the painter's own for a scene."""


def _module_text(source: ModuleSource) -> str:
    texts = "\n\n".join(text.markdown for text in source.texts)
    people = json.dumps(source.entities.get("npcs", []), ensure_ascii=False)
    return f"{texts}\n\nThe module's NPCs, as JSON:\n\n{people}"[:MAX_MODULE_CHARS]


def _text(raw: dict[str, Any], name: str) -> str:
    value = raw.get(name)
    return value.strip() if isinstance(value, str) else ""


def _read(limit: int) -> Callable[[str], list[Planned]]:
    def read(answer: str) -> list[Planned]:
        pictures = _object(answer).get("pictures")
        if not isinstance(pictures, list):
            raise Unreadable("it has no list of pictures")
        planned: list[Planned] = []
        ids: set[str] = set()
        for raw in pictures:
            if len(planned) == limit:
                break
            if not isinstance(raw, dict) or not _text(raw, "brief") or not _text(raw, "description"):
                continue
            base = slugify(_text(raw, "id") or _text(raw, "subject") or "picture")
            id, n = base, 2
            while id in ids:
                id, n = f"{base}-{n}", n + 1
            ids.add(id)
            aspect = PERSON_ASPECT if raw.get("kind") == "person" else ""
            planned.append(Planned(id, _text(raw, "brief"), _text(raw, "description"), aspect))
        return planned

    return read


async def plan_pictures(source: ModuleSource, limit: int, complete: Complete) -> tuple[list[Planned], list[Warning]]:
    """At most `limit` pictures chosen from the module; none and a warning when the choice can't be had."""
    asked = fill(prompt("generate-pictures.md"), module=_module_text(source), limit=str(limit))
    try:
        return await _asked(asked, complete, _read(limit)), []
    except Exception as error:  # noqa: BLE001 (the module stands without its pictures)
        return [], [Warning(PICTURE_NOT_PAINTED, f"No pictures were chosen: {error}.", None)]


async def paint_pictures(
    planned: list[Planned], paint: Paint, progress: Progress
) -> tuple[list[tuple[Attachment, bytes]], list[Warning]]:
    """The paintings as attachments for the players, in the planned order, and a warning for each that failed."""
    at_once = asyncio.Semaphore(PAINTERS_AT_ONCE)
    done = 0
    total = len(planned)
    warnings: list[Warning] = []
    progress("painting", 0, total)

    async def one(picture: Planned) -> tuple[Attachment, bytes] | None:
        nonlocal done
        async with at_once:
            try:
                data, media_type = await paint(picture)
                if media_type not in PAINTED_TYPES or not data:
                    raise ValueError(f"the painter answered {media_type or 'nothing'}")
            except Exception as error:  # noqa: BLE001 (one picture failing costs only that picture)
                reason = str(error) or type(error).__name__
                message = f"“{picture.description}” wasn't painted: {reason}."
                warnings.append(Warning(PICTURE_NOT_PAINTED, message, f"asset:{picture.id}"))
                made = None
            else:
                made = Attachment(picture.id, media_type, sha256(data), len(data), picture.description, "player"), data
        done += 1
        progress("painting", done, total)
        return made

    painted = await asyncio.gather(*(one(picture) for picture in planned))
    return [made for made in painted if made is not None], warnings
