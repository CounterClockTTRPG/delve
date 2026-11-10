"""Translation (plan 4 Task 7; spec §7.7): a player's words go into English before they join the beat, keeping their
original; the DM's words come out of English for each language at the table, paragraph by paragraph as they stream,
while readers of English get each delta at once. A translation has its entry's audience and goes only to seats of its
language. A failed or slow translation leaves the English, marked, and never holds up the beat (Review Focus 5)."""

import asyncio
import json

import pytest

from delve.dm.fake import FakeDM
from delve.dm.provider import TextDelta, ToolCall, ToolResult
from delve.dm.tools import all_specs
from delve.dm.tools.say import said_line
from delve.domain.settings import BackendChoice
from delve.modules.dscn import Bundle
from delve.modules.importer import import_bundle
from delve.play import beats, seats, translate
from delve.play.ask import ask
from delve.play.clock import FakeClock
from delve.play.context import context_for
from delve.play.sessions import new_session
from delve.play.table import AppServices, current_beat, story, wait_beat
from delve.play.talk import talk
from delve.web.auth import OWNER, seat_principal
from delve.web.events import EventBus, StoredTables, Viewer
from tests.fixtures import SAMPLES
from tests.fixtures.play_reference import PlayReference
from tests.fixtures.rulesets import over

SPECS = {spec.name: spec for spec in all_specs()}
SECRET = "SECRET-XYZZY"
INTO_DUTCH = "Translate the text below from English (en) into Dutch (nl)."
FROM_DUTCH = "Translate the text below from Dutch (nl) into English (en)."
DUTCH = {
    "Ik open de deur.": "I open the door.",
    "Zullen we rusten?": "Shall we rest?",
    "Wat is THAC0?": "What is THAC0?",
}


def the_text(prompt: str) -> str:
    return prompt.split("\nTHE TEXT:\n", 1)[1]


def translator(prompt: str) -> str:
    """The fake side pass: Dutch into English from `DUTCH`, English into "Dutch" as `NL: <text>`; and an answer to
    Ask the DM."""
    if not prompt.startswith("Translate the text below"):
        return "THAC0 is what you need to hit AC 0."
    first, text = prompt.splitlines()[0], the_text(prompt)
    if first == FROM_DUTCH:
        return DUTCH[text]
    assert first == INTO_DUTCH, first
    return f"NL: {text}"


class Table:
    """A table of the host (English), Ana (Dutch, plays Garrek) and Bo (Dutch, plays Mira), all present; everything
    published goes through a real event bus on the storage's tables."""

    def __init__(self, storage, campaign, script=None, handler=translator, dm=None):
        self.storage, self.campaign = storage, campaign
        self.host = seats.owner_seat(storage, campaign.id)
        self.ana = storage.seats.create(campaign.id, "Ana", "nl", "player")
        self.bo = storage.seats.create(campaign.id, "Bo", "nl", "player")
        self.garrek = storage.characters.create(campaign.id, "Garrek")
        self.mira = storage.characters.create(campaign.id, "Mira")
        seats.claim(storage, self.garrek.id, self.ana)
        seats.claim(storage, self.mira.id, self.bo)
        self.dm = dm or FakeDM(script or [[TextDelta("The hall is dark.")]], side_handler=handler)
        self.bus = EventBus(StoredTables(storage))
        self.here = {self.host.id, self.ana.id, self.bo.id}
        self.services = AppServices(
            storage=storage,
            catalogs=over(PlayReference()),
            spec_lookup=SPECS.get,
            dm=lambda campaign_id: (self.dm, BackendChoice("fake")),
            side=lambda campaign_id: (self.dm, BackendChoice("fake", "fake-large")),
            translation=lambda campaign_id: (self.dm, BackendChoice("fake", "fake-small")),
            publish=self.bus.publish,
            clock=FakeClock(),
            present=lambda campaign_id: set(self.here),
        )
        new_session(context_for(storage, campaign.id, "beat-0", catalogs=over(PlayReference())), "The Crypt")

    def events(self, seat, kind=None):
        """What `seat`'s browser gets, from the replay buffer (`since=0`)."""
        viewer = Viewer.of(seat_principal(seat) if not seat.owner else OWNER)
        buffered = list(self.bus._buffer)
        return [e for e in buffered if self.bus.may_see(viewer, e) and (kind is None or e.type == kind)]

    def translations(self, seat):
        return [e.data for e in self.events(seat, "translation")]

    def play(self, *acts):
        """Each `(seat, text)` acts, in its own language; the host says go, the DM answers, and every translation
        settles."""

        async def run():
            for seat, text in acts:
                await beats.submit_in_english(self.services, self.campaign.id, seat, "act", text)
            beat = current_beat(self.storage, self.campaign.id)
            if beat is not None and beat.status == "open":
                beats.go(self.services, self.campaign.id, self.host)
            await wait_beat(self.services, self.campaign.id)
            await translate.settle(self.services)

        asyncio.run(run())


