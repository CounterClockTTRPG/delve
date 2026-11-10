"""The library (cloud storage Task 9): a module published to a shared store, listed, downloaded and deleted, by right.

Publishing never overwrites: each version is new objects, created only if they aren't there, so two installs
publishing the same entry at once end as two versions (Review Focus 4). An entry the listing can't read is left out
with a warning, never failing the whole tab (Review Focus 5). The store is a local folder; never a real call."""

import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from delve.cloud.library import (
    ENTRY_FORMAT,
    NotFromLibrary,
    UpToDate,
    check_updates,
    delete_entry,
    download,
    edited,
    list_entries,
    module_hash,
    publish,
    update,
)
from delve.cloud.store import ENTRY_LIMIT, MODULE_LIMIT, Exists, Listed, LocalStore, Missing, StoreError
from delve.config import Config
from delve.domain.modules import ModuleMap
from delve.storage import open_storage
from tests.cloud.test_bundles import CRYPT, HIDDEN

HERE = "ins_0123456789ab"
FRIEND = "ins_ba9876543210"


def clock(day: int):
    return lambda: datetime(2026, 10, day, 9, 30, tzinfo=UTC)


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def store(tmp_path):
    (tmp_path / "library").mkdir()
    return LocalStore(tmp_path / "library", create_only=True)


@pytest.fixture
def storage(tmp_path):
    opened = open_storage(Config(data_dir=tmp_path / "here"))
    yield opened
    opened.close()


@pytest.fixture
def friend(tmp_path):
    opened = open_storage(Config(data_dir=tmp_path / "friend"))
    yield opened
    opened.close()


def crypt(storage, title="The Crypt"):
    module = storage.modules.create(title, {"summary": "A crypt under the chapel."})
    return storage.modules.put_map(module.id, ModuleMap("crypt", "map", CRYPT, is_default=True))


def edit(storage, module):
    storage.modules.put_map(module.id, ModuleMap("crypt", "map", CRYPT + HIDDEN, is_default=True))


def publish_now(storage, store, module, *, right="publish", install=HERE, author="Raf", day=20):
    return run(publish(storage, store, right, module.id, author=author, install=install, now=clock(day)))


def names(store):
    return [listed.name for listed in run(store.list())]


def test_publish_creates_v1_with_author_and_dates(storage, store):
    module = crypt(storage)
    entry = publish_now(storage, store, module)
    assert entry.key.startswith("lib_") and len(entry.key) == 16
    assert (entry.version, entry.title, entry.summary, entry.author) == (1, "The Crypt", "A crypt under the chapel.", "Raf")
    assert entry.created_at == entry.updated_at == "2026-10-20T09:30:00+00:00"
    assert (entry.publisher, entry.format, entry.hash) == (HERE, ENTRY_FORMAT, module_hash(storage, module.id))
    assert names(store) == [f"{entry.key}/v1/entry.json", f"{entry.key}/v1/module.dscn"]
    assert entry.size == len(run(store.get(f"{entry.key}/v1/module.dscn")))
    stored = storage.modules.get(module.id)
    assert (stored.library_key, stored.library_version, stored.library_hash) == (entry.key, 1, entry.hash)
    assert (stored.library_origin, stored.library_author) == ("published", "Raf")
    assert stored.updated_at == module.updated_at, "recording the entry isn't an edit"
    assert run(list_entries(store)) == ([entry], [])


