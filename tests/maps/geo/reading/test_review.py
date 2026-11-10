"""The review: the doubts first and in kind order, the colours mapped once, and each decision applied."""

import asyncio

import pytest

from delve.maps.geo.reading.ocr import OcrWord
from delve.maps.geo.reading.read import read_picture
from delve.maps.geo.reading.review import DOUBT_KINDS, OUTSIDE, Reading, apply_review, unmapped
from delve.maps.geo.reading.scale import ScaleKey
from delve.maps.geo.terrain import NO_TERRAIN, TERRAIN_LETTERS
from tests.maps.geo.pictures import fake_look, fake_ocr, hex_map

THIRTY_MILES = ScaleKey("hex", 30, "miles")


def _read(synthetic, key=THIRTY_MILES, *, ocr=None, look=None):
    return asyncio.run(
        read_picture(
            synthetic.image,
            key,
            ocr=ocr or fake_ocr(synthetic.truth),
            look=look or fake_look(synthetic.truth),
            progress=lambda step, done, total: None,
        )
    )


@pytest.fixture(scope="module")
def synthetic():
    return hex_map()


@pytest.fixture(scope="module")
def reading(synthetic):
    return _read(synthetic)


def _of(reading, kind):
    return [d for d in reading.doubts if d.kind == kind]


def _all_mapped(reading, synthetic):
    """Every unmapped colour mapped to the terrain the picture drew with it."""
    truth = synthetic.truth
    return {
        c.id: next(truth.terrain[i] for i in c.cells if i not in truth.mixed)
        for c in reading.clusters
        if c.terrain is None
    }


def test_the_doubts_come_in_kind_order_then_by_position(reading):
    kinds = [DOUBT_KINDS.index(d.kind) for d in reading.doubts]
    assert kinds == sorted(kinds)
    assert {d.kind for d in reading.doubts} >= {"cluster-unmapped", "label-unpaired", "kind-guessed", "cell-mixed"}
    for kind in DOUBT_KINDS:
        ats = [d.data["at"] for d in _of(reading, kind) if "at" in d.data]
        assert ats == sorted(ats, key=lambda at: (at[1], at[0]))
    assert len({d.id for d in reading.doubts}) == len(reading.doubts)


def test_every_colour_is_unmapped_until_mapped_and_its_cells_have_no_terrain(reading, synthetic):
    land = [c for c in reading.clusters if c.terrain is None]
    assert len(land) == 4
    assert sorted(unmapped(reading)) == sorted(c.id for c in land)
    assert sorted(d.ref for d in _of(reading, "cluster-unmapped")) == sorted(str(c.id) for c in land)
    for cluster in land:
        assert {reading.geo.terrain[i] for i in cluster.cells} == {NO_TERRAIN}


def test_with_every_colour_mapped_no_cell_is_without_terrain(reading, synthetic):
    reviewed = apply_review(reading, clusters=_all_mapped(reading, synthetic))
    assert unmapped(reviewed) == []
    assert NO_TERRAIN not in reviewed.geo.terrain
    assert all(d.resolved for d in _of(reviewed, "cluster-unmapped"))
    truth = synthetic.truth
    for i, letter in enumerate(reviewed.geo.terrain):
        if i not in truth.mixed:
            assert letter == TERRAIN_LETTERS[truth.terrain[i]]


def test_keeping_claudes_suggestions_maps_the_colours_at_once(reading, synthetic):
    reviewed = apply_review(reading, kinds={"cluster-unmapped": "keep"})
    assert unmapped(reviewed) == []
    assert {c.id: c.terrain for c in reviewed.clusters if c.id in unmapped(reading)} == _all_mapped(reading, synthetic)


def test_a_mixed_cell_decided_keeps_its_terrain_when_its_colour_is_mapped(reading, synthetic):
    (mixed,) = _of(reading, "cell-mixed")
    cell = int(mixed.ref.split(":")[1])
    reviewed = apply_review(reading, decisions={mixed.id: "hills"})
    reviewed = apply_review(reviewed, clusters=_all_mapped(reading, synthetic))
    assert reviewed.geo.terrain[cell] == TERRAIN_LETTERS["hills"]
    assert reviewed.doubt(mixed.id).resolved


def test_drop_removes_a_place(reading):
    port = reading.geo.feature("Port Wyn")
    (guessed,) = _of(reading, "kind-guessed")
    assert guessed.ref == port.id and port.props["doubt"] == guessed.id
    reviewed = apply_review(reading, decisions={guessed.id: "drop"})
    assert reviewed.geo.feature("Port Wyn") is None
    with pytest.raises(ValueError):
        apply_review(reviewed, decisions={guessed.id: "keep"})


def test_a_kind_decided_changes_the_place_and_clears_its_doubt(reading):
    (guessed,) = _of(reading, "kind-guessed")
    reviewed = apply_review(reading, decisions={guessed.id: "village"})
    port = reviewed.geo.feature("Port Wyn")
    assert port.kind == "village" and "doubt" not in port.props


