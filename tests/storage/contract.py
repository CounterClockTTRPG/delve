"""The storage contract: every backend must pass these, given a factory for a fresh, empty storage."""

from __future__ import annotations

import hashlib
import tempfile
from collections.abc import Callable
from dataclasses import asdict, replace
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

import pytest

from delve.dice import Roll, RollKey
from delve.domain.accounts import AccountLink, Identity, LoginSession, Profile
from delve.domain.board import Post, Topic, Zone
from delve.domain.campaigns import CampaignState, CombatRound, LootItem, Note, Session, StoryEntry, TableSession
from delve.domain.characters import Attack, CharacterState, Effect, Sheet
from delve.domain.house_rules import Bundle
from delve.domain.modules import ModuleMap
from delve.domain.setting_content import Proposal, SettingAddition, SettingFact, title_key
from delve.domain.world import (
    TILE_SIZE,
    CampaignFact,
    CampaignImage,
    CampaignWorldMap,
    Clock,
    Faction,
    ImagePortrait,
    Journey,
    Merchant,
    Possession,
    Quest,
    QuestNote,
    StartDate,
    TraitsPortrait,
    Weather,
    WorldKnowledge,
    WorldMapSource,
    WorldPicture,
    WorldPosition,
)
from delve.storage.interfaces import CampaignActivity, ModuleInUse, Storage


def test_settings_empty_load(storage: Storage) -> None:
    assert storage.settings.load() == {}


def test_settings_roundtrip(storage: Storage) -> None:
    raw = {
        "choices": {"dm": {"provider": "fake", "model": "fake-large", "effort": "high"}, "image.portrait": {}},
        "language": "nl",
        "flags": [1, 2.5, True, None, "ë"],
    }
    storage.settings.save(raw)
    assert storage.settings.load() == raw


def test_settings_overwrite(storage: Storage) -> None:
    storage.settings.save({"choices": {"dm": {"provider": "fake"}}, "language": "nl"})
    storage.settings.save({"language": "en"})
    assert storage.settings.load() == {"language": "en"}


def test_settings_update(storage: Storage) -> None:
    """`update` changes only the keys it names, and `within` a key only that key's keys; it answers the whole."""
    storage.settings.save({"language": "nl", "backup": {"time": "04:00", "last_run": {"status": "ok"}}})
    assert storage.settings.update({"sign_up": True}) == {
        "language": "nl",
        "backup": {"time": "04:00", "last_run": {"status": "ok"}},
        "sign_up": True,
    }
    storage.settings.update({"time": "05:30"}, within="backup")
    storage.settings.update({"time": "01:00"}, within="legal")
    assert storage.settings.load() == {
        "language": "nl",
        "backup": {"time": "05:30", "last_run": {"status": "ok"}},
        "sign_up": True,
        "legal": {"time": "01:00"},
    }
    storage.settings.save({"backup": "not a dict"})
    assert storage.settings.update({"time": "02:00"}, within="backup") == {"backup": {"time": "02:00"}}


CRYPT = ModuleMap(name="crypt", role="map", source="map crypt {}\n", is_default=True)
WALLS = ModuleMap(name="walls", role="library", source="def wall {}\n", is_default=False)


def test_module_crud(storage: Storage) -> None:
    assert storage.modules.get("mod_000000000000") is None
    assert storage.modules.list() == []

    module = storage.modules.create("The Crypt", {"author": "Raf"})
    assert module.id.startswith("mod_") and len(module.id) == len("mod_") + 12
    assert module.title == "The Crypt" and module.metadata == {"author": "Raf"}
    assert module.maps == () and module.head_revision is None and module.updated_at
    assert storage.modules.get(module.id) == module
    assert storage.modules.create("Bare").metadata == {}

    renamed = storage.modules.rename(module.id, "The Crypt of Saint Vellis")
    assert renamed.title == "The Crypt of Saint Vellis"
    storage.modules.set_metadata(module.id, {"level": 3})
    assert storage.modules.get(module.id).metadata == {"level": 3}
    assert [m.title for m in storage.modules.list()] == ["The Crypt of Saint Vellis", "Bare"]

    with pytest.raises(KeyError):
        storage.modules.rename("mod_000000000000", "nope")
    with pytest.raises(KeyError):
        storage.modules.put_map("mod_000000000000", CRYPT)

    storage.modules.delete(module.id)
    assert storage.modules.get(module.id) is None
    assert [m.title for m in storage.modules.list()] == ["Bare"]
    storage.modules.delete(module.id)  # deleting what is gone is not an error


def test_put_map_upserts_by_name(storage: Storage) -> None:
    module = storage.modules.create("The Crypt")
    module = storage.modules.put_map(module.id, CRYPT)
    module = storage.modules.put_map(module.id, WALLS)
    assert module.maps == (CRYPT, WALLS)

    edited = ModuleMap(name="crypt", role="map", source="map crypt { room a }\n", is_default=True)
    module = storage.modules.put_map(module.id, edited)
    assert module.maps == (edited, WALLS)
    assert storage.modules.get(module.id).maps == (edited, WALLS)

    module = storage.modules.delete_map(module.id, "crypt")
    assert module.maps == (WALLS,)
    with pytest.raises(KeyError):
        storage.modules.delete_map(module.id, "crypt")
    module = storage.modules.put_map(module.id, CRYPT)
    module = storage.modules.put_map(module.id, ModuleMap("tower", "map", "map tower {}\n", is_default=False))
    assert [m.name for m in module.maps] == ["walls", "crypt", "tower"]


def test_single_default_map(storage: Storage) -> None:
    module = storage.modules.create("The Crypt")
    storage.modules.put_map(module.id, CRYPT)
    module = storage.modules.put_map(module.id, ModuleMap("tower", "map", "map tower {}\n", is_default=True))
    assert [(m.name, m.is_default) for m in module.maps] == [("crypt", False), ("tower", True)]

    module = storage.modules.set_default_map(module.id, "crypt")
    assert [(m.name, m.is_default) for m in module.maps] == [("crypt", True), ("tower", False)]
    assert storage.modules.get(module.id) == module
    with pytest.raises(KeyError):
        storage.modules.set_default_map(module.id, "nowhere")


def test_snapshot_reuses_unchanged_revision(storage: Storage) -> None:
    module = storage.modules.create("The Crypt", {"author": "Raf"})
    storage.modules.put_map(module.id, CRYPT)
    assert storage.revisions.latest(module.id) is None
    assert storage.modules.changed_since(module.id, None)

    first = storage.revisions.snapshot(module.id)
    assert first.module_id == module.id and first.number == 1
    assert first.title == "The Crypt" and first.metadata == {"author": "Raf"} and first.maps == (CRYPT,)
    assert not storage.modules.changed_since(module.id, 1)
    assert storage.revisions.snapshot(module.id) == first
    assert storage.revisions.latest(module.id) == first
    assert storage.revisions.get(module.id, 1) == first
    assert storage.revisions.get(module.id, 2) is None
    assert storage.modules.get(module.id).head_revision == 1


def test_snapshot_after_edit_creates_next(storage: Storage) -> None:
    module = storage.modules.create("The Crypt")
    storage.modules.put_map(module.id, CRYPT)
    storage.revisions.snapshot(module.id)

    storage.modules.put_map(module.id, WALLS)
    assert storage.modules.changed_since(module.id, 1)
    second = storage.revisions.snapshot(module.id)
    assert second.number == 2 and second.maps == (CRYPT, WALLS)
    assert storage.modules.get(module.id).head_revision == 2

    storage.modules.rename(module.id, "Renamed")
    assert storage.revisions.snapshot(module.id).number == 3
    storage.modules.set_metadata(module.id, {"level": 1})
    assert storage.revisions.snapshot(module.id).number == 4
    assert storage.revisions.latest(module.id).number == 4
    with pytest.raises(KeyError):
        storage.revisions.snapshot("mod_000000000000")


def test_revision_immutable_after_edit(storage: Storage) -> None:
    module = storage.modules.create("The Crypt", {"author": "Raf"})
    storage.modules.put_map(module.id, CRYPT)
    first = storage.revisions.snapshot(module.id)

    storage.modules.put_map(module.id, ModuleMap("crypt", "map", "map crypt { room b }\n", is_default=True))
    storage.modules.put_map(module.id, WALLS)
    storage.modules.rename(module.id, "Other")
    storage.modules.set_metadata(module.id, {"author": "Someone else"})
    storage.modules.delete_map(module.id, "crypt")

    assert storage.revisions.get(module.id, 1) == first
    assert first.maps == (CRYPT,) and first.title == "The Crypt" and first.metadata == {"author": "Raf"}


def _started_campaign(storage: Storage):
    module = storage.modules.create("The Crypt")
    storage.modules.put_map(module.id, CRYPT)
    revision = storage.revisions.snapshot(module.id)
    return module, storage.campaigns.create("Tuesday", module.id, revision.number, ruleset="adnd2e", setting="greyhawk")


def test_campaign_and_characters(storage: Storage) -> None:
    assert storage.campaigns.get("cmp_000000000000") is None
    module, campaign = _started_campaign(storage)
    assert campaign.id.startswith("cmp_") and len(campaign.id) == len("cmp_") + 12
    assert (campaign.name, campaign.module_id, campaign.revision) == ("Tuesday", module.id, 1)
    assert (campaign.ruleset, campaign.setting) == ("adnd2e", "greyhawk")
    assert campaign.created_at
    elsewhere = storage.campaigns.create("Elsewhere", module.id, 1, ruleset="osric", setting="")
    assert storage.campaigns.get(elsewhere.id) == elsewhere
    assert (elsewhere.ruleset, elsewhere.setting) == ("osric", "")
    storage.campaigns.delete(elsewhere.id)
    assert storage.campaigns.get(campaign.id) == campaign
    assert storage.campaigns.list() == [campaign]

    with pytest.raises(KeyError):
        storage.campaigns.create("Nowhere", "mod_000000000000", 1, ruleset="adnd2e", setting="greyhawk")
    with pytest.raises(KeyError):
        storage.campaigns.create("No such revision", module.id, 7, ruleset="adnd2e", setting="greyhawk")

    storage.modules.put_map(module.id, WALLS)
    second = storage.revisions.snapshot(module.id)
    upgraded = storage.campaigns.set_revision(campaign.id, second.number)
    assert upgraded.revision == 2 and storage.campaigns.get(campaign.id) == upgraded
    with pytest.raises(KeyError):
        storage.campaigns.set_revision(campaign.id, 9)

    assert storage.characters.list(campaign.id) == []
    brother = storage.characters.create(campaign.id, "Brother Anselm")
    mira = storage.characters.create(campaign.id, "Mira")
    assert brother.id.startswith("chr_") and len(brother.id) == len("chr_") + 12
    assert (brother.campaign_id, brother.name) == (campaign.id, "Brother Anselm") and brother.created_at
    assert storage.characters.list(campaign.id) == [brother, mira]

    renamed = storage.characters.rename(mira.id, "Mira the Bold")
    assert renamed.name == "Mira the Bold" and renamed.id == mira.id
    storage.characters.delete(brother.id)
    assert storage.characters.list(campaign.id) == [renamed]
    storage.characters.delete(brother.id)
    with pytest.raises(KeyError):
        storage.characters.rename(brother.id, "Ghost")
    with pytest.raises(KeyError):
        storage.characters.create("cmp_000000000000", "Orphan")


def test_delete_campaign_cascades(storage: Storage) -> None:
    module, campaign = _started_campaign(storage)
    _, other = _started_campaign(storage)
    storage.characters.create(campaign.id, "Mira")
    storage.characters.create(other.id, "Anselm")
    storage.map_states.put(campaign.id, "crypt", {"characters": {}})
    storage.map_states.put(other.id, "crypt", {"characters": {}})

    storage.campaigns.delete(campaign.id)
    assert storage.campaigns.get(campaign.id) is None
    assert storage.characters.list(campaign.id) == []
    assert storage.map_states.list(campaign.id) == {}
    assert storage.map_states.get(campaign.id, "crypt") is None
    assert [c.name for c in storage.characters.list(other.id)] == ["Anselm"]
    assert storage.map_states.list(other.id) == {"crypt": {"characters": {}}}
    storage.campaigns.delete(campaign.id)

    storage.modules.delete(module.id)
    assert storage.modules.get(module.id) is None
    assert storage.revisions.latest(module.id) is None


def test_module_in_use_not_deleted(storage: Storage) -> None:
    module, campaign = _started_campaign(storage)
    with pytest.raises(ModuleInUse) as caught:
        storage.modules.delete(module.id)
    assert caught.value.module_id == module.id and caught.value.campaign_ids == (campaign.id,)
    assert storage.modules.get(module.id) is not None
    assert storage.revisions.get(module.id, 1) is not None

    storage.campaigns.delete(campaign.id)
    storage.modules.delete(module.id)
    assert storage.modules.get(module.id) is None


def test_campaign_maps(storage: Storage) -> None:
    """A campaign's own maps (campaign maps, 2026-10-23): by name, in the order first put, gone with the campaign."""
    _, campaign = _started_campaign(storage)
    assert storage.campaign_maps.list(campaign.id) == []
    assert storage.campaign_maps.get(campaign.id, "slums") is None

    storage.campaign_maps.put(campaign.id, "slums", 'map "Slums" {}')
    storage.campaign_maps.put(campaign.id, "refuge", 'map "Refuge" {}')
    storage.campaign_maps.put(campaign.id, "slums", 'map "The Slums" {}')  # replaced in place
    assert storage.campaign_maps.get(campaign.id, "slums") == ModuleMap("slums", "map", 'map "The Slums" {}', False)
    assert [m.name for m in storage.campaign_maps.list(campaign.id)] == ["slums", "refuge"]

    storage.campaign_maps.delete(campaign.id, "slums")
    assert [m.name for m in storage.campaign_maps.list(campaign.id)] == ["refuge"]
    with pytest.raises(KeyError):
        storage.campaign_maps.put("cmp_000000000000", "x", "")

    storage.campaigns.delete(campaign.id)
    assert storage.campaign_maps.list(campaign.id) == []


def test_map_state_roundtrip(storage: Storage) -> None:
    _, campaign = _started_campaign(storage)
    assert storage.map_states.get(campaign.id, "crypt") is None
    assert storage.map_states.list(campaign.id) == {}

    raw = {
        "characters": {"chr_0123456789ab": {"location": "nave", "nodes": ["nave", "crypt"], "doors": ["d1"]}},
        "door_states": {"d1": "open"},
        "revealed": ["altar"],
    }
    storage.map_states.put(campaign.id, "crypt", raw)
    assert storage.map_states.get(campaign.id, "crypt") == raw

    replaced = {"characters": {}, "door_states": {}, "revealed": []}
    storage.map_states.put(campaign.id, "crypt", replaced)
    storage.map_states.put(campaign.id, "tower", raw)
    assert storage.map_states.get(campaign.id, "crypt") == replaced
    assert storage.map_states.list(campaign.id) == {"crypt": replaced, "tower": raw}
    with pytest.raises(KeyError):
        storage.map_states.put("cmp_000000000000", "crypt", raw)


