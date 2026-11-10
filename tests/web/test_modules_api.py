import io
import threading
import time
import zipfile
from dataclasses import replace

import pytest

from delve.modules.dscn import VERSION, Bundle
from delve.modules.source import load_source, save_source
from delve.web.guard import UPLOAD_LIMIT
from delve.web.routes.module_source import editing
from tests.fixtures import SAMPLES
from tests.web.test_preferences_api import published

CRYPT = SAMPLES / "scenarios" / "crypt-of-saint-vellis"
ZIP = {"Content-Type": "application/zip"}
GOOD_MAP = 'map "Two rooms" {\n  grid { bounds 20 x 10 }\n}\n\nroom "a" {\n  rect 1,1 4 x 4\n}\n'
BROKEN_MAP = 'map "Broken" {\n  grid { bounds 20 x 10 }\n}\n\nroom "a" {\n  rect 1,1 4 x 4 @\n}\n'


def crypt_zip() -> bytes:
    return Bundle.load(CRYPT).to_zip()


def create(local, title="Keep") -> dict:
    response = local.post("/api/modules", json={"title": title})
    assert response.status_code == 201
    return response.json()


def put_source(local, module_id, name, source, **extra):
    return local.put(f"/api/modules/{module_id}/maps/{name}", json={"source": source, **extra})


def blob_files(config) -> list:
    root = config.data_dir / "blobs"
    return sorted(p for p in root.rglob("*") if p.is_file()) if root.exists() else []


def test_create_module_has_default_map(local):
    module = create(local, "The Keep")
    assert module["id"].startswith("mod_") and len(module["id"]) == 16
    assert module["title"] == "The Keep"
    assert module["maps"] == [{"name": "map", "role": "map", "is_default": True, "source": ""}]
    assert module["head_revision"] is None
    assert module["metadata"] == {"tags": ["homebrew"]}, "a module made here is homebrew (DEL-226)"
    listed = local.get("/api/modules").json()
    assert listed == [
        {
            "id": module["id"],
            "title": "The Keep",
            "draft": False,
            "maps": [{"name": "map", "role": "map", "is_default": True}],
            "head_revision": None,
            "updated_at": module["updated_at"],
            "empty": True,
            "library": None,
            "category": None,
            "banner": None,
            "setting": None,
            "levels": None,
            "tags": ["homebrew"],
            "summary": None,
        }
    ]
    assert local.get(f"/api/modules/{module['id']}").json() == module


def test_a_module_without_its_map_sources(local):
    """`?map_sources=false` (DEL-172): the metadata and the maps' names, roles and default, without their sources, for
    a caller that wants the metadata only."""
    module = create(local)
    assert put_source(local, module["id"], "map", GOOD_MAP).status_code == 200
    full = local.get(f"/api/modules/{module['id']}").json()
    assert full["maps"][0]["source"] == GOOD_MAP
    light = local.get(f"/api/modules/{module['id']}?map_sources=false").json()
    assert light["maps"] == [{k: v for k, v in m.items() if k != "source"} for m in full["maps"]]
    assert {k: v for k, v in light.items() if k != "maps"} == {k: v for k, v in full.items() if k != "maps"}
    assert "metadata" in light


def test_the_list_carries_what_the_filter_needs(local):
    module = create(local, "Saltmarsh")
    metadata = {
        "setting": " Greyhawk ",
        "party": {"levels": {"min": 1, "max": 3}},
        "tags": ["U1", "coast"],
        "summary": " Smugglers in a haunted house. ",
    }
    assert local.patch(f"/api/modules/{module['id']}", json={"metadata": metadata}).status_code == 200
    single = create(local, "Barrowmaze")
    assert local.patch(f"/api/modules/{single['id']}", json={"metadata": {"party": {"levels": 1}}}).status_code == 200
    listed = {m["title"]: m for m in local.get("/api/modules").json()}
    assert (listed["Saltmarsh"]["setting"], listed["Saltmarsh"]["levels"], listed["Saltmarsh"]["tags"]) == (
        "Greyhawk",
        {"min": 1, "max": 3},
        ["U1", "coast"],
    )
    assert (listed["Barrowmaze"]["setting"], listed["Barrowmaze"]["levels"]) == (None, {"min": 1, "max": 1})
    assert (listed["Saltmarsh"]["summary"], listed["Barrowmaze"]["summary"]) == ("Smugglers in a haunted house.", None)
    assert "metadata" not in listed["Saltmarsh"]


