"""Edit portrait (DEL-238): while Preferences draw PCs' portraits with portraitgen, a PC's sheet saves the traits made
in portraitgen's editor instead of repainting; who may is who may repaint, and only portraitgen's own traits are
kept."""

from fastapi.testclient import TestClient

from delve.domain.settings import Job
from delve.domain.world import TraitsPortrait
from delve.play import images
from tests.domain.test_portrait_traits import DWARF
from tests.web.conftest import BASE_URL, make_account, session_for
from tests.web.test_pictures_api import table  # noqa: F401 (the fixture `table`)
from tests.web.test_portrait_repaint_api import brush, choose, npc, registries, sheet  # noqa: F401 (fixtures)
from tests.web.test_preferences_api import published


def edit(client, cid, character_id, traits=DWARF):
    return client.put(f"/api/campaigns/{cid}/characters/{character_id}/portrait", json={"traits": traits})


def test_a_player_saves_their_pcs_edited_portrait(local, table, storage, app):  # noqa: F811
    cid, garrek = table["campaign"], table["garrek"]
    assert sheet(table["Ana"], cid, garrek)["portrait_editable"] is True, "portraitgen draws PCs by default"
    answered = edit(table["Ana"], cid, garrek, {**DWARF, "seed": "chr_x1"})
    assert answered.status_code == 200, answered.json()
    kept = {**DWARF, "seed": "chr_x1", "turn": 0.0}
    assert answered.json() == {"portrait": {"kind": "traits", "describe": "an adventurer", "seed": "chr_x1",
                                            "traits": kept}}  # fmt: skip
    assert storage.characters.get(garrek).sheet.portrait == TraitsPortrait("an adventurer", "chr_x1", traits=kept)
    assert sheet(table["Ana"], cid, garrek)["sheet"]["portrait"]["traits"] == kept
    assert ("characters", {"campaign_id": cid}) in [(e.type, e.data) for e in published(app)]


def test_who_may_edit(local, app, table, storage):  # noqa: F811
    cid, garrek, pippa = table["campaign"], table["garrek"], table["pippa"]
    assert edit(local, cid, pippa).status_code == 200, "the owner hosts"
    assert edit(table["Cy"], cid, garrek).status_code == 200, "a co-host runs the table"
    refused = edit(table["Ana"], cid, pippa)
    assert refused.status_code == 403
    with TestClient(app, base_url=BASE_URL) as stranger:
        session_for(storage, make_account(storage, "sam"), stranger)
        assert edit(stranger, cid, garrek).status_code == 403, "no seat at this table"
    assert edit(local, cid, "chr_nobody").status_code == 404


def test_only_a_pcs_portrait_while_portraitgen_draws_them(local, table, storage, npc):  # noqa: F811
    cid, garrek = table["campaign"], table["garrek"]
    refused = edit(local, cid, npc)
    assert refused.status_code == 422 and refused.json()["error"] == images.NOT_EDITABLE, "an NPC is repainted"
    choose(storage, Job.IMAGE_PORTRAIT, "brush")
    assert sheet(table["Ana"], cid, garrek)["portrait_editable"] is False, "a painter repaints"
    assert edit(table["Ana"], cid, garrek).status_code == 422


def test_traits_portraitgen_didnt_write_are_refused_and_nothing_changes(local, table, storage):  # noqa: F811
    cid, garrek = table["campaign"], table["garrek"]
    before = storage.characters.get(garrek).sheet.portrait
    refused = edit(table["Ana"], cid, garrek, {**DWARF, "hair": '"><image href=x onerror=alert(1)>'})
    assert refused.status_code == 422
    assert refused.json()["error"] == "These aren't portraitgen's traits: hair: one of portraitgen's ids."
    assert storage.characters.get(garrek).sheet.portrait == before
