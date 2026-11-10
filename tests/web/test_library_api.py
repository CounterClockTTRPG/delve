"""The library's routes (cloud storage plan Task 9): browse, download, publish and delete, for organisers, by the
library's right. The library is a local folder under `tmp_path`, set as the owner sets it or with a right played by
`LocalStore`; never a real call."""

import asyncio
import json

import pytest

from delve.cloud import library
from delve.cloud.connections import install_id
from delve.cloud.store import LocalStore, StoreError
from delve.config import Config
from delve.domain.modules import ModuleMap
from delve.storage import open_storage
from tests.cloud.test_bundles import CRYPT, HIDDEN
from tests.web.conftest import log_in, make_account
from tests.web.test_connections_api import seat_client  # noqa: F401 — a fixture
from tests.web.test_preferences_api import published


@pytest.fixture
def folder(tmp_path):
    path = tmp_path / "library"
    path.mkdir()
    return path


def set_library(app, folder, right):
    """The library as a store that can do just `right`, as the owner's Test would have found it."""
    store = LocalStore(folder, read_only=right == "read", create_only=right == "publish")
    app.state.stores.library = store
    app.state.stores.library_right = right
    return store


def crypt(storage, title="The Crypt"):
    module = storage.modules.create(title, {"summary": "A crypt under the chapel."})
    return storage.modules.put_map(module.id, ModuleMap("crypt", "map", CRYPT, is_default=True))


def delete(client, path):
    return client.request("DELETE", path, json={})


def test_the_owner_sets_a_library_then_publishes_lists_and_downloads(local, app, storage, config, folder):
    assert local.put("/api/storage/library", json={"provider": "local", "root": str(folder)}).status_code == 200
    module = crypt(storage)
    response = local.post(f"/api/modules/{module.id}/publish", json={"author": "Raf"})
    assert response.status_code == 200, response.text
    entry = response.json()
    assert (entry["version"], entry["author"], entry["title"]) == (1, "Raf", "The Crypt")
    assert entry["publisher"] == install_id(config.data_dir)

    listing = local.get("/api/library").json()
    assert listing == {
        "right": "manage",
        "entries": [{**entry, "local": {"module_id": module.id, "origin": "published", "version": 1}}],
        "warnings": [],
    }

    downloaded = local.post("/api/library/download", json={"key": entry["key"]})
    assert downloaded.status_code == 200, downloaded.text
    assert downloaded.json()["title"] == "The Crypt" and downloaded.json()["id"] != module.id
    copy = storage.modules.get(downloaded.json()["id"])
    assert (copy.library_key, copy.library_version, copy.library_origin) == (entry["key"], 1, "downloaded")


def test_publish_and_download_publish_modules(local, app, storage, folder):
    set_library(app, folder, "publish")
    module = crypt(storage)
    key = local.post(f"/api/modules/{module.id}/publish", json={}).json()["key"]
    copy = local.post("/api/library/download", json={"key": key}).json()
    seen = [(event.type, event.data) for event in published(app)]
    assert ("modules", {"id": module.id}) in seen and ("modules", {"id": copy["id"]}) in seen


def test_the_author_is_the_accounts_display_name(lan, app, storage, folder):
    set_library(app, folder, "publish")
    make_account(storage, "mira", organiser=True)
    log_in(lan, "mira")
    module = crypt(storage)
    response = lan.post(f"/api/modules/{module.id}/publish", json={})
    assert response.status_code == 200, response.text
    assert response.json()["author"] == "mira"


def test_without_a_name_the_author_is_the_modules_then_delve_never_the_machines(local, app, storage, folder,
                                                                                monkeypatch):
    import socket

    monkeypatch.setattr(socket, "gethostname", lambda: "raf-laptop.home")
    set_library(app, folder, "publish")
    module = crypt(storage)
    response = local.post(f"/api/modules/{module.id}/publish", json={})
    assert response.status_code == 200, response.text
    assert response.json()["author"] == "Delve", "the fixed word, never the host name"

    other = crypt(storage, "The Vault")
    storage.modules.set_library(other.id, key="lib_000000000000", version=1, hash="0" * 64, origin="downloaded",
                                author="Ana")
    response = local.post(f"/api/modules/{other.id}/publish", json={})
    assert response.status_code == 200, response.text
    assert response.json()["author"] == "Ana", "the module's library author"
    assert "raf-laptop" not in json.dumps(local.get("/api/library").json())


def test_a_read_right_is_403_and_nothing_is_written(local, app, storage, folder):
    set_library(app, folder, "read")
    module = crypt(storage)
    response = local.post(f"/api/modules/{module.id}/publish", json={})
    assert response.status_code == 403
    assert "read only" in response.json()["error"]
    assert list(folder.iterdir()) == []
    assert local.get("/api/library").json() == {"right": "read", "entries": [], "warnings": []}