def test_the_rivers_name_is_its_reading_and_another_choice_undoes_it(reading):
    (eldrin,) = [d for d in _of(reading, "label-unpaired") if d.reading == "ELDRIN"]
    assert eldrin.ref == "river-1"
    assert reading.geo.feature("river-1").name == "ELDRIN"
    assert reading.geo.feature("river-1").props["doubt"] == eldrin.id
    as_place = apply_review(reading, decisions={eldrin.id: "place"})
    assert as_place.geo.feature("river-1").name == ""
    assert as_place.geo.feature("ELDRIN").layer == "places"
    as_region = apply_review(as_place, decisions={eldrin.id: "region-name"})
    assert as_region.geo.feature("ELDRIN").layer == "regions"
    back = apply_review(as_region, decisions={eldrin.id: "river-name"})
    assert back.geo.feature("river-1").name == "ELDRIN"
    assert [f.name for f in back.geo.features if f.name == "ELDRIN"] == ["ELDRIN"]


def test_a_kind_decided_at_once_resolves_every_such_doubt(synthetic):
    words = fake_ocr(synthetic.truth)(synthetic.image)
    extra = [OcrWord("CAIRN", (500, 300, 600, 310), 95.0), OcrWord("Lonely", (600, 440, 640, 450), 95.0)]
    reading = _read(synthetic, ocr=lambda image: [*words, *extra])
    unpaired = _of(reading, "label-unpaired")
    assert len(unpaired) == 3
    reviewed = apply_review(reading, kinds={"label-unpaired": "drop"})
    assert all(d.resolved and d.choice == "drop" for d in _of(reviewed, "label-unpaired"))
    assert not any(f.name in ("CAIRN", "Lonely", "ELDRIN") for f in reviewed.geo.features)
    assert not _of(reviewed, "kind-guessed")[0].resolved


def test_a_kind_applies_only_where_the_choice_is_offered(reading):
    reviewed = apply_review(reading, kinds={"label-unpaired": "river-name", "kind-guessed": "castle"})
    (eldrin,) = _of(reviewed, "label-unpaired")
    assert eldrin.resolved
    assert reviewed.geo.feature("Port Wyn").kind == "castle"


def test_the_frames_colour_mapped_outside_lets_accept_through_with_its_cells_without_terrain():
    synthetic = hex_map(lines=False)
    key = ScaleKey(None, 100, "km", points=((40.0, 40.0), (140.0, 40.0)))
    reading = _read(synthetic, key)
    frame = next(c for c in reading.clusters if c.suggestion == OUTSIDE)
    assert frame.id in unmapped(reading)
    reviewed = apply_review(reading, kinds={"cluster-unmapped": "keep"})
    assert unmapped(reviewed) == []
    assert next(c for c in reviewed.clusters if c.id == frame.id).terrain == OUTSIDE
    assert reviewed.geo.terrain[0] == NO_TERRAIN
    assert {reviewed.geo.terrain[i] for i in frame.cells} == {NO_TERRAIN}


def test_a_guessed_water_kind_and_a_guessed_flow_are_doubts_and_reverse_reverses_the_river():
    synthetic = hex_map(sea=False, lakes=2)
    reading = _read(synthetic)
    water = _of(reading, "water-kind-guessed")
    assert {d.reading for d in water} == {"sea", "lake"}
    sea = next(d for d in water if d.reading == "sea")
    assert sea.alternatives == ["sea", "lake"]
    (flow,) = _of(reading, "river-flow-guessed")
    assert flow.alternatives == ["keep", "reverse"]
    assert flow.data["flows"] == ["lake", "sea"]  # what the review names it by (DEL-94)
    line = reading.geo.feature(flow.ref).geometry["coordinates"]
    reviewed = apply_review(reading, decisions={flow.id: "reverse", sea.id: "lake"})
    assert reviewed.geo.feature(flow.ref).geometry["coordinates"] == line[::-1]
    assert {reviewed.geo.terrain[c] for c in sea.data["cells"]} == {TERRAIN_LETTERS["lake"]}
    assert reviewed.geo.feature(sea.ref).kind == "lake"
    again = apply_review(reviewed, decisions={flow.id: "keep"})
    assert again.geo.feature(flow.ref).geometry["coordinates"] == line


def test_a_decision_that_isnt_offered_is_refused_and_changes_nothing(reading):
    (guessed,) = _of(reading, "kind-guessed")
    for bad in (
        {"decisions": {guessed.id: "dragon"}},
        {"decisions": {"no-such-doubt": "keep"}},
        {"clusters": {unmapped(reading)[0]: "lava"}},
        {"clusters": {99: "plains"}},
        {"kinds": {"no-such-kind": "drop"}},
    ):
        with pytest.raises(ValueError):
            apply_review(reading, **bad)


def test_a_reviewed_reading_round_trips_through_its_dict(reading, synthetic):
    reviewed = apply_review(reading, clusters=_all_mapped(reading, synthetic), kinds={"label-unpaired": "place"})
    assert Reading.from_dict(reviewed.to_dict(), reviewed.geo) == reviewed
