"""Histories written as jobs (carry-the-party-on plan Task 5), over `FakeDM(side_handler=…)`.

The fake writer answers the DM's prompt (the one that asks for Loose ends) with `DM-HISTORY` and the table's with
`TABLE-HISTORY`. Review Focus 2 (a job already running when the party is carried on) and 5 (an edited history and
Write again) are here.
"""

import asyncio
from dataclasses import replace

import pytest

from delve.conversions import ConversionServices, close_orphans, runner, wait
from delve.dm.fake import FakeDM
from delve.dm.provider import Usage
from delve.domain.characters import Item
from delve.domain.histories import History
from delve.domain.settings import BackendChoice
from delve.histories.jobs import (
    ORPHANED,
    RUNNING_MSG,
    HistoryEdited,
    close_orphan_histories,
    start_history,
)
from delve.novels.jobs import NovelServices
from tests.histories.test_material import SECRETS, secrets  # noqa: F401 (a fixture)
from tests.novels.test_material import played, storage  # noqa: F401 (fixtures)


class Writer:
    """The fake historian, which may fail at the table's text."""

    def __init__(self, *, fail_table: bool = False) -> None:
        self.fail_table = fail_table
        self.prompts: list[tuple[str, str]] = []

    def __call__(self, prompt: str) -> str:
        audience = "dm" if "Loose ends" in prompt else "table"
        self.prompts.append((audience, prompt))
        if audience == "table" and self.fail_table:
            raise RuntimeError("Claude didn't answer.")
        return "## The party\n\nDM-HISTORY" if audience == "dm" else "## The party\n\nTABLE-HISTORY"


def make(storage, writer: Writer):  # noqa: F811
    dm = FakeDM([], side_handler=writer, side_usage=Usage(100, 10, 0.01))
    events: list[tuple[str, dict]] = []
    where: list[dict] = []
    conversions = ConversionServices(
        storage=storage,
        conversion=lambda: (_ for _ in ()).throw(AssertionError("the conversion job's choice isn't asked")),
        publish=lambda kind, data, **at: (events.append((kind, data)), where.append({"kind": kind, **at})),
        ocr=None,
    )
    services = NovelServices(conversions, writer=lambda: (dm, BackendChoice("fake", "fake-large")))
    services.where = where  # where each event went, for the `history` events' table
    return services, events


@pytest.fixture
def carried(storage, played):  # noqa: F811 (fixtures)
    """The campaign the crypt's party was carried on into."""
    return storage.campaigns.create(
        "Barrowmaze", played.module_id, played.revision, ruleset="osric", setting="greyhawk"
    )


def run(services, to_id: str, from_id: str, **options) -> History:
    """Start the history and wait for its job; answers the history as stored."""

    async def scenario():
        history = await start_history(services, to_id, from_id, **options)
        await wait(services.conversions, history.conversion_id)
        return services.storage.histories.get(to_id)

    return asyncio.run(scenario())


def test_writes_dm_then_table_and_ends_done(storage, secrets, carried):  # noqa: F811
    writer = Writer()
    services, events = make(storage, writer)

    history = run(services, carried.id, secrets.id)

    assert history.status == "done" and history.error is None and not history.edited
    assert (history.dm_md, history.table_md) == ("## The party\n\nDM-HISTORY", "## The party\n\nTABLE-HISTORY")
    assert [audience for audience, _ in writer.prompts] == ["dm", "table"]
    (_, dm_prompt), (_, table_prompt) = writer.prompts
    assert "SECRETWORD" in dm_prompt, "the DM's material holds the secrets"
    for secret in SECRETS:
        assert secret not in table_prompt, secret
    assert "-37" not in table_prompt
    job = storage.conversions.get(history.conversion_id)
    assert (job.kind, job.title, job.status) == ("history", "History: Tuesday", "done")
    assert job.target == job.result == {"campaign_id": carried.id}
    steps = [(e["step"], e["done"], e["total"]) for kind, e in events if kind == "conversion" and e.get("step")]
    assert ("writing", 0, 2) in steps and ("writing", 1, 2) in steps and ("writing", 2, 2) in steps
    for _, event in events:
        assert "DM-HISTORY" not in str(event) and "TABLE-HISTORY" not in str(event)
    # Its table hears each change, ids only, instead of asking every few seconds (DEL-172): started, each text, done.
    told = [data for kind, data in events if kind == "history"]
    assert told == [{"campaign_id": carried.id}] * 4
    assert {(w["scope"], w["campaign_id"]) for w in services.where if w["kind"] == "history"} == {("table", carried.id)}


def test_cost_recorded(storage, played, carried):  # noqa: F811
    services, _ = make(storage, Writer())

    history = run(services, carried.id, played.id)

    assert history.cost_usd == pytest.approx(0.02) == storage.conversions.get(history.conversion_id).cost_usd


