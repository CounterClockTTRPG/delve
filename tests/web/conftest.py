"""An app on fakes in a temp data dir, and clients that call it from this machine or from elsewhere on the LAN.

TestClient's own client address is `testclient`, which is not loopback, so `lan` stands for another device.
"""

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from delve.config import Config
from delve.dm.fake import FAKE_DM_CAPABILITIES, FakeDM
from delve.domain.accounts import Account
from delve.domain.backends import ProviderCapabilities, Registry
from delve.domain.campaigns import TableSession
from delve.images.fake import FAKE_IMAGES_CAPABILITIES, FakeImages
from delve.play import logins
from delve.play.accounts import create_account
from delve.rules.fake import FakeRuleset
from delve.setting.catalog import register_settings
from delve.storage import open_storage
from delve.web.app import Registries, create_app
from tests.fixtures.rulesets import over

BASE_URL = "http://localhost:7810"
PASSWORD = "correct horse battery"
SESSION_COOKIE = "delve_session"
INDEX_HTML = "<!doctype html><title>Delve</title><div id=root></div>"


def playing(storage, campaign_id: str) -> None:
    """The table's session under way (DEL-199), so its seats act at once, as before the host started sessions."""
    storage.table_sessions.put(TableSession(campaign_id, "playing"))


def make_registries() -> Registries:
    registries = Registries(dm=Registry(), images=Registry(), rulesets=Registry(), settings_=Registry())
    registries.dm.register(FAKE_DM_CAPABILITIES, lambda: FakeDM([]))
    registries.images.register(FAKE_IMAGES_CAPABILITIES, FakeImages)
    registries.rulesets.register(ProviderCapabilities("fake-rules", "Fake ruleset", frozenset()), FakeRuleset)
    # The campaigns of the web tests play OSRIC's tables, without lookups, as AD&D 2e's played before it left core, in
    # Greyhawk or the Realms (their packs' doubles) or Aun.
    registries.catalogs = over(None)
    register_settings(registries.settings_, registries.catalogs.settings)
    return registries


@pytest.fixture
def config(tmp_path):
    return Config(data_dir=tmp_path / "data")


@pytest.fixture
def storage(config):
    storage = open_storage(config)
    yield storage
    storage.close()


@pytest.fixture
def registries():
    return make_registries()


@pytest.fixture
def static_dir(tmp_path):
    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text(INDEX_HTML)
    (static / "assets" / "app.js").write_text("console.log('delve')")
    return static


@pytest.fixture
def app(config, storage, registries, static_dir):
    return create_app(config, storage, registries, static_dir=static_dir)


@pytest.fixture
def token(app, config):
    return config.token_path.read_text().strip()


@pytest.fixture
def lan(app):
    """A browser on another device, without the token."""
    with TestClient(app, base_url=BASE_URL) as client:
        yield client


@pytest.fixture
def local(app):
    """A browser on this machine."""
    with TestClient(app, base_url=BASE_URL, client=("127.0.0.1", 50000)) as client:
        yield client


def make_account(storage, username="ana", *, organiser=False, owner=False) -> Account:
    """An account with `PASSWORD` (players and tavern Task C)."""
    return create_account(storage, username, PASSWORD, organiser=organiser, owner=owner)


def log_in(client: TestClient, username: str = "ana", password: str = PASSWORD) -> None:
    """Log the client in through `POST /api/login`."""
    response = client.post("/api/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text


@pytest.fixture
def player(app, storage, lan):
    """The `lan` client, logged in as `ana`."""
    make_account(storage)
    log_in(lan)
    return lan


def session_for(storage, account: Account, client: TestClient | None = None) -> str:
    """A login session for the account, started in storage, so a test doesn't depend on `POST /api/login`; with a
    client, its `delve_session` cookie is set too. Answers the session's token."""
    token = logins.start(storage, account.id, "testclient", "", datetime.now(UTC))
    if client is not None:
        client.cookies.set(SESSION_COOKIE, token)
    return token
