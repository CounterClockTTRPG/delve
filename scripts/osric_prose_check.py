"""Check that Delve's OSRIC rules text is its own (DEL-300): no passage of it matches the OSRIC 3.0 guides word for word.

    uv run python scripts/osric_prose_check.py ~/roleplaying/osric.tgz

The OSRIC 3.0 Third-Party License lets a product print verbatim only monsters, spells and magic items. The guides'
text comes from the owner's OSRIC engine (`osric/docs/*.md` in the archive); it is read, never copied. Each Markdown
file under `packs/osric/src/delve_osric/rules/` is compared in windows of WINDOW words: any window found in the guides is
reported, and the script fails.
"""

from __future__ import annotations

import re
import sys
import tarfile
from pathlib import Path

RULES = Path(__file__).resolve().parents[1] / "packs" / "osric" / "src" / "delve_osric" / "rules"
WINDOW = 8
"""Words in a row that may not match the guides: a short phrase ("a saving throw vs. poison") may, a sentence not."""


def words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def guides(archive: Path) -> set[tuple[str, ...]]:
    with tarfile.open(archive) as tar:
        text = " ".join(
            tar.extractfile(member).read().decode("utf-8")  # type: ignore[union-attr]
            for member in tar.getmembers()
            if member.name.startswith("osric/docs/") and member.name.endswith(".md")
        )
    seq = words(text)
    return {tuple(seq[i : i + WINDOW]) for i in range(len(seq) - WINDOW + 1)}


def main(archive: str) -> int:
    known = guides(Path(archive).expanduser())
    found = 0
    for path in sorted(RULES.glob("*.md")):
        seq = words(path.read_text("utf-8").split("---", 2)[-1])
        for i in range(len(seq) - WINDOW + 1):
            if tuple(seq[i : i + WINDOW]) in known:
                print(f"{path.name}: {' '.join(seq[i : i + WINDOW])}")
                found += 1
    print(f"{found} passages match the guides" if found else "no passage matches the guides")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "~/roleplaying/osric.tgz"))