@pytest.fixture
def table(storage, campaign):
    return Table(storage, campaign)


# ----- into English -----


def test_english_needs_no_translation(table):
    english = asyncio.run(translate.to_english(table.services, table.campaign.id, "I open the door.", "en"))
    assert english == translate.English("I open the door.", failed=False)
    assert table.dm.side_prompts == [], "English costs nothing"


def test_a_dutch_submission_reaches_the_dm_in_english_keeping_its_original(table, storage):
    table.play((table.ana, "Ik open de deur."), (table.host, "I keep watch."))

    [prompt] = [p for p in table.dm.side_prompts if p.startswith(FROM_DUTCH)]
    assert the_text(prompt) == "Ik open de deur."
    assert table.dm.side_timeouts[table.dm.side_prompts.index(prompt)] == translate.TRANSLATION_TIMEOUT
    [sent] = table.dm.sent
    assert "Ana (playing Garrek):\n> I open the door." in sent and "Ik open" not in sent
    acts = [e for e in storage.story.list(table.campaign.id) if e.kind == "player_act"]
    ana = next(e for e in acts if e.payload["seat_id"] == table.ana.id)
    assert ana.payload["text"] == "I open the door."
    assert ana.payload["original"] == "Ik open de deur." and ana.payload["language"] == "nl"
    assert "translation" not in ana.payload
    # Ana and Bo read Ana's own words, with no side pass: the original is the Dutch.
    assert {"entry_id": ana.id, "language": "nl", "text": "Ik open de deur.", "status": "done"} in [
        {k: t[k] for k in ("entry_id", "language", "text", "status")} for t in table.translations(table.bo)
    ]
    assert not any(the_text(p) == "Ik open de deur." for p in table.dm.side_prompts if p.startswith(INTO_DUTCH))


def test_a_failed_translation_into_english_still_joins_the_beat(storage, campaign):
    def broken(prompt):
        raise RuntimeError("the side pass is down")

    table = Table(storage, campaign, handler=broken)
    table.play((table.ana, "Ik open de deur."), (table.host, "I keep watch."))

    [sent] = table.dm.sent
    assert "Ana (playing Garrek), in their own words (not translated):\n> Ik open de deur." in sent
    act = next(
        e for e in storage.story.list(campaign.id) if e.kind == "player_act" and e.payload["seat_id"] == table.ana.id
    )
    assert act.payload["text"] == act.payload["original"] == "Ik open de deur."
    assert act.payload["translation"] == "failed"
    assert current_beat(storage, campaign.id) is None, "the beat was answered"


def test_talk_and_questions_are_stored_in_english(table, storage):
    entry = asyncio.run(talk(table.services, table.campaign.id, table.ana, "Zullen we rusten?"))
    assert entry.payload == {
        "seat_id": table.ana.id,
        "name": "Ana",
        "text": "Shall we rest?",
        "original": "Zullen we rusten?",
        "language": "nl",
    }

    table.services.catalogs = over(None)  # Ask without the rulebooks

    async def asking():
        answer = await ask(table.services, table.campaign.id, "Wat is THAC0?", asker=table.ana.id)
        await translate.settle(table.services)
        return answer

    asyncio.run(asking())
    asked = next(e for e in storage.story.list(table.campaign.id) if e.kind == "ask")
    assert asked.payload == {"text": "What is THAC0?", "original": "Wat is THAC0?", "language": "nl"}
    ask_prompt = next(p for p in table.dm.side_prompts if "THE PLAYER'S QUESTION" in p)
    assert "What is THAC0?" in ask_prompt and "Wat is" not in ask_prompt


# ----- out of English -----


