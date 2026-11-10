"""The rulesets' item rarity bands (plan "Rulesets" Task 2)."""

import pytest

from delve.domain.reference import RARITY_BANDS, rarity_band


@pytest.mark.parametrize(
    ("rarity", "band"),
    [
        (0, "common"),
        (5, "common"),
        (6, "uncommon"),
        (20, "uncommon"),
        (21, "rare"),
        (40, "rare"),
        (41, "very_rare"),
        (55, "very_rare"),
        (56, "legendary"),
        (70, "legendary"),
        (71, "artifact"),
        (100, "artifact"),
        (None, "common"),
    ],
)
def test_rarity_band(rarity, band):
    assert rarity_band(rarity) == band
    assert band in [name for name, _ in RARITY_BANDS]
