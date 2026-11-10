"""The dungeon-map drafts' routes (plan 7 Task 13): start a draft from a description or from the book's map page, list
the module's open drafts, keep one as a map, or discard it. Organisers only; Claude is `FakeDM`."""

from dataclasses import replace

import pytest

from delve.conversions.runner import _Live
from delve.dm.fake import FAKE_DM_CAPABILITIES, FakeDM
from delve.domain.backends import Registry
from delve.modules.books.sketch import DESCRIBED, FROM_BOOK
from delve.web.routes.conversions import conversions
from tests.conversions.test_dungeon_maps import (
    CELLAR,
    DESCRIPTION,
    GROUND,
    HOUSE_DRAFT,
    SKETCH,
    _book,
    _levelled,
    _levels,
    _module,
)
from tests.modules.books.test_sketch import GOOD
from tests.web.conftest import make_registries
from tests.web.test_conversions_api import ended
from tests.web.test_module_source_api import delete
from tests.web.test_preferences_api import published

VISION = [GOOD]
"""What the fake's vision call answers; a test may change it."""


@pytest.fixture(autouse=True)
def _vision():
    yield
    VISION[:] = [GOOD]


@pytest.fixture
def registries():
    dm = Registry()
    dm.register(
        FAKE_DM_CAPABILITIES,
        lambda: FakeDM([], side_handler=lambda prompt: GOOD, vision_handler=lambda prompt, image, media_type: VISION[0]),
    )
    return replace(make_registries(), dm=dm)


def drafts_path(module_id: str) -> str:
    return f"/api/modules/{module_id}/map-drafts"


def start(local, module_id: str, **body) -> dict:
    response = local.post(drafts_path(module_id), json={"description": DESCRIPTION, **body})
    assert response.status_code == 202, response.json()
    return ended(local, response.json()["id"])


def test_a_description_draft_is_listed_then_kept_as_a_new_map(local, storage, app):
    module_id = _module(storage)

    done = start(local, module_id, name="warren")

    assert (done["kind"], done["status"]) == ("dungeon-map", "done")
    [draft] = local.get(drafts_path(module_id)).json()
    assert draft == {
        "id": done["id"],
        "kind": "dungeon-map",
        "name": "warren",
        "source": f"{DESCRIBED}\n{GOOD}",
        "warnings": done["result"]["warnings"],
        "created_at": done["created_at"],
        "replaces": None,
        "part": None,
        "page": None,
        "maps": [{"name": "warren", "title": "warren", "source": f"{DESCRIBED}\n{GOOD}", "part": None}],
    }
    assert [m["name"] for m in local.get(f"/api/modules/{module_id}").json()["maps"]] == ["caves"]

    kept = local.post(f"{drafts_path(module_id)}/{done['id']}/keep", json={})

    assert kept.status_code == 201, kept.json()
    assert (kept.json()["name"], kept.json()["source"]) == ("warren", f"{DESCRIBED}\n{GOOD}")
    assert sorted(m["name"] for m in local.get(f"/api/modules/{module_id}").json()["maps"]) == ["caves", "warren"]
    assert local.get(drafts_path(module_id)).json() == []
    assert ("modules", {"id": module_id}) in [(event.type, event.data) for event in published(app)]


def test_keep_takes_a_name_and_a_taken_one_gets_2(local, storage):
    module_id = _module(storage)
    done = start(local, module_id)
    kept = local.post(f"{drafts_path(module_id)}/{done['id']}/keep", json={"name": "caves"})
    assert kept.status_code == 201 and kept.json()["name"] == "caves-2"


def test_a_book_draft_replaces_its_sketch(local, storage):
    module_id = _module(storage)

    response = local.post(f"{drafts_path(module_id)}/from-book", json={"map": "caves", "page": "map-page-3"})

    assert response.status_code == 202, response.json()
    done = ended(local, response.json()["id"])
    assert done["kind"] == "book-map"
    kept = local.post(f"{drafts_path(module_id)}/{done['id']}/keep", json={})
    assert kept.status_code == 201
    [caves] = local.get(f"/api/modules/{module_id}").json()["maps"]
    assert caves["source"] == f"{FROM_BOOK} asset:map-page-3.\n{GOOD}" != SKETCH


def test_a_page_that_isnt_a_map_page_is_422(local, storage):
    module_id = _module(storage)
    for page in ("notes-1", "map-page-9"):
        response = local.post(f"{drafts_path(module_id)}/from-book", json={"map": "caves", "page": page})
        assert response.status_code == 422, page
        assert "map page" in response.json()["error"]
    unknown = local.post(f"{drafts_path(module_id)}/from-book", json={"map": "nope", "page": "map-page-3"})
    assert unknown.status_code == 404


