"""Pictures in table talk (DEL-294): a campaign option the host turns on (off by default); then the seated players and
the hosts paste pictures, everyone at the table sees them, and the host, a co-host or the poster takes one down."""

import io

from fastapi.testclient import TestClient
from PIL import Image

from delve.web.seats import SEAT_COOKIE, new_seat_token, token_hash
from tests.web.conftest import BASE_URL
from tests.web.test_preferences_api import published
from tests.web.test_talk_api import dm, path, registries, table  # noqa: F401 (fixtures)


def png(size=(300, 200)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, (20, 120, 200)).save(out, "PNG")
    return out.getvalue()


def allow(client, table, on=True):  # noqa: F811
    return client.put(path(table, "play/options"), json={"talk_pictures": on})


def paste(client, table, data=None, media_type="image/png"):  # noqa: F811
    return client.post(
        path(table, "talk/picture"), content=png() if data is None else data, headers={"Content-Type": media_type}
    )


def take(client, table, entry):  # noqa: F811
    return client.request("DELETE", path(table, f"talk/pictures/{entry['id']}"), json={})


def test_pictures_are_off_until_the_host_allows_them(local, table):  # noqa: F811
    _, ana = table["Ana"]
    assert local.get(path(table, "play/options")).json()["talk_pictures"] is False
    assert ana.get(path(table, "play/state")).json()["talk_pictures"] is False
    refused = paste(ana, table)
    assert refused.status_code == 403 and "aren't allowed" in refused.json()["error"]
    assert allow(local, table).status_code == 200
    assert ana.get(path(table, "play/state")).json()["talk_pictures"] is True
    assert paste(ana, table).status_code == 201


def test_only_the_host_turns_them_on(local, app, storage, table):  # noqa: F811
    _, ana = table["Ana"]
    assert allow(ana, table).status_code == 403
    token = new_seat_token()
    storage.seats.create(table["campaign"], "Dee", "en", "cohost", token_hash=token_hash(token))
    with TestClient(app, base_url=BASE_URL) as dee:
        dee.cookies.set(SEAT_COOKIE, token)
        refused = allow(dee, table)
        assert (
            refused.status_code == 403 and refused.json()["error"] == "Only the host can allow pictures in table talk."
        )
    before = len(published(app))
    assert allow(local, table).status_code == 200
    assert [e.type for e in published(app)[before:]] == ["play_options"]


def test_a_pasted_picture_is_a_talk_line_everyone_sees(local, table):  # noqa: F811
    allow(local, table)
    ana_seat, ana = table["Ana"]
    response = paste(ana, table, png((5000, 1000)))
    assert response.status_code == 201, response.json()
    entry = response.json()["entry"]
    assert entry["kind"] == "talk" and entry["audience"] is None
    payload = entry["payload"]
    assert (payload["seat_id"], payload["name"], payload["text"]) == (ana_seat.id, "Ana", "")
    assert (payload["picture"]["width"], payload["picture"]["height"]) == (2048, 410)
    for client in (local, table["Bo"][1], table["Cy"][1], ana):
        served = client.get(path(table, f"talk/pictures/{entry['id']}"))
        assert served.status_code == 200
        assert served.headers["content-type"] == "image/webp"
        assert served.headers["x-content-type-options"] == "nosniff"
        assert Image.open(io.BytesIO(served.content)).size == (2048, 410)


def test_an_observer_sees_but_does_not_paste(local, table):  # noqa: F811
    allow(local, table)
    refused = paste(table["Cy"][1], table)
    assert refused.status_code == 403 and refused.json()["error"] == "Observers can't paste pictures."
    assert paste(local, table).status_code == 201  # the host may


def test_refusals(local, lan, table):  # noqa: F811
    allow(local, table)
    _, ana = table["Ana"]
    assert paste(ana, table, b"not a png").status_code == 400
    assert paste(ana, table, png(), "image/svg+xml").status_code == 415
    assert paste(ana, table, png(), "text/plain").status_code == 415
    assert paste(ana, table, b"\0" * (8 * 1024 * 1024 + 1)).status_code == 413
    assert paste(lan, table).status_code == 401
    text = ana.post(path(table, "talk"), json={"text": "Hi"}).json()["entry"]
    for missing in (text["id"], "sty_nothing"):
        assert ana.get(path(table, f"talk/pictures/{missing}")).status_code == 404
    assert lan.get(path(table, f"talk/pictures/{text['id']}")).status_code == 401


def test_who_may_take_a_picture_down(local, app, storage, table):  # noqa: F811
    allow(local, table)
    _, ana = table["Ana"]
    _, bo = table["Bo"]
    first = paste(ana, table).json()["entry"]
    refused = take(bo, table, first)
    assert (
        refused.status_code == 403
        and refused.json()["error"] == "Only the host, a co-host or who pasted it can take it down."
    )
    assert take(table["Cy"][1], table, first).status_code == 403

    before = len(published(app))
    taken = take(ana, table, first)
    assert taken.status_code == 200
    payload = taken.json()["entry"]["payload"]
    assert "picture" not in payload and payload["picture_removed"] is True
    assert [e.type for e in published(app)[before:]] == ["story"]
    assert bo.get(path(table, f"talk/pictures/{first['id']}")).status_code == 404
    assert storage.story.get(first["id"]).payload["picture_removed"] is True
    assert take(ana, table, first).status_code == 404

    second = paste(bo, table).json()["entry"]
    assert take(local, table, second).status_code == 200  # the host
    token = new_seat_token()
    storage.seats.create(table["campaign"], "Dee", "en", "cohost", token_hash=token_hash(token))
    third = paste(bo, table).json()["entry"]
    with TestClient(app, base_url=BASE_URL) as dee:
        dee.cookies.set(SEAT_COOKIE, token)
        assert take(dee, table, third).status_code == 200


def test_a_picture_counts_against_the_talk_throttle(local, table, monkeypatch):  # noqa: F811
    allow(local, table)
    _, ana = table["Ana"]
    taken = []
    from delve.web.routes import play

    class Counting:
        def take(self, seat_id, what):
            taken.append(what)

    monkeypatch.setattr(play, "seat_throttle", lambda app: Counting())
    paste(ana, table)
    assert taken == ["talk"]
