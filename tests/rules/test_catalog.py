"""The ruleset catalog (DEL-302, DEL-307): the rulesets of the installed packs, and each campaign's own on its context."""

import shutil
from pathlib import Path

import pytest

from delve.domain.backends import Registry
from delve.domain.campaigns import MissingPack
from delve.packs import loader
from delve.rules.catalog import CATALOG, catalog, make_ruleset, register_rulesets
from delve.rules.fake import FakeRuleset


def test_delve_has_no_ruleset_built_in():
    """DEL-307: every ruleset is a pack's; with none installed, the catalog is empty."""
    assert CATALOG == () and catalog(()) == ()


FIXTURES = Path(__file__).parent.parent / "fixtures" / "packs"


@pytest.fixture
def packs(tmp_path):
    shutil.copytree(FIXTURES / "test-ruleset", tmp_path / "test-ruleset")
    loader.reset()
    loaded, _ = loader.load_packs(tmp_path)
    yield loaded
    loader.reset()


def test_catalog_has_a_pack_ruleset(packs):
    cat = catalog(packs)
    assert [e.id for e in cat] == ["test-ruleset"]
    assert make_ruleset("test-ruleset", cat).id == "test-ruleset"


def test_the_registry_holds_the_catalog_and_the_fake_for_development(packs):
    registry = Registry()
    register_rulesets(registry, catalog(packs))
    assert [c.id for c in registry.capabilities()] == ["test-ruleset", "fake-rules"]
    fake = registry.capabilities()[-1]
    assert (fake.id, fake.development, fake.title) == ("fake-rules", True, "Fake ruleset (development)")


def test_an_id_that_is_not_in_the_catalog_is_missing():
    with pytest.raises(MissingPack) as raised:
        make_ruleset("adnd9")
    assert (raised.value.kind, raised.value.id) == ("ruleset", "adnd9")


def test_no_ruleset_and_the_fakes_own_id_are_the_fake():
    assert isinstance(make_ruleset(None), FakeRuleset)
    assert isinstance(make_ruleset(FakeRuleset.id), FakeRuleset)


def test_without_packs_the_registry_holds_the_fake_alone():
    registry = Registry()
    register_rulesets(registry)
    assert [c.id for c in registry.capabilities()] == ["fake-rules"]
