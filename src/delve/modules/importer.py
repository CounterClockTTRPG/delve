""".dscn in and out: a bundle becomes a module of maps, and a module becomes a bundle again (spec §8.1, §8.3).

Plateau 1 took the maps and the descriptive metadata; plateau 2b the text, keys and entities, for the DM
(`delve.modules.text`). Plateau 3 keeps them as the module's source (`delve.modules.source`), from which the DM's text
is derived, and puts each asset's bytes in the blob store as an attachment. The whole original bundle is kept as a
blob too. Plateau 6 reads the world maps into the source; one that doesn't parse is kept, and the import answers its
`worldmap-unreadable` warning. Plateau 7's `geojson` maps come with their pictures, which the caller cuts into tiles.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Protocol

from delve.domain.modules import Module, ModuleMap
from delve.modules.dscn import DEFAULT_LIMITS, Bundle, Diagnostic, check, sha256, vendor
from delve.modules.source import SOURCE_BUNDLE, ModuleSource, derive, from_bundle, store_attachments

BANNER_ASSET = "delve-banner"
BANNER_MARK = "x-delve-banner"
"""A module's banner in a `.dscn` (DEL-123): an image asset with this key, its value where the banner came from. Any
other reader sees a picture the players may see; Delve's import makes it the banner, not an attachment."""
BANNER_TYPES = frozenset({"image/png", "image/jpeg", "image/webp"})

__all__ = ["MEDIA_TYPE", "SOURCE_BUNDLE", "ImportRefused", "ImportResult", "export_bundle", "import_bundle"]

MEDIA_TYPE = "application/vnd.dscn+zip"

# Manifest keys that describe the bundle's parts rather than the module; everything else is the module's metadata.
STRUCTURAL = ("format", "version", "title", "maps", "worldmaps", "text", "entities", "assets", "keys", "start")


class ModuleStore(Protocol):
    def create(self, title: str, metadata: dict[str, Any] | None = None) -> Module: ...

    def put_map(self, id: str, map: ModuleMap) -> Module: ...

    def delete(self, id: str) -> None: ...


class BundleBlobs(Protocol):
    def put(self, data: bytes, mime: str) -> str: ...

    def link(self, module_id: str, role: str, sha: str) -> None: ...


class ModuleTexts(Protocol):
    def put(self, module_id: str, raw: dict[str, Any]) -> None: ...


class ModuleSources(Protocol):
    def put(self, module_id: str, source: ModuleSource) -> None: ...


class StorageLike(Protocol):
    """What the import needs of storage; `delve.storage.Storage` is one."""

    modules: ModuleStore
    blobs: BundleBlobs
    module_texts: ModuleTexts
    module_sources: ModuleSources


class ImportRefused(Exception):
    """The bundle loaded, but `check()` found errors in it."""

    def __init__(self, diagnostics: list[Diagnostic]) -> None:
        self.diagnostics = diagnostics
        self.errors = [d for d in diagnostics if d.severity == "error"]
        super().__init__(f"the scenario has {len(self.errors)} error(s): {self.errors[0].message}")


@dataclass(frozen=True)
class ImportResult:
    module: Module
    warnings: list[str] = field(default_factory=list)
    pictures: list[tuple[str, str]] = field(default_factory=list)
    """The `(sha256, mime)` of each world map's picture, its original in the blob store, for the caller to cut into
    tiles (`delve.maps.geo.pictures.store_blob`)."""


def import_bundle(storage_like: StorageLike, data: bytes) -> ImportResult:
    """A new module from the `.dscn` zip `data`.

    Raises `ScenarioError` when the container is unusable (a bad zip, an unsafe path, past the limits, no manifest)
    and `ImportRefused` when its content has errors. Either way nothing is stored, and a failure while storing
    removes the module again.
    """
    bundle = Bundle.load(data, limits=DEFAULT_LIMITS)
    report = check(bundle)
    if not report.ok:
        raise ImportRefused(report.diagnostics)

    metadata = {key: value for key, value in bundle.manifest.items() if key not in STRUCTURAL}
    default = bundle.default_map()
    module = storage_like.modules.create(bundle.title or "Imported module", metadata)
    try:
        for entry in bundle.maps():
            role = "library" if entry.get("role", "map") == "library" else "map"
            is_default = role == "map" and default is not None and entry["name"] == default["name"]
            module_map = ModuleMap(entry["name"], role, bundle.read_text(entry["file"]), is_default)
            module = storage_like.modules.put_map(module.id, module_map)
        source = from_bundle(bundle)
        # The module's banner (DEL-123), marked by Delve's export: the banner again, not an attachment.
        banner = next((a for a in bundle.entries("assets") if a.get(BANNER_MARK) and a.get("file") in bundle.files), None)
        if banner is not None:
            source = replace(source, attachments=[a for a in source.attachments if a.id != banner["id"]])
        derived = derive(source, module.maps)
        text = derived.text
        if not text.empty:
            storage_like.module_texts.put(module.id, text.to_json())
        storage_like.module_sources.put(module.id, source)
        store_attachments(storage_like.blobs, module.id, bundle)
        if banner is not None and str(banner.get("type")) in BANNER_TYPES:
            marked = str(banner[BANNER_MARK])
            origin = marked if marked in ("painted", "uploaded") or marked.startswith("picture:") else "uploaded"
            sha = storage_like.blobs.put(bundle.files[banner["file"]], str(banner["type"]))
            module = storage_like.modules.set_banner(module.id, sha, str(banner["type"]), origin)
        sha = storage_like.blobs.put(data, MEDIA_TYPE)
        storage_like.blobs.link(module.id, SOURCE_BUNDLE, sha)
    except BaseException:
        storage_like.modules.delete(module.id)
        raise
    warnings = [d.message for d in report.diagnostics if d.severity == "warning"]
    warnings += [w.message for w in derived.warnings if w.code == "worldmap-unreadable"]
    types = {sha256(bundle.files[a["file"]]): str(a.get("type")) for a in bundle.entries("assets") if a.get("file") in bundle.files}
    pictures = list(dict.fromkeys((w.picture, types[w.picture]) for w in source.worldmaps if w.picture in types))
    return ImportResult(module, warnings, pictures)


def export_bundle(module: Module) -> Bundle:
    """The module's metadata and maps as a `.dscn` bundle, with the built-in libraries they include vendored.
    `delve.modules.exporter.export_module` adds the rest of the module."""
    metadata = dict(module.metadata)
    scenario_id = metadata.pop("id", None)
    bundle = Bundle.new(module.title, id=str(scenario_id) if scenario_id else None)
    for key, value in metadata.items():
        # This bundle carries no assets, so a cover that is one would dangle.
        if key not in STRUCTURAL and not (key == "cover" and str(value).startswith("asset:")):
            bundle.manifest[key] = value
    # A map with no source yet (a new module's untouched default) is left out: it doesn't parse, so it would fail the
    # bundle's validation, and our own import would refuse the export.
    for module_map in module.maps:
        if module_map.source.strip():
            bundle.add_map(module_map.name, module_map.source, role=module_map.role, default=module_map.is_default)
    vendor(bundle)
    return bundle
