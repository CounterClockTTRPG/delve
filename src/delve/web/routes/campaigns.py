"""Campaigns (spec §8.1). Organisers only: the people at a campaign's table are its seats (plateau 4), and the owner's
seat, the host's, is made with the campaign.

A campaign pins a revision of its module: editing the module changes nothing in the campaign until the host upgrades
it. Upgrading changes map states, and publishes the event `map_state` for each. A campaign is created with its choice
of house rules (spec §9), and names its ruleset and setting (spec §10). It is seeded with its module's factions, their
clocks and its quests (plan 6 Task 5), and an upgrade adds the new ones, keeping the campaign's play state. Its page
shows its banner (looks and banners plan Task 3): the current one, and a newer one's status and, when it failed, error.
A campaign's party can be carried on into a new campaign on another module (carry-the-party-on plan Task 3), and the
two campaigns link to each other. Carrying on starts the job that writes the party's history (Task 5), which never
makes the carry fail.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool
from starlette.responses import Response

from delve.domain.campaigns import (
    CAMPAIGN_STATUSES,
    INITIATIVE_MODES,
    Campaign,
    MissingPack,
    default_ruleset,
    default_setting,
)
from delve.domain.histories import History
from delve.domain.modules import Module, Revision
from delve.domain.world import PLAIN_CALENDAR, Calendar
from delve.histories import jobs
from delve.maps import state as map_state
from delve.maps.dsl import DmapError
from delve.maps.sources import parsed_map
from delve.modules.source import pinned_source
from delve.packs.catalogs import Catalogs
from delve.play import banners, board, carry, factions, images, profiles, schedule, seats, world_maps
from delve.play import house_rules as play_house_rules
from delve.play.campaign_maps import played_revision, with_own_maps
from delve.play.context import PlayError, context_for
from delve.web.auth import Organiser, Principal
from delve.web.routes.modules import get_module, is_empty
from delve.web.routes.novels import novels
from delve.web.seats import HostSeat

router = APIRouter()
log = logging.getLogger(__name__)


def campaign_json(
    campaign: Campaign,
    storage: Any,
    now: datetime,
    carried: tuple[Campaign | None, list[Campaign | None]] | None = None,
) -> dict[str, Any]:
    """The campaign, with the links of carrying the party on: the campaign it was carried on from (None when it wasn't,
    or that one was deleted) and those it was carried on to, oldest first; and its schedule as stored, with its next
    sessions at `now` (`schedule.next_sessions`). `carried` is those two, when the caller has them (DEL-172)."""
    if carried is None:
        origin = storage.carries.origin(campaign.id)
        source = storage.campaigns.get(origin.from_campaign_id) if origin and origin.from_campaign_id else None
        onward = [storage.campaigns.get(link.to_campaign_id) for link in storage.carries.onward(campaign.id)]
    else:
        source, onward = carried
    return {
        "id": campaign.id,
        "name": campaign.name,
        "module_id": campaign.module_id,
        "revision": campaign.revision,
        "created_at": campaign.created_at,
        "ruleset": campaign.ruleset,
        "setting": campaign.setting,
        "status": campaign.status,
        "voice": campaign.voice,
        "initiative": campaign.initiative,
        "observers": campaign.observers,
        "visibility": campaign.visibility,
        "description": campaign.description,
        "slots": campaign.slots,
        "schedule": campaign.schedule,
        "next_sessions": schedule.next_sessions(campaign.schedule, now),
        "carried_from": {"id": source.id, "name": source.name} if source is not None else None,
        "carried_to": [{"id": c.id, "name": c.name} for c in onward if c is not None],
    }


def now_of(request: Request) -> datetime:
    """The time now by the app's clock (`delve.play.clock`), which tests move by hand."""
    return request.app.state.clock.now()


def get_campaign(request: Request, campaign_id: str) -> Campaign:
    campaign = request.app.state.storage.campaigns.get(campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="No such campaign.")
    return campaign


