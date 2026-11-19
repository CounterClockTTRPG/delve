"""Check the SRD 3.5 pack's data against the SRD's original RTF release (DEL-383). A report, not a test.

    python -I packs/srd35/scripts/check_rtf.py RTF_DIR DATA_DIR

RTF_DIR holds the 86 RTFs of archive.org's `dnd35srd` (never in the repo); DATA_DIR is the pack's `data/`. For the
spells, feats, skills and monsters it prints the names only in the pack's data, the names only in the RTFs, and 20
entries (seed 3835) compared field by field. The RTFs are untrusted input: they are only read as text.
"""

from __future__ import annotations

import json
import random
import re
import sys
from pathlib import Path

SEED = 3835
SCHOOLS = ("Abjuration", "Conjuration", "Divination", "Enchantment", "Evocation", "Illusion", "Necromancy",
           "Transmutation", "Universal")  # fmt: skip


def rtf_text(raw: str) -> str:
    """The text of an RTF document: its destinations (font and colour tables, styles, info) dropped, paragraphs as
    lines, `\\'hh` and `\\uN` as their characters."""
    out: list[str] = []
    skip_depth: list[int] = []
    depth = 0
    i = 0
    while i < len(raw):
        c = raw[i]
        if c == "{":
            depth += 1
            if raw.startswith("{\\*", i) or re.match(r"\{\\(fonttbl|colortbl|stylesheet|info|listtable|listoverridetable|"
                                                     r"rsidtbl|generator|xmlnstbl|pict|themedata|colorschememapping|"
                                                     r"latentstyles|datastore)", raw[i:]):  # fmt: skip
                skip_depth.append(depth)
            i += 1
        elif c == "}":
            if skip_depth and skip_depth[-1] == depth:
                skip_depth.pop()
            depth -= 1
            i += 1
        elif c == "\\":
            m = re.match(r"\\([a-z]+)(-?\d+)? ?|\\'([0-9a-f]{2})|\\(.)", raw[i:], flags=re.IGNORECASE)
            if not m:
                i += 1
                continue
            i += m.end()
            if skip_depth:
                continue
            word, number, hexa, symbol = m.groups()
            if hexa:
                out.append(bytes([int(hexa, 16)]).decode("cp1252", errors="replace"))
            elif word in ("par", "line", "row"):
                out.append("\n")
            elif word in ("tab", "cell"):
                out.append("\t")
            elif word == "u" and number:
                out.append(chr(int(number) % 65536))
                if i < len(raw) and raw[i] == "?":
                    i += 1
            elif symbol in ("\\", "{", "}"):
                out.append(symbol)
            elif symbol == "~":
                out.append(" ")
        else:
            if not skip_depth and c not in "\r\n":
                out.append(c)
            i += 1
    return "".join(out)


def lines(folder: Path, pattern: str) -> list[str]:
    found: list[str] = []
    for path in sorted(folder.glob(pattern)):
        text = rtf_text(path.read_text(encoding="latin-1"))
        found.extend("\t".join(" ".join(c.split()) for c in line.split("\t")).strip("\t") for line in text.splitlines())
    return [line for line in found if line.strip()]


def flat(line: str) -> str:
    return " ".join(line.replace("\t", " ").split())


def spells(folder: Path) -> dict[str, dict[str, str]]:
    """Each spell of the Spells*.rtf by name, with its fields: a name line, a school line, then `Level:`."""
    text = [flat(line) for line in lines(folder, "Spells*.rtf")]
    found: dict[str, dict[str, str]] = {}
    for n, line in enumerate(text):
        if not line.startswith("Level:") or n < 2:
            continue
        school = text[n - 1]
        name = text[n - 2] if school.split(" ")[0] in SCHOOLS else text[n - 1]
        fields: dict[str, str] = {}
        for after in text[n : n + 12]:
            field = re.match(r"(Level|Components|Casting Time|Range|Targets?|Area|Effect|Duration|Saving Throw|"
                             r"Spell Resistance):\s*(.*)", after)  # fmt: skip
            if not field:
                break  # the description: the spell's fields have ended
            fields.setdefault(field.group(1).lower().removesuffix("s") if field.group(1) == "Targets" else
                              field.group(1).lower(), field.group(2))  # fmt: skip
        found[name] = fields
    return found


