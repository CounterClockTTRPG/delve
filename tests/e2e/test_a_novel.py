"""A campaign becomes a short story end to end (novelization plan Task 8): through the API of `delve serve`, with the
fake `claude` and the real bridge and tool host.

Two beats play two sessions of the crypt. The DM keeps a secret note in the first, and the host's second act, for
Pippa, is in secret. The owner then novelizes the campaign as a short story: the fake answers the outline and the three
chapters by their prompts (`novel_answer`, which the browser check's server answers with too). The chapter prompts
held the private act, the secret note and a room of the module the party never reached; the novel is done with its
three chapters, and an organiser seat's token gets 403 on the novel's routes.

The real `claude` never runs.
"""

from __future__ import annotations

import json
import time

import httpx
import pytest

from delve.modules.dscn import Bundle
from delve.novels.material import MODULE_HEADING
from tests.e2e.test_play_with_fake_claude import CRYPT, GARREK, PIPPA, Delve
from tests.web.conftest import PASSWORD

NOVEL_TITLE = "The Saint's Silver"
CHAPTERS = [
    ("The Stair Down", "Garrek and Pippa go down into the crypt, and the Prior's fear goes with them."),
    ("What Pippa Kept", "In the vestry Pippa pockets the silver chalice, and says nothing."),
    ("The Sealed Door", "They come up into the dawn; the throne chamber they never opened waits below."),
]
OUTLINE = json.dumps(
    {"title": NOVEL_TITLE, "chapters": [{"title": title, "summary": summary} for title, summary in CHAPTERS]}
)
CHAPTER_TEXTS = [
    (
        "The stair was older than the chapel above it, and every step of it was worn hollow by the dead.\n\n"
        "Garrek went first, his shield up. Pippa came after, counting the steps under her breath."
    ),
    (
        "The vestry smelled of wax and mice. The chalice was there, as the Prior had feared.\n\n"
        "Pippa's hand closed on it before she had decided anything at all."
    ),
    (
        "Dawn was grey over the chapel roof when they came up. Below them a sealed door kept its silence.\n\n"
        "Garrek never asked what Pippa carried. Some things a friend leaves in the dark."
    ),
]
OUTLINE_PROMPT = "First you plan it: its title and its chapters."
CHAPTER_PROMPT = "Now write chapter {n} of {count}"


def novel_answer(prompt: str) -> str | None:
    """The fake writer's answer to a novel's side call, by its prompt: the outline, or chapter n of three; None for any
    other prompt."""
    if OUTLINE_PROMPT in prompt:
        return OUTLINE
    for n, text in enumerate(CHAPTER_TEXTS, start=1):
        if CHAPTER_PROMPT.format(n=n, count=len(CHAPTER_TEXTS)) in prompt:
            return text
    return None


PROMPTS = [
    {"has": [OUTLINE_PROMPT], "answer": OUTLINE},
    *(
        {"has": [CHAPTER_PROMPT.format(n=n, count=len(CHAPTER_TEXTS))], "answer": text}
        for n, text in enumerate(CHAPTER_TEXTS, start=1)
    ),
]
NOTE = "The Prior hid the vestry key under the third pew."
PRIVATE_ACT = "Pippa quietly pockets the silver chalice."
UNREACHED = "Throne Chamber"
TURNS = [
    [
        {"tool": "new_session", "args": {"title": "Into the crypt"}},
        {"tool": "create_character", "args": {"name": "Garrek", "sheet": GARREK}},
        {"tool": "create_character", "args": {"name": "Pippa", "sheet": PIPPA}},
        {"tool": "dm_note", "args": {"text": NOTE, "tags": ["plot"], "related_to": "Prior Anselm"}},
        {"tool": "move_party", "args": {"to": "Entry Hall"}},
        {"text": "Garrek and Pippa go down the worn stairs into the Entry Hall."},
    ],
    [
        {"tool": "new_session", "args": {"title": "The vestry"}},
        {"text": "The vestry is cold. Nobody sees what Pippa does."},
    ],
]


@pytest.fixture
def delve(tmp_path):
    server = Delve(tmp_path, turns=TURNS, prompts=PROMPTS)
    yield server
    server.stop()


def ok(response: httpx.Response, status: int = 200) -> dict:
    assert response.status_code == status, response.text
    return response.json()


