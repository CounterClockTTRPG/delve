"""The slice's data (DEL-388): domains, XP by Unearthed Arcana and the lists the playable 3.5 engine reads."""

from __future__ import annotations

import re
from fractions import Fraction
from pathlib import Path

from delve_srd35 import data

PACK = Path(__file__).resolve().parents[1]
NO_CR = {"human-warrior-skeleton"}  # the conversion prints its CR as "None"; the SRD gives it 1/3


def _numbers(line: str) -> list[int]:
    return [int(n.replace(",", "")) for n in re.findall(r"\d[\d,]*", line)]


def test_xp_matches_sources_md():
    text = (PACK / "SOURCES.md").read_text(encoding="utf-8")
    flat = " ".join(text.split())
    levels = re.search(r"XP per level, 1st to 20th: ([\d, ]+)\. Beyond", flat).group(1)
    awards = re.search(r"XP per monster, CR 1 to 20: ([\d, ]+)\. Beyond", flat).group(1)
    xp = data.load("xp")
    assert xp["levels"] == _numbers(levels) and len(xp["levels"]) == 20
    assert list(xp["by_cr"].values()) == _numbers(awards) and list(xp["by_cr"]) == [str(n) for n in range(1, 21)]
    assert xp["by_cr"]["1"] == 300 and xp["by_cr"]["20"] == 310000


def test_domains_have_the_war_domain():
    war = next(d for d in data.load("domains") if d["id"] == "war")
    assert war["spells"]["1"].lower() == "magic weapon" and "martial weapon" in war["granted_power"].lower()
    assert war["spells"]["9"] == "Power Word Kill" and list(war["spells"]) == [str(n) for n in range(1, 10)]


def test_every_domain_names_nine_real_spells():
    spells = {s["id"] for s in data.load("spells")}
    domains = data.load("domains")
    assert len(domains) == 22
    for domain in domains:
        assert list(domain["spells"]) == [str(n) for n in range(1, 10)], domain["id"]
        assert domain["granted_power"], domain["id"]
        for name in domain["spells"].values():
            assert re.sub(r"[^a-z0-9]+", "-", name.lower().replace("’", "")).strip("-") in spells, name


def test_the_slice_names_only_real_ids():
    s = data.load("slice")
    for kind in ("skills", "feats", "monsters", "classes", "races"):
        ids = {r["id"] for r in data.load(kind)}
        assert set(s[kind]) <= ids, kind
    assert len(s["skills"]) == 20 and 25 <= len(s["feats"]) <= 35 and 50 <= len(s["monsters"]) <= 70
    assert {"orc", "goblin", "kobold", "wolf", "human-warrior-skeleton"} <= set(s["monsters"])
    assert s["max_level"] == 5 and s["spell_levels"] == [0, 1, 2, 3]
    assert {"weapon-focus", "toughness", "improved-initiative", "alertness", "spell-focus"} <= set(s["feats"])
    for key in ("skills", "feats", "monsters"):
        assert len(set(s[key])) == len(s[key]), key


def test_slice_monsters_are_cr_5_or_less():
    rows = {r["id"]: r for r in data.load("monsters")}
    for id_ in data.load("slice")["monsters"]:
        if id_ in NO_CR:
            continue
        assert Fraction(rows[id_]["cr"]) <= 5, id_


def test_slice_spells_have_their_components():
    """R13: every cleric or wizard spell of levels 0 to 3 says its components (a variant takes its base's)."""
    empty = [s["name"] for s in data.load("spells")
             if any(s["levels"].get(cls, 9) <= 3 for cls in ("cleric", "wizard")) and not s["components"].strip()]  # fmt: skip
    assert empty == []
