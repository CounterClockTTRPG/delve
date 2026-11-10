"""A campaign of a module with a banner (DEL-123): it paints none of its own when it is made, and shows the module's
on its table, its page and the account's list of tables, until its own lands."""

from tests.web.test_campaigns_api import campaign, crypt_module, settled
from tests.web.test_module_banners_api import picture


def with_banner(local) -> dict:
    module = crypt_module(local, title="The Crypt")
    sent = local.post(f"/api/modules/{module['id']}/banner/upload", content=picture(840, 600),
                      headers={"Content-Type": "image/png"})  # fmt: skip
    assert sent.status_code == 200, sent.text
    return sent.json()


def test_a_campaign_shows_its_modules_banner_and_paints_none(local, storage):
    module = with_banner(local)
    started = campaign(local, module["id"])
    assert storage.campaign_images.list(started["id"], kind="banner") == [], "no painting of its own"
    page = local.get(f"/api/campaigns/{started['id']}").json()["banner"]
    assert page["from_module"] is True and page["image_id"].startswith("mod-")
    state = local.get(f"/api/campaigns/{started['id']}/play/state").json()
    assert state["banner"] == page["image_id"]
    served = local.get(f"/api/campaigns/{started['id']}/banner")
    assert served.status_code == 200 and served.headers["content-type"] == "image/webp"
    assert served.content == local.get(f"/api/modules/{module['id']}/banner").content


def test_its_own_banner_replaces_the_modules(local, storage):
    module = with_banner(local)
    started = campaign(local, module["id"])
    painted = local.post(f"/api/campaigns/{started['id']}/banner", json={"hint": ""})
    assert painted.status_code == 202, painted.text
    assert settled(storage, painted.json()["image_id"]).status == "done"
    page = local.get(f"/api/campaigns/{started['id']}").json()["banner"]
    assert page["from_module"] is False and page["image_id"] == painted.json()["image_id"]


def test_a_module_without_a_banner_still_paints_one_for_its_campaign(local, storage):
    started = campaign(local, crypt_module(local)["id"])
    assert len(storage.campaign_images.list(started["id"], kind="banner")) == 1
    assert local.get(f"/api/campaigns/{started['id']}").json()["banner"]["from_module"] is False


def test_the_campaigns_list_names_the_banner_each_shows(local, storage):
    """The list's cards (DEL-207) show each campaign's banner: the module's until its own lands, none without one."""
    module = with_banner(local)
    shows_module = campaign(local, module["id"])
    bare = campaign(local, crypt_module(local)["id"])
    for image in storage.campaign_images.list(bare["id"], kind="banner"):
        settled(storage, image.id)
        storage.campaign_images.delete(image.id)
    listed = {c["id"]: c["banner"] for c in local.get("/api/campaigns").json()}
    assert listed[shows_module["id"]] == local.get(f"/api/campaigns/{shows_module['id']}").json()["banner"]["image_id"]
    assert listed[bare["id"]] is None
