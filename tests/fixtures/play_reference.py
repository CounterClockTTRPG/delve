"""A reference with just what the play services look up: classes, their XP, Constitution, items and spells."""

XP_TABLES = {
    "Fighter": [0, 2000, 4000, 8000, 16000],
    "Thief": [0, 1250, 2500, 5000, 10000],
    "Mage": [0, 2500, 5000, 10000, 20000],
}
HP_ADJ = {"14": "0", "16": "+2", "17": "+2(+3)"}

# A few rows of 2e.db's items and spells, as the reference returns them.
ITEMS = [
    {"name": "Backpack", "item_type": "misc_equipment", "weight": "2 lbs.", "rarity": 0},
    {"name": "Bronze Plate Mail", "item_type": "armor", "weight": "45 lbs.", "rarity": 0},
    {"name": "Flight arrow", "item_type": "weapon_ammo", "weight": "*", "rarity": 0},
    {"name": "Hand or throwing axe", "item_type": "weapon_melee", "weight": "5", "rarity": 0},
    {"name": "Lantern, Hooded", "item_type": "misc_equipment", "weight": "2 lbs.", "rarity": 0},
    {"name": "Long sword", "item_type": "weapon_melee", "weight": "4", "rarity": 0},
    {"name": "Plate Mail", "item_type": "armor", "weight": "50 lbs.", "rarity": 0},
    {"name": "Rope (per 50 ft.), Hemp", "item_type": "misc_equipment", "weight": "20 lbs.", "rarity": 0},
    {"name": "Studded Leather", "item_type": "armor", "weight": "20 lbs.", "rarity": 0},
    {"name": "Thieves' picks", "item_type": "misc_equipment", "weight": "1 lb.", "rarity": 0},
    {"name": "Torch", "item_type": "misc_equipment", "weight": "1 lb.", "rarity": 0},
    {"name": "Plate Mail of Fear", "item_type": "Magic Armor", "weight": None, "rarity": 50},
]
SPELLS = [
    {"name": "Bless", "level": 1, "caster": "priest"},
    {"name": "Blessed Watchfulness", "level": 1, "caster": "priest"},
    {"name": "Cure Light Wounds", "level": 1, "caster": "priest"},
    {"name": "Hold Person", "level": 2, "caster": "priest"},
    {"name": "Hold Person", "level": 3, "caster": "wizard"},
    {"name": "Light", "level": 1, "caster": "priest"},
    {"name": "Light", "level": 1, "caster": "wizard"},
    {"name": "Lightning Bolt", "level": 3, "caster": "wizard"},
    {"name": "Magic Missile", "level": 1, "caster": "wizard"},
    {"name": "Sleep", "level": 1, "caster": "wizard"},
    {"name": "Web", "level": 2, "caster": "wizard"},
]


# The monsters the treasure rule asks about (`play.treasure._lair_rule`): one too dim to keep a hoard, one that keeps
# its hoard in its lair.
MONSTERS = (
    {"name": "stirge", "intelligence": "Animal (1)", "treasure_type": "Nil"},
    {"name": "troll", "intelligence": "Low (5-7)", "treasure_type": "Q (D)"},
)


class PlayReference:
    """The few reference lookups the play services use: classes, their XP, Constitution, items and spells."""

    snapshot_sha = "play"

    def char_class(self, name: str) -> dict | None:
        found = [c for c in XP_TABLES if c.lower() == name.strip().lower()]
        return {"name": found[0]} if found else None

    def class_levels(self, name: str) -> list[dict]:
        return [{"level": i + 1, "xp_required": xp} for i, xp in enumerate(XP_TABLES.get(name, []))]

    def ability(self, ability: str, score: str) -> dict:
        if ability != "constitution" or score not in HP_ADJ:
            return {"error": "unknown"}
        return {"ability": ability, "score": score, "values": {"hp_adj": HP_ADJ[score]}}

    def monster(self, name: str) -> list[dict]:
        """As the store's `monster`, over `MONSTERS`: the exact name only."""
        return [dict(row) for row in MONSTERS if row["name"] == name.strip().lower()]

    def item(self, name: str, item_type: str = "", max_rarity: int = 100, limit: int = 20) -> list[dict]:
        """As the store's `item`: name contains, type contains, commonest first, then by name."""
        rows = [
            r
            for r in ITEMS
            if name.lower() in r["name"].lower()
            and item_type.lower() in r["item_type"].lower()
            and r["rarity"] <= max_rarity
        ]
        return sorted(rows, key=lambda r: (r["rarity"], r["name"]))[:limit]

    def spell(self, name: str, caster: str = "") -> list[dict]:
        """As the store's `spell`: exact, then prefix, then contains, shorter names first; caster ignoring case."""
        q = name.strip().lower()
        if not q:
            return []
        rows = [r for r in SPELLS if q in r["name"].lower() and caster.strip().lower() in r["caster"].lower()]

        def rank(row: dict) -> tuple:
            low = row["name"].lower()
            return (0 if low == q else 1 if low.startswith(q) else 2, len(low), row["name"])

        return sorted(rows, key=rank)[:10]

    def encounter_tables(self) -> dict:
        """One band and one tier of bandits in every land terrain, for a journey's encounter (plan 6 Task 8)."""
        bandits = [{"range": [1, 6], "result": "2d4 bandits", "category": "humanoid", "monster": "bandit"}]
        lands = ("road", "wilderness", "forest", "hills", "plains", "mountain", "swamp", "urban", "ocean")
        return {
            "bands": [{"name": "low", "party_levels": [1, 99]}],
            "terrains": {t: {"tiers": [bandits]} for t in lands},
        }


RULES = (
    {
        "source": "phb",
        "label": "Player's Handbook",
        "chapter": "Chapter 9: Combat",
        "section": "Surprise",
        "body": "A surprised character or monster cannot act for one round. A roll of 1, 2 or 3 on a d10 surprises.",
    },
    {
        "source": "dmg",
        "label": "Dungeon Master Guide",
        "chapter": "Chapter 9: Combat",
        "section": "Morale",
        "body": "Morale checks are made with 2d10 when the party has lost half its number or its leader.",
    },
)
"""Two rules passages, as a ruleset's rules text holds them (the tiny reference's, before AD&D 2e became a pack)."""


class RulesReference(PlayReference):
    """The play reference with a rules text to search: `RULES`, a passage found when it holds every word of the query
    (a word matching any word it starts), as a full-text search finds it."""

    def rules_search(self, query: str, source: str = "", limit: int = 5) -> list[dict]:
        words = {word.strip("?\"*").lower() for word in query.split()} - {""}
        found = []
        for id, rule in enumerate(RULES, start=1):
            if source and rule["source"] != source.lower():
                continue
            text = rule["body"].lower()
            hits = [word for word in words if any(w.startswith(word) for w in text.replace(".", " ").split())]
            if words and len(hits) == len(words):
                snippet = rule["body"]
                for word in hits:
                    snippet = " ".join(f"<<{w}>>" if w.lower().startswith(word) else w for w in snippet.split())
                found.append({"id": id, **{k: v for k, v in rule.items() if k != "body"}, "snippet": snippet})
        return found[: max(1, limit)]
