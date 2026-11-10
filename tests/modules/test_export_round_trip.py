""".dscn version 2 (and later) and the whole-module export (plan 3 Task 2): an asset has a `description`, and a module exports with
its text, keys, entities, attachments, maps and metadata, so that importing the export gives the same module."""

import base64
from dataclasses import replace

import pytest

from delve.config import Config
from delve.domain.modules import ModuleMap
from delve.modules.dscn import VERSION, Bundle, check
from delve.modules.exporter import export_module
from delve.modules.importer import STRUCTURAL, import_bundle
from delve.modules.source import Attachment, ModuleSource, TextDoc, derive, from_bundle, load_source
from delve.storage import open_storage
from tests.fixtures import SAMPLES

CRYPT = SAMPLES / "scenarios" / "crypt-of-saint-vellis"
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


@pytest.fixture
def storage(tmp_path):
    opened = open_storage(Config(data_dir=tmp_path / "data"))
    yield opened
    opened.close()


def errors(bundle: Bundle) -> list[str]:
    return [str(d) for d in check(bundle).diagnostics if d.severity == "error"]


def test_export_is_the_whole_module(storage):
    module = import_bundle(storage, Bundle.load(CRYPT).to_zip()).module
    source = load_source(storage, module.id)
    bundle = Bundle.load(export_module(storage, module.id).to_zip())

    assert errors(bundle) == []
    assert bundle.manifest["version"] == VERSION == 3
    exported = from_bundle(bundle)
    assert exported.texts == source.texts
    assert exported.entities == source.entities
    assert exported.keys == source.keys
    assert exported.attachments == source.attachments
    assert [t["file"] for t in bundle.entries("text")] == ["text/intro.md", "text/crypt-key.md"]
    assert [(m["name"], m.get("role", "map"), bool(m.get("default"))) for m in bundle.maps()] == [
        (m.name, m.role, m.is_default) for m in module.maps
    ]
    assert all(bundle.map_source(m.name) == m.source for m in module.maps)
    metadata = {key: value for key, value in bundle.manifest.items() if key not in STRUCTURAL}
    assert metadata == module.metadata
    assert metadata["cover"] == "asset:ritualist-token"
    for attachment in source.attachments:
        entry = bundle.asset_entry(attachment.id)
        assert entry["file"] == f"assets/{attachment.id}.png"
        assert entry["description"] == attachment.description
        assert bundle.read(entry["file"]) == storage.blobs.get(attachment.sha256)


def test_import_export_import_is_stable(storage):
    first = import_bundle(storage, Bundle.load(CRYPT).to_zip()).module
    once = export_module(storage, first.id).to_zip()
    second = import_bundle(storage, once).module
    twice = export_module(storage, second.id).to_zip()
    assert from_bundle(Bundle.load(once)) == from_bundle(Bundle.load(twice))
    assert once == twice


def test_v1_caption_becomes_the_description():
    bundle = Bundle.load(CRYPT)
    assert bundle.manifest["version"] == 1
    assert "description" not in bundle.asset_entry("ritualist-token")
    assert errors(bundle) == []
    assert from_bundle(bundle).attachment("ritualist-token").description == "Cult ritualist token"


def test_an_asset_without_description_is_refused_from_version_2():
    bundle = Bundle.new("Pictures")
    assert bundle.manifest["version"] == 3
    bundle.add_asset("dot", PNG, "image/png", caption="A dot")
    found = [d for d in check(bundle).diagnostics if d.code == "asset-description"]
    assert [(d.severity, d.path) for d in found] == [("error", "scenario.json")]
    bundle.add_asset("dot", PNG, "image/png", description="")
    assert not [d for d in check(bundle).diagnostics if d.code == "asset-description"]
    bundle.add_asset("pdf", b"%PDF-1.4 x", "application/pdf", role="source")
    assert not [d for d in check(bundle).diagnostics if d.code == "asset-description"]


