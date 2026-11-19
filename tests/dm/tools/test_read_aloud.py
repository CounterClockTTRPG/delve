"""`read_aloud` (DEL-357): a keyed room's read-aloud text goes to the story word for word, its quotes of their own as
the speaker's `say` lines, in the passage's order. The DM of campaign sword (beat 34, room 1B) gave a talking door's
three quotes with `say` and none of the rest: the door, the runes and the song with the riddle's clues never reached
the players. The DM no longer copies the passage itself."""

import json

import pytest

from delve.dm.provider import TextDelta, ToolCall
from delve.dm.tools import player_view
from delve.dm.tools.read_aloud import Part, passage
from delve.modules.dscn import Bundle
from delve.modules.importer import import_bundle
from delve.play import seats
from tests.dm.tools.conftest import GARREK, SECRET
from tests.dm.tools.test_say import play, seen
from tests.fixtures import SAMPLES

DOOR = SAMPLES / "scenarios" / "the-singing-door"
CRYPT = SAMPLES / "scenarios" / "crypt-of-saint-vellis"


def said(text):
    return Part(text, spoken=True)


def told(text):
    return Part(text)


# ----- splitting a passage -----


def test_a_quote_of_its_own_is_spoken_and_the_rest_is_told_in_order():
    text = 'The door glows.\n\n"Who goes there?"\n\nIt hums. "Answer me." A light flickers.'
    assert passage(text) == [
        told("The door glows."),
        said("Who goes there?"),
        told("It hums."),
        said("Answer me."),
        told("A light flickers."),
    ]


def test_curly_straight_and_mixed_quote_marks():
    assert passage("“Halt.” The guard waits.") == [said("Halt."), told("The guard waits.")]
    assert passage('“Halt." The guard waits.') == [said("Halt."), told("The guard waits.")]
    assert passage('The guard waits. "Halt!"') == [told("The guard waits."), said("Halt!")]


def test_a_quote_inside_a_narration_sentence_stays_told():
    """Most of the modules' quotes carry an attribution ("Halt!" cries the guard), follow a lead-in (a sign reads,
    "EXIT."), or are a word in quotes (a giant "X"): cut out of their sentence, the rest would read as a fragment, or
    a sign would speak. The sentence stays whole in the narration."""
    for text in (
        '"Halt!" cries the guard.',
        "“Well met,” he says softly.",
        'A sign on the door reads, "EMPLOYEES ONLY."',
        "Gilthanas speaks: “Qualinost is guarded.”",
        "A giant “X” is carved into the floor.",
        "A sheet of 6” thick iron rests against the wall.",
        'The plaque bears the name "Warin" and a date.',
        "“*Don’t Disturb!*” sign on the south door.",
    ):
        assert passage(text) == [told(text)], text


def test_an_attributed_quote_stays_told_and_the_next_quote_of_its_own_is_spoken():
    text = '"Visitors again," says the voice. "The last ones\ndid not leave." A laugh rolls out.'
    assert passage(text) == [
        told('"Visitors again," says the voice.'),
        said("The last ones did not leave."),
        told("A laugh rolls out."),
    ]
    assert passage('"Tell me," says the voice, "what held the wall up?"') == [
        told('"Tell me," says the voice, "what held the wall up?"')
    ]


def test_verse_and_its_line_breaks_are_told_as_written():
    verse = "*Two brothers raised a wall,*\\\n*And each one swore it would not fall.*"
    text = f"The door sings:\n\n{verse}\n\n“What held it up?”"
    assert passage(text) == [told(f"The door sings:\n\n{verse}"), said("What held it up?")]


def test_a_quote_in_italics_keeps_them():
    assert passage("*“Turn back.”*\n\nThe wind drops.") == [said("*Turn back.*"), told("The wind drops.")]


def test_a_quote_inside_an_italic_run_is_not_cut_out_of_it():
    text = "*The voice whispers. “Turn back.” Then silence.*"
    assert passage(text) == [told(text)]


def test_a_speech_over_two_paragraphs_is_spoken_whole():
    """Prose leaves the quote of a paragraph open when the speech goes on in the next, which opens with a quote."""
    text = "“We came at dusk.\n\n“We left at dawn.”\n\nShe falls silent."
    assert passage(text) == [said("We came at dusk."), said("We left at dawn."), told("She falls silent.")]


def test_an_unclosed_quote_is_told():
    text = "“We came at dusk.\n\nShe falls silent."
    assert passage(text) == [told(text)]


def test_every_word_of_the_passage_is_in_its_parts():
    text = (DOOR / "text" / "keyed" / "tomb.md").read_text()
    body = text.split("{#t1}\n\n", 1)[1].split("\n\nThe answer", 1)[0]
    raw = "\n".join(line.removeprefix(">").removeprefix(" ") for line in body.splitlines())
    parts = passage(raw)
    assert [p.spoken for p in parts] == [False, True, False, True, False]

    def words(s):
        return [w for w in s.replace('"', " ").split() if w]

    assert words(" ".join(p.text for p in parts)) == words(raw)


# ----- the tool -----


@pytest.fixture
def door(storage):
    """The Singing Door, its DM text planted; a campaign on it."""
    bundle = Bundle.load(DOOR)
    key = bundle.text_entry("tomb-key")["file"]
    bundle.files[key] = bundle.read(key).replace(b"The answer is", f"{SECRET} The answer is".encode())
    module = import_bundle(storage, bundle.to_zip()).module
    revision = storage.revisions.snapshot(module.id)
    return storage.campaigns.create("Door", module.id, revision.number, ruleset="osric", setting="greyhawk")


