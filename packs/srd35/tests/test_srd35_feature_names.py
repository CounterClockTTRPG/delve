"""Every class feature row's id has its name in each of the web's five dictionaries (DEL-389): the script that lists
the missing ones lists none."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "feature_names.py"
I18N = Path(__file__).resolve().parents[3] / "web" / "src" / "i18n"


@pytest.mark.skipif(not I18N.is_dir(), reason="the web's dictionaries are not beside this pack")
def test_every_feature_has_a_name_in_each_language():
    done = subprocess.run([sys.executable, str(SCRIPT), str(I18N)], capture_output=True, text=True, check=False)
    assert (done.returncode, done.stdout, done.stderr) == (0, "", "")