def test_blob_content_addressed_and_deduplicated(storage: Storage) -> None:
    data = b"PK\x03\x04 a bundle"
    sha = storage.blobs.put(data, "application/zip")
    assert sha == hashlib.sha256(data).hexdigest()
    assert storage.blobs.exists(sha) and storage.blobs.get(sha) == data
    assert storage.blobs.put(data, "application/zip") == sha

    missing = hashlib.sha256(b"never stored").hexdigest()
    assert not storage.blobs.exists(missing) and storage.blobs.get(missing) is None
    assert not storage.blobs.exists("../../delve.db") and storage.blobs.get("../../delve.db") is None

    module = storage.modules.create("The Crypt")
    assert storage.blobs.links(module.id) == []
    storage.blobs.link(module.id, "source-bundle", sha)
    storage.blobs.link(module.id, "source-bundle", sha)
    assert storage.blobs.links(module.id) == [("source-bundle", sha)]
    with pytest.raises(KeyError):
        storage.blobs.link(module.id, "cover", missing)
    with pytest.raises(KeyError):
        storage.blobs.link("mod_000000000000", "source-bundle", sha)

    storage.modules.delete(module.id)
    assert storage.blobs.links(module.id) == []
    assert storage.blobs.get(sha) == data


def test_blob_written_atomically(storage: Storage) -> None:
    data = b"half a bundle, then the disk fails"
    sha = hashlib.sha256(data).hexdigest()
    with mock.patch("os.replace", side_effect=OSError("disk full")), pytest.raises(OSError):
        storage.blobs.put(data, "application/zip")
    assert not storage.blobs.exists(sha) and storage.blobs.get(sha) is None

    assert storage.blobs.put(data, "application/zip") == sha
    assert storage.blobs.get(sha) == data


def test_blob_put_file_streams_a_file_in(storage: Storage) -> None:
    data = b"%PDF-1.4 a whole book " * 50_000
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "book.pdf"
        path.write_bytes(data)
        sha = storage.blobs.put_file(path, "application/pdf")
        assert path.read_bytes() == data, "the file put is left as it was"
    assert sha == hashlib.sha256(data).hexdigest() == storage.blobs.put(data, "application/pdf")
    assert storage.blobs.exists(sha) and storage.blobs.get(sha) == data
    module = storage.modules.create("The Book")
    storage.blobs.link(module.id, "attachment", sha)
    assert storage.blobs.links(module.id) == [("attachment", sha)]


GARREK = Sheet(
    race="human",
    gender="male",
    cls="Fighter/Thief",
    levels={"fighter": 3, "thief": 4},
    hp_max=24,
    ac=4,
    thac0=18,
    saves={"spell": 15, "breath_weapon": 16},
    ability_scores={"str": "18/76", "dex": 16},
    attacks=(
        Attack("long sword", speed=5, attacks="3/2", damage_sm="1d8+3", damage_l="1d12+3"),
        Attack("short bow", speed=7, attacks=2, damage_sm="1d6", damage_l="1d6", range="5/10/15"),
    ),
    weapon="long sword",
    weapon_profs=("long sword", "short bow"),
    nwps=("tracking",),
    skills={"move_silently": 40},
    alignment="CG",
    spell_slots={1: 2, 2: 1},
)


def test_character_sheet_state_roundtrip(storage: Storage) -> None:
    _, campaign = _started_campaign(storage)
    state = CharacterState(
        hp=17, xp=2600, conditions=("poisoned",), effects=(Effect("bless", 6, to_hit=1, save=1, source="Anselm"),)
    )
    garrek = storage.characters.create(campaign.id, "Garrek", sheet=GARREK, state=state)
    assert (garrek.kind, garrek.order, garrek.sheet.label, garrek.sheet.kind) == ("pc", 0, "Garrek", "pc")
    assert storage.characters.get(garrek.id) == garrek
    assert storage.characters.get("chr_000000000000") is None
    loaded = storage.characters.get(garrek.id)
    assert loaded.sheet.spell_slots == {1: 2, 2: 1} and loaded.sheet.attacks[0].attacks == "3/2"
    assert loaded.state.effects[0] == Effect("bless", 6, to_hit=1, save=1, source="Anselm")

    tira = storage.characters.create(
        campaign.id, "Tira", kind="npc", sheet=Sheet(notes_md="Owes the guild.", disposition=-45)
    )
    assert (tira.kind, tira.order, tira.sheet.disposition) == ("npc", None, -45)
    pip = storage.characters.create(campaign.id, "Pip")
    assert pip.order == 1 and storage.characters.list(campaign.id) == [garrek, tira, pip]

    hurt = replace(garrek, name="Garrek the Grey", state=replace(garrek.state, hp=3), order=5)
    saved = storage.characters.save(hurt)
    assert saved.sheet.label == "Garrek the Grey"
    assert storage.characters.get(garrek.id) == saved and saved.state.hp == 3 and saved.order == 5
    assert storage.characters.save(replace(tira, order=3)).order is None  # NPCs have no marching order
    renamed = storage.characters.rename(tira.id, "Tira Vane")
    assert renamed.sheet.label == "Tira Vane" and storage.characters.get(tira.id) == renamed
    with pytest.raises(KeyError):
        storage.characters.save(replace(garrek, id="chr_000000000000"))
    _, other = _started_campaign(storage)
    with pytest.raises(KeyError):
        storage.characters.save(replace(garrek, campaign_id=other.id))


def test_campaign_state_roundtrip(storage: Storage) -> None:
    _, campaign = _started_campaign(storage)
    assert storage.campaign_states.get("cmp_000000000000") is None
    fresh = storage.campaign_states.get(campaign.id)
    assert fresh == CampaignState(campaign.id)
    assert (fresh.day, fresh.hour, fresh.session, fresh.coin["gp"], fresh.loot) == (1, 6, 1, 0, ())

    state = CampaignState(
        campaign.id,
        day=3,
        hour=21,
        minute=40,
        session=2,
        coin={"pp": 1, "gp": 450, "ep": 0, "sp": 12, "cp": 7},
        loot=(LootItem("gem", "a blue quartz", 10), LootItem("magic", "a potion of healing", 400, "potion")),
    )
    storage.campaign_states.put(state)
    assert storage.campaign_states.get(campaign.id) == state
    storage.campaign_states.put(replace(state, day=4, loot=()))
    assert storage.campaign_states.get(campaign.id) == replace(state, day=4, loot=())
    with pytest.raises(KeyError):
        storage.campaign_states.put(CampaignState("cmp_000000000000"))


def _roll(beat: str, purpose: str, total: int, **key) -> Roll:
    return Roll(
        id=f"roll_{beat}{purpose}{total}",
        key=RollKey(beat=beat, purpose=purpose, actor=key.pop("actor", "chr_aaaaaaaaaaaa"), **key),
        notation="4d6dl",
        faces=(1, 3, 4, 6),
        kept=(3, 4, 6),
        modifier=0,
        total=total,
        at="2026-10-17T20:00:00+00:00",
    )


def test_roll_log_find_and_record(storage: Storage) -> None:
    _, campaign = _started_campaign(storage)
    _, other = _started_campaign(storage)
    first = _roll("b1", "save:spell", 13, target="mon_1", combat_round=2)
    assert storage.rolls.find(campaign.id, first.key) is None
    storage.rolls.record(campaign.id, first)
    assert storage.rolls.find(campaign.id, first.key) == first
    assert storage.rolls.find(other.id, first.key) is None
    assert storage.rolls.find(campaign.id, replace(first.key, combat_round=3)) is None
    assert storage.rolls.find(campaign.id, replace(first.key, target=None)) is None

    nobody = _roll("b1", "surprise:party", 2, actor=None)
    storage.rolls.record(campaign.id, nobody)
    assert storage.rolls.find(campaign.id, nobody.key) == nobody
    later = _roll("b2", "save:spell", 9)
    storage.rolls.record(campaign.id, later)
    assert storage.rolls.list(campaign.id) == [first, nobody, later]
    assert storage.rolls.list(campaign.id, beat="b2") == [later]
    with pytest.raises(KeyError):
        storage.rolls.record("cmp_000000000000", later)
    # A story row's rolls, by id (DEL-270): the campaign's own only, an unknown id left out.
    assert storage.rolls.get_many(campaign.id, [later.id, first.id, "roll_000000000000"]) == {
        later.id: later,
        first.id: first,
    }
    assert storage.rolls.get_many(other.id, [first.id]) == {} and storage.rolls.get_many(campaign.id, []) == {}


def test_events_append_and_list(storage: Storage) -> None:
    _, campaign = _started_campaign(storage)
    _, other = _started_campaign(storage)
    assert storage.events.list(campaign.id) == [] and storage.events.recent(campaign.id, 8) == []
    created = storage.events.append(campaign.id, "character_created", {"name": "Mira"}, session=1, beat="b1")
    assert (created.campaign_id, created.session, created.beat, created.type) == (
        campaign.id,
        1,
        "b1",
        "character_created",
    )
    assert created.data == {"name": "Mira"} and created.at
    storage.events.append(other.id, "moved", {"to": "nave"}, session=1, beat="b1")
    moved = storage.events.append(
        campaign.id, "moved", {"to": "crypt", "who": ["chr_aaaaaaaaaaaa"]}, session=1, beat="b2"
    )
    healed = storage.events.append(campaign.id, "heal", {"amount": 4}, session=2, beat="b3")
    assert created.id < moved.id < healed.id

    assert storage.events.list(campaign.id) == [created, moved, healed]
    assert storage.events.list(campaign.id, after=created.id) == [moved, healed]
    assert storage.events.list(campaign.id, types=["moved", "heal"], limit=1) == [moved]
    assert storage.events.list(campaign.id, beat="b2") == [moved]
    assert storage.events.list(campaign.id, beat="b3", types=["moved"]) == []
    assert storage.events.recent(campaign.id, 2) == [moved, healed]
    assert [e.type for e in storage.events.list(other.id)] == ["moved"]
    with pytest.raises(KeyError):
        storage.events.append("cmp_000000000000", "moved", {}, session=1, beat="b1")


def test_combats_one_live_per_campaign(storage: Storage) -> None:
    _, campaign = _started_campaign(storage)
    _, other = _started_campaign(storage)
    assert storage.combats.live(campaign.id) is None
    fight = storage.combats.create(campaign.id, "setup", {"round": 1, "combatants": {}})
    assert fight.startswith("cbt_")
    assert storage.combats.live(campaign.id) == (fight, {"round": 1, "combatants": {}})
    with pytest.raises(ValueError):
        storage.combats.create(campaign.id, "setup", {})
    elsewhere = storage.combats.create(other.id, "round", {"round": 4})
    storage.combats.save(fight, "round", {"round": 2})
    assert storage.combats.live(campaign.id) == (fight, {"round": 2})
    storage.combats.save(fight, "ended", {"round": 2, "phase": "ended"})
    assert storage.combats.live(campaign.id) is None
    assert storage.combats.get(fight) == {"round": 2, "phase": "ended"}
    again = storage.combats.create(campaign.id, "setup", {"round": 1})
    assert again != fight and storage.combats.live(campaign.id) == (again, {"round": 1})
    assert storage.combats.live(other.id) == (elsewhere, {"round": 4})
    with pytest.raises(KeyError):
        storage.combats.create("cmp_000000000000", "setup", {})
    with pytest.raises(KeyError):
        storage.combats.save("cbt_000000000000", "round", {})
    storage.campaigns.delete(campaign.id)
    assert storage.combats.get(again) is None


class Halfway(Exception):
    pass


def test_transaction_rolls_back_all_repos(storage: Storage) -> None:
    """Review Focus 3: a tool call that fails halfway leaves nothing behind, in any repository."""
    _, campaign = _started_campaign(storage)
    mira = storage.characters.create(campaign.id, "Mira", sheet=Sheet(hp_max=8), state=CharacterState(hp=8))
    before = storage.campaign_states.get(campaign.id)
    with pytest.raises(Halfway), storage.transaction():
        storage.characters.save(replace(mira, state=replace(mira.state, hp=2, xp=300)))
        storage.characters.create(campaign.id, "Tira", kind="npc")
        storage.campaign_states.put(
            replace(before, coin={**before.coin, "gp": 450}, loot=(LootItem("gem", "a ruby", 500),))
        )
        storage.rolls.record(campaign.id, _roll("b1", "treasure:A", 77))
        storage.events.append(campaign.id, "treasure_awarded", {"types": "A"}, session=1, beat="b1")
        storage.map_states.put(campaign.id, "crypt", {"characters": {}})
        assert storage.characters.get(mira.id).state.hp == 2  # reads inside see the writes
        assert len(storage.characters.list(campaign.id)) == 2
        raise Halfway("the loot write raised")

    assert storage.characters.list(campaign.id) == [mira]
    assert storage.campaign_states.get(campaign.id) == before
    assert storage.rolls.list(campaign.id) == []
    assert storage.events.list(campaign.id) == []
    assert storage.map_states.list(campaign.id) == {}


def test_transaction_commits_together_and_nests(storage: Storage) -> None:
    _, campaign = _started_campaign(storage)
    with storage.transaction():
        mira = storage.characters.create(campaign.id, "Mira")
        with storage.transaction():  # joins the outer one
            storage.events.append(campaign.id, "character_created", {"id": mira.id}, session=1, beat="b1")
    assert storage.characters.get(mira.id) == mira
    assert [e.type for e in storage.events.list(campaign.id)] == ["character_created"]

    with pytest.raises(Halfway), storage.transaction():
        storage.events.append(campaign.id, "moved", {}, session=1, beat="b2")
        with storage.transaction():
            storage.events.append(campaign.id, "moved", {}, session=1, beat="b2")
        raise Halfway("after the inner block")
    assert len(storage.events.list(campaign.id)) == 1

    storage.events.append(campaign.id, "log", {"text": "outside a transaction"}, session=1, beat="b3")
    assert len(storage.events.list(campaign.id)) == 2  # still autocommits


def test_delete_campaign_cascades_play_state(storage: Storage) -> None:
    _, campaign = _started_campaign(storage)
    _, other = _started_campaign(storage)
    for target in (campaign, other):
        storage.characters.create(target.id, "Mira", sheet=GARREK)
        storage.campaign_states.put(CampaignState(target.id, day=9))
        storage.rolls.record(target.id, replace(_roll("b1", "save:spell", 13), id=f"roll_{target.id}"))
        storage.events.append(target.id, "moved", {}, session=1, beat="b1")
    storage.campaigns.delete(campaign.id)
    assert storage.campaign_states.get(campaign.id) is None
    assert storage.rolls.list(campaign.id) == [] and storage.events.list(campaign.id) == []
    assert storage.campaign_states.get(other.id).day == 9
    assert len(storage.rolls.list(other.id)) == 1 and len(storage.events.list(other.id)) == 1


