"""The fix-it routes (table voice and fixes Task F2.2): send a comment, follow its job, review what it would change,
keep it as a new revision (409 on a module changed since) or reject it, run a comment again, close one. Organisers
only; Claude is `FakeDM`, answering the fix-it prompt with `ADD_EXIT`."""

from dataclasses import replace

import pytest

from delve.dm.fake import FAKE_DM_CAPABILITIES, FakeDM
from delve.domain.backends import Registry
from delve.modules.source import load_source, save_source
from tests.conversions.test_fixit import ADD_EXIT, COMMENT, EXIT, INTRO, _module
from tests.web.conftest import make_registries
from tests.web.test_conversions_api import ended
from tests.web.test_preferences_api import published

ANSWERS: list[str] = []
"""The fake's next answers to the fix-it prompt, then `ADD_EXIT`."""


@pytest.fixture(autouse=True)
def _answers():
    yield
    ANSWERS.clear()


@pytest.fixture
def registries():
    dm = Registry()
    dm.register(
        FAKE_DM_CAPABILITIES, lambda: FakeDM([], side_handler=lambda p: ANSWERS.pop(0) if ANSWERS else ADD_EXIT)
    )
    return replace(make_registries(), dm=dm)


def send(local, module_id: str, **body) -> dict:
    response = local.post(f"/api/modules/{module_id}/fixits", json={"text": COMMENT, **body})
    assert response.status_code == 201, response.json()
    comment = response.json()
    ended(local, comment["conversion_id"])
    return next(c for c in local.get(f"/api/modules/{module_id}/fixits").json() if c["id"] == comment["id"])


def test_send_and_list(local, storage, app):
    module_id = _module(storage)

    comment = send(local, module_id, anchor={"kind": "map", "map": "caves"})

    assert (comment["status"], comment["text"], comment["anchor"]) == (
        "review",
        COMMENT,
        {"kind": "map", "map": "caves"},
    )
    assert comment["job"]["status"] == "done" and comment["job"]["steps"] == {"index": 1, "count": 1}
    assert ("modules", {"id": module_id}) in [(e.type, e.data) for e in published(app)]


def test_send_refuses_an_empty_comment_and_a_stray_anchor(local, storage):
    module_id = _module(storage)
    assert local.post(f"/api/modules/{module_id}/fixits", json={"text": "  "}).status_code == 422
    stray = {"text": COMMENT, "anchor": {"kind": "text", "text_id": "nowhere"}}
    assert local.post(f"/api/modules/{module_id}/fixits", json=stray).status_code == 422
    unknown = local.post(f"/api/modules/{module_id}/fixits", json={"text": COMMENT, "status": "kept"})
    assert unknown.status_code == 422 and storage.module_comments.list(module_id) == []
    assert local.post("/api/modules/mod_000000000000/fixits", json={"text": COMMENT}).status_code == 404


def test_review_shows_the_change(local, storage):
    module_id = _module(storage)
    comment = send(local, module_id)

    review = local.get(f"/api/fixits/{comment['conversion_id']}/review").json()

    assert review["summary"] == "Added the exit from the shrine." and review["stale"] is False
    assert review["texts"] == [] and review["entities"] == {"added": [], "changed": [], "removed": []}
    [drawn] = review["maps"]
    assert drawn["name"] == "caves" and EXIT in drawn["after"] and EXIT not in drawn["before"]
    assert "<svg" in drawn["before_svg"] and "data-exit-to" in drawn["after_svg"]
    assert review["comments"] == [comment["id"]]


def test_keep_makes_a_revision(local, storage):
    module_id = _module(storage)
    comment = send(local, module_id)

    response = local.post(f"/api/fixits/{comment['conversion_id']}/keep", json={})

    assert response.status_code == 200 and response.json() == {"revision": 1}
    assert EXIT in local.get(f"/api/modules/{module_id}/maps/caves").json()["source"]
    assert local.get(f"/api/modules/{module_id}/fixits").json()[0]["status"] == "kept"
    assert local.post(f"/api/fixits/{comment['conversion_id']}/keep", json={}).status_code == 404


def test_keep_after_edit_is_409_and_rerun(local, storage):
    module_id = _module(storage)
    comment = send(local, module_id)
    source = load_source(storage, module_id)
    save_source(storage, module_id, replace(source, texts=[replace(source.texts[0], markdown=INTRO + "Edit.\n")]))

    response = local.post(f"/api/fixits/{comment['conversion_id']}/keep", json={})

    assert response.status_code == 409 and response.json()["code"] == "stale"
    assert local.get(f"/api/fixits/{comment['conversion_id']}/review").json()["stale"] is True
    again = local.post(f"/api/fixit-comments/{comment['id']}/rerun", json={})
    assert again.status_code == 200 and again.json()["status"] in ("working", "review")
    ended(local, again.json()["conversion_id"])
    assert local.get(f"/api/modules/{module_id}/fixits").json()[0]["status"] == "review"


def test_reject_and_close(local, storage):
    module_id = _module(storage)
    comment = send(local, module_id)
    second = local.post(f"/api/modules/{module_id}/fixits", json={"text": "Not now."}).json()
    assert second["status"] == "open"

    assert local.post(f"/api/fixit-comments/{second['id']}/close", json={}).json()["status"] == "closed"
    assert local.post(f"/api/fixit-comments/{second['id']}/close", json={}).status_code == 409
    assert local.post(f"/api/fixits/{comment['conversion_id']}/reject", json={}).status_code == 200
    statuses = [c["status"] for c in local.get(f"/api/modules/{module_id}/fixits").json()]
    assert statuses == ["rejected", "closed"]
    assert EXIT not in local.get(f"/api/modules/{module_id}/maps/caves").json()["source"]
    assert local.get(f"/api/fixits/{comment['conversion_id']}/review").status_code == 404


def test_a_failed_comment_has_its_reason(local, storage):
    module_id = _module(storage)
    ANSWERS.append("No JSON here.")
    comment = send(local, module_id)
    assert comment["status"] == "failed" and comment["error"]
    assert local.post("/api/fixit-comments/mcm_000000000000/rerun", json={}).status_code == 404


def test_a_player_seat_is_403(player, storage):
    module_id = _module(storage)
    assert player.get(f"/api/modules/{module_id}/fixits").status_code == 403
    assert player.post(f"/api/modules/{module_id}/fixits", json={"text": COMMENT}).status_code == 403
    assert player.get("/api/fixits/cnv_000000000000/review").status_code == 403
    assert player.post("/api/fixits/cnv_000000000000/keep", json={}).status_code == 403
    assert player.post("/api/fixits/cnv_000000000000/reject", json={}).status_code == 403
    assert player.post("/api/fixit-comments/mcm_000000000000/rerun", json={}).status_code == 403
    assert player.post("/api/fixit-comments/mcm_000000000000/close", json={}).status_code == 403
