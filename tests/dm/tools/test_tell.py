"""Narration for some characters (plan 4 Task 5; spec §7.2, §7.4): `tell` tells some characters what the others don't
hear. The story gets a `dm_text` entry for those characters after the tool's row, the way `show_image` makes its
`image` entry, and only the seats that play them see either. A planted `SECRET-XYZZY` in a tell never reaches another
seat (Review Focus 1)."""

import asyncio
import json

import pytest

from delve.dm.fake import FakeDM
from delve.dm.provider import TextDelta, ToolCall, ToolResult
from delve.dm.tools import player_view
from delve.domain.settings import BackendChoice
from delve.play import seats
from delve.play.table import AppServices, run_beat, story, wait_beat
from tests.dm.tools.conftest import SECRET


@pytest.fixture
def table(storage, campaign, party):
    """Ana plays Garrek, Bo plays Pippa; Cy observes. The owner's seat hosts."""
    garrek, pippa, tira = (c["id"] for c in party)
    people = {"Host": seats.owner_seat(storage, campaign.id)}
    for name, role in (("Ana", "player"), ("Bo", "player"), ("Cy", "observer")):
        people[name] = storage.seats.create(campaign.id, name, "en", role)
    seats.claim(storage, garrek, people["Ana"])
    seats.claim(storage, pippa, people["Bo"])
    return {"garrek": garrek, "pippa": pippa, "tira": tira, **people}


def play(storage, host, campaign, *events) -> None:
    """Play one beat in which the fake DM sends `events`, each `tell` answered by the real tool host."""
    script = []
    for event in events:
        script.append(event)
        if isinstance(event, ToolCall):
            result = host.call(campaign.id, "beat-1", event.name, event.args)
            script.append(ToolResult(event.id, "error" not in result, json.dumps(result)))
    dm = FakeDM([script])
    services = AppServices(
        storage=storage,
        catalogs=host.catalogs,
        spec_lookup=host.spec,
        dm=lambda campaign_id: (dm, BackendChoice("fake")),
        side=lambda campaign_id: (dm, BackendChoice("fake")),
    )
    owner = seats.owner_seat(storage, campaign.id).id
    act = {"seat_id": owner, "kind": "act", "characters": [], "text": "On.", "original": "On.", "language": "en", "at": ""}

    async def beat():
        await run_beat(services, campaign.id, act)
        await wait_beat(services, campaign.id)

    asyncio.run(beat())


def seen(storage, campaign, seat) -> list[tuple[str, dict]]:
    """The DM's entries of the story as `seat` sees it: kind and payload, without the act."""
    entries = story(storage, campaign.id, storage.seats.get(seat.id))["entries"]
    return [(e.kind, e.payload) for e in entries if e.kind != "player_act"]


def test_tell_answers_the_characters_and_the_text(call, host, table):
    told = call("tell", characters=["Garrek", table["pippa"]], text="You hear chanting.")
    assert told == {"told": {"characters": [table["garrek"], table["pippa"]], "text": "You hear chanting."}}
    # The one output past the allow-list besides show_image's image.
    assert player_view(host.spec("tell"), {}, told) == told
    spec = host.spec("tell")
    assert spec.player_visible and not spec.mutates


def test_tell_refuses_unknown_characters_and_npcs(call, table):
    unknown = call("tell", characters=["Garek"], text="Psst.")
    assert unknown["error"] == "No character 'Garek'."
    assert {c["name"] for c in unknown["candidates"]} >= {"Garrek", "Pippa"}
    npc = call("tell", characters=["Tira"], text="Psst.")
    assert "error" in npc and "player character" in npc["error"]
    assert "error" in call("tell", characters=[], text="Psst.")
    assert "error" in call("tell", characters=["Garrek"], text="")


