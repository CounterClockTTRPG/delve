"""Table voice and fixes Task E3: `say` gives a PC's line when the PC is the DM's to play this beat.

A PC is handed to the DM when the beat's submissions hand it over: an act names it, by its exact name ("you can decide
what Garrek says"), and is for it (it covers it, or comes from the seat that plays it, or from the host for a PC nobody
claimed), or an `in_character` fallback covers it. A PC its player acted for without naming it, one a hold-back
fallback covers, or one outside a beat speaks for itself: refused, with a hint. Solo play's PCs, which nobody claims,
are no exception. The table makes the `say` entry by the same rule."""

import asyncio
import json
from dataclasses import replace

import pytest

from delve.dm.fake import FakeDM
from delve.dm.provider import ToolCall, ToolResult
from delve.dm.tools.say import handed_to_dm, said_line
from delve.play import seats
from delve.play.table import run_beat, set_play_settings, wait_beat
from tests.dm.tools.test_say import services_for


@pytest.fixture
def table(storage, campaign, party):
    """Ana plays Garrek; Pippa is nobody's (the host plays her)."""
    garrek, pippa, _ = (c["id"] for c in party)
    ana = storage.seats.create(campaign.id, "Ana", "en", "player")
    seats.claim(storage, garrek, ana)
    return {"garrek": garrek, "pippa": pippa, "Ana": ana, "Host": seats.owner_seat(storage, campaign.id)}


def act(seat, text, characters):
    return {
        "seat_id": seat.id,
        "kind": "act",
        "characters": characters,
        "text": text,
        "original": text,
        "language": "en",
        "at": "",
    }


def beat_with(storage, campaign, *submissions):
    return storage.beats.open(campaign.id, list(submissions), status="running")


def narrate(storage, host, campaign, submission, npc: str, text: str) -> None:
    """One beat opened by `submission`, in which the fake DM's `say` of `npc` answers the line, as the tool would for
    a handed PC: the table decides by the beat whether it makes a `say` entry."""
    speaker = next(c for c in storage.characters.list(campaign.id) if c.name == npc)
    result = {"said": said_line(speaker, text)}
    dm = FakeDM([[ToolCall("s1", "say", {"npc": npc, "text": text}), ToolResult("s1", True, json.dumps(result))]])

    services = services_for(storage, host, dm)

    async def beat():
        await run_beat(services, campaign.id, submission)
        await wait_beat(services, campaign.id)

    asyncio.run(beat())


def says(storage, campaign) -> list[dict]:
    return [e.payload for e in storage.story.list(campaign.id) if e.kind == "say"]


# ----- the rule -----


def test_a_pc_nobody_claimed_is_handed_by_the_hosts_act(storage, campaign, table):
    pippa = storage.characters.get(table["pippa"])
    assert not handed_to_dm(storage, campaign.id, "no-such-beat", pippa), "solo play's PCs speak for themselves"
    beat = beat_with(storage, campaign, act(table["Host"], "You can decide for Pippa.", []))
    assert handed_to_dm(storage, campaign.id, beat.id, pippa), "the host plays her, whatever the act covers"
    storage.beats.save(replace(beat, status="done"))
    beat = beat_with(storage, campaign, act(table["Ana"], "Pippa can decide for herself, DM.", [table["garrek"]]))
    assert not handed_to_dm(storage, campaign.id, beat.id, pippa), "a player doesn't hand over the host's PC"


def test_a_claimed_pc_outside_a_beat_is_not(storage, campaign, table):
    garrek = storage.characters.get(table["garrek"])
    assert not handed_to_dm(storage, campaign.id, "beat-1", garrek)


def test_an_act_that_names_it_hands_it_over(storage, campaign, table):
    garrek = storage.characters.get(table["garrek"])
    beat = beat_with(storage, campaign, act(table["Ana"], "You can decide what Garrek says.", [table["garrek"]]))
    assert handed_to_dm(storage, campaign.id, beat.id, garrek)
    assert handed_to_dm(storage, campaign.id, f"{beat.id}/cmb_1", garrek), "a fight's key is its beat's"