def test_running_job_gives_failed_history_with_message(storage, played, carried):  # noqa: F811
    writer = Writer()
    services, _ = make(storage, writer)

    async def scenario():
        gate = asyncio.Event()

        async def held(live):
            await gate.wait()
            runner.finish(services.conversions, live)

        other = await runner.start_job(services.conversions, "novel", "Novel: Tuesday", held)
        history = await start_history(services, carried.id, played.id)  # never ConversionRunning
        gate.set()
        await wait(services.conversions, other.id)
        return history

    history = asyncio.run(scenario())
    assert history.status == "failed"
    assert history.error == RUNNING_MSG == "A conversion is running: write the history again when it ends."
    assert storage.histories.get(carried.id) == history
    assert storage.campaigns.get(carried.id) is not None, "the campaign is still made"
    assert writer.prompts == []

    again = run(services, carried.id, played.id)  # Write again, once the other job has ended
    assert again.status == "done" and again.error is None and again.table_md.endswith("TABLE-HISTORY")


def test_failure_keeps_campaign_and_marks_failed(storage, played, carried):  # noqa: F811
    services, events = make(storage, Writer(fail_table=True))

    history = run(services, carried.id, played.id)

    assert history.status == "failed" and history.error == "Claude didn't answer."
    assert history.dm_md.endswith("DM-HISTORY"), "the DM's text was saved as it ended"
    assert [kind for kind, _ in events if kind == "history"] == ["history"] * 3  # started, the DM's text, failed
    assert storage.campaigns.get(carried.id) is not None
    assert storage.conversions.get(history.conversion_id).status == "failed"


def test_edited_needs_overwrite(storage, played, carried):  # noqa: F811
    services, _ = make(storage, Writer())
    storage.histories.put(History(carried.id, dm_md="MINE", table_md="OURS", status="done", edited=True))

    with pytest.raises(HistoryEdited):
        asyncio.run(start_history(services, carried.id, played.id))
    assert storage.histories.get(carried.id).dm_md == "MINE", "refused, the edit stays"

    history = run(services, carried.id, played.id, overwrite=True)
    assert history.status == "done" and not history.edited
    assert history.dm_md.endswith("DM-HISTORY")


def test_an_overwrite_failing_halfway_stays_edited(storage, played, carried):  # noqa: F811
    """Review fix: `edited` holds until a Write again ends done, so a failed overwrite still asks to confirm."""
    services, _ = make(storage, Writer(fail_table=True))
    storage.histories.put(History(carried.id, dm_md="MINE", table_md="OURS", status="done", edited=True))

    async def scenario():
        started = await start_history(services, carried.id, played.id, overwrite=True)
        assert started.status == "writing" and started.edited, "still edited while the job runs"
        await wait(services.conversions, started.conversion_id)
        return storage.histories.get(carried.id)

    history = asyncio.run(scenario())
    assert history.status == "failed" and history.edited
    assert history.table_md == "OURS", "the table's text wasn't replaced"
    with pytest.raises(HistoryEdited):
        asyncio.run(start_history(services, carried.id, played.id))


def test_the_carried_pcs_things_reach_the_writer(storage, secrets, carried):  # noqa: F811
    """The material holds what the carried PCs and the party carry, read from the carry the new campaign came by."""
    aldric = next(c for c in storage.characters.list(secrets.id) if c.name == "Aldric")
    mira = next(c for c in storage.characters.list(secrets.id) if c.name == "Mira")
    storage.characters.save(replace(aldric, state=replace(aldric.state, inventory=(Item("Aldric's shield"),))))
    storage.carries.add(secrets.id, carried.id, [mira.id])
    writer = Writer()
    services, _ = make(storage, writer)

    run(services, carried.id, secrets.id)

    for audience, prompt in writer.prompts:
        assert "Silk rope" in prompt and "a moonstone" in prompt and "The crypt cart" in prompt, audience
        assert "Aldric's shield" not in prompt, audience
    (_, dm_prompt), (_, table_prompt) = writer.prompts
    assert "POSSESSION-NOTES-XYZ" in dm_prompt and "POSSESSION-NOTES-XYZ" not in table_prompt


def test_an_unknown_old_campaign_is_a_key_error(storage, carried):  # noqa: F811
    services, _ = make(storage, Writer())

    with pytest.raises(KeyError):
        asyncio.run(start_history(services, carried.id, "cmp_000000000000"))
    assert storage.histories.get(carried.id) is None


def test_orphan_closed_at_start(storage, played, carried):  # noqa: F811
    left = storage.conversions.create("history", "History: Tuesday", "ready")
    storage.histories.put(History(carried.id, dm_md="HALF", status="writing", conversion_id=left.id))

    close_orphans(storage)
    [closed] = close_orphan_histories(storage)
    assert (closed.campaign_id, closed.status, closed.error) == (carried.id, "failed", ORPHANED)
    assert closed.dm_md == "HALF"
    assert ORPHANED == "Delve stopped while writing."
    assert close_orphan_histories(storage) == []


def test_close_orphan_histories_leaves_a_history_whose_job_runs(storage, played, carried):  # noqa: F811
    services, _ = make(storage, Writer())

    async def scenario():
        history = await start_history(services, carried.id, played.id)
        closed = close_orphan_histories(storage)
        await wait(services.conversions, history.conversion_id)
        return closed

    assert asyncio.run(scenario()) == []
