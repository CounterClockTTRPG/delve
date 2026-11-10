"""The conversion queue (thorough conversion, owner addition 2026-10-23; design d1, option A): a PDF uploaded while a
job runs is `queued` and starts by itself, oldest first, when the slot frees; a thorough job is paused by hand; and the
queue's switch, stored, starts no queued job while it is paused.

The running job is a `dungeon-map` job held on an `asyncio.Event`, or a thorough job whose agent hangs (the pieces
tests' `Agent`); the quick jobs are the runner tests' PDF with their `Claude`."""

import asyncio
import threading
from dataclasses import replace

import pytest

from delve.config import Config
from delve.conversions import cancel, close_orphans, runner, start_generate, start_pdf, wait
from delve.conversions.thorough import NotPausable, NotPaused, pause, resume, resume_stopped, start_thorough
from delve.conversions.thorough.workspace import DELVE_STOPPED, PAUSED_BY_ORGANISER, Workspace
from delve.modules.books.pdf import ReadStopped
from delve.storage import open_storage
from tests.conversions.test_runner import Claude, _caves_pdf
from tests.conversions.test_runner import _services as runner_services
from tests.conversions.thorough.test_pieces import COST, Agent, _until, pipeline
from tests.fixtures.pdfs import text_page, write_pdf


@pytest.fixture
def storage(tmp_path):
    opened = open_storage(Config(data_dir=tmp_path / "data"))
    yield opened
    opened.close()


def _services(storage):
    services, _, events = runner_services(storage, Claude())
    return services, events


def _statuses(events, id: str) -> list[str]:
    return [data["status"] for kind, data in events if kind == "conversion" and data["id"] == id]


def _book(tmp_path, name: str):
    return write_pdf(tmp_path / f"{name}.pdf", [text_page(["# The Caves", "## 1. Entrance", "Steps lead down."])])


async def _held(services):
    """A job that runs until its gate is set: it holds the slot."""
    gate = asyncio.Event()

    async def work(live):
        await gate.wait()
        runner.finish(services, live)

    job = await runner.start_job(services, "dungeon-map", "A crypt", work)
    await asyncio.sleep(0)  # it begins
    return job, gate


def test_an_upload_while_a_job_runs_is_queued_and_the_queue_starts_oldest_first(storage, tmp_path):
    services, events = _services(storage)

    async def scenario():
        held, gate = await _held(services)
        first = await start_pdf(services, _book(tmp_path, "first"), "First", "ready")
        second = await start_pdf(services, _book(tmp_path, "second"), "Second", "draft")
        assert (first.status, second.status) == ("queued", "queued"), "no longer refused"
        assert [c.id for c in storage.conversions.queued()] == [first.id, second.id]
        assert (tmp_path / "first.pdf").exists(), "a queued job keeps its book"
        gate.set()
        await wait(services, held.id)
        await _until(lambda: storage.conversions.get(second.id).status == "done")
        return first, second

    first, second = asyncio.run(scenario())

    done_first, done_second = storage.conversions.get(first.id), storage.conversions.get(second.id)
    assert done_first.status == done_second.status == "done"
    assert done_first.updated_at < done_second.updated_at, "oldest first"
    assert storage.modules.get(done_second.module_id).draft is True
    assert _statuses(events, first.id)[0] == "queued" and _statuses(events, first.id)[-1] == "done"
    assert not (tmp_path / "first.pdf").exists() and not (tmp_path / "second.pdf").exists()


def test_the_next_job_starts_when_the_running_one_is_cancelled(storage, tmp_path):
    services, _ = _services(storage)

    async def scenario():
        held, _ = await _held(services)
        queued = await start_pdf(services, _book(tmp_path, "next"), "Next", "ready")
        await cancel(services, held.id)
        return await _wait_done(services, queued.id)

    assert asyncio.run(scenario()).status == "done"


def test_a_queued_job_cancelled_leaves_the_queue_and_its_book(storage, tmp_path):
    services, events = _services(storage)

    async def scenario():
        held, gate = await _held(services)
        queued = await start_pdf(services, _book(tmp_path, "next"), "Next", "ready")
        cancelled = await cancel(services, queued.id)
        gate.set()
        await wait(services, held.id)
        return cancelled

    cancelled = asyncio.run(scenario())
    assert cancelled.status == "cancelled" and storage.conversions.queued() == []
    assert not (tmp_path / "next.pdf").exists(), "its book is removed"
    assert _statuses(events, cancelled.id) == ["queued", "cancelled"]


