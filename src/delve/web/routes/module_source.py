"""A module's source (plan 3 Task 3, spec §8.2): its texts and entities, and the links and warnings derived from them.
Organisers only.

Every change goes through `load_source` / `save_source`, so the DM's text is derived again with it, and publishes the
event `modules` with the module's id. The links and warnings answered are the whole module's, as `GET …/source` has
them. Entity records are the format's records, checked against `scenario.schema.json` as they are sent. Every audience is
`gm` or `player`, as the format has it (`docs/data-dictionary.md`).

The routes are sync, so they run in the threadpool (DEL-166): each derives the whole module, which took Thracia 300 ms
on the event loop. A change reads, changes and saves the source holding the module's edit lock (`editing`), so two
saves at once don't lose one.
"""

from __future__ import annotations

import dataclasses
import functools
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Body, HTTPException, Request
from pydantic import BaseModel
from starlette.responses import Response

from delve.modules.dscn import parse_ref
from delve.modules.dscn.refs import ENTITY_REF_KINDS
from delve.modules.source import (
    DEFAULT_AUDIENCES,
    Derived,
    ModuleSource,
    TextDoc,
    derive,
    load_source,
    save_source,
)
from delve.web.routes.modules import Organiser, changed, definition, diagnostic, get_module, schema_diagnostics

router = APIRouter()

FORM_KINDS = {"npcs": "npc", "encounters": "encounter", "factions": "faction", "quests": "quest", "pregens": "pregen"}
"""The entity kinds the editor's forms make, and their schema `$defs`; rumors and secrets stay import-only."""


_locks_lock = threading.Lock()
_locks: dict[str, threading.Lock] = {}


@contextmanager
def editing(module_id: str) -> Iterator[None]:
    """Hold the module's edit lock: a change reads the source, changes it and saves it whole, so two at once in the
    threadpool would lose the first (DEL-166)."""
    with _locks_lock:
        lock = _locks.setdefault(module_id, threading.Lock())
    with lock:
        yield


def edits[**P, R](route: Callable[P, R]) -> Callable[P, R]:
    """The route changes the module `module_id` names, holding its edit lock (`editing`)."""

    @functools.wraps(route)
    def holding(*args: P.args, **kwargs: P.kwargs) -> R:
        with editing(str(kwargs["module_id"])):
            return route(*args, **kwargs)

    return holding


def source_of(request: Request, module_id: str) -> ModuleSource:
    get_module(request, module_id)
    return load_source(request.app.state.storage, module_id)


def save(request: Request, module_id: str, source: ModuleSource) -> Derived:
    derived = save_source(request.app.state.storage, module_id, source)
    changed(request, module_id)
    return derived


def derived_json(derived: Derived) -> dict[str, Any]:
    return {
        "links": [dataclasses.asdict(link) for link in derived.links],
        "warnings": [dataclasses.asdict(warning) for warning in derived.warnings],
        "headings": [dataclasses.asdict(heading) for heading in derived.headings],
    }


def refused(error: str, diagnostics: list[dict[str, Any]]) -> HTTPException:
    return HTTPException(status_code=422, detail={"error": error, "diagnostics": diagnostics})


@router.get("/api/modules/{module_id}/source")
def read_source(request: Request, principal: Organiser, module_id: str) -> dict:
    module = get_module(request, module_id)
    source = load_source(request.app.state.storage, module_id)
    return {**source.to_json(), **derived_json(derive(source, module.maps))}


# --- texts -----------------------------------------------------------------------------------------------------------


class TextIn(BaseModel):
    id: str
    title: str
    audience: Literal["gm", "player"] = "gm"
    map: str | None = None


class TextPatch(BaseModel):
    title: str | None = None
    audience: Literal["gm", "player"] | None = None
    map: str | None = None
    markdown: str | None = None


def _text_title(raw: str) -> str:
    title = raw.strip()
    if not title:
        raise HTTPException(status_code=422, detail="A text needs a title.")
    return title


