"""Scenario metadata (spec §3.1): schema shapes + the semantic checks the
schema can't express."""
from __future__ import annotations

import pytest
from tests.modules.dscn.scn_helpers import codes, warn_codes

from delve.modules.dscn import normalise_metadata, parse_timestamp, render_html, validate


def test_sample_metadata_normalises(sample):
    md = normalise_metadata(sample.manifest)
    assert md["release"]["version"] == "1.1.0"
    assert md["party"]["levels"] == {"min": 1, "max": 3, "recommended": 2}
    assert md["duration"]["sessions"] == {"min": 1, "max": 1, "recommended": 1}
    assert md["license"]["spdx"] == "CC0-1.0"
    assert [a["role"] for a in md["authors"]] == ["author", "cartographer"]


def test_short_forms_are_valid_and_expand(sample):
    m = sample.manifest
    m["authors"] = ["Gary", {"name": "Ann", "role": "editor"}]
    m["party"] = {"size": 4, "levels": {"min": 2, "max": 4}}
    m["license"] = "All rights reserved"
    assert validate(sample) == []
    md = normalise_metadata(m)
    assert md["authors"][0] == {"name": "Gary", "role": "author"}
    assert md["party"]["size"] == {"min": 4, "max": 4, "recommended": 4}
    assert md["license"] == {"name": "All rights reserved"}


@pytest.mark.parametrize("field,value", [
    ("release", {"version": "1.2"}),                    # not semver
    ("release", {"date": "2026-10-17"}),                # version required
    ("language", "english"),
    ("party", {"size": 0}),                             # at least 1
    ("party", {"levels": {"min": 1}}),                  # max required
    ("created", "2026-10-17T10:00:00"),                 # no offset
    ("created", "17/10/2026"),
    ("authors", []),
    ("authors", [{"role": "author"}]),                  # name required
    ("homepage", "ftp://example.com"),
    ("cover", "images/cover.png"),                      # must be an asset ref
    ("tags", ["a", "a"]),
    ("license", {"url": "https://x.y"}),                # needs spdx or name
])
def test_schema_rejects(sample, field, value):
    sample.manifest[field] = value
    assert "schema" in codes(validate(sample)), (field, value)


@pytest.mark.parametrize("party,msg", [
    ({"levels": {"min": 5, "max": 3}}, "min 5 is greater than max 3"),
    ({"size": {"min": 3, "max": 5, "recommended": 8}}, "recommended 8 is outside 3–5"),
])
def test_ranges_are_ordered(sample, party, msg):
    sample.manifest["party"] = party
    errs = [d for d in validate(sample) if d.code == "metadata-range"]
    assert errs and msg in errs[0].message


def test_timestamps_must_be_real_and_ordered(sample):
    sample.manifest["created"] = "2026-02-30"            # matches the pattern, not the calendar
    assert "metadata-timestamp" in codes(validate(sample))
    sample.manifest["created"] = "2026-10-18T00:00:00+02:00"
    sample.manifest["updated"] = "2026-10-17T21:00:00Z"   # earlier, once in UTC
    assert any("earlier than created" in d.message for d in validate(sample))
    sample.manifest["updated"] = "2026-10-17T22:30:00Z"
    assert "metadata-timestamp" not in codes(validate(sample))
    assert parse_timestamp("2026-10-17") .isoformat() == "2026-10-17T00:00:00+00:00"


def test_cover_must_be_a_player_image(sample):
    sample.add_asset("map-pdf", b"%PDF-1.4 x", "application/pdf")
    sample.manifest["cover"] = "asset:map-pdf"
    assert "metadata-cover" in codes(validate(sample))
    sample.manifest["cover"] = "asset:nope"
    assert "dangling-ref" in codes(validate(sample))
    sample.manifest["cover"] = "asset:ritualist-token"
    sample.entries("assets")[0]["audience"] = "gm"
    assert "audience-leak" in warn_codes(validate(sample))


def test_unknown_metadata_keys_warn_not_fail(sample):
    """Forward compatibility: a newer writer's field is a warning here."""
    sample.manifest["party"]["players"] = 4
    diags = validate(sample)
    assert not codes(diags) and warn_codes(diags) == ["unknown-field"]


def test_moved_fields_warn_once_with_a_pointer(sample):
    sample.manifest["levels"] = "1-3"
    sample.manifest["revision"] = 2
    w = [d for d in validate(sample) if d.severity == "warning"]
    assert sorted(d.code for d in w) == ["metadata-moved", "metadata-moved"]
    assert any("party.levels" in d.message for d in w)


def test_render_shows_metadata(sample):
    html = render_html(sample)
    assert "by dungml samples" in html and "v1.1.0" in html
    assert "levels 1–3 (best 2)" in html and "players 3–6 (best 4)" in html
    assert "AD&amp;D 2nd Edition" in html and "Content warnings: human remains" in html
