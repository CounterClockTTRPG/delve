"""The pieces of a thorough conversion and its pause and resume (thorough conversion Task 4, Review Focus 3 and 5).

The agent sessions are an `Agent` here: it answers a `Run` per call, as `claude_cli.agent.run_agent` answers an
`AgentRun`, writes the piece's output into the folder unless told not to, and can be told to hang (a session
halfway when Delve stops), to fail, or to hit the usage limit. The pipeline is a few pieces run in order, then the
job's end (`finish`), so the tests see the lifecycle without the stages of Task 6."""

import asyncio
import json
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime

import pytest

from delve.config import Config
from delve.conversions import ConversionServices, cancel, close_orphans, runner, wait
from delve.conversions.thorough import NotPaused, pieces, resume, start_thorough
from delve.conversions.thorough.pieces import Paused, resume_delay, run_piece
from delve.conversions.thorough.workspace import Workspace
from delve.dm.claude_cli.agent import AgentStopped
from delve.dm.fake import FakeDM
from delve.dm.provider import Usage
from delve.domain.settings import BackendChoice
from delve.storage import open_storage
from tests.fixtures.pdfs import text_page, write_pdf

COST = 0.25
LIMIT_NOTICE_RESET = "2026-10-23T09:00:00+00:00"


@dataclass(frozen=True)
class Run:
    text: str = "Done."
    usage: Usage | None = field(default_factory=lambda: Usage(10, 10, COST))
    limited: bool = False
    resets_at: str | None = None
    session_id: str | None = None


class Agent:
    """Answers each piece by `plan[piece]`, a list of what its calls do in turn (`ok` when it runs out): `ok` writes
    `<piece>.md`, `empty` writes nothing, `crash` raises, `limit` hits the usage limit, `hang` waits forever."""

    def __init__(self, plan: dict[str, list[str]] | None = None) -> None:
        self.plan = {piece: list(steps) for piece, steps in (plan or {}).items()}
        self.calls: list[str] = []
        self.hanging = asyncio.Event()

    async def __call__(self, ws: Workspace, piece: str) -> Run:
        self.calls.append(piece)
        steps = self.plan.get(piece) or []
        step = steps.pop(0) if steps else "ok"
        if step == "hang":
            self.hanging.set()
            await asyncio.Event().wait()
        if step == "crash":
            raise RuntimeError("claude stopped (exit code 1): overloaded")
        if step == "limit":
            return Run(
                text="You've hit your session limit · resets 9am (UTC)",
                usage=Usage(1, 1, 0.01),
                limited=True,
                resets_at=LIMIT_NOTICE_RESET,
            )
        if step == "ok":
            (ws.root / f"{piece}.md").write_text(f"# {piece}\n")
        return Run()


def pipeline(names: list[str], agent: Agent):
    async def run(services, live, ws):
        spend = runner._spend(services, live)
        for name in names:
            expected = f"{name}.md"
            await run_piece(
                ws,
                name,
                lambda name=name: agent(ws, name),
                lambda expected=expected: [] if (ws.root / expected).exists() else [expected],
                spend=spend,
                outputs=[expected],
            )
        runner.finish(services, live)

    return run


@pytest.fixture
def storage(tmp_path):
    opened = open_storage(Config(data_dir=tmp_path / "data"))
    yield opened
    opened.close()


def _services(storage) -> tuple[ConversionServices, list[dict]]:
    dm = FakeDM([])
    events: list[dict] = []
    services = ConversionServices(
        storage=storage,
        conversion=lambda: (dm, BackendChoice("fake", "fake-large")),
        publish=lambda kind, data: events.append(data) if kind == "conversion" else None,
        ocr=None,
    )
    return services, events


def _pdf(tmp_path):
    return write_pdf(tmp_path / "upload.pdf", [text_page(["# The Caves", "## 1. Entrance"])])


async def _until(condition, *, limit: float = 5.0) -> None:
    deadline = asyncio.get_running_loop().time() + limit
    while not condition():
        assert asyncio.get_running_loop().time() < deadline, "waited too long"
        await asyncio.sleep(0.01)