@pytest.fixture
def ask(host, door):
    def run(tool, /, beat="beat-1", **args):
        return host.call(door.id, beat, tool, args)

    return run


@pytest.fixture
def voice(ask):
    assert "error" not in ask("create_character", name="Garrek", sheet=GARREK)
    return ask("create_character", name="The Voice", kind="npc", sheet={"notes_md": f"{SECRET}: Orsevar's ghost."})


def test_read_aloud_gives_the_passage_its_quotes_as_the_speakers_lines(ask, host, voice):
    result = ask("read_aloud", room="T1", speaker="The Voice")
    parts = result["read_aloud"]
    assert (result["key"], result["title"]) == ("T1", "The Singing Door")
    assert [("said" in p) for p in parts] == [False, True, False, True, False]
    assert parts[0]["text"].startswith("The door at the end of the passage")
    assert parts[1]["said"]["text"] == "The last ones did not leave."
    assert parts[1]["said"]["speaker"]["id"] == voice["id"] and parts[1]["said"]["mood"] == "neutral"
    assert "*Two brothers raised a single wall,*\\\n*And each one swore" in parts[4]["text"]
    assert parts[4]["text"].endswith('"Tell me," says the voice, "what held the wall up?"')
    assert SECRET not in json.dumps(result), "the DM text and the NPC's notes stay out"
    spec = host.spec("read_aloud")
    assert spec.player_visible and spec.areas == ()
    assert player_view(spec, {}, result) == {"read_aloud": parts}


def test_without_a_speaker_the_passage_is_all_told(ask, voice):
    [part] = ask("read_aloud", room="T1")["read_aloud"]
    assert part["text"].startswith("The door at the end") and '"Well. Sit, and answer me' in part["text"]


def test_a_list_of_speakers_speaks_the_lines_in_order(ask, voice):
    other = ask("create_character", name="Echo", kind="npc", sheet={})
    parts = ask("read_aloud", room="T1", speaker=["The Voice", "Echo"])["read_aloud"]
    assert [p["said"]["speaker"]["name"] for p in parts if "said" in p] == ["The Voice", "Echo"]
    assert other["id"]
    refused = ask("read_aloud", room="T1", beat="beat-2", speaker=["The Voice", "Echo", "The Voice"])
    assert "2 quoted lines" in refused["error"]
    assert "The last ones did not leave." in refused["hint"] and "Sit, and answer me" in refused["hint"]


def test_the_same_passage_again_in_the_beat_is_not_told_twice(ask, voice):
    assert "read_aloud" in ask("read_aloud", room="T1", speaker="The Voice")
    again = ask("read_aloud", room="T1", speaker="The Voice")
    assert "error" not in again and "read_aloud" not in again and "already" in again["told"]
    assert "read_aloud" in ask("read_aloud", room="T1", beat="beat-2", speaker="The Voice"), "a later beat may"


def test_a_key_without_read_aloud_or_a_wrong_speaker_is_refused(host, storage, ask, voice):
    module = import_bundle(storage, Bundle.load(CRYPT).to_zip()).module
    crypt = storage.campaigns.create(
        "Vellis", module.id, storage.revisions.snapshot(module.id).number, ruleset="osric", setting="greyhawk"
    )
    vestry = host.call(crypt.id, "beat-1", "read_aloud", {"room": "C3"})
    assert "no read-aloud" in vestry["error"] and vestry["hint"]
    assert "error" in ask("read_aloud", room="Kitchen")
    pc = ask("read_aloud", room="T1", speaker="Garrek")
    assert "player character" in pc["error"]
    unknown = ask("read_aloud", room="T1", speaker="Nobody")
    assert "error" in unknown and [c["name"] for c in unknown["candidates"]] == ["The Voice"]
    assert "read_aloud" in ask("read_aloud", room="T1", speaker="The Voice"), "a refusal told nothing"


# ----- the story -----


def test_the_passage_lands_after_the_dms_words_and_before_its_next(storage, host, door, voice):
    play(
        storage,
        host,
        door,
        TextDelta("You reach the end of the passage."),
        ToolCall("r1", "read_aloud", {"room": "T1", "speaker": "The Voice"}),
        TextDelta("The door waits."),
    )
    player = storage.seats.create(door.id, "Ana", "en", "player")
    entries = [(k, p) for k, p in seen(storage, door, player) if k in ("dm_text", "say")]
    assert [k for k, _ in entries] == ["dm_text", "dm_text", "say", "dm_text", "say", "dm_text", "dm_text"]
    assert entries[0][1] == {"text": "You reach the end of the passage."}
    assert entries[1][1]["text"].startswith("The door at the end of the passage")
    assert entries[2][1]["text"] == "The last ones did not leave." and entries[2][1]["speaker"]["name"] == "The Voice"
    assert entries[6][1] == {"text": "The door waits."}
    host_seat = seats.owner_seat(storage, door.id)
    assert SECRET not in json.dumps(seen(storage, door, host_seat))


def test_a_read_aloud_in_a_batch_lands_as_on_its_own(storage, host, door, voice):
    steps = [{"tool": "read_aloud", "args": {"room": "T1", "speaker": "The Voice"}}]
    play(storage, host, door, ToolCall("b1", "batch", {"steps": steps}))
    kinds = [e.kind for e in storage.story.list(door.id) if e.kind in ("dm_text", "say")]
    assert kinds == ["dm_text", "say", "dm_text", "say", "dm_text"]
