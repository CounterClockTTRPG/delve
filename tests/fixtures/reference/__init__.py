"""The tiny wikis of the settings: a few rows in ttrpg2's `settings/` and `global/lore_facts.db` schemas, and a few
pages of the Realms wiki's dump.

`write_source(dir)` makes the ttrpg2-shaped databases and `write_realms_dump(path)` the dump. The private
`delve-packs` repo's snapshot tools (`tools/snapshot_reference.py`, `tools/import_realms_wiki.py`) made the snapshots
of the setting doubles in `tests/fixtures/packs` from them, and its tests run those tools over them.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

# ttrpg2's settings/greyhawk/greyhawk.db: the wiki's pages, its tags, its redirects, the typed tables and the two the
# snapshot leaves out (`links`, `pages_fts`).
GREYHAWK_TYPED = {
    "characters": ("name", "title", "home", "race", "class", "alignment"),
    "settlements": ("name", "realm", "size", "population", "ruler"),
    "deities": ("name", "titles", "rank", "alignment", "portfolio"),
    "creatures": ("name", "type", "alignment"),
    "realms": ("name", "region", "capital", "ruler"),
    "archfiends": ("subtype", "name", "title", "home"),
    "locations": ("subtype", "name", "type", "region"),
    "organizations": ("name", "type", "leader", "headquarters"),
    "creators": ("name", "occupation"),
    "items": ("name", "type", "alignment"),
    "planes": ("name", "type", "alignment"),
    "holidays": ("name", "date", "observed_by"),
    "buildings": ("name", "type", "location"),
}
SCHEMA_GREYHAWK = """
CREATE TABLE pages (title TEXT PRIMARY KEY, type TEXT, is_redirect INTEGER NOT NULL DEFAULT 0, redirect_target TEXT,
    raw_text TEXT);
CREATE TABLE categories (page TEXT NOT NULL, category TEXT NOT NULL, PRIMARY KEY (page, category));
CREATE TABLE links (from_page TEXT NOT NULL, to_page TEXT NOT NULL, anchor TEXT);
CREATE TABLE redirects (alias TEXT PRIMARY KEY, target TEXT NOT NULL);
CREATE VIRTUAL TABLE pages_fts USING fts5(title, raw_text, content='pages', content_rowid='rowid',
    tokenize='unicode61');