def test_a_tell_to_one_character_is_for_its_seat_only(storage, host, campaign, table):
    play(
        storage,
        host,
        campaign,
        TextDelta("The corridor is cold."),
        ToolCall("t1", "tell", {"characters": ["Garrek"], "text": "A voice in your head says your name."}),
    )
    whisper = ("dm_text", {"text": "A voice in your head says your name.", "told_to": [table["garrek"]]})
    ana = seen(storage, campaign, table["Ana"])
    # The tool row is the host's alone (walkthrough fixes Task 5); here the host doesn't play Garrek.
    assert ana == [("dm_text", {"text": "The corridor is cold."}), whisper]
    # The host sees as their own seat, and Ana has claimed Garrek.
    for name in ("Bo", "Cy", "Host"):
        assert seen(storage, campaign, table[name]) == [("dm_text", {"text": "The corridor is cold."})], name


def test_a_split_party_gets_one_entry_per_group(storage, host, campaign, table):
    play(
        storage,
        host,
        campaign,
        ToolCall("t1", "tell", {"characters": ["Garrek"], "text": "The vestry: candles gutter."}),
        ToolCall("t2", "tell", {"characters": ["Pippa"], "text": "The throne room: a cold draught."}),
        TextDelta("Far off, a bell tolls."),
    )
    entries = storage.story.list(campaign.id)
    addressed = [e.audience for e in entries if e.kind == "dm_text" and e.audience is not None]
    assert addressed == [{"seats": [table["Ana"].id]}, {"seats": [table["Bo"].id]}]
    assert [p["text"] for k, p in seen(storage, campaign, table["Ana"]) if k == "dm_text"] == [
        "The vestry: candles gutter.",
        "Far off, a bell tolls.",
    ]
    assert [p["text"] for k, p in seen(storage, campaign, table["Bo"]) if k == "dm_text"] == [
        "The throne room: a cold draught.",
        "Far off, a bell tolls.",
    ]
    assert seen(storage, campaign, table["Cy"]) == [("dm_text", {"text": "Far off, a bell tolls."})]


def test_a_planted_secret_in_a_tell_reaches_only_its_seat(storage, host, campaign, table):
    """Review Focus 1: the secret told to Garrek reaches Ana, and nobody else at the table: not in a `dm_text`, and
    not in the tool row either, which would tell the others that something was said."""
    play(storage, host, campaign, ToolCall("t1", "tell", {"characters": [table["garrek"]], "text": f"{SECRET} you."}))
    assert SECRET in json.dumps(seen(storage, campaign, table["Ana"]))
    for name in ("Bo", "Cy", "Host"):
        assert seen(storage, campaign, table[name]) == [], name


def test_a_failed_or_forged_tell_makes_no_entry(storage, host, campaign, table):
    """A refused tell is the DM's business: no row, no entry. A result the DM's provider forged (an NPC, an id from
    elsewhere) addresses only the campaign's PCs it names, and none at all leaves no entry."""
    forged = {"told": {"characters": [table["tira"], "chr_000000000000"], "text": SECRET}}
    dm = FakeDM(
        [
            [
                ToolCall("t1", "tell", {"characters": ["Nobody"], "text": SECRET}),
                ToolResult("t1", False, json.dumps({"error": "No character 'Nobody'."})),
                ToolCall("t2", "tell", {"characters": ["Tira"], "text": SECRET}),
                ToolResult("t2", True, json.dumps(forged)),
            ]
        ]
    )
    services = AppServices(
        storage=storage,
        catalogs=host.catalogs,
        spec_lookup=host.spec,
        dm=lambda campaign_id: (dm, BackendChoice("fake")),
        side=lambda campaign_id: (dm, BackendChoice("fake")),
    )
    act = {"seat_id": table["Host"].id, "kind": "act", "characters": [], "text": "On.", "original": "On.", "language": "en", "at": ""}

    async def beat():
        await run_beat(services, campaign.id, act)
        await wait_beat(services, campaign.id)

    asyncio.run(beat())
    every = storage.story.list(campaign.id)
    assert [e.kind for e in every if e.kind != "player_act"] == ["tool"]
    assert every[-1].audience == {"seats": []}  # no seat plays an NPC or another campaign's character
    for name in ("Ana", "Bo", "Cy", "Host"):
        assert SECRET not in json.dumps(seen(storage, campaign, table[name])), name