def test_notes_create_list_and_save(storage: Storage) -> None:
    _, campaign = _started_campaign(storage)
    _, other = _started_campaign(storage)
    secret = storage.notes.create(
        campaign.id, "secret", "The innkeeper reports to the cult.", tags=("motive",), related_to="innkeeper", session=2
    )
    assert secret.id.startswith("note_") and (secret.kind, secret.session, secret.revealed) == ("secret", 2, False)
    assert secret.tags == ("motive",) and secret.created_at and secret.created_at == secret.updated_at
    room = storage.notes.create(campaign.id, "room", "Horse tied here.", map_name="crypt", node="room.entry_hall")
    log = storage.notes.create(campaign.id, "log", "The party entered the crypt.")
    storage.notes.create(other.id, "secret", "Not this campaign's.")
    assert storage.notes.get(secret.id) == secret and storage.notes.get("note_000000000000") is None
    assert storage.notes.list(campaign.id) == [secret, room, log]
    assert storage.notes.list(campaign.id, kind="secret") == [secret]
    assert storage.notes.list(campaign.id, kind="room", map_name="crypt", node="room.entry_hall") == [room]
    assert storage.notes.list(campaign.id, kind="room", map_name="crypt", node="room.throne_chamber") == []
    saved = storage.notes.save(replace(secret, text="The innkeeper is the cult.", revealed=True, tags=()))
    assert storage.notes.get(secret.id) == saved and saved.revealed and saved.text == "The innkeeper is the cult."
    assert saved.created_at == secret.created_at
    with pytest.raises(KeyError):
        storage.notes.save(replace(secret, id="note_000000000000"))
    with pytest.raises(KeyError):
        storage.notes.create("cmp_000000000000", "log", "nowhere")
    assert isinstance(saved, Note)


def test_sessions_start_end_and_list(storage: Storage) -> None:
    _, campaign = _started_campaign(storage)
    assert storage.sessions.list(campaign.id) == [] and storage.sessions.get(campaign.id, 1) is None
    first = storage.sessions.start(campaign.id, 1, "Into the crypt")
    assert (first.number, first.title, first.ended_at, first.recap_md) == (1, "Into the crypt", None, None)
    assert first.started_at and isinstance(first, Session)
    ended = storage.sessions.end(campaign.id, 1, "They found the hidden crypt.")
    assert ended.recap_md == "They found the hidden crypt." and ended.ended_at
    second = storage.sessions.start(campaign.id, 2, "The ritualist")
    assert storage.sessions.list(campaign.id) == [ended, second]
    assert storage.sessions.get(campaign.id, 1) == ended
    with pytest.raises(KeyError):
        storage.sessions.end(campaign.id, 7, "no such session")
    with pytest.raises(KeyError):
        storage.sessions.start("cmp_000000000000", 1, "nowhere")
    storage.campaigns.delete(campaign.id)
    assert storage.sessions.list(campaign.id) == []


def test_campaign_activity_over_two_sessions(storage: Storage) -> None:
    _, campaign = _started_campaign(storage)
    assert storage.campaigns.activity(campaign.id) == CampaignActivity(last_played=None, sessions=0, playtime_s=0)
    with pytest.raises(KeyError):
        storage.campaigns.activity("cmp_000000000000")

    first = storage.sessions.start(campaign.id, 1, "Into the crypt")
    storage.sessions.end(campaign.id, 1, "They went in.")
    second = storage.sessions.start(campaign.id, 2, "The ritualist")
    started = datetime.fromisoformat(second.started_at)
    two_hours = (started + timedelta(hours=2)).isoformat()
    beat = storage.beats.open(campaign.id, [], status="running")
    storage.beats.save(replace(beat, status="done", closed_at=two_hours))
    storage.beats.open(campaign.id, [], status="running")  # not closed: it doesn't count

    activity = storage.campaigns.activity(campaign.id)
    ended = storage.sessions.get(campaign.id, 1)
    first_s = (datetime.fromisoformat(ended.ended_at) - datetime.fromisoformat(first.started_at)).total_seconds()
    assert activity.sessions == 2 and activity.last_played == two_hours
    # The open session counts up to its last closed beat; the ended one up to its end.
    assert activity.playtime_s == int(7200 + first_s)


def test_house_rules_and_bundles(storage: Storage) -> None:
    assert storage.house_rules.list() == [] and storage.house_rule_bundles.list() == []
    hp = storage.house_rules.create(title="Maximum HP", body_md="At level 1.", phases=["character-creation"])
    assert hp.id.startswith("hr_") and len(hp.id) == len("hr_") + 12
    assert (hp.kind, hp.phases, hp.ruleset, hp.setting, hp.subject, hp.enabled) == (
        "general",
        frozenset({"character-creation"}),
        None,
        None,
        None,
        True,
    )
    lizard = storage.house_rules.create(
        title="Lizardfolk",
        body_md="Bite 1d6.",
        kind="race",
        phases=["character-creation", "level-up"],
        ruleset="adnd2e",
        setting="greyhawk",
        subject="lizardfolk",
        enabled=False,
    )
    assert storage.house_rules.get(lizard.id) == lizard and storage.house_rules.get("hr_000000000000") is None
    assert storage.house_rules.list() == [hp, lizard]
    edited = replace(lizard, title="Lizard men", phases=frozenset({"combat"}), setting=None, enabled=True)
    assert storage.house_rules.save(edited) == edited and storage.house_rules.get(lizard.id) == edited
    with pytest.raises(KeyError):
        storage.house_rules.save(replace(edited, id="hr_000000000000"))

    table = storage.house_rule_bundles.create(title="My table", rule_ids=[lizard.id, hp.id])
    assert table.id.startswith("hb_") and table.rule_ids == (lizard.id, hp.id) and table.description_md == ""
    assert storage.house_rule_bundles.get(table.id) == table and storage.house_rule_bundles.list() == [table]
    reordered = replace(table, title="Usual", description_md="Tuesdays.", rule_ids=(hp.id, lizard.id))
    assert storage.house_rule_bundles.save(reordered) == reordered
    assert storage.house_rule_bundles.get(table.id) == reordered
    with pytest.raises(KeyError):
        storage.house_rule_bundles.create(title="Bad", rule_ids=["hr_000000000000"])
    with pytest.raises(KeyError):
        storage.house_rule_bundles.save(replace(reordered, rule_ids=("hr_000000000000",)))
    with pytest.raises(KeyError):
        storage.house_rule_bundles.save(Bundle("hb_000000000000", "Nobody's"))
    assert storage.house_rule_bundles.get(table.id) == reordered

    storage.house_rules.delete(hp.id)  # leaves every bundle
    assert storage.house_rules.list() == [edited]
    assert storage.house_rule_bundles.get(table.id).rule_ids == (lizard.id,)
    storage.house_rule_bundles.delete(table.id)
    assert storage.house_rule_bundles.list() == [] and storage.house_rules.list() == [edited]


def test_campaign_house_rules(storage: Storage) -> None:
    _, campaign = _started_campaign(storage)
    assert storage.campaign_house_rules.get(campaign.id) == ([], [])
    assert storage.campaign_house_rules.get("cmp_000000000000") is None
    a = storage.house_rules.create(title="A")
    b = storage.house_rules.create(title="B")
    table = storage.house_rule_bundles.create(title="Table", rule_ids=[a.id])
    other = storage.house_rule_bundles.create(title="Other")
    storage.campaign_house_rules.put(campaign.id, [other.id, table.id], [b.id, a.id])
    assert storage.campaign_house_rules.get(campaign.id) == ([other.id, table.id], [b.id, a.id])
    storage.campaign_house_rules.put(campaign.id, [table.id], [])
    assert storage.campaign_house_rules.get(campaign.id) == ([table.id], [])
    for bad in (("cmp_000000000000", [], []), (campaign.id, ["hb_000000000000"], []), (campaign.id, [], ["x"])):
        with pytest.raises(KeyError):
            storage.campaign_house_rules.put(*bad)
    assert storage.campaign_house_rules.get(campaign.id) == ([table.id], [])

    storage.campaign_house_rules.put(campaign.id, [table.id, other.id], [a.id, b.id])
    storage.house_rule_bundles.delete(other.id)
    storage.house_rules.delete(b.id)
    assert storage.campaign_house_rules.get(campaign.id) == ([table.id], [a.id])
    storage.campaigns.delete(campaign.id)
    assert storage.campaign_house_rules.get(campaign.id) is None
    assert storage.house_rule_bundles.get(table.id).rule_ids == (a.id,)  # the library outlives campaigns


def test_beats_one_current_per_campaign(storage: Storage) -> None:
    _, campaign = _started_campaign(storage)
    _, other = _started_campaign(storage)
    host = storage.seats.create(campaign.id, "Host", "en", "host", organiser=True, owner=True)
    act = {"player": host.id, "character_ids": [], "kind": "act", "text": "We wait."}
    assert storage.beats.current(campaign.id) is None
    first = storage.beats.open(campaign.id, [act], status="running")
    assert first.id.startswith("beat_") and first.number == 1 and first.status == "running"
    assert storage.beats.get(first.id) == first == storage.beats.current(campaign.id)
    assert first.submissions == (act,) and first.closed_at is None
    with pytest.raises(ValueError):
        storage.beats.open(campaign.id, [act])
    assert storage.beats.open(other.id, []).number == 1
    done = storage.beats.save(replace(first, status="done", closed_at="2026-10-17T20:00:00+00:00"))
    assert storage.beats.get(first.id) == done and storage.beats.current(campaign.id) is None
    second = storage.beats.open(campaign.id, [])
    assert second.number == 2
    # A break moves an open beat's opening on (DEL-199), and its deadline with it.
    moved = storage.beats.save(replace(second, opened_at="2026-10-17T21:00:00+00:00"))
    assert storage.beats.get(second.id) == moved and moved.opened_at == "2026-10-17T21:00:00+00:00"
    with pytest.raises(KeyError):
        storage.beats.open("cmp_000000000000", [])
    with pytest.raises(KeyError):
        storage.beats.save(replace(first, id="beat_000000000000"))
    assert storage.beats.get("beat_000000000000") is None


def test_beats_latest(storage: Storage) -> None:
    """The campaign's beat of the highest number, whatever its status (table voice and fixes Task D1)."""
    _, campaign = _started_campaign(storage)
    _, other = _started_campaign(storage)
    assert storage.beats.latest(campaign.id) is None
    first = storage.beats.open(campaign.id, [], status="running")
    assert storage.beats.latest(campaign.id) == first
    failed = storage.beats.save(replace(first, status="failed", closed_at="2026-10-25T20:00:00+00:00"))
    assert storage.beats.latest(campaign.id) == failed
    second = storage.beats.open(campaign.id, [])
    storage.beats.open(other.id, [])
    assert storage.beats.latest(campaign.id) == second
    assert storage.beats.latest("cmp_000000000000") is None


def test_story_put_append_and_list(storage: Storage) -> None:
    _, campaign = _started_campaign(storage)
    beat = storage.beats.open(campaign.id, [], status="running")
    acted = storage.story.append(campaign.id, beat.id, "player_act", {"text": "We go in."})
    assert acted.id.startswith("sty_") and acted.seq == 1 and acted.at and acted.beat_id == beat.id
    told = storage.story.put(StoryEntry("sty_aaaaaaaaaaaa", campaign.id, beat.id, 0, "dm_text", {"text": "Dark"}))
    assert told.seq == 2
    again = storage.story.put(replace(told, seq=0, payload={"text": "Dark and cold."}))
    assert again == replace(told, payload={"text": "Dark and cold."})
    asked = storage.story.append(campaign.id, None, "ask", {"question": "What's a kobold?"})
    assert storage.story.list(campaign.id) == [acted, again, asked]
    assert storage.story.list(campaign.id, limit=2) == [again, asked]
    assert storage.story.list(campaign.id, before_seq=asked.seq, limit=1) == [again]
    with pytest.raises(KeyError):
        storage.story.append("cmp_000000000000", None, "ask", {})


def test_dm_log_and_dm_sessions(storage: Storage) -> None:
    _, campaign = _started_campaign(storage)
    _, other = _started_campaign(storage)
    beat = storage.beats.open(campaign.id, [], status="running")
    first = storage.dm_log.append(campaign.id, beat.id, {"type": "system", "session_id": "s1"})
    storage.dm_log.append(other.id, None, {"type": "result"})
    storage.dm_log.append(campaign.id, None, {"type": "result"})
    assert first.raw_event_json == {"type": "system", "session_id": "s1"} and first.at
    assert [e.raw_event_json["type"] for e in storage.dm_log.list(campaign.id)] == ["system", "result"]
    assert storage.dm_log.list(campaign.id, beat.id) == [first]

    # Summed per beat in the order the beats began, each Ask a row of its own (DEL-172).
    storage.beats.save(replace(beat, status="done", closed_at="2026-10-17T20:00:00+00:00"))
    second = storage.beats.open(campaign.id, [], status="running")
    log = [
        (beat.id, {"type": "tool_call", "name": "roll"}),
        (beat.id, {"type": "usage", "input_tokens": 100, "output_tokens": 20, "cost_usd": 0.5}),
        (None, {"type": "ask", "usage": {"input_tokens": 7, "output_tokens": 3, "cost_usd": 0.01}}),
        (second.id, {"type": "usage", "input_tokens": 5, "output_tokens": 1}),
        (beat.id, {"type": "tool_call", "name": "move"}),
        (beat.id, {"type": "usage", "input_tokens": 50, "output_tokens": 10, "cost_usd": 0.25}),
    ]
    for beat_id, raw in log:
        storage.dm_log.append(campaign.id, beat_id, raw)
    costs = storage.dm_log.costs(campaign.id)
    assert [{k: v for k, v in row.items() if k not in ("at", "beat")} for row in costs] == [
        {"ask": False, "tools": 2, "input": 150, "output": 30, "cost": 0.75},
        {"ask": False, "tools": 0, "input": 0, "output": 0, "cost": None},
        {"ask": True, "tools": 0, "input": 7, "output": 3, "cost": 0.01},
        {"ask": False, "tools": 0, "input": 5, "output": 1, "cost": None},
    ]
    assert [row["beat"] for row in costs][:2] == [beat.id, ""] and costs[2]["beat"].startswith("ask-")
    assert costs[0]["at"] == first.at
    assert storage.dm_log.costs(other.id)[0]["beat"] == ""

    assert storage.dm_sessions.get(campaign.id) is None
    storage.dm_sessions.set(campaign.id, "claude-cli", "sess-1", 42_000)
    stored = storage.dm_sessions.get(campaign.id)
    assert {k: stored[k] for k in ("provider", "session_id", "context_tokens")} == {
        "provider": "claude-cli",
        "session_id": "sess-1",
        "context_tokens": 42_000,
    }
    assert stored["updated_at"]
    storage.dm_sessions.set(campaign.id, "claude-cli", None, 0)
    assert storage.dm_sessions.get(campaign.id)["session_id"] is None
    storage.dm_sessions.set(other.id, "fake", "f-1", 5)
    storage.dm_sessions.clear(campaign.id)
    assert storage.dm_sessions.get(campaign.id) is None and storage.dm_sessions.get(other.id)["session_id"] == "f-1"
    storage.dm_sessions.clear(campaign.id)
    with pytest.raises(KeyError):
        storage.dm_sessions.set("cmp_000000000000", "fake", None, 0)

    storage.story.append(campaign.id, beat.id, "player_act", {})
    storage.dm_sessions.set(campaign.id, "fake", "f-2", 1)
    storage.campaigns.delete(campaign.id)
    assert storage.beats.get(beat.id) is None and storage.story.list(campaign.id) == []
    assert storage.dm_log.list(campaign.id) == [] and storage.dm_sessions.get(campaign.id) is None
    assert len(storage.dm_log.list(other.id)) == 1