""" + "".join(
    f"CREATE TABLE {table} (page TEXT PRIMARY KEY, {', '.join(f'"{c}" TEXT' for c in columns)}, extra TEXT);\n"
    for table, columns in GREYHAWK_TYPED.items()
)
# Title, type, text. The Hardby page has the words of "Circle of Eight" but not as a phrase.
GREYHAWK_PAGES = [
    ("Circle of Eight", "organization", "The '''Circle of Eight''' is a cabal of wizards founded by [[Mordenkainen]]."),
    ("Mordenkainen", "character", "'''Mordenkainen''' is an archmage of the [[Circle of Eight]]."),
    ("Hardby", "settlement", "'''Hardby''' is a port on the Woolly Bay; its eight gates circle the old town."),
    ("Boccob", "deitie", "'''Boccob''' the Uncaring is the god of magic."),
    ("Iuz", "deitie", "'''Iuz''' the Old is a cambion demigod."),
    ("Nyr Dyv", "body_of_water", "The '''Nyr Dyv''' is the Lake of Unknown Depths."),
    ("Woolly Bay", "body_of_water", "The '''Woolly Bay''' opens onto the Azure Sea."),
]
# Alias -> target: a chain of two, and a loop that leads nowhere.
GREYHAWK_REDIRECTS = [
    ("Circle of eight", "Circle of Eight"),
    ("Mordy", "Mordenkainen the Mage"),
    ("Mordenkainen the Mage", "Mordenkainen"),
    ("Loop A", "Loop B"),
    ("Loop B", "Loop A"),
]
GREYHAWK_CATEGORIES = [
    ("Circle of Eight", "Organizations"),
    ("Mordenkainen", "Human characters"),
    ("Mordenkainen", "Wizards"),
    ("Hardby", "Settlements"),
]
GREYHAWK_ROWS = {
    "organizations": [("Circle of Eight", {"name": "Circle of Eight", "type": "Cabal", "leader": "Mordenkainen"})],
    "characters": [("Mordenkainen", {"name": "Mordenkainen", "race": "Human", "class": "Wizard", "title": ""})],
    "settlements": [("Hardby", {"name": "Hardby", "realm": "Hardby", "size": "Large town", "population": "5,000"})],
    "deities": [
        ("Boccob", {"name": "Boccob", "rank": "Greater god", "portfolio": "Magic"}),
        ("Iuz", {"name": "Iuz", "rank": "Demigod", "portfolio": "Deceit, pain"}),
    ],
    "locations": [("Nyr Dyv", {"subtype": "body_of_water", "name": "Nyr Dyv", "type": "Lake"})],
}

# ttrpg2's global/lore_facts.db: text, category, enabled, campaign. The `campaign` facts belong to ttrpg2's campaigns
# and stay there, as do the disabled ones.
LORE_FACTS = [
    ("The Circle of Eight keeps any one power from ruling the Flanaess.", "greyhawk", 1, ""),
    ("A lich's life is bound to its phylactery.", "monster", 1, ""),
    ("THAC0 means To Hit Armor Class 0.", "rules", 1, ""),
    ("Iuz is the son of Iggwilv.", "greyhawk", 1, ""),
    ("The Twin Cataclysms ended the Suel Imperium.", "history", 1, ""),
    ("The party of the Ruins campaign slew a CAMPAIGN-ONLY dragon.", "campaign", 1, "wgr1-greyhawk-ruins"),
    ("A DISABLED fact.", "monster", 0, ""),
]


def write_greyhawk(path: Path) -> Path:
    """ttrpg2's `settings/greyhawk/greyhawk.db` in miniature."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as db:
        db.executescript(SCHEMA_GREYHAWK)
        db.executemany("INSERT INTO pages (title, type, raw_text) VALUES (?, ?, ?)", GREYHAWK_PAGES)
        db.executemany(
            "INSERT INTO pages (title, type, is_redirect, redirect_target, raw_text) VALUES (?, 'redirect', 1, ?, '')",
            GREYHAWK_REDIRECTS,
        )
        db.executemany("INSERT INTO redirects (alias, target) VALUES (?, ?)", GREYHAWK_REDIRECTS)
        db.executemany("INSERT INTO categories (page, category) VALUES (?, ?)", GREYHAWK_CATEGORIES)
        db.execute("INSERT INTO links (from_page, to_page) VALUES ('Mordenkainen', 'Circle of Eight')")
        for table, rows in GREYHAWK_ROWS.items():
            for page, fields in rows:
                names = ", ".join(f'"{name}"' for name in fields)
                db.execute(
                    f"INSERT INTO {table} (page, {names}, extra) VALUES (?, {', '.join('?' for _ in fields)}, ?)",
                    (page, *fields.values(), json.dumps({"image": f"{page}.jpg"})),
                )
        db.execute("INSERT INTO pages_fts(pages_fts) VALUES ('rebuild')")
    return path


def write_source(directory: Path) -> Path:
    """ttrpg2's `global/` in miniature for the settings: `lore_facts.db`, with the Greyhawk wiki next to it in
    `../settings/greyhawk/greyhawk.db`."""
    directory.mkdir(parents=True, exist_ok=True)
    write_greyhawk(directory.parent / "settings" / "greyhawk" / "greyhawk.db")
    with sqlite3.connect(directory / "lore_facts.db") as db:
        db.execute(
            "CREATE TABLE facts (  id INTEGER PRIMARY KEY AUTOINCREMENT,  text TEXT NOT NULL,"
            "  category TEXT NOT NULL DEFAULT '',  source TEXT NOT NULL DEFAULT '',"
            "  enabled INTEGER NOT NULL DEFAULT 1,  created_at TEXT NOT NULL DEFAULT (datetime('now')),"
            " campaign TEXT NOT NULL DEFAULT '')"
        )
        db.executemany(
            "INSERT INTO facts (text, category, source, enabled, campaign) VALUES (?, ?, 'seed', ?, ?)", LORE_FACTS
        )
    return directory


