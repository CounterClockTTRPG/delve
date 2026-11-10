"""Retry a failed beat (table voice and fixes Task D1; design §D): a beat the DM didn't finish for a reason that may
pass (the usage limit, a crash, a restart) is played again with the same acts, once, by the host or a seat that acted
in it, while it is the campaign's latest beat. The first attempt's effects stand and are never applied twice: its
rolls keep their keys, and the DM is told which of its tool calls were applied."""

import asyncio
import json
from dataclasses import replace

import pytest

from delve.dice import ScriptedRng
from delve.dm.claude_cli import account
from delve.dm.claude_cli.stream import parse_line
from delve.dm.fake import FakeDM
from delve.dm.provider import DMError, TextDelta, ToolCall, ToolResult, TurnEnd
from delve.dm.tools import ToolHost
from delve.play import seats
from delve.play.seats import NotAllowed
from delve.play.table import (
    RETRY_NOTE,
    BeatRunning,
    NotRetryable,
    beat_changed,
    open_beat,
    retry_beat,
    retry_state,
    run_beat,
    running_beat,
    story,
    wait_beat,
)
from tests.fixtures.play_reference import PlayReference
from tests.fixtures.rulesets import over
from tests.play.test_runner import services_for

LIMIT = DMError("The DM is paused: Claude's usage limit is reached.", True, resets_at="2026-10-25T18:00:00Z")


@pytest.fixture
def act(owner_seat):
    def make(text: str, seat=None) -> dict:
        return {
            "seat_id": (seat or owner_seat).id,
            "kind": "act",
            "characters": [],
            "text": text,
            "original": text,
            "language": "en",
            "at": "",
        }

    return make


def play(services, campaign_id, submission):
    async def scenario():
        await run_beat(services, campaign_id, submission)
        return await wait_beat(services, campaign_id)

    return asyncio.run(scenario())


def retried(services, campaign_id, beat_id, seat):
    async def scenario():
        retry_beat(services, campaign_id, beat_id, seat)
        return await wait_beat(services, campaign_id)

    return asyncio.run(scenario())


def errors(storage, campaign_id):
    entries = story(storage, campaign_id, seats.owner_seat(storage, campaign_id))["entries"]
    return [e.payload for e in entries if e.kind == "dm_error"]


def test_provider_failure_is_retryable(storage, campaign, owner_seat, act):
    services = services_for(storage, FakeDM([[TextDelta("The door "), LIMIT, TurnEnd("error")]]))
    beat = play(services, campaign.id, act("We open the door."))
    assert beat.status == "failed"
    [error] = errors(storage, campaign.id)
    assert error["retryable"] is True and error["resets_at"] == "2026-10-25T18:00:00Z"
    assert error["message"].startswith("The DM didn't answer: The DM is paused")
    assert retry_state(services, campaign.id, owner_seat) == {
        "beat_id": beat.id,
        "may_retry": True,
        "resets_at": "2026-10-25T18:00:00Z",
    }
    # An error that won't pass by trying again (the script ran out: `retryable` false) offers no Retry.
    services = services_for(storage, FakeDM([]))
    play(services, campaign.id, act("And again."))
    assert errors(storage, campaign.id)[-1]["retryable"] is False
    assert retry_state(services, campaign.id, owner_seat)["may_retry"] is False


def test_an_old_error_is_not_retryable(storage, campaign, owner_seat, act):
    """An entry stored before retry existed has no `retryable`: it isn't retryable."""
    services = services_for(storage, FakeDM([]))
    beat = open_beat(storage, campaign.id, act("We wait."))
    storage.story.append(campaign.id, beat.id, "dm_error", {"message": "The DM didn't answer: timeout"})
    from delve.play.table import close_beat

    close_beat(storage, beat.id, "failed")
    assert retry_state(services, campaign.id, owner_seat)["may_retry"] is False
    with pytest.raises(NotRetryable):
        retry_beat(services, campaign.id, beat.id, owner_seat)


def test_restart_leaves_it_retryable(storage, campaign, owner_seat, act):
    stale = open_beat(storage, campaign.id, act("We were saying…"))  # running, and nobody answers it: a restart
    services = services_for(storage, FakeDM([[TextDelta("Where were we? You were saying.")]]))
    assert running_beat(services, campaign.id) is None
    assert storage.beats.get(stale.id).status == "failed"
    [error] = errors(storage, campaign.id)
    assert error["retryable"] is True and error["resets_at"] is None
    assert retry_state(services, campaign.id, owner_seat)["may_retry"] is True
    assert retried(services, campaign.id, stale.id, owner_seat).status == "done"


