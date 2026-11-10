"""House rules in play (spec §9): a campaign's chosen rules, the rules of each phase, and the seed import from ttrpg2.

A campaign points to bundles and single rules; it copies nothing, so an edit to a rule applies to running campaigns.
Its effective set is the chosen bundles' rules, in order, then the single rules, without the disabled ones and those
tied to another ruleset or setting than the campaign's own (a campaign without a setting leaves out every rule tied
to one).

How the rules reach the DM:
- `rules_for(ctx)` without a phase is what sits in the system prompt (plateau 2b): the `behaviour` and `always` rules,
  and the race and class rules of the party's races and classes.
- `creation_rules` go into the result of creating a character, `level_up_rules` into `award_xp` when a level-up hint
  fires, and `item_rules` into adding or looking up an item. The DM never has to be reminded.

Note for the tool surface (plan 2a Task 11): `play.characters.create` returns a `Character`, so the
`create_character` tool must add `creation_rules(ctx, character)` to its result under `house_rules`, and the
`add_item` and `item_lookup` tools `item_rules(ctx, [name])`. `award_xp` already returns its `house_rules`.
"""

from __future__ import annotations

import re
import threading
from collections import OrderedDict
from collections.abc import Iterable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING

import delve
from delve.domain.campaigns import Campaign, Character
from delve.domain.house_rules import PHASES, PROMPT_PHASES, Bundle, HouseRule, Kind, Phase, subject_key
from delve.play.context import CampaignContext, NotFound, PlayError
from delve.storage.interfaces import Storage

if TYPE_CHECKING:
    from delve.packs.loader import LoadedPack

SEED_BUNDLE_TITLE = "My table (from ttrpg2)"
SEED_BUNDLE_DESCRIPTION = "The house rules ttrpg2 played with: its general rules, homebrew races, classes and items."

_PACKAGED_SEED = Path(delve.__file__).resolve().parent / "reference" / "house-rules"
SEED_DIR = _PACKAGED_SEED if _PACKAGED_SEED.is_dir() else Path(__file__).resolve().parents[3] / "reference" / "house-rules"
"""ttrpg2's `global/house-rules/`: in the wheel at `delve/reference/house-rules`, in the repository at the top."""


# --- a campaign's choice -------------------------------------------------------------------------------------------


def campaign_house_rules(storage: Storage, campaign_id: str) -> dict[str, list[str]]:
    """The bundles and single rules the campaign points to: `{bundle_ids, rule_ids}`, in order."""
    chosen = storage.campaign_house_rules.get(campaign_id)
    if chosen is None:
        raise NotFound(f"No campaign '{campaign_id}'.")
    bundle_ids, rule_ids = chosen
    return {"bundle_ids": bundle_ids, "rule_ids": rule_ids}


def set_campaign_house_rules(
    storage: Storage, campaign_id: str, *, bundle_ids: Iterable[str], rule_ids: Iterable[str]
) -> dict[str, list[str]]:
    """Point the campaign to these bundles and single rules, in this order, in place of its earlier choice."""
    bundle_ids, rule_ids = list(bundle_ids), list(rule_ids)
    if storage.campaigns.get(campaign_id) is None:
        raise NotFound(f"No campaign '{campaign_id}'.")
    unknown_bundles = [id for id in bundle_ids if storage.house_rule_bundles.get(id) is None]
    if unknown_bundles:
        raise NotFound(f"No house-rule bundle '{unknown_bundles[0]}'.")
    unknown_rules = [id for id in rule_ids if storage.house_rules.get(id) is None]
    if unknown_rules:
        raise NotFound(f"No house rule '{unknown_rules[0]}'.")
    storage.campaign_house_rules.put(campaign_id, bundle_ids, rule_ids)
    return campaign_house_rules(storage, campaign_id)


def _fits(rule: HouseRule, campaign: Campaign) -> bool:
    return rule.enabled and rule.ruleset in (None, campaign.ruleset) and rule.setting in (None, campaign.setting)


def effective_rules(storage: Storage, campaign_id: str) -> list[HouseRule]:
    """The campaign's rules: its bundles' rules in order, then its single rules, each once; minus the disabled ones
    and those tied to another ruleset or setting."""
    chosen = campaign_house_rules(storage, campaign_id)
    campaign = storage.campaigns.get(campaign_id)
    if campaign is None:
        raise NotFound(f"No campaign '{campaign_id}'.")
    ids: list[str] = []
    for bundle_id in chosen["bundle_ids"]:
        bundle = storage.house_rule_bundles.get(bundle_id)
        ids.extend(bundle.rule_ids if bundle else ())
    ids.extend(chosen["rule_ids"])
    library = {rule.id: rule for rule in storage.house_rules.list()}
    rules = (library.get(id) for id in dict.fromkeys(ids))
    return [rule for rule in rules if rule is not None and _fits(rule, campaign)]


# --- the rules of each phase ---------------------------------------------------------------------------------------


