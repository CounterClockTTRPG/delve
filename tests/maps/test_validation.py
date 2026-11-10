"""Delve's changes to the copied DSL's overlap check (DEL-171): rooms with `allow_overlap` left out before the pairs
are measured, `overlaps=False` for an export, and a bounding-box test before polygons are compared. The warnings are
the same as the DSL's as copied."""

import importlib

from delve.maps.dsl import geometry, parse, validate
from delve.maps.dsl.geometry import Area, find_overlapping_areas
from delve.modules.dscn import Bundle, check
from tests.fixtures import SAMPLES

MAP = """
map "M" { grid { bounds 60 x 60 } }
room "cave" { polygon (0,0) (40,0) (40,40) (0,40) allow_overlap }
room "building" { rect 5,5 8 x 6 }
room "hut" { rect 9,8 6 x 6 }
layer "below" {
  room "cellar" { rect 5,5 8 x 6 allow_overlap }
  room "well" { rect 6,6 2 x 2 }
}
"""


def overlaps(diagnostics) -> list[str]:
    return [d.message for d in diagnostics if "overlaps" in d.message]


def test_an_exempt_room_is_left_out_before_the_pairs_are_measured(monkeypatch):
    measured: list[list[str]] = []
    original = find_overlapping_areas

    def watched(areas, min_area=0.0):
        measured.append([area.label for area in areas])
        return original(areas, min_area=min_area)

    # The package's `validate` is the function; the validator's module is reached by its name.
    monkeypatch.setattr(importlib.import_module("delve.maps.dsl.validate"), "find_overlapping_areas", watched)
    found = overlaps(validate(parse(MAP)))
    assert found and all("building" in m and "hut" in m for m in found)
    assert measured == [["room 'building'", "room 'hut'"], ["room 'well'"]]


def test_without_overlaps_nothing_is_measured_and_the_rest_stays():
    dmap = parse(MAP)
    whole = validate(dmap)
    without = validate(dmap, overlaps=False)
    assert overlaps(without) == []
    assert [str(d) for d in without] == [str(d) for d in whole if "overlaps" not in d.message]


def test_a_pair_whose_boxes_dont_overlap_is_never_compared(monkeypatch):
    compared: list[tuple] = []
    original = geometry.polygons_overlap
    monkeypatch.setattr(geometry, "polygons_overlap", lambda a, b: compared.append((a, b)) or original(a, b))
    square = lambda x, y, size=2: [(x, y), (x + size, y), (x + size, y + size), (x, y + size)]
    areas = [
        Area("a", [square(0, 0)]),
        Area("b", [square(1, 1)]),  # overlaps a
        Area("c", [square(2, 0)]),  # touches a's edge: no shared interior
        Area("d", [square(10, 10)]),  # far away
    ]
    assert [(la, lb) for la, lb, _ in find_overlapping_areas(areas)] == [("a", "b"), ("b", "c")]
    assert len(compared) == 2, "only a–b and b–c: a–c's boxes only touch, and d is far from all"


def test_the_box_test_finds_what_comparing_every_pair_found():
    """Every sample map's overlap warnings, with and without the box test, are the same."""
    for path in sorted((SAMPLES).glob("*.dmap")):
        dmap = parse(path.read_text(), path=path)
        with_box = overlaps(validate(dmap))
        saved = geometry._boxes_overlap
        try:
            geometry._boxes_overlap = lambda a, b: True
            every_pair = overlaps(validate(dmap))
        finally:
            geometry._boxes_overlap = saved
        assert with_box == every_pair, path.name


def test_a_bundle_checked_without_overlaps_has_the_same_errors():
    bundle = Bundle.load(SAMPLES / "scenarios" / "crypt-of-saint-vellis")
    whole, without = check(bundle), check(bundle, overlaps=False)
    assert [str(d) for d in without.diagnostics] == [str(d) for d in whole.diagnostics if "overlaps" not in d.message]