PHLAN = """{{otheruses4|the city|the game|Pool of Radiance}}
{{Location
| image = Phlan_map-2e.jpg
| caption = Phlan circa [[1367 DR]].
| name = Phlan
| aliases = Jewel of the Moonsea
| type = City-state<br />{{Former}} Ruined city
| region = [[Moonsea North]], [[Moonsea]]
| size = Large city
| georefs = <ref name="FRCS">{{Cite book/FRCS|161}}</ref>
| religion = [[Tyr]], [[Bane|the Black Hand]]<ref name="PoR" />
| rulertype = Lord Protector
| ruler1 = [[Cvaal Daoran]]
| organizations = yes
}}
'''Phlan''', the '''Jewel of the Moonsea''', was a frontier city on the [[Moonsea]].<ref>Ruins of Adventure.</ref>
== History ==
In [[1340 DR]] the city was held by the Lord of the Ruins.
== Appendix ==
=== Appearances ===
* ''Pool of Radiance''
[[Category:Settlements]]
[[Category:Locations in the Moonsea|Phlan]]"""
# The Realms wiki's dump: (title, namespace, redirect target, text). Phlan has its references, a `{{Former}}` and an
# appendix; the novel and the author are out of world; "El" is a chain of two redirects, "Ed" leads out of world.
REALMS_PAGES = [
    ("Phlan", 0, None, PHLAN),
    (
        "Cormyr",
        0,
        None,
        (
            "{{State\n| name = Cormyr\n| capital = [[Suzail]]\n| leader1 = [[Azoun IV]]\n| type = Kingdom\n}}\n"
            "'''Cormyr''' was the Forest Kingdom.\n[[Category:Countries]]"
        ),
    ),
    (
        "Moonsea (lake)",
        0,
        None,
        "{{Body of water\n| name = Moonsea\n| type = Lake\n| region = [[Moonsea]]\n}}\nThe '''Moonsea''' was a vast sea.",
    ),
    (
        "Elminster",
        0,
        None,
        (
            "{{Person\n| name = Elminster Aumar\n| race = [[Human]]\n| alignment5e = Neutral good\n"
            "| alignment2e = Chaotic good\n| class2e = {{class table|edition=2e|[[Wizard]]|26|[[Cleric]]|9}}\n"
            "| refs2e = <ref>x</ref>\n}}\n'''Elminster''' was the Sage of Shadowdale."
        ),
    ),
    (
        "Bane",
        0,
        None,
        (
            "{{Deity\n| name = Bane\n| power2e = Greater deity\n| portfolio2e = Hatred, tyranny\n}}\n"
            "'''Bane''' was the god of tyranny."
        ),
    ),
    (
        "Zhentarim",
        0,
        None,
        (
            "{{Organization\n| name = Zhentarim\n| base = [[Zhentil Keep]]\n| members = yes\n}}\n"
            "The '''Zhentarim''' was the Black Network of Zhentil Keep."
        ),
    ),
    ("Calendar of Harptos", 0, None, "The '''Calendar of Harptos''' had twelve months of three tendays."),
    ("Pool of Radiance (novel)", 0, None, "{{Book\n| title = Pool of Radiance\n}}\nA novel set in Phlan."),
    ("Ed Greenwood", 0, None, "{{Real-world person\n| name = Ed Greenwood\n}}\nThe Realms' creator."),
    ("Jewel of the Moonsea", 0, "Phlan", ""),
    ("El", 0, "Elminster Aumar", ""),
    ("Elminster Aumar", 0, "Elminster#Early life", ""),
    ("Ed", 0, "Ed Greenwood", ""),
    ("Category:Settlements", 14, None, "Settlements of the Realms."),
]
REALMS_FACTS = """# The tiny reference's Realms facts.
Phlan was held by the Lord of the Ruins until 1340 DR.

The Zhentarim rule Zhentil Keep from behind its lords.
"""


def write_realms_dump(path: Path) -> Path:
    """The Realms wiki's dump, in its own XML, with `REALMS_PAGES`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    pages = []
    for title, ns, target, text in REALMS_PAGES:
        redirect = f"<redirect title={quoteattr(target)} />" if target else ""
        pages.append(
            f"<page><title>{escape(title)}</title><ns>{ns}</ns>{redirect}"
            f"<revision><text>{escape(text)}</text></revision></page>"
        )
    xml = '<mediawiki xmlns="http://www.mediawiki.org/xml/export-0.11/">' + "".join(pages) + "</mediawiki>"
    path.write_text(xml, "utf-8")
    return path
