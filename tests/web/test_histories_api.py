"""The history's routes (carry-the-party-on plan Task 5): carrying the party on starts the history's job; the host
reads and edits both texts, every other seat (a co-host too, as for a tool reply) reads the table's alone; Write again
asks before replacing an edit. A job already running when the party is carried on fails the history, never the carry (Review Focus 2).

The writer is `FakeDM(side_handler=…)` with the jobs tests' fake historian.
"""

import asyncio
import time
from dataclasses import replace

import pytest

from delve.dm.fake import FAKE_DM_CAPABILITIES, FakeDM
from delve.domain.backends import Registry
from delve.histories.jobs import RUNNING_MSG
from delve.histories.writer import HISTORY_MAX_CHARS
from tests.histories.test_jobs import Writer
from tests.web.conftest import make_registries
from tests.web.test_campaigns_api import crypt_module, seat_browser
from tests.web.test_carry_api import carry, old_party
from tests.web.test_preferences_api import published

EDITED = {"error": "The history was edited: confirm to replace it."}


@pytest.fixture
def writer():
    return Writer()


@pytest.fixture
def registries(writer):
    dm = Registry()
    dm.register(FAKE_DM_CAPABILITIES, lambda: FakeDM([], side_handler=writer))
    return replace(make_registries(), dm=dm)


def ended(client, campaign_id: str) -> dict:
    """The campaign's history once its job has ended."""
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        history = client.get(f"/api/campaigns/{campaign_id}/history").json()
        if history["status"] != "writing":
            return history
        time.sleep(0.02)
    raise AssertionError(f"the history of {campaign_id} is still writing")


def carried(local) -> tuple[dict, dict]:
    """A party carried on: the old campaign and the new one, its history written."""
    old, (ana, _) = old_party(local)
    response = carry(local, old["id"], crypt_module(local)["id"], [ana])
    assert response.status_code == 201, response.json()
    new = response.json()
    ended(local, new["id"])
    return old, new


def path(campaign: dict, rest: str = "") -> str:
    return f"/api/campaigns/{campaign['id']}/history{rest}"


def test_carry_starts_history(local, storage, writer):
    old, (ana, _) = old_party(local)
    response = carry(local, old["id"], crypt_module(local)["id"], [ana])

    assert response.status_code == 201, response.json()
    new = response.json()
    assert new["history"] == {"status": "writing"}
    assert new["carried_from"] == {"id": old["id"], "name": old["name"]}
    history = ended(local, new["id"])
    assert history["status"] == "done" and history["error"] is None
    assert history["dm_md"].endswith("DM-HISTORY") and history["table_md"].endswith("TABLE-HISTORY")
    assert history["campaign_id"] == new["id"] and history["edited"] is False
    job = local.get(f"/api/conversions/{history['conversion_id']}").json()
    assert (job["kind"], job["title"], job["target"]) == ("history", "History: Gentle", {"campaign_id": new["id"]})
    assert [audience for audience, _ in writer.prompts] == ["dm", "table"]


def test_running_job_gives_failed_history_campaign_still_made(local, app, storage, writer):
    gate = asyncio.Event()
    dm = app.state.registries.dm.get("fake")
    real = dm.side_call

    async def held(prompt, choice, **kw):
        if prompt.startswith("You are a novelist"):
            await gate.wait()
        return await real(prompt, choice, **kw)

    old, (ana, _) = old_party(local)
    dm.side_call = held
    novel = local.post("/api/novels", json={"source": "campaign", "id": old["id"]})
    assert novel.status_code == 202, novel.json()

    response = carry(local, old["id"], crypt_module(local)["id"], [ana])

    assert response.status_code == 201, response.json()
    new = response.json()
    assert new["history"] == {"status": "failed"}
    assert storage.campaigns.get(new["id"]) is not None and storage.characters.list(new["id"])
    assert storage.campaigns.get(old["id"]).status == "complete"
    history = local.get(path(new)).json()
    assert (history["status"], history["error"]) == ("failed", RUNNING_MSG)
    busy = local.post(path(new, "/write"), json={})
    assert busy.status_code == 409 and busy.json()["error"] == "A conversion is running."

    local.portal.call(gate.set)
    deadline = time.monotonic() + 20
    while local.get(f"/api/novels/{novel.json()['id']}").json()["status"] == "writing":
        assert time.monotonic() < deadline
        time.sleep(0.02)
    again = local.post(path(new, "/write"), json={})
    assert again.status_code == 202, again.json()
    assert again.json()["status"] == "writing"
    assert ended(local, new["id"])["status"] == "done"


