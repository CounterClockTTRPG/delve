"""A character's sheet (what it is) and state (how it is now), for PCs and NPCs alike (spec §7.8).

The sheet holds the static fields of ttrpg2's PC record (`campaign_mgmt.py:350-381`). The prose `weapon` stays, but
`attacks` is the structured source of truth. The state holds what play changes: hit points, XP, conditions and
effects, which outlive a fight, the inventory and the memorized spells.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

from delve.domain import data
from delve.domain.world import Portrait

Kind = Literal["pc", "npc"]


@dataclass(frozen=True)
class Attack:
    """One attack form: a weapon, a natural attack or an attack spell."""

    name: str
    speed: int | None = None
    """Weapon speed, added to the initiative die."""
    attacks: float | str = 1
    """Attacks per round: 1, 1.5, or "3/2"."""
    thac0: int | None = None
    """This attack's THAC0, when it differs from the sheet's."""
    damage_sm: str = ""
    """Damage against small and medium targets, as dice notation."""
    damage_l: str = ""
    """Damage against large targets."""
    range: str | None = None


@dataclass(frozen=True)
class Effect:
    """A timed effect: bless, a sleep spell, a potion. The modifiers apply to rolls while it lasts."""

    name: str
    duration: int
    """Rounds left; 0 for one that lasts until it is removed (an item's, DEL-335)."""
    to_hit: int = 0
    ac: int = 0
    dmg: int = 0
    save: int = 0
    source: str = ""
    hidden: bool = False
    """The DM's alone: it applies, but no seat sees it, nor the sheet's numbers change (an unidentified ring of
    protection, DEL-335). Shown once the item is identified."""


@dataclass(frozen=True)
class Item:
    """Something a character carries. One list of them is the character's inventory (spec §7.8). `notes` are what the
    characters know of it, and the players read them; `dm_notes` are the DM's alone (DEL-181): what it really is
    before it is identified, its curse. A note the DM wrote into `notes` as "(DM: …)" moves to `dm_notes` when the item
    is made, a stored one too, so it never reaches the players."""

    name: str
    qty: int = 1
    weight_lb: float | None = None
    """The weight of one, in pounds; None when the reference doesn't know the item."""
    notes: str = ""
    dm_notes: str = ""

    def __post_init__(self) -> None:
        notes, found = split_dm_notes(self.notes)
        if found:
            object.__setattr__(self, "notes", notes)
            object.__setattr__(self, "dm_notes", "; ".join(part for part in (self.dm_notes.strip(), *found) if part))


# "(DM: …)" or "[GM only: …]" in a note, and a line or sentence that starts "DM:" (DEL-181).
_DM_PART = re.compile(r"\s*[(\[]\s*(?:DM|GM)(?:\s+only)?\s*:\s*([^)\]]*)[)\]]", re.IGNORECASE)
_DM_TAIL = re.compile(r"(?:^|(?<=[.;\n]))\s*(?:DM|GM)(?:\s+only)?\s*:\s*(.+)$", re.IGNORECASE | re.DOTALL)


def split_dm_notes(notes: str) -> tuple[str, list[str]]:
    """`notes` without the parts written for the DM, and those parts."""
    found = [m.group(1).strip() for m in _DM_PART.finditer(notes) if m.group(1).strip()]
    rest = _DM_PART.sub("", notes)
    tail = _DM_TAIL.search(rest)
    if tail:
        found.append(tail.group(1).strip())
        rest = rest[: tail.start()]
    return (rest.strip(" ;,") if found else notes), found


@dataclass(frozen=True)
class SpellLoadout:
    """The spells a caster knows (a wizard's spellbook, a priest's usual prayers) and memorizes by default."""

    known: dict[int, tuple[str, ...]] = field(default_factory=dict)
    """By spell level."""
    default: dict[int, tuple[str, ...]] = field(default_factory=dict)
    """By spell level; at most the sheet's `spell_slots` of each level."""


@dataclass(frozen=True)
class MemorizedSpell:
    """One memorized spell; `cast` once it is spent, until the next rest."""

    name: str
    level: int
    cast: bool = False


@dataclass(frozen=True)
class Sheet:
    kind: Kind = "pc"
    label: str = ""
    race: str = ""
    gender: str = ""
    pronouns: str = ""
    """How the story speaks of the character ("she/her"), when not the gender's (`pronouns_of`)."""
    deity: str = ""
    """The god the character serves or swears by, so the story keeps to one (DEL-327)."""
    cls: str = ""
    """The class, or classes joined by "/": "Fighter/Thief"."""
    levels: dict[str, int] = field(default_factory=dict)
    """The level of each class, by lowercase class name: {"fighter": 1, "thief": 2}."""
    hp_max: int = 0
    ac: int = 10
    thac0: int = 20
    saves: dict[str, int] = field(default_factory=dict)
    """By save type: paralysis_poison_death, rod_staff_wand, petrify_polymorph, breath_weapon, spell."""
    ability_scores: dict[str, int | str] = field(default_factory=dict)
    """By ability, "str" … "cha"; exceptional strength as "18/76"."""
    attacks: tuple[Attack, ...] = ()
    weapon: str = ""
    """The weapon in prose, for the DM's narration."""
    weapon_profs: tuple[str, ...] = ()
    nwps: tuple[str, ...] = ()
    natural_abilities: tuple[str, ...] = ()
    skills: dict[str, int] = field(default_factory=dict)
    """Thief and other percentile skills."""
    size: str = "M"
    ac_vs_larger: int = 0
    """An AC bonus against attackers larger than this character (a pixie's +2)."""
    movement_rate: int = 12
    alignment: str = ""
    background: str = ""
    portrait_prompt: str = ""
    spell_slots: dict[int, int] = field(default_factory=dict)
    """Slots per spell level."""
    spell_loadout: SpellLoadout = field(default_factory=SpellLoadout)
    notes_md: str = ""
    """NPCs: their story. DM-only."""
    disposition: int = 0
    """NPCs: their attitude to the party, -100 … 100."""
    portrait: Portrait | None = None
    faction: str = ""
    """The id of the faction the character belongs to, if any."""

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Sheet:
        return data.from_dict(cls, raw)

    def to_dict(self) -> dict[str, Any]:
        return data.to_dict(self)


_SHE = frozenset({"f", "female", "woman", "girl"})
_HE = frozenset({"m", "male", "man", "boy"})


def pronouns_of(sheet: Sheet) -> str:
    """The pronouns the story uses for the character (DEL-327): the sheet's own, else its gender's ("she/her",
    "he/him"); "" when the sheet says neither."""
    if sheet.pronouns.strip():
        return sheet.pronouns.strip()
    gender = sheet.gender.strip().casefold()
    return "she/her" if gender in _SHE else "he/him" if gender in _HE else ""


@dataclass(frozen=True)
class CharacterState:
    hp: int = 0
    xp: int = 0
    conditions: tuple[str, ...] = ()
    """"downed", "poisoned", "prone" …"""
    effects: tuple[Effect, ...] = ()
    inventory: tuple[Item, ...] = ()
    memorized: tuple[MemorizedSpell, ...] = ()

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> CharacterState:
        return data.from_dict(cls, raw)

    def to_dict(self) -> dict[str, Any]:
        return data.to_dict(self)
