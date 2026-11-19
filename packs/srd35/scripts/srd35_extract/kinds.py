"""Each kind of the SRD's data, from its file in the SRD copy: classes (base, NPC and prestige), races, skills, feats,
spells, monsters, items (magic items and the equipment tables that parse), the ability table, the rules text and the
carrying capacity table in it."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from srd35_extract.common import Section, bullets, by_id, clean, inline, read, sections, slug, tables
from srd35_extract.markdown import markdown

BASIC = "Basic Rules and Legal"
CLASS_FILES = {
    "base": (f"{BASIC}/character-classes-i.md", f"{BASIC}/character-classes-ii.md"),
    "npc": (f"{BASIC}/npc-classes.md",),
    "prestige": (f"{BASIC}/prestige-classes.md",),
}
ABILITIES = {"str": "Strength", "dex": "Dexterity", "con": "Constitution", "int": "Intelligence", "wis": "Wisdom",
             "cha": "Charisma"}  # fmt: skip
_SPELL_CLASSES = {"sor/wiz": ("sorcerer", "wizard"), "clr": ("cleric",), "drd": ("druid",), "brd": ("bard",),
                  "pal": ("paladin",), "rgr": ("ranger",), "adp": ("adept",)}  # fmt: skip


def _subsections(section: Section) -> dict[str, str]:
    """A section's `###` parts by lowercase title."""
    return {s.title.lower().strip(): s.body for s in sections(section.body, 3)}


def _level(text: str) -> int | None:
    match = re.match(r"(\d+)", text.strip())
    return int(match.group(1)) if match else None


def _class_table(section: Section) -> list[dict[str, Any]]:
    """The class's progression: the first table with a row whose first cell names the level ("Level", "NPC Level"),
    which is its header (the first row of most, the second of a table that has its title as its first)."""
    found = tables(section.body)
    with_bab = [t for t in found if any("base attack" in c.lower() for row in (t.header, *t.rows[:2]) for c in row)]
    for table in with_bab or found:  # a caster's Spells Known table has a Level column too
        every = [table.header, *table.rows]
        at = next((n for n, row in enumerate(every) if row and re.fullmatch(r"(npc )?level", row[0].lower())), None)
        if at is None:
            continue
        header = ["level", *(h.lower() for h in every[at][1:])]
        rows = []
        for row in every[at + 1 :]:
            cells = dict(zip(header, row, strict=False))
            level = _level(cells.get("level", ""))
            if level is None or (rows and level <= rows[-1]["level"]):
                continue  # not a level row, or a footnote after the last level ("1 The monk's…")
            spells = {  # keyed by the level the column prints: a paladin's columns are 1st to 4th
                str(int(key[0])): cell
                for key, cell in cells.items()
                if re.fullmatch(r"\d(st|nd|rd|th)?", key) and cell not in ("", "—", "–")
            }
            rows.append(
                {
                    "level": level,
                    "bab": cells.get("base attack bonus", ""),
                    "fort": cells.get("fort save", ""),
                    "ref": cells.get("ref save", ""),
                    "will": cells.get("will save", ""),
                    "special": cells.get("special", ""),
                    "spells_per_day": spells,
                }
            )
        if rows:
            return rows
    return []


def _skill_points(parts: dict[str, str]) -> str:
    """The skill points a level gives: the first paragraph under "Skill Points at Each Additional Level" (a prestige
    class: "at Each Level"), not the class table that follows it."""
    text = parts.get("skill points at each additional level") or parts.get("skill points at each level") or ""
    return inline(re.split(r"\n\s*\n|\n\s*-{3,}|<table", text.strip(), maxsplit=1)[0]).rstrip(".")


def _class_skills(text: str) -> list[str]:
    """The skills a class's Class Skills paragraph names, as skill ids."""
    flat = inline(text)
    flat = flat.split(" are ", 1)[-1] if " are " in flat else flat
    flat = re.sub(r"\bSee Chapter.*$", "", flat)
    names = re.findall(r"([A-Z][A-Za-z' ]+?)(?: \([^)]*\))* \((?:Str|Dex|Con|Int|Wis|Cha)\)", flat)
    return sorted({slug(name.strip().removeprefix("and ").strip()) for name in names})


