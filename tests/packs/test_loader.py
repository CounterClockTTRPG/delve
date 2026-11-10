from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

from delve.config import Config
from delve.packs import loader
from delve.packs.loader import load_packs

FIXTURES = Path(__file__).parent.parent / "fixtures" / "packs"


@pytest.fixture(autouse=True)
def _fresh_loader():
    loader.reset()
    yield
    loader.reset()


@pytest.fixture
def packs(tmp_path: Path) -> Path:
    folder = tmp_path / "packs"
    shutil.copytree(FIXTURES / "test-ruleset", folder / "test-ruleset")
    return folder


def _edit(folder: Path, old: str, new: str) -> None:
    manifest = folder / "pack.toml"
    manifest.write_text(manifest.read_text().replace(old, new))


def test_loads_a_ruleset_and_a_setting_pack(tmp_path: Path):
    folder = tmp_path / "packs"
    shutil.copytree(FIXTURES / "test-ruleset", folder / "test-ruleset")
    shutil.copytree(FIXTURES / "test-setting", folder / "test-setting")
    loaded, skipped = load_packs(folder)
    assert skipped == ()
    assert [p.manifest.id for p in loaded] == ["test-ruleset", "test-setting"]
    ruleset, setting = loaded
    assert ruleset.entry.ruleset(ruleset.root).id == "test-ruleset"
    assert setting.entry.setting(setting.root, frozenset()).id == "test-setting"
    assert setting.manifest.fact_categories == frozenset({"place"})


def _no_manifest(folder: Path) -> None:
    (folder / "pack.toml").unlink()


def _bad_kind(folder: Path) -> None:
    _edit(folder, 'kind = "ruleset"', 'kind = "spell"')


def _bad_api(folder: Path) -> None:
    _edit(folder, "delve_api = 1", "delve_api = 2")


def _bad_entry(folder: Path) -> None:
    _edit(folder, "test_ruleset_pack.pack:PACK", "test_ruleset_pack.nowhere:PACK")


def _same_id(folder: Path) -> None:
    shutil.copytree(folder.parent / "test-ruleset", folder.parent / "zz-copy")


@pytest.mark.parametrize(
    ("break_it", "reason"),
    [
        (_no_manifest, "no pack.toml"),
        (_bad_kind, "kind 'spell'"),
        (_bad_api, "delve_api 2; this Delve reads 1"),
        (_bad_entry, "cannot be imported"),
        (_same_id, "id 'test-ruleset' is already used"),
    ],
    ids=["no-manifest", "bad-kind", "bad-api", "import-error", "same-id"],
)
def test_a_broken_pack_is_skipped_and_named(packs: Path, break_it, reason: str, caplog):
    shutil.copytree(FIXTURES / "test-setting", packs / "test-setting")
    broken = packs / "aa-broken"
    if break_it is _same_id:
        broken = packs / "zz-copy"
        shutil.copytree(FIXTURES / "test-ruleset", broken)
    else:
        shutil.copytree(FIXTURES / "test-ruleset", broken)
        shutil.rmtree(packs / "test-ruleset")
        shutil.copytree(FIXTURES / "test-ruleset", packs / "test-ruleset")
        break_it(broken)
    loaded, skipped = load_packs(packs)
    assert [p.manifest.id for p in loaded] == ["test-ruleset", "test-setting"]
    assert len(skipped) == 1
    assert skipped[0].folder == broken.resolve()
    assert reason in skipped[0].reason
    assert broken.name in caplog.text


def test_a_package_name_taken_by_delve_is_refused(packs: Path):
    _edit(packs / "test-ruleset", 'package = "test_ruleset_pack"', 'package = "delve"')
    loaded, skipped = load_packs(packs)
    assert loaded == ()
    assert len(skipped) == 1
    assert "package 'delve'" in skipped[0].reason


def test_no_packs_folder_is_no_packs(tmp_path: Path):
    assert load_packs(tmp_path / "none") == ((), ())


def test_packs_are_loaded_once_per_folder_until_reset(packs: Path):
    first = load_packs(packs)
    assert load_packs(packs) is first
    loader.reset()
    assert load_packs(packs) is not first


def test_packs_dir_is_under_the_data_dir(tmp_path: Path):
    assert Config(data_dir=tmp_path).packs_dir == tmp_path / "packs"


def test_two_packs_with_one_package_name_skip_the_second(packs: Path):
    shutil.copytree(FIXTURES / "test-ruleset", packs / "zz-other")
    _edit(packs / "zz-other", 'id = "test-ruleset"', 'id = "other-ruleset"')
    loaded, skipped = load_packs(packs)
    assert [p.manifest.id for p in loaded] == ["test-ruleset"]
    assert len(skipped) == 1
    assert "package 'test_ruleset_pack' is already used by test-ruleset" in skipped[0].reason


def test_after_reset_a_new_folder_imports_its_own_copy(tmp_path: Path):
    for name in ("one", "two"):
        shutil.copytree(FIXTURES / "test-ruleset", tmp_path / name / "test-ruleset")
    (first,), _ = load_packs(tmp_path / "one")
    loader.reset()
    (second,), _ = load_packs(tmp_path / "two")
    where = sys.modules["test_ruleset_pack.pack"].__file__
    assert Path(where).is_relative_to(tmp_path / "two")
    assert type(first.entry) is not type(second.entry)
