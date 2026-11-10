"""The module source in storage (plan 3 Task 1): the working copy in `module_sources`, a copy pinned by every revision,
and the attachments' bytes in the blob store, never deleted while a revision may name them."""

import base64
from dataclasses import replace

import pytest

from delve.config import Config
from delve.modules.dscn import Bundle
from delve.modules.importer import import_bundle
from delve.modules.source import Attachment, ModuleSource, TextDoc, derive, from_bundle, load_source, save_source
from delve.modules.text import ModuleText
from delve.storage import open_storage
from tests.fixtures import SAMPLES

CRYPT = SAMPLES / "scenarios" / "crypt-of-saint-vellis"
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


@pytest.fixture
def storage(tmp_path):
    opened = open_storage(Config(data_dir=tmp_path / "data"))
    yield opened
    opened.close()


def test_put_and_get_the_working_source(storage):
    module = storage.modules.create("Mine")
    assert storage.module_sources.get(module.id) is None
    source = ModuleSource([TextDoc("intro", "Intro", "player", None, "Hello.\n")], {}, [], [])
    storage.module_sources.put(module.id, source)
    assert storage.module_sources.get(module.id) == source
    assert storage.modules.changed_since(module.id, storage.revisions.snapshot(module.id).number) is False


def test_the_working_source_says_when_it_was_put(storage):
    module = storage.modules.create("Mine")
    assert storage.module_sources.updated_at(module.id) is None
    storage.module_sources.put(module.id, ModuleSource([], {}, [], []))
    first = storage.module_sources.updated_at(module.id)
    assert first is not None
    storage.module_sources.put(
        module.id, ModuleSource([TextDoc("intro", "Intro", "player", None, "Hi.\n")], {}, [], [])
    )
    assert storage.module_sources.updated_at(module.id) > first


def test_snapshot_pins_the_source_and_its_attachments(storage):
    module = storage.modules.create("Mine")
    sha = storage.blobs.put(PNG, "image/png")
    storage.blobs.link(module.id, "attachment", sha)
    source = ModuleSource([], {}, [], [Attachment("a1", "image/png", sha, len(PNG), "A dot.", "player")])
    storage.module_sources.put(module.id, source)
    first = storage.revisions.snapshot(module.id)
    assert first.number == 1

    storage.module_sources.put(module.id, replace(source, attachments=[]))
    assert storage.modules.changed_since(module.id, first.number)
    second = storage.revisions.snapshot(module.id)
    assert second.number == 2

    assert storage.module_sources.revision(module.id, 1).attachment("a1") is not None
    assert storage.module_sources.revision(module.id, 2).attachment("a1") is None
    assert storage.module_sources.revision(module.id, 3) is None
    assert storage.blobs.get(sha) == PNG


def test_import_stores_the_source_and_each_attachment(storage):
    bundle = Bundle.load(CRYPT)
    module = import_bundle(storage, bundle.to_zip()).module
    assert storage.module_sources.get(module.id) == from_bundle(bundle)
    token = bundle.asset_entry("ritualist-token")
    assert ("attachment", token["sha256"]) in storage.blobs.links(module.id)
    assert storage.blobs.get(token["sha256"]) == bundle.read(token["file"])


def test_save_source_stores_the_source_and_its_derived_text(storage):
    module = import_bundle(storage, Bundle.load(CRYPT).to_zip()).module
    source = load_source(storage, module.id)
    rewritten = replace(source.texts[1], markdown=source.texts[1].markdown.replace("40 gp", "a gelatinous cube"))
    edited = replace(source, texts=[source.texts[0], rewritten])
    derived = save_source(storage, module.id, edited)
    assert storage.module_sources.get(module.id) == edited
    assert storage.module_texts.get(module.id) == derived.text.to_json()
    assert "gelatinous cube" in derived.text.section("crypt-key#c3").markdown


def test_save_source_is_one_transaction(storage, monkeypatch):
    module = import_bundle(storage, Bundle.load(CRYPT).to_zip()).module
    before = load_source(storage, module.id)

    def broken_put(module_id, raw):
        raise OSError("disk full")

    monkeypatch.setattr(storage.module_texts, "put", broken_put)
    with pytest.raises(OSError):
        save_source(storage, module.id, replace(before, keys=[]))
    assert storage.module_sources.get(module.id) == before


def test_a_module_imported_before_plateau_3_gets_its_source_on_first_read(storage):
    """Review Focus 5: a module imported in plateau 2b has text but no source row, no attachment blobs, and revisions
    without a source. Its first read builds the source from its stored bundle, and changes nothing else."""
    bundle = Bundle.load(CRYPT)
    module = import_bundle(storage, bundle.to_zip()).module
    revision = storage.revisions.snapshot(module.id)
    text_before = storage.module_texts.get(module.id)
    with storage.engine.begin() as connection:
        connection.exec_driver_sql("DELETE FROM module_sources")
        connection.exec_driver_sql("UPDATE module_revisions SET source = NULL")
        connection.exec_driver_sql("DELETE FROM module_blobs WHERE role = 'attachment'")
    assert storage.module_sources.get(module.id) is None
    assert not storage.modules.changed_since(module.id, revision.number)

    source = load_source(storage, module.id)
    assert source == from_bundle(bundle)
    assert storage.module_sources.get(module.id) == source
    assert storage.module_texts.get(module.id) == text_before
    assert derive(source, storage.modules.get(module.id).maps).text == ModuleText.from_json(text_before)
    token = bundle.asset_entry("ritualist-token")
    assert ("attachment", token["sha256"]) in storage.blobs.links(module.id)
    assert storage.blobs.get(token["sha256"]) == bundle.read(token["file"])
    # The revision was made from the same bundle, so it pins the same source, and the module is unchanged.
    assert storage.module_sources.revision(module.id, revision.number) == source
    assert not storage.modules.changed_since(module.id, revision.number)
    assert load_source(storage, module.id) == source


def test_a_module_made_in_the_app_starts_with_an_empty_source(storage):
    module = storage.modules.create("Blank")
    assert load_source(storage, module.id) == ModuleSource([], {}, [], [])
    assert storage.module_sources.get(module.id) == ModuleSource([], {}, [], [])
