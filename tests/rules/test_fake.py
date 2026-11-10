import pytest

from delve.rules.fake import FakeRuleset
from delve.rules.ruleset import ReferenceHit

SLEEP = ReferenceHit("spell", "sleep", "Sleep", "Puts 2d4 Hit Dice of creatures to sleep.")
SHIELD = ReferenceHit("spell", "shield", "Shield", "An invisible barrier in front of the caster.")
KOBOLD = ReferenceHit("monster", "kobold", "Kobold", "A small, cowardly, reptilian humanoid.")


def ruleset():
    return FakeRuleset({"spell": [SLEEP, SHIELD], "monster": [KOBOLD]})


def test_identity_and_kinds():
    rules = ruleset()
    assert rules.id == "fake-rules"
    assert rules.title
    assert rules.kinds() == ("spell", "monster")


def test_ruleset_lookup_case_insensitive():
    rules = ruleset()
    assert rules.lookup("monster", "KOBOLD") == [KOBOLD]
    assert rules.lookup("spell", "s") == [SLEEP, SHIELD]
    assert rules.lookup("spell", "s", limit=1) == [SLEEP]
    assert rules.lookup("spell", "fireball") == []


def test_ruleset_unknown_kind_lists_kinds():
    with pytest.raises(ValueError) as excinfo:
        ruleset().lookup("deity", "Pelor")
    message = str(excinfo.value)
    assert "deity" in message and "spell" in message and "monster" in message


def test_default_ruleset_has_data():
    rules = FakeRuleset()
    assert rules.kinds()
    assert rules.lookup(rules.kinds()[0], "")
