"""Exceptional strength as the sheets give it: a percentile in the score ("18/76") or beside it (`str_pct`)."""

from delve.rules.classic.encumbrance import parse_strength


def test_percentile_in_the_score():
    assert parse_strength("18/76") == (18, 76)
    assert parse_strength("18/00") == (18, 100)


def test_percentile_beside_the_score():
    assert parse_strength(18, 76) == (18, 76)
    assert parse_strength(18, "00") == (18, 100)


def test_no_percentile_is_plain_18():
    # A str_pct of 0 is a sheet saying "none", not 18/00: a plain 18 carries 0 pounds more than its row.
    assert parse_strength(18, 0) == (18, 0)
    assert parse_strength(18, "0") == (18, 0)
    assert parse_strength(18, None) == (18, 0)
    assert parse_strength(18, "") == (18, 0)


def test_percentile_only_at_18():
    assert parse_strength(17, 50) == (17, 0)