def feats(folder: Path) -> set[str]:
    names = set()
    for line in (flat(line) for line in lines(folder, "Feats.rtf")):
        m = re.match(
            r"^(.+?) \[(?:General|Fighter|Item Creation|Metamagic|Special)[^\]]*\]$", line, flags=re.IGNORECASE
        )
        if m:
            names.add(m.group(1).strip().title() if m.group(1).isupper() else m.group(1).strip())
    return names


def skills(folder: Path) -> set[str]:
    text = [flat(line) for line in lines(folder, "Skills*.rtf")]
    return {
        m.group(1).strip().title()
        for line in text
        if (m := re.match(r"^([A-Z][A-Z ]+?) \((?:STR|DEX|CON|INT|WIS|CHA|NONE)\b[^)]*\)$", line))
    }


def monsters(folder: Path) -> dict[str, str]:
    """Each monster's name with its Hit Dice line: the name is the line before `Size/Type:`."""
    text = lines(folder, "Monsters*.rtf")
    found = {}
    for n, line in enumerate(text):
        if not line.startswith("Hit Dice:") or n < 2:
            continue
        dice = [c for c in line.removeprefix("Hit Dice:").split("\t") if c.strip()]
        names = [c for c in text[n - 2].split("\t") if c.strip()]
        for name, hit_dice in zip(names, dice, strict=False):
            found[name.strip()] = hit_dice.strip()
    return found


def normal(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", re.sub(r"['’]", "", name.lower())).strip()


def words(name: str) -> str:
    """A name by its words in any order, so "Air Elemental, Large" is "Large Air Elemental" and "ANGEL, ASTRAL DEVA"
    "Astral Deva Angel"."""
    return " ".join(sorted(normal(name).split()))


def report(kind: str, ours: set[str], theirs: set[str]) -> None:
    mine = {words(n): n for n in ours}
    wotc = {words(n): n for n in theirs}
    only_ours = sorted(mine[k] for k in set(mine) - set(wotc))
    only_theirs = sorted(wotc[k] for k in set(wotc) - set(mine))
    print(f"\n## {kind}: {len(ours)} in the pack, {len(theirs)} in the RTFs")
    print(f"- only in the pack ({len(only_ours)}): {', '.join(only_ours[:60])}")
    print(f"- only in the RTFs ({len(only_theirs)}): {', '.join(only_theirs[:60])}")


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    rtf, data = Path(argv[1]), Path(argv[2])

    def load(kind: str) -> list[dict]:
        return json.loads((data / f"{kind}.json").read_text(encoding="utf-8"))

    rng = random.Random(SEED)

    their_spells = spells(rtf)
    our_spells = load("spells")
    report("spells", {s["name"] for s in our_spells}, set(their_spells))
    by_name = {normal(k): v for k, v in their_spells.items()}
    print("- 20 spells compared (range, duration, saving throw, spell resistance):")
    for spell in rng.sample(our_spells, 20):
        theirs = by_name.get(normal(spell["name"]))
        if theirs is None:
            print(f"  - {spell['name']}: not in the RTFs by this name")
            continue
        diffs = [
            f"{k}: pack {spell[k]!r} / RTF {theirs.get(k.replace('_', ' '), '')!r}"
            for k in ("range", "duration", "saving_throw", "spell_resistance")
            if normal(spell[k]) != normal(theirs.get(k.replace("_", " "), ""))
        ]
        print(f"  - {spell['name']}: {'; '.join(diffs) if diffs else 'same'}")

    report("feats", {f["name"] for f in load("feats")}, feats(rtf))
    report("skills", {s["name"] for s in load("skills")}, skills(rtf))

    their_monsters = monsters(rtf)
    our_monsters = load("monsters")
    report("monsters", {m["name"] for m in our_monsters}, set(their_monsters))
    by_monster = {words(k): v for k, v in their_monsters.items()}
    print("- 20 monsters compared (hit dice):")
    for monster in rng.sample(our_monsters, 20):
        theirs = by_monster.get(words(monster["name"]))
        if theirs is None:
            print(f"  - {monster['name']}: not in the RTFs by this name")
        else:
            ours = monster["hit_dice"]
            same = bool(ours) and normal(theirs).startswith(normal(ours))
            print(f"  - {monster['name']}: " + ("same" if same else f"pack {ours!r} / RTF {theirs!r}"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
