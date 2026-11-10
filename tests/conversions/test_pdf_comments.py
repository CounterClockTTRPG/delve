"""Comments on the PDF form (table voice and fixes Task F1): kept on the job, queued ones too, and given to every
prompt of the job that reads the book, quick and thorough, after its task, under "The organiser's comments"."""

import asyncio

from delve.conversions import runner, start_pdf, wait
from delve.conversions.runner import COMMENTS_MAX, with_comments
from delve.conversions.thorough import start_thorough
from tests.conversions.test_runner import Claude, _caves_pdf, _services, storage  # noqa: F401 (the fixture)
from tests.conversions.thorough.test_pipeline import _book, agents  # noqa: F401 (the fixture)
from tests.conversions.thorough.test_pipeline import _services as thorough_services

COMMENTS = "Skip the appendix of pregenerated characters; room 7's trap is a pit, not a blade."
SECTION = "## The organiser's comments\n\n" + COMMENTS


def test_comments_max_is_2000():
    assert COMMENTS_MAX == 2000


def test_with_comments_follows_the_task():
    assert with_comments("Do the task.", COMMENTS) == f"Do the task.\n\n{SECTION}\n"
    assert with_comments("Do the task.", "  ") == "Do the task."


def test_comments_stored_on_the_job(storage, tmp_path):  # noqa: F811
    services, _, _ = _services(storage, Claude())

    async def scenario():
        started = await start_pdf(services, _caves_pdf(tmp_path), "The Kobold Caves", "ready", comments=COMMENTS)
        assert storage.conversions.get(started.id).comments == COMMENTS
        return await wait(services, started.id)

    assert asyncio.run(scenario()).comments == COMMENTS


def test_a_queued_job_keeps_its_comments(storage, tmp_path):  # noqa: F811
    services, _, _ = _services(storage, Claude())
    storage.conversions.set_queue_paused(True)

    async def scenario():
        return await start_pdf(services, _caves_pdf(tmp_path), "The Kobold Caves", "ready", comments=COMMENTS)

    queued = asyncio.run(scenario())
    assert queued.status == "queued" and storage.conversions.get(queued.id).comments == COMMENTS


def test_quick_prompts_hold_the_comments(storage, tmp_path):  # noqa: F811
    services, dm, _ = _services(storage, Claude())

    async def scenario():
        started = await start_pdf(services, _caves_pdf(tmp_path), "The Kobold Caves", "ready", comments=COMMENTS)
        return await wait(services, started.id)

    assert asyncio.run(scenario()).status == "done"
    prompts = dm.side_prompts + dm.vision_prompts
    converting = [p for p in dm.side_prompts if "<source>" in p]
    assert converting and dm.vision_prompts, "the book was read and its picture page looked at"
    assert all(p.rstrip().endswith(SECTION) for p in prompts), "every prompt of the job, the comments after its task"


def test_no_comments_no_section(storage, tmp_path):  # noqa: F811
    services, dm, _ = _services(storage, Claude())

    async def scenario():
        started = await start_pdf(services, _caves_pdf(tmp_path), "The Kobold Caves", "ready")
        return await wait(services, started.id)

    done = asyncio.run(scenario())
    assert done.status == "done" and done.comments == ""
    assert not any("The organiser's comments" in p for p in dm.side_prompts + dm.vision_prompts)


def test_thorough_prompts_hold_the_comments(storage, tmp_path, agents):  # noqa: F811
    services, _ = thorough_services(storage, tmp_path / "data")
    sent: list[str] = []
    agent = services.agent

    async def spy(prompt, folder, choice):
        sent.append(prompt)
        return await agent(prompt, folder, choice)

    services.agent = spy
    dm, _ = services.thorough()

    async def scenario():
        started = await start_thorough(
            services, _book(tmp_path), "Saltmarsh", "ready", data_dir=tmp_path / "data", comments=COMMENTS
        )
        assert storage.conversions.get(started.id).comments == COMMENTS
        return await wait(services, started.id)

    done = asyncio.run(scenario())
    assert done.status == "done", done.error
    assert sent and dm.side_prompts and dm.vision_prompts
    for prompt in sent + dm.side_prompts + dm.vision_prompts:
        assert prompt.rstrip().endswith(SECTION)
    assert all(p.startswith("PIECE: ") for p in sent), "a brief still starts with its piece"
    assert runner.load_source(storage, done.module_id).texts
