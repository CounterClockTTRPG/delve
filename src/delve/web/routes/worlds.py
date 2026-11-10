"""The rulesets and settings a campaign can name (spec §10), for organisers, from the app's registries."""

from __future__ import annotations

from collections.abc import Collection

from fastapi import APIRouter, Request

from delve.domain.backends import ProviderCapabilities
from delve.rules.fake import FakeRuleset
from delve.setting.fake import FakeSetting
from delve.web.auth import Organiser

router = APIRouter()

FAKES = frozenset({FakeRuleset.id, FakeSetting.id})


def offered(capabilities: list[ProviderCapabilities], preferred: Collection[str] = ()) -> list[dict[str, object]]:
    """`[{id, title}]` of the providers, without the fakes unless they are the only ones; `preferred: true` on one a
    new campaign takes when the module names none (its pack says so)."""
    real = [caps for caps in capabilities if caps.id not in FAKES]
    return [
        {"id": caps.id, "title": caps.title, **({"preferred": True} if caps.id in preferred else {})}
        for caps in real or capabilities
    ]


@router.get("/api/worlds")
def list_worlds(request: Request, principal: Organiser) -> dict:
    registries = request.app.state.registries
    catalogs = registries.catalogs
    return {
        "rulesets": offered(registries.rulesets.capabilities(), {e.id for e in catalogs.rulesets if e.preferred}),
        "settings": offered(registries.settings_.capabilities(), {e.id for e in catalogs.settings if e.preferred}),
    }
