"""Fixtures for the play services: a fresh storage with one campaign and its owner's seat, a small reference, and
contexts on them."""

import pytest

from delve.config import Config
from delve.dice import ScriptedRng, SeededRng
from delve.domain.modules import ModuleMap
from delve.play import seats
from delve.play.context import CampaignContext, context_for
from delve.storage import open_storage
from tests.fixtures.play_reference import PlayReference
from tests.fixtures.rulesets import over


@pytest.fixture
def storage(tmp_path):
    opened = open_storage(Config(data_dir=tmp_path / "data"))
    yield opened
    opened.close()


def crypt_campaign(storage, **options):
    """A campaign of a one-map module, "The Crypt"; `options` go to `campaigns.create` (`setting=""`: none)."""
    module = storage.modules.create("The Crypt")
    storage.modules.put_map(module.id, ModuleMap("crypt", "map", "map crypt {}\n", is_default=True))
    revision = storage.revisions.snapshot(module.id)
    return storage.campaigns.create(
        "Tuesday", module.id, revision.number, **{"ruleset": "osric", "setting": "greyhawk", **options}
    )


@pytest.fixture
def campaign(storage):
    return crypt_campaign(storage)


@pytest.fixture
def owner_seat(storage, campaign):
    """The owner's seat at the campaign's table: its host."""
    return seats.owner_seat(storage, campaign.id)


@pytest.fixture
def make_ctx(storage, campaign):
    """`make_ctx(*dice, beat="beat-1", seed=None)`: a context with scripted dice (or seeded ones)."""

    def make(*values: int, beat: str = "beat-1", seed: int | None = None) -> CampaignContext:
        rng = SeededRng(seed) if seed is not None else ScriptedRng(values)
        return context_for(storage, campaign.id, beat, rng, catalogs=over(PlayReference()))

    return make


@pytest.fixture
def ctx(make_ctx):
    return make_ctx()
