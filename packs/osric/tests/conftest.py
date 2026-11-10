"""The pack's tests import `delve_osric` from its `src`, as the loader does once it is installed."""

import sys
from pathlib import Path

SRC = str(Path(__file__).resolve().parents[1] / "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)
