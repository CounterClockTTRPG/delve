"""Novels written as jobs (novelization Task 5): start, Continue and the orphans, over `FakeDM(side_handler=…)`.

The fake writer answers an outline of `count` chapters, then each chapter as `CHAPTER-<n> …`, and may fail at one
chapter. Review Focus 3 (Delve stops mid-novella) and 4 (the source changes or goes) are here.
"""

import asyncio
import json
import re

import pytest

from delve.conversions import ConversionRunning, ConversionServices, close_orphans, runner, wait
from delve.dm.fake import FakeDM
from delve.dm.provider import Usage
from delve.domain.novels import Novel
from delve.domain.settings import BackendChoice
from delve.modules.source import ModuleSource, TextDoc, load_source, save_source
from delve.novels.jobs import (
    NOVEL_TIMEOUT,
    ORPHANED,
    NovelRequest,
    NovelServices,
    NovelStateError,
    close_orphan_novels,
    continue_novel,
    start_novel,
)
from delve.novels.material import SessionRangeError
from tests.novels.test_material import checksums, crypt_module, played, storage  # noqa: F401 (fixtures)

OUTLINE_START = "You are a novelist. You turn"
CHAPTER = re.compile(r"Now write chapter (\d+) of (\d+)")


class Writer:
    """The fake novelist. `stored` is read at each chapter call: the chapters written as stored then."""

    def __init__(self, count: int = 1, *, fail_at: int | None = None, title: str = "The Bell Below") -> None:
        self.count = count
        self.fail_at = fail_at
        self.title = title
        self.outlines: list[str] = []
        self.chapters: list[tuple[int, str]] = []
        self.on_chapter = lambda n: None

    def __call__(self, prompt: str) -> str:
        if prompt.startswith(OUTLINE_START):
            self.outlines.append(prompt)
            chapters = [{"title": f"Part {n}", "summary": f"SUMMARY-{n}"} for n in range(1, self.count + 1)]
            return json.dumps({"title": self.title, "chapters": chapters})
        found = CHAPTER.search(prompt)
        assert found, prompt[:200]
        number = int(found.group(1))
        self.chapters.append((number, prompt))
        self.on_chapter(number)
        if number == self.fail_at:
            raise RuntimeError("Claude didn't answer.")
        return f"CHAPTER-{number}: the bell tolled below."


def make(storage, writer: Writer):  # noqa: F811
    dm = FakeDM([], side_handler=writer, side_usage=Usage(100, 10, 0.01))
    events: list[tuple[str, dict]] = []
    conversions = ConversionServices(
        storage=storage,
        conversion=lambda: (_ for _ in ()).throw(AssertionError("the conversion job's choice isn't asked")),
        publish=lambda kind, data: events.append((kind, data)),
        ocr=None,
    )
    services = NovelServices(conversions, writer=lambda: (dm, BackendChoice("fake", "fake-large")))
    return services, dm, events


def written(novel: Novel) -> list[str | None]:
    return [chapter.text for chapter in novel.chapters]


def run(services, request=None, *, novel_id=None):
    """Start (or with `novel_id`, continue) a novel and wait for its job; answers the novel and its job as stored."""

    async def scenario():
        if novel_id is None:
            novel = await start_novel(services, request)
        else:
            novel = await continue_novel(services, novel_id)
        job = await wait(services.conversions, novel.conversion_id)
        return services.storage.novels.get(novel.id), job

    return asyncio.run(scenario())


def campaign_request(campaign, **choices) -> NovelRequest:
    return NovelRequest(source="campaign", id=campaign.id, **choices)


# ----- writing -----


def test_a_recap_ends_done_with_one_chapter(storage, played):  # noqa: F811
    writer = Writer(1)
    services, dm, _ = make(storage, writer)

    novel, job = run(services, campaign_request(played, tone="grimdark", instructions="Mira tells it."))

    assert novel.status == "done" and novel.error is None
    assert novel.title == "The Bell Below", "the writer's title"
    assert (novel.campaign_id, novel.module_id, novel.sessions) == (played.id, None, None)
    assert (novel.length, novel.tone, novel.language, novel.instructions) == (
        "recap",
        "grimdark",
        "en",
        "Mira tells it.",
    )
    assert written(novel) == ["CHAPTER-1: the bell tolled below."]
    assert (job.kind, job.title, job.status, job.target) == ("novel", "Novel: Tuesday", "done", {"novel_id": novel.id})
    assert job.result == {"novel_id": novel.id}
    assert novel.conversion_id == job.id
    assert novel.cost_usd == pytest.approx(0.02) == job.cost_usd, "an outline and a chapter"
    assert dm.side_timeouts == [NOVEL_TIMEOUT] * 2
    assert "The stair is cold." in writer.outlines[0] and "Mira tells it." in writer.outlines[0]


