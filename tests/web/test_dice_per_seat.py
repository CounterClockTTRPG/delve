"""The dice in the story, per seat (DEL-270): each tool row shows the dice its call rolled, filtered on the server for
the seat that reads it, in its story pages and in the live `story` events alike.

The DM plays one beat through the app's own tool host (`HostedDM`): it sets up a fight with a goblin whose hit points
are rolled, the goblin attacks Garrek, Garrek attacks it, Pippa makes a secret Move Silently, and a batch makes a
Strength check for Garrek, a wandering-encounter check (a DM-only tool) and the goblin's saving throw. The host reads
every roll. The players, the co-host and the observer read the party's own: never the goblin's hit points, its
attack or its save (behind the screen), the secret check or the encounter check. With the table's `enemy_dice` at
`open`, the goblin's attack and save show to every seat; its hit points and the secret check still don't.
"""

import asyncio
import itertools
import json

import pytest
from fastapi.testclient import TestClient

from delve.dice import SeededRng
from delve.dm.fake import FAKE_DM_CAPABILITIES, FakeConversation, FakeDM
from delve.dm.provider import TextDelta, ToolCall, ToolResult
from delve.dm.tools import ToolHost
from delve.domain.backends import Registry
from delve.play import seats
from delve.web.seats import SEAT_COOKIE, new_seat_token, token_hash
from tests.dm.tools.conftest import GARREK, PIPPA
from tests.fixtures.rulesets import osric_catalogs
from tests.web.conftest import BASE_URL, make_registries, playing
from tests.web.test_campaigns_api import campaign, crypt_module
from tests.web.test_fourth_wall_per_seat import act_and_wait, read_until

OTHERS = ("Ana", "Bo", "Dee", "Cy")
"""Ana plays Garrek, Bo plays Pippa, Dee is a co-host and Cy observes."""


class HostedConversation(FakeConversation):
    """A scripted reply whose tool calls run through the app's tool host in the running beat, as the bridge's do."""

    def __init__(self, dm, id: str, campaign_id: str) -> None:
        super().__init__(dm, id)
        self.campaign_id = campaign_id

    async def send(self, text):
        async for event in super().send(text):
            yield event
            if isinstance(event, ToolCall):
                beat = self._dm.app.state.storage.beats.current(self.campaign_id)
                host = self._dm.app.state.tool_host
                answer = await asyncio.to_thread(host.call, self.campaign_id, beat.id, event.name, event.args)
                yield ToolResult(event.id, "error" not in answer, json.dumps(answer))


class HostedDM(FakeDM):
    app = None

    def then(self, *events) -> None:
        self._script.append(list(events))

    async def open(self, spec):
        self._opened += 1
        return HostedConversation(self, f"fake-{self._opened}", spec.campaign_id)


@pytest.fixture
def dm():
    return HostedDM([])


@pytest.fixture
def registries(dm):
    registries = make_registries()
    registries.dm = Registry()
    registries.dm.register(FAKE_DM_CAPABILITIES, lambda: dm)
    return registries


@pytest.fixture
def table(app, local, storage, dm):
    """The crypt with Garrek and Pippa in its entry hall; the owner hosts, each other seat has its own browser."""
    seeds = itertools.count(1)
    app.state.tool_host = ToolHost(storage, lambda: SeededRng(next(seeds)), catalogs=osric_catalogs())
    dm.app = app
    cid = campaign(local, crypt_module(local)["id"])["id"]
    playing(storage, cid)
    host = app.state.tool_host
    garrek = host.call(cid, "setup", "create_character", {"name": "Garrek", "sheet": GARREK})["id"]
    pippa = host.call(cid, "setup", "create_character", {"name": "Pippa", "sheet": PIPPA})["id"]
    assert "error" not in host.call(cid, "setup", "move_party", {"to": "Entry Hall"})
    clients, people = [], {}
    for name, role, pc in (("Ana", "player", garrek), ("Bo", "player", pippa), ("Dee", "cohost", None), ("Cy", "observer", None)):
        token = new_seat_token()
        seat = storage.seats.create(cid, name, "en", role, token_hash=token_hash(token))
        if pc is not None:
            seats.claim(storage, pc, seat)
        client = TestClient(app, base_url=BASE_URL)
        client.__enter__()
        client.cookies.set(SEAT_COOKIE, token)
        clients.append(client)
        people[name] = (client, token)
    yield {"campaign": cid, "garrek": garrek, "pippa": pippa, **people}
    for client in clients:
        client.__exit__(None, None, None)


