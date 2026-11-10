"""The backup run (cloud storage Task 7): what changed goes to the backup store, latest copy only, with an index of
everything there; a run where one item fails is partial, says which and why, and that item is tried again next run
(Review Focus 3). The store is a local folder, or one that refuses one name; never a real call."""

import asyncio
import json
from datetime import UTC, datetime, timedelta

import pytest

from delve.cloud import backup
from delve.cloud.backup import RunResult, due, run_backup
from delve.cloud.store import LocalStore, StoreError
from delve.config import Config
from delve.storage import open_storage
from tests.cloud.test_bundles import crypt_campaign, crypt_module, greyhawk

INSTALL = "ins_0123456789ab"


@pytest.fixture
def storage(tmp_path):
    opened = open_storage(Config(data_dir=tmp_path / "data"))
    yield opened
    opened.close()


@pytest.fixture
def store(tmp_path):
    (tmp_path / "store").mkdir()
    return LocalStore(tmp_path / "store")


@pytest.fixture
def played(storage):
    """A module (two revisions), a campaign on it and the Greyhawk setting."""
    module = crypt_module(storage)
    campaign = crypt_campaign(storage, module)
    greyhawk(storage)
    return module, campaign


class Clock:
    def __init__(self) -> None:
        self.at = datetime(2026, 10, 26, 4, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        self.at += timedelta(seconds=1)
        return self.at


CLOCK = Clock()


class RefusingStore(LocalStore):
    """A local store whose writes of one name fail, as a store refusing one write (or one bundle too large) does."""

    def __init__(self, root, refuse: str) -> None:
        super().__init__(root)
        self.refuse = refuse

    async def put(self, name: str, data: bytes) -> None:
        if name == self.refuse:
            raise StoreError("The store refused the write.")
        await super().put(name, data)


def run(coro):
    return asyncio.run(coro)


def backup_now(storage, store) -> RunResult:
    return run(run_backup(storage, store, INSTALL, now=CLOCK))


def index(store) -> dict:
    return json.loads(run(store.get(f"{INSTALL}/index.json")))


def names(store) -> list[str]:
    return sorted(path.relative_to(store.root).as_posix() for path in store.root.rglob("*") if path.is_file())


def test_a_first_run_uploads_every_module_campaign_and_setting(storage, store, played):
    module, campaign = played
    result = backup_now(storage, store)

    assert result.status == "ok" and result.failed == [] and result.unchanged == 0
    assert sorted(result.uploaded) == ["The Crypt", "Tuesday", "greyhawk"]
    assert names(store) == [
        f"{INSTALL}/campaigns/{campaign.id}.dcmp",
        f"{INSTALL}/index.json",
        f"{INSTALL}/modules/{module.id}.dmod",
        f"{INSTALL}/settings/greyhawk.dset",
    ]
    listed = index(store)
    assert listed["install_id"] == INSTALL and isinstance(listed["name"], str) and listed["updated_at"]
    items = {(item["kind"], item["item_id"]): item for item in listed["items"]}
    assert set(items) == {("module", module.id), ("campaign", campaign.id), ("setting", "greyhawk")}
    for (kind, item_id), item in items.items():
        recorded = storage.backup_items.get(kind, item_id)
        assert recorded is not None
        assert item == {
            "kind": kind,
            "item_id": item_id,
            "title": {"module": "The Crypt", "campaign": "Tuesday", "setting": "greyhawk"}[kind],
            "hash": recorded.hash,
            "size": recorded.size,
            "backed_up_at": recorded.backed_up_at,
            "on_install": True,
            **({"module_id": module.id, "setting_id": None} if kind == "campaign" else {}),
        }
    bundle = run(store.get(f"{INSTALL}/modules/{module.id}.dmod"))
    assert storage.backup_items.get("module", module.id).size == len(bundle)


def test_the_result_is_stored_as_the_last_run(storage, store, played):
    result = backup_now(storage, store)
    stored = storage.settings.load()["backup"]["last_run"]
    assert stored == result.to_json()
    assert stored["status"] == "ok" and stored["started_at"] < stored["finished_at"]
    assert set(stored) == {"started_at", "finished_at", "uploaded", "unchanged", "failed", "status"}


def test_the_last_run_keeps_the_backup_time(storage, store, played):
    storage.settings.save({"backup": {"time": "02:30"}, "language": "nl"})
    backup_now(storage, store)
    stored = storage.settings.load()
    assert stored["backup"]["time"] == "02:30" and stored["language"] == "nl"


def test_a_second_run_uploads_only_what_changed(storage, store, played):
    _, campaign = played
    backup_now(storage, store)
    unchanged = backup_now(storage, store)
    assert unchanged.uploaded == [] and unchanged.unchanged == 3 and unchanged.status == "ok"

    before = storage.backup_items.get("module", played[0].id)
    storage.story.append(campaign.id, storage.beats.current(campaign.id).id, "dm", {"text": "A door creaks."})
    changed = backup_now(storage, store)
    assert changed.uploaded == ["Tuesday"] and changed.unchanged == 2
    assert storage.backup_items.get("module", played[0].id) == before


def test_a_new_store_gets_everything_again(storage, store, played, tmp_path):
    """The records say what the backup store had; a store that doesn't list an item at that hash gets it."""
    backup_now(storage, store)
    (tmp_path / "other").mkdir()
    other = LocalStore(tmp_path / "other")
    result = backup_now(storage, other)
    assert sorted(result.uploaded) == ["The Crypt", "Tuesday", "greyhawk"]
    assert len((index(other))["items"]) == 3


def test_one_failing_item_makes_the_run_partial_and_is_retried_next_time(storage, tmp_path, played):
    """Review Focus 3: the failure is listed with its reason, the rest is uploaded and in the index, and only what was
    uploaded is recorded, so the failed item goes up at the next run."""
    module, campaign = played
    (tmp_path / "store").mkdir()
    failing = f"{INSTALL}/campaigns/{campaign.id}.dcmp"
    store = RefusingStore(tmp_path / "store", refuse=failing)

    result = backup_now(storage, store)
    assert result.status == "partial"
    assert result.failed == [
        {"kind": "campaign", "item_id": campaign.id, "title": "Tuesday", "error": "The store refused the write."}
    ]
    assert sorted(result.uploaded) == ["The Crypt", "greyhawk"]
    assert storage.backup_items.get("campaign", campaign.id) is None
    assert storage.backup_items.get("module", module.id) is not None
    assert failing not in names(store)
    listed = index(store)
    assert {(item["kind"], item["item_id"]) for item in listed["items"]} == {
        ("module", module.id),
        ("setting", "greyhawk"),
    }
    # A partial run is never stored as a success.
    assert storage.settings.load()["backup"]["last_run"]["status"] == "partial"

    store.refuse = ""
    retried = backup_now(storage, store)
    assert retried.status == "ok" and retried.uploaded == ["Tuesday"] and retried.unchanged == 2
    assert storage.backup_items.get("campaign", campaign.id) is not None
    assert failing in names(store)


def test_a_failed_index_makes_the_run_partial(storage, tmp_path, played):
    (tmp_path / "store").mkdir()
    store = RefusingStore(tmp_path / "store", refuse=f"{INSTALL}/index.json")
    result = backup_now(storage, store)
    assert result.status == "partial" and len(result.uploaded) == 3
    assert [(failure["kind"], failure["title"]) for failure in result.failed] == [("index", "The backup's list")]


def test_a_store_that_takes_nothing_makes_the_run_failed(storage, tmp_path, played):
    (tmp_path / "store").mkdir()
    store = LocalStore(tmp_path / "store", read_only=True)
    result = backup_now(storage, store)
    assert result.status == "failed" and result.uploaded == []
    assert {failure["kind"] for failure in result.failed} == {"module", "campaign", "setting", "index"}
    assert storage.backup_items.list() == []
    assert storage.settings.load()["backup"]["last_run"]["status"] == "failed"


def test_an_unreadable_index_fails_the_run_and_uploads_nothing(storage, tmp_path, played):
    """Without the old index Delve can't keep the items no longer here in the new one, so it doesn't write one."""
    (tmp_path / "store").mkdir()

    class Unreadable(LocalStore):
        async def get(self, name):
            raise StoreError("The store didn't answer.")

    store = Unreadable(tmp_path / "store")
    result = backup_now(storage, store)
    assert result.status == "failed" and result.uploaded == []
    assert result.failed == [
        {"kind": "index", "item_id": "index.json", "title": "The backup's list", "error": "The store didn't answer."}
    ]
    assert storage.backup_items.list() == [] and names(store) == []


def test_a_store_without_its_folder_fails_every_item(storage, tmp_path, played):
    result = backup_now(storage, LocalStore(tmp_path / "gone"))
    assert result.status == "failed" and result.uploaded == []
    assert storage.backup_items.list() == []


def test_a_failure_never_names_a_credential(storage, tmp_path, played):
    (tmp_path / "store").mkdir()

    class Leaky(LocalStore):
        async def put(self, name, data):
            raise RuntimeError("https://x.blob.core.windows.net/c?sig=SECRET-XYZZY")

    result = backup_now(storage, Leaky(tmp_path / "store"))
    assert result.status == "failed" and "SECRET-XYZZY" not in json.dumps(result.to_json())


def test_an_item_deleted_locally_stays_in_the_index_as_not_on_this_install(storage, store, played):
    module, campaign = played
    backup_now(storage, store)
    first = {item["item_id"]: item for item in (index(store))["items"]}
    storage.campaigns.delete(campaign.id)

    result = backup_now(storage, store)
    assert result.status == "ok" and result.uploaded == []
    items = {item["item_id"]: item for item in (index(store))["items"]}
    assert items[campaign.id] == {**first[campaign.id], "on_install": False}
    assert items[module.id]["on_install"] is True
    assert f"{INSTALL}/campaigns/{campaign.id}.dcmp" in names(store)


UNFINISHED = {
    "kind": "index",
    "item_id": "index.json",
    "title": "The backup's list",
    "error": "Delve couldn't finish the backup.",
}


def test_a_run_that_raises_still_stores_a_failed_last_run(storage, store, played, monkeypatch):
    """An earlier run's `ok` never stays as the last run of one that broke off."""
    backup_now(storage, store)
    before = storage.settings.load()["backup"]["last_run"]

    def broken(kind):
        raise RuntimeError("the database is locked")

    monkeypatch.setattr(storage.snapshots, "item_ids", broken)
    result = backup_now(storage, store)

    stored = storage.settings.load()["backup"]["last_run"]
    assert stored == result.to_json()
    assert stored["status"] == "failed" and stored["failed"] == [UNFINISHED]
    assert stored["started_at"] > before["started_at"] and stored["finished_at"]


def test_a_run_that_raises_after_an_upload_is_partial(storage, store, played, monkeypatch):
    real = storage.backup_items.get
    calls = []

    def breaks_on_the_second(kind, item_id):
        calls.append(item_id)
        if len(calls) == 2:
            raise RuntimeError("no")
        return real(kind, item_id)

    monkeypatch.setattr(storage.backup_items, "get", breaks_on_the_second)
    result = backup_now(storage, store)
    assert result.status == "partial" and result.uploaded == ["The Crypt"]
    assert result.failed == [UNFINISHED]
    assert storage.settings.load()["backup"]["last_run"]["status"] == "partial"


class HangingStore(LocalStore):
    """A local store that takes `takes` writes, then waits forever on the next."""

    def __init__(self, root, takes: int) -> None:
        super().__init__(root)
        self.takes = takes
        self.waiting = asyncio.Event()

    async def put(self, name: str, data: bytes) -> None:
        if self.takes == 0:
            self.waiting.set()
            await asyncio.Event().wait()
        self.takes -= 1
        await super().put(name, data)


@pytest.mark.parametrize(("takes", "status", "uploaded"), [(0, "failed", []), (1, "partial", ["The Crypt"])])
def test_a_cancelled_run_stores_its_last_run(storage, tmp_path, played, takes, status, uploaded):
    (tmp_path / "store").mkdir()
    store = HangingStore(tmp_path / "store", takes=takes)
    backups = backup.Backups()

    async def cancel_midway():
        backups_task = asyncio.create_task(backups._run(storage, store, INSTALL))
        await backups.lock.acquire()  # as `start` does: `_run` releases it
        await store.waiting.wait()
        backups_task.cancel()
        await asyncio.gather(backups_task, return_exceptions=True)

    run(cancel_midway())
    stored = storage.settings.load()["backup"]["last_run"]
    assert stored["status"] == status and stored["uploaded"] == uploaded
    assert stored["failed"] == [UNFINISHED] and stored["finished_at"]
    assert not backups.running


class LoopState:
    """What `schedule_loop` reads of `app.state`, with a run that always breaks off."""

    def __init__(self, storage, store, tmp_path) -> None:
        self.storage = storage
        self.stores = type("Stores", (), {"backup": store})()
        self.config = Config(data_dir=tmp_path / "data")
        self.backups = backup.Backups()
        self.starts = 0
        start = self.backups.start

        async def counted(*args):
            self.starts += 1
            task = await start(*args)
            await task
            return task

        self.backups.start = counted


@pytest.mark.parametrize("saves", [True, False], ids=["last run saved", "settings unwritable"])
def test_a_run_that_failed_as_a_whole_isnt_retried_every_tick(storage, store, played, tmp_path, monkeypatch, saves):
    """The next try is at the next scheduled time (or Back up now), even when the last run can't be saved."""

    def broken(kind):
        raise RuntimeError("no")

    monkeypatch.setattr(storage.snapshots, "item_ids", broken)
    if not saves:
        monkeypatch.setattr(storage.settings, "save", broken)
    state = LoopState(storage, store, tmp_path)
    app = type("App", (), {"state": state})()
    now = datetime.now().astimezone().replace(hour=4, minute=30, second=0, microsecond=0)

    async def five_ticks():
        loop = asyncio.create_task(backup.schedule_loop(app, tick=0.01, now=lambda: now))
        await asyncio.sleep(0.1)
        loop.cancel()
        await asyncio.gather(loop, return_exceptions=True)

    run(five_ticks())
    assert state.starts == 1


def test_run_result_status():
    def result(uploaded, failed):
        return RunResult("a", "b", uploaded, 0, failed)

    failure = {"kind": "module", "item_id": "mod_1", "title": "X", "error": "No."}
    assert result([], []).status == "ok"
    assert result(["X"], [failure]).status == "partial"
    assert result([], [failure]).status == "failed"


LOCAL = datetime.now().astimezone().tzinfo


def at(hour: int, minute: int = 0, day: int = 26) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=LOCAL)