def classes(src: Path) -> list[dict[str, Any]]:
    rows = []
    for kind, files in CLASS_FILES.items():
        for relative in files:
            for section in sections(read(src, relative), 2):
                parts = _subsections(section)
                levels = _class_table(section)
                if not levels and "hit die" not in parts:
                    continue  # a section that isn't a class ("Definitions of Terms")
                rows.append(
                    {
                        "id": slug(section.title),
                        "name": inline(section.title),
                        "type": kind,
                        "hit_die": inline(parts.get("hit die", "")).rstrip("."),
                        "skill_points": _skill_points(parts),
                        "class_skills": _class_skills(parts.get("class skills", "")),
                        "levels": levels,
                        "text": markdown(section.body),
                    }
                )
    return by_id(rows)


_ADJUST = re.compile(r"([+–-]\d+)\s+(Strength|Dexterity|Constitution|Intelligence|Wisdom|Charisma)")


def races(src: Path) -> list[dict[str, Any]]:
    rows = []
    for section in sections(read(src, f"{BASIC}/races.md"), 2):
        items = bullets(section.body)
        if not any(_ADJUST.search(i) or "base land speed" in i for i in items):
            continue  # "Favored Class", "Small Characters"
        adjustments: dict[str, int] = {}
        for item in items[:2]:
            for amount, ability in _ADJUST.findall(item):
                key = next(k for k, v in ABILITIES.items() if v == ability)
                adjustments[key] = int(amount.replace("–", "-"))
        speed = next((m.group(1) for i in items if (m := re.search(r"base land speed is (\d+) feet", i))), "")
        size = next((m.group(1) for i in items if (m := re.match(r"(Small|Medium|Large)\b", i))), "")
        favored = next((m.group(1) for i in items if (m := re.match(r"Favored Class: ([^.]*)", i))), "").strip()
        rows.append(
            {
                "id": slug(section.title),
                "name": inline(section.title),
                "size": size,
                "speed": int(speed) if speed else None,
                "ability_adjustments": adjustments,
                "la": 0,
                "favored_class": favored,
                "traits": items,
                "text": markdown(section.body),
            }
        )
    return by_id(rows)


_SKILL = re.compile(r"^(.*?)\s*\[?\(([^)]*)\)\]?\s*$")


def _skill_heading(title: str) -> re.Match[str] | None:
    match = _SKILL.match(title)
    return match if match and re.match(r"(Str|Dex|Con|Int|Wis|Cha|None)\b", match.group(2)) else None


def _skill_sections(text: str, level: int) -> list[tuple[str, str]]:
    """Each skill heading at `level` with its text: its own body and, where the skill's parts (Check, Action) are
    headed at the same level, theirs too, up to the next skill."""
    found: list[tuple[str, tuple[str, ...], list[str]]] = []
    for section in sections(text, level):
        if _skill_heading(section.title):
            found.append((section.title, section.parents, [section.body]))
        elif found and section.parents == found[-1][1]:  # a part of the skill before, under the same heading
            found[-1][2].append(f"{'#' * (level + 1)} {section.title}\n{section.body}")
    return [(title, "\n\n".join(p for p in parts if p.strip())) for title, _, parts in found]


def skills(src: Path) -> list[dict[str, Any]]:
    rows = []
    for relative in (f"{BASIC}/skills-i.md", f"{BASIC}/skills-ii.md"):
        text = read(src, relative)
        for title, body in [*_skill_sections(text, 2), *_skill_sections(text, 3)]:  # skills-i heads them deeper
            match = _skill_heading(title)
            notes = [n.strip().lower() for n in match.group(2).split(";")]
            rows.append(
                {
                    "id": slug(match.group(1)),
                    "name": inline(match.group(1)),
                    "key_ability": notes[0][:3] if notes[0] != "none" else "",
                    "trained_only": any("trained only" in n for n in notes),
                    "armor_check": any("armor check" in n for n in notes),
                    "text": markdown(body),
                }
            )
    return by_id(rows)


_FEAT_PARTS = ("prerequisite", "prerequisites", "benefit", "normal", "special")


