"""The module source (plan 3 Task 1): one editable copy of a module's texts, entities, keys and attachments, from which
the DM's text, the room links and the editor's warnings are derived."""

import base64
from dataclasses import replace

import pytest

from delve.domain.modules import ModuleMap
from delve.modules.dscn import Bundle
from delve.modules.source import (
    PART_LENGTH,
    Attachment,
    Heading,
    Link,
    ModuleSource,
    TextDoc,
    Warning,
    derive,
    from_bundle,
    missing_refs,
    part_slug,
    scoped_entries,
    scoped_keys,
)
from delve.modules.text import Key, ModuleText
from tests.fixtures import SAMPLES

CRYPT = SAMPLES / "scenarios" / "crypt-of-saint-vellis"
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


@pytest.fixture
def crypt_bundle() -> Bundle:
    return Bundle.load(CRYPT)


def maps_of(bundle: Bundle) -> list[ModuleMap]:
    default = bundle.default_map()
    return [
        ModuleMap(
            entry["name"],
            "library" if entry.get("role") == "library" else "map",
            bundle.read_text(entry["file"]),
            default is not None and entry["name"] == default["name"],
        )
        for entry in bundle.maps()
    ]


def crypt_map() -> ModuleMap:
    return ModuleMap("crypt", "map", (CRYPT / "maps" / "crypt.dmap").read_text(), True)


def source_with(*texts: TextDoc, **parts) -> ModuleSource:
    return ModuleSource(
        texts=list(texts),
        entities=parts.get("entities", {}),
        keys=parts.get("keys", []),
        attachments=parts.get("attachments", []),
    )


def test_from_bundle_keeps_text_entities_keys_and_attachments(crypt_bundle):
    crypt_bundle.add_asset("dm-plan", PNG, "image/png", audience="gm", caption="The DM's plan of the crypt")
    source = from_bundle(crypt_bundle)

    assert [t.id for t in source.texts] == ["intro", "crypt-key"]
    for doc in source.texts:
        assert doc.markdown == crypt_bundle.read_text(crypt_bundle.text_entry(doc.id)["file"])
    intro, keyed = source.texts
    assert (intro.title, intro.audience, intro.map) == ("Introduction", "player", None)
    assert (keyed.title, keyed.audience, keyed.map) == ("Keyed encounters", "gm", "crypt")
    assert source.entities == {
        kind: crypt_bundle.entities(kind) for kind in ("npcs", "encounters", "rumors", "secrets")
    }
    assert source.keys == crypt_bundle.entries("keys")
    token = crypt_bundle.asset_entry("ritualist-token")
    assert source.attachments == [
        Attachment("ritualist-token", "image/png", token["sha256"], 79, "Cult ritualist token", "player"),
        Attachment(
            "dm-plan",
            "image/png",
            crypt_bundle.asset_entry("dm-plan")["sha256"],
            len(PNG),
            "The DM's plan of the crypt",
            "gm",
        ),
    ]
    assert source.attachment("dm-plan").audience == "gm"
    assert source.attachment("nothing") is None
    assert ModuleSource.from_json(source.to_json()) == source


def test_a_v2_description_wins_over_the_caption(crypt_bundle):
    crypt_bundle.add_asset("plan", PNG, "image/png", caption="old", description="The crypt from above.")
    assert from_bundle(crypt_bundle).attachment("plan").description == "The crypt from above."


def test_derive_reads_the_crypts_sections_keys_and_entities(crypt_bundle):
    derived = derive(from_bundle(crypt_bundle), maps_of(crypt_bundle))
    text = derived.text
    c1 = next(s for s in text.sections if s.anchor == "crypt-key#c1")
    assert c1.heading_path == ["Keyed encounters", "C1. Entry Hall"]
    assert c1.read_aloud.startswith("The crypt door grinds open")
    assert "pressure plate" in c1.markdown and "grinds open" not in c1.markdown
    assert c1.audience == "gm"
    intro = next(s for s in text.sections if s.anchor.startswith("intro#"))
    assert intro.audience == "player" and intro.read_aloud is None
    c2 = next(k for k in text.keys if k.key == "C2")
    assert replace(c2, part=None) == Key(
        key="C2",
        title="Throne Chamber",
        node="map:crypt#room.throne_chamber",
        text_anchor="crypt-key#c2",
        npcs=["npc:ritualist"],
        encounter="encounter:c2-saint",
        assets=["asset:ritualist-token"],
    )
    assert {kind: len(records) for kind, records in text.entities.items()} == {
        "npcs": 2,
        "encounters": 2,
        "rumors": 2,
        "secrets": 1,
    }
    assert ModuleText.from_json(text.to_json()) == text
    assert {k.part for k in text.keys} == {"keyed-encounters"}
    assert [(link.key, link.node, link.explicit) for link in derived.links] == [
        ("C1", "room.entry_hall", True),
        ("C2", "room.throne_chamber", True),
        ("C3", "room.vestry_alcove", True),
    ]
    assert [link.label for link in derived.links] == ["Entry Hall", "Throne Room", "Vestry"]
    assert not [w for w in derived.warnings if w.code in ("key-without-room", "missing-attachment", "missing-entity")]