def test_retry_plays_the_same_acts(storage, campaign, owner_seat, act):
    dm = FakeDM([[LIMIT, TurnEnd("error")], [TextDelta("The door opens.")]])
    events: list = []
    services = services_for(storage, dm, events)
    beat = play(services, campaign.id, act("We open the door."))
    events.clear()
    done = retried(services, campaign.id, beat.id, owner_seat)
    assert (done.id, done.number, done.status) == (beat.id, 1, "done") and done.closed_at
    assert done.submissions == beat.submissions
    assert dm.sent[1].endswith(dm.sent[0]), "the same acts, after the note"
    assert storage.beats.latest(campaign.id).id == beat.id, "no new beat"
    # The story keeps the first attempt and its error, marked retried; there is no second player_act.
    entries = story(storage, campaign.id, owner_seat)["entries"]
    assert [e.kind for e in entries] == ["player_act", "dm_error", "dm_text"]
    assert entries[1].payload["retried"] is True
    assert [kind for kind, _ in events if kind == "beat"] == ["beat", "beat"]
    assert ("story", {"campaign_id": campaign.id, "entry": json.loads(json.dumps(_as_json(entries[1])))}) in events
    assert retry_state(services, campaign.id, owner_seat)["may_retry"] is False
    # The DM's time on the retried beat counts from the retry, not from the beat's opening hours ago.
    events.clear()
    beat_changed(services, replace(done, status="running", closed_at=None, opened_at="2026-10-25T08:00:00+00:00"))
    assert events[0][1]["beat"]["elapsed_s"] < 5


def _as_json(entry):
    from delve.play.table import entry_json

    return entry_json(entry)


def test_retry_prompt_lists_applied_tools(storage, campaign, owner_seat, act):
    first = [
        ToolCall("t1", "apply_damage", {"target": "Garrek", "amount": 4}),
        ToolResult("t1", True, {"hp": 6}),
        ToolCall("t2", "apply_damage", {"target": "Pippa", "amount": 99}),
        ToolResult("t2", True, {"error": "Unknown character 'Pippa'."}),  # refused: nothing applied
        ToolCall("t3", "room", {}),  # reads nothing into the world
        ToolResult("t3", True, {"room": "hall"}),
        ToolCall("t4", "award_xp", {"amount": 50}),  # no answer came back
        DMError("the DM provider failed: crash", True),
        TurnEnd("error"),
    ]
    dm = FakeDM([first, [TextDelta("Garrek staggers on.")]])
    services = services_for(storage, dm)
    beat = play(services, campaign.id, act("I swing."))
    retried(services, campaign.id, beat.id, owner_seat)
    sent = dm.sent[1]
    note, acts = sent.split("\n\n", 1)
    assert note.startswith(RETRY_NOTE.split("{", 1)[0].rstrip())
    assert 'apply_damage {"amount": 4, "target": "Garrek"}\n  → {"hp": 6}' in note, "with what it did (DEL-336)"
    assert "narrate what those calls did" in note
    assert "Pippa" not in note and "room" not in note
    assert 'award_xp {"amount": 50}' in note and "no answer" in note
    assert acts == dm.sent[0]


def test_retry_note_says_when_nothing_was_applied(storage, campaign, owner_seat, act):
    dm = FakeDM([[LIMIT, TurnEnd("error")], [TextDelta("On.")]])
    services = services_for(storage, dm)
    beat = play(services, campaign.id, act("I wait."))
    retried(services, campaign.id, beat.id, owner_seat)
    assert "No tool call of an earlier attempt changed anything." in dm.sent[1]


class RollingDM(FakeDM):
    """A DM whose replies really roll through the tool host, with the dice it is given per reply, then follow the
    script."""

    def __init__(self, storage, campaign_id, script, dice):
        super().__init__(script)
        self.host = ToolHost(storage, lambda: ScriptedRng(self.dice.pop(0)), catalogs=over(PlayReference()))
        self.storage, self.campaign_id, self.dice, self.rolled = storage, campaign_id, dice, []

    async def open(self, spec):
        conversation = await super().open(spec)
        send = conversation.send

        async def rolling(text):
            beat = self.storage.beats.current(self.campaign_id)
            args = {"notation": "1d20", "purpose": "the lever"}
            result = self.host.call(self.campaign_id, beat.id, "roll", args)
            self.rolled.append(result["total"])
            yield ToolCall("r1", "roll", args)
            yield ToolResult("r1", True, result)
            async for event in send(text):
                yield event

        conversation.send = rolling
        return conversation


def test_retry_keeps_the_dice(storage, campaign, owner_seat, act):
    dm = RollingDM(storage, campaign.id, [[LIMIT, TurnEnd("error")], [TextDelta("It gives.")]], [[7], [19]])
    services = services_for(storage, dm)
    beat = play(services, campaign.id, act("I pull the lever."))
    retried(services, campaign.id, beat.id, owner_seat)
    assert dm.rolled == [7, 7], "the same roll again, never a re-roll"