def _prerequisites(text: str) -> tuple[list[dict[str, Any]], list[str]]:
    """The prerequisites that parse (ability, base attack bonus, caster level, skill ranks, a class level, a feat) and
    the ones that don't, kept as their words."""
    parsed, left = [], []
    for part in re.split(r",\s*(?![^()]*\))", inline(text).rstrip(".")):
        part = part.strip().removeprefix("and ").strip()
        if not part:
            continue
        if m := re.fullmatch(r"(Str|Dex|Con|Int|Wis|Cha) (\d+)", part):
            parsed.append({"kind": "ability", "ability": m.group(1).lower(), "min": int(m.group(2))})
        elif m := re.fullmatch(r"[Bb]ase attack bonus \+(\d+)", part):
            parsed.append({"kind": "bab", "min": int(m.group(1))})
        elif m := re.fullmatch(r"[Cc]aster level (\d+)(?:st|nd|rd|th)", part):
            parsed.append({"kind": "caster_level", "min": int(m.group(1))})
        elif m := re.fullmatch(r"(.+?) (\d+) ranks?", part):
            parsed.append({"kind": "skill", "skill": slug(m.group(1)), "min": int(m.group(2))})
        elif m := re.fullmatch(r"(\w[\w ]*?) level (\d+)(?:st|nd|rd|th)", part):
            parsed.append({"kind": "class_level", "class": slug(m.group(1)), "min": int(m.group(2))})
        elif re.fullmatch(r"[A-Z][\w'-]*(?:\s+(?:[A-Z][\w'-]*|of|the))*(?: \([^)]*\))?", part):
            parsed.append({"kind": "feat", "feat": slug(re.sub(r"\s*\(.*\)", "", part))})
        else:
            left.append(part)
    return parsed, left


def feats(src: Path) -> list[dict[str, Any]]:
    text = read(src, f"{BASIC}/feats.md")
    rows = []
    for section in sections(text, 3):
        if "Feat Descriptions" not in section.parents or not re.search(r"\*\*Benefits?:", section.body):
            continue
        if section.title.strip().lower() == "feat name":
            continue  # the SRD's example of how a feat reads
        name = re.sub(r"\s*\[.*\]$", "", section.title).strip()
        kind = re.search(r"\[([^\]]+)\]", section.title)
        typed = re.search(r"Feat Type:\s*([^*\n]+)", section.body)
        types = (kind.group(1) if kind else typed.group(1) if typed else "General").replace(",", " ").split()
        if re.search(r"fighter\s+bonus\s+feats?", section.body, flags=re.IGNORECASE):
            types.append("fighter")
        parts: dict[str, str] = {}
        for match in re.finditer(r"\*\*(\w+):\*\*(.*?)(?=\n\*\*\w+:\*\*|\Z)", section.body, flags=re.DOTALL):
            parts[match.group(1).lower()] = markdown(match.group(2))
        prerequisite = parts.get("prerequisites", parts.get("prerequisite", ""))
        parsed, left = _prerequisites(prerequisite)
        rows.append(
            {
                "id": slug(name),
                "name": inline(name),
                "type": sorted({t.strip().lower() for t in types if t.strip().lower() not in ("feat", "type:")}),
                "prerequisites": parsed,
                "prerequisites_text": inline(prerequisite) if left else "",
                "prerequisites_line": inline(prerequisite).rstrip("."),
                "benefit": parts.get("benefit", parts.get("benefits", "")),
                "normal": parts.get("normal", ""),
                "special": parts.get("special", ""),
            }
        )
    return by_id(rows)


_SPELL_FIELDS = {"level": "level", "components": "components", "component": "components",
                 "casting time": "casting_time", "range": "range", "target": "target", "targets": "target",
                 "area": "area", "effect": "effect", "duration": "duration",
                 "saving throw": "saving_throw", "spell resistance": "spell_resistance"}  # fmt: skip


def _spell_levels(text: str) -> dict[str, int]:
    levels: dict[str, int] = {}
    for part in text.split(","):
        match = re.fullmatch(r"\s*(.+?)\s+(\d)\s*", part)
        if not match:
            continue
        for name in _SPELL_CLASSES.get(match.group(1).lower(), (slug(match.group(1)),)):
            levels[name] = int(match.group(2))
    return dict(sorted(levels.items()))


