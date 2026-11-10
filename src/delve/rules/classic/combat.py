"""Combat as a small state machine (spec §6.5): surprise, declarations, initiative rolled again
every round, attacks, saving throws for anyone, morale notices, and the end of the fight.

Pure: every command takes a `Combat` (with the dice and the reference where it rolls or looks up) and returns a new
`Combat` with its result; nothing is written. `delve.play.combat` stores the fight and writes the characters back.

A fight goes `setup` (start, monsters, surprise, declarations) to `round` once the first initiative is rolled, and to
`ended`. Each round declares its actions, rolls its initiative (`order` is empty until it has), resolves the actions
in initiative order and ends: bleeding, effects ticking down, the next round. Combatants on the same initiative act
simultaneously, as a tie in initiative means: their actions are
rolled against the state at the start of their group, and the damage is applied together.

Initiative is rolled per combatant or per side (`delve.rules.classic.initiative`, which says how it plays), and
a combatant may be busy with an ongoing action (a spell, a scroll, a potion, an item, another long action) that
completes on a count of this round or carries over to a later one, and that damage or a failed save can break.

Combatants have ids, `chr_…` for characters and `mon_<n>` for monsters, and are named by their id or their exact
name; a name that fits several, or none, raises `UnknownCombatant` with the candidates, never a guess.

The stat-line helpers are ported from ttrpg2 `tools/combat.py:139-710`.
"""

from __future__ import annotations

import itertools
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from fractions import Fraction
from typing import Any, Literal

from delve.dice import BadNotation, Dice, Roll, parse, roll_json
from delve.domain import data
from delve.domain.campaigns import Character
from delve.domain.characters import Attack, Effect, Sheet
from delve.domain.reference import RulesetReference
from delve.rules.classic import checks
from delve.rules.classic import initiative as timing
from delve.rules.classic.initiative import Mode, Ongoing, ongoing_json
from delve.rules.classic.life import DEAD_AT, with_condition
from delve.rules.classic.tables import RuleTables
from delve.rules.classic.thac0 import attack_thac0

Side = Literal["party", "ally", "enemy"]
Phase = Literal["setup", "round", "ended"]

COMBAT_ONLY = ("casting", "surprised", "charging_ac_penalty", "removed")
"""Conditions that belong to the fight and are not written back to a character when it ends."""

MONSTER_OVERRIDES = (
    "hp",
    "ac",
    "thac0",
    "dmg",
    "dmg_large",
    "morale",
    "weapon_speed",
    "label",
    "size",
    "attacks_per_round",
    "hp_max",
)
"""The stats a monster's entry may be overridden with, as ttrpg2's `setup_combat` specs, and its `hp_max` (backlog
Fixes 10)."""


class CombatError(ValueError):
    """A command the state of the fight refuses; `hint` says what would work."""

    def __init__(self, message: str, hint: str = "") -> None:
        self.message = message
        self.hint = hint
        super().__init__(message)


class CombatActive(CombatError):
    """A fight is already under way in the campaign."""


class UnknownCombatant(CombatError, LookupError):
    """A name that fits no combatant, or several. `candidates` are `{"id", "name", "side"}`."""

    def __init__(self, message: str, candidates: Iterable[Combatant] = ()) -> None:
        self.candidates = [{"id": c.id, "name": c.name, "side": c.side} for c in candidates]
        super().__init__(message, "Name one of the candidates exactly, or use its id." if self.candidates else "")


@dataclass(frozen=True)
class AttackBlock:
    """One validated attack form. Its THAC0 and damage already include the attacker's bonuses."""

    name: str
    damage_sm: str
    damage_l: str
    thac0: int | None = None
    speed: int = 5
    rate: float = 1.0
    """Attacks per round: 1.5 is three every two rounds."""


@dataclass(frozen=True)
class Combatant:
    id: str
    name: str
    side: Side
    character_id: str | None = None
    hp: int = 0
    hp_max: int = 0
    ac: int = 10
    thac0: int = 20
    attacks: tuple[AttackBlock, ...] = ()
    size: str = "M"
    ac_vs_larger: int = 0
    conditions: tuple[str, ...] = ()
    effects: tuple[Effect, ...] = ()
    init: int | None = None
    init_roll: int | None = None
    """The d10 its `init` was rolled from (its side's in `side` mode), so a late declaration can place it again."""
    node: str | None = None
    """Its room on the map, as a node id or a name `resolve_node` knows."""
    morale: int | None = None
    weapon: int = 0
    """The attack in `attacks` it uses, until it picks another."""
    attacks_used: int = 0
    """Attacks made this round."""
    ongoing: Ongoing | None = None
    """The long action it is busy with, until the end of the round it completed or broke in."""
    group: str = ""
    """A monster's type, as it was added: "Goblin"."""
    hit_dice: str = ""
    xp_value: str = ""
    treasure_type: str = ""

    @property
    def casting(self) -> str | None:
        """The spell (or scroll) it is casting, while that is under way."""
        o = self.ongoing
        return o.what if o is not None and o.kind in timing.SPOILT_BY_HARM and o.under_way else None


@dataclass(frozen=True)
class Combat:
    phase: Phase = "setup"
    round: int = 1
    order: tuple[str, ...] = ()
    """This round's initiative order; empty until its initiative is rolled."""
    current: int = 0
    combatants: dict[str, Combatant] = field(default_factory=dict)
    surprise: dict[str, bool] = field(default_factory=lambda: {"party": False, "enemies": False})
    """The sides that lose the first round."""
    declared: dict[str, dict[str, Any]] = field(default_factory=dict)
    """This round's action of each combatant that declared one."""
    log: tuple[dict[str, Any], ...] = ()
    map: str | None = None
    """The map the fight is on, for its tokens."""
    mode: Mode = "combatant"
    """How this round's initiative was rolled: per combatant or per side."""


@dataclass(frozen=True)
class RoundResult:
    round: int
    initiative: dict[str, Any] | None
    """The initiative rolled for the round; None when it was rolled before (round 1, by setup)."""
    actions: tuple[dict[str, Any], ...]
    end_of_round: tuple[str, ...]
    """Bleeding and expired effects, one line each."""
    morale_due: tuple[dict[str, Any], ...]
    rolls: tuple[Roll, ...]
    """Every roll of the round, in order."""
    unused_attacks: dict[str, int] = field(default_factory=dict)
    living_foes: dict[str, list[str]] = field(default_factory=dict)
    mode: Mode = "combatant"
    slots: tuple[dict[str, Any], ...] = ()
    """The round's order as it was set, before its actions (`slots`); the record B2's timeline reads."""
    outcomes: dict[str, Any] = field(default_factory=dict)
    """Who acted, went down, died or fled, and which ongoing actions completed or broke (`outcomes`)."""
    ongoing: tuple[dict[str, Any], ...] = ()
    """The ongoing actions that carry over into the next round."""

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "round": self.round,
            "actions": list(self.actions),
            "end_of_round": list(self.end_of_round),
            "outcomes": self.outcomes,
            "rolls": [roll_json(r) for r in self.rolls],
        }
        if self.ongoing:
            out["ongoing"] = list(self.ongoing)
        if self.initiative is not None:
            out["initiative"] = self.initiative
        if self.morale_due:
            out["morale_due"] = list(self.morale_due)
        if self.unused_attacks:
            out["unused_attacks"] = self.unused_attacks
            out["living_foes"] = self.living_foes
            out["unused_note"] = "Their targets fell and these attacks were lost: name fallback targets in targets."
        return out


def to_json(combat: Combat) -> dict[str, Any]:
    return data.to_dict(combat)


def from_json(raw: Mapping[str, Any]) -> Combat:
    """A stored fight. One stored before ongoing actions (0021) has a per-round `casting` on its casters: it reads as
    a spell that goes off this round."""
    raw = dict(raw)
    round_no = int(raw.get("round") or 1)
    combatants = {}
    for id, c in (raw.get("combatants") or {}).items():
        c = dict(c)
        spell = c.pop("casting", None)
        if spell and c.get("ongoing") is None:
            c["ongoing"] = {"kind": "spell", "what": spell, "started_round": round_no, "completes_round": round_no}
            c["conditions"] = with_condition(tuple(c.get("conditions") or ()), "casting", True)
        combatants[id] = c
    raw["combatants"] = combatants
    return data.from_dict(Combat, raw)


# --- dice notation and sizes (ttrpg2 combat.py:139-245) --------------------------------------------------------

_DICE_RE = re.compile(r"^\s*(\d*)d(\d+)((?:\s*[+-]\s*\d+)*)\s*$", re.IGNORECASE)

# Damage-vs-Large (a weapon's second damage die) applies to targets of size Large or bigger.
_LARGE_SIZES = ("l", "h", "g")


def _parse_dice(notation: Any) -> tuple[int, int, int] | None:
    """Parse 'NdX+Y' into (count, sides, modifier), or None if unparseable.

    Also accepts a bare integer ('1', '3') for the handful of stat lines that give flat damage."""
    if isinstance(notation, int | float):
        return (0, 0, int(notation))
    s = str(notation or "").strip()
    if not s:
        return None
    if re.fullmatch(r"-?\d+", s):
        return (0, 0, int(s))
    m = _DICE_RE.match(s)
    if not m:
        return None
    count = int(m.group(1)) if m.group(1) else 1
    sides = int(m.group(2))
    if count < 1 or sides < 1:
        return None
    mod = sum(int(p.replace(" ", "")) for p in re.findall(r"[+-]\s*\d+", m.group(3) or ""))
    return (count, sides, mod)


def _rollable(notation: Any) -> bool:
    """Whether the dice can roll it: it parses, and it is within the notation limits."""
    parsed = _parse_dice(notation)
    if parsed is None:
        return False
    if parsed[0] == 0:
        return True
    try:
        parse(_notation(parsed))
    except BadNotation:
        return False
    return True


def _notation(parsed: tuple[int, int, int]) -> str:
    count, sides, mod = parsed
    return f"{count}d{sides}{mod:+d}" if mod else f"{count}d{sides}"


def _roll_damage(dice: Dice, notation: str, **key: Any) -> tuple[int, Roll | None]:
    """Roll a damage expression, at least 0. A flat number rolls nothing."""
    parsed = _parse_dice(notation)
    if parsed is None:
        raise CombatError(f"Unparseable dice notation: {notation!r}")
    if parsed[0] == 0:
        return max(0, parsed[2]), None
    roll = dice.roll(_notation(parsed), **key)
    return max(0, roll.total), roll


NATURAL_WEAPON_SPEED = {"T": 0, "S": 3, "M": 3, "L": 6, "H": 9, "G": 12}
"""The initiative modifier of a monster attacking with natural weapons, by its size."""


def _monster_speed(weapon_speed: Any, damage: Any, size_code: str) -> int:
    """A monster's initiative modifier: the `weapon_speed` it was given; else 5, the usual weapon's, for one whose
    damage line says it fights by weapon; else its size's, for natural weapons."""
    if weapon_speed is not None:
        return int(weapon_speed)
    if re.search(r"weapon", str(damage or ""), re.IGNORECASE):
        return 5
    return NATURAL_WEAPON_SPEED[size_code]


def _size_code(raw: Any) -> str:
    """First letter of a monster size line: 'Large (9' tall)' → 'L'.

    Returns 'M' when the line says nothing usable — man-sized is the safe default, since it selects the S/M damage
    die."""
    s = str(raw or "").strip()
    if not s:
        return "M"
    first = s[0].upper()
    return first if first in ("T", "S", "M", "L", "H", "G") else "M"


_SIZE_RANK = {"T": 0, "S": 1, "M": 2, "L": 3, "H": 4, "G": 5}

# Default size by race for a sheet that says nothing but M (under 4' tall is Small).
_RACE_SIZES = {
    "human": "M",
    "elf": "M",
    "half-elf": "M",
    "halfelf": "M",
    "dwarf": "M",
    "half-orc": "M",
    "halforc": "M",
    "orc": "M",
    "halfling": "S",
    "gnome": "S",
    "kender": "S",
    "pixie": "S",
    "sprite": "T",
    "brownie": "T",
    "goblin": "S",
    "kobold": "S",
    "lizardfolk": "M",
    "lizard man": "M",
    "tabaxi": "M",
    "bugbear": "L",
    "minotaur": "L",
    "ogre": "L",
}


def _size_rank(code: Any) -> int:
    return _SIZE_RANK.get(_size_code(code), 2)


