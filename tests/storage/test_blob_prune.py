"""Pruning the blob store (DEL-36): a blob goes when no text of any row names it and it is older than the grace
period; a running job's blobs, a day's blobs and every named one stay; a blob put again while a prune runs keeps its
file."""

import os
import time
from datetime import UTC, datetime, timedelta
from unittest import mock

import pytest
from sqlalchemy import update

from delve.__main__ import main
from delve.config import Config
from delve.domain.accounts import Profile
from delve.storage import open_storage
from delve.storage.sqlite import blobs as blob_module
from delve.storage.sqlite.tables import blobs, conversions

DAY = timedelta(days=1)
LONG_AGO = datetime(2026, 1, 1, tzinfo=UTC)


@pytest.fixture
def config(tmp_path):
    return Config(data_dir=tmp_path / "data")


@pytest.fixture
def storage(config):
    storage = open_storage(config)
    yield storage
    storage.close()


def old(storage, sha: str) -> str:
    """Make the blob look put long ago: its row's time and its file's."""
    with storage.engine.begin() as connection:
        connection.execute(update(blobs).where(blobs.c.sha256 == sha).values(created_at=LONG_AGO.isoformat()))
    path = storage.blobs._path(sha)
    os.utime(path, (LONG_AGO.timestamp(), LONG_AGO.timestamp()))
    return sha


def put_old(storage, data: bytes, mime: str = "image/png") -> str:
    return old(storage, storage.blobs.put(data, mime))


def test_a_blob_nothing_names_goes_and_every_named_one_stays(storage):
    module = storage.modules.create("The Sunken Shrine")
    linked = put_old(storage, b"bundle")
    storage.blobs.link(module.id, "source-bundle", linked)
    banner = put_old(storage, b"banner")
    storage.modules.set_banner(module.id, banner, "image/png", "uploaded")
    loose = put_old(storage, b"a picture the QA replaced")
    fresh = storage.blobs.put(b"just painted", "image/png")

    found = storage.blobs.unused(DAY)
    assert [blob.sha for blob in found.blobs] == [loose] and found.kept == 1
    assert found.blobs[0].mime == "image/png" and found.size == len(b"a picture the QA replaced")
    assert storage.blobs.exists(loose), "a dry run deletes nothing"

    gone = storage.blobs.prune(DAY)
    assert [blob.sha for blob in gone.blobs] == [loose]
    assert not storage.blobs.exists(loose) and not storage.blobs._path(loose).exists()
    for sha in (linked, banner, fresh):
        assert storage.blobs.get(sha) is not None
    assert storage.blobs.unused(DAY).blobs == []


def test_a_sha_in_json_or_any_text_keeps_its_blob(storage):
    avatar = put_old(storage, b"an avatar")
    tile = put_old(storage, b"a tile", "image/jpeg")
    storage.accounts.create("ana", Profile("Ana", avatar_sha=avatar))
    storage.settings.save({"notes": f"tiles: {{'0/0/0': '{tile}'}}"})
    assert storage.blobs.unused(DAY).blobs == []


def test_a_running_job_keeps_what_it_put_since_it_started(storage):
    before = put_old(storage, b"from before the job")
    during = put_old(storage, b"a conversion's picture")
    started = datetime.now(UTC) - timedelta(days=3)
    job = storage.conversions.create("pdf", "Book", "ready")
    with storage.engine.begin() as connection:
        connection.execute(update(conversions).where(conversions.c.id == job.id).values(created_at=started.isoformat()))
        connection.execute(update(blobs).where(blobs.c.sha256 == during).values(created_at=(started + DAY).isoformat()))
    os.utime(storage.blobs._path(during), ((started + DAY).timestamp(),) * 2)
    found = storage.blobs.unused(DAY)
    assert [blob.sha for blob in found.blobs] == [before] and found.kept == 1


def test_a_file_without_its_row_and_an_old_temporary_go(storage):
    kept = put_old(storage, b"kept")
    storage.blobs.link(storage.modules.create("M").id, "attachment", kept)
    stray = "ab" * 32
    path = storage.blobs._path(stray)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"a refused restore's picture")
    os.utime(path, (LONG_AGO.timestamp(), LONG_AGO.timestamp()))
    temp = path.parent / ".tmp-crashed"
    temp.write_bytes(b"half")
    os.utime(temp, (LONG_AGO.timestamp(), LONG_AGO.timestamp()))
    new_temp = path.parent / ".tmp-writing"
    new_temp.write_bytes(b"being written")

    found = storage.blobs.prune(DAY)
    assert [(blob.sha, blob.mime, blob.size) for blob in found.blobs] == [(stray, None, 27)]
    assert not path.exists() and not temp.exists() and new_temp.exists()
    assert storage.blobs.get(kept) == b"kept"


def test_a_blob_put_again_while_a_prune_runs_keeps_its_file(storage):
    """The prune deletes the row and the file between `put`'s look for the file and its row: `put` writes it again."""
    data = b"put again"
    sha = put_old(storage, data)
    insert = blob_module.SqliteBlobStore._insert

    def pruned_first(self, *args):
        assert [blob.sha for blob in self.prune(timedelta(0)).blobs] == [sha]
        insert(self, *args)

    with mock.patch.object(blob_module.SqliteBlobStore, "_insert", pruned_first):
        assert storage.blobs.put(data, "image/png") == sha
    assert storage.blobs.get(sha) == data


def test_put_file_while_a_prune_runs_keeps_its_file(storage, tmp_path):
    book = tmp_path / "book.pdf"
    book.write_bytes(b"%PDF a book")
    sha = put_old(storage, book.read_bytes(), "application/pdf")
    insert = blob_module.SqliteBlobStore._insert

    def pruned_first(self, *args):
        self.prune(timedelta(0))
        insert(self, *args)

    with mock.patch.object(blob_module.SqliteBlobStore, "_insert", pruned_first):
        assert storage.blobs.put_file(book, "application/pdf") == sha
    assert storage.blobs.get(sha) == book.read_bytes()


def test_put_again_marks_an_old_blob_new(storage):
    sha = put_old(storage, b"again")
    storage.blobs.put(b"again", "image/png")
    assert storage.blobs.unused(DAY).kept == 1
    assert time.time() - storage.blobs._path(sha).stat().st_mtime < 60


def test_the_command_lists_then_deletes(config, storage, monkeypatch, capsys):
    monkeypatch.setenv("DELVE_DATA_DIR", str(config.data_dir))
    loose = put_old(storage, b"loose")
    thumb = config.data_dir / "thumbs" / f"{loose}-800.webp"
    thumb.parent.mkdir(parents=True)
    thumb.write_bytes(b"card")

    assert main(["blobs", "prune"]) == 0
    out = capsys.readouterr().out
    assert loose in out and "run again with --delete" in out
    assert storage.blobs.exists(loose)

    assert main(["blobs", "prune", "--delete"]) == 0
    assert "Deleted 1 files nothing used" in capsys.readouterr().out
    assert not storage.blobs.exists(loose) and not thumb.exists()

    assert main(["blobs", "prune", "--grace-hours", "-1"]) == 2
