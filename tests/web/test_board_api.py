"""The board's API (DEL-297): the index, zones, topics and posts as the zone's rights allow, pictures and avatars served
by those rights, read marks for accounts, the throttle on writing, the guard's raw picture path, and a deleted
campaign's zone. Anything the caller may not read is 404, and absent from `/api/board`."""

import io

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from delve.domain.accounts import Profile
from delve.domain.board import Post
from delve.mail.settings import MailSettings, save, save_key
from delve.web.routes import board as board_routes
from tests.web.conftest import BASE_URL, make_account, session_for
from tests.web.test_preferences_api import published
from tests.web.test_seats_identity import make_campaign


def png(size=(300, 200)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, (20, 120, 200)).save(out, "PNG")
    return out.getvalue()


def make_zone(client, **fields) -> str:
    answer = client.post("/api/board/zones", json={"name": "Engine", **fields})
    assert answer.status_code == 201, answer.text
    return answer.json()["zone"]["id"]


def start(client, zone, title="Hello", text="First words.", with_picture=False) -> tuple[str, str]:
    answer = client.post(f"/api/board/zones/{zone}/topics", json={"title": title, "text": text})
    assert answer.status_code == 201, answer.text
    topic, post = answer.json()["topic"]["id"], answer.json()["post"]["id"]
    if with_picture:
        client.patch(f"/api/board/zones/{zone}", json={"pictures": True})
        assert attach(client, post).status_code == 200
    return topic, post


def attach(client, post, data=None, media_type="image/png"):
    return client.post(
        f"/api/board/posts/{post}/picture",
        content=png() if data is None else data,
        headers={"Content-Type": media_type},
    )


@pytest.fixture
def clients(app):
    made = []

    def make(address="10.0.0.9"):
        client = TestClient(app, base_url=BASE_URL, client=(address, 50000))
        client.__enter__()
        made.append(client)
        return client

    yield make
    for client in made:
        client.__exit__(None, None, None)


@pytest.fixture
def logged_in(storage, clients):
    """`logged_in("bob")`: a browser on the LAN logged in to a new account of that username."""

    def make(username, **flags):
        account = make_account(storage, username, **flags)
        client = clients()
        session_for(storage, account, client)
        return account, client

    return make


def delete(client, path):
    """A DELETE, which the guard takes as JSON as every write."""
    return client.request("DELETE", path, json={})


def board_events(app):
    return [(e.data, e.zone_id) for e in published(app) if e.type == "board"]


# ----- visitors and who may read -----


def test_a_visitor_reads_an_open_zone_and_is_told_to_log_in(local, clients):
    zone = make_zone(local, read="everybody", write="accounts")
    topic, _ = start(local, zone)
    visitor = clients()
    assert visitor.get(f"/api/board/zones/{zone}").status_code == 200
    assert visitor.get(f"/api/board/topics/{topic}").status_code == 200
    index = visitor.get("/api/board").json()
    assert index["signed_in"] is False and index["may_create"] is False
    assert [z["id"] for z in index["zones"]] == [zone]
    refused = visitor.post(f"/api/board/zones/{zone}/topics", json={"title": "Hi", "text": "x"})
    assert refused.status_code == 401, refused.text
    assert visitor.post(f"/api/board/topics/{topic}/posts", json={"text": "x"}).status_code == 401


def test_nothing_of_a_closed_zone_shows_to_who_may_not_read_it(app, local, logged_in):
    zone = make_zone(local, read="members", write="members")
    topic, post = start(local, zone, with_picture=True)
    _, bo = logged_in("bob")
    assert zone not in [z["id"] for z in bo.get("/api/board").json()["zones"]]
    for path in (f"zones/{zone}", f"topics/{topic}", f"posts/{post}/picture", f"posts/{post}/avatar"):
        assert bo.get(f"/api/board/{path}").status_code == 404, path
    assert bo.post(f"/api/board/topics/{topic}/posts", json={"text": "x"}).status_code == 404
    assert bo.patch(f"/api/board/posts/{post}", json={"text": "x"}).status_code == 404
    assert bo.get(f"/api/board/zones/{zone}/people").status_code == 404


