"""The Rulesets area's API (rulesets plan Task 5, Decisions 1–3 and 8): a ruleset's book, by sections, rows and
entries, for every reader.

The reader is `RulesetReader`: anyone Delve knows. A seat reads with its own campaign's house rules (its `?campaign=`
is ignored), and a seat that has left is refused, as at its table. An organiser without a seat reads the book alone,
or a campaign's house rules with `?campaign=<id>`.

Monsters are for the organiser role. For anyone else they don't exist: every refusal, for a ruleset, a section or an
entry, is the one `NOT_FOUND`, so a monster's 404 says no more than an unknown id's. A house rule's DM notes are cut
for anyone but an organiser (`delve.play.rulebook`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request

from delve.domain.campaigns import Campaign
from delve.domain.reference import Entry, Facet
from delve.play.context import NotFound
from delve.play.rulebook import RulebookView, view_for
from delve.web.auth import Principal, current_principal
from delve.web.seats import LEFT, NO_SEAT

router = APIRouter()

NOT_FOUND = "Not found."
PAGE = 50
MOST = 200
SEARCH = 20
MOST_OFFSET = 10**9
# The query parameters that aren't a section's filters.
NOT_FILTERS = frozenset({"q", "offset", "limit", "campaign"})


@dataclass(frozen=True)
class Reader:
    """Who reads, whether they may see the monsters and DM notes, and whose house rules they read with."""

    principal: Principal
    campaign: Campaign | None

    @property
    def organiser(self) -> bool:
        return "organiser" in self.principal.roles


def ruleset_reader(request: Request, campaign: str | None = None) -> Reader:
    """A dependency: the caller and their campaign, the seat's own, an account's `?campaign=` where it has a seat, or
    an organiser's `?campaign=` (404 if unknown); 401 for nobody, 403 for a seat that has left or an account without a
    seat there (unless it is an organiser's)."""
    principal = current_principal(request)
    storage = request.app.state.storage
    if principal.account is not None and campaign is not None and "organiser" not in principal.roles:
        seat = storage.seats.for_account(principal.account.id, campaign)
        if seat is None:
            raise HTTPException(status_code=403, detail=NO_SEAT)
        return Reader(principal, storage.campaigns.get(seat.campaign_id))
    if principal.seat is not None:
        if principal.seat.left_at is not None:
            raise HTTPException(status_code=403, detail=LEFT)
        return Reader(principal, storage.campaigns.get(principal.seat.campaign_id))
    if campaign is None or "organiser" not in principal.roles:
        return Reader(principal, None)
    chosen = storage.campaigns.get(campaign)
    if chosen is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    return Reader(principal, chosen)


RulesetReader = Annotated[Reader, Depends(ruleset_reader)]


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail=NOT_FOUND)


def _title(request: Request, ruleset_id: str) -> str:
    caps = next(c for c in request.app.state.registries.rulesets.capabilities() if c.id == ruleset_id)
    return caps.title


def _rulebook(request: Request, ruleset_id: str):
    """The ruleset's book, or None for a ruleset without one."""
    try:
        ruleset = request.app.state.registries.rulesets.get(ruleset_id)
    except KeyError:
        return None
    return ruleset.rulebook


def _view(request: Request, reader: Reader, ruleset_id: str) -> RulebookView:
    rulebook = _rulebook(request, ruleset_id)
    if rulebook is None:
        raise _not_found()
    campaign_id = reader.campaign.id if reader.campaign else None
    try:
        return view_for(rulebook, ruleset_id, request.app.state.storage, campaign_id, reader.organiser)
    except NotFound:
        raise _not_found() from None


def _number(value: str | None, default: int, low: int, high: int = MOST_OFFSET) -> int:
    """A query's number, clamped (at most `MOST_OFFSET`, which the store can page to); the default for one that isn't
    a number."""
    try:
        number = int(value) if value is not None else default
    except ValueError:
        number = default
    return min(high, max(low, number))


def facet_json(facet: Facet) -> dict[str, Any]:
    return {"key": facet.key, "options": [{"value": value, "count": count} for value, count in facet.options]}


def entry_json(entry: Entry) -> dict[str, Any]:
    return {
        "section": entry.section,
        "id": entry.id,
        "name": entry.name,
        "fields": entry.fields,
        "text": entry.text,
        "table": entry.table,
        "house_rule": entry.house_rule,
    }


@router.get("/api/rulesets")
def list_rulesets(request: Request, reader: RulesetReader) -> list[dict[str, str]]:
    """The registered rulesets that have a book, in the registry's order."""
    return [
        {"id": caps.id, "title": caps.title}
        for caps in request.app.state.registries.rulesets.capabilities()
        if _rulebook(request, caps.id) is not None
    ]


@router.get("/api/rulesets/{ruleset_id}")
def get_ruleset(request: Request, reader: RulesetReader, ruleset_id: str) -> dict[str, Any]:
    view = _view(request, reader, ruleset_id)
    return {
        "id": ruleset_id,
        "title": _title(request, ruleset_id),
        "sections": [{"key": s.key, "kind": s.kind, "count": s.count} for s in view.sections()],
        "campaign_id": reader.campaign.id if reader.campaign else None,
        "notice": request.app.state.registries.rulesets.get(ruleset_id).notice,
    }


@router.get("/api/rulesets/{ruleset_id}/search")
def search(
    request: Request, reader: RulesetReader, ruleset_id: str, q: str = "", limit: str | None = None
) -> dict[str, Any]:
    view = _view(request, reader, ruleset_id)
    hits = view.search(q, _number(limit, SEARCH, 1, MOST))
    return {"results": [{"section": section, "id": id, "name": name} for section, id, name in hits]}


@router.get("/api/rulesets/{ruleset_id}/{section}")
def get_section(
    request: Request,
    reader: RulesetReader,
    ruleset_id: str,
    section: str,
    q: str = "",
    offset: str | None = None,
    limit: str | None = None,
) -> dict[str, Any]:
    """A list's page, filtered by `q` and the section's facet keys (any other parameter is ignored), or a table."""
    view = _view(request, reader, ruleset_id)
    kinds = {s.key: s.kind for s in view.sections()}
    if section not in kinds:
        raise _not_found()
    try:
        if kinds[section] == "table":
            return {"kind": "table", "table": view.table(section)}
        facets = view.facets(section)
        keys = {facet.key for facet in facets}
        filters = {key: value for key, value in request.query_params.items() if key in keys - NOT_FILTERS}
        page = view.rows(section, {"q": q, **filters}, _number(offset, 0, 0), _number(limit, PAGE, 1, MOST))
    except KeyError:
        raise _not_found() from None
    return {
        "kind": "list",
        "facets": [facet_json(facet) for facet in facets],
        "total": page.total,
        "offset": page.offset,
        "rows": page.rows,
    }


@router.get("/api/rulesets/{ruleset_id}/{section}/{entry_id}")
def get_entry(request: Request, reader: RulesetReader, ruleset_id: str, section: str, entry_id: str) -> dict:
    view = _view(request, reader, ruleset_id)
    try:
        entry = view.entry(section, entry_id)
    except KeyError:
        raise _not_found() from None
    if entry is None:
        raise _not_found()
    return entry_json(entry)
