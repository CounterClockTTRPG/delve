"""NPCs speak through `say` (portraits plan Task 7; design, owner decision 5): every quoted NPC line is its own story
entry, with the speaker, the line's mood and its text, after the tool's row, as `tell` makes its `dm_text`. A `say`
is for everyone, like narration. Its payload is the speaker's id, name and portrait, the mood and the text: nothing of
the NPC's sheet, whose DM notes hold a planted `SECRET-XYZZY` (Review Focus 3)."""

import asyncio
import json
from dataclasses import replace

import pytest

from delve.dm.fake import FakeDM
from delve.dm.provider import TextDelta, ToolCall, ToolResult
from delve.dm.tools import player_view
from delve.dm.tools.say import MOODS
from delve.domain.settings import BackendChoice
from delve.domain.world import TraitsPortrait
from delve.play import seats
from delve.play.table import AppServices, run_beat, story, wait_beat
from tests.dm.tools.conftest import SECRET

TIRA_PORTRAIT = {"kind": "traits", "describe": "a stout innkeeper, grey braids", "seed": "tira-1"}


@pytest.fixture
def table(storage, campaign, party):
    """Ana plays Garrek, Bo plays Pippa; Cy observes. The owner's seat hosts. Tira, the innkeeper, has a portrait and
    a planted story."""
    garrek, pippa, tira = (c["id"] for c in party)
    npc = storage.characters.get(tira)
    storage.characters.save(replace(npc, sheet=replace(npc.sheet, portrait=TraitsPortrait.from_dict(TIRA_PORTRAIT))))
    people = {"Host": seats.owner_seat(storage, campaign.id)}
    for name, role in (("Ana", "player"), ("Bo", "player"), ("Cy", "observer")):
        people[name] = storage.seats.create(campaign.id, name, "en", role)
    seats.claim(storage, garrek, people["Ana"])
    seats.claim(storage, pippa, people["Bo"])
    return {"garrek": garrek, "pippa": pippa, "tira": tira, **people}


def services_for(storage, host, dm) -> AppServices:
    return AppServices(
        storage=storage,
        catalogs=host.catalogs,
        spec_lookup=host.spec,
        dm=lambda campaign_id: (dm, BackendChoice("fake")),
        side=lambda campaign_id: (dm, BackendChoice("fake")),
    )


def run(storage, host, campaign, script) -> None:
    services = services_for(storage, host, FakeDM([script]))
    owner = seats.owner_seat(storage, campaign.id).id
    act = {"seat_id": owner, "kind": "act", "characters": [], "text": "On.", "original": "On.", "language": "en", "at": ""}

    async def beat():
        await run_beat(services, campaign.id, act)
        await wait_beat(services, campaign.id)

    asyncio.run(beat())


def play(storage, host, campaign, *events) -> None:
    """Play one beat in which the fake DM sends `events`, each tool call answered by the real tool host."""
    script = []
    for event in events:
        script.append(event)
        if isinstance(event, ToolCall):
            result = host.call(campaign.id, "beat-1", event.name, event.args)
            script.append(ToolResult(event.id, "error" not in result, json.dumps(result)))
    run(storage, host, campaign, script)


def seen(storage, campaign, seat) -> list[tuple[str, dict]]:
    """The DM's entries of the story as `seat` sees it: kind and payload, without the act."""
    entries = story(storage, campaign.id, storage.seats.get(seat.id))["entries"]
    return [(e.kind, e.payload) for e in entries if e.kind != "player_act"]


# ----- the tool -----


def test_say_answers_the_speaker_the_mood_and_the_line(call, host, table):
    said = call("say", npc="Tira", text="Rooms are two silver a night.", mood="smile")
    assert said == {
        "said": {
            "speaker": {"id": table["tira"], "name": "Tira", "portrait": TIRA_PORTRAIT},
            "mood": "smile",
            "text": "Rooms are two silver a night.",
        }
    }
    assert SECRET not in json.dumps(said)
    assert player_view(host.spec("say"), {}, said) == said
    spec = host.spec("say")
    assert spec.player_visible and not spec.mutates


