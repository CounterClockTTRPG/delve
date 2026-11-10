"""Fix-it comments on a module (table voice and fixes Task F2.2): the comments, their job's review, and Keep or
Reject. Organisers only.

A comment is sent with `POST /api/modules/{id}/fixits` (201), which starts its job unless the module has one running
or waiting for review (`delve.conversions.fixit`); the job's progress arrives as `conversion` events, and each change
of a comment as a `modules` event. The review (`GET /api/fixits/{conversion_id}/review`) shows what Keep would write:
the texts it changes, before and after; the maps, before and after, as their sources and drawn; the entities added,
changed and removed. Keep answers the new revision, or 409 `{"error", "code": "stale"}` when the module changed since
the job read it, for which the page offers to run the comment again (`…/rerun`)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict
from starlette.concurrency import run_in_threadpool

from delve.conversions.fixit import (
    FixitStale,
    NotReviewable,
    close_comment,
    comment_json,
    comments,
    is_stale,
    keep,
    reject,
    rerun,
    result_of,
    send_comment,
)
from delve.domain.modules import ModuleMap
from delve.maps.dsl.errors import DmapError
from delve.maps.sources import parse_map
from delve.modules.source import ModuleSource, load_source
from delve.web.auth import Organiser, Principal
from delve.web.routes.conversions import conversions
from delve.web.routes.dsl import render_json
from delve.web.routes.modules import changed, get_module

router = APIRouter()

NO_REVIEW = "No fix-it result waits for review."
NO_COMMENT = "No such comment."
TEXT_MAX = 4000


class CommentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    anchor: dict[str, Any] | None = None


def _author(principal: Principal) -> str:
    if principal.account is not None:
        return principal.account.username
    return principal.seat.name if principal.seat is not None else ""


@router.get("/api/modules/{module_id}/fixits")
def list_comments(request: Request, principal: Organiser, module_id: str) -> list[dict]:
    """The module's comments, oldest first, each with its job's `job` (status and progress; null before one)."""
    get_module(request, module_id)
    storage = request.app.state.storage
    return [comment_json(storage, comment) for comment in comments(storage, module_id)]


@router.post("/api/modules/{module_id}/fixits", status_code=201)
async def send(request: Request, principal: Organiser, module_id: str, body: CommentIn) -> dict:
    """Send a comment; 422 for an empty or too long one, or an anchor that names nothing of the module."""
    get_module(request, module_id)
    if len(body.text) > TEXT_MAX:
        raise HTTPException(status_code=422, detail=f"A comment is at most {TEXT_MAX} characters.")
    services = conversions(request.app)
    try:
        comment = send_comment(services, module_id, body.text, anchor=body.anchor, author=_author(principal))
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    changed(request, module_id)
    return comment_json(services.storage, comment)


def _texts(before: ModuleSource, after: ModuleSource) -> list[dict[str, Any]]:
    old = {t.id: t for t in before.texts}
    new = {t.id: t for t in after.texts}
    shown = []
    for id in [*old, *(i for i in new if i not in old)]:
        was, now = old.get(id), new.get(id)
        if was != now:
            title = (now or was).title  # type: ignore[union-attr]
            shown.append(
                {
                    "id": id,
                    "title": title,
                    "before": was.markdown if was else None,
                    "after": now.markdown if now else None,
                }
            )
    return shown


def _drawn(maps: list[ModuleMap] | tuple[ModuleMap, ...], name: str) -> str | None:
    try:
        return render_json(parse_map(maps, name), None)["svg"]
    except (DmapError, KeyError, HTTPException):
        return None


def _maps(before: tuple[ModuleMap, ...], after: list[ModuleMap]) -> list[dict[str, Any]]:
    old = {m.name: m for m in before}
    new = {m.name: m for m in after}
    shown = []
    for name in [*old, *(n for n in new if n not in old)]:
        was, now = old.get(name), new.get(name)
        if was == now:
            continue
        shown.append(
            {
                "name": name,
                "before": was.source if was else None,
                "after": now.source if now else None,
                "before_svg": _drawn(before, name) if was and was.role == "map" else None,
                "after_svg": _drawn(after, name) if now and now.role == "map" else None,
            }
        )
    return shown


def _records(source: ModuleSource) -> dict[tuple[str, str], dict[str, Any]]:
    return {(kind, str(r.get("id"))): r for kind, records in source.entities.items() for r in records}


def _entities(before: ModuleSource, after: ModuleSource) -> dict[str, list[dict[str, Any]]]:
    old, new = _records(before), _records(after)

    def shown(key: tuple[str, str], record: dict[str, Any]) -> dict[str, Any]:
        return {"kind": key[0], "id": key[1], "name": record.get("name") or key[1], "record": record}

    return {
        "added": [shown(k, r) for k, r in new.items() if k not in old],
        "changed": [{**shown(k, r), "before": old[k]} for k, r in new.items() if k in old and old[k] != r],
        "removed": [shown(k, r) for k, r in old.items() if k not in new],
    }


def _review(storage: Any, conversion_id: str) -> dict[str, Any]:
    job, source, maps = result_of(storage, conversion_id)
    module_id = (job.target or {})["module_id"]
    module = storage.modules.get(module_id)
    before = load_source(storage, module_id)
    return {
        "conversion_id": job.id,
        "module_id": module_id,
        "revision": (job.result or {}).get("revision"),
        "summary": (job.result or {}).get("summary", ""),
        "stale": is_stale(storage, job),
        "comments": [c.id for c in storage.module_comments.for_conversion(job.id) if c.status == "review"],
        "texts": _texts(before, source),
        "maps": _maps(module.maps, maps),
        "entities": _entities(before, source),
    }


@router.get("/api/fixits/{conversion_id}/review")
async def review(request: Request, principal: Organiser, conversion_id: str) -> dict:
    """What Keep would write over the module as it is now; `stale` when the module changed since the job read it."""
    storage = request.app.state.storage
    try:
        return await run_in_threadpool(_review, storage, conversion_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=NO_REVIEW) from None


def _module_of(request: Request, conversion_id: str) -> str:
    job = request.app.state.storage.conversions.get(conversion_id)
    module_id = (job.target or {}).get("module_id") if job is not None and job.kind == "fixit" else None
    if module_id is None:
        raise HTTPException(status_code=404, detail=NO_REVIEW)
    return module_id


@router.post("/api/fixits/{conversion_id}/keep")
async def keep_route(request: Request, principal: Organiser, conversion_id: str) -> dict:
    """Write the result as a new revision: `{revision}`. 409 `{"error", "code": "stale"}` for a module changed since."""
    module_id = _module_of(request, conversion_id)
    try:
        revision = keep(conversions(request.app), conversion_id)
    except NotReviewable:
        raise HTTPException(status_code=404, detail=NO_REVIEW) from None
    except FixitStale as error:
        raise HTTPException(status_code=409, detail={"error": str(error), "code": "stale"}) from None
    changed(request, module_id)
    return {"revision": revision.number}


@router.post("/api/fixits/{conversion_id}/reject")
async def reject_route(request: Request, principal: Organiser, conversion_id: str) -> dict:
    """Drop the result; nothing is saved."""
    module_id = _module_of(request, conversion_id)
    try:
        reject(conversions(request.app), conversion_id)
    except NotReviewable:
        raise HTTPException(status_code=404, detail=NO_REVIEW) from None
    changed(request, module_id)
    return {"rejected": conversion_id}


def _comment(request: Request, comment_id: str) -> str:
    comment = request.app.state.storage.module_comments.get(comment_id)
    if comment is None:
        raise HTTPException(status_code=404, detail=NO_COMMENT)
    return comment.module_id


@router.post("/api/fixit-comments/{comment_id}/rerun")
async def rerun_route(request: Request, principal: Organiser, comment_id: str) -> dict:
    """Run a failed, rejected or stale comment again on the module as it is now; 409 for another status."""
    module_id = _comment(request, comment_id)
    services = conversions(request.app)
    try:
        comment = rerun(services, comment_id)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    changed(request, module_id)
    return comment_json(services.storage, comment)


@router.post("/api/fixit-comments/{comment_id}/close")
def close_route(request: Request, principal: Organiser, comment_id: str) -> dict:
    """Close an open comment without running it; 409 for another status."""
    module_id = _comment(request, comment_id)
    storage = request.app.state.storage
    try:
        comment = close_comment(storage, comment_id)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    changed(request, module_id)
    return comment_json(storage, comment)
