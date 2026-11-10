"""Thorough conversion (thorough conversion Task 4; spec docs/superpowers/specs/2026-10-23-thorough-conversion-design.md):
a PDF converted the way the hand QA passes did it, by agents working in a lasting job folder (`Workspace`), piece by
piece (`pieces.run_piece`), the pieces' ends recorded in the folder so the job pauses and resumes instead of failing.

A thorough job is a `pdf` conversion whose `target` is `{"thorough": true, "folder"}`, and it holds the one running
slot as every job does. Its pipeline (`run_thorough`, Task 6) runs on the workspace; how it ends:

- done: the pipeline made the module (Task 7);
- `Paused`, the usage limit: the job is `paused` with the reset time, and resumes by itself `pieces.resume_delay`
  after it (`ConversionServices.resumes`; another job running then puts it off by `RESUME_UNKNOWN`);
- any other error outside a piece: the job is `paused` with the error (`error`), its folder kept, for a resume after
  a fix; a thorough job never fails once its folder holds work;
- Delve stopping: the row stays `running`, and `close_orphans` pauses it at the next start (`DELVE_STOPPED`);
- paused by the organiser (`pause`): its agent sessions stop at once, and it is `paused` (`PAUSED_BY_ORGANISER`);
- cancelled: `runner.cancel` deletes its folder.

Every start goes through the queue (owner addition 2026-10-23): a job uploaded while the slot is taken is `queued`
with its book (`target.upload`), and its folder is made when it starts. `resume` puts a paused job back in the queue,
which starts it at once when the slot is free; it then runs the pipeline again on the same folder, finished stages
and pieces skipped, so nothing is redone or paid twice. At Delve's start every job Delve's stop paused goes back in
the queue (`resume_stopped`). `delve.conversions.runner` is imported as a module (it imports `workspace`, so names are looked up
when called)."""

from __future__ import annotations

import asyncio
import contextlib
import importlib
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from delve.conversions import runner
from delve.conversions.thorough import pieces
from delve.conversions.thorough.pieces import USAGE_LIMIT, Paused
from delve.conversions.thorough.workspace import DELVE_STOPPED, Workspace
from delve.domain.conversions import Conversion, ConversionMode
from delve.modules.books.pdf import ReadStopped

if TYPE_CHECKING:
    from delve.conversions.runner import ConversionServices, _Live

__all__ = [
    "NotPausable",
    "NotPaused",
    "Paused",
    "Pipeline",
    "Workspace",
    "pause",
    "restored",
    "resume",
    "resume_stopped",
    "schedule_resume",
    "start_thorough",
]

Pipeline = Callable[["ConversionServices", "_Live", Workspace], Awaitable[None]]
"""The stages run on a job's workspace (`pipeline.run_thorough`)."""


class NotPaused(ValueError):
    """A resume of a job that isn't a paused thorough job."""

    def __init__(self, id: str, message: str | None = None) -> None:
        super().__init__(message or f"The conversion {id} isn't paused.")


class NotPausable(ValueError):
    """A pause by hand of a job that isn't a running thorough job."""

    def __init__(self, id: str) -> None:
        super().__init__(f"The conversion {id} isn't a running thorough conversion: only one can be paused.")


UNREADABLE = "The conversion {id} can't be resumed: its folder's state can't be read."


def _default_pipeline() -> Pipeline:
    """`pipeline.run_thorough` (Task 6), looked up when a job starts: the pipeline imports this package."""
    return importlib.import_module("delve.conversions.thorough.pipeline").run_thorough