def test_say_by_id_and_without_a_mood_is_neutral(call, table, party):
    said = call("say", npc=table["tira"], text="Hm.")["said"]
    assert said["mood"] == "neutral" and said["speaker"]["id"] == table["tira"]


def test_the_moods_are_portraitgens_emotes_and_neutral():
    assert MOODS[0] == "neutral" and len(MOODS) == 16 == len(set(MOODS))
    assert {"talk", "blink", "breathe", "sleep", "idle", "lookaround", "yawn"}.isdisjoint(MOODS)


def test_an_unknown_mood_is_neutral(call, table):
    for mood in ("furious", "", "SMILE ", SECRET):
        said = call("say", npc="Tira", text="Out.", mood=mood)["said"]
        assert said["mood"] == ("smile" if mood == "SMILE " else "neutral"), mood


def test_a_say_that_names_nobody_or_the_wrong_one_is_refused_with_a_hint(call, storage, campaign, table):
    """Review Focus 3: an unknown NPC, a PC's id, an NPC of another campaign, an empty line."""
    other = storage.campaigns.create(
        "Wednesday", campaign.module_id, campaign.revision, ruleset="osric", setting="greyhawk"
    )
    stranger = storage.characters.create(other.id, "Morrow", kind="npc")
    for npc, text in (("Tiraa", "Out."), (table["garrek"], "Out."), (stranger.id, "Out."), ("Tira", "   ")):
        refused = call("say", npc=npc, text=text)
        assert "error" in refused and refused.get("hint"), (npc, refused)
    pc = call("say", npc=table["garrek"], text="Out.")
    assert "player character" in pc["error"]
    unknown = call("say", npc="Tiraa", text="Out.")
    assert [c["name"] for c in unknown["candidates"]] == ["Tira"], "the NPCs, never the PCs"
    assert "error" in call("say", npc="Tira", text="")


def test_a_long_line_is_kept_whole(call, table):
    line = "word " * 1000
    assert call("say", npc="Tira", text=line)["said"]["text"] == line


# ----- the story -----


def test_narration_a_line_and_narration_are_three_entries_in_order(storage, host, campaign, table):
    play(
        storage,
        host,
        campaign,
        TextDelta("The innkeeper looks up."),
        ToolCall("s1", "say", {"npc": "Tira", "text": "Rooms are two silver.", "mood": "smile"}),
        TextDelta("She wipes the bar."),
    )
    said = {
        "speaker": {"id": table["tira"], "name": "Tira", "portrait": TIRA_PORTRAIT},
        "mood": "smile",
        "text": "Rooms are two silver.",
    }
    for name in ("Ana", "Bo", "Cy"):
        assert seen(storage, campaign, table[name]) == [
            ("dm_text", {"text": "The innkeeper looks up."}),
            ("say", said),
            ("dm_text", {"text": "She wipes the bar."}),
        ], name
    entry = next(e for e in storage.story.list(campaign.id) if e.kind == "say")
    assert entry.audience is None, "for everyone, like narration"
    assert set(entry.payload) == {"speaker", "mood", "text"} and set(entry.payload["speaker"]) == {
        "id",
        "name",
        "portrait",
    }


def test_a_planted_secret_in_the_npcs_notes_reaches_no_seat(storage, host, campaign, table):
    play(storage, host, campaign, ToolCall("s1", "say", {"npc": "Tira", "text": "Welcome.", "mood": "nod"}))
    assert SECRET in json.dumps(host.call(campaign.id, "beat-1", "get_character", {"ref": "Tira"})), "the plant"
    for name in ("Ana", "Bo", "Cy", "Host"):
        lines = seen(storage, campaign, table[name])
        assert ("say" in [k for k, _ in lines]) and SECRET not in json.dumps(lines), name