def test_play_settings(storage: Storage) -> None:
    _, campaign = _started_campaign(storage)
    _, other = _started_campaign(storage)
    assert storage.play_settings.get(campaign.id) is None
    storage.play_settings.put(campaign.id, {"tone": "horror", "detail": 1, "effort": None, "model": None})
    storage.play_settings.put(other.id, {"tone": "heroic", "detail": 2})
    storage.play_settings.put(campaign.id, {"tone": "grimdark", "detail": 0, "effort": "high", "model": "sonnet"})
    assert storage.play_settings.get(campaign.id) == {
        "tone": "grimdark",
        "detail": 0,
        "effort": "high",
        "model": "sonnet",
    }
    with pytest.raises(KeyError):
        storage.play_settings.put("cmp_000000000000", {})
    storage.campaigns.delete(campaign.id)
    assert storage.play_settings.get(campaign.id) is None and storage.play_settings.get(other.id)["tone"] == "heroic"


def test_table_sessions(storage: Storage) -> None:
    """The table's session state (DEL-199): one row per campaign, replaced whole, its JSON kept as it was put, and
    gone with its campaign."""
    _, campaign = _started_campaign(storage)
    _, other = _started_campaign(storage)
    assert storage.table_sessions.get(campaign.id) is None
    storage.table_sessions.put(TableSession(campaign.id, "gathering"))
    assert storage.table_sessions.get(campaign.id) == TableSession(campaign.id, "gathering")
    on_break = TableSession(
        campaign.id,
        "break",
        since="2026-10-27T20:00:00+00:00",
        absent={"chr_1": "in_character", "chr_2": "out"},
        hands={"seat_1": {"at": "2026-10-27T20:05:00+00:00", "point": "A question about the map"}},
        break_at="2026-10-27T20:10:00+00:00",
        away={"seat_2": {"at": "2026-10-27T20:06:00+00:00", "part": "hold_back"}},
    )
    storage.table_sessions.put(on_break)
    storage.table_sessions.put(TableSession(other.id, "playing"))
    assert storage.table_sessions.get(campaign.id) == on_break
    assert storage.table_sessions.get(other.id).state == "playing"
    with pytest.raises(KeyError):
        storage.table_sessions.put(TableSession("cmp_000000000000", "playing"))
    storage.campaigns.delete(campaign.id)
    assert storage.table_sessions.get(campaign.id) is None and storage.table_sessions.get(other.id) is not None


def test_module_draft(storage: Storage) -> None:
    assert storage.modules.create("Ready").draft is False
    draft = storage.modules.create("From a book", {"level": 3}, draft=True)
    assert draft.draft is True and storage.modules.get(draft.id).draft is True
    assert [m.draft for m in storage.modules.list()] == [False, True]
    ready = storage.modules.set_draft(draft.id, False)
    assert ready.draft is False and storage.modules.get(draft.id).draft is False
    with pytest.raises(KeyError):
        storage.modules.set_draft("mod_000000000000", False)


def test_conversions_one_running_newest_first(storage: Storage) -> None:
    assert storage.conversions.get("cnv_000000000000") is None
    assert storage.conversions.running() is None and storage.conversions.list() == []

    first = storage.conversions.create("pdf", "The Kobold Caves", "draft")
    assert first.id.startswith("cnv_") and len(first.id) == len("cnv_") + 12
    assert (first.kind, first.title, first.mode, first.status) == ("pdf", "The Kobold Caves", "draft", "running")
    assert (first.step, first.done, first.total, first.module_id, first.warnings, first.error) == (
        "",
        0,
        0,
        None,
        [],
        None,
    )
    assert first.created_at and first.updated_at
    assert storage.conversions.get(first.id) == first and storage.conversions.running() == first
    with pytest.raises(ValueError):
        storage.conversions.create("generate", "Kobolds", "ready")

    module = storage.modules.create("The Kobold Caves")
    warnings = [
        {"code": "map-sketched", "message": "Sketched from the room key: an invented layout.", "ref": "map:caves"}
    ]
    done = replace(first, status="done", step="maps", done=1, total=1, module_id=module.id, warnings=warnings)
    saved = storage.conversions.save(done)
    assert saved.updated_at >= first.updated_at
    assert storage.conversions.get(first.id) == saved
    assert (saved.status, saved.module_id, saved.warnings) == ("done", module.id, warnings)
    assert storage.conversions.running() is None

    second = storage.conversions.create("generate", "Kobolds", "ready")
    storage.conversions.save(replace(second, status="failed", error="claude stopped"))
    assert [c.id for c in storage.conversions.list()] == [second.id, first.id]
    assert [c.id for c in storage.conversions.list(limit=1)] == [second.id]
    with pytest.raises(KeyError):
        storage.conversions.save(replace(first, id="cnv_000000000000"))

    storage.modules.delete(module.id)
    assert storage.conversions.get(first.id).module_id is None, "a deleted module leaves its conversion"


def test_conversions_paused_oldest_first(storage: Storage) -> None:
    assert storage.conversions.paused() == []
    first = storage.conversions.create("pdf", "Saltmarsh", "ready", target={"thorough": True})
    first = storage.conversions.save(replace(first, status="paused"))
    second = storage.conversions.create("pdf", "Danger at Dunwater", "ready", target={"thorough": True})
    second = storage.conversions.save(replace(second, status="paused"))
    done = storage.conversions.create("generate", "Kobolds", "ready")
    storage.conversions.save(replace(done, status="done"))

    assert [c.id for c in storage.conversions.paused()] == [first.id, second.id]
    assert storage.conversions.running() is None, "a paused job holds no slot"


def test_conversions_queue_oldest_first_and_its_switch(storage: Storage) -> None:
    """The conversion queue (thorough conversion, owner addition 2026-10-23): a job made `queued` holds no slot, the
    queue lists them oldest first, a paused job put back in it keeps its place by age, and the queue's switch is
    stored."""
    assert storage.conversions.queued() == [] and storage.conversions.queue_paused() is False
    running = storage.conversions.create("pdf", "Saltmarsh", "ready")
    first = storage.conversions.create("pdf", "Danger at Dunwater", "ready", status="queued")
    second = storage.conversions.create("pdf", "The Final Enemy", "draft", status="queued", target={"thorough": True})
    assert (first.status, second.status, second.target) == ("queued", "queued", {"thorough": True})
    assert storage.conversions.running() == running, "a queued job holds no slot"
    assert [c.id for c in storage.conversions.queued()] == [first.id, second.id]
    storage.conversions.save(replace(running, status="paused"))
    storage.conversions.save(replace(storage.conversions.get(running.id), status="queued"))
    assert [c.id for c in storage.conversions.queued()] == [running.id, first.id, second.id], "by age"
    with pytest.raises(ValueError):
        storage.conversions.create("pdf", "Wrong", "ready", status="done")  # type: ignore[arg-type]

    storage.conversions.set_queue_paused(True)
    assert storage.conversions.queue_paused() is True
    storage.conversions.set_queue_paused(False)
    assert storage.conversions.queue_paused() is False
    assert storage.settings.load() == {}, "the switch isn't one of the app's settings"


def test_seats_and_controllers(storage: Storage) -> None:
    _, campaign = _started_campaign(storage)
    _, other = _started_campaign(storage)
    assert campaign.join_token and campaign.join_token != other.join_token
    assert storage.seats.get("seat_000000000000") is None and storage.seats.owner_seat(campaign.id) is None

    host = storage.seats.create(campaign.id, "Host", "en", "host", organiser=True, owner=True)
    assert host.id.startswith("seat_") and len(host.id) == len("seat_") + 12
    assert (host.campaign_id, host.name, host.language, host.role) == (campaign.id, "Host", "en", "host")
    assert host.organiser and host.owner and host.joined_at and host.left_at is None
    assert storage.seats.get(host.id) == host == storage.seats.owner_seat(campaign.id)
    with pytest.raises(ValueError):
        storage.seats.create(campaign.id, "Host again", "en", "host", owner=True)

    ana = storage.seats.create(campaign.id, "Ana", "nl", "player", token_hash="a" * 64)
    assert not ana.organiser and not ana.owner
    assert storage.seats.by_token_hash("a" * 64) == ana and storage.seats.by_token_hash("b" * 64) is None
    with pytest.raises(ValueError):
        storage.seats.create(other.id, "Bo", "en", "player", token_hash="a" * 64)
    with pytest.raises(KeyError):
        storage.seats.create("cmp_000000000000", "Nobody", "en", "player")
    assert storage.seats.list(campaign.id) == [host, ana] and storage.seats.list(other.id) == []

    left = storage.seats.save(replace(ana, role="cohost", organiser=True, left_at="2026-10-18T20:00:00+00:00"))
    assert storage.seats.get(ana.id) == left and left.role == "cohost" and left.organiser
    with pytest.raises(KeyError):
        storage.seats.save(replace(ana, id="seat_000000000000"))

    mira = storage.characters.create(campaign.id, "Mira")
    assert mira.controller_id is None
    storage.seats.set_controller(mira.id, host.id)
    assert storage.characters.get(mira.id).controller_id == host.id
    assert storage.seats.controlled(host.id) == [mira.id] and storage.seats.controlled(ana.id) == []
    saved = storage.characters.save(replace(storage.characters.get(mira.id), name="Mira the Bold"))
    assert storage.characters.get(mira.id).controller_id == host.id == saved.controller_id, "saving keeps it"
    stranger = storage.seats.create(other.id, "Stranger", "en", "player")
    with pytest.raises(KeyError):
        storage.seats.set_controller(mira.id, stranger.id)  # a seat of another campaign
    with pytest.raises(KeyError):
        storage.seats.set_controller("chr_000000000000", host.id)
    storage.seats.set_controller(mira.id, None)
    assert storage.seats.controlled(host.id) == []

    storage.seats.set_controller(mira.id, host.id)
    storage.campaigns.delete(campaign.id)
    assert storage.seats.get(host.id) is None and storage.seats.list(campaign.id) == []


def test_account_round_trip(storage: Storage) -> None:
    assert storage.accounts.get("acc_000000000000") is None and storage.accounts.list() == []
    ana = storage.accounts.create("ana", Profile("Ana", avatar_emblem="lion"))
    assert ana.id.startswith("acc_") and len(ana.id) == len("acc_") + 12
    assert (ana.username, ana.profile, ana.organiser, ana.owner) == (
        "ana",
        Profile("Ana", avatar_emblem="lion"),
        False,
        False,
    )
    assert ana.created_at and ana.disabled_at is None and ana.external_id is None and not ana.has_password
    assert storage.accounts.get(ana.id) == ana == storage.accounts.by_username("ana")
    assert storage.accounts.by_username("ANA") is None, "the username is looked up as given: folded already"
    assert storage.accounts.by_external_id("kc-sub-1") is None
    bo = storage.accounts.create("bo", Profile("Bo"), organiser=True)
    assert bo.organiser and not bo.owner and storage.accounts.list() == [ana, bo]
    assert storage.accounts.has_owner() is False  # an EXISTS, not a read of every account (DEL-172)
    storage.accounts.set_owner(bo.id, True)
    assert storage.accounts.has_owner() is True
    storage.accounts.set_owner(bo.id, False)
    carla = storage.accounts.create("carla", Profile("Carla"), owner=True)
    assert carla.owner and not carla.organiser and storage.accounts.get(carla.id) == carla

    profile = Profile(
        "Ana the Bold", "she/her", None, "f" * 64, "ember", "nl", "I like maps.", "Late on Tuesdays.", "Europe/Brussels"
    )
    saved = storage.accounts.save_profile(ana.id, profile)
    assert saved.profile == profile and storage.accounts.get(ana.id) == saved
    assert storage.accounts.set_organiser(ana.id, True).organiser and storage.accounts.get(ana.id).organiser
    assert storage.accounts.set_owner(ana.id, True).owner and storage.accounts.get(ana.id).owner
    assert not storage.accounts.set_owner(ana.id, False).owner and storage.accounts.get(ana.id).organiser
    disabled = storage.accounts.set_disabled(ana.id, "2026-10-24T12:00:00+00:00")
    assert disabled.disabled_at == "2026-10-24T12:00:00+00:00" == storage.accounts.get(ana.id).disabled_at
    assert storage.accounts.set_disabled(ana.id, None).disabled_at is None
    for change in (
        lambda: storage.accounts.save_profile("acc_000000000000", profile),
        lambda: storage.accounts.set_organiser("acc_000000000000", True),
        lambda: storage.accounts.set_owner("acc_000000000000", True),
        lambda: storage.accounts.set_disabled("acc_000000000000", None),
        lambda: storage.accounts.set_password_hash("acc_000000000000", "scrypt$x"),
    ):
        with pytest.raises(KeyError):
            change()


def test_a_pending_account_is_approved_or_deleted(storage: Storage) -> None:
    """A sign-up waits for approval (DEL-156): `pending`, with the note it came with, until it is approved, or
    deleted when it is rejected, its username free again. Only a pending account is ever deleted."""
    ana = storage.accounts.create("ana", Profile("Ana"))
    assert not ana.pending and ana.request_note == ""
    cy = storage.accounts.create("cy", Profile("Cy"), pending=True, request_note="Bo's friend from Tuesday.")
    assert cy.pending and cy.request_note == "Bo's friend from Tuesday." and storage.accounts.get(cy.id) == cy
    assert storage.accounts.list() == [ana, cy]
    approved = storage.accounts.approve(cy.id)
    assert not approved.pending and approved.request_note == "Bo's friend from Tuesday." == storage.accounts.get(cy.id).request_note
    assert not storage.accounts.get(cy.id).pending

    dee = storage.accounts.create("dee", Profile("Dee"), pending=True)
    assert storage.accounts.delete_pending(dee.id) is True
    assert storage.accounts.get(dee.id) is None and storage.accounts.by_username("dee") is None
    assert storage.accounts.create("dee", Profile("Dee again"), pending=True).username == "dee", "the name is free"
    assert storage.accounts.delete_pending(ana.id) is False and storage.accounts.get(ana.id) == ana, "not pending: kept"
    assert storage.accounts.delete_pending("acc_000000000000") is False
    with pytest.raises(KeyError):
        storage.accounts.approve("acc_000000000000")


def test_identities_are_one_account_s_and_one_per_provider(storage: Storage) -> None:
    """An outside identity (DEL-206) is found by its provider and subject; it is one account's, and an account has one
    per provider. Deleting the account unlinks its identities."""
    ana = storage.accounts.create("ana", Profile("Ana"))
    bo = storage.accounts.create("bo", Profile("Bo"), pending=True)
    google = Identity("google", "1083", ana.id, "ana@example.org", "2026-10-27T10:00:00+00:00")
    assert storage.account_identities.get("google", "1083") is None
    assert storage.account_identities.add(google) == google
    assert storage.account_identities.get("google", "1083") == google
    assert storage.account_identities.get("other", "1083") is None
    with pytest.raises(ValueError):
        storage.account_identities.add(Identity("google", "1083", bo.id, "", "2026-10-27T10:01:00+00:00"))
    with pytest.raises(ValueError):
        storage.account_identities.add(Identity("google", "2222", ana.id, "", "2026-10-27T10:01:00+00:00"))
    with pytest.raises(ValueError):
        storage.account_identities.add(Identity("google", "3333", "acc_000000000000", "", "2026-10-27T10:01:00+00:00"))
    microsoft = storage.account_identities.add(Identity("microsoft", "m-1", ana.id, "", "2026-10-27T10:02:00+00:00"))
    assert storage.account_identities.list(ana.id) == [google, microsoft]
    assert storage.account_identities.remove(ana.id, "microsoft") is True
    assert storage.account_identities.remove(ana.id, "microsoft") is False
    assert storage.account_identities.list(ana.id) == [google]

    storage.account_identities.add(Identity("google", "4444", bo.id, "", "2026-10-27T10:03:00+00:00"))
    assert storage.accounts.delete_pending(bo.id) is True
    assert storage.account_identities.get("google", "4444") is None, "gone with its account"


