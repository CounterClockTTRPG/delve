"""OSRIC's DM system prompt, all of it, frozen (DEL-383): the procedure with OSRIC's part, and every addendum. 3.5
brings its words in its own pack, never by changing these. Regenerate with `DELVE_REGOLDEN=1` only for a change that
is meant to, and say why in the commit."""

from __future__ import annotations

from pathlib import Path

import pytest

from delve.config import Config
from delve.storage import open_storage
from tests.fixtures import rulesets
from tests.fixtures.prompt_snapshot import assembled_prompt
from tests.fixtures.snapshot import assert_snapshot

SNAPSHOTS = Path(__file__).parent / "snapshots"


@pytest.fixture
def storage(tmp_path):
    opened = open_storage(Config(data_dir=tmp_path / "store"))
    yield opened
    opened.close()


def test_the_osric_system_prompt_is_frozen(storage):
    text = assembled_prompt(storage, "osric", rulesets.osric_catalogs())
    assert_snapshot(SNAPSHOTS / "osric_system_prompt.md", text)