def test_a_paused_queue_starts_nothing_and_unpausing_starts_the_oldest(storage, tmp_path):
    services, _ = _services(storage)

    async def scenario():
        assert runner.set_queue_paused(services, True) is True
        queued = await start_pdf(services, _book(tmp_path, "night"), "At night", "ready")
        assert queued.status == "queued", "with the queue paused, even a free slot starts nothing"
        await asyncio.sleep(0.05)
        assert storage.conversions.get(queued.id).status == "queued" and services.live == {}
        assert runner.set_queue_paused(services, False) is False
        return await _wait_done(services, queued.id)

    assert asyncio.run(scenario()).status == "done"


def test_a_running_job_keeps_running_when_the_queue_is_paused(storage, tmp_path):
    services, _ = _services(storage)

    async def scenario():
        held, gate = await _held(services)
        queued = await start_pdf(services, _book(tmp_path, "next"), "Next", "ready")
        runner.set_queue_paused(services, True)
        assert storage.conversions.get(held.id).status == "running"
        gate.set()
        done = await wait(services, held.id)
        await asyncio.sleep(0.05)
        return done, storage.conversions.get(queued.id)

    done, queued = asyncio.run(scenario())
    assert done.status == "done" and queued.status == "queued", "the slot freed, the paused queue started nothing"


def test_the_queue_and_its_switch_survive_a_restart(tmp_path):
    """Delve stops with a quick and a thorough job queued and the queue paused: at the next start both are still
    queued and nothing starts; unpaused, they run oldest first from what they stored."""
    config = Config(data_dir=tmp_path / "data")
    storage = open_storage(config)
    services, _ = _services(storage)
    agent = Agent()

    async def before_the_stop():
        held, _ = await _held(services)
        quick = await start_pdf(services, _book(tmp_path, "quick"), "Quick", "ready", book_maps=False)
        thorough = await start_thorough(
            services, _book(tmp_path, "thorough"), "Thorough", "ready", data_dir=config.data_dir
        )
        runner.set_queue_paused(services, True)
        services.live[held.id].task.cancel()  # Delve stopping
        await asyncio.gather(services.live[held.id].task, return_exceptions=True)
        return quick, thorough

    quick, thorough = asyncio.run(before_the_stop())
    assert (tmp_path / "thorough.pdf").exists(), "a queued thorough job waits with its book"
    assert not Workspace(config.data_dir / "conversions" / thorough.id).exists(), "its folder is made when it starts"
    storage.close()

    storage = open_storage(config)
    try:
        services, _ = _services(storage)

        async def after_restart():
            close_orphans(storage)
            assert runner.start_queue(services) is None, "the paused queue starts nothing"
            assert [c.id for c in storage.conversions.queued()] == [quick.id, thorough.id]
            services.pipeline = pipeline(["a"], agent)
            runner.set_queue_paused(services, False)
            await _wait_done(services, quick.id)
            return await _wait_done(services, thorough.id)

        done = asyncio.run(after_restart())
        assert done.status == "done" and agent.calls == ["a"]
        assert storage.conversions.get(quick.id).module_id is not None
    finally:
        storage.close()


def test_a_request_while_a_job_runs_is_queued_as_a_book_is(storage, tmp_path):
    """DEL-141: a request to generate a module waits in the queue, in turn with the books, and keeps its request."""
    services, events = _services(storage)

    async def scenario():
        held, gate = await _held(services)
        book = await start_pdf(services, _book(tmp_path, "book"), "Book", "ready")
        request = await start_generate(services, "A dungeon with kobolds, no plot.", "draft")
        assert (book.status, request.status) == ("queued", "queued"), "no longer refused"
        assert request.target == {"request": "A dungeon with kobolds, no plot."}
        assert [c.id for c in storage.conversions.queued()] == [book.id, request.id]
        gate.set()
        await wait(services, held.id)
        await _until(lambda: storage.conversions.get(request.id).status == "done")
        return book, request

    book, request = asyncio.run(scenario())
    done_book, done_request = storage.conversions.get(book.id), storage.conversions.get(request.id)
    assert done_book.status == done_request.status == "done"
    assert done_book.updated_at < done_request.updated_at, "oldest first"
    assert storage.modules.get(done_request.module_id).draft is True
    assert _statuses(events, request.id)[0] == "queued"