def spells(src: Path) -> list[dict[str, Any]]:
    rows = []
    text = read(src, "Spells/Spells.md")
    for section in [*sections(text, 2), *sections(text, 3)]:  # part of the conversion heads its spells at ###
        lines = re.split(r"(?m)^#", section.body, maxsplit=1)[0].splitlines()  # its own text, not the next spell's
        fields: dict[str, str] = {}
        school_line = ""
        body_from = 0
        for n, line in enumerate(lines):
            item = re.match(r"^\s*[*-]\s+(.*)$", line)
            if not item:
                if (fields or school_line) and line.strip():
                    body_from = n
                    break
                continue
            content = item.group(1)
            field = re.match(r"\*\*(.+?)::?\*\*\s*(.*)", content)
            if field:
                fields[field.group(1).lower()] = inline(field.group(2))
            elif not school_line:
                school_line = inline(content)
        if "level" not in fields:
            continue
        school = re.match(r"([A-Za-z]+)\s*(?:\(([^)]*)\))?\s*(?:\[([^\]]*)\])?", school_line)
        row: dict[str, Any] = {
            "id": slug(section.title),
            "name": inline(section.title),
            "school": school.group(1) if school else "",
            "subschool": (school.group(2) or "") if school else "",
            "descriptors": [d.strip() for d in (school.group(3) or "").split(",") if d.strip()] if school else [],
            "levels": _spell_levels(fields.get("level", "")),
            "text": markdown("\n".join(lines[body_from:])) if body_from else "",
        }
        for key, name in _SPELL_FIELDS.items():
            if key != "level":
                row[name] = row.get(name) or fields.get(key, "")
        rows.append(row)
    return _inherit(by_id(rows))


_INHERITED = ("components", "casting_time", "range", "duration", "saving_throw", "spell_resistance")
_FUNCTIONS_LIKE = re.compile(
    r"(?:functions|works)(?: just)? (?:like|similarly to) (?:an? |the )?(?:_([^_]+)_|([A-Za-z’' ]+?),? except)"
)  # the name in italics, or once plain ("functions like create undead, except")
_ORDER = ("mass", "greater", "lesser")


def _base_id(name: str, ids: set[str]) -> str | None:
    """The spell a "functions like _X_" names, by id: "mass cure light wounds" is Cure Light Wounds, Mass."""
    name = re.sub(r"\s+’", "’", name).strip(" ,.;")
    words = name.lower().split()
    candidates = [slug(name)]
    if words and words[0] in _ORDER:
        candidates.append(slug(" ".join(words[1:]) + " " + words[0]))
    return next((c for c in candidates if c in ids), None)


