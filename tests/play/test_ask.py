"""Ask the DM (plan 2b Task 6; spec §7.3): a side pass with no tools that answers from the rules, the setting and what
the characters know. It never sees module canon, DM secrets or NPC notes (Review Focus 3)."""

import asyncio
import json
from dataclasses import replace

from delve.dm.fake import FakeDM
from delve.dm.provider import Usage
from delve.dm.tools import all_specs
from delve.domain.histories import History
from delve.domain.modules import ModuleMap
from delve.domain.setting_content import Proposal, SettingAddition, SettingFact
from delve.domain.settings import BackendChoice
from delve.modules.dscn import Bundle
from delve.modules.importer import import_bundle
from delve.play import seats
from delve.play.ask import RECENT, SESSION_CHARS, ask, ask_prompt
from delve.play.audience import for_seats
from delve.play.table import AppServices, add_entry, dm_log, story
from tests.dm.tools.conftest import CRYPT as CRYPT_WITH_HIDDEN_ROOM
from tests.fixtures import SAMPLES
from tests.fixtures.play_reference import RulesReference
from tests.fixtures.rulesets import over
from tests.play.conftest import crypt_campaign

SECRET = "SECRET-XYZZY"
SCENARIO = SAMPLES / "scenarios" / "crypt-of-saint-vellis"


class RecordingDM(FakeDM):
    """A fake side pass that records its prompts and answers with all of it, the worst a model could do."""

    def __init__(self):
        super().__init__([])
        self.prompts: list[tuple[str, BackendChoice]] = []

    async def side_call(self, prompt, choice, *, timeout=None, on_usage=None):
        self.prompts.append((prompt, choice))
        return f"Here is everything I was told: {prompt}"


def services_for(storage, dm, events=None):
    published = events if events is not None else []
    return AppServices(
        storage=storage,
        catalogs=over(RulesReference()),
        spec_lookup={spec.name: spec for spec in all_specs()}.get,
        dm=lambda campaign_id: (dm, BackendChoice("fake", "fake-large")),
        side=lambda campaign_id: (dm, BackendChoice("fake", "fake-small")),
        publish=lambda kind, data, **where: published.append((kind, data)),
    )


def planted_campaign(storage, **options):
    """The crypt sample with the secret in its module text, a hidden room, an NPC's notes and a DM secret; `options`
    go to `campaigns.create`."""
    bundle = Bundle.load(SCENARIO)
    key = bundle.text_entry("crypt-key")["file"]
    bundle.files[key] = bundle.read(key).replace(b"a purse of 40 gp.", f"a purse of 40 gp. {SECRET}".encode())
    module = import_bundle(storage, bundle.to_zip()).module
    storage.modules.put_map(module.id, ModuleMap("crypt", "map", CRYPT_WITH_HIDDEN_ROOM, is_default=True))
    revision = storage.revisions.snapshot(module.id)
    campaign = storage.campaigns.create(
        "Vellis", module.id, revision.number, **{"ruleset": "osric", "setting": "greyhawk", **options}
    )
    assert SECRET in json.dumps(storage.module_texts.revision(module.id, revision.number))
    storage.characters.create(campaign.id, "Garrek")
    storage.characters.create(campaign.id, "Tira", kind="npc")
    tira = storage.characters.list(campaign.id)[-1]
    from dataclasses import replace

    storage.characters.save(replace(tira, sheet=replace(tira.sheet, notes_md=f"{SECRET}: she is the cult.")))
    storage.notes.create(campaign.id, kind="secret", text=f"{SECRET}: the abbot is the ritualist.")
    return campaign


