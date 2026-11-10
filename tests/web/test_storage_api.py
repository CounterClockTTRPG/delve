"""Storage (cloud storage plan Task 4): the owner's backup store, the shared library and the backup time, owner only.

A credential goes into the data dir's files and never comes back out: not in an answer, a log, an event or an error,
a provider's error page that echoes it included (Review Focus 2). The stores are local folders under `tmp_path`, or
the `httpx.MockTransport` fakes of Azure and S3 from `tests/cloud`; never a real call."""

import asyncio
import json
import logging
import stat
import threading
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from delve.cloud.backup import run_backup
from delve.cloud.connections import StoreConfig, install_id, load_store, same_place, save_store
from delve.cloud.store import LocalStore, StoreError
from delve.config import Config
from delve.domain.modules import ModuleMap
from delve.storage import open_storage
from tests.cloud.test_azure import SIG, FakeAzure, sas_url
from tests.cloud.test_bundles import crypt_campaign, crypt_module
from tests.cloud.test_s3 import BUCKET, ENDPOINT, KEY_ID, SECRET, FakeS3
from tests.storage.test_blob_prune import put_old
from tests.web.conftest import BASE_URL, log_in, make_account
from tests.web.test_connections_api import seat_client  # noqa: F401 — a fixture
from tests.web.test_preferences_api import published

RAW_SIG = "SECRET-SIG+xyzzy="


@pytest.fixture(autouse=True)
def every_log(caplog):
    caplog.set_level(logging.DEBUG)
    return caplog


@pytest.fixture(autouse=True)
def nothing_answers(app):
    """No test reaches a socket: until a fake plays it, the cloud is down."""

    def down(request):
        raise httpx.ConnectError(f"down: {request.url}", request=request)

    app.state.stores.transport = httpx.MockTransport(down)


def plays(app, fake):
    app.state.stores.transport = httpx.MockTransport(fake.handle if isinstance(fake, FakeS3) else fake)
    return fake


def assert_no_secret(*texts):
    for text in texts:
        assert SIG not in text and RAW_SIG not in text and "sig=" not in text
        assert SECRET not in text


def folder(tmp_path, name="store"):
    path = tmp_path / name
    path.mkdir(exist_ok=True)
    return {"provider": "local", "root": str(path)}


def azure_body(sp="racwdl", **query):
    return {"provider": "azure", "sas_url": sas_url(sp, **query)}


def s3_body(right=None, secret=SECRET):
    body = {"provider": "s3", "endpoint": ENDPOINT, "bucket": BUCKET, "access_key_id": KEY_ID}
    if secret is not None:
        body["secret_access_key"] = secret
    if right is not None:
        body["right"] = right
    return body


def delete(client, path):
    return client.request("DELETE", path, json={})


def test_get_says_nothing_is_set(local, config):
    response = local.get("/api/storage")
    assert response.status_code == 200
    answer = response.json()
    assert answer == {
        "backup": None,
        "library": None,
        "schedule": {"time": "04:00", "last_run": None, "running": False},
        "install_id": answer["install_id"],
    }
    assert answer["install_id"].startswith("ins_")
    assert local.get("/api/storage").json()["install_id"] == answer["install_id"], "made once"


def test_a_local_backup_store_is_saved_and_read_back(local, app, config, tmp_path):
    response = local.put("/api/storage/backup", json=folder(tmp_path))
    assert response.status_code == 200, response.text
    view = {"provider": "local", "label": str(tmp_path / "store"), "secret": "unset", "right": "manage",
            "expires": None, "choice": None}
    assert response.json() == view
    assert local.get("/api/storage").json()["backup"] == view
    path = config.data_dir / "backup-store.json"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert app.state.stores.backup.label == str(tmp_path / "store")
    assert list((tmp_path / "store").iterdir()) == [], "the probe cleaned up"


def test_get_never_answers_a_secret(local, app, config, every_log):
    plays(app, FakeAzure())
    assert local.put("/api/storage/backup", json=azure_body()).status_code == 200
    fake = plays(app, FakeS3())
    library = local.put("/api/storage/library", json=s3_body(right="manage"))
    assert library.status_code == 200, library.text
    response = local.get("/api/storage")
    answer = response.json()
    assert answer["backup"] == {
        "provider": "azure", "label": "https://delveacct.blob.core.windows.net/delve", "secret": "set",
        "right": "manage", "expires": "2026-12-31T00:00:00+00:00", "choice": None,
    }
    assert answer["library"] == {
        "provider": "s3", "label": f"{ENDPOINT}/{BUCKET}", "secret": "set", "right": "manage", "expires": None,
        "choice": "manage",
    }
    assert fake.objects == {}
    texts = [response.text, library.text, local.get("/api/preferences").text]
    texts += [local.post(f"/api/storage/{kind}/test", json={}).text for kind in ("backup", "library")]
    texts += [json.dumps(event.data) for event in published(app)]
    assert_no_secret(*texts, every_log.text)
    assert load_store(config.data_dir, "library").secret_access_key == SECRET, "the file holds it"