def test_a_member_taken_out_loses_the_zone_at_once(local, logged_in):
    zone = make_zone(local, read="members", write="members")
    topic, _ = start(local, zone)
    bo_account, bo = logged_in("bob")
    assert local.post(f"/api/board/zones/{zone}/members", json={"username": "BOB "}).status_code == 200
    assert bo.get(f"/api/board/topics/{topic}").status_code == 200
    people = local.get(f"/api/board/zones/{zone}/people").json()
    assert people == {
        "moderators": [],
        "members": [{"account_id": bo_account.id, "display_name": "bob", "username": "bob"}],
    }
    assert delete(local, f"/api/board/zones/{zone}/members/{bo_account.id}").status_code == 200
    assert bo.get(f"/api/board/topics/{topic}").status_code == 404
    assert zone not in [z["id"] for z in bo.get("/api/board").json()["zones"]]


def test_a_post_shows_name_face_and_badges_but_not_the_profile(storage, local, logged_in):
    zone = make_zone(local, read="everybody", write="accounts", pictures=True)
    ana, ana_client = logged_in("ana")
    storage.accounts.save_profile(
        ana.id, Profile("Ana", pronouns="she/her", about="Secret things.", avatar_sha="ab" * 32)
    )
    storage.blobs.put(b"avatar bytes", "image/webp")
    _, bo = logged_in("bob")
    topic, _ = start(ana_client, zone)
    local.put(f"/api/board/zones/{zone}/moderators", json={"usernames": ["ana"]})
    shown = bo.get(f"/api/board/topics/{topic}").json()
    author = shown["posts"][0]["author"]
    assert set(author) == {"account_id", "display_name", "avatar", "colour", "badges"}
    assert author["account_id"] == ana.id and author["display_name"] == "Ana"
    assert author["avatar"] == {"picture": "ab" * 6} and author["badges"] == ["moderator"]
    assert shown["posts"][0]["mine"] is False
    assert ana_client.get(f"/api/board/topics/{topic}").json()["posts"][0]["mine"] is True
    assert shown["topic"]["author"] == author and shown["topic"]["last_author"] == author


def test_the_authors_avatar_is_served_to_who_reads_the_zone(storage, local, logged_in, clients):
    zone = make_zone(local, read="everybody", write="accounts")
    ana, ana_client = logged_in("ana")
    _, post = start(ana_client, zone)
    assert clients().get(f"/api/board/posts/{post}/avatar").status_code == 404  # no uploaded avatar
    sha = storage.blobs.put(b"avatar bytes", "image/webp")
    storage.accounts.save_profile(ana.id, Profile("Ana", avatar_sha=sha))
    answer = clients().get(f"/api/board/posts/{post}/avatar")
    assert answer.status_code == 200 and answer.content == b"avatar bytes"
    assert answer.headers["content-type"] == "image/webp"


def test_the_owner_by_token_posts_with_no_author_and_it_is_theirs(local):
    zone = make_zone(local)
    topic, _ = start(local, zone)
    post = local.get(f"/api/board/topics/{topic}").json()["posts"][0]
    assert post["author"] == {"account_id": None, "display_name": "", "avatar": None, "colour": None, "badges": []}
    assert post["mine"] is True


def test_a_gone_authors_posts_keep_the_id_and_lose_the_name(storage, local):
    zone = make_zone(local)
    topic, _ = start(local, zone)
    storage.board.add_post(Post("", topic, "acc_gone", "Still here.", "2026-10-29T21:00:00+00:00"))
    posts = local.get(f"/api/board/topics/{topic}").json()["posts"]
    author = next(p["author"] for p in posts if p["text"] == "Still here.")
    assert author == {"account_id": "acc_gone", "display_name": "", "avatar": None, "colour": None, "badges": []}


# ----- zones -----


