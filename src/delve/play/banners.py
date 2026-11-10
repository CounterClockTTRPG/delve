"""A campaign's banner (looks and banners spec, owner decisions 6 and 8): a wide painting of its module's world.

Making a campaign asks for it (`ask`), after the campaign's transaction, and never fails or waits because of it. The
banner is a `campaign_images` row of the kind `banner`, painted by `delve.play.images` with the scene's choice of
model. While the paid gate is closed for that model (`gate_open`), the row is `waiting`; when the gate opens (the host
turning paid images on, Preferences saved, or Delve starting), `wake` paints it, once.

The brief is built only from what any player may know: the module's title, its metadata `summary` and `description`
(player-safe by the schema) and the setting's title. The tone joins it when it is painted (`images.paint`). Never
keyed text, DM notes, entities or the campaign's story.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from delve.domain import new_id
from delve.domain.modules import ModuleBanner
from delve.domain.settings import Job
from delve.domain.world import CampaignImage
from delve.play import images
from delve.play.context import NotFound, PlayError
from delve.storage import Storage

if TYPE_CHECKING:
    from delve.play.table import AppServices

__all__ = [
    "DESCRIPTION_CHARS",
    "PAINTING_ALREADY",
    "ask",
    "brief",
    "current",
    "decide",
    "gate_open",
    "paint_again",
    "pending",
    "shown",
    "wake",
]

DESCRIPTION_CHARS = 600
PAINTING_ALREADY = "A banner is being painted already."

_HEADING = re.compile(r"^\s{0,3}#{1,6}\s*(.*?)\s*#*\s*$")
_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.*)$")
_IMAGE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_MARKS = re.compile(r"[*_`~]+|^\s*>\s?", re.MULTILINE)
_END = (".", "!", "?")

log = logging.getLogger(__name__)
_deciding: set[asyncio.Task] = set()  # the `decide` tasks under way, kept from the garbage collector


# ----- the brief -----


def brief(title: str, summary: str, description: str, setting: str, hint: str = "") -> str:
    """The painter's brief: the world of the module, in its setting, with its summary and the start of its description
    as plain text, and the hint as the emphasis. Empty parts and their punctuation are dropped."""
    head = "A wide cinematic landscape painting"
    if title.strip():
        head += f" of the world of {title.strip()}"
    if setting.strip():
        head += f", in {setting.strip()}"
    parts = [_sentence(head), _sentence(summary.strip()), _sentence(_cut(_plain(description)))]
    parts.append("No characters in the foreground, no text, no lettering.")
    hint = hint.strip().rstrip(".")
    if hint:
        parts.append(f"Emphasis: {hint}.")
    return " ".join(part for part in parts if part)


def _sentence(text: str) -> str:
    return text if not text or text.endswith(_END) else f"{text}."


def _plain(markdown: str) -> str:
    """Markdown as plain text: headings and emphasis lose their marks, links and images become their text, and a
    list's items become sentences."""
    lines = []
    for line in markdown.splitlines():
        if heading := _HEADING.match(line):
            line = heading.group(1)
        elif item := _ITEM.match(line):
            line = _sentence(item.group(1).strip())
        lines.append(line)
    text = _MARKS.sub("", _LINK.sub(r"\1", _IMAGE.sub(r"\1", "\n".join(lines))))
    return " ".join(text.split())


def _cut(text: str) -> str:
    """At most `DESCRIPTION_CHARS` of `text`, cut at a word."""
    if len(text) <= DESCRIPTION_CHARS:
        return text
    cut = text[: DESCRIPTION_CHARS + 1]
    cut = cut.rsplit(" ", 1)[0] if " " in cut else cut[:DESCRIPTION_CHARS]
    return cut.rstrip(" ,;:")


def _module_brief(storage: Storage, campaign_id: str, setting_title: str, hint: str) -> str:
    campaign = storage.campaigns.get(campaign_id)
    if campaign is None:
        raise NotFound(f"No campaign '{campaign_id}'.")
    module = storage.modules.get(campaign.module_id)
    metadata = module.metadata if module is not None else {}
    summary, description = (metadata.get(key) for key in ("summary", "description"))
    return brief(
        module.title if module is not None else "",
        summary if isinstance(summary, str) else "",
        description if isinstance(description, str) else "",
        setting_title,
        hint,
    )


# ----- asking -----


def gate_open(services: AppServices, campaign_id: str) -> bool:
    """Whether a banner may be painted now: the host turned paid images on, or the scene's model is free."""
    return images.paid_images(services.storage, campaign_id) or not services.image_paid(Job.IMAGE_SCENE)


def ask(
    services: AppServices, campaign_id: str, setting_title: str, hint: str = "", *, decide_later: bool = False
) -> CampaignImage:
    """A new banner row for the campaign, replacing its waiting ones: `painting`, and scheduled, when the gate is
    open; else `waiting`, for `wake`. Called in the event loop, which paints it. With `decide_later` it never reads
    the gate, which may ask a provider over the network: the row is `waiting`, and a task reads the gate off the loop
    and paints it if it is open (`decide`)."""
    storage = services.storage
    prompt = _module_brief(storage, campaign_id, setting_title, hint)
    status = "waiting" if decide_later or not gate_open(services, campaign_id) else "painting"
    with storage.transaction():
        for waiting in storage.campaign_images.list(campaign_id, kind=images.BANNER, status="waiting"):
            storage.campaign_images.delete(waiting.id)
        image = storage.campaign_images.put(
            CampaignImage(new_id("img"), campaign_id, images.BANNER, status=status, prompt=prompt)
        )
    if status == "painting":
        images.schedule(services, image.id)
    elif decide_later:
        task = asyncio.create_task(_decide_logged(services, campaign_id))
        _deciding.add(task)
        task.add_done_callback(_deciding.discard)
    return image