def _subjects_of(character: Character) -> list[str]:
    """The character's race and classes, as subjects: "Lizardfolk", "Fighter/Witch" → lizardfolk, fighter, witch."""
    names = [character.sheet.race, *character.sheet.cls.split("/")]
    return [subject_key(name) for name in names if name.strip()]


def rules_for(
    ctx: CampaignContext, *, phase: Phase | None = None, subjects: Iterable[str] | None = None
) -> list[HouseRule]:
    """The campaign's rules for `phase`: those with that phase whose subject is none or one of `subjects` (any
    subject when `subjects` is None).

    Without a phase: the rules of the system prompt, which are the `behaviour` and `always` rules, and the race and
    class rules whose subject is a race or class of a PC in the party."""
    rules = effective_rules(ctx.storage, ctx.campaign_id)
    if phase is None:
        party = {s for c in ctx.storage.characters.list(ctx.campaign_id) if c.kind == "pc" for s in _subjects_of(c)}
        return [
            rule
            for rule in rules
            if rule.phases & PROMPT_PHASES or (rule.kind in ("race", "class") and rule.subject in party)
        ]
    if phase not in PHASES:
        raise PlayError(f"Unknown phase '{phase}'.", hint=f"Use one of {', '.join(PHASES)}.")
    wanted = None if subjects is None else {subject_key(s) for s in subjects}
    return [
        rule
        for rule in rules
        if phase in rule.phases and (rule.subject is None or wanted is None or rule.subject in wanted)
    ]


def creation_rules(ctx: CampaignContext, character: Character) -> list[HouseRule]:
    """The `character-creation` rules for a new character: the general ones, and those of its race and classes."""
    return rules_for(ctx, phase="character-creation", subjects=_subjects_of(character))


def level_up_rules(ctx: CampaignContext, character: Character) -> list[HouseRule]:
    """The `level-up` rules for a character going up a level: the general ones, and those of its race and classes."""
    return rules_for(ctx, phase="level-up", subjects=_subjects_of(character))


def item_rules(ctx: CampaignContext, names: Iterable[str]) -> list[HouseRule]:
    """The `items` rules about any of the items `names`, by subject or by title: "Shrinking Blade" and "Marten
    Martialist's Shrinking Blade" both find the homebrew blade."""
    wanted = {subject_key(name) for name in names}
    return [
        rule
        for rule in effective_rules(ctx.storage, ctx.campaign_id)
        if "items" in rule.phases and (rule.subject in wanted or subject_key(rule.title) in wanted)
    ]


# --- the seed import -----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Seed:
    title: str
    body_md: str
    kind: Kind
    phases: tuple[Phase, ...]
    subject: str | None = None
    ruleset: str | None = None
    setting: str | None = None


_HEADING_PHASES: dict[str, Phase] = {"character-creation": "character-creation", "level-up": "level-up"}
_BULLET = re.compile(r"^\s*[-*+]\s+(.*)$")
_TITLE_WORDS = 8


def _title(text: str) -> str:
    """A rule's title from its first words: up to the first stop or comma, at most eight words."""
    clause = re.split(r"[.,;:!?](?:\s|$)", text, maxsplit=1)[0]
    return " ".join(clause.replace("*", "").replace("_", " ").split()[:_TITLE_WORDS]).strip()


def _general(text: str) -> list[_Seed]:
    """`general.md`: one rule per bullet, its phase from the `#` heading above it."""
    seeds: list[_Seed] = []
    phase: Phase = "always"
    bullet: list[str] | None = None

    def close() -> None:
        if bullet:
            body = " ".join(bullet)
            seeds.append(_Seed(_title(body), body, "general", (phase,)))

    for line in text.splitlines():
        heading = re.match(r"^#\s+(.*)$", line)
        match = _BULLET.match(line)
        if heading:
            close()
            bullet = None
            phase = _HEADING_PHASES.get(subject_key(heading.group(1)), "always")
        elif match:
            close()
            bullet = [match.group(1).strip()]
        elif bullet is not None and line.strip():
            bullet.append(line.strip())
        else:
            close()
            bullet = None
    close()
    return seeds


def _homebrew(path: Path, kind: Kind, phases: tuple[Phase, ...], ruleset: str | None) -> _Seed:
    """A file of `races/`, `classes/` or `items/`: titled by its `#` heading without "(Homebrew …)", about the subject
    its file name gives."""
    text = path.read_text(encoding="utf-8")
    first, _, rest = text.partition("\n")
    heading = re.match(r"^#\s+(.*)$", first)
    if heading:
        title = re.sub(r"\s*\(homebrew[^)]*\)\s*$", "", heading.group(1), flags=re.IGNORECASE).strip()
        body = rest.strip()
    else:
        title, body = path.stem.replace("-", " ").title(), text.strip()
    return _Seed(title, body, kind, phases, subject_key(path.stem), ruleset)


_HOMEBREW_FOLDERS: tuple[tuple[str, Kind, tuple[Phase, ...]], ...] = (
    ("races", "race", ("character-creation",)),
    ("classes", "class", ("character-creation", "level-up")),
    ("items", "item", ("items",)),
)
PACK_SEED_FOLDER = "house-rules"
"""The folder of a pack that holds its house rules, laid out as Delve's own."""


