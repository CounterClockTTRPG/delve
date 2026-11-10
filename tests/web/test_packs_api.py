"""The packs in the web (DEL-366): listed for the organisers, downloaded as `.delvepack` files; installed, updated and
removed by the owner alone, used once Delve restarts, which the owner can ask for when systemd runs it; and a setting's
additions exported and imported by an organiser."""

import io
import shutil
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from delve.domain.setting_content import SettingAddition
from delve.packs import loader
from delve.packs.transit import build_pack, install_pack
from delve.web.routes import packs as packs_routes
from tests.web.conftest import BASE_URL, make_account, session_for

FIXTURES = Path(__file__).parent.parent / "fixtures" / "packs"
ZIP = {"Content-Type": "application/zip"}


@pytest.fixture
def packs_dir(tmp_path, monkeypatch):
    """A packs folder of the test's own, with the test ruleset installed: never the shared test packs."""
    folder = tmp_path / "own-packs"
    install_pack(FIXTURES / "test-ruleset", folder)
    monkeypatch.setattr(packs_routes, "_packs_dir", lambda request: folder)
    yield folder
    loader.reset()


@pytest.fixture
def organiser(app, storage):
    """A browser of an organiser's account: not the owner."""
    account = make_account(storage, "orla", organiser=True)
    with TestClient(app, base_url=BASE_URL) as client:
        session_for(storage, account, client)
        yield client


def delvepack(tmp_path: Path, version: str) -> bytes:
    source = tmp_path / f"src-{version}"
    shutil.copytree(FIXTURES / "test-ruleset", source)
    manifest = source / "pack.toml"
    manifest.write_text(manifest.read_text().replace('version = "1.0.0"', f'version = "{version}"'))
    return build_pack(source, tmp_path / f"out-{version}").read_bytes()


def test_the_packs_are_listed_and_downloaded(local, organiser, packs_dir):
    listed = organiser.get("/api/packs")
    assert listed.status_code == 200
    body = listed.json()
    assert [(p["id"], p["kind"], p["version"]) for p in body["packs"]] == [("test-ruleset", "ruleset", "1.0.0")]
    assert body["packs"][0]["active"] is False, "installed after this Delve started"
    assert body["can_install"] is False and local.get("/api/packs").json()["can_install"] is True
    assert body["restart"]["needed"] is True and body["restart"]["possible"] is False
    assert "osric" in body["removed"], "loaded at the start, not in this folder"

    download = organiser.get("/api/packs/test-ruleset/download")
    assert download.status_code == 200
    assert download.headers["content-disposition"] == 'attachment; filename="test-ruleset-1.0.0.delvepack"'
    names = zipfile.ZipFile(io.BytesIO(download.content)).namelist()
    assert names[:2] == ["pack.toml", "MANIFEST"] and "pack.db" not in names
    assert organiser.get("/api/packs/nope/download").status_code == 404


def test_the_owner_installs_updates_and_removes(local, organiser, packs_dir, tmp_path, storage):
    newer = delvepack(tmp_path, "2.0.0")
    refused = organiser.post("/api/packs", content=newer, headers=ZIP)
    assert refused.status_code == 403, "a pack runs code on the server: the owner's alone"
    put = local.post("/api/packs", content=newer, headers=ZIP)
    assert put.status_code == 201, put.text
    assert put.json()["pack"]["version"] == "2.0.0" and put.json()["restart"]["needed"] is True
    assert local.post("/api/packs", content=b"not a zip", headers=ZIP).status_code == 422
    assert local.post("/api/packs", content=newer, headers={"Content-Type": "text/plain"}).status_code == 415

    module = storage.modules.create("M")
    revision = storage.revisions.snapshot(module.id)
    storage.campaigns.create("Uses it", module.id, revision.number, ruleset="test-ruleset", setting="")
    assert organiser.request("DELETE", "/api/packs/test-ruleset", json={}).status_code == 403
    in_use = local.request("DELETE", "/api/packs/test-ruleset", json={})
    assert in_use.status_code == 409 and in_use.json()["campaigns"] == ["Uses it"]
    assert local.request("DELETE", "/api/packs/test-ruleset?force=true", json={}).status_code == 200
    assert local.get("/api/packs").json()["packs"] == []
    assert local.request("DELETE", "/api/packs/test-ruleset", json={}).status_code == 404


def test_a_restart_is_asked_for_only_where_delve_can(app, local, organiser, packs_dir):
    refused = local.post("/api/restart", json={})
    assert refused.status_code == 409 and "restart it as you started it" in refused.json()["error"]
    stopped: list[bool] = []
    app.state.restart = lambda: stopped.append(True)
    assert organiser.post("/api/restart", json={}).status_code == 403
    assert local.get("/api/packs").json()["restart"]["possible"] is True
    answer = local.post("/api/restart", json={})
    assert answer.status_code == 202 and answer.json() == {"restarting": True, "beats": [], "conversion": None}


def test_an_organiser_exports_and_imports_a_settings_additions(organiser, storage, lan):
    storage.setting_pages.put(SettingAddition("greyhawk", "Hommlet", text="A village."))
    exported = organiser.get("/api/settings/greyhawk/additions/export")
    assert exported.status_code == 200
    assert exported.headers["content-disposition"] == 'attachment; filename="greyhawk-additions.zip"'
    storage.setting_pages.delete("greyhawk", "Hommlet")
    imported = organiser.post("/api/settings/greyhawk/additions", content=exported.content, headers=ZIP)
    assert imported.status_code == 200, imported.text
    assert imported.json()["imported"]["pages_added"] == 1
    assert storage.setting_pages.get("greyhawk", "Hommlet").text == "A village."
    again = organiser.post("/api/settings/greyhawk/additions?keep=false", content=exported.content, headers=ZIP)
    assert again.json()["imported"]["pages_replaced"] == 1
    wrong = organiser.post("/api/settings/forgotten-realms/additions", content=exported.content, headers=ZIP)
    assert wrong.status_code == 422 and "not of 'forgotten-realms'" in wrong.json()["error"]
    assert organiser.get("/api/settings/nowhere/additions/export").status_code == 404
    assert lan.get("/api/settings/greyhawk/additions/export").status_code == 401
