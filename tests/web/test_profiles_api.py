"""The profile routes (players and tavern Task D3): an account reads and changes its own profile and uploads an
avatar; others read it only when they share a table with it, and only a host of its tables reads the note for the
host and the time zone. A stranger can't tell an account exists, and no route lists accounts to a player.

`test_profiles_fourth_wall` plants `SECRET-XYZZY` in Ana's note for the host and `ABOUT-PLUGH` in her about me, then
calls every GET route of the API as Ana's table-mate, as a player at another table and as a seat token at another
table: the secret reaches none of them, and only the table-mate reads the about.
"""

import io
import re
from contextlib import ExitStack
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from delve.play import avatars as avatar_module
from delve.play import profiles, schedule, seats
from delve.play.avatars import AVATAR_LIMIT
from delve.web.routes import profiles as profile_routes
from delve.web.seats import SEAT_COOKIE, new_seat_token, token_hash
from tests.fixtures import avatars
from tests.web.conftest import BASE_URL, make_account, session_for
from tests.web.test_seats_identity import make_campaign

SECRET = "SECRET-XYZZY"
ABOUT = "ABOUT-PLUGH"
ZONE = "Pacific/Chatham"
NO_SUCH_PLAYER = {"error": "No such player."}


@pytest.fixture
def clients(app):
    with ExitStack() as stack:

        def open_client(*, local: bool = False) -> TestClient:
            client = TestClient(app, base_url=BASE_URL, **({"client": ("127.0.0.1", 50000)} if local else {}))
            return stack.enter_context(client)

        yield open_client


@pytest.fixture
def table(storage, clients):
    """Ana and Cy at Tuesday's table, Bo at Friday's, the owner hosting both; each account's LAN browser."""
    a, b = make_campaign(storage), make_campaign(storage, "Friday")
    for campaign in (a, b):
        seats.owner_seat(storage, campaign.id)
    found = {"a": a, "b": b}
    for username, campaign, name in (("ana", a, "Ana"), ("bob", b, "Bo"), ("cyd", a, "Cy")):
        account = make_account(storage, username)
        found[f"{username}_seat"] = storage.seats.create(campaign.id, name, "en", "player", account_id=account.id)
        client = clients()
        session_for(storage, account, client)
        found[username], found[f"{username}_client"] = account, client
    return found


def published(app) -> list[tuple[str, dict]]:
    return [(e.type, e.data) for e in app.state.events._buffer]


def upload(client: TestClient, data: bytes, media_type: str = "image/png"):
    return client.post("/api/account/avatar", content=data, headers={"Content-Type": media_type})


def test_put_profile_round_trip(table):
    ana = table["ana_client"]
    own = ana.get("/api/account/profile").json()
    assert (
        own["display_name"] == "ana" and own["colour"] == "teal" and own["avatar"] == {"emblem": own["avatar_emblem"]}
    )
    changes = {
        "display_name": " Ana the Bold ",
        "pronouns": "she/her",
        "avatar_emblem": "oak",
        "colour": "ember",
        "language": "nl",
        "about": "Likes maps.",
        "host_note": "Leaves at ten.",
        "time_zone": "Europe/Brussels",
    }
    response = ana.put("/api/account/profile", json=changes)
    assert response.status_code == 200, response.text
    assert response.json() == {
        "account_id": table["ana"].id,
        "display_name": "Ana the Bold",
        "pronouns": "she/her",
        "avatar": {"emblem": "oak"},
        "avatar_emblem": "oak",
        "colour": "ember",
        "language": "nl",
        "about": "Likes maps.",
        "host_note": "Leaves at ten.",
        "time_zone": "Europe/Brussels",
    }
    assert ana.get("/api/account/profile").json() == response.json()
    # Only the given keys change; `/api/me` follows the display name and the language.
    assert ana.put("/api/account/profile", json={"pronouns": ""}).json()["colour"] == "ember"
    assert ana.get("/api/me").json()["account"]["display_name"] == "Ana the Bold"
    assert ana.get("/api/me").json()["account"]["language"] == "nl"


def test_put_profile_refusals(table):
    ana = table["ana_client"]
    for body, message in (
        ({"display_name": ""}, "A display name has 1 to 40 characters."),
        ({"colour": "pink"}, "A colour is one of teal, jade, gold, ember."),
        ({"time_zone": "Mars/Olympus"}, "That isn't a time zone, such as Europe/Brussels."),
        ({"avatar_sha": "ab" * 32}, "A profile has no field 'avatar_sha'."),
        ({"about": "x" * 501}, "About you has at most 500 characters."),
    ):
        response = ana.put("/api/account/profile", json=body)
        assert (response.status_code, response.json()) == (422, {"error": message})
    assert ana.put("/api/account/profile", json=["display_name"]).status_code == 422
    assert ana.get("/api/account/profile").json()["display_name"] == "ana"


