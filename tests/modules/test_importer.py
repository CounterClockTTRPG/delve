import hashlib
import io
import zipfile
from dataclasses import replace

import pytest

from delve.domain.modules import Module, ModuleMap
from delve.modules.dscn import Bundle, ScenarioError
from delve.modules.importer import ImportRefused, export_bundle, import_bundle
from tests.fixtures import SAMPLES

CRYPT = SAMPLES / "scenarios" / "crypt-of-saint-vellis"


class FakeModules:
    def __init__(self) -> None:
        self.by_id: dict[str, Module] = {}

    def create(self, title, metadata=None):
        module = Module(f"mod_{len(self.by_id):012x}", title, dict(metadata or {}), (), None, "now")
        self.by_id[module.id] = module
        return module

    def put_map(self, id, map):
        module = self.by_id[id]
        maps = [m for m in module.maps if m.name != map.name]
        if map.is_default:
            maps = [replace(m, is_default=False) for m in maps]
        self.by_id[id] = replace(module, maps=(*maps, map))
        return self.by_id[id]

    def delete(self, id):
        self.by_id.pop(id, None)


class FakeBlobs:
    def __init__(self) -> None:
        self.data: dict[str, bytes] = {}
        self.linked: list[tuple[str, str, str]] = []

    def put(self, data, mime):
        sha = hashlib.sha256(data).hexdigest()
        self.data[sha] = data
        return sha

    def link(self, module_id, role, sha):
        self.linked.append((module_id, role, sha))


class FakeTexts:
    def __init__(self) -> None:
        self.by_module: dict[str, dict] = {}

    def put(self, module_id, raw):
        self.by_module[module_id] = raw


class FakeSources:
    def __init__(self) -> None:
        self.by_module: dict[str, object] = {}

    def put(self, module_id, source):
        self.by_module[module_id] = source


class FakeStore:
    def __init__(self) -> None:
        self.modules = FakeModules()
        self.blobs = FakeBlobs()
        self.module_texts = FakeTexts()
        self.module_sources = FakeSources()


def crypt_zip() -> bytes:
    return Bundle.load(CRYPT).to_zip()


def test_import_sample_creates_module_with_maps_and_keeps_bundle():
    store = FakeStore()
    data = crypt_zip()
    result = import_bundle(store, data)
    module = result.module
    assert module.title == "The Crypt of Saint Vellis"
    assert [(m.name, m.role, m.is_default) for m in module.maps] == [
        ("crypt", "map", True),
        ("core.dmap", "library", False),
    ]
    assert module.maps[0].source == (CRYPT / "maps" / "crypt.dmap").read_text()
    assert module.metadata["system"] == "adnd2e"
    assert module.metadata["id"] == "3f6c1a52-8d1e-4c0b-9b7a-5a2d6e1f0c11"
    for structural in ("format", "version", "title", "maps", "text", "entities", "assets", "keys", "start"):
        assert structural not in module.metadata
    sha = hashlib.sha256(data).hexdigest()
    token = (CRYPT / "assets" / "img" / "ritualist-token.png").read_bytes()
    token_sha = hashlib.sha256(token).hexdigest()
    assert store.blobs.linked == [(module.id, "attachment", token_sha), (module.id, "source-bundle", sha)]
    assert store.blobs.data[sha] == data and store.blobs.data[token_sha] == token
    assert [a.id for a in store.module_sources.by_module[module.id].attachments] == ["ritualist-token"]


def test_bundle_with_errors_is_refused_and_nothing_stored():
    bundle = Bundle.load(CRYPT)
    bundle.manifest["maps"].append({"name": "ghost", "file": "maps/ghost.dmap"})
    store = FakeStore()
    with pytest.raises(ImportRefused) as refused:
        import_bundle(store, bundle.to_zip())
    assert refused.value.errors
    assert store.modules.by_id == {}
    assert store.blobs.data == {}


def test_unusable_container_raises_scenario_error():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("maps/crypt.dmap", 'map "x" {}')
    store = FakeStore()
    with pytest.raises(ScenarioError):
        import_bundle(store, buffer.getvalue())
    assert store.modules.by_id == {} and store.blobs.data == {}


def test_failure_while_storing_removes_the_module():
    store = FakeStore()

    def broken_put(data, mime):
        raise OSError("disk full")

    store.blobs.put = broken_put
    with pytest.raises(OSError):
        import_bundle(store, crypt_zip())
    assert store.modules.by_id == {}


def test_export_bundle_round_trips_maps():
    store = FakeStore()
    module = import_bundle(store, crypt_zip()).module
    exported = Bundle.load(export_bundle(module).to_zip())
    assert exported.id == module.metadata["id"]
    assert exported.title == module.title
    again = import_bundle(FakeStore(), exported.to_zip()).module
    assert again.maps == module.maps


def test_export_without_scenario_id_gets_one():
    module = Module("mod_000000000001", "Bare", {}, (ModuleMap("map", "map", "map map {}\n", True),), None, "now")
    bundle = export_bundle(module)
    assert bundle.id
    assert bundle.maps() == [{"name": "map", "file": "maps/map.dmap", "default": True}]
