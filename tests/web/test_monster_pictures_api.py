"""The kinds of monsters' pictures (DEL-275): an organiser has one painted, for every campaign, and anyone Delve knows
reads it; seeded from the owner's own paintings, never the counter set beside them."""

import json
import time

import pytest

from delve.domain.backends import Registry
from delve.domain.modules import ModuleMap
from delve.domain.world import MonsterPicture
from delve.images.fake import PIXEL_PNG
from delve.images.portraitgen import PORTRAITGEN_CAPABILITIES, PortraitgenImages
from delve.play import monster_pictures
from tests.web.conftest import log_in, make_account, make_registries
from tests.web.test_pictures_api import SLOW, SlowPainter


@pytest.fixture
def painter():
    return SlowPainter()


@pytest.fixture
def registries(painter):
    registries = make_registries()
    images = Registry()
    images.register(PORTRAITGEN_CAPABILITIES, PortraitgenImages)
    images.register(SLOW, lambda: painter)
    registries.images = images
    return registries


@pytest.fixture
def slow(storage):
    storage.settings.save({"choices": {"image.possession": {"provider": "slow", "model": None, "effort": None}}})


@pytest.fixture
def campaign_with_mudviper(storage):
    module = storage.modules.create("The Inn")
    storage.modules.put_map(module.id, ModuleMap("inn", "map", "map inn {}\n", is_default=True))
    note = 'giant poisonous snake, AC 5; MV 15"; HD 4+2'
    storage.module_texts.put(
        module.id,
        {"sections": [], "entities": {"encounters": [{"fixed": [{"creature": "monster:mudviper", "notes": note}]}]}},
    )
    revision = storage.revisions.snapshot(module.id)
    return storage.campaigns.create("Tuesday", module.id, revision.number, ruleset="osric", setting="").id


def settle(storage, slug: str, timeout: float = 5.0) -> MonsterPicture:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        picture = storage.monster_pictures.get(slug)
        if picture is not None and picture.status != "painting":
            return picture
        time.sleep(0.02)
    raise AssertionError(f"{slug} is still painting")


def test_an_organiser_has_a_kind_painted_once_for_everyone(local, storage, painter, slow):
    asked = local.post("/api/monster-pictures", json={"name": "Giant rat"})
    assert asked.status_code == 202, asked.text
    assert asked.json() == {
        "slug": "giant-rat",
        "picture": False,
        "version": None,
        "painting": True,
        "error": None,
        "paid": True,
    }
    assert local.post("/api/monster-pictures", json={"name": "Giant rat"}).status_code == 422, "one at a time"
    painter.gate.set()
    done = settle(storage, "giant-rat")
    assert (done.status, done.source, done.name) == ("done", "painted", "Giant rat")
    assert monster_pictures.STYLE not in done.prompt and done.prompt.startswith("A Giant rat.")
    served = local.get("/api/monster-pictures/giant-rat")
    assert served.status_code == 200 and served.content == PIXEL_PNG
    assert local.get("/api/monster-pictures", params={"name": "Giant rats"}).json()["picture"] is True


def test_a_repaint_keeps_the_old_picture_until_the_new_one_lands(local, storage, painter, slow):
    old = storage.blobs.put(b"old goblin", "image/webp")
    storage.monster_pictures.put(MonsterPicture("goblin", "Goblin", blob=old, mime="image/webp", source="seeded"))
    assert local.post("/api/monster-pictures", json={"name": "Goblin"}).json()["painting"] is True
    assert local.get("/api/monster-pictures/goblin").content == b"old goblin"
    painter.gate.set()
    assert settle(storage, "goblin").blob != old


def test_a_player_may_see_a_picture_and_whether_a_kind_has_one_but_not_paint_one(app, storage, lan):
    sha = storage.blobs.put(b"kobold", "image/webp")
    storage.monster_pictures.put(MonsterPicture("kobold", "Kobold", blob=sha, mime="image/webp", source="seeded"))
    make_account(storage)
    log_in(lan)
    assert lan.get("/api/monster-pictures/kobold").content == b"kobold"
    assert lan.post("/api/monster-pictures", json={"name": "Kobold"}).status_code == 403
    assert lan.get("/api/monster-pictures", params={"name": "Kobold"}).json()["picture"] is True
    assert lan.get("/api/monster-pictures/no-such-thing").status_code == 404


def test_nobody_reads_a_picture(app, storage, lan):
    assert lan.get("/api/monster-pictures/kobold").status_code == 401


def test_an_organiser_account_paints(storage, lan, painter, slow):
    make_account(storage, "olga", organiser=True)
    log_in(lan, "olga")
    assert lan.post("/api/monster-pictures", json={"name": "Mastiff"}).status_code == 202
    painter.gate.set()
    settle(storage, "mastiff")


def test_a_painting_a_stopped_delve_left_fails_and_keeps_its_picture(storage):
    old = storage.blobs.put(b"orc", "image/webp")
    storage.monster_pictures.put(MonsterPicture("orc", "Orc", status="painting", blob=old, mime="image/webp"))
    assert monster_pictures.resume(storage) == ["orc"]
    left = storage.monster_pictures.get("orc")
    assert (left.status, left.blob, left.error) == ("failed", old, monster_pictures.INTERRUPTED)


