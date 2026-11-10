"""`marker … image "asset:<id>"` resolution (spec §9.2).

Assets are inlined as data URIs so a rendered SVG stays self-contained —
the token-gated `<img src=…/render?token=…>` contract keeps working with
no second authorised fetch. A players' (fogged) render inlines only
`player`-audience assets; a GM asset's marker falls back to its glyph.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Iterable

if TYPE_CHECKING:  # dungml is only needed by callers that hold a parsed map
    from delve.maps.dsl import DungeonMap, Marker

from .container import Bundle
from .media import IMAGE_TYPES, data_uri

ASSET_PREFIX = "asset:"


@dataclass(frozen=True)
class ResolvedAsset:
    mime: str
    data: bytes
    audience: str = "gm"


Resolver = Callable[[str], "ResolvedAsset | None"]


def iter_markers(dmap: "DungeonMap") -> "Iterable[Marker]":
    yield from dmap.markers
    for layer in getattr(dmap, "layers", []) or []:
        yield from getattr(layer, "markers", []) or []


def asset_markers(dmap: "DungeonMap") -> list[str]:
    """Asset ids referenced by marker images, in order, de-duplicated."""
    out: list[str] = []
    for m in iter_markers(dmap):
        if m.image and m.image.startswith(ASSET_PREFIX):
            aid = m.image[len(ASSET_PREFIX):]
            if aid not in out:
                out.append(aid)
    return out


def inline_marker_images(dmap: "DungeonMap", resolve: Resolver, *, players: bool) -> int:
    """Rewrite `asset:` marker images in place. Returns how many were inlined.

    Unresolvable ids, non-image assets and (for `players`) GM-only assets
    are dropped to `None`, so the renderer draws the marker's glyph rather
    than a broken `<image href="asset:…">`.
    """
    n = 0
    for m in iter_markers(dmap):
        if not (m.image and m.image.startswith(ASSET_PREFIX)):
            continue
        got = resolve(m.image[len(ASSET_PREFIX):])
        if got is None or got.mime not in IMAGE_TYPES or (players and got.audience != "player"):
            m.image = None
            continue
        m.image = data_uri(got.mime, got.data)
        n += 1
    return n


def bundle_resolver(bundle: Bundle) -> Resolver:
    def resolve(aid: str) -> ResolvedAsset | None:
        a = bundle.asset_entry(aid)
        if a is None or a.get("file") not in bundle.files:
            return None
        return ResolvedAsset(a.get("type", ""), bundle.files[a["file"]], a.get("audience", "gm"))

    return resolve
