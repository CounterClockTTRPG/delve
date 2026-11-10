"""The table's session state (DEL-199): gathering, playing and a break, which the host and co-hosts move; the session's
start and end as Delve-written beats; the absent PCs' choices as their fallbacks; the beat timer stopped by a break;
the raised hands; and seats away mid-session, with the parts their PCs take (DEL-224)."""

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from delve.dm.provider import TextDelta, ToolCall, ToolResult
from delve.domain.campaigns import TableSession
from delve.play import beats, seats, table_session
from delve.play.context import PlayError
from delve.play.seats import NotAllowed
from delve.play.table import BEGIN_SESSION, BeatRunning, set_play_settings
from tests.play.test_beats import Table


@pytest.fixture
def host(owner_seat):
    return owner_seat


@pytest.fixture
def party(storage, campaign, host):
    """Garrek, played by Ana; Mira, played by Bo; and Pip, whom nobody plays."""
    ana = storage.seats.create(campaign.id, "Ana", "en", "player")
    bo = storage.seats.create(campaign.id, "Bo", "en", "player")
    garrek = storage.characters.create(campaign.id, "Garrek")
    mira = storage.characters.create(campaign.id, "Mira")
    pip = storage.characters.create(campaign.id, "Pip")
    seats.claim(storage, garrek.id, ana)
    seats.claim(storage, mira.id, bo)
    return ana, bo, garrek, mira, pip


def gathering(storage, campaign):
    storage.table_sessions.put(TableSession(campaign.id, "gathering"))


def table_events(table):
    return [data for kind, data in table.events if kind == "table"]


# ----- the state without a stored row -----


def test_a_new_table_gathers_and_a_table_mid_session_plays(storage, campaign, host):
    """No row yet: gathering while the pregame's rule says so, else playing, so a table mid-session keeps playing."""
    assert table_session.current(storage, campaign.id).state == "gathering"
    storage.story.append(campaign.id, None, "player_act", {"text": "I open the door."})
    assert table_session.current(storage, campaign.id).state == "playing"
    storage.story.append(campaign.id, None, "recap", {"text": "A door was opened."})
    assert table_session.current(storage, campaign.id).state == "gathering"
    storage.table_sessions.put(TableSession(campaign.id, "break", break_at="2026-10-27T20:00:00+00:00"))
    assert table_session.current(storage, campaign.id).state == "break", "a stored row wins"


def test_a_session_the_dm_has_started_is_being_played(storage, campaign, host):
    """A DM session that is open and not ended (`new_session`) is play under way, before any act was stored."""
    Table(storage, campaign)  # starts the DM's session
    assert table_session.current(storage, campaign.id).state == "playing"


def test_the_table_json(storage, campaign, host, party):
    ana, bo, _garrek, _mira, _pip = party
    table = Table(storage, campaign)
    shown = table_session.table_json(storage, campaign.id)
    assert shown == {"state": "playing", "since": None, "solo": False, "absent": {}, "hands": [], "away": []}
    storage.seats.save(replace(ana, left_at="2026-10-27T19:00:00+00:00"))
    storage.seats.save(replace(bo, role="observer"))
    assert table_session.table_json(storage, campaign.id)["solo"] is True, "only the host still plays"
    assert table.events == []


# ----- gathering -----


def test_while_gathering_acts_and_passes_wait_for_the_host(storage, campaign, host, party):
    ana, bo, *_ = party
    table = Table(storage, campaign)
    gathering(storage, campaign)
    for seat, kind in ((ana, "act"), (bo, "pass"), (host, "act")):
        with pytest.raises(table_session.NotStarted) as refused:
            table.submit(seat, kind, "I open the door." if kind == "act" else "")
        assert refused.value.message == "The session hasn't started yet: the host starts it."
    assert table.beat() is None and table_session.current(storage, campaign.id).state == "gathering"


def test_at_a_solo_table_the_first_act_starts_the_session(storage, campaign, host):
    storage.characters.create(campaign.id, "Garrek")
    table = Table(storage, campaign)
    gathering(storage, campaign)

    async def scenario():
        beat = table.submit(host, "act", "We open the door.")
        assert beat.status == "running"
        return await table.answered()

    assert asyncio.run(scenario()).status == "done"
    assert table_session.current(storage, campaign.id).state == "playing"
    assert [e["table"]["state"] for e in table_events(table)] == ["playing"]
    assert table_events(table)[0]["campaign_id"] == campaign.id


# ----- starting the session -----