def test_player_gets_table_text_only(local, app, storage):
    _, new = carried(local)

    for role in ("cohost", "player", "observer"):
        seat = seat_browser(app, storage, new["id"], role)
        response = seat.get(path(new))
        assert response.status_code == 200, response.json()
        assert response.json() == {"status": "done", "table_md": "## The party\n\nTABLE-HISTORY"}
        assert "DM-HISTORY" not in response.text
        assert seat.put(path(new), json={"dm_md": "", "table_md": ""}).status_code == 403
        assert seat.post(path(new, "/write"), json={"overwrite": True}).status_code == 403
    stored = storage.histories.get(new["id"])
    assert stored.dm_md.endswith("DM-HISTORY") and not stored.edited, "no seat but the host edits it"
    assert local.get(path(new)).json()["dm_md"].endswith("DM-HISTORY"), "the host reads the DM's"


def test_no_history_is_null(local):
    old, _ = old_party(local)

    response = local.get(path(old))
    assert response.status_code == 200 and response.json() is None, "no history is an answer, not a 404"
    assert local.put(path(old), json={"dm_md": "a", "table_md": "b"}).status_code == 404


def test_host_put_marks_edited(local, app, storage):
    _, new = carried(local)
    before = len(published(app))

    response = local.put(path(new), json={"dm_md": "## The party\n\nMINE", "table_md": "## The party\n\nOURS"})

    assert response.status_code == 200, response.json()
    assert response.json()["edited"] is True and response.json()["status"] == "done"
    stored = storage.histories.get(new["id"])
    assert (stored.dm_md, stored.table_md, stored.edited) == ("## The party\n\nMINE", "## The party\n\nOURS", True)
    # The table's play screens hear it, ids only (DEL-172).
    told = [e for e in published(app)[before:] if e.type == "history"]
    assert [(e.data, e.scope, e.campaign_id) for e in told] == [({"campaign_id": new["id"]}, "table", new["id"])]
    assert local.put(path(new), json={"dm_md": "a"}).status_code == 422
    assert local.put(path(new), json={"dm_md": "a", "table_md": "b", "x": 1}).status_code == 422


def test_put_over_cap_422(local, storage):
    _, new = carried(local)

    for body in (
        {"dm_md": "x" * (HISTORY_MAX_CHARS + 1), "table_md": ""},
        {"dm_md": "", "table_md": "x" * (HISTORY_MAX_CHARS + 1)},
    ):
        response = local.put(path(new), json=body)
        assert response.status_code == 422 and "6000" in response.json()["error"]
    assert not storage.histories.get(new["id"]).edited
    assert local.put(path(new), json={"dm_md": "x" * HISTORY_MAX_CHARS, "table_md": ""}).status_code == 200


def test_put_409_while_writing(local, storage):
    _, new = carried(local)
    running = storage.conversions.create("history", "History: Gentle", "ready")  # its job, as if it ran
    storage.histories.put(replace(storage.histories.get(new["id"]), status="writing", conversion_id=running.id))

    assert local.put(path(new), json={"dm_md": "a", "table_md": "b"}).status_code == 409
    assert local.post(path(new, "/write"), json={"overwrite": True}).status_code == 409


def test_write_again_409_when_edited_then_202_with_overwrite(local, writer):
    _, new = carried(local)
    assert local.put(path(new), json={"dm_md": "MINE", "table_md": "OURS"}).status_code == 200

    refused = local.post(path(new, "/write"), json={})
    assert refused.status_code == 409 and refused.json() == EDITED
    assert local.get(path(new)).json()["dm_md"] == "MINE"

    accepted = local.post(path(new, "/write"), json={"overwrite": True})
    assert accepted.status_code == 202, accepted.json()
    history = ended(local, new["id"])
    assert history["status"] == "done" and history["edited"] is False
    assert history["dm_md"].endswith("DM-HISTORY")


def test_write_again_404_without_origin(local):
    old, new = carried(local)

    assert local.post(path(old, "/write"), json={}).status_code == 404, "the old one wasn't carried on"
    assert local.request("DELETE", f"/api/campaigns/{old['id']}", json={}).status_code == 204
    gone = local.post(path(new, "/write"), json={})
    assert gone.status_code == 404 and "error" in gone.json()
    assert local.get(path(new)).json()["status"] == "done", "the history stays"
