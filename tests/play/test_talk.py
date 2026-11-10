"""Table talk and private questions (plan 4 Task 6; spec §7.3): talk reaches every seat at the table and never the DM;
an Ask the DM answer reaches its asker only, who may share it into table talk; Ask's prompt sees only the asker's own
characters."""

import asyncio
import json

import pytest

from delve.dm.fake import FakeDM
from delve.play import seats
from delve.play.ask import ask, ask_prompt
from delve.play.context import NotFound, context_for
from delve.play.sessions import primer
from delve.play.table import dm_message, story, system_prompt
from delve.play.talk import NotYours, share, talk
from tests.fixtures.rulesets import osric_catalogs
from tests.play.test_ask import RecordingDM, services_for

TALK_ONLY = "TALK-ONLY-PLUGH"


@pytest.fixture
def table(storage, campaign):
    """Ana plays Garrek, Bo plays Tira, Cy observes; the host (the owner's seat) plays nobody."""
    garrek = storage.characters.create(campaign.id, "Garrek")
    tira = storage.characters.create(campaign.id, "Tira")
    people = {"host": seats.owner_seat(storage, campaign.id)}
    for name, role in (("Ana", "player"), ("Bo", "player"), ("Cy", "observer")):
        people[name] = storage.seats.create(campaign.id, name, "en", role)
    seats.claim(storage, garrek.id, people["Ana"])
    seats.claim(storage, tira.id, people["Bo"])
    return {"campaign": campaign.id, "garrek": garrek, "tira": tira, **people}


def kinds(storage, table, who: str) -> list[str]:
    return [e.kind for e in story(storage, table["campaign"], table[who])["entries"]]


def test_talk_reaches_every_seat(storage, table):
    events: list = []
    services = services_for(storage, FakeDM([]), events)
    entry = asyncio.run(talk(services, table["campaign"], table["Cy"], "  Shall we rest first?  "))

    assert entry.kind == "talk" and entry.beat_id is None and entry.audience is None
    cy = table["Cy"]
    assert entry.payload == {
        "seat_id": cy.id,
        "name": "Cy",
        "text": "Shall we rest first?",
        "original": "Shall we rest first?",
        "language": "en",
    }
    for who in ("host", "Ana", "Bo", "Cy"):
        assert kinds(storage, table, who) == ["talk"], who
    assert [(kind, data["entry"]["id"]) for kind, data in events] == [("story", entry.id)]


def test_talk_refuses_nothing_to_say(storage, table):
    services = services_for(storage, FakeDM([]))
    with pytest.raises(Exception, match="Say something."):
        asyncio.run(talk(services, table["campaign"], table["Ana"], "   "))
    assert storage.story.list(table["campaign"]) == []


def test_talk_never_reaches_the_dm(storage, table):
    """Talk is no submission: it is in no beat, the DM's message, the primer or the system prompt."""
    cid = table["campaign"]
    services = services_for(storage, FakeDM([]))
    asyncio.run(talk(services, cid, table["Ana"], f"{TALK_ONLY}: I think the abbot did it."))
    act = {
        "seat_id": table["Bo"].id,
        "kind": "act",
        "characters": [table["tira"].id],
        "text": "Tira opens the door.",
        "original": "Tira opens the door.",
        "language": "en",
        "at": "",
    }
    beat = storage.beats.open(cid, [act], status="running")

    message = dm_message(storage, cid, beat)
    assert "Tira opens the door." in message
    assert TALK_ONLY not in message
    assert TALK_ONLY not in json.dumps(primer(context_for(storage, cid, "talk", catalogs=osric_catalogs())))
    assert TALK_ONLY not in system_prompt(services, cid)
    assert TALK_ONLY not in json.dumps(beat.submissions)


def test_an_answer_reaches_its_asker_only(storage, table):
    cid = table["campaign"]
    services = services_for(storage, RecordingDM())
    asyncio.run(ask(services, cid, "Can Garrek climb the wall?", asker=table["Ana"].id))
    asyncio.run(ask(services, cid, "How far can Tira see in the dark?", asker=table["Bo"].id))

    ana = story(storage, cid, table["Ana"])["entries"]
    bo = story(storage, cid, table["Bo"])["entries"]
    assert [(e.kind, e.payload["text"][:9]) for e in ana] == [("ask", "Can Garre"), ("answer", "Here is e")]
    assert [(e.kind, e.payload["text"][:9]) for e in bo] == [("ask", "How far c"), ("answer", "Here is e")]
    assert kinds(storage, table, "host") == [] and kinds(storage, table, "Cy") == []