def test_a_discarded_draft_isnt_listed_nor_kept(local, storage):
    module_id = _module(storage)
    done = start(local, module_id)

    assert delete(local, f"{drafts_path(module_id)}/{done['id']}").status_code == 204

    assert local.get(drafts_path(module_id)).json() == []
    assert local.post(f"{drafts_path(module_id)}/{done['id']}/keep", json={}).status_code == 404
    assert delete(local, f"{drafts_path(module_id)}/{done['id']}").status_code == 404


def test_refusals(local, storage):
    module_id = _module(storage)
    assert local.post(drafts_path(module_id), json={"description": " "}).status_code == 422
    assert local.post(drafts_path("mod_nope"), json={"description": DESCRIPTION}).status_code == 404
    assert local.get(drafts_path("mod_nope")).status_code == 404
    done = start(local, module_id)
    bad_name = local.post(f"{drafts_path(module_id)}/{done['id']}/keep", json={"name": "a/b"})
    assert bad_name.status_code == 422


def test_a_second_draft_while_one_runs_is_409(local, storage, app):
    module_id = _module(storage)
    services = conversions(app)
    running = storage.conversions.create("generate", "A dungeon", "ready")
    services.live[running.id] = _Live(running)
    try:
        response = local.post(drafts_path(module_id), json={"description": DESCRIPTION})
    finally:
        services.live.pop(running.id)
    assert response.status_code == 409
    assert response.json()["conversion"]["id"] == running.id


def test_a_seat_or_another_device_is_refused(lan, storage):
    module_id = _module(storage)
    assert lan.get(drafts_path(module_id)).status_code == 401
    assert lan.post(drafts_path(module_id), json={"description": DESCRIPTION}).status_code == 401


def test_from_book_takes_any_page_picture(local, storage):
    module_id = _book(storage)
    for page in ("page-37", "page-37-2"):
        response = local.post(f"{drafts_path(module_id)}/from-book", json={"page": page})
        assert response.status_code == 202, (page, response.json())
        ended(local, response.json()["id"])
    for page in ("source-pdf", "page-12"):
        refused = local.post(f"{drafts_path(module_id)}/from-book", json={"page": page})
        assert refused.status_code == 422, page
    unknown = local.post(f"{drafts_path(module_id)}/from-book", json={"page": "page-37", "part": "the-castle"})
    assert unknown.status_code == 404


def test_keep_refuses_a_mismatch_with_its_problems_and_force_keeps_it(local, storage):
    module_id = _book(storage)
    VISION[0] = f"```dmap\n{HOUSE_DRAFT}```"
    response = local.post(
        f"{drafts_path(module_id)}/from-book", json={"map": None, "page": "page-35", "part": "the-sea-ghost"}
    )
    done = ended(local, response.json()["id"])
    [draft] = local.get(drafts_path(module_id)).json()
    assert (draft["replaces"], draft["part"], draft["page"]) == (None, "the-sea-ghost", "page-35")

    refused = local.post(f"{drafts_path(module_id)}/{done['id']}/keep", json={})

    assert refused.status_code == 409
    assert refused.json()["error"] == "The draft's rooms don't match The Sea Ghost."
    assert len(refused.json()["problems"]) == 2
    kept = local.post(f"{drafts_path(module_id)}/{done['id']}/keep", json={"force": True})
    assert kept.status_code == 201, kept.json()
    assert kept.json()["name"] == "page-35"


def test_a_book_draft_of_two_levels_is_listed_and_kept_as_two_maps(local, storage):
    module_id = _levelled(storage)
    VISION[0] = _levels(GROUND, CELLAR)
    response = local.post(f"{drafts_path(module_id)}/from-book", json={"page": "map-page-2", "part": "the-haunted-house"})
    ended(local, response.json()["id"])
    [draft] = local.get(drafts_path(module_id)).json()
    names = ["the-haunted-house-ground-floor", "the-haunted-house-cellar"]
    assert [(m["name"], m["title"], m["part"]) for m in draft["maps"]] == [
        (names[0], "Ground floor", "the-haunted-house"),
        (names[1], "Cellar", "the-haunted-house"),
    ]

    kept = local.post(f"{drafts_path(module_id)}/{draft['id']}/keep", json={})

    assert kept.status_code == 201, kept.json()
    assert kept.json()["name"] == names[0]
    maps = [m["name"] for m in local.get(f"/api/modules/{module_id}").json()["maps"]]
    assert set(names) <= set(maps)