def test_the_hash_reads_no_picture_once_known_and_is_the_whole_exports(storage, monkeypatch):
    """DEL-163: `module_hash` is the hash of the whole export, as before, and once it is known for a module as it
    stands it is found again without reading a picture's bytes; a new picture, or a new banner, is a new hash."""
    from delve.cloud import library
    from delve.cloud.library import _hash
    from delve.modules.exporter import export_module
    from delve.modules.source import Attachment, ModuleSource
    from tests.modules.test_export_round_trip import PNG

    monkeypatch.setattr(library, "_HASHES", {})
    module = crypt(storage)
    picture = Attachment("plan", "image/png", storage.blobs.put(PNG, "image/png"), len(PNG), "The plan.", "gm")
    storage.module_sources.put(module.id, ModuleSource(attachments=[picture]))
    whole = _hash(export_module(storage, module.id))

    assert module_hash(storage, module.id) == whole
    reads = []
    real_get = storage.blobs.get
    monkeypatch.setattr(storage.blobs, "get", lambda sha: reads.append(sha) or real_get(sha))
    assert module_hash(storage, module.id) == whole
    assert reads == [], "a known module's pictures aren't read again"

    other = PNG + b"\0"
    storage.module_sources.put(
        module.id, ModuleSource(attachments=[replace(picture, sha256=storage.blobs.put(other, "image/png"), size=len(other))])
    )
    changed = module_hash(storage, module.id)
    assert changed != whole and changed == _hash(export_module(storage, module.id))

    # A banner changes without the module's time, and is in the export.
    storage.modules.set_banner(module.id, storage.blobs.put(PNG, "image/png"), "image/png", "uploaded")
    assert module_hash(storage, module.id) == _hash(export_module(storage, module.id)) != changed


def test_the_hash_is_the_same_for_an_unchanged_module(storage):
    module = crypt(storage)
    before = module_hash(storage, module.id)
    assert module_hash(storage, module.id) == before, "the export's random scenario id isn't hashed"
    edit(storage, module)
    assert module_hash(storage, module.id) != before


def test_publishing_again_after_an_edit_creates_v2_and_keeps_v1(storage, store):
    module = crypt(storage)
    first = publish_now(storage, store, module, day=20)
    edit(storage, module)
    second = publish_now(storage, store, module, author="Someone else", day=22)
    assert (second.key, second.version) == (first.key, 2)
    assert second.created_at == first.created_at and second.updated_at == "2026-10-22T09:30:00+00:00"
    assert second.author == "Raf", "the author is the entry's, set at its first publish"
    assert second.hash != first.hash
    assert f"{first.key}/v1/module.dscn" in names(store)
    assert json.loads(run(store.get(f"{first.key}/v1/entry.json")))["version"] == 1, "v1 is kept as it was"
    assert run(list_entries(store)) == ([second], []), "the listing shows the newest version only"
    assert storage.modules.get(module.id).library_version == 2


def test_an_unchanged_module_is_up_to_date(storage, store):
    module = crypt(storage)
    publish_now(storage, store, module)
    before = names(store)
    with pytest.raises(UpToDate):
        publish_now(storage, store, module)
    assert names(store) == before


def test_a_read_right_cannot_publish(storage, tmp_path):
    (tmp_path / "read").mkdir()
    store = LocalStore(tmp_path / "read", read_only=True)
    module = crypt(storage)
    with pytest.raises(PermissionError):
        publish_now(storage, store, module, right="read")
    assert names(store) == []
    assert storage.modules.get(module.id).library_key is None


def test_publish_right_cannot_add_a_version_to_anothers_entry_but_creates_its_own(storage, friend, store):
    theirs = publish_now(friend, store, crypt(friend), install=FRIEND, author="Ana")
    downloaded = run(download(storage, store, theirs.key))
    edit(storage, downloaded)
    mine = publish_now(storage, store, downloaded, author="Raf")
    assert mine.key != theirs.key and mine.version == 1
    assert (mine.author, mine.publisher) == ("Raf", HERE)
    assert storage.modules.get(downloaded.id).library_origin == "published"
    # A module that says it was published here, on an entry another install published (a restored install's
    # module, say): only a manager may add to that entry.
    restored = storage.modules.get(downloaded.id)
    storage.modules.set_library(restored.id, key=theirs.key, version=1, hash=restored.library_hash,
                                origin="published", author="Ana")
    with pytest.raises(PermissionError):
        publish_now(storage, store, restored)
    assert not [name for name in names(store) if name.startswith(f"{theirs.key}/v2/")]


