"""The sample module that ships with Delve, The Lady of the Weir (DEL-378): it validates as a bundle, imports whole as
an OSRIC module set in Aun, every key lands on a room of its map, and every monster it names is in OSRIC's bestiary."""

import re
from pathlib import Path

import yaml

from delve.maps.dsl import parse
from delve.modules.dscn import Bundle
from delve.modules.dscn.validate import validate
from delve.modules.importer import import_bundle
from tests.modules.test_importer import FakeStore

SAMPLE = Path(__file__).resolve().parents[2] / "samples" / "lady-of-the-weir"
PLAYED = ("valley", "weirholt", "sluice-house")


def test_the_sample_module_validates_without_errors():
    errors = [d for d in validate(Bundle.load(SAMPLE)) if d.severity == "error"]
    assert errors == []


def test_the_sample_module_imports_whole():
    result = import_bundle(FakeStore(), Bundle.load(SAMPLE).to_zip())
    module = result.module
    assert module.title == "The Lady of the Weir"
    assert (module.metadata["system"], module.metadata["setting"]) == ("osric", "aun")
    assert module.metadata["license"]["spdx"] == "CC-BY-4.0"
    played = [(m.name, m.is_default) for m in module.maps if m.role == "map"]
    assert played == [("valley", True), ("weirholt", False), ("sluice-house", False)]


def test_every_key_lands_on_a_room_of_its_map():
    bundle = Bundle.load(SAMPLE)
    manifest = bundle.manifest
    libraries = {m["name"]: (SAMPLE / m["file"]).read_text() for m in manifest["maps"] if m.get("role") == "library"}
    rooms = {}
    for entry in manifest["maps"]:
        if entry["name"] in PLAYED:
            dmap = parse((SAMPLE / entry["file"]).read_text(), include_sources=libraries)
            rooms[entry["name"]] = set(dmap.rooms)
    assert len(manifest["keys"]) == 23
    for key in manifest["keys"]:
        found = re.fullmatch(r"map:([a-z-]+)#room\.([a-z_]+)", key["node"])
        assert found and found.group(2) in rooms[found.group(1)], key


def test_the_assets_are_the_files_in_the_bundle():
    manifest = Bundle.load(SAMPLE).manifest
    listed = {a["file"] for a in manifest["assets"]}
    on_disk = {str(p.relative_to(SAMPLE)) for p in (SAMPLE / "assets").rglob("*") if p.is_file()}
    assert listed == on_disk


def test_the_sample_modules_monsters_are_osrics(osric_catalogs):
    from delve_osric.ruleset import OsricRuleset

    osric = OsricRuleset()
    named = set()
    for kind in ("encounters", "npcs"):
        text = (SAMPLE / "entities" / f"{kind}.yaml").read_text()
        named |= set(re.findall(r"monster:([a-z0-9-]+)", text))
    assert named
    # Exactly that entry, not a near miss: the slug of one of the lookup's hits.
    unknown = sorted(
        slug for slug in named if slug not in {hit.key for hit in osric.lookup("monster", slug.replace("-", " "))}
    )
    assert unknown == []


def test_the_side_quests_pay_the_designs_xp():
    quests = {q["id"]: q["description"] for q in yaml.safe_load((SAMPLE / "entities" / "quests.yaml").read_text())}
    xp = {qid: re.findall(r"\*\*(\d+) XP", text) for qid, text in quests.items()}
    assert xp == {
        "the-ladys-matter": ["300", "150"],
        "dilly-home": ["100"],
        "sorrel-at-rest": ["150"],
        "the-friars-torch": ["75"],
        "odo-in-check": ["100"],
        "the-boatman": ["50"],
    }


def test_every_npc_of_the_design_is_there():
    npcs = {n["id"] for n in yaml.safe_load((SAMPLE / "entities" / "npcs.yaml").read_text())}
    assert {"reeve-haldan", "wenna", "odo-tesk", "the-lady", "sorrel", "brother-aldo", "pim", "magge", "tam-ruddle",
            "dilly", "merrit-vane", "ostric"} <= npcs  # fmt: skip


def test_no_npc_record_a_player_may_see_holds_a_secret():
    """A player-audience record is shown to players by any reader of the format: only Pim, who hides nothing."""
    npcs = yaml.safe_load((SAMPLE / "entities" / "npcs.yaml").read_text())
    assert [n["id"] for n in npcs if n.get("audience") == "player"] == ["pim"]