def test_a_novellas_chapters_are_saved_one_by_one(storage, played):  # noqa: F811
    writer = Writer(9)
    services, _, events = make(storage, writer)
    seen: list[int] = []
    writer.on_chapter = lambda n: seen.append(sum(text is not None for text in written(storage.novels.writing()[0])))

    novel, _ = run(services, campaign_request(played, length="novella"))

    assert novel.status == "done"
    assert seen == list(range(9)), "chapter n is called with the n-1 before it stored"
    assert written(novel) == [f"CHAPTER-{n}: the bell tolled below." for n in range(1, 10)]
    writing = [data for kind, data in events if kind == "conversion" and data["step"] == "writing"]
    assert [(e["done"], e["total"], e["status"]) for e in writing] == [
        *((n, 9, "running") for n in range(10)),
        (9, 9, "done"),
    ]
    assert {e["steps"]["index"] for e in writing} == {3}


def test_no_conversion_event_holds_the_novels_text(storage, played):  # noqa: F811
    services, _, events = make(storage, Writer(3))
    novel, _ = run(services, campaign_request(played, length="short-story"))
    published = json.dumps(events)
    assert events and all(kind == "conversion" for kind, _ in events)
    for secret in ("CHAPTER-", "SUMMARY-", novel.title, "The stair is cold."):
        assert secret not in published, secret


def test_a_failure_at_chapter_3_keeps_two_chapters_and_continue_writes_the_rest(storage, played):  # noqa: F811
    writer = Writer(5, fail_at=3)
    services, _, _ = make(storage, writer)

    failed, job = run(services, campaign_request(played, length="short-story"))

    assert failed.status == "failed" and failed.error == "Claude didn't answer." == job.error
    assert job.status == "failed"
    assert written(failed)[:2] == ["CHAPTER-1: the bell tolled below.", "CHAPTER-2: the bell tolled below."]
    assert written(failed)[2:] == [None, None, None]
    assert len(writer.outlines) == 1

    writer.fail_at = None
    writer.chapters.clear()
    novel, again = run(services, novel_id=failed.id)

    assert again.id != job.id and again.title == "Novel: Tuesday"
    assert novel.status == "done" and novel.error is None and novel.conversion_id == again.id
    assert [n for n, _ in writer.chapters] == [3, 4, 5], "only the missing chapters"
    assert len(writer.outlines) == 1, "the outline is kept"
    third = writer.chapters[0][1]
    assert "SUMMARY-1" in third and "SUMMARY-2" in third, "the running summary, rebuilt from what is stored"
    assert "CHAPTER-1" not in third, "never a chapter's text"
    assert written(novel) == [f"CHAPTER-{n}: the bell tolled below." for n in range(1, 6)]
    assert novel.cost_usd == pytest.approx(job.cost_usd + again.cost_usd), "both jobs' spend"


def test_continue_outlines_first_when_there_is_no_outline(storage, played):  # noqa: F811
    writer = Writer(1)
    services, _, _ = make(storage, writer)
    original = writer.__call__
    writer_calls = {"n": 0}

    def flaky(prompt):
        writer_calls["n"] += 1
        if writer_calls["n"] <= 2:  # the outline and its retry
            return "not json"
        return original(prompt)

    services.writer = lambda: (FakeDM([], side_handler=flaky), BackendChoice("fake", "fake-large"))
    failed, _ = run(services, campaign_request(played))
    assert failed.status == "failed" and failed.error.startswith("The outline couldn't be read")
    assert failed.chapters == [] and failed.title == "Tuesday"

    novel, _ = run(services, novel_id=failed.id)
    assert novel.status == "done" and novel.title == "The Bell Below" and len(novel.chapters) == 1


def test_continue_is_only_for_a_failed_or_cancelled_novel(storage, played):  # noqa: F811
    services, _, _ = make(storage, Writer(1))
    done, _ = run(services, campaign_request(played))
    with pytest.raises(NovelStateError):
        asyncio.run(continue_novel(services, done.id))
    with pytest.raises(KeyError):
        asyncio.run(continue_novel(services, "nov_missing"))