def test_a_thorough_job_runs_its_pieces_in_its_folder_and_adds_their_cost(storage, tmp_path):
    services, _ = _services(storage)
    agent = Agent()
    upload = _pdf(tmp_path)

    async def scenario():
        started = await start_thorough(
            services, upload, "The Caves", "ready", data_dir=tmp_path / "data", pipeline=pipeline(["a", "b"], agent)
        )
        assert started.target == {"thorough": True, "folder": str(tmp_path / "data" / "conversions" / started.id)}
        return await wait(services, started.id)

    done = asyncio.run(scenario())

    assert (done.kind, done.status, done.cost_usd) == ("pdf", "done", 2 * COST)
    assert agent.calls == ["a", "b"]
    assert not upload.exists(), "the upload is copied into the folder and removed"
    state = Workspace(tmp_path / "data" / "conversions" / done.id).state()
    assert {p: (r.status, r.attempts, r.cost_usd, r.outputs) for p, r in state.pieces.items()} == {
        "a": ("done", 1, COST, ["a.md"]),
        "b": ("done", 1, COST, ["b.md"]),
    }


def test_restart_pauses_and_resume_skips_done_pieces(storage, tmp_path):
    """Review Focus 3: Delve stops while the third piece's agent is halfway. At the next start the job is paused
    (not failed); the resume runs only the third piece, and the two finished pieces' cost isn't added again."""
    agent = Agent({"c": ["hang"]})
    run = pipeline(["a", "b", "c"], agent)

    async def until_delve_stops():
        services, _ = _services(storage)
        started = await start_thorough(
            services, _pdf(tmp_path), "The Caves", "ready", data_dir=tmp_path / "data", pipeline=run
        )
        await agent.hanging.wait()
        services.live[started.id].task.cancel()  # Delve stopping: no cancel of the job
        await asyncio.gather(services.live[started.id].task, return_exceptions=True)
        return started.id

    id = asyncio.run(until_delve_stops())
    left = storage.conversions.get(id)
    assert (left.status, left.cost_usd) == ("running", 2 * COST), "the row stays as the stopped Delve left it"
    ws = Workspace(tmp_path / "data" / "conversions" / id)
    assert ws.is_done("a") and ws.is_done("b") and ws.piece("c") is None, "a piece stopped halfway records nothing"

    [closed] = close_orphans(storage)  # the next start

    assert (closed.id, closed.status, closed.error) == (id, "paused", None)
    assert ws.state().paused.reason == "Delve stopped"
    agent.calls.clear()

    async def after_restart():
        services, events = _services(storage)
        resumed = await resume(services, id, pipeline=run)
        assert resumed.status == "running"
        return await wait(services, id), events

    done, events = asyncio.run(after_restart())

    assert agent.calls == ["c"], "finished pieces are never run again"
    assert (done.status, done.cost_usd) == ("done", 3 * COST), "each piece's cost added once"
    assert ws.state().paused is None
    assert [e["status"] for e in events] == ["queued", "running", "done"], "a resume goes through the queue"


def test_usage_limit_pauses_without_spending_a_retry(storage, tmp_path, monkeypatch):
    """Review Focus 5: the session's limit notice pauses the job with the reset time and uses no attempt; the job
    resumes by itself after the reset. Three limits in a row would have used every attempt."""
    monkeypatch.setattr(pieces, "RESUME_GRACE", 0.0)  # the reset is in the past: resume at once
    services, events = _services(storage)
    agent = Agent({"b": ["limit", "limit", "limit"]})

    async def scenario():
        started = await start_thorough(
            services,
            _pdf(tmp_path),
            "The Caves",
            "ready",
            data_dir=tmp_path / "data",
            pipeline=pipeline(["a", "b"], agent),
        )
        first = await wait(services, started.id)
        assert first.status == "paused"
        ws = Workspace(tmp_path / "data" / "conversions" / started.id)
        assert ws.state().paused.resets_at == LIMIT_NOTICE_RESET
        await _until(lambda: storage.conversions.get(started.id).status == "done")
        return storage.conversions.get(started.id), ws

    done, ws = asyncio.run(scenario())

    assert done.status == "done" and done.error is None
    assert agent.calls == ["a", "b", "b", "b", "b"], "the finished piece isn't rerun after each pause"
    b = ws.piece("b")
    assert (b.status, b.attempts) == ("done", 1), "the limits used no attempt"
    assert b.cost_usd == pytest.approx(3 * 0.01 + COST), "what the limited sessions spent is counted once each"
    assert done.cost_usd == pytest.approx(2 * COST + 3 * 0.01)
    statuses = [e["status"] for e in events]
    assert statuses.count("paused") == 3 and statuses[-1] == "done"
    assert services.resumes == {}


