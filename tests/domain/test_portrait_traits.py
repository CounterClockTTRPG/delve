"""portraitgen's traits as a player's editor saves them (DEL-238): what portraitgen writes gets through, and nothing
that could become markup in another seat's drawing does."""

import pytest

from delve.domain.portrait_traits import TraitsError, checked

DWARF = {
    "version": 1, "seed": "abc", "theme": "fantasy", "archetype": "dwarf", "presentation": "masculine",
    "build": "heavy", "age": "elder", "expression": "smug", "lighting": "studio", "framing": "shoulders", "turn": 0,
    "style": "illustrated", "face": "round", "ears": "round", "eyes": "almond", "brows": "thick", "nose": "wide",
    "mouth": "pursed", "hair": "receding", "facialHair": "longBeard", "clothing": "armor", "background": "ruins",
    "frame": "ornate",
    "colors": {"skin": "#e0ac85", "hair": "#3b2516", "eyes": "#4f8a4a", "clothing": "#5a4a6e", "accent": "#c0c0c0",
               "background": "#d8c08a"},
    "accessories": ["shoulderDragon", "mailCoif"],
}  # fmt: skip


def test_what_portraitgen_writes_gets_through():
    assert checked(DWARF) == {**DWARF, "turn": 0.0}
    tuned = checked({**DWARF, "archetype": None, "tweaks": {"eyeSize": 1.2, "turn": -0.5}})
    assert tuned["archetype"] is None and tuned["tweaks"] == {"eyeSize": 1.2, "turn": -0.5}


@pytest.mark.parametrize(
    ("change", "where"),
    [
        ({"hair": '"><script>alert(1)</script>'}, "hair"),
        ({"colors": {**DWARF["colors"], "skin": "red;fill:url(x)"}}, "colors.skin"),
        ({"colors": {"skin": "#ffffff"}}, "colors"),
        ({"accessories": ["mailCoif", "<g onload=x>"]}, "accessories[1]"),
        ({"accessories": ["mailCoif", "mailCoif"]}, "accessories"),
        ({"accessories": ["hood"] * 25}, "accessories"),
        ({"seed": "a b<"}, "seed"),
        ({"turn": 3}, "turn"),
        ({"turn": float("nan")}, "turn"),
        ({"tweaks": {"jaw": True}}, "tweaks.jaw"),
        ({"tweaks": {"nose": 1}}, "tweaks"),
        ({"version": "1"}, "version"),
        ({"script": "x"}, "script"),
    ],
)
def test_anything_else_is_refused(change, where):
    with pytest.raises(TraitsError) as refused:
        checked({**DWARF, **change})
    assert refused.value.where == where


def test_every_part_is_required():
    with pytest.raises(TraitsError) as refused:
        checked({k: v for k, v in DWARF.items() if k != "nose"})
    assert refused.value.where == "nose"
    with pytest.raises(TraitsError):
        checked(["not", "an", "object"])
