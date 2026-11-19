"""The DM's whole system prompt for a fixed campaign, the same for every ruleset but the ruleset itself, so that a
ruleset's snapshot of it changes only when what that ruleset's DM is sent does (DEL-383)."""

from __future__ import annotations

from delve.dm.prompt import build_system_prompt
from delve.domain.characters import Sheet
from delve.domain.modules import ModuleMap
from delve.packs.catalogs import Catalogs
from delve.play.context import context_for
from delve.play.house_rules import set_campaign_house_rules
from tests.fixtures import SAMPLES

PART = "\n\n---- next part ----\n\n"


def assembled_prompt(storage, ruleset: str, catalogs: Catalogs) -> str:
    """Every part `build_system_prompt` makes for a campaign of `ruleset` on the crypt sample, with a fighter and a
    mage, house rules of each kind, a non-default tone, detail and XP awards, and a rehydrate note, joined by `PART`."""
    module = storage.modules.create("The Crypt")
    storage.modules.put_map(module.id, ModuleMap("crypt", "map", (SAMPLES / "crypt.dmap").read_text(), True))
    campaign = storage.campaigns.create(
        "Tuesday", module.id, storage.revisions.snapshot(module.id).number, ruleset=ruleset, setting="greyhawk"
    )
    storage.characters.create(campaign.id, "Ssth", sheet=Sheet(label="Ssth", race="Lizardfolk", cls="Fighter"))
    storage.characters.create(campaign.id, "Corwin", sheet=Sheet(label="Corwin", race="Human", cls="Mage"))
    rules = storage.house_rules
    chosen = [
        rules.create(title="Speak plainly", body_md="NPCs never monologue.", kind="behaviour", phases=["behaviour"]),
        rules.create(title="Lizardfolk swim", body_md="They swim at 12.", kind="race", subject="lizardfolk"),
        rules.create(title="Mages wear leather", body_md="Mages may wear leather.", kind="class", subject="mage"),
        rules.create(title="Honest dice", body_md="All rolls are in the open.", phases=["always"]),
    ]
    set_campaign_house_rules(storage, campaign.id, bundle_ids=[], rule_ids=[r.id for r in chosen])
    ctx = context_for(storage, campaign.id, "beat-1", catalogs=catalogs)
    parts = build_system_prompt(
        ctx, tone="horror", detail=0, xp_awards=["monsters", "gold"], rehydrate="Garrek rolled 17 STR."
    )
    return PART.join(parts) + "\n"