GOBLIN = {"enemies": [{"name": "goblin", "count": 1}]}
STEPS = [
    {"tool": "ability_check", "args": {"character": "Garrek", "ability": "str", "occasion": "the door"}},
    {"tool": "encounter_check", "args": {"terrain": "dungeon", "dungeon_level": 1}},
    {"tool": "saving_throw", "args": {"character": "Goblin", "save_type": "para"}},
]


def play_the_fight(app, local, dm, cid) -> int:
    dm.then(
        TextDelta("A goblin leaps from the dark."),
        ToolCall("c1", "setup_combat", GOBLIN),
        ToolCall("c2", "resolve_attack", {"attacker": "Goblin", "target": "Garrek"}),
        ToolCall("c3", "resolve_attack", {"attacker": "Garrek", "target": "Goblin"}),
        ToolCall("c4", "skill_check", {"character": "Pippa", "skill": "move silently", "secret": True}),
        ToolCall("c5", "batch", {"steps": STEPS}),
        TextDelta("Steel rings."),
    )
    return act_and_wait(app, local, cid)


def dice_of(entries) -> list[dict]:
    """Every dice line of the tool rows, the batches' steps' included, each with the row's or step's tool."""
    lines = []
    for entry in entries:
        if entry["kind"] != "tool":
            continue
        for line in entry["payload"].get("dice", []):
            lines.append({**line, "tool": entry["payload"]["name"]})
        for step in entry["payload"].get("steps", []):
            lines += [{**line, "tool": step["name"]} for line in step.get("dice", [])]
    return lines


def page(client, cid) -> list[dict]:
    response = client.get(f"/api/campaigns/{cid}/story")
    assert response.status_code == 200
    return response.json()["entries"]


def streamed(app, cid, last, cookie) -> list[dict]:
    """The `story` entries the event stream's replay sends this seat."""
    frames = asyncio.run(read_until(app, "/api/events?since=0", last, cookie))
    entries = []
    for frame in frames:
        if "event: story\n" not in frame:
            continue
        data = next(line[len("data: ") :] for line in frame.split("\n") if line.startswith("data: "))
        entries.append(json.loads(data)["entry"])
    return entries


def who(lines) -> set[tuple]:
    return {(line["who"], line["side"], line["what"], line["tool"]) for line in lines}


def test_each_seat_reads_the_dice_it_may(app, local, dm, storage, table):
    cid = table["campaign"]
    storage.campaigns.set_initiative(cid, "combatant")  # each combatant's own initiative die, to be read
    last = play_the_fight(app, local, dm, cid)

    host_lines = dice_of(page(local, cid))
    seen = who(host_lines)
    assert ("Goblin", None, "hp", "setup_combat") in seen, "a monster's hit points are the host's to read"
    assert ("Goblin", None, "attack", "resolve_attack") in seen and ("Garrek", None, "attack", "resolve_attack") in seen
    assert ("Pippa", None, "skill", "skill_check") in seen, "the secret check is the host's to read"
    assert ("Goblin", None, "save", "saving_throw") in seen and ("Garrek", None, "ability", "ability_check") in seen
    assert ("Garrek", None, "initiative", "setup_combat") in seen and ("Goblin", None, "initiative", "setup_combat") in seen
    assert dice_of(streamed(app, cid, last, None)) == host_lines, "the host's live events are its pages"
    # Never a modifier, a target number or an id: the dice, the faces and their total.
    assert all(set(line) == {"who", "side", "what", "detail", "dice", "faces", "total", "tool"} for line in host_lines)
    assert "roll_" not in json.dumps(page(local, cid))

    for name in OTHERS:
        client, cookie = table[name]
        for lines in (dice_of(page(client, cid)), dice_of(streamed(app, cid, last, cookie))):
            seen = who(lines)
            assert seen, name
            assert all(line["who"] in ("Garrek", "Pippa") or line["side"] == "party" for line in lines), (name, seen)
            assert not any(line["what"] in ("hp", "encounter") for line in lines), name
            assert ("Pippa", None, "skill", "skill_check") not in seen, f"{name} reads the secret check"
            assert ("Garrek", None, "attack", "resolve_attack") in seen, name
            assert ("Garrek", None, "ability", "ability_check") in seen, f"{name}: a batch step's own dice"
        assert "roll_" not in json.dumps(page(client, cid)), name


