"""A table of three end to end (plan 4 Task 10): `delve serve` with the fake `claude` on `PATH`, and three people, each
with their own client and their own event stream: the host (the owner, on this machine), Ana, who plays in Dutch, and
Cy, who watches.

The host invites, Ana and Cy join by the link, and Ana claims Pippa. Both the host and Ana act, and the beat closes on
the second act: the DM gets both, Ana's in English. The fake DM tells Pippa a planted secret, which only Ana's stream
gets, and Ana's stream gets the reply in Dutch. Table talk reaches all three, and Cy's act is refused. Then, with a
30 s beat timer and the table's clock moved through `DELVE_CLOCK_FILE`, the host alone acts, the timer runs out, and
Pippa holds back.

The real `claude` never runs: translations are the fake's side answers, by their prompt.
"""

from __future__ import annotations

import json
import threading
import time

import httpx
import pytest

from delve.modules.dscn import Bundle
from tests.e2e.test_play_with_fake_claude import CRYPT, GARREK, PIPPA, SECRET, Delve
from tests.web.conftest import PASSWORD

DUTCH_ACT = "Ik open de deur van de kapel."
ENGLISH_ACT = "I open the chapel door."
TOLD = f"{SECRET}: Pippa alone hears a voice behind the altar, calling her by name."
REPLY = "The door creaks open on a dusty nave.\n\nA cold draught comes from the east."
TURNS = [
    [
        {"tool": "session_primer", "args": {}},
        {"tool": "new_session", "args": {"title": "Into the crypt"}},
        {"tool": "create_character", "args": {"name": "Garrek", "sheet": GARREK}},
        {"tool": "create_character", "args": {"name": "Pippa", "sheet": PIPPA}},
        {"tool": "set_marching_order", "args": {"order": ["Garrek", "Pippa"]}},
        {"text": "Garrek the fighter and Pippa the thief stand at the chapel door."},
    ],
    [
        {"tool": "tell", "args": {"characters": ["Pippa"], "text": TOLD}},
        {"text": REPLY},
    ],
    [{"text": "Garrek keeps watch while Pippa stays where she is."}],
]


class Stream:
    """One client's event stream from the start (`since=0`), read in a thread: every frame, raw and parsed."""

    def __init__(self, http: httpx.Client, campaign: str | None = None) -> None:
        """`campaign`: the table an account listens at (players and tavern Task C3)."""
        self.raw: list[str] = []
        self._params = {"since": 0} if campaign is None else {"since": 0, "campaign": campaign}
        self.events: list[tuple[str, dict]] = []
        self._http = http
        self._open = threading.Event()
        threading.Thread(target=self._read, daemon=True).start()
        assert self._open.wait(10), "the event stream didn't open"

    def _read(self) -> None:
        kind = None
        try:
            with self._http.stream("GET", "/api/events", params=self._params, timeout=None) as response:
                assert response.status_code == 200
                self._open.set()
                for line in response.iter_lines():
                    self.raw.append(line)
                    if line.startswith("event: "):
                        kind = line[len("event: ") :]
                    elif line.startswith("data: ") and kind is not None:
                        self.events.append((kind, json.loads(line[len("data: ") :])))
        except httpx.HTTPError:
            return  # the server stopped

    def of(self, kind: str) -> list[dict]:
        return [data for k, data in list(self.events) if k == kind]

    def wait(self, test, what: str, timeout: float = 30) -> dict:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for kind, data in list(self.events):
                if test(kind, data):
                    return data
            time.sleep(0.05)
        raise AssertionError(f"no {what} in the stream")

    def text(self) -> str:
        return "\n".join(self.raw)


def ok(response: httpx.Response, status: int = 200):
    assert response.status_code == status, response.text
    return response.json() if response.content else None


def beat_of(http: httpx.Client, campaign: str) -> dict | None:
    return ok(http.get(f"/api/campaigns/{campaign}/play/state"))["beat"]


def until_done(http: httpx.Client, campaign: str, timeout: float = 60) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if beat_of(http, campaign) is None:
            return
        time.sleep(0.1)
    raise AssertionError("the beat didn't end")


def dm_inputs(delve: Delve) -> list[str]:
    return [line["text"] for line in delve.lines(delve.input_log) if not line["text"].startswith("Translate ")]


@pytest.fixture
def delve(tmp_path):
    server = Delve(tmp_path, turns=TURNS, side=(), translations={DUTCH_ACT: ENGLISH_ACT}, clock=True
    )
    yield server
    server.stop()


