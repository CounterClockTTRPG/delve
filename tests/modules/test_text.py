"""Module text for the DM (plan 2b Task 1): a `.dscn`'s text, keys and entities, unpacked on import into the module's
working copy and snapshotted with every revision, with a full-text search over a revision's sections."""

import pytest

from delve.config import Config
from delve.domain.modules import ModuleMap
from delve.modules.dscn import Bundle, vendor
from delve.modules.importer import import_bundle
from delve.modules.text import ModuleText, TextSection, sections_of
from delve.storage import open_storage
from tests.fixtures import SAMPLES

CRYPT = SAMPLES / "scenarios" / "crypt-of-saint-vellis"


@pytest.fixture
def storage(tmp_path):
    opened = open_storage(Config(data_dir=tmp_path / "data"))
    yield opened
    opened.close()


def test_import_unpacks_text_keys_entities(storage):
    """The crypt sample's text, its three keys and its entities land in the module's working copy."""
    module = import_bundle(storage, Bundle.load(CRYPT).to_zip()).module
    stored = ModuleText.from_json(storage.module_texts.get(module.id))
    assert [k.key for k in stored.keys] == ["C1", "C2", "C3"]
    assert {s.anchor for s in stored.sections} >= {"crypt-key#c1", "crypt-key#c2", "crypt-key#c3"}
    assert all(isinstance(s, TextSection) for s in stored.sections)
    assert [n["id"] for n in stored.entities["npcs"]] == ["prior-anselm", "ritualist"]
    assert stored.entities["secrets"][0]["id"] == "prior-knew"


def test_map_only_import_stores_no_text(storage):
    bundle = Bundle.new("Just a map")
    bundle.add_map("crypt", (SAMPLES / "crypt.dmap").read_text(), default=True)
    vendor(bundle)
    module = import_bundle(storage, bundle.to_zip()).module
    assert storage.module_texts.get(module.id) is None


def test_revision_snapshots_text(storage):
    """A revision keeps the text it was made with: editing the working copy's text makes the module changed, the next
    snapshot a new revision, and the search follows each revision's own text."""
    module = import_bundle(storage, Bundle.load(CRYPT).to_zip()).module
    first = storage.revisions.snapshot(module.id)
    assert ModuleText.from_json(storage.module_texts.revision(module.id, first.number)).keys[0].key == "C1"
    assert not storage.modules.changed_since(module.id, first.number)
    hits = storage.module_texts.search(module.id, first.number, "pressure plate")
    assert hits[0]["anchor"] == "crypt-key#c1"
    assert hits[0]["heading_path"] == ["Keyed encounters", "C1. Entry Hall"]
    assert "pressure plate" in hits[0]["snippet"]

    edited = ModuleText.from_json(storage.module_texts.get(module.id))
    edited.sections[0] = TextSection(
        anchor=edited.sections[0].anchor,
        heading_path=edited.sections[0].heading_path,
        markdown="A gelatinous cube waits here.",
        audience="gm",
        read_aloud=None,
    )
    storage.module_texts.put(module.id, edited.to_json())
    assert storage.modules.changed_since(module.id, first.number)
    second = storage.revisions.snapshot(module.id)
    assert second.number == first.number + 1
    assert storage.module_texts.search(module.id, first.number, "gelatinous cube") == []
    assert storage.module_texts.search(module.id, second.number, "gelatinous cube")[0]["snippet"].startswith(
        "A gelatinous cube"
    )
    assert storage.revisions.snapshot(module.id).number == second.number


def test_search_takes_words_not_fts_syntax_and_filters_sections(storage):
    module = import_bundle(storage, Bundle.load(CRYPT).to_zip()).module
    number = storage.revisions.snapshot(module.id).number
    assert storage.module_texts.search(module.id, number, 'purse" OR "*') == []
    assert storage.module_texts.search(module.id, number, "") == []
    assert len(storage.module_texts.search(module.id, number, "ritualist", limit=1)) == 1
    only = storage.module_texts.search(module.id, number, "ritualist", section="C3")
    assert only and all("C3. Vestry Alcove" in hit["heading_path"] for hit in only)
    assert storage.module_texts.search(module.id, number, "ritualist", section="100%_") == []


def test_module_without_text_has_none_in_revisions(storage):
    module = storage.modules.create("Maps only")
    storage.modules.put_map(module.id, ModuleMap("crypt", "map", (SAMPLES / "crypt.dmap").read_text(), True))
    number = storage.revisions.snapshot(module.id).number
    assert storage.module_texts.revision(module.id, number) is None
    assert storage.module_texts.search(module.id, number, "crypt") == []


def test_deleting_a_module_drops_its_text_and_index(storage):
    module = import_bundle(storage, Bundle.load(CRYPT).to_zip()).module
    number = storage.revisions.snapshot(module.id).number
    storage.modules.delete(module.id)
    assert storage.module_texts.get(module.id) is None
    assert storage.module_texts.search(module.id, number, "ritualist") == []


ROOM = """## 4. The Study

> Dust lies thick on a desk.

The desk holds a letter.

> As you step closer, the floorboards creak.
> A draught stirs the papers.

A trapdoor lies under the rug.

### Treasure

> A glint under the desk.

20 gp.

## Background

> The house was built by an alchemist.

His notes say more.

> A later quote stays DM text here.
"""


def test_every_boxed_text_of_a_keyed_section_is_read_aloud():
    """Faithful modules Task 11 (Delve's reading of R13): a keyed section's read-aloud is every blockquote of its own
    lines, in order, and its DM text keeps none of them; an unkeyed section keeps today's rule, the leading quotes."""
    study, treasure, background = sections_of("key", "Key", "gm", ROOM)[0:3]

    assert study.read_aloud == (
        "Dust lies thick on a desk.\n\nAs you step closer, the floorboards creak.\nA draught stirs the papers."
    )
    assert study.markdown == "The desk holds a letter.\n\nA trapdoor lies under the rug."
    assert (treasure.read_aloud, treasure.markdown) == ("A glint under the desk.", "20 gp.")
    assert background.read_aloud == "The house was built by an alchemist."
    assert background.markdown == "His notes say more.\n\n> A later quote stays DM text here."


def test_a_quote_in_a_fence_is_not_read_aloud():
    source = "## 5. Cellar\n\n> Damp.\n\n```\n> not a quote\n```\n\nRats.\n"
    [cellar] = sections_of("key", "Key", "gm", source)
    assert cellar.read_aloud == "Damp."
    assert cellar.markdown == "```\n> not a quote\n```\n\nRats."