def test_ask_has_no_module_canon(storage):
    campaign = planted_campaign(storage)
    dm = RecordingDM()
    events: list = []
    services = services_for(storage, dm, events)

    asker = seats.owner_seat(storage, campaign.id)
    answer = asyncio.run(ask(services, campaign.id, "Who is Tira, and what is in the crypt?", asker=asker.id))
    [(prompt, choice)] = dm.prompts
    assert choice == BackendChoice("fake", "fake-small")  # the side job's choice
    assert "Who is Tira, and what is in the crypt?" in prompt and "Garrek" in prompt
    assert "never from the module" in prompt
    assert SECRET not in prompt and SECRET not in answer

    entries = story(storage, campaign.id, asker)["entries"]
    assert [(e.kind, e.beat_id) for e in entries] == [("ask", None), ("answer", None)]
    assert [e.audience for e in entries] == [{"seats": [asker.id]}] * 2, "for the asker alone"
    other = storage.seats.create(campaign.id, "Bo", "en", "player")
    assert story(storage, campaign.id, other)["entries"] == []
    assert entries[0].payload == {
        "text": "Who is Tira, and what is in the crypt?",
        "original": "Who is Tira, and what is in the crypt?",
        "language": "en",
    }
    assert entries[1].payload == {"text": answer}
    assert SECRET not in json.dumps([e.payload for e in entries])
    assert SECRET not in json.dumps(events)
    assert [kind for kind, _ in events] == ["story", "story"]
    [logged] = dm_log(storage, campaign.id)
    assert (logged.beat_id, logged.raw_event_json) == (None, {"type": "ask", "usage": None}), "no usage reported"


def test_an_ask_writes_its_cost_in_the_dm_log(storage, campaign):
    """G2: the side pass's usage is an `ask` row under no beat, with no words of the question or the answer."""
    dm = FakeDM([], side_handler=lambda prompt: "Two silver pieces.", side_usage=Usage(900, 60, 0.004))
    asker = seats.owner_seat(storage, campaign.id)

    asyncio.run(ask(services_for(storage, dm), campaign.id, "What does a torch cost?", asker=asker.id))

    [logged] = dm_log(storage, campaign.id)
    assert logged.beat_id is None
    assert logged.raw_event_json == {
        "type": "ask",
        "usage": {"input_tokens": 900, "output_tokens": 60, "cost_usd": 0.004},
    }


def test_a_question_never_writes_the_campaign(storage, campaign):
    """DEL-161: asking reads the characters and the day, and rolls no weather and seeds no factions, clocks or
    quests, as a beat would."""
    asker = seats.owner_seat(storage, campaign.id)
    state = storage.campaign_states.get(campaign.id)
    before = (state, storage.factions.list(campaign.id), storage.clocks.list(campaign.id), storage.quests.list(campaign.id))

    prompt = ask_prompt(services_for(storage, RecordingDM()), campaign.id, "What do I know?", asker)

    assert "THE ASKER'S CHARACTERS" in prompt
    after = storage.campaign_states.get(campaign.id)
    assert after == state and not after.weather, "no weather rolled"
    assert (after, storage.factions.list(campaign.id), storage.clocks.list(campaign.id), storage.quests.list(campaign.id)) == before