def test_manage_can_add_a_version_to_any_entry_and_delete(storage, friend, tmp_path):
    (tmp_path / "managed").mkdir()
    store = LocalStore(tmp_path / "managed")
    theirs = publish_now(friend, store, crypt(friend), install=FRIEND, author="Ana")
    module = crypt(storage)
    storage.modules.set_library(module.id, key=theirs.key, version=1, hash=theirs.hash, origin="published",
                                author="Ana")
    edit(storage, module)
    second = publish_now(storage, store, module, right="manage")
    assert (second.key, second.version, second.author, second.publisher) == (theirs.key, 2, "Ana", HERE)

    with pytest.raises(PermissionError):
        run(delete_entry(store, "publish", theirs.key, None))
    run(delete_entry(store, "manage", theirs.key, 2))
    assert run(list_entries(store))[0] == [theirs], "v1 is the newest again"
    run(delete_entry(store, "manage", theirs.key, None))
    assert names(store) == [f"{theirs.key}/v1/deleted", f"{theirs.key}/v2/deleted"], "only the tombstones are left"
    assert run(list_entries(store)) == ([], [])
    with pytest.raises(Missing):
        run(delete_entry(store, "manage", theirs.key, None))


def test_a_deleted_versions_number_is_never_used_again(storage, friend, tmp_path):
    """Deleting v2 leaves a tombstone, `<key>/v2/deleted`, that is never removed: the next publish is v3, and an
    install that downloaded v2 is offered v3."""
    (tmp_path / "managed").mkdir()
    store = LocalStore(tmp_path / "managed")
    published = crypt(friend)
    publish_now(friend, store, published, install=FRIEND, author="Ana", day=20)
    edit(friend, published)
    second = publish_now(friend, store, published, install=FRIEND, author="Ana", day=21)
    module = run(download(storage, store, second.key))
    assert module.library_version == 2

    run(delete_entry(store, "manage", second.key, 2))
    assert f"{second.key}/v2/deleted" in names(store)
    assert not [name for name in names(store) if name.startswith(f"{second.key}/v2/") and "deleted" not in name]
    assert [entry.version for entry in run(list_entries(store))[0]] == [1]
    assert run(check_updates(storage, store)) == {}, "v1 is older than the v2 this install has"
    with pytest.raises(Missing):
        run(delete_entry(store, "manage", second.key, 2))

    friend.modules.put_map(published.id, ModuleMap("vault", "map", CRYPT, is_default=False))
    third = publish_now(friend, store, published, install=FRIEND, author="Ana", day=22)
    assert (third.key, third.version) == (second.key, 3)
    assert [entry.version for entry in run(list_entries(store))[0]] == [3]
    assert run(check_updates(storage, store)) == {module.id: 3}
    assert run(update(storage, store, module.id, keep_copy=False)).library_version == 3


def test_a_tombstoned_version_is_never_listed(storage, store):
    """A delete that stopped after its tombstone (the entry.json still there) has still deleted the version."""
    first = publish_now(storage, store, crypt(storage))
    run(store.create(f"{first.key}/v1/deleted", b""))
    assert run(list_entries(store)) == ([], [])
    with pytest.raises(Missing):
        run(download(storage, store, first.key))


class Racing(LocalStore):
    """A library where another install publishes the same version just before this one: its first create of a
    `module.dscn` finds `rival` objects put there first, and answers `Exists`, as a create-only store does."""

    def __init__(self, root, rival: dict[str, bytes]) -> None:
        super().__init__(root, create_only=True)
        self.rival = rival
        self.raced = False

    async def create(self, name, data):
        if not self.raced and name.endswith("/module.dscn"):
            self.raced = True
            for rival_name, rival_data in self.rival.items():
                await super().create(rival_name, rival_data)
        await super().create(name, data)


@pytest.mark.parametrize("rival_has_entry", [True, False], ids=["rival-done", "rival-midway"])
def test_two_publishes_at_once_take_the_next_number(storage, store, tmp_path, rival_has_entry):
    module = crypt(storage)
    first = publish_now(storage, store, module)
    edit(storage, module)
    rival_entry = {**json.loads(run(store.get(f"{first.key}/v1/entry.json"))), "version": 2, "publisher": FRIEND}
    rival = {f"{first.key}/v2/module.dscn": b"the rival's v2"}
    if rival_has_entry:
        rival[f"{first.key}/v2/entry.json"] = json.dumps(rival_entry).encode()
    racing = Racing(tmp_path / "library", rival)

    entry = publish_now(storage, racing, module, day=21)
    assert entry.version == 3
    assert run(racing.get(f"{first.key}/v2/module.dscn")) == b"the rival's v2", "never overwritten"
    assert f"{first.key}/v3/module.dscn" in names(racing)
    assert storage.modules.get(module.id).library_version == 3
    assert run(list_entries(racing))[0] == [entry]