def test_cancel_leaves_a_cancelled_novel(storage, played):  # noqa: F811
    writer = Writer(5)
    services, _, _ = make(storage, writer)
    gate: dict = {}

    async def scenario():
        gate["event"] = asyncio.Event()
        held = asyncio.Event()

        def at_chapter(n):
            if n == 2:
                held.set()

        writer.on_chapter = at_chapter
        dm = FakeDM([], side_handler=writer)
        real = dm.side_call

        async def side_call(prompt, choice, **kw):
            answer = await real(prompt, choice, **kw)
            if held.is_set():
                await gate["event"].wait()
            return answer

        dm.side_call = side_call
        services.writer = lambda: (dm, BackendChoice("fake", "fake-large"))
        novel = await start_novel(services, campaign_request(played, length="short-story"))
        await held.wait()
        await runner.cancel(services.conversions, novel.conversion_id)
        return services.storage.novels.get(novel.id)

    cancelled = asyncio.run(scenario())
    assert cancelled.status == "cancelled" and written(cancelled)[0] is not None
    assert storage.conversions.get(cancelled.conversion_id).status == "cancelled"


def test_one_job_at_a_time_and_a_refused_start_leaves_no_novel(storage, played):  # noqa: F811
    services, _, _ = make(storage, Writer(1))

    async def scenario():
        gate = asyncio.Event()

        async def held(live):
            await gate.wait()
            runner.finish(services.conversions, live)

        other = await runner.start_job(services.conversions, "generate", "Another job", held)
        with pytest.raises(ConversionRunning):
            await start_novel(services, campaign_request(played))
        gate.set()
        await wait(services.conversions, other.id)

    asyncio.run(scenario())
    assert storage.novels.for_campaign(played.id) == []


# ----- the request is checked -----


@pytest.mark.parametrize(
    ("choices", "message"),
    [
        ({"length": "saga"}, "length"),
        ({"tone": "whimsical"}, "tone"),
        ({"tone": "custom", "custom_tone": "  "}, "custom tone"),
        ({"language": "es"}, "language"),
    ],
)
def test_a_bad_choice_is_refused(storage, played, choices, message):  # noqa: F811
    services, _, _ = make(storage, Writer(1))
    with pytest.raises(ValueError, match=message):
        asyncio.run(start_novel(services, campaign_request(played, **choices)))
    assert storage.novels.for_campaign(played.id) == []
    assert storage.conversions.list() == []


@pytest.mark.parametrize("sessions", [(3, 2), (0, 2), (1, 5)])
def test_a_bad_range_is_refused_with_a_hint(storage, played, sessions):  # noqa: F811
    services, _, _ = make(storage, Writer(1))
    with pytest.raises(SessionRangeError) as refused:
        asyncio.run(start_novel(services, campaign_request(played, sessions=sessions)))
    assert refused.value.hint
    assert storage.novels.for_campaign(played.id) == []


def test_a_range_is_kept_and_read(storage, played):  # noqa: F811
    writer = Writer(1)
    services, _, _ = make(storage, writer)
    novel, _ = run(services, campaign_request(played, sessions=(2, 2)))
    assert novel.sessions == (2, 2)
    assert "Aldric falls to the ghouls." in writer.outlines[0] and "The stair is cold." not in writer.outlines[0]


def test_a_module_novel_needs_no_sessions_and_an_unknown_source_is_a_key_error(storage, played):  # noqa: F811
    services, _, _ = make(storage, Writer(1))
    with pytest.raises(ValueError, match="sessions"):
        asyncio.run(start_novel(services, NovelRequest("module", played.module_id, sessions=(1, 1))))
    for source in ("campaign", "module"):
        with pytest.raises(KeyError):
            asyncio.run(start_novel(services, NovelRequest(source, "missing")))
    with pytest.raises(ValueError, match="source"):
        asyncio.run(start_novel(services, NovelRequest("world", played.id)))  # type: ignore[arg-type]
    with pytest.raises(KeyError):
        asyncio.run(start_novel(services, NovelRequest("module", played.module_id, revision=99)))


# ----- Review Focus 3: Delve stops mid-novella -----