def test_an_unchanged_module_is_409_up_to_date(local, app, storage, folder):
    set_library(app, folder, "publish")
    module = crypt(storage)
    assert local.post(f"/api/modules/{module.id}/publish", json={}).status_code == 200
    response = local.post(f"/api/modules/{module.id}/publish", json={})
    assert response.status_code == 409
    assert response.json() == {"error": "This module is up to date with the library."}
    storage.modules.put_map(module.id, ModuleMap("crypt", "map", CRYPT + HIDDEN, is_default=True))
    assert local.post(f"/api/modules/{module.id}/publish", json={}).json()["version"] == 2


@pytest.mark.parametrize(
    "body", [{"author": ""}, {"author": 3}, {"author": "x" * 101}, {"other": 1}, []], ids=str
)
def test_a_bad_publish_body_is_422(local, app, storage, folder, body):
    set_library(app, folder, "publish")
    module = crypt(storage)
    assert local.post(f"/api/modules/{module.id}/publish", json=body).status_code == 422
    assert list(folder.iterdir()) == []


def test_publishing_an_unknown_module_is_404(local, app, folder):
    set_library(app, folder, "publish")
    assert local.post("/api/modules/mod_nope/publish", json={}).status_code == 404


def test_a_malformed_entry_is_a_warning_not_a_500(local, app, storage, folder):
    """Review Focus 5, through the route: the tab still lists what it can read."""
    set_library(app, folder, "publish")
    good = local.post(f"/api/modules/{crypt(storage).id}/publish", json={}).json()
    (folder / "lib_0000deadbeef" / "v1").mkdir(parents=True)
    (folder / "lib_0000deadbeef" / "v1" / "entry.json").write_text(json.dumps({"format": 99}))
    response = local.get("/api/library")
    assert response.status_code == 200
    answer = response.json()
    assert [entry["key"] for entry in answer["entries"]] == [good["key"]]
    assert len(answer["warnings"]) == 1 and "lib_0000deadbeef" in answer["warnings"][0]


def test_downloading_an_unknown_entry_is_404(local, app, storage, folder):
    set_library(app, folder, "read")
    for key in ("lib_000000000000", "../etc"):
        response = local.post("/api/library/download", json={"key": key})
        assert response.status_code == 404, key
    assert storage.modules.list() == []


def test_delete_needs_manage(local, app, storage, folder):
    set_library(app, folder, "publish")
    key = local.post(f"/api/modules/{crypt(storage).id}/publish", json={}).json()["key"]
    response = delete(local, f"/api/library/{key}")
    assert response.status_code == 403
    assert response.json() == {"error": "Only the library's managers can delete from it."}
    assert len(local.get("/api/library").json()["entries"]) == 1

    set_library(app, folder, "manage")
    assert delete(local, f"/api/library/{key}?version=2").status_code == 404
    assert delete(local, f"/api/library/{key}?version=1").status_code == 204
    assert local.get("/api/library").json()["entries"] == []
    assert [path.name for path in (folder / key / "v1").iterdir()] == ["deleted"], "the tombstone stays"
    assert delete(local, f"/api/library/{key}?version=1").status_code == 404
    assert delete(local, f"/api/library/{key}").status_code == 404


def test_a_failing_store_answers_its_own_words(local, app, storage, folder):
    class Down(LocalStore):
        async def list(self, prefix=""):
            raise StoreError("The store didn't answer.")

    app.state.stores.library = Down(folder)
    app.state.stores.library_right = "manage"
    response = local.get("/api/library")
    assert response.status_code == 502
    assert response.json() == {"error": "The store didn't answer."}


ROUTES = [
    ("GET", "/api/library", None),
    ("POST", "/api/library/download", {"key": "lib_000000000000"}),
    ("POST", "/api/modules/{module}/publish", {}),
    ("DELETE", "/api/library/lib_000000000000", {}),
    ("POST", "/api/modules/{module}/library-update", {"keep_copy": False}),
]


@pytest.mark.parametrize(("method", "path", "body"), ROUTES)
def test_the_library_answers_409_without_a_store(local, storage, method, path, body):
    path = path.format(module=crypt(storage).id)
    response = local.request(method, path, json=body)
    assert response.status_code == 409, path
    assert response.json() == {"error": "No library store is set up."}


@pytest.mark.parametrize(("method", "path", "body"), ROUTES)
def test_a_seat_gets_403(seat_client, app, storage, folder, method, path, body):  # noqa: F811
    client = seat_client(role="player")
    set_library(app, folder, "manage")
    path = path.format(module=crypt(storage).id)
    response = client.request(method, path, json=body)
    assert response.status_code == 403, path
    assert list(folder.iterdir()) == []


@pytest.mark.parametrize(("method", "path", "body"), ROUTES)
def test_a_player_account_gets_403(lan, app, storage, folder, method, path, body):
    set_library(app, folder, "manage")
    make_account(storage)
    log_in(lan)
    response = lan.request(method, path.format(module=crypt(storage).id), json=body)
    assert response.status_code == 403, path