def test_export_maps_dm_audience_back_to_gm(storage):
    module = storage.modules.create("Secrets")
    sha = storage.blobs.put(PNG, "image/png")
    storage.blobs.link(module.id, "attachment", sha)
    storage.module_sources.put(
        module.id,
        ModuleSource(
            texts=[
                TextDoc("notes", "Notes", "gm", None, "The DM's notes.\n"),
                TextDoc("letter", "A letter", "player", None, "Dear friends,\n"),
            ],
            entities={"npcs": [{"id": "brokk", "name": "Brokk", "audience": "gm"}]},
            attachments=[
                Attachment("plan", "image/png", sha, len(PNG), "The DM's plan.", "gm"),
                Attachment("dot", "image/png", sha, len(PNG), "A dot the players see.", "player"),
            ],
        ),
    )
    bundle = Bundle.load(export_module(storage, module.id).to_zip())
    assert errors(bundle) == []
    assert [(t["id"], t["audience"]) for t in bundle.entries("text")] == [("notes", "gm"), ("letter", "player")]
    assert [(a["id"], a["audience"]) for a in bundle.entries("assets")] == [("plan", "gm"), ("dot", "player")]
    assert bundle.entities("npcs") == [{"id": "brokk", "name": "Brokk", "audience": "gm"}]
    assert [(a.id, a.audience) for a in from_bundle(bundle).attachments] == [("plan", "gm"), ("dot", "player")]


def test_export_of_a_map_only_module(storage):
    module = storage.modules.create("Just a map")
    bundle = Bundle.load(export_module(storage, module.id).to_zip())
    assert errors(bundle) == []
    assert from_bundle(bundle) == ModuleSource()


ROOMS = (
    'map "Gatehouse" {\n  grid { bounds 30 x 10 }\n}\n\n'
    'room "gate" {\n  rect 1,1 4 x 4\n  label "The Gate"\n}\n\n'
    'room "hall" {\n  rect 10,1 4 x 4\n  label "The Hall"\n}\n'
)


def test_headings_that_link_themselves_export_as_keys(storage):
    """In the bundle `keys[]` is the only source of truth (format §5.3), so a heading that links itself to its room in
    Delve is written as a key, and a `key:` ref to it resolves on import."""
    module = storage.modules.create("Gatehouse")
    storage.modules.put_map(module.id, ModuleMap("map", "map", ROOMS, True))
    markdown = "## 1. The Gate\n\nA gate.\n\n## 2. The Hall\n\nA hall.\n"
    rats = {"id": "rats", "name": "Rats", "key": "key:2", "fixed": [{"count": "2d4", "creature": "monster:rat"}]}
    storage.module_sources.put(
        module.id, ModuleSource(texts=[TextDoc("key", "Key", "gm", "map", markdown)], entities={"encounters": [rats]})
    )
    bundle = Bundle.load(export_module(storage, module.id).to_zip())
    assert errors(bundle) == []
    assert bundle.manifest["keys"] == [
        {"key": "1", "title": "The Gate", "node": "map:map#room.gate", "text": "text:key#1"},
        {"key": "2", "title": "The Hall", "node": "map:map#room.hall", "text": "text:key#2"},
    ]
    again = import_bundle(storage, bundle.to_zip()).module
    assert load_source(storage, again.id).keys == bundle.manifest["keys"]


def test_a_new_modules_untouched_empty_map_is_left_out(storage):
    """"New module" makes an empty default map. A module written as text only exports without it, and its export
    imports back (our own import refused the empty map with `map-parse`)."""
    from delve.modules.source import save_source

    module = storage.modules.create("Rumours of Hommlet")
    storage.modules.put_map(module.id, ModuleMap("map", "map", "", True))
    text = TextDoc("rumours", "Rumours", "player", "map", "# Rumours\n\nThe moathouse is haunted.\n")
    save_source(storage, module.id, ModuleSource(texts=[text], entities={}, keys=[], attachments=[]))

    bundle = export_module(storage, module.id)
    assert errors(bundle) == []
    assert bundle.maps() == [] and "map" not in bundle.text_entry("rumours")
    again = import_bundle(storage, bundle.to_zip()).module
    assert [doc.markdown for doc in load_source(storage, again.id).texts] == [text.markdown]