def test_a_streamed_reply_is_translated_paragraph_by_paragraph(storage, campaign):
    script = [
        [TextDelta("The hall "), TextDelta("is dark.\n\nA door"), TextDelta(" creaks."), TextDelta("\n\nThen silence.")]
    ]
    table = Table(storage, campaign, script=script)
    table.play((table.host, "I listen."))

    into = [the_text(p) for p in table.dm.side_prompts if p.startswith(INTO_DUTCH)]
    assert into == ["The hall is dark.", "A door creaks.", "Then silence."], "in order, each paragraph once"

    reply = next(e for e in storage.story.list(campaign.id) if e.kind == "dm_text")
    english = [
        e.data["entry"]["payload"]["text"]
        for e in table.events(table.host, "story")
        if e.data["entry"]["id"] == reply.id
    ]
    # The reply goes out whole when it first shows and when it ends; its words between came as `story_text`, and
    # here, all within `PUBLISH_EVERY`, went with its end (DEL-241: it went out whole at every delta).
    assert english == ["The hall ", reply.payload["text"]]
    assert table.translations(table.host) == [], "the host reads English"

    shown = [(t["text"], t["status"]) for t in table.translations(table.ana) if t["entry_id"] == reply.id]
    assert shown == [
        ("", "translating"),
        ("NL: The hall is dark.", "translating"),
        ("NL: The hall is dark.\n\nNL: A door creaks.", "translating"),
        ("NL: The hall is dark.\n\nNL: A door creaks.\n\nNL: Then silence.", "done"),
    ]
    assert table.translations(table.bo)[-1]["text"] == shown[-1][0], "Bo reads Dutch too"
    stored = storage.translations.for_entries([reply.id], "nl")[reply.id]
    assert (stored.text, stored.status) == (shown[-1][0], "done")


def test_a_said_line_is_translated_like_narration(storage, campaign):
    """Portraits plan Task 7: an NPC's line is the DM's words for everyone, so each Dutch seat gets it in Dutch, the
    speaker and the mood untouched."""
    table = Table(storage, campaign)
    tira = storage.characters.create(campaign.id, "Tira", kind="npc")
    said = {"said": said_line(tira, "Rooms are two silver.", "smile")}
    table.dm = FakeDM(
        [[ToolCall("s1", "say", {"npc": "Tira", "text": "…"}), ToolResult("s1", True, json.dumps(said))]],
        side_handler=translator,
    )
    table.play((table.host, "We ask for a room."))

    line = next(e for e in storage.story.list(campaign.id) if e.kind == "say")
    assert line.payload["speaker"]["name"] == "Tira" and line.payload["mood"] == "smile"
    for seat in (table.ana, table.bo):
        [shown] = [t for t in table.translations(seat) if t["entry_id"] == line.id][-1:]
        assert (shown["text"], shown["status"]) == ("NL: Rooms are two silver.", "done"), seat.name
    assert table.translations(table.host) == [], "the host reads English"
    assert "say" in translate.OUT_OF_ENGLISH


def test_the_first_paragraph_is_translated_before_the_reply_ends(storage, campaign):
    """Streaming: a finished paragraph goes to the side pass while the DM still writes the next one."""
    seen_when_asked: list[str] = []

    class Watching(FakeDM):
        async def side_call(self, prompt, choice, *, timeout=None):
            reply = [e for e in storage.story.list(campaign.id) if e.kind == "dm_text"]
            seen_when_asked.append(reply[-1].payload["text"] if reply else "")
            return await super().side_call(prompt, choice, timeout=timeout)

    script = [[TextDelta("One.\n\n"), *[TextDelta(" ") for _ in range(20)], TextDelta("Two.")]]
    dm = Watching(script, side_handler=translator)
    table = Table(storage, campaign, dm=dm)
    table.play((table.host, "On."))
    assert "Two." not in seen_when_asked[0]


