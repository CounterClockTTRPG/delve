"""A ruleset pack's `playable` and `monster_pictures` (DEL-384): left out, a ruleset plays and paints as every pack did
before; a reference pack says it can't be played and reuses the shared monster pictures."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from delve.packs.manifest import PackError, PackManifest

FIXTURES = Path(__file__).parent.parent / "fixtures" / "packs"
OSRIC = Path(__file__).resolve().parents[2] / "packs" / "osric"


def _copy(tmp_path: Path, name: str, extra: str = "") -> Path:
    folder = tmp_path / name
    shutil.copytree(FIXTURES / name, folder)
    if extra:
        manifest = folder / "pack.toml"
        manifest.write_text(manifest.read_text() + extra)
    return folder


def test_playable_and_monster_pictures_default_to_today():
    osric = PackManifest.read(OSRIC)
    assert (osric.playable, osric.monster_pictures) == (True, "paint")


def test_a_reference_pack_reads_as_unplayable_and_reusing_pictures(tmp_path):
    folder = _copy(tmp_path, "test-ruleset", 'playable = false\nmonster_pictures = "reuse"\n')
    manifest = PackManifest.read(folder)
    assert (manifest.playable, manifest.monster_pictures) == (False, "reuse")


def test_monster_pictures_must_be_paint_or_reuse(tmp_path):
    with pytest.raises(PackError, match="monster_pictures"):
        PackManifest.read(_copy(tmp_path, "test-ruleset", 'monster_pictures = "draw"\n'))


def test_playable_must_be_true_or_false(tmp_path):
    with pytest.raises(PackError, match="playable"):
        PackManifest.read(_copy(tmp_path, "test-ruleset", 'playable = "no"\n'))


@pytest.mark.parametrize("field", ["playable = false\n", 'monster_pictures = "reuse"\n'])
def test_playable_and_pictures_are_for_rulesets_only(tmp_path, field):
    with pytest.raises(PackError, match="rulesets only"):
        PackManifest.read(_copy(tmp_path, "test-setting", field))