def test_a_queued_request_survives_a_restart(tmp_path):
    config = Config(data_dir=tmp_path / "data")
    storage = open_storage(config)
    services, _ = _services(storage)

    async def before_the_stop():
        held, _ = await _held(services)
        request = await start_generate(services, "A dungeon with kobolds, no plot.", "ready")
        services.live[held.id].task.cancel()  # Delve stopping
        await asyncio.gather(services.live[held.id].task, return_exceptions=True)
        return request

    runner.set_queue_paused(services, True)  # so the stop's cancel starts nothing
    request = asyncio.run(before_the_stop())
    storage.close()

    storage = open_storage(config)
    try:
        services, _ = _services(storage)

        async def after_restart():
            close_orphans(storage)
            assert [c.id for c in storage.conversions.queued()] == [request.id]
            runner.set_queue_paused(services, False)
            return await _wait_done(services, request.id)

        done = asyncio.run(after_restart())
        assert done.status == "done" and storage.modules.get(done.module_id) is not None
    finally:
        storage.close()


def test_a_queued_job_whose_book_is_lost_fails_at_the_start(storage, tmp_path):
    left = storage.conversions.create(
        "pdf", "Lost", "ready", status="queued", target={"upload": str(tmp_path / "gone.pdf"), "book_maps": False}
    )
    folder = tmp_path / "data" / "conversions" / "cnv_copying"
    copying = storage.conversions.create(
        "pdf", "Copying", "ready", status="queued", target={"thorough": True, "folder": str(folder)}
    )
    folder.mkdir(parents=True)  # Delve stopped while copying the book in
    services, _ = _services(storage)

    lost = runner.close_lost(storage)

    assert {c.id for c in lost} == {left.id, copying.id}
    assert {storage.conversions.get(c.id).status for c in lost} == {"failed"}
    assert storage.conversions.get(left.id).error == runner.LOST
    assert not folder.exists()
    assert runner.start_queue(services) is None


# ----- a thorough job paused and resumed by hand -----


def test_a_thorough_job_paused_by_hand_spends_no_retry_and_no_cost_twice(storage, tmp_path):
    """The organiser pauses the job while its second piece's agent works: the agent stops at once, the piece counts
    neither as done nor as a failed attempt, the folder stays, and the queued job starts. The resume runs the second
    piece only, and the first piece's cost isn't added again."""
    services, events = _services(storage)
    agent = Agent({"b": ["hang"]})
    run = pipeline(["a", "b"], agent)

    async def scenario():
        started = await start_thorough(
            services, _book(tmp_path, "saltmarsh"), "Saltmarsh", "ready", data_dir=tmp_path / "data", pipeline=run
        )
        await agent.hanging.wait()
        gate = asyncio.Event()

        async def work(live):
            await gate.wait()
            runner.finish(services, live)

        paused = await pause(services, started.id)
        next_job = await runner.start_job(services, "dungeon-map", "Next", work)
        gate.set()
        await wait(services, next_job.id)
        return started, paused

    started, paused = asyncio.run(scenario())

    assert (paused.status, paused.error, paused.cost_usd) == ("paused", None, COST)
    ws = Workspace(tmp_path / "data" / "conversions" / started.id)
    assert ws.exists() and ws.state().paused.reason == PAUSED_BY_ORGANISER == "paused by the organiser"
    assert ws.is_done("a") and ws.piece("b") is None, "the piece stopped halfway is no attempt and isn't done"
    assert services.resumes == {}, "a pause by hand waits for a resume by hand"

    agent.calls.clear()

    async def resumed():
        again = await resume(services, started.id, pipeline=run)
        assert again.status == "running"
        return await wait(services, started.id)

    done = asyncio.run(resumed())
    assert agent.calls == ["b"] and done.status == "done"
    assert done.cost_usd == pytest.approx(2 * COST), "the first piece's cost counts once"
    assert _statuses(events, started.id) == ["paused", "queued", "running", "done"]


