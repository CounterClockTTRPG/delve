"""Dangling refs rewritten or dropped (plan faithful-modules Task 1, Review Focus 1): a converted module always exports."""

from delve.domain.modules import ModuleMap
from delve.modules.books.convert import merge_entities_mapped
from delve.modules.books.repair import repair_refs
from delve.modules.source import Attachment, ModuleSource, TextDoc, Warning, derive

HOUSE = "# The House\n\n## 7. The Kitchen {#7}\n\nPots.\n\n## 8. The Pantry {#8}\n\nJars.\n"


def _npc(id: str, name: str, **fields) -> dict:
    return {"id": id, "name": name, "audience": "gm", **fields}


def _source(**kw) -> ModuleSource:
    kw.setdefault("texts", [TextDoc("the-house", "The House", "gm", None, HOUSE)])
    return ModuleSource(**kw)


def _codes(warnings: list[Warning]) -> list[str]:
    return [w.code for w in warnings]


def _missing(source: ModuleSource) -> list[Warning]:
    return [w for w in derive(source, []).warnings if w.code in ("missing-entity", "missing-attachment")]


def test_repair_rewrites_a_merged_id():
    source = _source(
        entities={
            "npcs": [_npc("the-bosun", "The Bosun")],
            "factions": [_npc("crew", "The Crew", members=["npc:bosun-2", "npc:the-bosun"])],
        },
        keys=[{"key": "7", "text": "text:the-house#7", "npcs": ["npc:bosun-2"]}],
    )

    repaired, warnings = repair_refs(source, {"npc:bosun-2": "npc:the-bosun"})

    assert repaired.entities["factions"][0]["members"] == ["npc:the-bosun", "npc:the-bosun"]
    assert repaired.keys[0]["npcs"] == ["npc:the-bosun"]
    assert set(_codes(warnings)) == {"ref-rewritten"}
    assert {w.ref for w in warnings} == {"npc:bosun-2"}
    assert source.keys[0]["npcs"] == ["npc:bosun-2"], "the source given is left as it is"
    assert _missing(repaired) == []


def test_repair_rewrites_the_one_match():
    """`factions.yaml:194` of the U1 conversion: `npc:bosun`, and only `the-bosun` exists."""
    source = _source(
        entities={
            "npcs": [_npc("the-bosun", "The Bosun"), _npc("ned", "Ned")],
            "factions": [_npc("crew", "The Crew", members=["npc:bosun"], summary="Led by [the bosun](npc:bosun).")],
        }
    )

    repaired, warnings = repair_refs(source)

    faction = repaired.entities["factions"][0]
    assert faction["members"] == ["npc:the-bosun"]
    assert faction["summary"] == "Led by [the bosun](npc:the-bosun)."
    assert _codes(warnings) == ["ref-rewritten"], "one warning for a ref where it is"
    assert warnings[0].ref == "npc:bosun"
    assert "npc:the-bosun" in warnings[0].message


def test_repair_drops_an_ambiguous_ref():
    """Two records could be meant: never guessed."""
    source = _source(
        entities={
            "npcs": [_npc("smuggler-2", "Smuggler"), _npc("smuggler-3", "Smuggler"), _npc("ned", "Ned")],
            "factions": [_npc("ring", "The Ring", members=["npc:smuggler", "npc:ned"])],
            "quests": [_npc("catch", "Catch them", giver="npc:smuggler")],
        }
    )

    repaired, warnings = repair_refs(source)

    assert repaired.entities["factions"][0]["members"] == ["npc:ned"]
    assert "giver" not in repaired.entities["quests"][0]
    assert _codes(warnings) == ["ref-dropped", "ref-dropped"]
    assert {w.ref for w in warnings} == {"npc:smuggler"}
    assert "The Ring" in warnings[0].message or "ring" in warnings[0].message
    assert _missing(repaired) == []


