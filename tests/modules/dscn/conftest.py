from __future__ import annotations

import pytest
from tests.modules.dscn.scn_helpers import SAMPLE

from delve.modules.dscn import Bundle


@pytest.fixture
def sample() -> Bundle:
    """A fresh, mutable copy of the bundled sample scenario."""
    return Bundle.from_dir(SAMPLE)
