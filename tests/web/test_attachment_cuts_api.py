"""Crop, turn and split a module's picture (DEL-40): the cut is taken from the kept original, which only the organiser
sees."""

import dataclasses
import io

from PIL import Image

from delve.modules.dscn import sha256
from delve.modules.source import TextDoc, load_source, save_source
from delve.web.routes import assets
from tests.modules.test_cuts import BLUE, RED, colours, halves
from tests.web.test_assets_api import PDF, upload
from tests.web.test_campaigns_api import campaign, crypt_module
from tests.web.test_module_source_api import delete
from tests.web.test_modules_api import create
from tests.web.test_preferences_api import published

PICTURE = halves()


def picture(local, mid=None, name="cabins.png") -> tuple[str, str]:
    mid = mid or create(local)["id"]
    response = upload(local, mid, name, PICTURE, "image/png")
    assert response.status_code == 201, response.json()
    return mid, response.json()["id"]


def cut(local, mid, aid, rotate=0, *pieces):
    return local.post(f"/api/modules/{mid}/assets/{aid}/cut", json={"rotate": rotate, "pieces": list(pieces)})


def shown(local, mid, aid, **params) -> Image.Image:
    response = local.get(f"/api/modules/{mid}/assets/{aid}", params=params)
    assert response.status_code == 200
    image = Image.open(io.BytesIO(response.content))
    image.load()
    return image


def test_a_crop_keeps_the_original(local, storage):
    mid, aid = picture(local)
    response = cut(local, mid, aid, 0, {"box": [0.5, 0, 0.5, 1]})
    assert response.status_code == 200, response.json()
    [answered] = response.json()["attachments"]
    assert answered["id"] == aid
    assert answered["cut"] == {
        "original": sha256(PICTURE),
        "original_type": "image/png",
        "original_size": len(PICTURE),
        "rotate": 0,
        "box": [0.5, 0, 0.5, 1],
        "proposed": False,
    }
    image = shown(local, mid, aid)
    assert image.size == (100, 100) and colours(image) == {BLUE}
    assert answered["sha256"] != sha256(PICTURE)
    assert local.get(f"/api/modules/{mid}/assets/{aid}", params={"original": "true"}).content == PICTURE
    assert ("attachment", sha256(PICTURE)) in storage.blobs.links(mid)
    assert ("attachment", answered["sha256"]) in storage.blobs.links(mid)


def test_cutting_again_starts_from_the_original(local):
    mid, aid = picture(local)
    cut(local, mid, aid, 0, {"box": [0.5, 0, 0.5, 1]})
    again = cut(local, mid, aid, 0, {"box": [0, 0, 0.5, 1]}).json()["attachments"][0]
    image = shown(local, mid, aid)
    assert image.size == (100, 100) and colours(image) == {RED}
    assert again["cut"]["original"] == sha256(PICTURE)


def test_a_turn_with_no_box_keeps_all_of_it(local):
    mid, aid = picture(local)
    assert cut(local, mid, aid, 90, {"box": None}).status_code == 200
    assert shown(local, mid, aid).size == (100, 200)


def test_a_split_keeps_the_first_id(local):
    mid, aid = picture(local)
    local.patch(f"/api/modules/{mid}/assets/{aid}", json={"description": "Two cabins", "audience": "player"})
    response = cut(
        local,
        mid,
        aid,
        0,
        {"box": [0, 0, 0.5, 1], "description": "Cabin A"},
        {"box": [0.5, 0, 0.5, 1], "description": "Cabin B"},
    )
    assert response.status_code == 200, response.json()
    first, second = response.json()["attachments"]
    assert [first["id"], second["id"]] == [aid, f"{aid}-2"]
    assert first["cut"]["original"] == second["cut"]["original"] == sha256(PICTURE)
    assert (first["description"], second["description"]) == ("Cabin A", "Cabin B")
    assert first["audience"] == "player" and second["audience"] == "player"
    assert colours(shown(local, mid, first["id"])) == {RED}
    assert colours(shown(local, mid, second["id"])) == {BLUE}
    ids = [a["id"] for a in local.get(f"/api/modules/{mid}/source").json()["attachments"]]
    assert ids == [aid, f"{aid}-2"]


def test_a_split_never_takes_an_id_in_use(local):
    mid, aid = picture(local)
    picture(local, mid, f"{aid}-2.png")
    pieces = [{"box": [0, 0, 0.5, 1]}, {"box": [0.5, 0, 0.5, 1], "audience": "gm"}]
    _, second = cut(local, mid, aid, 0, *pieces).json()["attachments"]
    assert second["id"] == f"{aid}-3" and second["audience"] == "gm"
    named = cut(local, mid, aid, 0, {"box": None}, {"box": [0, 0, 0.5, 1], "id": aid}).json()["attachments"]
    assert named[1]["id"] == f"{aid}-4"


def test_reset_shows_the_whole_original(local):
    mid, aid = picture(local)
    _, second = cut(local, mid, aid, 0, {"box": [0, 0, 0.5, 1]}, {"box": [0.5, 0, 0.5, 1]}).json()["attachments"]
    response = delete(local, f"/api/modules/{mid}/assets/{aid}/cut")
    assert response.status_code == 200
    reset = response.json()
    assert reset["sha256"] == sha256(PICTURE) and reset["size"] == len(PICTURE) and reset["cut"] is None
    assert shown(local, mid, aid).size == (200, 100)
    after = {a["id"]: a for a in local.get(f"/api/modules/{mid}/source").json()["attachments"]}
    assert after[second["id"]] == second
    assert delete(local, f"/api/modules/{mid}/assets/{aid}/cut").status_code == 404