def test_an_organiser_makes_reorders_and_deletes_zones(app, local):
    engine = make_zone(local, name="Engine", description="How Delve works.")
    rules = make_zone(local, name="Rules")
    shown = local.get(f"/api/board/zones/{engine}").json()["zone"]
    assert shown == {
        "id": engine,
        "name": "Engine",
        "description": "How Delve works.",
        "position": 0,
        "read": "accounts",
        "write": "accounts",
        "pictures": False,
        "campaign_id": None,
        "rights": {"read": True, "write": True, "moderate": True, "manage": True, "manage_wide": True},
    }
    order = local.put("/api/board/order", json={"zone_ids": [rules, engine]})
    assert [z["id"] for z in order.json()["zones"]] == [rules, engine]
    assert local.put("/api/board/order", json={"zone_ids": [rules]}).status_code == 422
    renamed = local.patch(f"/api/board/zones/{engine}", json={"name": "The engine"})
    assert renamed.json()["zone"]["name"] == "The engine"
    assert (
        local.patch(f"/api/board/zones/{engine}", json={"read": "everybody", "write": "everybody"}).status_code == 422
    )
    assert delete(local, f"/api/board/zones/{engine}").status_code == 204
    assert local.get(f"/api/board/zones/{engine}").status_code == 404
    assert local.get("/api/board").json()["may_create"] is True
    assert ({"zone_id": engine}, engine) in board_events(app)


def test_an_account_may_not_make_a_zone(logged_in):
    _, bo = logged_in("bob")
    assert bo.post("/api/board/zones", json={"name": "Mine"}).status_code == 403


def test_a_host_cannot_open_their_zone_to_accounts(storage, logged_in):
    campaign = make_campaign(storage)
    host, client = logged_in("hal")
    storage.seats.create(campaign.id, "hal", "en", "host", account_id=host.id)
    made = client.post("/api/board/zones", json={"name": "Our table", "campaign_id": campaign.id})
    assert made.status_code == 201, made.text
    zone = made.json()["zone"]
    assert (zone["read"], zone["write"]) == ("table", "table")
    refused = client.patch(f"/api/board/zones/{zone['id']}", json={"read": "accounts", "write": "accounts"})
    assert refused.status_code == 403, refused.text
    assert (
        client.patch(f"/api/board/zones/{zone['id']}", json={"read": "members", "write": "members"}).status_code == 200
    )
    assert client.post("/api/board/zones", json={"name": "Another", "campaign_id": campaign.id}).status_code == 409


def test_a_host_saves_a_zone_an_organiser_opened_wider(storage, local, logged_in):
    campaign = make_campaign(storage)
    host, client = logged_in("hal")
    storage.seats.create(campaign.id, "hal", "en", "host", account_id=host.id)
    zone = make_zone(local, campaign_id=campaign.id, read="table", write="table")
    assert local.patch(f"/api/board/zones/{zone}", json={"read": "accounts", "write": "accounts"}).status_code == 200
    saved = client.patch(
        f"/api/board/zones/{zone}", json={"name": "Tuesdays", "read": "accounts", "write": "accounts", "pictures": True}
    )
    assert saved.status_code == 200, saved.text
    shown = saved.json()["zone"]
    assert (shown["name"], shown["read"], shown["write"]) == ("Tuesdays", "accounts", "accounts")
    assert shown["pictures"] is True
    assert client.patch(f"/api/board/zones/{zone}", json={"read": "everybody"}).status_code == 403


def test_deleting_a_campaign_unties_its_zone(storage, local):
    campaign = make_campaign(storage)
    zone = make_zone(local, campaign_id=campaign.id, read="table", write="table")
    assert delete(local, f"/api/campaigns/{campaign.id}").status_code == 204
    shown = local.get(f"/api/board/zones/{zone}").json()["zone"]
    assert (shown["campaign_id"], shown["read"], shown["write"]) == (None, "members", "members")


# ----- topics, posts and marks -----


