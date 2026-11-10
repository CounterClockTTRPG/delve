"""Validator (§10): the sample is clean; each rule fires on a targeted break."""
from __future__ import annotations

import pytest
import yaml
from tests.modules.dscn.scn_helpers import codes, warn_codes

from delve.modules.dscn import Bundle, check, keyed_texts, suggest, validate, vendor


def test_sample_is_clean(sample):
    assert validate(sample) == []


def test_report_carries_parsed_maps_and_texts(sample):
    rep = check(sample)
    assert rep.ok
    assert "room.entry_hall" in rep.maps["crypt"].nodes
    assert rep.texts["crypt-key"].section("c2").key == "C2"


def test_dangling_include_and_vendor(sample):
    lib = sample.maps("library")[0]
    sample.manifest["maps"].remove(lib)
    del sample.files[lib["file"]]
    assert "dangling-include" in codes(validate(sample))
    assert vendor(sample) == ["core.dmap"]
    assert validate(sample) == []


def test_unknown_node_in_keys(sample):
    sample.manifest["keys"][0]["node"] = "map:crypt#room.nowhere"
    assert "dangling-ref" in codes(validate(sample))


def test_unknown_anchor_and_entity_refs(sample):
    sample.manifest["keys"][0]["text"] = "text:crypt-key#c9"
    sample.manifest["keys"][1]["npcs"] = ["npc:ghost"]
    errs = [d.message for d in validate(sample) if d.code == "dangling-ref"]
    assert any("#c9" in m for m in errs) and any("npc:ghost" in m for m in errs)


def test_refs_inside_text_and_entities_are_checked(sample):
    path = sample.text_entry("crypt-key")["file"]
    sample.files[path] += b"\nSee [[npc:nobody]].\n"
    recs = sample.entities("npcs")
    recs[1]["description"] = "Flees to [x](text:crypt-key#nope)."
    sample.set_entities("npcs", recs)
    msgs = [d.message for d in validate(sample) if d.code == "dangling-ref"]
    assert any("npc:nobody" in m for m in msgs)
    assert any("#nope" in m for m in msgs)


def test_hash_size_and_type_checks(sample):
    a = sample.entries("assets")[0]
    sample.files[a["file"]] = b"GIF89a-not-a-png"
    got = codes(validate(sample))
    assert {"hash-mismatch", "size-mismatch", "type-mismatch"} <= set(got)


def test_active_svg_rejected():
    b = Bundle.new("T")
    b.add_asset("x", b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
                "image/svg+xml")
    assert "svg-active" in codes(validate(b))
    b.add_asset("x", b'<svg xmlns="http://www.w3.org/2000/svg"><rect onload="x()"/></svg>',
                "image/svg+xml")
    assert "svg-active" in codes(validate(b))
    b.add_asset("x", b'<svg xmlns="http://www.w3.org/2000/svg"><rect/></svg>', "image/svg+xml")
    assert "svg-active" not in codes(validate(b))


def test_secret_cannot_be_player_facing(sample):
    recs = sample.entities("secrets")
    recs[0]["audience"] = "player"
    sample.set_entities("secrets", recs)
    assert "schema" in codes(validate(sample))


def test_audience_leak_is_a_warning(sample):
    path = sample.text_entry("intro")["file"]
    sample.files[path] += b"\nAlso [[npc:ritualist]].\n"   # ritualist is GM-only
    diags = validate(sample)
    assert "audience-leak" in warn_codes(diags) and not codes(diags)


def test_unlisted_file_and_unknown_field_warn(sample):
    sample.files["notes/todo.txt"] = b"x"
    sample.manifest["frobnicate"] = 1
    sample.manifest["x-tool"] = {"kept": True}   # extensions are fine
    w = warn_codes(validate(sample))
    assert "unlisted-file" in w and w.count("unknown-field") == 1


def test_missing_file_and_duplicates(sample):
    sample.manifest["text"].append({"id": "intro", "file": "text/gone.md"})
    got = codes(validate(sample))
    assert "missing-file" in got and "duplicate-id" in got


def test_unkeyed_section_warns_and_suggest_finds_it(sample):
    sample.set_keys(sample.entries("keys")[:2])   # drop C3
    assert "unkeyed-section" in warn_codes(validate(sample))
    sug = suggest(sample)
    assert sug == [{"key": "C3", "title": "Vestry Alcove", "text": "text:crypt-key#c3",
                    "node": "map:crypt#room.vestry_alcove"}]


def test_keyed_texts_join(sample):
    kt = {k.key: k for k in keyed_texts(sample)}
    assert kt["C1"].node == "map:crypt#room.entry_hall"
    assert kt["C1"].read_aloud.startswith("The crypt door grinds open")
    assert "pressure plate" in kt["C1"].gm_md


def test_map_parse_error_reported(sample):
    sample.files[sample.map_entry("crypt")["file"]] += b"\nroom {{{\n"
    assert "map-parse" in codes(validate(sample))


def test_without_dungml_map_checks_are_skipped_not_fatal(sample, monkeypatch):
    """ttrpg2 runs on an interpreter without dungml: everything but the
    map checks must still work, and say that it skipped them."""
    import sys
    monkeypatch.setitem(sys.modules, "delve.maps.dsl", None)   # `import dungml` -> ImportError
    sample.manifest["keys"][0]["node"] = "map:crypt#room.nowhere"   # undetectable now
    rep = check(sample)
    assert rep.ok and not rep.maps_checked
    assert warn_codes(rep.diagnostics) == ["maps-unchecked"]
    sample.manifest["keys"][0]["text"] = "text:crypt-key#c9"       # still caught
    assert "dangling-ref" in codes(validate(sample))


def test_requires_version_warning(sample):
    sample.manifest["requires"] = {"dungml": ">=99"}
    assert "requires" in warn_codes(validate(sample))


BOMB = "a: &a [x, x, x, x, x, x, x, x, x]\nb: &b [*a, *a, *a, *a, *a, *a, *a, *a, *a]\nc: &c [*b, *b, *b, *b, *b, *b, *b, *b, *b]\n"


def test_entities_with_yaml_aliases_are_refused(sample):
    """An alias bomb: a few hundred bytes that grow to gigabytes once stored (DEL-152, audit finding 5)."""
    path = sample.set_entities("npcs", sample.entities("npcs"))
    sample.files[path] = f"- id: bomb\n  name: Bomb\n  notes:\n    {BOMB.replace(chr(10), chr(10) + '    ')}".encode()
    diags = validate(sample)
    assert "entities-parse" in codes(diags)
    assert any("alias" in d.message for d in diags if d.code == "entities-parse")
    with pytest.raises(yaml.YAMLError, match="alias"):
        sample.entities("npcs")  # the bundle's own reading refuses it too