def test_create_module_needs_a_title(local):
    assert local.post("/api/modules", json={"title": "  "}).status_code == 422
    assert "error" in local.post("/api/modules", json={}).json()


def test_patch_module_title_and_metadata(local):
    module = create(local)
    patched = local.patch(f"/api/modules/{module['id']}", json={"title": "Keep II", "metadata": {"tags": ["x"]}})
    assert patched.status_code == 200
    assert patched.json()["title"] == "Keep II"
    assert patched.json()["metadata"] == {"tags": ["x"]}


def test_the_party_notes_round_trip_and_an_empty_one_goes(local):
    module = create(local)
    path = f"/api/modules/{module['id']}"
    party = {"size": 4, "notes": "A cleric is a must."}
    assert local.patch(path, json={"metadata": {"party": party}}).status_code == 200
    assert local.get(path).json()["metadata"]["party"] == party
    assert local.patch(path, json={"metadata": {"party": {"size": 4}}}).status_code == 200
    assert local.get(path).json()["metadata"]["party"] == {"size": 4}


def test_unknown_module_404(local):
    for method, path in (
        ("GET", "/api/modules/mod_000000000000"),
        ("GET", "/api/modules/mod_000000000000/maps/map"),
        ("GET", "/api/modules/mod_000000000000/export.dscn"),
    ):
        response = local.request(method, path)
        assert response.status_code == 404
        assert "error" in response.json()
    response = local.patch("/api/modules/mod_000000000000", json={"title": "x"})
    assert response.status_code == 404


def test_get_map_detail(local):
    module = create(local)
    detail = local.get(f"/api/modules/{module['id']}/maps/map").json()
    assert set(detail) == {"module_id", "name", "role", "is_default", "updated_at", "source"}
    assert detail["module_id"] == module["id"]
    assert (detail["name"], detail["role"], detail["is_default"], detail["source"]) == ("map", "map", True, "")
    assert local.get(f"/api/modules/{module['id']}/maps/nope").status_code == 404


def test_put_map_saves_source(local):
    module = create(local)
    response = put_source(local, module["id"], "map", GOOD_MAP)
    assert response.status_code == 200
    assert response.json()["source"] == GOOD_MAP
    assert local.get(f"/api/modules/{module['id']}/maps/map").json()["source"] == GOOD_MAP


def test_put_map_parse_error_400_with_line(local):
    module = create(local)
    put_source(local, module["id"], "map", GOOD_MAP)
    response = put_source(local, module["id"], "map", BROKEN_MAP, new_name="renamed")
    assert response.status_code == 400
    body = response.json()
    assert set(body) == {"error", "line", "column"}
    assert body["line"] == 6
    assert body["column"] > 0
    stored = local.get(f"/api/modules/{module['id']}/maps/map").json()
    assert (stored["source"], stored["role"]) == (GOOD_MAP, "map")
    assert local.get(f"/api/modules/{module['id']}/maps/renamed").status_code == 404
    to_map = local.post(f"/api/modules/{module['id']}/maps", json={"name": "lib", "role": "library"})
    assert to_map.status_code == 201
    put_source(local, module["id"], "lib", BROKEN_MAP)
    assert local.put(f"/api/modules/{module['id']}/maps/lib", json={"role": "map"}).status_code == 400
    assert local.get(f"/api/modules/{module['id']}/maps/lib").json()["role"] == "library"


def test_library_source_saved_even_if_it_does_not_parse_alone(local):
    module = create(local)
    created = local.post(f"/api/modules/{module['id']}/maps", json={"name": "lib.dmap", "role": "library"})
    assert created.status_code == 201
    assert created.json()["role"] == "library"
    response = put_source(local, module["id"], "lib.dmap", 'feature_def "x" { glyph {')
    assert response.status_code == 200