def test_a_topic_pages_its_posts(local, monkeypatch):
    monkeypatch.setattr(board_routes, "POSTS_PER_MINUTE", 1000)
    zone = make_zone(local)
    topic, _ = start(local, zone)
    for n in range(board_routes.POST_PAGE + 4):
        assert local.post(f"/api/board/topics/{topic}/posts", json={"text": f"Reply {n}"}).status_code == 201
    first = local.get(f"/api/board/topics/{topic}?page=1").json()
    assert (first["page"], first["pages"], len(first["posts"])) == (1, 2, board_routes.POST_PAGE)
    second = local.get(f"/api/board/topics/{topic}?page=2").json()
    assert len(second["posts"]) == 5 and second["posts"][-1]["text"] == f"Reply {board_routes.POST_PAGE + 3}"
    assert local.get(f"/api/board/topics/{topic}?page=0").status_code == 422


def test_reading_a_topic_clears_its_new_mark(local, logged_in):
    zone = make_zone(local)
    _, bo = logged_in("bob")
    bo.get("/api/board")  # the first visit: what comes after it is new
    topic, _ = start(local, zone)
    index = bo.get("/api/board").json()["zones"][0]
    assert (index["topics"], index["new_topics"]) == (1, 1)
    listed = bo.get(f"/api/board/zones/{zone}").json()["topics"][0]
    assert listed["new"] is True and listed["posts"] == 1
    read = bo.get(f"/api/board/topics/{topic}").json()
    assert read["first_unread_page"] == 1
    assert bo.get(f"/api/board/zones/{zone}").json()["topics"][0]["new"] is False
    assert bo.get("/api/board").json()["zones"][0]["new_topics"] == 0


def test_the_board_names_each_zones_latest_topic(local, logged_in):
    zone = make_zone(local)
    quiet = make_zone(local, name="Quiet")
    _, bo = logged_in("bob")
    first, _ = start(local, zone, title="Older")
    later, _ = start(bo, zone, title="Newer")
    local.post(f"/api/board/topics/{first}/posts", json={"text": "Back to this one."})
    zones = {listed["id"]: listed for listed in local.get("/api/board").json()["zones"]}
    latest = zones[zone]["latest"]
    assert (latest["topic_id"], latest["title"], latest["author"]["account_id"]) == (first, "Older", None)
    assert zones[quiet]["latest"] is None
    assert later != first


def test_a_topic_names_its_first_unread_post_on_the_page(local, logged_in):
    zone = make_zone(local)
    _, bo = logged_in("bob")
    topic, first = start(bo, zone)
    assert bo.get(f"/api/board/topics/{topic}").json()["first_unread_post"] is None  # bob wrote it
    later = local.post(f"/api/board/topics/{topic}/posts", json={"text": "News."}).json()["post"]["id"]
    local.post(f"/api/board/topics/{topic}/posts", json={"text": "More news."})
    read = bo.get(f"/api/board/topics/{topic}").json()
    assert read["first_unread_post"] == later and first != later
    assert bo.get(f"/api/board/topics/{topic}").json()["first_unread_post"] is None


def test_a_visitor_sees_no_new_marks(local, clients):
    zone = make_zone(local, read="everybody", write="accounts")
    start(local, zone)
    visitor = clients()
    assert visitor.get("/api/board").json()["zones"][0]["new_topics"] == 0
    assert visitor.get(f"/api/board/zones/{zone}").json()["topics"][0]["new"] is False


