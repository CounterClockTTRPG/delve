"""Hotseat play (DEL-365): several players at the host's screen, each acting for their own characters, one beat
waiting for all of them; the DM reads each act under its player's name."""

import asyncio

import pytest

from delve.play import beats, hotseat, seats
from delve.play.context import PlayError
from delve.play.table import play_settings, set_play_settings, story
from tests.play.test_beats import Table


@pytest.fixture
def host(owner_seat):
    return owner_seat


@pytest.fixture
def trio(storage, campaign):
    """Garrek, Mira and Pip, whom nobody has claimed: the host's seat plays them all."""
    return tuple(storage.characters.create(campaign.id, name) for name in ("Garrek", "Mira", "Pip"))


def seat_players(storage, campaign, players, on=True):
    stored = set_play_settings(storage, campaign.id, {"hotseat": on, "hotseat_players": players})
    return {p["name"]: p["id"] for p in stored["hotseat_players"]}


def hotseat_submit(table, seat, player, kind="act", text="", characters=None):
    return beats.submit(table.services, table.campaign.id, seat, kind, text, characters, player=player)


def test_the_beat_waits_for_every_player_at_the_screen(storage, campaign, host, trio):
    garrek, mira, pip = trio
    ids = seat_players(
        storage, campaign, [{"name": "Anna", "characters": [garrek.id]}, {"name": "Ben", "characters": [mira.id, pip.id]}]
    )
    table = Table(storage, campaign)
    table.here = {host.id}

    async def scenario():
        first = hotseat_submit(table, host, ids["Anna"], text="I listen at the door.")
        assert first.status == "open", "alone at the table, the beat still waits for Ben"
        assert table.beat_events()[-1]["submitted"] == [host.id]
        mine = beats.pending(storage, campaign.id, host)
        assert [(p["name"], p["hotseat"], p["characters"]) for p in mine] == [("Anna", ids["Anna"], [garrek.id])]
        second = hotseat_submit(table, host, ids["Ben"], text="We keep watch.")
        assert second.status == "running" and second.id == first.id
        return await table.answered()

    done = asyncio.run(scenario())
    assert done.status == "done"
    assert table.dm.sent[0].splitlines() == [
        "Anna (playing Garrek):",
        "> I listen at the door.",
        "Ben (playing Mira, Pip):",
        "> We keep watch.",
    ]
    acts = [e.payload for e in story(storage, campaign.id, host)["entries"] if e.kind == "player_act"]
    assert [(a["name"], a["text"]) for a in acts] == [("Anna", "I listen at the door."), ("Ben", "We keep watch.")]


def test_a_player_changes_only_their_own_act(storage, campaign, host, trio):
    garrek, mira, _pip = trio
    ids = seat_players(storage, campaign, [{"name": "Anna", "characters": [garrek.id]}, {"name": "Ben", "characters": [mira.id]}])
    table = Table(storage, campaign)
    table.here = {host.id}
    hotseat_submit(table, host, ids["Anna"], text="I listen.")
    beat = hotseat_submit(table, host, ids["Anna"], text="I knock.")
    assert beat.status == "open"
    assert [(s.get("hotseat"), s["text"]) for s in beat.submissions] == [(ids["Anna"], "I knock.")]


def test_the_hosts_other_characters_need_their_own_turn(storage, campaign, host, trio):
    """Pip is no hotseat player's: the host's seat acts for him, apart, and the beat waits for that too."""
    garrek, mira, pip = trio
    ids = seat_players(storage, campaign, [{"name": "Anna", "characters": [garrek.id]}, {"name": "Ben", "characters": [mira.id]}])
    table = Table(storage, campaign)
    table.here = {host.id}

    async def scenario():
        hotseat_submit(table, host, ids["Anna"], text="I listen.")
        assert hotseat_submit(table, host, ids["Ben"], kind="pass").status == "open"
        closed = table.submit(host, "act", "Pip searches the floor.")
        assert closed.status == "running"
        return await table.answered()

    done = asyncio.run(scenario())
    own = next(s for s in done.submissions if s["seat_id"] == host.id and not s.get("hotseat"))
    assert own["characters"] == [pip.id], "the host's default leaves the hotseat players' characters out"
    assert table.dm.sent[0].splitlines() == [
        "Anna (playing Garrek):",
        "> I listen.",
        "Ben passes.",
        "Host (playing Pip):",
        "> Pip searches the floor.",
    ]


def test_go_gives_the_players_who_didnt_act_the_fallback(storage, campaign, host, trio):
    garrek, mira, pip = trio
    ids = seat_players(
        storage, campaign, [{"name": "Anna", "characters": [garrek.id]}, {"name": "Ben", "characters": [mira.id, pip.id]}]
    )
    table = Table(storage, campaign)
    table.here = {host.id}

    async def scenario():
        hotseat_submit(table, host, ids["Anna"], text="I listen.")
        beats.go(table.services, campaign.id, host)
        return await table.answered()

    done = asyncio.run(scenario())
    fallbacks = [s for s in done.submissions if s["kind"] == "fallback"]
    assert [(s["seat_id"], s.get("hotseat"), s["characters"]) for s in fallbacks] == [
        (host.id, ids["Ben"], [mira.id, pip.id])
    ]
    assert table.dm.sent[0].splitlines()[-1] == "(Mira, Pip hold back this beat: they do nothing.)"