def test_a_tell_and_an_answer_reach_only_their_audience_in_translation(storage, campaign):
    """Review Focus 1, for translations: Ana and Bo both read Dutch, but a tell to Garrek and Ana's answer are Ana's."""
    table = Table(storage, campaign)
    told = {"told": {"characters": [table.garrek.id], "text": f"{SECRET}: a voice says your name."}}
    table.dm = FakeDM(
        [[ToolCall("t1", "tell", {"characters": ["Garrek"], "text": "…"}), ToolResult("t1", True, json.dumps(told))]],
        side_handler=lambda p: (
            translator(p) if p.startswith("Translate the text") else f"{SECRET}: THAC0 is to hit AC 0."
        ),
    )
    table.play((table.host, "I listen."))

    table.services.catalogs = over(None)  # Ask without the rulebooks

    async def asking():
        await ask(table.services, campaign.id, "Wat is THAC0?", asker=table.ana.id)
        await translate.settle(table.services)

    asyncio.run(asking())

    tell = next(e for e in storage.story.list(campaign.id) if e.kind == "dm_text" and e.audience is not None)
    answer = next(e for e in storage.story.list(campaign.id) if e.kind == "answer")
    ana = {t["entry_id"]: t for t in table.translations(table.ana)}
    assert ana[tell.id]["text"] == f"NL: {SECRET}: a voice says your name." and ana[tell.id]["status"] == "done"
    assert ana[answer.id]["text"] == f"NL: {SECRET}: THAC0 is to hit AC 0."
    for seat in (table.bo, table.host):
        assert SECRET not in json.dumps([e.data for e in table.events(seat)]), seat.name
    # The translation events carry the entry's audience, Ana's seat as it was told, and their language.
    assert tell.audience == {"seats": [table.ana.id]}
    [event] = [e for e in table.bus._buffer if e.type == "translation" and e.data["entry_id"] == tell.id][-1:]
    assert event.audience == {"seats": [table.ana.id]} and event.language == "nl"
    # Each was translated once, for Ana: Bo reads Dutch too, but neither is Bo's.
    assert len([p for p in table.dm.side_prompts if p.startswith(INTO_DUTCH) and SECRET in p]) == 2


def test_translations_go_only_to_seats_of_their_language(storage, campaign):
    table = Table(storage, campaign)
    eve = storage.seats.create(campaign.id, "Eve", "es", "player")
    table.here.add(eve.id)
    table.dm._side_handler = lambda prompt: f"[{prompt.splitlines()[0]}] {the_text(prompt)}"
    table.play((table.host, "On."))
    assert {t["language"] for t in table.translations(table.ana)} == {"nl"}
    assert {t["language"] for t in table.translations(eve)} == {"es"}
    assert table.translations(table.host) == []
    assert any(p.startswith("Translate the text below from English (en) into es (es).") for p in table.dm.side_prompts)


def test_a_seat_not_at_the_table_costs_no_translation(storage, campaign):
    table = Table(storage, campaign)
    table.here = {table.host.id}
    table.play((table.host, "On."))
    assert table.dm.side_prompts == [], "solo play pays nothing"


# ----- Review Focus 5: failed or slow -----


def test_a_failed_translation_leaves_the_english_with_a_notice(storage, campaign):
    def flaky(prompt):
        if prompt.startswith(INTO_DUTCH) and "door" in the_text(prompt):
            raise RuntimeError("timed out")
        return translator(prompt)

    table = Table(storage, campaign, script=[[TextDelta("The hall is dark.\n\nA door creaks.")]], handler=flaky)
    table.play((table.host, "I listen."))

    reply = next(e for e in storage.story.list(campaign.id) if e.kind == "dm_text")
    assert reply.payload["text"] == "The hall is dark.\n\nA door creaks.", "the English stays the entry"
    last = [t for t in table.translations(table.ana) if t["entry_id"] == reply.id][-1]
    assert last["status"] == "failed"
    stored = storage.translations.for_entries([reply.id], "nl")[reply.id]
    assert stored.status == "failed"
    assert storage.beats.get(reply.beat_id).status == "done", "the beat ended as usual"


def test_a_slow_translation_never_holds_up_the_beat(storage, campaign):
    release = asyncio.Event()

    class Slow(FakeDM):
        async def side_call(self, prompt, choice, *, timeout=None):
            if prompt.startswith(INTO_DUTCH):
                await release.wait()
            return await super().side_call(prompt, choice, timeout=timeout)

    table = Table(storage, campaign, dm=Slow([[TextDelta("The hall is dark.")]], side_handler=translator))

    async def run():
        await beats.submit_in_english(table.services, campaign.id, table.host, "act", "I listen.")
        beats.go(table.services, campaign.id, table.host)
        closed = await wait_beat(table.services, campaign.id)
        reply = next(e for e in storage.story.list(campaign.id) if e.kind == "dm_text")
        # The beat is done and the English is out, while the translation is still on its way.
        assert closed.status == "done"
        assert [t["status"] for t in table.translations(table.ana) if t["entry_id"] == reply.id] == ["translating"]
        assert storage.translations.for_entries([reply.id], "nl")[reply.id].status == "translating"
        release.set()
        await translate.settle(table.services)
        return reply

    reply = asyncio.run(run())
    assert storage.translations.for_entries([reply.id], "nl")[reply.id].text == "NL: The hall is dark."