def test_replies_edits_and_removals(app, local, logged_in):
    zone = make_zone(local)
    _, ana = logged_in("ana")
    topic, first = start(ana, zone)
    _, bo = logged_in("bob")
    reply = bo.post(f"/api/board/topics/{topic}/posts", json={"text": "  Welcome!  "})
    assert reply.status_code == 201 and reply.json()["post"]["text"] == "Welcome!"
    assert bo.patch(f"/api/board/posts/{first}", json={"text": "Mine now"}).status_code == 403
    edited = ana.patch(f"/api/board/posts/{first}", json={"text": "Better words."}).json()["post"]
    assert edited["text"] == "Better words." and edited["edited_at"] is not None
    removed = delete(local, f"/api/board/posts/{first}").json()["post"]
    assert (removed["removed"], removed["text"]) == ("moderator", "")
    assert ana.patch(f"/api/board/posts/{first}", json={"text": "Again"}).status_code == 409
    assert local.patch(f"/api/board/topics/{topic}", json={"locked": True}).json()["topic"]["locked"] is True
    assert bo.post(f"/api/board/topics/{topic}/posts", json={"text": "Late"}).status_code == 409
    assert bo.patch(f"/api/board/topics/{topic}", json={"pinned": True}).status_code == 403
    assert local.patch(f"/api/board/topics/{topic}", json={"pinned": "yes"}).status_code == 422
    assert ({"zone_id": zone, "topic_id": topic}, zone) in board_events(app)
    assert delete(local, f"/api/board/topics/{topic}").status_code == 204
    assert local.get(f"/api/board/topics/{topic}").status_code == 404


def test_bad_input_is_422(local):
    zone = make_zone(local)
    assert local.post(f"/api/board/zones/{zone}/topics", json={"title": " ", "text": "x"}).status_code == 422
    assert local.post(f"/api/board/zones/{zone}/topics", json=["x"]).status_code == 422
    assert local.post("/api/board/zones", json={"name": "x", "colour": "red"}).status_code == 422
    assert local.put(f"/api/board/zones/{zone}/moderators", json={"usernames": "ana"}).status_code == 422
    assert local.post(f"/api/board/zones/{zone}/members", json={"username": "nobody"}).status_code == 422


# ----- pictures -----


def test_a_picture_is_refused_while_the_zone_has_pictures_off(local, logged_in):
    zone = make_zone(local)
    _, ana = logged_in("ana")
    _, post = start(ana, zone)
    assert attach(ana, post).status_code == 403
    local.patch(f"/api/board/zones/{zone}", json={"pictures": True})
    attached = attach(ana, post)
    assert attached.status_code == 200, attached.text
    assert attached.json()["post"]["picture"] == {"width": 300, "height": 200}
    assert attach(ana, post, data=b"not a png").status_code == 400


def test_a_picture_is_served_to_readers_and_taken_down(local, logged_in, clients):
    zone = make_zone(local, read="everybody", write="accounts", pictures=True)
    _, ana = logged_in("ana")
    _, post = start(ana, zone)
    attach(ana, post)
    visitor = clients()
    shown = visitor.get(f"/api/board/posts/{post}/picture")
    assert shown.status_code == 200 and shown.headers["content-type"] == "image/webp"
    assert shown.headers["cache-control"] == "private, no-cache"
    again = visitor.get(f"/api/board/posts/{post}/picture", headers={"If-None-Match": shown.headers["etag"]})
    assert again.status_code == 304
    _, bo = logged_in("bob")
    assert delete(bo, f"/api/board/posts/{post}/picture").status_code == 403
    assert delete(ana, f"/api/board/posts/{post}/picture").json()["post"]["picture"] is None
    assert visitor.get(f"/api/board/posts/{post}/picture").status_code == 404


def test_who_may_not_attach_costs_no_decoding(local, logged_in, clients, monkeypatch):
    zone = make_zone(local, read="everybody", write="accounts", pictures=True)
    _, ana = logged_in("ana")
    _, post = start(ana, zone)

    def no_decoding(*_):
        raise AssertionError("decoded a picture for who may not attach one")

    monkeypatch.setattr(board_routes, "talk_picture", no_decoding)
    assert attach(clients(), post).status_code == 401
    _, bo = logged_in("bob")
    assert attach(bo, post).status_code == 403
    local.patch(f"/api/board/zones/{zone}", json={"pictures": False})
    assert attach(ana, post).status_code == 403