def test_a_second_clash_gives_up_without_overwriting(storage, store, tmp_path):
    module = crypt(storage)
    first = publish_now(storage, store, module)
    edit(storage, module)

    class Crowded(LocalStore):
        async def create(self, name, data):
            raise Exists("That object is already there.")

    with pytest.raises(Exists):
        publish_now(storage, Crowded(tmp_path / "library"), module)
    assert storage.modules.get(module.id).library_version == 1
    assert names(store) == [f"{first.key}/v1/entry.json", f"{first.key}/v1/module.dscn"]


@pytest.mark.parametrize(
    "written",
    [b"{not json", b"[1, 2]", json.dumps({"format": ENTRY_FORMAT + 1}).encode(), b'{"format": 1, "title": 3}'],
    ids=["not-json", "not-an-object", "newer-format", "wrong-types"],
)
def test_a_malformed_or_newer_entry_is_skipped_with_a_warning(storage, store, tmp_path, written):
    good = publish_now(storage, store, crypt(storage))
    bad = "lib_0000deadbeef"
    run(store.create(f"{bad}/v1/module.dscn", b"zip"))
    run(store.create(f"{bad}/v1/entry.json", written))
    entries, warnings = run(list_entries(store))
    assert entries == [good]
    assert len(warnings) == 1 and bad in warnings[0]


class Lying(LocalStore):
    """A library whose listing gives the sizes in `sizes` (by name) instead of the objects' own, and that records each
    get's limit."""

    def __init__(self, root, sizes: dict[str, int] | None = None) -> None:
        super().__init__(root, create_only=True)
        self.sizes = sizes or {}
        self.gets: list[tuple[str, int | None]] = []

    async def list(self, prefix=""):
        listed = await super().list(prefix)
        return [Listed(item.name, self.sizes.get(item.name, item.size), item.modified) for item in listed]

    async def get(self, name, *, limit=None):
        self.gets.append((name, limit))
        return await super().get(name, limit=limit)


@pytest.mark.parametrize("listed_size", [ENTRY_LIMIT + 1, 10], ids=["listed-too-large", "listing-says-small"])
def test_an_entry_json_too_large_is_skipped_with_a_warning(storage, tmp_path, listed_size):
    (tmp_path / "library").mkdir()
    store = Lying(tmp_path / "library")
    good = publish_now(storage, store, crypt(storage))
    bad = "lib_0000deadbeef"
    run(store.create(f"{bad}/v1/module.dscn", b"zip"))
    run(store.create(f"{bad}/v1/entry.json", b" " * (ENTRY_LIMIT + 1)))
    store.sizes = {f"{bad}/v1/entry.json": listed_size}
    store.gets.clear()
    entries, warnings = run(list_entries(store))
    assert entries == [good]
    assert len(warnings) == 1 and bad in warnings[0]
    assert {limit for _, limit in store.gets} == {ENTRY_LIMIT}, "every entry.json is read within the limit"
    fetched = f"{bad}/v1/entry.json" in [name for name, _ in store.gets]
    assert fetched == (listed_size <= ENTRY_LIMIT), "one the listing says is too large isn't even fetched"


def test_a_module_dscn_is_read_within_the_limit_on_download_and_update(storage, friend, tmp_path):
    (tmp_path / "library").mkdir()
    store = Lying(tmp_path / "library")
    module = downloaded_with_a_newer_version(storage, friend, store)
    run(update(storage, store, module.id, keep_copy=False))
    reads = [(name.rsplit("/", 1)[-1], limit) for name, limit in store.gets]
    assert ("module.dscn", MODULE_LIMIT) in reads and ("module.dscn", None) not in reads
    assert {limit for file, limit in reads if file == "entry.json"} == {ENTRY_LIMIT}


