"""The novels API (novelization Task 5): every route is the owner's alone, reads too (owner decision 7). An organiser
seat and a player seat get 403, nobody 401; the owner, on this machine or with the token, is let through.

The writer is `FakeDM(side_handler=…)` with the jobs tests' fake novelist.
"""

import asyncio
import io
import time
import zipfile
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from delve.conversions import runner
from delve.dm.fake import FAKE_DM_CAPABILITIES, FakeDM
from delve.domain.backends import Registry
from delve.domain.novels import Chapter, Novel
from delve.web.seats import SEAT_COOKIE, new_seat_token, token_hash
from tests.novels.test_jobs import Writer
from tests.novels.test_material import played  # noqa: F401 (a fixture)
from tests.web.conftest import BASE_URL, make_registries
from tests.web.test_campaigns_api import crypt_module

ONLY_THE_OWNER = {"error": "Only the install's owner can do this."}
NOVEL_FIELDS = {
    "id",
    "title",
    "campaign_id",
    "module_id",
    "revision",
    "sessions",
    "length",
    "tone",
    "custom_tone",
    "language",
    "instructions",
    "chapters",
    "status",
    "error",
    "conversion_id",
    "cost_usd",
    "created_at",
    "updated_at",
}


@pytest.fixture
def writer():
    return Writer(3)


@pytest.fixture
def registries(writer):
    dm = Registry()
    dm.register(FAKE_DM_CAPABILITIES, lambda: FakeDM([], side_handler=writer))
    return replace(make_registries(), dm=dm)


def ended(local, id: str) -> dict:
    """The novel once its job has ended."""
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        novel = local.get(f"/api/novels/{id}").json()
        if novel["status"] != "writing":
            return novel
        time.sleep(0.02)
    raise AssertionError(f"novel {id} still writing")


def novelize(local, played, **choices):  # noqa: F811
    return local.post("/api/novels", json={"source": "campaign", "id": played.id, **choices})


# ----- writing and reading -----


def test_a_campaign_becomes_a_novel(local, played):  # noqa: F811
    response = novelize(local, played, length="short-story", tone="heroic", instructions="Mira tells it.")

    assert response.status_code == 202, response.text
    started = response.json()
    assert set(started) == NOVEL_FIELDS
    assert started["status"] == "writing" and started["conversion_id"]
    assert (started["campaign_id"], started["module_id"], started["sessions"]) == (played.id, None, None)

    novel = ended(local, started["id"])
    assert novel["status"] == "done" and novel["title"] == "The Bell Below"
    assert novel["chapters"][0] == {
        "title": "Part 1",
        "summary": "SUMMARY-1",
        "text": "CHAPTER-1: the bell tolled below.",
    }
    job = local.get(f"/api/conversions/{started['conversion_id']}").json()
    assert (job["kind"], job["title"], job["status"]) == ("novel", "Novel: Tuesday", "done")
    assert job["target"] == {"novel_id": started["id"]}


def test_the_list_has_no_chapter_text(local, played):  # noqa: F811
    first = ended(local, novelize(local, played).json()["id"])
    second = ended(local, novelize(local, played, tone="grimdark").json()["id"])

    listed = local.get("/api/novels", params={"campaign_id": played.id})

    assert listed.status_code == 200
    assert [n["id"] for n in listed.json()] == [second["id"], first["id"]], "newest first"
    assert listed.json()[0]["chapters"] == [
        {"title": "Part 1", "summary": "SUMMARY-1 SUMMARY-2 SUMMARY-3", "written": True}
    ]
    assert "CHAPTER-" not in listed.text
    assert local.get("/api/novels", params={"module_id": played.module_id}).json() == []


def test_the_list_needs_one_source(local, played):  # noqa: F811
    assert local.get("/api/novels").status_code == 422
    both = {"campaign_id": played.id, "module_id": played.module_id}
    assert local.get("/api/novels", params=both).status_code == 422
    assert local.get("/api/novels", params={"campaign_id": "cmp_missing"}).status_code == 404
    assert local.get("/api/novels", params={"module_id": "mod_missing"}).status_code == 404


def test_a_module_becomes_a_novel_at_its_latest_revision(local, played):  # noqa: F811
    response = local.post("/api/novels", json={"source": "module", "id": played.module_id})
    assert response.status_code == 202, response.text
    novel = ended(local, response.json()["id"])
    assert novel["status"] == "done" and novel["revision"] == played.revision
    listed = local.get("/api/novels", params={"module_id": played.module_id}).json()
    assert [n["id"] for n in listed] == [novel["id"]]


def test_a_novel_is_renamed(local, played):  # noqa: F811
    novel = ended(local, novelize(local, played).json()["id"])
    renamed = local.patch(f"/api/novels/{novel['id']}", json={"title": "  The Ossuary  "})
    assert renamed.status_code == 200 and renamed.json()["title"] == "The Ossuary"
    assert local.get(f"/api/novels/{novel['id']}").json()["title"] == "The Ossuary"
    for body in ({"title": " "}, {"title": "x" * 201}, {}, {"title": 3}):
        assert local.patch(f"/api/novels/{novel['id']}", json=body).status_code == 422, body