def test_ask_sees_what_the_askers_characters_saw_lately(storage, campaign):
    """Walkthrough D4 and owner item 3: the session's story entries the asker could see, in English. A tell to
    another seat's character stays out (the fourth wall), and so do tool rows and the DM's errors."""
    host = seats.owner_seat(storage, campaign.id)
    ana = storage.seats.create(campaign.id, "Ana", "nl", "player")
    bo = storage.seats.create(campaign.id, "Bo", "en", "player")
    garrek = storage.characters.create(campaign.id, "Garrek")
    mira = storage.characters.create(campaign.id, "Mira")
    seats.claim(storage, garrek.id, ana)
    seats.claim(storage, mira.id, bo)
    beat = storage.beats.open(campaign.id, [], status="running")
    add_entry(storage, campaign.id, beat.id, "dm_text", {"text": "Long ago, the old road."})
    for n in range(RECENT - 4):
        add_entry(storage, campaign.id, beat.id, "dm_text", {"text": f"The rain keeps on, hour {n}."})
    add_entry(storage, campaign.id, beat.id, "player_act", {"kind": "act", "name": "Ana", "text": "I open the door."})
    add_entry(storage, campaign.id, beat.id, "tool", {"name": "roll", "error": None})
    add_entry(storage, campaign.id, beat.id, "dm_text", {"text": f"{SECRET}: Mira hears a voice."}, for_seats([bo.id]))
    add_entry(storage, campaign.id, beat.id, "dm_text", {"text": "Garrek feels a chill."}, {"characters": [garrek.id]})
    add_entry(storage, campaign.id, beat.id, "dm_error", {"message": "The DM didn't answer: timeout"})
    add_entry(storage, campaign.id, None, "talk", {"seat_id": host.id, "name": "Raf", "text": "Snacks?"})
    add_entry(storage, campaign.id, beat.id, "dm_text", {"text": "The door opens on a stair."})

    services = services_for(storage, RecordingDM())
    prompt = ask_prompt(services, campaign.id, "What is behind the door?", ana)
    assert "WHAT HAPPENED THIS SESSION" in prompt
    lately = prompt.split("WHAT HAPPENED THIS SESSION", 1)[1].split("THE PLAYER'S QUESTION", 1)[0]
    for seen in ("Long ago", "I open the door.", "Garrek feels a chill.", "Snacks?", "The door opens on a stair."):
        assert seen in lately, seen
    assert SECRET not in prompt, "a tell to another seat's character"
    assert lately.count("\n- ") == RECENT + 1, "no session started yet: the whole story is this session"
    assert "roll" not in lately and "didn't answer" not in lately

    # Bo sees his own tell, and not Garrek's.
    bo_lately = ask_prompt(services, campaign.id, "What was that voice?", bo)
    assert SECRET in bo_lately and "Garrek feels a chill." not in bo_lately


def test_ask_hears_what_npcs_said(storage, campaign):
    """Portraits plan Task 7: an NPC's line is its own `say` entry now, and still part of what happened, by its
    speaker's name."""
    ana = storage.seats.create(campaign.id, "Ana", "en", "player")
    beat = storage.beats.open(campaign.id, [], status="running")
    add_entry(storage, campaign.id, beat.id, "dm_text", {"text": "The innkeeper looks up."})
    speaker = {"id": "chr_000000000001", "name": "Tira", "portrait": None}
    add_entry(storage, campaign.id, beat.id, "say", {"speaker": speaker, "mood": "smile", "text": "Two silver."})
    prompt = ask_prompt(services_for(storage, RecordingDM()), campaign.id, "Is it cheap?", ana)
    assert 'Tira said: "Two silver."' in session_block(prompt)


def next_session(storage, campaign_id, title):
    """Start the campaign's next session, as `new_session` does."""
    state = storage.campaign_states.get(campaign_id)
    number = state.session if storage.sessions.get(campaign_id, state.session) is None else state.session + 1
    storage.campaign_states.put(replace(state, session=number))
    return storage.sessions.start(campaign_id, number, title)


def session_block(prompt):
    return prompt.split("WHAT HAPPENED THIS SESSION", 1)[1].split("THE PLAYER'S QUESTION", 1)[0]


