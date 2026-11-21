"""A combatant's defences in a fight (DEL-389 part 3): damage reduction and what overcomes it, energy resistance and
immunity, regeneration and fast healing, and spell resistance. They are in `Combatant.d20` as the monster row has
them (`dr`, `sr`, `sr_plus_class_levels`, `regeneration`, `fast_healing`, `resist`, `immune`); a character's DR is
its derived "2/—" in the same list shape (`numbers.reduction`).

What an attack form has against DR (`overcomes`), by the SRD's Damage Reduction (Types, Subtypes, and Special
Abilities):
- `magic` with an enhancement bonus of +1 or more (`form["enhancement"]`, or a monster's "+2 bastard sword" by its
  name), and `epic` with +6 or more; a monk's ki strike (`form["bypasses"]`);
- its materials (`form["materials"]`: silver, cold iron, adamantine) and alignments (`form["aligned"]`) — "not made
  of the correct material have their damage reduced, even if the weapon has an enhancement bonus";
- its damage type: a weapon's from `weapons.json`, a natural weapon's by its kind (`NATURAL_TYPES`);
- a monster's natural weapons are magic where its own DR is x/magic, magic and epic where it is x/epic ("Such
  creatures' natural weapons ... are treated as magic weapons"), and every attack of a creature with an alignment
  subtype has that alignment ("as if the weapons or natural weapons had an alignment ... that match the subtype(s)").
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from delve_srd35.engine import attack_line, class_features, numbers

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from delve.rules.classic.combat import Combatant

KEYS = ("dr", "sr", "sr_plus_class_levels", "regeneration", "fast_healing", "resist", "immune")
"""The defence keys a monster row has, and a combatant's `d20` carries from it."""
NATURAL_TYPES = {
    "bite": ("bludgeoning", "piercing", "slashing"),
    "claw": ("piercing", "slashing"),
    "talon": ("piercing", "slashing"),
    "gore": ("piercing",),
    "slap": ("bludgeoning",),
    "slam": ("bludgeoning",),
    "sting": ("piercing",),
    "tentacle": ("bludgeoning",),
}
"""The SRD's damage types of natural weapons (Natural Weapons): a bite is all three, a claw or talon piercing and
slashing, a gore and a sting piercing, a slap, slam and tentacle bludgeoning."""
TYPES = ("bludgeoning", "piercing", "slashing")
ALIGNMENTS = ("good", "evil", "lawful", "chaotic")
ENERGY = ("acid", "cold", "electricity", "fire", "sonic")
_ENERGY_DICE = re.compile(r"(\d+d\d+(?:[+-]\d+)?)\s+(" + "|".join(ENERGY) + r")\b", re.IGNORECASE)
_JOINED_ENERGY = re.compile(r"(?:\s*(?:,|\band\b|\bplus\b)\s*)?" + _ENERGY_DICE.pattern, re.IGNORECASE)
"""An energy's dice with the joiner before it (", ", " and ", " plus "), taken out of a `plus` together."""
_OR_ENERGY = re.compile(r"\s+or\s+" + _ENERGY_DICE.pattern, re.IGNORECASE)
_OFFERED = re.compile(_ENERGY_DICE.pattern + r"(?:\s+or\s+" + _ENERGY_DICE.pattern + ")+", re.IGNORECASE)
"""An energy offered instead of the one before it ("3d6 sonic or 3d6 electricity"): one is dealt, not both."""
_JOINERS = re.compile(r"^(?:\s*(?:,|\band\b|\bplus\b)\s*)+|(?:\s*(?:,|\band\b|\bplus\b)\s*)+$", re.IGNORECASE)
_ENHANCED = re.compile(r"^\+(\d+)\s")
NONE = "—"


def of_row(row: Mapping[str, Any]) -> dict[str, Any]:
    """The row's defences, the keys it has (`KEYS`)."""
    return {key: row[key] for key in KEYS if row.get(key) not in (None, [], {}, False, 0)}


def of_combatant(target: Combatant) -> dict[str, Any]:
    """The target's defences: its `d20`'s, and for a monster stored before its row had them (its `d20` without any
    defence key) its row's (`class_features.monster_row` by its `monster` id)."""
    mine = dict(target.d20 or {})
    if mine.get("monster") and not any(key in mine for key in KEYS):
        row = class_features.monster_row(target)
        if row is not None:
            mine.update(of_row(row))
    return mine


def _words(entry: Mapping[str, Any]) -> list[str]:
    return list(entry.get("bypass") or entry.get("bypass_any") or [NONE])


def said(entry: Mapping[str, Any]) -> str:
    """A DR as the SRD writes it: "10/magic", "15/good and silver", "10/cold iron or good", "5/—"."""
    joiner = " or " if entry.get("bypass_any") else " and "
    return f"{entry['value']}/{joiner.join(_words(entry))}"


