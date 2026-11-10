"""Carrying a party into another campaign (carry-the-party-on plan Task 2): the chosen PCs are copied with a new id,
their possessions and the party's coin, loot and unowned possessions go with them, a painted portrait is copied so the
new campaign serves it, and the old campaign keeps every row it had, set to `complete`."""

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from delve.config import Config
from delve.domain.campaigns import CampaignState, LootItem
from delve.domain.characters import CharacterState, Effect, Item, MemorizedSpell, Sheet
from delve.domain.world import PLAIN_CALENDAR, CampaignImage, ImagePortrait, Possession, StartDate, TraitsPortrait
from delve.images.fake import PIXEL_PNG
from delve.play import seats
from delve.play.carry import FIGHT_CONDITIONS, FightLive, NotCarried, carry_into, check_carry
from delve.web.app import create_app
from tests.play.conftest import crypt_campaign
from tests.web.conftest import BASE_URL, INDEX_HTML, make_registries


@pytest.fixture
def old(storage):
    return crypt_campaign(storage)


@pytest.fixture
def new(storage):
    return crypt_campaign(storage)


def pc(storage, campaign_id, name, **state):
    sheet = Sheet(cls="Fighter", levels={"fighter": 3}, hp_max=24, faction="fac_guild")
    return storage.characters.create(campaign_id, name, sheet=sheet, state=CharacterState(**state))


@pytest.fixture
def party(storage, old):
    """Ana, Bo and Cy, in that marching order, and an NPC."""
    ana = pc(
        storage,
        old.id,
        "Ana",
        hp=17,
        xp=4200,
        inventory=(Item("rope", 1, 7.5), Item("torch", 6)),
        memorized=(MemorizedSpell("sleep", 1, cast=True), MemorizedSpell("light", 1)),
        conditions=("diseased", "prone", "casting", "downed"),
        effects=(Effect("bless", 4, to_hit=1),),
    )
    bo = pc(storage, old.id, "Bo", hp=9)
    cy = pc(storage, old.id, "Cy", hp=11)
    npc = storage.characters.create(old.id, "Innkeeper", kind="npc")
    return {"Ana": ana, "Bo": bo, "Cy": cy, "npc": npc}


def everything_of(storage, campaign_id):
    """Every row a carry could touch, of one campaign."""
    return (
        storage.campaigns.get(campaign_id),
        storage.characters.list(campaign_id),
        storage.possessions.list(campaign_id),
        storage.campaign_states.get(campaign_id),
        storage.campaign_images.list(campaign_id),
    )


def carried(storage, mapping, old_id):
    return storage.characters.get(mapping[old_id])


def test_copies_sheet_and_state_with_a_new_id(storage, old, new, party):
    ids = [party["Cy"].id, party["Ana"].id, party["Bo"].id]
    mapping = carry_into(storage, old.id, new.id, ids)
    assert set(mapping) == set(ids)
    for name in ("Ana", "Bo", "Cy"):
        before, after = party[name], carried(storage, mapping, party[name].id)
        assert after.id != before.id and after.id.startswith("chr_")
        assert after.campaign_id == new.id and after.name == name and after.kind == "pc"
        assert after.sheet.levels == before.sheet.levels and after.sheet.hp_max == before.sheet.hp_max
        assert (after.state.hp, after.state.xp) == (before.state.hp, before.state.xp)
        assert after.state.inventory == before.state.inventory
        assert after.state.memorized == before.state.memorized
    marching = [c.name for c in sorted(storage.characters.list(new.id), key=lambda c: c.order)]
    assert marching == ["Ana", "Bo", "Cy"], "A's marching order, not the order the ids came in"


def test_drops_effects_and_fight_conditions_keeps_lasting_ones(storage, old, new, party):
    mapping = carry_into(storage, old.id, new.id, [party["Ana"].id])
    state = carried(storage, mapping, party["Ana"].id).state
    assert state.effects == ()
    assert state.conditions == ("diseased", "downed")
    assert not set(state.conditions) & set(FIGHT_CONDITIONS)


def test_clears_faction_and_controller(storage, old, new, party):
    owner_seat = seats.owner_seat(storage, old.id)
    storage.seats.set_controller(party["Ana"].id, owner_seat.id)
    mapping = carry_into(storage, old.id, new.id, [party["Ana"].id])
    ana = carried(storage, mapping, party["Ana"].id)
    assert ana.sheet.faction == ""
    assert ana.controller_id is None
    assert storage.characters.get(party["Ana"].id).controller_id == owner_seat.id


