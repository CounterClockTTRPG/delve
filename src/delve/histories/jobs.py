"""Histories written as jobs (carry-the-party-on plan Task 5): start, Write again, and the histories a stopped Delve
left behind.

A history is written by a conversion-runner job of the kind `history` (`runner.start_job`), titled "History: <old
campaign's name>" and targeting `{"campaign_id"}` (the new campaign's), so it has the runner's progress events,
cancel, `cost_usd` and the rule of one job at a time. Its writer is Preferences' `novel` choice (`NovelServices`).
Its steps are `condensing` (only for material longer than `MAX_PROMPT_CHARS`), then `writing`, whose `done/total`
count the two texts: the DM's first, then the table's, each from its own material, and each stored as it ends. The
events carry only the job's title, step and counts: never a text.

Both materials are read from the old campaign when the job starts. Carrying the party on never fails because of the
history: while another job runs, `start_history` stores a `failed` history with `RUNNING_MSG` instead of raising. A
failed job leaves the history `failed` with the job's message, a cancel with `CANCELLED`; a Delve that stops leaves
it `writing`, and the next start fails it with `ORPHANED` (`close_orphan_histories`). Texts already written stay
until new ones replace them. A history the host edited is replaced only with `overwrite`, and stays `edited` until
the job ends done, so an overwrite that fails halfway still asks to confirm the next time. The carried PCs (the
carry the new campaign came by) choose whose inventories and possessions the material holds.

Each change of a history while it is written (started, a text stored, done, failed) is published to its table as a
`history` event, `{campaign_id}` only, so each seat reads it again through its own route instead of asking every few
seconds (DEL-172).
"""

from __future__ import annotations

import asyncio
from dataclasses import replace

from delve.conversions import ConversionRunning, complete_with, finish, progress_for, start_job
from delve.conversions.runner import CONVERSION_TIMEOUT
from delve.domain.histories import History
from delve.histories.material import history_material
from delve.histories.writer import write_history
from delve.novels.jobs import NovelServices
from delve.novels.material import Material, condense, render
from delve.storage import Storage

__all__ = [
    "CANCELLED",
    "EDITED",
    "HISTORY_EVENT",
    "HISTORY_TIMEOUT",
    "ORPHANED",
    "RUNNING_MSG",
    "HistoryEdited",
    "close_orphan_histories",
    "history_changed",
    "start_history",
]

HISTORY_TIMEOUT = CONVERSION_TIMEOUT
"""Seconds one Claude call of a history may take."""
RUNNING_MSG = "A conversion is running: write the history again when it ends."
ORPHANED = "Delve stopped while writing."
CANCELLED = "The history's job was cancelled."
EDITED = "The history was edited: confirm to replace it."


HISTORY_EVENT = "history"


def history_changed(services: NovelServices, campaign_id: str) -> None:
    """Tell the table its history changed: ids only, for every seat may read its status."""
    data = {"campaign_id": campaign_id}
    services.conversions.publish(HISTORY_EVENT, data, scope="table", campaign_id=campaign_id)


class HistoryEdited(ValueError):
    """Write again on a history the host edited, without `overwrite`."""

    def __init__(self) -> None:
        super().__init__(EDITED)


# ----- starting -----


async def start_history(
    services: NovelServices, to_campaign_id: str, from_campaign_id: str, *, overwrite: bool = False
) -> History:
    """Write the history of `from_campaign_id` for `to_campaign_id`, the campaign its party was carried on into, and
    answer it (`writing`, or `failed` with `RUNNING_MSG` while another job runs). `KeyError` for no such campaign,
    `HistoryEdited` for an edited history without `overwrite`; a refused start changes no history."""
    storage = services.storage
    close_orphan_histories(storage)
    old = storage.campaigns.get(from_campaign_id)
    if old is None or storage.campaigns.get(to_campaign_id) is None:
        raise KeyError(from_campaign_id if old is None else to_campaign_id)
    before = storage.histories.get(to_campaign_id)
    if before is not None and before.edited and not overwrite:
        raise HistoryEdited()
    carry = storage.carries.origin(to_campaign_id)
    carried = carry.character_ids if carry is not None and carry.from_campaign_id == old.id else None
    dm, table = history_material(storage, old.id, "dm", carried), history_material(storage, old.id, "table", carried)
    history = before or History(to_campaign_id)
    spent = history.cost_usd or 0.0
    try:
        job = await start_job(
            services.conversions,
            "history",
            f"History: {old.name}",
            lambda live: _write(services, live, to_campaign_id, dm, table, spent),
            target={"campaign_id": to_campaign_id},
        )
    except ConversionRunning:
        stored = storage.histories.put(replace(history, status="failed", error=RUNNING_MSG))
    else:
        # The job's task runs from the next `await`: the history holds its job's id before the job first saves it.
        stored = storage.histories.put(replace(history, status="writing", error=None, conversion_id=job.id))
    history_changed(services, to_campaign_id)
    return stored


# ----- the job -----


async def _write(services: NovelServices, live, campaign_id: str, dm: Material, table: Material, spent: float) -> None:
    """The job's work: condense each material if it must, write the DM's text and then the table's, then end the job.
    The history is read again before each save, so it is never saved over a deleted campaign."""
    storage = services.storage
    progress = progress_for(services.conversions, live)
    complete = complete_with(services.conversions, live, services.writer, HISTORY_TIMEOUT)

    def save(**changes) -> History:
        current = storage.histories.get(campaign_id)
        if current is None:
            raise KeyError(campaign_id)
        cost = spent + (live.conversion.cost_usd or 0.0)
        saved = storage.histories.put(replace(current, cost_usd=cost or None, **changes))
        history_changed(services, campaign_id)
        return saved

    try:
        dm = await condense(dm, complete, progress)
        table = await condense(table, complete, progress)
        progress("writing", 0, 2)
        save(dm_md=await write_history(complete, render(dm), "dm"))
        progress("writing", 1, 2)
        save(table_md=await write_history(complete, render(table), "table"))
        progress("writing", 2, 2)
        save(status="done", error=None, edited=False)
        finish(services.conversions, live, result={"campaign_id": campaign_id})
    except asyncio.CancelledError:
        if live.cancelled:  # the owner's cancel; a Delve that stops leaves the history writing, for the next start
            _end(services, campaign_id, CANCELLED, spent + (live.conversion.cost_usd or 0.0))
        raise
    except Exception as error:
        _end(services, campaign_id, str(error) or type(error).__name__, spent + (live.conversion.cost_usd or 0.0))
        raise


def _end(services: NovelServices, campaign_id: str, error: str, cost: float) -> None:
    storage = services.storage
    current = storage.histories.get(campaign_id)
    if current is None:
        return
    try:
        storage.histories.put(replace(current, status="failed", error=error, cost_usd=cost or None))
    except KeyError:  # the campaign went between the read and the save
        return
    history_changed(services, campaign_id)


# ----- orphans -----


def close_orphan_histories(storage: Storage) -> list[History]:
    """Every `writing` history whose job isn't running (a Delve that stopped left it) becomes `failed` with
    `ORPHANED`, its texts kept. Answers the histories closed. At start, after `close_orphans`, and before each
    start."""
    closed = []
    for history in storage.histories.writing():
        job = storage.conversions.get(history.conversion_id) if history.conversion_id is not None else None
        if job is not None and job.status == "running":
            continue
        closed.append(storage.histories.put(replace(history, status="failed", error=ORPHANED)))
    return closed
