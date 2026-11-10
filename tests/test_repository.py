"""What the repository may hold: never the owner's map picture, and no large picture at all."""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PICTURES = (".jpg", ".jpeg", ".png", ".webp", ".tif")
MAX_PICTURE_BYTES = 2 * 1024 * 1024


def _tracked() -> list[str]:
    listed = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True)
    return [name for name in listed.stdout.decode().split("\0") if name]


def test_no_tracked_picture_is_the_owners_map_or_large():
    pictures = [name for name in _tracked() if Path(name).suffix.lower() in PICTURES]
    assert pictures, "the repository's screenshots are pictures: git ls-files found none"
    assert [name for name in pictures if Path(name).name.lower().startswith("greyhawk")] == []
    large = [name for name in pictures if (ROOT / name).is_file() and (ROOT / name).stat().st_size > MAX_PICTURE_BYTES]
    assert large == []


def test_gitignore_refuses_the_owners_map():
    ignored = subprocess.run(["git", "check-ignore", "-q", "greyhawk.jpg"], check=False, cwd=ROOT)
    assert ignored.returncode == 0
