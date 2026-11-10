import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
LINT_IMPORTS = Path(sys.executable).parent / "lint-imports"

# The probes below write files into src/delve that break a contract on purpose, and every lint run reads the whole
# tree: under `pytest -n auto` they run on one worker, in turn, so no run sees another's probe (DEL-242). Needs
# `--dist loadgroup`, as `make ci` passes.
pytestmark = pytest.mark.xdist_group("import-probes")


def lint_imports() -> subprocess.CompletedProcess[str]:
    return subprocess.run([str(LINT_IMPORTS), "--no-cache"], check=False, cwd=ROOT, capture_output=True, text=True)


def test_import_contracts_hold():
    result = lint_imports()
    assert result.returncode == 0, result.stdout + result.stderr


def test_contract_catches_violation():
    probe = ROOT / "src/delve/domain/_probe.py"
    probe.write_text("import delve.web  # noqa: F401\n")
    try:
        result = lint_imports()
        assert result.returncode != 0, result.stdout
        assert "delve.domain._probe -> delve.web" in result.stdout
    finally:
        probe.unlink()


@pytest.mark.parametrize("package", ["conversions", "play", "dm", "storage", "modules"])
def test_only_the_web_and_the_cli_import_the_novels(package):
    probe = ROOT / f"src/delve/{package}/_probe.py"
    probe.write_text("import delve.novels.material  # noqa: F401\n")
    try:
        result = lint_imports()
        assert result.returncode != 0, result.stdout
        assert f"delve.{package}._probe -> delve.novels.material" in result.stdout
    finally:
        probe.unlink()


@pytest.mark.parametrize("package", ["conversions", "play", "dm", "storage", "modules", "novels"])
def test_only_the_web_and_the_cli_import_the_histories(package):
    probe = ROOT / f"src/delve/{package}/_probe.py"
    probe.write_text("import delve.histories.material  # noqa: F401\n")
    try:
        result = lint_imports()
        assert result.returncode != 0, result.stdout
        assert f"delve.{package}._probe -> delve.histories.material" in result.stdout
    finally:
        probe.unlink()


# The settings plan's new modules: no setting is special in generic code. A file not there yet is skipped.
NEW_SETTING_CODE = (
    "src/delve/play/setting_layer.py",
    "src/delve/setting/text.py",
    "src/delve/play/proposals.py",
    "src/delve/play/setting_maps.py",
    "src/delve/web/routes/setting_area.py",
    "src/delve/web/routes/setting_world_maps.py",
)


def test_new_setting_code_names_no_setting():
    paths = [ROOT / name for name in NEW_SETTING_CODE]
    paths += sorted(path for path in (ROOT / "web/src/setting").rglob("*") if path.is_file())
    naming = [
        str(path.relative_to(ROOT)) for path in paths if path.is_file() and "greyhawk" in path.read_text().lower()
    ]
    assert naming == []


def test_only_auth_reads_cookies():
    """Who is asking is decided in `delve.web.auth` alone (players and tavern Task C2): no other module of the web
    reads a request's cookies."""
    web = ROOT / "src/delve/web"
    readers = sorted(
        str(path.relative_to(web)) for path in web.rglob("*.py") if ".cookies" in path.read_text() and path.name != "auth.py"
    )
    assert readers == []
