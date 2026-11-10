"""The module's text for the DM (plan 2b Task 1): `module_lookup` searches the campaign's pinned revision and
`module_key` gives a room's keyed text. Both are DM-only: module text is canon the players never read."""

import json

import pytest

from delve.dm.tools.redact import player_view
from delve.domain.modules import ModuleMap
from delve.modules.dscn import Bundle
from delve.modules.importer import import_bundle
from delve.modules.source import ModuleSource, TextDoc, save_source
from delve.modules.text import ModuleText, TextSection
from tests.dm.tools.conftest import GARREK, SECRET
from tests.fixtures import SAMPLES

CRYPT = SAMPLES / "scenarios" / "crypt-of-saint-vellis"


@pytest.fixture
def crypt(storage):
    """The crypt sample, imported, with the secret planted in its keyed text of the vestry; a campaign on it."""
    bundle = Bundle.load(CRYPT)
    key = bundle.text_entry("crypt-key")["file"]
    bundle.files[key] = bundle.read(key).replace(b"a purse of 40 gp.", f"a purse of 40 gp. {SECRET}".encode())
    module = import_bundle(storage, bundle.to_zip()).module
    revision = storage.revisions.snapshot(module.id)
    return storage.campaigns.create("Vellis", module.id, revision.number, ruleset="osric", setting="greyhawk")


@pytest.fixture
def ask(host, crypt):
    def run(tool, /, **args):
        return host.call(crypt.id, "beat-1", tool, args)

    return run


def test_module_lookup_searches_pinned_revision(storage, ask, crypt):
    """The search runs over the revision the campaign pinned, not the module's working copy."""
    found = ask("module_lookup", query="pressure plate")
    assert found["results"][0]["anchor"] == "crypt-key#c1"
    assert found["results"][0]["heading_path"] == ["Keyed encounters", "C1. Entry Hall"]
    assert "pressure plate" in found["results"][0]["snippet"]

    edited = ModuleText.from_json(storage.module_texts.get(crypt.module_id))
    edited.sections.append(TextSection("extra#cube", ["Extra", "Cube"], "A gelatinous cube.", "dm", None))
    storage.module_texts.put(crypt.module_id, edited.to_json())
    storage.revisions.snapshot(crypt.module_id)
    assert ask("module_lookup", query="gelatinous")["results"] == []

    in_vestry = ask("module_lookup", query="ritualist", section="C3")
    assert [r["anchor"] for r in in_vestry["results"]] == ["crypt-key#c3"]
    assert ask("module_lookup", query="ritualist", limit=1)["count"] == 1


def test_module_key_by_room(ask):
    """A room by its key, its node id, its bare name or its label on the map, as move_party takes it: the keyed
    text, the read-aloud, the NPCs and the encounter."""
    by_key = ask("module_key", room="C2")
    assert (by_key["key"], by_key["title"], by_key["map"], by_key["node"]) == (
        "C2",
        "Throne Chamber",
        "crypt",
        "room.throne_chamber",
    )
    assert by_key["read_aloud"].startswith("A hexagonal hall.")
    assert "two rounds from finishing" in by_key["dm_text"]
    assert [npc["id"] for npc in by_key["npcs"]] == ["ritualist"]
    assert by_key["npcs"][0]["stats"]["adnd2e"]["hp"] == 18
    assert by_key["encounter"]["name"] == "The risen saint"
    assert by_key["assets"] == ["asset:ritualist-token"]
    for room in ("room.throne_chamber", "throne_chamber", "Throne Room", "c2"):
        assert ask("module_key", room=room)["key"] == "C2", room
    vestry = ask("module_key", room="Vestry")
    assert vestry["key"] == "C3" and vestry["read_aloud"] == "" and SECRET in vestry["dm_text"]
    unknown = ask("module_key", room="Kitchen")
    assert unknown["error"].startswith("No room 'Kitchen'") and unknown["candidates"]