def test_rename_role_default_and_delete_map(local):
    module = create(local)
    mid = module["id"]
    assert local.post(f"/api/modules/{mid}/maps", json={"name": "second", "role": "map"}).status_code == 201
    assert local.post(f"/api/modules/{mid}/maps", json={"name": "second", "role": "map"}).status_code == 409
    assert local.post(f"/api/modules/{mid}/maps", json={"name": "x", "role": "other"}).status_code == 422

    default = local.put(f"/api/modules/{mid}/maps/second/default", json={})
    assert default.status_code == 200
    assert default.json()["is_default"] is True
    assert local.get(f"/api/modules/{mid}/maps/map").json()["is_default"] is False

    renamed = local.put(f"/api/modules/{mid}/maps/second", json={"new_name": "lower"})
    assert renamed.status_code == 200
    assert (renamed.json()["name"], renamed.json()["is_default"]) == ("lower", True)
    assert [m["name"] for m in local.get(f"/api/modules/{mid}").json()["maps"]] == ["map", "lower"]
    assert local.put(f"/api/modules/{mid}/maps/lower", json={"new_name": "map"}).status_code == 409

    as_library = local.put(f"/api/modules/{mid}/maps/map", json={"role": "library"})
    assert as_library.json()["role"] == "library"
    assert local.put(f"/api/modules/{mid}/maps/map/default", json={}).status_code == 400

    assert local.request("DELETE", f"/api/modules/{mid}/maps/map", json={}).status_code == 204
    assert [m["name"] for m in local.get(f"/api/modules/{mid}").json()["maps"]] == ["lower"]
    assert local.request("DELETE", f"/api/modules/{mid}/maps/map", json={}).status_code == 404


TWO_ROOMS = (
    'map "Gatehouse" {\n  grid { bounds 30 x 10 }\n}\n\n'
    'room "gate" {\n  rect 1,1 4 x 4\n  label "The Gate"\n}\n\n'
    'room "hall" {\n  rect 10,1 4 x 4\n  label "The Hall"\n}\n'
)


def test_renaming_a_map_waits_for_the_edit_lock_before_the_database(local, storage):
    """A rename takes the module's edit lock before it begins its transaction, as the source routes do: while a source
    edit holds the lock, the rename waits without holding the database, so the edit's own write goes through. The other
    order, a rename holding the write lock while it waits for the edit lock, made that write time out (database is
    locked) and stalled the event loop meanwhile."""
    mid = create(local)["id"]
    assert local.post(f"/api/modules/{mid}/maps", json={"name": "upper", "role": "map"}).status_code == 201
    answers: list[int] = []
    with editing(mid):
        renaming = threading.Thread(
            target=lambda: answers.append(local.put(f"/api/modules/{mid}/maps/upper", json={"new_name": "lower"}).status_code)
        )
        renaming.start()
        time.sleep(0.3)  # the rename reaches the lock
        with storage.transaction():
            save_source(storage, mid, load_source(storage, mid))
    renaming.join(10)
    assert answers == [200]


