"""The stages of a thorough conversion (thorough conversion Task 6, Review Focus 2).

The agents are `tests/fakes/fake_claude_agent.py`, a fake `claude` on `PATH` that `run_agent` runs for real in the
job folder; the side calls (the drafts, the entities, the sketches) and the page classifier's look are a `FakeDM`. The
book has two parts keyed 1, 2, 3 each (the house and the ship), the house's map on page 3 and a picture on page 4."""

import asyncio
import json
import os
import re
import time
from pathlib import Path

import pytest

from delve.config import Config
from delve.conversions import ConversionServices, runner, wait
from delve.conversions.thorough import pause, pieces, pipeline, resume, start_thorough
from delve.conversions.thorough.workspace import Workspace, install_qa
from delve.dm.claude_cli.agent import run_agent
from delve.dm.fake import FakeDM
from delve.domain.settings import BackendChoice
from delve.storage import open_storage
from tests.fakes import fake_claude_agent
from tests.fakes.fake_claude_agent import COST, HOUSE, ORPHAN, SHIP, traced
from tests.fixtures.pdfs import image_page, picture_page, text_page, write_pdf

STAGES = [stage for (stage,) in runner.STEPS["pdf-thorough"]]
SKETCH = traced("Sketched", HOUSE)
SKETCHED_FIRST_LINE = "# Sketched from the room key: an invented layout."
REPOSITORY = Path(__file__).resolve().parents[3]


def _answer(prompt: str) -> str:
    """The side calls: a draft is the page's text, a sketch a map of three rooms, the entities none."""
    source = re.search(r"<source>\n(.*)\n</source>", prompt, re.DOTALL)
    if source:
        return source.group(1).replace("\n", "\n\n")
    if prompt.startswith("You draw a schematic map"):
        return SKETCH
    return "{}"


@pytest.fixture
def storage(tmp_path):
    opened = open_storage(Config(data_dir=tmp_path / "data"))
    yield opened
    opened.close()


@pytest.fixture
def agents(tmp_path, monkeypatch):
    """Install the fake agent; answers `(configure, calls)`: `configure(**config)` sets its plan and book, `calls()`
    the pieces its sessions ran, in order."""
    log = tmp_path / "agent-log.jsonl"

    def configure(**config):
        path = fake_claude_agent.install(tmp_path / "agent-bin", {"log": str(log), **config})
        monkeypatch.setenv("FAKE_AGENT_CONFIG", str(path))

    def calls() -> list[str]:
        return [json.loads(line)["piece"] for line in log.read_text().splitlines()] if log.exists() else []

    monkeypatch.setenv("PATH", f"{tmp_path / 'agent-bin'}:{os.environ['PATH']}")
    configure()
    return configure, calls


def _services(storage, data_dir: Path, timeout: float = 60.0):
    dm = FakeDM([], side_handler=_answer, vision_handler=lambda *_: '{"kind": "map", "title": "The Haunted House"}')
    events: list[dict] = []
    services = ConversionServices(
        storage=storage,
        conversion=lambda: (dm, BackendChoice("fake", "fake-large")),
        thorough=lambda: (dm, BackendChoice("fake", "opus")),
        agent=lambda prompt, folder, choice: run_agent(
            prompt, folder, choice, timeout=timeout, repo=REPOSITORY, data_dir=data_dir, qa=install_qa(data_dir)
        ),
        publish=lambda kind, data: events.append(data) if kind == "conversion" else None,
        ocr=None,
    )
    return services, events


def _book(tmp_path):
    return write_pdf(
        tmp_path / "upload.pdf",
        [
            text_page(HOUSE),
            text_page(SHIP),
            picture_page(),
            image_page(0.2, texts=["A ghost drifts through the hall of the haunted house, at night."]),
        ],
    )


def _convert(storage, tmp_path, timeout: float = 60.0):
    """Start the conversion and wait for it; the job as it ended, and its events."""
    services, events = _services(storage, tmp_path / "data", timeout)

    async def scenario():
        started = await start_thorough(services, _book(tmp_path), "Saltmarsh", "ready", data_dir=tmp_path / "data")
        return await wait(services, started.id)

    return asyncio.run(scenario()), events, services


def _doubts(job) -> list[dict]:
    return job.questions["doubts"]


