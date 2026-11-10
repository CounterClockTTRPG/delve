"""An attack's worked THAC0 (plateau 7): which proficiency names the weapon, and which `+N` is the weapon's own."""

from delve.domain.characters import Attack, Sheet
from delve.rules.classic.thac0 import attack_thac0
from delve.rules.fake import FAKE_TABLES
from delve.rules.ruleset import NO_LOOKUPS


def _parts(profs: tuple[str, ...], weapon: str) -> dict[str, int]:
    sheet = Sheet(cls="hero", thac0=18, weapon_profs=profs)
    return dict(attack_thac0(sheet, Attack(name=weapon), NO_LOOKUPS, rules=FAKE_TABLES).parts)


def test_a_proficiency_names_its_weapon():
    assert "nonproficient" not in _parts(("long sword",), "Long sword")
    assert "nonproficient" not in _parts(("long sword",), "Longsword +1")
    assert "nonproficient" not in _parts(("footman's mace",), "Footman's mace")
    assert "nonproficient" not in _parts(("dart",), "Darts")


def test_a_proficiency_doesnt_name_a_weapon_its_name_is_part_of():
    assert _parts(("bow",), "Crossbow")["nonproficient"] == 2
    assert _parts(("sword",), "Two-handed sword")["nonproficient"] == 2
    assert _parts(("two-handed sword",), "Sword")["nonproficient"] == 2


def test_specialised_proficiency():
    assert _parts(("long sword (specialised)",), "Long sword")["specialised"] == -1


def test_the_magic_is_the_weapons_own_plus():
    assert _parts((), "Long sword +1")["magic"] == -1
    assert _parts((), "+2 dagger")["magic"] == -2
    assert _parts((), "Long sword +1, +3 vs regenerating creatures")["magic"] == -1
    assert _parts((), "Dagger +1 (+2 vs giants)")["magic"] == -1


def test_a_bonus_against_some_foes_isnt_the_weapons():
    assert "magic" not in _parts((), "Dagger (+2 vs giants)")
    assert "magic" not in _parts((), "Mace +3 vs undead")
    assert "magic" not in _parts((), "Mace +3 vs. undead")
    assert _parts((), "Mace +1, +3 against undead")["magic"] == -1
