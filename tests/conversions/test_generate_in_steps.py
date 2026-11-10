"""Generate in steps (DEL-134): a request scoped as a campaign is outlined, then written level by level, each with its
own map, and the organiser's answers to the scope questions go into its prompts and its making notes."""

import asyncio
import json

from delve.conversions import runner
from delve.conversions.runner import MAKING_NOTES, scope_generate, start_generate, wait
from delve.modules.books.campaign import ANSWERS_HEADING, Answer
from delve.modules.source import load_source
from tests.conversions.test_runner import Claude, _services, storage  # noqa: F401 (the fixture)
from tests.modules.books.test_campaign import Fake

REQUEST = "A sprawling multi-level dungeon, campaign-sized."


class CampaignClaude(Claude):
    """The runner tests' Claude, which also writes a campaign's outline, texts, levels and level maps."""

    def __init__(self, scale: str = "campaign") -> None:
        super().__init__()
        self.fake = Fake(scope=[json.dumps({"scale": scale, "questions": []})] * 3)
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        try:
            self.fake.kind(prompt)
        except AssertionError:
            return super().__call__(prompt)
        return self.fake.answer(prompt)


def test_a_campaign_is_written_in_steps_with_the_answers(storage):  # noqa: F811
    claude = CampaignClaude()
    services, dm, events = _services(storage, claude)
    answers = [Answer("How many levels?", "Five.", "Two"), Answer("Tone?", "Grim.")]

    async def scenario():
        started = await start_generate(services, REQUEST, "ready", scale="campaign", answers=answers)
        return await wait(services, started.id)

    done = asyncio.run(scenario())
    assert done.status == "done", done.error
    steps = [(d["step"], d["steps"]) for k, d in events if k == "conversion"]
    assert ("levels", {"index": 4, "count": 5}) in steps and ("maps", {"index": 5, "count": 5}) in steps
    assert not [p for p in claude.prompts if p.startswith("You help an organiser")], "scoped already: not again"
    written = [p for p in claude.prompts if "You write one level" in p]
    assert len(written) == 2 and all(ANSWERS_HEADING in p and "**Two**" in p for p in written)
    assert set(dm.side_timeouts) == {runner.CONVERSION_TIMEOUT}, "each step fits in a conversion's call"

    source = load_source(storage, done.module_id)
    assert [t.title for t in source.texts][:4] == [
        "The Weeping Deep",
        "History",
        "Level A: The Gallery",
        "Level B: The Brine",
    ]
    module = storage.modules.get(done.module_id)
    assert [m.name for m in module.maps] == ["level-a", "level-b"]
    notes = next(t for t in source.texts if t.id == MAKING_NOTES)
    assert "**How many levels?** Two" in notes.markdown and "**Tone?** Assumed: Grim." in notes.markdown


def test_a_request_without_a_scale_is_scoped_by_its_job(storage):  # noqa: F811
    claude = CampaignClaude()
    services, _, _ = _services(storage, claude)

    async def scenario():
        started = await start_generate(services, REQUEST, "ready")
        return await wait(services, started.id)

    done = asyncio.run(scenario())
    assert done.status == "done", done.error
    assert done.target == {"scale": "campaign"}
    assert len(storage.modules.get(done.module_id).maps) == 2


def test_a_queued_request_keeps_its_scale_and_answers(storage):  # noqa: F811
    services, _, _ = _services(storage, Claude())
    storage.conversions.set_queue_paused(True)

    queued = asyncio.run(
        start_generate(services, "Kobolds.", "ready", scale="module", answers=[Answer("Q?", "D.", "A")])
    )

    assert queued.status == "queued"
    assert queued.target == {
        "scale": "module",
        "request": "Kobolds.",
        "answers": [{"text": "Q?", "default": "D.", "answer": "A"}],
    }
    start = runner._restored(services, queued)
    assert start is not None


def test_scope_generate_asks_before_writing(storage):  # noqa: F811
    claude = CampaignClaude()
    claude.fake.overrides["scope"] = [
        json.dumps({"scale": "campaign", "questions": [{"text": "Levels?", "default": "Five."}]})
    ]
    services, _, _ = _services(storage, claude)

    scope = asyncio.run(scope_generate(services, REQUEST))

    assert scope.scale == "campaign" and [q.text for q in scope.questions] == ["Levels?"]
    assert storage.conversions.list() == [], "no job"


def test_answers_that_cant_be_noted_are_a_warning_of_the_done_job(storage, monkeypatch):  # noqa: F811
    """The answers are written into the making notes once the job is done: a failure there can't fail the job any
    more, so it is a warning rather than lost."""
    services, _, _ = _services(storage, CampaignClaude())

    def broken(*args, **kwargs):
        raise RuntimeError("the notes broke")

    monkeypatch.setattr(runner, "answer_questions", broken)

    async def scenario():
        started = await start_generate(services, REQUEST, "ready", scale="campaign", answers=[Answer("Q?", "D.", "A")])
        return await wait(services, started.id)

    done = asyncio.run(scenario())

    assert done.status == "done" and done.module_id is not None
    warning = next(w for w in storage.conversions.get(done.id).warnings if w["code"] == runner.ANSWERS_NOT_NOTED)
    assert "the notes broke" in warning["message"]
