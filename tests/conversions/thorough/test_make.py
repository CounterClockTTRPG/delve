"""The module made from a thorough conversion's job folder (thorough conversion Task 7, Review Focus 1).

The folder is written by hand, as the stages leave it: two parts keyed 1, 2, 3 each (the house and the ship, as U1's
house and Sea Ghost), each with its own traced map whose rooms are `r1`, `r2`, `r3`. The making itself runs as the
pipeline's last stage, on a job started with a pipeline that only writes the folder and makes."""

import asyncio
import io
import json
from pathlib import Path

import pytest
from PIL import Image

from delve.config import Config
from delve.conversions import ConversionServices, runner, wait
from delve.conversions.thorough import pipeline, start_thorough
from delve.conversions.thorough.make import build_source
from delve.conversions.thorough.workspace import Workspace
from delve.dm.fake import FakeDM
from delve.domain.settings import BackendChoice
from delve.modules.dscn import sha256
from delve.modules.source import derive, load_source
from delve.storage import open_storage
from tests.fakes.fake_claude_agent import HOUSE, SHIP, markdown, traced
from tests.fixtures.pdfs import text_page, write_pdf
from tests.modules.test_cuts import BLUE, RED, colours, halves

PNG = b"\x89PNG\r\n\x1a\n" + b"picture"


def _parts() -> dict:
    return {
        "parts": [
            {"id": "intro", "title": "Introduction", "kind": "front", "audience": "player", "pages": [1, 1],
             "key_pattern": None, "map_pages": [], "maps": [], "order": 1},
            {"id": "ship", "title": "The Sea Ghost", "kind": "level", "audience": "gm", "pages": [3, 3],
             "key_pattern": "^\\d+$", "map_pages": [5],
             "maps": [{"name": "ship-main-deck", "title": "Main Deck", "page": 5, "level": "Main Deck"}], "order": 3},
            {"id": "house", "title": "The Haunted House", "kind": "level", "audience": "gm", "pages": [2, 2],
             "key_pattern": "^\\d+$", "map_pages": [4],
             "maps": [{"name": "house-ground-floor", "title": "Ground Floor", "page": 4, "level": "Ground Floor"}],
             "order": 2},
        ],
        "pictures": [6],
    }  # fmt: skip


def _folder(root: Path) -> Workspace:
    """A job folder as the stages before the making leave it."""
    ws = Workspace(root)
    root.mkdir(parents=True, exist_ok=True)
    ws.write_json("parts.json", _parts())
    (root / "clean").mkdir(exist_ok=True)
    (root / "clean" / "intro.md").write_text("# Introduction\n\nThe village of Saltmarsh lies on the coast.\n")
    (root / "clean" / "house.md").write_text(markdown(HOUSE))
    (root / "clean" / "ship.md").write_text(markdown(SHIP))
    (root / "joined").mkdir(exist_ok=True)
    (root / "joined" / "house-ground-floor.dmap").write_text(traced("Ground Floor", HOUSE))
    (root / "joined" / "ship-main-deck.dmap").write_text(traced("Main Deck", SHIP))
    (root / "art").mkdir(exist_ok=True)
    for name in ("p002-1.png", "p006-1.png", "p003-1.png", "p003-2.png"):
        (root / "art" / name).write_bytes(PNG + name.encode())
    ws.write_json(
        "art/descriptions.json",
        [
            {"file": "p006-1.png", "id": "region", "part": None, "key": None, "audience": "player",
             "description": "The coast around Saltmarsh. Show it when the party sets out."},
            {"file": "p003-1.png", "id": "r2-cabin", "part": "ship", "key": "2", "audience": "gm",
             "description": "The captain's cabin, charts on the table. Show it when the party enters room 2."},
        ],
    )  # fmt: skip
    ws.write_json(
        "entities.json",
        {
            "entities": {"npcs": [{"id": "captain", "name": "The Captain", "summary": "Smuggler, in his cabin."}]},
            "renamed": {"npc:the-captain": "npc:captain"},
            "origins": {"npc:captain": "ship"},
        },
    )
    ws.doubt("clean-1", [{"part": "house", "pages": [2], "kind": "missing-text", "text": "Room 3 is cut off."}])
    ws.doubt("join", [])
    return ws


def _links(source, maps) -> dict[tuple[str, str], tuple[str, str]]:
    """Each linked room `(map, room)` with the heading it links to, `(text, anchor)`."""
    return {
        (link.map, link.node.removeprefix("room.")): (link.text_id, link.anchor) for link in derive(source, maps).links
    }


