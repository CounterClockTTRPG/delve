"""What the mail tests share: a storage, an app that holds it, and accounts with an address."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from delve.config import Config
from delve.domain.accounts import Profile
from delve.mail.compose import Composed
from delve.mail.settings import KEY_ENV
from delve.storage import open_storage

NOW = datetime(2026, 10, 30, 10, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def no_environment(monkeypatch):
    monkeypatch.delenv(KEY_ENV, raising=False)
    monkeypatch.delenv("DELVE_ALLOWED_HOSTS", raising=False)


@pytest.fixture
def storage(tmp_path):
    opened = open_storage(Config(data_dir=tmp_path))
    yield opened
    opened.close()


@pytest.fixture
def app(storage, tmp_path):
    return SimpleNamespace(state=SimpleNamespace(storage=storage, config=Config(data_dir=tmp_path)))


def with_address(storage, name, *, pending=None, confirmed=True):
    account = storage.accounts.create(name, Profile(name.title()))
    email = f"{name}@example.org"
    storage.accounts.set_email(account.id, email=email if confirmed else None, email_pending=pending)
    return storage.accounts.get(account.id)


def composed(subject="A word"):
    return Composed(subject=subject, text="Hello\n", html="<p>Hello</p>")