def test_resume_delay_reads_the_reset_time():
    now = datetime(2026, 10, 23, 14, 0, tzinfo=UTC)
    assert resume_delay("2026-10-23T14:30:00+00:00", now) == 30 * 60 + pieces.RESUME_GRACE
    assert resume_delay("2:50pm (UTC)", now) == 50 * 60 + pieces.RESUME_GRACE
    assert resume_delay("1pm (UTC)", now) == 23 * 3600 + pieces.RESUME_GRACE, "the next such time"
    assert resume_delay("5pm (Europe/Brussels)", now) == 60 * 60 + pieces.RESUME_GRACE  # 15:00 UTC in summer time
    assert resume_delay("2026-10-23T13:00:00+00:00", now) == pieces.RESUME_GRACE, "a reset past: at once"
    assert resume_delay(None, now) == pieces.RESUME_UNKNOWN
    assert resume_delay("soon", now) == pieces.RESUME_UNKNOWN
    assert resume_delay("3pm (Nowhere/Land)", now) == pieces.RESUME_UNKNOWN


def test_a_resume_by_itself_while_another_job_runs_waits_in_the_queue(storage, tmp_path):
    services, _ = _services(storage)
    agent = Agent({"a": ["limit"]})

    async def scenario():
        blocker = asyncio.Event()

        async def other(live):
            await blocker.wait()
            runner.finish(services, live)

        started = await start_thorough(
            services, _pdf(tmp_path), "The Caves", "ready", data_dir=tmp_path / "data", pipeline=pipeline(["a"], agent)
        )
        await wait(services, started.id)
        scheduled = services.resumes[started.id]
        assert scheduled.when() - asyncio.get_running_loop().time() > pieces.RESUME_GRACE - 1, "after the reset"
        other_job = await runner.start_job(services, "dungeon-map", "Another", other)
        fire = scheduled._callback
        scheduled.cancel()
        fire()  # the reset comes while the other job runs
        await asyncio.gather(*services.follow_ups)
        queued = storage.conversions.get(started.id)
        blocker.set()
        await wait(services, other_job.id)
        await _until(lambda: storage.conversions.get(started.id).status == "done")
        return queued

    queued = asyncio.run(scenario())
    assert queued.status == "queued" and services.resumes == {}
    assert agent.calls == ["a", "a"], "it ran once the other job ended"


def test_three_failures_skip_and_doubt(tmp_path):
    ws = Workspace.create("cnv_000000000001", tmp_path / "data", _pdf(tmp_path))
    agent = Agent({"trace-house": ["crash", "empty", "empty"]})
    spent = []

    outcome = asyncio.run(
        run_piece(
            ws,
            "trace-house",
            lambda: agent(ws, "trace-house"),
            lambda: [] if (ws.root / "trace-house.md").exists() else ["maps/house.dmap"],
            spend=spent.append,
        )
    )

    assert outcome == "skipped" and agent.calls == ["trace-house"] * 3
    record = ws.piece("trace-house")
    assert (record.status, record.attempts, record.cost_usd) == ("skipped", 3, 2 * COST)
    assert [u.cost_usd for u in spent] == [COST, COST], "a failed attempt's cost is the job's too"
    [doubt] = json.loads((ws.root / "doubts" / "trace-house.skipped.json").read_text())
    assert doubt["part"] == "trace-house" and doubt["kind"] == "other"
    assert doubt["text"] == "Skipped after 3 failed attempts: Missing: maps/house.dmap"
    assert asyncio.run(run_piece(ws, "trace-house", lambda: agent(ws, "trace-house"), list)) == "skipped"
    assert len(agent.calls) == 3, "a skipped piece is finished: never run again"