def test_own_profile_is_an_accounts(table, local, join_token_seat):
    assert local.get("/api/account/profile").status_code == 403
    assert local.put("/api/account/profile", json={"about": "x"}).status_code == 403
    assert upload(local, avatars.png_600x400()).status_code == 403
    _, seat_client = join_token_seat(table["a"].id)
    assert seat_client.get("/api/account/profile").json() == {"error": "Log in to an account first."}


def test_profile_change_tells_the_tables(app, storage, table):
    storage.seats.create(table["b"].id, "Ana", "en", "observer", account_id=table["ana"].id)
    before = len(published(app))
    assert table["ana_client"].put("/api/account/profile", json={"colour": "gold"}).status_code == 200
    told = published(app)[before:]
    assert sorted(data["campaign_id"] for kind, data in told if kind == "seats") == sorted(
        [table["a"].id, table["b"].id]
    )
    assert all(set(data) == {"campaign_id"} for _, data in told)


def test_avatar_upload(app, storage, table):
    ana = table["ana_client"]
    response = upload(ana, avatars.png_600x400())
    assert response.status_code == 200, response.text
    sha = storage.accounts.get(table["ana"].id).profile.avatar_sha
    assert response.json()["avatar"] == {"picture": sha[:12]}
    picture = ana.get(f"/api/profiles/{table['ana'].id}/avatar")
    assert picture.status_code == 200 and picture.headers["content-type"] == "image/webp"
    assert picture.headers["x-content-type-options"] == "nosniff"
    assert picture.headers["cache-control"] == "private, max-age=86400"
    image = Image.open(io.BytesIO(picture.content))
    assert (image.format, image.size) == ("WEBP", (256, 256))
    assert picture.content == storage.blobs.get(sha)
    # A table-mate sees it; the seat list carries it.
    assert table["cyd_client"].get(f"/api/profiles/{table['ana'].id}/avatar").content == picture.content
    listed = table["cyd_client"].get(f"/api/campaigns/{table['a'].id}/seats").json()
    assert next(s for s in listed if s["name"] == "Ana")["profile"]["avatar"] == {"picture": sha[:12]}
    # Back to the emblem; then the picture is gone.
    emblem = storage.accounts.get(table["ana"].id).profile.avatar_emblem
    removed = ana.request("DELETE", "/api/account/avatar", json={})
    assert removed.status_code == 200 and removed.json()["avatar"] == {"emblem": emblem}
    assert ana.get(f"/api/profiles/{table['ana'].id}/avatar").json() == NO_SUCH_PLAYER


def test_avatar_upload_tells_the_tables(app, table):
    before = len(published(app))
    assert upload(table["ana_client"], avatars.exif_rotated_jpeg(), "image/jpeg").status_code == 200
    assert ("seats", {"campaign_id": table["a"].id}) in published(app)[before:]


def test_avatar_refusals(storage, table):
    ana = table["ana_client"]
    mismatch = upload(ana, avatars.png_600x400(), "image/jpeg")
    assert (mismatch.status_code, mismatch.json()) == (400, {"error": "That picture isn't a JPEG."})
    bomb = upload(ana, avatars.pixel_bomb_png())
    assert (bomb.status_code, bomb.json()) == (422, {"error": "That picture is too large: at most 16 million pixels."})


def test_avatar_zeros_bomb_is_422(table):
    """155 KB that would decode to 160 MB: refused at the cap, before it is decoded (Clara's final audit, finding 1)."""
    bomb = upload(table["ana_client"], avatars.zeros_png(6320, 6320))
    assert (bomb.status_code, bomb.json()) == (422, {"error": "That picture is too large: at most 16 million pixels."})


def test_avatar_busy_is_503(table, monkeypatch):
    monkeypatch.setattr(avatar_module, "AVATAR_WAIT_S", 0.01)
    monkeypatch.setattr(avatar_module, "_making", avatar_module.threading.BoundedSemaphore(1))
    avatar_module._making.acquire()
    busy = upload(table["ana_client"], avatars.png_600x400())
    assert (busy.status_code, busy.json()) == (503, {"error": "Busy: try again in a moment."})
    avatar_module._making.release()
    assert upload(table["ana_client"], avatars.png_600x400()).status_code == 200