def test_pictures_count_against_the_throttle(local, logged_in, monkeypatch):
    monkeypatch.setattr(board_routes, "clock", lambda: 1000.0)
    zone = make_zone(local, pictures=True)
    _, ana = logged_in("ana")
    _, post = start(ana, zone)
    for _ in range(board_routes.POSTS_PER_MINUTE - 1):
        assert attach(ana, post).status_code == 200
    assert attach(ana, post).status_code == 429
    assert ana.post(f"/api/board/zones/{zone}/topics", json={"title": "t", "text": "x"}).status_code == 429


def test_the_guard_takes_a_board_picture_and_nothing_else_raw(local):
    as_text = local.post("/api/board/posts/p1/picture", content=b"x", headers={"Content-Type": "text/plain"})
    assert as_text.status_code == 415 and "picture" in as_text.json()["error"]
    # Through the guard to the route, which knows no such post.
    assert attach(local, "p1").status_code == 404
    elsewhere = local.post("/api/board/posts/p1/text", content=png(), headers={"Content-Type": "image/png"})
    assert elsewhere.status_code == 415 and elsewhere.json() == {"error": "send the body as application/json"}
    patched = local.patch("/api/board/posts/p1/picture", content=png(), headers={"Content-Type": "image/png"})
    assert patched.status_code == 415


# ----- the throttle -----