def test_a_room_with_two_encounters_lists_both(host, storage):
    """Plateau 7 Task 20: `encounters` is every encounter whose record's `key` names the room, the one `keys[]` names
    first; `encounter` stays that first one."""
    bundle = Bundle.load(CRYPT)
    encounters = "entities/encounters.yaml"
    guards = "- id: c2-guards\n  name: The saint's guards\n  key: key:C2\n  fixed:\n  - count: 2\n    creature: monster:skeleton\n"
    bundle.files[encounters] = guards.encode() + bundle.read(encounters)
    module = import_bundle(storage, bundle.to_zip()).module
    campaign = storage.campaigns.create(
        "Vellis", module.id, storage.revisions.snapshot(module.id).number, ruleset="osric", setting="greyhawk"
    )

    c2 = host.call(campaign.id, "beat-1", "module_key", {"room": "C2"})

    assert [e["id"] for e in c2["encounters"]] == ["c2-saint", "c2-guards"]
    assert c2["encounter"]["id"] == "c2-saint"
    assert host.call(campaign.id, "beat-1", "module_key", {"room": "C3"})["encounters"] == []


def test_module_key_on_the_partys_map(ask):
    assert "error" not in ask("create_character", name="Garrek", sheet=GARREK)
    assert "error" not in ask("move_party", to="Entry Hall")
    assert ask("module_key", room="Entry Hall")["key"] == "C1"


def test_module_tools_are_dm_only(host, ask):
    """Neither tool has a view for the players: their results reach no feed, whatever they hold."""
    for name, args in (("module_lookup", {"query": "purse"}), ("module_key", {"room": "C3"})):
        spec = host.spec(name)
        assert not spec.player_visible and not spec.mutates
        result = ask(name, **args)
        assert SECRET in json.dumps(result), name
        assert player_view(spec, args, result) is None


def test_map_only_module_answers_no_text(call):
    """The 2a campaign fixture is a module of one map: no text, no keys."""
    assert call("module_lookup", query="crypt") == {"error": "this module has no text"}
    assert call("module_key", room="Entry Hall") == {"error": "this module has no text"}


HOUSE_MAP = (
    'map "House" {\n  grid { bounds 30 x 10 }\n}\n\nroom "r7" {\n  rect 1,1 4 x 4\n  label "7. Kitchen"\n}\n'
    'room "r22" {\n  rect 10,1 4 x 4\n  label "22. Attic"\n}\n'
)
SHIP_MAP = 'map "Ship" {\n  grid { bounds 30 x 10 }\n}\n\nroom "r7" {\n  rect 1,1 4 x 4\n  label "7. Hold"\n}\n'


@pytest.fixture
def saltmarsh(host, storage):
    """Faithful modules Task 8: a house and a ship, each keyed from its own 7, and a 22 only the house has."""
    return play_saltmarsh(host, storage)


def play_saltmarsh(host, storage, entities=None):
    module = storage.modules.create("Saltmarsh")
    storage.modules.put_map(module.id, ModuleMap("house", "map", HOUSE_MAP, True))
    storage.modules.put_map(module.id, ModuleMap("ship", "map", SHIP_MAP, False))
    texts = [
        TextDoc(
            "house",
            "Part One — The Haunted House",
            "gm",
            "house",
            "## 7. Kitchen\n\nPots.\n\n## 22. Attic\n\n> Dust.\n\nA chest.\n\n> It scuttles.\n",
        ),
        TextDoc("the-sea-ghost", "Part Two — The Sea Ghost Ship", "gm", "ship", "## 7. Hold\n\nCrates.\n"),
    ]
    save_source(storage, module.id, ModuleSource(texts=texts, entities=entities or {}))
    campaign = storage.campaigns.create(
        "Saltmarsh", module.id, storage.revisions.snapshot(module.id).number, ruleset="osric", setting="greyhawk"
    )

    def run(**args):
        return host.call(campaign.id, "beat-1", "module_key", args)

    return run


