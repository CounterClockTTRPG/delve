"""Terrain words onto the terrain keys the encounter, weather and travel tables use."""

# Terrain synonyms onto the keys of the encounter tables, as ttrpg2's `_TERRAIN_ALIASES`.
TERRAIN_ALIASES = {
    "mountains": "mountain", "alpine": "mountain",
    "marsh": "swamp", "marshes": "swamp", "bog": "swamp", "fen": "swamp",
    "underdark": "dungeon", "subterranean": "dungeon", "underground": "dungeon",
    "cave": "dungeon", "cavern": "dungeon",
    "sea": "ocean", "aquatic": "ocean", "water": "ocean", "coast": "ocean",
    "grassland": "plains", "grasslands": "plains", "steppe": "plains",
    "tundra": "arctic", "glacier": "arctic", "polar": "arctic",
    "city": "urban", "town": "urban", "ruins": "urban",
    "forests": "forest", "woods": "forest", "woodland": "forest",
    "hill": "hills", "jungles": "jungle", "rainforest": "jungle",
}  # fmt: skip