def test_repeated_keys_link_within_their_part(tmp_path):
    source, maps, _, _ = build_source(_folder(tmp_path / "job"), "Saltmarsh")
    links = _links(source, maps)
    for room, key in (("r1", "1"), ("r2", "2"), ("r3", "3")):
        assert links[("house-ground-floor", room)] == ("house", key)
        assert links[("ship-main-deck", room)] == ("ship", key)
    explicit = {k["node"]: k for k in source.keys if k.get("node")}
    assert explicit["map:ship-main-deck#room.r2"]["text"] == "text:ship#2"
    assert explicit["map:house-ground-floor#room.r2"]["text"] == "text:house#2"
    assert explicit["map:ship-main-deck#room.r2"]["key"] != explicit["map:house-ground-floor#room.r2"]["key"]
    assert len({k["key"] for k in source.keys}) == len(source.keys)
    assert not [w for w in derive(source, maps).warnings if w.code in {"room-without-text", "key-without-room"}]


def test_a_room_on_a_part_with_a_sketch_links_by_its_sketched_name(tmp_path):
    ws = _folder(tmp_path / "job")
    (ws.root / "joined" / "ship-main-deck.dmap").unlink()
    parts = _parts()
    parts["parts"][1]["maps"] = []
    ws.write_json("parts.json", parts)
    (ws.root / "joined" / "ship.dmap").write_text(traced("Sketched", SHIP))  # a sketch's rooms are `r<key>` too
    ws.write_json("sketches.json", {"ship": {"part": "ship", "reason": "No map page was found in the book."}})
    source, maps, _, _ = build_source(ws, "Saltmarsh")
    assert {t.id: t.map for t in source.texts}["ship"] == "ship"
    assert _links(source, maps)[("ship", "r1")] == ("ship", "1")
    assert _links(source, maps)[("house-ground-floor", "r1")] == ("house", "1")


def test_traced_letter_keys_link_by_their_lower_case_name(tmp_path):
    ws = _folder(tmp_path / "job")
    (ws.root / "clean" / "house.md").write_text("# The Haunted House\n\n## W211. Hall {#w211}\n\nDust.\n")
    (ws.root / "joined" / "house-ground-floor.dmap").write_text(
        traced("Ground Floor", HOUSE).replace('room "r1"', 'room "w211"').replace("room.r1", "room.w211")
    )
    source, maps, _, _ = build_source(ws, "Saltmarsh")
    assert _links(source, maps)[("house-ground-floor", "w211")] == ("house", "w211")


def test_texts_in_parts_order_with_maps(tmp_path):
    source, maps, _, _ = build_source(_folder(tmp_path / "job"), "Saltmarsh")
    assert [(t.id, t.title, t.audience, t.map) for t in source.texts] == [
        ("intro", "Introduction", "player", None),
        ("house", "The Haunted House", "gm", "house-ground-floor"),
        ("ship", "The Sea Ghost", "gm", "ship-main-deck"),
    ]
    assert [(m.name, m.is_default) for m in maps] == [("house-ground-floor", True), ("ship-main-deck", False)]
    assert source.texts[1].markdown == markdown(HOUSE)


def test_pictures_described_no_strips(tmp_path):
    source, _, pictures, _ = build_source(_folder(tmp_path / "job"), "Saltmarsh")
    assert [(a.id, a.audience, a.type) for a, _ in pictures] == [
        ("region", "player", "image/png"),
        ("r2-cabin", "gm", "image/png"),
    ]
    for attachment, data in pictures:
        assert attachment.sha256 == sha256(data) and attachment.size == len(data)
        assert attachment.description
    assert [a.id for a in source.attachments] == ["region", "r2-cabin"]  # the undescribed crops are never attached
    cabin = next(k for k in source.keys if k.get("text") == "text:ship#2")
    assert cabin["assets"] == ["asset:r2-cabin"]
    assert not any("asset:r2-cabin" in k.get("assets", []) for k in source.keys if k is not cabin)


def test_entities_keyed_and_refs_repaired(tmp_path):
    ws = _folder(tmp_path / "job")
    (ws.root / "clean" / "ship.md").write_text(
        markdown(SHIP).replace("its charts in order.", "its charts in order. The Captain sleeps here.")
        + "\nSee [the captain](npc:the-captain) and [the hall](text:ship#99).\n"
    )
    source, maps, _, _ = build_source(ws, "Saltmarsh")
    assert [r["id"] for r in source.entities["npcs"]] == ["captain"]
    ship = next(t for t in source.texts if t.id == "ship")
    assert "npc:captain" in ship.markdown and "npc:the-captain" not in ship.markdown
    assert "text:ship#99" not in ship.markdown
    assert not [w for w in derive(source, maps).warnings if w.code.startswith("missing-")]
    made = {w["ref"]: w["code"] for w in ws.read_json("warnings.json", {})["making"]}
    assert made["text:ship#99"] in {"ref-rewritten", "ref-dropped"}