def test_asks_prompt_holds_only_the_askers_characters(storage, table):
    cid = table["campaign"]
    services = services_for(storage, RecordingDM())

    ana = ask_prompt(services, cid, "Can I climb?", table["Ana"])
    assert "Garrek" in ana and "Tira" not in ana
    bo = ask_prompt(services, cid, "Can I climb?", table["Bo"])
    assert "Tira" in bo and "Garrek" not in bo
    for nobody in (table["Cy"], table["host"]):  # an observer, and a host whose PCs are all claimed
        prompt = ask_prompt(services, cid, "Can I climb?", nobody)
        assert "Garrek" not in prompt and "Tira" not in prompt
        assert "(no characters of the asker)" in prompt

    # The host plays every PC nobody has claimed: in solo play, the whole party.
    seats.release(storage, table["tira"].id, table["Bo"])
    host = ask_prompt(services, cid, "Can I climb?", table["host"])
    assert "Tira" in host and "Garrek" not in host

    # And ask itself sends that prompt.
    dm = RecordingDM()
    asyncio.run(ask(services_for(storage, dm), cid, "Can I climb?", asker=table["Ana"].id))
    [(prompt, _)] = dm.prompts
    assert "Garrek" in prompt and "Tira" not in prompt


def test_the_asker_shares_an_answer_into_table_talk(storage, table):
    cid = table["campaign"]
    events: list = []
    services = services_for(storage, FakeDM([], side_handler=lambda prompt: "Yes, with a rope."), events)
    asyncio.run(ask(services, cid, "Can Garrek climb the wall?", asker=table["Ana"].id))
    answer = story(storage, cid, table["Ana"])["entries"][-1]
    events.clear()

    shared = share(services, cid, table["Ana"], answer.id)
    assert shared.kind == "talk" and shared.audience is None and shared.beat_id is None
    assert shared.payload == {
        "seat_id": table["Ana"].id,
        "name": "Ana",
        "text": "Can Garrek climb the wall?",
        "original": "Can Garrek climb the wall?",
        "language": "en",
        "answer": "Yes, with a rope.",
        "shared": answer.id,
    }
    for who in ("host", "Bo", "Cy"):
        assert kinds(storage, table, who) == ["talk"], who
    assert kinds(storage, table, "Ana") == ["ask", "answer", "talk"]
    assert [kind for kind, _ in events] == ["story"]


def test_only_the_asker_may_share(storage, table):
    cid = table["campaign"]
    services = services_for(storage, FakeDM([], side_handler=lambda prompt: "Yes."))
    asyncio.run(ask(services, cid, "Can Garrek climb the wall?", asker=table["Ana"].id))
    asked, answer = story(storage, cid, table["Ana"])["entries"]

    for who in ("Bo", "Cy", "host"):
        with pytest.raises(NotYours):
            share(services, cid, table[who], answer.id)
    with pytest.raises(NotFound):
        share(services, cid, table["Ana"], asked.id)  # a question is no answer
    with pytest.raises(NotFound):
        share(services, cid, table["Ana"], "sty_nothing")
    talked = asyncio.run(talk(services, cid, table["Ana"], "Hello."))
    with pytest.raises(NotFound):
        share(services, cid, table["Ana"], talked.id)
    assert kinds(storage, table, "Bo") == ["talk"]


def test_an_answer_of_another_campaign_is_not_found(storage, table, campaign):
    other = storage.campaigns.create(
        "Thursday", campaign.module_id, campaign.revision, ruleset="osric", setting="greyhawk"
    )
    services = services_for(storage, FakeDM([], side_handler=lambda prompt: "Yes."))
    owner = seats.owner_seat(storage, other.id)
    asyncio.run(ask(services, other.id, "Is it raining?", asker=owner.id))
    answer = story(storage, other.id, owner)["entries"][-1]
    with pytest.raises(NotFound):
        share(services, table["campaign"], table["host"], answer.id)