def pinned_revision(request: Request, campaign: Campaign) -> Revision:
    revision = played_revision(request.app.state.storage, campaign)
    if revision is None:  # storage keeps a campaign's revision; this is a broken database
        raise HTTPException(status_code=500, detail="The campaign's revision is missing.")
    return revision


def played_maps(revision: Revision) -> list[str]:
    """The names of the revision's maps that are played: its `map`s, not its libraries."""
    return [m.name for m in revision.maps if m.role == "map"]


def map_state_changed(request: Request, campaign_id: str, map_name: str) -> None:
    """The table's: ids only, so that each browser reads the map again through its own route."""
    data = {"campaign_id": campaign_id, "map": map_name}
    request.app.state.events.publish("map_state", data, scope="table", campaign_id=campaign_id)


def name_of(raw: str, what: str) -> str:
    name = raw.strip()
    if not name:
        raise HTTPException(status_code=422, detail=f"A {what} needs a name.")
    return name


class CampaignIn(BaseModel):
    name: str
    module_id: str
    ruleset: str | None = None
    setting: str | None = None
    """Left out: the module's; null: no setting."""
    bundle_ids: list[str] = []
    rule_ids: list[str] = []


def world_of(request: Request, module: Module, body: CampaignIn) -> tuple[str, str]:
    """The campaign's ruleset and setting: the ones it is given (422 for an unknown id), else the module's.

    The module's `metadata.system` is its ruleset when that is a registered ruleset, else the preferred ruleset this
    install has (`default_ruleset` of its catalogs). Its `metadata.setting` is its setting when it matches a setting's
    id or title, case-insensitively, else the preferred setting this install has, else "": no setting."""
    registries = request.app.state.registries
    catalogs = registries.catalogs
    rulesets = [caps.id for caps in registries.rulesets.capabilities()]
    settings = registries.settings_.capabilities()
    if body.ruleset is not None:
        if body.ruleset not in rulesets:
            raise HTTPException(status_code=422, detail=f"No ruleset '{body.ruleset}'.")
        ruleset = body.ruleset
    else:
        system = module.metadata.get("system")
        ruleset = system if isinstance(system, str) and system in rulesets else default_ruleset(
            [e.id for e in catalogs.rulesets], {e.id for e in catalogs.rulesets if e.preferred}
        )
    if "setting" in body.model_fields_set:
        if body.setting and body.setting not in {caps.id for caps in settings}:
            raise HTTPException(status_code=422, detail=f"No setting '{body.setting}'.")
        return ruleset, body.setting or ""
    named = module.metadata.get("setting")
    wanted = named.strip().casefold() if isinstance(named, str) else ""
    matching = (caps.id for caps in settings if wanted in (caps.id.casefold(), caps.title.casefold()))
    return ruleset, next(
        matching, default_setting([e.id for e in catalogs.settings], {e.id for e in catalogs.settings if e.preferred})
    )


def campaigns_changed(request: Request, campaign_id: str) -> None:
    request.app.state.events.publish("campaigns", {"id": campaign_id})


