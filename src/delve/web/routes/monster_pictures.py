"""The kinds of monsters' pictures, for every campaign (DEL-275): `delve.play.monster_pictures`.

`GET /api/monster-pictures/{slug}` is a kind's picture, for anyone Delve knows (a seat, an account, the owner): a
monster's picture is no campaign's secret, and which kinds a fight holds is the timeline's to say; so is which kind
has one (`GET /api/monster-pictures?name=`, for a Rulesets entry). Asking for one to be painted is the organisers'
(`POST /api/monster-pictures`): they pay for it."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from delve.play import monster_pictures
from delve.play.context import PlayError
from delve.web.auth import Organiser, Principal, current_principal
from delve.web.refusals import refusal
from delve.web.routes.assets import attachment_response
from delve.web.routes.play import table

router = APIRouter()

NAME_CHARS = 120


@router.get("/api/monster-pictures")
def picture_state(
    request: Request,
    principal: Annotated[Principal, Depends(current_principal)],
    name: Annotated[str, Query(min_length=1, max_length=NAME_CHARS)],
) -> dict:
    """The kind `name`'s picture as a Rulesets entry and Paint show it: `{slug, picture, version, painting, error,
    paid}`, `paid` when painting it costs money."""
    services = table(request)
    picture = monster_pictures.find(services.storage, name) or services.storage.monster_pictures.get(
        monster_pictures.slug(name)
    )
    return {**monster_pictures.picture_json(picture, name), "paid": services.image_paid(monster_pictures.JOB)}


@router.get("/api/monster-pictures/{slug}")
def picture(request: Request, principal: Annotated[Principal, Depends(current_principal)], slug: str) -> Response:
    """The kind's picture; 404 while it has none."""
    found = request.app.state.storage.monster_pictures.get(slug)
    data = request.app.state.storage.blobs.get(found.blob) if found is not None and found.blob else None
    if found is None or data is None:
        raise HTTPException(status_code=404, detail="No such picture.")
    response = attachment_response(data, found.mime or "image/png")
    response.headers["Cache-Control"] = "private, max-age=86400"
    return response


class PaintIn(BaseModel):
    name: str = Field(min_length=1, max_length=NAME_CHARS)
    campaign_id: str | None = Field(default=None, max_length=64)
    """The table that asked, which reads its strip again when the picture lands."""


@router.post("/api/monster-pictures", status_code=202)
async def paint(request: Request, principal: Organiser, body: PaintIn) -> dict:
    """Paint the kind (again) in the background: 202 with its state; 422 while it is being painted, or without a
    model that paints."""
    services = table(request)
    try:
        row = monster_pictures.ask(services, body.name, campaign_id=body.campaign_id)
    except PlayError as refused:
        raise refusal(refused) from None
    return {**monster_pictures.picture_json(row, body.name), "paid": services.image_paid(monster_pictures.JOB)}