def test_ask_reads_the_whole_session_and_the_last_recap(storage, campaign):
    """Plan faithful modules Task 23 (F5): every entry of the current session the asker may see, from its first
    beat, and the last recap; never what was told to another seat, and never a key number."""
    ana = storage.seats.create(campaign.id, "Ana", "en", "player")
    bo = storage.seats.create(campaign.id, "Bo", "en", "player")
    garrek = storage.characters.create(campaign.id, "Garrek")
    mira = storage.characters.create(campaign.id, "Mira")
    seats.claim(storage, garrek.id, ana)
    seats.claim(storage, mira.id, bo)
    first = next_session(storage, campaign.id, "The road")
    beat = storage.beats.open(campaign.id, [], status="running")
    add_entry(storage, campaign.id, beat.id, "dm_text", {"text": "Last session, on the road."})
    storage.sessions.end(campaign.id, first.number, "The party reached Saltmarsh.")
    add_entry(storage, campaign.id, beat.id, "recap", {"text": "The party reached Saltmarsh.", "session": 1})
    next_session(storage, campaign.id, "The house")

    for n in range(13):
        add_entry(storage, campaign.id, beat.id, "player_act", {"kind": "act", "name": "Ana", "text": f"I act {n}."})
        if n == 2:
            add_entry(storage, campaign.id, beat.id, "dm_text", {"text": f"{SECRET}: a voice."}, for_seats([bo.id]))
            add_entry(storage, campaign.id, beat.id, "dm_text", {"text": f"{SECRET} hides."}, {"characters": [mira.id]})
        add_entry(storage, campaign.id, beat.id, "dm_text", {"text": f"The DM answers beat {n}."})

    services = services_for(storage, RecordingDM())
    prompt = ask_prompt(services, campaign.id, "What did we see at first?", ana)
    block = session_block(prompt)
    assert "I act 0." in block and "The DM answers beat 12." in block, "the session from its first beat"
    assert block.index("I act 0.") < block.index("I act 12."), "oldest first"
    assert "Last session, on the road." not in block, "an earlier session's entry"
    assert "(earlier entries left out)" not in block
    assert SECRET not in prompt, "told to another seat"
    assert "LAST RECAP" in prompt and "The party reached Saltmarsh." in prompt.split("LAST RECAP", 1)[1]
    assert "Never name a room by a key number ('room 4'): name it as the characters know it." in prompt

    # Bo sees his own tells in his session block.
    assert SECRET in ask_prompt(services, campaign.id, "What was that voice?", bo)


def test_ask_keeps_the_newest_of_a_long_session(storage, campaign):
    """Over `SESSION_CHARS`, the newest entries that fit, marked as cut; never fewer than the last `RECENT`."""
    owner = seats.owner_seat(storage, campaign.id)
    next_session(storage, campaign.id, "A long one")
    beat = storage.beats.open(campaign.id, [], status="running")
    for n in range(60):
        add_entry(storage, campaign.id, beat.id, "dm_text", {"text": f"Entry {n:02d}. " + "rain " * 60})
    block = session_block(ask_prompt(services_for(storage, RecordingDM()), campaign.id, "Now?", owner))
    assert "(earlier entries left out)" in block
    assert "Entry 59." in block and "Entry 00." not in block
    assert len(block) <= SESSION_CHARS + 200

    huge = "storm " * 2000
    for n in range(RECENT):
        add_entry(storage, campaign.id, beat.id, "dm_text", {"text": f"Huge {n}. {huge}"})
    block = session_block(ask_prompt(services_for(storage, RecordingDM()), campaign.id, "Now?", owner))
    assert all(f"Huge {n}." in block for n in range(RECENT)), f"never fewer than the last {RECENT}"


def test_ask_fills_a_new_session_with_the_last_entries(storage, campaign):
    """A session just started still shows the last `RECENT` entries the asker may see, from before it."""
    owner = seats.owner_seat(storage, campaign.id)
    beat = storage.beats.open(campaign.id, [], status="running")
    for n in range(RECENT + 2):
        add_entry(storage, campaign.id, beat.id, "dm_text", {"text": f"Before {n}."})
    next_session(storage, campaign.id, "Fresh")
    add_entry(storage, campaign.id, beat.id, "dm_text", {"text": "Now we begin."})
    block = session_block(ask_prompt(services_for(storage, RecordingDM()), campaign.id, "Now?", owner))
    assert block.count("\n- ") == RECENT
    assert "Now we begin." in block and f"Before {RECENT + 1}." in block and "Before 2." not in block


def test_ask_answers_rules_with_figures(storage, campaign):
    """Walkthrough D4: the rules' actual figures, and no deferral to the DM."""
    prompt = ask_prompt(services_for(storage, RecordingDM()), campaign.id, "How does turning work?",
                        seats.owner_seat(storage, campaign.id))  # fmt: skip
    assert "actual figures" in prompt
    assert "never say that the DM should confirm" in prompt