def test_a_read_only_backup_store_is_refused_with_the_reason(local, app, config, every_log):
    fake = plays(app, FakeAzure("rl"))
    response = local.put("/api/storage/backup", json=azure_body("rl"))
    assert response.status_code == 422
    assert response.json() == {
        "error": "This credential can read but not create, so backups can't use it. "
        "Make the SAS again with Create (c), Write (w) and Delete (d).",
    }
    assert not (config.data_dir / "backup-store.json").exists()
    assert app.state.stores.backup is None
    plays(app, FakeAzure("rcl"))
    publish_only = local.put("/api/storage/backup", json=azure_body("rcl"))
    assert publish_only.status_code == 422
    assert publish_only.json() == {
        "error": "This credential can create but not overwrite, so backups can't use it. "
        "Make the SAS again with Write (w) and Delete (d).",
    }
    assert fake.blobs == {}
    assert_no_secret(response.text, publish_only.text, every_log.text)


@pytest.mark.parametrize(
    ("allow", "right", "expected"),
    [
        (("list", "get"), None, "read"),
        (("list", "get", "create", "put", "delete"), None, "publish"),
        (("list", "get", "create", "put", "delete"), "publish", "publish"),
        (("list", "get", "create", "put", "delete"), "manage", "manage"),
    ],
)
def test_a_library_store_answers_its_right(local, app, allow, right, expected):
    """An S3 store's right is the probe's, capped at the owner's choice (R2 only tells read from write)."""
    plays(app, FakeS3(allow=allow))
    response = local.put("/api/storage/library", json=s3_body(right=right))
    assert response.status_code == 200, response.text
    assert response.json()["right"] == expected
    assert app.state.stores.library_right == expected
    assert local.get("/api/storage").json()["library"]["right"] == expected


@pytest.mark.parametrize(("sp", "expected"), [("rl", "read"), ("rcl", "publish"), ("racwdl", "manage")])
def test_an_azure_library_answers_the_sas_right(local, app, sp, expected):
    plays(app, FakeAzure(sp))
    response = local.put("/api/storage/library", json=azure_body(sp))
    assert response.status_code == 200, response.text
    assert response.json()["right"] == expected
    test = local.post("/api/storage/library/test", json={}).json()
    assert test["ok"] is True and test["right"] == expected


def test_a_library_that_cannot_list_is_refused(local, app, config):
    plays(app, FakeS3(allow=("get",)))
    response = local.put("/api/storage/library", json=s3_body())
    assert response.status_code == 422
    assert response.json() == {"error": "This credential can't list the library, so Delve can't use it."}
    assert not (config.data_dir / "library-store.json").exists()


def test_an_error_page_echoing_the_credential_never_reaches_an_answer(local, app, config, every_log):
    """Review Focus 2: the provider answers 500 with the request's URL, headers and the secret in its body."""

    def echo(request):
        return httpx.Response(500, text=f"Server busy for {request.url} {dict(request.headers)} {SECRET}")

    plays(app, echo)
    texts = []
    for kind in ("backup", "library"):
        for body in (azure_body(), s3_body()):
            response = local.put(f"/api/storage/{kind}", json=body)
            assert response.status_code == 422
            texts.append(response.text)
    assert json.loads(texts[0]) == {"error": "Azure answered 500."}
    assert json.loads(texts[1]) == {"error": "The S3 store answered 500."}
    assert not (config.data_dir / "backup-store.json").exists()

    fake = plays(app, FakeAzure())
    local.put("/api/storage/library", json=azure_body())
    fake.fail = 500  # its error page quotes the request's URL, SAS and all
    test = local.post("/api/storage/library/test", json={})
    assert test.json() == {"ok": False, "right": None, "message": "Azure answered 500."}
    texts.append(test.text)
    assert_no_secret(*texts, every_log.text)


def test_an_unreachable_store_names_no_credential(local, every_log):
    response = local.put("/api/storage/backup", json=azure_body())
    assert response.status_code == 422
    assert response.json() == {"error": "Azure isn't answering."}
    assert_no_secret(response.text, every_log.text)


