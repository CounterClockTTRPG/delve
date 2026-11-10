"""The "Did you know" facts for the play screen (plan 6 Task 3): `GET /api/campaigns/{id}/lore/random` gives a seat its
campaign's setting's lore facts, never the campaign's own facts. Through the setting layer (settings plan Task 5) they
hold the install's facts and the seat's campaign's proposed ones, never a DM-only one."""

import pytest
from fastapi.testclient import TestClient

from delve.domain.backends import ProviderCapabilities, Registry
from delve.domain.modules import ModuleMap
from delve.domain.setting_content import Proposal, SettingFact
from delve.domain.world import CampaignFact
from delve.play import seats
from delve.setting.fake import FakeSetting
from delve.web.seats import SEAT_COOKIE, new_seat_token, token_hash
from tests.fixtures.reference import LORE_FACTS
from tests.fixtures.rulesets import setting
from tests.web.conftest import BASE_URL, make_registries

CAMPAIGN_ONLY = "CAMPAIGN-FACT-PLUGH"
SECRET = "SECRET-XYZZY"


@pytest.fixture
def registries():
    registries = make_registries()
    registries.settings_ = Registry()
    registries.settings_.register(
        ProviderCapabilities("greyhawk", "Greyhawk", frozenset()), lambda: setting("greyhawk")
    )
    registries.settings_.register(ProviderCapabilities("fake-setting", "Fake setting", frozenset()), FakeSetting)
    return registries


def campaign(storage, setting="greyhawk"):
    module = storage.modules.create("The Crypt")
    storage.modules.put_map(module.id, ModuleMap("crypt", "map", "map crypt {}\n", is_default=True))
    revision = storage.revisions.snapshot(module.id)
    made = storage.campaigns.create("Tuesday", module.id, revision.number, setting=setting, ruleset="osric")
    seats.owner_seat(storage, made.id)
    storage.campaign_facts.add(CampaignFact(0, made.id, f"{CAMPAIGN_ONLY}: the party slew a dragon.", "victory"))
    return made.id


@pytest.fixture
def player(app, storage):
    """A player's browser on the LAN, seated at a Greyhawk campaign."""
    cid = campaign(storage)
    token = new_seat_token()
    storage.seats.create(cid, "Ana", "en", "player", token_hash=token_hash(token))
    with TestClient(app, base_url=BASE_URL) as client:
        client.cookies.set(SEAT_COOKIE, token)
        yield cid, client


def test_a_seat_gets_the_settings_lore_facts(player):
    cid, client = player
    response = client.get(f"/api/campaigns/{cid}/lore/random")
    assert response.status_code == 200, response.json()
    facts = response.json()["facts"]
    kept = {text for text, category, enabled, _ in LORE_FACTS if enabled and category != "campaign"}
    assert {fact["text"] for fact in facts} == kept  # fewer than 20 in the fixture: every one
    assert all(set(fact) == {"text", "category"} for fact in facts)
    assert CAMPAIGN_ONLY not in response.text and "CAMPAIGN-ONLY" not in response.text
    assert len(client.get(f"/api/campaigns/{cid}/lore/random?n=2").json()["facts"]) == 2


def test_n_is_bounded(player):
    cid, client = player
    assert client.get(f"/api/campaigns/{cid}/lore/random?n=0").status_code == 422
    assert client.get(f"/api/campaigns/{cid}/lore/random?n=101").status_code == 422


def test_a_campaign_without_a_setting_has_no_facts(local, storage):
    cid = campaign(storage, setting="")
    response = local.get(f"/api/campaigns/{cid}/lore/random")
    assert response.status_code == 200 and response.json() == {"facts": []}


def test_another_tables_seat_is_refused(player, app, storage):
    cid, _ = player
    other = campaign(storage)
    token = new_seat_token()
    storage.seats.create(other, "Bo", "en", "player", token_hash=token_hash(token))
    with TestClient(app, base_url=BASE_URL) as client:
        client.cookies.set(SEAT_COOKIE, token)
        response = client.get(f"/api/campaigns/{cid}/lore/random")
    assert response.status_code in (401, 403) and CAMPAIGN_ONLY not in response.text


def texts(client, cid, n=100):
    response = client.get(f"/api/campaigns/{cid}/lore/random?n={n}")
    assert response.status_code == 200, response.json()
    return response, {fact["text"] for fact in response.json()["facts"]}


def test_lore_has_install_facts_and_never_dm_only_ones(player, storage):
    cid, client = player
    storage.setting_facts.add(SettingFact(0, "greyhawk", "Hardby's gynarchs wear white.", "greyhawk"))
    storage.setting_facts.add(SettingFact(0, "greyhawk", f"{SECRET}: the Gynarch is a doppelganger.", dm_only=True))
    storage.setting_facts.add(
        SettingFact(0, "greyhawk", f"The Wild Coast is lawless.\n\n::: dm\n{SECRET}: Iuz pays its lords.\n:::\n")
    )
    storage.proposals.add(Proposal(0, "greyhawk", cid, "fact", text=f"{SECRET}: the party's patron is Iuz.", dm_only=True))
    storage.proposals.add(Proposal(0, "greyhawk", cid, "fact", text="The party is owed a boon in Hardby."))
    response, first = texts(client, cid)
    assert {"Hardby's gynarchs wear white.", "The Wild Coast is lawless.", "The party is owed a boon in Hardby."} <= first
    assert SECRET not in response.text
    for _ in range(50):
        assert SECRET not in texts(client, cid)[0].text


def test_lore_has_no_other_campaigns_proposals(player, storage, local):
    cid, client = player
    other = campaign(storage)
    storage.proposals.add(Proposal(0, "greyhawk", other, "fact", text="The other table razed Hardby."))
    assert "The other table razed Hardby." not in texts(client, cid)[1]
    assert "The other table razed Hardby." in texts(local, other)[1]
