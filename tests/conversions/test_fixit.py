"""Fix-it comments (table voice and fixes Task F2.1): a comment on a module starts a `fixit` job that proposes the
change it asks for; nothing is saved before Keep, Keep makes a new revision and refuses a module changed since the job
read it, and a module runs one fix-it job at a time.

Claude is FakeDM's side handler (`Claude`), answering the fix-it prompt with `ADD_EXIT` unless told otherwise."""

import asyncio
import json
from contextlib import contextmanager
from dataclasses import replace

import pytest

from delve.config import Config
from delve.conversions import ConversionServices, fixit, runner, wait
from delve.conversions.fixit import (
    CHANGED_UNASKED,
    FIXIT_PROMPT,
    NOT_SHOWN_WHOLE,
    PROMPT_BUDGET,
    FixitStale,
    close_comment,
    comments,
    is_stale,
    keep,
    reject,
    rerun,
    send_comment,
)
from delve.dm.fake import FakeDM
from delve.domain.modules import ModuleMap
from delve.domain.settings import BackendChoice
from delve.modules.source import ModuleSource, TextDoc, load_source, save_source
from delve.storage import open_storage
from tests.modules.books.test_sketch import GOOD

CAVES = (
    "# The Kobold Caves\n\n## 1. Entrance\n\nSteps down.\n\n## 2. Hall\n\nA long hall.\n\n## C3. Shrine\n\nAn altar.\n"
)
INTRO = "# Introduction\n\nKobolds live here.\n"
EXIT = 'exit at 12,9 { to "surface" at 1,1  label "Up to the pond" }'
COMMENT = "The exit from the shrine to the surface is not yet in place, fix it."


def _answer(*operations, summary="Added the exit from the shrine.") -> str:
    return "```json\n" + json.dumps({"summary": summary, "operations": list(operations)}) + "\n```"


ADD_EXIT = _answer({"op": "put_map", "name": "caves", "source": GOOD + EXIT + "\n"})


@pytest.fixture
def storage(tmp_path):
    opened = open_storage(Config(data_dir=tmp_path / "data"))
    yield opened
    opened.close()


def _module(storage) -> str:
    module = storage.modules.create("The Kobold Caves")
    storage.modules.put_map(module.id, ModuleMap("caves", "map", GOOD, True))
    texts = [
        TextDoc("intro", "Introduction", "player", None, INTRO),
        TextDoc("caves", "The Kobold Caves", "gm", None, CAVES),
    ]
    entities = {"npcs": [{"id": "grik", "name": "Grik", "summary": "The chief."}]}
    save_source(storage, module.id, ModuleSource(texts=texts, entities=entities))
    return module.id


class Claude:
    """FakeDM answering the fix-it prompt from `answers` in turn (then `ADD_EXIT`), recording the prompts."""

    def __init__(self, *answers: str):
        self.answers = list(answers)
        self.dm = FakeDM([], side_handler=lambda prompt: self.answers.pop(0) if self.answers else ADD_EXIT)

    def services(self, storage) -> ConversionServices:
        return ConversionServices(
            storage=storage, conversion=lambda: (self.dm, BackendChoice("fake", "fake-large")), ocr=None
        )


async def _settled(services, comment_id: str):
    """The comment once its job has ended."""
    comment = services.storage.module_comments.get(comment_id)
    if comment.conversion_id is not None:
        await wait(services, comment.conversion_id)
    return services.storage.module_comments.get(comment_id)


def _sent(services, module_id: str, text: str = COMMENT, anchor=None):
    async def scenario():
        sent = send_comment(services, module_id, text, anchor=anchor, author="Raf")
        return await _settled(services, sent.id)

    return asyncio.run(scenario())


def test_send_starts_a_job(storage):
    module_id = _module(storage)
    claude = Claude()
    services = claude.services(storage)

    comment = _sent(services, module_id)

    assert (comment.status, comment.author, comment.text) == ("review", "Raf", COMMENT)
    job = storage.conversions.get(comment.conversion_id)
    assert (job.kind, job.status, job.module_id) == ("fixit", "done", None)
    assert job.target["module_id"] == module_id and job.target["comment_ids"] == [comment.id]
    assert job.target["revision"] is None, "the module had no revision yet"
    assert job.result["revision"] is None and job.result["summary"] == "Added the exit from the shrine."
    assert EXIT in next(m["source"] for m in job.result["maps"] if m["name"] == "caves")
    assert ModuleSource.from_json(job.result["source"]).texts == load_source(storage, module_id).texts
    [prompt] = claude.dm.side_prompts
    assert prompt.startswith(FIXIT_PROMPT)
    assert COMMENT in prompt and GOOD in prompt and CAVES in prompt and '"grik"' in prompt


