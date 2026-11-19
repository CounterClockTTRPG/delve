"""The pack's tests import `delve_srd35` from its `src`, as the loader does once it is installed; the tool tests play
a campaign on it."""

import itertools
import sys
from pathlib import Path

import pytest

SRC = str(Path(__file__).resolve().parents[1] / "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)


# The fixtures of a campaign on SRD 3.5 and a tool host over catalogs with the pack installed from `packs/srd35`, built
# as `tests/d20/conftest.py` builds its own; the pack says it is playable (DEL-388).


def srd35_play_catalogs():
    """OSRIC's catalogs and the installed SRD 3.5 pack."""
    from tests.fixtures.rulesets import srd35_catalogs

    return srd35_catalogs()


@pytest.fixture
def srd35_storage(tmp_path):
    from delve.config import Config
    from delve.storage import open_storage

    opened = open_storage(Config(data_dir=tmp_path / "data"))
    yield opened
    opened.close()


def _crypt_campaign(storage, ruleset):
    from delve.domain.modules import ModuleMap
    from tests.dm.tools.conftest import CRYPT

    module = storage.modules.create("The Crypt")
    storage.modules.put_map(module.id, ModuleMap("crypt", "map", CRYPT, is_default=True))
    revision = storage.revisions.snapshot(module.id)
    return storage.campaigns.create("Tuesday", module.id, revision.number, ruleset=ruleset, setting="greyhawk")


@pytest.fixture
def srd35_campaign(srd35_storage):
    return _crypt_campaign(srd35_storage, "srd35")


@pytest.fixture
def srd35_host(srd35_storage):
    from delve.dice import SeededRng
    from delve.dm.tools import ToolHost

    seeds = itertools.count(1)
    return ToolHost(srd35_storage, lambda: SeededRng(next(seeds)), catalogs=srd35_play_catalogs())


@pytest.fixture
def srd35_call(srd35_host, srd35_campaign):
    """`srd35_call(tool, beat="beat-1", **args)`: a tool call on the srd35 campaign."""

    def run(tool, /, beat="beat-1", **args):
        return srd35_host.call(srd35_campaign.id, beat, tool, args)

    return run


@pytest.fixture
def call(srd35_host, srd35_storage):
    """`call(tool, **args)`: a tool call on an OSRIC campaign, through the same host as `srd35_call`."""
    campaign = _crypt_campaign(srd35_storage, "osric")

    def run(tool, /, beat="beat-1", **args):
        return srd35_host.call(campaign.id, beat, tool, args)

    return run


class _Tripwire:
    """The pack's tables, but reading one of `tests.fixtures.d20.CLASSIC_MATHS` raises: a 3.5 path that reached the
    classic maths, which the engine replaces."""

    def __init__(self, tables):
        self._tables = tables

    def __getattr__(self, name):
        from tests.fixtures.d20 import CLASSIC_MATHS

        if name in CLASSIC_MATHS:
            raise AssertionError(f"classic table read under srd35: {name}")
        return getattr(self._tables, name)


@pytest.fixture
def srd35_tripwire(monkeypatch):
    """The srd35 ruleset with its `tables` wrapped in the tripwire, for every instance made while the test runs."""
    from delve_srd35.ruleset import Srd35Ruleset

    monkeypatch.setattr(Srd35Ruleset, "tables", _Tripwire(Srd35Ruleset.tables))
    return Srd35Ruleset.tables
