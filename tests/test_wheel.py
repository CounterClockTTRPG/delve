import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "src/delve/web/static"


def test_wheel_contains_data_files(tmp_path):
    if not STATIC.is_dir():
        pytest.skip("src/delve/web/static doesn't exist: run `make build` first")
    uv = shutil.which("uv")
    if uv is None:
        pytest.skip("uv is not on PATH")
    subprocess.run([uv, "build", "--wheel", "-o", str(tmp_path)], check=True, cwd=ROOT, capture_output=True)
    (wheel,) = tmp_path.glob("delve-*.whl")
    names = set(zipfile.ZipFile(wheel).namelist())

    assert "delve/maps/dsl/grammar.lark" in names
    assert any(n.startswith("delve/maps/dsl/includes/") and n.endswith(".dmap") for n in names)
    assert "delve/modules/dscn/scenario.schema.json" in names
    assert "delve/dm/prompt/dm.md" in names
    assert "delve/web/static/index.html" in names
    # reference/house-rules/, the general rules any table may import: in the wheel inside the package. The homebrew
    # races, classes and items are AD&D 2e's, in its pack (DEL-307).
    assert "delve/reference/house-rules/general.md" in names
    assert [n for n in names if n.startswith("delve/reference/house-rules/")] == ["delve/reference/house-rules/general.md"]
    # web/src/help/topics/, which Ask the DM reads (DEL-221).
    assert "delve/help/topics/run-a-session.md" in names
    # Delve ships its own setting, Aun, and no other ruleset's or setting's files (DEL-307): no 2e, no Greyhawk, no Realms,
    # no reference.db snapshots.
    assert "delve/setting/data/aun/pages/hask.md" in names and "delve/setting/data/aun/reaches.map" in names
    shipped = [n for n in names if any(word in n.lower() for word in ("adnd", "greyhawk", "realms", "reference/snapshots"))]
    assert shipped == []
