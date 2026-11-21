"""The d20 engine: what a ruleset brings when its maths are not the classic engine's (DEL-387).

A ruleset that plays by d20 rules offers an object with this protocol as `Ruleset.d20`; `CampaignContext.d20` reads it
with `getattr`, so the classic rulesets, which have none, play as they always did. This module only names the protocol and
what it answers; it imports nothing from `delve.play`, `delve.web` or `delve.storage`.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from delve.dice import Roll
from delve.domain.characters import CharacterState, Sheet
from delve.domain.reference import RulesetReference
from delve.rules.classic.checks import CheckResult, SaveResult
from delve.rules.classic.combat import Combatant, HitDie
from delve.rules.classic.tables import FightRules

if TYPE_CHECKING:
    from delve.dice import Dice
    from delve.domain.campaigns import Character

__all__ = ["D20Engine", "HitDie", "Initiative", "Progress", "Swing"]


@dataclass(frozen=True)
class Swing:
    """One attack, as the engine resolved it."""

    hit: bool
    damage: int
    """0 on a miss."""
    roll: int
    """The d20 face."""
    notes: tuple[str, ...]
    rolls: tuple[Roll, ...]
    attacker: Combatant
    """The attacker after the attack (its d20 state, `attacks_used`)."""
    damage_die: str | None = None
    extra_attack: str | None = None
    """An extra attack the swing earns, by its feat's name: "cleave" or "great cleave" when it dropped its target and
    the attacker may cleave (3.5's Cleave, once a round; Great Cleave, without limit). None for none."""
    nonlethal: int = 0
    """The part of the hit that is nonlethal damage (a regenerating target's, but for what stops it), not in `damage`:
    core adds it to the target's `d20["nonlethal"]` (DEL-421). 0 on a miss."""


@dataclass(frozen=True)
class Initiative:
    roll: int | None
    """None for a combatant that rolls nothing."""
    total: int
    rolls: tuple[Roll, ...]


@dataclass(frozen=True)
class Progress:
    level: int
    """By the engine's one XP total."""
    xp: int
    xp_next: int | None
    ready: tuple[str, ...]
    """The classes that may take a level."""


class D20Engine(Protocol):
    def fill_derived(self, sheet: Sheet, reference: RulesetReference) -> Sheet: ...

    def level_up(self, sheet: Sheet, cls: str, reference: RulesetReference, dice: Dice) -> Sheet: ...

    def award_xp(self, sheet: Sheet, state: CharacterState, amount: int) -> CharacterState: ...

    def progress(self, sheet: Sheet, state: CharacterState, reference: RulesetReference) -> Progress: ...

    def drain(
        self, sheet: Sheet, state: CharacterState, levels: int, reference: RulesetReference, dice: Dice
    ) -> tuple[Sheet, CharacterState, dict[str, Any]]: ...

    def rest(
        self, sheet: Sheet, state: CharacterState, days: int, *, bed_rest: bool = False
    ) -> tuple[CharacterState, dict[str, Any]]:
        """The state after `days` of rest (of complete bed rest with `bed_rest`) and a report; the report's `basis`, if
        it has one, is the rest's answer's basis (how the healing was worked out). The DM's `full` override is the
        core's, applied after."""
        ...

    def cast(
        self,
        sheet: Sheet,
        state: CharacterState,
        spell: str,
        level: int,
        dice: Dice | None = None,
        *,
        actor: str | None = None,
        unprepared: bool = False,
    ) -> tuple[CharacterState, dict[str, Any]]:
        """The state and a report; a refusal keeps the state and says `{"cast": False, "refusal": text}`. `unprepared`
        is True when core casts from the engine's per-day pool (no memorized copy was spent: a caster without slots, or
        `casts_unprepared`); a memorized copy's cast passes nothing. A spell that fails
        (arcane spell failure) says `{"cast": False, "lost": True}`: a memorized copy stays spent. `dice` is for the
        rolls a cast makes, and `actor` (the caster's character id) is their key's actor: two casters of one name roll
        their own dice (DEL-395)."""
        ...

    def can_memorize(self, sheet: Sheet, levels: Iterable[int], spells: Sequence[str] = ()) -> str | None:
        """A refusal, or None. `spells` are the names being memorized, for a rule that goes by name (domain slots)."""
        ...

    def casts_unprepared(self, sheet: Sheet, spell: str) -> bool:
        """Whether the engine casts `spell` for this caster from a per-day pool rather than from a memorized copy (a
        sorcerer's spell known, for a sorcerer/cleric whose cleric has spell slots): core then casts it as it casts for a
        caster without slots, the engine naming its level and spending from its pool. Asked only when no uncast copy
        is memorized."""
        ...

    def spell_level(self, sheet: Sheet, name: str) -> int | None:
        """The level of the spell `name` (as the reference spells it) for this caster, by its own lists; None when it is
        on none of them. Memorizing and a spell loadout take a named spell's level from here (ruling R16)."""
        ...

    def save(
        self,
        subject: Sheet | Combatant,
        save_type: str,
        dc: int | None,
        modifier: int,
        dice: Dice,
        *,
        actor: str,
        combat_round: int | None = None,
    ) -> SaveResult: ...

    def skill_check(
        self, sheet: Sheet, skill: str, dc: int | None, modifier: int, dice: Dice, *, actor: str, occasion: str
    ) -> CheckResult: ...

    def ability_check(
        self, sheet: Sheet, ability: str, dc: int | None, modifier: int, dice: Dice, *, actor: str, occasion: str
    ) -> CheckResult: ...

    def turn_undead(
        self,
        sheet: Sheet | None,
        level: int,
        undead: str,
        hd: int,
        dice: Dice,
        *,
        actor: str | None,
        state: CharacterState | None = None,
    ) -> dict[str, Any]:
        """The turning's answer. A `state` key in it is a `CharacterState` core saves for the turner, and drops."""
        ...

    def combatant_from_sheet(self, character: Character, combatant: Combatant) -> Combatant: ...

    def combatant_from_monster(
        self, row: Mapping[str, Any], combatant: Combatant, overrides: Mapping[str, Any]
    ) -> Combatant: ...

    def read_hit_dice(self, line: str) -> tuple[HitDie, ...] | None:
        """A monster row's Hit Dice line as the parts its hit points are rolled from (DEL-402), or None when the
        engine can't read all of it: core then reads it as R18 does, and says when that read only part of it."""
        ...

    def load_multiplier(self, sheet: Sheet) -> float:
        """What the ruleset's encumbrance bands are multiplied by for this character (a Small one's ×3/4, DEL-399)."""
        ...

    def loaded_speed(self, sheet: Sheet, band: str, speed: int) -> int | None:
        """This character's movement under a load in `band` (core's encumbrance band) from its unloaded `speed`, when
        it isn't the ruleset's rule for everyone (a 3.5 dwarf's, unslowed by a medium or heavy load, DEL-404; one in
        3.5's medium or heavy armour, slowed by a load no more than by the armour, DEL-407); None for the ruleset's."""
        ...

    def swing(
        self, attacker: Combatant, target: Combatant, condition: str, dice: Dice, combat_round: int, fight: FightRules
    ) -> Swing: ...

    def initiative(self, combatant: Combatant, dice: Dice, combat_round: int) -> Initiative: ...

    def nonlethal_state(self, c: Combatant) -> str | None:
        """What the combatant's nonlethal damage (`d20["nonlethal"]`, absent for none) makes it: "staggered" (one
        action, as disabled is, with no strain), "unconscious" (it can't act and doesn't stand; a monster's fate is
        "down"), or None. Core asks it only with an engine (DEL-421)."""
        ...

    def xp_for_defeated(self, combatant: Combatant, party_levels: Sequence[int]) -> int | None: ...

    def sheet_numbers(self, sheet: Sheet) -> dict[str, Any]: ...

    def prompt_terms(self) -> Mapping[str, str]:
        """The DM prompt's wording for the engine's numbers: the keys `attack_number` (what stands for THAC0) and
        `saves_list` (what stands for the five saves)."""
        ...

    def tools(self) -> list[Any]:
        """The engine's own tools, as `delve.dm.tools.schema.ToolSpec`s; typed loosely because `delve.rules` may not
        import the DM's package."""
        ...