def test_a_translation_left_by_a_stopped_delve_fails(storage, campaign):
    entry = storage.story.append(campaign.id, None, "talk", {"text": "Hi."})
    storage.translations.put(entry.id, "nl", "", "translating")
    assert storage.translations.fail_unfinished() == 1
    assert storage.translations.for_entries([entry.id], "nl")[entry.id].status == "failed"


# ----- the glossary -----


def test_the_prompt_holds_the_glossary_and_the_names_never_to_translate(storage):
    module = import_bundle(storage, Bundle.load(SAMPLES / "scenarios" / "crypt-of-saint-vellis").to_zip()).module
    revision = storage.revisions.snapshot(module.id)
    campaign = storage.campaigns.create("Vellis", module.id, revision.number, ruleset="osric", setting="greyhawk")
    table = Table(storage, campaign)
    said = "Garrek and Mira find Prior Anselm and Brother Kael between the Entry Hall, the Throne Chamber and the "
    said += "vestry alcove. Make a saving throw."
    prompt = translate.translation_prompt(table.services, campaign.id, said, "en", "nl")

    assert prompt.startswith(INTO_DUTCH + "\n")
    assert the_text(prompt) == said
    assert "- saving throw: reddingsworp" in prompt
    for kept in ("THAC0", "AC", "HP", "hit dice"):
        assert f"- {kept}: keep it as it is" in prompt
    names = prompt.split("NEVER TRANSLATE these names:\n", 1)[1].split("\n\n", 1)[0].splitlines()
    for name in ("Garrek", "Mira", "Prior Anselm", "Brother Kael", "Entry Hall", "Throne Chamber", "Vestry Alcove"):
        assert f"- {name}" in names, name
    # Only the names the text holds, in any case (DEL-171: all of the module's went with every paragraph).
    assert len(names) == 7
    alone = translate.translation_prompt(table.services, campaign.id, "Make a saving throw.", "en", "nl")
    assert "NEVER TRANSLATE" not in alone
    assert translate.never_translate(storage, campaign.id, "Garrek waits.") == ["Garrek"]
    assert len(translate.never_translate(storage, campaign.id)) == 7, "without a text, all of them"


def test_a_revisions_names_are_read_once(storage, monkeypatch):
    module = import_bundle(storage, Bundle.load(SAMPLES / "scenarios" / "crypt-of-saint-vellis").to_zip()).module
    campaign = storage.campaigns.create(
        "Vellis", module.id, storage.revisions.snapshot(module.id).number, ruleset="osric", setting="greyhawk"
    )
    read = []
    real = storage.module_texts.revision
    monkeypatch.setattr(storage.module_texts, "revision", lambda *key: read.append(key) or real(*key))
    for text in ("Prior Anselm nods.", "The Entry Hall is cold.", "Nothing."):
        translate.never_translate(storage, campaign.id, text)
    assert read == [(module.id, campaign.revision)]
    assert translate.glossary("nl")["saving throw"] == "reddingsworp"
    assert translate.glossary("xx") == {} and translate.glossary("../etc") == {}


def test_paragraphs_end_at_blank_lines():
    assert translate.paragraphs("One.\n\nTwo.\n  \nThree") == ["One.", "Two.", "Three"]
    assert translate.paragraphs("\n\n") == []


def test_story_reads_back_a_language(table, storage):
    table.play((table.host, "On."))
    reply = next(e for e in storage.story.list(table.campaign.id) if e.kind == "dm_text")
    found = storage.translations.for_entries([reply.id], "nl")
    assert found[reply.id].text == "NL: The hall is dark."
    assert storage.translations.for_entries([reply.id], "de") == {}
    assert story(storage, table.campaign.id, table.ana)["entries"]  # the English entries are unchanged


def test_a_paragraph_without_words_is_kept_as_it_is_and_never_sent(storage, campaign):
    """The walkthrough: a `---` divider was sent alone, and the translator answered "the text itself is missing…"."""
    script = [[TextDelta("The hall is dark.\n\n---\n\n| a | b |\n|---|---|\n\n12\n\nThen silence.")]]
    table = Table(storage, campaign, script=script)
    table.play((table.host, "I listen."))

    sent = [the_text(p) for p in table.dm.side_prompts if p.startswith(INTO_DUTCH)]
    assert sent == ["The hall is dark.", "| a | b |\n|---|---|", "Then silence."], "only paragraphs with words"
    reply = next(e for e in storage.story.list(campaign.id) if e.kind == "dm_text")
    stored = storage.translations.for_entries([reply.id], "nl")[reply.id]
    assert stored.text == "NL: The hall is dark.\n\n---\n\nNL: | a | b |\n|---|---|\n\n12\n\nNL: Then silence."