def test_renaming_a_map_keeps_its_texts_links(local, storage):
    """Walkthrough E1 (52 → 49 links), reduced to two headings: a text on the renamed map, and an explicit key on it,
    follow the new name in the same write; the answer lists the texts it updated."""
    mid = create(local)["id"]
    assert local.post(f"/api/modules/{mid}/maps", json={"name": "upper", "role": "map"}).status_code == 201
    assert put_source(local, mid, "upper", TWO_ROOMS).status_code == 200
    assert local.post(f"/api/modules/{mid}/texts", json={"id": "key", "title": "Key", "map": "upper"}).status_code == 201
    assert local.post(f"/api/modules/{mid}/texts", json={"id": "other", "title": "Other"}).status_code == 201
    markdown = "## 1. The Gate\n\nA gate.\n\n## The Hall {#hall}\n\nA hall.\n"
    assert local.put(f"/api/modules/{mid}/texts/key", json={"markdown": markdown}).status_code == 200
    source = load_source(storage, mid)
    key = {"key": "2", "title": "The Hall", "node": "map:upper#room.hall", "text": "text:key#hall"}
    save_source(storage, mid, replace(source, keys=[key]))
    before = local.get(f"/api/modules/{mid}/source").json()
    assert sorted((link["key"], link["map"]) for link in before["links"]) == [("1", "upper"), ("2", "upper")]

    renamed = local.put(f"/api/modules/{mid}/maps/upper", json={"new_name": "lurneslye"})
    assert renamed.status_code == 200
    assert renamed.json()["updated_texts"] == ["key"]
    after = local.get(f"/api/modules/{mid}/source").json()
    assert {t["id"]: t["map"] for t in after["texts"]} == {"key": "lurneslye", "other": None}
    assert [k["node"] for k in after["keys"]] == ["map:lurneslye#room.hall"]
    assert sorted((link["key"], link["map"], link["node"]) for link in after["links"]) == [
        ("1", "lurneslye", "room.gate"),
        ("2", "lurneslye", "room.hall"),
    ]
    assert not [w for w in after["warnings"] if w["code"] == "room-without-text"]


def test_render_returns_svg_and_diagnostics(local):
    module = create(local)
    put_source(local, module["id"], "map", GOOD_MAP)
    response = local.post(f"/api/modules/{module['id']}/maps/map/render", json={})
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"svg", "diagnostics"}
    assert body["svg"].lstrip().startswith("<svg") or "<svg" in body["svg"]
    assert isinstance(body["diagnostics"], list)
    for diagnostic in body["diagnostics"]:
        assert set(diagnostic) == {"severity", "message", "line", "column", "end_line", "end_column"}

    live = local.post(f"/api/modules/{module['id']}/maps/map/render", json={"source": BROKEN_MAP})
    assert live.status_code == 400
    assert live.json()["line"] == 6

    renderer = local.post(f"/api/modules/{module['id']}/maps/map/render", json={"renderer": "no-such"})
    assert renderer.status_code == 400
    assert "error" in renderer.json()


def test_render_reports_validation_diagnostics(local):
    module = create(local)
    overlapping = GOOD_MAP + '\nroom "b" {\n  rect 2,2 4 x 4\n}\n'
    response = local.post(f"/api/modules/{module['id']}/maps/map/render", json={"source": overlapping})
    assert response.status_code == 200
    overlap = next(d for d in response.json()["diagnostics"] if "overlaps" in d["message"])
    assert overlap == {
        "severity": "warning",
        "message": overlap["message"],
        "line": 5,
        "column": 1,
        "end_line": 7,
        "end_column": 2,
    }


def test_include_resolves_module_library_then_builtin(local):
    module = create(local)
    mid = module["id"]
    uses_core = 'include "core.dmap"\n' + GOOD_MAP.replace("rect 1,1 4 x 4", "rect 1,1 4 x 4\n  feature pillar at 2,2")
    builtin = local.post(f"/api/modules/{mid}/maps/map/render", json={"source": uses_core})
    assert builtin.status_code == 200

    local.post(f"/api/modules/{mid}/maps", json={"name": "core.dmap", "role": "library"})
    own_core = 'feature_def "pillar" {\n  name "MODULE-PILLAR"\n  glyph { circle fill at 0,0 radius 0.1 }\n}\n'
    assert put_source(local, mid, "core.dmap", own_core).status_code == 200
    names = local.post(f"/api/modules/{mid}/maps/map/feature-names", json={"source": uses_core}).json()
    assert {"source": "core.dmap", "names": ["pillar"]} in names["groups"]
    builtin_names = local.post("/api/dsl/parse", json={"source": uses_core}).json()["map"]["feature_defs"]
    assert len(builtin_names) > 1
    module_names = local.post("/api/dsl/parse", json={"source": uses_core, "module_id": mid}).json()["map"]
    assert list(module_names["feature_defs"]) == ["pillar"]
    assert module_names["feature_defs"]["pillar"]["display_name"] == "MODULE-PILLAR"