@pytest.mark.parametrize(("method", "path", "body"), ROUTES)
def test_nobody_gets_401(lan, storage, method, path, body):
    assert lan.request(method, path.format(module=crypt(storage).id), json=body).status_code == 401, path


def test_an_organiser_seat_may_publish(seat_client, app, storage, folder):  # noqa: F811
    client = seat_client(organiser=True)
    set_library(app, folder, "publish")
    response = client.post(f"/api/modules/{crypt(storage).id}/publish", json={})
    assert response.status_code == 200, response.text
    assert response.json()["author"] == "Ana", "the seat's name"


# Updates from the library (Task 10).

FRIEND = "ins_ba9876543210"


@pytest.fixture
def friend(tmp_path):
    opened = open_storage(Config(data_dir=tmp_path / "friend"))
    yield opened
    opened.close()


def friend_publishes(friend, store, module):
    return asyncio.run(library.publish(friend, store, "publish", module.id, author="Ana", install=FRIEND))


def downloaded_with_a_newer_version(local, app, friend, folder):
    """Ana's crypt downloaded here at v1, then Ana publishing v2 with the hidden room; the module's id here."""
    store = set_library(app, folder, "manage")
    theirs = crypt(friend)
    key = friend_publishes(friend, store, theirs).key
    module_id = local.post("/api/library/download", json={"key": key}).json()["id"]
    friend.modules.put_map(theirs.id, ModuleMap("crypt", "map", CRYPT + HIDDEN, is_default=True))
    friend_publishes(friend, store, theirs)
    return module_id


def test_a_module_not_from_the_library_has_library_null(local, app, storage, folder):
    set_library(app, folder, "manage")
    module = crypt(storage)
    assert local.get(f"/api/modules/{module.id}").json()["library"] is None
    assert [m["library"] for m in local.get("/api/modules").json()] == [None]


def test_a_newer_version_shows_on_the_module_once_the_library_is_read(local, app, storage, friend, folder):
    module_id = downloaded_with_a_newer_version(local, app, friend, folder)
    key = storage.modules.get(module_id).library_key
    shown = {"key": key, "version": 1, "origin": "downloaded", "newer": None, "edited": False}
    assert local.get(f"/api/modules/{module_id}").json()["library"] == shown

    assert local.get("/api/library").status_code == 200
    assert app.state.stores.updates == {module_id: 2}
    assert ("modules", {"id": module_id}) in [(event.type, event.data) for event in published(app)]
    assert local.get(f"/api/modules/{module_id}").json()["library"] == {**shown, "newer": 2}
    assert [m["library"] for m in local.get("/api/modules").json()] == [{**shown, "newer": 2}]

    storage.modules.put_map(module_id, ModuleMap("vault", "map", CRYPT, is_default=False))
    assert local.get(f"/api/modules/{module_id}").json()["library"]["edited"] is True


def test_a_check_keeps_the_updates_on_the_stores(app, storage, friend, folder, local):
    module_id = downloaded_with_a_newer_version(local, app, friend, folder)
    asyncio.run(library.refresh_updates(app.state))
    assert app.state.stores.updates == {module_id: 2}


def test_update_takes_the_newer_version_and_campaigns_stay_on_theirs(local, app, storage, friend, folder):
    module_id = downloaded_with_a_newer_version(local, app, friend, folder)
    pinned = storage.revisions.snapshot(module_id)
    campaign = storage.campaigns.create("Tuesday", module_id, pinned.number, ruleset="osric", setting="greyhawk")
    local.get("/api/library")

    response = local.post(f"/api/modules/{module_id}/library-update", json={"keep_copy": True})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == module_id and body["head_revision"] == pinned.number + 1
    assert body["library"]["version"] == 2 and body["library"]["newer"] is None
    assert storage.campaigns.get(campaign.id).revision == pinned.number
    assert app.state.stores.updates == {}
    titles = sorted(m["title"] for m in local.get("/api/modules").json())
    assert titles == ["The Crypt", "The Crypt (my version)"]
    again = local.post(f"/api/modules/{module_id}/library-update", json={"keep_copy": False})
    assert again.status_code == 409
    assert again.json() == {"error": "This module is at the library's newest version."}


@pytest.mark.parametrize("body", [{}, {"keep_copy": "yes"}, {"keep_copy": True, "more": 1}])
def test_a_bad_update_body_is_422(local, app, storage, friend, folder, body):
    module_id = downloaded_with_a_newer_version(local, app, friend, folder)
    assert local.post(f"/api/modules/{module_id}/library-update", json=body).status_code == 422


def test_updating_a_module_not_from_the_library_is_409(local, app, storage, folder):
    set_library(app, folder, "manage")
    response = local.post(f"/api/modules/{crypt(storage).id}/library-update", json={"keep_copy": False})
    assert response.status_code == 409
    assert response.json() == {"error": "This module didn't come from the library."}
    assert local.post("/api/modules/mod_missing/library-update", json={"keep_copy": False}).status_code == 404