def _text_map(request: Request, module_id: str, name: str | None) -> str | None:
    playable = {m.name for m in get_module(request, module_id).maps if m.role == "map"}
    if name is not None and name not in playable:
        raise HTTPException(status_code=422, detail=f"The module has no map {name!r}.")
    return name


def _text(source: ModuleSource, text_id: str) -> TextDoc:
    found = next((t for t in source.texts if t.id == text_id), None)
    if found is None:
        raise HTTPException(status_code=404, detail="No such text.")
    return found


@router.post("/api/modules/{module_id}/texts", status_code=201)
@edits
def create_text(request: Request, principal: Organiser, module_id: str, body: TextIn) -> dict:
    source = source_of(request, module_id)
    if not _is_slug(body.id):
        raise HTTPException(status_code=422, detail="A text's id is lowercase letters, digits, '.', '_' or '-'.")
    doc = TextDoc(body.id, _text_title(body.title), body.audience, _text_map(request, module_id, body.map), "")
    if any(t.id == doc.id for t in source.texts):
        raise HTTPException(status_code=409, detail=f"The module already has a text {doc.id!r}.")
    save(request, module_id, dataclasses.replace(source, texts=[*source.texts, doc]))
    return dataclasses.asdict(doc)


@router.put("/api/modules/{module_id}/texts/{text_id}")
@edits
def update_text(request: Request, principal: Organiser, module_id: str, text_id: str, body: TextPatch) -> dict:
    source = source_of(request, module_id)
    doc = _text(source, text_id)
    sent = body.model_fields_set
    doc = dataclasses.replace(
        doc,
        title=_text_title(body.title) if body.title is not None else doc.title,
        audience=body.audience or doc.audience,
        map=_text_map(request, module_id, body.map) if "map" in sent else doc.map,
        markdown=body.markdown if body.markdown is not None else doc.markdown,
    )
    texts = [doc if t.id == text_id else t for t in source.texts]
    derived = save(request, module_id, dataclasses.replace(source, texts=texts))
    return {"text": dataclasses.asdict(doc), **derived_json(derived)}


@router.delete("/api/modules/{module_id}/texts/{text_id}", status_code=204)
@edits
def delete_text(request: Request, principal: Organiser, module_id: str, text_id: str) -> Response:
    """The text goes, and with it the explicit keys that point into it."""
    source = source_of(request, module_id)
    _text(source, text_id)
    keys = [k for k in source.keys if (ref := parse_ref(str(k.get("text") or ""))) is None or ref.id != text_id]
    texts = [t for t in source.texts if t.id != text_id]
    save(request, module_id, dataclasses.replace(source, texts=texts, keys=keys))
    return Response(status_code=204)


def _is_slug(value: str) -> bool:
    return not schema_diagnostics(definition("slug"), value)


# --- entities --------------------------------------------------------------------------------------------------------


def _defname(kind: str) -> str:
    if kind not in FORM_KINDS:
        raise HTTPException(status_code=404, detail="No such kind of entity: npcs, encounters, factions, quests or pregens.")
    return FORM_KINDS[kind]


@router.put("/api/modules/{module_id}/entities/{kind}/{entity_id}")
@edits
def put_entity(
    request: Request,
    principal: Organiser,
    module_id: str,
    kind: str,
    entity_id: str,
    record: Annotated[dict[str, Any], Body()],
) -> dict:
    """Add the record, or replace the one with its id."""
    defname = _defname(kind)
    source = source_of(request, module_id)
    diagnostics = schema_diagnostics(definition(defname), record)
    if record.get("id") != entity_id:
        diagnostics.append(diagnostic("id", f"The record's id must be {entity_id!r}.", "id"))
    if diagnostics:
        raise refused(f"This {defname} doesn't fit the module schema.", diagnostics)
    records = source.entities.get(kind, [])
    if any(r.get("id") == entity_id for r in records):
        records = [record if r.get("id") == entity_id else r for r in records]
    else:
        records = [*records, record]
    derived = save(request, module_id, dataclasses.replace(source, entities={**source.entities, kind: records}))
    return {"record": record, "warnings": derived_json(derived)["warnings"]}