def test_a_novel_is_deleted_but_not_while_written(local, app, played, writer):  # noqa: F811
    gate = asyncio.Event()
    dm = app.state.registries.dm.get("fake")
    real = dm.side_call

    async def held(prompt, choice, **kw):
        await gate.wait()
        return await real(prompt, choice, **kw)

    dm.side_call = held
    started = novelize(local, played).json()
    refused = local.request("DELETE", f"/api/novels/{started['id']}", json={})
    assert refused.status_code == 409 and "error" in refused.json()
    local.portal.call(gate.set)
    ended(local, started["id"])

    assert local.request("DELETE", f"/api/novels/{started['id']}", json={}).status_code == 204
    assert local.get(f"/api/novels/{started['id']}").status_code == 404
    assert local.request("DELETE", f"/api/novels/{started['id']}", json={}).status_code == 404


def test_cancel_and_continue(local, app, played, writer):  # noqa: F811
    gate = asyncio.Event()
    dm = app.state.registries.dm.get("fake")
    real = dm.side_call

    async def held(prompt, choice, **kw):
        if "Now write chapter 2" in prompt:
            await gate.wait()
        return await real(prompt, choice, **kw)

    dm.side_call = held
    started = novelize(local, played, length="short-story").json()
    deadline = time.monotonic() + 10
    while local.get(f"/api/novels/{started['id']}").json()["chapters"][:1] == [] or not any(
        c["text"] for c in local.get(f"/api/novels/{started['id']}").json()["chapters"]
    ):
        assert time.monotonic() < deadline
        time.sleep(0.02)

    cancelled = local.post(f"/api/novels/{started['id']}/cancel", json={})
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert [c["text"] is not None for c in cancelled.json()["chapters"]] == [True, False, False]
    assert local.post(f"/api/novels/{started['id']}/cancel", json={}).json()["status"] == "cancelled"

    dm.side_call = real
    writer.chapters.clear()
    continued = local.post(f"/api/novels/{started['id']}/continue", json={})
    assert continued.status_code == 202 and continued.json()["status"] == "writing"
    assert continued.json()["conversion_id"] != started["conversion_id"]
    done = ended(local, started["id"])
    assert done["status"] == "done" and [n for n, _ in writer.chapters] == [2, 3]
    again = local.post(f"/api/novels/{started['id']}/continue", json={})
    assert again.status_code == 409 and "error" in again.json()


def test_one_job_at_a_time(local, app, played):  # noqa: F811
    gate = asyncio.Event()
    dm = app.state.registries.dm.get("fake")
    real = dm.side_call

    async def held(prompt, choice, **kw):
        await gate.wait()
        return await real(prompt, choice, **kw)

    dm.side_call = held
    first = novelize(local, played).json()
    second = novelize(local, played)
    assert second.status_code == 409
    assert second.json()["error"] == "A conversion is running."
    assert second.json()["conversion"]["id"] == first["conversion_id"]
    assert len(local.get("/api/novels", params={"campaign_id": played.id}).json()) == 1
    local.portal.call(gate.set)
    assert ended(local, first["id"])["status"] == "done"


@pytest.mark.parametrize(
    "choices",
    [
        {"length": "saga"},
        {"tone": "whimsical"},
        {"tone": "custom"},
        {"language": "es"},
        {"sessions": [1]},
        {"sessions": "all"},
        {"source": "world"},
        {"revision": 1},
        {"unknown": True},
    ],
)
def test_a_bad_request_is_422(local, played, choices):  # noqa: F811
    response = novelize(local, played, **choices)
    assert response.status_code == 422, response.text
    assert "error" in response.json()
    assert local.get("/api/novels", params={"campaign_id": played.id}).json() == []


@pytest.mark.parametrize("sessions", [[3, 2], [0, 5], [1, 5]])
def test_a_bad_range_is_422_with_a_hint(local, played, sessions):  # noqa: F811
    response = novelize(local, played, sessions=sessions)
    assert response.status_code == 422
    assert response.json()["error"] == "That range of sessions can't be written."
    assert response.json()["hint"]


def test_a_range_is_kept(local, played):  # noqa: F811
    response = novelize(local, played, sessions=[1, 2])
    assert response.status_code == 202 and response.json()["sessions"] == [1, 2]


def test_an_unknown_source_or_novel_is_404(local, played):  # noqa: F811
    assert local.post("/api/novels", json={"source": "campaign", "id": "cmp_missing"}).status_code == 404
    assert local.post("/api/novels", json={"source": "module", "id": "mod_missing"}).status_code == 404
    for method, path in [
        ("GET", "/api/novels/nov_missing"),
        ("PATCH", "/api/novels/nov_missing"),
        ("DELETE", "/api/novels/nov_missing"),
        ("POST", "/api/novels/nov_missing/continue"),
        ("POST", "/api/novels/nov_missing/cancel"),
    ]:
        body = {"title": "x"} if method == "PATCH" else {}
        assert local.request(method, path, json=body).status_code == 404, path