@pytest.mark.parametrize(
    "body",
    [
        [],
        {},
        {"provider": "ftp"},
        {"provider": "azure"},
        {"provider": "azure", "sas_url": f"http://delveacct.blob.core.windows.net/delve?sv=1&sig={SIG}"},
        {"provider": "azure", "sas_url": "https://delveacct.blob.core.windows.net/delve?sv=1"},
        {"provider": "azure", "sas_url": 42},
        {**s3_body(), "secret_access_key": f"{SECRET} two"},
        {**s3_body(), "endpoint": f"https://{SECRET}@acct.r2.cloudflarestorage.com"},
        {**s3_body(), "right": "read"},
        {**s3_body(), "extra": SECRET},
        {"provider": "local", "root": "relative"},
    ],
)
def test_a_refused_body_is_never_echoed(local, config, body, every_log):
    response = local.put("/api/storage/backup", json=body)
    assert response.status_code == 422
    assert set(response.json()) == {"error"}
    assert not (config.data_dir / "backup-store.json").exists()
    assert_no_secret(response.text, every_log.text)


def test_the_stored_secret_is_kept_when_the_form_sends_none(local, app, config):
    fake = plays(app, FakeS3())
    assert local.put("/api/storage/library", json=s3_body()).status_code == 200
    response = local.put("/api/storage/library", json=s3_body(right="manage", secret=None))
    assert response.status_code == 200, response.text
    assert response.json()["choice"] == "manage"
    assert load_store(config.data_dir, "library").secret_access_key == SECRET
    assert fake.objects == {}
    plays(app, FakeAzure())
    assert local.put("/api/storage/backup", json=azure_body()).status_code == 200
    assert local.put("/api/storage/backup", json={"provider": "azure"}).status_code == 200
    assert load_store(config.data_dir, "backup").sas_url == sas_url()


def test_delete_removes_the_store(local, app, config, tmp_path):
    local.put("/api/storage/library", json=folder(tmp_path))
    assert app.state.stores.library is not None
    response = delete(local, "/api/storage/library")
    assert response.status_code == 200
    assert response.json() is None
    assert not (config.data_dir / "library-store.json").exists()
    assert app.state.stores.library is None and app.state.stores.library_right is None
    assert local.get("/api/storage").json()["library"] is None


def test_test_without_a_store_says_so(local):
    assert local.post("/api/storage/backup/test", json={}).json() == {
        "ok": False, "right": None, "message": "No backup store is set.",
    }
    assert local.post("/api/storage/library/test", json={}).json() == {
        "ok": False, "right": None, "message": "No library is set.",
    }


def test_a_backup_store_says_what_its_sas_lacks(local, app):
    """The SAS can create but not delete, or create but not overwrite: the refusal names the permission to add."""
    plays(app, FakeAzure("rcwl"))
    response = local.put("/api/storage/backup", json=azure_body("rcwl"))
    assert response.json() == {
        "error": "This credential can create and overwrite but not delete, so backups can't use it. "
        "Make the SAS again with Delete (d).",
    }
    plays(app, FakeAzure("rcdl"))
    response = local.put("/api/storage/backup", json=azure_body("rcdl"))
    assert response.json() == {
        "error": "This credential can create but not overwrite, so backups can't use it. "
        "Make the SAS again with Write (w) and Delete (d).",
    }


def test_a_backup_store_whose_container_is_missing_says_so(local, app):
    app.state.stores.transport = httpx.MockTransport(lambda request: httpx.Response(404, text="ContainerNotFound"))
    response = local.put("/api/storage/backup", json=azure_body())
    assert response.json() == {
        "error": "The container isn't there: check its name in the URL, after the host, or create it in the storage. "
        "In the Azure portal: the storage account's Data storage, Containers.",
    }


def test_test_says_a_backup_store_lost_its_rights(local, app, tmp_path):
    fake = plays(app, FakeAzure())
    local.put("/api/storage/backup", json=azure_body())
    assert local.post("/api/storage/backup/test", json={}).json() == {
        "ok": True, "right": "manage", "message": "Delve can back up to this store.",
    }
    fake.sp = "rl"  # the owner made a new SAS of fewer rights behind Delve's back
    assert local.post("/api/storage/backup/test", json={}).json() == {
        "ok": False, "right": "read",
        "message": "This credential can read but not create, so backups can't use it. "
        "Make the SAS again with Create (c), Write (w) and Delete (d).",
    }


