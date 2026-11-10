"""Fixtures shared by every test package: a data dir with the test packs installed (OSRIC and the doubles of the
private Greyhawk and Realms packs, over the tiny wikis of `tests/fixtures/reference`), OCR off, and fast password
hashes."""

import pytest

from delve.config import Config
from delve.play import passwords
from tests.fixtures.rulesets import install_test_packs


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "real_scrypt: hash passwords with Delve's own scrypt cost, not the tests' low one"
    )


@pytest.fixture(autouse=True)
def fast_scrypt(request, monkeypatch):
    """Passwords hash with scrypt at N = 2**10 in tests (players and tavern Task B2), not 2**15, so a test that logs in
    takes milliseconds. A test marked `real_scrypt` keeps Delve's own cost."""
    if request.node.get_closest_marker("real_scrypt") is None:
        monkeypatch.setattr(passwords, "SCRYPT_N", 2**10)


@pytest.fixture(autouse=True)
def _no_ocr(monkeypatch):
    """Tests never run `tesseract`: `DELVE_OCR=off` makes every OCR factory answer None, in this process and in any
    `delve serve` a test starts, which inherits the environment."""
    monkeypatch.setenv("DELVE_OCR", "off")


@pytest.fixture
def reference_config(tmp_path):
    """A config whose data dir has the test packs installed: OSRIC, and Greyhawk and the Realms over their tiny
    wikis."""
    config = Config(data_dir=tmp_path / "data")
    config.data_dir.mkdir()
    install_test_packs(config.packs_dir)
    return config
