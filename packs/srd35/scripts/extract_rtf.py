"""Add to the SRD 3.5 pack's data what the SRD's original RTF release has and the Markdown conversion lost (DEL-388).

    python -I packs/srd35/scripts/extract_rtf.py RTF_DIR DATA_DIR

RTF_DIR holds the 86 RTFs of archive.org's `dnd35srd` (never in the repo); DATA_DIR is the pack's `data/`, already
made by `extract.py`. It writes `weapons.json` from the weapons table, and adds to `monsters.json` the monsters of CR 5
or less the conversion lacks, sorted by id as `extract.py` sorts; the rows already there stay as they are. The same
RTFs give the same bytes on every run. Exits 2 when RTF_DIR lacks a file it needs.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_rtf import normal
from srd35_extract.common import by_id, write_json
from srd35_extract.rtf import missing_monsters, weapons

__all__ = ["extract", "missing_monsters", "weapons"]


def extract(rtf: Path, data: Path) -> dict[str, int]:
    """Write `weapons.json` and add the missing monsters to `monsters.json` under `data`; the count of each."""
    path = data / "monsters.json"
    monsters = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []
    found = weapons(rtf)
    added = missing_monsters(rtf, {normal(m["name"]) for m in monsters})
    write_json(data / "weapons.json", found)
    write_json(path, by_id([*monsters, *added]))
    return {"weapons": len(found), "monsters added": len(added), "monsters": len(monsters) + len(added)}


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    try:
        counts = extract(Path(argv[1]), Path(argv[2]))
    except FileNotFoundError as missing:
        print(f"extract_rtf: {argv[1]} has no {Path(missing.filename).name}", file=sys.stderr)
        return 2
    for kind, count in counts.items():
        print(f"{kind}: {count}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