def test_the_schedule_is_saved_and_read_back(local, app, storage):
    response = local.put("/api/storage/schedule", json={"time": "21:30"})
    assert response.status_code == 200
    assert response.json() == {"time": "21:30", "last_run": None, "running": False}
    assert local.get("/api/storage").json()["schedule"] == {"time": "21:30", "last_run": None, "running": False}
    assert storage.settings.load()["backup"] == {"time": "21:30"}


def test_saving_preferences_keeps_the_backup_time(local, storage):
    local.put("/api/storage/schedule", json={"time": "21:30"})
    response = local.put("/api/preferences", json={"choices": {}, "language": "nl"})
    assert response.status_code == 200, response.text
    assert local.get("/api/storage").json()["schedule"]["time"] == "21:30"


@pytest.mark.parametrize(
    "body", [{"time": "24:00"}, {"time": "4:00"}, {"time": "04:60"}, {"time": 4}, {}, {"time": "04:00", "x": 1}]
)
def test_a_bad_time_is_422(local, body):
    response = local.put("/api/storage/schedule", json=body)
    assert response.status_code == 422
    assert set(response.json()) == {"error"}
    assert local.get("/api/storage").json()["schedule"]["time"] == "04:00"


def test_an_azure_sas_answers_its_expiry(local, app):
    plays(app, FakeAzure())
    response = local.put("/api/storage/library", json=azure_body(se="2027-03-01"))
    assert response.status_code == 200, response.text
    assert response.json()["expires"] == "2027-03-01T00:00:00+00:00"
    assert local.get("/api/storage").json()["library"]["expires"] == "2027-03-01T00:00:00+00:00"


def test_each_change_publishes_preferences(local, app, tmp_path):
    local.put("/api/storage/backup", json=folder(tmp_path))
    local.put("/api/storage/schedule", json={"time": "05:00"})
    delete(local, "/api/storage/backup")
    assert [event.type for event in published(app)].count("preferences") == 3


SAME_STORE = {"error": "The backup store and the library must be different stores."}
ORDERS = [("backup", "library"), ("library", "backup")]


def azure_variant(sp="racwdl"):
    """The same container, written otherwise: another case and a trailing slash."""
    url = sas_url(sp)
    container, query = url.split("?", 1)
    return {"provider": "azure", "sas_url": f"{container.upper().replace('HTTPS', 'https')}/?{query}"}


def assert_refused(local, app, config, second, body, every_log):
    stored = load_store(config.data_dir, second)
    response = local.put(f"/api/storage/{second}", json=body)
    assert response.status_code == 422, response.text
    assert response.json() == SAME_STORE
    assert load_store(config.data_dir, second) == stored, "nothing is stored"
    assert_no_secret(response.text, every_log.text)


@pytest.mark.parametrize(("first", "second"), ORDERS)
def test_one_azure_container_is_never_both_stores(local, app, config, first, second, every_log):
    """A friend's library credential must never reach the owner's backups (DEL-110)."""
    plays(app, FakeAzure())
    assert local.put(f"/api/storage/{first}", json=azure_body()).status_code == 200
    assert_refused(local, app, config, second, azure_body("rl"), every_log)
    assert_refused(local, app, config, second, azure_variant(), every_log)
    container, query = sas_url().split("?", 1)
    host = container.removeprefix("https://").split("/", 1)[0]
    for written in (container.replace(host, f"{host}:443"), container.replace(host, f"{host}."),
                    container.replace(host, f"{host}/")):
        assert_refused(local, app, config, second, {"provider": "azure", "sas_url": f"{written}?{query}"}, every_log)
    other = {"provider": "azure", "sas_url": sas_url().replace("delveacct", "otheracct")}
    assert local.put(f"/api/storage/{second}", json=other).status_code == 200, "another container is fine"


@pytest.mark.parametrize(("first", "second"), ORDERS)
def test_one_s3_bucket_is_never_both_stores(local, app, config, first, second, every_log):
    plays(app, FakeS3())
    assert local.put(f"/api/storage/{first}", json=s3_body(right="manage")).status_code == 200
    assert_refused(local, app, config, second, s3_body(), every_log)
    assert_refused(local, app, config, second, {**s3_body(), "endpoint": ENDPOINT.upper().replace("HTTPS", "https")
                                                + "/", "access_key_id": "OTHERKEY"}, every_log)
    for endpoint in (f"{ENDPOINT}:443", f"{ENDPOINT}.", f"{ENDPOINT}./"):
        assert_refused(local, app, config, second, {**s3_body(), "endpoint": endpoint}, every_log)
    elsewhere = {**s3_body(right="manage"), "endpoint": "https://other.r2.cloudflarestorage.com"}
    assert local.put(f"/api/storage/{second}", json=elsewhere).status_code == 200, "another account's bucket is fine"
    assert same_place(StoreConfig("s3", endpoint=ENDPOINT, bucket=BUCKET),
                      StoreConfig("s3", endpoint=ENDPOINT, bucket="delve-backups")) is False
    assert_no_secret(every_log.text)