def test_a_forged_say_is_rebuilt_from_the_campaigns_npc(storage, host, campaign, table):
    """A result the DM's provider forged: its speaker's name, portrait and extra keys come from the campaign's own
    NPC, and its mood from the vocabulary; a PC, an NPC of another campaign or a refusal makes no entry."""
    other = storage.campaigns.create(
        "Wednesday", campaign.module_id, campaign.revision, ruleset="osric", setting="greyhawk"
    )
    stranger = storage.characters.create(other.id, "Morrow", kind="npc")

    def said(speaker_id, **extra):
        speaker = {"id": speaker_id, "name": SECRET, "portrait": {**TIRA_PORTRAIT, "notes": SECRET}}
        return json.dumps({"said": {"speaker": speaker, "mood": SECRET, "text": "Psst.", **extra}, "dm_only": SECRET})

    run(
        storage,
        host,
        campaign,
        [
            ToolCall("s1", "say", {"npc": "Tira", "text": "Psst."}),
            ToolResult("s1", True, said(table["tira"], notes=SECRET)),
            ToolCall("s2", "say", {"npc": "Garrek", "text": "Psst."}),
            ToolResult("s2", True, said(table["garrek"])),
            ToolCall("s3", "say", {"npc": "Morrow", "text": "Psst."}),
            ToolResult("s3", True, said(stranger.id)),
            ToolCall("s4", "say", {"npc": "Nobody", "text": "Psst."}),
            ToolResult("s4", False, json.dumps({"error": f"No character '{SECRET}'."})),
        ],
    )
    [entry] = [e for e in storage.story.list(campaign.id) if e.kind == "say"]
    assert entry.payload == {
        "speaker": {"id": table["tira"], "name": "Tira", "portrait": TIRA_PORTRAIT},
        "mood": "neutral",
        "text": "Psst.",
    }
    for name in ("Ana", "Bo", "Cy", "Host"):
        assert SECRET not in json.dumps(seen(storage, campaign, table[name])), name


def test_an_npc_without_a_portrait_gets_one_the_first_time_it_speaks(call, storage, campaign, table):
    """DEL-41: an NPC made before NPCs were drawn when made spoke beside its initial. Its first line draws it with
    portraitgen, from the look its sheet gives (`portrait_prompt`), never from its story's secrets; then it keeps it."""
    from delve.domain.characters import Sheet

    look = "a stooped old woman with a lantern and a patched grey shawl"
    sheet = Sheet(race="Human", gender="female", portrait_prompt=look, notes_md=f"{SECRET}: she buried the abbot.")
    mara = storage.characters.create(campaign.id, "Old Mara", kind="npc", sheet=sheet)
    assert mara.sheet.portrait is None
    said = call("say", npc="Old Mara", text="Mind the third step.")["said"]
    assert said["speaker"]["portrait"] == {"kind": "traits", "describe": look, "seed": mara.id}
    assert SECRET not in json.dumps(said)
    assert storage.characters.get(mara.id).sheet.portrait == TraitsPortrait(look, mara.id)
    again = call("say", npc="Old Mara", text="And the fourth.")["said"]
    assert again["speaker"]["portrait"] == said["speaker"]["portrait"], "drawn once"


def test_without_a_look_the_portrait_is_its_race_and_gender(call, storage, campaign, table):
    from delve.domain.characters import Sheet

    storage.characters.create(campaign.id, "Brom", kind="npc", sheet=Sheet(race="Dwarf", gender="male"))
    assert call("say", npc="Brom", text="Hm.")["said"]["speaker"]["portrait"]["describe"] == "a male dwarf"


def test_with_no_portrait_for_npcs_the_initial_stays(call, storage, campaign, table):
    storage.settings.save({"choices": {"image.npc_portrait": {"provider": "none", "model": None, "effort": None}}})
    brom = storage.characters.create(campaign.id, "Brom", kind="npc")
    assert call("say", npc="Brom", text="Hm.")["said"]["speaker"]["portrait"] is None
    assert storage.characters.get(brom.id).sheet.portrait is None