def test_pipeline_end_to_end_with_fake_agents(storage, tmp_path, agents):
    _, calls = agents

    job, events, _ = _convert(storage, tmp_path)

    assert job.status == "done", job.error
    assert calls() == ["sort", "clean-1", "sort-orphans", "trace-house", "describe"]
    assert job.cost_usd == pytest.approx(5 * COST)
    steps = [e["step"] for e in events]
    assert list(dict.fromkeys(steps)) == STAGES, "every stage, in order"
    assert events[-1]["steps"] == {"index": len(STAGES), "count": len(STAGES)}
    assert not (tmp_path / "data" / "conversions" / job.id).exists()

    module = storage.modules.get(job.module_id)
    maps = {m.name: m for m in module.maps}
    assert [m.name for m in module.maps] == ["house", "ship"]
    assert maps["house"].source == traced("The Haunted House", HOUSE) and maps["house"].is_default
    assert maps["ship"].source.startswith(SKETCHED_FIRST_LINE), "the ship has keys and no map: it is sketched"
    source = runner.load_source(storage, job.module_id)
    texts = {t.id: t for t in source.texts}
    assert [t.id for t in source.texts] == ["house", "ship"]
    assert texts["house"].map == "house" and texts["ship"].map == "ship"
    assert ORPHAN in texts["ship"].markdown, "sort-orphans placed the clean piece's orphan"
    assert source.attachment("source-pdf") is not None
    kinds = {(d["piece"], d["kind"]) for d in _doubts(job)}
    assert ("clean-1", "checker-flag") in kinds and ("describe", "picture-unsure") in kinds
    assert ("sketch-ship", "sketched-map") in kinds and ("sketch-house", "sketched-map") not in kinds


def test_a_session_that_timed_out_makes_the_cost_a_doubt(storage, tmp_path, agents):
    """Review finding 7: the describe session times out once, with no cost; the job's cost is what was measured, and
    the doubts say it is incomplete, with the stopped session's cost estimated at the job's rate."""
    configure, calls = agents
    configure(plan={"describe": ["stall"]}, slow_seconds=30)

    job, _, _ = _convert(storage, tmp_path, timeout=3.0)

    assert job.status == "done", job.error
    assert calls() == ["sort", "clean-1", "sort-orphans", "trace-house", "describe", "describe"]
    assert job.cost_usd == pytest.approx(5 * COST), "the measured cost, never an estimate"
    [doubt] = [d for d in _doubts(job) if d["part"] == "cost"]
    assert doubt["text"] == (
        "Cost incomplete: 1 session stopped before its end, so the cost shown leaves it out. It used 150 tokens: "
        f"about ${COST:.2f}, estimated at this job's rate."
    )
    assert _doubts(job)[-1] == doubt, "last, after the pieces' doubts"


# (piece, the files its stopped session leaves that the restarted one mustn't see, other pieces' files that stay)
_STOPPED_PIECES = [
    (
        "sort",
        ["original.md", "parts.json", "keys/house.txt", "keys/ship.txt", "work/sort/trial.txt", "doubts/sort.json"],
        ["book.json", "classes.json", "drafted/texts.json"],
    ),
    (
        "clean-1",
        [
            "clean/house.md",
            "clean/ship.md",
            "clean/clean-1-orphans.md",
            "work/clean-1/trial.txt",
            "doubts/clean-1.json",
        ],
        ["parts.json", "original.md", "keys/house.txt", "draft/house.md", "doubts/sort.json"],
    ),
    (
        "trace-house",
        ["maps/house.dmap", "maps/house.exits.json", "work/trace-house/trial.txt", "doubts/trace-house.json"],
        ["clean/house.md", "clean/ship.md", "doubts/clean-1.json", "doubts/sort-orphans.json", "keys/house.txt"],
    ),
    (
        "describe",
        ["art/descriptions.json", "work/describe/trial.txt", "doubts/describe.json"],
        ["maps/house.dmap", "maps/ship.dmap", "doubts/trace-house.json", "clean/house.md"],
    ),
]