@pytest.mark.parametrize(("first", "second"), ORDERS)
def test_one_folder_is_never_both_stores(local, app, config, tmp_path, first, second, every_log):
    """The same folder, by another path, and a folder inside the other store's (or holding it), are refused."""
    store = folder(tmp_path)
    assert local.put(f"/api/storage/{first}", json=store).status_code == 200
    (tmp_path / "store" / "inner").mkdir()
    (tmp_path / "link").symlink_to(tmp_path / "store")
    for root in (store["root"], f"{tmp_path}/store/", f"{tmp_path}/store/../store", f"{tmp_path}/link",
                 f"{tmp_path}/store/inner", str(tmp_path)):
        assert_refused(local, app, config, second, {"provider": "local", "root": root}, every_log)
    assert local.put(f"/api/storage/{second}", json=folder(tmp_path, "store2")).status_code == 200, "a neighbour"


def test_a_store_may_be_saved_again_in_its_own_place(local, app, tmp_path):
    store = folder(tmp_path)
    assert local.put("/api/storage/backup", json=store).status_code == 200
    assert local.put("/api/storage/backup", json=store).status_code == 200


def test_an_unknown_store_is_404(local):
    assert local.put("/api/storage/dropbox", json={"provider": "local"}).status_code == 404
    assert local.post("/api/storage/dropbox/test", json={}).status_code == 404


ROUTES = [
    ("GET", "/api/storage", None),
    ("PUT", "/api/storage/backup", s3_body()),
    ("PUT", "/api/storage/library", s3_body()),
    ("DELETE", "/api/storage/backup", {}),
    ("DELETE", "/api/storage/library", {}),
    ("POST", "/api/storage/backup/test", {}),
    ("POST", "/api/storage/library/test", {}),
    ("PUT", "/api/storage/schedule", {"time": "05:00"}),
]
OWNER_ONLY = [
    *ROUTES,
    ("POST", "/api/storage/backup", {}),
    ("GET", "/api/storage/backups", None),
    ("GET", "/api/storage/backups/ins_0123456789ab", None),
    ("POST", "/api/storage/restore", {"install_id": "ins_0123456789ab", "items": [{"kind": "module", "item_id": "m"}]}),
    ("GET", "/api/storage/unused", None),
    ("POST", "/api/storage/unused/delete", {}),
]


@pytest.mark.parametrize(("method", "path", "body"), OWNER_ONLY)
def test_an_organiser_gets_403(lan, storage, config, method, path, body, every_log):
    make_account(storage, organiser=True)
    log_in(lan)
    assert lan.get("/api/preferences").status_code == 200, "the account is an organiser"
    response = lan.request(method, path, json=body)
    assert response.status_code == 403, path
    assert response.json() == {"error": "Only the install's owner can do this."}
    assert not (config.data_dir / "backup-store.json").exists()
    assert not (config.data_dir / "library-store.json").exists()
    assert "backup" not in storage.settings.load()
    assert_no_secret(response.text, every_log.text)


@pytest.mark.parametrize(("method", "path", "body"), OWNER_ONLY)
def test_an_organiser_seat_gets_403(seat_client, method, path, body):  # noqa: F811
    response = seat_client(organiser=True).request(method, path, json=body)
    assert response.status_code == 403, path


@pytest.mark.parametrize(("method", "path", "body"), OWNER_ONLY)
def test_nobody_gets_401(lan, method, path, body):
    assert lan.request(method, path, json=body).status_code == 401, path


@pytest.mark.parametrize(("method", "path", "body"), ROUTES)
def test_the_owner_token_gets_200(lan, app, token, method, path, body):
    plays(app, FakeS3())
    lan.headers["Authorization"] = f"Bearer {token}"
    response = lan.request(method, path, json=body)
    assert response.status_code == 200, path
    assert_no_secret(response.text)


# ----- Back up now and the schedule (plan Task 7) -----


class GatedStore(LocalStore):
    """A local store whose puts wait for `gate` (a threading.Event), like a slow upload; one name may be refused."""

    def __init__(self, root, refuse: str = "") -> None:
        super().__init__(root)
        self.gate = threading.Event()
        self.gate.set()
        self.refuse = refuse

    async def put(self, name, data):
        while not self.gate.is_set():
            await asyncio.sleep(0.01)
        if self.refuse and self.refuse in name:
            raise StoreError("The store refused the write.")
        await super().put(name, data)