def test_pausing_by_hand_starts_the_next_queued_job(storage, tmp_path):
    services, _ = _services(storage)
    agent = Agent({"a": ["hang"]})

    async def scenario():
        started = await start_thorough(
            services,
            _book(tmp_path, "saltmarsh"),
            "Saltmarsh",
            "ready",
            data_dir=tmp_path / "data",
            pipeline=pipeline(["a"], agent),
        )
        await agent.hanging.wait()
        queued = await start_pdf(services, _book(tmp_path, "next"), "Next", "ready")
        assert queued.status == "queued"
        await pause(services, started.id)
        return await _wait_done(services, queued.id), started

    done, started = asyncio.run(scenario())
    assert done.status == "done" and storage.conversions.get(started.id).status == "paused"


def test_a_pause_while_reading_pauses_and_doesnt_cancel(storage, tmp_path):
    services, _ = _services(storage)

    async def scenario():
        reading = asyncio.Event()

        async def run(services, live, ws):
            reading.set()
            await asyncio.Event().wait()

        started = await start_thorough(
            services, _book(tmp_path, "b"), "Saltmarsh", "ready", data_dir=tmp_path / "data", pipeline=run
        )
        await reading.wait()
        return await pause(services, started.id)

    paused = asyncio.run(scenario())
    assert paused.status == "paused"


@pytest.mark.parametrize("stops_with", ["cancelled", "read-stopped"])
def test_a_cancel_racing_a_pause_cancels(storage, tmp_path, stops_with):
    """Review finding 2: the organiser pauses and, before the job has stopped, cancels it. The cancel wins: the job
    ends `cancelled` and its folder is deleted, whether its work stops at the cancel or the reading sees it first
    (`ReadStopped`)."""
    services, _ = _services(storage)

    async def scenario():
        working = asyncio.Event()

        async def run(services, live, ws):
            working.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                await asyncio.sleep(0)  # the cancel arrives while the work stops
                if stops_with == "read-stopped":
                    raise ReadStopped from None
                raise

        started = await start_thorough(
            services, _book(tmp_path, "b"), "Saltmarsh", "ready", data_dir=tmp_path / "data", pipeline=run
        )
        await working.wait()
        await asyncio.gather(pause(services, started.id), cancel(services, started.id), return_exceptions=True)
        return started

    started = asyncio.run(scenario())
    assert storage.conversions.get(started.id).status == "cancelled"
    assert not (tmp_path / "data" / "conversions" / started.id).exists(), "the cancel deletes the folder"


def test_a_cancel_after_the_module_is_made_leaves_the_job_done(storage, tmp_path):
    """Review finding 10: a cancel while the made job removes its folder (`pipeline.make`'s last step) keeps the
    job `done`, with its module, and the folder is removed all the same."""
    services, events = _services(storage)

    async def scenario():
        removing = asyncio.Event()

        async def run(services, live, ws):
            runner.finish(services, live)  # the module made, in the transaction with the job's end
            removing.set()
            await asyncio.Event().wait()  # the folder being removed, off the loop

        started = await start_thorough(
            services, _book(tmp_path, "b"), "Saltmarsh", "ready", data_dir=tmp_path / "data", pipeline=run
        )
        await removing.wait()
        return await cancel(services, started.id)

    cancelled = asyncio.run(scenario())
    assert cancelled.status == "done" and storage.conversions.get(cancelled.id).status == "done"
    assert _statuses(events, cancelled.id)[-1] == "done"
    assert not (tmp_path / "data" / "conversions" / cancelled.id).exists()


def _slow_folder(monkeypatch, fail: bool = False):
    """`Workspace.create` held until `release` is set, as a big book's copy is; with `fail`, it fails halfway."""
    entered, release = threading.Event(), threading.Event()
    create = Workspace.create

    def held(conversion_id, data_dir, pdf, *, options=None):
        entered.set()
        release.wait(5)
        if fail:
            (data_dir / "conversions" / conversion_id).mkdir(parents=True)
            (data_dir / "conversions" / conversion_id / "book.pdf").write_bytes(b"%PDF-half")
            raise OSError("No space left on device")
        return create(conversion_id, data_dir, pdf, options=options)

    monkeypatch.setattr(Workspace, "create", staticmethod(held))
    return entered, release