def test_an_export_leaves_out_a_source_attachment(storage):
    """A `source` asset, such as the original PDF of a conversion, is opt-in on export (format R8): the export leaves
    it out, and keeps the other attachments."""
    module = storage.modules.create("From a book")
    pdf = b"%PDF-1.4 the book"
    picture = Attachment("page-2", "image/png", storage.blobs.put(PNG, "image/png"), len(PNG), "Page 2", "gm")
    original = Attachment(
        "source-pdf", "application/pdf", storage.blobs.put(pdf, "application/pdf"), len(pdf), "The original PDF", "gm",
        "source",
    )  # fmt: skip
    storage.module_sources.put(module.id, ModuleSource(attachments=[picture, original]))

    bundle = Bundle.load(export_module(storage, module.id).to_zip())

    assert errors(bundle) == []
    assert [a["id"] for a in bundle.entries("assets")] == ["page-2"]
    assert from_bundle(bundle).attachments == [picture]


def test_an_assets_role_is_carried_into_the_source():
    bundle = Bundle.new("Published")
    bundle.add_asset("book", b"%PDF-1.4 the book", "application/pdf", role="source")
    bundle.add_asset("plate", PNG, "image/png", description="A plate")
    attachments = {a.id: a.role for a in from_bundle(bundle).attachments}
    assert attachments == {"book": "source", "plate": "attachment"}
    assert Attachment("x", "image/png", "ab", 1, "", "gm").role == "attachment"


def test_a_key_without_a_node_exports_with_its_room(storage):
    """A keyed entity's entry (walkthrough fixes Task 3) has no `node` until the map is drawn; the export fills it in,
    once, and importing the export gives the same keys again."""
    module = storage.modules.create("Gatehouse")
    storage.modules.put_map(module.id, ModuleMap("map", "map", ROOMS, True))
    markdown = "## 1. The Gate {#1}\n\nA gate.\n\n## 2. The Hall {#2}\n\nA hall.\n"
    rats = {"id": "rats", "name": "Rats", "key": "key:2"}
    entry = {"key": "2", "title": "The Hall", "text": "text:key#2", "npcs": [], "encounter": "encounter:rats"}
    storage.module_sources.put(
        module.id,
        ModuleSource(texts=[TextDoc("key", "Key", "gm", "map", markdown)], entities={"encounters": [rats]}, keys=[entry]),
    )

    bundle = Bundle.load(export_module(storage, module.id).to_zip())

    assert errors(bundle) == []
    assert bundle.manifest["keys"] == [
        {"key": "2", "title": "The Hall", "text": "text:key#2", "npcs": [], "encounter": "encounter:rats",
         "node": "map:map#room.hall"},
        {"key": "1", "title": "The Gate", "node": "map:map#room.gate", "text": "text:key#1"},
    ]
    again = import_bundle(storage, bundle.to_zip()).module
    assert load_source(storage, again.id).keys == bundle.manifest["keys"]
    assert Bundle.load(export_module(storage, again.id).to_zip()).manifest["keys"] == bundle.manifest["keys"]


HOUSE = 'map "House" {\n  grid { bounds 30 x 10 }\n}\n\nroom "r7" {\n  rect 1,1 4 x 4\n  label "7. Kitchen"\n}\n'
SHIP = 'map "Ship" {\n  grid { bounds 30 x 10 }\n}\n\nroom "r7" {\n  rect 1,1 4 x 4\n  label "7. Hold"\n}\n'


def two_parts(storage, keys: list[dict]) -> str:
    """A module of a house and a ship, each with its own map and its own room 7."""
    module = storage.modules.create("Saltmarsh")
    storage.modules.put_map(module.id, ModuleMap("house", "map", HOUSE, True))
    storage.modules.put_map(module.id, ModuleMap("ship", "map", SHIP, False))
    texts = [
        TextDoc("house", "Part One — The Haunted House", "gm", "house", "## 7. Kitchen\n\nPots.\n"),
        TextDoc("ship", "Part Two — The Sea Ghost Ship", "gm", "ship", "## 7. Hold\n\nCrates.\n"),
    ]
    cook = {"id": "cook", "name": "The cook"}
    storage.module_sources.put(module.id, ModuleSource(texts=texts, entities={"npcs": [cook]}, keys=keys))
    return module.id


