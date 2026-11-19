"""Exceptional strength as the sheets give it: a percentile in the score ("18/76") or beside it (`str_pct`); a load
multiplier and a ruleset's own movement rule (DEL-399)."""

from dataclasses import replace

from delve.rules.classic.encumbrance import EncumbranceTables, compute, parse_strength


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


TABLES = EncumbranceTables({}, {}, {3: (30, 60, 90, 120)}, (), 30, {"light": 0, "moderate": -2, "heavy": -4,
                                                                      "severe": -6, "overloaded": -8})  # fmt: skip


def test_a_load_multiplier_scales_the_bands_rounded_down():  # DEL-399
    # ×3/4: 30, 60, 90, 120 are 22 (22.5 rounded down), 45, 67 and 90; 50 lb. is then heavy, not moderate.
    small = compute([("sack", 1, 50.0)], strength=10, multiplier=0.75, rules=TABLES)
    assert small["thresholds"] == {"light": 22, "moderate": 45, "heavy": 67, "severe": 90}
    assert small["band"] == "heavy"
    # Without one the bands are the table's.
    plain = compute([("sack", 1, 50.0)], strength=10, rules=TABLES)
    assert plain["thresholds"] == {"light": 30, "moderate": 60, "heavy": 90, "severe": 120}
    assert plain["band"] == "moderate"


def test_a_rulesets_own_movement_rule_gives_the_movement():  # DEL-399
    def slowed(band: str, rate: int) -> int:
        return {"light": rate, "moderate": rate - 5}.get(band, 0)

    rules = replace(TABLES, band_movement=slowed)
    out = compute([("sack", 1, 50.0)], strength=10, movement_rate=20, rules=rules)
    assert (out["band"], out["movement"], out["penalty"]) == ("moderate", 15, -5)