def test_second_comment_queues_behind(storage):
    module_id = _module(storage)
    services = Claude().services(storage)
    first = _sent(services, module_id)

    async def scenario():
        second = send_comment(services, module_id, "The caves need a second exit.", anchor=None, author="Raf")
        assert storage.module_comments.get(second.id).status == "open", "one fix-it job at a time"
        assert second.conversion_id is None
        reject(services, first.conversion_id)
        return await _settled(services, second.id)

    second = asyncio.run(scenario())
    assert second.status == "review" and second.conversion_id != first.conversion_id


def test_a_busy_slot_queues_the_job(storage):
    module_id = _module(storage)
    services = Claude().services(storage)

    async def scenario():
        gate = asyncio.Event()

        async def work(live):
            await gate.wait()
            runner.finish(services, live)

        await runner.start_job(services, "dungeon-map", "A crypt", work)
        sent = send_comment(services, module_id, COMMENT, anchor=None, author="")
        comment = storage.module_comments.get(sent.id)
        assert comment.status == "working"
        assert storage.conversions.get(comment.conversion_id).status == "queued"
        gate.set()
        return await _settled_when_done(services, sent.id)

    assert asyncio.run(scenario()).status == "review"


async def _settled_when_done(services, comment_id: str):
    for _ in range(200):
        comment = services.storage.module_comments.get(comment_id)
        job = services.storage.conversions.get(comment.conversion_id)
        if job.status not in ("queued", "running"):
            return comment
        live = services.live.get(job.id)
        await (asyncio.shield(live.task) if live is not None and live.task is not None else asyncio.sleep(0.01))
    raise AssertionError("the job never ended")


def test_result_is_not_saved_before_keep(storage):
    module_id = _module(storage)
    before = (load_source(storage, module_id), storage.modules.get(module_id))
    _sent(Claude().services(storage), module_id)
    assert load_source(storage, module_id) == before[0]
    assert storage.modules.get(module_id).maps == before[1].maps
    assert storage.revisions.latest(module_id) is None, "no revision is made before Keep"


def test_keep_makes_a_new_revision(storage):
    module_id = _module(storage)
    pinned = storage.revisions.snapshot(module_id)
    campaign = storage.campaigns.create("Tuesday", module_id, pinned.number, ruleset="osric", setting="greyhawk")
    services = Claude().services(storage)
    comment = _sent(services, module_id)

    revision = keep(services, comment.conversion_id)

    assert revision.number == pinned.number + 1
    assert EXIT in next(m.source for m in storage.modules.get(module_id).maps if m.name == "caves")
    assert EXIT in next(m.source for m in revision.maps if m.name == "caves")
    assert storage.campaigns.get(campaign.id).revision == pinned.number, "the campaign stays pinned"
    assert EXIT not in next(m.source for m in storage.revisions.get(module_id, pinned.number).maps)
    kept = storage.module_comments.get(comment.id)
    assert (kept.status, kept.revision) == ("kept", revision.number)
    with pytest.raises(KeyError):
        keep(services, comment.conversion_id)  # kept once


def test_keep_after_edit_is_409(storage):
    module_id = _module(storage)
    services = Claude().services(storage)
    comment = _sent(services, module_id)
    source = load_source(storage, module_id)
    edited = replace(source, texts=[replace(source.texts[0], markdown=INTRO + "\nAn edit.\n"), *source.texts[1:]])
    save_source(storage, module_id, edited)

    with pytest.raises(FixitStale):
        keep(services, comment.conversion_id)

    assert load_source(storage, module_id) == edited, "Keep never overwrites the editor's save"
    assert EXIT not in storage.modules.get(module_id).maps[0].source
    assert storage.module_comments.get(comment.id).status == "review"

    async def again():
        rerun(services, comment.id)
        return await _settled(services, comment.id)

    rerun_comment = asyncio.run(again())
    assert rerun_comment.status == "review" and rerun_comment.conversion_id != comment.conversion_id
    assert keep(services, rerun_comment.conversion_id).number == 1
    assert "An edit." in load_source(storage, module_id).texts[0].markdown