def test_reviewed_clears_proposed(local, storage):
    mid, aid = picture(local)
    cut(local, mid, aid, 0, {"box": [0, 0, 0.5, 1]})
    source = load_source(storage, mid)
    [attachment] = source.attachments
    proposed = dataclasses.replace(attachment, cut=dataclasses.replace(attachment.cut, proposed=True))
    save_source(storage, mid, dataclasses.replace(source, attachments=[proposed]))
    response = local.patch(f"/api/modules/{mid}/assets/{aid}", json={"reviewed": True})
    assert response.status_code == 200 and response.json()["cut"]["proposed"] is False
    assert load_source(storage, mid).attachments[0].cut.proposed is False


def test_refusals(local, lan):
    mid, aid = picture(local)
    assert cut(local, mid, aid, 45, {"box": None}).status_code == 422
    assert cut(local, mid, aid, 0, {"box": [0.9, 0, 0.2, 1]}).status_code == 422
    assert cut(local, mid, aid).status_code == 422
    assert cut(local, mid, aid, 0, *[{"box": None}] * 13).status_code == 422
    pdf = upload(local, mid, "rules.pdf", PDF, "application/pdf").json()["id"]
    assert cut(local, mid, pdf, 0, {"box": None}).status_code == 422
    assert cut(local, mid, "nothing", 0, {"box": None}).status_code == 404
    assert shown(local, mid, aid).size == (200, 100)  # nothing was cut
    refused = lan.post(f"/api/modules/{mid}/assets/{aid}/cut", json={"rotate": 0, "pieces": [{}]})
    assert refused.status_code in (401, 403)
    assert lan.get(f"/api/modules/{mid}/assets/{aid}", params={"original": "true"}).status_code in (401, 403)


def test_a_cut_publishes_modules(local, app):
    mid, aid = picture(local)
    before = len(published(app))
    cut(local, mid, aid, 0, {"box": [0, 0, 0.5, 1]})
    delete(local, f"/api/modules/{mid}/assets/{aid}/cut")
    events = [(event.type, event.data) for event in published(app)[before:]]
    assert events == [("modules", {"id": mid})] * 2


def test_players_never_get_the_original(local):
    module = crypt_module(local)
    mid, aid = picture(local, module["id"])
    local.patch(f"/api/modules/{mid}/assets/{aid}", json={"audience": "player"})
    cut(local, mid, aid, 0, {"box": [0.5, 0, 0.5, 1]})
    started = campaign(local, mid)
    response = local.get(f"/api/campaigns/{started['id']}/images/{aid}")
    assert response.status_code == 200
    image = Image.open(io.BytesIO(response.content))
    assert image.size == (100, 100)
    original = local.get(f"/api/campaigns/{started['id']}/images/{aid}", params={"original": "true"})
    assert original.content != PICTURE


def test_an_edit_while_cutting_is_kept(local, storage, monkeypatch):
    """The cut decodes before it reads the source to save: a text saved meanwhile (a second tab) is not lost."""
    mid, aid = picture(local)
    real = assets.cut_picture

    def slow_cut(*args):
        source = load_source(storage, mid)
        notes = TextDoc("notes", "Notes", "gm", None, "# Notes\n")
        save_source(storage, mid, dataclasses.replace(source, texts=[*source.texts, notes]))
        return real(*args)

    monkeypatch.setattr(assets, "cut_picture", slow_cut)
    assert cut(local, mid, aid, 0, {"box": [0, 0, 0.5, 1]}).status_code == 200
    after = load_source(storage, mid)
    assert [t.id for t in after.texts] == ["notes"]
    assert after.attachments[0].cut is not None


def test_a_picture_deleted_while_cutting_is_not_brought_back(local, storage, monkeypatch):
    mid, aid = picture(local)
    real = assets.cut_picture

    def deleting_cut(*args):
        source = load_source(storage, mid)
        save_source(storage, mid, dataclasses.replace(source, attachments=[]))
        return real(*args)

    monkeypatch.setattr(assets, "cut_picture", deleting_cut)
    assert cut(local, mid, aid, 0, {"box": [0, 0, 0.5, 1]}).status_code == 404
    assert load_source(storage, mid).attachments == []


def test_a_cut_may_be_proposed_for_review(local):
    """A crop pass over a module's pictures (DEL-293) proposes its cuts, as a conversion does, for Looks right."""
    mid, aid = picture(local)
    body = {"rotate": 0, "pieces": [{"box": [0, 0, 0.5, 1]}, {"box": [0.5, 0, 0.5, 1]}], "proposed": True}
    pieces = local.post(f"/api/modules/{mid}/assets/{aid}/cut", json=body).json()["attachments"]
    assert [p["cut"]["proposed"] for p in pieces] == [True, True]
    assert cut(local, mid, aid, 0, {"box": None}).json()["attachments"][0]["cut"]["proposed"] is False
