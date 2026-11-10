"""Fixtures for the tests of core and of the packs in this repo: OSRIC installed as a pack, once per run."""

import pytest

from delve.config import Config
from delve.packs import loader
from delve.packs.catalogs import Catalogs
from tests.fixtures import rulesets


@pytest.fixture(scope="session")
def osric_packs_dir():
    """A packs folder with `packs/osric` installed, made once per test process (`tests.fixtures.rulesets`). Core
    tests that play OSRIC use it through `osric_packs`, `osric_catalogs` or `config_with_osric`; none imports
    `delve_osric`."""
    return rulesets.osric_packs_dir()


@pytest.fixture
def osric_packs(osric_packs_dir):
    """The loaded packs of `osric_packs_dir`: OSRIC."""
    packs, skipped = loader.load_packs(osric_packs_dir)
    assert not skipped
    return packs


@pytest.fixture
def osric_catalogs(osric_packs):
    """The catalogs of OSRIC beside the in-tree entries, over no reference."""
    return Catalogs.of(osric_packs)


@pytest.fixture
def config_with_osric(tmp_path, osric_packs_dir):
    """A config whose data dir has OSRIC installed under `packs/` (the session's folder, linked, so it is loaded once),
    over no `reference.db`. A test must not change the packs."""
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "packs").symlink_to(osric_packs_dir)
    return Config(data_dir=tmp_path / "data")