def test_keep_checks_staleness_inside_the_transaction_that_writes(storage, monkeypatch):
    """An editor's save between Keep's check and its writes would be overwritten: the check is part of the
    transaction that writes."""
    module_id = _module(storage)
    services = Claude().services(storage)
    comment = _sent(services, module_id)
    within, checked = [], []
    transaction = storage.transaction

    @contextmanager
    def watched():
        with transaction():
            within.append(True)
            try:
                yield
            finally:
                within.pop()

    def stale(storage, job):
        checked.append(bool(within))
        return is_stale(storage, job)

    monkeypatch.setattr(storage, "transaction", watched)
    monkeypatch.setattr(fixit, "is_stale", stale)
    keep(services, comment.conversion_id)
    assert checked == [True]


def test_reject_saves_nothing(storage):
    module_id = _module(storage)
    services = Claude().services(storage)
    comment = _sent(services, module_id)
    before = (load_source(storage, module_id), storage.modules.get(module_id).maps)

    reject(services, comment.conversion_id)

    assert (load_source(storage, module_id), storage.modules.get(module_id).maps) == before
    assert storage.module_comments.get(comment.id).status == "rejected"
    assert storage.revisions.latest(module_id) is None
    with pytest.raises(KeyError):
        keep(services, comment.conversion_id)


def test_failed_has_reason_and_rerun(storage):
    module_id = _module(storage)
    broken = _answer({"op": "put_map", "name": "caves", "source": "map {"})
    services = Claude("I can't answer in JSON.", broken).services(storage)

    comment = _sent(services, module_id)
    assert comment.status == "failed" and comment.error
    assert storage.conversions.get(comment.conversion_id).status == "failed"

    async def again():
        rerun(services, comment.id)
        return await _settled(services, comment.id)

    again_comment = asyncio.run(again())
    assert again_comment.status == "failed" and "caves" in again_comment.error, "a map that doesn't parse fails"
    assert asyncio.run(again()).status == "review"


def test_close_without_running(storage):
    module_id = _module(storage)
    services = Claude().services(storage)
    first = _sent(services, module_id)
    second = send_comment(services, module_id, "Never mind this one.", anchor=None, author="")

    assert close_comment(storage, second.id).status == "closed"
    with pytest.raises(ValueError):
        close_comment(storage, first.id)  # it is in review, not open
    with pytest.raises(ValueError):
        rerun(services, second.id)  # closed is the end
    reject(services, first.conversion_id)
    assert storage.module_comments.get(second.id).conversion_id is None, "a closed comment never runs"


def test_only_asked_parts_change(storage):
    module_id = _module(storage)
    unasked = _answer(
        {"op": "put_text", "id": "caves", "markdown": CAVES + "\nA way out.\n"},
        {"op": "put_text", "id": "intro", "markdown": INTRO + "\nAlso this.\n"},
    )
    services = Claude(unasked).services(storage)

    comment = _sent(services, module_id, anchor={"kind": "text", "text_id": "caves"})

    assert comment.status == "failed"
    assert comment.error.startswith(CHANGED_UNASKED) and "intro" in comment.error
    unanchored = Claude(unasked).services(storage)
    assert _sent(unanchored, module_id, text="Tidy up everything.").status == "review"


def test_room_anchor_allows_its_map_and_its_texts(storage):
    module_id = _module(storage)
    services = Claude().services(storage)
    comment = _sent(services, module_id, anchor={"kind": "room", "map": "caves", "node": "rC3"})
    assert comment.status == "review"


# ----- what the prompt holds (DEL-170) -----

TOWER = "# The Tower\n\n## T1. Stair\n\nA winding stair.\n\n## T2. Top\n\nThe wizard's study.\n"
TOWER_MAP = GOOD.replace('"Kobold Caves"', '"Tower"').replace("1. Entrance", "T1. Stair").replace("2. Hall", "T2. Top")
CAVES_KEYS = [
    {"key": "C3", "title": "Shrine", "text": "text:caves#c3", "node": "map:caves#room.rC3"},
    {"key": "1", "title": "Entrance", "text": "text:caves#1", "node": "map:caves#room.r1"},
]
TOWER_KEY = {"key": "T1", "title": "Stair", "text": "text:tower#t1", "node": "map:tower#room.r1"}


