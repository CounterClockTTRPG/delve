from pathlib import Path

import pytest
from tests.fixtures import SAMPLES

SAMPLES_DIR = SAMPLES


@pytest.fixture
def crypt_source() -> str:
    return (SAMPLES_DIR / "crypt.dmap").read_text(encoding="utf-8")


@pytest.fixture
def cottage_source() -> str:
    return (SAMPLES_DIR / "cottage.dmap").read_text(encoding="utf-8")


@pytest.fixture
def quickstart_source() -> str:
    return (SAMPLES_DIR / "quickstart.dmap").read_text(encoding="utf-8")
