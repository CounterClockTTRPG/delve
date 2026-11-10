"""The scale key: a cell's or two points' distance, in km or miles, and what it refuses."""

import pytest

from delve.maps.geo.reading.scale import ScaleKey


def test_a_hex_of_30_miles_is_48_28_km():
    assert ScaleKey("hex", 30, "miles").km() == pytest.approx(48.28032)


def test_km_stay_km():
    assert ScaleKey("square", 5, "km").km() == 5


def test_two_points_carry_the_scale_without_a_grid():
    key = ScaleKey(None, 100, "km", points=((0.0, 0.0), (300.0, 400.0)))
    key.check()
    assert key.km() == 100


@pytest.mark.parametrize(
    "key",
    [
        ScaleKey(None, 30, "miles"),
        ScaleKey("hex", 0, "miles"),
        ScaleKey("hex", -1, "km"),
        ScaleKey(None, 10, "km", points=((5.0, 5.0), (5.0, 5.0))),
    ],
    ids=["no-grid-no-points", "zero", "negative", "equal-points"],
)
def test_check_refuses_a_key_it_cannot_measure_with(key):
    with pytest.raises(ValueError):
        key.check()