@router.get("/api/campaigns")
def list_campaigns(request: Request, principal: Organiser) -> list[dict]:
    """Every campaign, with its module's title, the names of its players (the seats that haven't left, observers
    excepted), who sits at its table as its card shows them (`people`, `profiles.people`) and the places they take
    (`taken`, beside `slots`; DEL-230), how much it has been played (`campaigns.activity`) and the banner it shows
    (`banners.shown`, its `image_id` for the list's cards, DEL-207; null for none).

    Each kind of thing is read once for every campaign (DEL-172): it took 111 queries for two campaigns, most of them
    loading every module whole for its title."""
    storage = request.app.state.storage
    heads = storage.modules.heads()
    now = now_of(request)
    campaigns = storage.campaigns.list()
    by_id = {c.id: c for c in campaigns}
    activities = storage.campaigns.activities()
    seats_of = storage.seats.by_campaign()
    accounts = {a.id: a for a in storage.accounts.list()}
    own_banners = {image.campaign_id: image for image in storage.campaign_images.everywhere(images.BANNER, "done")}
    carries = storage.carries.all()
    listed = []
    for campaign in campaigns:
        origin = next((c for c in carries if c.to_campaign_id == campaign.id), None)
        source = by_id.get(origin.from_campaign_id) if origin and origin.from_campaign_id else None
        onward = [by_id.get(c.to_campaign_id) for c in carries if c.from_campaign_id == campaign.id]
        activity = activities[campaign.id]
        table = seats_of.get(campaign.id, [])
        players = [s.name for s in table if s.left_at is None and s.role != "observer"]
        head = heads.get(campaign.module_id)
        banner = banners.shown_of(own_banners.get(campaign.id), head.banner if head is not None else None)
        listed.append(
            {
                **campaign_json(campaign, storage, now, (source, onward)),
                "module_title": head.title if head is not None else "",
                "players": players,
                "people": profiles.people(storage, campaign.id, table, accounts),
                "taken": seats.taken(storage, campaign.id, table),
                "last_played": activity.last_played,
                "sessions": activity.sessions,
                "playtime_s": activity.playtime_s,
                "banner": banner.id if banner is not None else None,
            }
        )
    return listed


@router.post("/api/campaigns", status_code=201)
async def create_campaign(request: Request, principal: Organiser, body: CampaignIn) -> dict:
    """A campaign on a snapshot of the module: its latest revision, or a new one if the module changed since. It
    plays in the ruleset and setting it is given, else the module's (`world_of`). It points to the house-rule bundles
    and single rules it is given; an unknown one refuses the whole campaign. A draft module is refused (409), and so
    is an empty one (`is_empty`); a campaign on a module emptied since keeps playing. Its host's seat is made with
    it: an organiser's account's own, else the owner's. Then it asks for its banner, which never fails or holds up the campaign (`ask_for_banner`)."""
    name = name_of(body.name, "campaign")
    module = get_module(request, body.module_id)
    if module.draft:
        raise HTTPException(status_code=409, detail="This module is a draft: mark it ready first.")
    if is_empty(request.app.state.storage, module):
        raise HTTPException(status_code=409, detail="This module is empty: write or import something first.")
    ruleset, setting = world_of(request, module, body)
    storage = request.app.state.storage
    with storage.transaction():
        campaign = make_campaign(request, principal, name, module, ruleset, setting, body.bundle_ids, body.rule_ids)
    if body.bundle_ids or body.rule_ids:
        request.app.state.events.publish("house_rules", {"campaign_id": campaign.id})
    ask_for_banner(request, campaign)
    return campaign_json(campaign, storage, now_of(request))


def make_campaign(
    request: Request,
    principal: Principal,
    name: str,
    module: Module,
    ruleset: str,
    setting: str,
    bundle_ids: list[str],
    rule_ids: list[str],
) -> Campaign:
    """Make the campaign on a snapshot of the module, with its host's seat (an organiser's account's own, else the
    owner's), its module's world and its house rules (422 for an unknown one), inside the caller's transaction."""
    storage = request.app.state.storage
    revision = storage.revisions.snapshot(module.id)
    campaign = storage.campaigns.create(name, module.id, revision.number, ruleset=ruleset, setting=setting)
    if principal.account is not None and not principal.owner:
        seats.create_organiser_seat(storage, campaign.id, principal.account)
    else:
        seats.create_owner_seat(storage, campaign.id)
    seed_world(storage, campaign, request.app.state.registries.catalogs)
    campaign = initiative_of_ruleset(storage, campaign, request.app.state.registries.catalogs)
    if bundle_ids or rule_ids:
        choose_house_rules(request, campaign.id, bundle_ids, rule_ids)
    return campaign


class CarryIn(BaseModel):
    name: str
    module_id: str
    character_ids: list[str]
    ruleset: str | None = None
    setting: str | None = None
    """Left out: the old campaign's; null: no setting."""
    bundle_ids: list[str] | None = None
    rule_ids: list[str] | None = None
    """Left out (both): the old campaign's house rules."""


