"""The Settings area's API and the play screen's Setting tab's (settings plan Task 8).

Under `/api/settings` organisers search, browse and read a setting, add, override and revert its pages, keep its
facts and decide the DM's proposals. The area shows DM-only content, so every route of it is `Organiser`, reads too.

Under `/api/campaigns/{campaign_id}/setting` any seat at the table reads its campaign's setting: read-only, through a
seat's layer (`dm=False`), so never a DM-only page, section, fact or proposal, whoever calls, the owner's seat too.
That campaign's own proposals apply there; another campaign's only once accepted."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from delve.domain.reference import ReferenceHit, SettingPage
from delve.domain.setting_content import Proposal, SettingAddition, SettingFact, title_key
from delve.domain.world import Calendar
from delve.play import proposals
from delve.play.setting_layer import SettingLayer
from delve.setting.catalog import entry
from delve.setting.setting import Setting
from delve.setting.text import wiki_markdown
from delve.web.auth import Organiser
from delve.web.routes.worlds import offered
from delve.web.seats import TableSeat

router = APIRouter()

SHIPPED_FACTS_PER_CATEGORY = 100
NO_SETTING = "This campaign has no setting."


class PageIn(BaseModel):
    kind: str = ""
    fields: dict[str, str] = Field(default_factory=dict)
    text: str
    dm_only: bool = False


class FactIn(BaseModel):
    text: str
    category: str = ""
    dm_only: bool = False


class ProposalEditIn(BaseModel):
    title: str | None = None
    text: str | None = None
    category: str | None = None
    page_kind: str | None = None
    dm_only: bool | None = None


# --- the shapes ----------------------------------------------------------------------------------------------------


def calendar_json(calendar: Calendar) -> dict[str, Any]:
    return {
        "id": calendar.id,
        "era": calendar.era,
        "months": [
            {
                "name": month.name,
                "days": month.days,
                "season": month.season,
                "weather_season": month.weather_season,
                "festival": month.festival,
            }
            for month in calendar.months
        ],
        "default_start": list(calendar.default_start),
    }


def hit_json(hit: ReferenceHit, layer: SettingLayer) -> dict[str, Any]:
    found = {"kind": hit.kind, "key": hit.key, "title": hit.title, "text": hit.text, "origin": hit.origin}
    if hit.origin == "proposal":
        found["campaign_id"] = layer.campaign_id
    return found


def page_json(page: SettingPage, asked: str | None = None) -> dict[str, Any]:
    """A page as the web reads it: its text always Markdown; `redirected_from` the title asked when it isn't the
    page's."""
    return {
        "title": page.title,
        "kind": page.kind,
        "fields": dict(page.fields),
        "text": wiki_markdown(page.text) if page.format == "wiki" else page.text,
        "categories": list(page.categories),
        "origin": page.origin,
        "dm_only": page.dm_only,
        "campaign_id": page.campaign_id,
        "revertible": page.origin == "override",
        "redirected_from": asked if asked is not None and title_key(asked) != title_key(page.title) else None,
    }


def fact_json(fact: SettingFact) -> dict[str, Any]:
    return {
        "id": fact.id,
        "text": fact.text,
        "category": fact.category,
        "dm_only": fact.dm_only,
        "created_at": fact.created_at,
    }


def proposal_json(request: Request, proposal: Proposal) -> dict[str, Any]:
    campaign = request.app.state.storage.campaigns.get(proposal.campaign_id)
    return {
        "id": proposal.id,
        "campaign_id": proposal.campaign_id,
        "campaign_title": campaign.name if campaign is not None else "",
        "kind": proposal.kind,
        "title": proposal.title,
        "text": proposal.text,
        "mode": proposal.mode,
        "page_kind": proposal.page_kind,
        "category": proposal.category,
        "dm_only": proposal.dm_only,
        "status": proposal.status,
        "created_at": proposal.created_at,
        "decided_at": proposal.decided_at,
    }


# --- shared ---------------------------------------------------------------------------------------------------------


def _shipped(request: Request, setting_id: str) -> Setting:
    try:
        return request.app.state.registries.settings_.get(setting_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"There is no setting '{setting_id}'.") from None


def _organisers(request: Request, setting_id: str) -> SettingLayer:
    """The organisers' layer: everything, and no campaign's proposals."""
    return SettingLayer(_shipped(request, setting_id), request.app.state.storage, dm=True)


