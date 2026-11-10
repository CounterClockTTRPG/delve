"""Module categories (DEL-114) and module banners (DEL-123) in storage: neither is an edit of the module."""

import pytest

from delve.config import Config
from delve.storage import open_storage
from delve.storage.interfaces import CategoryNameTaken


@pytest.fixture
def storage(tmp_path):
    opened = open_storage(Config(data_dir=tmp_path))
    yield opened
    opened.close()


def test_categories_keep_their_order_and_unique_names(storage):
    cats = storage.module_categories
    mega, one, arcs = cats.create("Megadungeons"), cats.create("One-shots"), cats.create("Campaign arcs")
    assert [c.name for c in cats.list()] == ["Megadungeons", "One-shots", "Campaign arcs"]
    with pytest.raises(CategoryNameTaken):
        cats.create("one-SHOTS")
    with pytest.raises(CategoryNameTaken):
        cats.rename(arcs.id, "megadungeons")
    assert cats.rename(one.id, "One shots").name == "One shots"
    assert [c.name for c in cats.move(arcs.id, 0)] == ["Campaign arcs", "Megadungeons", "One shots"]
    assert [c.position for c in cats.list()] == [0, 1, 2]
    assert [c.name for c in cats.move(arcs.id, 99)] == ["Megadungeons", "One shots", "Campaign arcs"]
    assert cats.get(mega.id) == cats.list()[0]
    with pytest.raises(KeyError):
        cats.rename("cat_none", "X")


def test_a_modules_category_is_no_edit_and_goes_with_its_category(storage):
    module = storage.modules.create("Crypt")
    mega = storage.module_categories.create("Megadungeons")
    other = storage.module_categories.create("Other")
    put = storage.modules.set_category(module.id, mega.id)
    assert put.category_id == mega.id and put.updated_at == module.updated_at, "not an edit"
    with pytest.raises(KeyError):
        storage.modules.set_category(module.id, "cat_none")
    assert storage.module_categories.delete(mega.id) == 1
    assert storage.modules.get(module.id).category_id is None
    assert [(c.name, c.position) for c in storage.module_categories.list()] == [("Other", 0)]
    assert storage.modules.set_category(module.id, other.id).category_id == other.id
    assert storage.modules.set_category(module.id, None).category_id is None


def test_a_banner_paints_lands_fails_and_clears(storage):
    module = storage.modules.create("Crypt")
    painting = storage.modules.banner_painting(module.id, "a crypt, at dusk")
    assert painting.banner.status == "painting" and painting.banner.blob is None and painting.banner.prompt
    sha = storage.blobs.put(b"\x89PNG banner", "image/png")
    landed = storage.modules.set_banner(module.id, sha, "image/png", "painted")
    assert (landed.banner.blob, landed.banner.mime, landed.banner.source) == (sha, "image/png", "painted")
    assert landed.banner.status is None and landed.banner.prompt is None
    assert landed.updated_at == module.updated_at, "not an edit"
    assert ("banner", sha) in storage.blobs.links(module.id), "linked, so exports and backups carry it"
    failed = storage.modules.banner_failed(module.id, "the painter is off")
    assert failed.banner.status == "failed" and failed.banner.blob == sha, "the picture shown stays"
    assert storage.modules.clear_banner(module.id).banner is None
