"""What a new campaign plays when its module names nothing (DEL-307): a ruleset or setting its pack says is preferred
(`preferred = true`), where the install has it; core names none."""

from delve.domain.campaigns import default_ruleset, default_setting


def test_default_setting_is_a_preferred_one_where_installed_else_none():
    assert default_setting(["forgotten-realms", "greyhawk"], {"greyhawk"}) == "greyhawk"
    assert default_setting(["forgotten-realms"], {"greyhawk"}) == ""
    assert default_setting(["aun", "forgotten-realms"]) == ""
    assert default_setting([]) == ""


def test_default_ruleset_is_the_first_preferred_that_is_offered_else_the_first_offered():
    assert default_ruleset(["adnd2e", "osric"], {"adnd2e", "osric"}) == "adnd2e"
    assert default_ruleset(["mine", "osric"], {"osric"}) == "osric"
    assert default_ruleset(["mine", "yours"]) == "mine"
    assert default_ruleset([]) == ""


def test_the_packs_say_which_are_preferred():
    from tests.fixtures.rulesets import osric_catalogs

    catalogs = osric_catalogs()
    assert {e.id for e in catalogs.rulesets if e.preferred} == {"osric"}
    assert {e.id for e in catalogs.settings if e.preferred} == {"greyhawk"}  # the double, as the real pack