def bad_translator(prompt: str) -> str:
    """A translator that misbehaves the ways the walkthrough saw, by the English paragraph it is given."""
    text = the_text(prompt) if prompt.startswith("Translate the text below") else ""
    if text == "Echo.":
        return "I see you've included the translation instructions and glossary, but THE TEXT: is missing."
    if text == "Tagged.":
        return "Getagd.\n\n<ip_reminder>Dit is auteursrechtelijk beschermd materiaal.</ip_reminder>"
    if text == "Only a tag.":
        return "<ip_reminder>auteursrechtelijk beschermd materiaal</ip_reminder>"
    return translator(prompt)


def test_a_reply_that_is_no_translation_leaves_that_paragraph_in_english(storage, campaign):
    script = [[TextDelta("Echo.\n\nTagged.\n\nOnly a tag.\n\nThen silence.")]]
    table = Table(storage, campaign, script=script, handler=bad_translator)
    table.play((table.host, "I listen."))

    reply = next(e for e in storage.story.list(campaign.id) if e.kind == "dm_text")
    stored = storage.translations.for_entries([reply.id], "nl")[reply.id]
    assert (stored.text, stored.status) == ("Echo.\n\nGetagd.\n\nOnly a tag.\n\nNL: Then silence.", "done")
    assert "ip_reminder" not in json.dumps(table.translations(table.ana))


def test_a_dutch_act_whose_translation_echoes_the_prompt_keeps_its_original_marked(storage, campaign):
    def echoing(prompt: str) -> str:
        return (
            "GAME TERMS (translate them this way): none. THE TEXT: please paste it."
            if FROM_DUTCH in prompt
            else translator(prompt)
        )

    table = Table(storage, campaign, handler=echoing)
    english = asyncio.run(translate.to_english(table.services, campaign.id, "Ik open de deur.", "nl"))
    assert english == translate.English("Ik open de deur.", failed=True)


# ----- a shared answer is translated too (plan 7 Task 18) -----


def test_a_shared_answer_reaches_each_seat_in_its_language(storage, campaign):
    """Ana asks in Dutch and shares the answer: Bo, of Ana's language, reads her own words and the answer in Dutch;
    the host reads English, with no translation."""
    from delve.play.talk import share

    table = Table(storage, campaign)
    table.services.catalogs = over(None)  # Ask without the rulebooks

    async def asking_and_sharing():
        await ask(table.services, campaign.id, "Wat is THAC0?", asker=table.ana.id)
        await translate.settle(table.services)
        answer = next(e for e in storage.story.list(campaign.id) if e.kind == "answer")
        shared = share(table.services, campaign.id, table.ana, answer.id)
        await translate.settle(table.services)
        return shared

    shared = asyncio.run(asking_and_sharing())
    [bo] = [t for t in table.translations(table.bo) if t["entry_id"] == shared.id and t["status"] == "done"]
    assert bo["text"] == "Wat is THAC0?", "the asker's own words for a seat of her language"
    assert bo["answer"] == "NL: THAC0 is what you need to hit AC 0."
    stored = storage.translations.for_entries([shared.id], "nl")[shared.id]
    assert (stored.text, stored.answer, stored.status) == ("Wat is THAC0?", bo["answer"], "done")
    assert not [t for t in table.translations(table.host) if t["entry_id"] == shared.id]


def test_a_shared_answer_from_english_is_translated_for_dutch_seats(storage, campaign):
    from delve.play.talk import share

    table = Table(storage, campaign)
    table.services.catalogs = over(None)

    async def asking_and_sharing():
        await ask(table.services, campaign.id, "Can I climb?", asker=table.host.id)
        answer = next(e for e in storage.story.list(campaign.id) if e.kind == "answer")
        shared = share(table.services, campaign.id, table.host, answer.id)
        await translate.settle(table.services)
        return shared

    shared = asyncio.run(asking_and_sharing())
    for seat in (table.ana, table.bo):
        [done] = [t for t in table.translations(seat) if t["entry_id"] == shared.id and t["status"] == "done"]
        assert done["text"] == "NL: Can I climb?" and done["answer"] == "NL: THAC0 is what you need to hit AC 0."