@pytest.mark.parametrize("stop", ["pause", "cancel"])
def test_a_stop_while_the_folder_is_made_waits_for_the_folder(storage, tmp_path, monkeypatch, stop):
    """Review finding 3: a pause or a cancel while the folder is being made lets it finish first. Paused, the job
    has its folder, whole, and resumes from it; cancelled, it leaves no folder. The book is removed only once the
    folder holds its copy."""
    services, _ = _services(storage)
    entered, release = _slow_folder(monkeypatch)
    agent = Agent()
    book = _book(tmp_path, "b")

    async def scenario():
        started = await start_thorough(
            services, book, "Saltmarsh", "ready", data_dir=tmp_path / "data", pipeline=pipeline(["a"], agent)
        )
        await asyncio.to_thread(entered.wait, 5)
        asyncio.get_running_loop().call_later(0.05, release.set)
        stopped = await (pause if stop == "pause" else cancel)(services, started.id)
        return started, stopped

    started, stopped = asyncio.run(scenario())
    folder = tmp_path / "data" / "conversions" / started.id
    assert not book.exists()
    if stop == "cancel":
        assert stopped.status == "cancelled" and not folder.exists()
        return
    assert stopped.status == "paused" and Workspace(folder).exists() and (folder / "book.pdf").is_file()
    assert Workspace(folder).state().paused.reason == PAUSED_BY_ORGANISER

    async def resumed():
        await resume(services, started.id, pipeline=pipeline(["a"], agent))
        return await wait(services, started.id)

    assert asyncio.run(resumed()).status == "done" and agent.calls == ["a"]


def test_a_folder_that_fails_halfway_is_removed(storage, tmp_path, monkeypatch):
    """Review finding 3: no half-made folder is left behind."""
    services, _ = _services(storage)
    _, release = _slow_folder(monkeypatch, fail=True)
    release.set()

    async def scenario():
        started = await start_thorough(
            services, _book(tmp_path, "b"), "Saltmarsh", "ready", data_dir=tmp_path / "data", pipeline=None
        )
        return await wait(services, started.id)

    ended = asyncio.run(scenario())
    assert ended.status == "failed" and "No space left" in ended.error
    assert not (tmp_path / "data" / "conversions" / ended.id).exists()


def test_only_a_running_thorough_job_can_be_paused(storage, tmp_path):
    services, _ = _services(storage)

    async def scenario():
        held, gate = await _held(services)
        with pytest.raises(NotPausable):
            await pause(services, held.id)  # not thorough
        quick = await start_pdf(services, _book(tmp_path, "quick"), "Quick", "ready")
        with pytest.raises(NotPausable):
            await pause(services, quick.id)  # a quick job
        thorough = await start_thorough(services, _book(tmp_path, "t"), "Thorough", "ready", data_dir=tmp_path / "data")
        assert thorough.status == "queued"
        with pytest.raises(NotPausable):
            await pause(services, thorough.id)  # queued: cancel it, or pause the queue
        with pytest.raises(KeyError):
            await pause(services, "cnv_unknown")
        for job in (quick, thorough, held):
            await cancel(services, job.id)
        gate.set()

    asyncio.run(scenario())


# ----- resume through the queue -----


def test_a_resume_while_another_job_runs_queues_the_job(storage, tmp_path):
    services, _ = _services(storage)
    agent = Agent()
    paused, _ = _paused_job(storage, tmp_path, DELVE_STOPPED)

    async def scenario():
        held, gate = await _held(services)
        queued = await resume(services, paused.id, pipeline=pipeline(["a"], agent))
        assert queued.status == "queued" and queued.error is None
        gate.set()
        await wait(services, held.id)
        return await _wait_done(services, paused.id)

    assert asyncio.run(scenario()).status == "done" and agent.calls == ["a"]