def test_a_campaign_becomes_a_short_story(delve):
    http = delve.http
    crypt = ok(
        http.post(
            "/api/modules/import", content=Bundle.load(CRYPT).to_zip(), headers={"Content-Type": "application/zip"}
        ),
        201,
    )
    campaign = ok(http.post("/api/campaigns", json={"name": "Vellis", "module_id": crypt["id"]}), 201)["id"]
    play = f"/api/campaigns/{campaign}"

    # Two sessions: the party and the DM's secret note in the first; the host's act in secret opens the second beat.
    ok(http.post(f"{play}/act", json={"text": "Make us a fighter and a thief."}), 202)
    delve.settle(campaign)
    ok(http.post(f"{play}/act", json={"text": PRIVATE_ACT, "private": True}), 202)
    state = delve.settle(campaign)
    assert state["session_number"] == 2

    # The owner novelizes it as a short story; the fake writes the outline and three chapters.
    body = {"source": "campaign", "id": campaign, "length": "short-story", "tone": "classic", "language": "en"}
    novel = ok(http.post("/api/novels", json=body), 202)
    assert novel["status"] == "writing" and novel["campaign_id"] == campaign
    deadline = time.monotonic() + 60
    while (novel := ok(http.get(f"/api/novels/{novel['id']}")))["status"] == "writing":
        assert time.monotonic() < deadline, "the novel wasn't written"
        time.sleep(0.2)
    assert novel["status"] == "done", novel.get("error")
    assert novel["title"] == NOVEL_TITLE
    assert [(c["title"], c["text"]) for c in novel["chapters"]] == [
        (title, text) for (title, _), text in zip(CHAPTERS, CHAPTER_TEXTS, strict=True)
    ]
    [listed] = ok(http.get("/api/novels", params={"campaign_id": campaign}))
    assert listed["id"] == novel["id"] and "text" not in json.dumps(listed["chapters"])

    # The writer read the whole record: the act in secret, the secret note, and the room nobody reached.
    prompts = [line["text"] for line in delve.lines(delve.input_log)]
    chapters = [p for p in prompts if "Now write chapter" in p]
    assert len(chapters) == 3 and sum(OUTLINE_PROMPT in p for p in prompts) == 1
    for prompt in chapters:
        assert f"Host (in secret): {PRIVATE_ACT}" in prompt  # the host plays the PCs nobody claimed
        assert NOTE in prompt
        module = prompt[prompt.index(MODULE_HEADING) :]
        assert UNREACHED in module
    # The DM never heard the novel, and nothing of it went to the table's story.
    story = json.dumps(ok(http.get(f"{play}/story", params={"limit": 200})))
    assert CHAPTER_TEXTS[0] not in story

    # An organiser account: the owner invites, a player joins and is made an organiser on the Players page; it gets 403
    # on every novel route.
    token = ok(http.get(f"{play}/invite"))["join_token"]
    with httpx.Client(base_url=str(http.base_url), timeout=30) as ana:
        seat = ok(
            ana.post(
                f"/api/join/{token}/account",
                json={
                    "username": "ana",
                    "password": PASSWORD,
                    "display_name": "Ana",
                    "language": "en",
                    "role": "player",
                },
            ),
            201,
        )
        ok(http.put(f"/api/accounts/{seat['account']['id']}", json={"organiser": True}))
        assert ana.get("/api/preferences").status_code == 200, "the account is an organiser"
        refused = [
            ana.get("/api/novels", params={"campaign_id": campaign}),
            ana.get(f"/api/novels/{novel['id']}"),
            ana.post("/api/novels", json=body),
            ana.patch(f"/api/novels/{novel['id']}", json={"title": "Mine"}),
            ana.post(f"/api/novels/{novel['id']}/continue", json={}),
            ana.post(f"/api/novels/{novel['id']}/cancel", json={}),
            ana.delete(f"/api/novels/{novel['id']}", headers={"Content-Type": "application/json"}),
        ]
        assert [answer.status_code for answer in refused] == [403] * len(refused)
        for answer in refused:
            assert CHAPTER_TEXTS[0] not in answer.text and NOVEL_TITLE not in answer.text
    assert ok(http.get(f"/api/novels/{novel['id']}"))["title"] == NOVEL_TITLE
