"""The characters API answers each character's kind, sheet, state and order (plan 2a, for Task 13's sheets)."""


from delve.dice import ScriptedRng
from delve.play import characters
from delve.play.context import context_for
from tests.fixtures.play_reference import PlayReference
from tests.fixtures.rulesets import osric, over
from tests.web.test_campaigns_api import played
from tests.web.test_house_rules_api import published


def test_characters_have_sheet_state_and_order(local, storage):
    started, (ana,) = played(local, names=("Ana",))
    ctx = context_for(storage, started["id"], "beat-1", ScriptedRng([]), catalogs=over(PlayReference()))
    garrek = characters.create(ctx, name="Garrek", sheet={"cls": "Fighter", "level": 3, "hp_max": 24, "ac": 4})
    characters.apply_damage(ctx, "Garrek", 5)
    tira = characters.create(ctx, name="Tira", kind="npc", sheet={"race": "elf"})

    listed = {c["name"]: c for c in local.get(f"/api/campaigns/{started['id']}/characters").json()}
    assert [(c["kind"], c.get("order")) for c in listed.values()] == [("pc", 0), ("pc", 1), ("npc", None)]
    sheet = listed["Garrek"]["sheet"]
    assert (sheet["label"], sheet["cls"], sheet["levels"], sheet["hp_max"], sheet["ac"]) == (
        "Garrek",
        "Fighter",
        {"fighter": 3},
        24,
        4,
    )
    assert sheet["saves"] == garrek.sheet.saves
    assert listed["Garrek"]["state"] == {**garrek.state.to_dict(), "hp": 19}
    assert listed["Tira"] == {"id": tira.id, "name": "Tira", "kind": "npc"}, "an NPC is the DM's to know"
    assert listed["Ana"]["id"] == ana


def test_character_changes_publish_characters(local, app):
    started, (ana,) = played(local, names=("Ana",))
    cid = started["id"]
    local.patch(f"/api/campaigns/{cid}/characters/{ana}", json={"name": "Anna"})
    local.request("DELETE", f"/api/campaigns/{cid}/characters/{ana}", json={})
    assert [e for e in published(app) if e[0] == "characters"] == [("characters", {"campaign_id": cid})] * 3


def test_characters_carry_their_encumbrance(config, storage, static_dir):
    """Plan 2a Task 13/14: each character's `encumbrance` is `play.inventory.encumbrance`, computed on the server from
    its inventory and the 2e reference; the browser computes no rules. Without a 2e reference it is null."""
    from fastapi.testclient import TestClient

    from delve.__main__ import build_registries
    from delve.play import inventory
    from delve.web.app import create_app
    from tests.web.conftest import BASE_URL

    registries = build_registries(config)
    registries.catalogs = over(PlayReference())
    app = create_app(config, storage, registries, static_dir=static_dir)
    with TestClient(app, base_url=BASE_URL, client=("127.0.0.1", 50000)) as local:
        started, _ = played(local, names=("Ana",))
        ctx = context_for(storage, started["id"], "beat-1", ScriptedRng([]), catalogs=over(PlayReference()))
        characters.create(ctx, name="Garrek", sheet={"hp_max": 10, "ability_scores": {"str": 16}, "movement_rate": 12})
        inventory.add_item(ctx, "Garrek", "Plate Mail")
        inventory.add_item(ctx, "Garrek", "Rope (per 50 ft.), Hemp")
        listed = {c["name"]: c for c in local.get(f"/api/campaigns/{started['id']}/characters").json()}
    expected = inventory.encumbrance(ctx, "Garrek")
    assert listed["Garrek"]["encumbrance"] == {k: expected[k] for k in ("total_lb", "band", "movement", "penalty")}
    assert listed["Garrek"]["encumbrance"]["total_lb"] == 70
    assert listed["Ana"]["encumbrance"]["total_lb"] == 0


def test_encumbrance_is_null_without_a_reference(local, storage):
    started, _ = played(local, names=("Ana",))
    assert [c["encumbrance"] for c in local.get(f"/api/campaigns/{started['id']}/characters").json()] == [None]


def test_an_npcs_story_is_the_organisers_and_never_a_seats(app, local, storage):
    """Plan walkthrough Task 8: the organiser's `…/dm/characters` has an NPC's story (`notes_md`) and disposition; the
    seat's `…/characters` still has neither, for an NPC or a PC, and refuses the organiser's route with 403."""
    from fastapi.testclient import TestClient

    from delve.web.seats import SEAT_COOKIE, new_seat_token, token_hash
    from tests.web.conftest import BASE_URL

    started, _ = played(local, names=("Ana",))
    cid = started["id"]
    ctx = context_for(storage, cid, "beat-1", ScriptedRng([]), catalogs=over(PlayReference()))
    characters.create(ctx, name="Tira", kind="npc", sheet={"race": "elf", "notes_md": "SECRET-XYZZY", "disposition": 40})
    characters.create(ctx, name="Garrek", sheet={"hp_max": 8, "notes_md": "SECRET-XYZZY"})

    organiser = {c["name"]: c for c in local.get(f"/api/campaigns/{cid}/dm/characters").json()}
    assert (organiser["Tira"]["sheet"]["notes_md"], organiser["Tira"]["sheet"]["disposition"]) == ("SECRET-XYZZY", 40)

    token = new_seat_token()
    storage.seats.create(cid, "Bo", "en", "player", token_hash=token_hash(token))
    with TestClient(app, base_url=BASE_URL) as seat:
        seat.cookies.set(SEAT_COOKIE, token)
        listed = seat.get(f"/api/campaigns/{cid}/characters")
        assert listed.status_code == 200
        assert "SECRET-XYZZY" not in listed.text and "notes_md" not in listed.text and "disposition" not in listed.text
        assert seat.get(f"/api/campaigns/{cid}/dm/characters").status_code == 403