def test_doubts_last(tmp_path):
    _, _, _, found = build_source(_folder(tmp_path / "job"), "Saltmarsh")
    assert found == [
        {"piece": "clean-1", "part": "house", "pages": [2], "kind": "missing-text", "text": "Room 3 is cut off."}
    ]


# ----- the making stage, on a job -----


@pytest.fixture
def storage(tmp_path):
    opened = open_storage(Config(data_dir=tmp_path / "data"))
    yield opened
    opened.close()


def _services(storage):
    dm = FakeDM([])
    return ConversionServices(
        storage=storage,
        conversion=lambda: (dm, BackendChoice("fake", "fake-large")),
        thorough=lambda: (dm, BackendChoice("fake", "opus")),
        agent=lambda *_: None,
        publish=lambda kind, data: None,
        ocr=None,
    )


async def _make(storage, tmp_path):
    """A thorough job whose pipeline writes the folder and runs the making stage; answers the job when it ends."""
    pdf = tmp_path / "upload.pdf"
    write_pdf(pdf, [text_page(["The Haunted House"])])

    async def making_only(services, live, ws):
        _folder(ws.root)
        await pipeline._Job(services, live, ws).make()

    services = _services(storage)
    job = await start_thorough(services, pdf, "Saltmarsh", "draft", data_dir=tmp_path / "data", pipeline=making_only)
    await wait(services, job.id)
    return storage.conversions.get(job.id), Path(job.target["folder"])


def test_doubts_stored_on_job(storage, tmp_path):
    job, folder = asyncio.run(_make(storage, tmp_path))
    assert job.status == "done"
    assert job.questions["doubts"] == [
        {"piece": "clean-1", "part": "house", "pages": [2], "kind": "missing-text", "text": "Room 3 is cut off."}
    ]
    module = storage.modules.get(job.module_id)
    assert [m.name for m in module.maps] == ["house-ground-floor", "ship-main-deck"]
    source = load_source(storage, job.module_id)
    assert [a.id for a in source.attachments] == ["region", "r2-cabin", runner.SOURCE_PDF]
    assert storage.blobs.get(source.attachments[0].sha256) == PNG + b"p006-1.png"
    assert not folder.exists()  # removed once the module is made
    # the answers to a job's questions keep its doubts
    runner.answer_questions(storage, job.id, {}, ["Fine."])
    assert storage.conversions.get(job.id).questions["doubts"] == job.questions["doubts"]


def test_made_in_one_transaction(storage, tmp_path, monkeypatch):
    def broken(*_args, **_kwargs):
        raise RuntimeError("the disk is full")

    monkeypatch.setattr(runner, "save_source", broken)
    job, folder = asyncio.run(_make(storage, tmp_path))
    assert job.status == "paused" and job.error == "the disk is full"
    assert job.module_id is None and storage.modules.list() == []
    assert folder.is_dir() and json.loads((folder / "parts.json").read_text())


UPPER_DECK = """\
map "Upper Deck" {
  grid { cell 32 px  units feet 10  bounds 20 x 10 }
  room_numbers off
}

room "r2" { rect 1,1 6 x 5  label "2. Forecastle" }
"""


def test_a_text_opens_on_the_map_of_its_first_room(tmp_path):
    """U1: Part Two lists the Sea Ghost's upper deck first, but its room 1, where the boarding starts, is on the main
    deck: the text points at the map that holds its first keyed room, and the module's default follows the same rule."""
    ws = _folder(tmp_path / "job")
    parts = _parts()
    ship = next(part for part in parts["parts"] if part["id"] == "ship")
    ship["maps"].insert(0, {"name": "ship-upper-deck", "title": "Upper Deck", "page": 5, "level": "Upper Deck"})
    ship["order"] = 1
    ws.write_json("parts.json", {**parts, "parts": sorted(parts["parts"], key=lambda part: part["id"] != "ship")})
    (ws.root / "joined" / "ship-upper-deck.dmap").write_text(UPPER_DECK)

    source, maps, _, _ = build_source(ws, "Saltmarsh")

    texts = {text.id: text for text in source.texts}
    assert texts["ship"].map == "ship-main-deck"
    assert [m.name for m in maps if m.is_default] == ["ship-main-deck"]
    assert _links(source, maps)[("ship-upper-deck", "r2")] == ("ship", "2"), "room 2 still links on the upper deck"


