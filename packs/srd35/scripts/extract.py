"""Extract the SRD 3.5 pack's data from the SRD's Markdown conversion (DEL-383).

    python packs/srd35/scripts/extract.py SRC_DIR OUT_DIR

SRC_DIR is the conversion (Obsidian-TTRPG-Community/DnD-3.5-SRD-Markdown at 70a6b26); OUT_DIR
the pack's package (packs/srd35/src/delve_srd35). It writes data/*.json and rules/*.md there, replacing what was
there, the same bytes for the same source. No text is typed or rewritten: what ships is the SRD's own, converted.
Exits 2 when SRC_DIR lacks a file it needs.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from srd35_extract import kinds
from srd35_extract.common import SourceMissing, write_json

KINDS = ("classes", "races", "skills", "feats", "spells", "monsters", "items", "domains")


def extract(src: Path, out: Path) -> dict[str, int]:
    """Write every kind's data and the rules under `out`; the count of each."""
    counts: dict[str, int] = {}
    data = {kind: getattr(kinds, kind)(src) for kind in KINDS}
    kinds.class_list_levels(data["classes"], data["spells"])
    kinds.spells_known(data["classes"])
    rules = kinds.rules(src)
    for kind, rows in data.items():
        write_json(out / "data" / f"{kind}.json", rows)
        counts[kind] = len(rows)
    write_json(out / "data" / "abilities.json", kinds.abilities())
    write_json(out / "data" / "carrying.json", kinds.carrying(rules))
    folder = out / "rules"
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    for name, text in rules:
        (folder / name).write_text(text, encoding="utf-8")
    counts["rules"] = len(rules)
    return counts


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    try:
        counts = extract(Path(argv[1]), Path(argv[2]))
    except SourceMissing as missing:
        print(f"extract: {argv[1]} has no {missing}", file=sys.stderr)
        return 2
    for kind, count in counts.items():
        print(f"{kind}: {count}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