async def decide(services: AppServices, campaign_id: str) -> list[str]:
    """Read the campaign's gate in a worker thread, and paint its waiting banners if it is open; the ids
    scheduled."""
    if not await asyncio.to_thread(gate_open, services, campaign_id):
        return []
    woken = _start_waiting(services, campaign_id)
    for image_id in woken:
        images.schedule(services, image_id)
    return woken


async def _decide_logged(services: AppServices, campaign_id: str) -> None:
    try:
        await decide(services, campaign_id)
    except Exception:  # the banner stays waiting, for `wake`
        log.exception("deciding the banner of %s failed", campaign_id)


def paint_again(services: AppServices, campaign_id: str, setting_title: str, hint: str = "") -> CampaignImage:
    """The organiser's "Paint again": `PlayError` with the paid hint while the gate is closed, or while one of the
    campaign's banners is being painted; otherwise a new banner (`ask`). The old one stays until the new one lands."""
    if not gate_open(services, campaign_id):
        raise PlayError(images.PAID_OFF, images.PAID_HINT)
    if services.storage.campaign_images.list(campaign_id, kind=images.BANNER, status="painting"):
        raise PlayError(PAINTING_ALREADY)
    return ask(services, campaign_id, setting_title, hint)


def wake(services: AppServices, campaign_id: str | None = None) -> list[str]:
    """Paint the waiting banners, of the campaign or of every one, whose gate is open now; the ids scheduled. A row
    that is no longer `waiting` is left alone, so calling it again paints nothing twice."""
    storage = services.storage
    ids = [campaign_id] if campaign_id is not None else [c.id for c in storage.campaigns.list()]
    woken: list[str] = []
    for cid in ids:
        if storage.campaign_images.list(cid, kind=images.BANNER, status="waiting") and gate_open(services, cid):
            woken += _start_waiting(services, cid)
    for image_id in woken:
        images.schedule(services, image_id)
    return woken


def _start_waiting(services: AppServices, campaign_id: str) -> list[str]:
    """Mark the campaign's banners that are still `waiting` as `painting`; their ids, to schedule."""
    storage = services.storage
    waiting = storage.campaign_images.list(campaign_id, kind=images.BANNER, status="waiting")
    if not waiting:
        return []
    started: list[str] = []
    with storage.transaction():
        for image in waiting:
            stored = storage.campaign_images.get(image.id)
            if stored is not None and stored.status == "waiting":
                storage.campaign_images.put(replace(stored, status="painting"))
                started.append(stored.id)
    services.publish("campaigns", {"id": campaign_id})
    return started


# ----- reading -----


@dataclass(frozen=True)
class Shown:
    """The banner a campaign shows: its own (`from_module` false, `id` its image row), or, while it has none, its
    module's (DEL-123: `id` names that picture, so a page's address changes with it)."""

    id: str
    blob: str
    mime: str
    from_module: bool


def shown(storage: Storage, campaign_id: str) -> Shown | None:
    """The campaign's banner as its table and pages show it: its own `current` one, else its module's picture, else
    None."""
    campaign = None
    own = current(storage, campaign_id)
    if own is None or own.blob is None:
        campaign = storage.campaigns.get(campaign_id)
    module = storage.modules.get(campaign.module_id) if campaign is not None else None
    return shown_of(own, module.banner if module is not None else None)


def shown_of(own: CampaignImage | None, module_banner: ModuleBanner | None) -> Shown | None:
    """The banner shown, from the campaign's `current` one and its module's: for a list of campaigns, which reads them
    for all at once (DEL-172)."""
    if own is not None and own.blob is not None:
        return Shown(own.id, own.blob, own.mime or "image/png", False)
    if module_banner is None or module_banner.blob is None:
        return None
    return Shown(f"mod-{module_banner.blob[:12]}", module_banner.blob, module_banner.mime or "image/webp", True)


def module_has_banner(storage: Storage, campaign_id: str) -> bool:
    """Whether the campaign's module has a banner picture, which the campaign shows until it paints its own."""
    found = shown(storage, campaign_id)
    return found is not None and found.from_module


def current(storage: Storage, campaign_id: str) -> CampaignImage | None:
    """The campaign's banner: its newest `done` banner row."""
    done = storage.campaign_images.list(campaign_id, kind=images.BANNER, status="done")
    return done[-1] if done else None


def pending(storage: Storage, campaign_id: str) -> CampaignImage | None:
    """The newest banner row newer than the current one that isn't `done`: `waiting`, `painting` or `failed`."""
    rows = storage.campaign_images.list(campaign_id, kind=images.BANNER)
    shown = current(storage, campaign_id)
    newer = rows[next(i for i, r in enumerate(rows) if r.id == shown.id) + 1 :] if shown is not None else rows
    return next((r for r in reversed(newer) if r.status != "done"), None)
