"""The owner token from the browser (DEL-154, audit finding 9): the page trades the link's `#token=` for an `HttpOnly`
cookie, and the owner makes a new token from Preferences.

The `delve_token` cookie was written by the page, where any script on it could read it; now only the server sets it
(`HttpOnly; SameSite=Strict; Path=/`, a year, `Secure` when the browser came over HTTPS), and the page never sees it
again. No cookie is set through a proxy on this machine, where the owner token isn't taken (`OwnerTokenIdentity`);
an owner account may make a new token from anywhere.
"""

from __future__ import annotations

import secrets
from typing import Annotated, Any

from fastapi import APIRouter, Body, HTTPException, Request
from starlette.responses import JSONResponse, Response

from delve.web import guard
from delve.web.auth import (
    OWNER_TOKEN_NOT_HERE,
    TOKEN_COOKIE,
    Owner,
    new_token,
    presented_owner_token,
    token_links,
)
from delve.web.routes.accounts import COOKIE_MAX_AGE, text_field
from delve.web.routes.voice import table_changed

router = APIRouter()

NOT_THE_TOKEN = "That isn't the owner token: ask for a new link."


def _with_cookie(request: Request, response: Response, token: str) -> Response:
    response.set_cookie(
        TOKEN_COOKIE,
        token,
        max_age=COOKIE_MAX_AGE,
        path="/",
        httponly=True,
        samesite="strict",
        secure=guard.came_over_https(request),
    )
    return response


@router.post("/api/owner-token/cookie", status_code=204)
def token_cookie(request: Request, body: Annotated[dict[str, Any], Body()]) -> Response:
    """Keep the owner token in this browser: 204 with the `HttpOnly` cookie; 401 for a token that isn't it, 403
    through a proxy on this machine. The token is never echoed."""
    token = text_field(body, "token")
    if guard.from_a_proxy_here(request):
        raise HTTPException(status_code=403, detail=OWNER_TOKEN_NOT_HERE)
    if not secrets.compare_digest(token.encode(), request.app.state.owner_token.token().encode()):
        raise HTTPException(status_code=401, detail=NOT_THE_TOKEN)
    return _with_cookie(request, Response(status_code=204), token)


@router.post("/api/owner-token/new")
def make_new_token(request: Request, principal: Owner) -> JSONResponse:
    """A new owner token, the old one refused from the next request on (as `delve token --new`): the owner's alone.
    Answers the token and its links once; a browser that used the owner token gets the new one in its cookie."""
    by_token = principal.account is None and presented_owner_token(request) is not None
    config = request.app.state.config
    token = new_token(config)
    request.app.state.owner_token.token()  # read now: the old token is refused from the next request on
    table_changed(request.app)  # a voice on the old token goes with it
    links = [*token_links(config.port, token), f"http://localhost:{config.port}/#token={token}"]
    response = JSONResponse({"token": token, "links": links})
    return _with_cookie(request, response, token) if by_token else response
