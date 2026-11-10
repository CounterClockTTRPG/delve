"""The retry routes (table voice and fixes Task D1): whether the latest beat may be retried, for the asking seat, and
the retry itself, refused with 409 for a second press or a beat that isn't retryable and 403 for another player's
seat."""

import pytest

from delve.dm.fake import FakeDM
from delve.dm.provider import DMError, TextDelta, TurnEnd
from tests.web.test_beats_api import campaign, host, path, present, registries, settle, sit  # noqa: F401

LIMIT = DMError("The DM is paused: Claude's usage limit is reached.", True, resets_at="2026-10-25T18:00:00Z")


@pytest.fixture
def dm():
    return FakeDM([[LIMIT, TurnEnd("error")], [TextDelta("The door opens.")], [TextDelta("Again.")]])


def failed_beat(local, storage, campaign) -> str:  # noqa: F811
    answer = local.post(path(campaign, "act"), json={"text": "We open the door."})
    assert answer.status_code == 202
    settle(storage, campaign)
    return answer.json()["beat"]["id"]


def test_retry_route(app, local, storage, dm, campaign, host):  # noqa: F811
    assert local.get(path(campaign, "retry")).json() == {"beat_id": None, "may_retry": False, "resets_at": None}
    beat_id = failed_beat(local, storage, campaign)
    assert local.get(path(campaign, "retry")).json() == {
        "beat_id": beat_id,
        "may_retry": True,
        "resets_at": "2026-10-25T18:00:00Z",
    }
    answer = local.post(path(campaign, f"beats/{beat_id}/retry"), json={})
    assert answer.status_code == 202, answer.text
    assert answer.json()["beat"]["id"] == beat_id and answer.json()["beat"]["status"] == "running"
    settle(storage, campaign)
    assert storage.beats.get(beat_id).status == "done"
    assert dm.sent[1].endswith(dm.sent[0])
    assert local.get(path(campaign, "retry")).json()["may_retry"] is False
    # Done now: a retry is refused, and nothing is sent again.
    again = local.post(path(campaign, f"beats/{beat_id}/retry"), json={})
    assert again.status_code == 409 and "error" in again.json()
    assert len(dm.sent) == 2


def test_open_beat_is_409(app, local, storage, campaign, host):  # noqa: F811
    beat_id = failed_beat(local, storage, campaign)
    storage.beats.open(campaign.id, [], status="open")  # someone acted again
    assert local.get(path(campaign, "retry")).json()["may_retry"] is False
    refused = local.post(path(campaign, f"beats/{beat_id}/retry"), json={})
    assert refused.status_code == 409 and "error" in refused.json()


def test_other_players_seat_403(app, local, storage, campaign, host, sit):  # noqa: F811
    garrek = storage.characters.create(campaign.id, "Garrek")
    mira = storage.characters.create(campaign.id, "Mira")
    ana, ana_client = sit(campaign, "Ana", "player", garrek.id)
    _bo, bo_client = sit(campaign, "Bo", "player", mira.id)
    present(app, ana.id)
    answer = ana_client.post(path(campaign, "act"), json={"text": "I listen."})
    assert answer.status_code == 202
    settle(storage, campaign)
    beat_id = answer.json()["beat"]["id"]
    assert bo_client.get(path(campaign, "retry")).json()["may_retry"] is False
    refused = bo_client.post(path(campaign, f"beats/{beat_id}/retry"), json={})
    assert refused.status_code == 403 and "error" in refused.json()
    assert ana_client.get(path(campaign, "retry")).json()["may_retry"] is True
    assert ana_client.post(path(campaign, f"beats/{beat_id}/retry"), json={}).status_code == 202
    settle(storage, campaign)


def test_unknown_beat_404(app, local, storage, campaign, host):  # noqa: F811
    answer = local.post(path(campaign, "beats/beat_000000000000/retry"), json={})
    assert answer.status_code == 404 and "error" in answer.json()


def test_retry_needs_json(app, local, storage, campaign, host):  # noqa: F811
    beat_id = failed_beat(local, storage, campaign)
    answer = local.post(path(campaign, f"beats/{beat_id}/retry"), content=b"", headers={"Content-Type": "text/plain"})
    assert answer.status_code == 415
