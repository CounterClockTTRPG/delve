"""Fixtures for the DM's tools: a campaign on the crypt map (with a hidden room planted for the fourth-wall tests, and
a player image and a DM-only one), and a tool host on them with seeded dice."""

import itertools

import pytest

from delve.config import Config
from delve.dice import SeededRng
from delve.dm.tools import ToolHost
from delve.domain.modules import ModuleMap
from delve.modules.source import ATTACHMENT, Attachment, ModuleSource
from delve.storage import open_storage
from tests.fixtures import SAMPLES
from tests.fixtures.rulesets import osric_catalogs

SECRET = "SECRET-XYZZY"

# The crypt with a hidden room behind a secret door off the vestry, its label, text and DM notes planted, and a secret
# trapdoor in the vestry, its DM notes planted.
CRYPT = (
    (SAMPLES / "crypt.dmap")
    .read_text()
    .replace(
        'room "vestry_alcove" {',
        f'room "vestry_alcove" {{\n  feature chest at 44,24 id trapdoor_4 {{ secret dm_notes "{SECRET} the stair below." }}',
    )
    + f"""
room "hidden_crypt" {{
  rect 44,14 4 x 6
  label "{SECRET}"
  description "{SECRET} bones."
  dm_notes "{SECRET} the ritualist hides here."
}}
door at 46,20 {{ connects room.vestry_alcove, room.hidden_crypt type secret }}
"""
)

GARREK = {
    "race": "Human",
    "cls": "Fighter",
    "level": 1,
    "hp_max": 10,
    "ac": 4,
    "thac0": 20,
    "ability_scores": {"str": 16, "dex": 12, "con": 15},
    "attacks": [{"name": "long sword", "speed": 5, "attacks": 1, "thac0": 20, "damage_sm": "1d8", "damage_l": "1d12"}],
}
PIPPA = {
    "race": "Halfling",
    "cls": "Thief",
    "level": 1,
    "hp_max": 6,
    "ac": 7,
    "thac0": 20,
    "ability_scores": {"dex": 17, "con": 12},
    "skills": {"move_silently": 25, "hide_in_shadows": 20, "detect_noise": 15},
    "weapon": "short sword",
}


@pytest.fixture
def storage(tmp_path):
    opened = open_storage(Config(data_dir=tmp_path / "data"))
    yield opened
    opened.close()


SPY = {
    "id": "spy",
    "name": "The Spy",
    "audience": "gm",
    "description": f"{SECRET}: works for the smugglers.",
    "class": "Thief",
    "level": 2,
    "background": f"{SECRET}: paid by the lizard men.",
}
"""A pregen the DM keeps back (faithful modules Task 19): `module_pregens` gives it, and no seat ever sees it."""

PNG = (SAMPLES / "scenarios" / "crypt-of-saint-vellis" / "assets" / "img" / "ritualist-token.png").read_bytes()


def images(storage, module_id: str) -> list[Attachment]:
    """The crypt's gate, for the players, and the lich behind the altar, DM-only, its description planted."""
    sha = storage.blobs.put(PNG, "image/png")
    storage.blobs.link(module_id, ATTACHMENT, sha)
    return [
        Attachment("gate", "image/png", sha, len(PNG), "The crypt's gate at dusk.", "player"),
        Attachment("lich", "image/png", sha, len(PNG), f"{SECRET}: the lich behind the altar.", "dm"),
    ]


@pytest.fixture
def campaign(storage):
    module = storage.modules.create("The Crypt")
    storage.modules.put_map(module.id, ModuleMap("crypt", "map", CRYPT, is_default=True))
    # a map, images and a DM-only pregen with the secret, no text
    source = ModuleSource(attachments=images(storage, module.id), entities={"pregens": [SPY]})
    storage.module_sources.put(module.id, source)
    revision = storage.revisions.snapshot(module.id)
    return storage.campaigns.create("Tuesday", module.id, revision.number, ruleset="osric", setting="greyhawk")


@pytest.fixture
def host(storage):
    seeds = itertools.count(1)
    return ToolHost(storage, lambda: SeededRng(next(seeds)), catalogs=osric_catalogs())


@pytest.fixture
def call(host, campaign):
    """`call(tool, beat="beat-1", **args)`: a tool call on the campaign."""

    def run(tool, /, beat="beat-1", **args):
        return host.call(campaign.id, beat, tool, args)

    return run


@pytest.fixture
def party(call):
    """Garrek (a fighter) and Pippa (a thief), and the innkeeper Tira, an NPC whose story is planted."""
    garrek = call("create_character", name="Garrek", sheet=GARREK)
    pippa = call("create_character", name="Pippa", sheet=PIPPA)
    tira = call(
        "create_character", name="Tira", kind="npc", sheet={"race": "Human", "notes_md": f"{SECRET}: she is the cult."}
    )
    return garrek, pippa, tira