def test_repair_drops_a_markdown_link_to_its_label():
    markdown = (
        "# Rumours\n\nAsk [the old smuggler](npc:old-smuggler) about [[npc:sea-ghost]].\n\n"
        "Or the [crew](faction:crew).\n"
    )
    source = _source(
        texts=[TextDoc("rumours", "Rumours", "gm", None, markdown)],
        entities={"factions": [_npc("crew", "The Crew")]},
    )

    repaired, warnings = repair_refs(source)

    assert (
        repaired.texts[0].markdown
        == "# Rumours\n\nAsk the old smuggler about sea ghost.\n\nOr the [crew](faction:crew).\n"
    )
    assert _codes(warnings) == ["ref-dropped", "ref-dropped"]
    assert [w.ref for w in warnings] == ["npc:old-smuggler", "npc:sea-ghost"]


def test_repair_drops_a_missing_picture():
    picture = Attachment("page-3", "image/png", "0" * 64, 4, "Page 3", "gm")
    markdown = "# The House\n\n![The cellar](asset:page-9)\n\n![The hall](asset:page-3)\n"
    source = _source(
        texts=[TextDoc("the-house", "The House", "gm", None, markdown)],
        entities={"npcs": [_npc("ned", "Ned", portrait="asset:page-12")]},
        keys=[{"key": "7", "assets": ["asset:page-3", "asset:page-9"]}],
        attachments=[picture],
    )

    repaired, warnings = repair_refs(source)

    assert repaired.texts[0].markdown == "# The House\n\n\n\n![The hall](asset:page-3)\n"
    assert "portrait" not in repaired.entities["npcs"][0]
    assert repaired.keys[0]["assets"] == ["asset:page-3"]
    assert _codes(warnings) == ["ref-dropped"] * 3
    assert _missing(repaired) == []


def test_repair_keeps_external_and_resolving_refs():
    source = _source(
        entities={
            "npcs": [_npc("ned", "Ned", location="text:the-house#7")],
            "encounters": [
                _npc("rats", "Rats", key="key:7", fixed=[{"creature": "monster:giant-rat", "count": "2d4"}])
            ],
        },
        keys=[{"key": "7", "text": "text:the-house#7", "npcs": ["npc:ned"], "encounter": "encounter:rats"}],
    )

    repaired, warnings = repair_refs(source)

    assert repaired == source
    assert warnings == []


def test_repair_resolves_a_key_ref_in_the_records_own_text():
    """The party's amendment: `key:`, `text:` and `map:` refs are resolved within the record's own text first. Both
    parts have a key 8; the galley's rats are keyed to the ship's, as written (`ship-8`, faithful modules Task 9)."""
    ship = TextDoc("the-ship", "The Ship", "gm", None, "# The Ship\n\n## 8. The Galley {#8}\n\nSoup.\n")
    source = _source(
        texts=[TextDoc("the-house", "The House", "gm", None, HOUSE), ship],
        entities={"encounters": [_npc("rats", "Rats", key="key:8", summary="In [the galley](text:the-ship#8).\n")]},
    )

    repaired, warnings = repair_refs(source)

    assert repaired.entities["encounters"][0]["key"] == "key:ship-8"
    assert repaired.keys == [{"key": "ship-8", "title": "The Galley", "text": "text:the-ship#8"}]
    assert [(w.code, w.ref) for w in warnings] == [("ref-rewritten", "key:8")]


def test_repair_rewrites_a_bare_key_to_its_headings_entry():
    """Faithful modules Task 9: a heading's entry is written with its scoped key, and a bare `key:7` in its own text
    takes it, so the export finds it."""
    ship = TextDoc("the-ship", "The Ship", "gm", None, "# The Ship\n\n## 7. The Deck {#7}\n\nRopes.\n")
    markdown = HOUSE + "\nBack to [the kitchen](key:7).\n"
    source = _source(
        texts=[TextDoc("the-house", "The House", "gm", None, markdown), ship],
        keys=[{"key": "house-7", "text": "text:the-house#7"}, {"key": "ship-7", "text": "text:the-ship#7"}],
    )

    repaired, warnings = repair_refs(source)

    assert repaired.texts[0].markdown.endswith("Back to [the kitchen](key:house-7).\n")
    assert repaired.keys == source.keys
    assert _codes(warnings) == ["ref-rewritten"]