def test_an_act_that_doesnt_name_it_keeps_it(storage, campaign, table):
    garrek = storage.characters.get(table["garrek"])
    for text in ("We go north.", "Garreks are fine.", "garrek? no: Garrekson."):
        beat = beat_with(storage, campaign, act(table["Ana"], text, [table["garrek"]]))
        assert not handed_to_dm(storage, campaign.id, beat.id, garrek), text
        storage.beats.save(replace(beat, status="done"))


def test_an_act_for_other_characters_doesnt_hand_it_over(storage, campaign, table):
    garrek = storage.characters.get(table["garrek"])
    beat = beat_with(storage, campaign, act(table["Host"], "Garrek can wait; I go on.", [table["pippa"]]))
    assert not handed_to_dm(storage, campaign.id, beat.id, garrek)


def test_another_campaigns_beat_hands_nothing(storage, campaign, table):
    other = storage.campaigns.create(
        "Wednesday", campaign.module_id, campaign.revision, ruleset="osric", setting="greyhawk"
    )
    beat = storage.beats.open(other.id, [act(table["Ana"], "Garrek, you decide.", [table["garrek"]])])
    assert not handed_to_dm(storage, campaign.id, beat.id, storage.characters.get(table["garrek"]))


def test_the_fallback_hands_it_over_only_in_character(storage, campaign, table):
    garrek = storage.characters.get(table["garrek"])
    fallback = {
        "seat_id": table["Ana"].id,
        "kind": "fallback",
        "characters": [table["garrek"]],
        "text": "(…)",
        "original": "",
        "language": "en",
        "at": "",
    }
    beat = beat_with(storage, campaign, fallback)
    assert not handed_to_dm(storage, campaign.id, beat.id, garrek), "hold back: Garrek does nothing"
    set_play_settings(storage, campaign.id, {"fallback": "in_character"})
    assert handed_to_dm(storage, campaign.id, beat.id, garrek)


def test_an_npc_is_never_handed(storage, campaign, party):
    tira = storage.characters.get(party[2]["id"])
    assert not handed_to_dm(storage, campaign.id, "beat-1", tira)


# ----- the tool and the story -----


def test_say_for_a_handed_pc(storage, campaign, table, call):
    beat = beat_with(storage, campaign, act(table["Ana"], "DM, you decide what Garrek says.", [table["garrek"]]))
    said = call("say", beat=beat.id, npc="Garrek", text="Stand aside.")
    assert said["said"]["speaker"]["id"] == table["garrek"] and said["said"]["text"] == "Stand aside."


def test_say_for_the_hosts_pc(storage, campaign, table, call):
    assert "player character" in call("say", npc="Pippa", text="Shh.")["error"], "outside a beat"
    beat = beat_with(storage, campaign, act(table["Host"], "Pippa says what you like.", [table["pippa"]]))
    assert call("say", beat=beat.id, npc="Pippa", text="Shh.")["said"]["speaker"]["id"] == table["pippa"]


def test_say_for_a_pc_its_player_plays_is_refused(storage, campaign, table, call):
    beat = beat_with(storage, campaign, act(table["Ana"], "I draw my sword.", [table["garrek"]]))
    refused = call("say", beat=beat.id, npc="Garrek", text="Aye.")
    assert "player character" in refused["error"] and "names" in refused["hint"]
    assert "error" in call("say", npc="Garrek", text="Aye."), "outside a beat"


def test_the_story_gets_a_handed_pcs_line(storage, host, campaign, table):
    narrate(
        storage,
        host,
        campaign,
        act(table["Ana"], "DM, you decide what Garrek says.", [table["garrek"]]),
        "Garrek",
        "Stand aside.",
    )
    assert [(s["speaker"]["name"], s["text"]) for s in says(storage, campaign)] == [("Garrek", "Stand aside.")]


def test_the_story_gets_no_line_of_a_pc_its_player_plays(storage, host, campaign, table):
    narrate(storage, host, campaign, act(table["Ana"], "I draw my sword.", [table["garrek"]]), "Garrek", "Aye.")
    assert says(storage, campaign) == []
