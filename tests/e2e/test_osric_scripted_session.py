"""An OSRIC session played through the tool host, and its final state frozen (DEL-383): what OSRIC's engine decides,
roll by roll, on a seeded die. The helpers are those of the AD&D 2e pack's scripted session, which is private.

The script (`tests/fixtures/scripts/osric_session.json`) makes three characters (a fighter with 18/50 Strength, a
magic-user and a cleric), fights two goblins with initiative by side, as a new OSRIC campaign rolls it, attacks a fleeing
goblin, saves, takes a character to 0 hit points, rests three days and awards XP. Regenerate the golden with
`DELVE_REGOLDEN=1` only for a change that is meant to, review it against OSRIC's rules, and say why in the commit.

Reviewed against OSRIC's rules (`packs/osric/src/delve_osric/rules/`) when the golden was made (2026-11-16):
- A new OSRIC campaign rolls initiative by side: one d6 a side each round, lower acting first (21-initiative.md); the
  party's 1 beats the goblins' 5 in round 1.
- Halvaine casts Magic Missile in round 1: the spell is cast in its segment and leaves its memorized slot spent; its
  effect is the DM's to apply, as Delve's spells are.
- Garrek attacks a fleeing Goblin 2 at +4, on top of his own attack ("The attack on a fleeing foe comes on top of the
  attacker's own this round."), and kills it.
- In round 3 Garrek kills Goblin 1, the last goblin, on the party's count; Anselm, on the same count, has no living
  target left, so he rolls nothing and the corpse takes no second hit (DEL-385).
- Anselm, a 1st-level cleric, needs 10 to save against paralysation and rolls 15: saved.
- Halvaine at 4 hp takes 4: 0 hp, downed, not dead (OSRIC: dead at -10).
- Three days' rest heal 1 hp a day, with no bed-rest rate (Halvaine 0 -> 3), and the rest makes his spell uncast
  again.
- 200 XP each to Garrek (Strength 18/50) and Anselm (Wisdom 16) earn the prime-requisite bonus of 10%: 220.
"""

import json
import re

import pytest

from delve.config import Config
from delve.storage import open_storage
from delve.web.routes.campaigns import initiative_of_ruleset
from tests.e2e.scripted import SCRIPTS, load, play, start_campaign
from tests.fixtures import rulesets
from tests.fixtures.snapshot import assert_snapshot

pytestmark = pytest.mark.slow

GOLDEN = SCRIPTS / "osric_session.golden.json"


@pytest.fixture(scope="module")
def session(tmp_path_factory):
    config = Config(data_dir=tmp_path_factory.mktemp("e2e") / "data")
    storage = open_storage(config)
    catalogs = rulesets.osric_catalogs()
    script = load("osric_session")
    campaign = initiative_of_ruleset(storage, start_campaign(storage, script, ruleset="osric"), catalogs)
    campaign, calls = play(storage, script, campaign, catalogs=catalogs)
    yield storage, campaign, calls
    storage.close()


def _names(storage, campaign_id) -> dict[str, str]:
    """Every id of the session by the name the golden file uses for it."""
    names = {c.id: c.name for c in storage.characters.list(campaign_id)}
    for event in storage.events.list(campaign_id, types=["combat_started"]):
        names[event.data["combat_id"]] = "<fight>"
    return names


def _normalised(value, names: dict[str, str]):
    text = json.dumps(value, sort_keys=True)
    for id, name in names.items():
        text = text.replace(id, name)
    text = re.sub(r'"(roll|note|hr)_[0-9a-f]{12}"', r'"<\1 id>"', text)
    text = re.sub(r'"\d{4}-\d\d-\d\dT[^"]+"', '"<time>"', text)
    return json.loads(text)


def _final_state(storage, campaign_id) -> dict:
    state = storage.campaign_states.get(campaign_id)
    return {
        "characters": [
            {
                "name": c.name,
                "kind": c.kind,
                "order": c.order,
                "levels": dict(c.sheet.levels),
                "hp": c.state.hp,
                "hp_max": c.sheet.hp_max,
                "saves": dict(c.sheet.saves),
                "xp": c.state.xp,
                "conditions": list(c.state.conditions),
                "effects": [e.name for e in c.state.effects],
                "inventory": [i.name for i in c.state.inventory],
                "memorized": [[s.name, s.level, s.cast] for s in c.state.memorized],
            }
            for c in storage.characters.list(campaign_id)
        ],
        "campaign": {
            "day": state.day,
            "time": f"{state.hour:02d}:{state.minute:02d}",
            "session": state.session,
            "coin": dict(state.coin),
            "loot": [item.description for item in state.loot],
        },
        "sessions": [
            {"number": s.number, "title": s.title, "recap_md": s.recap_md} for s in storage.sessions.list(campaign_id)
        ],
        "map_states": storage.map_states.list(campaign_id),
        "live_fight": storage.combats.live(campaign_id) is not None,
        "events": [[e.beat, e.type] for e in storage.events.list(campaign_id)],
        "rolls": [
            {
                "beat": r.key.beat,
                "purpose": r.key.purpose,
                "actor": r.key.actor,
                "target": r.key.target,
                "round": r.key.combat_round,
                "notation": r.notation,
                "faces": list(r.faces),
                "total": r.total,
            }
            for r in storage.rolls.list(campaign_id)
        ],
    }


def test_every_call_answers(session):
    _, _, calls = session
    assert len(calls) == sum(len(b["calls"]) for b in load("osric_session")["beats"])
    assert [c.tool for c in calls if "error" in c.result] == []


def test_osric_final_state_matches_golden(session):
    storage, campaign, _ = session
    final = _normalised(_final_state(storage, campaign.id), _names(storage, campaign.id))
    assert_snapshot(GOLDEN, json.dumps(final, indent=1, sort_keys=True, ensure_ascii=False) + "\n")
