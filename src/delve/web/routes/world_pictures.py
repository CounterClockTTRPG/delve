"""A world-map picture's raw tiles (plan 7 Task 5), for the organisers' editors and the DM view. Organisers only: a
seat gets its tiles fogged, through its campaign's world-map routes, never these.

A tile is JPEG, served with `nosniff`, and kept a day by the browser: a picture's tiles never change, since the
picture is its original's sha256.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from starlette.responses import Response

from delve.maps.geo import pictures
from delve.web.auth import Organiser

router = APIRouter()


@router.get("/api/world-pictures/{picture_id}/tiles/{z}/{x}/{y}")
def raw_tile(request: Request, principal: Organiser, picture_id: str, z: int, x: int, y: int) -> Response:
    data = pictures.tile(request.app.state.storage, picture_id, z, x, y)
    if data is None:
        raise HTTPException(status_code=404, detail="no such tile")
    headers = {"X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=86400"}
    return Response(data, media_type="image/jpeg", headers=headers)
