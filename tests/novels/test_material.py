"""What a novel's writer reads (novelization Task 3): a campaign's record and its module, or a module alone, and the
condensing of a campaign too long for one prompt."""

import asyncio
import hashlib
import sqlite3

import pytest

from delve.config import Config
from delve.domain.characters import CharacterState, Sheet
from delve.domain.modules import ModuleMap
from delve.modules.source import ModuleSource, TextDoc, save_source
from delve.novels.material import (
    MAX_PROMPT_CHARS,
    Material,
    Part,
    SessionRangeError,
    campaign_material,
    condense,
    module_material,
    render,
)
from delve.play.audience import for_characters, for_seats
from delve.storage import open_storage

CRYPT_TEXT = """# The Crypt of Saint Vellis

## 1. The Stair {#r1}

> Cold air rises from the dark below.

A stair of worn stone goes down.

## 2. The Ossuary {#r2}

Bones line the walls. Behind the third niche lies the saint's silver ring.
"""


@pytest.fixture
def storage(tmp_path):
    opened = open_storage(Config(data_dir=tmp_path / "data"))
    yield opened
    opened.close()


def crypt_module(storage):
    module = storage.modules.create("The Crypt of Saint Vellis")
    storage.modules.put_map(module.id, ModuleMap("crypt", "map", "map crypt {}\n", is_default=True))
    entities = {
        "npcs": [{"id": "brother-oswin", "name": "Brother Oswin", "role": "the crypt's keeper"}],
        "encounters": [{"id": "ghouls", "name": "Ghouls in the ossuary", "key": "key:2"}],
        "factions": [{"id": "order", "name": "The Order of the Lamp", "goals": "keep the dead asleep"}],
        "pregens": [
            {"id": "tenser", "name": "Tenser", "class": "mage", "level": 3},
            {"id": "robilar", "name": "Robilar", "class": "fighter", "level": 3},
        ],
    }
    texts = [TextDoc("crypt", "The Crypt", "gm", None, CRYPT_TEXT)]
    save_source(storage, module.id, ModuleSource(texts=texts, entities=entities))
    return module, storage.revisions.snapshot(module.id)


@pytest.fixture
def played(storage):
    """A campaign of the crypt with two sessions: Aldric fell in session 2, Mira lives."""
    module, revision = crypt_module(storage)
    campaign = storage.campaigns.create("Tuesday", module.id, revision.number, ruleset="osric", setting="greyhawk")
    host = storage.seats.create(campaign.id, "Raf", "en", "host", owner=True)
    aldric = storage.characters.create(
        campaign.id,
        "Aldric",
        sheet=Sheet(race="human", cls="Fighter", levels={"fighter": 3}),
        state=CharacterState(hp=-10, conditions=("downed",)),
    )
    mira = storage.characters.create(
        campaign.id, "Mira", sheet=Sheet(race="elf", cls="Thief", levels={"thief": 2}), state=CharacterState(hp=7)
    )
    storage.characters.create(campaign.id, "Brother Oswin", kind="npc", sheet=Sheet(kind="npc", background="keeper"))
    story = storage.story
    story.append(campaign.id, None, "dm_text", {"text": "Before anything, the bell tolled."})
    storage.sessions.start(campaign.id, 1, "Down the stair")
    story.append(
        campaign.id, None, "player_act", {"seat_id": host.id, "character_ids": [aldric.id], "text": "I go down."}
    )
    story.append(campaign.id, None, "dm_text", {"text": "The stair is cold."})
    story.append(
        campaign.id,
        None,
        "player_act",
        {"seat_id": host.id, "character_ids": [mira.id], "text": "I pocket the coin.", "private": True},
        for_seats([host.id]),
    )
    story.append(campaign.id, None, "tool", {"name": "roll_dice", "summary": "TOOL-ROW-XYZ"})
    story.append(campaign.id, None, "dm_error", {"message": "The DM didn't answer: DM-ERROR-XYZ"})
    story.append(
        campaign.id,
        None,
        "dm_text",
        {"text": "You hear a whisper.", "told_to": [mira.id]},
        for_characters([mira.id]),
    )
    storage.sessions.end(campaign.id, 1, "They went down the stair.")
    storage.sessions.start(campaign.id, 2, "The ossuary")
    storage.events.append(campaign.id, "damage", {"character_id": aldric.id, "hp_after": -10}, session=2, beat="b2")
    story.append(campaign.id, None, "dm_text", {"text": "Aldric falls to the ghouls."})
    storage.notes.create(campaign.id, "secret", "The keeper is a ghoul himself.")
    storage.notes.create(campaign.id, "room", "The niche is empty now.", map_name="crypt", node="r2")
    storage.notes.create(campaign.id, "log", "LOG-NOTE-XYZ")
    return campaign


