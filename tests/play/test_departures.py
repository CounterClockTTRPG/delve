"""A character leaves the party (table voice and fixes Task C1): it keeps its sheet and its story, leaves a live fight,
comes back with `rejoin_party`, and while away it is out of `party()`, holds no beat up and gets no fallback line."""

import asyncio

import pytest

from delve.play import beats, characters, combat, departures, seats
from delve.play.context import PlayError
from delve.play.table import story
from tests.play.test_beats import Table

GOBLIN = {"name": "goblin", "count": 1, "hp": 5, "ac": 6, "thac0": 20, "dmg": "1d6", "weapon_speed": 6, "morale": 8}


@pytest.fixture
def pcs(ctx):
    return (
        characters.create(ctx, name="Garrek", sheet={"hp_max": 12, "thac0": 18, "ac": 4}),
        characters.create(ctx, name="Tansy", sheet={"hp_max": 8, "thac0": 20, "ac": 7}),
    )


def test_leave_keeps_the_sheet_and_story(storage, campaign, ctx, pcs, owner_seat):
    garrek, tansy = pcs
    beat = storage.beats.open(campaign.id, [], status="running")
    storage.story.append(campaign.id, beat.id, "dm_text", {"text": "Tansy lights a torch."})
    out = departures.leave_party(ctx, "Tansy", "died")
    assert out["character_id"] == tansy.id and out["departure"] == "died"
    stored = storage.characters.get(tansy.id)
    assert stored.departure == "died" and stored.departed_at
    assert stored.sheet == tansy.sheet and stored.state == tansy.state, "the sheet stays as it was"
    assert [c.id for c in characters.party(ctx)] == [garrek.id], "out of the party"
    assert characters.get(ctx, "Tansy").id == tansy.id, "still found by name"
    assert story(storage, campaign.id, owner_seat)["entries"][0].payload["text"] == "Tansy lights a torch."
    logged = [e for e in storage.events.list(campaign.id) if e.type == "departure"]
    assert len(logged) == 1 and logged[0].data["departure"] == "died"
    assert logged[0].data["character_id"] == tansy.id


def test_leave_during_a_fight_leaves_the_fight(storage, campaign, make_ctx, pcs):
    _garrek, tansy = pcs
    ctx = make_ctx(seed=7)
    combat.setup_combat(ctx, enemies=[dict(GOBLIN)], surprise=False)
    out = departures.leave_party(ctx, tansy.id, "left")
    assert out["left_fight"] is True
    fighter = combat.combatant(ctx, tansy.id)
    assert fighter is not None and "removed" in fighter.conditions
    removed = [e for e in storage.events.list(campaign.id) if e.type == "departure"]
    assert removed and removed[-1].data["left_fight"] is True


def test_leave_outside_a_fight_leaves_none(ctx, pcs):
    assert departures.leave_party(ctx, "Garrek", "retired")["left_fight"] is False


def test_rejoin_undoes(storage, ctx, pcs):
    garrek, tansy = pcs
    departures.leave_party(ctx, "Tansy", "retired")
    out = departures.rejoin_party(ctx, "Tansy")
    assert out == {"character_id": tansy.id, "name": "Tansy", "departure": None}
    stored = storage.characters.get(tansy.id)
    assert stored.departure is None and stored.departed_at is None
    assert {c.id for c in characters.party(ctx)} == {garrek.id, tansy.id}
    with pytest.raises(PlayError, match="hasn't left"):
        departures.rejoin_party(ctx, "Tansy")


def test_npc_cannot_leave(ctx, pcs):
    characters.create(ctx, name="Old Bert", kind="npc", sheet={"hp_max": 4})
    with pytest.raises(PlayError, match="NPC"):
        departures.leave_party(ctx, "Old Bert", "left")


def test_leave_twice_or_for_no_reason_is_refused(ctx, pcs):
    with pytest.raises(PlayError, match="one of died, retired, left"):
        departures.leave_party(ctx, "Tansy", "vanished")
    departures.leave_party(ctx, "Tansy", "left")
    with pytest.raises(PlayError, match="already"):
        departures.leave_party(ctx, "Tansy", "died")


def test_leave_is_one_transaction(storage, campaign, ctx, pcs, monkeypatch):
    """A failing log write undoes the departure too."""
    _garrek, tansy = pcs

    def broken(*args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(ctx, "log", broken)
    with pytest.raises(RuntimeError):
        departures.leave_party(ctx, "Tansy", "died")
    assert storage.characters.get(tansy.id).departure is None


@pytest.fixture
def table_of_two(storage, campaign, owner_seat, ctx):
    """Ana plays Garrek, Bo plays Tansy, and nobody plays Pip; all three present with the host."""
    ana = storage.seats.create(campaign.id, "Ana", "en", "player")
    bo = storage.seats.create(campaign.id, "Bo", "en", "player")
    garrek = characters.create(ctx, name="Garrek", sheet={"hp_max": 12})
    tansy = characters.create(ctx, name="Tansy", sheet={"hp_max": 8})
    pip = characters.create(ctx, name="Pip", sheet={"hp_max": 6})
    seats.claim(storage, garrek.id, ana)
    seats.claim(storage, tansy.id, bo)
    table = Table(storage, campaign)
    table.here = {owner_seat.id, ana.id, bo.id}
    return table, ana, bo, garrek, tansy, pip


def test_departed_pc_holds_no_beat(campaign, owner_seat, ctx, table_of_two):
    """Bo's only PC and the PC the host covered have left: neither Bo nor the host is waited for, and the host's act
    no longer covers the departed PC."""
    table, ana, _bo, _garrek, tansy, pip = table_of_two
    departures.leave_party(ctx, tansy.id, "died")
    departures.leave_party(ctx, pip.id, "left")
    assert beats.waiting_for(table.services, campaign.id, []) == {ana.id}

    async def scenario():
        beat = table.submit(ana, "act", "I bury Tansy.")
        assert beat.status == "running", "nobody else holds the beat up"
        return await table.answered()

    done = asyncio.run(scenario())
    assert [s["kind"] for s in done.submissions] == ["act"], "no fallback for the departed"
    assert table.dm.sent == ["Garrek:\n> I bury Tansy."]


def test_departed_pc_gets_no_fallback(campaign, owner_seat, ctx, table_of_two):
    """At go, Bo's departed PC gets no fallback line, while Pip, whom nobody plays, still does; the host's own act
    leaves a departed free PC out."""
    table, ana, _bo, garrek, tansy, pip = table_of_two
    departures.leave_party(ctx, tansy.id, "retired")

    async def scenario():
        table.submit(ana, "act", "I listen.")
        beats.go(table.services, campaign.id, owner_seat)
        return await table.answered()

    done = asyncio.run(scenario())
    lines = table.dm.sent[0].splitlines()
    assert "(Pip holds back this beat: they do nothing.)" in lines
    assert not any("Tansy" in line for line in lines)
    assert all(tansy.id not in s["characters"] for s in done.submissions)
    assert garrek.id in done.submissions[0]["characters"]

    departures.leave_party(ctx, pip.id, "left")
    host_act = beats.submit(table.services, campaign.id, owner_seat, "pass")
    assert next(s for s in host_act.submissions if s["seat_id"] == owner_seat.id)["characters"] == []
