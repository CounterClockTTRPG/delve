"""Converters into the format: ttrpg2 module text and legacy `.dmapproj`."""
from __future__ import annotations

import io
import json
import zipfile

from .container import Bundle, ScenarioError
from .text import add_anchors


def convert_module(
    bundle: Bundle,
    module_md: str,
    *,
    text_id: str,
    map_name: str | None = None,
    title: str | None = None,
    audience: str | None = None,
    file: str | None = None,
) -> tuple[dict, int]:
    """Add a ttrpg2 `reference/*-module.md` to `bundle` as keyed text.

    Keyed headings (`### W101. Dwarven Guard Post`) get explicit `{#w101}`
    anchors and "(read aloud)" sections become blockquotes, so the text
    follows §5.2 without hand edits. Returns (text entry, anchors added).
    """
    converted, count = add_anchors(module_md)
    entry = bundle.add_text(
        text_id, converted,
        file=file or (f"text/keyed/{text_id}.md" if map_name else None),
        title=title, audience=audience, map=map_name,
    )
    return entry, count


def upgrade_dmapproj(data: bytes, *, title: str | None = None) -> Bundle:
    """A `.dmapproj` project export → a maps-only scenario with a fresh id.

    Libraries are recognised by content (no top-level `map` block), the
    same rule dungml's `Map.kind` uses; missing bundled includes are then
    vendored so the result validates on its own.
    """
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
        manifest = json.loads(zf.read("manifest.json"))
    except (zipfile.BadZipFile, KeyError, json.JSONDecodeError) as e:
        raise ScenarioError(f"not a .dmapproj archive: {e}") from e
    if manifest.get("format") != "dungml-project":
        raise ScenarioError("not a dungml-project archive")
    bundle = Bundle.new(title or str(manifest.get("name") or "Imported project"))
    first = True
    for entry in manifest.get("maps", []):
        if not isinstance(entry, dict) or not entry.get("file"):
            continue
        try:
            src = zf.read(entry["file"]).decode("utf-8")
        except (KeyError, UnicodeDecodeError):
            continue
        name = str(entry.get("name") or "map")
        role = "library" if 'map "' not in src else "map"
        bundle.add_map(name, src, role=role, default=(role == "map" and first))
        if role == "map":
            first = False
    from .maps import vendor

    vendor(bundle)
    return bundle