def test_delve_stopping_mid_novella_fails_it_and_continue_writes_the_rest(storage, played):  # noqa: F811
    writer = Writer(9)
    services, _, _ = make(storage, writer)

    async def stopped():
        reached = asyncio.Event()
        writer.on_chapter = lambda n: reached.set() if n == 4 else None
        novel = await start_novel(services, campaign_request(played, length="novella"))
        await reached.wait()
        task = services.conversions.live[novel.conversion_id].task
        task.cancel()  # as the app's shutdown does: not a cancel the owner asked for
        await asyncio.gather(task, return_exceptions=True)
        return novel.id

    novel_id = asyncio.run(stopped())
    assert storage.novels.get(novel_id).status == "writing", "a stopped Delve leaves it writing"

    # The next start: the job and then the novel are closed.
    close_orphans(storage)
    assert [n.id for n in close_orphan_novels(storage)] == [novel_id]
    failed = storage.novels.get(novel_id)
    assert failed.status == "failed" and failed.error == ORPHANED == "Delve stopped while writing."
    assert sum(text is not None for text in written(failed)) == 3

    fresh, _, _ = make(storage, writer)  # a new process
    writer.on_chapter = lambda n: None
    writer.chapters.clear()
    novel, _ = run(fresh, novel_id=novel_id)
    assert novel.status == "done"
    assert [n for n, _ in writer.chapters] == list(range(4, 10))
    assert all(f"SUMMARY-{n}" in writer.chapters[0][1] for n in (1, 2, 3))


def test_close_orphan_novels_leaves_a_novel_whose_job_runs(storage, played):  # noqa: F811
    services, _, _ = make(storage, Writer(3))

    async def scenario():
        novel = await start_novel(services, campaign_request(played, length="short-story"))
        closed = close_orphan_novels(storage)
        await wait(services.conversions, novel.conversion_id)
        return closed

    assert asyncio.run(scenario()) == []


# ----- Review Focus 4: the source changes or goes -----


def test_the_campaign_deleted_while_written_fails_the_job_and_takes_the_novel(storage, played):  # noqa: F811
    writer = Writer(5)
    services, _, _ = make(storage, writer)
    writer.on_chapter = lambda n: storage.campaigns.delete(played.id) if n == 2 else None

    async def scenario():
        novel = await start_novel(services, campaign_request(played, length="short-story"))
        return novel.id, await wait(services.conversions, novel.conversion_id)

    novel_id, job = asyncio.run(scenario())
    assert job.status == "failed" and job.error == "The novel's source was deleted."
    assert storage.novels.get(novel_id) is None


def test_a_module_novel_keeps_reading_the_revision_it_started_with(storage, played):  # noqa: F811
    writer = Writer(3)
    services, _, _ = make(storage, writer)
    module_id = played.module_id
    latest = storage.revisions.latest(module_id)

    def edit(n):
        if n == 1:
            source = load_source(storage, module_id)
            texts = [TextDoc("crypt", "The Crypt", "gm", None, "# The Crypt\n\nNEW-REVISION-TEXT\n")]
            save_source(storage, module_id, ModuleSource(texts=texts, entities=source.entities))
            storage.revisions.snapshot(module_id)

    writer.on_chapter = edit
    novel, job = run(services, NovelRequest("module", module_id, length="short-story"))

    assert novel.status == "done" and novel.revision == latest.number
    assert job.title == "Novel: The Crypt of Saint Vellis"
    assert storage.revisions.latest(module_id).number == latest.number + 1, "the edit made a revision"
    assert all("NEW-REVISION-TEXT" not in prompt for _, prompt in writer.chapters)
    assert all("Behind the third niche" in prompt for _, prompt in writer.chapters)
    assert "Tenser" in writer.outlines[0], "the pregens are the party"


def test_a_module_novel_may_name_its_revision(storage, played):  # noqa: F811
    services, _, _ = make(storage, Writer(1))
    novel, _ = run(services, NovelRequest("module", played.module_id, revision=played.revision))
    assert novel.revision == played.revision and novel.status == "done"


# ----- reading never writes -----


def test_a_novel_job_writes_nothing_but_its_novel_and_its_job(storage, played, tmp_path):  # noqa: F811
    path = tmp_path / "data" / "delve.db"
    before = checksums(path)
    services, _, _ = make(storage, Writer(3))
    novel, _ = run(services, campaign_request(played, length="short-story"))
    assert novel.status == "done"
    after = checksums(path)
    for table in ("novels", "conversions"):
        before.pop(table)
        after.pop(table)
    assert after == before