def test_join_requests(storage: Storage) -> None:
    """A request to join a table (DEL-204) is an account's at a campaign: one pending per account and table, any
    number decided. The account's are read newest first, the table's oldest first; a save stores the status, the
    thread, when it was decided and the seat it made. It goes with its campaign."""
    _, campaign = _started_campaign(storage)
    _, other = _started_campaign(storage)
    ana = storage.accounts.create("ana", Profile("Ana"))
    bo = storage.accounts.create("bo", Profile("Bo"))
    note = {"from": "player", "name": "Ana", "text": "Hi!", "at": "2026-10-27T10:00:00+00:00"}
    assert storage.join_requests.get("jrq_000000000000") is None

    asked = storage.join_requests.create(campaign.id, ana.id, (note,), "2026-10-27T10:00:00+00:00")
    assert asked.id.startswith("jrq_") and len(asked.id) == len("jrq_") + 12
    assert (asked.campaign_id, asked.account_id, asked.status) == (campaign.id, ana.id, "pending")
    assert asked.messages == (note,)
    assert (asked.created_at, asked.decided_at, asked.seat_id) == ("2026-10-27T10:00:00+00:00", None, None)
    assert storage.join_requests.get(asked.id) == asked
    assert asked.role == "player", "a player's request unless it says otherwise"
    watching = storage.join_requests.create(other.id, bo.id, (), "2026-10-27T10:01:00+00:00", role="observer")
    assert storage.join_requests.get(watching.id).role == "observer"
    with pytest.raises(ValueError):
        storage.join_requests.create(campaign.id, ana.id, (), "2026-10-27T10:01:00+00:00")
    with pytest.raises(KeyError):
        storage.join_requests.create("cmp_000000000000", ana.id, (), "2026-10-27T10:01:00+00:00")
    with pytest.raises(KeyError):
        storage.join_requests.create(campaign.id, "acc_000000000000", (), "2026-10-27T10:01:00+00:00")

    elsewhere = storage.join_requests.create(other.id, ana.id, (), "2026-10-27T10:02:00+00:00")
    bos = storage.join_requests.create(campaign.id, bo.id, (), "2026-10-27T10:03:00+00:00")
    assert storage.join_requests.of_account(ana.id) == [elsewhere, asked]
    assert storage.join_requests.of_campaign(campaign.id) == [asked, bos]

    seat = storage.seats.create(campaign.id, "Ana", "en", "player", account_id=ana.id)
    reply = {"from": "host", "name": "Host", "text": "Welcome.", "at": "2026-10-27T10:04:00+00:00"}
    accepted = replace(
        asked, status="accepted", messages=(note, reply), decided_at="2026-10-27T10:05:00+00:00", seat_id=seat.id
    )
    assert storage.join_requests.save(accepted) == accepted == storage.join_requests.get(asked.id)
    with pytest.raises(KeyError):
        storage.join_requests.save(replace(asked, id="jrq_000000000000"))
    again = storage.join_requests.create(campaign.id, ana.id, (), "2026-10-27T11:00:00+00:00")
    assert again.status == "pending", "asking again once the last was decided"
    assert storage.join_requests.of_account(ana.id) == [again, elsewhere, accepted]

    storage.campaigns.delete(other.id)
    assert storage.join_requests.get(elsewhere.id) is None, "gone with its campaign"


def test_username_in_use_is_value_error(storage: Storage) -> None:
    storage.accounts.create("ana", Profile("Ana"))
    with pytest.raises(ValueError):
        storage.accounts.create("ana", Profile("Another Ana"))
    assert [account.username for account in storage.accounts.list()] == ["ana"]


def test_password_hash_only_through_its_methods(storage: Storage) -> None:
    ana = storage.accounts.create("ana", Profile("Ana"))
    assert storage.accounts.password_hash(ana.id) is None and storage.accounts.password_hash("acc_000000000000") is None
    storage.accounts.set_password_hash(ana.id, "scrypt$1024$8$1$c2FsdA$a2V5")
    assert storage.accounts.password_hash(ana.id) == "scrypt$1024$8$1$c2FsdA$a2V5"
    account = storage.accounts.get(ana.id)
    assert account.has_password and storage.accounts.by_username("ana").has_password
    assert "scrypt" not in repr(asdict(account)) and "scrypt" not in repr(storage.accounts.list())


def test_link_used_once(storage: Storage) -> None:
    ana = storage.accounts.create("ana", Profile("Ana"))
    link = AccountLink(ana.id, "set-password", "2026-10-24T12:00:00+00:00", "2026-10-25T12:00:00+00:00")
    assert storage.account_links.get("a" * 64) is None
    storage.account_links.put("a" * 64, link)
    assert storage.account_links.get("a" * 64) == link
    assert storage.account_links.use("a" * 64, "2026-10-24T13:00:00+00:00") is True
    assert storage.account_links.get("a" * 64).used_at == "2026-10-24T13:00:00+00:00"
    assert storage.account_links.use("a" * 64, "2026-10-24T14:00:00+00:00") is False
    assert storage.account_links.get("a" * 64).used_at == "2026-10-24T13:00:00+00:00", "the first use stays"
    assert storage.account_links.use("b" * 64, "2026-10-24T14:00:00+00:00") is False

    storage.account_links.put("c" * 64, replace(link, kind="reset-password"))
    storage.account_links.drop_unused(ana.id)
    assert storage.account_links.get("c" * 64) is None, "the unused one is gone"
    assert storage.account_links.get("a" * 64) is not None, "the used one stays"


def test_login_sessions_round_trip(storage: Storage) -> None:
    ana = storage.accounts.create("ana", Profile("Ana"))
    bo = storage.accounts.create("bo", Profile("Bo"))
    first = storage.login_sessions.create(ana.id, "a" * 64, "Firefox", "192.0.2.7", "2026-10-24T12:00:00+00:00")
    assert first.id.startswith("lgn_") and first == LoginSession(
        first.id, ana.id, "2026-10-24T12:00:00+00:00", "2026-10-24T12:00:00+00:00", "Firefox", "192.0.2.7"
    )
    assert storage.login_sessions.by_token_hash("a" * 64) == first
    assert storage.login_sessions.by_token_hash("b" * 64) is None
    second = storage.login_sessions.create(ana.id, "b" * 64, "", "", "2026-10-24T12:01:00+00:00")
    third = storage.login_sessions.create(ana.id, "c" * 64, "", "", "2026-10-24T12:02:00+00:00")
    theirs = storage.login_sessions.create(bo.id, "d" * 64, "", "", "2026-10-24T12:03:00+00:00")
    storage.login_sessions.touch(first.id, "2026-10-24T13:00:00+00:00")
    listed = storage.login_sessions.list(ana.id)
    assert [s.id for s in listed] == [first.id, third.id, second.id], "newest use first"
    assert listed[0].last_used_at == "2026-10-24T13:00:00+00:00"

    storage.login_sessions.end(second.id)
    assert storage.login_sessions.by_token_hash("b" * 64) is None
    storage.login_sessions.end_all(ana.id, but=first.id)
    assert [s.id for s in storage.login_sessions.list(ana.id)] == [first.id]
    storage.login_sessions.end_all(ana.id)
    assert storage.login_sessions.list(ana.id) == []
    assert storage.login_sessions.list(bo.id) == [theirs], "another account's sessions stay"
    with pytest.raises(ValueError):
        storage.login_sessions.create(bo.id, "d" * 64, "", "", "2026-10-24T12:04:00+00:00")


def test_an_account_s_seat_has_no_token(storage: Storage) -> None:
    """Keeping a seat (saving it with an account) drops its token in the same save (audit-auth finding 2)."""
    _, campaign = _started_campaign(storage)
    ana = storage.accounts.create("ana", Profile("Ana"))
    seat = storage.seats.create(campaign.id, "Bo", "en", "player", token_hash="a" * 64)
    storage.seats.save(replace(seat, name="Bob"))
    assert storage.seats.by_token_hash("a" * 64) == replace(seat, name="Bob"), "a seat without an account keeps it"
    kept = storage.seats.save(replace(seat, account_id=ana.id))
    assert storage.seats.by_token_hash("a" * 64) is None and storage.seats.get(seat.id) == kept


def test_one_live_seat_per_account_and_campaign(storage: Storage) -> None:
    _, campaign = _started_campaign(storage)
    _, other = _started_campaign(storage)
    ana = storage.accounts.create("ana", Profile("Ana"))
    seat = storage.seats.create(campaign.id, "Ana", "en", "player", account_id=ana.id)
    assert seat.account_id == ana.id and storage.seats.get(seat.id) == seat
    with pytest.raises(ValueError):
        storage.seats.create(campaign.id, "Ana again", "en", "player", account_id=ana.id)
    elsewhere = storage.seats.create(other.id, "Ana", "en", "player", account_id=ana.id)
    assert elsewhere.account_id == ana.id, "one live seat per table, not per install"
    storage.seats.create(campaign.id, "Bo", "en", "player")
    storage.seats.create(campaign.id, "Carla", "en", "player")  # seats without an account aren't limited

    storage.seats.save(replace(seat, left_at="2026-10-24T12:00:00+00:00"))
    again = storage.seats.create(campaign.id, "Ana", "en", "player", account_id=ana.id)
    assert again.id != seat.id and again.account_id == ana.id
    with pytest.raises(ValueError):
        storage.seats.save(replace(seat, left_at=None))  # a seat that left can't come back beside the live one


def test_for_account_and_of_account(storage: Storage) -> None:
    _, campaign = _started_campaign(storage)
    _, other = _started_campaign(storage)
    ana = storage.accounts.create("ana", Profile("Ana"))
    bo = storage.accounts.create("bo", Profile("Bo"))
    assert storage.seats.for_account(ana.id, campaign.id) is None and storage.seats.of_account(ana.id) == []
    first = storage.seats.create(campaign.id, "Ana", "en", "player", account_id=ana.id)
    second = storage.seats.create(other.id, "Ana", "nl", "observer", account_id=ana.id)
    storage.seats.create(campaign.id, "Bo", "en", "player", account_id=bo.id)
    assert storage.seats.for_account(ana.id, campaign.id) == first
    assert storage.seats.for_account(ana.id, other.id) == second
    assert storage.seats.of_account(ana.id) == [first, second]

    left = storage.seats.save(replace(first, left_at="2026-10-24T12:00:00+00:00"))
    assert storage.seats.get(first.id) == left and left.account_id == ana.id, "save keeps the account"
    assert storage.seats.for_account(ana.id, campaign.id) is None
    assert storage.seats.of_account(ana.id) == [second]
    moved = storage.seats.save(replace(second, account_id=bo.id))
    assert storage.seats.get(second.id).account_id == bo.id == moved.account_id, "save stores account_id"
    assert storage.seats.of_account(ana.id) == []


def test_join_tokens(storage: Storage) -> None:
    _, campaign = _started_campaign(storage)
    _, other = _started_campaign(storage)
    assert storage.campaigns.by_join_token(campaign.join_token) == campaign
    assert storage.campaigns.by_join_token("no-such-token") is None and storage.campaigns.by_join_token("") is None

    renewed = storage.campaigns.new_join_token(campaign.id)
    assert renewed.join_token and renewed.join_token not in (campaign.join_token, other.join_token)
    assert renewed == replace(campaign, join_token=renewed.join_token) == storage.campaigns.get(campaign.id)
    assert storage.campaigns.by_join_token(campaign.join_token) is None, "the old link stops working"
    assert storage.campaigns.by_join_token(renewed.join_token) == renewed
    with pytest.raises(KeyError):
        storage.campaigns.new_join_token("cmp_000000000000")


def test_campaign_state_keeps_the_world(storage: Storage) -> None:
    _, campaign = _started_campaign(storage)
    state = CampaignState(
        campaign.id,
        day=12,
        start_date=StartDate(576, 99),
        weather=(Weather(12, "forest", "light rain", "-1 to missiles", 0.75),),
        world=WorldPosition("greyhawk-region", 12.5, 40.0, at="Greyhawk"),
    )
    storage.campaign_states.put(state)
    assert storage.campaign_states.get(campaign.id) == state
    storage.campaign_states.put(replace(state, world=None, weather=()))
    assert storage.campaign_states.get(campaign.id) == replace(state, world=None, weather=())


def test_factions_and_clocks(storage: Storage) -> None:
    _, campaign = _started_campaign(storage)
    _, other = _started_campaign(storage)
    assert storage.factions.get(campaign.id, "circle") is None and storage.factions.list(campaign.id) == []

    circle = Faction(campaign.id, "circle", "The Circle of Eight", alignment="N", goals="Balance", scope="regional")
    assert (circle.known, circle.strength, circle.reputation, circle.source_ref) == (False, 100, 0, None)
    assert storage.factions.put(circle) == circle
    known = storage.factions.put(Faction(campaign.id, "guild", "Thieves' Guild", known=True, notes_md="SECRET"))
    storage.factions.put(Faction(other.id, "circle", "Another circle"))
    assert storage.factions.get(campaign.id, "circle") == circle
    assert storage.factions.list(campaign.id) == [circle, known]
    assert storage.factions.list(campaign.id, known=True) == [known]
    hurt = storage.factions.put(replace(circle, strength=60, reputation=-25, source_ref="faction:circle"))
    assert storage.factions.get(campaign.id, "circle") == hurt and storage.factions.list(campaign.id)[0] == hurt
    with pytest.raises(KeyError):
        storage.factions.put(Faction("cmp_000000000000", "circle", "Nowhere"))

    assert storage.clocks.get(1) is None
    march = storage.clocks.add(
        Clock(0, campaign.id, "The orcs march", "countdown", faction_id="circle", days_remaining=3, started_day=2)
    )
    assert march.id > 0 and storage.clocks.get(march.id) == march
    plot = storage.clocks.add(Clock(0, campaign.id, "The plot", "progress", segments=6, filled=1, on_complete="X"))
    elsewhere = storage.clocks.add(Clock(0, other.id, "Elsewhere", "countdown", days_remaining=9))
    assert len({march.id, plot.id, elsewhere.id}) == 3
    assert storage.clocks.list(campaign.id) == [march, plot]
    assert storage.clocks.list(campaign.id, faction_id="circle") == [march]
    done = storage.clocks.put(replace(march, days_remaining=0, done_day=5))
    assert storage.clocks.get(march.id) == done
    assert storage.clocks.list(campaign.id, running=True) == [plot]
    assert storage.clocks.list(campaign.id, running=False) == [done]
    with pytest.raises(KeyError):
        storage.clocks.put(replace(march, id=99999))
    with pytest.raises(KeyError):
        storage.clocks.add(Clock(0, "cmp_000000000000", "Nowhere", "countdown", days_remaining=1))

    storage.factions.delete(campaign.id, "circle")
    assert storage.factions.get(campaign.id, "circle") is None and storage.factions.get(other.id, "circle")
    assert storage.clocks.get(march.id).faction_id is None, "a deleted faction's clocks stay, unowned"
    storage.factions.delete(campaign.id, "circle")
    storage.clocks.delete(plot.id)
    assert storage.clocks.list(campaign.id) == [storage.clocks.get(march.id)]
    storage.clocks.delete(plot.id)

    storage.campaigns.delete(campaign.id)
    assert storage.factions.list(campaign.id) == [] and storage.clocks.get(march.id) is None
    assert [c.label for c in storage.clocks.list(other.id)] == ["Elsewhere"] and storage.factions.list(other.id)