def test_a_module_dscn_listed_too_large_is_not_fetched(storage, friend, tmp_path):
    (tmp_path / "library").mkdir()
    store = Lying(tmp_path / "library")
    module = downloaded_with_a_newer_version(storage, friend, store)
    store.sizes = {f"{module.library_key}/v2/module.dscn": MODULE_LIMIT + 1}
    store.gets.clear()
    with pytest.raises(StoreError):
        run(download(storage, store, module.library_key))
    with pytest.raises(StoreError):
        run(update(storage, store, module.id, keep_copy=False))
    assert not [name for name, _ in store.gets if name.endswith("module.dscn")]
    assert [m.id for m in storage.modules.list()] == [module.id]
    assert storage.modules.get(module.id).library_version == 1


def test_the_probes_objects_are_not_entries(storage, store):
    """A publish-only credential can't delete what its Test created; none of it is listed or warned about."""
    entry = publish_now(storage, store, crypt(storage))
    run(store.create(".delve-probe/0123456789abcdef", b"delve probe"))
    run(store.create(".delve-probe/lib_0000deadbeef/v1/entry.json", b"{not json"))
    assert run(list_entries(store)) == ([entry], [])


def test_a_version_without_its_entry_yet_is_not_listed(storage, store):
    entry = publish_now(storage, store, crypt(storage))
    run(store.create(f"{entry.key}/v2/module.dscn", b"still uploading"))
    assert run(list_entries(store)) == ([entry], [])


def test_entries_are_listed_newest_updated_first(storage, store):
    old = publish_now(storage, store, crypt(storage, "Old"), day=10)
    new = publish_now(storage, store, crypt(storage, "New"), day=12)
    assert run(list_entries(store))[0] == [new, old]


def test_download_makes_a_local_module_remembering_its_entry(storage, friend, store):
    published = crypt(friend)
    edit(friend, published)
    entry = publish_now(friend, store, published, install=FRIEND, author="Ana")
    module = run(download(storage, store, entry.key))
    assert module.id != published.id
    assert module.title == "The Crypt"
    assert {m.name: m.source for m in module.maps}["crypt"] == CRYPT + HIDDEN
    assert (module.library_key, module.library_version, module.library_origin) == (entry.key, 1, "downloaded")
    assert module.library_author == "Ana"
    assert module.library_hash == module_hash(storage, module.id), "what was downloaded, so an edit shows"
    assert module.library_hash == entry.hash, "the export of the import is the published module"
    edit(storage, module)
    storage.modules.put_map(module.id, ModuleMap("crypt", "map", CRYPT, is_default=True))
    assert module_hash(storage, module.id) != module.library_hash


def test_download_of_an_unknown_entry_is_missing(storage, store):
    with pytest.raises(Missing):
        run(download(storage, store, "lib_000000000000"))
    assert storage.modules.list() == []


# Updates from the library (Task 10): a downloaded module whose entry has a newer version shows it, and Update makes
# that version a new revision of the same module, leaving every campaign on the revision it pinned.


def downloaded_with_a_newer_version(storage, friend, store):
    """Ana's crypt downloaded here at v1, then Ana publishing v2 with the hidden room."""
    published = crypt(friend)
    entry = publish_now(friend, store, published, install=FRIEND, author="Ana", day=20)
    module = run(download(storage, store, entry.key))
    edit(friend, published)
    publish_now(friend, store, published, install=FRIEND, author="Ana", day=22)
    return module


def test_a_newer_version_shows_on_the_module(storage, friend, store):
    published = crypt(friend)
    entry = publish_now(friend, store, published, install=FRIEND, author="Ana")
    module = run(download(storage, store, entry.key))
    mine = crypt(storage, "My own")
    publish_now(storage, store, mine)
    assert run(check_updates(storage, store)) == {}
    edit(friend, published)
    publish_now(friend, store, published, install=FRIEND, author="Ana", day=22)
    assert run(check_updates(storage, store)) == {module.id: 2}, "only downloaded modules, not ones published here"


