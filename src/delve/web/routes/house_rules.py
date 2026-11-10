"""House rules and bundles (spec §9), for organisers: the library, and each campaign's choice of bundles and rules.

Every change publishes the event `house_rules`, with the `rule_id`, `bundle_id` or `campaign_id` that changed.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, StrictBool
from starlette.responses import Response

from delve.domain.house_rules import Bundle, HouseRule, Kind, Phase, subject_key
from delve.play import house_rules as play_house_rules
from delve.web.auth import Organiser
from delve.web.routes.campaigns import choose_house_rules, get_campaign

router = APIRouter()


class RuleIn(BaseModel):
    title: str
    body_md: str = ""
    kind: Kind = "general"
    phases: list[Phase] = []
    ruleset: str | None = None
    setting: str | None = None
    subject: str | None = None
    enabled: StrictBool = True


class BundleIn(BaseModel):
    title: str
    description_md: str = ""
    rule_ids: list[str] = []


class ChoiceIn(BaseModel):
    bundle_ids: list[str] = []
    rule_ids: list[str] = []


def _title(raw: str, what: str) -> str:
    title = raw.strip()
    if not title:
        raise HTTPException(status_code=422, detail=f"A {what} needs a title.")
    return title


def _tag(raw: str | None) -> str | None:
    """A ruleset or setting id; blank means any."""
    return (raw or "").strip() or None


def _rule_fields(body: RuleIn) -> dict[str, Any]:
    return {
        "title": _title(body.title, "house rule"),
        "body_md": body.body_md,
        "kind": body.kind,
        "phases": frozenset(body.phases),
        "ruleset": _tag(body.ruleset),
        "setting": _tag(body.setting),
        "subject": subject_key(body.subject or "") or None,
        "enabled": body.enabled,
    }


def _changed(request: Request, **data: str) -> None:
    request.app.state.events.publish("house_rules", data)


def _get_rule(request: Request, rule_id: str) -> HouseRule:
    rule = request.app.state.storage.house_rules.get(rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="No such house rule.")
    return rule


def _get_bundle(request: Request, bundle_id: str) -> Bundle:
    bundle = request.app.state.storage.house_rule_bundles.get(bundle_id)
    if bundle is None:
        raise HTTPException(status_code=404, detail="No such house-rule bundle.")
    return bundle


def _known_rules(request: Request, rule_ids: list[str]) -> None:
    unknown = [id for id in rule_ids if request.app.state.storage.house_rules.get(id) is None]
    if unknown:
        raise HTTPException(status_code=422, detail=f"No house rule '{unknown[0]}'.")


# --- rules ---------------------------------------------------------------------------------------------------------


@router.get("/api/house-rules")
def list_rules(request: Request, principal: Organiser) -> list[dict]:
    return [rule.to_dict() for rule in request.app.state.storage.house_rules.list()]


@router.post("/api/house-rules", status_code=201)
def create_rule(request: Request, principal: Organiser, body: RuleIn) -> dict:
    rule = request.app.state.storage.house_rules.create(**_rule_fields(body))
    _changed(request, rule_id=rule.id)
    return rule.to_dict()


@router.post("/api/house-rules/import-example")
def import_example(request: Request, principal: Organiser) -> dict:
    """Import the example rules Delve ships into an empty library, as `delve house-rules import` does; a fresh install
    starts without house rules. When the example bundle is there, it is answered as it is: no rule is re-created or
    added to it, so the owner's edits and deletions stand. A library with rules or bundles but no example bundle is
    the owner's own, and is a 409 that changes nothing."""
    storage = request.app.state.storage
    with storage.transaction():
        bundles = storage.house_rule_bundles.list()
        example = next((b for b in bundles if b.title == play_house_rules.SEED_BUNDLE_TITLE), None)
        if example is not None:
            return example.to_dict()
        if bundles or storage.house_rules.list():
            raise HTTPException(status_code=409, detail="The library already has house rules.")
        bundle = play_house_rules.import_house_rules(
            storage, play_house_rules.SEED_DIR, request.app.state.registries.catalogs.packs
        )
    _changed(request, bundle_id=bundle.id)
    return bundle.to_dict()


