"""No Product Identity ships in the SRD 3.5 pack (DEL-384): none of the names the SRD's own legal text designates
Product Identity (OGL 1.0a Section 1(e) and 7), and no Wizards of the Coast trademark, in any file the pack ships,
but the licence and the notice, which must name them."""

from __future__ import annotations

import re
from pathlib import Path

PACK = Path(__file__).resolve().parents[1]

PRODUCT_IDENTITY = (
    "Dungeons & Dragons",
    "D&D",
    "Player's Handbook",
    "Dungeon Master",
    "Monster Manual",
    "d20 System",
    "Wizards of the Coast",
    "Forgotten Realms",
    "Faerûn",
    "Red Wizard of Thay",
    "the City of Union",
    "Heroic Domains of Ysgard",
    "Ever-Changing Chaos of Limbo",
    "Windswept Depths of Pandemonium",
    "Infinite Layers of the Abyss",
    "Tarterian Depths of Carceri",
    "Gray Waste of Hades",
    "Bleak Eternity of Gehenna",
    "Nine Hells of Baator",
    "Infernal Battlefield of Acheron",
    "Clockwork Nirvana of Mechanus",
    "Peaceable Kingdoms of Arcadia",
    "Seven Mounting Heavens of Celestia",
    "Twin Paradises of Bytopia",
    "Blessed Fields of Elysium",
    "Wilderness of the Beastlands",
    "Olympian Glades of Arborea",
    "Concordant Domain of the Outlands",
    "Lady of Pain",
    "Book of Exalted Deeds",
    "Book of Vile Darkness",
    "beholder",
    "gauth",
    "carrion crawler",
    "tanar'ri",
    "baatezu",
    "displacer beast",
    "githyanki",
    "githzerai",
    "mind flayer",
    "illithid",
    "umber hulk",
    "yuan-ti",
)
"""As the SRD's legal text (`Basic Rules and Legal/legal-information.md`) lists them, copied by script."""
MORE = ("AD&D", "Dungeons and Dragons", "illithids", "tanar\u2019ri")
"""Other forms of the same: the first edition's mark, the name spelled out, a plural, the curly apostrophe."""
NOTICES = {PACK / "NOTICE.md", PACK / "src" / "delve_srd35" / "notice.md"}
"""The two files that must name them: the licence with its Section 15, and the notice shown with the book."""
SHIPPED = (".json", ".md", ".py", ".toml", ".txt")
NAMED_TO_SWAP = {("scripts/srd35_extract/kinds.py", "Ever-Changing Chaos of Limbo")}
"""The extractor's swap table names the one Product Identity name the conversion has, to take it out."""


def pattern(names) -> re.Pattern[str]:
    words = sorted((re.escape(n) for n in names), key=len, reverse=True)
    return re.compile(r"(?<![\w&])(?:" + "|".join(words) + r")(?:s|es|'s|’s)?(?![\w&])", re.IGNORECASE)


PI = pattern((*PRODUCT_IDENTITY, *MORE))
SIGIL = re.compile(r"(?<!Snake )\bSigil\b")
"""The city, by its proper name; a sigil (a magic symbol) and the spell *sepia snake sigil* are open content."""


def shipped() -> list[Path]:
    """Every file of the pack that goes public, but its tests (whose fixtures are the SRD's own legal text): the
    manifest, the package, SOURCES.md and the scripts."""
    return sorted(
        p
        for p in [PACK / "pack.toml", PACK / "SOURCES.md", *(PACK / "src").rglob("*"), *(PACK / "scripts").rglob("*")]
        if p.is_file() and p.suffix in SHIPPED and p not in NOTICES
    )


def test_no_shipped_file_names_a_local_path():
    """The pack goes public: no file of it says where the owner keeps things (review, Important 4)."""
    found = [
        f"{path.relative_to(PACK)}:{number}"
        for path in [*shipped(), *NOTICES]
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        if re.search(r"~/|/home/|adnd35|\bocr/", line)
    ]
    assert found == []


def test_no_shipped_file_names_product_identity():
    found = []
    for path in shipped():
        text = " ".join(path.read_text(encoding="utf-8").split())  # a name wrapped across lines too
        for match in [*PI.finditer(text), *SIGIL.finditer(text)]:
            if (str(path.relative_to(PACK)), match.group(0)) not in NAMED_TO_SWAP:
                found.append(f"{path.relative_to(PACK)}: {match.group(0)}")
    assert found == [], "\n".join(found[:40])


def test_the_pi_check_matches_whole_words_any_case():
    for line in ("A Mind Flayer's tentacles.", "BEHOLDER", "two beholders", "an illithid", "D&D", "Faerûn"):
        assert PI.search(line), line
    for line in ("a gauthor", "the sigillum", "bead of force", "DDR", "a d20 roll"):
        assert not PI.search(line), line
    assert SIGIL.search("the city of Sigil") and not SIGIL.search("Sepia Snake Sigil") and not SIGIL.search("a sigil")


def test_the_notices_hold_the_licence_and_its_section_15():
    licence = (PACK / "NOTICE.md").read_text(encoding="utf-8")
    assert "OPEN GAME LICENSE Version 1.0a" in licence and "15. COPYRIGHT NOTICE" in licence
    assert "System Reference Document Copyright 2000-2003, Wizards of the Coast" in " ".join(licence.split())
    assert "DnD-3.5-SRD-Markdown" in licence