def test_avatar_uploads_per_account_per_minute(table, monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(profile_routes, "clock", lambda: now[0])
    ana, cyd = table["ana_client"], table["cyd_client"]
    for _ in range(profile_routes.AVATARS_PER_MINUTE):
        assert upload(ana, b"not a picture").status_code == 400, "a refused upload counts too"
    too_many = upload(ana, avatars.png_600x400())
    assert (too_many.status_code, too_many.json()) == (429, {"error": "Too many avatars: wait a minute."})
    assert upload(cyd, avatars.png_600x400()).status_code == 200, "per account"
    now[0] += 61
    assert upload(ana, avatars.png_600x400()).status_code == 200


def test_avatar_bytes_counted(storage, table):
    def undeclared():
        yield b"\x89PNG\r\n\x1a\n"
        yield b"\0" * AVATAR_LIMIT

    response = table["ana_client"].post(
        "/api/account/avatar", content=undeclared(), headers={"Content-Type": "image/png"}
    )
    assert response.status_code == 413
    assert response.json() == {"error": f"An avatar may be at most {AVATAR_LIMIT} bytes."}


def test_avatar_refusal_stores_nothing(storage, table, monkeypatch):
    stored = []
    real_put = storage.blobs.put
    monkeypatch.setattr(storage.blobs, "put", lambda data, mime: stored.append(mime) or real_put(data, mime))
    ana = table["ana_client"]
    assert upload(ana, avatars.png_600x400(), "image/webp").status_code == 400
    assert upload(ana, avatars.pixel_bomb_png()).status_code == 422
    assert upload(ana, b"\x89PNG" + b"\0" * 100).status_code == 400
    assert stored == [] and storage.accounts.get(table["ana"].id).profile.avatar_sha is None


def test_profile_of_a_stranger_is_404(table, clients):
    ana_id = table["ana"].id
    bo = table["bob_client"]
    assert upload(table["ana_client"], avatars.png_600x400()).status_code == 200
    for path in (f"/api/profiles/{ana_id}", f"/api/profiles/{ana_id}/avatar"):
        assert (bo.get(path).status_code, bo.get(path).json()) == (404, NO_SUCH_PLAYER)
    # The same answer as for an account that doesn't exist.
    for path in ("/api/profiles/acc_nobody", "/api/profiles/acc_nobody/avatar"):
        assert (bo.get(path).status_code, bo.get(path).json()) == (404, NO_SUCH_PLAYER)
    # Nobody logged in is nobody.
    assert clients().get(f"/api/profiles/{ana_id}").status_code == 401


def test_table_mate_reads_the_card(table):
    seen = table["cyd_client"].get(f"/api/profiles/{table['ana'].id}")
    assert seen.status_code == 200
    assert set(seen.json()) == {"account_id", "display_name", "pronouns", "avatar", "colour", "about"}


def test_seat_list_carries_profiles(storage, table, join_token_seat):
    a = table["a"].id
    join_token_seat(a)
    listed = {s["name"]: s for s in table["cyd_client"].get(f"/api/campaigns/{a}/seats").json()}
    assert listed["Ana"]["profile"] == {
        "account_id": table["ana"].id,
        "display_name": "ana",
        "pronouns": "",
        "avatar": {"emblem": table["ana"].profile.avatar_emblem},
        "colour": "teal",
    }
    assert listed["Dee"]["profile"] is None  # a token seat
    owner = next(s for s in listed.values() if s["role"] == "host")
    assert owner["profile"] is None


def test_host_reads_the_note(storage, table, local, lan, token):
    storage.accounts.save_profile(
        table["ana"].id, replace(table["ana"].profile, host_note="Leaves at ten.", time_zone=ZONE)
    )
    path = f"/api/profiles/{table['ana'].id}"
    for host in (local, lan_with_token(lan, token)):
        card = host.get(path).json()
        assert card["host_note"] == "Leaves at ten." and card["time_zone"] == ZONE
    # Cy, made A's co-host, reads them too.
    storage.seats.save(replace(table["cyd_seat"], role="cohost"))
    assert table["cyd_client"].get(path).json()["host_note"] == "Leaves at ten."


def test_player_does_not_read_the_note(storage, table, clients):
    storage.accounts.save_profile(
        table["ana"].id, replace(table["ana"].profile, host_note="Leaves at ten.", time_zone=ZONE)
    )
    card = table["cyd_client"].get(f"/api/profiles/{table['ana'].id}").json()
    assert "host_note" not in card and "time_zone" not in card
    # An organiser account hosting another table reads the card, not the host's fields.
    organiser = make_account(storage, "orga", organiser=True)
    storage.seats.create(table["b"].id, "Org", "en", "cohost", account_id=organiser.id)
    client = clients()
    session_for(storage, organiser, client)
    card = client.get(f"/api/profiles/{table['ana'].id}").json()
    assert card["display_name"] == "ana" and "host_note" not in card


def test_seat_token_reads_its_tables_profiles(table, join_token_seat):
    _, at_a = join_token_seat(table["a"].id)
    _, at_b = join_token_seat(table["b"].id)
    assert at_a.get(f"/api/profiles/{table['ana'].id}").json()["display_name"] == "ana"
    assert at_b.get(f"/api/profiles/{table['ana'].id}").json() == NO_SUCH_PLAYER
    _, host = join_token_seat(table["b"].id, role="cohost")
    card = host.get(f"/api/profiles/{table['bob'].id}").json()
    assert "host_note" in card and "host_note" not in at_b.get(f"/api/profiles/{table['bob'].id}").json()


def test_no_route_lists_accounts_to_a_player(table, join_token_seat):
    _, seat_client = join_token_seat(table["a"].id)
    for client in (table["ana_client"], seat_client):
        assert client.get("/api/accounts").status_code == 403
        assert client.get("/api/profiles").status_code in (404, 405)


def lan_with_token(lan: TestClient, token: str) -> TestClient:
    lan.headers["Authorization"] = f"Bearer {token}"
    return lan


@pytest.fixture
def join_token_seat(app, storage, clients):
    """`join_token_seat(campaign_id, role="player")`: a seat made by a token, as before accounts, named Dee, and a
    LAN browser holding it."""

    def make(campaign_id, role="player"):
        token = new_seat_token()
        seat = storage.seats.create(campaign_id, "Dee", "en", role, token_hash=token_hash(token))
        client = clients()
        client.cookies.set(SEAT_COOKIE, token)
        return seat, client

    return make


PARAMS = re.compile(r"{([^}:]+)(?::[^}]+)?}")


def get_routes(app, values: dict[str, str]) -> list[str]:
    """Every GET route of the API whose path parameters `values` fills, filled; the event stream left out (it doesn't
    end), and the SPA."""
    paths = []
    for path, operations in app.openapi()["paths"].items():
        if "get" not in operations or not path.startswith("/api/") or path == "/api/events":
            continue
        if all(name in values for name in PARAMS.findall(path)):
            paths.append(PARAMS.sub(lambda m: values[m.group(1)], path))
    return paths


def test_profiles_fourth_wall(app, storage, table, join_token_seat):
    ana = table["ana"]
    storage.accounts.save_profile(ana.id, replace(ana.profile, about=ABOUT, host_note=SECRET, time_zone=ZONE))
    _, token_at_b = join_token_seat(table["b"].id)
    viewers = {
        "Cy (Ana's table)": table["cyd_client"],
        "Bo (another table)": table["bob_client"],
        "a token seat at B": token_at_b,
    }
    for campaign in ("a", "b"):
        values = {"campaign_id": table[campaign].id, "account_id": ana.id, "seat_id": table["ana_seat"].id}
        paths = get_routes(app, values)
        assert f"/api/profiles/{ana.id}" in paths and f"/api/campaigns/{table[campaign].id}/seats" in paths
        for who, client in viewers.items():
            for path in [*paths, f"/api/me?campaign={table[campaign].id}"]:
                text = client.get(path).text
                assert SECRET not in text, (who, path)
                # The list of every time zone names Ana's too, not as hers.
                assert path == "/api/time-zones" or ZONE not in text, (who, path)
                if who != "Cy (Ana's table)":
                    assert ABOUT not in text, (who, path)
    # The control: the planted words are there for those who may read them.
    assert ABOUT in table["cyd_client"].get(f"/api/profiles/{ana.id}").text
    assert SECRET in table["ana_client"].get("/api/account/profile").text


def test_time_zones_are_the_ones_the_server_takes(table):
    """The pickers' zones (DEL-239) come from the server: each one a profile and a schedule accept, none of ICU's
    aliases the tz database dropped (the browser offered Africa/Asmera, which the schedule then refused)."""
    zones = table["ana_client"].get("/api/time-zones").json()
    assert "Europe/Brussels" in zones and "Africa/Asmara" in zones and zones[-1] == "UTC"
    assert "Africa/Asmera" not in zones and "US/Eastern" not in zones and not any(z.startswith("Etc/") for z in zones)
    for zone in zones:
        assert profiles.updated(table["ana"].profile, {"time_zone": zone}).time_zone == zone
        schedule._zone(zone)