def _two_maps(storage) -> str:
    """The kobold caves with a tower beside them: its own map and text, and explicit keys on both maps."""
    module_id = _module(storage)
    storage.modules.put_map(module_id, ModuleMap("tower", "map", TOWER_MAP, False))
    source = load_source(storage, module_id)
    texts = [*source.texts, TextDoc("tower", "The Tower", "gm", "tower", TOWER)]
    keys = [CAVES_KEYS[0], TOWER_KEY, CAVES_KEYS[1]]
    entities = {"npcs": [*source.entities["npcs"], {"id": "zed", "name": "Zed", "summary": "The wizard."}]}
    save_source(storage, module_id, replace(source, texts=texts, keys=keys, entities=entities))
    return module_id


def _prompt_for(storage, module_id, text, anchor=None) -> str:
    """The prompt the comment's job sent; its result is rejected, so the module takes the next comment."""
    claude = Claude(_answer(summary="Nothing."))
    services = claude.services(storage)
    comment = _sent(services, module_id, text=text, anchor=anchor)
    reject(services, comment.conversion_id)
    [prompt] = claude.dm.side_prompts
    return prompt


def test_a_room_comment_sends_its_text_its_map_and_an_index_of_the_rest(storage):
    """DEL-170: a one-room comment on Thracia sent all 1.46 M characters. It sends the room's text and map, their
    explicit keys, and an index of the other parts by name, with their headings."""
    module_id = _two_maps(storage)

    prompt = _prompt_for(
        storage, module_id, "The shrine needs an altar.", {"kind": "room", "map": "caves", "node": "room.rC3"}
    )

    assert "(on the room `room.rC3` of the map `caves`, key C3 in the text `caves`)" in prompt
    assert prompt.index(CAVES) < prompt.index(GOOD), "the text keyed to the room first"
    assert CAVES in prompt and GOOD in prompt, "the room's text (on the default map) and its map, whole"
    assert TOWER not in prompt and TOWER_MAP not in prompt and INTRO not in prompt
    assert '"text:caves#c3"' in prompt and '"text:tower#t1"' not in prompt, "only the keys of the parts shown"
    assert "### Index of the parts not shown" in prompt
    assert "- `tower`: The Tower (gm, map `tower`," in prompt and "Headings: The Tower; T1. Stair; T2. Top" in prompt
    assert "- `intro`: Introduction (player," in prompt and "`grik` (Grik), `zed` (Zed)" in prompt
    assert "- `tower` (map," in prompt
    assert '"summary": "The chief."' not in prompt, "no entity's record"


def test_a_comment_sends_what_it_names(storage):
    """DEL-170: the parts a comment names by id, title or name are sent whole too, after its anchored ones."""
    module_id = _two_maps(storage)

    prompt = _prompt_for(storage, module_id, "Zed should live in the tower.", {"kind": "text", "text_id": "intro"})

    assert INTRO in prompt and TOWER in prompt and TOWER_MAP in prompt, "the text `tower`, the map `tower`"
    assert '"summary": "The wizard."' in prompt and '"summary": "The chief."' not in prompt
    assert CAVES not in prompt and GOOD not in prompt


def test_a_comment_with_no_anchor_and_no_name_sends_the_whole_module(storage):
    module_id = _two_maps(storage)

    prompt = _prompt_for(storage, module_id, "Tidy up the spelling everywhere.")

    assert all(part in prompt for part in (CAVES, INTRO, TOWER, GOOD, TOWER_MAP, '"The chief."', '"The wizard."'))
    assert '"text:tower#t1"' in prompt and "### Index" not in prompt