def _changed(request: Request, setting_id: str) -> None:
    request.app.state.events.publish("setting", {"id": setting_id})


def _search(layer: SettingLayer, q: str, limit: int) -> dict[str, Any]:
    return {"query": q, "results": [hit_json(hit, layer) for hit in layer.search(q, limit)]}


def _kind(layer: SettingLayer, kind: str, q: str, limit: int) -> dict[str, Any]:
    try:
        hits = layer.lookup(kind, q, limit)
    except ValueError:
        raise HTTPException(status_code=404, detail=f"There is no kind '{kind}' in {layer.title}.") from None
    return {"kind": kind, "results": [hit_json(hit, layer) for hit in hits]}


def _page(layer: SettingLayer, title: str) -> dict[str, Any]:
    page = layer.page(title)
    if page is None:
        raise HTTPException(status_code=404, detail=f"There is no page '{title}' in {layer.title}.")
    return page_json(page, title)


def _shipped_facts(request: Request, layer: SettingLayer) -> list[dict[str, Any]]:
    """The shipped facts of the setting's own categories, by id, at most 100 per category."""
    found = entry(layer.id, request.app.state.registries.catalogs.settings)
    categories = sorted(found.fact_categories) if found is not None else []
    facts = [
        fact
        for category in categories
        for fact in layer.shipped.lore_facts(SHIPPED_FACTS_PER_CATEGORY, category, seed=0)
    ]
    return [{"id": f.id, "text": f.text, "category": f.category} for f in sorted(facts, key=lambda f: f.id)]


def _fact(request: Request, setting_id: str, fact_id: int) -> SettingFact:
    fact = request.app.state.storage.setting_facts.get(fact_id)
    if fact is None or fact.setting != setting_id:
        raise HTTPException(status_code=404, detail=f"There is no fact {fact_id} of this setting.")
    return fact


def _proposal(request: Request, setting_id: str, proposal_id: int) -> Proposal:
    proposal = request.app.state.storage.proposals.get(proposal_id)
    if proposal is None or proposal.setting != setting_id:
        raise HTTPException(status_code=404, detail=f"There is no proposal {proposal_id} of this setting.")
    return proposal


def _refused(refused: proposals.ProposalRefused) -> HTTPException:
    return HTTPException(status_code=refused.status, detail=str(refused))


Limit = Annotated[int, Query(ge=1, le=50)]
KindLimit = Annotated[int, Query(ge=1, le=500)]


# --- the Settings area: organisers ---------------------------------------------------------------------------------


@router.get("/api/settings")
def list_settings(request: Request, principal: Organiser) -> list[dict[str, str]]:
    """`[{id, title}]`: the settings Delve knows, the fakes only when they are alone."""
    return offered(request.app.state.registries.settings_.capabilities())


@router.get("/api/settings/{setting_id}")
def get_setting(request: Request, principal: Organiser, setting_id: str) -> dict:
    layer = _organisers(request, setting_id)
    storage = request.app.state.storage
    own_maps = [m for m in storage.setting_maps.list(setting_id) if m.status == "ready"]
    return {
        "id": layer.id,
        "title": layer.title,
        "kinds": list(layer.kinds()),
        "calendar": calendar_json(layer.calendar()),
        "counts": {
            "pages": len(storage.setting_pages.list(setting_id)),
            "facts": len(storage.setting_facts.list(setting_id)),
            "proposals": len(storage.proposals.list(setting_id, status="pending")),
        },
        "maps_in_use": "install" if own_maps else "built-in",
        "built_in_maps": [{"name": m.name, "title": m.title} for m in layer.shipped.world_maps()],
    }


@router.get("/api/settings/{setting_id}/search")
def search(request: Request, principal: Organiser, setting_id: str, q: str = "", limit: Limit = 10) -> dict:
    return _search(_organisers(request, setting_id), q, limit)


@router.get("/api/settings/{setting_id}/kinds/{kind}")
def browse(
    request: Request, principal: Organiser, setting_id: str, kind: str, q: str = "", limit: KindLimit = 100
) -> dict:
    return _kind(_organisers(request, setting_id), kind, q, limit)


@router.get("/api/settings/{setting_id}/pages/{title:path}")
def get_page(request: Request, principal: Organiser, setting_id: str, title: str) -> dict:
    return _page(_organisers(request, setting_id), title)


