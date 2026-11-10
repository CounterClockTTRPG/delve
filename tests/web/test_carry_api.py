"""Carry the party on, the route (carry-the-party-on plan Task 3): `POST /api/campaigns/{id}/carry` makes a campaign
on another module as `POST /api/campaigns` does, copies the chosen PCs into it, and links both campaigns."""

from delve.modules.dscn import Bundle
from tests.fixtures import SAMPLES
from tests.web.test_campaigns_api import campaign, character, crypt_module, seat_browser
from tests.web.test_house_rules_api import bundle, rule


def carry(local, old_id: str, module_id: str, character_ids: list[str], **fields):
    body = {"name": "Barrowmaze", "module_id": module_id, "character_ids": character_ids, **fields}
    return local.post(f"/api/campaigns/{old_id}/carry", json=body)


def factioned_module(local) -> str:
    """A module whose campaigns are seeded with one faction, the Abbey Guard."""
    scenario = Bundle.load(SAMPLES / "scenarios" / "crypt-of-saint-vellis")
    scenario.set_entities("factions", [{"id": "guard", "name": "The Abbey Guard"}])
    imported = local.post("/api/modules/import", content=scenario.to_zip(), headers={"Content-Type": "application/zip"})
    assert imported.status_code == 201, imported.json()
    return imported.json()["id"]


def old_party(local, names=("Ana", "Bo")) -> tuple[dict, list[str]]:
    """A campaign on a crypt module, and the ids of its PCs."""
    old = campaign(local, crypt_module(local, title="Gentle")["id"], "Gentle")
    return old, [character(local, old["id"], name)["id"] for name in names]


def test_carry_makes_a_campaign_on_the_module_with_the_party(local, storage):
    old, (ana, _) = old_party(local)
    module_id = factioned_module(local)
    response = carry(local, old["id"], module_id, [ana])
    assert response.status_code == 201, response.json()
    new = response.json()
    assert new["id"] != old["id"] and new["name"] == "Barrowmaze"
    assert new["module_id"] == module_id and new["revision"] == 1 and new["status"] == "in_progress"
    assert [c.name for c in storage.characters.list(new["id"])] == ["Ana"]
    assert [s.role for s in storage.seats.list(new["id"])] == ["host"], "the owner's seat"
    assert [f.id for f in storage.factions.list(new["id"])] == ["guard"]
    assert storage.campaigns.get(old["id"]).status == "complete"
    assert [c.name for c in storage.characters.list(old["id"])] == ["Ana", "Bo"], "the old party stays"


def test_the_calendar_goes_on_in_the_same_setting_and_starts_again_in_another(local, storage):
    """DEL-104: carried on in the old campaign's setting, the new one's day 1 is the old one's today at its hour; in
    another setting, whose calendar is another, its days start again."""
    from dataclasses import replace

    from delve.domain.campaigns import CampaignState
    from delve.domain.world import StartDate

    old, (ana, bo) = old_party(local)
    assert old["setting"] is not None
    state = storage.campaign_states.get(old["id"]) or CampaignState(old["id"])
    storage.campaign_states.put(replace(state, day=10, hour=20, minute=15, start_date=StartDate(1340, 100)))
    same = carry(local, old["id"], crypt_module(local)["id"], [ana]).json()
    went_on = storage.campaign_states.get(same["id"])
    assert (went_on.day, went_on.hour, went_on.minute, went_on.start_date) == (1, 20, 15, StartDate(1340, 109))

    storage.campaigns.set_status(old["id"], "in_progress")
    other = carry(local, old["id"], crypt_module(local)["id"], [bo], setting=None).json()
    again = storage.campaign_states.get(other["id"]) or CampaignState(other["id"])
    assert (again.day, again.hour, again.start_date) == (1, 6, None)


def test_defaults_to_old_campaigns_ruleset_setting_and_house_rules(local, storage):
    lizard = rule(local)
    table = bundle(local, [lizard["id"]])
    module = crypt_module(local, title="Gentle")
    started = local.post(
        "/api/campaigns",
        json={
            "name": "Gentle",
            "module_id": module["id"],
            "setting": None,
            "bundle_ids": [table["id"]],
            "rule_ids": [lizard["id"]],
        },
    )
    assert started.status_code == 201, started.json()
    old = started.json()
    ana = character(local, old["id"], "Ana")["id"]
    # The scenario names its setting; the carry keeps the old campaign's none, not the module's.
    response = carry(local, old["id"], factioned_module(local), [ana])
    assert response.status_code == 201, response.json()
    new = response.json()
    assert (new["ruleset"], new["setting"]) == (old["ruleset"], "")
    assert storage.campaign_house_rules.get(new["id"]) == ([table["id"]], [lizard["id"]])


def test_given_ruleset_and_house_rules_win(local, storage):
    lizard, other = rule(local), rule(local, title="Elves", subject="Elf")
    old, (ana, _) = old_party(local)
    chosen = local.put(f"/api/campaigns/{old['id']}/house-rules", json={"bundle_ids": [], "rule_ids": [lizard["id"]]})
    assert chosen.status_code == 200, chosen.json()
    response = carry(
        local, old["id"], crypt_module(local)["id"], [ana], ruleset="fake-rules", setting=None, rule_ids=[other["id"]]
    )
    assert response.status_code == 201, response.json()
    new = response.json()
    assert (new["ruleset"], new["setting"]) == ("fake-rules", "")
    assert storage.campaign_house_rules.get(new["id"]) == ([], [other["id"]])
    empty = carry(local, old["id"], crypt_module(local)["id"], [ana], rule_ids=[], bundle_ids=[])
    assert empty.status_code == 201, empty.json()
    assert storage.campaign_house_rules.get(empty.json()["id"]) == ([], []), "an empty choice is a choice"