def test_derive_parses_each_map_once_and_each_text_once(crypt_bundle, monkeypatch):
    """`derive` runs on every source read and save (DEL-166): its maps come from the one cache of parsed maps, so a
    second derive parses none, and each text's Markdown is parsed once per derive, not once per helper."""
    from delve.maps import sources
    from delve.modules import source as source_module
    from delve.modules import text as text_module

    sources.clear_cache()
    source, maps = from_bundle(crypt_bundle), maps_of(crypt_bundle)
    first = derive(source, maps)
    calls = {"map": 0, "markdown": 0}
    parse, parse_text = sources.parse, source_module.parse_text

    def counting_parse(*args, **kwargs):
        calls["map"] += 1
        return parse(*args, **kwargs)

    def counting_parse_text(*args, **kwargs):
        calls["markdown"] += 1
        return parse_text(*args, **kwargs)

    monkeypatch.setattr(sources, "parse", counting_parse)
    monkeypatch.setattr(source_module, "parse_text", counting_parse_text)
    monkeypatch.setattr(text_module, "parse_text", counting_parse_text)
    assert derive(source, maps) == first
    assert calls == {"map": 0, "markdown": len(source.texts)}
    sources.clear_cache()


def test_a_keyed_heading_links_itself_to_its_room():
    text = TextDoc("key", "Key", "gm", None, "## 2. Throne Room\n\nA throne of bones.\n")
    derived = derive(source_with(text), [crypt_map()])
    assert derived.links == [Link("key", "2", "2", "crypt", "room.throne_chamber", "Throne Room", False)]
    assert not [w for w in derived.warnings if w.code == "key-without-room"]
    linked = next(k for k in derived.text.keys if k.key == "2")
    assert (linked.node, linked.text_anchor) == ("map:crypt#room.throne_chamber", "key#2")


def test_a_text_links_to_its_own_map_before_the_default():
    other = ModuleMap(
        "other",
        "map",
        'map "Other" {\n  grid {\n    cell 32 px\n    bounds 10 x 10\n  }\n}\n'
        'room "vestry" {\n  rect 1,1 4 x 4\n  label "Vestry"\n}\n',
        False,
    )
    text = TextDoc("key", "Key", "gm", "other", "## 3. Vestry\n")
    derived = derive(source_with(text), [crypt_map(), other])
    assert [(link.map, link.node) for link in derived.links] == [("other", "room.vestry")]


def test_a_keyed_heading_links_to_the_room_labelled_like_the_whole_heading():
    """A sketched map (plan 5 Task 3) names its rooms `r<key>` and labels them `<key>. <name>`, as the heading."""
    sketched = ModuleMap(
        "sketch",
        "map",
        'map "Sketch" {\n  grid {\n    cell 32 px\n    bounds 20 x 10\n  }\n  room_numbers off\n}\n'
        'room "r1" {\n  rect 1,1 6 x 5\n  label "1. Entrance"\n}\n'
        'room "rC3" {\n  rect 7,1 6 x 5\n  label "C3. Guard Room"\n}\n',
        True,
    )
    text = TextDoc("key", "Key", "gm", None, "## 1. Entrance\n\nSteps.\n\n## C3. Guard Room\n\nBunks.\n")
    derived = derive(source_with(text), [sketched])
    assert [(link.anchor, link.node, link.label) for link in derived.links] == [
        ("1", "room.r1", "1. Entrance"),
        ("c3", "room.rC3", "C3. Guard Room"),
    ]
    assert not [w for w in derived.warnings if w.code in ("key-without-room", "room-without-text")]


def test_warnings_for_unlinked_rooms_keys_and_refs():
    text = TextDoc(
        "key",
        "Key",
        "gm",
        None,
        "## 2. Throne Room\n\n## 9. Nowhere\n\n![The plan](asset:gone) and [[npc:nobody]] meet [[npc:brokk]].\n",
    )
    source = source_with(text, entities={"npcs": [{"id": "brokk", "name": "Brokk"}]})
    warnings = derive(source, [crypt_map()]).warnings
    by_code = {code: [w.ref for w in warnings if w.code == code] for code in {w.code for w in warnings}}
    assert by_code["key-without-room"] == ["text:key#9"]
    assert by_code["missing-attachment"] == ["asset:gone"]
    assert by_code["missing-entity"] == ["npc:nobody"]
    assert "map:crypt#room.entry_hall" in by_code["room-without-text"]
    assert "map:crypt#room.throne_chamber" not in by_code["room-without-text"]
    assert all(isinstance(w, Warning) and w.message for w in warnings)
    missing = ("missing-attachment", "missing-entity", "missing-key")
    assert missing_refs(source) == [w for w in warnings if w.code in missing], "derive's, without a map (DEL-171)"