@pytest.mark.parametrize("name", ["/etc/passwd", "../../../../etc/passwd", "includes/core.dmap", "missing.dmap"])
def test_include_never_reads_the_filesystem(local, name):
    module = create(local)
    source = f'include "{name}"\n' + GOOD_MAP
    for path, body in (
        (f"/api/modules/{module['id']}/maps/map/render", {"source": source}),
        ("/api/dsl/render", {"source": source}),
        ("/api/dsl/parse", {"source": source, "module_id": module["id"]}),
    ):
        response = local.post(path, json=body)
        assert response.status_code == 400, path
        assert response.json() == {"error": f'include not found: "{name}"', "line": 1, "column": 1}
    saved = put_source(local, module["id"], "map", source)
    assert saved.status_code == 400
    assert "include not found" in saved.json()["error"]


def test_feature_names_shape(local):
    module = create(local)
    source = 'include "core.dmap"\nfeature_def "zz-local" {\n  glyph { circle fill at 0,0 radius 0.1 }\n}\n' + GOOD_MAP
    response = local.post(f"/api/modules/{module['id']}/maps/map/feature-names", json={"source": source})
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"names", "groups"}
    assert "zz-local" in body["names"] and "pillar" in body["names"]
    assert body["names"] == sorted(body["names"], key=str.lower)
    assert all(set(group) == {"source", "names"} for group in body["groups"])
    sources = [group["source"] for group in body["groups"]]
    assert sources == sorted(sources, key=str.lower)
    assert {"source": "(this file)", "names": ["zz-local"]} in body["groups"]
    broken = local.post(f"/api/modules/{module['id']}/maps/map/feature-names", json={"source": "map {"})
    assert broken.json() == {"names": [], "groups": []}


def test_simplify_shape(local):
    module = create(local)
    source = (
        'map "S" {\n  grid { bounds 30 x 10 }\n}\n\n'
        'corridor "c" {\n  width 1\n  segment line from 1,5 to 5,5\n  segment line from 5,5 to 10,5\n}\n'
    )
    response = local.post(
        f"/api/modules/{module['id']}/maps/map/simplify", json={"source": source, "door_spurs": False}
    )
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"source", "changed", "changes", "stats", "saved"}
    assert body["saved"] is False
    for change in body["changes"]:
        assert set(change) == {"kind", "target", "message", "line", "applied"}
    assert local.get(f"/api/modules/{module['id']}/maps/map").json()["source"] == ""
    broken = local.post(f"/api/modules/{module['id']}/maps/map/simplify", json={"source": BROKEN_MAP})
    assert broken.status_code == 400 and broken.json()["line"] == 6


def test_import_sample_dscn(local, storage):
    data = crypt_zip()
    response = local.post("/api/modules/import", content=data, headers=ZIP)
    assert response.status_code == 201
    module = response.json()
    assert module["title"] == "The Crypt of Saint Vellis"
    assert [(m["name"], m["role"], m["is_default"]) for m in module["maps"]] == [
        ("crypt", "map", True),
        ("core.dmap", "library", False),
    ]
    links = dict(storage.blobs.links(module["id"]))
    assert sorted(links) == ["attachment", "source-bundle"]
    assert storage.blobs.get(links["source-bundle"]) == data
    rendered = local.post(f"/api/modules/{module['id']}/maps/crypt/render", json={})
    assert rendered.status_code == 200

    other = local.post("/api/modules/import", content=data, headers={"Content-Type": "application/vnd.dscn+zip"})
    assert other.status_code == 201
    assert other.json()["id"] != module["id"]


