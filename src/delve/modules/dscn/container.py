"""The `.dscn` container — one layout, two forms (spec §2).

A `Bundle` is the in-memory scenario: the manifest dict plus every other
file as bytes, keyed by its relative POSIX path. It loads from a zip
(`.dscn`) or from an unpacked directory and writes back to either. Loading
is where the import hardening lives (§11): unsafe paths, symlinks, size
caps and zip-bomb ratios are refused before anything is parsed.

Packing is deterministic — entries sorted, timestamps fixed — so the same
directory always packs to byte-identical zips that diff and hash cleanly.
"""
from __future__ import annotations

import hashlib
import io
import json
import stat
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

import yaml

from .yamlsafe import load_yaml

FORMAT = "dungml-scenario"
# Version 2 (Delve plateau 3) gives every attachment asset a `description`; version 3 (faithful
# modules) adds the `pregens` entity kind. The reader takes versions 1 to 3; a version 1 asset has
# only its `caption`.
VERSION = 3
EXT = ".dscn"
MEDIA_TYPE = "application/vnd.dungml.scenario+zip"
MANIFEST = "scenario.json"

# Already-compressed media: deflating them again only costs CPU.
_STORED_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".pdf", ".mp3", ".ogg"}
_FIXED_TIME = (1980, 1, 1, 0, 0, 0)

# Delve faithful modules adds `pregens`, last, with version 3.
ENTITY_KINDS = ("npcs", "factions", "quests", "rumors", "secrets", "encounters", "pregens")


class ScenarioError(Exception):
    """The container itself is unusable: not a zip, no manifest, an unsafe
    path, over a size limit. Content problems are diagnostics, not this."""


@dataclass(frozen=True)
class Limits:
    max_total: int = 512 * 1024 * 1024
    max_file: int = 64 * 1024 * 1024
    max_entries: int = 5000
    # Uncompressed/compressed. Text deflates ~5-10x; 200x is a bomb.
    max_ratio: float = 200.0


DEFAULT_LIMITS = Limits()


def safe_path(name: str) -> str:
    """Normalise and check a bundle-relative path; raise ScenarioError if
    it could escape the bundle root."""
    if not name or "\\" in name or "\x00" in name:
        raise ScenarioError(f"unsafe path in bundle: {name!r}")
    if name.startswith("/") or (len(name) > 1 and name[1] == ":"):
        raise ScenarioError(f"absolute path in bundle: {name!r}")
    parts = PurePosixPath(name).parts
    if any(p in ("..", ".") for p in parts) or not parts:
        raise ScenarioError(f"unsafe path in bundle: {name!r}")
    return "/".join(parts)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass
class Bundle:
    manifest: dict[str, Any]
    files: dict[str, bytes] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def new(cls, title: str, *, id: str | None = None, **fields: Any) -> "Bundle":
        manifest: dict[str, Any] = {
            "format": FORMAT,
            "version": VERSION,
            "id": id or str(uuid.uuid4()),
            "title": title,
            "maps": [],
        }
        manifest.update({k: v for k, v in fields.items() if v is not None})
        return cls(manifest=manifest)

    @classmethod
    def load(cls, src: str | Path | bytes, *, limits: Limits = DEFAULT_LIMITS) -> "Bundle":
        """Load from a `.dscn` path, raw zip bytes, or a directory."""
        if isinstance(src, (bytes, bytearray)):
            return cls.from_zip(bytes(src), limits=limits)
        p = Path(src)
        if p.is_dir():
            return cls.from_dir(p, limits=limits)
        if not p.is_file():
            raise ScenarioError(f"no such scenario: {p}")
        return cls.from_zip(p.read_bytes(), limits=limits)

    @classmethod
    def from_zip(cls, data: bytes, *, limits: Limits = DEFAULT_LIMITS) -> "Bundle":
        try:
            zf = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile as e:
            raise ScenarioError("this is not a .dscn file (it isn't a zip archive)") from e
        infos = [i for i in zf.infolist() if not i.is_dir()]
        if len(infos) > limits.max_entries:
            raise ScenarioError(f"too many entries ({len(infos)} > {limits.max_entries})")
        total = whole = 0
        files: dict[str, bytes] = {}
        for info in infos:
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise ScenarioError(f"symlink in bundle: {info.filename!r}")
            name = safe_path(info.filename)
            if name in files:
                raise ScenarioError(f"duplicate entry: {name!r}")
            if info.file_size > limits.max_file:
                raise ScenarioError(f"{name}: {info.file_size} bytes exceeds the per-file limit")
            if info.compress_size and info.file_size / info.compress_size > limits.max_ratio \
                    and info.file_size > 1024 * 1024:
                raise ScenarioError(f"{name}: suspicious compression ratio")
            # Small entries skip the check above: the archive as a whole is held to it (DEL-152).
            whole += info.file_size
            if whole > 1024 * 1024 and whole / len(data) > limits.max_ratio:
                raise ScenarioError("suspicious compression ratio for the archive as a whole")
            total += info.file_size
            if total > limits.max_total:
                raise ScenarioError("bundle exceeds the total size limit")
            # Read in a bounded way: a lying header must not let us inflate
            # past the limit.
            with zf.open(info) as fh:
                blob = fh.read(limits.max_file + 1)
            if len(blob) > limits.max_file:
                raise ScenarioError(f"{name}: exceeds the per-file limit")
            files[name] = blob
        return cls._from_files(files)

    @classmethod
    def from_dir(cls, root: Path, *, limits: Limits = DEFAULT_LIMITS) -> "Bundle":
        root = Path(root)
        files: dict[str, bytes] = {}
        total = 0
        for p in sorted(root.rglob("*")):
            rel = p.relative_to(root)
            # Dotfiles/dirs (.git, .DS_Store) are never part of a scenario.
            if any(part.startswith(".") for part in rel.parts):
                continue
            if p.is_symlink():
                raise ScenarioError(f"symlink in bundle directory: {rel}")
            if not p.is_file():
                continue
            size = p.stat().st_size
            if size > limits.max_file:
                raise ScenarioError(f"{rel}: exceeds the per-file limit")
            total += size
            if total > limits.max_total or len(files) >= limits.max_entries:
                raise ScenarioError("bundle directory exceeds the size/entry limits")
            files[safe_path(rel.as_posix())] = p.read_bytes()
        return cls._from_files(files)

    @classmethod
    def _from_files(cls, files: dict[str, bytes]) -> "Bundle":
        raw = files.pop(MANIFEST, None)
        if raw is None:
            raise ScenarioError(f"bundle is missing {MANIFEST}")
        try:
            manifest = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            raise ScenarioError(f"{MANIFEST} is not valid JSON: {e}") from e
        if not isinstance(manifest, dict):
            raise ScenarioError(f"{MANIFEST} must be a JSON object")
        if manifest.get("format") != FORMAT:
            raise ScenarioError(
                f"unrecognised format {manifest.get('format')!r} (expected {FORMAT!r})"
            )
        v = manifest.get("version")
        if not isinstance(v, int) or v > VERSION:
            raise ScenarioError(
                f"unsupported {FORMAT} version {v!r}; this reader understands ≤ {VERSION}"
            )
        return cls(manifest=manifest, files=files)

    # ------------------------------------------------------------------
    # Output
    # ------------------------------------------------------------------

    def manifest_bytes(self) -> bytes:
        return (json.dumps(self.manifest, indent=2, ensure_ascii=False) + "\n").encode("utf-8")

    def to_zip(self) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            entries = [(MANIFEST, self.manifest_bytes())]
            entries += sorted(self.files.items())
            for name, data in entries:
                info = zipfile.ZipInfo(name, date_time=_FIXED_TIME)
                info.external_attr = (0o100644 & 0xFFFF) << 16
                info.create_system = 3  # unix, so the mode above is honoured
                suffix = PurePosixPath(name).suffix.lower()
                info.compress_type = (
                    zipfile.ZIP_STORED if suffix in _STORED_SUFFIXES else zipfile.ZIP_DEFLATED
                )
                zf.writestr(info, data)
        return buf.getvalue()

    def write_zip(self, path: str | Path) -> Path:
        p = Path(path)
        p.write_bytes(self.to_zip())
        return p

    def write_dir(self, root: str | Path) -> Path:
        root = Path(root)
        root.mkdir(parents=True, exist_ok=True)
        (root / MANIFEST).write_bytes(self.manifest_bytes())
        for name, data in self.files.items():
            dest = root / safe_path(name)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
        return root

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    @property
    def id(self) -> str:
        return str(self.manifest.get("id", ""))

    @property
    def title(self) -> str:
        return str(self.manifest.get("title", ""))

    def entries(self, section: str) -> list[dict]:
        val = self.manifest.get(section) or []
        return [e for e in val if isinstance(e, dict)] if isinstance(val, list) else []

    def maps(self, role: str | None = None) -> list[dict]:
        out = self.entries("maps")
        if role is not None:
            out = [m for m in out if m.get("role", "map") == role]
        return out

    def map_entry(self, name: str) -> dict | None:
        return next((m for m in self.maps() if m.get("name") == name), None)

    def default_map(self) -> dict | None:
        playable = self.maps("map")
        return next((m for m in playable if m.get("default")), playable[0] if playable else None)

    def text_entry(self, tid: str) -> dict | None:
        return next((t for t in self.entries("text") if t.get("id") == tid), None)

    def asset_entry(self, aid: str) -> dict | None:
        return next((a for a in self.entries("assets") if a.get("id") == aid), None)

    def read(self, path: str) -> bytes:
        try:
            return self.files[path]
        except KeyError:
            raise ScenarioError(f"missing file in bundle: {path}") from None

    def read_text(self, path: str) -> str:
        return self.read(path).decode("utf-8")

    def map_source(self, name: str) -> str:
        entry = self.map_entry(name)
        if entry is None:
            raise ScenarioError(f"no map named {name!r}")
        return self.read_text(entry["file"])

    def library_sources(self) -> dict[str, str]:
        """{include name: source} for every bundled library — what
        `dungml.parse(include_sources=…)` needs to resolve in-bundle."""
        out: dict[str, str] = {}
        for m in self.maps("library"):
            if m.get("file") in self.files:
                out[m["name"]] = self.read_text(m["file"])
        return out

    def entities(self, kind: str) -> list[dict]:
        path = (self.manifest.get("entities") or {}).get(kind)
        if not path or path not in self.files:
            return []
        data = load_yaml(self.read_text(path))
        return [r for r in data if isinstance(r, dict)] if isinstance(data, list) else []

    # ------------------------------------------------------------------
    # Mutators — used by exporters to assemble a bundle
    # ------------------------------------------------------------------

    def _upsert(self, section: str, key: str, entry: dict) -> dict:
        items = self.manifest.setdefault(section, [])
        for i, e in enumerate(items):
            if isinstance(e, dict) and e.get(key) == entry[key]:
                items[i] = entry
                return entry
        items.append(entry)
        return entry

    def add_map(self, name: str, source: str, *, role: str = "map", file: str | None = None,
                default: bool = False, title: str | None = None) -> dict:
        if file is None:
            stem = _file_stem(name.removesuffix(".dmap"))
            file = f"maps/lib/{stem}.dmap" if role == "library" else f"maps/{stem}.dmap"
        file = self._unique_file(safe_path(file), owner=("maps", name))
        self.files[file] = source.encode("utf-8")
        entry: dict[str, Any] = {"name": name, "file": file}
        if role != "map":
            entry["role"] = role
        if default:
            for m in self.maps():
                m.pop("default", None)
            entry["default"] = True
        if title:
            entry["title"] = title
        return self._upsert("maps", "name", entry)

    def add_text(self, tid: str, content: str, *, file: str | None = None, **meta: Any) -> dict:
        file = self._unique_file(safe_path(file or f"text/{_file_stem(tid)}.md"), owner=("text", tid))
        self.files[file] = content.encode("utf-8")
        entry = {"id": tid, "file": file, **{k: v for k, v in meta.items() if v is not None}}
        return self._upsert("text", "id", entry)

    def add_asset(self, aid: str, data: bytes, mime: str, *, file: str | None = None,
                  **meta: Any) -> dict:
        if file is None:
            file = f"assets/{_file_stem(aid)}{_suffix_for(mime)}"
        file = self._unique_file(safe_path(file), owner=("assets", aid))
        self.files[file] = data
        entry = {
            "id": aid, "file": file, "type": mime,
            "sha256": sha256(data), "size": len(data),
            **{k: v for k, v in meta.items() if v is not None},
        }
        return self._upsert("assets", "id", entry)

    def add_worldmap(self, name: str, source: str, *, type: str = "ttrpg2-worldmap",
                     file: str | None = None, **meta: Any) -> dict:
        file = self._unique_file(
            safe_path(file or f"worldmaps/{_file_stem(name)}.map"), owner=("worldmaps", name)
        )
        self.files[file] = source.encode("utf-8")
        entry = {"name": name, "file": file, "type": type,
                 **{k: v for k, v in meta.items() if v is not None}}
        return self._upsert("worldmaps", "name", entry)

    def set_entities(self, kind: str, records: Iterable[dict]) -> str | None:
        if kind not in ENTITY_KINDS:
            raise ValueError(f"unknown entity kind {kind!r}")
        records = list(records)
        ents = self.manifest.setdefault("entities", {})
        path = ents.get(kind) or f"entities/{kind}.yaml"
        if not records:
            ents.pop(kind, None)
            self.files.pop(path, None)
            if not ents:
                self.manifest.pop("entities", None)
            return None
        self.files[path] = yaml.safe_dump(
            records, sort_keys=False, allow_unicode=True, width=100
        ).encode("utf-8")
        ents[kind] = path
        return path

    def set_keys(self, keys: list[dict]) -> None:
        if keys:
            self.manifest["keys"] = keys
        else:
            self.manifest.pop("keys", None)

    def _unique_file(self, file: str, *, owner: tuple[str, str]) -> str:
        """Keep two entries from silently sharing one file path."""
        section, key = owner
        keyname = "id" if section in ("text", "assets") else "name"
        taken = {
            e.get("file") for sec in ("maps", "text", "assets", "worldmaps")
            for e in self.entries(sec)
            if not (sec == section and e.get(keyname) == key)
        }
        taken |= set((self.manifest.get("entities") or {}).values())
        if file not in taken:
            return file
        stem, dot, suffix = file.rpartition(".")
        n = 2
        while f"{stem}-{n}{dot}{suffix}" in taken:
            n += 1
        return f"{stem}-{n}{dot}{suffix}"


def _file_stem(name: str) -> str:
    import re

    s = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-.")
    return s or "item"


_MIME_SUFFIX = {
    "image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "image/gif": ".gif",
    "image/svg+xml": ".svg", "application/pdf": ".pdf", "text/plain": ".txt",
    "text/markdown": ".md", "audio/mpeg": ".mp3", "audio/ogg": ".ogg",
}


def _suffix_for(mime: str) -> str:
    return _MIME_SUFFIX.get(mime, "")