def test_attempts_count_across_runs(tmp_path):
    """A failed attempt before a stop counts after the resume: a piece gets three in all, never three per run."""
    ws = Workspace.create("cnv_000000000001", tmp_path / "data", _pdf(tmp_path))
    ws.failed("clean-1", "claude stopped")
    ws.failed("clean-1", "claude stopped")
    agent = Agent({"clean-1": ["crash"]})

    outcome = asyncio.run(run_piece(ws, "clean-1", lambda: agent(ws, "clean-1"), list))

    assert outcome == "skipped" and agent.calls == ["clean-1"]


def _stopped(error: BaseException, input: int, output: int) -> BaseException:
    error.seen_usage = Usage(input, output, None)  # as `claude_cli.agent.run_agent` stops a session
    return error


def test_a_stopped_session_counts_and_its_cost_is_estimated_at_the_jobs_rate(tmp_path):
    """Review finding 7: a session that timed out, or was cancelled (a pause by hand), sends no cost. Its tokens are
    recorded, the job's measured cost stays as measured, and the doubt says the cost is incomplete, with an
    estimate at this job's own rate (cost per token of its finished sessions)."""
    ws = Workspace.create("cnv_000000000001", tmp_path / "data", _pdf(tmp_path))
    agent = Agent()
    asyncio.run(run_piece(ws, "a", lambda: agent(ws, "a"), list))  # 20 tokens for COST
    calls = iter([_stopped(AgentStopped("no answer within 10800 s", None), 30, 10), None])

    async def timed_out_once():
        stop = next(calls)
        if stop is not None:
            raise stop
        return await agent(ws, "b")

    assert asyncio.run(run_piece(ws, "b", timed_out_once, list)) == "done"

    async def cancelled():
        raise _stopped(asyncio.CancelledError(), 60, 20)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(run_piece(ws, "c", cancelled, list))

    assert ws.piece("b").cost_usd == COST and (ws.piece("b").attempts, ws.piece("b").tokens) == (2, 20)
    assert ws.piece("c") is None, "a cancelled piece is started over: no attempt"
    rate = 2 * COST / 40
    assert pieces.stopped_doubt(ws) == {
        "part": "cost",
        "pages": [],
        "kind": "other",
        "text": "Cost incomplete: 2 sessions stopped before their end, so the cost shown leaves them out. They used "
        f"120 tokens: about ${120 * rate:.2f}, estimated at this job's rate.",
    }


def test_a_stopped_session_with_nothing_to_estimate_from(tmp_path):
    ws = Workspace.create("cnv_000000000001", tmp_path / "data", _pdf(tmp_path))
    assert pieces.stopped_doubt(ws) is None, "nothing stopped, no doubt"

    async def timed_out():
        raise _stopped(AgentStopped("no answer within 10800 s", None), 30, 10)

    asyncio.run(run_piece(ws, "a", timed_out, list))
    assert pieces.stopped_doubt(ws)["text"] == (
        "Cost incomplete: 3 sessions stopped before their end, so the cost shown leaves them out. They used 120 "
        "tokens; no session of this job ended, so there is no rate to estimate the cost from."
    )


def test_a_limited_session_raises_paused(tmp_path):
    ws = Workspace.create("cnv_000000000001", tmp_path / "data", _pdf(tmp_path))
    agent = Agent({"sort": ["limit"]})

    with pytest.raises(Paused) as paused:
        asyncio.run(run_piece(ws, "sort", lambda: agent(ws, "sort"), list))

    assert paused.value.resets_at == LIMIT_NOTICE_RESET
    assert (ws.piece("sort").attempts, ws.is_done("sort")) == (0, False)
    assert ws.piece("sort").status == "paused", "a piece that only met the limit hasn't failed (DEL-91)"