@router.put("/api/settings/{setting_id}/pages/{title:path}")
def put_page(
    request: Request, principal: Organiser, setting_id: str, title: str, body: PageIn, response: Response
) -> dict:
    """Add the page, or change the install's page of that title; an override when the shipped setting has it. It is
    stored under the shipped page's title when `title` is a redirect. 201 when it made the addition."""
    layer = _organisers(request, setting_id)
    if not title.strip():
        raise HTTPException(status_code=422, detail="A page needs its title.")
    if not body.text.strip():
        raise HTTPException(status_code=422, detail="A page needs its text.")
    shipped, existing = layer.shipped_page(title), layer.addition(title)
    # The shipped page's own kind (the reference's table, as the form sends it back) leaves the override without a
    # kind of its own, as an accepted edit does, so it keeps the shipped page's.
    kind = "" if shipped and body.kind == shipped.kind else body.kind
    if kind and kind not in layer.kinds():
        raise HTTPException(status_code=422, detail=f"There is no kind '{kind}'; kinds: {', '.join(layer.kinds())}.")
    canonical = shipped.title if shipped else existing.title if existing else " ".join(title.split())
    request.app.state.storage.setting_pages.put(
        SettingAddition(setting_id, canonical, kind=kind, fields=body.fields, text=body.text, dm_only=body.dm_only)
    )
    _changed(request, setting_id)
    if existing is None:
        response.status_code = 201
    return _page(layer, title)


@router.delete("/api/settings/{setting_id}/pages/{title:path}", status_code=204)
def delete_page(request: Request, principal: Organiser, setting_id: str, title: str) -> Response:
    """Delete the install's new page, or revert an override to the shipped page."""
    existing = _organisers(request, setting_id).addition(title)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"This install has no page '{title}'.")
    request.app.state.storage.setting_pages.delete(setting_id, existing.title)
    _changed(request, setting_id)
    return Response(status_code=204)


@router.get("/api/settings/{setting_id}/facts")
def list_facts(request: Request, principal: Organiser, setting_id: str) -> dict:
    """`{shipped, own}`: the reference's facts of the setting, and the install's."""
    layer = _organisers(request, setting_id)
    own = request.app.state.storage.setting_facts.list(setting_id)
    return {"shipped": _shipped_facts(request, layer), "own": [fact_json(fact) for fact in own]}


@router.post("/api/settings/{setting_id}/facts", status_code=201)
def add_fact(request: Request, principal: Organiser, setting_id: str, body: FactIn) -> dict:
    _shipped(request, setting_id)
    if not body.text.strip():
        raise HTTPException(status_code=422, detail="A fact needs its text.")
    fact = request.app.state.storage.setting_facts.add(
        SettingFact(0, setting_id, body.text, body.category, body.dm_only)
    )
    _changed(request, setting_id)
    return fact_json(fact)


@router.put("/api/settings/{setting_id}/facts/{fact_id}")
def put_fact(request: Request, principal: Organiser, setting_id: str, fact_id: int, body: FactIn) -> dict:
    fact = _fact(request, setting_id, fact_id)
    if not body.text.strip():
        raise HTTPException(status_code=422, detail="A fact needs its text.")
    stored = request.app.state.storage.setting_facts.put(
        SettingFact(fact.id, setting_id, body.text, body.category, body.dm_only, fact.created_at)
    )
    _changed(request, setting_id)
    return fact_json(stored)


@router.delete("/api/settings/{setting_id}/facts/{fact_id}", status_code=204)
def delete_fact(request: Request, principal: Organiser, setting_id: str, fact_id: int) -> Response:
    _fact(request, setting_id, fact_id)
    request.app.state.storage.setting_facts.delete(fact_id)
    _changed(request, setting_id)
    return Response(status_code=204)


@router.get("/api/settings/{setting_id}/proposals")
def list_proposals(
    request: Request,
    principal: Organiser,
    setting_id: str,
    status: Literal["pending", "accepted", "rejected"] | None = None,
) -> list[dict]:
    _shipped(request, setting_id)
    found = request.app.state.storage.proposals.list(setting_id, status=status)
    return [proposal_json(request, proposal) for proposal in found]


