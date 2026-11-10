"""Dangling refs rewritten or dropped (faithful modules A1): a module made from a book or a request always exports.

Claude's entity drafts name records that were merged away (`npc:bosun-2`), or never made (`npc:bosun`, with only
`the-bosun`), and pictures and headings that aren't there. `repair_refs` goes through every ref of a source, in its
texts, its entity records and its `keys[]` entries, read as `source._missing_refs` and `dscn validate` read them, and
leaves none dangling:

- **An entity ref** (every kind of `ENTITY_REF_KINDS`) in `renamed` is rewritten to the record kept; one to an id
  nothing has is rewritten when exactly one record of its kind matches (`_matches`), with a `ref-rewritten` warning.
- **A `key:`, `text:` or `map:` ref** is resolved within the record's own text (`_own_text`): a `key:` ref to one of its
  keyed headings gets that heading's `keys[]` entry, made when there is none; a `text:` ref to a fragment it hasn't, or
  a `map:` ref to a map or room the module hasn't, becomes `text:<own text>#<anchor>` when the fragment names one of
  its keyed headings (by key, or by title), with a `ref-rewritten` warning. A `keys[]` entry's `node` is never
  rewritten to a text: it is dropped, and the entry waits for its heading's room.
- **Otherwise the ref is dropped,** with a `ref-dropped` warning naming where it was: removed from a list, its field
  removed when it is a scalar; in Markdown, `[label](kind:id)` becomes `label`, `[[kind:id]]` the id with its hyphens as
  spaces, and `![…](kind:id)` is removed. An encounter's table row whose `creature` is dropped keeps it as its `result`,
  in words; a `fixed` row without its creature is removed, since the format needs one.

An `asset:` ref resolves to an attachment, a `worldmap:` ref to a world map, and the external kinds (`monster:`,
`item:`, `spell:`) are the reference's, never touched. The source given is left as it is.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from delve.domain.modules import ModuleMap
from delve.maps.dsl import DmapParseError
from delve.maps.sources import cached_map, graph_of
from delve.modules.dscn import parse_ref, parse_text, slugify
from delve.modules.dscn.refs import ENTITY_REF_KINDS, KINDS, Ref, is_ref, refs_in_value
from delve.modules.source import ModuleSource, TextDoc, Warning, scoped_keys

_KIND = "|".join(KINDS)
_MD_REF = re.compile(
    rf"(?P<image>!?)\[(?P<label>[^\]\n]*)\]\(\s*(?P<link>(?:{_KIND}):[^)\s]+)\s*\)"
    rf"|\[\[\s*(?P<wiki>(?:{_KIND}):[^\]\s]+)\s*\]\]"
    rf"|\]\(\s*(?P<bare>(?:{_KIND}):[^)\s]+)\s*\)"
)
"""A ref in Markdown: a link or an image (`[label](ref)`, `![alt](ref)`), the `[[ref]]` shorthand, or, for a label
holding brackets, a link's `](ref)` alone."""
_KEY_LIKE = re.compile(r"^[a-z]?\d+[a-z]?$")
_SKETCHED = re.compile(r"^r([a-z]?\d+[a-z]?)$")
"""A room of a map `sketch_map` drew: `r<key>`."""
_NUMBERED = re.compile(r"-\d+$")
_PLAIN_FIELDS = frozenset({"name", "text"})
"""A record's fields that are its words, never only a ref: a dropped ref there leaves its words."""
_DROP = object()


def _words(ref: Ref) -> str:
    return ref.id.replace("-", " ")