def shared_calendar(request: Request, old: Campaign, setting: str | None) -> Calendar | None:
    """The calendar the old campaign and one in `setting` both count days in, so a carry goes on with it (DEL-104):
    the setting's when it is the old one's (the plain calendar for none, as `days.calendar`); None between settings."""
    if setting != old.setting:
        return None
    try:
        shipped = request.app.state.registries.settings_.get(setting) if setting else None
    except KeyError:
        shipped = None
    return shipped.calendar() if shipped is not None else PLAIN_CALENDAR


@router.post("/api/campaigns/{campaign_id}/carry", status_code=201)
async def carry_campaign(request: Request, principal: Organiser, campaign_id: str, body: CarryIn) -> dict:
    """Carry the party on: a new campaign on the module, made as `create_campaign` makes one, with copies of the
    chosen PCs and all the party owns (`carry.carry_into`). Left out, the ruleset, the setting and the house rules
    are the old campaign's, not the module's. Refused, nothing is made: a draft module is 409, a live fight in the old
    campaign 409 "End the fight first.", and an empty party or an id that isn't one of its PCs 422. The old campaign
    is kept, set to `complete`, and both link to each other (`carried_from`, `carried_to`)."""
    old = get_campaign(request, campaign_id)
    name = name_of(body.name, "campaign")
    module = get_module(request, body.module_id)
    if module.draft:
        raise HTTPException(status_code=409, detail="This module is a draft: mark it ready first.")
    given = body.model_dump(include={"name", "module_id", "ruleset", "setting"}, exclude_unset=True)
    ruleset, setting = world_of(request, module, CampaignIn(**given))  # 422 for an unknown one given
    if body.ruleset is None:
        ruleset = old.ruleset
    if "setting" not in body.model_fields_set:
        setting = old.setting
    storage = request.app.state.storage
    if body.bundle_ids is None and body.rule_ids is None:
        bundle_ids, rule_ids = storage.campaign_house_rules.get(old.id) or ([], [])
    else:
        bundle_ids, rule_ids = body.bundle_ids or [], body.rule_ids or []
    try:
        carry.check_carry(storage, old.id, body.character_ids)
        with storage.transaction():
            campaign = make_campaign(request, principal, name, module, ruleset, setting, bundle_ids, rule_ids)
            carry.carry_into(storage, old.id, campaign.id, body.character_ids, shared_calendar(request, old, setting))
    except carry.FightLive as error:
        raise HTTPException(status_code=409, detail=error.message) from None
    except carry.NotCarried as error:
        raise HTTPException(status_code=422, detail=error.message) from None
    if bundle_ids or rule_ids:
        request.app.state.events.publish("house_rules", {"campaign_id": campaign.id})
    campaigns_changed(request, old.id)
    history = await start_history(request, campaign.id, old.id)
    ask_for_banner(request, campaign)
    return {**campaign_json(campaign, storage, now_of(request)), "history": {"status": history.status}}


async def start_history(request: Request, campaign_id: str, from_campaign_id: str) -> History:
    """Start writing the carried party's history (`histories.jobs.start_history`). Carrying the party on never fails
    because of it: a start that fails for any reason leaves the history `failed`, with Write again to try later."""
    try:
        return await jobs.start_history(novels(request.app), campaign_id, from_campaign_id)
    except Exception as error:
        log.exception("starting the history of %s failed", campaign_id)
        failed = History(campaign_id, status="failed", error=str(error) or type(error).__name__)
        return request.app.state.storage.histories.put(failed)


def ask_for_banner(request: Request, campaign: Campaign) -> None:
    """Ask for the campaign's banner (`banners.ask`), in the setting's title, deciding later whether it may be
    painted now, since reading the gate may ask a provider over the network; any failure is only logged. A campaign
    whose module has a banner asks for none: it shows the module's until its page paints one (DEL-123)."""
    from delve.web.routes.play import table  # it imports this module's `get_campaign`

    if banners.module_has_banner(request.app.state.storage, campaign.id):
        return
    try:
        banners.ask(table(request), campaign.id, setting_title(request, campaign), decide_later=True)
    except Exception:
        log.exception("asking for the banner of %s failed", campaign.id)