def _pc_size(sheet: Sheet) -> str:
    """A character's size code: the sheet's own `size` when it isn't the default M, else the race default."""
    if _size_code(sheet.size) != "M":
        return _size_code(sheet.size)
    return _RACE_SIZES.get(sheet.race.strip().lower(), "M")


def _takes_large_damage(size_code: str) -> bool:
    return str(size_code or "M").lower() in _LARGE_SIZES


def _attack_rate(entry: Mapping[str, Any]) -> float:
    """Attacks per round from an attack block. Accepts 1.5, '3/2', '2'."""
    raw = entry.get("attacks", 1)
    if isinstance(raw, int | float):
        return max(0.5, float(raw))
    s = str(raw).strip()
    m = re.fullmatch(r"(\d+)\s*/\s*(\d+)", s)
    if m and int(m.group(2)):
        return max(0.5, int(m.group(1)) / int(m.group(2)))
    try:
        return max(0.5, float(s))
    except ValueError:
        return 1.0


def _rate_text(rate: float) -> str:
    """1.5 → '3/2', 0.5 → '1/2', 2.0 → '2'."""
    return str(Fraction(rate).limit_denominator(12))


def _attacks_allowed_in_round(rate: float, round_no: int) -> int:
    """How many attacks a rate allows in this round alone.

    floor(rate x round) - floor(rate x (round-1)): a 3/2 fighter gets one swing in round 1, two in round 2, one in
    round 3; a 1/2 creature none in round 1 and one in round 2. Stateless in the round number: an entitlement is spent
    in its own round or lost, so a fighter who spent a round unconscious can't bank swings."""
    r = max(1, int(round_no))
    exact = Fraction(rate).limit_denominator(12)
    return int(exact * r) - int(exact * (r - 1))


def _normalize_attacks(label: str, attacks: Iterable[Attack]) -> tuple[list[AttackBlock], list[str]]:
    """Turn a sheet's `attacks` into validated attack blocks.

    Returns (blocks, warnings). A block whose S/M damage won't parse is dropped and reported — better a loud warning
    at setup than a silent 1-point hit."""
    blocks: list[AttackBlock] = []
    warnings: list[str] = []
    for entry in attacks:
        name = str(entry.name or "attack").strip()
        dmg_sm = entry.damage_sm or ""
        if not _rollable(dmg_sm):
            warnings.append(
                f"{label}: attack '{name}' has unusable S/M damage {dmg_sm!r} — skipped. Fix the sheet's attacks[] entry."
            )
            continue
        dmg_l = entry.damage_l or ""
        if dmg_l and not _rollable(dmg_l):
            warnings.append(
                f"{label}: attack '{name}' has unusable L damage {dmg_l!r} — "
                f"falling back to the S/M die against large targets."
            )
            dmg_l = ""
        blocks.append(
            AttackBlock(
                name=name,
                damage_sm=str(dmg_sm),
                damage_l=str(dmg_l or dmg_sm),
                thac0=int(entry.thac0) if entry.thac0 is not None else None,
                speed=int(entry.speed or 5),
                rate=_attack_rate({"attacks": entry.attacks}),
            )
        )
    return _magic_speeds(blocks), warnings


_BONUS = re.compile(r"\+\s*(\d+)")
_AGAINST = re.compile(r"\s+vs\.?\s+", re.IGNORECASE)


def _stem(name: str) -> str:
    """A weapon's name without its bonuses: 'Grudgekeeper (+1)' and 'Grudgekeeper vs Yorke (+3)' are 'grudgekeeper'."""
    return re.sub(r"[\s()]+$", "", _BONUS.sub("", _AGAINST.split(name)[0])).strip().lower()


def _magic_speeds(blocks: list[AttackBlock]) -> list[AttackBlock]:
    """Each bonus point of a magical weapon reduces its speed factor by 1, never below 0.
    Of two bonuses the lesser is used, so a block against one foe ('Grudgekeeper vs Yorke (+3)') takes the bonus of
    its plain block ('Grudgekeeper (+1)') when there is one. A sheet has no bonus field: it is read from the name."""
    plain = {
        _stem(b.name): min(map(int, _BONUS.findall(b.name)))
        for b in blocks
        if _BONUS.search(b.name) and not _AGAINST.search(b.name)
    }
    out = []
    for b in blocks:
        bonuses = [int(n) for n in _BONUS.findall(b.name)]
        if not bonuses:
            out.append(b)
            continue
        bonus = min(bonuses)
        if _AGAINST.search(b.name) and _stem(b.name) in plain:
            bonus = min(bonus, plain[_stem(b.name)])
        out.append(replace(b, speed=max(0, b.speed - bonus)))
    return out


_RANGED = re.compile(r"\b(thrown|throw|hurled|missile|ranged)\b", re.IGNORECASE)


def _select_attack(combatant: Combatant, wanted: str) -> tuple[int | None, str]:
    """Find one of a combatant's attack blocks by (partial) name. Returns (index, note). An exact name wins; then a
    name holding `wanted` as a whole word, a melee block before one marked thrown or missile unless `wanted` asks for
    one, so "Dagger" in melee is the melee dagger, not "Dagger (thrown)" (backlog Fixes 10); then a case-insensitive
    substring, shortest name first, so 'undead' picks 'Sunsweep long sword +3 (vs undead)'."""
    blocks = combatant.attacks
    if not blocks:
        return None, f"{combatant.name} has no attack blocks on their sheet — using their current weapon."
    needle = str(wanted or "").strip().lower()
    if not needle:
        return None, ""
    exact = [i for i, b in enumerate(blocks) if b.name.lower() == needle]
    if exact:
        return exact[0], ""
    word = re.compile(rf"(?<!\w){re.escape(needle)}(?!\w)")
    whole = sorted((i for i, b in enumerate(blocks) if word.search(b.name.lower())), key=lambda i: len(blocks[i].name))
    if whole:
        melee = [i for i in whole if not _RANGED.search(blocks[i].name)]
        return (whole if _RANGED.search(needle) or not melee else melee)[0], ""
    hits = sorted((i for i, b in enumerate(blocks) if needle in b.name.lower()), key=lambda i: len(blocks[i].name))
    if hits:
        return hits[0], ""
    current = blocks[combatant.weapon].name or "current weapon"
    return None, (
        f"No attack matching {wanted!r} for {combatant.name}; available: {[b.name for b in blocks]}. Kept {current}."
    )


# --- monster stat lines (ttrpg2 combat.py:496-670) --------------------------------------------------------------
# A bestiary stores prose, not numbers: AC "5 (10)", HD "4+4" / "½" / "1-4 hp", morale "Elite (13-14)", damage
# "2-8" or "By weapon". These parse best-effort and the DM can always override with an explicit value.


def _first_int(text: Any, default: int | None = None) -> int | None:
    """First signed integer in a string, or `default`."""
    if isinstance(text, int | float):
        return int(text)
    m = re.search(r"-?\d+", str(text or ""))
    return int(m.group()) if m else default


def _parse_ac(raw: Any, default: int = 10) -> int:
    """'5' → 5 · '-2' → -2 · '5 (10)' → 5 · '0 (base)' → 0 · 'Varies' → default."""
    return _first_int(raw, default)


def _parse_morale(raw: Any, default: int = 10) -> int:
    """'Elite (13-14)' → 13 · 'Fearless (20)' → 20 · '11' → 11.

    Takes the low end of a range: the honest reading when the DM hasn't picked a specific value."""
    s = str(raw or "")
    paren = re.search(r"\(([^)]*)\)", s)
    if paren:
        n = _first_int(paren.group(1))
        if n is not None:
            return n
    return _first_int(s, default)


_XP_PER_HP = re.compile(r"^\s*([\d,]+)\s*\+\s*([\d,]+)\s*/\s*hp\s*$", re.IGNORECASE)


def xp_of(xp_value: str, hp_max: int) -> int | None:
    """What one defeated monster is worth: a plain number as it is, "135 +4/hp" its base and so much a hit point of
    its maximum; None for anything else ("175-975", "Varies"), which the DM reads."""
    text = str(xp_value or "").strip()
    if re.fullmatch(r"[\d,]+", text):
        return int(text.replace(",", ""))
    found = _XP_PER_HP.match(text)
    if found:
        return int(found.group(1).replace(",", "")) + int(found.group(2).replace(",", "")) * max(0, hp_max)
    return None


def _parse_hd(raw: Any) -> dict[str, Any]:
    """Parse a bestiary's Hit Dice line into a rollable shape.

    Returns {dice, sides, mod, fixed, hp_range, raw}: `fixed` is a literal HP value for the 'N hp' creatures,
    `hp_range` the [low, high] of a '1-6 hp' line (rolled per creature), and `dice` is 0 when the line carries no
    usable number ('Varies', 'Nil', 'See below') — the caller must then be given an explicit hp."""
    s = str(raw or "").strip()
    out: dict[str, Any] = {"dice": 0, "sides": 8, "mod": 0, "fixed": None, "hp_range": None, "raw": s}
    if not s:
        return out

    low = s.lower()
    if "½" in s or "1/2" in s:
        # Half-HD creatures roll d4.
        out.update(dice=1, sides=4)
        return out

    # '1 hp', '1 hit point', '1-6 hp' — literal hit points, not dice.
    if re.search(r"h(p|it\s*point)", low):
        nums = [int(n) for n in re.findall(r"\d+", s)]
        if len(nums) > 1:
            out["hp_range"] = [nums[0], nums[1]]
        elif nums:
            out["fixed"] = nums[0]
        return out

    # '8, 12, or 16' — a creature with variant grades; take the first.
    if "," in s:
        n = _first_int(s)
        if n is not None:
            out["dice"] = n
        return out

    m = re.match(r"^(\d+)\s*([+-])\s*(\d+)", s)
    if m:
        dice, sign, mod = int(m.group(1)), m.group(2), int(m.group(3))
        if sign == "-" and mod > 3:
            # '5-6' in a bestiary is an HD *range*, not a subtraction; only the small forms ('1-1', '2-2') mean "minus".
            # Take the low end.
            out["dice"] = dice
        else:
            out.update(dice=dice, mod=mod if sign == "+" else -mod)
        return out

    n = _first_int(s)
    if n is not None:
        out["dice"] = n
    return out


def _roll_monster_hp(dice: Dice, hd: Mapping[str, Any], *, actor: str) -> int | None:
    """Roll HP from a parsed HD shape, logged under purpose `hp`. None when the line gave us nothing."""
    if hd.get("fixed") is not None:
        return max(1, int(hd["fixed"]))
    if hd.get("hp_range"):
        lo, hi = sorted(int(n) for n in hd["hp_range"])
        roll = dice.roll(_notation((1, hi - lo + 1, lo - 1)), purpose="hp", actor=actor)
        return max(1, roll.total)
    count = int(hd.get("dice") or 0)
    if count <= 0:
        return None
    roll = dice.roll(_notation((count, int(hd.get("sides") or 8), int(hd.get("mod") or 0))), purpose="hp", actor=actor)
    return max(1, roll.total)


def _parse_damage(raw: Any, default: str = "1d6") -> tuple[str, bool]:
    """Normalise a bestiary's damage line to dice notation.

    '1d8' → unchanged · '1-6' → '1d6' · '2-8' → '1d7+1' (same 2..8 spread) · '1-10 or by weapon' → '1d10' ·
    '5-8/5-8/5-12' → first attack only.

    Returns (notation, parsed) — `parsed` is False for lines carrying no numbers at all ('By weapon', 'Nil',
    'Special'), where the caller gets `default` and should say so rather than pretend it read a stat block."""
    s = str(raw or "").strip()
    if not s:
        return default, False
    first = s.split("/")[0].strip()

    m = re.match(r"^(\d*)d(\d+)\s*([+-]\s*\d+)?", first, re.IGNORECASE)
    if m:
        count = m.group(1) or "1"
        mod = (m.group(3) or "").replace(" ", "")
        return f"{count}d{m.group(2)}{mod}", True

    # Prefix match, not full: bestiary lines trail prose ('1-10 or by weapon').
    m = re.match(r"^(\d+)\s*-\s*(\d+)", first)
    if m:
        lo, hi = int(m.group(1)), int(m.group(2))
        if hi > lo:
            span = hi - lo + 1
            return (f"1d{span}+{lo - 1}" if lo > 1 else f"1d{span}"), True
        return f"1d{max(1, hi)}", True

    return default, False