def test_seed_loads_the_owners_paintings_and_not_the_counter_set(storage, tmp_path):
    tokens = tmp_path / "tokens"
    tokens.mkdir()
    for key in ("kobold", "osric-kobold", "osric-giant-fire-beetle", "black-dragon"):
        (tokens / f"{key}-portrait.webp").write_bytes(key.encode())
    manifest = [
        {
            "key": "osric-kobold",
            "portrait": "osric-kobold-portrait.webp",
            "source": "generated/monsters/osric-kobold.png",
        },
        {"key": "kobold", "portrait": "kobold-portrait.webp", "source": "generated/monsters/kobold.png"},
        {"key": "osric-giant-fire-beetle", "source": "generated/monsters/osric-giant-fire-beetle.png"},
        {"key": "black-dragon", "portrait": "black-dragon-portrait.webp", "source": "DRAGON/dragon_black.jpg"},
    ]
    (tmp_path / "assets.json").write_text(json.dumps({"tokens": manifest}))
    assert sorted(monster_pictures.seed(storage, tmp_path)) == ["giant-fire-beetle", "kobold"]
    assert storage.blobs.get(storage.monster_pictures.get("kobold").blob) == b"kobold", "the plain key wins"
    assert storage.monster_pictures.get("black-dragon") is None
    assert monster_pictures.seed(storage, tmp_path) == [], "a kind with a picture keeps it"


@pytest.mark.parametrize(
    ("names", "found"),
    [
        (("Kobold 2", "Kobold"), "kobold"),
        (("Kobold leader", "Kobold"), "kobold-leader"),
        (("Freddie", "Thug"), None),
        (("Rat 3", "Giant rats"), "giant-rat"),
        (("Beetle 1", "Beetle, Giant Fire"), "giant-fire-beetle"),
        (("Skeleton 1", "Skeleton"), "skeleton"),
        (("Skeleton, Animal 1", "Skeleton, Animal"), None),
    ],
)
def test_a_combatant_finds_its_kinds_picture(storage, names, found):
    for kind in ("kobold", "kobold-leader", "giant-rat", "giant-fire-beetle", "skeleton"):
        sha = storage.blobs.put(kind.encode(), "image/webp")
        storage.monster_pictures.put(MonsterPicture(kind, kind, blob=sha, mime="image/webp", source="seeded"))
    picture = monster_pictures.find(storage, *names)
    assert (picture.slug if picture is not None else None) == found


def test_monster_picture_subject_from_the_ruleset_only(storage):
    """The brief reads the campaign's ruleset's lookups and nothing else: the table's services hold no reference."""
    from dataclasses import fields

    from delve.play.table import AppServices

    class Lookups:
        def monster(self, name):
            return [{"description": "A pale thing.  It hisses. It waits. It never rests."}]

    assert monster_pictures.subject(storage, Lookups(), "Wight") == "A Wight. A pale thing. It hisses."
    assert monster_pictures.subject(storage, None, "Wight") == "A Wight."
    assert "reference" not in {field.name for field in fields(AppServices)}


def test_a_kind_the_ruleset_doesnt_know_is_what_its_module_says_it_is(storage):
    """DEL-359: a module's own "mudviper" was painted from its name alone, as a lizard man; its encounter's note says
    it is a snake, and so does the parenthesis after its name in the prose."""
    encounter = {"fixed": [{"creature": "monster:mudviper", "notes": 'giant poisonous snake, AC 5; MV 15"; HD 4+2'}]}
    text = {"sections": [], "entities": {"encounters": [encounter]}}
    assert monster_pictures.subject(storage, None, "Mudviper", text) == "A Mudviper, a giant poisonous snake."
    prose = {"sections": [{"markdown": "the **mudvipers** (giant poisonous snake, AC 5; HD 4+2) wake"}], "entities": {}}
    assert monster_pictures.what_it_is(prose, "Mudviper") == "giant poisonous snake"
    for said in ("(q.v., AC 5)", "(INT low, AC 5)", "(males, AC 5)", "(they have no attacks, AC 7)", "(a big one)"):
        assert monster_pictures.what_it_is({"sections": [{"markdown": f"the mudviper {said}"}]}, "Mudviper") is None
    # The ruleset's entry comes first.

    class Lookups:
        def monster(self, name):
            return [{"description": "A snake of the swamps."}]

    assert monster_pictures.subject(storage, Lookups(), "Mudviper", text) == "A Mudviper. A snake of the swamps."


def test_the_style_paints_a_beast_as_an_animal():
    """DEL-359: the bust framing alone ("head, shoulders and chest") painted a crocodile in armour."""
    assert "never with a person's torso" in monster_pictures.STYLE
    assert "a beast its head and forebody" in monster_pictures.STYLE


def test_a_campaigns_module_text_goes_into_the_brief(local, storage, painter, slow, campaign_with_mudviper):
    asked = local.post("/api/monster-pictures", json={"name": "Mudviper", "campaign_id": campaign_with_mudviper})
    assert asked.status_code == 202, asked.text
    painter.gate.set()
    assert settle(storage, "mudviper").prompt == "A Mudviper, a giant poisonous snake."
