"""A PC the DM makes for a player is theirs at once (DEL-253): a new player asked "a human fighter named Mira", the DM
made her, and the player still played no character."""

from dataclasses import replace

import pytest

GARREK = {"race": "Human", "cls": "Fighter", "hp_max": 10}


@pytest.fixture
def asks(storage, campaign, host):
    """`asks(*seats)`: a running beat in which these seats acted, and the call of a tool in it."""

    def make(*acting):
        current = storage.beats.current(campaign.id)
        if current is not None:  # the beat before is over
            storage.beats.save(replace(current, status="done", closed_at="2026-10-28T12:00:00+00:00"))
        submissions = [{"player": s.id, "character_ids": [], "kind": "act", "text": "Make me one."} for s in acting]
        beat = storage.beats.open(campaign.id, submissions, status="running")
        return lambda tool, **args: host.call(campaign.id, beat.id, tool, args)

    return make


def controller(storage, character_id):
    return storage.characters.get(character_id).controller_id


def test_the_one_player_who_asked_gets_the_pc(storage, campaign, asks):
    ana = storage.seats.create(campaign.id, "Ana", "en", "player")
    call = asks(ana)
    mira = call("create_character", name="Mira", sheet=GARREK)
    assert mira["played_by"] == "Ana" and controller(storage, mira["id"]) == ana.id


def test_a_named_player_gets_it_when_several_asked(storage, campaign, asks):
    ana = storage.seats.create(campaign.id, "Ana", "en", "player")
    bo = storage.seats.create(campaign.id, "Bo", "en", "player")
    call = asks(ana, bo)
    unnamed = call("create_character", name="Who", sheet=GARREK)
    assert "played_by" not in unnamed and controller(storage, unnamed["id"]) is None, "two asked: the host's for now"
    pip = call("create_character", name="Pip", sheet=GARREK, player="bo")
    assert pip["played_by"] == "Bo" and controller(storage, pip["id"]) == bo.id
    refused = call("create_character", name="X", sheet=GARREK, player="Zed")
    assert "No player 'Zed'" in refused["error"] and "Ana, Bo" in refused["hint"]


def test_a_host_or_a_player_who_has_a_character_doesnt_get_it_by_default(storage, campaign, asks):
    """The host makes the pregens' party and plays the PCs nobody has; a player with a character asked for another."""
    ana = storage.seats.create(campaign.id, "Ana", "en", "player")
    first = asks(ana)("create_character", name="Mira", sheet=GARREK)
    assert first["played_by"] == "Ana"
    again = asks(ana)("create_character", name="Second", sheet=GARREK)
    assert "played_by" not in again, "Ana plays Mira already"
    host = storage.seats.create(campaign.id, "Raf", "en", "host")
    by_host = asks(host)("create_character", name="Pregen", sheet=GARREK)
    assert "played_by" not in by_host and controller(storage, by_host["id"]) is None


def test_an_npc_has_no_player(storage, campaign, asks):
    ana = storage.seats.create(campaign.id, "Ana", "en", "player")
    call = asks(ana)
    npc = call("create_character", name="Tira", kind="npc", sheet={"race": "Human"})
    assert "played_by" not in npc and controller(storage, npc["id"]) is None
    assert call("create_character", name="T2", kind="npc", sheet={}, player="Ana")["error"] == "An NPC is yours to play."