def _inherit(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The SRD writes a variant as "This spell functions like _X_, except …": it has the entries of X it doesn't
    print. Each empty field of `_INHERITED` is filled from the named spell, itself filled first (a chain)."""
    by = {row["id"]: row for row in rows}

    def fill(row: dict[str, Any], seen: frozenset[str]) -> None:
        found = _FUNCTIONS_LIKE.search(row["text"])
        base = _base_id(found.group(1) or found.group(2), set(by)) if found else None
        if base is None or base in seen or not any(not row[f] for f in _INHERITED):
            return
        fill(by[base], seen | {row["id"]})
        for field in _INHERITED:
            row[field] = row[field] or by[base][field]

    for row in rows:
        fill(row, frozenset())
    return rows


def domains(src: Path) -> list[dict[str, Any]]:
    """The cleric domains of the class spell list: the granted power (its text without the label) and the domain
    spell of each level 1 to 9, by the name the SRD prints."""
    text = read(src, "Spells/Class Spell List.md")
    rows = []
    for section in sections(text, 2):
        if not section.title.endswith(" Domain"):
            continue
        power_text, _, spell_text = section.body.partition("### ")
        power = re.sub(r"^\*\*[^*]*\*\*:?\s*", "", power_text.strip())
        spells: dict[str, str] = {}
        for level, line in re.findall(r"(?m)^([1-9])\s*\n+\s*(\S[^\n]*)", spell_text):
            name = re.match(r"\*\*(.+?)\*\*|\*(.+?)\\?:\*", line)
            spells[level] = inline((name.group(1) or name.group(2)) if name else line).rstrip(":").strip()
            spells[level] = re.sub(r"\s+(?:XP|DF|[FMX]{1,2})$", "", spells[level])  # the component marks the list prints
        rows.append(
            {
                "id": slug(section.title.removesuffix(" Domain")),
                "name": inline(section.title.removesuffix(" Domain")),
                "granted_power": clean(power).strip(),
                "spells": spells,
            }
        )
    return by_id(rows)


def _pairs(items: list[Any]) -> dict[str, str]:
    """A statblock's list of `{name: value}` as one dict; a record that lists "Name +8" strings instead is read too."""
    out: dict[str, str] = {}
    for item in items or []:
        if isinstance(item, dict):
            out.update({str(k).strip().lower(): str(v).strip() for k, v in item.items()})
        elif isinstance(item, str) and item.strip():
            name, _, value = item.strip().rpartition(" ")
            if not name or not re.fullmatch(r"[+–-]?\d+", value):
                name, value = item.strip(), ""
            out[name.lower()] = value
    return out


PRODUCT_IDENTITY_SWAPS = {"Ever-Changing Chaos of Limbo": "A chaotic neutral-aligned plane"}
"""A Product Identity name the conversion has in Open Game Content, and what the pack says instead (SOURCES.md)."""


def scrubbed(text: str) -> str:
    for name, instead in PRODUCT_IDENTITY_SWAPS.items():
        text = text.replace(name, instead)
    return text


SIZES = ("Fine", "Diminutive", "Tiny", "Small", "Medium", "Large", "Huge", "Gargantuan", "Colossal")
_SPLIT_TYPES = {("Magical", "Beast"): "Magical Beast", ("Monstrous", "Humanoid"): "Monstrous Humanoid"}


def _size_and_type(record: dict[str, Any]) -> tuple[str, str, list[str]]:
    """The record's size, type and subtypes, with the conversion's certain slips undone: a size in the type field
    (the name in the size field) moved back, a classed monster's name and level ("Goblin", "1st-Level", then
    "Warrior") dropped from before its size, and a two-word type split into type and subtype joined."""
    size, kind, subtypes = record.get("size") or "", record.get("type") or "", list(record.get("subtypes") or [])
    if size not in SIZES and re.fullmatch(r"\d+(st|nd|rd|th)-Level", kind) and any(s in SIZES for s in subtypes[:-1]):
        at = next(n for n, s in enumerate(subtypes) if s in SIZES)  # "Goblin", "1st-Level", ["Warrior", "Small", …]
        size, kind, subtypes = subtypes[at], subtypes[at + 1], subtypes[at + 2 :]
    elif size not in SIZES and kind in SIZES and subtypes:
        size, kind, subtypes = kind, subtypes[0], subtypes[1:]
    if subtypes and (kind, subtypes[0]) in _SPLIT_TYPES:
        kind, subtypes = _SPLIT_TYPES[(kind, subtypes[0])], subtypes[1:]
    return size, kind, subtypes


def _merged(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The records with one per name: a later record of a name fills the first's empty fields and continues its
    description (the conversion splits a long entry over two)."""
    out: dict[str, dict[str, Any]] = {}
    for record in records:
        first = out.get(record["name"])
        if first is None:
            out[record["name"]] = dict(record)
            continue
        for key, value in record.items():
            if key == "description":
                first["description"] = [*(first.get("description") or []), *(value or [])]
            elif value not in (None, "", [], {}) and first.get(key) in (None, "", [], {}):
                first[key] = value
    return list(out.values())


def monsters(src: Path) -> list[dict[str, Any]]:
    path = src / "3.5 Compendium" / "3.5 Monster Statblock File.json"
    if not path.is_file():
        read(src, "3.5 Compendium/3.5 Monster Statblock File.json")
    rows = []
    for record in _merged(json.loads(path.read_text(encoding="utf-8"))):
        actions = {a["name"].lower(): a["desc"] for a in record.get("actions", [])}
        traits = {t["name"].lower(): t["desc"] for t in record.get("traits", [])}
        stats = _pairs(record.get("stats", []))
        saves = _pairs(record.get("saves", []))
        reach = _pairs([record.get("space_reach", {})])
        size, kind, subtypes = _size_and_type(record)
        rows.append(
            {
                "id": slug(record["name"]),
                "name": record["name"],
                "size": size,
                "type": kind,
                "subtypes": subtypes,
                "hit_dice": record.get("hit_dice", ""),
                "hp": record.get("hp"),
                "initiative": record.get("initiative"),
                "speed": record.get("speed", ""),
                "armor_class": record.get("ac", ""),
                "flat_footed": record.get("flat_footed", ""),
                "base_attack_grapple": record.get("base_attack_grapple", ""),
                "attack": actions.get("attack", ""),
                "full_attack": actions.get("full attack", ""),
                "space_reach": reach.get("space/reach", ""),
                "special_attacks": record.get("special_attacks", "") or traits.get("special attacks", ""),
                "special_qualities": traits.get("special qualities", ""),
                "saves": {k: saves[k] for k in sorted(saves)},
                "abilities": {k: stats[k] for k in sorted(stats)},
                "skills": _pairs(record.get("skillsaves", [])),
                "feats": traits.get("feats", ""),
                "environment": scrubbed(record.get("environment", "") or ""),
                "organization": record.get("organization", ""),
                "cr": str(record.get("cr", "")),
                "treasure": record.get("treasure", ""),
                "alignment": record.get("alignment", ""),
                "advancement": record.get("advancement", ""),
                "level_adjustment": record.get("level_adjustment", ""),
                "languages": record.get("languages", ""),
                "senses": list(record.get("senses", [])),
                "text": "\n\n".join(record.get("description", [])),
            }
        )
    return by_id(rows)


MAGIC_ITEM_FILES = tuple(
    f"Magic Items/{name}.md"
    for name in (
        "magic-items-ii-armor-and-weapons",
        "magic-items-iii-potions-rings-and-rods",
        "magic-items-iv-scrolls-staffs-and-wands",
        "magic-items-v-wondrous-items",
        "magic-items-vi-intelligent-cursed-and-artifacts",
    )
)
_TYPES = (("armor", "armor"), ("weapon", "weapon"), ("potion", "potion"), ("ring", "ring"), ("rod", "rod"),
          ("scroll", "scroll"), ("staff", "staff"), ("staves", "staff"), ("wand", "wand"), ("wondrous", "wondrous"),
          ("cursed", "cursed"), ("artifact", "artifact"), ("intelligent", "intelligent"))  # fmt: skip


def _item_type(headings: tuple[str, ...]) -> str:
    """An item's type from its headings, the nearest first and its own title last, by whole words ("Ring
    Descriptions" is a ring; "Bag of Devouring" and "Bracers of Armor" aren't)."""
    *parents, title = headings
    for heading in [*reversed(parents), title]:
        lowered = heading.lower()
        for word, kind in _TYPES:
            if re.search(rf"\b{word}s?\b", lowered):
                return kind
    return ""


def items(src: Path) -> list[dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for relative in MAGIC_ITEM_FILES:
        for section in sections(read(src, relative), 3):
            level = re.search(r"^(?:Faint|Moderate|Strong|Overwhelming)\b[^\n]*?;\s*CL (\d+)(?:st|nd|rd|th)", section.body,
                              flags=re.MULTILINE)  # fmt: skip
            if not level:
                continue  # rules text, not an item: an item has its aura and caster level
            price = re.search(r"\bPrice\s+([^;\n]+?)(?:;|\.\s*$|\n|$)", section.body, flags=re.MULTILINE)
            row = {
                "id": slug(section.title),
                "name": inline(section.title),
                "item_type": _item_type((*section.parents, section.title)),
                "price": inline(price.group(1)) if price else "",
                "weight": inline(m.group(1))
                if (m := re.search(r"\bWeight\s+(\d[\d,/ ]*\s*lb\.?)", section.body))
                else "",
                "caster_level": int(level.group(1)),
                "slot": "",
                "text": markdown(section.body),
            }
            rows.setdefault(row["id"], row)
    equipment = read(src, f"{BASIC}/equipment.md")
    for table in tables(equipment):
        if table.caption not in ("Table: Armor and Shields",):
            continue
        header = [h.lower() for h in table.header]
        for cells in table.rows:
            named = dict(zip(header, cells, strict=False))
            name, cost = cells[0], named.get("cost", "")
            if not name or not cost or cost in ("—",):
                continue
            row = {"id": slug(name), "name": name, "item_type": "armor", "price": cost,
                   "weight": named.get("weight1", named.get("weight", "")), "caster_level": None, "slot": "",
                   "text": ""}  # fmt: skip
            rows.setdefault(row["id"], row)
    return by_id(list(rows.values()))


def abilities() -> dict[str, Any]:
    """3.5's ability modifiers and bonus spells for scores 1 to 45, by the SRD's own rule: the modifier is half the
    score less 10, rounded down, and a modifier of at least a spell level gives 1 + (modifier − level) ÷ 4 bonus spells
    of that level (none of level 0)."""
    modifiers, bonus = [], []
    for score in range(1, 46):
        modifier = (score - 10) // 2
        modifiers.append({"score": score, "modifier": modifier})
        bonus.append(
            {"score": score, **{str(lvl): 1 + (modifier - lvl) // 4 if modifier >= lvl else 0 for lvl in range(1, 10)}}
        )
    return {"modifiers": modifiers, "bonus_spells": bonus}


_LOAD_ROW = re.compile(
    r"^\|\s*(\d+)\s*\|\s*([\d,]+) lb\. or less\s*\|\s*[\d,]+\s*[–-]+\s*([\d,]+) lb\.\s*\|\s*[\d,]+\s*[–-]+\s*([\d,]+) lb\.",
    re.MULTILINE,
)
_TREMENDOUS = re.compile(r"^\|\s*\+10\s*\|\s*x(\d+)\s*\|", re.MULTILINE)
_SIZE_MULTIPLIER = re.compile(r"\b([A-Z][a-z]+)[\s|]+x(\d+(?:/\d+)?)\b")
_REDUCED_SPEED = re.compile(r"(\d+) ft\.[\s|]+(\d+) ft\.")


def _between(text: str, start: str, end: str) -> str:
    """The text after `start` up to `end` (or the end); empty when `start` isn't in it."""
    at = text.find(start)
    if at < 0:
        return ""
    stop = text.find(end, at + len(start))
    return text[at + len(start) : stop if stop >= 0 else len(text)]


def carrying(rules: list[tuple[str, str]]) -> dict[str, Any]:
    """Table: Carrying Capacity from the rules' Carrying Capacity section: each Strength's heaviest light, medium and
    heavy load in pounds, and the Tremendous Strength multiplier for every ten points over a row ("+10 ×4"). With them
    Bigger and Smaller Creatures' multiplier for each size of biped (`sizes`, "3/4" for Small; the quadrupeds' are left
    out) and Armor and Encumbrance for Other Base Speeds' reduced speed for each base speed (`reduced_speeds`).
    `ValueError` when the section or its table isn't there."""
    text = next((body for _, body in rules if body.startswith('---\ntitle: "Carrying Capacity"\n')), "")
    loads = [
        {"strength": int(score), **{band: int(lb.replace(",", "")) for band, lb in zip(("light", "medium", "heavy"),
                                                                                     found, strict=True)}}
        for score, *found in _LOAD_ROW.findall(text)
    ]  # fmt: skip
    tremendous = _TREMENDOUS.search(text)
    if not loads or tremendous is None:
        raise ValueError("the rules have no Table: Carrying Capacity under Carrying Capacity")
    bipeds = _between(text, "### Bigger and Smaller Creatures", "Quadrupeds")
    speeds = _between(text, "### Armor and Encumbrance for Other Base Speeds", "###")
    reduced = sorted((int(base), int(slow)) for base, slow in _REDUCED_SPEED.findall(speeds))
    return {
        "loads": loads,
        "tremendous": int(tremendous.group(1)),
        "sizes": dict(_SIZE_MULTIPLIER.findall(bipeds)),
        "reduced_speeds": [{"base": base, "reduced": slow} for base, slow in reduced],
    }


RULES_LEFT_OUT = ("legal-information.md",)


def rules(src: Path) -> list[tuple[str, str]]:
    """Each `##` section of the basic rules as a Markdown file `(name, text)`, with its title, source (its file)
    and section (its chapter) in front matter."""
    folder = src / BASIC
    if not folder.is_dir():
        read(src, BASIC + "/combat-i-basics.md")
    files = []
    for number, path in enumerate(sorted(p for p in folder.iterdir() if p.suffix == ".md"), start=1):
        if path.name in RULES_LEFT_OUT:
            continue
        text = read(src, f"{BASIC}/{path.name}")
        chapter = next((inline(s.title) for s in sections(text, 1)), path.stem)
        for n, section in enumerate(sections(text, 2), start=1):
            if section.title.lower() == "table of contents" or not section.body.strip():
                continue
            title = inline(section.title)
            front = f'---\ntitle: "{title}"\nsource: {path.stem}\nsection: "{chapter}"\n---\n'
            files.append((f"{number:02d}-{n:02d}-{slug(title)}.md", front + markdown(section.body) + "\n"))
    return files
