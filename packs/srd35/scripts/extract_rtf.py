"""Add to the SRD 3.5 pack's data what the SRD's original RTF release has and the Markdown conversion lost (DEL-388).

    python -I packs/srd35/scripts/extract_rtf.py RTF_DIR DATA_DIR [SRD_DIR]

RTF_DIR holds the 86 RTFs of archive.org's `dnd35srd` (never in the repo); DATA_DIR is the pack's `data/`, already
made by `extract.py`. It writes `weapons.json` from the weapons table, and adds to `monsters.json` the monsters of CR 5
or less the conversion lacks, sorted by id as `extract.py` sorts. Then (DEL-389) it completes every row a stat block
has from that block (`srd35_extract.rtf.qualities`): the special qualities the conversion lost with its link text, a
blank level adjustment, the "… AS CHARACTERS" race traits, and the damage reduction, spell resistance, regeneration,
fast healing, resistances and immunities as keys. Rows no block has keep their fields. Then (DEL-389 part 3) the
true dragons by age, a full stat block each from the colour's age tables (`srd35_extract.families.dragons`), take the
place of the conversion's rows of the same id, and each family's parent row names its variants (`variants`). With the
magic items' RTFs in RTF_DIR, it writes `magic_tables.json`, the random magic item tables (`srd35_extract.magic`),
each row naming its `items.json`, `spells.json` or `weapons.json` entry where one matches. The same RTFs give the same
bytes on every run. Then (DEL-389 part 4), with `classes.json` in DATA_DIR and PrestigeClasses.rtf in RTF_DIR, a class
the conversion left without a level table (the mystic theurge's, a broken grid) gets its levels from the RTF's
(`srd35_extract.rtf.class_levels`). SRD_DIR, the SRD Markdown copy `extract.py` reads, stands in for an RTF qualities
line that is garbled (the tojanidas'); the pack's data is made with it. Exits 2 when RTF_DIR lacks a file it needs.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_rtf import normal
from srd35_extract.common import by_id, write_json
from srd35_extract.families import dragons, variants
from srd35_extract.magic import FILES as MAGIC_FILES
from srd35_extract.magic import Names, magic_tables, unresolved
from srd35_extract.rtf import CLASS_FILE, DEFENCES, class_levels, missing_monsters, qualities, weapons

__all__ = ["class_tables", "dragons", "extract", "magic", "missing_monsters", "qualities", "variants", "weapons"]


def _rows(path: Path) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []


def magic(rtf: Path, data: Path, weapons: list[dict[str, Any]]) -> tuple[dict[str, Any], list[str]]:
    """The random magic item tables (`srd35_extract.magic`), their rows naming `data`'s items and spells and
    `weapons`; and the rows that name none."""
    tables = magic_tables(rtf, Names(_rows(data / "items.json"), _rows(data / "spells.json"), weapons))
    return tables, unresolved(tables)


def class_tables(rtf: Path, data: Path) -> int | None:
    """Fill `data`'s `classes.json` classes that have no levels from their RTF tables; how many were filled, None when
    there is no `classes.json` or no prestige classes' RTF (the fixture has neither). A class the RTF lacks a table
    for stays as it is."""
    path = data / "classes.json"
    if not path.is_file() or not (rtf / CLASS_FILE).is_file():
        return None
    classes = json.loads(path.read_text(encoding="utf-8"))
    filled = 0
    for row in classes:
        if not row["levels"] and (levels := class_levels(rtf, row["name"])):
            row["levels"] = levels
            filled += 1
    write_json(path, classes)
    return filled


def extract(rtf: Path, data: Path, srd: Path | None = None) -> dict[str, int]:
    """Write `weapons.json`, add the missing monsters to `monsters.json` under `data` and complete its rows (a garbled
    RTF qualities line from the SRD Markdown copy at `srd`, when given); the count of each, of the fields completed
    and of the rows with each of the keys `qualities` adds."""
    path = data / "monsters.json"
    monsters = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []
    found = weapons(rtf)
    added = missing_monsters(rtf, {normal(m["name"]) for m in monsters})
    before = by_id([*monsters, *added])
    completed = qualities(rtf, before, srd)
    by_age = dragons(rtf)
    aged = {row["id"]: row for row in by_age}
    after = variants(by_id([*(aged.pop(row["id"], row) for row in completed), *aged.values()]))
    write_json(data / "weapons.json", found)
    write_json(path, after)
    magic_found = magic(rtf, data, found) if (rtf / MAGIC_FILES[0]).is_file() else None  # the fixture has none
    if magic_found:
        write_json(data / "magic_tables.json", magic_found[0])
    counts = {"weapons": len(found), "monsters added": len(added), "monsters": len(after),
              "dragons by age": len(by_age), "families": sum("variants" in row for row in after)}  # fmt: skip
    changed = [(old, new) for old, new in zip(before, completed, strict=True) if old != new]
    for field in ("special_qualities", "special_attacks", "space_reach", "level_adjustment", "text"):
        counts[f"{field} completed"] = sum(old.get(field) != new.get(field) for old, new in changed)
    for key in DEFENCES:
        counts[f"with {key}"] = sum(key in row for row in after)
    if magic_found:
        counts["magic tables"] = len(magic_found[0])
        counts["magic rows naming no entry"] = len(magic_found[1])
    if (filled := class_tables(rtf, data)) is not None:
        counts["class tables filled"] = filled
    return counts


def main(argv: list[str]) -> int:
    if len(argv) not in (3, 4):
        print(__doc__, file=sys.stderr)
        return 2
    try:
        counts = extract(Path(argv[1]), Path(argv[2]), Path(argv[3]) if len(argv) == 4 else None)
    except FileNotFoundError as missing:
        print(f"extract_rtf: {argv[1]} has no {Path(missing.filename).name}", file=sys.stderr)
        return 2
    for kind, count in counts.items():
        print(f"{kind}: {count}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