@pytest.fixture
def crypt(storage):
    module = storage.modules.create("The Crypt")
    storage.modules.put_map(module.id, ModuleMap("crypt", "map", "map crypt {}\n", is_default=True))
    revision = storage.revisions.snapshot(module.id)
    return storage.campaigns.create("Tuesday", module.id, revision.number, ruleset="osric", setting="greyhawk")


def backing_up(local, app, tmp_path, **kwargs) -> GatedStore:
    """A backup store set through the route, then played by a gated local store on the same folder."""
    assert local.put("/api/storage/backup", json=folder(tmp_path)).status_code == 200
    store = GatedStore(tmp_path / "store", **kwargs)
    app.state.stores.backup = store
    return store


def finished(local, timeout: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        schedule = local.get("/api/storage").json()["schedule"]
        if not schedule["running"] and schedule["last_run"] is not None:
            return schedule["last_run"]
        time.sleep(0.02)
    raise AssertionError("the backup is still running")


def test_backup_now_answers_202_then_409_while_running(local, app, tmp_path, crypt):
    store = backing_up(local, app, tmp_path)
    store.gate.clear()
    response = local.post("/api/storage/backup", json={})
    assert response.status_code == 202
    assert response.json()["running"] is True
    again = local.post("/api/storage/backup", json={})
    assert again.status_code == 409
    assert again.json() == {"error": "A backup is already running."}

    store.gate.set()
    last_run = finished(local)
    assert last_run["status"] == "ok" and sorted(last_run["uploaded"]) == ["The Crypt", "Tuesday"]
    assert set(last_run) == {"started_at", "finished_at", "uploaded", "unchanged", "failed", "status"}
    assert (tmp_path / "store" / install_id(app.state.config.data_dir) / "index.json").is_file()
    assert [e for e in published(app) if e.type == "preferences"], "its end tells the Storage section"
    assert local.post("/api/storage/backup", json={}).status_code == 202, "a run may start once the last ended"
    finished(local)


def test_backup_now_without_a_store_is_409(local):
    response = local.post("/api/storage/backup", json={})
    assert response.status_code == 409
    assert response.json() == {"error": "No backup store is set."}


def test_a_partial_run_is_shown_as_partial_with_its_failure(local, app, tmp_path, crypt):
    backing_up(local, app, tmp_path, refuse="/campaigns/")
    assert local.post("/api/storage/backup", json={}).status_code == 202
    last_run = finished(local)
    assert last_run["status"] == "partial"
    assert last_run["uploaded"] == ["The Crypt"]
    assert last_run["failed"] == [
        {"kind": "campaign", "item_id": crypt.id, "title": "Tuesday", "error": "The store refused the write."}
    ]


def test_backup_never_blocks_a_beat(local, app, tmp_path, crypt):
    """A beat is acted and closes while the backup's upload still waits."""
    store = backing_up(local, app, tmp_path)
    store.gate.clear()
    assert local.post("/api/storage/backup", json={}).status_code == 202

    assert local.post(f"/api/campaigns/{crypt.id}/act", json={"text": "We listen."}).status_code == 202
    deadline = time.monotonic() + 5
    while local.get(f"/api/campaigns/{crypt.id}/play/state").json()["beat"] is not None:
        assert time.monotonic() < deadline, "the beat waits for the backup"
        time.sleep(0.02)
    assert local.get("/api/storage").json()["schedule"]["running"] is True, "the backup still waits"
    assert app.state.storage.story.list(crypt.id), "the story got the beat"

    store.gate.set()
    assert finished(local)["status"] == "ok"


def test_a_run_missed_while_delve_was_down_runs_at_start(app, storage, config, tmp_path, crypt):
    """The time has passed today and no run started since: the start runs it, with nobody asking."""
    (tmp_path / "store").mkdir()
    save_store(config.data_dir, "backup", StoreConfig("local", root=str(tmp_path / "store")), keep_secret=False)
    storage.settings.save({"backup": {"time": "00:00", "last_run": {"started_at": "2026-01-01T04:00:00+00:00"}}})
    with TestClient(app, base_url=BASE_URL, client=("127.0.0.1", 50000)) as client:
        last_run = finished_since(client, "2026-01-01T04:00:00+00:00")
    assert last_run["status"] == "ok" and sorted(last_run["uploaded"]) == ["The Crypt", "Tuesday"]


def test_no_run_starts_without_a_backup_store(app, storage, crypt):
    storage.settings.save({"backup": {"time": "00:00"}})
    with TestClient(app, base_url=BASE_URL, client=("127.0.0.1", 50000)) as client:
        time.sleep(0.2)
        assert client.get("/api/storage").json()["schedule"] == {"time": "00:00", "last_run": None, "running": False}


def finished_since(client, started_at: str, timeout: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        schedule = client.get("/api/storage").json()["schedule"]
        if not schedule["running"] and schedule["last_run"]["started_at"] > started_at:
            return schedule["last_run"]
        time.sleep(0.02)
    raise AssertionError("no backup ran")


# ----- Restore (plan Task 8) -----

OLD = "ins_0123456789ab"


@pytest.fixture
def old_install(tmp_path):
    """Another install, backed up to the store folder: the crypt and Tuesday on it."""
    other = open_storage(Config(data_dir=tmp_path / "old"))
    module = crypt_module(other)
    campaign = crypt_campaign(other, module)
    (tmp_path / "store").mkdir(exist_ok=True)
    assert asyncio.run(run_backup(other, LocalStore(tmp_path / "store"), OLD, name="old laptop")).status == "ok"
    yield other, module, campaign
    other.close()


def test_restore_lists_installs_and_items_then_restores_a_campaign_with_its_module(local, app, tmp_path, old_install):
    other, module, campaign = old_install
    assert local.put("/api/storage/backup", json=folder(tmp_path)).status_code == 200

    installs = local.get("/api/storage/backups")
    assert installs.status_code == 200
    assert [(i["install_id"], i["name"]) for i in installs.json()] == [(OLD, "old laptop")]

    items = local.get(f"/api/storage/backups/{OLD}")
    assert items.status_code == 200
    by_id = {item["item_id"]: item for item in items.json()}
    assert by_id[campaign.id]["module_id"] == module.id and by_id[campaign.id]["setting_id"] is None
    assert not any(item["exists_here"] for item in items.json())

    before = len(published(app))
    body = {"install_id": OLD, "items": [{"kind": "campaign", "item_id": campaign.id}], "replace": False}
    restored = local.post("/api/storage/restore", json=body)
    assert restored.status_code == 200
    assert restored.json() == [
        {"kind": "module", "item_id": module.id, "ok": True, "warnings": [], "error": None, "added": True},
        {"kind": "campaign", "item_id": campaign.id, "ok": True, "warnings": [], "error": None},
    ]
    events = [(e.type, e.data) for e in published(app)[before:]]
    assert ("modules", {"id": module.id}) in events and ("campaigns", {"id": campaign.id}) in events
    assert app.state.storage.snapshots.dump("campaign", campaign.id) == other.snapshots.dump("campaign", campaign.id)
    assert all(item["exists_here"] for item in local.get(f"/api/storage/backups/{OLD}").json())


def test_restoring_over_an_existing_item_needs_replace(local, app, tmp_path, old_install):
    _, module, _ = old_install
    assert local.put("/api/storage/backup", json=folder(tmp_path)).status_code == 200
    body = {"install_id": OLD, "items": [{"kind": "module", "item_id": module.id}]}
    assert local.post("/api/storage/restore", json=body).json()[0]["ok"] is True
    app.state.storage.modules.rename(module.id, "Changed here")

    before = len(published(app))
    refused = local.post("/api/storage/restore", json=body)
    assert refused.status_code == 200
    assert refused.json() == [{"kind": "module", "item_id": module.id, "ok": False, "warnings": [], "error": "exists"}]
    assert app.state.storage.modules.get(module.id).title == "Changed here"
    assert not [e for e in published(app)[before:] if e.type == "modules"], "nothing changed, nothing published"

    replaced = local.post("/api/storage/restore", json={**body, "replace": True})
    assert replaced.json()[0]["ok"] is True
    assert app.state.storage.modules.get(module.id).title == "The Crypt"


def test_restore_without_a_backup_store_is_409(local):
    assert local.get("/api/storage/backups").status_code == 409
    assert local.get(f"/api/storage/backups/{OLD}").json() == {"error": "No backup store is set."}
    body = {"install_id": OLD, "items": [{"kind": "module", "item_id": "mod_1"}]}
    assert local.post("/api/storage/restore", json=body).status_code == 409


def test_an_install_without_a_backup_is_404(local, tmp_path):
    assert local.put("/api/storage/backup", json=folder(tmp_path)).status_code == 200
    assert local.get(f"/api/storage/backups/{OLD}").status_code == 404
    assert local.get("/api/storage/backups/ins.x").status_code == 404


@pytest.mark.parametrize(
    "body",
    [
        {"install_id": OLD},
        {"install_id": OLD, "items": []},
        {"install_id": "../x", "items": [{"kind": "module", "item_id": "mod_1"}]},
        {"install_id": OLD, "items": [{"kind": "map", "item_id": "mod_1"}]},
        {"install_id": OLD, "items": [{"kind": "module", "item_id": "../index"}]},
        {"install_id": OLD, "items": [{"kind": "module", "item_id": "mod_1", "extra": 1}]},
        {"install_id": OLD, "items": [{"kind": "module", "item_id": "mod_1"}], "replace": "yes"},
        {"install_id": OLD, "items": [{"kind": "module", "item_id": "mod_1"}], "other": 1},
    ],
)
def test_a_bad_restore_body_is_422(local, tmp_path, body):
    assert local.put("/api/storage/backup", json=folder(tmp_path)).status_code == 200
    assert local.post("/api/storage/restore", json=body).status_code == 422


def test_a_failing_store_answers_its_own_words(local, app, tmp_path):
    class Down(LocalStore):
        async def list(self, prefix=""):
            raise StoreError("The store didn't answer.")

    assert local.put("/api/storage/backup", json=folder(tmp_path)).status_code == 200
    app.state.stores.backup = Down(tmp_path / "store")
    response = local.get("/api/storage/backups")
    assert response.status_code == 502
    assert response.json() == {"error": "The store didn't answer."}


def test_restore_needs_the_owner(lan, storage, tmp_path, app, old_install):
    _, module, _ = old_install
    save_store(app.state.config.data_dir, "backup", StoreConfig("local", root=str(tmp_path / "store")), keep_secret=False)
    app.state.stores.backup = LocalStore(tmp_path / "store")
    make_account(storage, organiser=True)
    log_in(lan)
    body = {"install_id": OLD, "items": [{"kind": "module", "item_id": module.id}], "replace": True}
    response = lan.post("/api/storage/restore", json=body)
    assert response.status_code == 403
    assert response.json() == {"error": "Only the install's owner can do this."}
    assert storage.modules.get(module.id) is None, "nothing was restored"


def test_put_and_test_record_the_right_and_a_start_makes_no_request(app, config):
    """Only saving and Test probe the library; a restart takes the right they recorded (a publish-only SAS can't delete
    its probe object, so a probe at each start would litter the library)."""
    from fastapi.testclient import TestClient

    fake = FakeAzure("rcl")
    with TestClient(app, base_url=BASE_URL, client=("127.0.0.1", 50000)) as client:
        plays(app, fake)
        assert client.put("/api/storage/library", json=azure_body("rcl")).json()["right"] == "publish"
        assert json.loads((config.data_dir / "library-store.json").read_text())["probed"] == "publish"
        fake.sp = "racwdl"  # the owner gave the SAS more rights; Test finds them
        assert client.post("/api/storage/library/test", json={}).json()["right"] == "manage"
        assert json.loads((config.data_dir / "library-store.json").read_text())["probed"] == "manage"
    fake.requests.clear()
    with TestClient(app, base_url=BASE_URL, client=("127.0.0.1", 50000)) as client:
        assert app.state.stores.library_right == "manage"
        assert client.get("/api/storage").json()["library"]["right"] == "manage"
    assert fake.requests == [], "a start makes no request to the store"


def test_unused_files_are_listed_then_deleted(app, local, storage):
    """Files nothing uses (DEL-36): the owner sees what would go, by type, then deletes it."""
    module = storage.modules.create("The Crypt")
    storage.blobs.link(module.id, "attachment", put_old(storage, b"used"))
    loose = [put_old(storage, b"a replaced picture"), put_old(storage, b"an old book", "application/pdf")]
    storage.blobs.put(b"just painted", "image/png")

    expected = {
        "count": 2,
        "size": 29,
        "kept": 1,
        "kinds": [{"mime": "image/png", "count": 1, "size": 18}, {"mime": "application/pdf", "count": 1, "size": 11}],
    }
    assert local.get("/api/storage/unused").json() == expected
    assert all(storage.blobs.exists(sha) for sha in loose)
    before = [event.type for event in published(app)].count("preferences")
    assert local.post("/api/storage/unused/delete", json={}).json() == expected
    assert [event.type for event in published(app)].count("preferences") == before + 1
    assert not any(storage.blobs.exists(sha) for sha in loose)
    assert local.get("/api/storage/unused").json() == {"count": 0, "size": 0, "kept": 1, "kinds": []}