def _stopped_and_restarted(storage, tmp_path, agents, piece: str):
    """Delve stops `piece` halfway, by a pause by hand, once its session has written its files; resumed, the job
    ends. Answers the job and what each of the piece's two sessions saw in the folder as it began."""
    configure, _ = agents
    configure(plan={piece: ["partial"]}, slow_seconds=60)
    services, _ = _services(storage, tmp_path / "data")
    log = tmp_path / "agent-log.jsonl"

    def sessions() -> list[dict]:
        entries = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
        return [entry for entry in entries if entry["piece"] == piece]

    async def scenario():
        started = await start_thorough(services, _book(tmp_path), "Saltmarsh", "ready", data_dir=tmp_path / "data")
        trial = tmp_path / "data" / "conversions" / started.id / "work" / piece / "trial.txt"
        for _ in range(600):
            if trial.exists():
                break
            await asyncio.sleep(0.05)
        assert trial.exists(), "the session wrote its files"
        assert (await pause(services, started.id)).status == "paused"
        await resume(services, started.id)
        return await wait(services, started.id)

    job = asyncio.run(scenario())
    return job, [entry["seen"] for entry in sessions()]


@pytest.mark.parametrize(("piece", "own", "others"), _STOPPED_PIECES, ids=[p for p, _, _ in _STOPPED_PIECES])
def test_a_restarted_piece_starts_from_a_clean_slate(storage, tmp_path, agents, piece, own, others):
    """DEL-92 (owner decision): a piece Delve stopped halfway is started over from a clean slate. What its stopped
    session wrote in its own files (outputs, `work/<piece>/`, its doubts) is gone when the restarted session begins;
    the job's inputs and the other pieces' files stay."""
    job, (stopped, restarted) = _stopped_and_restarted(storage, tmp_path, agents, piece)

    assert job.status == "done", job.error
    assert not set(own) & set(stopped), "the first session began with none of them"
    left = [name for name in own if name in restarted]
    assert left == [], f"the restarted {piece} saw what the stopped session left"
    assert [name for name in others if name not in restarted] == [], "other pieces' files stay"
    assert "book.pdf" in restarted and "state.json" in restarted


def test_a_restarted_sort_orphans_starts_from_the_cleaning(storage, tmp_path, agents):
    """DEL-92: `sort-orphans` edits the cleaning pieces' files, so its clean slate is `clean/` as the cleaning left
    it: the orphans it had placed are back in their file, the ship's text holds none of them, and the orphan is
    placed once."""
    job, (stopped, restarted) = _stopped_and_restarted(storage, tmp_path, agents, "sort-orphans")

    assert job.status == "done", job.error
    assert restarted["clean/clean-1-orphans.md"] == stopped["clean/clean-1-orphans.md"] > 0, "the orphans are back"
    assert restarted["clean/ship.md"] == stopped["clean/ship.md"], "as the cleaning wrote it"
    assert restarted["clean/house.md"] == stopped["clean/house.md"]
    assert restarted["cleaned/ship.md"] == stopped["cleaned/ship.md"], "Delve's copy, kept for a restart"
    assert "work/sort-orphans/trial.txt" not in restarted and "doubts/sort-orphans.json" not in restarted
    assert "doubts/clean-1.json" in restarted, "the cleaning's doubts stay"
    ship = {t.id: t for t in runner.load_source(storage, job.module_id).texts}["ship"]
    assert ship.markdown.count(ORPHAN) == 1


def test_no_map_pages_sketches_and_doubts(storage, tmp_path, agents):
    configure, calls = agents
    configure(maps=False)

    job, _, _ = _convert(storage, tmp_path)

    assert job.status == "done", job.error
    assert not any(piece.startswith("trace-") for piece in calls()), "no map in the book: nothing to trace"
    module = storage.modules.get(job.module_id)
    assert sorted(m.name for m in module.maps) == ["house", "ship"]
    for module_map in module.maps:
        assert module_map.source.startswith(f"{SKETCHED_FIRST_LINE} No map page was found in the book.\n")
    texts = {t.id: t for t in runner.load_source(storage, job.module_id).texts}
    assert texts["house"].map == "house" and texts["ship"].map == "ship"
    sketched = [d for d in _doubts(job) if d["kind"] == "sketched-map"]
    assert sorted(d["part"] for d in sketched) == ["house", "ship"]
    assert all("no map in the book" in d["text"] for d in sketched)
    assert [d["pages"] for d in sorted(sketched, key=lambda d: d["part"])] == [[1], [2]]


