"""dungml-scenario — the portable `.dscn` scenario format.

See docs/scenario-format.md. One file (zip) or one directory holding dungml
maps (with their include libraries vendored), keyed module text, entities,
world maps and assets, plus a `keys[]` table joining map nodes to module
room keys.

The core — container, manifest/entity validation, keyed text, refs — needs
only PyYAML and jsonschema, so a consumer without dungml installed (ttrpg2
on a bare interpreter) can still read and write bundles. Everything that
parses maps (`analyse_map(s)`, `vendor`, `suggest`, `render_html`,
`upgrade_dmapproj`, the map checks inside `validate`) imports dungml on
first use.

Ported from dungml (commit a66a1bb).
"""
from __future__ import annotations

from importlib import import_module
from typing import Any

from .assets import ResolvedAsset, asset_markers, bundle_resolver, inline_marker_images
from .container import (
    DEFAULT_LIMITS,
    ENTITY_KINDS,
    EXT,
    FORMAT,
    MANIFEST,
    MEDIA_TYPE,
    VERSION,
    Bundle,
    Limits,
    ScenarioError,
    sha256,
)
from .convert import convert_module, upgrade_dmapproj
from .keys import KeyedText, keyed_texts, suggest
from .media import ALLOWED_TYPES, sniff, type_for_name
from .metadata import normalise as normalise_metadata
from .metadata import parse_timestamp
from .refs import Ref, parse_ref, refs_in_markdown, slugify
from .text import Section, TextDoc, add_anchors, parse_text
from .validate import Diagnostic, Report, check, has_errors, schema, validate

__version__ = "0.1.0"

# name -> module, imported on first attribute access (they need dungml).
_LAZY = {
    "MapInfo": "maps", "analyse_map": "maps", "analyse_maps": "maps", "vendor": "maps",
    "render_html": "render",
}


def __getattr__(name: str) -> Any:
    mod = _LAZY.get(name)
    if mod is None:
        raise AttributeError(f"module 'dungml_scenario' has no attribute {name!r}")
    value = getattr(import_module(f".{mod}", __name__), name)
    globals()[name] = value
    return value


__all__ = [
    "ALLOWED_TYPES", "DEFAULT_LIMITS", "ENTITY_KINDS", "EXT", "FORMAT", "MANIFEST",
    "MEDIA_TYPE", "VERSION",
    "Bundle", "Diagnostic", "KeyedText", "Limits", "MapInfo", "Ref", "Report",
    "ResolvedAsset", "ScenarioError", "Section", "TextDoc",
    "add_anchors", "analyse_map", "analyse_maps", "asset_markers", "bundle_resolver",
    "check", "convert_module", "has_errors", "inline_marker_images", "keyed_texts",
    "normalise_metadata", "parse_ref", "parse_text", "parse_timestamp", "refs_in_markdown", "render_html", "schema", "sha256",
    "slugify", "sniff", "suggest", "type_for_name", "upgrade_dmapproj", "validate",
    "vendor",
]