def test_an_error_outside_a_piece_pauses_with_it_and_keeps_the_folder(storage, tmp_path):
    services, _ = _services(storage)

    async def broken(services, live, ws):
        raise RuntimeError("the stage broke")

    async def scenario():
        started = await start_thorough(
            services, _pdf(tmp_path), "The Caves", "ready", data_dir=tmp_path / "data", pipeline=broken
        )
        return await wait(services, started.id)

    paused = asyncio.run(scenario())

    assert (paused.status, paused.error) == ("paused", "the stage broke")
    ws = Workspace(tmp_path / "data" / "conversions" / paused.id)
    assert ws.exists() and ws.state().paused.reason == "the stage broke"
    assert services.resumes == {}, "an error waits for a resume by hand"


def test_resume_is_refused_unless_paused(storage, tmp_path):
    services, _ = _services(storage)
    agent = Agent({"a": ["hang"]})
    quick = storage.conversions.create("generate", "Kobolds", "ready")
    storage.conversions.save(replace(quick, status="done"))
    gone = storage.conversions.create("pdf", "Gone", "ready", target={"thorough": True, "folder": str(tmp_path / "x")})
    storage.conversions.save(replace(gone, status="paused"))
    paused = storage.conversions.create("pdf", "Paused", "ready")
    ws = Workspace.create(paused.id, tmp_path / "data", _pdf(tmp_path))
    storage.conversions.save(replace(paused, status="paused", target={"thorough": True, "folder": str(ws.root)}))

    async def scenario():
        with pytest.raises(NotPaused):
            await resume(services, quick.id)
        with pytest.raises(NotPaused):
            await resume(services, gone.id)  # its folder is gone
        with pytest.raises(KeyError):
            await resume(services, "cnv_unknown")
        started = await start_thorough(
            services, _pdf(tmp_path), "Running", "ready", data_dir=tmp_path / "data", pipeline=pipeline(["a"], agent)
        )
        await agent.hanging.wait()
        assert (await resume(services, paused.id)).status == "queued", "while another runs, it waits in the queue"
        await cancel(services, paused.id)
        await cancel(services, started.id)

    asyncio.run(scenario())


def test_a_piece_stopped_halfway_is_cleared_before_its_next_session(tmp_path):
    """DEL-92 (owner decision): a session that ended no attempt, cancelled (Delve stopping, a pause) or at the usage
    limit, leaves the piece `running`; its next session begins after `clear`. A failed attempt's files stay for the
    retry, as before, and a piece that ended is no longer `running`."""
    ws = Workspace.create("cnv_000000000001", tmp_path / "data", _pdf(tmp_path))
    cleared: list[str] = []
    agent = Agent({"a": ["hang"], "b": ["limit"], "c": ["crash"]})

    async def stopped_halfway():
        task = asyncio.create_task(run_piece(ws, "a", lambda: agent(ws, "a"), list, clear=lambda: cleared.append("a")))
        await agent.hanging.wait()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    asyncio.run(stopped_halfway())
    assert ws.was_stopped("a") and ws.state().running == ["a"] and cleared == []
    assert Workspace(ws.root).was_stopped("a"), "kept in state.json, for the run after Delve's restart"

    assert asyncio.run(run_piece(ws, "a", lambda: agent(ws, "a"), list, clear=lambda: cleared.append("a"))) == "done"
    assert cleared == ["a"] and not ws.was_stopped("a")

    with pytest.raises(Paused):
        asyncio.run(run_piece(ws, "b", lambda: agent(ws, "b"), list, clear=lambda: cleared.append("b")))
    assert ws.was_stopped("b"), "the usage limit stopped it halfway too"
    asyncio.run(run_piece(ws, "b", lambda: agent(ws, "b"), list, clear=lambda: cleared.append("b")))
    assert cleared == ["a", "b"]

    done = asyncio.run(run_piece(ws, "c", lambda: agent(ws, "c"), list, clear=lambda: cleared.append("c")))
    assert done == "done" and agent.calls[-2:] == ["c", "c"]
    assert cleared == ["a", "b"], "a failed attempt is retried on its files"
    assert ws.state().running == []