def test_two_parts_that_share_a_key_export_validly_and_round_trip(storage):
    """Faithful modules Task 8: a key two parts share is written `<part>-<n>`, so `keys[].key` stays unique."""
    bundle = Bundle.load(export_module(storage, two_parts(storage, [])).to_zip())

    assert errors(bundle) == []
    assert [(k["key"], k["text"], k["node"]) for k in bundle.manifest["keys"]] == [
        ("haunted-house-7", "text:house#7", "map:house#room.r7"),
        ("sea-ghost-ship-7", "text:ship#7", "map:ship#room.r7"),
    ]
    again = import_bundle(storage, bundle.to_zip()).module
    assert load_source(storage, again.id).keys == bundle.manifest["keys"]
    assert Bundle.load(export_module(storage, again.id).to_zip()).manifest["keys"] == bundle.manifest["keys"]
    keys = derive(load_source(storage, again.id), again.maps).text.keys
    assert [(k.key, k.part) for k in keys] == [("haunted-house-7", "haunted-house"), ("sea-ghost-ship-7", "sea-ghost-ship")]


def test_bare_duplicate_keys_of_an_older_conversion_export_validly(storage):
    entries = [
        {"key": "7", "title": "Kitchen", "text": "text:house#7", "npcs": ["npc:cook"]},
        {"key": "7", "title": "Hold", "text": "text:ship#7", "npcs": []},
    ]
    bundle = Bundle.load(export_module(storage, two_parts(storage, entries)).to_zip())

    assert errors(bundle) == []
    assert bundle.manifest["keys"] == [
        {"key": "haunted-house-7", "title": "Kitchen", "text": "text:house#7", "npcs": ["npc:cook"],
         "node": "map:house#room.r7"},
        {"key": "sea-ghost-ship-7", "title": "Hold", "text": "text:ship#7", "npcs": [], "node": "map:ship#room.r7"},
    ]  # fmt: skip


PREGENS = [
    {"id": "ned", "name": "Ned Shakeshaft", "audience": "player", "race": "human", "class": "thief", "level": 3,
     "alignment": "CN", "gear": ["short sword"], "background": "A rogue.",
     "stats": {"adnd2e": {"ability_scores": {"str": 11, "dex": 17}, "hp_max": 12}}},
    {"id": "ilsa", "name": "Ilsa", "audience": "gm", "race": "½E", "class": "fighter/mage", "level": "3/3"},
]  # fmt: skip


def test_pregens_round_trip_through_import_and_export(storage):
    """Pregens (faithful modules Task 16) are a section of the format: import, export and import give them back."""
    bundle = Bundle.load(CRYPT)
    bundle.set_entities("pregens", PREGENS)
    assert errors(bundle) == []
    first = import_bundle(storage, bundle.to_zip()).module
    assert load_source(storage, first.id).entities["pregens"] == PREGENS
    once = export_module(storage, first.id).to_zip()
    assert errors(Bundle.load(once)) == []
    assert Bundle.load(once).entities("pregens") == PREGENS
    second = import_bundle(storage, once).module
    assert load_source(storage, second.id).entities["pregens"] == PREGENS
    assert export_module(storage, second.id).to_zip() == once


def test_a_pregen_without_an_audience_is_for_the_players():
    bundle = Bundle.new("Pregens")
    bundle.set_entities("pregens", [{"id": "ned", "name": "Ned"}])
    assert from_bundle(bundle).entities["pregens"] == [{"id": "ned", "name": "Ned", "audience": "player"}]


def test_a_missing_pregen_is_a_missing_entity():
    source = ModuleSource(
        entities={"pregens": [PREGENS[0]]},
        keys=[{"key": "1", "npcs": ["pregen:ned"]}, {"key": "2", "npcs": ["pregen:nobody"]}],
    )
    warnings = [(w.code, w.ref) for w in derive(source, []).warnings if w.code == "missing-entity"]
    assert warnings == [("missing-entity", "pregen:nobody")]


