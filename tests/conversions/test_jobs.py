"""Conversion jobs that make no module (plan 7 Task 6): `start_job` runs any work under plateau 5's one-at-a-time
rule, with its cancel and orphan handling, and `finish` ends it with a `result` instead of a module."""

import asyncio

import pytest

from delve.config import Config
from delve.conversions import (
    CONVERSION_TIMEOUT,
    ConversionRunning,
    ConversionServices,
    cancel,
    conversion_json,
    finish,
    look_for,
    progress_for,
    start_generate,
    start_job,
    wait,
)
from delve.conversions.runner import STEPS
from delve.dm.fake import FakeDM
from delve.domain.settings import BackendChoice
from delve.modules.source import Warning
from delve.storage import open_storage

TARGET = {"module_id": "mod_1", "name": "flanaess", "title": "The Flanaess"}


@pytest.fixture
def storage(tmp_path):
    opened = open_storage(Config(data_dir=tmp_path / "data"))
    yield opened
    opened.close()


def _services(storage, dm: FakeDM | None = None) -> tuple[ConversionServices, FakeDM, list[tuple[str, dict]]]:
    dm = dm or FakeDM([], vision_handler=lambda prompt, image, media_type: f"seen {len(image)} bytes")
    events: list[tuple[str, dict]] = []
    services = ConversionServices(
        storage=storage,
        conversion=lambda: (dm, BackendChoice("fake", "fake-large")),
        publish=lambda kind, data: events.append((kind, data)),
        ocr=None,
    )
    return services, dm, events


def test_the_new_kinds_have_their_steps():
    assert STEPS["worldmap"] == (("tiles",), ("grid",), ("terrain",), ("water",), ("places",), ("routes",))
    assert STEPS["dungeon-map"] == (("drawing",),)
    assert STEPS["book-map"] == (("drawing",),)


def test_a_job_reports_progress_looks_and_finishes_with_a_result(storage):
    services, dm, events = _services(storage)

    async def work(live):
        progress = progress_for(services, live)
        progress("tiles", 0, 2)
        progress("grid", 1, 1)
        seen = await look_for(services)("Which terrain?", b"\x89PNG....", "image/png")
        finish(services, live, result={"seen": seen}, warnings=[Warning("map-described", "Drawn.", "map:flanaess")])

    async def scenario():
        started = await start_job(services, "worldmap", "The Flanaess", work, target=TARGET)
        assert (started.kind, started.mode, started.status, started.target) == ("worldmap", "ready", "running", TARGET)
        return await wait(services, started.id)

    done = asyncio.run(scenario())

    assert (done.status, done.module_id, done.error) == ("done", None, None)
    assert done.result == {"seen": "seen 8 bytes"}
    assert done.target == TARGET
    assert done.warnings == [{"code": "map-described", "message": "Drawn.", "ref": "map:flanaess"}]
    assert storage.conversions.get(done.id) == done
    assert storage.modules.list() == [], "a job that makes no module makes none"
    assert dm.vision_prompts == ["Which terrain?"] and dm.vision_images == [("image/png", 8)]

    conversion = [data for kind, data in events if kind == "conversion"]
    assert [(d["step"], d["steps"]) for d in conversion[:2]] == [
        ("tiles", {"index": 1, "count": 6}),
        ("grid", {"index": 2, "count": 6}),
    ]
    assert conversion[-1]["status"] == "done"

    shown = conversion_json(done)
    assert (shown["target"], shown["result"], shown["questions"]) == (TARGET, {"seen": "seen 8 bytes"}, None)


def test_the_look_waits_for_the_conversion_timeout(storage):
    seen: list[float | None] = []

    class Timed(FakeDM):
        async def vision_call(self, prompt, image, media_type, choice, *, timeout=None, on_usage=None):
            seen.append(timeout)
            return "ok"

    services, _, _ = _services(storage, Timed([]))
    assert asyncio.run(look_for(services)("Look.", b"x", "image/png")) == "ok"
    assert seen == [CONVERSION_TIMEOUT]


def test_a_second_job_is_refused_while_one_runs(storage):
    services, _, _ = _services(storage)

    async def scenario():
        release = asyncio.Event()

        async def work(live):
            await release.wait()
            finish(services, live)

        first = await start_job(services, "dungeon-map", "A map", work, target={"module_id": "mod_1"})
        with pytest.raises(ConversionRunning) as refused:
            await start_job(services, "book-map", "Another", work)
        assert refused.value.conversion.id == first.id
        queued = await start_generate(services, "A dungeon with kobolds.", "ready")
        assert queued.status == "queued", "a request waits in the queue instead (DEL-141)"
        await cancel(services, queued.id)
        release.set()
        return await wait(services, first.id)

    assert asyncio.run(scenario()).status == "done"


def test_cancel_ends_a_job_cancelled_and_runs_its_cleanup(storage):
    services, _, events = _services(storage)
    cleaned: list[str] = []

    async def scenario():
        async def work(live):
            progress_for(services, live)("drawing", 0, 1)
            await asyncio.Event().wait()

        started = await start_job(services, "dungeon-map", "A map", work, cleanup=lambda: cleaned.append("done"))
        await asyncio.sleep(0)
        return await cancel(services, started.id)

    cancelled = asyncio.run(scenario())
    assert cancelled.status == "cancelled" and cancelled.result is None
    assert cleaned == ["done"]
    assert services.live == {}
    assert events[-1][1]["status"] == "cancelled"


def test_a_failing_job_fails_with_its_reason(storage):
    services, _, _ = _services(storage)

    async def scenario():
        async def work(live):
            raise RuntimeError("claude stopped (exit code 1): overloaded")

        started = await start_job(services, "book-map", "A map", work)
        return await wait(services, started.id)

    failed = asyncio.run(scenario())
    assert (failed.status, failed.error) == ("failed", "claude stopped (exit code 1): overloaded")


def test_a_late_finish_changes_nothing(storage):
    services, _, _ = _services(storage)

    async def scenario():
        async def work(live):
            finish(services, live, result={"n": 1})
            finish(services, live, result={"n": 2})

        started = await start_job(services, "dungeon-map", "A map", work)
        return await wait(services, started.id)

    assert asyncio.run(scenario()).result == {"n": 1}


def test_a_job_left_running_fails_at_the_next_start(storage):
    left = storage.conversions.create("worldmap", "The Flanaess", "ready", target=TARGET)
    services, _, _ = _services(storage)

    async def scenario():
        async def work(live):
            finish(services, live)

        started = await start_job(services, "dungeon-map", "A map", work)
        return await wait(services, started.id)

    assert asyncio.run(scenario()).status == "done"
    orphan = storage.conversions.get(left.id)
    assert (orphan.status, orphan.error) == ("failed", "Delve stopped during the conversion.")


def test_a_refused_start_runs_its_cleanup(storage):
    services, _, _ = _services(storage)
    cleaned: list[str] = []

    async def scenario():
        async def wait_forever(live):
            await asyncio.Event().wait()

        first = await start_job(services, "dungeon-map", "A map", wait_forever)
        with pytest.raises(ConversionRunning):
            await start_job(services, "book-map", "B", wait_forever, cleanup=lambda: cleaned.append("b"))
        await cancel(services, first.id)

    asyncio.run(scenario())
    assert cleaned == ["b"], "a refused job's upload is removed at once, as a refused PDF's is"
