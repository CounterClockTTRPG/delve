import os
import re
import socket
import sqlite3
import subprocess
import sys
import time

import httpx
import pytest

from delve.__main__ import main
from delve.config import Config
from delve.modules.dscn import Bundle
from delve.storage import migrate
from tests.fixtures import SAMPLES
from tests.fixtures.rulesets import install_test_packs

CRYPT = SAMPLES / "scenarios" / "crypt-of-saint-vellis"


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_serve_starts_without_reference_db(config_with_osric):
    """No reference.db is no hindrance: the app answers, and OSRIC, installed as a pack, is there to play (AD&D 2e,
    which reads that file, isn't offered)."""
    from fastapi.testclient import TestClient

    from delve.__main__ import build_registries
    from delve.storage import open_storage
    from delve.web.app import create_app

    config = config_with_osric
    storage = open_storage(config)
    try:
        app = create_app(config, storage, build_registries(config, storage=storage))
        with TestClient(app, base_url="http://localhost:7810", client=("127.0.0.1", 50000)) as local:
            assert local.get("/api/health").status_code == 200
            ids = [r["id"] for r in local.get("/api/rulesets").json()]
        assert "osric" in ids and "adnd2e" not in ids
    finally:
        storage.close()


def test_serve_port_in_use_exits_2(reference_config, monkeypatch, capsys):
    monkeypatch.setenv("DELVE_DATA_DIR", str(reference_config.data_dir))
    with socket.socket() as taken:
        taken.bind(("0.0.0.0", 0))
        taken.listen()
        port = taken.getsockname()[1]
        assert main(["serve", "--port", str(port)]) == 2
    assert f"Port {port} is in use; start with --port <other>" in capsys.readouterr().err


def test_serve_leaves_the_house_rules_as_they_are(reference_config, monkeypatch, capsys):
    """Plan "Open fixes" Decision 7: a fresh start leaves the library empty, and a library that has rules keeps them
    as they are; the example is imported only on request."""
    from delve.play.house_rules import SEED_DIR, import_house_rules
    from delve.storage import open_storage

    monkeypatch.setenv("DELVE_DATA_DIR", str(reference_config.data_dir))
    with socket.socket() as taken:  # stop serve after it has started up, at the bind
        taken.bind(("0.0.0.0", 0))
        taken.listen()
        port = str(taken.getsockname()[1])
        assert main(["serve", "--port", port]) == 2
        storage = open_storage(reference_config)
        try:
            assert storage.house_rules.list() == [] and storage.house_rule_bundles.list() == []
            bundle = import_house_rules(storage, SEED_DIR)
            [first, *_] = storage.house_rules.list()
            storage.house_rules.delete(first.id)
            before = (storage.house_rules.list(), storage.house_rule_bundles.list())
        finally:
            storage.close()
        assert main(["serve", "--port", port]) == 2
    storage = open_storage(reference_config)
    try:
        assert (storage.house_rules.list(), storage.house_rule_bundles.list()) == before
        assert len(before[0]) == 3 and [b.id for b in before[1]] == [bundle.id]
    finally:
        storage.close()


def test_serve_schema_too_new_exits_3(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DELVE_DATA_DIR", str(tmp_path))
    migrate(Config(data_dir=tmp_path))
    with sqlite3.connect(tmp_path / "delve.db") as db:
        db.execute("UPDATE alembic_version SET version_num = '9999_future'")
    assert main(["serve", "--port", str(free_port())]) == 3
    err = capsys.readouterr().err
    assert "9999_future" in err
    assert "Upgrade Delve" in err


def test_migrate_prints_head(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DELVE_DATA_DIR", str(tmp_path / "new"))
    assert main(["migrate"]) == 0
    head = capsys.readouterr().out.strip()
    with sqlite3.connect(tmp_path / "new" / "delve.db") as db:
        assert db.execute("SELECT version_num FROM alembic_version").fetchone() == (head,)


@pytest.mark.slow
def test_serve_smoke(tmp_path):
    install_test_packs(Config(data_dir=tmp_path).packs_dir)
    port = free_port()
    env = {**os.environ, "DELVE_DATA_DIR": str(tmp_path)}
    process = subprocess.Popen(
        [sys.executable, "-m", "delve", "serve", "--host", "127.0.0.1", "--port", str(port)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        base = f"http://127.0.0.1:{port}"
        deadline = time.monotonic() + 10
        health = None
        while time.monotonic() < deadline:
            try:
                health = httpx.get(f"{base}/api/health", timeout=1)
                break
            except httpx.TransportError:
                assert process.poll() is None, process.stdout.read()
                time.sleep(0.1)
        assert health is not None, "delve serve did not answer within 10 s"
        assert health.json()["ok"] is True
        assert httpx.get(f"{base}/", timeout=2).status_code == 200
        with httpx.Client(base_url=base, timeout=10) as client:
            assert client.get("/api/house-rule-bundles").json() == []
            walk_the_maps_flow(client)
    finally:
        process.terminate()
        output, _ = process.communicate(timeout=10)
    assert f"http://localhost:{port}/" in output


def walk_the_maps_flow(client: httpx.Client) -> None:
    """Plateau 1 end to end: import the sample, split two characters, compare their views and the DM view."""
    imported = client.post(
        "/api/modules/import", content=Bundle.load(CRYPT).to_zip(), headers={"Content-Type": "application/zip"}
    )
    assert imported.status_code == 201, imported.text
    module = imported.json()
    crypt = next(m["name"] for m in module["maps"] if m["is_default"])

    campaign = client.post("/api/campaigns", json={"name": "Smoke", "module_id": module["id"]}).json()
    detail = client.get(f"/api/campaigns/{campaign['id']}").json()
    assert detail["maps"] == [crypt]
    ana, bo = (
        client.post(f"/api/campaigns/{campaign['id']}/characters", json={"name": name}).json()["id"]
        for name in ("Ana", "Bo")
    )
    state = f"/api/campaigns/{campaign['id']}/maps/{crypt}"
    assert client.post(f"{state}/start", json={"characters": [ana, bo]}).status_code == 200
    for characters, to in (
        ([ana, bo], "room.entry_hall"),
        ([bo], "corridor.main_hall"),
        ([bo], "room.throne_chamber"),
        ([ana], "room.vestry_alcove"),  # down the chute
    ):
        assert client.post(f"{state}/move", json={"characters": characters, "to": to}).status_code == 200

    ana_view = client.get(f"{state}/view", params={"characters": ana}).json()["svg"]
    bo_view = client.get(f"{state}/view", params={"characters": bo}).json()["svg"]
    assert ana_view != bo_view
    dm_view = client.get(f"{state}/dm-view").json()["svg"]
    discs = re.findall(r'<g class="party" data-node="([^"]*)"', dm_view)
    assert sorted(discs) == ["room.throne_chamber", "room.vestry_alcove"]

    editor = client.get(f"/maps/{module['id']}/{crypt}")
    assert editor.status_code == 200
    assert editor.headers["content-type"].startswith("text/html")