def headings(material: Material) -> list[str]:
    return [part.heading for part in material.parts]


def test_a_campaign_s_parts_come_in_order(storage, played):
    material = campaign_material(storage, played.id, None)

    assert material.title == "Tuesday"
    assert material.kind == "campaign"
    assert material.party == ["Aldric", "Mira"]
    assert headings(material) == [
        "The characters",
        "Session 1: Down the stair",
        "Session 2: The ossuary",
        "The NPCs met",
        "The DM's secrets and notes",
        "The module: what was there, played or not",
    ]
    assert [part.session for part in material.parts] == [None, 1, 2, None, None, None]


def test_the_characters_have_their_fates(storage, played):
    characters = campaign_material(storage, played.id, None).parts[0].text

    assert "Aldric" in characters and "dead (in session 2)" in characters
    assert "Mira" in characters and "alive" in characters


def test_a_session_has_its_recap_and_its_story_every_audience_marked(storage, played):
    session = campaign_material(storage, played.id, None).parts[1].text

    assert "They went down the stair." in session
    assert "Before anything, the bell tolled." in session  # story before session 1 counts in session 1
    assert "Aldric: I go down." in session
    assert "Mira (in secret): I pocket the coin." in session
    assert "(told only to Mira)" in session and "You hear a whisper." in session
    assert session.index("I go down.") < session.index("The stair is cold.") < session.index("I pocket the coin.")
    assert "TOOL-ROW-XYZ" not in session and "DM-ERROR-XYZ" not in session
    assert "Aldric falls" not in session


def test_the_secrets_and_room_notes_are_there_and_the_log_lines_aren_t(storage, played):
    notes = campaign_material(storage, played.id, None).parts[4].text

    assert "The keeper is a ghoul himself." in notes
    assert "The niche is empty now." in notes
    assert "LOG-NOTE-XYZ" not in notes


def test_the_module_s_unreached_room_is_under_its_heading(storage, played):
    module = campaign_material(storage, played.id, None).parts[-1]

    assert module.heading == "The module: what was there, played or not"
    assert "The Ossuary" in module.text and "the saint's silver ring" in module.text


def test_a_module_gives_its_texts_key_entities_and_pregens(storage):
    module, revision = crypt_module(storage)
    material = module_material(storage, module.id, revision.number)

    assert material.title == "The Crypt of Saint Vellis"
    assert material.kind == "module"
    assert material.party == ["Tenser", "Robilar"]
    text = render(material)
    assert "(read aloud) Cold air rises from the dark below." in text
    assert "The Ossuary" in text
    for name in ("Brother Oswin", "Ghouls in the ossuary", "The Order of the Lamp", "Tenser"):
        assert name in text
    assert "{#r2}" not in text
    assert [p.heading for p in material.parts if p.summarise] == ["The Crypt"]  # condense's second choice: the texts


def test_a_module_novel_keeps_reading_its_revision(storage):
    module, revision = crypt_module(storage)
    save_source(storage, module.id, ModuleSource(texts=[TextDoc("crypt", "The Crypt", "gm", None, "# Rewritten\n")]))
    storage.revisions.snapshot(module.id)

    assert "The Ossuary" in render(module_material(storage, module.id, revision.number))


def test_render_writes_the_title_the_party_and_the_parts(storage):
    material = Material("T", "module", ["A", "B"], [Part("One", "first", None), Part("Two", "second", 2)])

    text = render(material)

    assert text.index("T") < text.index("A, B") < text.index("One") < text.index("first") < text.index("Two")


@pytest.mark.parametrize(
    ("sessions", "hint"),
    [((3, 2), "reversed"), ((0, 2), "1"), ((1, 5), "2 sessions"), ((3, 3), "2 sessions")],
)
def test_a_bad_range_is_refused_with_a_hint(storage, played, sessions, hint):
    with pytest.raises(SessionRangeError) as refused:
        campaign_material(storage, played.id, sessions)

    assert hint in refused.value.hint


def test_a_range_gives_only_its_sessions(storage, played):
    material = campaign_material(storage, played.id, (2, 2))

    assert [p.session for p in material.parts if p.session is not None] == [2]
    assert "Before anything" not in render(material)


def test_a_fate_after_the_range_isn_t_told(storage, played):
    characters = campaign_material(storage, played.id, (1, 1)).parts[0].text

    assert "dead" not in characters
    assert "alive at the end of session 1" in characters