@router.put("/api/settings/{setting_id}/proposals/{proposal_id}")
def edit_proposal(
    request: Request, principal: Organiser, setting_id: str, proposal_id: int, body: ProposalEditIn
) -> dict:
    _proposal(request, setting_id, proposal_id)
    try:
        edited = proposals.edit(request.app.state.storage, proposal_id, **body.model_dump())
    except proposals.ProposalRefused as refused:
        raise _refused(refused) from None
    _changed(request, setting_id)
    return proposal_json(request, edited)


@router.post("/api/settings/{setting_id}/proposals/{proposal_id}/accept")
def accept_proposal(request: Request, principal: Organiser, setting_id: str, proposal_id: int) -> dict:
    """`{proposal, page}` or `{proposal, fact}`: the proposal accepted, and what it made of the install's."""
    layer = _organisers(request, setting_id)
    _proposal(request, setting_id, proposal_id)
    storage = request.app.state.storage
    try:
        made = proposals.accept(storage, layer, proposal_id)
    except proposals.ProposalRefused as refused:
        raise _refused(refused) from None
    _changed(request, setting_id)
    proposal = proposal_json(request, storage.proposals.get(proposal_id))
    if isinstance(made, SettingFact):
        return {"proposal": proposal, "fact": fact_json(made)}
    return {"proposal": proposal, "page": _page(layer, made.title)}


@router.post("/api/settings/{setting_id}/proposals/{proposal_id}/reject")
def reject_proposal(request: Request, principal: Organiser, setting_id: str, proposal_id: int) -> dict:
    _proposal(request, setting_id, proposal_id)
    try:
        rejected = proposals.reject(request.app.state.storage, proposal_id)
    except proposals.ProposalRefused as refused:
        raise _refused(refused) from None
    _changed(request, setting_id)
    return proposal_json(request, rejected)


# --- the Setting tab: any seat at the table, filtered --------------------------------------------------------------


def _seats(request: Request, campaign_id: str) -> SettingLayer:
    """A seat's layer of the campaign's setting: no DM-only content, for every caller; the campaign's proposals."""
    campaign = request.app.state.storage.campaigns.get(campaign_id)
    if campaign is None or not campaign.setting:
        raise HTTPException(status_code=404, detail=NO_SETTING)
    try:
        shipped = request.app.state.registries.settings_.get(campaign.setting)
    except KeyError:
        raise HTTPException(status_code=404, detail=NO_SETTING) from None
    return SettingLayer(shipped, request.app.state.storage, campaign_id=campaign_id, dm=False)


@router.get("/api/campaigns/{campaign_id}/setting")
def table_setting(request: Request, seat: TableSeat, campaign_id: str) -> dict:
    layer = _seats(request, campaign_id)
    return {
        "id": layer.id,
        "title": layer.title,
        "kinds": list(layer.kinds()),
        "calendar": calendar_json(layer.calendar()),
    }


@router.get("/api/campaigns/{campaign_id}/setting/search")
def table_search(request: Request, seat: TableSeat, campaign_id: str, q: str = "", limit: Limit = 10) -> dict:
    return _search(_seats(request, campaign_id), q, limit)


@router.get("/api/campaigns/{campaign_id}/setting/kinds/{kind}")
def table_browse(
    request: Request, seat: TableSeat, campaign_id: str, kind: str, q: str = "", limit: KindLimit = 100
) -> dict:
    return _kind(_seats(request, campaign_id), kind, q, limit)


@router.get("/api/campaigns/{campaign_id}/setting/pages/{title:path}")
def table_page(request: Request, seat: TableSeat, campaign_id: str, title: str) -> dict:
    return _page(_seats(request, campaign_id), title)


@router.get("/api/campaigns/{campaign_id}/setting/facts")
def table_facts(request: Request, seat: TableSeat, campaign_id: str) -> dict:
    """`{facts: [{text, category, origin}]}`: the shipped facts of the setting, then the install's and this
    campaign's that a seat may read; `origin` is `shipped`, `install` or `campaign`."""
    layer = _seats(request, campaign_id)
    shipped = [{**fact, "origin": "shipped"} for fact in _shipped_facts(request, layer)]
    own = [{"text": f.text, "category": f.category, "origin": f.source} for f in layer.facts()]
    return {"facts": [{k: fact[k] for k in ("text", "category", "origin")} for fact in shipped] + own}