def setting_title(request: Request, campaign: Campaign) -> str:
    """The title of the campaign's setting, for its banner's brief: its id when no setting has it, "" for none."""
    titles = {caps.id: caps.title for caps in request.app.state.registries.settings_.capabilities()}
    return titles.get(campaign.setting, campaign.setting) if campaign.setting else ""


def initiative_of_ruleset(storage: Any, campaign: Campaign, catalogs: Catalogs) -> Campaign:
    """A new campaign rolls initiative as its ruleset does (`RuleTables.initiative_mode`: OSRIC's d6 a side); the host
    may change it. A ruleset that isn't installed leaves the default."""
    try:
        mode = context_for(storage, campaign.id, "seed", catalogs=catalogs).rules.initiative_mode
    except (PlayError, MissingPack):
        return campaign
    if mode == campaign.initiative or mode not in INITIATIVE_MODES:
        return campaign
    return storage.campaigns.set_initiative(campaign.id, mode)


def seed_world(storage: Any, campaign: Campaign, catalogs: Catalogs) -> None:
    """Add the pinned revision's factions, clocks and quests the campaign doesn't have yet, and give a campaign
    without world maps the module's and then the setting's (plan 6 Task 8). Seeding reads no reference and rolls no
    dice."""
    source = pinned_source(storage, campaign.module_id, campaign.revision)
    ctx = context_for(storage, campaign.id, "seed", catalogs=catalogs)
    if source is not None:
        factions.seed(ctx, source)
    if not storage.world_maps.list(campaign.id):
        world_maps.seed(ctx, source)


def choose_house_rules(request: Request, campaign_id: str, bundle_ids: list[str], rule_ids: list[str]) -> dict:
    """Point the campaign to the bundles and rules; 422 naming the first unknown one."""
    try:
        return play_house_rules.set_campaign_house_rules(
            request.app.state.storage, campaign_id, bundle_ids=bundle_ids, rule_ids=rule_ids
        )
    except PlayError as error:
        raise HTTPException(status_code=422, detail=error.message) from None


@router.get("/api/campaigns/{campaign_id}")
async def read_campaign(request: Request, principal: Organiser, campaign_id: str) -> dict:
    return await campaign_page(request, get_campaign(request, campaign_id))


async def campaign_page(request: Request, campaign: Campaign) -> dict[str, Any]:
    """The campaign as its page reads it: `campaign_json` with its module's title, its maps, whether an upgrade is
    there and its banner."""
    campaign_id = campaign.id
    module = get_module(request, campaign.module_id)
    revision = pinned_revision(request, campaign)
    return {
        **campaign_json(campaign, request.app.state.storage, now_of(request)),
        "module_title": module.title,
        "maps": played_maps(revision),
        "own_maps": [m.name for m in request.app.state.storage.campaign_maps.list(campaign_id)],
        "upgrade_available": request.app.state.storage.modules.changed_since(module.id, campaign.revision),
        "banner": await banner_json(request, campaign_id),
    }


async def banner_json(request: Request, campaign_id: str) -> dict[str, Any]:
    """The campaign's banner for its page: the current one, the newer one that is waiting, painting (with its
    `images.waiting`, DEL-138) or failed (with its error, only when failed), and whether it may be painted again now, read in a worker thread since it may ask
    a provider over the network. Never a banner's prompt."""
    from delve.web.routes.play import table  # it imports this module's `get_campaign`

    storage = request.app.state.storage
    shown, newer = banners.shown(storage, campaign_id), banners.pending(storage, campaign_id)
    can_paint = await run_in_threadpool(banners.gate_open, table(request), campaign_id)
    return {
        "image_id": shown.id if shown is not None else None,
        # The module's banner (DEL-123), shown while the campaign has none of its own.
        "from_module": shown is not None and shown.from_module,
        "pending": (
            {
                "status": newer.status,
                "error": newer.error if newer.status == "failed" else None,
                **(images.waiting(newer) if newer.status == "painting" else {}),
            }
            if newer is not None
            else None
        ),
        "can_paint": can_paint,
        # `why_not` in English for the API; the web app says `why_not_code` in the reader's language (DEL-97).
        "why_not": None if can_paint else images.PAID_HINT,
        "why_not_code": None if can_paint else "paid_images_off",
    }