def _types(form: Mapping[str, Any]) -> set[str]:
    """The form's damage types: its weapon's (`weapons.json`'s "Piercing or slashing" is either), else by the
    natural weapon's kind; none for a kind the SRD's list hasn't (a wing, a hoof)."""
    weapon = attack_line.weapon(str(form.get("name") or ""))
    if weapon is not None:
        return {t for t in TYPES if t in str(weapon.get("type") or "").lower()}
    words = [attack_line.singular(w) for w in re.findall(r"[a-z]+", str(form.get("name") or "").lower())]
    return {t for w in words for t in NATURAL_TYPES.get(w, ())}


def natural(form: Mapping[str, Any]) -> bool:
    """A natural weapon: a form that is no weapon of the SRD's table, and no touch."""
    return attack_line.weapon(str(form.get("name") or "")) is None and not form.get("touch")


def enhancement(form: Mapping[str, Any]) -> int:
    """The form's enhancement bonus: its `enhancement`, else a "+2 bastard sword"'s by its name."""
    if form.get("enhancement"):
        return int(form["enhancement"])
    found = _ENHANCED.match(str(form.get("name") or ""))
    return int(found.group(1)) if found else 0


def overcomes(attacker: Combatant, form: Mapping[str, Any]) -> set[str]:
    """The words of DR the attacker's form has (the module's list)."""
    has = {str(w).lower() for key in ("bypasses", "materials", "aligned") for w in form.get(key) or ()}
    plus = enhancement(form)
    if plus >= 1:
        has.add("magic")
    if plus >= 6:
        has.add("epic")
    has |= _types(form)
    mine = attacker.d20 or {}
    if mine.get("monster"):
        if natural(form):
            own = {w for entry in numbers.reduction(mine.get("dr")) for w in _words(entry)}
            if "epic" in own:
                has |= {"epic", "magic"}
            elif "magic" in own:
                has.add("magic")
        row = class_features.monster_row(attacker) or {}
        has |= {str(s).lower() for s in row.get("subtypes") or ()} & set(ALIGNMENTS)
    return has


def _bypassed(entry: Mapping[str, Any], has: set[str]) -> bool:
    if entry.get("bypass_any"):
        return any(w in has for w in entry["bypass_any"])
    words = _words(entry)
    return NONE not in words and all(w in has for w in words)


def reduce(damage: int, attacker: Combatant, form: Mapping[str, Any], target: Combatant) -> tuple[int, list[str]]:
    """The damage less the target's damage reduction, to no less than 0, and the notes: of several, the highest the
    form doesn't overcome counts (they don't stack); one it overcomes is named with what overcame it."""
    entries = numbers.reduction(of_combatant(target).get("dr"))
    if not entries or damage <= 0:
        return damage, []
    has = overcomes(attacker, form)
    standing = [e for e in entries if not _bypassed(e, has)]
    if not standing:
        best = max(entries, key=lambda e: int(e["value"]))
        words = [w for w in _words(best) if w in has]
        return damage, [f"DR {said(best)} overcome ({' and '.join(words) if not best.get('bypass_any') else words[0]})"]
    best = max(standing, key=lambda e: int(e["value"]))
    soaked = min(int(best["value"]), damage)
    notes = [f"DR {said(best)} (-{soaked})"]
    if not _types(form) and set(_words(best)) & set(TYPES):
        notes.append(f"{form.get('name')}: its damage type isn't known: rule whether it overcomes DR {said(best)}")
    return damage - soaked, notes


def energy(form: Mapping[str, Any]) -> tuple[list[tuple[str, str]], str]:
    """The energy dice added to the form's damage ("plus 2d6 fire" is [("2d6", "fire")], "plus 1d6 fire and 1d6 cold"
    both, "plus 3d6 sonic or 3d6 electricity" the first, the other named in the rest for the DM) and the rest of its
    `plus` (for the DM: "poison"), without the joiners the energies took."""
    text = str(form.get("plus") or "")
    offered = [m.group(0).strip() for m in _OFFERED.finditer(text)]
    text = _OR_ENERGY.sub("", text)
    found = [(dice, kind.lower()) for dice, kind in _ENERGY_DICE.findall(text)]
    rest = _JOINERS.sub("", _JOINED_ENERGY.sub("", text)).strip()
    for words in offered:  # "3d6 sonic or 3d6 electricity" (the marut): one of them, the first rolled
        dice, kind = _ENERGY_DICE.findall(words)[0]
        said = f"{words.lower()}: the DM's choice, {dice} {kind.lower()} rolled"
        rest = f"{rest}; {said}" if rest else said
    return found, rest


def resisted(kind: str, amount: int, target: Combatant) -> tuple[int, str]:
    """The energy damage the target takes of `amount` of `kind`, and how: none if immune, less its resistance."""
    theirs = of_combatant(target)
    if kind in {str(i).lower() for i in theirs.get("immune") or ()}:
        return 0, f"immune to {kind}"
    resist = int(dict(theirs.get("resist") or {}).get(kind, 0))
    if resist:
        return max(0, amount - resist), f"{amount}, resistance to {kind} {resist} (-{min(resist, amount)})"
    return amount, str(amount)