def test_quests_and_campaign_facts(storage: Storage) -> None:
    _, campaign = _started_campaign(storage)
    _, other = _started_campaign(storage)
    assert storage.quests.get(campaign.id, "rescue") is None and storage.quests.list(campaign.id) == []
    rescue = Quest(
        campaign.id,
        "rescue",
        "Rescue the miller",
        giver="npc:reeve",
        stakes="The mill burns",
        related=("npc:miller", "place:mill"),
        log=(QuestNote(2, "Taken north.", known=True), QuestNote(3, "SECRET-XYZZY", known=False)),
        notes_md="The reeve lies.",
        source_ref="quest:rescue",
    )
    assert (rescue.status, rescue.known, rescue.scope) == ("available", False, "local")
    assert storage.quests.put(rescue) == rescue
    hunt = storage.quests.put(Quest(campaign.id, "hunt", "The hunt", status="active", known=True, started_day=4))
    storage.quests.put(Quest(other.id, "rescue", "Another rescue"))
    assert storage.quests.get(campaign.id, "rescue") == rescue
    assert storage.quests.list(campaign.id) == [rescue, hunt]
    assert storage.quests.list(campaign.id, status="active") == [hunt]
    assert storage.quests.list(campaign.id, known=False) == [rescue]
    ended = storage.quests.put(replace(hunt, status="complete", ended_day=9))
    assert storage.quests.get(campaign.id, "hunt") == ended
    with pytest.raises(KeyError):
        storage.quests.put(Quest("cmp_000000000000", "rescue", "Nowhere"))
    storage.quests.delete(campaign.id, "hunt")
    assert storage.quests.list(campaign.id) == [rescue]
    storage.quests.delete(campaign.id, "hunt")

    assert storage.campaign_facts.get(1) is None and storage.campaign_facts.list(campaign.id) == []
    fact = storage.campaign_facts.add(CampaignFact(0, campaign.id, "The miller owes the reeve 40 gp.", "npc", 3))
    assert fact.id > 0 and storage.campaign_facts.get(fact.id) == fact
    bridge = storage.campaign_facts.add(CampaignFact(0, campaign.id, "The north bridge is out.", "place", 4))
    storage.campaign_facts.add(CampaignFact(0, other.id, "The miller is elsewhere.", "npc", 1))
    assert storage.campaign_facts.list(campaign.id) == [fact, bridge]
    assert storage.campaign_facts.list(campaign.id, query="MILLER") == [fact]
    assert storage.campaign_facts.list(campaign.id, category="place") == [bridge]
    with pytest.raises(KeyError):
        storage.campaign_facts.add(CampaignFact(0, "cmp_000000000000", "Nowhere"))

    storage.campaigns.delete(campaign.id)
    assert storage.quests.list(campaign.id) == [] and storage.campaign_facts.get(fact.id) is None
    assert len(storage.quests.list(other.id)) == 1 and len(storage.campaign_facts.list(other.id)) == 1


def test_possessions_and_their_owners(storage: Storage) -> None:
    _, campaign = _started_campaign(storage)
    _, other = _started_campaign(storage)
    mira = storage.characters.create(campaign.id, "Mira")
    stranger = storage.characters.create(other.id, "Stranger")
    assert storage.possessions.get(campaign.id, "pos_horse") is None

    horse = Possession(
        campaign.id,
        "pos_horse",
        "Bramble",
        "mount",
        owner_id=mira.id,
        location="the stable",
        value_gp=75,
        description="A brown mare",
        notes_md="SECRET-XYZZY",
        inventory=("saddlebags", "a blanket"),
        stats={"species": "riding-horse", "hp": 18, "hp_max": 18, "mv": 24, "attacks": ["1d3 (kick)"]},
        portrait=TraitsPortrait("a brown mare", "pos_horse"),
    )
    stored = storage.possessions.put(horse)
    assert stored.created_at and stored.updated_at
    assert stored == replace(horse, created_at=stored.created_at, updated_at=stored.updated_at)
    assert storage.possessions.get(campaign.id, "pos_horse") == stored
    house = storage.possessions.put(Possession(campaign.id, "pos_house", "The mill house", "house"))
    assert house.owner_id is None, "None is the party"
    assert storage.possessions.list(campaign.id) == [stored, house]
    assert storage.possessions.list(campaign.id, owner_id=mira.id) == [stored]
    assert storage.possessions.list(campaign.id, kind="house") == [house]

    moved = storage.possessions.put(replace(stored, location="Hardby", portrait=ImagePortrait("img_000000000001")))
    assert moved.created_at == stored.created_at and moved.location == "Hardby"
    assert storage.possessions.get(campaign.id, "pos_horse") == moved
    with pytest.raises(KeyError):
        storage.possessions.put(replace(house, owner_id=stranger.id))  # a character of another campaign
    with pytest.raises(KeyError):
        storage.possessions.put(replace(house, campaign_id="cmp_000000000000"))

    storage.characters.delete(mira.id)
    assert storage.possessions.get(campaign.id, "pos_horse").owner_id is None, "the dead leave it to the party"
    storage.possessions.delete(campaign.id, "pos_house")
    assert [p.id for p in storage.possessions.list(campaign.id)] == ["pos_horse"]
    storage.possessions.delete(campaign.id, "pos_house")

    storage.possessions.put(Possession(other.id, "pos_ship", "The Gull", "ship", stats={"mv": 6, "capacity": 20}))
    storage.campaigns.delete(campaign.id)
    assert storage.possessions.list(campaign.id) == [] and len(storage.possessions.list(other.id)) == 1


def test_world_maps(storage: Storage) -> None:
    _, campaign = _started_campaign(storage)
    _, other = _started_campaign(storage)
    assert storage.world_maps.get(campaign.id, "region") is None and storage.world_maps.list(campaign.id) == []

    region = storage.world_maps.put(
        CampaignWorldMap(campaign.id, "region", "The Greyhawk region", "setting", "workspace {}\n")
    )
    assert region.updated_at and region.revealed == ()
    assert storage.world_maps.get(campaign.id, "region") == region
    caves = storage.world_maps.put(CampaignWorldMap(campaign.id, "caves", "The caves", "module", "workspace {}\n"))
    storage.world_maps.put(CampaignWorldMap(other.id, "region", "Elsewhere", "campaign", ""))
    assert storage.world_maps.list(campaign.id) == [region, caves]
    revealed = storage.world_maps.put(replace(region, revealed=("castle-greyhawk",), source="campaign"))
    assert revealed.updated_at >= region.updated_at
    assert storage.world_maps.get(campaign.id, "region") == revealed
    with pytest.raises(KeyError):
        storage.world_maps.put(CampaignWorldMap("cmp_000000000000", "region", "Nowhere", "campaign", ""))
    storage.world_maps.delete(campaign.id, "caves")
    assert storage.world_maps.list(campaign.id) == [revealed]
    storage.world_maps.delete(campaign.id, "caves")

    storage.campaigns.delete(campaign.id)
    assert storage.world_maps.list(campaign.id) == [] and len(storage.world_maps.list(other.id)) == 1


def test_merchants(storage: Storage) -> None:
    _, campaign = _started_campaign(storage)
    _, other = _started_campaign(storage)
    tira = storage.characters.create(campaign.id, "Tira", kind="npc")
    assert storage.merchants.get(campaign.id, "tira") is None

    shelf = Merchant(
        campaign.id,
        "tira",
        "Tira's stall",
        npc_id=tira.id,
        settlement="city",
        cost="expensive",
        seed=1234,
        rolled_day=3,
        items=({"name": "Potion of healing", "price_gp": 800, "tier": "common"},),
    )
    assert storage.merchants.put(shelf) == shelf and storage.merchants.get(campaign.id, "tira") == shelf
    pedlar = storage.merchants.put(Merchant(campaign.id, "pedlar", "A pedlar", rolled_day=4))
    assert (pedlar.settlement, pedlar.cost, pedlar.items, pedlar.sold) == ("pedlar", "moderate", (), ())
    storage.merchants.put(Merchant(other.id, "tira", "Elsewhere"))
    sold = storage.merchants.put(replace(shelf, items=(), sold=({"name": "Potion of healing", "to": "chr_1"},)))
    assert storage.merchants.list(campaign.id) == [sold, pedlar]
    with pytest.raises(KeyError):
        storage.merchants.put(Merchant("cmp_000000000000", "tira", "Nowhere"))

    storage.characters.delete(tira.id)
    assert storage.merchants.get(campaign.id, "tira").npc_id is None
    storage.campaigns.delete(campaign.id)
    assert storage.merchants.list(campaign.id) == [] and len(storage.merchants.list(other.id)) == 1


def test_campaign_images(storage: Storage) -> None:
    _, campaign = _started_campaign(storage)
    _, other = _started_campaign(storage)
    assert storage.campaign_images.get("img_000000000000") is None and storage.campaign_images.painting() == []

    portrait = storage.campaign_images.put(
        CampaignImage("img_000000000001", campaign.id, "portrait", subject_id="chr_1", prompt="a dwarf", backend="fake")
    )
    assert portrait.created_at and (portrait.status, portrait.attempts, portrait.audience) == ("painting", 0, None)
    assert storage.campaign_images.get(portrait.id) == portrait
    scene = storage.campaign_images.put(
        CampaignImage(
            "img_000000000002",
            campaign.id,
            "scene",
            prompt="the bridge at dusk",
            caption="The bridge",
            backend="replicate",
            audience={"characters": ["chr_1"]},
        )
    )
    elsewhere = storage.campaign_images.put(CampaignImage("img_000000000003", other.id, "scene", prompt="far"))
    assert storage.campaign_images.list(campaign.id) == [portrait, scene]
    assert storage.campaign_images.list(campaign.id, kind="scene") == [scene] and scene.caption == "The bridge"
    assert storage.campaign_images.list(campaign.id, subject_id="chr_1") == [portrait]
    assert storage.campaign_images.painting() == [portrait, scene, elsewhere], "across campaigns"

    sha = storage.blobs.put(b"\x89PNG fake", "image/png")
    done = storage.campaign_images.put(replace(portrait, status="done", blob=sha, mime="image/png", attempts=1))
    assert done.created_at == portrait.created_at and storage.campaign_images.get(portrait.id) == done
    failed = storage.campaign_images.put(replace(scene, status="failed", error="Replicate said no"))
    assert storage.campaign_images.list(campaign.id, status="failed") == [failed]
    assert storage.campaign_images.painting() == [elsewhere]
    with pytest.raises(KeyError):
        storage.campaign_images.put(CampaignImage("img_000000000009", "cmp_000000000000", "scene"))
    storage.campaign_images.delete(failed.id)
    assert storage.campaign_images.list(campaign.id) == [done]
    storage.campaign_images.delete(failed.id)

    storage.campaigns.delete(campaign.id)
    assert storage.campaign_images.get(done.id) is None and storage.campaign_images.painting() == [elsewhere]
    assert storage.blobs.get(sha) == b"\x89PNG fake", "the blob store keeps the bytes"


GEO = {"type": "FeatureCollection", "features": [], "delve": {"frame": {"width_km": 480.0, "height_km": 320.0}}}


def test_world_maps_keep_geo_knowledge_and_reading(storage: Storage) -> None:
    _, campaign = _started_campaign(storage)
    plain = storage.world_maps.put(CampaignWorldMap(campaign.id, "region", "The region", "setting", "workspace {}\n"))
    assert (plain.geo, plain.picture, plain.status, plain.knowledge, plain.reading) == (None, None, "ready", None, None)

    knowledge = WorldKnowledge(cells=(1, 2, 3, 7), features=("greyhawk",), forgotten=("hardby",))
    read = storage.world_maps.put(
        replace(
            plain,
            geo=GEO,
            picture="a" * 64,
            status="review",
            knowledge=knowledge,
            reading={"doubts": [{"kind": "colour", "colour": "#7f7f7f"}]},
        )
    )
    assert storage.world_maps.get(campaign.id, "region") == read
    assert read.knowledge == knowledge and read.geo == GEO and read.status == "review"
    known_all = storage.world_maps.put(replace(read, knowledge=WorldKnowledge(everything=True)))
    assert storage.world_maps.get(campaign.id, "region").knowledge == WorldKnowledge(everything=True)
    assert storage.world_maps.list(campaign.id) == [known_all]


def test_campaign_state_keeps_the_journey(storage: Storage) -> None:
    _, campaign = _started_campaign(storage)
    journey = Journey(
        "flanaess",
        "river-boat",
        "hardby",
        "Hardby",
        ((10.0, 20.0), (12.5, 30.25)),
        48.3,
        done_km=12.0,
        by=("pos_boat",),
        planned_on="2026-10-18T00:00:00+00:00",
        miles_per_day=30.0,
    )
    state = CampaignState(campaign.id, world=WorldPosition("flanaess", 10.0, 20.0, at="greyhawk", km=True))
    storage.campaign_states.put(replace(state, journey=journey))
    assert storage.campaign_states.get(campaign.id) == replace(state, journey=journey)
    storage.campaign_states.put(state)
    assert storage.campaign_states.get(campaign.id).journey is None


def test_campaign_status(storage: Storage) -> None:
    _, campaign = _started_campaign(storage)
    assert campaign.status == "in_progress" and storage.campaigns.get(campaign.id).status == "in_progress"
    paused = storage.campaigns.set_status(campaign.id, "paused")
    assert paused == replace(campaign, status="paused") == storage.campaigns.get(campaign.id)
    assert storage.campaigns.list() == [paused]
    assert storage.campaigns.set_status(campaign.id, "complete").status == "complete"
    with pytest.raises(KeyError):
        storage.campaigns.set_status("cmp_000000000000", "paused")


def test_conversions_keep_target_result_and_questions(storage: Storage) -> None:
    module = storage.modules.create("The Kobold Caves")
    other = storage.modules.create("Elsewhere")
    made = storage.conversions.create("pdf", "The Kobold Caves", "draft")
    assert (made.target, made.result, made.questions, made.cost_usd) == (None, None, None, None)
    storage.conversions.save(
        replace(made, status="done", module_id=module.id, questions={"open": ["How deep?"]}, cost_usd=0.03)
    )

    draft = storage.conversions.create("dungeon-map", "A crypt", "draft", target={"module_id": module.id})
    assert draft.target == {"module_id": module.id} and storage.conversions.get(draft.id) == draft
    result = {"maps": [{"name": "crypt-1", "source": "map {}"}]}
    finished = storage.conversions.save(replace(draft, status="done", result=result))
    assert storage.conversions.get(draft.id) == finished and finished.result == result

    storage.conversions.save(
        replace(
            storage.conversions.create("worldmap", "Elsewhere", "ready", target={"module_id": other.id}), status="done"
        )
    )
    for n in range(20):
        storage.conversions.save(replace(storage.conversions.create("generate", f"Job {n}", "ready"), status="done"))
    assert draft.id not in [c.id for c in storage.conversions.list()], "a 21st conversion falls off the list"
    found = storage.conversions.for_module(module.id)
    assert [c.id for c in found] == [draft.id, made.id], "newest first, by module_id or target.module_id"
    assert found[1].questions == {"open": ["How deep?"]}
    assert found[1].cost_usd == 0.03
    assert storage.conversions.for_module("mod_000000000000") == []