def test_old_characters_unchanged(storage, old, new, party):
    storage.possessions.put(Possession(old.id, "pos_mare", "Mare", "mount", owner_id=party["Ana"].id))
    storage.possessions.put(Possession(old.id, "pos_cart", "Cart", "vehicle"))
    storage.campaign_states.put(CampaignState(old.id, coin={"gp": 40}, loot=(LootItem("gem", "a ruby", 50),)))
    before = everything_of(storage, old.id)
    carry_into(storage, old.id, new.id, [party["Ana"].id, party["Bo"].id])
    campaign, *rest = everything_of(storage, old.id)
    assert (replace(campaign, status=before[0].status), *rest) == before, "only the status changes"


def test_owned_and_unowned_possessions_copied(storage, old, new, party):
    ana, cy = party["Ana"], party["Cy"]
    storage.possessions.put(
        Possession(old.id, "pos_mare", "Mare", "mount", owner_id=ana.id, stats={"hp": 13}, notes_md="skittish")
    )
    storage.possessions.put(Possession(old.id, "pos_cart", "Cart", "vehicle", value_gp=30))
    storage.possessions.put(Possession(old.id, "pos_lute", "Lute", "other", owner_id=cy.id))
    mapping = carry_into(storage, old.id, new.id, [ana.id, party["Bo"].id])
    copied = {p.name: p for p in storage.possessions.list(new.id)}
    assert set(copied) == {"Mare", "Cart"}, "the possessions of a PC left behind stay behind"
    mare, cart = copied["Mare"], copied["Cart"]
    assert mare.owner_id == mapping[ana.id] and mare.id != "pos_mare" and mare.id.startswith("pos_")
    assert (mare.kind, mare.stats, mare.notes_md) == ("mount", {"hp": 13}, "skittish")
    assert cart.owner_id is None and cart.value_gp == 30 and cart.id != "pos_cart"
    assert storage.possessions.get(old.id, "pos_mare").owner_id == ana.id


def test_coin_added_and_loot_appended(storage, old, new, party):
    storage.campaign_states.put(
        CampaignState(old.id, coin={"gp": 40, "sp": 12}, loot=(LootItem("gem", "a ruby", 50), LootItem("art", "a urn")))
    )
    storage.campaign_states.put(CampaignState(new.id, coin={"gp": 5}, loot=(LootItem("item", "a map"),), day=3, hour=9))
    carry_into(storage, old.id, new.id, [party["Ana"].id])
    state = storage.campaign_states.get(new.id)
    assert state.coin["gp"] == 45 and state.coin["sp"] == 12
    assert [item.description for item in state.loot] == ["a map", "a ruby", "a urn"]
    assert (state.day, state.hour) == (3, 9), "only the coin and the loot change"


def test_the_calendar_goes_on_in_a_shared_calendar(storage, old, new, party):
    """Carried on in the same calendar, the new campaign's day 1 is the old one's today, at its hour (DEL-104)."""
    storage.campaign_states.put(CampaignState(old.id, day=40, hour=19, minute=30, start_date=StartDate(1340, 120)))
    carry_into(storage, old.id, new.id, [party["Ana"].id], PLAIN_CALENDAR)
    state = storage.campaign_states.get(new.id)
    assert (state.day, state.hour, state.minute, state.start_date) == (1, 19, 30, StartDate(1340, 159))
    went_on, was = PLAIN_CALENDAR.date(state.start_date.as_tuple(), 1), PLAIN_CALENDAR.date((1340, 120), 40)
    assert (went_on.year, went_on.day_of_year, went_on.season) == (was.year, was.day_of_year, was.season)


def test_the_calendar_goes_on_from_its_default_start_and_over_the_year(storage, old, new, party):
    storage.campaign_states.put(CampaignState(old.id, day=400))
    carry_into(storage, old.id, new.id, [party["Ana"].id], PLAIN_CALENDAR)
    assert storage.campaign_states.get(new.id).start_date == StartDate(2, 36)  # 364 days a year, from (1, 1)


def test_coin_and_loot_reach_a_campaign_without_a_state(storage, old, new, party):
    storage.campaign_states.put(CampaignState(old.id, coin={"gp": 40}, loot=(LootItem("gem", "a ruby", 50),)))
    carry_into(storage, old.id, new.id, [party["Ana"].id])
    state = storage.campaign_states.get(new.id)
    assert state.coin["gp"] == 40 and [item.description for item in state.loot] == ["a ruby"]


def painted(storage, campaign_id, image_id, kind, subject_id, status="done"):
    sha = storage.blobs.put(PIXEL_PNG, "image/png") if status == "done" else None
    return storage.campaign_images.put(
        CampaignImage(image_id, campaign_id, kind, subject_id, status=status, blob=sha, mime="image/png", prompt="p")
    )


