"""Places: town symbols and their labels, the labels that name a river or a region, and Claude on the crops."""

import asyncio
import math

import pytest
from PIL import ImageDraw

from delve.maps.geo.reading import places
from delve.maps.geo.reading.grid_detect import find_grid
from delve.maps.geo.reading.ocr import OcrWord, tesseract_words
from delve.maps.geo.reading.places import read_places
from delve.maps.geo.reading.water import find_water
from tests.maps.geo.pictures import _label, fake_look, fake_ocr, hex_map, square_map


def _read(synthetic, *, ocr="fake", look=None):
    grid = find_grid(synthetic.image, synthetic.truth.grid.kind)
    water = find_water(synthetic.image, grid)
    ocr = fake_ocr(synthetic.truth) if ocr == "fake" else ocr
    look = look or fake_look(synthetic.truth)
    return asyncio.run(read_places(synthetic.image, grid, ocr=ocr, look=look, water=water))


def _named(reading):
    return {p.name: p for p in reading.places}


@pytest.mark.parametrize(
    "make", [hex_map, square_map, lambda: hex_map(orientation="flat")], ids=["hex", "square", "flat"]
)
def test_the_towns_are_found_with_their_names_at_their_symbols(make):
    synthetic = make()
    reading = _read(synthetic)
    places = _named(reading)
    assert set(places) == {"Arden", "Brask", "Corvel", "Port Wyn"}
    for true in synthetic.truth.places:
        assert math.dist(places[true.name].point_px, true.point) <= 2
        assert places[true.name].symbol is not None


def test_the_towns_symbol_is_the_usual_one_and_the_port_square_is_a_guessed_port():
    reading = _read(hex_map())
    places = _named(reading)
    assert {places[n].kind for n in ("Arden", "Brask", "Corvel")} == {"town"}
    assert places["Port Wyn"].kind == "port"
    guessed = [d for d in reading.doubts if d.kind == "kind-guessed"]
    assert [d.ref for d in guessed] == [places["Port Wyn"].id]
    assert guessed[0].alternatives[0] == "port"


def test_a_label_moved_away_from_its_symbol_is_unpaired():
    synthetic = hex_map()
    truth = synthetic.truth
    brask = truth.place("Brask")
    draw = ImageDraw.Draw(synthetic.image)
    x0, y0, x1, y1 = brask.label.box
    draw.rectangle((x0, y0, x1, y1), fill=synthetic.image.getpixel((x0 - 1, y1 + 1)))
    moved = _label(draw, "Brask", (x0 + x1) / 2, y1 - 60)
    words = [w for w in fake_ocr(truth)(synthetic.image) if w.text != "Brask"]

    def ocr(image):
        return [*words, OcrWord("Brask", moved.box, 95.0)]

    reading = _read(synthetic, ocr=ocr, look=fake_look(truth, labels=False))
    assert "Brask" not in _named(reading)
    unpaired = [d for d in reading.doubts if d.kind == "label-unpaired" and d.reading == "Brask"]
    assert len(unpaired) == 1
    assert unpaired[0].alternatives == ["place", "river-name", "region-name", "drop"]
    unlabelled = [d for d in reading.doubts if d.kind == "symbol-unlabelled"]
    assert len(unlabelled) == 1
    assert math.dist(unlabelled[0].data["at"], brask.point) <= 2


def test_without_ocr_the_labels_come_from_claude_on_the_crops():
    synthetic = hex_map()
    prompts = []
    reading = _read(synthetic, ocr=None, look=fake_look(synthetic.truth, prompts=prompts))
    assert set(_named(reading)) == {"Arden", "Brask", "Corvel", "Port Wyn"}
    assert not [d for d in reading.doubts if d.kind in ("symbol-unlabelled", "label-unpaired")]
    asked = [p for p in prompts if p.startswith("# Labels")]
    assert len(asked) == 1 and asked[0].count("a place's symbol at") == 4


