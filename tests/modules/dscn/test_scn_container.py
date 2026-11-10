"""Container: both forms, deterministic packing, import hardening (§2, §11)."""
from __future__ import annotations

import io
import json
import zipfile

import pytest

from delve.modules.dscn import Bundle, Limits, ScenarioError, sha256


def _zip(entries: dict[str, bytes], *, symlink: str | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
        if symlink:
            info = zipfile.ZipInfo(symlink)
            info.create_system = 3
            info.external_attr = (0o120777 & 0xFFFF) << 16
            zf.writestr(info, "../../etc/passwd")
    return buf.getvalue()


MANIFEST = json.dumps({"format": "dungml-scenario", "version": 1,
                       "id": "00000000-0000-4000-8000-000000000000",
                       "title": "t", "maps": []}).encode()


def test_zip_and_dir_round_trip(sample, tmp_path):
    data = sample.to_zip()
    again = Bundle.from_zip(data)
    assert again.manifest == sample.manifest
    assert again.files == sample.files
    again.write_dir(tmp_path / "out")
    assert Bundle.from_dir(tmp_path / "out").to_zip() == data


def test_packing_is_deterministic(sample):
    assert sample.to_zip() == Bundle.from_zip(sample.to_zip()).to_zip()
    names = zipfile.ZipFile(io.BytesIO(sample.to_zip())).namelist()
    assert names[0] == "scenario.json"
    assert names[1:] == sorted(names[1:])


def test_images_are_stored_text_is_deflated(sample):
    zf = zipfile.ZipFile(io.BytesIO(sample.to_zip()))
    kinds = {i.filename: i.compress_type for i in zf.infolist()}
    assert kinds["assets/img/ritualist-token.png"] == zipfile.ZIP_STORED
    assert kinds["maps/crypt.dmap"] == zipfile.ZIP_DEFLATED


def test_dotfiles_are_ignored_in_dir_form(sample, tmp_path):
    root = sample.write_dir(tmp_path / "s")
    (root / ".git").mkdir()
    (root / ".git" / "HEAD").write_text("ref")
    (root / ".DS_Store").write_bytes(b"x")
    assert not any(p.startswith(".") for p in Bundle.from_dir(root).files)


@pytest.mark.parametrize("bad", ["../evil.txt", "/etc/passwd", "a/../../b", "C:/x", "a\\b"])
def test_unsafe_paths_rejected(bad):
    with pytest.raises(ScenarioError):
        Bundle.from_zip(_zip({"scenario.json": MANIFEST, bad: b"x"}))


def test_symlink_entries_rejected():
    with pytest.raises(ScenarioError, match="symlink"):
        Bundle.from_zip(_zip({"scenario.json": MANIFEST}, symlink="assets/link"))


def test_symlink_in_directory_rejected(tmp_path):
    (tmp_path / "scenario.json").write_bytes(MANIFEST)
    (tmp_path / "link").symlink_to("/etc/hostname")
    with pytest.raises(ScenarioError, match="symlink"):
        Bundle.from_dir(tmp_path)


def test_size_limits():
    blob = _zip({"scenario.json": MANIFEST, "big.txt": b"a" * 5000})
    with pytest.raises(ScenarioError, match="per-file"):
        Bundle.from_zip(blob, limits=Limits(max_file=1000))
    with pytest.raises(ScenarioError, match="total"):
        Bundle.from_zip(blob, limits=Limits(max_total=1000))
    with pytest.raises(ScenarioError, match="entries"):
        Bundle.from_zip(blob, limits=Limits(max_entries=1))


def test_zip_bomb_ratio_rejected():
    blob = _zip({"scenario.json": MANIFEST, "bomb.txt": b"\0" * (4 * 1024 * 1024)})
    with pytest.raises(ScenarioError, match="ratio"):
        Bundle.from_zip(blob)


@pytest.mark.parametrize("manifest,match", [
    (None, "missing scenario.json"),
    (b"{not json", "not valid JSON"),
    (json.dumps({"format": "dungml-project", "version": 1}).encode(), "unrecognised format"),
    (json.dumps({"format": "dungml-scenario", "version": 4}).encode(), "version"),
])
def test_bad_manifests(manifest, match):
    entries = {"x.txt": b"x"}
    if manifest is not None:
        entries["scenario.json"] = manifest
    with pytest.raises(ScenarioError, match=match):
        Bundle.from_zip(_zip(entries))


def test_not_a_zip():
    with pytest.raises(ScenarioError, match=r"^this is not a \.dscn file \(it isn't a zip archive\)$"):
        Bundle.from_zip(b"definitely not a zip")


def test_mutators_build_a_bundle():
    b = Bundle.new("T")
    b.add_map("one", 'map "One" { grid { bounds 10 x 10 } }', default=True)
    b.add_map("two", 'map "Two" { grid { bounds 10 x 10 } }', default=True)
    assert [m.get("default") for m in b.maps()] == [None, True]  # one default only
    a = b.add_asset("pic", b"\x89PNG\r\n\x1a\nrest", "image/png")
    assert a["sha256"] == sha256(b"\x89PNG\r\n\x1a\nrest") and a["file"] == "assets/pic.png"
    # Re-adding replaces, not duplicates.
    b.add_asset("pic", b"\x89PNG\r\n\x1a\nnew", "image/png")
    assert len(b.entries("assets")) == 1
    b.set_entities("npcs", [{"id": "x", "name": "X"}])
    assert b.entities("npcs") == [{"id": "x", "name": "X"}]
    b.set_entities("npcs", [])
    assert "entities" not in b.manifest and "entities/npcs.yaml" not in b.files


def test_distinct_entries_never_share_a_file():
    b = Bundle.new("T")
    first = b.add_text("a", "one", file="text/x.md")
    second = b.add_text("b", "two", file="text/x.md")
    assert first["file"] != second["file"]
    assert b.read_text(first["file"]) == "one"


def test_many_small_bombs_are_rejected_by_the_whole_archive_ratio():
    """Entries of 1 MB or less skipped the ratio check: 500 of them made a 545 KB zip that inflated to 500 MB in
    memory (DEL-152, audit finding 11). The archive as a whole is held to the ratio too."""
    entries = {"scenario.json": MANIFEST} | {f"f{i}.txt": b"\0" * (1024 * 1024) for i in range(40)}
    with pytest.raises(ScenarioError, match="ratio"):
        Bundle.from_zip(_zip(entries))