def test_only_the_latest_beat(storage, campaign, owner_seat, act):
    dm = FakeDM([[LIMIT, TurnEnd("error")], [LIMIT, TurnEnd("error")]])
    services = services_for(storage, dm)
    older = play(services, campaign.id, act("First."))
    newer = play(services, campaign.id, act("Second."))
    with pytest.raises(NotRetryable):
        retry_beat(services, campaign.id, older.id, owner_seat)
    assert retry_state(services, campaign.id, owner_seat)["beat_id"] == newer.id
    with pytest.raises(KeyError):
        retry_beat(services, campaign.id, "beat_000000000000", owner_seat)


def test_newer_beat_hides_retry(storage, campaign, owner_seat, act):
    dm = FakeDM([[LIMIT, TurnEnd("error")], [TextDelta("Fine.")]])
    services = services_for(storage, dm)
    failed = play(services, campaign.id, act("First."))
    # A beat open for the table's submissions: someone acted again, so the failed beat's Retry is gone.
    opened = storage.beats.open(campaign.id, [act("We act again instead.")], status="open")
    state = retry_state(services, campaign.id, owner_seat)
    assert state == {"beat_id": opened.id, "may_retry": False, "resets_at": None}
    with pytest.raises(BeatRunning):
        retry_beat(services, campaign.id, failed.id, owner_seat)
    # Once the newer beat has been played, the failed one isn't the latest any more.
    from delve.play.table import close_beat

    close_beat(storage, opened.id, "done")
    with pytest.raises(NotRetryable):
        retry_beat(services, campaign.id, failed.id, owner_seat)


def test_retry_twice_is_409(storage, campaign, owner_seat, act):
    dm = FakeDM([[LIMIT, TurnEnd("error")], [TextDelta("On.")], [TextDelta("Again?")]])
    services = services_for(storage, dm)
    beat = play(services, campaign.id, act("Go."))

    async def twice():
        retry_beat(services, campaign.id, beat.id, owner_seat)
        with pytest.raises(BeatRunning):
            retry_beat(services, campaign.id, beat.id, owner_seat)
        return await wait_beat(services, campaign.id)

    assert asyncio.run(twice()).status == "done"
    with pytest.raises(NotRetryable):  # done now: nothing to retry
        retry_beat(services, campaign.id, beat.id, owner_seat)
    assert len(dm.sent) == 2, "one re-run, never two"


def test_other_players_seat_403(storage, campaign, owner_seat, act):
    ana = storage.seats.create(campaign.id, "Ana", "en", "player")
    bo = storage.seats.create(campaign.id, "Bo", "en", "player")
    cohost = storage.seats.create(campaign.id, "Cy", "en", "cohost")
    observer = storage.seats.create(campaign.id, "Ob", "en", "observer")
    dm = FakeDM([[LIMIT, TurnEnd("error")], [TextDelta("On.")]])
    services = services_for(storage, dm)
    beat = play(services, campaign.id, act("I listen.", ana))
    for seat in (bo, observer):
        assert retry_state(services, campaign.id, seat)["may_retry"] is False
        with pytest.raises(NotAllowed):
            retry_beat(services, campaign.id, beat.id, seat)
    assert all(retry_state(services, campaign.id, s)["may_retry"] for s in (ana, cohost, owner_seat))
    assert retried(services, campaign.id, beat.id, ana).status == "done"


def test_resets_at_from_account_json(tmp_path):
    """The usage limit's end comes from the CLI's last rate-limit event, kept in `account.json`: the reset of the
    window that is full."""
    kept = {
        "at": "2026-10-25T13:00:00Z",
        "status": "rejected",
        "windows": [
            {"name": "five_hour", "utilization": 1.0, "resets_at": "2026-10-25T14:50:00Z"},
            {"name": "seven_day", "utilization": 0.4, "resets_at": "2026-10-30T09:00:00Z"},
        ],
    }
    (tmp_path / account.FILE).write_text(json.dumps(kept), "utf-8")
    account.configure(tmp_path)
    try:
        notice = "You've hit your session limit · resets 2:50pm (UTC)"
        line = {"type": "result", "is_error": True, "result": notice, "usage": {}}
        error = next(e for e in parse_line(line) if isinstance(e, DMError))
        assert error.retryable is True and error.resets_at == "2026-10-25T14:50:00Z"
        # Another error doesn't say when a limit ends.
        other = {"type": "result", "is_error": True, "subtype": "error_max_turns", "result": "", "usage": {}}
        assert next(e for e in parse_line(other) if isinstance(e, DMError)).resets_at is None
    finally:
        account.reset()
    # Without a window that is full, nothing is guessed.
    assert account.limit_resets_at() is None
