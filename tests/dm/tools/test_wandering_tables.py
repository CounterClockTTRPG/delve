"""The module's own wandering tables (DEL-321): encounter_check rolls the one for where the party is, the most
closely placed first, names them when several tie, and falls back to the ruleset's tables."""

import shutil

import pytest
import yaml

from delve.dice import ScriptedRng
from delve.dm.tools import ToolHost
from delve.modules.dscn import Bundle
from delve.modules.importer import import_bundle
from tests.fixtures import SAMPLES

CRYPT = SAMPLES / "scenarios" / "crypt-of-saint-vellis"
BRUISER = {"race": "Human", "cls": "Fighter", "level": 1, "hp_max": 10, "ac": 4, "thac0": 20}


def placed(id: str, where: list[str] | None, creature: str, **extra) -> dict:
    record = {"id": id, "name": id.replace("-", " "), "wandering": True, "kind": "dungeon", **extra}
    if where is not None:
        record["where"] = where
    record["table"] = [{"roll": "1-6", "count": "2", "creature": f"monster:{creature}"}]
    return record


def crypt_with(tmp_path, storage, extra: list[dict], keep_own: bool = True):
    """A campaign of the crypt sample, its encounters with `extra` added (and its own crypt-wandering kept or not),
    the party of one in the entry hall."""
    root = tmp_path / "crypt"
    shutil.copytree(CRYPT, root)
    path = root / "entities" / "encounters.yaml"
    records = [r for r in yaml.safe_load(path.read_text()) if keep_own or r["id"] != "crypt-wandering"]
    path.write_text(yaml.safe_dump(records + extra, sort_keys=False))
    module = import_bundle(storage, Bundle.load(root).to_zip()).module
    revision = storage.revisions.latest(module.id) or storage.revisions.snapshot(module.id)
    return storage.campaigns.create("Crypt", module.id, revision.number, ruleset="osric", setting=None)


@pytest.fixture
def play(storage, osric_catalogs):
    """`play(campaign, *dice)`: a tool call on the campaign, its dice scripted."""

    def run(campaign, *dice):
        host = ToolHost(storage, lambda: ScriptedRng(dice), catalogs=osric_catalogs)

        def call(tool, /, **args):
            return host.call(campaign.id, "beat-1", tool, args)

        return call

    return run


def party_in(call, room: str) -> None:
    call("create_character", name="Bren", sheet=BRUISER)
    call("move_party", to=room)


def test_the_modules_one_table_rolls_in_the_sample(tmp_path, storage, play):
    """The crypt's own table, placed nowhere: a check that comes up rolls it, not the ruleset's (the DEL-315 runs
    met toads, kobolds and yellow mold in a crypt of rats and skeletons)."""
    campaign = crypt_with(tmp_path, storage, [])
    party_in(play(campaign), "entry_hall")
    out = play(campaign, 1, 2, 3)("encounter_check", terrain="dungeon")
    assert (out["triggered"], out["source"], out["table_id"]) == (True, "module", "crypt-wandering")
    assert (out["creature"], out["number"]) == ("monster:giant-rat", "3")


def test_the_most_closely_placed_table_wins(tmp_path, storage, play):
    """A room's table over its section's, over its text's, over its map's, over the unplaced one."""
    tables = [
        placed("map-wide", ["map:crypt"], "ghoul"),
        placed("key-text", ["text:crypt-key"], "zombie"),
        placed("hall-section", ["text:crypt-key#c1"], "shadow"),
        placed("hall-room", ["key:C1"], "wight"),
        placed("vestry-room", ["map:crypt#room.vestry_alcove"], "ghost"),
    ]
    campaign = crypt_with(tmp_path, storage, tables)
    party_in(play(campaign), "entry_hall")
    assert play(campaign, 1, 1)("encounter_check", terrain="dungeon")["table_id"] == "hall-room"

    campaign = crypt_with(tmp_path / "2", storage, tables[:3])
    party_in(play(campaign), "entry_hall")
    assert play(campaign, 1, 1)("encounter_check", terrain="dungeon")["table_id"] == "hall-section"

    campaign = crypt_with(tmp_path / "3", storage, tables[:2])
    party_in(play(campaign), "entry_hall")
    assert play(campaign, 1, 1)("encounter_check", terrain="dungeon")["table_id"] == "key-text"

    campaign = crypt_with(tmp_path / "4", storage, [tables[0], tables[4]])
    party_in(play(campaign), "vestry_alcove")
    assert play(campaign, 1, 1)("encounter_check", terrain="dungeon")["table_id"] == "vestry-room"
    call = play(campaign)
    call("move_party", to="entry_hall")
    assert play(campaign, 1, 1)("encounter_check", terrain="dungeon")["table_id"] == "map-wide"