def _monster_stats(reference: RulesetReference, name: str) -> dict[str, Any] | None:
    """The tactically relevant slice of the reference's best monster entry for `name`, or None."""
    rows = reference.monster(name)
    if not rows:
        return None
    row = rows[0]
    return {
        "name": row.get("name"),
        "ac": row.get("armor_class"),
        "hit_dice": row.get("hit_dice"),
        "thac0": row.get("thac0"),
        "damage": row.get("damage_attack"),
        "no_of_attacks": row.get("no_of_attacks"),
        "no_appearing": row.get("no_appearing"),
        "morale": row.get("morale"),
        "xp_value": row.get("xp_value"),
        "treasure_type": row.get("treasure_type"),
        "intelligence": row.get("intelligence"),
        "alignment": row.get("alignment"),
        "size": row.get("size"),
        "move": row.get("move"),
        "special_attacks": row.get("special_attacks"),
        "special_defenses": row.get("special_defenses"),
        "magic_resistance": row.get("magic_resistance"),
    }


casting_time = timing.casting_time


# --- the state of a combatant ------------------------------------------------------------------------------------


def _is_dead(c: Combatant) -> bool:
    """Dead, not merely down. Monsters die at 0 hp; the 0 to -9 unconscious-and-bleeding band is for the party
    and its allies."""
    return c.hp <= DEAD_AT or (c.side == "enemy" and c.hp <= 0)


def _removed(c: Combatant) -> bool:
    return "removed" in c.conditions


def _can_act(c: Combatant) -> bool:
    return c.hp > 0 and not _removed(c)


def _standing(c: Combatant) -> bool:
    return not _is_dead(c) and c.hp > 0 and not _removed(c)


def _enemy_fate(c: Combatant) -> str:
    """slain (dead — a monster at 0 or below), down (an ally at exactly 0), fled (fleeing), removed, or standing."""
    if _removed(c):
        return "removed"
    if c.hp < 0 or _is_dead(c):
        return "slain"
    if c.hp == 0:
        return "down"
    if "fleeing" in c.conditions:
        return "fled"
    return "standing"


def _kind(c: Combatant) -> str:
    """The kind of a monster for XP: its group, or its name without the number setup gave it ("Goblin 3" →
    "goblin")."""
    return (c.group or re.sub(r"\s+\d+$", "", c.name)).strip().lower()