@dataclass
class _Repair:
    source: ModuleSource
    renamed: Mapping[str, str]
    maps: Sequence[ModuleMap]
    keys: list[dict[str, Any]]
    headings_are_keys: bool = False
    warnings: list[Warning] = field(default_factory=list)
    _nodes: dict[str, set[str] | None] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.texts = {doc.id: doc for doc in self.source.texts}
        parsed = {doc.id: parse_text(doc.markdown) for doc in self.source.texts}
        self.sections = {id: text.keyed() for id, text in parsed.items()}
        self.anchors = {id: text.anchors() for id, text in parsed.items()}
        self.scoped = scoped_keys(self.source.texts)
        self.ids = {kind: {str(r.get("id")) for r in records} for kind, records in self.source.entities.items()}
        self.attachments = {a.id for a in self.source.attachments}
        self.worldmaps = {w.name for w in self.source.worldmaps}

    # --- what a ref is ---------------------------------------------------------------------------------------------

    def _map_nodes(self, name: str) -> set[str] | None:
        """The nodes of the module's map `name`, or None when it doesn't parse (any room is taken as there)."""
        if name not in self._nodes:
            try:
                self._nodes[name] = set(graph_of(cached_map(self.maps, name)).nodes)
            except (DmapParseError, KeyError):
                self._nodes[name] = None
        return self._nodes[name]

    def resolves(self, ref: Ref) -> bool:
        if ref.external:
            return True
        if ref.kind == "asset":
            return ref.id in self.attachments
        if ref.kind == "worldmap":
            return ref.id in self.worldmaps
        if ref.kind == "key":
            if self.headings_are_keys and ref.id in self.scoped.values():
                return True
            return any(str(k.get("key")) == ref.id for k in self.keys)
        if ref.kind == "text":
            anchors = self.anchors.get(ref.id)
            return anchors is not None and (ref.fragment is None or ref.fragment in anchors)
        if ref.kind == "map":
            if not any(m.name == ref.id for m in self.maps):
                return False
            nodes = self._map_nodes(ref.id)
            return ref.fragment is None or nodes is None or ref.fragment in nodes
        kind = ENTITY_REF_KINDS.get(ref.kind)
        return kind is None or ref.id in self.ids.get(kind, set())

    def _matches(self, ref: Ref) -> list[str]:
        """The ids of `ref`'s kind that it means: the record whose id, or name's slug, is the ref's id without a trailing
        `-<digits>` and a leading `the-` or `a-`, or that with `the-` before it."""
        bare = _NUMBERED.sub("", ref.id)
        bare = re.sub(r"^(?:the|a)-", "", bare) or bare
        wanted = {bare, f"the-{bare}"}
        records = self.source.entities.get(ENTITY_REF_KINDS[ref.kind], [])
        found = [
            str(r.get("id"))
            for r in records
            if str(r.get("id")) in wanted or (isinstance(r.get("name"), str) and slugify(r["name"]) in wanted)
        ]
        return list(dict.fromkeys(found))

    def _heading(self, own: TextDoc | None, fragment: str | None) -> str | None:
        """The anchor of the keyed heading of `own` that `fragment` names: by its key (`7`, `7-the-kitchen`,
        `room.7`, or a sketched map's `room.r7`) or its title's slug, when exactly one does."""
        if own is None or not fragment:
            return None
        want = fragment.casefold()
        tokens = set()
        for token in re.split(r"[-._]", want):
            sketched = _SKETCHED.match(token)
            tokens |= {token} if _KEY_LIKE.match(token) else set()
            tokens |= {sketched.group(1)} if sketched else set()
        hits = [
            str(s.anchor)
            for s in self.sections[own.id]
            if str(s.key).casefold() == want or str(s.key).casefold() in tokens or slugify(s.title) == want
        ]
        hits = list(dict.fromkeys(hits))
        return hits[0] if len(hits) == 1 else None

    def _key_entry(self, own: TextDoc | None, key: str) -> str | None:
        """The key as written of `own`'s heading keyed `key`: its `keys[]` entry's, made when it has none with the
        heading's scoped key (`scoped_keys`), so a key two parts share is `<part>-<key>`; None when it has no such
        heading."""
        section = next((s for s in self.sections[own.id] if str(s.key) == key), None) if own else None
        if own is None or section is None:
            return None
        text = f"text:{own.id}#{section.anchor}"
        found = next((k for k in self.keys if k.get("text") == text and k.get("key") is not None), None)
        if found is None:
            found = {"key": self.scoped[(own.id, str(section.anchor))], "title": section.title, "text": text}
            self.keys.append(found)
        return str(found["key"])

    def fix(self, raw: str, own: TextDoc | None, where: str) -> str | None:
        """`raw` as it is when it resolves, the ref it is rewritten to, or None when it is dropped."""
        ref = parse_ref(raw)
        if ref is None or self.resolves(ref):
            return raw
        new: str | None = None
        if ref.kind in ENTITY_REF_KINDS:
            kept = self.renamed.get(f"{ref.kind}:{ref.id}")
            if kept is None:
                found = self._matches(ref)
                kept = f"{ref.kind}:{found[0]}" if len(found) == 1 else None
            if kept is not None:
                new = kept + (f"#{ref.fragment}" if ref.fragment else "")
        elif ref.kind == "key":
            written = self._key_entry(own, ref.id)
            if written == ref.id:
                return raw
            new = f"key:{written}" if written is not None else None
        elif ref.kind in ("text", "map"):
            target = self.texts.get(ref.id) if ref.kind == "text" else None
            anchor = self._heading(target or own, ref.fragment)
            if anchor is not None:
                new = f"text:{(target or own).id}#{anchor}"  # the heading is in `target or own`
        if new is not None:
            self.warn("ref-rewritten", f"{where} referred to {raw}, which isn't there: it now refers to {new}.", raw)
            return new
        self.drop(raw, where)
        return None

    def drop(self, raw: str, where: str) -> None:
        self.warn("ref-dropped", f"{where} referred to {raw}, which isn't there: the reference was removed.", raw)

    def warn(self, code: str, message: str, raw: str) -> None:
        """One warning for a ref where it is, however often it is there."""
        warning = Warning(code, message, raw)
        if warning not in self.warnings:
            self.warnings.append(warning)

    # --- where refs are --------------------------------------------------------------------------------------------

    def markdown(self, text: str, own: TextDoc | None, where: str) -> str:
        def replaced(match: re.Match[str]) -> str:
            raw = match.group("link") or match.group("wiki") or match.group("bare")
            new = self.fix(raw, own, where)
            if new == raw:
                return match.group(0)
            if new is not None:
                return match.group(0).replace(raw, new, 1)
            if match.group("wiki"):
                return _words(parse_ref(raw))
            if match.group("bare"):
                return "]"
            return "" if match.group("image") else match.group("label")

        return _MD_REF.sub(replaced, text)

    def value(self, value: Any, own: TextDoc | None, where: str, plain: frozenset[str] = frozenset()) -> Any:
        """`value` with its refs fixed; `_DROP` for a ref that is dropped. A dropped ref in one of its `plain` fields
        leaves its words."""
        if isinstance(value, str):
            if is_ref(value):
                new = self.fix(value.strip(), own, where)
                return _DROP if new is None else (value if new == value.strip() else new)
            if "\n" in value or "](" in value or "[[" in value:
                new = self.markdown(value, own, where)
                return new.rstrip() if value == value.rstrip() else new
            return value
        if isinstance(value, list):
            return [v for v in (self.value(x, own, where) for x in value) if v is not _DROP]
        if isinstance(value, dict):
            out: dict[str, Any] = {}
            for k, v in value.items():
                if isinstance(k, str) and k.startswith("x-"):
                    out[k] = v  # extensions are opaque
                    continue
                new = self.value(v, own, where)
                if new is not _DROP:
                    out[k] = new
                elif k == "creature" and "result" not in value:
                    out["result"] = _words(parse_ref(v.strip()))
                elif k in plain:
                    out[k] = _words(parse_ref(v.strip()))
            return out
        return value

    def own_text(self, record: Mapping[str, Any]) -> TextDoc | None:
        """The text a record is in: the text its `location`, `text` or `key` names (a `key:` ref by its `keys[]` entry),
        else the first text any of its refs names, else the module's one text when it has one."""
        for name in ("location", "text", "key"):
            ref = parse_ref(str(record.get(name) or ""))
            if ref is not None and ref.kind == "text" and ref.id in self.texts:
                return self.texts[ref.id]
            if ref is not None and ref.kind == "key":
                entry = next((k for k in self.keys if str(k.get("key")) == ref.id), None)
                text = parse_ref(str(entry.get("text") or "")) if entry else None
                if text is not None and text.kind == "text" and text.id in self.texts:
                    return self.texts[text.id]
        for raw in refs_in_value(dict(record)):
            ref = parse_ref(raw)
            if ref is not None and ref.kind == "text" and ref.id in self.texts:
                return self.texts[ref.id]
        return self.source.texts[0] if len(self.source.texts) == 1 else None