def test_painted_portrait_is_copied_and_served(storage, old, new, party, tmp_path):
    ana, bo, cy = party["Ana"], party["Bo"], party["Cy"]
    face = painted(storage, old.id, "img_anaface000", "portrait", ana.id)
    storage.characters.save(replace(ana, sheet=replace(ana.sheet, portrait=ImagePortrait(face.id))))
    painting = painted(storage, old.id, "img_bopainting", "portrait", bo.id, status="painting")
    storage.characters.save(replace(bo, sheet=replace(bo.sheet, portrait=ImagePortrait(painting.id))))
    traits = TraitsPortrait("a tall man", "seed-1")
    storage.characters.save(replace(cy, sheet=replace(cy.sheet, portrait=traits)))
    mare = painted(storage, old.id, "img_mare000000", "possession", "pos_mare")
    storage.possessions.put(
        Possession(old.id, "pos_mare", "Mare", "mount", owner_id=ana.id, portrait=ImagePortrait(mare.id))
    )

    mapping = carry_into(storage, old.id, new.id, [ana.id, bo.id, cy.id])

    new_ana = carried(storage, mapping, ana.id)
    copies = {image.kind: image for image in storage.campaign_images.list(new.id)}
    assert set(copies) == {"portrait", "possession"}, "a picture not done isn't copied"
    face_copy, mare_copy = copies["portrait"], copies["possession"]
    assert face_copy.id != face.id and face_copy.blob == face.blob and face_copy.status == "done"
    assert face_copy.subject_id == new_ana.id and new_ana.sheet.portrait == ImagePortrait(face_copy.id)
    new_mare = storage.possessions.list(new.id)[0]
    assert mare_copy.blob == mare.blob and mare_copy.subject_id == new_mare.id
    assert new_mare.portrait == ImagePortrait(mare_copy.id)
    assert carried(storage, mapping, bo.id).sheet.portrait is None
    assert carried(storage, mapping, cy.id).sheet.portrait == traits
    assert storage.characters.get(ana.id).sheet.portrait == ImagePortrait(face.id)

    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text(INDEX_HTML)
    app = create_app(Config(data_dir=tmp_path / "data"), storage, make_registries(), static_dir=static)
    with TestClient(app, base_url=BASE_URL, client=("127.0.0.1", 50000)) as local:
        for image in (face_copy, mare_copy):
            response = local.get(f"/api/campaigns/{new.id}/pictures/{image.id}")
            assert response.status_code == 200 and response.content == PIXEL_PNG
        assert local.get(f"/api/campaigns/{new.id}/pictures/{face.id}").status_code == 404
        assert local.get(f"/api/campaigns/{old.id}/pictures/{face.id}").status_code == 200


def test_records_carry_and_completes_old_campaign(storage, old, new, party):
    ids = [party["Ana"].id, party["Bo"].id]
    carry_into(storage, old.id, new.id, ids)
    carry = storage.carries.origin(new.id)
    assert carry.from_campaign_id == old.id and carry.to_campaign_id == new.id
    assert carry.character_ids == tuple(ids)
    assert storage.campaigns.get(old.id).status == "complete"
    assert storage.campaigns.get(new.id).status == "in_progress"


def test_carry_is_one_transaction(storage, old, new, party):
    storage.carries.add(old.id, new.id, [])  # the second carry into `new` is refused, at the very end
    with pytest.raises(ValueError):
        carry_into(storage, old.id, new.id, [party["Ana"].id])
    assert storage.characters.list(new.id) == []
    assert storage.campaigns.get(old.id).status == "in_progress"


def test_check_refuses_a_live_fight(storage, old, party):
    storage.combats.create(old.id, "initiative", {})
    with pytest.raises(FightLive) as refused:
        check_carry(storage, old.id, [party["Ana"].id])
    assert refused.value.message == "End the fight first."


def test_check_refuses_npc_unknown_and_empty(storage, old, new, party):
    stranger = pc(storage, new.id, "Stranger")
    for ids, named in (
        ([party["Ana"].id, party["npc"].id], party["npc"].id),
        (["chr_000000000000"], "chr_000000000000"),
        ([stranger.id], stranger.id),
    ):
        with pytest.raises(NotCarried) as refused:
            check_carry(storage, old.id, ids)
        assert named in refused.value.message
    with pytest.raises(NotCarried):
        check_carry(storage, old.id, [])
    check_carry(storage, old.id, [party["Ana"].id, party["Bo"].id])


def test_dead_pc_carried_when_asked(storage, old, new, party):
    dead = pc(storage, old.id, "Dag", hp=-12, conditions=("dead",))
    check_carry(storage, old.id, [dead.id])
    mapping = carry_into(storage, old.id, new.id, [dead.id])
    copy = carried(storage, mapping, dead.id)
    assert copy.state.hp == -12 and copy.state.conditions == ("dead",)
