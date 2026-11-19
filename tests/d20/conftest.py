"""Fixtures for the d20 hooks' tests: a campaign on the fake d20 ruleset and a tool host over `d20_catalogs()`, built as
`tests/dm/tools/conftest.py` builds `campaign` and `call`."""

import itertools

import pytest

from delve.config import Config
from delve.dice import SeededRng
from delve.dm.tools import ToolHost
from delve.domain.modules import ModuleMap
from delve.storage import open_storage
from tests.dm.tools.conftest import CRYPT
from tests.fixtures.d20 import FAKE_D20, d20_catalogs


@pytest.fixture
def d20_storage(tmp_path):
    opened = open_storage(Config(data_dir=tmp_path / "data"))
    yield opened
    opened.close()


@pytest.fixture
def d20_campaign(d20_storage):
    module = d20_storage.modules.create("The Crypt")
    d20_storage.modules.put_map(module.id, ModuleMap("crypt", "map", CRYPT, is_default=True))
    revision = d20_storage.revisions.snapshot(module.id)
    return d20_storage.campaigns.create("Tuesday", module.id, revision.number, ruleset=FAKE_D20, setting="greyhawk")


@pytest.fixture
def d20_host(d20_storage):
    seeds = itertools.count(1)
    return ToolHost(d20_storage, lambda: SeededRng(next(seeds)), catalogs=d20_catalogs())


@pytest.fixture
def d20_call(d20_host, d20_campaign):
    """`d20_call(tool, beat="beat-1", **args)`: a tool call on the d20 campaign."""

    def run(tool, /, beat="beat-1", **args):
        return d20_host.call(d20_campaign.id, beat, tool, args)

    return run


@pytest.fixture
def d20_web(d20_storage, tmp_path):
    """The web app over `d20_storage`, its registries on the d20 catalogs, and a client from this machine."""
    from fastapi.testclient import TestClient

    from delve.web.app import create_app
    from tests.web.conftest import make_registries

    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text("<!doctype html><title>Delve</title>")
    registries = make_registries()
    registries.catalogs = d20_catalogs()
    app = create_app(Config(data_dir=tmp_path / "data"), d20_storage, registries, static_dir=static)
    with TestClient(app, base_url="http://localhost:7810", client=("127.0.0.1", 50000)) as client:
        yield client
