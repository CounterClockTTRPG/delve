"""A converted module always exports (plan faithful-modules Task 1, Review Focus 1): the refs Claude's entity drafts
leave dangling are rewritten or dropped by the conversion, so `export.dscn` answers 200 and its bundle validates."""

import asyncio

from delve.modules.books.convert import convert_book
from delve.modules.books.pdf import PdfBook, PdfPage
from delve.modules.dscn import Bundle, validate
from delve.modules.source import ATTACHMENT, save_source
from tests.modules.books.test_convert import FakeClaude

SHIP = "# The Ship\n\n## 7. The Hold\n\nThe bosun waits by the crates. Smugglers come at night."

ENTITIES = {
    "the-ship": {
        "npcs": [
            {"id": "the-bosun", "name": "The Bosun", "summary": "Gruff."},
            {"id": "bosun-2", "name": "the bosun", "role": "bosun"},
            {"id": "smuggler-2", "name": "Smuggler Anna"},
            {"id": "smuggler-3", "name": "Smuggler Bert"},
        ],
        "factions": [
            {
                "id": "crew",
                "name": "The Crew",
                "members": ["npc:bosun", "npc:bosun-2", "npc:smuggler"],
                "summary": "Led by [the bosun](npc:bosun).\n\n![The deck](asset:page-99)",
            }
        ],
        "encounters": [{"id": "night", "name": "Night visitors", "key": "key:7", "summary": "Smugglers."}],
        "quests": [{"id": "catch", "name": "Catch them", "giver": "npc:smuggler", "related": ["text:the-ship#9"]}],
    }
}


def test_a_converted_module_exports(local, storage):
    book = PdfBook([PdfPage(1, SHIP, False, [])], [])
    converted = asyncio.run(convert_book(book, "The Ship", FakeClaude(entities=ENTITIES), lambda *a: None))
    codes = {w.code for w in converted.warnings}
    assert {"ref-rewritten", "ref-dropped"} <= codes

    module = storage.modules.create("The Ship")
    for attachment, data in converted.pictures:
        storage.blobs.link(module.id, ATTACHMENT, storage.blobs.put(data, attachment.type))
    save_source(storage, module.id, converted.source)

    response = local.get(f"/api/modules/{module.id}/export.dscn")

    assert response.status_code == 200
    errors = [d for d in validate(Bundle.from_zip(response.content)) if d.severity == "error"]
    assert errors == []
    faction = converted.source.entities["factions"][0]
    assert faction["members"] == ["npc:the-bosun", "npc:the-bosun"]
    assert faction["summary"] == "Led by [the bosun](npc:the-bosun)."
