"""Novels in the database (novelization plan Task 1): a novel of a campaign or a module, its choices, its outline and
its chapters, saved as they are written; it goes with its source."""

import sqlite3
from dataclasses import replace

import pytest

from delve.config import Config
from delve.conversions.runner import STEPS
from delve.domain.novels import LENGTHS, Chapter, LengthSpec, Novel
from delve.storage import open_storage


@pytest.fixture
def config(tmp_path):
    return Config(data_dir=tmp_path)


@pytest.fixture
def storage(config):
    opened = open_storage(config)
    yield opened
    opened.close()


@pytest.fixture
def campaign(storage):
    module = storage.modules.create("The Crypt of Saint Vellis")
    return storage.campaigns.create(
        "Tuesday", module.id, storage.revisions.snapshot(module.id).number, ruleset="adnd2e", setting="greyhawk"
    )


def _novel(**fields) -> Novel:
    return Novel(id="", title="", **fields)


def test_the_lengths_and_statuses():
    assert LENGTHS == {
        "recap": LengthSpec(1_500, (1, 1)),
        "short-story": LengthSpec(6_000, (3, 5)),
        "novella": LengthSpec(25_000, (8, 14)),
    }


def test_a_novel_round_trips_with_a_written_and_a_planned_chapter(storage, campaign):
    chapters = [
        Chapter("Into the crypt", "The party goes down.", "The stairs were *wet*.\n\nMira went first."),
        Chapter("The well", "Anselm falls.", None),
    ]
    made = storage.novels.create(
        _novel(
            campaign_id=campaign.id,
            sessions=(1, 3),
            length="short-story",
            tone="grimdark",
            language="nl",
            instructions="Tell it from Mira's point of view.",
        )
    )
    assert made.id.startswith("nov_") and made.created_at and made.updated_at == made.created_at
    assert (made.status, made.chapters, made.cost_usd, made.module_id) == ("writing", [], None, None)

    written = storage.novels.save(
        replace(made, title="The Wet Stairs", chapters=chapters, conversion_id="cnv_000000000001", cost_usd=0.25)
    )
    assert written.created_at == made.created_at and written.updated_at >= made.updated_at
    stored = storage.novels.get(made.id)
    assert stored == written
    assert stored.chapters[0].text.startswith("The stairs") and stored.chapters[1].text is None
    assert (stored.sessions, stored.length, stored.tone, stored.language) == ((1, 3), "short-story", "grimdark", "nl")


def test_a_module_novel_keeps_its_revision_and_custom_tone(storage):
    module = storage.modules.create("The Kobold Caves")
    made = storage.novels.create(
        _novel(module_id=module.id, revision=1, length="recap", tone="custom", custom_tone="like a fairy tale")
    )
    stored = storage.novels.get(made.id)
    assert (stored.module_id, stored.revision, stored.custom_tone, stored.sessions) == (
        module.id,
        1,
        "like a fairy tale",
        None,
    )
    assert storage.novels.for_module(module.id) == [stored]


def test_lists_are_per_source_and_newest_first(storage, campaign):
    first = storage.novels.create(_novel(campaign_id=campaign.id, length="recap"))
    second = storage.novels.create(_novel(campaign_id=campaign.id, length="novella"))
    other = storage.novels.create(_novel(module_id=campaign.module_id, revision=1, length="recap"))
    assert [n.id for n in storage.novels.for_campaign(campaign.id)] == [second.id, first.id]
    assert [n.id for n in storage.novels.for_module(campaign.module_id)] == [other.id]
    assert storage.novels.for_campaign("cmp_000000000000") == []


def test_writing_lists_the_novels_still_being_written(storage, campaign):
    writing = storage.novels.create(_novel(campaign_id=campaign.id, length="recap"))
    done = storage.novels.create(_novel(campaign_id=campaign.id, length="recap"))
    storage.novels.save(replace(done, status="done"))
    assert [n.id for n in storage.novels.writing()] == [writing.id]


def test_delete_and_unknown_ids(storage, campaign):
    made = storage.novels.create(_novel(campaign_id=campaign.id, length="recap"))
    assert storage.novels.delete(made.id) is True
    assert storage.novels.get(made.id) is None
    assert storage.novels.delete(made.id) is False
    with pytest.raises(KeyError):
        storage.novels.save(made)
    with pytest.raises(KeyError):
        storage.novels.create(_novel(campaign_id="cmp_000000000000", length="recap"))


def test_deleting_its_campaign_deletes_it(storage, campaign):
    made = storage.novels.create(_novel(campaign_id=campaign.id, length="recap"))
    storage.campaigns.delete(campaign.id)
    assert storage.novels.get(made.id) is None


def test_deleting_its_module_deletes_it(storage):
    module = storage.modules.create("The Kobold Caves")
    made = storage.novels.create(_novel(module_id=module.id, revision=1, length="recap"))
    storage.modules.delete(module.id)
    assert storage.novels.get(made.id) is None


def test_a_novel_has_exactly_one_source(storage, campaign):
    with pytest.raises(ValueError):
        storage.novels.create(_novel(length="recap"))
    with pytest.raises(ValueError):
        storage.novels.create(_novel(campaign_id=campaign.id, module_id=campaign.module_id, length="recap"))


@pytest.mark.parametrize("both", [True, False], ids=["both", "neither"])
def test_the_table_refuses_a_row_with_both_sources_or_neither(storage, config, campaign, both):
    now = "2026-10-20T00:00:00+00:00"
    sources = (campaign.id, campaign.module_id) if both else (None, None)
    with sqlite3.connect(config.db_path) as db, pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        db.execute(
            "INSERT INTO novels (id, title, campaign_id, module_id, length, tone, custom_tone, language, "
            "instructions, chapters, status, created_at, updated_at) "
            "VALUES ('nov_000000000001', '', ?, ?, 'recap', 'classic', '', 'en', '', '[]', 'writing', ?, ?)",
            (*sources, now, now),
        )


def test_a_novel_has_its_steps():
    assert STEPS["novel"] == (("condensing",), ("outlining",), ("writing",))
