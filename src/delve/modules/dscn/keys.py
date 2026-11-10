"""`keys[]` suggestions (spec §5.3) and key lookup.

The bundle's `keys[]` is the only source of truth; this module proposes
entries for an author to review, it never writes them on its own.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .container import Bundle
from .refs import slugify
from .text import Section, TextDoc, parse_text

if TYPE_CHECKING:
    from .maps import MapInfo


def _norm(s: str) -> str:
    s = re.sub(r"\*\([^)]*\)\*|\([^)]*\)", "", s)  # drop "*(locked)*" style notes
    return re.sub(r"[^a-z0-9]+", "", s.lower())


def match_node(sec: Section, info: "MapInfo") -> str | None:
    if info.graph is None:
        return None
    nodes = info.graph.nodes
    for kind in ("room", "corridor"):
        nid = f"{kind}.{sec.anchor}"
        if nid in nodes:
            return nid
    if sec.key:
        for kind in ("room", "corridor"):
            nid = f"{kind}.{sec.key}"
            if nid in nodes:
                return nid
    want = _norm(sec.title)
    if not want:
        return None
    hits = [n.id for n in nodes.values() if _norm(n.name) == want]
    return hits[0] if len(hits) == 1 else None


def suggest(bundle: Bundle) -> list[dict]:
    """Candidate `keys[]` entries for keyed sections not yet keyed.
    Needs dungml (it matches headings against the map graph)."""
    from .maps import analyse_maps

    infos = analyse_maps(bundle)
    have = {k.get("text") for k in bundle.entries("keys")}
    have_keys = {k.get("key") for k in bundle.entries("keys")}
    out: list[dict] = []
    for t in bundle.entries("text"):
        mname = t.get("map")
        if not mname or mname not in infos or t.get("file") not in bundle.files:
            continue
        doc = parse_text(bundle.read_text(t["file"]))
        for sec in doc.keyed():
            tref = f"text:{t['id']}#{sec.anchor}"
            if tref in have or sec.key in have_keys:
                continue
            entry: dict = {"key": sec.key, "title": sec.title, "text": tref}
            node = match_node(sec, infos[mname])
            if node:
                entry["node"] = f"map:{mname}#{node}"
            out.append(entry)
    return out


@dataclass
class KeyedText:
    key: str
    title: str
    node: str | None
    read_aloud: str
    gm_md: str
    entry: dict


def _doc(bundle: Bundle, tid: str, cache: dict[str, TextDoc]) -> TextDoc | None:
    if tid not in cache:
        t = bundle.text_entry(tid)
        if t is None or t.get("file") not in bundle.files:
            return None
        cache[tid] = parse_text(bundle.read_text(t["file"]))
    return cache[tid]


def keyed_texts(bundle: Bundle) -> list[KeyedText]:
    """Every `keys[]` entry joined to its section text."""
    cache: dict[str, TextDoc] = {}
    out: list[KeyedText] = []
    for k in bundle.entries("keys"):
        read_aloud = gm = ""
        tref = k.get("text") or ""
        if tref.startswith("text:"):
            tid, _, anchor = tref[5:].partition("#")
            doc = _doc(bundle, tid, cache)
            sec = doc.section(anchor) if (doc and anchor) else None
            if sec:
                read_aloud, gm = sec.read_aloud, sec.gm_md
        out.append(KeyedText(
            key=str(k.get("key")), title=k.get("title") or "",
            node=k.get("node"), read_aloud=read_aloud, gm_md=gm, entry=k,
        ))
    return out


def slug_key(key: str) -> str:
    return slugify(key)
