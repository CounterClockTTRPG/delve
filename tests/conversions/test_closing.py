"""Closing the questions and doubts box (table voice and fixes Task F3): a job's questions and doubts are closed by
key (`question:<id>`, `doubt:<index>`), stored on the job, so every organiser sees the same; closing changes neither
"Notes from making this module" nor a running job's saves."""

from dataclasses import replace

import pytest

from delve.config import Config
from delve.conversions.runner import MAKING_NOTES, answer_questions, close_items, module_questions, tell_dm
from delve.modules.source import load_source
from delve.storage import open_storage

QUESTION = {"id": "q1", "text": "Should Grik bargain?", "default": "He bargains.", "answer": None}
DOUBTS = [
    {"piece": "clean-1", "part": "house", "pages": [3], "kind": "checker-flag", "text": "Key 3 covers 80%."},
    {"piece": "describe", "part": "ship", "pages": [], "kind": "picture-unsure", "text": "A ghost or a sail?"},
]


@pytest.fixture
def storage(tmp_path):
    opened = open_storage(Config(data_dir=tmp_path / "data"))
    yield opened
    opened.close()


def _asked(storage, *, doubts=True) -> tuple[str, str]:
    """A module made by a thorough job that asked one question and had two doubts: (module id, conversion id)."""
    module = storage.modules.create("The Kobold Caves")
    made = storage.conversions.create("pdf", "The Kobold Caves", "ready")
    questions = {"questions": [QUESTION], "remarks": [], **({"doubts": DOUBTS} if doubts else {})}
    storage.conversions.save(replace(made, status="done", module_id=module.id, questions=questions))
    return module.id, made.id


def test_closed_round_trip(storage):
    module_id, conversion_id = _asked(storage)
    [entry] = module_questions(storage, module_id)
    assert entry["closed"] == []

    closed = close_items(storage, conversion_id, ["doubt:1", "question:q1", "doubt:1"])
    assert closed["closed"] == ["doubt:1", "question:q1"]
    assert closed["conversion_id"] == conversion_id and closed["doubts"] == DOUBTS
    [entry] = module_questions(storage, module_id)
    assert entry["closed"] == ["doubt:1", "question:q1"]

    reopened = close_items(storage, conversion_id, ["question:q1"])
    assert reopened["closed"] == ["question:q1"]
    assert module_questions(storage, module_id)[0]["closed"] == ["question:q1"]


def test_unknown_key_is_422(storage):
    _, conversion_id = _asked(storage)
    for key in ("question:q7", "doubt:2", "doubt:-1", "doubt:x", "remark:0", "q1"):
        with pytest.raises(ValueError, match="names no question or doubt"):
            close_items(storage, conversion_id, [key])
    _, plain = _asked(storage, doubts=False)
    with pytest.raises(ValueError):
        close_items(storage, plain, ["doubt:0"])
    assert storage.conversions.get(conversion_id).closed == []


def test_unknown_job_is_a_key_error(storage):
    asked_nothing = storage.conversions.create("generate", "plain", "ready")
    for id in ("cnv_missing", asked_nothing.id):
        with pytest.raises(KeyError):
            close_items(storage, id, [])


def test_closing_leaves_the_notes(storage):
    module_id, conversion_id = _asked(storage)
    answer_questions(storage, conversion_id, {"q1": "He fights."}, ["Check the cellar."])
    tell_dm(storage, conversion_id)
    notes = next(t for t in load_source(storage, module_id).texts if t.id == MAKING_NOTES).markdown
    revision = storage.modules.get(module_id).head_revision

    close_items(storage, conversion_id, ["question:q1", "doubt:0", "doubt:1"])
    after = next(t for t in load_source(storage, module_id).texts if t.id == MAKING_NOTES).markdown
    assert after == notes, "closing only hides"
    assert "He fights." in after and "Key 3 covers 80%." in after
    assert storage.modules.get(module_id).head_revision == revision

    # Answering again keeps what was closed, and the notes still hold the closed items.
    entry = answer_questions(storage, conversion_id, {"q1": "He runs."}, [])
    assert entry["closed"] == ["question:q1", "doubt:0", "doubt:1"]
    assert "He runs." in next(t for t in load_source(storage, module_id).texts if t.id == MAKING_NOTES).markdown


def test_running_job_save_keeps_closed(storage):
    module_id, conversion_id = _asked(storage)
    stale = storage.conversions.get(conversion_id)
    close_items(storage, conversion_id, ["doubt:0"])
    saved = storage.conversions.save(replace(stale, step="maps", done=1, total=1))
    assert saved.closed == ["doubt:0"]
    assert module_questions(storage, module_id)[0]["closed"] == ["doubt:0"]
