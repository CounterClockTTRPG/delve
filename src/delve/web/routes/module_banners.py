"""A module's banner (DEL-123), for organisers: see it, upload one, use one of the module's own pictures, or remove
it; painting one is `POST …/banner/paint`. Every change publishes `modules`.

The upload is the sixth raw-body exception to the JSON rule: the guard lets only `BANNER_TYPES` through, of at most
`BANNER_LIMIT` bytes as declared (`BANNER_UPLOAD_PATH`); the route counts the bytes too, and `band` checks them against
the type. The crop position (`position`, 0 the top, 1 the bottom) chooses the 21:9 band kept.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool
from starlette.responses import Response

from delve.domain.settings import Job
from delve.play import module_banners
from delve.play.context import NotFound, PlayError
from delve.play.module_banners import BANNER_LIMIT, BANNER_TYPES, BannerRefused, use_picture, use_upload
from delve.web.auth import Organiser
from delve.web.routes.assets import BannerSize, banner_picture
from delve.web.routes.modules import changed, get_module, module_json, updates_of

router = APIRouter()

Position = Annotated[float, Field(ge=0.0, le=1.0)]


class PaintIn(BaseModel):
    hint: str = Field("", max_length=300)


class PictureIn(BaseModel):
    picture: str
    """One of the module's attachments, by id."""
    position: Position = 0.5


@router.get("/api/modules/{module_id}/banner")
async def read_banner(
    request: Request, principal: Organiser, module_id: str, size: BannerSize | None = None
) -> Response:
    """The module's banner picture, or with `size=card` its small copy for the modules list (DEL-234); 404 while it
    has none (a first one still painting has none yet)."""
    module = get_module(request, module_id)
    banner = module.banner
    return await banner_picture(
        request, banner.blob if banner else None, (banner.mime if banner else None) or "image/webp", size
    )


@router.post("/api/modules/{module_id}/banner/upload")
async def upload_banner(
    request: Request, principal: Organiser, module_id: str, position: Annotated[float, Query(ge=0.0, le=1.0)] = 0.5
) -> dict:
    """The body is the picture: its band at `position` becomes the banner. 400 for bytes that aren't their type, 413
    past `BANNER_LIMIT`, 415 for another type, 422 for a picture of too many pixels, 503 while others are being cut."""
    get_module(request, module_id)
    media_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if media_type not in BANNER_TYPES:
        raise HTTPException(status_code=415, detail="This kind of file can't be a banner.")
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > BANNER_LIMIT:
            raise HTTPException(status_code=413, detail=f"A banner may be at most {BANNER_LIMIT} bytes.")
    storage = request.app.state.storage
    try:
        module = await run_in_threadpool(use_upload, storage, module_id, bytes(data), media_type, position)
    except BannerRefused as refused:
        raise HTTPException(status_code=refused.status, detail=refused.message) from None
    changed(request, module_id)
    return module_json(module, storage, updates=updates_of(request))


@router.put("/api/modules/{module_id}/banner")
async def picture_banner(request: Request, principal: Organiser, module_id: str, body: PictureIn) -> dict:
    """One of the module's own pictures (a converted book's cover, a handout), its band at `position`, becomes the
    banner. 404 for no such picture, 400 for one that isn't a PNG, JPEG or WebP."""
    get_module(request, module_id)
    storage = request.app.state.storage
    try:
        module = await run_in_threadpool(use_picture, storage, module_id, body.picture, body.position)
    except BannerRefused as refused:
        raise HTTPException(status_code=refused.status, detail=refused.message) from None
    changed(request, module_id)
    return module_json(module, storage, updates=updates_of(request))


@router.get("/api/modules/{module_id}/banner/paint")
async def paint_info(request: Request, principal: Organiser, module_id: str) -> dict:
    """Whether painting costs money (the scene's image model is paid), and whether this caller may paint: anyone with
    a free model, only the owner with a paid one. Read in a worker thread: it may ask a provider over the network."""
    from delve.web.routes.play import table  # it imports the modules' routes

    get_module(request, module_id)
    paid = await run_in_threadpool(table(request).image_paid, Job.IMAGE_SCENE)
    return {"paid": paid, "allowed": principal.owner or not paid}


@router.post("/api/modules/{module_id}/banner/paint", status_code=202)
async def paint_banner(request: Request, principal: Organiser, module_id: str, body: PaintIn) -> dict:
    """Paint the module's banner in the background, with the hint as its emphasis; the picture shown stays until it
    lands. 202 with the module, marked painting; 409 while one is being painted; 422 for a paid model unless the caller
    is the owner."""
    from delve.web.routes.play import table  # it imports the modules' routes

    get_module(request, module_id)
    services = table(request)
    paid = await run_in_threadpool(services.image_paid, Job.IMAGE_SCENE)
    if paid and not principal.owner:
        raise HTTPException(status_code=422, detail=module_banners.PAID_FOR_OWNER)
    try:
        module = module_banners.paint(services, module_id, body.hint, owner=principal.owner)
    except NotFound:
        raise HTTPException(status_code=404, detail="No such module.") from None
    except PlayError as refused:
        raise HTTPException(status_code=409, detail=refused.message) from None
    changed(request, module_id)
    return module_json(module, request.app.state.storage, updates=updates_of(request))


@router.delete("/api/modules/{module_id}/banner")
async def remove_banner(request: Request, principal: Organiser, module_id: str) -> dict:
    """No banner: the picture and any painting's state go. A painting still under way lands as no banner."""
    get_module(request, module_id)
    storage = request.app.state.storage
    module = storage.modules.clear_banner(module_id)
    changed(request, module_id)
    return module_json(module, storage, updates=updates_of(request))
