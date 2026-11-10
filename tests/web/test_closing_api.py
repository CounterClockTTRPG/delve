"""Closing the questions and doubts box, through the API (table voice and fixes Task F3): `PUT
/api/conversions/{id}/closed` stores the keys, the questions route answers them, and every organiser's page hears
`modules`."""

from dataclasses import replace

from tests.web.test_preferences_api import published

QUESTION = {"id": "q1", "text": "Should Grik bargain?", "default": "He bargains.", "answer": None}
DOUBT = {"piece": "clean-1", "part": "house", "pages": [3], "kind": "checker-flag", "text": "Key 3 covers 80%."}


def _asked(storage) -> tuple[str, str]:
    module = storage.modules.create("The Kobold Caves")
    made = storage.conversions.create("pdf", "The Kobold Caves", "ready")
    questions = {"questions": [QUESTION], "remarks": [], "doubts": [DOUBT]}
    storage.conversions.save(replace(made, status="done", module_id=module.id, questions=questions))
    return module.id, made.id


def test_closed_round_trip(local, app, storage):
    module_id, conversion_id = _asked(storage)
    assert local.get(f"/api/modules/{module_id}/questions").json()[0]["closed"] == []

    answer = local.put(f"/api/conversions/{conversion_id}/closed", json={"closed": ["question:q1", "doubt:0"]})
    assert answer.status_code == 200, answer.json()
    assert answer.json()["closed"] == ["question:q1", "doubt:0"]
    assert local.get(f"/api/modules/{module_id}/questions").json()[0]["closed"] == ["question:q1", "doubt:0"]
    assert [(e.type, e.data) for e in published(app)] == [("modules", {"id": module_id})]

    reopened = local.put(f"/api/conversions/{conversion_id}/closed", json={"closed": []})
    assert reopened.json()["closed"] == []


def test_unknown_key_is_422(local, storage):
    _, conversion_id = _asked(storage)
    refused = local.put(f"/api/conversions/{conversion_id}/closed", json={"closed": ["doubt:1"]})
    assert refused.status_code == 422 and "doubt:1" in refused.json()["error"]
    assert local.put("/api/conversions/cnv_missing/closed", json={"closed": []}).status_code == 404
    assert local.put(f"/api/conversions/{conversion_id}/closed", json={}).status_code == 422
    stray = {"closed": ["doubt:0"], "reopen": ["question:q1"]}
    assert local.put(f"/api/conversions/{conversion_id}/closed", json=stray).status_code == 422


def test_closing_is_for_organisers(lan, storage):
    _, conversion_id = _asked(storage)
    assert lan.put(f"/api/conversions/{conversion_id}/closed", json={"closed": []}).status_code == 401