def _seeds(root: Path) -> list[_Seed]:
    """The seeds of Delve's own folder: `general.md`, for any ruleset. The homebrew races, classes and items are a
    ruleset's, in its pack (`_pack_seeds`)."""
    if not root.is_dir():
        raise FileNotFoundError(f"No house-rules directory at {root}")
    return _general((root / "general.md").read_text(encoding="utf-8")) if (root / "general.md").is_file() else []


def _pack_seeds(pack: LoadedPack) -> list[_Seed]:
    """The seeds of a pack's `house-rules/` folder (none without one), each tagged with the pack's id: as its ruleset
    for a ruleset pack, as its setting for a setting pack."""
    root = pack.root / PACK_SEED_FOLDER
    if not root.is_dir():
        return []
    tag = {"ruleset" if pack.manifest.kind == "ruleset" else "setting": pack.manifest.id}
    seeds = _general((root / "general.md").read_text(encoding="utf-8")) if (root / "general.md").is_file() else []
    for folder, kind, phases in _HOMEBREW_FOLDERS:
        seeds.extend(_homebrew(path, kind, phases, None) for path in sorted((root / folder).glob("*.md")))
    return [replace(seed, **tag) for seed in seeds]


def import_house_rules(storage: Storage, root: Path, packs: Iterable[LoadedPack] = ()) -> Bundle:
    """Import ttrpg2's house rules from `root` into the library, and put them all in the bundle "My table (from
    ttrpg2)".

    `general.md` gives one rule per bullet: under "Character creation" with phase `character-creation`, under "Level
    up" with `level-up`, under any other heading with `always`.

    The installed `packs` add the rules of their own `house-rules/` folders, each tagged with its pack's id
    (`_pack_seeds`): a `general.md` as above, and each file of `races/`, `classes/` and `items/` one race rule
    (`character-creation`), class rule (`character-creation`, `level-up`) or item rule (`items`), about the subject its
    file name names.

    Importing again is idempotent: a rule matches an existing one by kind, subject and title, and is then left as it
    is, so edits are kept. Rules missing from the bundle are added to its end."""
    seeds = _seeds(root) + [seed for pack in packs for seed in _pack_seeds(pack)]
    with storage.transaction():
        existing = {(r.kind, r.subject, r.title): r for r in storage.house_rules.list()}
        ids: list[str] = []
        for seed in seeds:
            key = (seed.kind, seed.subject, seed.title)
            if key not in existing:
                existing[key] = storage.house_rules.create(
                    title=seed.title,
                    body_md=seed.body_md,
                    kind=seed.kind,
                    phases=seed.phases,
                    ruleset=seed.ruleset,
                    setting=seed.setting,
                    subject=seed.subject,
                )
            ids.append(existing[key].id)
        bundle = next((b for b in storage.house_rule_bundles.list() if b.title == SEED_BUNDLE_TITLE), None)
        if bundle is None:
            return storage.house_rule_bundles.create(
                title=SEED_BUNDLE_TITLE, description_md=SEED_BUNDLE_DESCRIPTION, rule_ids=ids
            )
        missing = tuple(id for id in dict.fromkeys(ids) if id not in bundle.rule_ids)
        if missing:
            bundle = storage.house_rule_bundles.save(replace(bundle, rule_ids=bundle.rule_ids + missing))
        return bundle


def seed_house_rules(storage: Storage, root: Path = SEED_DIR) -> Bundle | None:
    """Import the house rules shipped with Delve when the library is empty; None when it isn't. `delve serve` no
    longer calls it (a fresh install starts without house rules); tests and fixtures seed with it."""
    if storage.house_rules.list() or storage.house_rule_bundles.list():
        return None
    return import_house_rules(storage, root)


# ----- house rules in tool results, once a beat (DEL-79) -----

GIVEN_BEATS = 64
"""How many beats `given` remembers; an older beat's rules come whole again, which is only longer."""
_given: OrderedDict[tuple[str, str], set[str]] = OrderedDict()
_given_lock = threading.Lock()


def given(ctx: CampaignContext, rules: Iterable[HouseRule]) -> list[dict]:
    """The rules for a tool's result: whole the first time a result of this beat gives one, then only its id and
    title. Making a party gave every character the same creation rules, 18 KB each (DEL-79)."""
    with _given_lock:
        key = (ctx.campaign_id, ctx.beat)
        seen = _given.setdefault(key, set())
        _given.move_to_end(key)
        while len(_given) > GIVEN_BEATS:
            _given.popitem(last=False)
        out = []
        for rule in rules:
            if rule.id in seen:
                out.append({"id": rule.id, "title": rule.title, "given": "whole earlier in this beat"})
            else:
                seen.add(rule.id)
                out.append(rule.to_dict())
        return out


def forget_beat(campaign_id: str, beat_id: str) -> None:
    """A beat runs again (Retry) with a DM that may not have its earlier results: its rules come whole again."""
    with _given_lock:
        _given.pop((campaign_id, beat_id), None)