def test_a_key_two_parts_share_needs_its_part(saltmarsh):
    refused = saltmarsh(room="7")
    assert refused["error"] == "The key '7' is in more than one part."
    assert "part=" in refused["hint"]
    assert [(c["key"], c["part"]) for c in refused["candidates"]] == [
        ("haunted-house-7", "haunted-house"),
        ("sea-ghost-ship-7", "sea-ghost-ship"),
    ]
    for args in (
        {"room": "7", "part": "ship"},
        {"room": "7", "part": "Sea-Ghost-Ship"},
        {"room": "7", "part": "the-sea-ghost"},
        {"room": "sea-ghost-ship-7"},
        {"room": "Sea-Ghost-Ship-7"},
    ):
        found = saltmarsh(**args)
        assert (found["key"], found["part"], found["map"], found["dm_text"]) == (
            "sea-ghost-ship-7",
            "sea-ghost-ship",
            "ship",
            "Crates.",
        ), args
    assert saltmarsh(room="7", part="house")["key"] == "haunted-house-7"
    assert saltmarsh(room="22")["key"] == "22"
    assert saltmarsh(room="22", part="ship")["error"].startswith("No room '22'")


def test_a_part_that_names_no_text_or_two_is_refused(saltmarsh):
    for part in ("castle", "part"):
        refused = saltmarsh(room="7", part=part)
        assert "part" in refused["error"], part
        assert sorted(c["part"] for c in refused["candidates"]) == ["haunted-house", "sea-ghost-ship"], part


def test_module_key_gives_every_boxed_text_of_the_room(saltmarsh):
    """Faithful modules Task 11: a quote after the DM text is read-aloud too, and not in the DM text."""
    attic = saltmarsh(room="22")
    assert (attic["read_aloud"], attic["dm_text"]) == ("Dust.\n\nIt scuttles.", "A chest.")


def test_an_encounter_at_a_printed_key_shows_in_its_own_part(host, storage):
    """Final review fix 1: an encounter of an older conversion keyed `key:7` belongs to the 7 of its own part, the
    part of the text its record names; one that names no text could be either 7, and shows in neither."""
    rats = {"id": "rats", "name": "Rats", "key": "key:7", "description": "In [the hold](text:the-sea-ghost#7)."}
    cook = {"id": "cook", "name": "The cook", "key": "key:7"}
    crabs = {"id": "crabs", "name": "Crabs", "key": "key:sea-ghost-ship-7"}
    saltmarsh = play_saltmarsh(host, storage, {"encounters": [rats, cook, crabs]})

    assert [e["id"] for e in saltmarsh(room="7", part="ship")["encounters"]] == ["rats", "crabs"]
    assert saltmarsh(room="7", part="house")["encounters"] == []


def test_a_shared_key_is_the_one_on_the_partys_map_and_a_part_by_its_start(host, storage, saltmarsh):
    """DEL-330: "key '2' is in more than one part" with the party standing on that part's map, and "No part 'kovel'"
    for kovel-mansion."""
    (campaign,) = [c for c in storage.campaigns.list() if c.name == "Saltmarsh"]
    host.call(campaign.id, "beat-1", "create_character", {"name": "Garrek", "sheet": {"cls": "Fighter", "hp_max": 9}})
    assert "error" not in host.call(campaign.id, "beat-1", "move_party", {"to": "r7", "map": "ship"})
    assert saltmarsh(room="7")["key"] == "sea-ghost-ship-7"
    assert saltmarsh(room="7", part="house")["key"] == "haunted-house-7"
    assert saltmarsh(room="7", part="sea")["key"] == "sea-ghost-ship-7"  # the part's start


def test_a_search_that_finds_nothing_falls_back_to_any_word(ask):
    """DEL-330: "the council's missions and their pay" found nothing in a Ruins evening; any of its words, and the
    headings naming one, to look under."""
    found = ask("module_lookup", query="the ritualist and his secret pact with demons")
    assert found["matched"] == "any word" and found["count"] >= 1
    assert any(r["anchor"] == "crypt-key#c3" for r in found["results"])
    headings = ask("module_lookup", query="vestry zzyzx")
    assert any("Vestry" in h for h in headings["headings"])
    assert ask("module_lookup", query="pressure plate").get("matched") is None, "every word found: as before"


def test_a_key_only_one_part_has_answers_to_its_part_too(saltmarsh):
    """DEL-330: Puppets' 8 and 10 are keyed "8" and "10" (no other part has them), and "introduction-8" was refused."""
    assert saltmarsh(room="haunted-house-22")["key"] == "22"