def test_update_makes_a_new_revision_and_campaigns_stay_on_theirs(storage, friend, store):
    module = downloaded_with_a_newer_version(storage, friend, store)
    pinned = storage.revisions.snapshot(module.id)
    campaign = storage.campaigns.create("Tuesday", module.id, pinned.number, ruleset="osric", setting="greyhawk")

    updated = run(update(storage, store, module.id, keep_copy=False))

    assert updated.id == module.id and updated.head_revision == pinned.number + 1
    assert {m.name: m.source for m in updated.maps}["crypt"] == CRYPT + HIDDEN
    assert (updated.library_version, updated.library_origin, updated.library_author) == (2, "downloaded", "Ana")
    assert updated.library_hash == module_hash(storage, module.id) and not edited(storage, updated)
    assert storage.campaigns.get(campaign.id).revision == pinned.number, "the campaign stays on its revision"
    kept = storage.revisions.get(module.id, pinned.number)
    assert {m.name: m.source for m in kept.maps}["crypt"] == CRYPT, "its revision is unchanged"
    assert [m.id for m in storage.modules.list()] == [module.id], "the scratch module is gone"
    assert run(check_updates(storage, store)) == {}
    with pytest.raises(UpToDate):
        run(update(storage, store, module.id, keep_copy=False))


def test_an_edited_copy_is_flagged_edited(storage, friend, store):
    module = downloaded_with_a_newer_version(storage, friend, store)
    assert not edited(storage, storage.modules.get(module.id))
    storage.modules.put_map(module.id, ModuleMap("crypt", "map", CRYPT + HIDDEN, is_default=True))
    assert edited(storage, storage.modules.get(module.id))


def test_keep_copy_keeps_the_local_version_as_its_own_module(storage, friend, store):
    module = downloaded_with_a_newer_version(storage, friend, store)
    storage.modules.put_map(module.id, ModuleMap("vault", "map", CRYPT, is_default=False))

    updated = run(update(storage, store, module.id, keep_copy=True))

    assert "vault" not in {m.name for m in updated.maps}, "the edit is replaced by the library's version"
    copies = [m for m in storage.modules.list() if m.id != module.id]
    assert len(copies) == 1
    copy = copies[0]
    assert copy.title == "The Crypt (my version)"
    assert {"crypt", "vault"} <= {m.name for m in copy.maps}, "the copy keeps the local edits"
    assert {m.name: m.source for m in copy.maps}["crypt"] == CRYPT
    assert copy.library_key is None, "the copy is a module of its own, not the entry's"


def test_a_module_not_from_the_library_cannot_be_updated(storage, store):
    mine = crypt(storage)
    with pytest.raises(NotFromLibrary):
        run(update(storage, store, mine.id, keep_copy=False))
    publish_now(storage, store, mine)
    with pytest.raises(NotFromLibrary):
        run(update(storage, store, mine.id, keep_copy=False))


def test_a_failed_update_changes_nothing(storage, friend, store, monkeypatch):
    module = downloaded_with_a_newer_version(storage, friend, store)
    storage.revisions.snapshot(module.id)
    before = storage.modules.get(module.id)

    def refuse(module_id):
        raise RuntimeError("the disk is full")

    monkeypatch.setattr(storage.revisions, "snapshot", refuse)
    with pytest.raises(RuntimeError):
        run(update(storage, store, module.id, keep_copy=True))
    assert [m.id for m in storage.modules.list()] == [module.id], "neither the scratch nor the copy is left"
    assert storage.modules.get(module.id) == before


def test_updates_are_checked_at_start_and_at_each_days_backup_time(storage, monkeypatch):
    from types import SimpleNamespace

    from delve.cloud import library

    checks, times = [], iter(
        [
            datetime(2026, 10, 20, 9, 0).astimezone(),  # at start: checked
            datetime(2026, 10, 20, 10, 0).astimezone(),  # the same day, after 04:00: not again
            datetime(2026, 10, 21, 3, 0).astimezone(),  # the next day, before 04:00: not yet
            datetime(2026, 10, 21, 4, 1).astimezone(),  # past 04:00: checked
        ]
    )
    now = next(times)

    async def refresh(state):
        checks.append(now)

    def clock():
        return now

    async def go():
        nonlocal now
        task = asyncio.create_task(library.updates_loop(SimpleNamespace(state=state), tick=0, now=clock))
        for moment in [None, *times]:
            if moment is not None:
                now = moment
            for _ in range(3):
                await asyncio.sleep(0)
        task.cancel()

    state = SimpleNamespace(storage=storage)
    monkeypatch.setattr(library, "refresh_updates", refresh)
    run(go())
    assert [at.day for at in checks] == [20, 21]