IN_THE_DAMAGE = ", in the damage"
"""What a rider's note ends with when it dealt something: its damage is already in the hit's `damage`."""


def rider_said(head: str, amount: int, taken: int, how: str) -> str:
    """An energy rider's note, "plus 1d6 fire: 2, in the damage": `how` says what it dealt (`resisted`), and a rider
    that dealt nothing (immune, or all of it resisted) says no more than that."""
    return f"{head}: {how}{IN_THE_DAMAGE if taken else ''}"


_RIDER = re.compile(r"^plus \S+ (\w+)(?: \(critical\))?: (\d+)(?:, resistance to \w+ \d+ \(-(\d+)\))?" + IN_THE_DAMAGE + "$")


def of_which(notes: Sequence[str]) -> dict[str, int]:
    """The riders' damage in a hit's total by energy, from its notes (`rider_said`): {"fire": 2}."""
    out: dict[str, int] = {}
    for note in notes:
        if (found := _RIDER.match(note)) is not None:
            kind, amount, resisted = found.group(1), int(found.group(2)), int(found.group(3) or 0)
            out[kind] = out.get(kind, 0) + amount - resisted
    return out


def _alternatives(regeneration: Mapping[str, Any]) -> list[list[str]]:
    return [list(alt) for alt in regeneration.get("bypass") or () if alt]


SPELL = "spell"
"""The word of a regeneration alternative that only a spell or effect meets ("spells or effects with the good
descriptor" is `["good", "spell"]`): no weapon has it, so a weapon's hit never meets that alternative."""


def alternative_said(alt: list[str]) -> str:
    """A regeneration alternative as the DM reads it: "fire", "good and silver", "good spells"."""
    words = [w for w in alt if w != SPELL]
    return f"{' and '.join(words)} spells" if SPELL in alt else " and ".join(words)


def stoppers(regeneration: Mapping[str, Any]) -> str:
    """What deals a regenerating creature lethal damage: "fire or acid", "good and silver or good spells"."""
    return " or ".join(alternative_said(alt) for alt in _alternatives(regeneration)) or "nothing"



def regenerated(
    target: Combatant, has: set[str], energy_dealt: Mapping[str, int], damage: int
) -> tuple[int, int, str | None]:
    """How regeneration takes a hit of `damage` (its energy riders' `energy_dealt` in it): "Damage dealt to the
    creature is treated as nonlethal damage", but "certain attack forms, typically fire and acid, deal damage to the
    creature normally". The lethal part, the nonlethal part (DEL-421) and the note. Without regeneration all of it is
    lethal, with no note; an attack form that stops it (`has` meets an alternative) is lethal whole; otherwise an
    energy that stops it is lethal (its dealt part) and the rest nonlethal."""
    regeneration = of_combatant(target).get("regeneration")
    if not regeneration:
        return damage, 0, None
    value = regeneration["value"]
    alternatives = _alternatives(regeneration)
    lethal = next((alt for alt in alternatives if all(w in has for w in alt)), None)
    if lethal is not None:
        return damage, 0, f"regeneration {value}: lethal ({alternative_said(lethal)})"
    by_energy = [k for k, n in energy_dealt.items() if n and any(all(w in has | {k} for w in a) for a in alternatives)]
    if by_energy:
        dealt = ", ".join(f"{k} damage ({energy_dealt[k]})" for k in by_energy)
        part = min(damage, sum(energy_dealt[k] for k in by_energy))
        return part, damage - part, f"regeneration {value}: the {dealt} is lethal, the rest nonlethal"
    return 0, damage, f"regeneration {value}: nonlethal damage ({stoppers(regeneration)} deals lethal)"


def regeneration_said(c: Combatant, before: int, after: int) -> str:
    """The round's note of a combatant's regeneration lowering its nonlethal damage (`tools._combat_round`)."""
    regeneration = of_combatant(c)["regeneration"]
    said = f"regeneration {regeneration['value']} ({stoppers(regeneration)} deals lethal damage)"
    return f"{c.name}: {said}: nonlethal {before} → {after}."


def fast_healing_said(c: Combatant, before: int, after: int) -> str:
    """The round's note of a combatant's fast healing raising its hit points (`tools._combat_round`)."""
    return f"{c.name}: fast healing {of_combatant(c)['fast_healing']}: hp {before} → {after}."


def spell_resistance(target: Combatant | None, row: Mapping[str, Any] | None, levels: int) -> int:
    """The target's spell resistance: its combatant's `sr` (a stored one without it, its row's), else its race row's
    (`row`); "+ class levels" (`sr_plus_class_levels`) adds the `levels` of a character's classes. 0 for none."""
    theirs = of_combatant(target) if target is not None else {}
    source = theirs if theirs.get("sr") else dict(row or {})
    sr = int(source.get("sr") or 0)
    if sr and source.get("sr_plus_class_levels"):
        sr += levels
    return sr