def test_a_table_of_three(delve):
    host = delve.http
    crypt = Bundle.load(CRYPT).to_zip()
    crypt = ok(host.post("/api/modules/import", content=crypt, headers={"Content-Type": "application/zip"}), 201)
    campaign = ok(host.post("/api/campaigns", json={"name": "Vellis", "module_id": crypt["id"]}), 201)["id"]
    play = f"/api/campaigns/{campaign}"

    # The host alone builds the party: solo play, one act closes the beat at once.
    ok(host.post(f"{play}/act", json={"text": "Make us a fighter and a thief."}), 202)
    until_done(host, campaign)
    pcs = {pc["name"]: pc["id"] for pc in ok(host.get(f"{play}/play/state"))["party"]}
    assert set(pcs) == {"Garrek", "Pippa"}

    # 1. The host invites; a Dutch player and an observer join with the link.
    token = ok(host.get(f"{play}/invite"))["join_token"]
    base = str(host.base_url)
    ana, cy = httpx.Client(base_url=base, timeout=30), httpx.Client(base_url=base, timeout=30)
    try:
        assert ok(ana.get(f"/api/join/{token}"))["campaign"]["name"] == "Vellis"
        ana_seat = ok(
            ana.post(
                f"/api/join/{token}/account",
                json={
                    "username": "ana",
                    "password": PASSWORD,
                    "display_name": "Ana",
                    "language": "nl",
                    "role": "player",
                },
            ),
            201,
        )
        cy_seat = ok(
            cy.post(
                f"/api/join/{token}/account",
                json={
                    "username": "cy.r",
                    "password": PASSWORD,
                    "display_name": "Cy",
                    "language": "en",
                    "role": "observer",
                },
            ),
            201,
        )
        assert ana_seat["campaign_id"] == campaign and "delve_session" in ana.cookies
        ana_id, cy_id = ana_seat["seat"]["id"], cy_seat["seat"]["id"]
        assert ok(ana.get(f"/api/me?campaign={campaign}"))["seat"]["language"] == "nl"

        streams = {"host": Stream(host), "ana": Stream(ana, campaign), "cy": Stream(cy, campaign)}
        host_id = next(s["id"] for s in ok(host.get(f"{play}/seats")) if s["role"] == "host")
        present = {s["id"]: s["present"] for s in ok(host.get(f"{play}/seats"))}
        assert present == {host_id: True, ana_id: True, cy_id: True}

        # 2. Ana claims Pippa. The host acts and the beat waits for Ana; Ana's act, in Dutch, closes it.
        ok(ana.post(f"{play}/characters/{pcs['Pippa']}/claim", json={}))
        opened = ok(host.post(f"{play}/act", json={"text": "Garrek keeps his shield up."}), 202)["beat"]
        assert opened["status"] == "open" and opened["submitted"] == [host_id]
        streams["ana"].wait(lambda k, d: k == "beat" and d["submitted"] == [host_id], "the host's submission")
        closed = ok(ana.post(f"{play}/act", json={"text": DUTCH_ACT}), 202)["beat"]
        assert closed["status"] == "running" and set(closed["submitted"]) == {host_id, ana_id}
        until_done(host, campaign)

        # The DM got both acts at once, Ana's in English, and nothing of Ana's Dutch.
        message = dm_inputs(delve)[-1]
        assert "Host (playing Garrek):\n> Garrek keeps his shield up." in message
        assert f"Ana (playing Pippa):\n> {ENGLISH_ACT}" in message
        assert DUTCH_ACT not in message

        # 3. The DM tells Pippa a secret: only Ana gets it, not the host, not Cy, not in a replay.
        streams["ana"].wait(lambda k, d: k == "story" and SECRET in json.dumps(d), "the told secret")
        ana_story = ok(ana.get(f"{play}/story", params={"limit": 200}))["entries"]
        assert any(e["kind"] == "dm_text" and e["payload"]["text"] == TOLD for e in ana_story)
        for who, client in (("host", host), ("cy", cy)):
            assert SECRET not in json.dumps(ok(client.get(f"{play}/story", params={"limit": 200}))), who
        assert SECRET not in streams["host"].text() and SECRET not in streams["cy"].text()
        replay = Stream(host)
        streams["host"].wait(lambda k, d: k == "beat" and d["status"] == "done", "the beat's end")
        time.sleep(0.5)
        assert SECRET not in replay.text()

        # 4. Ana reads the reply in Dutch, paragraph by paragraph; the others get no translation at all.
        dutch = "NL: The door creaks open on a dusty nave.\n\nNL: A cold draught comes from the east."
        streams["ana"].wait(
            lambda k, d: k == "translation" and d["status"] == "done" and d["text"] == dutch, "the Dutch reply"
        )
        assert all(t["language"] == "nl" for t in streams["ana"].of("translation"))
        assert not streams["host"].of("translation") and not streams["cy"].of("translation")
        read = ok(ana.get(f"{play}/story", params={"limit": 200, "language": "nl"}))["entries"]
        reply = next(e for e in read if e["kind"] == "dm_text" and e["payload"]["text"] == REPLY)
        assert reply["translation"] == {"language": "nl", "text": dutch, "status": "done"}

        # 5. Table talk, from the observer, reaches all three (and Ana in Dutch); it is never the DM's.
        said = ok(cy.post(f"{play}/talk", json={"text": "Mind the altar!"}), 201)["entry"]
        for who, stream in streams.items():
            stream.wait(lambda k, d: k == "story" and d.get("entry", {}).get("id") == said["id"], f"the talk for {who}")
        streams["ana"].wait(
            lambda k, d: k == "translation" and d["entry_id"] == said["id"] and d["text"] == "NL: Mind the altar!",
            "the talk in Dutch",
        )

        # 6. The observer's act is refused.
        refused = cy.post(f"{play}/act", json={"text": "I take the gold."})
        assert refused.status_code == 403 and refused.json() == {"error": "Observers don't act."}

        # 7. A 30 s beat timer: the host alone acts, the beat waits for Ana, the clock moves on, and Pippa holds back.
        assert ok(host.put(f"{play}/play/options", json={"beat_timer_s": 30}))["fallback"] == "hold_back"
        waiting = ok(host.post(f"{play}/act", json={"text": "Garrek keeps watch."}), 202)["beat"]
        assert waiting["status"] == "open" and waiting["deadline"]
        time.sleep(1)
        assert beat_of(host, campaign)["status"] == "open"
        delve.advance(31)
        until_done(host, campaign)
        message = dm_inputs(delve)[-1]
        assert "Host (playing Garrek):\n> Garrek keeps watch." in message
        assert "(Pippa holds back this beat: they do nothing.)" in message
        assert "Mind the altar" not in "\n".join(dm_inputs(delve))
    finally:
        ana.close()
        cy.close()