def test_translations_keep_the_answer(storage: Storage) -> None:
    _, campaign = _started_campaign(storage)
    entry = storage.story.append(campaign.id, None, "answer", {"text": "A kobold is a small reptile."})
    plain = storage.translations.put(entry.id, "nl", "Een kobold…", "translating")
    assert plain.answer is None
    done = storage.translations.put(entry.id, "nl", "Een kobold.", "done", answer="Een klein reptiel.")
    assert done.answer == "Een klein reptiel."
    assert storage.translations.for_entries([entry.id], "nl") == {entry.id: done}


def test_world_pictures(storage: Storage) -> None:
    assert storage.world_pictures.get("0" * 64) is None
    picture = WorldPicture("b" * 64, "image/jpeg", 13706, 10678, 6, {"0/0/0": "c" * 64, "6/53/41": "d" * 64})
    stored = storage.world_pictures.put(picture)
    assert stored.created_at and stored == replace(picture, created_at=stored.created_at)
    assert storage.world_pictures.get(picture.id) == stored
    again = storage.world_pictures.put(replace(picture, max_zoom=5))
    assert again.created_at == stored.created_at and storage.world_pictures.get(picture.id).max_zoom == 5
    assert TILE_SIZE == 256


def test_setting_pages(storage: Storage) -> None:
    assert title_key("  Hardby \t of\nthe  Wild ") == "hardby of the wild"
    assert storage.setting_pages.get("greyhawk", "Hardby") is None
    hardby = SettingAddition("greyhawk", "Hardby", "place", {"ruler": "Despotrix"}, "A [[gynarchy]] on the bay.")
    first = storage.setting_pages.put(hardby)
    assert first.created_at and first.updated_at
    assert first == replace(hardby, created_at=first.created_at, updated_at=first.updated_at)
    assert storage.setting_pages.get("greyhawk", "  hardby ") == first
    assert storage.setting_pages.get("forgotten-realms", "Hardby") is None

    again = storage.setting_pages.put(replace(hardby, title="HARDBY", text="Ruled by women.", dm_only=True))
    assert again.created_at == first.created_at and again.updated_at > first.updated_at
    assert (again.title, again.text, again.dm_only) == ("HARDBY", "Ruled by women.", True)
    assert storage.setting_pages.get("greyhawk", "hardby") == again

    odd = storage.setting_pages.put(SettingAddition("greyhawk", "Ready'reat / Patchwall?", "place", text="100% oak"))
    storage.setting_pages.put(SettingAddition("greyhawk", "Mordenkainen", "person", text="A gynarchy? Never."))
    storage.setting_pages.put(SettingAddition("forgotten-realms", "Waterdeep", "place", text="a gynarchy"))
    assert storage.setting_pages.get("greyhawk", "ready'reat / patchwall?") == odd
    assert [a.title for a in storage.setting_pages.list("greyhawk")] == [
        "HARDBY",
        "Mordenkainen",
        "Ready'reat / Patchwall?",
    ]
    assert [a.title for a in storage.setting_pages.list("greyhawk", kind="place")] == [
        "HARDBY",
        "Ready'reat / Patchwall?",
    ]
    assert [a.title for a in storage.setting_pages.list("greyhawk", query="GYNARCHY")] == ["Mordenkainen"]
    assert [a.title for a in storage.setting_pages.list("greyhawk", query="hard")] == ["HARDBY"]
    assert [a.title for a in storage.setting_pages.list("greyhawk", query="%")] == ["Ready'reat / Patchwall?"]
    assert storage.setting_pages.list("greyhawk", query="_") == []

    storage.setting_pages.delete("greyhawk", " READY'REAT / PATCHWALL? ")
    storage.setting_pages.delete("greyhawk", "Ready'reat / Patchwall?")
    assert storage.setting_pages.get("greyhawk", "Ready'reat / Patchwall?") is None
    assert [a.title for a in storage.setting_pages.list("greyhawk")] == ["HARDBY", "Mordenkainen"]


def test_setting_facts(storage: Storage) -> None:
    assert storage.setting_facts.get(1) is None and storage.setting_facts.list("greyhawk") == []
    first = storage.setting_facts.add(SettingFact(0, "greyhawk", "Hardby pays tribute to Greyhawk.", "greyhawk"))
    second = storage.setting_facts.add(SettingFact(0, "greyhawk", "The Despotrix is a sea witch.", dm_only=True))
    storage.setting_facts.add(SettingFact(0, "forgotten-realms", "Waterdeep has a masked council."))
    assert first.id and second.id and first.id != second.id and first.created_at
    assert storage.setting_facts.get(first.id) == first
    assert storage.setting_facts.list("greyhawk") == [first, second]
    assert storage.setting_facts.list("greyhawk", query="DESPOTRIX") == [second]

    edited = storage.setting_facts.put(replace(first, text="Hardby pays tribute.", dm_only=True))
    assert storage.setting_facts.get(first.id) == edited and edited.created_at == first.created_at
    with pytest.raises(KeyError):
        storage.setting_facts.put(replace(first, id=9999))
    storage.setting_facts.delete(second.id)
    storage.setting_facts.delete(second.id)
    assert storage.setting_facts.list("greyhawk") == [edited]


def test_proposals(storage: Storage) -> None:
    module, campaign = _started_campaign(storage)
    other = storage.campaigns.create("Wednesday", module.id, 1, ruleset="adnd2e", setting="greyhawk")
    assert storage.proposals.get(1) is None and storage.proposals.list() == []
    page = storage.proposals.add(Proposal(0, "greyhawk", campaign.id, "page", "Hardby", "A city.", page_kind="place"))
    fact = storage.proposals.add(Proposal(0, "greyhawk", campaign.id, "fact", text="Rain.", dm_only=True))
    edit = storage.proposals.add(Proposal(0, "greyhawk", other.id, "edit", "Hardby", "Burnt.", mode="replace"))
    realms = storage.proposals.add(Proposal(0, "forgotten-realms", other.id, "fact", text="Elves."))
    assert page.id and page.created_at and page.status == "pending" and page.decided_at is None
    assert storage.proposals.get(page.id) == page
    assert storage.proposals.list() == [page, fact, edit, realms]
    assert storage.proposals.list("greyhawk") == [page, fact, edit]
    assert storage.proposals.list(campaign_id=other.id) == [edit, realms]
    assert storage.proposals.list("greyhawk", kind="fact") == [fact]

    accepted = storage.proposals.put(replace(fact, status="accepted", decided_at="2026-10-19T12:00:00+00:00"))
    assert storage.proposals.get(fact.id) == accepted
    assert storage.proposals.list("greyhawk", status="pending") == [page, edit]
    assert storage.proposals.list("greyhawk", campaign_id=campaign.id, status="accepted") == [accepted]
    with pytest.raises(KeyError):
        storage.proposals.add(Proposal(0, "greyhawk", "cmp_000000000000", "fact", text="Lost."))
    with pytest.raises(KeyError):
        storage.proposals.put(replace(page, id=9999))

    storage.campaigns.delete(other.id)
    assert storage.proposals.list() == [page, accepted], "deleting a campaign deletes its proposals"


def test_setting_maps(storage: Storage) -> None:
    assert storage.setting_maps.get("greyhawk", "flanaess") is None and storage.setting_maps.list("greyhawk") == []
    flanaess = WorldMapSource(
        "flanaess", "The Flanaess", "", geo=GEO, picture="a" * 64, status="review", reading={"doubts": []}
    )
    stored = storage.setting_maps.put("greyhawk", flanaess)
    assert stored == flanaess and storage.setting_maps.get("greyhawk", "flanaess") == flanaess
    region = storage.setting_maps.put("greyhawk", WorldMapSource("region", "The region", "", geo=GEO))
    storage.setting_maps.put("forgotten-realms", WorldMapSource("faerun", "Faerûn", "", geo=GEO))
    ready = storage.setting_maps.put("greyhawk", replace(flanaess, status="ready", reading=None))
    assert storage.setting_maps.list("greyhawk") == [ready, region], "the order of the first put"
    with pytest.raises(ValueError):
        storage.setting_maps.put("greyhawk", WorldMapSource("dsl", "A .map", "workspace {}\n"))
    assert storage.setting_maps.get("greyhawk", "dsl") is None
    storage.setting_maps.delete("greyhawk", "flanaess")
    storage.setting_maps.delete("greyhawk", "flanaess")
    assert storage.setting_maps.list("greyhawk") == [region]
    assert [m.name for m in storage.setting_maps.list("forgotten-realms")] == ["faerun"]


def test_campaign_voice_and_initiative(storage: Storage) -> None:
    _, campaign = _started_campaign(storage)
    assert (campaign.voice, campaign.initiative) == ("allowed", "combatant"), "a new campaign's defaults"
    off = storage.campaigns.set_voice(campaign.id, "off")
    assert off == replace(campaign, voice="off") == storage.campaigns.get(campaign.id)
    side = storage.campaigns.set_initiative(campaign.id, "side")
    assert side == replace(off, initiative="side") == storage.campaigns.get(campaign.id)
    assert storage.campaigns.set_status(campaign.id, "paused") == replace(side, status="paused"), "the others keep"
    with pytest.raises(ValueError):
        storage.campaigns.set_voice(campaign.id, "loud")
    with pytest.raises(ValueError):
        storage.campaigns.set_initiative(campaign.id, "group")
    with pytest.raises(KeyError):
        storage.campaigns.set_voice("cmp_000000000000", "off")
    with pytest.raises(KeyError):
        storage.campaigns.set_initiative("cmp_000000000000", "side")


def test_campaign_observers(storage: Storage) -> None:
    """Who may watch the table (DEL-215): anyone by default, then what the host sets; the rest keeps."""
    _, campaign = _started_campaign(storage)
    assert campaign.observers == "anyone"
    approved = storage.campaigns.set_observers(campaign.id, "approved")
    assert approved == replace(campaign, observers="approved") == storage.campaigns.get(campaign.id)
    assert storage.campaigns.set_observers(campaign.id, "nobody").observers == "nobody"
    with pytest.raises(ValueError):
        storage.campaigns.set_observers(campaign.id, "friends")
    with pytest.raises(KeyError):
        storage.campaigns.set_observers("cmp_000000000000", "nobody")


def test_campaign_listing(storage: Storage) -> None:
    _, campaign = _started_campaign(storage)
    assert (campaign.visibility, campaign.description, campaign.slots) == ("private", "", None), "the defaults"
    listed = storage.campaigns.set_listing(campaign.id, "public", "We play on **Tuesdays**.", 4)
    assert listed == replace(campaign, visibility="public", description="We play on **Tuesdays**.", slots=4)
    assert storage.campaigns.get(campaign.id) == listed
    assert storage.campaigns.set_voice(campaign.id, "off") == replace(listed, voice="off"), "the others keep"
    unlimited = storage.campaigns.set_listing(campaign.id, "private", "", None)
    assert (unlimited.visibility, unlimited.description, unlimited.slots) == ("private", "", None)
    assert storage.campaigns.set_listing(campaign.id, "public", "x" * 4000, 20).slots == 20, "the most allowed"
    for wrong in (("secret", "", None), ("public", "x" * 4001, None), ("public", "", 0), ("public", "", 21)):
        with pytest.raises(ValueError):
            storage.campaigns.set_listing(campaign.id, *wrong)
    assert storage.campaigns.get(campaign.id).slots == 20, "a refused listing changes nothing"
    with pytest.raises(KeyError):
        storage.campaigns.set_listing("cmp_000000000000", "public", "", None)


def test_campaign_schedule(storage: Storage) -> None:
    _, campaign = _started_campaign(storage)
    assert campaign.schedule is None, "a new campaign has none"
    rule = {
        "every_weeks": 2,
        "first": "2026-11-07",
        "start": "20:00",
        "end": "22:00",
        "time_zone": "Europe/Brussels",
        "changes": [{"on": "2026-11-21", "to": "2026-11-22T19:00"}, {"on": "2026-12-05", "to": None}],
    }
    scheduled = storage.campaigns.set_schedule(campaign.id, rule)
    assert scheduled == replace(campaign, schedule=rule) == storage.campaigns.get(campaign.id)
    assert storage.campaigns.set_voice(campaign.id, "off") == replace(scheduled, voice="off"), "the others keep"
    assert storage.campaigns.list()[0].schedule == rule
    assert storage.campaigns.set_schedule(campaign.id, None).schedule is None
    assert storage.campaigns.get(campaign.id).schedule is None
    with pytest.raises(KeyError):
        storage.campaigns.set_schedule("cmp_000000000000", rule)


def test_character_departure(storage: Storage) -> None:
    _, campaign = _started_campaign(storage)
    tansy = storage.characters.create(campaign.id, "Tansy")
    assert (tansy.departure, tansy.departed_at) == (None, None)
    fallen = storage.characters.set_departure(tansy.id, "died", "2026-10-25T20:00:00+00:00")
    assert (fallen.departure, fallen.departed_at) == ("died", "2026-10-25T20:00:00+00:00")
    assert storage.characters.get(tansy.id) == fallen
    stale = replace(tansy, state=replace(tansy.state, hp=-10))
    saved = storage.characters.save(stale)
    assert (saved.departure, saved.departed_at) == ("died", "2026-10-25T20:00:00+00:00"), "save never brings one back"
    assert storage.characters.get(tansy.id).state.hp == -10
    retired = storage.characters.set_departure(tansy.id, "retired")
    assert retired.departure == "retired" and retired.departed_at, "now, by default"
    back = storage.characters.set_departure(tansy.id, None)
    assert (back.departure, back.departed_at) == (None, None) and storage.characters.get(tansy.id) == back
    with pytest.raises(ValueError):
        storage.characters.set_departure(tansy.id, "vanished")
    with pytest.raises(KeyError):
        storage.characters.set_departure("chr_000000000000", "left")


def test_conversion_comments_and_closed(storage: Storage) -> None:
    plain = storage.conversions.create("pdf", "The Kobold Caves", "ready")
    assert (plain.comments, plain.closed) == ("", [])
    storage.conversions.save(replace(plain, status="done"))
    made = storage.conversions.create("pdf", "Barrowmaze", "draft", comments="the room key starts on page 40")
    assert made.comments == "the room key starts on page 40" and storage.conversions.get(made.id) == made
    closed = storage.conversions.set_closed(made.id, ["question:q1", "doubt:0", "question:q1"])
    assert closed.closed == ["question:q1", "doubt:0"] and storage.conversions.get(made.id) == closed
    saved = storage.conversions.save(replace(made, step="converting", done=3, total=9))
    assert saved.closed == ["question:q1", "doubt:0"], "a job's save never reopens what was closed"
    assert storage.conversions.get(made.id).closed == ["question:q1", "doubt:0"]
    assert storage.conversions.get(made.id).done == 3
    assert storage.conversions.set_closed(made.id, []).closed == []
    storage.conversions.save(replace(made, status="done"))
    with pytest.raises(KeyError):
        storage.conversions.set_closed("cnv_000000000000", ["doubt:0"])
    fixit = storage.conversions.create("fixit", "Fix: Barrowmaze", "ready", target={"module_id": "mod_x"})
    assert storage.conversions.get(fixit.id).kind == "fixit"


