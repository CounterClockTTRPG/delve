"""Test fixtures shared across packages."""
from pathlib import Path

# dungml's samples/ (commit a66a1bb): .dmap maps and the crypt-of-saint-vellis scenario.
SAMPLES: Path = Path(__file__).resolve().parent / "samples"
