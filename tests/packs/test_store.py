from __future__ import annotations

import gzip
import hashlib
import sqlite3
from pathlib import Path

import pytest

from delve.packs.store import SnapshotCorrupt, load_snapshots, open_pack_db


def _snapshot(folder: Path, files: dict[str, str]) -> Path:
    folder.mkdir()
    sums = []
    for name, text in files.items():
        raw = gzip.compress(text.encode())
        (folder / name).write_bytes(raw)
        sums.append(f"{hashlib.sha256(raw).hexdigest()}  {name}")
    (folder / "SHA256SUMS").write_text("\n".join(sums) + "\n")
    return folder


@pytest.fixture
def data(tmp_path: Path) -> Path:
    return _snapshot(
        tmp_path / "data",
        {
            "base.sql.gz": "CREATE TABLE pages (id INTEGER PRIMARY KEY, title TEXT, body TEXT);",
            "more.sql.gz": "INSERT INTO pages (title, body) VALUES ('Orcs', 'Orcs raid the roads'), ('Elves', 'Elves sing');",
            "tables.json.gz": '{"a": [1, 2]}',
        },
    )


def test_loads_sql_json_and_fts(tmp_path, data):
    db = tmp_path / "out" / "pack.db"
    sha = load_snapshots(
        data, db, ["base.sql.gz", "more.sql.gz"], {"tables.json.gz": "tables"}, {"pages": ("title", "body")}
    )
    assert sha == hashlib.sha256((data / "SHA256SUMS").read_bytes()).hexdigest()
    conn = open_pack_db(db)
    assert conn.execute("SELECT count(*) FROM pages").fetchone() == (2,)
    assert conn.execute("SELECT data FROM tables WHERE id = 1").fetchone() == ('{"a": [1, 2]}',)
    assert conn.execute("SELECT title FROM pages_fts WHERE pages_fts MATCH 'raiding'").fetchall() == [("Orcs",)]
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("DELETE FROM pages")
    conn.close()


def test_refuses_a_snapshot_not_in_the_sums(tmp_path, data):
    (data / "SHA256SUMS").write_text(
        "\n".join(line for line in (data / "SHA256SUMS").read_text().splitlines() if "more.sql" not in line)
    )
    with pytest.raises(SnapshotCorrupt, match="more.sql.gz"):
        load_snapshots(data, tmp_path / "pack.db", ["base.sql.gz", "more.sql.gz"], {})
    assert not (tmp_path / "pack.db").exists()


def test_a_failed_build_leaves_no_db(tmp_path):
    data = _snapshot(tmp_path / "data", {"bad.sql.gz": "THIS IS NOT SQL;"})
    db = tmp_path / "pack.db"
    with pytest.raises(sqlite3.Error):
        load_snapshots(data, db, ["bad.sql.gz"], {})
    assert list(tmp_path.glob("*.db*")) == [] and list(tmp_path.glob(".*building")) == []
