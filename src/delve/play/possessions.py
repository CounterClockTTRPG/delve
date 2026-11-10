"""Possessions (spec §7.9; ttrpg2 `tools/holdings.py`): a mount, a vehicle, a ship, a house, a stronghold, a domain or
anything else, owned by a character or by the party (`owner_id` None).

ttrpg2's houses and mounts are one kind of thing here, with a `kind`. A mount of a species the ruleset knows gets its
stats (`rules.classic.mounts`), which `stats` overrides; its `mv` and `fly` set the party's travel speed
(`movement`). A vehicle's or ship's stats are `{mv, capacity}`; other kinds keep any object. Possessions have no
management rules: no staff, upkeep or rations. When an owner is deleted, the storage gives the possession to the party.

A possession's `notes_md` is the DM's: every answer here but `detail` leaves it out.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace
from typing import Any, cast

from delve.domain import new_id
from delve.domain.world import POSSESSION_KINDS, Possession, PossessionKind
from delve.play import characters
from delve.play.context import CampaignContext, NotFound, PlayError
from delve.rules.classic.mounts import UnknownSpecies, mount_stats, species_key

__all__ = ["PARTY", "add", "detail", "listing", "movement", "mph", "public", "remove", "update"]

PARTY = "party"
"""The owner that names the party, for `listing` and `update`."""

_NUMBERS = ("hp", "hp_max", "ac", "mv", "fly", "thac0", "morale", "capacity")
_NOT_NEGATIVE = ("mv", "fly", "capacity")


def _kind(kind: str) -> PossessionKind:
    wanted = kind.strip().lower()
    if wanted not in POSSESSION_KINDS:
        raise PlayError(f"No possession kind '{kind}'.", hint=f"A kind is one of: {', '.join(POSSESSION_KINDS)}.")
    return cast(PossessionKind, wanted)


def _name(name: str) -> str:
    if not name.strip():
        raise PlayError("A possession needs a name.")
    return name.strip()


def _owner(ctx: CampaignContext, owner: str) -> str | None:
    """The owner's character id, None for the party ("" or "party")."""
    if not owner.strip() or owner.strip().casefold() == PARTY:
        return None
    return characters.get(ctx, owner).id


def _stats(stats: Any) -> dict[str, Any]:
    if not isinstance(stats, dict):
        raise PlayError("stats must be an object.")
    for key in _NUMBERS:
        value = stats.get(key)
        if key in stats and (not isinstance(value, int) or isinstance(value, bool)):
            raise PlayError(f"stats.{key} must be a whole number.")
        if key in _NOT_NEGATIVE and key in stats and value < 0:
            raise PlayError(f"stats.{key} can't be negative.")
    speed = stats.get("mph")
    if "mph" in stats and (not isinstance(speed, (int, float)) or isinstance(speed, bool) or speed < 0):
        raise PlayError("stats.mph must be a number of miles an hour, not negative.")
    return dict(stats)


def _with_species(ctx: CampaignContext, kind: PossessionKind, species: str, stats: dict[str, Any]) -> dict[str, Any]:
    """A mount's stats from its species and `stats`; the others' `stats` as given."""
    if kind != "mount":
        if species.strip():
            raise PlayError("Only a mount has a species.", hint="Leave species empty, or make it a mount.")
        return stats
    try:
        return mount_stats(species or str(stats.get("species", "")), stats, rules=ctx.rules)
    except UnknownSpecies as unknown:
        raise PlayError(
            f"A {unknown} has no defaults: give its hp_max and thac0 in stats.",
            hint=f"AC and movement may be anything, 0 included. Known species: {', '.join(ctx.rules.mounts)}.",
        ) from None


def _inventory(items: Iterable[Any]) -> tuple[str, ...]:
    return tuple(str(item).strip() for item in items if str(item).strip())


def _candidate(possession: Possession) -> dict[str, Any]:
    return {"id": possession.id, "name": possession.name, "kind": possession.kind}


def _get(ctx: CampaignContext, ref: str) -> Possession:
    """The possession with the id `ref`, or the one whose name is exactly `ref` (ignoring case and outer spaces)."""
    wanted = ref.strip()
    everything = ctx.storage.possessions.list(ctx.campaign_id)
    for possession in everything:
        if possession.id == wanted:
            return possession
    named = [p for p in everything if p.name.casefold() == wanted.casefold()]
    if len(named) == 1:
        return named[0]
    if named:
        raise NotFound(f"'{ref}' is ambiguous: {len(named)} possessions have that name.", map(_candidate, named))
    near = [p for p in everything if wanted.casefold() and wanted.casefold() in p.name.casefold()]
    hint = "" if everything else "add_possession makes one."
    raise NotFound(f"No possession '{ref}'.", map(_candidate, near or everything), hint=hint)


def public(possession: Possession, names: dict[str, str]) -> dict[str, Any]:
    """A possession as the party may know it, without `notes_md`: its owner by id and by name (None for the
    party's). `names` are the campaign's characters' names by id."""
    raw = possession.to_dict()
    for key in ("campaign_id", "notes_md"):
        raw.pop(key)
    raw["owner"] = names.get(possession.owner_id) if possession.owner_id else None
    return raw