@router.delete("/api/modules/{module_id}/entities/{kind}/{entity_id}", status_code=204)
@edits
def delete_entity(request: Request, principal: Organiser, module_id: str, kind: str, entity_id: str) -> Response:
    _defname(kind)
    source = source_of(request, module_id)
    records = source.entities.get(kind, [])
    if not any(r.get("id") == entity_id for r in records):
        raise HTTPException(status_code=404, detail="No such entity.")
    entities = {**source.entities, kind: [r for r in records if r.get("id") != entity_id]}
    save(request, module_id, dataclasses.replace(source, entities={k: v for k, v in entities.items() if v}))
    return Response(status_code=204)


# --- audiences, many at once (E6) ------------------------------------------------------------------------------------


class AudienceIn(BaseModel):
    refs: list[str]
    audience: Literal["gm", "player"]


@router.post("/api/modules/{module_id}/audience")
@edits
def set_audiences(request: Request, principal: Organiser, module_id: str, body: AudienceIn) -> dict:
    """Give every item named the audience, in one save: `text:<id>`, an entity's `npc:<id>` (any entity kind), or
    `asset:<id>`. All or nothing: an unknown ref is a 422 that names it (`unknown`), and so is an entity record that
    the change would take out of its schema definition (`invalid`; a secret is always `gm`), and nothing changes.
    `changed` counts the items whose audience was another."""
    source = source_of(request, module_id)
    wanted: dict[str, set[str]] = {}
    unknown: list[str] = []
    for raw in body.refs:
        ref = parse_ref(raw)
        known = ref is not None and ref.fragment is None and ref.id in _ids(source, ref.kind)
        if not known:
            unknown.append(raw)
        else:
            wanted.setdefault(ref.kind, set()).add(ref.id)
    if unknown:
        raise HTTPException(
            status_code=422, detail={"error": f"The module has no {', '.join(unknown)}.", "unknown": unknown}
        )
    count = 0

    def given(kind: str, item_id: str, audience: str) -> str:
        nonlocal count
        if item_id not in wanted.get(kind, ()) or audience == body.audience:
            return audience
        count += 1
        return body.audience

    invalid: list[str] = []

    def record(kind: str, record: dict[str, Any]) -> dict[str, Any]:
        prefix = _ref_kind(kind)
        current = _record_audience(kind, record)
        audience = given(prefix, record.get("id"), current)
        if audience == current:
            return record
        changed_record = {**record, "audience": audience}
        if schema_diagnostics(definition(prefix), changed_record):
            invalid.append(f"{prefix}:{record.get('id')}")
        return changed_record

    texts = [dataclasses.replace(t, audience=given("text", t.id, t.audience)) for t in source.texts]
    attachments = [dataclasses.replace(a, audience=given("asset", a.id, a.audience)) for a in source.attachments]
    entities = {kind: [record(kind, r) for r in records] for kind, records in source.entities.items()}
    if invalid:
        error = f"These can't have the audience {body.audience}: {', '.join(invalid)}."
        raise HTTPException(status_code=422, detail={"error": error, "invalid": invalid})
    if count:
        save(request, module_id, dataclasses.replace(source, texts=texts, attachments=attachments, entities=entities))
    return {"changed": count}


def _ref_kind(kind: str) -> str:
    """An entity kind's ref prefix: `npcs` is `npc`."""
    return next((prefix for prefix, k in ENTITY_REF_KINDS.items() if k == kind), kind)


def _record_audience(kind: str, record: dict[str, Any]) -> str:
    return record.get("audience") or DEFAULT_AUDIENCES.get(kind, "gm")


def _ids(source: ModuleSource, kind: str) -> set[str]:
    if kind == "text":
        return {t.id for t in source.texts}
    if kind == "asset":
        return {a.id for a in source.attachments}
    if kind in ENTITY_REF_KINDS:
        return {r.get("id") for r in source.entities.get(ENTITY_REF_KINDS[kind], [])}
    return set()