@pytest.mark.parametrize(
    ("time", "last", "now", "expected"),
    [
        pytest.param("04:00", None, at(3, 59), False, id="before the time"),
        pytest.param("04:00", at(4, 0, day=25), at(3, 59), False, id="before the time, run yesterday"),
        pytest.param("04:00", at(4, 0, day=25), at(4, 0), True, id="at the time, not yet run today"),
        pytest.param("04:00", at(4, 0, day=25), at(4, 1), True, id="after, not yet run today"),
        pytest.param("04:00", None, at(4, 1), True, id="after, never run"),
        pytest.param("04:00", at(4, 0), at(4, 1), False, id="after, already run"),
        pytest.param("04:00", at(3, 0), at(4, 1), True, id="after, run by hand before the time"),
        pytest.param("04:00", at(4, 0, day=24), at(9, 0), True, id="Delve down at 04:00, started at 09:00"),
        pytest.param("23:30", at(23, 30, day=25), at(9, 0), False, id="late time, run last night"),
        pytest.param("04:00", "2026-10-26T03:30:00+00:00", at(4, 1), None, id="a UTC time is compared as a time"),
    ],
)
def test_due(time, last, now, expected):
    last_at = last if isinstance(last, str) or last is None else last.isoformat()
    if expected is None:
        expected = datetime.fromisoformat(last_at) < at(4, 0)
    assert due(time, last_at, now) is expected


def test_due_takes_a_damaged_last_run_as_none():
    assert due("04:00", "yesterday", at(5)) is True
    assert due("04:00", "yesterday", at(3)) is False


def test_the_tick_is_a_minute():
    assert backup.TICK == 60