def _names(ctx: CampaignContext) -> dict[str, str]:
    return {c.id: c.name for c in ctx.storage.characters.list(ctx.campaign_id)}


def _save(ctx: CampaignContext, possession: Possession, action: str) -> dict[str, Any]:
    with ctx.storage.transaction():
        stored = ctx.storage.possessions.put(possession)
        ctx.log("possession", action=action, id=stored.id, name=stored.name, kind=stored.kind)
    return public(stored, _names(ctx))


def add(
    ctx: CampaignContext,
    name: str,
    kind: str,
    owner: str = "",
    species: str = "",
    location: str = "",
    value_gp: int = 0,
    description: str = "",
    notes: str = "",
    stats: dict[str, Any] | None = None,
    inventory: Iterable[Any] = (),
) -> dict[str, Any]:
    """Register a possession of a character (`owner`, by id or exact name) or of the party (no owner). A mount of a
    known species gets its defaults, which `stats` overrides; an unknown species needs `hp_max` and `thac0`."""
    which = _kind(kind)
    possession = Possession(
        campaign_id=ctx.campaign_id,
        id=new_id("pos"),
        name=_name(name),
        kind=which,
        owner_id=_owner(ctx, owner),
        location=location.strip(),
        value_gp=int(value_gp),
        description=description.strip(),
        notes_md=notes.strip(),
        inventory=_inventory(inventory),
        stats=_with_species(ctx, which, species, _stats(stats or {})),
    )
    return _save(ctx, possession, "added")


def update(
    ctx: CampaignContext,
    ref: str,
    *,
    name: str | None = None,
    kind: str | None = None,
    owner: str | None = None,
    species: str | None = None,
    location: str | None = None,
    value_gp: int | None = None,
    description: str | None = None,
    notes: str | None = None,
    stats: dict[str, Any] | None = None,
    inventory: Iterable[Any] | None = None,
    hp_change: int | None = None,
) -> dict[str, Any]:
    """Change only the fields given. `owner` "" or "party" gives it to the party; `stats` are merged over the
    current ones; `inventory` replaces the list; `hp_change` moves its hit points, never past `hp_max`."""
    possession = _get(ctx, ref)
    which = _kind(kind) if kind is not None else possession.kind
    merged = {**possession.stats, **_stats(stats or {})}
    if species is not None:
        if which != "mount":
            raise PlayError("Only a mount has a species.", hint="Make it a mount first.")
        merged["species"] = species_key(species)
    if hp_change is not None:
        if not isinstance(merged.get("hp"), int):
            raise PlayError(f"{possession.name} has no hit points.", hint="Give it stats.hp first.")
        hp = merged["hp"] + int(hp_change)
        merged["hp"] = min(hp, merged["hp_max"]) if isinstance(merged.get("hp_max"), int) else hp
    changed = replace(
        possession,
        name=_name(name) if name is not None else possession.name,
        kind=which,
        owner_id=_owner(ctx, owner) if owner is not None else possession.owner_id,
        location=location.strip() if location is not None else possession.location,
        value_gp=int(value_gp) if value_gp is not None else possession.value_gp,
        description=description.strip() if description is not None else possession.description,
        notes_md=notes.strip() if notes is not None else possession.notes_md,
        inventory=_inventory(inventory) if inventory is not None else possession.inventory,
        stats=merged,
    )
    return _save(ctx, changed, "updated")


def remove(ctx: CampaignContext, ref: str) -> dict[str, Any]:
    """Remove a possession: sold, lost, dead."""
    possession = _get(ctx, ref)
    with ctx.storage.transaction():
        ctx.storage.possessions.delete(ctx.campaign_id, possession.id)
        ctx.log("possession", action="removed", id=possession.id, name=possession.name, kind=possession.kind)
    return {"id": possession.id, "name": possession.name, "removed": True}


def listing(ctx: CampaignContext, owner: str = "") -> dict[str, Any]:
    """Every possession, or one owner's: a character (id or exact name), or "party" for the party's own."""
    everything = ctx.storage.possessions.list(ctx.campaign_id)
    if owner.strip():
        owner_id = _owner(ctx, owner)
        everything = [p for p in everything if p.owner_id == owner_id]
    names = _names(ctx)
    return {"count": len(everything), "possessions": [public(p, names) for p in everything]}


def detail(ctx: CampaignContext, ref: str) -> dict[str, Any]:
    """The whole record of a possession, its DM-only `notes_md` too."""
    possession = _get(ctx, ref)
    return {**public(possession, _names(ctx)), "notes_md": possession.notes_md}


def movement(possession: Possession) -> tuple[int, int]:
    """A possession's movement rates, `(mv, fly)`: its stats' whole numbers, 0 when it has none."""
    rates = [possession.stats.get(key, 0) for key in ("mv", "fly")]
    mv, fly = (rate if isinstance(rate, int) and not isinstance(rate, bool) else 0 for rate in rates)
    return mv, fly


def mph(possession: Possession) -> float | None:
    """A boat's or a ship's miles an hour on water (its stats' `mph`), None when it has none."""
    speed = possession.stats.get("mph")
    if isinstance(speed, (int, float)) and not isinstance(speed, bool) and speed > 0:
        return float(speed)
    return None
