"""CLI round trips, rendering, asset inlining and `.dmapproj` upgrade."""
from __future__ import annotations

import io
import json
import zipfile

import delve.maps.dsl as dungml

from tests.modules.dscn.scn_helpers import SAMPLE

from delve.modules.dscn import (
    Bundle,
    analyse_map,
    bundle_resolver,
    inline_marker_images,
    render_html,
    upgrade_dmapproj,
    validate,
)
from delve.modules.dscn.cli import main


def test_pack_unpack_validate(tmp_path, capsys):
    out = tmp_path / "s.dscn"
    assert main(["pack", str(SAMPLE), str(out)]) == 0
    assert main(["validate", str(out)]) == 0
    assert main(["unpack", str(out), str(tmp_path / "d")]) == 0
    assert Bundle.load(tmp_path / "d").files == Bundle.load(out).files


def test_pack_refuses_invalid_and_strips_sources(sample, tmp_path):
    root = sample.write_dir(tmp_path / "s")
    sample.add_asset("pdf", b"%PDF-1.4 fake", "application/pdf", role="source")
    sample.write_dir(root)
    out = tmp_path / "s.dscn"
    assert main(["pack", str(root), str(out)]) == 0
    assert Bundle.load(out).asset_entry("pdf") is None          # R8: opt-in
    assert main(["pack", str(root), str(out), "--include-sources"]) == 0
    assert Bundle.load(out).asset_entry("pdf") is not None
    (root / "maps" / "crypt.dmap").write_text("garbage {{{")
    assert main(["pack", str(root), str(out)]) == 1


def test_new_keys_convert(tmp_path, capsys):
    root = tmp_path / "s"
    assert main(["new", str(root), "--title", "Module"]) == 0
    mod = tmp_path / "WGR1-module.md"
    mod.write_text("# Tower\n\n### W101. Guard Post\n\nDwarves.\n")
    assert main(["convert-module", str(mod), "-o", str(root), "--id", "wgr1"]) == 0
    b = Bundle.load(root)
    assert "{#w101}" in b.read_text(b.text_entry("wgr1")["file"])
    capsys.readouterr()
    assert main(["keys", str(root)]) == 0   # no map -> nothing to suggest
    assert json.loads(capsys.readouterr().out) == []


def test_render_html(sample):
    html = render_html(sample)
    assert html.startswith("<!doctype html>")
    assert 'id="text-crypt-key-c2"' in html and "{#c2}" not in html
    assert "<blockquote>" in html and "<svg" in html
    assert 'href="#npc-ritualist"' in html and ">Brother Kael<" in html
    assert html.count("data:image/png;base64,") == 3   # cover + marker + inline image


def test_render_escapes_raw_html(sample):
    path = sample.text_entry("intro")["file"]
    sample.files[path] += b"\n<script>alert(1)</script>\n"
    html = render_html(sample)
    assert "<script>alert(1)" not in html and "&lt;script&gt;" in html


def test_marker_inlining_respects_audience(sample):
    info = analyse_map(sample, "crypt")
    resolve = bundle_resolver(sample)
    assert inline_marker_images(info.model, resolve, players=True) == 1   # asset is player
    a = sample.entries("assets")[0]
    a["audience"] = "gm"
    info = analyse_map(sample, "crypt")
    assert inline_marker_images(info.model, resolve, players=True) == 0
    marker = next(m for m in info.model.markers if m.name == "ritualist")
    assert marker.image is None
    assert "asset:" not in dungml.render(info.model)


def test_upgrade_dmapproj():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("manifest.json", json.dumps({
            "format": "dungml-project", "version": 1, "name": "Old",
            "maps": [{"name": "core.dmap", "file": "maps/0000_core.dmap"},
                     {"name": "Keep", "file": "maps/0001_keep.dmap"}]}))
        zf.writestr("maps/0000_core.dmap", dungml.library_source("core.dmap"))
        zf.writestr("maps/0001_keep.dmap",
                    'include "core.dmap"\ninclude "crypt.dmap"\n'
                    'map "Keep" { grid { bounds 10 x 10 } }\n'
                    'room "hall" { rect 1,1 4 x 4 }\n')
    b = upgrade_dmapproj(buf.getvalue())
    assert b.title == "Old" and b.default_map()["name"] == "Keep"
    assert {m["name"] for m in b.maps("library")} == {"core.dmap", "crypt.dmap"}
    assert validate(b) == []