def test_repair_resolves_in_a_modules_one_text():
    source = _source(entities={"encounters": [_npc("rats", "Rats", key="key:8")]})

    repaired, warnings = repair_refs(source)

    assert repaired.keys == [{"key": "8", "title": "The Pantry", "text": "text:the-house#8"}]
    assert warnings == []


def test_repair_rewrites_text_and_map_refs_to_the_own_texts_heading():
    markdown = HOUSE + "\nFrom [the kitchen](text:the-house#7-the-kitchen) go to [the pantry](map:house#room.8).\n"
    source = _source(
        texts=[TextDoc("the-house", "The House", "gm", None, markdown)],
        entities={"npcs": [_npc("cook", "The Cook", location="text:the-house#the-kitchen")]},
    )

    repaired, warnings = repair_refs(source)

    assert repaired.texts[0].markdown.endswith(
        "From [the kitchen](text:the-house#7) go to [the pantry](text:the-house#8).\n"
    )
    assert repaired.entities["npcs"][0]["location"] == "text:the-house#7"
    assert _codes(warnings) == ["ref-rewritten"] * 3


def test_repair_drops_refs_the_own_text_cant_resolve():
    source = _source(
        entities={
            "npcs": [_npc("cook", "The Cook", location="text:the-ship#3", faction="faction:crew")],
            "encounters": [_npc("rats", "Rats", key="key:31")],
        },
        keys=[
            {"key": "7", "text": "text:the-house#7", "node": "map:house#room.7"},
            {"key": "9", "text": "text:the-house#9"},
        ],
    )

    repaired, warnings = repair_refs(source)

    assert "location" not in repaired.entities["npcs"][0]
    assert "faction" not in repaired.entities["npcs"][0]
    assert "key" not in repaired.entities["encounters"][0]
    assert repaired.keys == [{"key": "7", "text": "text:the-house#7"}, {"key": "9"}]
    assert _codes(warnings) == ["ref-dropped"] * 5


def test_repair_keeps_a_map_ref_to_a_maps_node():
    dsl = 'map "Cellar" {\n  grid { bounds 10 x 10 }\n}\n\nroom "stairs" {\n  rect 1,1 4 x 4\n}\n'
    maps = [ModuleMap("cellar", "map", dsl, True)]
    markdown = (
        "# The House\n\nSee [the cellar](map:cellar), [its stairs](map:cellar#room.stairs) "
        "and [the well](map:cellar#nowhere).\n"
    )
    source = _source(texts=[TextDoc("the-house", "The House", "gm", None, markdown)])

    repaired, warnings = repair_refs(source, maps=maps)

    assert repaired.texts[0].markdown == (
        "# The House\n\nSee [the cellar](map:cellar), [its stairs](map:cellar#room.stairs) and the well.\n"
    )
    assert _codes(warnings) == ["ref-dropped"]


def test_a_dropped_creature_keeps_its_table_row_as_words():
    rows = [{"roll": "1", "creature": "npc:sea-ghost"}, {"roll": "2", "creature": "monster:stirge"}]
    source = _source(
        entities={
            "encounters": [_npc("wander", "Wandering", table=rows, fixed=[{"creature": "npc:sea-ghost"}])],
        }
    )

    repaired, warnings = repair_refs(source)

    encounter = repaired.entities["encounters"][0]
    assert encounter["table"] == [{"roll": "1", "result": "sea ghost"}, {"roll": "2", "creature": "monster:stirge"}]
    assert encounter["fixed"] == []
    assert _codes(warnings) == ["ref-dropped"]


def test_merge_entities_mapped_names_the_dropped_ids():
    records = [
        _npc("the-bosun", "The Bosun", summary="Gruff."),
        _npc("bosun-2", " the bosun ", role="bosun"),
        _npc("ned", "Ned"),
        _npc("bosun-3", "The Bosun"),
    ]

    merged, renamed = merge_entities_mapped(records)

    assert [r["id"] for r in merged] == ["the-bosun", "ned"]
    assert renamed == {"bosun-2": "the-bosun", "bosun-3": "the-bosun"}
