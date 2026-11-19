"""A name as the lookups compare it (DEL-401): any apostrophe a player types or the data spells is the straight one."""

from __future__ import annotations

from delve.domain.reference import straight_apostrophes


def test_every_apostrophe_is_the_straight_one():
    assert straight_apostrophes("Bull’s ‘Strength’ Bull`s Bull´s Bull's") == "Bull's 'Strength' Bull's Bull's Bull's"


def test_a_name_without_one_is_unchanged():
    assert straight_apostrophes("Magic Missile") == "Magic Missile"