def repair_refs(
    source: ModuleSource,
    renamed: Mapping[str, str] = {},
    *,
    maps: Sequence[ModuleMap] = (),
    headings_are_keys: bool = False,
) -> tuple[ModuleSource, list[Warning]]:
    """`source` with no dangling ref, and a `ref-rewritten` or `ref-dropped` warning for each one it had. `renamed`
    holds the full refs of records merged into another (`{"npc:bosun-2": "npc:the-bosun"}`), and `maps` the module's
    maps, which its `map:` refs name. With `headings_are_keys` (the export, which writes a key for every keyed heading
    a `key:` ref names), a `key:` ref to a heading's scoped key resolves without a `keys[]` entry."""
    repair = _Repair(source, renamed, maps, [dict(k) for k in source.keys], headings_are_keys)

    texts = [replace(doc, markdown=repair.markdown(doc.markdown, doc, doc.title)) for doc in source.texts]

    entities: dict[str, list[dict[str, Any]]] = {}
    for kind, records in source.entities.items():
        fixed = []
        for record in records:
            own = repair.own_text(record)
            record = repair.value(record, own, f"{kind} {record.get('id')}", _PLAIN_FIELDS)
            if kind == "encounters" and isinstance(record.get("fixed"), list):
                record["fixed"] = [r for r in record["fixed"] if not isinstance(r, dict) or "creature" in r]
            fixed.append(record)
        entities[kind] = fixed

    keys = []
    for entry in list(repair.keys):
        text = parse_ref(str(entry.get("text") or ""))
        own = repair.texts.get(text.id) if text is not None and text.kind == "text" else None
        where = f"key {entry.get('key')}"
        node = entry.get("node")
        if isinstance(node, str) and is_ref(node) and not _node_resolves(repair, node):
            repair.drop(node.strip(), where)
            entry = {k: v for k, v in entry.items() if k != "node"}
        keys.append(repair.value(entry, own, where))
    keys += repair.keys[len(keys) :]  # made for a `key:` ref met while fixing the keys themselves

    repaired = replace(source, texts=texts, entities=entities, keys=keys)
    return (source, []) if not repair.warnings and repaired == source else (repaired, repair.warnings)


def _node_resolves(repair: _Repair, raw: str) -> bool:
    ref = parse_ref(raw)
    return ref is not None and ref.kind == "map" and repair.resolves(ref)
