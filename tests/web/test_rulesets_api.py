"""The rulesets API (rulesets plan Task 5): the book's sections, rows and entries for every reader, its monsters for
organisers only, and the campaign's homebrew beside it with its DM notes cut for anyone else.

A reader without the organiser role meets no monster by any door: the section, its rows, its entries, its count and
its search hits all answer as for something that doesn't exist, the same 404 byte for byte.
"""

import json
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from delve.domain.backends import ProviderCapabilities
from delve.domain.reference import PAGE_LIMIT
from delve.play import seats
from delve.rules.catalog import make_ruleset
from delve.web.seats import SEAT_COOKIE, new_seat_token, token_hash
from tests.fixtures.rulesets import osric_catalogs
from tests.web.conftest import BASE_URL, make_registries
from tests.web.test_campaigns_api import campaign, crypt_module

SECRET = "SECRET-XYZZY"
ITEM_BODY = (
    "## Description\n\nA blade that hums near a minotaur.\n\n## DM Notes\n\nSECRET-XYZZY: it was the minotaur's.\n"
)
CUT_BODY = "## Description\n\nA blade that hums near a minotaur.\n"


def with_the_book(registries) -> None:
    """OSRIC, installed as a pack, beside the fakes: its book, and the campaigns that play it."""
    registries.catalogs = osric_catalogs()
    ruleset = make_ruleset("osric", registries.catalogs.rulesets)
    registries.rulesets.register(ProviderCapabilities(ruleset.id, ruleset.title, frozenset()), lambda: ruleset)


@pytest.fixture
def registries():
    registries = make_registries()
    with_the_book(registries)
    return registries


def seat_client(app, storage, campaign_id: str, name: str, role: str = "player", *, organiser: bool = False):
    """A browser on the LAN with a new seat at the campaign's table."""
    token = new_seat_token()
    seat = storage.seats.create(campaign_id, name, "en", role, token_hash=token_hash(token))
    if organiser:
        seat = storage.seats.save(replace(seat, organiser=True))
    client = TestClient(app, base_url=BASE_URL)
    client.cookies.set(SEAT_COOKIE, token)
    return seat, client


@pytest.fixture
def tuesday(local):
    return campaign(local, crypt_module(local)["id"])["id"]


@pytest.fixture
def ana(app, storage, tuesday):
    seat, client = seat_client(app, storage, tuesday, "Ana")
    with client:
        yield seat, client


def choose(storage, campaign_id: str, *rules) -> None:
    storage.campaign_house_rules.put(campaign_id, [], [rule.id for rule in rules])


def item_rule(storage, title="Minotaur-bane", body=ITEM_BODY, **options):
    return storage.house_rules.create(title=title, body_md=body, kind="item", phases=["items"], **options)


def monster_id(local, name="minotaur") -> str:
    """The id of the monster named `name`, as the owner finds it."""
    (found,) = [row for row in local.get(f"{BASE}/monsters?q={name}").json()["rows"] if row["name"].lower() == name]
    return str(found["id"])


BASE = "/api/rulesets/osric"


# --- the rulesets ----------------------------------------------------------------------------------------------------


def test_the_rulesets_with_a_book(local):
    """The fake ruleset has no book, so only OSRIC is listed."""
    assert local.get("/api/rulesets").json() == [{"id": "osric", "title": "OSRIC 3.0"}]


def test_a_ruleset_and_its_sections(local):
    body = local.get(BASE).json()
    assert body["id"] == "osric" and body["title"] == "OSRIC 3.0" and body["campaign_id"] is None
    sections = {s["key"]: s for s in body["sections"]}
    assert list(sections) == ["spells", "monsters", "items", "classes", "races", "rules", "abilities", "turning"]
    assert sections["spells"] == {"key": "spells", "kind": "list", "count": 469}
    assert sections["abilities"]["kind"] == "table"


def test_unknown_things_are_404(local):
    for path in (
        "/api/rulesets/nope",
        "/api/rulesets/fake-rules",
        f"{BASE}/nope",
        f"{BASE}/spells/999999",
        f"{BASE}/spells/abc",
        f"{BASE}/nope/1",
        f"{BASE}/proficiencies",
    ):
        response = local.get(path)
        assert response.status_code == 404, path
        assert response.json() == {"error": "Not found."}, path


# --- Review Focus 1: monsters ------------------------------------------------------------------------------------