def test_attacks_carry_their_worked_thac0(config, storage, static_dir):
    """Plateau 7 Task 20: each attack has `thac0_worked`, `rules.classic.thac0.attack_thac0` on the server, which the
    fight uses too; without a reference there is none."""
    from fastapi.testclient import TestClient

    from delve.__main__ import build_registries
    from delve.web.app import create_app
    from tests.web.conftest import BASE_URL

    sheet = {
        "cls": "Fighter",
        "thac0": 18,
        "weapon_profs": ["dagger"],
        "attacks": [{"name": "long sword +1", "damage_sm": "1d8+1"}, {"name": "dagger", "thac0": 12}],
    }
    registries = build_registries(config)
    registries.catalogs = over(PlayReference())
    app = create_app(config, storage, registries, static_dir=static_dir)
    with TestClient(app, base_url=BASE_URL, client=("127.0.0.1", 50000)) as local:
        started, _ = played(local, names=("Ana",))
        ctx = context_for(storage, started["id"], "beat-1", ScriptedRng([]), catalogs=over(PlayReference()))
        characters.create(ctx, name="Garrek", sheet=sheet)
        listed = {c["name"]: c for c in local.get(f"/api/campaigns/{started['id']}/characters").json()}
    sword, dagger = listed["Garrek"]["sheet"]["attacks"]
    assert sword["thac0"] is None
    assert sword["thac0_worked"] == {"value": 19, "parts": [["base", 18], ["nonproficient", 2], ["magic", -1]]}
    assert dagger["thac0_worked"] == {"value": 12, "parts": [["stored", 12]]}


def test_attacks_have_no_worked_thac0_without_a_reference(local, storage):
    started, _ = played(local, names=("Ana",))
    ctx = context_for(storage, started["id"], "beat-1", ScriptedRng([]), catalogs=over(PlayReference()))
    characters.create(ctx, name="Garrek", sheet={"attacks": [{"name": "club", "damage_sm": "1d6"}]})
    listed = {c["name"]: c for c in local.get(f"/api/campaigns/{started['id']}/characters").json()}
    assert "thac0_worked" not in listed["Garrek"]["sheet"]["attacks"][0]


def test_characters_carry_the_emote_their_sheets_show(local, storage):
    """Portraits plan Task 9: `sheet_emote` of the character's HP and conditions, on the seat's and the DM's route."""
    started, _ = played(local, names=("Ana",))
    cid = started["id"]
    ctx = context_for(storage, cid, "beat-1", ScriptedRng([]), catalogs=over(PlayReference()))
    characters.create(ctx, name="Garrek", sheet={"cls": "Fighter", "level": 3, "hp_max": 21})
    characters.create(ctx, name="Mira", sheet={"cls": "Thief", "level": 2, "hp_max": 21})
    characters.create(ctx, name="Odo", sheet={"cls": "Cleric", "level": 2, "hp_max": 21})
    characters.apply_damage(ctx, "Garrek", 14)
    characters.update(ctx, "Mira", {"conditions": ["Frightened"]})
    characters.apply_damage(ctx, "Odo", 21)

    for route in ("characters", "dm/characters"):
        listed = {c["name"]: c for c in local.get(f"/api/campaigns/{cid}/{route}").json()}
        assert {name: listed[name]["emote"] for name in ("Garrek", "Mira", "Odo")} == {
            "Garrek": "upset",
            "Mira": "afraid",
            "Odo": "sleep",
        }


def test_characters_carry_each_class_xp_progress(config, storage, static_dir):
    """Backlog 25: each character's `xp_progress` is `class_xp.progress` on its sheet and XP total, one row per class
    with its share, level and the share its next level needs, so the sheet shows how close a level is. Without a 2e
    reference it is null."""
    from fastapi.testclient import TestClient

    from delve.__main__ import build_registries
    from delve.rules.classic import class_xp
    from delve.web.app import create_app
    from tests.web.conftest import BASE_URL

    registries = build_registries(config)
    registries.catalogs = over(PlayReference())
    app = create_app(config, storage, registries, static_dir=static_dir)
    with TestClient(app, base_url=BASE_URL, client=("127.0.0.1", 50000)) as local:
        started, _ = played(local, names=("Ana",))
        ctx = context_for(storage, started["id"], "beat-1", ScriptedRng([]), catalogs=over(PlayReference()))
        garrek = characters.create(ctx, name="Garrek", sheet={"cls": "Fighter", "level": 3, "hp_max": 24})
        characters.award_xp(ctx, "Garrek", 5000)
        listed = {c["name"]: c for c in local.get(f"/api/campaigns/{started['id']}/characters").json()}
    rows = listed["Garrek"]["xp_progress"]
    assert rows == class_xp.progress(garrek.sheet, 5000, PlayReference(), rules=osric().tables)
    assert (rows[0]["class"], rows[0]["level"], rows[0]["xp"], rows[0]["xp_next"]) == ("Fighter", 3, 5000, 8000)


def test_xp_progress_is_null_without_a_reference(local, storage):
    started, _ = played(local, names=("Ana",))
    assert [c["xp_progress"] for c in local.get(f"/api/campaigns/{started['id']}/characters").json()] == [None]