def test_an_encounter_at_a_heading_with_no_room_exports_its_key(storage):
    """Where offers every keyed heading (faithful modules Task 15). An encounter placed at one that has neither a room
    nor an entry gets a key without a node in the export, so its `key:` ref resolves and the export imports."""
    module = storage.modules.create("Saltmarsh")
    storage.modules.put_map(module.id, ModuleMap("house", "map", HOUSE, True))
    markdown = "## 7. Kitchen\n\nPots.\n\n## 19. Cellar Stair\n\nSteps.\n\n## 20. Cellar\n\nDamp.\n"
    texts = [TextDoc("house", "Part One — The Haunted House", "gm", "house", markdown)]
    rats = {"id": "rats", "name": "Rats", "key": "key:19"}
    storage.module_sources.put(module.id, ModuleSource(texts=texts, entities={"encounters": [rats]}))

    bundle = Bundle.load(export_module(storage, module.id).to_zip())

    assert errors(bundle) == []
    assert bundle.manifest["keys"] == [
        {"key": "7", "title": "Kitchen", "node": "map:house#room.r7", "text": "text:house#7"},
        {"key": "19", "title": "Cellar Stair", "text": "text:house#19"},
    ]
    again = import_bundle(storage, bundle.to_zip()).module
    assert Bundle.load(export_module(storage, again.id).to_zip()).manifest["keys"] == bundle.manifest["keys"]


def _with_encounters(storage, module_id: str, *encounters: dict) -> None:
    source = load_source(storage, module_id)
    storage.module_sources.put(module_id, replace(source, entities={**source.entities, "encounters": list(encounters)}))


def test_a_bare_key_ref_two_parts_share_exports_validly(storage):
    """Final review fix 1: `key:7` where the export writes `haunted-house-7` and `sea-ghost-ship-7`. The record's own
    text decides which 7 it is; one that names no text is either, and the export drops its `key`."""
    module_id = two_parts(storage, [])
    rats = {"id": "rats", "name": "Rats", "key": "key:7", "description": "In [the hold](text:ship#7)."}
    cook = {"id": "cook-fight", "name": "The cook", "key": "key:7"}
    _with_encounters(storage, module_id, rats, cook)

    bundle = Bundle.load(export_module(storage, module_id).to_zip())

    assert errors(bundle) == []
    assert [e.get("key") for e in bundle.entities("encounters")] == ["key:sea-ghost-ship-7", None]
    assert load_source(storage, module_id).entities["encounters"] == [rats, cook]  # the source stays as it is


def test_a_bare_key_ref_of_an_older_conversion_exports_validly(storage):
    """The older conversion's bare duplicate entries, scoped by the export, and an encounter at `key:7`."""
    entries = [
        {"key": "7", "title": "Kitchen", "text": "text:house#7", "npcs": ["npc:cook"]},
        {"key": "7", "title": "Hold", "text": "text:ship#7", "npcs": []},
    ]
    module_id = two_parts(storage, entries)
    _with_encounters(storage, module_id, {"id": "rats", "name": "Rats", "key": "key:7"})

    bundle = Bundle.load(export_module(storage, module_id).to_zip())

    assert errors(bundle) == []
    assert [k["key"] for k in bundle.manifest["keys"]] == ["haunted-house-7", "sea-ghost-ship-7"]


def test_a_key_ref_no_key_is_written_as_is_a_warning(storage):
    """A `key:` ref that names no key as the export writes it is a `missing-key` warning in the editor; a scoped key,
    and a heading's key with no room, are there."""
    module_id = two_parts(storage, [])
    module = storage.modules.get(module_id)
    _with_encounters(
        storage,
        module_id,
        {"id": "rats", "name": "Rats", "key": "key:7"},
        {"id": "crabs", "name": "Crabs", "key": "key:sea-ghost-ship-7"},
        {"id": "eels", "name": "Eels", "key": "key:99"},
    )

    warnings = [(w.code, w.ref) for w in derive(load_source(storage, module_id), module.maps).warnings]

    assert [w for w in warnings if w[0] == "missing-key"] == [("missing-key", "key:7"), ("missing-key", "key:99")]