def test_posting_too_fast_is_429(local, logged_in, monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(board_routes, "clock", lambda: now[0])
    zone = make_zone(local)
    _, ana = logged_in("ana")
    topic, post = start(ana, zone)
    for n in range(board_routes.POSTS_PER_MINUTE - 2):
        assert ana.post(f"/api/board/topics/{topic}/posts", json={"text": f"{n}"}).status_code == 201
    assert ana.patch(f"/api/board/posts/{post}", json={"text": "edited"}).status_code == 200
    assert ana.post(f"/api/board/topics/{topic}/posts", json={"text": "one too many"}).status_code == 429
    assert ana.post(f"/api/board/zones/{zone}/topics", json={"title": "t", "text": "x"}).status_code == 429
    _, bo = logged_in("bob")
    assert bo.post(f"/api/board/topics/{topic}/posts", json={"text": "mine"}).status_code == 201
    now[0] += 61
    assert ana.post(f"/api/board/topics/{topic}/posts", json={"text": "later"}).status_code == 201


# Board replies by email (DEL-314): follow a topic, and a reply queues one email for its followers.

FAR = "2100-01-01T00:00:00+00:00"


@pytest.fixture
def mail_on(config, monkeypatch):
    monkeypatch.delenv("EMAILIT_API_KEY", raising=False)
    monkeypatch.delenv("DELVE_ALLOWED_HOSTS", raising=False)
    save(config.data_dir, MailSettings(provider="emailit", sender="d@example.org", public_url="https://delve.example"))
    save_key(config.data_dir, "k-1")


def with_mail(storage, account):
    storage.accounts.set_email(account.id, email=f"{account.username}@example.org", email_pending=None)


def board_mail(storage, account_id=None):
    return [m for m in storage.mail.due(FAR, 100) if m.kind == "board" and account_id in (None, m.account_id)]


def test_an_account_follows_and_stops_following_a_topic(local, logged_in, clients):
    zone = make_zone(local, read="everybody", write="accounts")
    _, ana = logged_in("ana")
    topic, _ = start(local, zone)
    assert ana.get(f"/api/board/topics/{topic}").json()["topic"]["following"] is False
    assert ana.put(f"/api/board/topics/{topic}/follow", json={}).json() == {"following": True}
    assert ana.get(f"/api/board/topics/{topic}").json()["topic"]["following"] is True
    assert delete(ana, f"/api/board/topics/{topic}/follow").json() == {"following": False}
    assert ana.get(f"/api/board/topics/{topic}").json()["topic"]["following"] is False
    assert clients().put(f"/api/board/topics/{topic}/follow", json={}).status_code == 401


def test_only_who_may_read_follows(local, logged_in):
    zone = make_zone(local, read="members", write="members")
    topic, _ = start(local, zone)
    _, ana = logged_in("ana")
    assert ana.put(f"/api/board/topics/{topic}/follow", json={}).status_code == 404
    assert ana.put("/api/board/topics/btp_nothing/follow", json={}).status_code == 404


def test_a_reply_or_a_topic_with_follow_follows_it(storage, local, logged_in):
    zone = make_zone(local)
    ana_account, ana = logged_in("ana")
    answer = ana.post(f"/api/board/zones/{zone}/topics", json={"title": "Hi", "text": "Words", "follow": True})
    assert answer.status_code == 201 and answer.json()["topic"]["following"] is True
    other, _ = start(local, zone)
    assert ana.post(f"/api/board/topics/{other}/posts", json={"text": "Me too", "follow": True}).status_code == 201
    assert storage.board.following(ana_account.id, other)
    assert ana.post(f"/api/board/topics/{other}/posts", json={"text": "Me", "follow": "yes"}).status_code == 422


def test_a_reply_queues_one_email_for_a_follower_until_they_read(storage, local, logged_in, mail_on):
    zone = make_zone(local)
    ana_account, ana = logged_in("ana")
    bob_account, bob = logged_in("bob")
    with_mail(storage, ana_account)
    with_mail(storage, bob_account)
    topic, _ = start(ana, zone)
    ana.put(f"/api/board/topics/{topic}/follow", json={})
    bob.post(f"/api/board/topics/{topic}/posts", json={"text": "One", "follow": True})
    bob.post(f"/api/board/topics/{topic}/posts", json={"text": "Two"})
    [mail] = board_mail(storage, ana_account.id)
    assert f"https://delve.example/board/{zone}/{topic}" in mail.text and "One" in mail.text
    assert board_mail(storage, bob_account.id) == []
    ana.get(f"/api/board/topics/{topic}")
    ana.post(f"/api/board/topics/{topic}/posts", json={"text": "Back"})
    bob.post(f"/api/board/topics/{topic}/posts", json={"text": "Three"})
    assert len(board_mail(storage, ana_account.id)) == 2
    assert len(board_mail(storage, bob_account.id)) == 1


def test_no_email_while_mail_is_off(storage, local, logged_in):
    zone = make_zone(local)
    ana_account, ana = logged_in("ana")
    with_mail(storage, ana_account)
    topic, _ = start(local, zone)
    ana.put(f"/api/board/topics/{topic}/follow", json={})
    local.post(f"/api/board/topics/{topic}/posts", json={"text": "News"})
    assert board_mail(storage) == []


def test_a_reply_answers_at_once_with_a_provider_that_raises(app, storage, local, logged_in, mail_on):
    def broken(request):
        raise httpx.ConnectError("down")

    app.state.mail_transport = httpx.MockTransport(broken)
    zone = make_zone(local)
    ana_account, ana = logged_in("ana")
    with_mail(storage, ana_account)
    topic, _ = start(local, zone)
    ana.put(f"/api/board/topics/{topic}/follow", json={})
    assert local.post(f"/api/board/topics/{topic}/posts", json={"text": "News"}).status_code == 201
    [mail] = board_mail(storage, ana_account.id)
    assert mail.sent_at is None


def test_a_reply_stands_and_is_told_when_its_mail_fails(app, local, monkeypatch, caplog):
    def broken(*args, **kwargs):
        raise KeyError("email.board.subject")

    monkeypatch.setattr(board_routes.board_mail, "notify", broken)
    zone = make_zone(local)
    topic, _ = start(local, zone)
    answer = local.post(f"/api/board/topics/{topic}/posts", json={"text": "News"})
    assert answer.status_code == 201 and answer.json()["post"]["text"] == "News"
    assert ({"zone_id": zone, "topic_id": topic}, zone) in board_events(app)
    assert "board mail for" in caplog.text
    assert local.get(f"/api/board/topics/{topic}").json()["topic"]["posts"] == 2
