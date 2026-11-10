"""Module categories (DEL-114): the organisers' short, ordered list. A module has one or none (`PATCH
/api/modules/{id}` with `category_id`). Every change publishes `modules`, as a module's does, so the lists follow.
Names are trimmed, 1 to 60 characters, unique in any case (409 otherwise)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from starlette.responses import Response

from delve.domain.modules import ModuleCategory
from delve.storage.interfaces import CategoryNameTaken
from delve.web.auth import Organiser

router = APIRouter()

NAME_MAX = 60


class CategoryIn(BaseModel):
    name: str


class CategoryPatch(BaseModel):
    name: str | None = None
    position: int | None = None


def category_json(category: ModuleCategory) -> dict:
    return {"id": category.id, "name": category.name, "position": category.position}


def _name(raw: str) -> str:
    name = raw.strip()
    if not name or len(name) > NAME_MAX:
        raise HTTPException(status_code=422, detail=f"A category's name is 1 to {NAME_MAX} characters.")
    return name


def _changed(request: Request) -> None:
    request.app.state.events.publish("modules", {"id": None, "categories": True})


@router.get("/api/module-categories")
def list_categories(request: Request, principal: Organiser) -> list[dict]:
    return [category_json(c) for c in request.app.state.storage.module_categories.list()]


@router.post("/api/module-categories", status_code=201)
def create_category(request: Request, principal: Organiser, body: CategoryIn) -> dict:
    try:
        category = request.app.state.storage.module_categories.create(_name(body.name))
    except CategoryNameTaken:
        raise HTTPException(status_code=409, detail="Another category has this name.") from None
    _changed(request)
    return category_json(category)


@router.put("/api/module-categories/{category_id}")
def update_category(request: Request, principal: Organiser, category_id: str, body: CategoryPatch) -> list[dict]:
    """Rename it, move it to `position` (from 0), or both; the whole list, in its new order."""
    categories = request.app.state.storage.module_categories
    try:
        if body.name is not None:
            categories.rename(category_id, _name(body.name))
        if body.position is not None:
            categories.move(category_id, body.position)
        elif categories.get(category_id) is None:
            raise KeyError(category_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="No such category.") from None
    except CategoryNameTaken:
        raise HTTPException(status_code=409, detail="Another category has this name.") from None
    _changed(request)
    return [category_json(c) for c in categories.list()]


@router.delete("/api/module-categories/{category_id}", status_code=204)
def delete_category(request: Request, principal: Organiser, category_id: str) -> Response:
    """Delete it; its modules get no category."""
    try:
        request.app.state.storage.module_categories.delete(category_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="No such category.") from None
    _changed(request)
    return Response(status_code=204)