def test_a_resume_of_a_job_whose_state_cant_be_read_is_refused(storage, tmp_path):
    services, _ = _services(storage)
    paused, ws = _paused_job(storage, tmp_path, DELVE_STOPPED)
    (ws.root / "state.json").write_text("{not json")

    with pytest.raises(NotPaused):
        asyncio.run(resume(services, paused.id))
    assert storage.conversions.get(paused.id).status == "paused"


def test_the_start_queues_every_job_delve_stopped_and_starts_the_oldest(storage, tmp_path):
    services, _ = _services(storage)
    services.pipeline = pipeline(["a"], Agent())
    older, _ = _paused_job(storage, tmp_path, DELVE_STOPPED)
    errored, _ = _paused_job(storage, tmp_path, "list index out of range")
    newer, _ = _paused_job(storage, tmp_path, DELVE_STOPPED)

    async def scenario():
        started = await resume_stopped(services)
        assert started is not None and started.id == older.id
        assert [c.id for c in storage.conversions.queued()] == [newer.id]
        await _wait_done(services, older.id)
        return await _wait_done(services, newer.id)

    assert asyncio.run(scenario()).status == "done"
    assert storage.conversions.get(errored.id).status == "paused", "an error waits for a resume by hand"


def test_the_start_with_the_queue_paused_queues_but_starts_nothing(storage, tmp_path):
    services, _ = _services(storage)
    stopped, _ = _paused_job(storage, tmp_path, DELVE_STOPPED)
    storage.conversions.set_queue_paused(True)

    assert asyncio.run(resume_stopped(services)) is None
    assert storage.conversions.get(stopped.id).status == "queued" and services.live == {}


def test_a_follow_up_holds_the_queue_until_it_ends(storage, tmp_path):
    """A quick job's book maps are drawn, one job after another, before the next queued job takes the slot."""
    services, _ = _services(storage)
    order = []

    async def then(conversion):
        order.append("then started")
        await asyncio.sleep(0.05)
        assert storage.conversions.get(queued_id[0]).status == "queued", "the queue waits for the follow-up"
        order.append("then ended")

    queued_id = []

    async def scenario():
        held, gate = await _held(services)
        first = await start_pdf(services, _caves_pdf(tmp_path), "First", "ready", then=then)
        queued = await start_pdf(services, _book(tmp_path, "second"), "Second", "ready")
        queued_id.append(queued.id)
        gate.set()
        await wait(services, held.id)
        await _wait_done(services, first.id)
        return await _wait_done(services, queued.id)

    assert asyncio.run(scenario()).status == "done"
    assert order == ["then started", "then ended"]


def test_the_queue_in_order(storage, tmp_path):
    services, _ = _services(storage)
    paused, _ = _paused_job(storage, tmp_path, DELVE_STOPPED)
    done = storage.conversions.save(replace(storage.conversions.create("generate", "Old", "ready"), status="done"))

    async def scenario():
        held, gate = await _held(services)
        first = await start_pdf(services, _book(tmp_path, "first"), "First", "ready")
        second = await start_pdf(services, _book(tmp_path, "second"), "Second", "ready")
        listed = [c.id for c in runner.queue(storage)]
        await cancel(services, first.id)
        await cancel(services, second.id)
        gate.set()
        await wait(services, held.id)
        return listed, [held.id, first.id, second.id, paused.id]

    listed, expected = asyncio.run(scenario())
    assert listed == expected and done.id not in listed


# ----- helpers -----


def _paused_job(storage, tmp_path, reason: str):
    job = storage.conversions.create("pdf", reason, "ready")
    ws = Workspace.create(job.id, tmp_path / "data", _book(tmp_path, job.id), options={"mode": "ready"})
    ws.pause(reason)
    job = storage.conversions.save(replace(job, status="paused", target={"thorough": True, "folder": str(ws.root)}))
    return job, ws


async def _wait_done(services, id: str):
    await _until(lambda: services.storage.conversions.get(id).status not in ("queued", "running"))
    live = services.live.get(id)
    if live is not None and live.task is not None:
        await asyncio.gather(live.task, return_exceptions=True)
    await asyncio.gather(*services.follow_ups, return_exceptions=True)
    return services.storage.conversions.get(id)

