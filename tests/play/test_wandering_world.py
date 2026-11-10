"""The world a campaign's wandering encounters come from (DEL-337) is its setting's own (`world`), so core names no
setting's world (DEL-307)."""

import pytest

from delve.play import wandering
from delve.play.context import context_for
from tests.fixtures.rulesets import osric_catalogs
from tests.play.conftest import crypt_campaign


@pytest.mark.parametrize(
    ("setting", "world"), [("greyhawk", "oerth"), ("forgotten-realms", "toril"), ("aun", "aun"), (None, "")]
)
def test_a_campaign_is_on_its_settings_world(storage, setting, world):
    campaign = crypt_campaign(storage, setting=setting)
    assert wandering.world(context_for(storage, campaign.id, "b1", catalogs=osric_catalogs())) == world