def test_a_player_never_meets_a_monster(app, local, storage, tuesday, ana):
    """By the section, a pasted address, its rows and filters, its facets, a section count, the search, and an item
    whose text names a monster: a player meets none, and every refusal is the unknown id's 404, byte for byte."""
    _, player = ana
    minotaur = monster_id(local)
    choose(storage, tuesday, item_rule(storage))
    unknown = player.get(f"{BASE}/spells/999999")
    assert unknown.status_code == 404
    for path in (
        f"{BASE}/monsters",
        f"{BASE}/monsters?q=minotaur",
        f"{BASE}/monsters?size=M",
        f"{BASE}/monsters?limit=1&offset=0",
        f"{BASE}/monsters/{minotaur}",
        f"{BASE}/monsters/999999",
        f"{BASE}/monsters/abc",
    ):
        refused = player.get(path)
        assert refused.status_code == 404, path
        assert refused.content == unknown.content, path
        assert refused.headers["content-type"] == unknown.headers["content-type"], path

    sections = player.get(BASE).json()["sections"]
    assert "monsters" not in [s["key"] for s in sections]
    owners = {s["key"]: s["count"] for s in local.get(f"{BASE}?campaign={tuesday}").json()["sections"]}
    assert {s["key"]: s["count"] for s in sections} == {k: n for k, n in owners.items() if k != "monsters"}, (
        "no other section's count holds the monsters"
    )

    for q in ("minotaur", "goblin", "bat", "brownie", "Minotaur-bane", "a"):
        results = player.get(f"{BASE}/search?q={q}&limit=200").json()["results"]
        assert all(hit["section"] != "monsters" for hit in results), q
    assert player.get(f"{BASE}/search?q=minotaur").json()["results"] == [
        {
            "section": "items",
            "id": player.get(f"{BASE}/items?q=Minotaur").json()["rows"][0]["id"],
            "name": "Minotaur-bane",
        }
    ]

    rows = player.get(f"{BASE}/items?q=minotaur").json()["rows"]
    (bane,) = rows
    entry = player.get(f"{BASE}/items/{bane['id']}").json()
    assert entry["text"] == CUT_BODY and SECRET not in json.dumps(entry)
    assert all("monster" not in json.dumps(v) for v in entry["fields"].values())

    for path in (
        BASE,
        f"{BASE}/spells",
        f"{BASE}/items",
        f"{BASE}/classes",
        f"{BASE}/abilities",
        f"{BASE}/proficiencies",
        f"{BASE}/turning",
        f"{BASE}/search?q=goblin",
    ):
        assert "monsters" not in json.dumps(player.get(path).json()), path


def test_the_owner_and_an_organiser_seat_meet_the_monsters(app, local, storage, tuesday):
    minotaur = monster_id(local)
    _, organiser = seat_client(app, storage, tuesday, "Oz", organiser=True)
    with organiser:
        for client in (local, organiser):
            assert "monsters" in [s["key"] for s in client.get(BASE).json()["sections"]]
            listed = client.get(f"{BASE}/monsters?q=minotaur").json()
            assert listed["kind"] == "list" and [r["id"] for r in listed["rows"]] == [minotaur]
            assert {f["key"] for f in listed["facets"]} >= {"size", "alignment"}
            assert client.get(f"{BASE}/monsters/{minotaur}").json()["name"] == "Minotaur"
            hits = client.get(f"{BASE}/search?q=minotaur").json()["results"]
            assert {"section": "monsters", "id": minotaur, "name": "Minotaur"} in hits


# --- house rules ---------------------------------------------------------------------------------------------------


def test_a_seat_reads_its_campaigns_homebrew(app, local, storage, tuesday, ana):
    """The seat's campaign's item rule is listed, with its DM notes cut; `?campaign=<another>` changes nothing."""
    _, player = ana
    other = campaign(local, crypt_module(local, title="Other")["id"], name="Other")["id"]
    bane = item_rule(storage)
    choose(storage, tuesday, bane)
    choose(storage, other, item_rule(storage, title="Elsewhere blade"))

    for path in (f"{BASE}/items", f"{BASE}/items?campaign={other}"):
        listed = player.get(path).json()
        assert listed["rows"][0] == {
            "id": f"hr-{bane.id}",
            "name": "Minotaur-bane",
            "item_type": "",
            "cost": "",
            "weight": "",
            "house_rule": True,
        }, path
        assert "Elsewhere blade" not in json.dumps(listed), path
    assert player.get(f"{BASE}?campaign={other}").json()["campaign_id"] == tuesday
    entry = player.get(f"{BASE}/items/hr-{bane.id}?campaign={other}").json()
    assert entry == {
        "section": "items",
        "id": f"hr-{bane.id}",
        "name": "Minotaur-bane",
        "fields": {},
        "text": CUT_BODY,
        "table": None,
        "house_rule": True,
    }
    assert local.get(f"{BASE}/items/hr-{bane.id}?campaign={tuesday}").json()["text"] == ITEM_BODY


def test_an_organiser_picks_a_campaign(local, storage, tuesday):
    bane = item_rule(storage)
    choose(storage, tuesday, bane)
    assert all(not row["house_rule"] for row in local.get(f"{BASE}/items").json()["rows"])
    assert local.get(f"{BASE}/items/hr-{bane.id}").status_code == 404
    picked = local.get(f"{BASE}/items?campaign={tuesday}").json()
    assert picked["rows"][0]["id"] == f"hr-{bane.id}"
    assert local.get(f"{BASE}?campaign={tuesday}").json()["campaign_id"] == tuesday
    assert local.get(f"{BASE}/items?campaign=cmp_nope").status_code == 404