def test_the_host_starts_the_session_with_the_absent_pcs_choices(storage, campaign, host, party):
    _ana, _bo, garrek, mira, pip = party
    storage.characters.save(replace(storage.characters.get(pip.id), name="Pip\nthe Quick"))
    table = Table(storage, campaign)
    gathering(storage, campaign)
    absent = {garrek.id: "in_character", mira.id: "hold_back", pip.id: "out"}

    async def scenario():
        state, beat = table_session.start_session(table.services, campaign.id, host, absent)
        assert state.state == "playing" and state.absent == absent and state.since is not None
        assert beat.status == "running"
        return beat, await table.answered()

    _beat, done = asyncio.run(scenario())
    assert done.status == "done"
    assert [s["kind"] for s in done.submissions] == ["session"], "the start's beat gets no fallbacks"
    assert done.submissions[0]["seat_id"] == host.id
    message = table.dm.sent[0]
    assert BEGIN_SESSION not in message, "the DM's session is already open here"
    (line,) = message.splitlines()
    assert line.startswith("[Not from a player:") and line.endswith("]")
    assert "Garrek" in line and "cautiously" in line and "until their player arrives" in line
    assert "Mira" in line and "in the background" in line
    assert "Pip the Quick" in line and "keep them out of the scene" in line
    assert table_events(table)[-1]["table"]["state"] == "playing"
    assert table_events(table)[-1]["table"]["absent"] == absent


def test_a_new_session_starts_with_the_dm_s_session_start(storage, campaign, host):
    """At a table whose DM session ended (or never began), the start's beat begins with `BEGIN_SESSION`."""
    table = Table(storage, campaign)
    storage.sessions.end(campaign.id, storage.campaign_states.get(campaign.id).session, "The first evening.")
    storage.story.append(campaign.id, None, "recap", {"text": "The first evening."})

    async def scenario():
        table_session.start_session(table.services, campaign.id, host, {})
        await table.answered()

    asyncio.run(scenario())
    assert table.dm.sent[0].startswith(BEGIN_SESSION)
    assert table.dm.sent[0].splitlines()[-1].startswith("[Not from a player: the host starts")


def test_starting_the_session_is_refused_out_of_turn(storage, campaign, host, party):
    ana, _bo, garrek, *_ = party
    table = Table(storage, campaign)
    gathering(storage, campaign)
    with pytest.raises(NotAllowed):
        table_session.start_session(table.services, campaign.id, ana, {})
    with pytest.raises(PlayError) as unknown:
        table_session.start_session(table.services, campaign.id, host, {"chr_000000000000": "out"})
    assert not isinstance(unknown.value, table_session.SessionRefused)
    with pytest.raises(PlayError) as mode:
        table_session.start_session(table.services, campaign.id, host, {garrek.id: "asleep"})
    assert not isinstance(mode.value, table_session.SessionRefused)
    storage.beats.open(campaign.id, [], status="open")
    with pytest.raises(table_session.SessionRefused):
        table_session.start_session(table.services, campaign.id, host, {})
    storage.table_sessions.put(TableSession(campaign.id, "playing"))
    with pytest.raises(table_session.SessionRefused):
        table_session.start_session(table.services, campaign.id, host, {})
    assert table_events(table) == []


def test_starting_while_the_dm_answers_is_refused(storage, campaign, host):
    table = Table(storage, campaign)
    gathering(storage, campaign)
    storage.beats.open(campaign.id, [], status="running")
    with pytest.raises(BeatRunning):
        table_session.start_session(table.services, campaign.id, host, {})


def test_an_absent_pc_s_choice_is_its_fallback(storage, campaign, host, party):
    """The play settings hold back, but the host chose: Garrek is played in character, Mira is out of the session
    and gets no line at all; Pip, nobody's, holds back by the settings."""
    _ana, _bo, garrek, mira, pip = party
    table = Table(storage, campaign)
    gathering(storage, campaign)
    table.here = {host.id}

    async def scenario():
        table_session.start_session(table.services, campaign.id, host, {garrek.id: "in_character", mira.id: "out"})
        await table.answered()
        table.submit(host, "act", "We wait.", characters=[])
        return await table.answered()

    done = asyncio.run(scenario())
    lines = table.dm.sent[1].splitlines()
    assert lines[-2:] == [
        (
            "(Nobody is playing Garrek this beat: play a cautious action for them — keep watch or follow the party; "
            "spend no spell or charge, and start no fight.)"
        ),
        "(Pip holds back this beat: they do nothing.)",
    ]
    assert "Mira" not in table.dm.sent[1]
    assert {cid for s in done.submissions if s["kind"] == "fallback" for cid in s["characters"]} == {garrek.id, pip.id}