def test_skipped_trace_falls_back_to_sketch_with_doubt(storage, tmp_path, agents):
    configure, calls = agents
    configure(plan={"trace-house": ["crash", "empty", "crash"]})

    job, _, _ = _convert(storage, tmp_path)

    assert job.status == "done", job.error
    assert calls().count("trace-house") == 3
    module = storage.modules.get(job.module_id)
    house = next(m for m in module.maps if m.name == "house")
    assert house.source.startswith(SKETCHED_FIRST_LINE), "the sketch takes the traced map's name"
    assert "page 3" in house.source.splitlines()[0]
    doubts = _doubts(job)
    assert any(d["kind"] == "sketched-map" and d["part"] == "house" and d["pages"] == [3] for d in doubts)
    assert any(d["piece"] == "trace-house" and "Skipped after 3 failed attempts" in d["text"] for d in doubts)
    assert job.cost_usd == pytest.approx(5 * COST), "the empty session's cost counts too; a crash reports none"


def test_skipped_clean_keeps_draft_with_doubt(storage, tmp_path, agents):
    configure, calls = agents
    configure(plan={"clean-1": ["empty", "empty", "empty"]})

    job, _, _ = _convert(storage, tmp_path)

    assert job.status == "done", job.error
    assert "sort-orphans" not in calls(), "nothing was left to place"
    texts = {t.id: t for t in runner.load_source(storage, job.module_id).texts}
    assert texts["house"].markdown == fake_claude_agent.markdown(HOUSE)
    assert texts["ship"].markdown == fake_claude_agent.markdown(SHIP)
    not_cleaned = [d for d in _doubts(job) if "not cleaned" in d["text"]]
    assert sorted(d["part"] for d in not_cleaned) == ["house", "ship"]


def test_stage_error_pauses_with_error(storage, tmp_path, agents, monkeypatch):
    _, calls = agents
    services, _ = _services(storage, tmp_path / "data")

    join_folder, broke = pipeline.join_folder, []

    def broken(maps, out):
        if not broke:
            broke.append(True)
            raise RuntimeError("the joiner broke")
        return join_folder(maps, out)

    monkeypatch.setattr(pipeline, "join_folder", broken)

    async def scenario():
        started = await start_thorough(services, _book(tmp_path), "Saltmarsh", "ready", data_dir=tmp_path / "data")
        paused = await wait(services, started.id)
        ws = Workspace(tmp_path / "data" / "conversions" / started.id)
        assert paused.status == "paused" and paused.error == "the joiner broke"
        assert ws.exists(), "the folder is kept for a resume"
        assert [s for s in STAGES if ws.is_stage_done(s)] == STAGES[: STAGES.index("joining")]
        cost = paused.cost_usd
        await resume(services, started.id)
        return cost, await wait(services, started.id)

    cost, done = asyncio.run(scenario())

    assert done.status == "done" and done.error is None
    assert calls() == ["sort", "clean-1", "sort-orphans", "trace-house", "describe"], "finished pieces never rerun"
    assert cost == pytest.approx(4 * COST) and done.cost_usd == pytest.approx(5 * COST)


def _drafting_breaks(storage, tmp_path, monkeypatch, failures: int):
    """Services whose draft of the ship's page fails `failures` times (a claude that exited 1), a chunk per page and
    no wait between attempts; answers the services and the draft prompts sent, each page's by its title."""
    monkeypatch.setattr(pipeline, "chunk_pages", lambda pages, title=None: [[page] for page in pages])
    monkeypatch.setattr(pipeline, "DRAFT_RETRY_DELAYS", (0.0, 0.0))
    services, _ = _services(storage, tmp_path / "data")
    sent: list[str] = []
    left = [failures]

    def answer(prompt: str) -> str:
        source = re.search(r"<source>\n(.*)\n</source>", prompt, re.DOTALL)
        if source:
            sent.append(next((part[0] for part in (HOUSE, SHIP) if part[0][2:] in source.group(1)), "other"))
            if sent[-1] == SHIP[0] and left[0] > 0:
                left[0] -= 1
                raise RuntimeError("claude stopped (exit code 1): API Error: 529 Overloaded")
        return _answer(prompt)

    services.conversion()[0]._side_handler = answer
    return services, sent


