from __future__ import annotations

import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

from delve.packs import loader
from delve.packs.loader import load_packs
from delve.packs.transit import PackError, build_pack, install_pack, remove_pack

FIXTURES = Path(__file__).parent.parent / "fixtures" / "packs"
GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@example.com"]


@pytest.fixture(autouse=True)
def _fresh_loader():
    loader.reset()
    yield
    loader.reset()


def _copy(tmp_path: Path, name: str = "source", version: str = "1.0.0") -> Path:
    folder = tmp_path / name
    shutil.copytree(FIXTURES / "test-ruleset", folder)
    if version != "1.0.0":
        manifest = folder / "pack.toml"
        manifest.write_text(manifest.read_text().replace('version = "1.0.0"', f'version = "{version}"'))
    return folder


def _git(folder: Path, *args: str) -> None:
    subprocess.run([*GIT, *args], cwd=folder, check=True, capture_output=True)


def _repo(folder: Path) -> str:
    _git(folder, "init", "-q")
    _git(folder, "add", "-A")
    _git(folder, "commit", "-q", "-m", "pack")
    return folder.resolve().as_uri()


def _names(archive: Path) -> list[str]:
    with zipfile.ZipFile(archive) as z:
        return z.namelist()


def _break_build(folder: Path) -> None:
    pack = folder / "src" / "test_ruleset_pack" / "pack.py"
    pack.write_text(
        pack.read_text().replace(
            "class Pack:", "class Pack:\n    def build(self, root, db):\n        raise RuntimeError('boom')\n"
        )
    )


def test_build_then_install_round_trips(tmp_path: Path):
    source = _copy(tmp_path)
    (source / "tests").mkdir()
    (source / "tests" / "test_x.py").write_text("")
    (source / "pack.db").write_text("x")
    archive = build_pack(source, tmp_path / "out")
    assert archive.name == "test-ruleset-1.0.0.delvepack"
    names = _names(archive)
    assert names[0] == "pack.toml"
    assert "tests/test_x.py" not in names and "pack.db" not in names
    assert not any(n.startswith("data/") for n in names)  # data/.gitkeep is a dot-file
    packs = tmp_path / "packs"
    manifest = install_pack(archive, packs)
    assert manifest.id == "test-ruleset"
    loaded, skipped = load_packs(packs)
    assert [p.manifest.id for p in loaded] == ["test-ruleset"] and skipped == ()
    assert not (packs / "test-ruleset" / "tests").exists()
    assert [p.name for p in packs.iterdir()] == ["test-ruleset"]


def test_install_from_a_folder(tmp_path: Path):
    packs = tmp_path / "packs"
    install_pack(_copy(tmp_path), packs)
    assert [p.manifest.id for p in load_packs(packs)[0]] == ["test-ruleset"]


def test_install_from_a_git_url(tmp_path: Path):
    url = _repo(_copy(tmp_path))
    packs = tmp_path / "packs"
    install_pack(url, packs)
    assert [p.manifest.id for p in load_packs(packs)[0]] == ["test-ruleset"]


def test_install_from_a_git_url_subfolder(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    shutil.copytree(FIXTURES / "test-ruleset", repo / "rules")
    shutil.copytree(FIXTURES / "test-setting", repo / "world")
    url = _repo(repo)
    packs = tmp_path / "packs"
    assert install_pack(url + "#world", packs).id == "test-setting"
    assert [p.name for p in packs.iterdir()] == ["test-setting"]
    with pytest.raises(PackError, match="no folder"):
        install_pack(url + "#../x", packs)


def test_install_refuses_path_escape(tmp_path: Path):
    evil = tmp_path / "evil.delvepack"
    with zipfile.ZipFile(evil, "w") as z:
        z.writestr("pack.toml", "")
        z.writestr("../evil.py", "x")
    packs = tmp_path / "inner" / "packs"
    with pytest.raises(PackError, match="outside the pack"):
        install_pack(evil, packs)
    assert not (tmp_path / "inner" / "evil.py").exists()
    assert list(packs.iterdir()) == []


def test_install_refuses_a_file_not_in_the_manifest(tmp_path: Path):
    archive = build_pack(_copy(tmp_path), tmp_path / "out")
    with zipfile.ZipFile(archive, "a") as z:
        z.writestr("extra.py", "x")
    with pytest.raises(PackError, match="extra.py is not in MANIFEST"):
        install_pack(archive, tmp_path / "packs")


def test_install_refuses_bad_checksum(tmp_path: Path):
    archive = build_pack(_copy(tmp_path), tmp_path / "out")
    altered = tmp_path / "altered.delvepack"
    with zipfile.ZipFile(archive) as src, zipfile.ZipFile(altered, "w") as dst:
        for info in src.infolist():
            data = src.read(info)
            if info.filename.endswith("pack.py"):
                data += b"# changed\n"
            dst.writestr(info.filename, data)
    packs = tmp_path / "packs"
    with pytest.raises(PackError, match="pack.py"):
        install_pack(altered, packs)
    assert list(packs.iterdir()) == []


def test_install_refuses_a_symlink(tmp_path: Path):
    archive = build_pack(_copy(tmp_path), tmp_path / "out")
    link = zipfile.ZipInfo("link.py")
    link.external_attr = 0o120777 << 16
    with zipfile.ZipFile(archive, "a") as z:
        z.writestr(link, "/etc/passwd")
    with pytest.raises(PackError, match="symlink"):
        install_pack(archive, tmp_path / "packs")


def test_failed_install_keeps_the_old_version(tmp_path: Path):
    packs = tmp_path / "packs"
    install_pack(_copy(tmp_path), packs)
    (packs / "test-ruleset" / "pack.db").write_text("v1 data")
    v2 = _copy(tmp_path, "v2", "1.1.0")
    _break_build(v2)
    with pytest.raises(PackError, match="boom"):
        install_pack(v2, packs)
    assert (packs / "test-ruleset" / "pack.db").read_text() == "v1 data"
    assert 'version = "1.0.0"' in (packs / "test-ruleset" / "pack.toml").read_text()
    assert [p.name for p in packs.iterdir()] == ["test-ruleset"]


def test_reinstall_replaces_atomically(tmp_path: Path):
    packs = tmp_path / "packs"
    install_pack(_copy(tmp_path), packs)
    install_pack(_copy(tmp_path, "v2", "1.1.0"), packs)
    loaded, _ = load_packs(packs)
    assert loaded[0].manifest.version == "1.1.0"
    assert [p.name for p in packs.iterdir()] == ["test-ruleset"]


def test_remove_pack(tmp_path: Path):
    packs = tmp_path / "packs"
    install_pack(_copy(tmp_path), packs)
    remove_pack("test-ruleset", packs)
    assert list(packs.iterdir()) == []
    with pytest.raises(PackError, match="nope"):
        remove_pack("nope", packs)