async def start_thorough(
    services: ConversionServices,
    path: Path,
    title: str,
    mode: ConversionMode,
    *,
    data_dir: Path,
    pipeline: Pipeline | None = None,
    comments: str = "",
) -> Conversion:
    """Start converting the PDF at `path` thoroughly into a module titled `title`, a draft or ready to play, in the
    job folder `<data_dir>/conversions/<id>/`, or queue it while the slot is taken or the queue paused. The job owns
    `path` from here: it is copied into the folder when the job starts and removed, and removed at once when the job
    is refused. Its agents, side calls and looks are given the organiser's `comments` (table voice and fixes Task F1).
    Answers the job, running or queued; `ValueError` for no title, another mode or comments over
    `runner.COMMENTS_MAX`."""
    try:
        runner.check_pdf(title, mode, comments)
        admitted = runner._admit(
            services,
            "pdf",
            title.strip(),
            mode,
            target={"thorough": True},
            waiting={"upload": str(path)},
            comments=comments.strip(),
        )
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    row = admitted.conversion if isinstance(admitted, runner._Live) else admitted
    folder = data_dir / "conversions" / row.id
    row = services.storage.conversions.save(replace(row, target={**(row.target or {}), "folder": str(folder)}))
    if isinstance(admitted, runner._Live):
        admitted.conversion = row
    else:
        admitted = row
    return runner._begin(services, admitted, _first_start(services, Workspace(folder), path, row, pipeline))


def _first_start(
    services: ConversionServices, workspace: Workspace, path: Path, row: Conversion, pipeline: Pipeline | None
) -> runner._Start:
    """A new job's start: its folder made from the book at `path` (afresh, should a stopped Delve have left half of
    one), then the pipeline. A pause, a cancel or Delve stopping while the folder is made lets it finish first, so
    the job stops with its folder whole, the book copied in, and a failed making leaves no half of one."""
    options = {"mode": row.mode, "title": row.title}

    async def work(live: _Live) -> None:
        def create() -> None:
            workspace.remove()
            try:
                Workspace.create(live.conversion.id, workspace.root.parent.parent, path, options=options)
            except BaseException:
                workspace.remove()
                raise

        making = asyncio.ensure_future(asyncio.to_thread(create))
        try:
            await asyncio.shield(making)
        except asyncio.CancelledError:
            while not making.done():  # a second cancel waits too: `asyncio.wait` never cancels what it waits for
                with contextlib.suppress(asyncio.CancelledError):
                    await asyncio.wait([making])
            raise
        path.unlink(missing_ok=True)
        await _work(services, live, workspace, pipeline)

    return runner._Start(work, cleanup=lambda: path.unlink(missing_ok=True), upload=path)


def restored(services: ConversionServices, conversion: Conversion) -> runner._Start | None:
    """How a thorough job queued before a restart starts: on its folder, or from its book when it never started;
    None when it has neither (`runner.close_lost` fails it at the start)."""
    workspace = runner.job_folder(conversion)
    if workspace is None:
        return None
    if workspace.exists():
        return runner._Start(lambda live: _work(services, live, workspace, None))
    upload = (conversion.target or {}).get("upload")
    if upload and Path(upload).is_file():
        return _first_start(services, workspace, Path(upload), conversion, None)
    return None


async def resume(services: ConversionServices, id: str, *, pipeline: Pipeline | None = None) -> Conversion:
    """Put the paused thorough job `id` back in the queue, which starts it at once when the slot is free and the
    queue isn't paused: it runs again on its folder, from its first unfinished piece. Its scheduled resume, if any,
    is dropped. Answers the job, running or queued; `NotPaused` for a job that isn't a paused thorough job (or whose
    folder is gone, or whose state can't be read), `KeyError` for an unknown id."""
    _requeue(services, id, pipeline)
    runner.start_queue(services)
    live = services.live.get(id)
    return live.conversion if live is not None else services.storage.conversions.get(id)


def _requeue(services: ConversionServices, id: str, pipeline: Pipeline | None) -> Conversion:
    storage = services.storage
    conversion = storage.conversions.get(id)
    if conversion is None:
        raise KeyError(id)
    workspace = runner.job_folder(conversion)
    if conversion.status != "paused" or workspace is None or not workspace.exists():
        raise NotPaused(id)
    try:
        workspace.resumed()
    except (OSError, ValueError, TypeError):  # a state Delve can't read
        raise NotPaused(id, UNREADABLE.format(id=id)) from None
    scheduled = services.resumes.pop(id, None)
    if scheduled is not None:
        scheduled.cancel()
    queued = storage.conversions.save(replace(conversion, status="queued", error=None))
    services.starts[id] = runner._Start(lambda live: _work(services, live, workspace, pipeline))
    services.publish("conversion", runner._event(queued))
    return queued


