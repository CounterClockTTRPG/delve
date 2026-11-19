"""The fake d20 ruleset and its tripwire (DEL-387)."""

import pytest

from delve.play.context import context_for
from delve.rules.catalog import entry as ruleset_entry
from tests.fixtures.d20 import FAKE_D20, FakeD20Engine, Tripwire, d20_catalogs, fake_engine
from tests.fixtures.rulesets import osric


def test_the_tripwire_names_what_was_read():
    with pytest.raises(AssertionError, match="initiative_die"):
        _ = Tripwire().initiative_die
    assert Tripwire().surprise_die == osric().tables.surprise_die
    assert Tripwire().fight.initiative_once and Tripwire().fight.highest_first


def test_the_fake_ruleset_is_in_its_catalogs():
    found = ruleset_entry(FAKE_D20, d20_catalogs().rulesets)
    assert found is not None and found.playable
    assert isinstance(found.make().d20, FakeD20Engine)
    assert found.make() is ruleset_entry(FAKE_D20, d20_catalogs().rulesets).make()


def test_a_fake_campaign_has_its_engine(d20_storage, d20_campaign):
    ctx = context_for(d20_storage, d20_campaign.id, "beat-1", catalogs=d20_catalogs())
    assert ctx.d20 is fake_engine()