def test_races_appear_with_a_race_rule(local, storage, tuesday):
    race = storage.house_rules.create(title="Lizardfolk", body_md="Scaled.", kind="race", phases=["always"])
    choose(storage, tuesday, race)
    assert local.get(f"{BASE}/races").status_code == 404
    sections = [s["key"] for s in local.get(f"{BASE}?campaign={tuesday}").json()["sections"]]
    assert sections.index("races") == sections.index("classes") + 1
    races = local.get(f"{BASE}/races?campaign={tuesday}").json()
    assert races["kind"] == "list" and races["facets"] == [] and races["total"] == 1
    assert local.get(f"{BASE}/races/hr-{race.id}?campaign={tuesday}").json()["name"] == "Lizardfolk"


# --- seats ---------------------------------------------------------------------------------------------------------


def test_a_seat_that_left_is_refused(app, storage, tuesday, ana):
    seat, player = ana
    seats.leave(storage, seat)
    for path in (BASE, f"{BASE}/spells", f"{BASE}/spells/1", f"{BASE}/search?q=web", "/api/rulesets"):
        response = player.get(path)
        assert response.status_code == 403, path
        assert response.json() == {"error": "You have left this table."}, path


def test_nobody_is_refused(lan):
    assert lan.get(BASE).status_code == 401


# --- lists and tables ------------------------------------------------------------------------------------------------


def test_filters_and_paging(local):
    everything = local.get(f"{BASE}/spells?school=necromancy").json()
    total = everything["total"]
    assert total > 2 and everything["offset"] == 0
    assert all("necromancy" in r["school"] for r in everything["rows"])
    page = local.get(f"{BASE}/spells?school=necromancy&limit=1&offset=1").json()
    assert page["kind"] == "list" and page["total"] == total and page["offset"] == 1
    assert page["rows"] == everything["rows"][1:2]
    school = next(f for f in page["facets"] if f["key"] == "school")
    assert {"value": "necromancy", "count": total} in school["options"]
    assert set(page["rows"][0]) == {"id", "name", "caster", "level", "school", "house_rule"}


def test_limit_is_clamped_and_bad_numbers_fall_back(local):
    assert len(local.get(f"{BASE}/spells?limit=0").json()["rows"]) == 1
    assert len(local.get(f"{BASE}/spells?limit=9999").json()["rows"]) == PAGE_LIMIT
    fallback = local.get(f"{BASE}/spells?limit=abc&offset=-3").json()
    assert fallback["offset"] == 0 and fallback["rows"] == local.get(f"{BASE}/spells").json()["rows"]


HUGE = "9" * 25


@pytest.mark.parametrize(
    "path",
    [
        f"{BASE}/spells?offset={HUGE}",
        f"{BASE}/spells?limit={HUGE}",
        f"{BASE}/spells?level={HUGE}",
        f"{BASE}/spells?offset={'9' * 5000}",
        f"{BASE}/items?offset={HUGE}",
        f"{BASE}/spells/{HUGE}",
        f"{BASE}/items/{HUGE}",
        f"{BASE}/classes/{HUGE}",
        f"{BASE}/monsters/{HUGE}",
        f"{BASE}/spells/{2**63}",
        f"{BASE}/spells/\u00b2",
    ],
)
def test_huge_numbers_answer_json(local, path):
    response = local.get(path)
    assert response.status_code in (200, 404), response.text
    assert response.headers["content-type"] == "application/json"
    assert response.json()


def test_a_spell_level_outside_one_to_nine_matches_nothing(local):
    for level in ("0", "10", HUGE):
        body = local.get(f"{BASE}/spells?level={level}").json()
        assert (body["total"], body["rows"]) == (0, []), level
    assert local.get(f"{BASE}/spells?level=1").json()["total"] > 0
    assert local.get(f"{BASE}/spells?offset={HUGE}").json()["rows"] == []


def test_an_unknown_filter_is_ignored(local, storage, tuesday):
    choose(storage, tuesday, item_rule(storage))
    listed = local.get(f"{BASE}/items?campaign={tuesday}&colour=red").json()
    assert listed["rows"][0]["house_rule"] is True


def test_tables(local):
    for section in ("abilities", "turning"):
        body = local.get(f"{BASE}/{section}").json()
        assert body["kind"] == "table" and body["table"], section
        assert set(body) == {"kind", "table"}, section
    assert local.get(f"{BASE}/abilities").json()["table"][0]["key"] == "strength"


def test_a_spells_entry(local):
    (web,) = [row for row in local.get(f"{BASE}/spells?q=Web").json()["rows"] if row["name"] == "Web"]
    entry = local.get(f"{BASE}/spells/{web['id']}").json()
    assert set(entry) == {"section", "id", "name", "fields", "text", "table", "house_rule"}
    assert entry["name"] == "Web" and entry["fields"]["school"] == web["school"] and entry["house_rule"] is False


def test_the_search(local):
    assert local.get(f"{BASE}/search?q=").json() == {"results": []}
    assert local.get(f"{BASE}/search").json() == {"results": []}
    hits = local.get(f"{BASE}/search?q=light&limit=2").json()["results"]
    assert len(hits) == 2 and all(set(hit) == {"section", "id", "name"} for hit in hits)