def test_a_hotseat_beside_a_seat_at_its_own_screen(storage, campaign, host, trio):
    """Cleo joined from her own browser and plays Pip: the beat waits for her and for both players at the host's."""
    garrek, mira, pip = trio
    cleo = storage.seats.create(campaign.id, "Cleo", "en", "player")
    seats.claim(storage, pip.id, cleo)
    ids = seat_players(
        storage, campaign, [{"name": "Anna", "characters": [garrek.id]}, {"name": "Ben", "characters": [mira.id, pip.id]}]
    )
    assert [p["characters"] for p in hotseat.players(storage, campaign.id)] == [[garrek.id], [mira.id]], (
        "Pip is Cleo's now, whatever the list says"
    )
    table = Table(storage, campaign)
    table.here = {host.id, cleo.id}

    async def scenario():
        assert table.submit(cleo, "act", "I sneak ahead.").status == "open"
        assert hotseat_submit(table, host, ids["Anna"], text="I follow.").status == "open"
        assert hotseat_submit(table, host, ids["Ben"], text="I light a torch.").status == "running"
        return await table.answered()

    asyncio.run(scenario())
    assert table.dm.sent[0].splitlines() == [
        "Cleo (playing Pip):",
        "> I sneak ahead.",
        "Anna (playing Garrek):",
        "> I follow.",
        "Ben (playing Mira):",
        "> I light a torch.",
    ]


def test_turning_hotseat_off_leaves_the_host_one_act_again(storage, campaign, host, trio):
    garrek, _mira, _pip = trio
    ids = seat_players(storage, campaign, [{"name": "Anna", "characters": [garrek.id]}], on=False)
    table = Table(storage, campaign)
    table.here = {host.id}
    assert hotseat.players(storage, campaign.id) == []
    with pytest.raises(PlayError, match="Hotseat is off"):
        hotseat_submit(table, host, ids["Anna"], text="I listen.")

    async def scenario():
        assert table.submit(host, "act", "We all go in.").status == "running", "one act closes it, as in solo play"
        return await table.answered()

    assert asyncio.run(scenario()).status == "done"


def test_nobody_but_the_host_plays_the_hotseat_and_nothing_is_private(storage, campaign, host, trio):
    garrek, *_ = trio
    ana = storage.seats.create(campaign.id, "Ana", "en", "cohost")
    ids = seat_players(storage, campaign, [{"name": "Anna", "characters": [garrek.id]}])
    table = Table(storage, campaign)
    table.here = {host.id, ana.id}
    with pytest.raises(PlayError, match="host's screen"):
        hotseat_submit(table, ana, ids["Anna"], text="I listen.")
    with pytest.raises(PlayError, match="shared screen"):
        beats.submit(table.services, campaign.id, host, "act", "A secret.", private=True, player=ids["Anna"])
    with pytest.raises(PlayError, match="No such hotseat player"):
        hotseat_submit(table, host, "hs_nobody", text="I listen.")


def test_the_players_are_checked_before_they_are_stored(storage, campaign, trio):
    garrek, mira, _pip = trio
    stored = set_play_settings(
        storage, campaign.id, {"hotseat_players": [{"name": "  Anna   Lee ", "characters": [garrek.id, garrek.id]}]}
    )["hotseat_players"]
    assert [(p["name"], p["characters"]) for p in stored] == [("Anna Lee", [garrek.id])]
    assert stored[0]["id"].startswith("hs_")
    kept = set_play_settings(storage, campaign.id, {"hotseat_players": stored})["hotseat_players"]
    assert kept[0]["id"] == stored[0]["id"], "a player keeps their id"
    refused = [
        ([{"name": "", "characters": []}], "needs a name"),
        ([{"name": "Anna"}, {"name": "anna"}], "Two hotseat players"),
        ([{"name": "Anna", "characters": [garrek.id]}, {"name": "Ben", "characters": [garrek.id]}], "played by Anna"),
        ([{"name": "Anna", "characters": ["chr_nope"]}], "No such PC"),
        ([{"name": f"P{n}"} for n in range(hotseat.MAX_PLAYERS + 1)], "at most"),
        ([{"name": "A" * (hotseat.NAME_CHARS + 1)}], "at most"),
        ([{"name": "Anna", "seat": "x"}], "a name and the characters"),
        ("Anna", "a list"),
    ]
    for players, message in refused:
        with pytest.raises(PlayError, match=message):
            set_play_settings(storage, campaign.id, {"hotseat_players": players})
    with pytest.raises(PlayError, match="on or off"):
        set_play_settings(storage, campaign.id, {"hotseat": "yes"})
    assert play_settings(storage, campaign.id)["hotseat_players"] == kept
    assert mira.id not in str(kept)