def test_refs_in_entities_and_keys_are_checked_too():
    source = source_with(
        entities={"encounters": [{"id": "e1", "name": "E", "fixed": [{"count": 1, "creature": "npc:ghost"}]}]},
        keys=[{"key": "X1", "assets": ["asset:art"], "encounter": "encounter:e2"}],
    )
    warnings = derive(source, []).warnings
    assert sorted((w.code, w.ref) for w in warnings) == [
        ("missing-attachment", "asset:art"),
        ("missing-entity", "encounter:e2"),
        ("missing-entity", "npc:ghost"),
    ]


def test_a_map_that_does_not_parse_links_nothing_and_warns_nothing():
    broken = ModuleMap("broken", "map", "map {{{ not a map", True)
    text = TextDoc("key", "Key", "gm", None, "## 2. Throne Room\n")
    derived = derive(source_with(text), [broken])
    assert derived.links == []
    assert derived.warnings == []


def test_a_key_without_a_node_leaves_its_heading_to_link_itself():
    """A converted book's entities are keyed before its map is sketched (walkthrough fixes Task 3): an entry without
    `node` doesn't claim its heading, which still links itself, and its one key carries the entry's NPCs and encounter.
    """
    text = TextDoc("key", "Key", "gm", None, "## 2. Throne Room {#2}\n\nA throne of bones.\n")
    entry = {"key": "2", "title": "Throne Room", "text": "text:key#2", "npcs": ["npc:brokk"], "encounter": "encounter:e"}
    entities = {"npcs": [{"id": "brokk", "name": "Brokk"}], "encounters": [{"id": "e", "name": "E"}]}

    derived = derive(source_with(text, keys=[entry], entities=entities), [crypt_map()])

    assert derived.links == [Link("key", "2", "2", "crypt", "room.throne_chamber", "Throne Room", False)]
    [key] = [k for k in derived.text.keys if k.key == "2"]
    assert (key.node, key.text_anchor, key.npcs, key.encounter) == (
        "map:crypt#room.throne_chamber",
        "key#2",
        ["npc:brokk"],
        "encounter:e",
    )
    assert not [w for w in derived.warnings if w.code in ("key-without-room", "missing-entity")]


def test_a_key_with_a_node_still_claims_its_heading():
    text = TextDoc("key", "Key", "gm", None, "## 2. Throne Room {#2}\n")
    entry = {"key": "2", "text": "text:key#2", "node": "map:crypt#room.vestry"}

    derived = derive(source_with(text, keys=[entry]), [crypt_map()])

    assert [(link.node, link.explicit) for link in derived.links] == [("room.vestry", True)]
    assert [k.node for k in derived.text.keys if k.key == "2"] == ["map:crypt#room.vestry"]


def test_a_key_without_a_node_and_no_room_warns():
    text = TextDoc("key", "Key", "gm", None, "## 9. Nowhere {#9}\n")
    entry = {"key": "9", "text": "text:key#9", "npcs": []}

    derived = derive(source_with(text, keys=[entry]), [crypt_map()])

    assert derived.links == []
    assert [w.ref for w in derived.warnings if w.code == "key-without-room"] == ["text:key#9"]
    assert [k.key for k in derived.text.keys] == ["9"]


# --- keys scoped to their part (faithful modules Task 8) -------------------------------------------------------------

HOUSE_MAP = ModuleMap(
    "house",
    "map",
    'map "House" {\n  grid {\n    cell 32 px\n    bounds 20 x 10\n  }\n  room_numbers off\n}\n'
    'room "r7" {\n  rect 1,1 6 x 5\n  label "7. Kitchen"\n}\n'
    'room "r22" {\n  rect 7,1 6 x 5\n  label "22. Attic"\n}\n',
    True,
)
SHIP_MAP = ModuleMap(
    "ship",
    "map",
    'map "Ship" {\n  grid {\n    cell 32 px\n    bounds 20 x 10\n  }\n  room_numbers off\n}\n'
    'room "r7" {\n  rect 1,1 6 x 5\n  label "7. Hold"\n}\n',
    False,
)
HOUSE = TextDoc("house", "PART ONE — THE HAUNTED HOUSE", "gm", "house", "## 7. Kitchen\n\nPots.\n\n## 22. Attic\n\nDust.\n")
SHIP = TextDoc("the-sea-ghost", "Part Two — The Sea Ghost Ship", "gm", "ship", "## 7. Hold\n\nCrates.\n")


