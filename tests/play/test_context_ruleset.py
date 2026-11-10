"""Each campaign's context carries its own ruleset, from the catalog (DEL-302)."""

import pytest

from delve.domain.campaigns import MissingPack
from delve.packs.catalogs import Catalogs
from delve.play.context import context_for
from tests.fixtures.play_reference import PlayReference
from tests.fixtures.rulesets import over
from tests.play.conftest import crypt_campaign


def test_a_campaigns_context_carries_its_own_ruleset(storage):
    campaign = crypt_campaign(storage)
    ctx = context_for(storage, campaign.id, "b1", catalogs=over(PlayReference()))
    assert ctx.ruleset is not None and ctx.ruleset.id == campaign.ruleset == "osric"


def test_a_campaign_whose_ruleset_or_setting_isnt_installed_raises_missing_pack(storage):
    for kinds, expected in (
        ({"ruleset": "adnd9"}, MissingPack("ruleset", "adnd9")),
        ({"setting": "eberron"}, MissingPack("setting", "eberron")),
    ):
        module = storage.modules.create("The Crypt")
        revision = storage.revisions.snapshot(module.id)
        campaign = storage.campaigns.create(
            "Tuesday", module.id, revision.number, **{"ruleset": "osric", "setting": "greyhawk", **kinds}
        )
        with pytest.raises(MissingPack) as raised:
            context_for(storage, campaign.id, "b1", catalogs=over(PlayReference()))
        assert (raised.value.kind, raised.value.id) == (expected.kind, expected.id)
        assert str(raised.value) == f"This campaign's {expected.kind}, {expected.id}, isn't installed."


def test_the_fake_ruleset_and_no_setting_are_never_missing(storage):
    module = storage.modules.create("The Crypt")
    revision = storage.revisions.snapshot(module.id)
    campaign = storage.campaigns.create("Tuesday", module.id, revision.number, ruleset="fake-rules", setting="")
    assert context_for(storage, campaign.id, "b1").ruleset.id == "fake-rules"


def test_every_id_resolves_with_its_pack_installed(storage, osric_packs):
    """With OSRIC installed (and AD&D 2e not: its pack's tests install it), every id this install has resolves."""
    for ruleset, setting in (("osric", "greyhawk"), ("osric", "forgotten-realms"), ("fake-rules", "fake-setting")):
        module = storage.modules.create("The Crypt")
        revision = storage.revisions.snapshot(module.id)
        campaign = storage.campaigns.create("Tuesday", module.id, revision.number, ruleset=ruleset, setting=setting)
        catalogs = Catalogs.of(osric_packs)
        assert context_for(storage, campaign.id, "b1", catalogs=catalogs).ruleset.id == ruleset


def test_context_has_no_reference_attribute(storage):
    """A context holds its ruleset's lookups, never the install's `reference.db`."""
    from dataclasses import fields

    from delve.play.context import CampaignContext

    assert "reference" not in {field.name for field in fields(CampaignContext)}
    campaign = crypt_campaign(storage)
    ctx = context_for(storage, campaign.id, "b1", catalogs=over(PlayReference()))
    assert not hasattr(ctx, "reference") and ctx.lookups is ctx.ruleset.reference
