"""How long, and how often, a seat may speak (DEL-154, audit finding 7): an act, a question or a line of table talk past
its length is 422 with the reason, before anything reaches Claude; a seat that acts, asks, talks or asks for a scene
too often in a window waits, 429 with `Retry-After`, while the other seats go on. The web's composer mirrors the
lengths (`web/src/play/limits.ts`)."""

import re
from pathlib import Path

import pytest

from delve.web.play_limits import ACT_CHARS, ASK_CHARS, HINT_CHARS, TALK_CHARS, SeatThrottle, seat_throttle
from tests.web import test_talk_api as talk_api
from tests.web.test_talk_api import path

# The table of the talk tests: Ana plays Garrek, Bo plays Tira, Cy observes.
dm, registries, table = talk_api.dm, talk_api.registries, talk_api.table

WEB_LIMITS = Path(__file__).parents[2] / "web" / "src" / "play" / "limits.ts"


@pytest.fixture
def ticks(app):
    """The throttle's clock, moved by hand: `ticks.now += 60`."""

    class Ticks:
        now = 1000.0

    seat_throttle(app).clock = lambda: Ticks.now
    return Ticks


def test_the_lengths_fit_real_play():
    assert ACT_CHARS == 4000, "a long act of a few paragraphs"
    assert ASK_CHARS == 2000 and TALK_CHARS == 1500 and HINT_CHARS == 500


def test_the_composer_mirrors_the_lengths():
    found = dict(re.findall(r"(\w+): (\d+)", WEB_LIMITS.read_text(encoding="utf-8")))
    assert {k: int(v) for k, v in found.items()} == {
        "act": ACT_CHARS,
        "ask": ASK_CHARS,
        "talk": TALK_CHARS,
        "hint": HINT_CHARS,
    }


@pytest.mark.parametrize(
    ("rest", "field", "limit", "message"),
    [
        ("act", "text", ACT_CHARS, f"An act is at most {ACT_CHARS} characters."),
        ("ask", "question", ASK_CHARS, f"A question is at most {ASK_CHARS} characters."),
        ("talk", "text", TALK_CHARS, f"Table talk is at most {TALK_CHARS} characters."),
        ("scene", "hint", HINT_CHARS, f"A hint is at most {HINT_CHARS} characters."),
    ],
)
def test_words_past_their_length_are_refused_before_claude_hears_them(table, dm, rest, field, limit, message):
    _, ana = table["Ana"]
    refused = ana.post(path(table, rest), json={field: "x" * (limit + 1)})
    assert refused.status_code == 422
    assert refused.json() == {"error": message, "hint": "Say it in fewer words, or in two."}
    assert dm.sent == [] and dm.side_prompts == []


def test_an_act_at_its_length_fits(table, dm):
    _, ana = table["Ana"]
    paragraphs = "\n\n".join(["I creep to the door and listen. " * 40] * 3)[:ACT_CHARS]
    assert ana.post(path(table, "act"), json={"text": f"  {paragraphs}  "}).status_code == 202, "trimmed first"


def test_asking_too_often_waits_and_says_how_long(table, dm, ticks):
    _, ana = table["Ana"]
    for _ in range(SeatThrottle.LIMITS["ask"][0]):
        assert ana.post(path(table, "ask"), json={"question": "Can I climb it?"}).status_code == 200
    asked = len(dm.side_prompts)
    refused = ana.post(path(table, "ask"), json={"question": "Can I climb it?"})
    assert refused.status_code == 429
    assert refused.json()["error"] == "You're asking the DM fast: ask again in 300 seconds."
    assert refused.headers["Retry-After"] == "300"
    assert len(dm.side_prompts) == asked, "the DM is never asked"

    _, bo = table["Bo"]
    assert bo.post(path(table, "ask"), json={"question": "And I?"}).status_code == 200, "per seat"
    ticks.now += SeatThrottle.LIMITS["ask"][1]
    assert ana.post(path(table, "ask"), json={"question": "Now?"}).status_code == 200, "the window slides"


def test_talking_too_often_waits(table, ticks):
    _, cy = table["Cy"]
    count, window = SeatThrottle.LIMITS["talk"]
    for n in range(count):
        ticks.now += 1
        assert cy.post(path(table, "talk"), json={"text": f"Line {n}"}).status_code == 201
    refused = cy.post(path(table, "talk"), json={"text": "One more"})
    assert refused.status_code == 429 and refused.json()["error"].startswith("You're talking fast")
    assert int(refused.headers["Retry-After"]) == window - count + 1, "until the oldest line leaves the window"
    ticks.now += int(refused.headers["Retry-After"])
    assert cy.post(path(table, "talk"), json={"text": "One more"}).status_code == 201


def test_a_refused_line_isnt_counted(table, ticks):
    _, cy = table["Cy"]
    for _ in range(SeatThrottle.LIMITS["talk"][0] * 2):
        assert cy.post(path(table, "talk"), json={"text": "x" * (TALK_CHARS + 1)}).status_code == 422
    assert cy.post(path(table, "talk"), json={"text": "Hello"}).status_code == 201


def test_acting_too_often_waits(table, dm, ticks):
    """An act can be changed while its beat is open, and each change may be translated: a loop of them is held too."""
    _, ana = table["Ana"]
    for _ in range(SeatThrottle.LIMITS["act"][0]):
        assert ana.post(path(table, "act"), json={"text": "I listen."}).status_code in (202, 409), "409: the DM answers"
    refused = ana.post(path(table, "act"), json={"text": "I listen."})
    assert refused.status_code == 429 and refused.json()["error"].startswith("You're acting fast")