def test_a_campaign_without_sessions_has_its_story_as_session_1(storage):
    module, revision = crypt_module(storage)
    campaign = storage.campaigns.create("Fresh", module.id, revision.number, ruleset="osric", setting="greyhawk")
    storage.story.append(campaign.id, None, "dm_text", {"text": "The bell tolled."})

    material = campaign_material(storage, campaign.id, None)

    assert [p.session for p in material.parts if p.session is not None] == [1]
    with pytest.raises(SessionRangeError):
        campaign_material(storage, campaign.id, (1, 1))


def test_an_unknown_campaign_or_module_is_a_key_error(storage):
    with pytest.raises(KeyError):
        campaign_material(storage, "cmp_nope", None)
    with pytest.raises(KeyError):
        module_material(storage, "mod_nope", 1)


class Recorder:
    def __init__(self):
        self.prompts: list[str] = []

    async def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return f"SUMMARY {len(self.prompts)}"


def long_campaign(sessions: int, chars_each: int) -> Material:
    paragraph = "The party walked on through the dark, and the torches guttered. " * 20
    text = "\n\n".join([paragraph] * (chars_each // len(paragraph) + 1))
    parts = [Part("The characters", "Aldric: alive", None)]
    parts += [Part(f"Session {n}: on", text, n) for n in range(1, sessions + 1)]
    parts += [Part("The module: what was there, played or not", "## 2. The Ossuary\n\nBones.", None)]
    return Material("Long", "campaign", ["Aldric"], parts)


def test_material_that_fits_isn_t_condensed():
    complete = Recorder()
    material = long_campaign(2, 1000)

    assert asyncio.run(condense(material, complete)) == material
    assert complete.prompts == []


def test_an_over_long_campaign_is_condensed_one_call_per_session():
    complete = Recorder()
    material = long_campaign(400, 7_500)  # 3 MB of narration
    assert len(render(material)) > 3_000_000
    seen: list[tuple[str, int, int]] = []

    condensed = asyncio.run(condense(material, complete, lambda step, done, total: seen.append((step, done, total))))

    assert len(complete.prompts) == 400
    assert max(len(p) for p in complete.prompts) <= MAX_PROMPT_CHARS
    assert len(render(condensed)) <= MAX_PROMPT_CHARS
    assert [p.session for p in condensed.parts] == [p.session for p in material.parts]
    assert condensed.parts[0] == material.parts[0] and condensed.parts[-1] == material.parts[-1]
    assert all(p.text.startswith("SUMMARY") for p in condensed.parts[1:-1])
    assert all("names" in p and "deaths" in p and "secrets" in p for p in complete.prompts[:1])
    assert seen[-1] == ("condensing", 400, 400)


def test_a_session_longer_than_a_prompt_is_condensed_in_pieces():
    complete = Recorder()
    material = long_campaign(1, MAX_PROMPT_CHARS * 2)

    condensed = asyncio.run(condense(material, complete))

    assert len(complete.prompts) >= 3
    assert max(len(p) for p in complete.prompts) <= MAX_PROMPT_CHARS
    assert len(render(condensed)) <= MAX_PROMPT_CHARS


def test_an_over_long_module_is_condensed_text_by_text():
    complete = Recorder()
    big = "Rooms upon rooms. " * 20_000
    parts = [Part(f"Level {n}", big, None, summarise=True) for n in range(1, 4)] + [
        Part("The NPCs", "Brother Oswin", None)
    ]
    material = Material("Big", "module", [], parts)

    condensed = asyncio.run(condense(material, complete))

    assert len(complete.prompts) == 3
    assert condensed.parts[-1].text == "Brother Oswin"
    assert len(render(condensed)) <= MAX_PROMPT_CHARS


def checksums(path) -> dict[str, tuple[int, str]]:
    connection = sqlite3.connect(path)
    try:
        tables = [r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
        out = {}
        for table in tables:
            rows = sorted(repr(row) for row in connection.execute(f'SELECT * FROM "{table}"'))
            out[table] = (len(rows), hashlib.sha256("\n".join(rows).encode()).hexdigest())
        return out
    finally:
        connection.close()


def test_reading_writes_nothing(storage, played, tmp_path):
    before = checksums(tmp_path / "data" / "delve.db")

    material = campaign_material(storage, played.id, None)
    module_material(storage, played.module_id, played.revision)
    asyncio.run(condense(material, Recorder()))

    assert checksums(tmp_path / "data" / "delve.db") == before