def test_a_table_placed_elsewhere_never_rolls(tmp_path, storage, play):
    campaign = crypt_with(tmp_path, storage, [placed("vestry", ["key:C3"], "ghoul")], keep_own=False)
    party_in(play(campaign), "entry_hall")
    out = play(campaign, 4)("encounter_check", terrain="dungeon")
    assert (out["triggered"], out["source"], out["table_id"]) == (False, "ruleset", "")


def test_tied_tables_wait_for_the_dm_to_name_one(tmp_path, storage, play):
    """Two tables placed nowhere: the check comes up and names both; naming one rolls it on the stored check, and
    'ruleset' asks for the ruleset's tables."""
    campaign = crypt_with(tmp_path, storage, [placed("level-b-wandering", None, "ghoul")])
    party_in(play(campaign), "entry_hall")
    out = play(campaign, 1)("encounter_check", terrain="dungeon")
    assert (out["triggered"], out["source"]) == (True, "")
    assert [c["id"] for c in out["choose"]] == ["crypt-wandering", "level-b-wandering"]

    named = play(campaign, 6, 4)("encounter_check", terrain="dungeon", table="level-b-wandering")
    assert named["check"]["id"] == out["check"]["id"]  # the same check, not a new one
    assert (named["source"], named["creature"], named["number"]) == ("module", "monster:ghoul", "2")
    assert play(campaign, 3, 4, 1)("encounter_check", terrain="dungeon", table="ruleset")["source"] == "ruleset"
    assert "error" in play(campaign)("encounter_check", terrain="dungeon", table="nowhere")


def test_an_unplaced_table_of_another_terrain_isnt_for_the_dungeon(tmp_path, storage, play):
    forest = placed("forest-wandering", None, "bear", kind="wilderness")
    campaign = crypt_with(tmp_path, storage, [forest], keep_own=False)
    party_in(play(campaign), "entry_hall")
    assert play(campaign, 4)("encounter_check", terrain="dungeon")["table_id"] == ""
    assert play(campaign, 1, 5)("encounter_check", terrain="forest")["table_id"] == "forest-wandering"
    assert play(campaign, 4)("encounter_check", terrain="town")["table_id"] == ""


def test_a_room_with_no_wandering_monsters_beats_the_map_wide_table(tmp_path, storage, play):
    """The vestry is quiet (an empty table placed there); the map's table still rolls in the entry hall."""
    quiet = {
        "id": "vestry-quiet",
        "name": "No wanderers in the vestry",
        "wandering": True,
        "where": ["key:C3"],
        "table": [],
    }
    campaign = crypt_with(tmp_path, storage, [quiet, placed("map-wide", ["map:crypt"], "ghoul")])
    party_in(play(campaign), "vestry_alcove")
    out = play(campaign, 1)("encounter_check", terrain="dungeon")
    assert (out["triggered"], out["table_id"], out["note"]) == (
        False,
        "vestry-quiet",
        "The module has no wandering monsters here.",
    )
    play(campaign)("move_party", to="entry_hall")
    assert play(campaign, 1, 1)("encounter_check", terrain="dungeon")["table_id"] == "map-wide"