def test_ask_includes_rules_snippets(storage, campaign):
    dm = RecordingDM()
    services = services_for(storage, dm)
    asker = seats.owner_seat(storage, campaign.id).id
    asyncio.run(ask(services, campaign.id, "What does surprise do?", asker=asker))
    [(prompt, _)] = dm.prompts
    assert "A surprised character or monster cannot act for one round" in prompt.replace("<<", "").replace(">>", "")
    assert prompt.count("\n- PHB") + prompt.count("\n- DMG") <= 3

    # A question that is all punctuation, or about nothing in the books, still gets asked.
    asyncio.run(ask(services, campaign.id, "??? \"*\" OR NOT", asker=asker))
    assert len(dm.prompts) == 2


def greyhawk_campaign(storage):
    return crypt_campaign(storage, setting="greyhawk")


def setting_block(prompt):
    assert "FROM THE SETTING, Greyhawk (searched for the question):" in prompt
    return prompt.split("FROM THE SETTING", 1)[1].split("THE PLAYER'S QUESTION", 1)[0]


def test_ask_is_given_the_setting_for_the_question(storage):
    """Settings plan Task 6: the setting's hits for the question's words, after the rules, and the page the question
    names."""
    campaign = greyhawk_campaign(storage)
    prompt = ask_prompt(services_for(storage, RecordingDM()), campaign.id, "Who rules Hardby?",
                        seats.owner_seat(storage, campaign.id))  # fmt: skip
    block = setting_block(prompt)
    assert "\n- Hardby: " in block and "<<hardby>>" in block.casefold()
    assert "**Hardby** is a port on the Woolly Bay" in block, "the page the question names, as Markdown"
    assert prompt.index("FROM THE SETTING") < prompt.index("THE PLAYER'S QUESTION")
    if "FROM THE RULEBOOKS" in prompt:
        assert prompt.index("FROM THE RULEBOOKS") < prompt.index("FROM THE SETTING")
    assert "don't volunteer more of the setting than the question needs" in prompt


def test_ask_is_given_the_install_and_campaign_additions(storage):
    campaign = greyhawk_campaign(storage)
    other = greyhawk_campaign(storage)
    storage.setting_pages.put(SettingAddition("greyhawk", "Saltmarsh", text="A fishing town on the Azure coast."))
    storage.proposals.add(
        Proposal(0, "greyhawk", campaign.id, "page", title="Cove of Bones", text="A fishing cove.", page_kind="place")
    )
    storage.proposals.add(
        Proposal(0, "greyhawk", other.id, "page", title="Gull Rock", text="A fishing rock.", page_kind="place")
    )
    services = services_for(storage, RecordingDM())
    block = setting_block(ask_prompt(services, campaign.id, "Where do they go fishing?",
                                     seats.owner_seat(storage, campaign.id)))  # fmt: skip
    assert "\n- Cove of Bones: " in block and "\n- Saltmarsh: " in block
    assert "Gull Rock" not in block, "another campaign's proposal"


