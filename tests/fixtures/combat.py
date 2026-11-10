"""A fight for the play tests: Garrek and Pippa against two goblins, in an OSRIC campaign over a stand-in reference
(`CombatReference`), set up with scripted dice."""

from delve.play import combat
from tests.fixtures.play_reference import PlayReference

GARREK = {
    "hp_max": 30,
    "thac0": 18,
    "ac": 4,
    "movement_rate": 12,
    "attacks": [
        {"name": "long sword", "speed": 5, "attacks": 1, "thac0": 18, "damage_sm": "1d8+2", "damage_l": "1d12+2"}
    ],
}
PIPPA = {"hp_max": 10, "thac0": 20, "ac": 7, "weapon": "dagger"}

GOBLIN = {"name": "goblin", "count": 2, "hp": 5, "ac": 6, "thac0": 20, "dmg": "1d6", "weapon_speed": 6, "morale": 8}

# What the reference hands combat for a goblin: MM prose, as in ttrpg2's monster DB.
GOBLIN_DB = {
    "name": "goblin",
    "armor_class": "6",
    "hit_dice": "1-1",
    "thac0": 20,
    "damage_attack": "1-6",
    "no_of_attacks": "1",
    "no_appearing": "4-24",
    "morale": "Steady (11-12)",
    "xp_value": "15",
    "treasure_type": "K",
    "intelligence": "Low",
    "alignment": "Lawful evil",
    "size": "Small (4' tall)",
    "move": "6",
    "special_attacks": "Nil",
    "special_defenses": "Nil",
    "magic_resistance": "Nil",
}


class CombatReference(PlayReference):
    """The play reference with the goblin of the monster DB (when `goblins`) and the sleep spell."""

    def __init__(self, goblins: bool = False) -> None:
        self.goblins = goblins

    def monster(self, name: str) -> list[dict]:
        return [GOBLIN_DB] if self.goblins and name.lower() == "goblin" else []

    def spell(self, name: str, caster: str = "") -> list[dict]:
        if name.lower() == "sleep":
            return [{"name": "Sleep", "caster": "wizard", "casting_time": "1", "casting_time_init": 1}]
        return []


def setup_fight(at, surprise_rolls=(5, 4), init_rolls=(4, 2, 5, 6), surprise=True, **kw):
    """Party [Garrek, Pippa] + two goblins, in OSRIC. Default dice: surprise d6s 5/4 (nobody surprised), initiative
    d6s 4,2,5,6 in the order Garrek, Pippa, Goblin 1, Goblin 2 -> counts 4, 2 (3 with a 1-segment spell), 5, 6."""
    ctx = at(*(surprise_rolls if surprise else ()), *init_rolls)
    out = combat.setup_combat(ctx, enemies=kw.pop("enemies", [dict(GOBLIN)]), surprise=surprise, **kw)
    ctx.dice.rng.assert_done()
    return out