@router.get("/api/house-rules/{rule_id}")
def read_rule(request: Request, principal: Organiser, rule_id: str) -> dict:
    return _get_rule(request, rule_id).to_dict()


@router.put("/api/house-rules/{rule_id}")
def update_rule(request: Request, principal: Organiser, rule_id: str, body: RuleIn) -> dict:
    """Replace every field of the rule. Campaigns point to it, so the change applies to them at once."""
    rule = request.app.state.storage.house_rules.save(replace(_get_rule(request, rule_id), **_rule_fields(body)))
    _changed(request, rule_id=rule.id)
    return rule.to_dict()


@router.delete("/api/house-rules/{rule_id}", status_code=204)
def delete_rule(request: Request, principal: Organiser, rule_id: str) -> Response:
    """Delete the rule; it leaves every bundle and campaign."""
    _get_rule(request, rule_id)
    request.app.state.storage.house_rules.delete(rule_id)
    _changed(request, rule_id=rule_id)
    return Response(status_code=204)


# --- bundles -------------------------------------------------------------------------------------------------------


@router.get("/api/house-rule-bundles")
def list_bundles(request: Request, principal: Organiser) -> list[dict]:
    return [bundle.to_dict() for bundle in request.app.state.storage.house_rule_bundles.list()]


@router.post("/api/house-rule-bundles", status_code=201)
def create_bundle(request: Request, principal: Organiser, body: BundleIn) -> dict:
    title = _title(body.title, "bundle")
    _known_rules(request, body.rule_ids)
    bundle = request.app.state.storage.house_rule_bundles.create(
        title=title, description_md=body.description_md, rule_ids=body.rule_ids
    )
    _changed(request, bundle_id=bundle.id)
    return bundle.to_dict()


@router.get("/api/house-rule-bundles/{bundle_id}")
def read_bundle(request: Request, principal: Organiser, bundle_id: str) -> dict:
    return _get_bundle(request, bundle_id).to_dict()


@router.put("/api/house-rule-bundles/{bundle_id}")
def update_bundle(request: Request, principal: Organiser, bundle_id: str, body: BundleIn) -> dict:
    """Replace the bundle's title, description and ordered rules."""
    bundle = _get_bundle(request, bundle_id)
    title = _title(body.title, "bundle")
    _known_rules(request, body.rule_ids)
    saved = request.app.state.storage.house_rule_bundles.save(
        replace(bundle, title=title, description_md=body.description_md, rule_ids=tuple(body.rule_ids))
    )
    _changed(request, bundle_id=saved.id)
    return saved.to_dict()


@router.delete("/api/house-rule-bundles/{bundle_id}", status_code=204)
def delete_bundle(request: Request, principal: Organiser, bundle_id: str) -> Response:
    """Delete the bundle; it leaves every campaign, and its rules stay in the library."""
    _get_bundle(request, bundle_id)
    request.app.state.storage.house_rule_bundles.delete(bundle_id)
    _changed(request, bundle_id=bundle_id)
    return Response(status_code=204)


# --- a campaign's choice -------------------------------------------------------------------------------------------


@router.get("/api/campaigns/{campaign_id}/house-rules")
def read_campaign_house_rules(request: Request, principal: Organiser, campaign_id: str) -> dict:
    get_campaign(request, campaign_id)
    return play_house_rules.campaign_house_rules(request.app.state.storage, campaign_id)


@router.put("/api/campaigns/{campaign_id}/house-rules")
def update_campaign_house_rules(request: Request, principal: Organiser, campaign_id: str, body: ChoiceIn) -> dict:
    get_campaign(request, campaign_id)
    chosen = choose_house_rules(request, campaign_id, body.bundle_ids, body.rule_ids)
    _changed(request, campaign_id=campaign_id)
    return chosen