def test_an_encounter_named_as_its_room_is_keyed_to_it(tmp_path):
    """U1: the entities came back as "1. Main Deck", "3. Poop Deck" with no location; the first was keyed nowhere and
    the second to the cabin whose text names the poop deck. Named as a keyed heading of its own text, an encounter is
    keyed to that heading."""
    ws = _folder(tmp_path / "job")
    (ws.root / "clean" / "ship.md").write_text(
        "# The Sea Ghost\n\n## 1. Main Deck {#1}\n\nTwo sailors watch the coast.\n\n"
        "## 2. Cabin {#2}\n\nA ladder climbs from the cabin to the poop deck.\n\n"
        "## 3. Poop Deck {#3}\n\nA smuggler leans on the tiller bar.\n"
    )
    stored = ws.read_json("entities.json")
    stored["entities"]["encounters"] = [
        {"id": "main-deck", "name": "1. Main Deck", "summary": "Two sailors watch the coast.", "kind": "dungeon"},
        {"id": "poop-deck", "name": "3. Poop Deck", "summary": "A smuggler at the tiller.", "kind": "dungeon"},
        {"id": "galley", "name": "2. Galley", "summary": "A galley no plan of the ship shows.", "kind": "dungeon"},
    ]
    stored["origins"].update({f"encounter:{id}": "ship" for id in ("main-deck", "poop-deck", "galley")})
    ws.write_json("entities.json", stored)

    source, _, _, _ = build_source(ws, "Saltmarsh")

    key_of = {entry["text"]: entry["key"] for entry in source.keys}
    encounters = {record["id"]: record for record in source.entities["encounters"]}
    assert encounters["main-deck"]["key"] == f"key:{key_of['text:ship#1']}"
    assert encounters["poop-deck"]["key"] == f"key:{key_of['text:ship#3']}"
    assert "key" not in encounters["galley"], "a number with another title places nothing"


def _plate(ws: Workspace, *entries: dict) -> None:
    """`art/plate.png`, the 200×100 red|blue picture, and `descriptions.json` listing `entries` of it."""
    (ws.root / "art" / "plate.png").write_bytes(halves())
    ws.write_json("art/descriptions.json", [{"file": "plate.png", "audience": "player", **e} for e in entries])


def test_a_plate_listed_twice_is_split(tmp_path):
    ws = _folder(tmp_path / "job")
    _plate(
        ws,
        {"id": "cabin-a", "description": "Cabin A.", "crop": [0, 0, 0.5, 1]},
        {"id": "cabin-b", "description": "Cabin B.", "crop": [0.5, 0, 0.5, 1]},
    )
    source, _, pictures, _ = build_source(ws, "Saltmarsh")
    a, b = source.attachments
    assert (a.id, b.id) == ("cabin-a", "cabin-b")
    original = sha256(halves())
    for attachment in (a, b):
        assert attachment.cut is not None and attachment.cut.proposed
        assert attachment.cut.original == original and attachment.cut.original_size == len(halves())
    stored = {sha256(data): data for _, data in pictures}
    assert colours(Image.open(io.BytesIO(stored[a.sha256]))) == {RED}
    assert colours(Image.open(io.BytesIO(stored[b.sha256]))) == {BLUE}
    assert stored[original] == halves()  # the original's bytes are stored, for the organiser
    assert {sha for _, data in pictures for sha in [sha256(data)]} == {a.sha256, b.sha256, original}


def test_a_turn_alone_is_a_cut(tmp_path):
    ws = _folder(tmp_path / "job")
    _plate(ws, {"id": "sideways", "description": "A plate.", "rotate": 90})
    source, _, pictures, _ = build_source(ws, "Saltmarsh")
    [plate] = source.attachments
    assert plate.cut is not None and plate.cut.rotate == 90 and plate.cut.box is None
    data = next(data for a, data in pictures if sha256(data) == plate.sha256)
    assert Image.open(io.BytesIO(data)).size == (100, 200)


def test_a_bad_crop_is_attached_uncut_with_a_doubt(tmp_path):
    ws = _folder(tmp_path / "job")
    _plate(ws, {"id": "plate", "description": "A plate.", "crop": [2, 0, 1, 1]}, {"id": "plain", "description": "All."})
    source, _, pictures, found = build_source(ws, "Saltmarsh")
    bad, plain = source.attachments
    assert bad.cut is None and bad.sha256 == sha256(halves())
    assert bad.audience == "gm"  # the crop was to hide something: the whole picture is the DM's until checked
    assert plain.cut is None and plain.sha256 == sha256(halves()) and plain.audience == "player"
    assert len(pictures) == 2  # nothing cut: no original besides
    assert [d["kind"] for d in found if d["kind"] == "crop-refused"] == ["crop-refused"]
    told = next(d["text"] for d in found if d["kind"] == "crop-refused")
    assert "plate.png" in told and "DM only" in told
