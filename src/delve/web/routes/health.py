"""Whether Delve is up, and which one it is. Open to anyone who may reach the host.

`dm` says whether the real DM, `claude -p`, can run here: it is unavailable when `claude` isn't on `PATH`.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from delve import __version__
from delve.dm.claude_cli import CLAUDE_CLI_CAPABILITIES

router = APIRouter()


@router.get("/api/health")
def health(request: Request) -> dict:
    providers = [caps.id for caps in request.app.state.registries.dm.capabilities()]
    dm = "available" if CLAUDE_CLI_CAPABILITIES.id in providers else "unavailable"
    return {"ok": True, "name": "delve", "version": __version__, "dm": dm}