def test_a_symbol_claude_cant_read_either_is_a_doubt():
    synthetic = hex_map()
    reading = _read(synthetic, ocr=None, look=fake_look(synthetic.truth, labels=False))
    assert len([d for d in reading.doubts if d.kind == "symbol-unlabelled"]) == 4
    assert {p.name for p in reading.places} == {""}


def test_the_frames_digit_labels_make_no_doubt_and_no_place():
    synthetic = hex_map()
    reading = _read(synthetic)
    assert not any(any(ch.isdigit() for ch in d.reading) for d in reading.doubts)
    assert not any(any(ch.isdigit() for ch in p.name) for p in reading.places)


def test_the_rivers_name_is_offered_as_its_name_and_isnt_the_river_towns():
    synthetic = hex_map()
    reading = _read(synthetic)
    assert _named(reading)["Arden"].label_box == synthetic.truth.place("Arden").label.box
    eldrin = [d for d in reading.doubts if d.reading == "ELDRIN"]
    assert len(eldrin) == 1
    assert eldrin[0].kind == "label-unpaired"
    assert eldrin[0].alternatives[0] == "river-name"
    assert eldrin[0].data["river"] == "river-1"


def test_a_wide_or_letter_spaced_label_is_offered_as_a_regions_name():
    synthetic = hex_map()
    words = fake_ocr(synthetic.truth)(synthetic.image)
    wide = OcrWord("CAIRN", (500, 300, 600, 310), 95.0), OcrWord("HILLS", (606, 300, 700, 310), 95.0)
    spaced = [OcrWord(ch, (480 + 14 * k, 450, 488 + 14 * k, 460), 95.0) for k, ch in enumerate("URNST")]
    reading = _read(synthetic, ocr=lambda image: [*words, *wide, *spaced])
    regions = {d.reading: d for d in reading.doubts if d.alternatives[0] == "region-name"}
    assert set(regions) == {"CAIRN HILLS", "URNST"}
    assert all(d.kind == "label-unpaired" for d in regions.values())


def test_a_label_ocr_isnt_sure_of_is_read_again_by_claude():
    synthetic = hex_map()
    corvel = synthetic.truth.place("Corvel").label.words[0][1]
    words = [
        OcrWord("C0rvel", w.box, 40.0) if w.box == corvel else w for w in fake_ocr(synthetic.truth)(synthetic.image)
    ]
    reading = _read(synthetic, ocr=lambda image: words)
    assert "Corvel" in _named(reading)
    uncertain = [d for d in reading.doubts if d.kind == "label-uncertain"]
    assert len(uncertain) == 1
    assert uncertain[0].reading == "Corvel"
    assert uncertain[0].alternatives == ["keep", "C0rvel", "drop"]


def test_tesseract_is_off_in_tests():
    assert tesseract_words() is None


def test_ocr_noise_and_a_word_claude_reads_nothing_at_make_no_doubt():
    synthetic = hex_map()
    words = fake_ocr(synthetic.truth)(synthetic.image)
    noise = [OcrWord("ee", (560, 300, 572, 308), 12.0), OcrWord("~%", (600, 330, 612, 338), 80.0)]
    unsure = OcrWord("Zqk", (620, 440, 640, 450), 45.0)
    reading = _read(synthetic, ocr=lambda image: [*words, *noise, unsure])
    assert not [d for d in reading.doubts if d.reading in ("ee", "~%", "Zqk")]
    assert set(_named(reading)) == {"Arden", "Brask", "Corvel", "Port Wyn"}


def test_read_in_small_tiles_the_places_are_the_same(monkeypatch):
    synthetic = hex_map()
    whole = _named(_read(synthetic))
    monkeypatch.setattr(places, "TILE", 256)
    monkeypatch.setattr(places, "OVERLAP", 96)
    tiled = _named(_read(synthetic))
    assert set(tiled) == set(whole)
    for name, place in whole.items():
        assert math.dist(tiled[name].point_px, place.point_px) <= 1
