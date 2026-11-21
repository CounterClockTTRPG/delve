"""List the class features whose name a web dictionary lacks (DEL-389).

    python packs/srd35/scripts/feature_names.py [I18N_DIR]

Each row id of the pack's `features.json` (but a prestige class's `requirement` rows, which the sheet doesn't list
as features: the engine words an unmet one) needs a `sheet.d20.feature.<id>` key in each of the web's five dictionaries
(I18N_DIR, by default the checkout's web/src/i18n). Prints one line per missing name, "<language> <id>", and exits 1
when there is any; prints nothing and exits 0 when every name is there.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PACK = Path(__file__).resolve().parents[1]
FEATURES = PACK / "src" / "delve_srd35" / "data" / "features.json"
I18N = PACK.parents[1] / "web" / "src" / "i18n"
LANGUAGES = ("en", "nl", "fr", "de", "lv")
KEY = "sheet.d20.feature.{}"


def feature_ids() -> list[str]:
    """Every row id of `features.json` but the requirements', once each, in table order."""
    rows = json.loads(FEATURES.read_text(encoding="utf-8"))
    return list(dict.fromkeys(row["id"] for cls in rows.values() for row in cls if row["kind"] != "requirement"))


def missing(folder: Path) -> list[tuple[str, str]]:
    """(language, id) for each feature id a dictionary in `folder` has no name (or an empty one) for."""
    ids = feature_ids()
    out = []
    for language in LANGUAGES:
        names = json.loads((folder / f"{language}.json").read_text(encoding="utf-8"))
        out += [(language, id_) for id_ in ids if not names.get(KEY.format(id_))]
    return out


def main(argv: list[str]) -> int:
    folder = Path(argv[1]) if len(argv) > 1 else I18N
    found = missing(folder)
    for language, id_ in found:
        print(f"{language} {id_}")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