async def pause(services: ConversionServices, id: str) -> Conversion:
    """Pause the running thorough job `id` by hand: its agent sessions stop now, the pieces in progress count
    neither as done nor as a failed attempt, its folder is kept, and it is `paused` with `PAUSED_BY_ORGANISER`,
    waiting for a resume by hand; the next queued job starts. `NotPausable` for any other job (a quick one, a
    queued one), `KeyError` for an unknown id."""
    conversion = services.storage.conversions.get(id)
    if conversion is None:
        raise KeyError(id)
    live = services.live.get(id)
    running = live is not None and live.task is not None and not live.task.done()
    if runner.job_folder(conversion) is None or conversion.status != "running" or not running:
        raise NotPausable(id)
    live.pausing = True
    live.task.cancel()
    await asyncio.gather(live.task, return_exceptions=True)
    runner._never_began(services, live, lambda: runner._paused_by_hand(services, live))
    return services.storage.conversions.get(id)


async def resume_stopped(services: ConversionServices) -> Conversion | None:
    """At Delve's start, after `runner.close_orphans`: every job Delve's stop paused goes back in the queue, oldest
    first, and the queue starts (unless it is paused). A job paused at the usage limit gets its resume scheduled
    again, at its reset time; one paused by an error or by hand waits for a resume by hand, and one whose folder
    can't be read stays as it is, so Delve still starts. Answers the job started, if any."""
    for conversion in services.storage.conversions.paused():
        workspace = runner.job_folder(conversion)
        try:
            paused = workspace.state().paused if workspace is not None and workspace.exists() else None
        except (OSError, ValueError, TypeError):  # a folder Delve can't read stays paused
            continue
        if paused is None:
            continue
        if paused.reason == DELVE_STOPPED:
            _requeue(services, conversion.id, None)
        elif paused.reason == USAGE_LIMIT:
            schedule_resume(services, conversion.id, paused.resets_at)
    return runner.start_queue(services)


async def _work(services: ConversionServices, live: _Live, workspace: Workspace, pipeline: Pipeline | None) -> None:
    """The pipeline, and the job paused for whatever stops it but a cancel or Delve stopping."""
    run = pipeline or services.pipeline or _default_pipeline()
    try:
        await run(services, live, workspace)
    except Paused as paused:
        _pause(services, live, workspace, paused.reason, paused.resets_at)
        _schedule(services, live.conversion.id, pieces.resume_delay(paused.resets_at, datetime.now(UTC)), run)
    except ReadStopped:  # a cancel: `runner._job` ends the job
        raise
    except Exception as error:  # noqa: BLE001 (a thorough job pauses with its error, its folder kept)
        message = str(error) or type(error).__name__
        _pause(services, live, workspace, message, None, error=message)


def _pause(
    services: ConversionServices,
    live: _Live,
    workspace: Workspace,
    reason: str,
    resets_at: str | None,
    *,
    error: str | None = None,
) -> None:
    if live.conversion.status != "running":
        return
    workspace.pause(reason, resets_at)
    live.conversion = services.storage.conversions.save(replace(live.conversion, status="paused", error=error))
    services.publish("conversion", runner._event(live.conversion))


def schedule_resume(services: ConversionServices, id: str, resets_at: str | None) -> None:
    """Resume the job `id`, paused at the usage limit, by itself `pieces.resume_delay` after `resets_at`: at Delve's
    start, for a job whose scheduled resume stopped with the Delve before (thorough conversion Task 8)."""
    _schedule(services, id, pieces.resume_delay(resets_at, datetime.now(UTC)), None)


def _schedule(services: ConversionServices, id: str, delay: float, pipeline: Pipeline | None) -> None:
    """Resume the job `id` by itself in `delay` seconds, through the queue: with another job running, or the queue
    paused, it waits there."""

    def fire() -> None:
        services.resumes.pop(id, None)
        task = asyncio.create_task(_resume_by_itself())
        services.follow_ups.add(task)
        task.add_done_callback(services.follow_ups.discard)

    async def _resume_by_itself() -> None:
        try:
            await resume(services, id, pipeline=pipeline)
        except (KeyError, NotPaused):  # cancelled, or resumed by hand and done
            pass

    previous = services.resumes.pop(id, None)
    if previous is not None:
        previous.cancel()
    services.resumes[id] = asyncio.get_running_loop().call_later(delay, fire)
