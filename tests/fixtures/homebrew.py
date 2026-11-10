"""Homebrew races, classes and items in the house-rule library, as a ruleset pack's `house-rules/` gives them: Delve's
own seeds are general rules only, and the homebrew Delve's tests used to import (ttrpg2's) is AD&D 2e's, in its pack."""

from dataclasses import replace

from delve.domain.house_rules import Bundle
from delve.play import house_rules as hr

HOMEBREW = (
    ("Lizardfolk", "race", ["character-creation"], "lizardfolk"),
    ("Kobold", "race", ["character-creation"], "kobold"),
    ("Witch", "class", ["character-creation", "level-up"], "witch"),
    ("Barbarian", "class", ["character-creation", "level-up"], "barbarian"),
    ("Caster's Aid", "item", ["items"], "casters-aid"),
    ("Hand of Tyr", "item", ["items"], "hand-of-tyr"),
    ("Marten Martialist's Shrinking Blade", "item", ["items"], "shrinking-blade"),
    ("The Hawkblade", "item", ["items"], "the-hawkblade"),
)
"""(title, kind, phases, subject), by file name as a pack's folders hold them."""


def seed_with_homebrew(storage) -> Bundle:
    """Delve's seeds and `HOMEBREW` in the seed bundle "My table (from ttrpg2)"."""
    bundle = hr.import_house_rules(storage, hr.SEED_DIR)
    made = [
        storage.house_rules.create(
            title=title, body_md=f"## Description\n\n{title}.", kind=kind, phases=phases, subject=subject
        )
        for title, kind, phases, subject in HOMEBREW
    ]
    return storage.house_rule_bundles.save(replace(bundle, rule_ids=bundle.rule_ids + tuple(r.id for r in made)))
