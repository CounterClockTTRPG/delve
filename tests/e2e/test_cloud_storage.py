"""Cloud storage end to end (cloud storage plan Task 13): three installs, each its own data dir and database, behind
its own API. A and B share one library, a local folder; A backs up to another.

A publishes the crypt and B downloads it, then plays a campaign on it. A publishes a second version: B sees the
update and takes it, and B's campaign stays on the revision it pinned. A backs up, and a fresh install C, pointed at
A's backup store, restores A's campaign (its module comes along) and plays a beat on it with the fake DM.

The stores are `LocalStore` folders under `tmp_path`: no call leaves the machine.
"""

import time
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager

import pytest
from fastapi.testclient import TestClient

from delve.config import Config
from delve.dm.fake import FAKE_DM_CAPABILITIES, FakeDM
from delve.dm.provider import TextDelta
from delve.domain.backends import Registry
from delve.storage import open_storage
from delve.web.app import create_app
from tests.cloud.test_bundles import CRYPT, HIDDEN
from tests.web.conftest import BASE_URL, INDEX_HTML, make_registries

REPLY = "Dust settles on the restored crypt."


@contextmanager
def install(tmp_path, name: str, dm: FakeDM | None = None) -> Iterator[TestClient]:
    """An install of its own: data dir, database and app, and the owner's browser on this machine."""
    storage = open_storage(Config(data_dir=tmp_path / name / "data"))
    static = tmp_path / name / "static"
    static.mkdir(parents=True)
    (static / "index.html").write_text(INDEX_HTML)
    registries = make_registries()
    if dm is not None:
        registries.dm = Registry()
        registries.dm.register(FAKE_DM_CAPABILITIES, lambda: dm)
    app = create_app(Config(data_dir=tmp_path / name / "data"), storage, registries, static_dir=static)
    try:
        with TestClient(app, base_url=BASE_URL, client=("127.0.0.1", 50000)) as client:
            yield client
    finally:
        storage.close()


def ok(response, status: int = 200):
    assert response.status_code == status, response.text
    return response.json()


def set_store(client: TestClient, kind: str, root) -> dict:
    root.mkdir(exist_ok=True)
    return ok(client.put(f"/api/storage/{kind}", json={"provider": "local", "root": str(root)}))


def crypt_module(client: TestClient, title: str = "The Crypt") -> str:
    module = ok(client.post("/api/modules", json={"title": title}), 201)
    ok(client.put(f"/api/modules/{module['id']}/maps/map", json={"source": CRYPT, "new_name": "crypt"}))
    return module["id"]


def campaign(client: TestClient, module_id: str, name: str = "Tuesday") -> dict:
    return ok(client.post("/api/campaigns", json={"name": name, "module_id": module_id}), 201)


def until(test, what: str, timeout: float = 10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if result := test():
            return result
        time.sleep(0.02)
    raise AssertionError(f"waited for {what}")


@pytest.fixture
def dm():
    return FakeDM([[TextDelta(REPLY)]])


def test_two_installs_share_a_module_and_one_restores_from_its_backup(tmp_path, dm):
    library, backups = tmp_path / "library", tmp_path / "backups"
    with ExitStack() as stack:
        a = stack.enter_context(install(tmp_path, "a"))
        b = stack.enter_context(install(tmp_path, "b"))
        assert set_store(a, "library", library)["right"] == "manage"
        assert set_store(b, "library", library)["right"] == "manage"

        # A publishes the crypt; B finds it in the library and downloads it.
        module_a = crypt_module(a)
        v1 = ok(a.post(f"/api/modules/{module_a}/publish", json={"author": "Raf"}))
        assert (v1["version"], v1["title"], v1["author"]) == (1, "The Crypt", "Raf")
        listed = ok(b.get("/api/library"))
        assert [(entry["key"], entry["version"], entry["local"]) for entry in listed["entries"]] == [
            (v1["key"], 1, None)
        ]
        downloaded = ok(b.post("/api/library/download", json={"key": v1["key"]}))
        module_b = downloaded["id"]
        assert downloaded["library"] == {
            "key": v1["key"], "version": 1, "origin": "downloaded", "newer": None, "edited": False
        }  # fmt: skip
        tuesday_b = campaign(b, module_b)
        pinned = tuesday_b["revision"]

        # A publishes a second version; B sees it on the module and takes it.
        ok(a.put(f"/api/modules/{module_a}/maps/crypt", json={"source": CRYPT + HIDDEN}))
        v2 = ok(a.post(f"/api/modules/{module_a}/publish", json={}))
        assert (v2["key"], v2["version"]) == (v1["key"], 2)
        ok(b.get("/api/library"))
        assert ok(b.get(f"/api/modules/{module_b}"))["library"]["newer"] == 2
        updated = ok(b.post(f"/api/modules/{module_b}/library-update", json={"keep_copy": False}))
        assert updated["library"] == {
            "key": v1["key"], "version": 2, "origin": "downloaded", "newer": None, "edited": False
        }  # fmt: skip
        assert "hidden_crypt" in ok(b.get(f"/api/modules/{module_b}/maps/crypt"))["source"]
        assert ok(b.get(f"/api/campaigns/{tuesday_b['id']}"))["revision"] == pinned, "B's campaign stays on v1"

        # A backs up, with a campaign on its crypt.
        tuesday_a = campaign(a, module_a, "Thursday")
        set_store(a, "backup", backups)
        ok(a.post("/api/storage/backup", json={}), 202)

        def last_run():
            schedule = ok(a.get("/api/storage"))["schedule"]
            return not schedule["running"] and schedule["last_run"]

        run = until(last_run, "A's backup")
        assert run["status"] == "ok" and run["failed"] == []
        assert {"The Crypt", "Thursday"} <= set(run["uploaded"])
        install_a = ok(a.get("/api/storage"))["install_id"]

    # A fresh install C restores A's campaign from A's backup, and plays a beat on it.
    with install(tmp_path, "c", dm) as c:
        set_store(c, "backup", backups)
        assert [entry["install_id"] for entry in ok(c.get("/api/storage/backups"))] == [install_a]
        items = ok(c.get(f"/api/storage/backups/{install_a}"))
        assert {(item["kind"], item["item_id"]): item["exists_here"] for item in items}[
            ("campaign", tuesday_a["id"])
        ] is False
        results = ok(
            c.post(
                "/api/storage/restore",
                json={"install_id": install_a, "items": [{"kind": "campaign", "item_id": tuesday_a["id"]}]},
            )
        )
        assert all(result["ok"] for result in results), results
        assert [(r["kind"], r["item_id"], r.get("added", False)) for r in results] == [
            ("module", module_a, True),
            ("campaign", tuesday_a["id"], False),
        ]
        restored = ok(c.get(f"/api/campaigns/{tuesday_a['id']}"))
        assert (restored["module_id"], restored["revision"]) == (module_a, tuesday_a["revision"])

        play = f"/api/campaigns/{tuesday_a['id']}"
        ok(c.post(f"{play}/act", json={"text": "We open the crypt."}), 202)
        until(lambda: ok(c.get(f"{play}/play/state"))["beat"] is None, "the beat's end")
        story = ok(c.get(f"{play}/story"))["entries"]
        assert any(REPLY in str(entry["payload"]) for entry in story), story
        assert dm.sent and "We open the crypt." in dm.sent[-1]