def test_a_big_module_is_cut_to_the_budget_with_a_note(storage):
    """DEL-170: Thracia's size (1.46 M characters in 16 texts and 18 maps): a one-room prompt stays within the
    budget, and a part beyond it is cut with a note, or left out by name."""
    module = storage.modules.create("Thracia")
    level = "# Level 1\n\n## 1. Hall\n\nA hall.\n\n" + "Dust and bones. " * 4_000  # 68k characters
    big_map = GOOD + "\n".join(f"# {'x' * 70}" for _ in range(1_100)) + "\n"  # 85k characters
    texts = [TextDoc(f"level-{n}", f"Level {n}", "gm", f"level-{n}", level) for n in range(1, 17)]
    for n in range(1, 19):
        storage.modules.put_map(module.id, ModuleMap(f"level-{n}", "map", big_map, n == 1))
    lore = TextDoc("lore", "Lore", "gm", None, "# Lore\n\n" + "Old tales. " * 30_000)  # 330k characters
    save_source(storage, module.id, ModuleSource(texts=[*texts, lore]))
    whole = sum(len(t.markdown) for t in [*texts, lore]) + 18 * len(big_map)
    assert whole > 1_400_000

    room = _prompt_for(
        storage, module.id, "Room 1 needs a door.", {"kind": "room", "map": "level-3", "node": "room.r1"}
    )
    assert len(room) <= PROMPT_BUDGET
    assert f"<text>\n{level}\n</text>" in room and big_map in room, "the room's text and map, whole"

    cut = _prompt_for(storage, module.id, "The lore is wrong about the gods.", {"kind": "text", "text_id": "lore"})
    assert len(cut) <= PROMPT_BUDGET
    assert "(Cut: the first " in cut and f"of its {len(lore.markdown):,} characters are shown" in cut
    assert "Don't replace it: you haven't seen it whole." in cut

    everything = _prompt_for(storage, module.id, "Tidy up the spelling everywhere.")
    assert len(everything) <= PROMPT_BUDGET
    assert "Left out for the prompt's size: " in everything and "`map:level-18`" in everything


def test_an_answer_that_replaces_a_part_it_was_not_shown_fails(storage):
    """DEL-170: Claude saw the tower only in the index; a `put_text` of it would write it from its headings."""
    module_id = _two_maps(storage)
    blind = _answer({"op": "put_text", "id": "tower", "markdown": "# The Tower\n\nA tower.\n"})

    comment = _sent(Claude(blind).services(storage), module_id, text="Zed is a sorcerer, not a wizard.")

    assert comment.status == "failed"
    assert comment.error == f"{NOT_SHOWN_WHOLE}: text:tower."
    added = _answer({"op": "put_text", "id": "zed-notes", "markdown": "# Zed\n\nHis notes.\n"})
    assert _sent(Claude(added).services(storage), module_id, text="Zed needs notes.").status == "review", "a new part"


def test_put_keys_replaces_the_keys_shown_and_keeps_the_others(storage):
    """DEL-170: the room's prompt shows the caves' keys only; its `put_keys` replaces them, where the first was,
    and the tower's key stays."""
    module_id = _two_maps(storage)
    fixed = {**CAVES_KEYS[0], "title": "The Shrine"}
    answer = _answer({"op": "put_keys", "keys": [fixed, CAVES_KEYS[1]]})

    comment = _sent(
        Claude(answer).services(storage), module_id, anchor={"kind": "room", "map": "caves", "node": "room.rC3"}
    )

    assert comment.status == "review", comment.error
    result = storage.conversions.get(comment.conversion_id).result
    assert ModuleSource.from_json(result["source"]).keys == [fixed, CAVES_KEYS[1], TOWER_KEY]


def test_queued_job_restored(storage):
    """A fix-it job queued when Delve stopped starts from its row in the next process."""
    module_id = _module(storage)
    services = Claude().services(storage)

    async def before_the_stop():
        gate = asyncio.Event()

        async def work(live):
            await gate.wait()

        held = await runner.start_job(services, "dungeon-map", "A crypt", work)
        await asyncio.sleep(0)  # it begins
        sent = send_comment(services, module_id, COMMENT, anchor=None, author="")
        services.live[held.id].task.cancel()  # Delve stopping
        await asyncio.gather(services.live[held.id].task, return_exceptions=True)
        return sent

    sent = asyncio.run(before_the_stop())
    restarted = Claude().services(storage)

    async def after_restart():
        runner.close_orphans(storage)
        started = runner.start_queue(restarted)
        assert started is not None and started.kind == "fixit"
        return await _settled(restarted, sent.id)

    assert asyncio.run(after_restart()).status == "review"


def test_a_cancelled_job_fails_its_comments(storage):
    module_id = _module(storage)
    services = Claude().services(storage)

    async def scenario():
        gate = asyncio.Event()

        async def work(live):
            await gate.wait()

        await runner.start_job(services, "dungeon-map", "A crypt", work)
        sent = send_comment(services, module_id, COMMENT, anchor=None, author="")
        await runner.cancel(services, storage.module_comments.get(sent.id).conversion_id)

    asyncio.run(scenario())
    [listed] = comments(storage, module_id)
    assert listed.status == "failed" and listed.error