def test_draft_module_409(local, storage):
    old, (ana, _) = old_party(local)
    module = crypt_module(local)
    storage.modules.set_draft(module["id"], True)
    response = carry(local, old["id"], module["id"], [ana])
    assert response.status_code == 409
    assert response.json() == {"error": "This module is a draft: mark it ready first."}


def test_unknown_module_404(local):
    old, (ana, _) = old_party(local)
    response = carry(local, old["id"], "mod_000000000000", [ana])
    assert response.status_code == 404
    assert "error" in response.json()


def test_unknown_campaign_404(local):
    response = carry(local, "cmp_000000000000", crypt_module(local)["id"], ["chr_000000000000"])
    assert response.status_code == 404
    assert response.json() == {"error": "No such campaign."}


def test_live_fight_409_with_end_the_fight_first(local, storage):
    old, (ana, _) = old_party(local)
    storage.combats.create(old["id"], "round", {"round": 1, "combatants": {}})
    response = carry(local, old["id"], crypt_module(local)["id"], [ana])
    assert response.status_code == 409
    assert response.json()["error"] == "End the fight first."


def test_npc_or_foreign_id_422(local, storage):
    old, (ana, _) = old_party(local)
    npc = storage.characters.create(old["id"], "Tira", kind="npc")
    stranger = old_party(local, ("Cy",))[1][0]
    module_id = crypt_module(local)["id"]
    for wrong in (npc.id, stranger, "chr_000000000000"):
        response = carry(local, old["id"], module_id, [ana, wrong])
        assert response.status_code == 422, wrong
        assert wrong in response.json()["error"]


def test_empty_party_422(local):
    old, _ = old_party(local)
    response = carry(local, old["id"], crypt_module(local)["id"], [])
    assert response.status_code == 422
    assert "error" in response.json()


def test_player_seat_403(app, local, storage):
    old, (ana, _) = old_party(local)
    module_id = crypt_module(local)["id"]
    with seat_browser(app, storage, old["id"], "player") as player:
        response = carry(player, old["id"], module_id, [ana])
    assert response.status_code == 403
    assert len(storage.campaigns.list()) == 1


def test_campaign_json_links_both_ways(local):
    old, (ana, bo) = old_party(local)
    module_id = crypt_module(local)["id"]
    first = carry(local, old["id"], module_id, [ana]).json()
    second = carry(local, old["id"], module_id, [bo], name="Split").json()
    assert first["carried_from"] == {"id": old["id"], "name": "Gentle"} and first["carried_to"] == []
    read = local.get(f"/api/campaigns/{old['id']}").json()
    assert read["carried_from"] is None
    assert read["carried_to"] == [{"id": first["id"], "name": "Barrowmaze"}, {"id": second["id"], "name": "Split"}]
    assert local.get(f"/api/campaigns/{second['id']}").json()["carried_from"] == {"id": old["id"], "name": "Gentle"}
    listed = {c["id"]: c for c in local.get("/api/campaigns").json()}
    assert listed[old["id"]]["carried_to"] == read["carried_to"]


def test_links_survive_deleting_the_old_campaign(local, storage):
    old, (ana, _) = old_party(local)
    new = carry(local, old["id"], crypt_module(local)["id"], [ana]).json()
    assert local.request("DELETE", f"/api/campaigns/{old['id']}", json={}).status_code == 204
    read = local.get(f"/api/campaigns/{new['id']}").json()
    assert read["carried_from"] is None
    assert [c.name for c in storage.characters.list(new["id"])] == ["Ana"]


def test_refused_carry_makes_nothing(local, storage):
    old, (ana, _) = old_party(local)
    module_id = crypt_module(local)["id"]
    assert carry(local, old["id"], module_id, [ana, "chr_000000000000"]).status_code == 422
    assert carry(local, old["id"], module_id, [ana], rule_ids=["hr_000000000000"]).status_code == 422
    assert carry(local, old["id"], module_id, [ana], ruleset="nope").json() == {"error": "No ruleset 'nope'."}
    storage.combats.create(old["id"], "round", {"round": 1, "combatants": {}})
    assert carry(local, old["id"], module_id, [ana]).status_code == 409
    assert [c.id for c in storage.campaigns.list()] == [old["id"]]
    assert storage.campaigns.get(old["id"]).status == "in_progress"


def test_carrying_a_campaign_without_a_setting_accepts_an_empty_setting(local):
    """The Carry form sends the old campaign's `""` for none."""
    old = local.post(
        "/api/campaigns", json={"name": "Gentle", "module_id": crypt_module(local)["id"], "setting": None}
    ).json()
    ana = character(local, old["id"], "Ana")["id"]
    response = carry(local, old["id"], crypt_module(local)["id"], [ana], setting="")
    assert response.status_code == 201, response.json()
    assert response.json()["setting"] == ""