def test_a_failed_draft_call_is_tried_again(storage, tmp_path, agents, monkeypatch):
    services, sent = _drafting_breaks(storage, tmp_path, monkeypatch, failures=2)

    async def scenario():
        started = await start_thorough(services, _book(tmp_path), "Saltmarsh", "ready", data_dir=tmp_path / "data")
        return await wait(services, started.id)

    job = asyncio.run(scenario())

    assert job.status == "done", job.error
    assert sent.count(SHIP[0]) == 3, "two failures, then the third attempt"


@pytest.mark.parametrize("slow_disk", [False, True])
def test_a_resumed_drafting_keeps_the_chunks_already_drafted(storage, tmp_path, agents, monkeypatch, slow_disk):
    """With `slow_disk`, a chunk's answer is still being written when the ship's third failure cancels it: it is
    kept all the same (a machine under load once lost it, and the resume drafted the house again)."""
    services, sent = _drafting_breaks(storage, tmp_path, monkeypatch, failures=3)
    if slow_disk:
        keep = pipeline._keep
        monkeypatch.setattr(pipeline, "_keep", lambda path, text: (time.sleep(0.3), keep(path, text)))

    async def scenario():
        started = await start_thorough(services, _book(tmp_path), "Saltmarsh", "ready", data_dir=tmp_path / "data")
        paused = await wait(services, started.id)
        assert paused.status == "paused"
        assert paused.error == "claude stopped (exit code 1): API Error: 529 Overloaded"
        before = list(sent)
        await resume(services, started.id)
        return before, await wait(services, started.id)

    before, done = asyncio.run(scenario())

    assert done.status == "done", done.error
    assert before.count(HOUSE[0]) == 1 and before.count(SHIP[0]) == 3
    resumed = sent[len(before) :]
    assert SHIP[0] in resumed and HOUSE[0] not in resumed, "the resume never drafts a chunk again"


def test_the_usage_limit_while_drafting_pauses_until_the_reset(storage, tmp_path, agents, monkeypatch):
    services, _ = _drafting_breaks(storage, tmp_path, monkeypatch, failures=0)
    dm = services.conversion()[0]

    def limited(prompt: str) -> str:
        raise RuntimeError("claude stopped (exit code 1): You've hit your session limit · resets 3pm (UTC)")

    dm._side_handler = limited

    async def scenario():
        started = await start_thorough(services, _book(tmp_path), "Saltmarsh", "ready", data_dir=tmp_path / "data")
        job = await wait(services, started.id)
        return job, Workspace(tmp_path / "data" / "conversions" / started.id).state().paused

    job, paused = asyncio.run(scenario())

    assert job.status == "paused"
    assert paused.reason == pieces.USAGE_LIMIT and paused.resets_at == "3pm (UTC)"
    assert len(dm.side_prompts) <= pipeline.DRAFT_CALLS, "the limit isn't tried again"


LIMIT = "claude stopped (exit code 1): You've hit your session limit · resets 3pm (UTC)"


def _limited_at(storage, tmp_path, monkeypatch, *, look: bool = False, entities: bool = False):
    """Run a conversion whose page look (`look`) or entities call (`entities`) meets the usage limit; answers the job
    as it ended, the stages done and the folder's pause."""
    services, _ = _drafting_breaks(storage, tmp_path, monkeypatch, failures=0)
    dm = services.conversion()[0]
    handler = dm._side_handler

    def side(prompt: str) -> str:
        if entities and "<text>" in prompt:
            raise RuntimeError(LIMIT)
        return handler(prompt)

    def vision(*_):
        if look:
            raise RuntimeError(LIMIT)
        return '{"kind": "map", "title": "The Haunted House"}'

    dm._side_handler = side
    dm._vision_handler = vision

    async def scenario():
        started = await start_thorough(services, _book(tmp_path), "Saltmarsh", "ready", data_dir=tmp_path / "data")
        job = await wait(services, started.id)
        ws = Workspace(tmp_path / "data" / "conversions" / started.id)
        return job, [s for s in STAGES if ws.is_stage_done(s)], ws.state().paused

    return asyncio.run(scenario())