def zip_of(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries.items():
            archive.writestr(zipfile.ZipInfo(name), data, compress_type=zipfile.ZIP_DEFLATED)
    return buffer.getvalue()


def test_import_refuses_traversal_and_bomb_and_missing_manifest(local, storage, config):
    manifest = Bundle.load(CRYPT).manifest_bytes()
    hostile = {
        "traversal": zip_of({"scenario.json": manifest, "../evil.dmap": b"x"}),
        "bomb": zip_of({"scenario.json": manifest, "maps/bomb.dmap": b"\0" * (4 * 1024 * 1024)}),
        "missing manifest": zip_of({"maps/crypt.dmap": (CRYPT / "maps" / "crypt.dmap").read_bytes()}),
        "not a zip": b"PK\x03\x04 but not really",
        "errors in the bundle": zip_of({"scenario.json": manifest}),
    }
    for reason, data in hostile.items():
        response = local.post("/api/modules/import", content=data, headers=ZIP)
        assert response.status_code == 400, reason
        assert response.json()["error"], reason
        assert storage.modules.list() == [], reason
        assert blob_files(config) == [], reason
    assert "unsafe path" in local.post("/api/modules/import", content=hostile["traversal"], headers=ZIP).json()["error"]
    assert "compression" in local.post("/api/modules/import", content=hostile["bomb"], headers=ZIP).json()["error"]
    errors = local.post("/api/modules/import", content=hostile["errors in the bundle"], headers=ZIP).json()
    assert errors["diagnostics"] and all(d["severity"] == "error" for d in errors["diagnostics"])


def test_import_wrong_content_type_415(local, storage):
    data = crypt_zip()
    for content_type in ("application/json", "application/octet-stream", "multipart/form-data", "text/plain"):
        response = local.post("/api/modules/import", content=data, headers={"Content-Type": content_type})
        assert response.status_code == 415, content_type
        assert "application/zip" in response.json()["error"]
    assert local.post("/api/modules/import", content=data).status_code == 415
    assert local.post("/api/modules", content=b"x", headers=ZIP).status_code == 415
    cross_site = local.post("/api/modules/import", content=data, headers={**ZIP, "Origin": "http://evil.example"})
    assert cross_site.status_code == 403
    assert storage.modules.list() == []


def test_import_too_large_413(local, storage, config):
    response = local.post("/api/modules/import", content=b"\0" * (UPLOAD_LIMIT + 1), headers=ZIP)
    assert response.status_code == 413
    assert "error" in response.json()
    assert storage.modules.list() == [] and blob_files(config) == []


def test_import_too_large_without_content_length_413(local, storage, monkeypatch):
    monkeypatch.setattr("delve.web.routes.modules.UPLOAD_LIMIT", 1000)

    def chunks():
        for _ in range(10):
            yield b"\0" * 200

    response = local.post("/api/modules/import", content=chunks(), headers=ZIP)
    assert response.status_code == 413
    assert storage.modules.list() == []


def test_export_roundtrip(local):
    module = local.post("/api/modules/import", content=crypt_zip(), headers=ZIP).json()
    response = local.get(f"/api/modules/{module['id']}/export.dscn")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/vnd.dscn+zip"
    assert response.headers["content-disposition"] == 'attachment; filename="the-crypt-of-saint-vellis.dscn"'
    exported = Bundle.load(response.content)
    assert exported.manifest["version"] == VERSION == 3
    assert [t["id"] for t in exported.entries("text")] == ["intro", "crypt-key"]
    assert exported.asset_entry("ritualist-token")["description"] == "Cult ritualist token"
    again = local.post("/api/modules/import", content=response.content, headers=ZIP)
    assert again.status_code == 201
    assert again.json()["maps"] == module["maps"]
    assert again.json()["title"] == module["title"]


def test_export_of_a_new_module_imports(local):
    module = create(local, "Fresh")
    put_source(local, module["id"], "map", 'include "core.dmap"\n' + GOOD_MAP)
    exported = local.get(f"/api/modules/{module['id']}/export.dscn")
    again = local.post("/api/modules/import", content=exported.content, headers=ZIP)
    assert again.status_code == 201
    maps = {m["name"]: m for m in again.json()["maps"]}
    assert maps["map"]["is_default"] is True
    assert maps["core.dmap"]["role"] == "library"


def test_delete_module(local):
    module = create(local)
    assert local.request("DELETE", f"/api/modules/{module['id']}", json={}).status_code == 204
    assert local.get(f"/api/modules/{module['id']}").status_code == 404
    assert local.request("DELETE", f"/api/modules/{module['id']}", json={}).status_code == 404


def test_delete_module_in_use_409(local, storage):
    module = create(local)
    revision = storage.revisions.snapshot(module["id"])
    campaign = storage.campaigns.create("Tuesday", module["id"], revision.number, ruleset="osric", setting="greyhawk")
    response = local.request("DELETE", f"/api/modules/{module['id']}", json={})
    assert response.status_code == 409
    assert response.json()["campaigns"] == [campaign.id]
    assert "error" in response.json()
    assert local.get(f"/api/modules/{module['id']}").status_code == 200


def test_modules_need_organiser(lan, token):
    calls = [
        ("GET", "/api/modules", None),
        ("POST", "/api/modules", {"title": "x"}),
        ("GET", "/api/modules/mod_000000000000", None),
        ("PATCH", "/api/modules/mod_000000000000", {"title": "x"}),
        ("DELETE", "/api/modules/mod_000000000000", None),
        ("GET", "/api/modules/mod_000000000000/maps/map", None),
        ("PUT", "/api/modules/mod_000000000000/maps/map", {"source": ""}),
        ("POST", "/api/modules/mod_000000000000/maps", {"name": "x", "role": "map"}),
        ("DELETE", "/api/modules/mod_000000000000/maps/map", None),
        ("PUT", "/api/modules/mod_000000000000/maps/map/default", None),
        ("POST", "/api/modules/mod_000000000000/maps/map/render", {}),
        ("POST", "/api/modules/mod_000000000000/maps/map/feature-names", {}),
        ("POST", "/api/modules/mod_000000000000/maps/map/simplify", {"source": ""}),
        ("GET", "/api/modules/mod_000000000000/export.dscn", None),
        ("POST", "/api/dsl/render", {"source": ""}),
        ("POST", "/api/dsl/parse", {"source": ""}),
        ("POST", "/api/dsl/connectivity", {"source": ""}),
    ]
    for method, path, body in calls:
        response = lan.request(method, path, json=body if body is not None else {})
        assert response.status_code == 401, (method, path)
        assert "error" in response.json()
    imported = lan.post("/api/modules/import", content=crypt_zip(), headers=ZIP)
    assert imported.status_code == 401
    with_token = lan.get("/api/modules", headers={"Authorization": f"Bearer {token}"})
    assert with_token.status_code == 200


def test_modules_events_published(local, app):
    module = create(local)
    mid = module["id"]
    local.patch(f"/api/modules/{mid}", json={"title": "Renamed"})
    local.post(f"/api/modules/{mid}/maps", json={"name": "second", "role": "map"})
    put_source(local, mid, "second", GOOD_MAP)
    local.put(f"/api/modules/{mid}/maps/second/default", json={})
    local.request("DELETE", f"/api/modules/{mid}/maps/second", json={})
    local.post(f"/api/modules/{mid}/maps/map/render", json={})
    imported = local.post("/api/modules/import", content=crypt_zip(), headers=ZIP).json()
    local.request("DELETE", f"/api/modules/{mid}", json={})
    events = [(event.type, event.data) for event in published(app)]
    assert events == [("modules", {"id": mid})] * 6 + [("modules", {"id": imported["id"]}), ("modules", {"id": mid})]


def test_an_export_that_doesnt_validate_is_refused(local, monkeypatch):
    """Final review fix 3: the route validates its own bundle, and answers 409 with the problems rather than a bundle
    that wouldn't import."""
    from delve.modules.exporter import export_module

    def duplicated(storage, module_id):
        bundle = export_module(storage, module_id)
        bundle.set_keys([{"key": "7", "title": "Kitchen"}, {"key": "7", "title": "Hold"}])
        return bundle

    module = local.post("/api/modules/import", content=crypt_zip(), headers=ZIP).json()
    monkeypatch.setattr("delve.web.routes.modules.export_whole_module", duplicated)

    response = local.get(f"/api/modules/{module['id']}/export.dscn")

    assert response.status_code == 409
    body = response.json()
    assert body["error"].startswith("the export doesn't validate: ")
    assert body["problems"] and all(isinstance(p, str) for p in body["problems"])
    assert any("7" in p for p in body["problems"])


def test_an_export_derives_once_and_doesnt_look_for_overlaps(local, monkeypatch):
    """Review P6/P23 (DEL-171): an export derived its source three times, partly on the event loop, then checked the
    bundle with the overlap check, whose warnings it never shows."""
    import delve.web.routes.modules as routes
    from delve.modules import exporter

    module = local.post("/api/modules/import", content=crypt_zip(), headers=ZIP).json()
    derived, checked = [], []
    real_derive, real_check = exporter.derive, routes.check_bundle
    monkeypatch.setattr(exporter, "derive", lambda *a: derived.append(1) or real_derive(*a))
    monkeypatch.setattr(routes, "check_bundle", lambda bundle, **kw: checked.append(kw) or real_check(bundle, **kw))

    response = local.get(f"/api/modules/{module['id']}/export.dscn")

    assert response.status_code == 200
    assert derived == [1]
    assert checked == [{"overlaps": False}]


def test_an_explicit_key_on_a_room_the_map_lacks_exports(local, storage):
    """The reviewer's case: an entry's `node` names a room the map hasn't; the export drops it and validates."""
    from delve.domain.modules import ModuleMap
    from delve.modules.dscn import check
    from delve.modules.source import ModuleSource, TextDoc

    module = storage.modules.create("G")
    house = 'map "House" {\n  grid { bounds 30 x 10 }\n}\n\nroom "r7" {\n  rect 1,1 4 x 4\n  label "7. Kitchen"\n}\n'
    storage.modules.put_map(module.id, ModuleMap("house", "map", house, True))
    texts = [TextDoc("house", "House", "gm", "house", "## 7. Kitchen\n\nPots.\n\n## 8. Hall\n\nH.\n")]
    keys = [{"key": "8", "title": "Hall", "text": "text:house#8", "node": "map:house#room.r8"}]
    storage.module_sources.put(module.id, ModuleSource(texts=texts, keys=keys))

    response = local.get(f"/api/modules/{module.id}/export.dscn")

    assert response.status_code == 200
    assert [d for d in check(Bundle.load(response.content)).diagnostics if d.severity == "error"] == []


# ----- its campaigns' banners (looks and banners plan Task 3) -----


def test_the_module_page_lists_its_campaigns_banners(app, local, storage):
    from delve.images.fake import PIXEL_PNG
    from tests.web.test_campaigns_api import campaign, crypt_module, seat_browser, settled

    module = crypt_module(local)["id"]
    painted, bare = (campaign(local, module, name)["id"] for name in ("Painted", "Bare"))
    elsewhere = campaign(local, crypt_module(local, title="Other")["id"], "Elsewhere")["id"]
    for cid in (painted, bare, elsewhere):
        [row] = storage.campaign_images.list(cid, kind="banner")
        settled(storage, row.id)
    [shown] = storage.campaign_images.list(painted, kind="banner")
    [gone] = storage.campaign_images.list(bare, kind="banner")
    storage.campaign_images.delete(gone.id)

    listed = local.get(f"/api/modules/{module}/banners")
    assert listed.status_code == 200
    assert listed.json() == [{"campaign_id": painted, "name": "Painted", "image_id": shown.id}]
    bytes_ = local.get(f"/api/modules/{module}/banners/{painted}")
    assert bytes_.status_code == 200 and bytes_.content == PIXEL_PNG
    assert local.get(f"/api/modules/{module}/banners/{bare}").status_code == 404
    assert local.get(f"/api/modules/{module}/banners/{elsewhere}").status_code == 404, "another module's campaign"
    assert local.get("/api/modules/mod_000000000000/banners").status_code == 404

    player = seat_browser(app, storage, painted, "player")
    assert player.get(f"/api/modules/{module}/banners").status_code == 403
    assert player.get(f"/api/modules/{module}/banners/{painted}").status_code == 403
