"""The public privacy policy and terms of service (DEL-208): what their pages (`/privacy`, `/terms`) need from the
server. `GET /api/legal` is open to all, as the pages are read before anyone logs in: the operator's name and contact
email (the owner's to set, `PUT /api/legal`, and theirs to publish), and which outside services this install uses,
so the privacy policy names only those: Google sign-in, Replicate's pictures and a backup store, each once set up.
Anthropic's Claude runs the game master on every install, so the page always names it.
"""

from __future__ import annotations

import re
from typing import Annotated, Any

from fastapi import APIRouter, Body, HTTPException, Request

from delve.images import connections as image_connections
from delve.web import oidc
from delve.web.auth import Owner
from delve.web.routes.connections import _object

router = APIRouter()

SETTING = "operator"
"""The stored settings' key of the operator's `{name, email}`."""
NAME_MAX = 100
EMAIL = re.compile(r"^[^\s@<>\"]{1,64}@[^\s@<>\"]{1,190}\.[^\s@<>\".]{2,63}$")


def operator(request: Request) -> dict[str, str]:
    stored = request.app.state.storage.settings.load().get(SETTING)
    stored = stored if isinstance(stored, dict) else {}
    return {key: str(stored.get(key) or "") for key in ("name", "email")}


@router.get("/api/legal")
def legal(request: Request) -> dict[str, Any]:
    """The operator, and the outside services in use: `{operator: {name, email}, services: {google, replicate,
    backups}}`; nothing secret, nothing about anyone's account."""
    data_dir = request.app.state.config.data_dir
    return {
        "operator": operator(request),
        "services": {
            "google": oidc.load_client(data_dir, "google") is not None,
            "replicate": image_connections.replicate_state(data_dir) != "unset",
            "backups": getattr(request.app.state, "stores", None) is not None
            and request.app.state.stores.backup is not None,
        },
    }


@router.put("/api/legal")
def set_operator(request: Request, principal: Owner, raw: Annotated[Any, Body()] = None) -> dict[str, Any]:
    """`{"name", "email"}`: who runs this install, as the pages show it (either may be empty)."""
    body = _object(raw, required={"name", "email"})
    name, email = body["name"], body["email"]
    if not isinstance(name, str) or not isinstance(email, str):
        raise HTTPException(status_code=422, detail="Send the name and the email as text.")
    name, email = " ".join(name.split()), email.strip()
    if len(name) > NAME_MAX:
        raise HTTPException(status_code=422, detail=f"A name has at most {NAME_MAX} characters.")
    if email and not EMAIL.fullmatch(email):
        raise HTTPException(status_code=422, detail="That isn't an email address.")
    request.app.state.storage.settings.update({SETTING: {"name": name, "email": email}})
    return legal(request)