class CampaignPatch(BaseModel):
    status: str


@router.patch("/api/campaigns/{campaign_id}")
def patch_campaign(request: Request, seat: HostSeat, campaign_id: str, body: CampaignPatch) -> dict:
    """The host or a co-host sets the campaign's status: one of `CAMPAIGN_STATUSES`, else 422."""
    if body.status not in CAMPAIGN_STATUSES:
        raise HTTPException(
            status_code=422, detail=f"No status '{body.status}': it is one of {', '.join(CAMPAIGN_STATUSES)}."
        )
    storage = request.app.state.storage
    campaign = storage.campaigns.set_status(campaign_id, body.status)
    campaigns_changed(request, campaign_id)
    return campaign_json(campaign, storage, now_of(request))


@router.delete("/api/campaigns/{campaign_id}", status_code=204)
def delete_campaign(request: Request, principal: Organiser, campaign_id: str) -> Response:
    """Delete the campaign. Its board zone stays, untied first: a `table` level becomes `members` (DEL-297)."""
    get_campaign(request, campaign_id)
    storage = request.app.state.storage
    with storage.transaction():
        zone = storage.board.zone_of_campaign(campaign_id)
        board.untie_campaign(storage, campaign_id)
        storage.campaigns.delete(campaign_id)
    if zone is not None:
        request.app.state.events.publish("board", {"zone_id": zone.id}, scope="board", zone_id=zone.id)
    return Response(status_code=204)


@router.post("/api/campaigns/{campaign_id}/upgrade")
async def upgrade_campaign(request: Request, principal: Organiser, campaign_id: str) -> dict:
    """Move the campaign to a snapshot of its module, and every stored map state with it.

    A map state keeps what still exists in the new version of its map. One whose map is gone, or no longer parses, is
    left as it is: its map is offline until a later upgrade.
    """
    campaign = get_campaign(request, campaign_id)
    storage = request.app.state.storage
    revision = with_own_maps(storage.revisions.snapshot(campaign.module_id), storage.campaign_maps.list(campaign_id))
    upgraded = await run_in_threadpool(_upgraded_states, revision, storage.map_states.list(campaign_id))
    campaign = await run_in_threadpool(_move_to, request, campaign_id, revision.number, upgraded)
    for map_name in upgraded:
        map_state_changed(request, campaign_id, map_name)
    return campaign_json(campaign, storage, now_of(request))


def _move_to(request: Request, campaign_id: str, revision: int, upgraded: dict[str, dict]) -> Campaign:
    """The campaign on `revision`, its world seeded from it and its map states `upgraded`, in one transaction: a
    failure part way leaves it on its old revision, whole. Its events are the caller's, once it has committed."""
    storage = request.app.state.storage
    with storage.transaction():
        campaign = storage.campaigns.set_revision(campaign_id, revision)
        seed_world(storage, campaign, request.app.state.registries.catalogs)
        for map_name, raw in upgraded.items():
            storage.map_states.put(campaign_id, map_name, raw)
    return campaign


def _upgraded_states(revision: Revision, states: dict[str, dict]) -> dict[str, dict]:
    upgraded = {}
    for map_name, raw in states.items():
        if map_name not in played_maps(revision):
            continue
        try:
            dmap, _ = parsed_map(revision.module_id, revision.number, revision.maps, map_name)
        except DmapError:
            continue
        upgraded[map_name] = map_state.to_json(map_state.upgrade(map_state.from_json(raw), dmap))
    return upgraded