def _enemy_record(combatants: Iterable[Combatant]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Per-enemy fate plus a count of defeated (slain or down) by kind."""
    enemies, defeated = [], {}
    for c in combatants:
        if c.side == "party":
            continue
        fate = _enemy_fate(c)
        enemies.append({"id": c.id, "name": c.name, "side": c.side, "hp": c.hp, "hp_max": c.hp_max, "fate": fate})
        if fate in ("slain", "down") and c.side == "enemy":
            defeated[_kind(c)] = defeated.get(_kind(c), 0) + 1
    return enemies, defeated


def _sum_modifier(c: Combatant, key: str) -> int:
    """Total a numeric effect modifier across all active effects on a combatant."""
    return sum(int(getattr(e, key) or 0) for e in c.effects)


def _block(c: Combatant) -> AttackBlock:
    return c.attacks[c.weapon] if c.attacks else AttackBlock("", "1d6", "1d6")


def _thac0(c: Combatant) -> int:
    block = _block(c)
    return block.thac0 if block.thac0 is not None else c.thac0


def effect_json(effect: Effect) -> dict[str, Any]:
    """An effect with only the modifiers it has."""
    out: dict[str, Any] = {"name": effect.name, "duration": effect.duration}
    for key in ("to_hit", "ac", "dmg", "save", "source"):
        if getattr(effect, key):
            out[key] = getattr(effect, key)
    return out


def _effect(raw: Effect | Mapping[str, Any]) -> Effect:
    if isinstance(raw, Effect):
        return raw
    try:
        return data.from_dict(Effect, dict(raw))
    except data.DataError as error:
        raise CombatError(
            f"Bad effect: {error}", hint="An effect has name, duration and to_hit, ac, dmg, save."
        ) from None


def _amount(amount: Any) -> int:
    if isinstance(amount, bool) or not isinstance(amount, int) or amount < 0:
        raise CombatError(f"The amount must be a whole number of at least 0, not {amount!r}.")
    return amount


# --- the fight ---------------------------------------------------------------------------------------------------


def _put(combat: Combat, *changed: Combatant) -> Combat:
    return replace(combat, combatants={**combat.combatants, **{c.id: c for c in changed}})


def _logged(combat: Combat, entry: dict[str, Any]) -> Combat:
    return replace(combat, log=(*combat.log, {"round": combat.round, **entry}))


def _live(combat: Combat) -> None:
    if combat.phase == "ended":
        raise CombatError("The fight is over.", hint="Start a new one with setup_combat.")


def _in_round(combat: Combat) -> None:
    _live(combat)
    if not combat.order:
        raise CombatError(
            f"Round {combat.round} hasn't started: its initiative isn't rolled yet.",
            hint="combat_round declares the round's actions, rolls its initiative and resolves them.",
        )


def find(combat: Combat, ref: str) -> Combatant:
    """The combatant with the id `ref`, or the one whose name is exactly `ref`, ignoring case and outer spaces."""
    wanted = str(ref).strip()
    if wanted in combat.combatants:
        return combat.combatants[wanted]
    everyone = list(combat.combatants.values())
    named = [c for c in everyone if c.name.strip().casefold() == wanted.casefold()]
    if len(named) == 1:
        return named[0]
    if named:
        raise UnknownCombatant(f"'{ref}' is ambiguous: {len(named)} combatants have that name.", named)
    near = [c for c in everyone if wanted and wanted.casefold() in c.name.casefold()]
    raise UnknownCombatant(f"No combatant '{ref}'.", near or everyone)


def party_blocks(
    character: Character, reference: RulesetReference | None = None, rules: RuleTables | None = None
) -> tuple[list[AttackBlock], list[str]]:
    """A character's attack blocks as the fight rolls them, and the warnings about its sheet: its sheet's attacks, an
    attack without a stored `thac0` hitting with `thac0.attack_thac0`'s value (with a `reference`); with none usable,
    its prose `weapon` when that is dice, else 1d6. Made when the fight starts, and again when the sheet's attacks
    change during it (DEL-332)."""
    sheet = character.sheet
    attacks = sheet.attacks
    if reference is not None and rules is not None:
        attacks = tuple(
            a if a.thac0 is not None else replace(a, thac0=attack_thac0(sheet, a, reference, rules=rules).value)
            for a in attacks
        )
    blocks, warnings = _normalize_attacks(character.name, attacks)
    if not blocks:
        # No usable attacks: fall back to the prose `weapon`, but only if it actually parses as dice. It usually
        # doesn't: it holds a weapon's name.
        legacy = sheet.weapon or "1d6"
        if _rollable(legacy):
            blocks = [AttackBlock(legacy, legacy, legacy)]
        else:
            warnings.append(
                f"{character.name}: no usable attacks[] on the sheet and weapon={legacy!r} is not dice notation — "
                f"defaulted to 1d6. Add an attacks[] entry (name, thac0, damage_sm, damage_l, speed, attacks) "
                f"before this fight matters."
            )
            blocks = [AttackBlock(legacy, "1d6", "1d6")]
    return list(blocks), list(warnings)


def start(
    party: Iterable[Character],
    *,
    map_nodes: Mapping[str, str | None] | None = None,
    live: Combat | None = None,
    abort: bool = False,
    reference: RulesetReference | None = None,
    rules: RuleTables | None = None,
) -> tuple[Combat, dict[str, Any]]:
    """A new fight with the party (PCs, and NPCs as allies) at their hit points, conditions and effects, each on its
    node of `map_nodes` (by character id).

    With a `reference`, an attack without a stored `thac0` hits with `thac0.attack_thac0`'s value, what the sheet
    shows; without one, with the sheet's THAC0.

    Refuses with `CombatActive` while `live` is a fight that hasn't ended, unless `abort`."""
    if live is not None and live.phase != "ended" and not abort:
        raise CombatActive(
            "A fight is already under way.", hint="End it with end_combat before starting another, or abort it."
        )
    nodes = dict(map_nodes or {})
    combatants: dict[str, Combatant] = {}
    warnings: list[str] = []
    for character in party:
        sheet, state = character.sheet, character.state
        blocks, block_warnings = party_blocks(character, reference, rules)
        warnings.extend(block_warnings)
        combatants[character.id] = Combatant(
            id=character.id,
            name=character.name,
            side="ally" if character.kind == "npc" else "party",
            character_id=character.id,
            hp=state.hp,
            hp_max=sheet.hp_max,
            ac=sheet.ac,
            thac0=sheet.thac0,
            attacks=tuple(blocks),
            size=_pc_size(sheet),
            ac_vs_larger=sheet.ac_vs_larger,
            conditions=state.conditions,
            effects=state.effects,
            node=nodes.get(character.id),
        )
    combat = _logged(Combat(combatants=combatants), {"type": "start", "ids": list(combatants)})
    out: dict[str, Any] = {
        "party_loaded": [c.name for c in combatants.values()],
        "party_attacks": {
            c.name: {
                "weapon": _block(c).name,
                "thac0": _thac0(c),
                "damage_sm": _block(c).damage_sm,
                "damage_l": _block(c).damage_l,
                "speed": _block(c).speed,
                "per_round": _block(c).rate,
                "alternates": [b.name for b in c.attacks[1:]],
            }
            for c in combatants.values()
        },
    }
    if warnings:
        out["warnings"] = warnings
    return combat, out


def add_monsters(
    combat: Combat,
    dice: Dice,
    reference: RulesetReference,
    name: str,
    count: int = 1,
    *,
    node: str | None = None,
    side: Side = "enemy",
    overrides: Mapping[str, Any] | None = None,
) -> tuple[Combat, dict[str, Any]]:
    """`count` monsters of the reference's entry for `name`, each with its own hit points rolled from its Hit Dice
    (purpose `hp`), as `mon_<n>` and named "Goblin 1", "Goblin 2"… (just "Goblin" for one).

    `overrides` replace what the entry says: hp, ac, thac0, dmg, dmg_large, morale, weapon_speed, label, size and
    attacks_per_round. The result is the group, with the stats the DM needs for morale and treasure."""
    _live(combat)
    over = dict(overrides or {})
    unknown = sorted(set(over) - set(MONSTER_OVERRIDES))
    if unknown:
        raise CombatError(
            f"Unknown monster stat '{unknown[0]}'.", hint=f"Override any of {', '.join(MONSTER_OVERRIDES)}."
        )
    if side not in ("party", "ally", "enemy"):
        raise CombatError(f"Unknown side '{side}'.", hint="Use enemy, ally or party.")
    raw_name = str(name or "").strip()
    if not raw_name:
        raise CombatError("A monster needs a name.")
    count = max(1, int(count or 1))
    notes: list[str] = []
    stats = _monster_stats(reference, raw_name)
    if stats is None:
        notes.append(f"'{raw_name}' not found in the monster DB — using the supplied/default stats.")
        stats = {}

    hd = _parse_hd(stats.get("hit_dice"))
    ac = int(over["ac"]) if over.get("ac") is not None else _parse_ac(stats.get("ac"))
    thac0 = int(over["thac0"]) if over.get("thac0") is not None else _first_int(stats.get("thac0"), 20)
    if over.get("dmg"):
        dmg, dmg_parsed = str(over["dmg"]), True
        if not _rollable(dmg):
            raise CombatError(
                f"dmg={dmg!r} is not dice notation (e.g. '1d8', '2d6+1'). "
                f"Pass the creature's damage dice, not its weapon's name."
            )
    else:
        dmg, dmg_parsed = _parse_damage(stats.get("damage"))
    dmg_large = str(over.get("dmg_large") or "")
    if dmg_large and not _rollable(dmg_large):
        raise CombatError(f"dmg_large={dmg_large!r} is not dice notation.")
    morale = int(over["morale"]) if over.get("morale") is not None else _parse_morale(stats.get("morale"))
    if over.get("label"):
        base_label = str(over["label"]).strip()
    else:
        # DB names are lower-case ("goblin shaman"); a display label the caller supplied is left as they wrote it.
        base_label = str(stats.get("name") or raw_name).strip().title()
    size_code = _size_code(over.get("size") or stats.get("size") or "M")
    wspeed = _monster_speed(over.get("weapon_speed"), stats.get("damage"), size_code)
    # A plain integer attack line ("3") is a real attack rate; anything else ("1 or 2", "See below") stays at 1 and the
    # note below tells the DM to resolve the extras by hand.
    atk_raw = str(stats.get("no_of_attacks") or "").strip()
    atk_rate = float(atk_raw) if re.fullmatch(r"\d+", atk_raw) else 1.0
    if over.get("attacks_per_round") is not None:
        atk_rate = _attack_rate({"attacks": over["attacks_per_round"]})

    if over.get("hp") is None and hd.get("dice", 0) <= 0 and hd.get("fixed") is None and not hd.get("hp_range"):
        notes.append(
            f"'{base_label}' HD reads {hd.get('raw')!r} — no rollable dice. Defaulted to 1d8; pass hp= to set it "
            f"honestly."
        )
    if not dmg_parsed:
        notes.append(
            f"'{base_label}' damage reads {stats.get('damage')!r} — no dice in the line. "
            f"Defaulted to {dmg}; pass dmg= (e.g. from the creature's weapon) before it swings."
        )
    if atk_raw and atk_raw not in ("1", "Nil"):
        if atk_rate > 1:
            notes.append(
                f"'{base_label}' gets {atk_rate:g} attacks/round — every one is resolved in its action. Its damage "
                f"line is {stats.get('damage')!r}: if the attacks differ, pass dmg= per swing."
            )
        else:
            notes.append(
                f"'{base_label}' attack line reads {atk_raw!r} ({stats.get('damage')!r}) — "
                f"left at 1/round; pass attacks_per_round= if it should be more."
            )

    group: dict[str, Any] = {
        "type": base_label,
        "size_code": size_code,
        "attacks_per_round": atk_rate,
        "matched": stats.get("name"),
        "count": count,
        "ac": ac,
        "thac0": thac0,
        "damage": dmg,
        "hit_dice": hd.get("raw"),
        "morale_rating": morale,
        "individuals": [],
    }
    for extra in (
        "treasure_type",
        "intelligence",
        "alignment",
        "size",
        "move",
        "no_of_attacks",
        "special_attacks",
        "special_defenses",
        "magic_resistance",
        "xp_value",
    ):
        if stats.get(extra) not in (None, ""):
            group[extra] = stats[extra]

    taken = [int(i[4:]) for i in combat.combatants if re.fullmatch(r"mon_\d+", i)]
    first = max(taken, default=0) + 1
    added = []
    for i in range(count):
        id = f"mon_{first + i}"
        if over.get("hp") is not None:
            hp = int(over["hp"])
        elif over.get("hp_max") is not None:
            hp = int(over["hp_max"])
        else:
            hp = _roll_monster_hp(dice, hd, actor=id)
            if hp is None:
                # The HD line carried no usable number; 1d8 keeps the fight moving and `notes` tells the DM.
                hp = dice.d(8, purpose="hp", actor=id).total
        added.append(
            Combatant(
                id=id,
                name=f"{base_label} {i + 1}" if count > 1 else base_label,
                side=side,
                hp=hp,
                hp_max=max(hp, int(over["hp_max"])) if over.get("hp_max") is not None else hp,
                ac=ac,
                thac0=thac0,
                attacks=(AttackBlock("", dmg, dmg_large or dmg, None, wspeed, atk_rate),),
                size=size_code,
                node=node,
                morale=morale,
                group=base_label,
                hit_dice=str(stats.get("hit_dice") or ""),
                xp_value=str(stats.get("xp_value") or ""),
                treasure_type=str(stats.get("treasure_type") or ""),
            )
        )
        group["individuals"].append({"id": id, "name": added[-1].name, "hp": hp})
    if notes:
        group["notes"] = notes
    combat = _logged(_put(combat, *added), {"type": "added", "group": base_label, "ids": [c.id for c in added]})
    return combat, group


def apply_surprise(combat: Combat, result: checks.SurpriseResult) -> tuple[Combat, dict[str, Any]]:
    """A surprised side loses the first round. Its combatants are marked `surprised` and get no
    action in round 1. When both sides are surprised, neither gains."""
    if combat.phase != "setup":
        raise CombatError("Surprise is settled before the first round.")
    party, enemies = result.party_surprised, result.enemies_surprised
    if party and enemies:
        party = enemies = False
    sides = (("party", "ally") if party else ()) + (("enemy",) if enemies else ())
    surprised = [c for c in combat.combatants.values() if c.side in sides]
    combat = _put(combat, *(replace(c, conditions=with_condition(c.conditions, "surprised", True)) for c in surprised))
    combat = _logged(
        replace(combat, surprise={"party": party, "enemies": enemies}),
        {"type": "surprise", "ids": [c.id for c in surprised]},
    )
    return combat, {
        "party_surprised": result.party_surprised,
        "enemies_surprised": result.enemies_surprised,
        "party_roll": result.rolls["party"].total,
        "enemy_roll": result.rolls["enemies"].total,
        "party_threshold": result.party_threshold,
        "enemy_threshold": result.enemy_threshold,
        "description": result.description,
        "loses_first_round": [c.name for c in surprised],
        "rolls": [roll_json(r) for r in result.all_rolls],
    }


def _starting(
    combat: Combat, c: Combatant, kind: str, what: str, reference: RulesetReference | None, rounds: int | None = None
) -> Combatant:
    """`c` busy with a new ongoing action from this round: its duration from the reference (a spell's or a scroll's
    casting time, an item's modifier) or `rounds` for another action. A spell or scroll marks it `casting`."""
    if rounds is not None:
        span, modifier = max(1, rounds) - 1, timing.ROUND_END
    else:
        span, modifier = timing.duration(kind, what, reference)
    ongoing = Ongoing(
        kind="item" if kind in timing.ITEM_MODIFIERS and kind != "potion" else kind,  # type: ignore[arg-type]
        what=what,
        started_round=combat.round,
        completes_round=combat.round + span,
        completes_count=timing.ROUND_END if span else None,
        modifier=modifier if reference is not None or rounds is not None else None,
    )
    casting = kind in timing.SPOILT_BY_HARM
    return replace(c, ongoing=ongoing, conditions=with_condition(c.conditions, "casting", casting))


def declare(
    combat: Combat,
    id: str,
    action: Mapping[str, Any],
    reference: RulesetReference | None = None,
    rules: RuleTables | None = None,
) -> tuple[Combat, dict[str, Any]]:
    """The round's action of a combatant, before it resolves:

    - an attack: `target`, and optionally `targets` (fallbacks, in order), `weapon` (one of its attacks, by name)
      and `condition` (rear, charging, set_vs_charge, fleeing);
    - a spell: `spell`, and optionally `target`. Its casting time is the caster's initiative modifier; one
      of a round or more takes effect at the end of its last round; damage or a failed save before then spoils it;
    - a magic item: `item` and its `kind` (potion, scroll, ring, rod, stave, wand, item), with its kind's modifier; a
      scroll's `spell` (or an item named "scroll of …") gives its casting time;
    - anything else: `action`, in words, and `rounds` when it takes that many rounds (an ongoing action).

    The actor's own key (`attacker`, `caster` or `actor`) may be in `action` too. A combatant has one action a round;
    a second declaration replaces the first, and a new action abandons an ongoing one. Declared after the round's
    initiative is rolled (round 1 after setup_combat), the declarer is placed again at its new count, on the roll
    it already has, and `hint` says so (backlog Fixes 10: Sleep in round 1); its weapon's speed counts only where
    `rules` add it to initiative, as `roll_initiative`'s."""
    _live(combat)
    c = find(combat, id)
    raw = {k: v for k, v in action.items() if k not in ("attacker", "caster", "actor")}
    out: dict[str, Any]
    before = c.ongoing
    c = replace(c, ongoing=None, conditions=with_condition(c.conditions, "casting", False))
    if raw.get("spell") and str(raw.get("kind") or "spell") == "spell" and not raw.get("item"):
        spell = str(raw["spell"]).strip()
        declared: dict[str, Any] = {"spell": spell}
        out = {"caster": c.name, "caster_id": c.id, "spell": spell}
        if raw.get("target"):
            target = find(combat, str(raw["target"]))
            declared["target"] = target.id
            out.update(target=target.name, target_id=target.id)
        c = _starting(combat, c, "spell", spell, reference)
    elif raw.get("item"):
        kind = str(raw.get("kind") or "item").strip().lower()
        item = str(raw["item"]).strip()
        if kind not in (*timing.ITEM_MODIFIERS, "scroll"):
            raise CombatError(
                f"Unknown kind of item '{kind}'.", hint="kind is potion, scroll, ring, rod, stave, wand or item."
            )
        if kind == "scroll":
            spell = str(raw.get("spell") or re.sub(r"^\s*scroll\s+of\s+", "", item, flags=re.IGNORECASE)).strip()
            declared = {"spell": spell, "item": item, "kind": "scroll"}
            out = {"caster": c.name, "caster_id": c.id, "spell": spell, "scroll": item}
            c = _starting(combat, c, "scroll", spell, reference)
        else:
            declared = {"item": item, "kind": kind}
            out = {"actor": c.name, "actor_id": c.id, "item": item, "kind": kind}
            c = _starting(combat, c, kind, item, reference)
        if raw.get("target"):
            target = find(combat, str(raw["target"]))
            declared["target"] = target.id
            out.update(target=target.name, target_id=target.id)
    elif raw.get("missile") and raw.get("target"):
        kind = str(raw["missile"]).strip().lower().removeprefix("flask of ").removeprefix("vial of ")
        if kind not in MISSILES:
            raise CombatError(f"Unknown missile '{raw['missile']}'.", hint=f"Throw one of: {', '.join(MISSILES)}.")
        target = find(combat, str(raw["target"]))
        declared = {"missile": kind, "target": target.id}
        out = {"attacker": c.name, "attacker_id": c.id, "missile": kind, "target": target.name, "target_id": target.id}
    elif raw.get("target"):
        target = find(combat, str(raw["target"]))
        fallbacks = [find(combat, str(t)).id for t in raw.get("targets") or []]
        declared = {
            "target": target.id,
            "targets": fallbacks,
            "condition": str(raw.get("condition") or ""),
        }
        out = {"attacker": c.name, "attacker_id": c.id, "target": target.name, "target_id": target.id}
        if raw.get("weapon"):
            index, note = _select_attack(c, str(raw["weapon"]))
            if index is not None:
                c = replace(c, weapon=index)
                out["weapon"] = c.attacks[index].name
            elif note:
                out["note"] = note
    elif raw.get("action"):
        declared = {"action": str(raw["action"])}
        out = {"actor": c.name, "actor_id": c.id, "action": declared["action"]}
        if raw.get("rounds") is not None:
            rounds = raw["rounds"]
            if isinstance(rounds, bool) or not isinstance(rounds, int) or rounds < 1:
                raise CombatError(f"rounds must be a whole number of at least 1, not {rounds!r}.")
            declared["rounds"] = rounds
            out["rounds"] = rounds
            c = _starting(combat, c, "other", declared["action"], reference, rounds=rounds)
    else:
        raise CombatError(
            f"What does {c.name} do?",
            hint="An action is an attack (target), a thrown missile (missile: oil or holy water, target), a spell "
            "(spell), a magic item (item, kind) or anything else (action, in words; rounds when it takes that long).",
        )
    if before is not None and before.under_way and before.started_round < combat.round:
        out["abandons"] = before.what
        combat = _logged(combat, _broke(c, before, f"{c.name} turned to something else"))
    combat = _put(combat, c)
    combat = replace(combat, declared={**combat.declared, c.id: declared})
    if combat.order and c.init_roll is not None:
        combat, placed = _place_again(combat, c.id, reference, rules)
        if placed is not None:
            out["hint"] = placed
    return combat, out


def _modifier(c: Combatant, reference: RulesetReference | None) -> int:
    """Its initiative modifier this round: its ongoing action's, else its weapon's speed."""
    o = c.ongoing
    if o is None or not o.under_way:
        return _block(c).speed
    if o.modifier is not None:
        return o.modifier
    return timing.duration(o.kind, o.what, reference)[1] if o.kind != "other" else timing.ROUND_END


def _resolved(c: Combatant, reference: RulesetReference | None) -> Combatant:
    """An ongoing action declared without the reference (an old fight's, or a direct `declare`) gets its duration."""
    o = c.ongoing
    if o is None or o.modifier is not None or o.kind == "other":
        return c
    span, modifier = timing.duration(o.kind, o.what, reference)
    return replace(
        c, ongoing=replace(o, modifier=modifier, completes_round=max(o.completes_round, o.started_round + span))
    )


def _ends_round(c: Combatant) -> bool:
    o = c.ongoing
    return o is not None and o.under_way and o.ends_round


def _round_end(combat: Combat) -> int:
    """The count of what takes effect at the round's end: after every other count, and at least 10."""
    counts = [c.init for c in combat.combatants.values() if c.init is not None and not _ends_round(c)]
    return max([timing.ROUND_END, *counts])


def _ordered(combat: Combat) -> Combat:
    """The order of the combatants with an initiative: lowest count first, what ends the round last, then as added.
    Each ongoing action completing this round learns its count."""
    end = _round_end(combat)
    changed = []
    for c in combat.combatants.values():
        if c.init is None:
            continue
        if _ends_round(c):
            c = replace(c, init=end)
        o = c.ongoing
        if o is not None and o.under_way and o.completes_round == combat.round:
            c = replace(c, ongoing=replace(o, completes_count=c.init))
        changed.append(c)
    combat = _put(combat, *changed)
    added = {id: i for i, id in enumerate(combat.combatants)}
    placed = [c for c in combat.combatants.values() if c.init is not None and c.id in combat.order]
    placed.sort(key=lambda c: (c.init, _ends_round(c), added[c.id]))
    return replace(combat, order=tuple(c.id for c in placed))


def _speed(c: Combatant, reference: RulesetReference | None, rules: RuleTables | None) -> int:
    """What it adds to its initiative roll: an ongoing action's modifier always, its weapon's speed only where the
    ruleset adds it (every ruleset without `rules`)."""
    busy = c.ongoing is not None and c.ongoing.under_way
    weapons = rules.weapon_speed_in_initiative if rules is not None else True
    return _modifier(c, reference) if busy or weapons else 0


def _place_again(
    combat: Combat, id: str, reference: RulesetReference | None, rules: RuleTables | None = None
) -> tuple[Combat, str | None]:
    """A declaration after the round's initiative: the combatant acts on its roll plus its new modifier."""
    c = _resolved(combat.combatants[id], reference)
    roll = c.init_roll or 0
    modifier = _speed(c, reference, rules)
    was = c.init
    combat = _ordered(_put(combat, replace(c, init=roll + modifier)))
    now = combat.combatants[id].init
    if now == was:
        return combat, None
    how = "at the end of the round" if _ends_round(combat.combatants[id]) else f"(the roll {roll} plus {modifier})"
    return combat, f"Declared after round {combat.round}'s initiative: {c.name} now acts on {now} {how}."


def _initiative(
    combat: Combat,
    dice: Dice,
    reference: RulesetReference | None,
    mode: Mode = "combatant",
    rules: RuleTables | None = None,
) -> tuple[Combat, dict[str, Any], list[Roll]]:
    _live(combat)
    if combat.order:
        raise CombatError(f"Round {combat.round}'s initiative is already rolled.")
    if mode not in ("combatant", "side"):
        raise CombatError(f"Unknown initiative mode '{mode}'.", hint="Use combatant or side.")
    rolls: list[Roll] = []
    die = rules.initiative_die if rules is not None else 10
    able = [_resolved(c, reference) for c in combat.combatants.values() if _can_act(c)]
    sides: dict[str, Roll] = {}
    if mode == "side":
        # One die for each side; each combatant adds its own modifier.
        for side in dict.fromkeys(timing.side_of(c.side) for c in combat.combatants.values()):
            if any(timing.side_of(c.side) == side for c in able):
                sides[side] = dice.d(die, purpose="initiative", actor=f"side:{side}", combat_round=combat.round)
                rolls.append(sides[side])
    updated = [replace(c, init=None, init_roll=None) for c in combat.combatants.values() if not _can_act(c)]
    for c in able:
        if mode == "side":
            face: int | None = sides[timing.side_of(c.side)].total
        elif _ends_round(c):
            # A spell of a round or more rolls no initiative: it ends the round.
            face = None
        else:
            roll = dice.d(die, purpose="initiative", actor=c.id, combat_round=combat.round)
            rolls.append(roll)
            face = roll.total
        speed = _speed(c, reference, rules)
        updated.append(replace(c, init=(face or 0) + speed, init_roll=face))
    combat = _put(combat, *updated)
    combat = _ordered(replace(combat, order=tuple(c.id for c in able), mode=mode))
    entries = []
    for id in combat.order:
        c = combat.combatants[id]
        entry = {
            "id": c.id,
            "name": c.name,
            "roll": c.init_roll,
            "speed": _speed(c, reference, rules),
            "total": c.init,
            "side": c.side,
        }
        if mode == "side":
            entry["group"] = timing.side_of(c.side)
        if _ends_round(c):
            entry["end_of_round"] = True
        entries.append(entry)
    combat = _logged(replace(combat, phase="round", current=0), {"type": "initiative", "order": list(combat.order)})
    out: dict[str, Any] = {"round": combat.round, "mode": mode, "order": entries}
    if mode == "side":
        out["sides"] = {side: roll.total for side, roll in sides.items()}
    return combat, out, rolls


def roll_initiative(
    combat: Combat,
    dice: Dice,
    reference: RulesetReference | None,
    mode: Mode = "combatant",
    rules: RuleTables | None = None,
) -> tuple[Combat, dict[str, Any]]:
    """Initiative, lowest first, combatants on the same total acting together. `combatant`: each combatant who can act
    rolls d10 plus its weapon speed, or the casting time of the spell it declared, or its item's modifier. `side`: one
    d10 for the party and its allies and one for the enemies, each combatant adding its own modifier.
    A spell of a round or more rolls nothing and takes effect at the round's end, after every other count."""
    combat, out, rolls = _initiative(combat, dice, reference, mode, rules)
    return combat, {**out, "rolls": [roll_json(r) for r in rolls]}


def _swing(
    attacker: Combatant, target: Combatant, dice: Dice, combat_round: int, condition: str, notes: list[str]
) -> tuple[dict[str, Any], int, Combatant, list[Roll]]:
    """One attack roll and its damage, against the target as it stands; nothing is applied. Returns the result, the
    damage (0 on a miss), the attacker after it and the rolls."""
    block = _block(attacker)
    thac0 = _thac0(attacker)
    n = attacker.attacks_used + 1
    cond = condition.lower().strip()
    conditions = attacker.conditions
    key = {"actor": attacker.id, "target": target.id, "combat_round": combat_round}
    roll = dice.d(20, purpose=f"attack#{n}", **key)
    rolls = [roll]
    face = roll.total
    hit_bonus = _sum_modifier(attacker, "to_hit")
    target_effect_ac = _sum_modifier(target, "ac")
    if hit_bonus:
        notes.append(f"{hit_bonus:+d} to hit (active effects on {attacker.name}).")
    if target_effect_ac:
        notes.append(f"{target_effect_ac:+d} AC modifier on {target.name} (active effects).")
    if cond == "rear":
        hit_bonus += 2
        notes.append("+2 to hit (rear attack).")
    elif cond == "fleeing":
        # A fleeing target turns its back: the rear-attack bonus, with a real roll.
        hit_bonus += 2
        notes.append("+2 to hit (target fleeing: attack from the rear).")
    elif cond == "charging":
        hit_bonus += 2
        conditions = with_condition(conditions, "charging_ac_penalty", True)
        notes.append("+2 to hit (charging). Attacker has AC penalty this round.")

    if face == 20:
        hit = True
        notes.append("Natural 20 — an automatic hit.")
    elif face == 1:
        hit = False
        notes.append("Natural 1 — automatic miss!")
    else:
        target_ac = target.ac + target_effect_ac
        if target.ac_vs_larger and _size_rank(attacker.size) > _size_rank(target.size):
            target_ac -= target.ac_vs_larger
            notes.append(
                f"{target.name} gets {target.ac_vs_larger:+d} AC against the larger {attacker.name} "
                f"(size {_size_code(attacker.size)})."
            )
        hit = face + hit_bonus >= thac0 - target_ac

    damage, notation = 0, None
    if hit:
        damage_bonus = _sum_modifier(attacker, "dmg")
        large = _takes_large_damage(target.size)
        notation = (block.damage_l or block.damage_sm) if large else block.damage_sm
        if large and notation != block.damage_sm:
            notes.append(
                f"{target.name} is size {_size_code(target.size)} — rolling the Large damage die ({notation})."
            )
        rolled, damage_roll = _roll_damage(dice, notation, purpose=f"damage#{n}", **key)
        if damage_roll is not None:
            rolls.append(damage_roll)
        raw = rolled + damage_bonus
        if damage_bonus:
            notes.append(f"{damage_bonus:+d} damage (active effects).")
        if cond == "set_vs_charge":
            raw *= 2
            notes.append("Set vs. charge — double damage!")
        damage = max(0, raw)

    after = replace(attacker, attacks_used=n, conditions=conditions)
    allowed = _attacks_allowed_in_round(block.rate, combat_round)
    result = {
        "attacker": attacker.name,
        "attacker_id": attacker.id,
        "target": target.name,
        "target_id": target.id,
        "weapon": block.name or None,
        "roll": face,
        "hit": hit,
        "damage": damage if hit else None,
        "damage_die": notation,
        "hp_after": None,
        "downed": False,
        "dead": False,
        "spell_disrupted": False,
        "attacks_per_round": block.rate,
        "attacks_remaining_this_round": max(0, allowed - n),
        "notes": notes,
    }
    if n > allowed:
        result["extra_attack"] = True
    return result, damage, after, rolls


def _broke(c: Combatant, ongoing: Ongoing, reason: str) -> dict[str, Any]:
    return {"type": "interrupted", "id": c.id, "what": ongoing.what, "kind": ongoing.kind, "reason": reason}


def _break(combat: Combat, id: str, reason: str) -> Combat:
    """The combatant's ongoing action breaks, for `reason`; it stays on the combatant, marked, until the round ends."""
    c = combat.combatants[id]
    o = c.ongoing
    if o is None or not o.under_way:
        return combat
    broken = replace(c, ongoing=replace(o, state="interrupted", reason=reason))
    broken = replace(broken, conditions=with_condition(broken.conditions, "casting", False))
    return _logged(_put(combat, broken), _broke(c, o, reason))


def _spoilt_by_harm(c: Combatant) -> bool:
    """A hit or a failed saving throw before the spell is cast spoils it."""
    o = c.ongoing
    return o is not None and o.under_way and o.kind in timing.SPOILT_BY_HARM


def _hurt(combat: Combat, id: str, amount: int) -> tuple[Combat, dict[str, Any]]:
    """Take hit points off a combatant, to no less than -10; damage spoils a spell (or scroll) under way, in this
    round or one it carries over from."""
    c = combat.combatants[id]
    disrupted = amount > 0 and _spoilt_by_harm(c)
    if disrupted:
        combat = _break(combat, id, f"{c.name} was hit")
        c = combat.combatants[id]
    hp = max(DEAD_AT, c.hp - amount)
    hurt = replace(c, hp=hp, conditions=with_condition(c.conditions, "downed", hp <= 0))
    info = {"hp_before": c.hp, "hp_after": hp, "downed": hp <= 0, "dead": _is_dead(hurt), "spell_disrupted": disrupted}
    return _put(combat, hurt), info


def _land(combat: Combat, swing: dict[str, Any], damage: int) -> Combat:
    """Apply a hit's damage and put what it did into its result."""
    combat, hurt = _hurt(combat, swing["target_id"], damage)
    name = swing["target"]
    swing.update(
        hp_after=hurt["hp_after"], downed=hurt["downed"], dead=hurt["dead"], spell_disrupted=hurt["spell_disrupted"]
    )
    notes = swing["notes"]
    if hurt["spell_disrupted"]:
        notes.append(f"{name} was casting — spell disrupted!")
    if hurt["dead"]:
        notes.append(f"{name} is dead!")
    elif hurt["downed"]:
        notes.append(f"{name} is unconscious!")
        if hurt["hp_after"] < 0:
            notes.append("Bleeding: loses 1 HP/round until stabilised or dead at -10.")
    return combat


def _morale_due(combat: Combat, side: str) -> tuple[Combat, dict[str, Any] | None]:
    """A one-shot morale-due notice when `side` first has half its number down (a group checks when it has lost
    half its number). The DM rolls it with morale_check."""
    if side == "party":
        return combat, None
    members = [c for c in combat.combatants.values() if c.side == side]
    down = sum(1 for c in members if c.hp <= 0)
    if not members or down * 2 < len(members):
        return combat, None
    if any(e.get("type") == "morale_due" and e.get("side") == side for e in combat.log):
        return combat, None
    notice = {
        "side": side,
        "down": down,
        "total": len(members),
        "ratings": {c.group or c.name: c.morale for c in members if c.morale is not None},
        "message": f"Morale check due: {down}/{len(members)} of side '{side}' down. "
        f"Call morale_check(rating) using the group's morale rating "
        f"(monster_lookup → 'morale').",
    }
    return _logged(combat, {"type": "morale_due", "side": side}), notice


def attack(
    combat: Combat, dice: Dice, attacker_id: str, target_id: str, *, condition: str = "", weapon: str = ""
) -> tuple[Combat, dict[str, Any]]:
    """One attack in the current round, applied at once. Natural 20 always hits; natural 1 always misses.

    condition: 'rear' (+2 to hit), 'fleeing' (the target turned its back: +2), 'charging' (+2 to hit,
    AC penalty), 'set_vs_charge' (double damage on a hit). weapon picks one of the attacker's attacks by name and
    sticks. The Large damage die is rolled against targets of size L or bigger. It counts against the
    attacker's attacks this round; one beyond them is flagged `extra_attack`.

    Refused before the round's initiative, and for an attacker that is down or dead."""
    _in_round(combat)
    atk, tgt = find(combat, attacker_id), find(combat, target_id)
    for c in (atk, tgt):
        if _removed(c):
            raise CombatError(f"{c.name} has been removed from the fight.")
    if _is_dead(atk):
        raise CombatError(f"{atk.name} is dead and can't attack.")
    if atk.hp <= 0:
        raise CombatError(f"{atk.name} is down and can't attack.")
    notes: list[str] = []
    if weapon:
        index, note = _select_attack(atk, weapon)
        if index is not None:
            atk = replace(atk, weapon=index)
            block = _block(atk)
            notes.append(
                f"{atk.name} attacks with {block.name} (THAC0 {_thac0(atk)}, {block.damage_sm}/{block.damage_l})."
            )
        elif note:
            notes.append(note)
    swing, damage, atk, rolls = _swing(atk, tgt, dice, combat.round, condition, notes)
    combat = _put(combat, atk)
    if swing["hit"]:
        combat = _land(combat, swing, damage)
    remaining = swing["attacks_remaining_this_round"]
    if remaining:
        notes.append(f"{atk.name} has {remaining} more attack(s) this round ({_rate_text(_block(atk).rate)}/round).")
    if swing["downed"]:
        combat, notice = _morale_due(combat, tgt.side)
        if notice:
            swing["morale_due"] = notice
    swing["rolls"] = [roll_json(r) for r in rolls]
    entry = {"type": "attack", "attacker": atk.id, "target": tgt.id, "hit": swing["hit"], "damage": swing["damage"]}
    return _logged(combat, entry), swing


MISSILES: dict[str, tuple[str, str, str]] = {
    # name: (its damage on a direct hit, what it does after, its splash on a miss)
    "oil": ("2d6", "It burns on for 1d6 more next round.", "Those within 3 feet of where it lands take 1d3."),
    "holy water": ("2d4", "", "Undead within 3 feet of where it lands take 2."),
}
"""The grenade-like missiles a character throws: a flask of burning oil, a vial of holy water."""
_UNDEAD = re.compile(
    r"\b(?:zombie|skeleton|ghoul|ghast|wight|wraith|spectre|specter|mummy|vampire|ghost|lich|shadow|banshee|"
    r"revenant|haunt|poltergeist|crypt thing|undead|dracolich|death knight|juju)\b",
    re.IGNORECASE,
)


def throw(
    combat: Combat,
    dice: Dice,
    thrower_id: str,
    target_id: str,
    missile: str,
    reference: RulesetReference | None = None,
) -> tuple[Combat, dict[str, Any]]:
    """A grenade-like missile thrown at a combatant in the current round (DEL-333): an attack roll with the thrower's
    THAC0 and its effects, as `attack`'s, and on a hit the missile's damage, `MISSILES`: burning oil 2d6, holy water
    2d4 to undead (from the name, or "undead" in its monster entry; nothing to the living). A miss splashes nearby,
    which the notes say for the DM to rule. It counts as one of the thrower's attacks this round."""
    combat, swing, rolls = _throw(combat, dice, thrower_id, target_id, missile, reference)
    swing["rolls"] = [roll_json(r) for r in rolls]
    return combat, swing


def _throw(
    combat: Combat,
    dice: Dice,
    thrower_id: str,
    target_id: str,
    missile: str,
    reference: RulesetReference | None = None,
) -> tuple[Combat, dict[str, Any], list[Roll]]:
    kind = missile.strip().lower().removeprefix("flask of ").removeprefix("vial of ")
    if kind not in MISSILES:
        raise CombatError(f"Unknown missile '{missile}'.", hint=f"Throw one of: {', '.join(MISSILES)}.")
    _in_round(combat)
    atk, tgt = find(combat, thrower_id), find(combat, target_id)
    for c in (atk, tgt):
        if _removed(c):
            raise CombatError(f"{c.name} has been removed from the fight.")
    if atk.hp <= 0:
        raise CombatError(f"{atk.name} is {'dead' if _is_dead(atk) else 'down'} and can't throw.")
    dmg, after, splash = MISSILES[kind]
    notes: list[str] = []
    if kind == "holy water" and not _undead(tgt, reference):
        dmg = "0"
        notes.append(f"Holy water harms only the undead (and fiends): {tgt.name} is unhurt even if it hits.")
    held = AttackBlock(f"flask of {kind}" if kind == "oil" else f"vial of {kind}", dmg, dmg)
    swing, damage, thrown, rolls = _swing(
        replace(atk, attacks=(*atk.attacks, held), weapon=len(atk.attacks)), tgt, dice, combat.round, "", notes
    )
    combat = _put(combat, replace(thrown, attacks=atk.attacks, weapon=atk.weapon))
    if swing["hit"] and damage:
        combat = _land(combat, swing, damage)
        if after:
            notes.append(after)
    elif not swing["hit"]:
        notes.append(f"It misses {tgt.name} and shatters nearby. {splash}")
    if swing["downed"]:
        combat, notice = _morale_due(combat, tgt.side)
        if notice:
            swing["morale_due"] = notice
    swing.update(missile=kind, notes=notes)
    entry = {"type": "throw", "attacker": atk.id, "target": tgt.id, "missile": kind, "hit": swing["hit"]}
    return _logged(combat, {**entry, "damage": swing["damage"]}), swing, rolls


def _undead(c: Combatant, reference: RulesetReference | None) -> bool:
    if _UNDEAD.search(f"{c.name} {c.group}"):
        return True
    rows = reference.monster(c.group or c.name) if reference is not None else []
    return bool(rows) and "undead" in str(rows[0].get("description") or "").lower()


def _skip(actor: Combatant, reason: str, key: str = "attacker") -> dict[str, Any]:
    return {key: actor.name, f"{key}_id": actor.id, "skipped": reason}


def _cannot_act(combat: Combat, actor: Combatant, key: str) -> dict[str, Any] | None:
    if _removed(actor):
        return _skip(actor, "removed from the fight", key)
    if _is_dead(actor):
        return _skip(actor, "dead — cannot act", key)
    if actor.hp <= 0:
        return _skip(actor, "down — cannot act", key)
    if combat.round == 1 and "surprised" in actor.conditions:
        return _skip(actor, "surprised — loses the first round", key)
    return None


def _foes(combat: Combat, actor: Combatant) -> list[str]:
    return [c.name for c in combat.combatants.values() if c.side != actor.side and _standing(c)]


def _attack_action(
    combat: Combat, snapshot: Combat, dice: Dice, actor_id: str, action: Mapping[str, Any]
) -> tuple[Combat, list[dict[str, Any]], list[tuple[dict[str, Any], int]], list[Roll]]:
    """An attacker's whole action: every swing it is owed this round, at the first target in [target, *targets] still
    up when its group began (less what its own earlier swings did). Returns the swings and their pending damage."""
    actor = combat.combatants[actor_id]
    block = _block(actor)
    allowed = _attacks_allowed_in_round(block.rate, combat.round)
    if allowed == 0:
        return combat, [_skip(actor, f"no attack this round ({_rate_text(block.rate)} per round)")], [], []
    if actor.attacks_used >= allowed:
        return combat, [_skip(actor, "already made this round's attacks")], [], []
    pool = [action["target"], *action.get("targets", [])]
    own: dict[str, int] = {}

    def up(target_id: str, first: bool) -> bool:
        t = snapshot.combatants[target_id]
        hit = replace(t, hp=t.hp - own.get(target_id, 0))
        if _removed(hit) or _is_dead(hit):
            return False
        return first or hit.hp > 0

    target = action["target"] if up(action["target"], True) else next((t for t in pool[1:] if up(t, False)), None)
    if target is None:
        dead = snapshot.combatants[action["target"]]
        skipped = {**_skip(actor, "target already dead — attack not rolled"), "target": dead.name}
        return combat, [{**skipped, "target_id": dead.id, "living_foes": _foes(snapshot, actor)}], [], []
    swings, pending, rolls = [], [], []
    for k in range(allowed - actor.attacks_used):
        if k:
            target = next((t for t in pool if up(t, False)), None)
            if target is None:
                break
        swing, damage, attacker, swing_rolls = _swing(
            combat.combatants[actor_id],
            snapshot.combatants[target],
            dice,
            combat.round,
            action.get("condition", ""),
            [],
        )
        combat = _put(combat, attacker)
        rolls.extend(swing_rolls)
        if k:
            swing["follow_up"] = True
        swings.append(swing)
        if swing["hit"]:
            own[target] = own.get(target, 0) + damage
            pending.append((swing, damage))
    return combat, swings, pending, rolls


def _ongoing_action(combat: Combat, actor_id: str, action: Mapping[str, Any]) -> tuple[Combat, dict[str, Any]]:
    """A combatant's ongoing action at its count: lost when it broke, going on when it carries over, else done.
    Done marks it `completed` before the group's damage lands: on a tie the spell goes off (a wizard may fall to
    goblins that collapse from the sleep spell at the same moment)."""
    c = combat.combatants[actor_id]
    o = c.ongoing
    assert o is not None
    if o.kind in timing.SPOILT_BY_HARM:
        out: dict[str, Any] = {"caster": c.name, "caster_id": c.id, "spell": o.what}
        if o.kind == "scroll":
            out["scroll"] = action.get("item") or o.what
        done_key = "cast"
    elif o.kind == "other":
        out, done_key = {"actor": c.name, "actor_id": c.id, "action": o.what}, "done"
    else:
        out, done_key = {"actor": c.name, "actor_id": c.id, "item": o.what, "kind": action.get("kind", o.kind)}, "used"
    if action.get("target"):
        target = combat.combatants[action["target"]]
        out.update(target=target.name, target_id=target.id)
    if not o.under_way:
        out[done_key] = False
        if o.reason == f"{c.name} was hit":
            out["note"] = (
                f"{c.name} was hit before the {'spell went off' if done_key == 'cast' else 'action was done'}: it is lost."
            )
        else:
            out["note"] = f"{o.reason}: it is lost."
        return combat, out
    if o.completes_round > combat.round:
        out.update(continues=True, completes_round=o.completes_round)
        out["note"] = f"{c.name} keeps at it: it takes effect at the end of round {o.completes_round}."
        return combat, out
    out[done_key] = True
    done = replace(c, ongoing=replace(o, state="completed"), conditions=with_condition(c.conditions, "casting", False))
    entry = {"type": "completed", "id": c.id, "what": o.what, "kind": o.kind}
    return _logged(_put(combat, done), entry), out


# The conditions the DM gives a dying character whose wounds someone bound: it bleeds no more.
TENDED = frozenset({"stabilized", "stabilised", "stable", "bandaged"})


def _tended(c: Combatant) -> bool:
    return any(condition.strip().lower() in TENDED for condition in c.conditions)


def _end_round(combat: Combat) -> tuple[Combat, list[str]]:
    """The round ends: the dying of the party and its allies bleed 1 HP unless their wounds
    were bound (`TENDED`), effects tick down, surprise ends, the ongoing actions that completed or broke are put
    away (one that carries over stays), and the next round begins, waiting for its declarations and initiative."""
    lines: list[str] = []
    changed: dict[str, Combatant] = {}
    for c in combat.combatants.values():
        if c.side in ("party", "ally") and DEAD_AT < c.hp < 0 and not _removed(c) and not _tended(c):
            hp = max(DEAD_AT, c.hp - 1)
            lines.append(f"{c.name} bleeds 1 HP ({'dead' if hp <= DEAD_AT else f'hp now {hp}'})")
            changed[c.id] = replace(c, hp=hp)
    for c in combat.combatants.values():
        c = changed.get(c.id, c)
        surviving = []
        for effect in c.effects:
            if effect.duration == 0:
                surviving.append(effect)  # until it is removed: an item's
            elif effect.duration <= 1:
                lines.append(f"{c.name}: '{effect.name}' expires.")
            else:
                surviving.append(replace(effect, duration=effect.duration - 1))
        conditions = with_condition(c.conditions, "surprised", False) if combat.round == 1 else c.conditions
        o = c.ongoing
        if o is not None and (not o.under_way or o.completes_round <= combat.round):
            c = replace(c, ongoing=None)
            conditions = with_condition(conditions, "casting", False)
        changed[c.id] = replace(c, effects=tuple(surviving), attacks_used=0, conditions=conditions)
    combat = replace(combat, combatants={**combat.combatants, **changed}, surprise={"party": False, "enemies": False})
    combat = _logged(combat, {"type": "round_end"})
    return replace(combat, round=combat.round + 1, order=(), current=0, declared={}), lines


def slots(combat: Combat) -> list[dict[str, Any]]:
    """The round's order as the table's timeline reads it (B2 redacts it): each combatant with an initiative, in
    order, at its count and in its group (its side's in `side` mode, else its own id), with what it is busy with.
    An ongoing action shows as under way: how it ended is the round's `outcomes`, released after the narration.
    Then the downed and the dead of the fight, with no count."""
    out = []
    for id in combat.order:
        c = combat.combatants[id]
        out.append(_slot(combat, c, c.init))
    for c in combat.combatants.values():
        if c.id not in combat.order and not _removed(c) and c.hp <= 0:
            out.append(_slot(combat, c, None))
    return out


def _slot(combat: Combat, c: Combatant, count: int | None) -> dict[str, Any]:
    o = c.ongoing
    shown = ongoing_json(replace(o, state="ongoing", reason=None)) if o is not None else None
    return {
        "id": c.id,
        "name": c.name,
        "side": c.side,
        "character_id": c.character_id,
        "node": c.node,
        "count": count,
        "group": timing.side_of(c.side) if combat.mode == "side" else c.id,
        "ongoing": shown,
    }


def _outcomes(before: Combat, after: Combat, acted: Iterable[str], number: int) -> dict[str, Any]:
    """Who acted; who went down, died or fled in the round; which ongoing actions completed or broke in it."""
    downed, dead, fled = [], [], []
    for id, c in after.combatants.items():
        was = before.combatants.get(id)
        if _is_dead(c) and (was is None or not _is_dead(was)):
            dead.append(id)
        elif c.hp <= 0 and (was is None or was.hp > 0):
            downed.append(id)
        gone = "fleeing" in c.conditions or _removed(c)
        if gone and (was is None or not ("fleeing" in was.conditions or _removed(was))):
            fled.append(id)
    this_round = [e for e in after.log if e.get("round") == number]
    return {
        "acted": list(dict.fromkeys(acted)),
        "downed": downed,
        "dead": dead,
        "fled": fled,
        "completed": [{"id": e["id"], "what": e["what"]} for e in this_round if e.get("type") == "completed"],
        "interrupted": [
            {"id": e["id"], "what": e["what"], "reason": e["reason"]}
            for e in this_round
            if e.get("type") == "interrupted"
        ],
    }


def run_round(
    combat: Combat,
    dice: Dice,
    reference: RulesetReference,
    declarations: Sequence[Mapping[str, Any]] = (),
    mode: Mode = "combatant",
    rules: RuleTables | None = None,
) -> tuple[Combat, RoundResult]:
    """One whole round:

    1. the declarations (ttrpg2's shape: `{"attacker", "target", "targets"?, "weapon"?, "condition"?}`,
       `{"caster", "spell", "target"?}`, `{"actor", "item", "kind"}` or `{"actor", "action", "rounds"?}`), one per
       combatant; one still busy with an ongoing action from an earlier round keeps at it unless it declares another;
    2. initiative in `mode` (per combatant or per side; `delve.rules.classic.initiative`), unless the round's was rolled
       already (round 1, by setup, in the mode it was rolled with);
    3. the actions in initiative order. Combatants on the same total act simultaneously: each action is rolled
       against the state at the start of the group, and the group's damage is applied together. The order within a
       group is the listed order, and only orders the log;
    4. downed, dead, removed and (in round 1) surprised combatants are skipped, and an ongoing action of theirs is
       lost; so is an attack on a target already dead, unless one of its fallback targets still stands;
    5. an attacker makes every attack its rate allows this round; a fractional rate follows the round number;
    6. an ongoing action takes effect at its count, unless damage or a failed save broke it first; one of a round or
       more at the round's end, or a later round's;
    7. the end of the round: bleeding, effects ticking down, the next round.

    Morale notices come due when a side first has half its number down. The result has the round's `slots` (its
    order as it was set) and `outcomes`."""
    _live(combat)
    listed: list[str] = []
    for action in declarations:
        if not isinstance(action, Mapping):
            raise CombatError(f"An action is an object, not {action!r}.")
        ref = action.get("attacker") or action.get("caster") or action.get("actor")
        if not ref:
            raise CombatError("Every action names its attacker, caster or actor.")
        actor = find(combat, str(ref))
        if actor.id in listed:
            raise CombatError(
                f"{actor.name} has one action a round.", hint="Give fallback targets for further swings in targets."
            )
        combat, _ = declare(combat, actor.id, action, reference, rules)
        listed.append(actor.id)
    carried = {
        c.id: {"continuing": True}
        for c in combat.combatants.values()
        if c.ongoing is not None and c.ongoing.under_way and c.id not in combat.declared
    }
    combat = replace(combat, declared={**combat.declared, **carried})
    number = combat.round
    rolls: list[Roll] = []
    initiative = None
    if not combat.order:
        combat, initiative, init_rolls = _initiative(combat, dice, reference, mode, rules)
        rolls.extend(init_rolls)
    before = combat
    order_slots = tuple(slots(combat))

    results: list[dict[str, Any]] = []
    morale: list[dict[str, Any]] = []
    acted: list[str] = []
    for _, group in itertools.groupby(combat.order, key=lambda id: combat.combatants[id].init):
        ids = list(group)
        acting = [i for i in listed if i in ids] + [i for i in ids if i in combat.declared and i not in listed]
        snapshot = combat
        pending: list[tuple[dict[str, Any], int]] = []
        for actor_id in acting:
            action = combat.declared[actor_id]
            busy = combat.combatants[actor_id].ongoing is not None
            key = "caster" if "spell" in action else "actor" if busy or "action" in action else "attacker"
            skipped = _cannot_act(snapshot, snapshot.combatants[actor_id], key)
            if skipped:
                results.append(skipped)
                if busy:
                    combat = _break(combat, actor_id, f"{snapshot.combatants[actor_id].name}: {skipped['skipped']}")
            elif busy:
                combat, out = _ongoing_action(combat, actor_id, action)
                results.append(out)
                if out.get("cast") or out.get("used") or out.get("done"):
                    acted.append(actor_id)
            elif "action" in action:
                actor = snapshot.combatants[actor_id]
                results.append({"actor": actor.name, "actor_id": actor.id, "action": action["action"]})
                acted.append(actor_id)
            elif "missile" in action:
                combat, thrown, thrown_rolls = _throw(
                    combat, dice, actor_id, action["target"], action["missile"], reference
                )
                rolls.extend(thrown_rolls)
                results.append(thrown)
                acted.append(actor_id)
            else:
                combat, swings, hits, swing_rolls = _attack_action(combat, snapshot, dice, actor_id, action)
                results.extend(swings)
                pending.extend(hits)
                rolls.extend(swing_rolls)
                if any("skipped" not in s for s in swings):
                    acted.append(actor_id)
        sides = []
        for swing, damage in pending:
            combat = _land(combat, swing, damage)
            if swing["downed"]:
                sides.append(combat.combatants[swing["target_id"]].side)
        for side in dict.fromkeys(sides):
            combat, notice = _morale_due(combat, side)
            if notice:
                morale.append(notice)
        combat = replace(combat, current=combat.order.index(ids[0]))

    unused = {}
    living: dict[str, list[str]] = {}
    for actor_id in listed:
        actor = combat.combatants[actor_id]
        if "target" not in combat.declared.get(actor_id, {}) or not _can_act(actor):
            continue
        left = _attacks_allowed_in_round(_block(actor).rate, number) - actor.attacks_used
        if left > 0 and actor.attacks_used:
            unused[actor.name] = left
            living[actor.name] = _foes(combat, actor)
    # An ongoing action of this round that nobody reached (its actor never came up) is lost with the round.
    for c in list(combat.combatants.values()):
        if c.ongoing is not None and c.ongoing.under_way and c.ongoing.completes_round <= number:
            combat = _break(combat, c.id, f"{c.name} never got to it")
    entry = {"type": "round", "actions": len(results)}
    round_mode = combat.mode
    combat, lines = _end_round(_logged(combat, entry))
    outcomes = _outcomes(before, combat, acted, number)
    carrying = tuple(
        {"id": c.id, "name": c.name, **(ongoing_json(c.ongoing) or {})}
        for c in combat.combatants.values()
        if c.ongoing is not None
    )
    return combat, RoundResult(
        number,
        initiative,
        tuple(results),
        tuple(lines),
        tuple(morale),
        tuple(rolls),
        unused,
        living,
        mode=round_mode,
        slots=order_slots,
        outcomes=outcomes,
        ongoing=carrying,
    )


# --- changes during the fight ------------------------------------------------------------------------------------


def damage(combat: Combat, id: str, amount: int) -> tuple[Combat, dict[str, Any]]:
    """Damage from outside an attack (a spell, a trap, a fall): HP to no less than -10, and a spell being cast is
    spoilt."""
    _live(combat)
    c = find(combat, id)
    combat, hurt = _hurt(combat, c.id, _amount(amount))
    out = {"id": c.id, "name": c.name, **hurt}
    if hurt["downed"]:
        combat, notice = _morale_due(combat, c.side)
        if notice:
            out["morale_due"] = notice
    return _logged(combat, {"type": "damage", "id": c.id, "amount": amount}), out


def heal(combat: Combat, id: str, amount: int) -> tuple[Combat, dict[str, Any]]:
    """Healing up to the maximum; above 0 the combatant comes to. The dead are not healed (only
    magic such as raise dead brings them back)."""
    _live(combat)
    c = find(combat, id)
    amount = _amount(amount)
    if _is_dead(c):
        raise CombatError(
            f"{c.name} is dead (HP {c.hp}); healing doesn't raise the dead.",
            hint="Use raise dead or resurrection (with resurrection_check), then set hp with update_character.",
        )
    hp = min(c.hp + amount, c.hp_max)
    notes = [f"{c.name} regains consciousness."] if c.hp <= 0 < hp else []
    healed = replace(c, hp=hp, conditions=with_condition(c.conditions, "downed", hp <= 0))
    combat = _logged(_put(combat, healed), {"type": "heal", "id": c.id, "amount": amount})
    return combat, {"id": c.id, "name": c.name, "healed": hp - c.hp, "hp_before": c.hp, "hp_after": hp, "notes": notes}


def add_condition(combat: Combat, id: str, condition: str) -> tuple[Combat, dict[str, Any]]:
    """A condition such as stunned or prone; nothing changes if it is there already."""
    _live(combat)
    c = find(combat, id)
    c = replace(c, conditions=with_condition(c.conditions, condition.strip(), True))
    return _put(combat, c), {"id": c.id, "name": c.name, "conditions": list(c.conditions)}


def remove_condition(combat: Combat, id: str, condition: str) -> tuple[Combat, dict[str, Any]]:
    _live(combat)
    c = find(combat, id)
    c = replace(c, conditions=with_condition(c.conditions, condition.strip(), False))
    return _put(combat, c), {"id": c.id, "name": c.name, "conditions": list(c.conditions)}


def apply_effect(combat: Combat, id: str, effect: Effect | Mapping[str, Any]) -> tuple[Combat, dict[str, Any]]:
    """A timed effect. Its `to_hit` adds to the bearer's attack rolls, `ac` to its armour class when attacked (negative
    is harder to hit), `dmg` to its damage and `save` to its saving throws. `duration` counts the current round: it
    lasts through round + duration - 1, ticking down at the end of each round; 0 lasts until it is removed (an
    item's). A `hidden` one is the DM's alone (DEL-335)."""
    _live(combat)
    c = find(combat, id)
    added = _effect(effect)
    c = replace(c, effects=(*c.effects, added))
    return _put(combat, c), {
        "target": c.name,
        "target_id": c.id,
        "effect": effect_json(added),
        "active_count": len(c.effects),
        "lasts_through_round": combat.round + added.duration - 1 if added.duration else None,
    }


def remove_effect(combat: Combat, id: str, name: str) -> tuple[Combat, dict[str, Any]]:
    """Remove the first effect called `name` (ignoring case) before it expires."""
    _live(combat)
    c = find(combat, id)
    index = next((i for i, e in enumerate(c.effects) if e.name.casefold() == name.strip().casefold()), None)
    if index is None:
        raise CombatError(f"No active effect named '{name}' on {c.name}.")
    removed = c.effects[index]
    c = replace(c, effects=c.effects[:index] + c.effects[index + 1 :])
    return _put(combat, c), {
        "target": c.name,
        "target_id": c.id,
        "removed": effect_json(removed),
        "remaining": len(c.effects),
    }


def adjudicate(combat: Combat, note: str, effects: Iterable[Mapping[str, Any]] = ()) -> tuple[Combat, dict[str, Any]]:
    """The DM's ruling on anything the rules here don't cover (a grapple, a called shot): logged, not refused. Each
    of `effects` is an effect with its `target`, applied as `apply_effect`."""
    _live(combat)
    if not str(note or "").strip():
        raise CombatError("A ruling needs a note saying what was decided.")
    applied = []
    for raw in effects:
        raw = dict(raw)
        target = raw.pop("target", None)
        if not target:
            raise CombatError("Each effect of a ruling names its target.")
        combat, out = apply_effect(combat, str(target), raw)
        applied.append({"target": out["target"], "target_id": out["target_id"], "effect": out["effect"]})
    out = {"note": note.strip(), "effects": applied}
    return _logged(combat, {"type": "ruling", **out}), out


def interrupt(combat: Combat, id: str, reason: str) -> tuple[Combat, dict[str, Any]]:
    """Break a combatant's ongoing action, for `reason` ("Mirela was hit"): the DM's ruling where the rules name no
    disruption (a potion knocked away, a long action stopped), or any other. It is lost, and the round's outcomes say
    so. Refused when the combatant has nothing under way."""
    _live(combat)
    c = find(combat, id)
    reason = str(reason or "").strip()
    if not reason:
        raise CombatError("Say why it is interrupted: 'Mirela was hit'.")
    o = c.ongoing
    if o is None or not o.under_way:
        raise CombatError(
            f"{c.name} has nothing under way to interrupt.",
            hint="combat_status shows each combatant's ongoing action; a spell, scroll, potion or long action is "
            "declared in combat_round (or setup_combat's spells).",
        )
    combat = _break(combat, c.id, reason)
    out = {
        "id": c.id,
        "name": c.name,
        "side": c.side,
        "kind": o.kind,
        "what": o.what,
        "reason": reason,
        "lost": f"{reason}; {o.what} is lost",
    }
    return combat, out


def remove(combat: Combat, id: str, reason: str = "") -> tuple[Combat, dict[str, Any]]:
    """Take a combatant out of the fight (it fled the map, was banished): it no longer acts or can be attacked, and a
    character still gets its state back at the end."""
    _live(combat)
    c = find(combat, id)
    combat = _put(combat, replace(c, conditions=with_condition(c.conditions, "removed", True)))
    out = {"id": c.id, "name": c.name, "reason": reason}
    return _logged(combat, {"type": "removed", **out}), out


COMBATANT_STATS = ("hp", "hp_max", "ac", "thac0", "dmg", "dmg_large", "morale")
"""What `update_combatant` sets."""


def update_combatant(combat: Combat, id: str, changes: Mapping[str, Any]) -> tuple[Combat, dict[str, Any]]:
    """Set a combatant's numbers to what the module or a ruling says (DEL-333): its hit points and their maximum, AC,
    THAC0, morale, and its current attack's damage (`dmg`, and `dmg_large` against Large, the same when not given), in
    place of an effect that only approximates them. A monster's, chiefly: a character's come from its sheet."""
    _live(combat)
    c = find(combat, id)
    unknown = sorted(set(changes) - set(COMBATANT_STATS))
    if unknown:
        raise CombatError(f"Can't set '{unknown[0]}'.", hint=f"Set any of {', '.join(COMBATANT_STATS)}.")
    numbers = {k: v for k, v in changes.items() if k not in ("dmg", "dmg_large")}
    for key, value in numbers.items():
        if isinstance(value, bool) or not isinstance(value, int):
            raise CombatError(f"{key} is a whole number, not {value!r}.")
    for key in ("dmg", "dmg_large"):
        if key in changes and not _rollable(str(changes[key])):
            raise CombatError(f"{key} is dice notation ('1d6+1'), not {changes[key]!r}.")
    updated = replace(c, **numbers)
    if "dmg" in changes or "dmg_large" in changes:
        if not updated.attacks:
            raise CombatError(f"{c.name} has no attack to set the damage of.")
        index = updated.weapon if 0 <= updated.weapon < len(updated.attacks) else 0
        block = updated.attacks[index]
        sm = str(changes.get("dmg", block.damage_sm))
        block = replace(block, damage_sm=sm, damage_l=str(changes.get("dmg_large", changes.get("dmg", block.damage_l))))
        updated = replace(updated, attacks=(*updated.attacks[:index], block, *updated.attacks[index + 1 :]))
    if updated.hp > updated.hp_max:
        updated = replace(updated, hp_max=updated.hp)
    combat = _put(combat, updated)
    out = {"id": c.id, "name": c.name, "set": dict(changes)}
    return _logged(combat, {"type": "updated", **out}), out


def saving_throw(
    combat: Combat,
    dice: Dice,
    reference: RulesetReference,
    id: str,
    save_type: str,
    *,
    modifier: int = 0,
    sheet: Sheet | None = None,
    rules: RuleTables,
) -> tuple[Combat, dict[str, Any]]:
    """A saving throw for any combatant (a monster by its Hit Dice, as the ruleset's tables say),
    with its effects' `save` modifiers. A character's base comes from its `sheet`. The roll is keyed by the combat
    round, so the same save twice in one round is the same roll."""
    _live(combat)
    c = find(combat, id)
    if sheet is not None:
        subject: Any = sheet
    elif c.character_id is not None:
        subject = {"kind": "pc"}
    else:
        subject = {"hit_dice": c.hit_dice, "name": c.group or c.name} if c.hit_dice else {"name": c.group or c.name}
    try:
        base = checks.save_base_for(subject, save_type, reference, rules=rules)
        result = checks.saving_throw(
            dice,
            save_type=save_type,
            base=base,
            modifier=modifier,
            effects=c.effects,
            actor=c.id,
            combat_round=combat.round,
            rules=rules,
        )
    except checks.CheckError as error:
        raise CombatError(str(error), error.hint) from None
    out = {
        "id": c.id,
        "name": c.name,
        "save_type": result.save_type,
        "save": result.name,
        "needed": result.needed,
        "roll": result.roll.total,
        "roll_id": result.roll.id,
        "success": result.success,
        "base": result.base,
        "modifier": result.modifier,
        "basis": result.basis,
        "round": combat.round,
    }
    entry = {"type": "save", "id": c.id, "save_type": result.save_type, "success": result.success}
    combat = _logged(combat, entry)
    if not result.success and _spoilt_by_harm(c):
        # A caster who fails a saving throw before the spell is cast loses it.
        combat = _break(combat, c.id, f"{c.name} failed a saving throw")
        out["spell_disrupted"] = True
    return combat, out


# --- status and the end ------------------------------------------------------------------------------------------


def status_of(c: Combatant) -> str:
    """active, unconscious, dead or removed."""
    if _removed(c):
        return "removed"
    if _is_dead(c):
        return "dead"
    return "unconscious" if c.hp <= 0 else "active"


def status(combat: Combat) -> dict[str, Any]:
    """The fight as it stands: the round, how its initiative was rolled (`mode`), and every combatant by initiative,
    with its hit points, armour class, conditions, effects, attack and ongoing action. Always answers, even with
    nobody in the fight."""
    added = {id: i for i, id in enumerate(combat.combatants)}
    entries = []
    for c in combat.combatants.values():
        block = _block(c)
        entry: dict[str, Any] = {
            "id": c.id,
            "name": c.name,
            "side": c.side,
            "hp": c.hp,
            "hp_max": c.hp_max,
            "ac": c.ac,
            "thac0": _thac0(c),
            "init": c.init,
            "size": c.size,
            "node": c.node,
            "conditions": list(c.conditions),
            # duration counts this round, so it runs through round + d - 1.
            "effects": [
                {**effect_json(e), "lasts_through_round": combat.round + e.duration - 1 if e.duration else None}
                for e in c.effects
            ],
            "status": status_of(c),
            "ongoing": ongoing_json(c.ongoing),
            "damage_sm": block.damage_sm,
            "damage_l": block.damage_l,
        }
        if block.name:
            entry["weapon"] = block.name
        if c.morale is not None:
            entry["morale"] = c.morale
        if block.rate != 1.0:
            entry["attacks_per_round"] = block.rate
            entry["attacks_remaining_this_round"] = max(
                0, _attacks_allowed_in_round(block.rate, combat.round) - c.attacks_used
            )
        entries.append(entry)
    entries.sort(key=lambda e: (e["init"] is None, e["init"] or 0, added[e["id"]]))
    current = combat.combatants[combat.order[combat.current]].name if combat.order else None
    return {
        "phase": combat.phase,
        "round": combat.round,
        "mode": combat.mode,
        "started": bool(combat.order),
        "current": current,
        "map": combat.map,
        "declared": dict(combat.declared),
        "combatants": entries,
    }


def end(combat: Combat) -> tuple[Combat, dict[str, Any]]:
    """The end of the fight. The outcome has, per character (by id), its hit points, its conditions (without the
    combat's own) and its effects, to write back; the fate of each enemy; and the defeated groups, for XP and
    treasure."""
    _live(combat)
    everyone = list(combat.combatants.values())
    rounds = combat.round if combat.order else combat.round - 1
    characters = {
        c.character_id: {
            "hp": c.hp,
            "conditions": [k for k in c.conditions if k not in COMBAT_ONLY],
            "effects": [effect_json(e) for e in c.effects],
        }
        for c in everyone
        if c.character_id is not None
    }
    enemies, defeated = _enemy_record(everyone)
    groups: dict[str, dict[str, Any]] = {}
    for c in everyone:
        if c.side != "enemy" or c.character_id is not None:
            continue
        group = groups.setdefault(
            c.group or _kind(c),
            {
                "group": c.group or _kind(c),
                "defeated": 0,
                "total": 0,
                "xp_value": c.xp_value,
                "treasure_type": c.treasure_type,
            },
        )
        group["total"] += 1
        beaten = _enemy_fate(c) in ("slain", "down")
        group["defeated"] += beaten
        earned = xp_of(c.xp_value, c.hp_max)
        if beaten and earned is not None:
            group["xp_earned"] = group.get("xp_earned", 0) + earned
    ended = _logged(replace(combat, phase="ended", declared={}), {"type": "end", "rounds": rounds})
    return ended, {
        "rounds": rounds,
        "characters": characters,
        "saved": {c.name: c.hp for c in everyone if c.character_id is not None},
        "enemies": enemies,
        "defeated": defeated,
        "groups": list(groups.values()),
    }
