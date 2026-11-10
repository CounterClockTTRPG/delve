"""The object store seam (cloud storage plan Task 1): the local-folder store that backs the tests, and the probe that
reads a credential's right from what it can do (list; create; overwrite; delete), leaving no probe object behind."""

import asyncio

import pytest

from delve.cloud.store import ENTRY_LIMIT, MODULE_LIMIT, Exists, LocalStore, Missing, StoreError, probe


def run(coro):
    return asyncio.run(coro)


def test_create_refuses_an_existing_object(tmp_path):
    store = LocalStore(tmp_path)
    run(store.create("a/b.txt", b"one"))
    with pytest.raises(Exists):
        run(store.create("a/b.txt", b"two"))
    assert run(store.get("a/b.txt")) == b"one"


def test_put_overwrites(tmp_path):
    store = LocalStore(tmp_path)
    run(store.put("x", b"one"))
    run(store.put("x", b"two"))
    assert run(store.get("x")) == b"two"


def test_list_by_prefix_is_sorted_by_name(tmp_path):
    store = LocalStore(tmp_path)
    for name in ("m/b", "m/a", "m/c/d", "n/z"):
        run(store.put(name, b"12345"))
    listed = run(store.list("m/"))
    assert [item.name for item in listed] == ["m/a", "m/b", "m/c/d"]
    assert all(item.size == 5 and item.modified for item in listed)
    assert [item.name for item in run(store.list())] == ["m/a", "m/b", "m/c/d", "n/z"]


def test_get_of_a_missing_object_raises_missing(tmp_path):
    store = LocalStore(tmp_path)
    with pytest.raises(Missing):
        run(store.get("nothing"))
    with pytest.raises(Missing):
        run(store.delete("nothing"))


@pytest.mark.parametrize("name", ["../x", "/x", "a/../../x"])
def test_a_name_escaping_the_root_is_refused(tmp_path, name):
    store = LocalStore(tmp_path / "root")
    for call in (store.get(name), store.put(name, b"x"), store.create(name, b"x"), store.delete(name)):
        with pytest.raises(StoreError):
            run(call)
    assert not (tmp_path / "x").exists()


@pytest.mark.parametrize(
    ("options", "right"),
    [({"read_only": True}, "read"), ({"create_only": True}, "publish"), ({}, "manage")],
)
def test_probe_gives_each_right(tmp_path, options, right):
    store = LocalStore(tmp_path, **options)
    assert run(probe(store)) == right
    assert run(LocalStore(tmp_path).list(".delve-probe/")) == []


def test_probe_of_a_store_that_cannot_list_is_none(tmp_path):
    assert run(probe(LocalStore(tmp_path / "absent"))) is None


def test_get_past_its_limit_is_refused(tmp_path):
    store = LocalStore(tmp_path)
    run(store.put("big", b"x" * 11))
    assert run(store.get("big", limit=11)) == b"x" * 11
    with pytest.raises(StoreError) as caught:
        run(store.get("big", limit=10))
    assert str(caught.value) == "It is larger than Delve takes."
    with pytest.raises(Missing):
        run(store.get("nothing", limit=10))


def test_the_limits_are_64_kib_and_64_mib():
    assert ENTRY_LIMIT == 64 * 1024
    assert MODULE_LIMIT == 64 * 1024 * 1024


def test_the_folder_is_read_and_written_off_the_event_loop(tmp_path, monkeypatch):
    """The store is used from the event loop (DEL-172): the folder's files are read and written in a thread."""
    import threading

    from delve.cloud import store as store_module

    threads = []
    write, replace = LocalStore._create, store_module.os.replace

    def recording_create(self, name, data):
        threads.append(threading.current_thread())
        return write(self, name, data)

    def recording_replace(*args):
        threads.append(threading.current_thread())
        return replace(*args)

    monkeypatch.setattr(LocalStore, "_create", recording_create)
    monkeypatch.setattr(store_module.os, "replace", recording_replace)

    async def run():
        store = LocalStore(tmp_path)
        await store.create("a/one", b"1")
        await store.put("a/one", b"2")
        return await store.get("a/one"), [item.name for item in await store.list()]

    assert asyncio.run(run()) == (b"2", ["a/one"])
    assert len(threads) == 2 and threading.main_thread() not in threads