# ----- a break -----


def test_a_break_refuses_acts_passes_and_go(storage, campaign, host, party):
    ana, *_ = party
    table = Table(storage, campaign)
    with pytest.raises(table_session.SessionRefused):
        table_session.back_to_story(table.services, campaign.id, host)
    state = table_session.take_break(table.services, campaign.id, host)
    assert state.state == "break" and state.break_at is not None
    with pytest.raises(table_session.OnABreak) as refused:
        table.submit(ana, "act", "I listen.")
    assert refused.value.message == "The table is on a break."
    with pytest.raises(table_session.OnABreak):
        table.submit(ana, "pass")
    with pytest.raises(table_session.OnABreak):
        beats.go(table.services, campaign.id, host)
    with pytest.raises(table_session.SessionRefused):
        table_session.take_break(table.services, campaign.id, host)
    with pytest.raises(NotAllowed):
        table_session.back_to_story(table.services, campaign.id, ana)
    assert table_session.back_to_story(table.services, campaign.id, host).state == "playing"
    assert [e["table"]["state"] for e in table_events(table)] == ["break", "playing"]


def test_a_break_stops_the_beat_timer_and_the_story_moves_its_deadline_on(storage, campaign, host, party):
    ana, bo, *_ = party
    set_play_settings(storage, campaign.id, {"beat_timer_s": 60})
    table = Table(storage, campaign)
    table.here = {ana.id, bo.id}

    async def scenario():
        opened = table.submit(ana, "act", "I listen.")
        await table.clock.advance(20)
        table_session.take_break(table.services, campaign.id, host)
        assert campaign.id not in table.services.timers, "the timer stops"
        await table.clock.advance(300)
        assert table.beat().status == "open", "a break closes nothing"
        table.here = {ana.id}  # Bo went away: nobody is waited for, but the break holds
        assert beats.recheck(table.services, campaign.id) is None
        beats.timer_changed(table.services, campaign.id)
        assert table.beat().status == "open" and campaign.id not in table.services.timers
        table_session.back_to_story(table.services, campaign.id, host)
        table.here = {ana.id, bo.id}
        moved = table.beat()
        shift = datetime.fromisoformat(moved.opened_at) - datetime.fromisoformat(opened.opened_at)
        assert shift == timedelta(seconds=300), "the opening moves on by the break's length"
        assert campaign.id in table.services.timers
        await table.clock.advance(39)
        assert table.beat().status == "open", "40 of its 60 seconds were left"
        await table.clock.advance(2)
        return await table.answered()

    assert asyncio.run(scenario()).status == "done"


def test_a_restart_during_a_break_closes_nothing(storage, campaign, host, party):
    ana, bo, *_ = party
    table = Table(storage, campaign)
    table.here = {ana.id, bo.id}

    async def scenario():
        table.submit(ana, "act", "I listen.")
        table_session.take_break(table.services, campaign.id, host)
        beats.resume(table.services)  # Delve starts again
        assert table.beat().status == "open" and table.services.timers == {}

    asyncio.run(scenario())


# ----- ending the session -----


def test_the_host_ends_the_session(storage, campaign, host, party):
    ana, _bo, garrek, *_ = party
    recap = "They opened the crypt."
    script = [
        [TextDelta("The party settles in.")],
        [
            TextDelta("And so the evening ends."),
            ToolCall("t1", "end_session", {"recap": recap}),
            ToolResult("t1", True, {"session": 1, "title": "The Crypt", "recap_md": recap}),
        ],
    ]
    table = Table(storage, campaign, script)
    gathering(storage, campaign)

    async def scenario():
        with pytest.raises(table_session.SessionRefused):
            table_session.end_session(table.services, campaign.id, host)
        table_session.start_session(table.services, campaign.id, host, {garrek.id: "hold_back"})
        await table.answered()
        table_session.raise_hand(table.services, campaign.id, ana, "One thing")
        state, beat = table_session.end_session(table.services, campaign.id, host)
        assert state.state == "gathering" and state.absent == {} and state.hands == {}
        assert beat.status == "running" and [s["kind"] for s in beat.submissions] == ["session"]
        return await table.answered()

    assert asyncio.run(scenario()).status == "done"
    (line,) = table.dm.sent[1].splitlines()
    assert line.startswith("[Not from a player:") and "end_session(recap)" in line and "pause" in line
    assert table_session.current(storage, campaign.id).state == "gathering"


