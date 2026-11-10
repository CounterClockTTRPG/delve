"""Core names no ruleset or setting it doesn't ship (DEL-307): AD&D, Greyhawk and the Forgotten Realms are packs an
install may have, so Delve's code, prompts, help and words never name them, but where the allow-list says why. The
migrations hold the past; tests and the built web app (`web/static`) aren't Delve's sources."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = (ROOT / "src" / "delve", ROOT / "web" / "src")
NAMES = re.compile(r"AD&D|Greyhawk|Forgotten Realms|Faer[uû]n", re.IGNORECASE)
LEFT_OUT = re.compile(r"/(static|__pycache__|migrations/versions)/|\.test\.tsx?$|/testing\.tsx?$")
SUFFIXES = {".py", ".md", ".json", ".ts", ".tsx", ".css", ".html", ".toml", ".txt", ".map"}

ALLOWED = {
    "src/delve/modules/books/prompts/metadata.md": (
        "the metadata pass reads a published module: it recognises the game and the world the book names, by the names "
        "it prints (`system_name`, `setting`, the edition tags)"
    ),
    "src/delve/modules/books/prompts/entities.md": "the module format's `stats.adnd2e` key, said in words",
    "src/delve/modules/dscn/scenario.schema.json": "the module format's schema, shared with DungML: its examples",
}


def _named() -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for source in SOURCES:
        for path in source.rglob("*"):
            relative = path.relative_to(ROOT).as_posix()
            if not path.is_file() or path.suffix not in SUFFIXES or LEFT_OUT.search("/" + relative):
                continue
            hits = sorted({match.group(0) for match in NAMES.finditer(path.read_text("utf-8", errors="replace"))})
            if hits:
                found[relative] = hits
    return found


def test_core_names_no_pack_but_where_it_says_why():
    named = _named()
    assert {path: hits for path, hits in named.items() if path not in ALLOWED} == {}


def test_every_allowance_is_still_needed():
    named = _named()
    assert [path for path in ALLOWED if path not in named] == []