def test_a_player_sees_only_the_rows_and_steps_with_dice_for_them(app, local, dm, storage, table):
    """A player or observer sees no tool rows but those whose dice it reads, and of a batch only those steps; the
    co-host sees every row as before, the dice filtered."""
    cid = table["campaign"]
    play_the_fight(app, local, dm, cid)
    ana = [e for e in page(table["Ana"][0], cid) if e["kind"] == "tool"]
    assert all(e["payload"].get("dice") or e["payload"].get("steps") for e in ana)
    (batch,) = [e for e in ana if e["payload"]["name"] == "batch"]
    assert [s["name"] for s in batch["payload"]["steps"]] == ["ability_check"]
    assert "skill_check" not in [e["payload"]["name"] for e in ana], "a secret check's row has nothing for her"
    dee = [e["payload"]["name"] for e in page(table["Dee"][0], cid) if e["kind"] == "tool"]
    assert dee == ["setup_combat", "resolve_attack", "resolve_attack", "skill_check", "batch"]


def test_with_the_enemies_dice_in_the_open(app, local, dm, storage, table):
    cid = table["campaign"]
    changed = local.put(f"/api/campaigns/{cid}/play/options", json={"enemy_dice": "open"})
    assert changed.status_code == 200 and changed.json()["enemy_dice"] == "open"
    last = play_the_fight(app, local, dm, cid)
    for name in OTHERS:
        client, cookie = table[name]
        for lines in (dice_of(page(client, cid)), dice_of(streamed(app, cid, last, cookie))):
            seen = who(lines)
            assert ("Goblin", None, "attack", "resolve_attack") in seen, name
            assert ("Goblin", None, "save", "saving_throw") in seen, name
            assert not any(line["what"] in ("hp", "encounter") for line in lines), name
            assert ("Pippa", None, "skill", "skill_check") not in seen, name

    # Back behind the screen: the pages show the goblin's dice no more.
    assert local.put(f"/api/campaigns/{cid}/play/options", json={"enemy_dice": "screen"}).status_code == 200
    assert ("Goblin", None, "attack", "resolve_attack") not in who(dice_of(page(table["Ana"][0], cid)))


def test_the_option_is_the_hosts_and_every_seat_reads_its_story_again(app, local, storage, table):
    cid = table["campaign"]
    path = f"/api/campaigns/{cid}/play/options"
    assert local.get(path).json()["enemy_dice"] == "screen"
    for name in ("Ana", "Dee"):
        assert table[name][0].put(path, json={"enemy_dice": "open"}).status_code == 403, name
    assert local.put(path, json={"enemy_dice": "everyone"}).status_code == 422
    since = app.state.events.publish("beat", {"campaign_id": cid}, scope="table", campaign_id=cid)
    assert local.put(path, json={"enemy_dice": "open"}).status_code == 200
    told = [e for e in app.state.events._buffer if e.seq > since and e.type == "play_options"]
    assert [e.data for e in told] == [{"campaign_id": cid, "story": True}]


def test_with_the_dice_hidden_the_players_read_the_story_in_words(app, local, dm, storage, table):
    """DEL-280: the host turns the dice off; no other seat reads a roll, the host every one, and every seat reads its
    story again. Only the host may."""
    cid = table["campaign"]
    path = f"/api/campaigns/{cid}/play/options"
    assert local.get(path).json()["show_dice"] is True
    assert table["Dee"][0].put(path, json={"show_dice": False}).status_code == 403
    assert local.put(path, json={"show_dice": "no"}).status_code == 422
    since = app.state.events.publish("beat", {"campaign_id": cid}, scope="table", campaign_id=cid)
    assert local.put(path, json={"show_dice": False}).json()["show_dice"] is False
    told = [e for e in app.state.events._buffer if e.seq > since and e.type == "play_options"]
    assert [e.data for e in told] == [{"campaign_id": cid, "story": True}]
    last = play_the_fight(app, local, dm, cid)
    for name in OTHERS:
        client, cookie = table[name]
        assert dice_of(page(client, cid)) == [] and dice_of(streamed(app, cid, last, cookie)) == [], name
    assert dice_of(page(local, cid)), "the host still reads them"


def test_rows_from_before_show_no_dice(app, local, storage, table):
    """A row stored before DEL-270 has no rolls: it shows as it did, to the host and the co-host, and to no player."""
    cid = table["campaign"]
    storage.story.append(cid, None, "tool", {"name": "roll", "call_id": "toolu_old"})
    storage.story.append(cid, None, "tool", {"name": "roll", "rolls": ["roll_gone00000000"]})
    rows = [e["payload"] for e in page(local, cid) if e["kind"] == "tool"]
    assert rows == [{"name": "roll"}, {"name": "roll"}], "an id whose roll is gone shows nothing"
    assert [e["kind"] for e in page(table["Dee"][0], cid)] == ["tool", "tool"]
    assert [e["kind"] for e in page(table["Ana"][0], cid)] == []