def test_ending_is_refused_while_a_beat_is_open(storage, campaign, host, party):
    ana, bo, *_ = party
    table = Table(storage, campaign)
    table.here = {ana.id, bo.id}
    table.submit(ana, "act", "I listen.")
    with pytest.raises(table_session.SessionRefused):
        table_session.end_session(table.services, campaign.id, host)
    with pytest.raises(NotAllowed):
        table_session.end_session(table.services, campaign.id, ana)


def test_the_dm_s_recap_ends_the_session(storage, campaign, host):
    """The DM's own `end_session`, in any beat, sets the table gathering, its choices and hands cleared."""
    recap = "They rested."
    script = [
        [
            ToolCall("t1", "end_session", {"recap": recap}),
            ToolResult("t1", True, {"session": 1, "title": "The Crypt", "recap_md": recap}),
        ]
    ]
    table = Table(storage, campaign, script)
    storage.table_sessions.put(
        TableSession(campaign.id, "playing", absent={"chr_1": "out"}, hands={host.id: {"at": "x", "point": None}})
    )

    async def scenario():
        table.submit(host, "act", "We rest for the night.")
        await table.answered()

    asyncio.run(scenario())
    state = table_session.current(storage, campaign.id)
    assert state.state == "gathering" and state.absent == {} and state.hands == {}
    assert table_events(table)[-1]["table"]["state"] == "gathering"


# ----- raised hands -----


def test_raised_hands(storage, campaign, host, party):
    ana, bo, *_ = party
    watcher = storage.seats.create(campaign.id, "Cy", "en", "observer")
    table = Table(storage, campaign)
    first = table_session.raise_hand(table.services, campaign.id, ana, "  About the map  ")
    at = first.hands[ana.id]["at"]
    assert first.hands[ana.id]["point"] == "About the map"
    asyncio.run(table.clock.advance(5))
    table_session.raise_hand(table.services, campaign.id, watcher, None)
    again = table_session.raise_hand(table.services, campaign.id, ana, "   ")
    assert again.hands[ana.id] == {"at": at, "point": None}, "raising again keeps `at` and replaces the point"
    shown = table_session.table_json(storage, campaign.id)["hands"]
    assert [h["seat_id"] for h in shown] == [ana.id, watcher.id], "oldest first"
    assert shown[0] == {"seat_id": ana.id, "at": at, "point": None}
    with pytest.raises(PlayError):
        table_session.raise_hand(table.services, campaign.id, bo, "x" * 201)
    table_session.raise_hand(table.services, campaign.id, bo, "x" * 200)
    with pytest.raises(NotAllowed):
        table_session.lower_hand(table.services, campaign.id, bo, ana.id)
    table_session.lower_hand(table.services, campaign.id, bo, bo.id)
    table_session.lower_hand(table.services, campaign.id, host, ana.id)
    table_session.lower_hand(table.services, campaign.id, host, ana.id)  # not up: fine
    assert list(table_session.current(storage, campaign.id).hands) == [watcher.id]
    assert len(table_events(table)) == 6, "every change, and only a change, is told"


# ----- away mid-session (DEL-224) -----

CAUTIOUS = "(Nobody is playing Garrek this beat: play a cautious action for them"


def test_a_seat_that_steps_away_is_not_waited_for_and_its_pcs_take_its_part(storage, campaign, host, party):
    """Ana's tab is open, but she stepped away: the beat closes on the host's and Bo's acts, and Garrek is played
    cautiously, the part she chose, though the settings hold back."""
    ana, bo, garrek, *_ = party
    table = Table(storage, campaign)
    table.here = {host.id, ana.id, bo.id}

    async def scenario():
        table_session.step_away(table.services, campaign.id, ana, ana.id, "in_character")
        table.submit(host, "act", "We wait.", characters=[])
        assert table.beat().status == "open", "Bo is still waited for"
        table.submit(bo, "act", "I listen at the door.")
        return await table.answered()

    done = asyncio.run(scenario())
    assert any(line.startswith(CAUTIOUS) for line in table.dm.sent[0].splitlines())
    assert next(s["characters"] for s in done.submissions if s["kind"] == "fallback") == [garrek.id]
    shown = table_session.table_json(storage, campaign.id)["away"]
    assert [(a["seat_id"], a["part"]) for a in shown] == [(ana.id, "in_character")]


