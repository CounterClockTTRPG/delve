"""Bundle validation (spec §10). Diagnostics, not exceptions: an importer
decides what to do with warnings, and refuses only on errors."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from typing import Any

from typing import TYPE_CHECKING

import yaml
from jsonschema import Draft202012Validator

from .container import ENTITY_KINDS, MANIFEST, Bundle, sha256
from .yamlsafe import load_yaml
from .media import ALLOWED_TYPES, svg_is_active, type_matches
from .metadata import MOVED as _MOVED
from .metadata import check as check_metadata
from .refs import ENTITY_REF_KINDS, parse_ref, refs_in_markdown, refs_in_value
from .text import TextDoc, parse_text

if TYPE_CHECKING:
    from .maps import MapInfo


@dataclass(frozen=True)
class Diagnostic:
    severity: str          # "error" | "warning"
    code: str              # stable slug, e.g. "dangling-ref"
    message: str
    path: str | None = None  # bundle file the finding is about

    def __str__(self) -> str:
        where = f"{self.path}: " if self.path else ""
        return f"[{self.severity}] {where}{self.message} ({self.code})"

    def as_dict(self) -> dict:
        return {"severity": self.severity, "code": self.code,
                "message": self.message, "path": self.path}


@lru_cache(maxsize=1)
def schema() -> dict:
    return json.loads(
        resources.files("delve.modules.dscn").joinpath("scenario.schema.json").read_text("utf-8")
    )


def _sub_validator(defname: str) -> Draft202012Validator:
    s = dict(schema())
    for k in ("type", "required", "properties", "patternProperties", "additionalProperties"):
        s.pop(k, None)
    s["$ref"] = f"#/$defs/{defname}"
    return Draft202012Validator(s)


def has_errors(diags: list[Diagnostic]) -> bool:
    return any(d.severity == "error" for d in diags)


@dataclass
class Report:
    """Validation result plus what was learned on the way — callers that
    import reuse the parsed maps and texts instead of parsing twice."""
    diagnostics: list[Diagnostic]
    maps: dict[str, "MapInfo"]
    texts: dict[str, TextDoc]
    maps_checked: bool = True

    @property
    def ok(self) -> bool:
        return not has_errors(self.diagnostics)


def validate(bundle: Bundle) -> list[Diagnostic]:
    return check(bundle).diagnostics


def check(bundle: Bundle, *, overlaps: bool = True) -> Report:
    """Delve (DEL-171): without `overlaps`, the maps' overlap warnings aren't looked for (the DSL's `validate`)."""
    diags: list[Diagnostic] = []

    def err(code: str, msg: str, path: str | None = None) -> None:
        diags.append(Diagnostic("error", code, msg, path))

    def warn(code: str, msg: str, path: str | None = None) -> None:
        diags.append(Diagnostic("warning", code, msg, path))

    m = bundle.manifest

    # -- 1. manifest schema ------------------------------------------------
    for e in sorted(Draft202012Validator(schema()).iter_errors(m), key=lambda e: list(e.path)):
        loc = "/".join(str(p) for p in e.absolute_path) or "(root)"
        if e.validator == "additionalProperties":
            if not e.absolute_path and isinstance(e.instance, dict):
                extra = set(e.instance) - set((e.schema or {}).get("properties", {}))
                if extra and extra <= set(_MOVED) | {k for k in extra if k.startswith("x-")}:
                    continue  # reported once, with a pointer, as metadata-moved
            warn("unknown-field", f"{loc}: {e.message}", MANIFEST)
        else:
            err("schema", f"{loc}: {e.message}", MANIFEST)

    # -- 1b. metadata semantics (ranges, timestamps, cover) ---------------
    for f in check_metadata(m, asset_lookup=bundle.asset_entry):
        (err if f.severity == "error" else warn)(f.code, f.message, MANIFEST)

    # -- 2. files and uniqueness ------------------------------------------
    referenced: set[str] = set()

    def need_file(path: Any, what: str) -> bool:
        if not isinstance(path, str):
            return False
        referenced.add(path)
        if path not in bundle.files:
            err("missing-file", f"{what} file not in bundle", path)
            return False
        return True

    def unique(section: str, key: str) -> list[dict]:
        seen: set[str] = set()
        for e in bundle.entries(section):
            v = e.get(key)
            if v in seen:
                err("duplicate-id", f"duplicate {section} {key} {v!r}", MANIFEST)
            seen.add(v)
        return bundle.entries(section)

    for mp in unique("maps", "name"):
        need_file(mp.get("file"), f"map {mp.get('name')!r}")
    defaults = [mp for mp in bundle.maps("map") if mp.get("default")]
    if len(defaults) > 1:
        err("multiple-defaults", "more than one map is marked default", MANIFEST)
    if any(mp.get("default") for mp in bundle.maps("library")):
        err("library-default", "a library cannot be the default map", MANIFEST)
    for wm in unique("worldmaps", "name"):
        need_file(wm.get("file"), f"worldmap {wm.get('name')!r}")
    texts_meta = unique("text", "id")
    for t in texts_meta:
        need_file(t.get("file"), f"text {t.get('id')!r}")
    for kind, path in (m.get("entities") or {}).items() if isinstance(m.get("entities"), dict) else []:
        if kind in ENTITY_KINDS:
            need_file(path, f"entities {kind}")

    # -- 3. assets ---------------------------------------------------------
    v2 = isinstance(m.get("version"), int) and m["version"] >= 2
    for a in unique("assets", "id"):
        if v2 and a.get("role", "attachment") == "attachment" and not isinstance(a.get("description"), str):
            err("asset-description", f"asset {a.get('id')!r} has no description (version 2)", MANIFEST)
        path = a.get("file")
        if not need_file(path, f"asset {a.get('id')!r}"):
            continue
        data = bundle.files[path]
        if a.get("sha256") and sha256(data) != a.get("sha256"):
            err("hash-mismatch", "sha256 does not match the file", path)
        if isinstance(a.get("size"), int) and a["size"] != len(data):
            err("size-mismatch", f"size is {len(data)}, manifest says {a['size']}", path)
        mime = a.get("type")
        if mime in ALLOWED_TYPES and not type_matches(mime, data):
            err("type-mismatch", f"content is not {mime}", path)
        if mime == "image/svg+xml" and svg_is_active(data):
            err("svg-active", "SVG contains script, event handlers or external references", path)

    for path in sorted(set(bundle.files) - referenced):
        warn("unlisted-file", "file is in the bundle but not in the manifest", path)

    # -- 4. maps -----------------------------------------------------------
    # Needs dungml. Without it (e.g. ttrpg2 on a bare interpreter) the map
    # checks are skipped with a warning — the dungml server that imports
    # the bundle runs them again and refuses on error.
    try:
        import delve.maps.dsl as dungml

        from .maps import analyse_maps
    except ImportError:
        dungml = None  # type: ignore[assignment]
        infos = {}
        warn("maps-unchecked",
             "dungml is not installed here; maps, includes and node ids were not checked")
    else:
        infos = analyse_maps(bundle)
    map_names = {mp.get("name") for mp in bundle.maps("map")}
    for name, info in infos.items():
        path = (bundle.map_entry(name) or {}).get("file")
        if info.missing_includes:
            err("dangling-include",
                f"map {name!r} includes {', '.join(info.missing_includes)}, not in the bundle "
                f"(run `dscn vendor`)", path)
        elif info.error and path in bundle.files:
            err("map-parse", f"map {name!r}: {info.error}", path)
        if info.model is not None:
            for d in dungml.validate(info.model, overlaps=overlaps):
                (err if d.severity == "error" else warn)(
                    "map-" + d.severity, f"map {name!r} line {d.line}: {d.message}", path
                )
    for lib in bundle.maps("library"):
        src = bundle.files.get(lib.get("file", ""))
        if src is not None and b'map "' in src and _has_map_block(src):
            err("library-has-map", f"library {lib.get('name')!r} contains a map block",
                lib.get("file"))

    # -- 5. text -----------------------------------------------------------
    docs: dict[str, TextDoc] = {}
    for t in texts_meta:
        path = t.get("file")
        if path not in bundle.files:
            continue
        try:
            raw = bundle.files[path].decode("utf-8")
        except UnicodeDecodeError:
            err("text-encoding", "text is not UTF-8", path)
            continue
        doc = parse_text(raw)
        docs[t["id"]] = doc
        for line, msg in doc.errors:
            err("duplicate-anchor", f"line {line}: {msg}", path)
        if t.get("map") and t["map"] not in map_names:
            err("dangling-ref", f"text {t['id']!r} names unknown map {t['map']!r}", MANIFEST)

    # -- 6. entities -------------------------------------------------------
    entities: dict[str, dict[str, dict]] = {}
    for kind in ENTITY_KINDS:
        path = (m.get("entities") or {}).get(kind) if isinstance(m.get("entities"), dict) else None
        if not path or path not in bundle.files:
            continue
        try:
            data = load_yaml(bundle.files[path].decode("utf-8"))
        except (UnicodeDecodeError, yaml.YAMLError) as e:
            err("entities-parse", f"not valid YAML: {e}", path)
            continue
        if data is None:
            data = []
        v = _sub_validator(f"{kind}File")
        for e in v.iter_errors(data):
            loc = "/".join(str(p) for p in e.absolute_path) or "(root)"
            err("schema", f"{loc}: {e.message}", path)
        recs: dict[str, dict] = {}
        for r in data if isinstance(data, list) else []:
            if not isinstance(r, dict):
                continue
            rid = r.get("id")
            if rid in recs:
                err("duplicate-id", f"duplicate {kind} id {rid!r}", path)
            if isinstance(rid, str):
                recs[rid] = r
        entities[kind] = recs

    # -- 7. references -----------------------------------------------------
    keys = {k.get("key"): k for k in bundle.entries("keys")}
    seen_keys: set[str] = set()
    for k in bundle.entries("keys"):
        if k.get("key") in seen_keys:
            err("duplicate-id", f"duplicate key {k.get('key')!r}", MANIFEST)
        seen_keys.add(k.get("key"))

    def resolve(s: str) -> str | None:
        """None if `s` resolves; otherwise why not."""
        r = parse_ref(s)
        if r is None:
            return "not a valid reference"
        if r.external:
            return None
        if r.kind == "map":
            info = infos.get(r.id)
            if info is None and bundle.map_entry(r.id) is None:
                return f"no map {r.id!r}"
            if r.fragment and info is not None and info.graph is not None \
                    and r.fragment not in info.nodes:
                return f"map {r.id!r} has no node {r.fragment!r}"
            return None
        if r.kind == "text":
            if r.id not in docs and bundle.text_entry(r.id) is None:
                return f"no text {r.id!r}"
            if r.fragment and r.id in docs and r.fragment not in docs[r.id].anchors():
                return f"text {r.id!r} has no anchor #{r.fragment}"
            return None
        if r.kind == "key":
            return None if r.id in keys else f"no key {r.id!r}"
        if r.kind == "asset":
            return None if bundle.asset_entry(r.id) else f"no asset {r.id!r}"
        if r.kind == "worldmap":
            return None if any(w.get("name") == r.id for w in bundle.entries("worldmaps")) \
                else f"no worldmap {r.id!r}"
        ek = ENTITY_REF_KINDS.get(r.kind)
        if ek:
            return None if r.id in entities.get(ek, {}) else f"no {r.kind} {r.id!r}"
        return "unknown reference kind"

    def check_refs(refs: list[str], where: str, path: str | None) -> None:
        for s in refs:
            why = resolve(s)
            if why:
                err("dangling-ref", f"{where}: {s} — {why}", path)

    for k in bundle.entries("keys"):
        where = f"key {k.get('key')}"
        node = k.get("node")
        if isinstance(node, str):
            check_refs([node], where, MANIFEST)
        check_refs([v for v in [k.get("text"), k.get("encounter")] if isinstance(v, str)]
                   + [v for v in (k.get("assets") or []) + (k.get("npcs") or [])
                      if isinstance(v, str)], where, MANIFEST)

    start = m.get("start") if isinstance(m.get("start"), dict) else None
    if start:
        smap = start.get("map")
        if smap and smap not in map_names:
            err("dangling-ref", f"start: no map {smap!r}", MANIFEST)
        elif smap and start.get("node") and smap in infos and infos[smap].graph is not None \
                and start["node"] not in infos[smap].nodes:
            err("dangling-ref", f"start: map {smap!r} has no node {start['node']!r}", MANIFEST)
        if isinstance(start.get("text"), str):
            check_refs([start["text"]], "start", MANIFEST)

    for t in texts_meta:
        doc = docs.get(t.get("id"))
        if doc is None:
            continue
        check_refs(refs_in_markdown(doc.body), f"text {t['id']!r}", t["file"])
    ent_paths = m.get("entities") if isinstance(m.get("entities"), dict) else {}
    for kind, recs in entities.items():
        for rid, r in recs.items():
            check_refs(refs_in_value(r), f"{kind} {rid!r}", ent_paths.get(kind))

    # -- 8. audience leaks -------------------------------------------------
    def audience_of(s: str) -> str:
        r = parse_ref(s)
        if r is None:
            return "gm"
        if r.kind == "asset":
            return (bundle.asset_entry(r.id) or {}).get("audience", "gm")
        if r.kind == "text":
            return (bundle.text_entry(r.id) or {}).get("audience", "gm")
        ek = ENTITY_REF_KINDS.get(r.kind)
        if ek:
            return (entities.get(ek, {}).get(r.id) or {}).get("audience", "gm")
        return "player"  # maps/keys/external refs carry no audience of their own

    for t in texts_meta:
        if t.get("audience") != "player" or t.get("id") not in docs:
            continue
        for s in refs_in_markdown(docs[t["id"]].body):
            if audience_of(s) == "gm" and resolve(s) is None:
                warn("audience-leak",
                     f"player text {t['id']!r} references GM-only {s}", t["file"])
    for kind, recs in entities.items():
        for rid, r in recs.items():
            if r.get("audience") != "player":
                continue
            for s in refs_in_value(r):
                if audience_of(s) == "gm" and resolve(s) is None:
                    warn("audience-leak",
                         f"player {kind} {rid!r} references GM-only {s}", ent_paths.get(kind))

    # -- 9. coverage + environment ----------------------------------------
    keyed_texts = {k.get("text") for k in bundle.entries("keys") if isinstance(k.get("text"), str)}
    for t in texts_meta:
        doc = docs.get(t.get("id"))
        if doc is None or not t.get("map"):
            continue
        for sec in doc.keyed():
            if f"text:{t['id']}#{sec.anchor}" not in keyed_texts:
                warn("unkeyed-section",
                     f"line {sec.line}: section {sec.key} has no keys[] entry "
                     f"(see `dscn keys --suggest`)", t["file"])

    req = (m.get("requires") or {}).get("dungml") if isinstance(m.get("requires"), dict) else None
    if isinstance(req, str):
        have = _dungml_version()
        if have and not _satisfies(have, req):
            warn("requires", f"bundle requires dungml {req}, this is {have}", MANIFEST)

    return Report(diagnostics=diags, maps=infos, texts=docs, maps_checked=dungml is not None)


def _has_map_block(src: bytes) -> bool:
    return re.search(rb'(?m)^\s*map\s+"', src) is not None


def _dungml_version() -> str | None:
    try:
        from delve.maps.dsl import __version__
    except ImportError:
        return None
    return __version__.split("+", 1)[0]


def _vt(s: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", s)[:3])


def _satisfies(have: str, spec: str) -> bool:
    """Tiny comparator for `>=x.y`, `>x`, `==x.y.z`, `<x` (comma = and)."""
    for part in spec.split(","):
        part = part.strip()
        m = re.match(r"^(>=|<=|==|>|<)?\s*([\d.]+)$", part)
        if not m:
            return True  # unparseable: don't nag
        op, ver = m.group(1) or ">=", _vt(m.group(2))
        h = _vt(have)
        ok = {">=": h >= ver, "<=": h <= ver, "==": h == ver, ">": h > ver, "<": h < ver}[op]
        if not ok:
            return False
    return True