def test_ask_never_gets_dm_only_setting_content(storage):
    """The fourth wall: Ask reads the setting as a seat does, so no DM-only section, page, fact or proposal comes in,
    even when the question names their words."""
    campaign = greyhawk_campaign(storage)
    storage.setting_pages.put(
        SettingAddition("greyhawk", "Saltmarsh", text=f"A fishing town.\n\n::: dm\nThe cove {SECRET} smugglers.\n:::")
    )
    storage.setting_pages.put(SettingAddition("greyhawk", "Hidden Keep", text=f"Keep {SECRET}.", dm_only=True))
    storage.setting_facts.add(SettingFact(0, "greyhawk", f"The smugglers of Hardby are {SECRET}.", "greyhawk", dm_only=True))
    for kind, fields in (
        ("fact", {"text": f"The smugglers fear {SECRET}."}),
        ("edit", {"title": "Hardby", "text": f"The smugglers' harbour hides {SECRET}."}),
        ("page", {"title": "Smugglers Cove", "text": f"Smugglers {SECRET}.", "page_kind": "place"}),
    ):
        storage.proposals.add(Proposal(0, "greyhawk", campaign.id, kind, dm_only=True, **fields))
    services = services_for(storage, RecordingDM())
    asker = seats.owner_seat(storage, campaign.id)
    for question in (
        "Who are the smugglers of Saltmarsh and Hardby?",
        "What is the Hidden Keep?",
        "Tell me about Smugglers Cove, the cove and SECRET-XYZZY.",
        "What hides in Hardby's harbour?",
    ):
        prompt = ask_prompt(services, campaign.id, question.replace(SECRET, "xyzzy"), asker)
        assert SECRET not in prompt, question
    assert "\n- Saltmarsh: " in setting_block(ask_prompt(services, campaign.id, "Who fish at Saltmarsh?", asker))


def test_ask_without_a_setting_has_no_setting_block(storage):
    campaign = crypt_campaign(storage, setting=None)
    prompt = ask_prompt(services_for(storage, RecordingDM()), campaign.id, "Who rules Hardby?",
                        seats.owner_seat(storage, campaign.id))  # fmt: skip
    assert "FROM THE SETTING" not in prompt
    greyhawk = greyhawk_campaign(storage)
    for question in ("??? \"*\"", "Where is Zzyzzx?"):
        prompt = ask_prompt(services_for(storage, RecordingDM()), greyhawk.id, question,
                            seats.owner_seat(storage, greyhawk.id))  # fmt: skip
        assert "FROM THE SETTING" not in prompt, "no words, or no hits"


def test_ask_still_gets_no_module_text(storage):
    """With a setting, the module's text, NPC notes and DM secrets still never come in."""
    campaign = planted_campaign(storage)
    assert campaign.setting == "greyhawk"
    prompt = ask_prompt(services_for(storage, RecordingDM()), campaign.id,
                        "What is the purse in the crypt, and who rules Hardby?",
                        seats.owner_seat(storage, campaign.id))  # fmt: skip
    assert "FROM THE SETTING" in prompt
    assert SECRET not in prompt


def test_ask_prompt_includes_table_history_never_dm(storage, campaign):
    """Carry-the-party-on plan Task 6: Ask reads the table's history, after the last recap, never the DM's, and only
    once it has a table text."""
    ana = storage.seats.create(campaign.id, "Ana", "en", "player")
    first = next_session(storage, campaign.id, "The road")
    beat = storage.beats.open(campaign.id, [], status="running")
    storage.sessions.end(campaign.id, first.number, "The party reached Saltmarsh.")
    add_entry(storage, campaign.id, beat.id, "recap", {"text": "The party reached Saltmarsh.", "session": 1})
    services = services_for(storage, RecordingDM())
    head = "THE PARTY'S EARLIER HISTORY (what the table knows):\n"

    assert "EARLIER HISTORY" not in ask_prompt(services, campaign.id, "Who was Ulric?", ana), "no history"
    storage.histories.put(History(campaign.id, dm_md=f"{SECRET}: the abbot lives."))
    assert "EARLIER HISTORY" not in ask_prompt(services, campaign.id, "Who was Ulric?", ana), "no table text yet"

    storage.histories.put(
        History(campaign.id, dm_md=f"{SECRET}: the abbot lives.", table_md="We met Ulric.", status="done")
    )
    prompt = ask_prompt(services, campaign.id, "Who was Ulric?", ana)
    assert f"{head}We met Ulric." in prompt
    assert SECRET not in prompt, "the DM's history"
    assert prompt.index("LAST RECAP") < prompt.index(head) < prompt.index("THE PLAYER'S QUESTION")