def test_combat_rounds(storage: Storage) -> None:
    _, campaign = _started_campaign(storage)
    fight = storage.combats.create(campaign.id, "round", {"round": 1})
    slot = {"id": "chr_x", "name": "Mirela", "side": "party", "count": 7, "ongoing": None}
    rolled = CombatRound(fight, 1, campaign.id, "combatant", (slot,), beat_id="bt_1", rolled_at="2026-10-25T20:00:00")
    assert storage.combat_rounds.put(rolled) == rolled and storage.combat_rounds.get(fight, 1) == rolled
    assert storage.combat_rounds.unreleased(campaign.id) == [], "rolled, not resolved"
    outcomes = {"acted": ["chr_x"], "downed": [], "dead": [], "fled": [], "completed": [], "interrupted": []}
    resolved = replace(rolled, outcomes=outcomes, resolved_at="2026-10-25T20:00:05")
    storage.combat_rounds.put(resolved)
    second = CombatRound(fight, 2, campaign.id, "side", (slot,), rolled_at="2026-10-25T20:01:00")
    storage.combat_rounds.put(second)
    assert storage.combat_rounds.unreleased(campaign.id) == [resolved]
    assert storage.combat_rounds.latest(fight) == second
    assert storage.combat_rounds.list(fight) == [resolved, second]
    assert storage.combat_rounds.release(fight, 1, "2026-10-25T20:00:09") is True
    assert storage.combat_rounds.release(fight, 1, "2026-10-25T20:00:10") is False, "once"
    assert storage.combat_rounds.release(fight, 9, "2026-10-25T20:00:10") is False
    released = storage.combat_rounds.get(fight, 1)
    assert released == replace(resolved, released_at="2026-10-25T20:00:09")
    storage.combat_rounds.put(replace(resolved, slots=()))
    assert storage.combat_rounds.get(fight, 1).released_at == "2026-10-25T20:00:09", "put keeps the release"
    assert storage.combat_rounds.unreleased(campaign.id) == []
    with pytest.raises(KeyError):
        storage.combat_rounds.put(replace(rolled, combat_id="cbt_000000000000"))
    storage.campaigns.delete(campaign.id)
    assert storage.combat_rounds.list(fight) == []


def test_module_comments(storage: Storage) -> None:
    module = storage.modules.create("Barrowmaze")
    other = storage.modules.create("Elsewhere")
    first = storage.module_comments.create(module.id, "exit X is not yet in place, fix it", author="Raf")
    assert first.id.startswith("mcm_") and (first.status, first.anchor, first.author) == ("open", None, "Raf")
    assert first.created_at and first.updated_at and storage.module_comments.get(first.id) == first
    anchor = {"kind": "room", "map": "level-1", "node": "r12"}
    second = storage.module_comments.create(module.id, "the well is dry", anchor=anchor)
    storage.module_comments.create(other.id, "elsewhere")
    assert storage.module_comments.list(module.id) == [first, second]
    job = storage.conversions.create("fixit", "Fix: Barrowmaze", "ready", target={"module_id": module.id})
    working = storage.module_comments.save(replace(first, status="working", conversion_id=job.id, revision=1))
    assert storage.module_comments.get(first.id) == working
    assert storage.module_comments.with_status(module.id, "open") == [second]
    assert storage.module_comments.with_status(module.id, "open", "working") == [working, second]
    assert storage.module_comments.for_conversion(job.id) == [working]
    failed = storage.module_comments.save(replace(working, status="failed", error="Claude didn't answer"))
    assert storage.module_comments.get(first.id).error == "Claude didn't answer" == failed.error
    with pytest.raises(ValueError):
        storage.module_comments.save(replace(second, status="done"))
    with pytest.raises(KeyError):
        storage.module_comments.save(replace(second, id="mcm_000000000000"))
    with pytest.raises(KeyError):
        storage.module_comments.create("mod_000000000000", "nowhere")
    storage.modules.delete(module.id)
    assert storage.module_comments.get(second.id) is None


def test_story_notes_and_events_search_newest_first(storage: Storage) -> None:
    """The DM's `search_campaign` (DEL-172): in SQL, newest first, at most `limit`, `%` and `_` taken as written."""
    _, campaign = _started_campaign(storage)
    _, other = _started_campaign(storage)
    old = storage.story.append(campaign.id, None, "dm_text", {"text": "The Silver Key lies here."})
    storage.story.append(campaign.id, None, "dm_text", {"text": "Nothing of note."})
    storage.story.append(campaign.id, None, "player_text", {"name": "silver key"})  # no text: not searched
    new = storage.story.append(campaign.id, None, "dm_text", {"text": "the silver key turns."})
    storage.story.append(other.id, None, "dm_text", {"text": "Another silver key."})
    assert [e.id for e in storage.story.search(campaign.id, "SILVER KEY", 5)] == [new.id, old.id]
    assert [e.id for e in storage.story.search(campaign.id, "silver key", 1)] == [new.id]
    assert storage.story.search(campaign.id, "silver_key", 5) == []

    first = storage.notes.create(campaign.id, "secret", "100% cursed.")
    storage.notes.create(campaign.id, "secret", "1000 cursed.")
    assert [n.id for n in storage.notes.search(campaign.id, "100%", 5)] == [first.id]

    storage.events.append(campaign.id, "moved", {"to": "the nave", "note": "quiet"}, session=1, beat="b1")
    later = storage.events.append(campaign.id, "moved", {"to": "Nave door"}, session=1, beat="b1")
    storage.events.append(campaign.id, "nave", {"count": 3}, session=1, beat="b1")  # a type, a number: not found
    storage.events.append(campaign.id, "moved", {"nave": "crypt"}, session=1, beat="b1")  # a key: not found
    found = storage.events.search(campaign.id, "nave", 5)
    assert [e.data for e in found] == [{"to": "Nave door"}, {"to": "the nave", "note": "quiet"}] and found[0] == later


def test_the_campaign_lists_reads_of_everything(storage: Storage) -> None:
    """What the list of campaigns reads once for all of them (DEL-172) answers as the reads for one do."""
    module, campaign = _started_campaign(storage)
    _, other = _started_campaign(storage)
    _, idle = _started_campaign(storage)
    storage.sessions.start(campaign.id, 1, "Into the crypt")
    beat = storage.beats.open(campaign.id, [], status="running")
    storage.beats.save(replace(beat, status="done", closed_at="2099-01-01T20:00:00+00:00"))
    assert storage.campaigns.activities() == {c.id: storage.campaigns.activity(c.id) for c in (campaign, other, idle)}
    assert storage.campaigns.activities()[campaign.id].sessions == 1

    storage.seats.create(campaign.id, "Host", "en", "host", organiser=True, owner=True)
    storage.seats.create(other.id, "Bo", "en", "player")
    storage.seats.create(campaign.id, "Ana", "en", "player")
    assert storage.seats.by_campaign() == {c.id: storage.seats.list(c.id) for c in (campaign, other)}

    first = storage.carries.add(campaign.id, other.id, [])
    second = storage.carries.add(campaign.id, idle.id, [])
    assert storage.carries.all() == [first, second]

    banner = storage.campaign_images.put(CampaignImage("img_000000000101", campaign.id, "banner", status="done"))
    storage.campaign_images.put(CampaignImage("img_000000000102", other.id, "banner", status="waiting"))
    storage.campaign_images.put(CampaignImage("img_000000000103", other.id, "scene", status="done"))
    assert storage.campaign_images.everywhere("banner", "done") == [banner]

    heads = storage.modules.heads()
    assert heads[module.id].title == "The Crypt" and heads[module.id].banner == storage.modules.get(module.id).banner


AT = "2026-10-29T10:00:00+00:00"
LATER = "2026-10-29T11:00:00+00:00"


def test_board_zones(storage: Storage) -> None:
    a = storage.board.create_zone(Zone("", "The engine", read="everybody", write="accounts", created_at=AT))
    b = storage.board.create_zone(Zone("", "OSRIC", created_at=AT))
    assert a.id.startswith("bzn_") and (a.position, b.position) == (0, 1)
    assert [z.name for z in storage.board.zones()] == ["The engine", "OSRIC"]
    storage.board.save_zone(replace(b, position=-1, moderators=("acc_1",), members=("acc_2",)))
    assert [z.name for z in storage.board.zones()] == ["OSRIC", "The engine"]
    assert storage.board.get_zone(b.id).members == ("acc_2",)


def test_board_one_zone_per_campaign(storage: Storage) -> None:
    _, campaign = _started_campaign(storage)
    storage.board.create_zone(
        Zone("", "Our table", read="table", write="table", campaign_id=campaign.id, created_at=AT)
    )
    assert storage.board.zone_of_campaign(campaign.id).name == "Our table"
    with pytest.raises(ValueError):
        storage.board.create_zone(Zone("", "Again", campaign_id=campaign.id, created_at=AT))


def test_board_topics_and_posts(storage: Storage) -> None:
    zone = storage.board.create_zone(Zone("", "The engine", created_at=AT))
    topic, first = storage.board.add_topic(
        Topic("", zone.id, "Morale", "acc_1", AT, AT, "acc_1"), Post("", "", "acc_1", "Hi", AT)
    )
    assert first.topic_id == topic.id and topic.posts == 1
    second = storage.board.add_post(Post("", topic.id, "acc_2", "Yes", LATER))
    again = storage.board.get_topic(topic.id)
    assert (again.posts, again.last_post_at, again.last_author_id) == (2, LATER, "acc_2")
    assert [p.text for p in storage.board.posts(topic.id)] == ["Hi", "Yes"]
    assert [p.text for p in storage.board.posts(topic.id, offset=1, limit=1)] == ["Yes"]
    assert (storage.board.post_index(first), storage.board.post_index(second)) == (0, 1)
    storage.board.save_post(replace(second, text="No", edited_at=LATER, removed="moderator"))
    assert storage.board.get_post(second.id).removed == "moderator"
    pinned, _ = storage.board.add_topic(
        Topic("", zone.id, "Rules", "acc_1", AT, AT, "acc_1", pinned=True), Post("", "", "acc_1", "x", AT)
    )
    assert [t.title for t in storage.board.topics(zone.id)] == ["Rules", "Morale"]
    storage.board.save_topic(replace(pinned, locked=True))
    assert storage.board.get_topic(pinned.id).locked
    storage.board.mark_read("acc_1", topic.id, LATER)
    storage.board.delete_zone(zone.id)
    assert storage.board.get_topic(topic.id) is None and storage.board.get_post(first.id) is None
    assert storage.board.read_marks("acc_1") == {}


def test_board_read_marks(storage: Storage) -> None:
    zone = storage.board.create_zone(Zone("", "The engine", created_at=AT))
    topic, _ = storage.board.add_topic(
        Topic("", zone.id, "Morale", "acc_1", AT, AT, "acc_1"), Post("", "", "acc_1", "Hi", AT)
    )
    storage.board.mark_read("acc_1", topic.id, LATER)
    storage.board.mark_read("acc_1", topic.id, AT)
    assert storage.board.read_marks("acc_1") == {topic.id: LATER}
    storage.board.mark_read("acc_1", "top_gone", LATER)  # deleted a moment ago: nothing to mark
    assert storage.board.read_marks("acc_1") == {topic.id: LATER}
    storage.board.set_first_visit("acc_1", AT)
    storage.board.set_first_visit("acc_1", LATER)
    assert storage.board.first_visit("acc_1") == AT
    assert storage.board.first_visit("acc_2") is None


CONTRACT = (
    test_settings_update,
    test_settings_empty_load,
    test_play_settings,
    test_table_sessions,
    test_settings_roundtrip,
    test_settings_overwrite,
    test_module_crud,
    test_put_map_upserts_by_name,
    test_single_default_map,
    test_snapshot_reuses_unchanged_revision,
    test_snapshot_after_edit_creates_next,
    test_revision_immutable_after_edit,
    test_campaign_and_characters,
    test_delete_campaign_cascades,
    test_module_in_use_not_deleted,
    test_map_state_roundtrip,
    test_campaign_maps,
    test_board_zones,
    test_board_one_zone_per_campaign,
    test_board_topics_and_posts,
    test_board_read_marks,
    test_blob_content_addressed_and_deduplicated,
    test_blob_written_atomically,
    test_blob_put_file_streams_a_file_in,
    test_character_sheet_state_roundtrip,
    test_campaign_state_roundtrip,
    test_roll_log_find_and_record,
    test_events_append_and_list,
    test_story_notes_and_events_search_newest_first,
    test_transaction_rolls_back_all_repos,
    test_transaction_commits_together_and_nests,
    test_delete_campaign_cascades_play_state,
    test_combats_one_live_per_campaign,
    test_notes_create_list_and_save,
    test_sessions_start_end_and_list,
    test_campaign_activity_over_two_sessions,
    test_house_rules_and_bundles,
    test_campaign_house_rules,
    test_beats_one_current_per_campaign,
    test_beats_latest,
    test_story_put_append_and_list,
    test_dm_log_and_dm_sessions,
    test_module_draft,
    test_conversions_one_running_newest_first,
    test_conversions_paused_oldest_first,
    test_conversions_queue_oldest_first_and_its_switch,
    test_seats_and_controllers,
    test_join_requests,
    test_join_tokens,
    test_account_round_trip,
    test_username_in_use_is_value_error,
    test_password_hash_only_through_its_methods,
    test_link_used_once,
    test_login_sessions_round_trip,
    test_one_live_seat_per_account_and_campaign,
    test_an_account_s_seat_has_no_token,
    test_for_account_and_of_account,
    test_campaign_state_keeps_the_world,
    test_factions_and_clocks,
    test_quests_and_campaign_facts,
    test_possessions_and_their_owners,
    test_world_maps,
    test_merchants,
    test_campaign_images,
    test_the_campaign_lists_reads_of_everything,
    test_world_maps_keep_geo_knowledge_and_reading,
    test_campaign_state_keeps_the_journey,
    test_campaign_status,
    test_conversions_keep_target_result_and_questions,
    test_translations_keep_the_answer,
    test_world_pictures,
    test_setting_pages,
    test_setting_facts,
    test_proposals,
    test_setting_maps,
    test_campaign_voice_and_initiative,
    test_campaign_listing,
    test_campaign_schedule,
    test_character_departure,
    test_conversion_comments_and_closed,
    test_combat_rounds,
    test_module_comments,
)


def run_contract_suite(make_storage: Callable[[], Storage]) -> None:
    """Run every contract check, each against its own fresh storage from `make_storage`."""
    for check in CONTRACT:
        storage = make_storage()
        try:
            check(storage)
        finally:
            storage.close()