def test_the_usage_limit_while_classifying_pauses_the_job(storage, tmp_path, agents, monkeypatch):
    """A failed look leaves a page a picture with a warning; the usage limit isn't such a failure: the stage would be
    done, and the module poorer, for a limit that resets in hours."""
    job, done, paused = _limited_at(storage, tmp_path, monkeypatch, look=True)

    assert job.status == "paused", job.error
    assert "classifying" not in done
    assert paused.reason == pieces.USAGE_LIMIT and paused.resets_at == "3pm (UTC)"


def test_the_usage_limit_while_reading_the_entities_pauses_the_job(storage, tmp_path, agents, monkeypatch):
    job, done, paused = _limited_at(storage, tmp_path, monkeypatch, entities=True)

    assert job.status == "paused", job.error
    assert "drafting" in done and "entities" not in done
    assert paused.reason == pieces.USAGE_LIMIT and paused.resets_at == "3pm (UTC)"


def test_a_draft_the_content_filter_blocks_keeps_the_pages_text(storage, tmp_path, agents, monkeypatch):
    """The API blocks an answer that repeats a book's text at length: tried again, it is blocked again, so the
    drafting keeps the text read from the PDF for that chunk, says so, and goes on."""
    services, sent = _drafting_breaks(storage, tmp_path, monkeypatch, failures=0)
    dm = services.conversion()[0]
    handler = dm._side_handler

    def filtered(prompt: str) -> str:
        if SHIP[0][2:] in prompt and "<source>" in prompt:
            sent.append(SHIP[0])
            raise RuntimeError("claude stopped (exit code 1): API Error: Output blocked by content filtering policy")
        return handler(prompt)

    dm._side_handler = filtered

    async def scenario():
        started = await start_thorough(services, _book(tmp_path), "Saltmarsh", "ready", data_dir=tmp_path / "data")
        return await wait(services, started.id)

    job = asyncio.run(scenario())

    assert job.status == "done", job.error
    assert sent.count(SHIP[0]) == 1, "a blocked answer isn't asked for again"
    codes = [w["code"] for w in job.warnings]
    assert "content-filtered" in codes and "conversion-short" in codes


def test_unreadable_doubts_file_is_a_doubt(storage, tmp_path, agents):
    configure, _ = agents
    configure(plan={"describe": ["bad-doubts"]})

    job, _, _ = _convert(storage, tmp_path)

    assert job.status == "done", job.error
    assert {"piece": "describe", "part": "describe", "pages": [], "kind": "other",
            "text": "The agent's doubts file was unreadable."} in _doubts(job)  # fmt: skip


def test_clean_groups_hold_at_most_25_pages():
    parts = [{"id": f"p{n}", "pages": [1, pages]} for n, pages in enumerate([10, 10, 10, 30, 5], start=1)]

    assert [[p["id"] for p in group] for group in pipeline.clean_groups(parts)] == [
        ["p1", "p2"],
        ["p3"],
        ["p4"],
        ["p5"],
    ]


def test_without_the_claude_cli_the_job_pauses_at_the_first_agent(storage, tmp_path, agents):
    services, _ = _services(storage, tmp_path / "data")
    services.agent = None

    async def scenario():
        started = await start_thorough(services, _book(tmp_path), "Saltmarsh", "ready", data_dir=tmp_path / "data")
        return await wait(services, started.id)

    job = asyncio.run(scenario())

    assert job.status == "paused" and job.error == pipeline.NO_AGENT
    ws = Workspace(tmp_path / "data" / "conversions" / job.id)
    assert ws.exists() and not ws.state().stages, "nothing ran, nothing was skipped"


def test_the_sort_is_told_when_its_pictures_are_not_pages(tmp_path):
    (tmp_path / "draft").mkdir()
    (tmp_path / "draft" / "house.md").write_text("# The House\n", "utf-8")
    part = {"id": "house", "title": "The House", "maps": []}
    for pictures, told in (([3, {"name": "m", "page": 4}], False), (["3"], True), ([{"name": "m"}], True), (3, True)):
        (tmp_path / "parts.json").write_text(json.dumps({"parts": [part], "pictures": pictures}), "utf-8")
        problems = pipeline._sort_problems(tmp_path)
        assert ("parts.json: `pictures` as a list of page numbers" in problems) is told, pictures