def test_stepping_away_closes_a_beat_that_waited_only_for_that_seat(storage, campaign, host, party):
    ana, bo, *_ = party
    table = Table(storage, campaign)
    table.here = {host.id, ana.id, bo.id}

    async def scenario():
        table.submit(host, "act", "We wait.", characters=[])
        table.submit(bo, "pass")
        assert table.beat().status == "open"
        table_session.step_away(table.services, campaign.id, ana, ana.id)
        return await table.answered()

    assert asyncio.run(scenario()).status == "done"
    assert "(Garrek holds back this beat: they do nothing.)" in table.dm.sent[0].splitlines(), "the table's fallback"


def test_who_may_mark_a_seat_away_and_when(storage, campaign, host, party):
    ana, bo, *_ = party
    watcher = storage.seats.create(campaign.id, "Cy", "en", "observer")
    table = Table(storage, campaign)
    with pytest.raises(NotAllowed):
        table_session.step_away(table.services, campaign.id, bo, ana.id)
    with pytest.raises(PlayError):
        table_session.step_away(table.services, campaign.id, ana, ana.id, "asleep")
    with pytest.raises(PlayError):
        table_session.step_away(table.services, campaign.id, host, watcher.id)
    with pytest.raises(PlayError):
        table_session.step_away(table.services, campaign.id, host, "seat_nobody")
    first = table_session.step_away(table.services, campaign.id, host, bo.id, "hold_back")
    asyncio.run(table.clock.advance(5))
    again = table_session.step_away(table.services, campaign.id, bo, bo.id, "out")
    assert again.away[bo.id] == {"at": first.away[bo.id]["at"], "part": "out"}, "keeps when it began"
    with pytest.raises(NotAllowed):
        table_session.come_back(table.services, campaign.id, ana, bo.id)
    table_session.come_back(table.services, campaign.id, host, bo.id)
    table_session.come_back(table.services, campaign.id, host, bo.id)  # not away: fine, nothing told
    assert table_session.current(storage, campaign.id).away == {}
    assert len(table_events(table)) == 3
    gathering(storage, campaign)
    with pytest.raises(table_session.SessionRefused):
        table_session.step_away(table.services, campaign.id, ana, ana.id)


def test_acting_or_passing_brings_a_seat_back(storage, campaign, host, party):
    ana, bo, *_ = party
    table = Table(storage, campaign)
    table.here = {host.id, ana.id, bo.id}
    table_session.step_away(table.services, campaign.id, ana, ana.id)
    table_session.step_away(table.services, campaign.id, bo, bo.id)
    table.submit(ana, "act", "I'm back: I light a torch.")
    table.submit(bo, "pass")
    assert table_session.current(storage, campaign.id).away == {}


def test_the_host_sets_a_pc_s_part_mid_session_over_its_player_s_own(storage, campaign, host, party):
    """Ana stepped away to be played in character, but the host sets Garrek out, and Mira, whose player is here but
    doesn't act, to be played cautiously; then leaves Garrek to Ana's own part again."""
    ana, bo, garrek, mira, _pip = party
    table = Table(storage, campaign)
    table.here = {host.id, ana.id}
    with pytest.raises(NotAllowed):
        table_session.set_part(table.services, campaign.id, bo, garrek.id, "out")
    with pytest.raises(PlayError):
        table_session.set_part(table.services, campaign.id, host, "chr_nobody", "out")
    with pytest.raises(PlayError):
        table_session.set_part(table.services, campaign.id, host, garrek.id, "asleep")
    table_session.step_away(table.services, campaign.id, ana, ana.id, "in_character")
    table_session.set_part(table.services, campaign.id, host, garrek.id, "out")
    table_session.set_part(table.services, campaign.id, host, mira.id, "in_character")

    async def scenario():
        table.submit(host, "act", "We wait.", characters=[])
        return await table.answered()

    asyncio.run(scenario())
    sent = table.dm.sent[0]
    assert "Garrek" not in sent, "the host's choice wins over Ana's own"
    assert "(Nobody is playing Mira this beat" in sent
    state = table_session.set_part(table.services, campaign.id, host, garrek.id, None)
    assert garrek.id not in state.absent and state.absent[mira.id] == "in_character"
    gathering(storage, campaign)
    with pytest.raises(table_session.SessionRefused):
        table_session.set_part(table.services, campaign.id, host, garrek.id, "out")


def test_the_end_of_the_session_clears_who_is_away(storage, campaign, host, party):
    ana, *_ = party
    table = Table(storage, campaign, [[TextDelta("And so the evening ends.")]])
    table_session.step_away(table.services, campaign.id, ana, ana.id, "hold_back")

    async def scenario():
        state, _beat = table_session.end_session(table.services, campaign.id, host)
        assert state.away == {}
        await table.answered()

    asyncio.run(scenario())