def test_ask_reads_the_table_history_a_failed_write_again_kept(storage, campaign):
    """Review fix: a failed Write again keeps the old texts; Ask reads the table's, never the DM's."""
    ana = storage.seats.create(campaign.id, "Ana", "en", "player")
    services = services_for(storage, RecordingDM())
    storage.histories.put(
        History(
            campaign.id,
            dm_md=f"{SECRET}: the abbot lives.",
            table_md="We met Ulric.",
            status="failed",
            error="Claude stopped.",
        )
    )

    prompt = ask_prompt(services, campaign.id, "Who was Ulric?", ana)

    assert "THE PARTY'S EARLIER HISTORY (what the table knows):\nWe met Ulric." in prompt
    assert SECRET not in prompt, "the DM's history"


def test_a_question_about_the_app_gets_the_help_and_the_askers_role(storage, campaign):
    """DEL-221: "How do I give a character to another player?" from the host was answered as a rules question. The
    prompt now has the Help's topics, the best ones whole, and who asks; the rule says to answer from them."""
    host = storage.seats.create(campaign.id, "Raf", "en", "host")
    player = storage.seats.create(campaign.id, "Ana", "en", "player")
    services = services_for(storage, RecordingDM())

    prompt = ask_prompt(services, campaign.id, "How do I give a character to another player?", host)
    assert "HOW DELVE WORKS" in prompt and "answer it from HOW DELVE WORKS" in prompt
    assert "The asker is the table's host" in prompt
    assert 'THE HELP TOPIC "Inviting players"' in prompt and "Who plays whom" in prompt
    assert "- Running a session (for hosts and organisers):" in prompt, "every topic is listed"
    assert "<figure" not in prompt and "](/help/" not in prompt, "no pictures"
    assert "The asker is a player at the table" in ask_prompt(services, campaign.id, "How do I raise my hand?", player)


def test_help_for_reads_a_topic_folder(tmp_path):
    from delve.play import help_topics

    (tmp_path / "seats.md").write_text(
        "---\ntitle: Seats\naudience: organiser\nsummary: Who plays whom.\n---\n"
        'Give a seat its characters.\n\n<figure><img src="/help/x.webp"></figure>\n' + "More. " * 800
    )
    (tmp_path / "dice.md").write_text("---\ntitle: Dice\naudience: player\nsummary: Rolling.\n---\nRoll them.\n")
    out = help_topics.help_for(["seat", "characters"], "cohost", root=tmp_path)
    assert "The asker is a co-host of the table" in out
    assert "- Seats (for hosts and organisers): Who plays whom." in out and "- Dice (for players): Rolling." in out
    assert 'THE HELP TOPIC "Seats"' in out and 'THE HELP TOPIC "Dice"' not in out, "only the topics that match"
    assert "<figure" not in out and out.endswith(" …")
    assert help_topics.help_for(["seat"], "host", root=tmp_path / "none") == ""


def test_ask_reads_an_items_notes_never_its_dm_notes(storage, campaign):
    """DEL-181: what the characters know of an item reaches Ask the DM; what only the DM knows never does. The DM's
    primer has both."""
    from delve.domain.characters import Item
    from delve.play.context import context_for
    from delve.play.sessions import primer

    ana = storage.seats.create(campaign.id, "Ana", "en", "player")
    garrek = storage.characters.create(campaign.id, "Garrek")
    phial = Item("Glass phial", notes="stoppered, cloudy", dm_notes="SECRET-XYZZY potion of neutralize poison")
    storage.characters.save(replace(garrek, state=replace(garrek.state, inventory=(phial,))))
    seats.claim(storage, garrek.id, ana)
    services = services_for(storage, RecordingDM())

    prompt = ask_prompt(services, campaign.id, "What is the phial?", ana)
    assert "Glass phial x1 (stoppered, cloudy)" in prompt and "SECRET-XYZZY" not in prompt
    (pc,) = primer(context_for(storage, campaign.id, "beat-1", catalogs=over(RulesReference())), roll_weather=False)["party"]
    assert pc["dm_notes"] == ["Glass phial: SECRET-XYZZY potion of neutralize poison"]
    assert "SECRET-XYZZY" not in pc["inventory"]