def test_part_slug_is_the_title_without_part_numbers_and_articles():
    def titled(title: str, id: str = "t") -> TextDoc:
        return TextDoc(id, title, "gm", None, "")

    assert part_slug(titled("PART ONE — THE HAUNTED HOUSE")) == "haunted-house"
    assert part_slug(titled("Part Two — The Sea Ghost")) == "sea-ghost"
    assert part_slug(titled("Chapter 3: The Lizard Lair of the Marsh")) == "lizard-lair-marsh"
    assert len(part_slug(titled("The Smugglers' Underground Caves Beneath"))) <= PART_LENGTH
    assert part_slug(titled("The Smugglers' Underground Caves Beneath")) == "smugglers"
    assert part_slug(titled("Part One", "a-very-long-text-identifier-indeed")) == "a-very-long-text-id"


def test_a_key_two_parts_share_is_scoped_and_a_unique_key_stays_as_printed():
    assert scoped_keys([HOUSE, SHIP]) == {
        ("house", "7"): "haunted-house-7",
        ("house", "22"): "22",
        ("the-sea-ghost", "7"): "sea-ghost-ship-7",
    }
    assert scoped_keys([HOUSE]) == {("house", "7"): "7", ("house", "22"): "22"}


def test_two_parts_with_the_same_slug_are_scoped_by_their_text_id():
    first = TextDoc("house-1", "The House", "gm", None, "## 7. Kitchen\n")
    second = TextDoc("house-2", "The House", "gm", None, "## 7. Cellar\n")
    assert scoped_keys([first, second]) == {("house-1", "7"): "house-1-7", ("house-2", "7"): "house-2-7"}


def test_derive_links_each_part_by_its_scoped_key():
    derived = derive(source_with(HOUSE, SHIP), [HOUSE_MAP, SHIP_MAP])

    assert [(link.key, link.map, link.node) for link in derived.links] == [
        ("haunted-house-7", "house", "room.r7"),
        ("22", "house", "room.r22"),
        ("sea-ghost-ship-7", "ship", "room.r7"),
    ]
    assert [(k.key, k.part, k.text_anchor) for k in derived.text.keys] == [
        ("haunted-house-7", "haunted-house", "house#7"),
        ("22", "haunted-house", "house#22"),
        ("sea-ghost-ship-7", "sea-ghost-ship", "the-sea-ghost#7"),
    ]


def test_bare_duplicate_entries_take_their_headings_scoped_key():
    """An older conversion wrote `keys[]` entries with the printed key, twice: each takes its heading's scoped key, and
    keeps its NPCs. An entry written with another key keeps it."""
    entries = [
        {"key": "7", "title": "Kitchen", "text": "text:house#7", "npcs": ["npc:cook"]},
        {"key": "7", "title": "Hold", "text": "text:the-sea-ghost#7", "npcs": ["npc:bosun"]},
        {"key": "attic", "title": "Attic", "text": "text:house#22", "node": "map:house#room.r22"},
    ]
    derived = derive(source_with(HOUSE, SHIP, keys=entries), [HOUSE_MAP, SHIP_MAP])

    assert [(k.key, k.node, k.npcs, k.part) for k in derived.text.keys] == [
        ("haunted-house-7", "map:house#room.r7", ["npc:cook"], "haunted-house"),
        ("sea-ghost-ship-7", "map:ship#room.r7", ["npc:bosun"], "sea-ghost-ship"),
        ("attic", "map:house#room.r22", [], "haunted-house"),
    ]
    assert scoped_entries(source_with(HOUSE, SHIP, keys=entries))[:2] == [
        {**entries[0], "key": "haunted-house-7"},
        {**entries[1], "key": "sea-ghost-ship-7"},
    ]
    assert not [w for w in derived.warnings if w.code == "key-without-room"]


def test_every_keyed_heading_is_listed_with_its_scoped_key_linked_or_not():
    """The editor's Where (faithful modules Task 15) offers every keyed heading, not only the linked rooms."""
    house = replace(HOUSE, markdown=HOUSE.markdown + "\n## 19. Cellar Stair\n\nSteps.\n")
    derived = derive(source_with(house, SHIP), [HOUSE_MAP, SHIP_MAP])
    assert derived.headings == [
        Heading("haunted-house-7", "Kitchen", "house", "7"),
        Heading("22", "Attic", "house", "22"),
        Heading("19", "Cellar Stair", "house", "19"),
        Heading("sea-ghost-ship-7", "Hold", "the-sea-ghost", "7"),
    ]
    assert "19" not in {link.key for link in derived.links}