def test_a_write_needs_json(local, played):  # noqa: F811
    assert local.post("/api/novels", content=b"{}").status_code == 415


# ----- the owner only -----


@pytest.fixture
def stored(storage, played):  # noqa: F811
    """A written novel of the campaign, its chapter planted."""
    chapters = [Chapter("Part 1", "SECRET-XYZZY summary", "SECRET-XYZZY: the keeper is a ghoul.")]
    return storage.novels.create(
        Novel("", "SECRET-XYZZY title", campaign_id=played.id, chapters=chapters, status="done")
    )


def routes(novel: Novel, played) -> list[tuple[str, str, dict | None]]:  # noqa: F811
    return [
        ("POST", "/api/novels", {"source": "campaign", "id": played.id}),
        ("GET", f"/api/novels?campaign_id={played.id}", None),
        ("GET", f"/api/novels?module_id={played.module_id}", None),
        ("GET", f"/api/novels/{novel.id}", None),
        ("PATCH", f"/api/novels/{novel.id}", {"title": "Mine now"}),
        ("DELETE", f"/api/novels/{novel.id}", {}),
        ("POST", f"/api/novels/{novel.id}/continue", {}),
        ("POST", f"/api/novels/{novel.id}/cancel", {}),
    ]


ROUTE_COUNT = 8


@pytest.fixture
def seat_client(app, storage, played):  # noqa: F811
    """A browser on the LAN holding a seat's token at the campaign's table."""
    clients = []

    def make(role="host", *, organiser=False):
        token = new_seat_token()
        storage.seats.create(played.id, "Ana", "en", role, organiser=organiser, token_hash=token_hash(token))
        client = TestClient(app, base_url=BASE_URL)
        client.__enter__()
        client.cookies.set(SEAT_COOKIE, token)
        clients.append(client)
        return client

    yield make
    for client in clients:
        client.__exit__(None, None, None)


@pytest.mark.parametrize("index", range(ROUTE_COUNT))
@pytest.mark.parametrize(("role", "organiser"), [("host", True), ("cohost", True), ("player", False)])
def test_a_seat_gets_403_on_every_route(seat_client, storage, stored, played, index, role, organiser):  # noqa: F811
    client = seat_client(role, organiser=organiser)
    if organiser:
        assert client.get("/api/preferences").status_code == 200, "the seat is an organiser"
    method, path, body = routes(stored, played)[index]
    response = client.request(method, path, json=body)
    assert response.status_code == 403, path
    assert response.json() == ONLY_THE_OWNER
    assert storage.novels.get(stored.id) == stored, "nothing changed"
    assert len(storage.novels.for_campaign(played.id)) == 1
    assert storage.conversions.list() == []


@pytest.mark.parametrize("index", range(ROUTE_COUNT))
def test_nobody_gets_401(lan, stored, played, index):  # noqa: F811
    method, path, body = routes(stored, played)[index]
    assert lan.request(method, path, json=body).status_code == 401, path


def test_the_owner_token_reads_a_novel_from_the_lan(lan, token, stored):
    lan.headers["Authorization"] = f"Bearer {token}"
    response = lan.get(f"/api/novels/{stored.id}")
    assert response.status_code == 200 and response.json()["chapters"][0]["text"].startswith("SECRET-XYZZY")


def test_a_novel_goes_with_its_campaign(local, storage, stored, played):  # noqa: F811
    assert local.request("DELETE", f"/api/campaigns/{played.id}", json={}).status_code == 204
    assert storage.novels.get(stored.id) is None


def test_a_novel_is_in_no_export(local, storage):
    module = crypt_module(local)
    chapters = [Chapter("Part 1", "SECRET-XYZZY summary", "SECRET-XYZZY: the keeper is a ghoul.")]
    storage.novels.create(Novel("", "SECRET-XYZZY title", module_id=module["id"], chapters=chapters, status="done"))
    exported = local.get(f"/api/modules/{module['id']}/export.dscn")
    assert exported.status_code == 200, exported.text
    with zipfile.ZipFile(io.BytesIO(exported.content)) as bundle:
        assert all(b"SECRET-XYZZY" not in bundle.read(name) for name in bundle.namelist())


def test_close_orphan_novels_runs_at_startup(config, storage, registries, static_dir, played):  # noqa: F811
    from delve.web.app import create_app

    left = storage.conversions.create("novel", "Novel: Tuesday", "ready", target={})
    novel = storage.novels.create(
        Novel("", "Tuesday", campaign_id=played.id, chapters=[Chapter("Part 1", "s", "text"), Chapter("Part 2", "s")])
    )
    storage.novels.save(replace(novel, conversion_id=left.id))
    with TestClient(create_app(config, storage, registries, static_dir=static_dir), base_url=BASE_URL):
        assert storage.conversions.get(left.id).status == "failed"
        closed = storage.novels.get(novel.id)
        assert (closed.status, closed.error) == ("failed", "Delve stopped while writing.")
        assert [c.text for c in closed.chapters] == ["text", None]


def test_the_job_kind_is_the_runners(storage):
    assert runner.STEPS["novel"] == (("condensing",), ("outlining",), ("writing",))
