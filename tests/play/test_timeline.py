"""The initiative timeline as one seat sees it (table voice and fixes Task B2.1): the fight's order and its ongoing
actions, with no unseen monster named and nothing of a monster's that is the DM's."""

import json
from dataclasses import replace

import pytest

from delve.dice import ScriptedRng
from delve.domain.world import MonsterPicture
from delve.maps import state as map_state
from delve.play import characters, seats
from delve.play.context import context_for
from delve.play.timeline import timeline_for
from delve.rules.classic import combat as rules
from tests.fixtures.combat import GARREK, PIPPA, CombatReference, setup_fight
from tests.fixtures.rulesets import over

SECRET = "SECRET-XYZZY"


@pytest.fixture
def at(storage, campaign):
    def make(*values: int, beat: str = "beat-1"):
        return context_for(storage, campaign.id, beat, ScriptedRng(values), catalogs=over(CombatReference()))

    return make


@pytest.fixture
def party(at):
    ctx = at()
    return [characters.create(ctx, name="Garrek", sheet=GARREK), characters.create(ctx, name="Pippa", sheet=PIPPA)]


@pytest.fixture
def host(owner_seat):
    return owner_seat


def fight_id(storage, campaign):
    return storage.combats.live(campaign.id)[0]


def edit_round(storage, campaign, change):
    """Rewrite the live fight's latest round's slots with `change(slot) -> slot`."""
    row = storage.combat_rounds.latest(fight_id(storage, campaign))
    storage.combat_rounds.put(replace(row, slots=tuple(change(dict(s)) for s in row.slots)))


def on_a_map(storage, campaign, party, seen: set[str]):
    """Put the live fight on the map "crypt", the party in node "hall" having discovered `seen`, and the goblins in
    their own nodes: Goblin 1 in "hall", Goblin 2 in "vault"."""
    views = {pc.id: map_state.CharacterView(location="hall", nodes=frozenset(seen)) for pc in party}
    storage.map_states.put(campaign.id, "crypt", map_state.to_json(map_state.MapState(characters=views)))
    id, raw = storage.combats.live(campaign.id)
    fight = rules.from_json(raw)
    nodes = {"mon_1": "hall", "mon_2": "vault"}
    combatants = {k: replace(c, node=nodes.get(k, c.node)) for k, c in fight.combatants.items()}
    storage.combats.save(id, fight.phase, rules.to_json(replace(fight, map="crypt", combatants=combatants)))
    edit_round(storage, campaign, lambda s: {**s, "node": nodes.get(s["id"], s["node"])})


def player_seat(storage, campaign, plays=()):
    seat = storage.seats.create(campaign.id, "Ana", "en", "player")
    for character in plays:
        storage.seats.set_controller(character.id, seat.id)
    return seat


def test_no_fight_is_null(storage, campaign, host, party):
    assert timeline_for(storage, campaign.id, host) == {"fight": None}


def test_observer_gets_null(storage, campaign, at, party):
    setup_fight(at)
    observer = storage.seats.create(campaign.id, "Olga", "en", "observer")
    assert timeline_for(storage, campaign.id, observer) == {"fight": None}


def test_player_whose_characters_dont_fight_gets_null(storage, campaign, at, party):
    setup_fight(at)
    assert timeline_for(storage, campaign.id, player_seat(storage, campaign)) == {"fight": None}
    assert timeline_for(storage, campaign.id, player_seat(storage, campaign, [party[1]]))["fight"] is not None


def test_the_order_as_rolled(storage, campaign, at, host, party):
    setup_fight(at, spells=[{"caster": "Pippa", "spell": "sleep"}])
    fight = timeline_for(storage, campaign.id, host)["fight"]
    assert (fight["round"], fight["mode"], fight["released"], fight["max_count"]) == (1, "combatant", False, 10)
    assert [(s["key"], s["name"], s["count"], s["state"]) for s in fight["slots"]] == [
        (party[1].id, "Pippa", 3, "waiting"),
        (party[0].id, "Garrek", 4, "waiting"),
        ("mon_1", "Goblin 1", 5, "waiting"),
        ("mon_2", "Goblin 2", 6, "waiting"),
    ]


def test_unseen_monster_unnamed(storage, campaign, at, host, party):
    setup_fight(at)
    on_a_map(storage, campaign, party, seen={"hall"})
    edit_round(
        storage,
        campaign,
        lambda s: {**s, "name": SECRET, "ongoing": {**_spell(SECRET), "reason": SECRET}} if s["id"] == "mon_2" else s,
    )
    fight = timeline_for(storage, campaign.id, host)["fight"]
    hidden = [s for s in fight["slots"] if s["name"] is None]
    assert [(s["key"], s["count"], s["ongoing"], s["character_id"]) for s in hidden] == [("unseen-1", 6, None, None)]
    text = json.dumps(fight)
    assert SECRET not in text and "mon_2" not in text and "vault" not in text


def test_seen_monster_named(storage, campaign, at, host, party):
    setup_fight(at)
    on_a_map(storage, campaign, party, seen={"hall", "vault"})
    names = [s["name"] for s in timeline_for(storage, campaign.id, host)["fight"]["slots"]]
    assert "Goblin 1" in names and "Goblin 2" in names


def test_without_a_map_every_monster_is_named(storage, campaign, at, host, party):
    setup_fight(at)
    assert all(s["name"] for s in timeline_for(storage, campaign.id, host)["fight"]["slots"])


def _spell(what, completes_round=1, completes_count=7):
    return {
        "kind": "spell",
        "what": what,
        "started_round": 1,
        "started_count": 1,
        "completes_round": completes_round,
        "completes_count": completes_count,
        "state": "ongoing",
        "reason": None,
    }


def test_monster_spell_shows_only_its_kind(storage, campaign, at, host, party):
    setup_fight(at)
    edit_round(storage, campaign, lambda s: {**s, "ongoing": _spell(SECRET)} if s["id"] == "mon_1" else s)
    slot = next(s for s in timeline_for(storage, campaign.id, host)["fight"]["slots"] if s["key"] == "mon_1")
    assert slot["ongoing"] == {
        "kind": "spell",
        "what": None,
        "from": 1,
        "to": 7,
        "next_round": False,
        "state": "ongoing",
        "reason": None,
    }


def test_party_spell_shows_whole(storage, campaign, at, host, party):
    setup_fight(at, spells=[{"caster": "Pippa", "spell": "sleep"}])
    slot = timeline_for(storage, campaign.id, host)["fight"]["slots"][0]
    assert slot["ongoing"] == {
        "kind": "spell",
        "what": "sleep",
        "from": 1,
        "to": 3,
        "next_round": False,
        "state": "ongoing",
        "reason": None,
    }


def test_a_long_spell_runs_into_the_next_round(storage, campaign, at, host, party):
    setup_fight(at)
    edit_round(
        storage,
        campaign,
        lambda s: {**s, "ongoing": _spell("Fireball", completes_round=2, completes_count=None)}
        if s["name"] == "Pippa"
        else s,
    )
    slot = next(s for s in timeline_for(storage, campaign.id, host)["fight"]["slots"] if s["name"] == "Pippa")
    assert (slot["ongoing"]["from"], slot["ongoing"]["to"], slot["ongoing"]["next_round"]) == (1, 10, True)


def test_no_enemy_hp_anywhere(storage, campaign, at, host, party):
    setup_fight(at)
    fight = timeline_for(storage, campaign.id, host)["fight"]
    keys = {k for s in fight["slots"] for k in s}
    assert keys == {"key", "name", "side", "character_id", "count", "state", "ongoing", "monster"}
    assert {k for s in fight["slots"] for k in s.get("monster", {})} == {"kind", "picture", "version", "painting"}
    assert not {"hp", "hp_max", "ac", "thac0", "node", "declared"} & set(fight)


def test_side_mode_groups_at_the_side_count(storage, campaign, at, host, party):
    storage.campaigns.set_initiative(campaign.id, "side")
    # Surprise 5/4 (nobody surprised), then the party's d6 3 and the enemy's 6 (OSRIC adds no weapon speed): each
    # side stands together at its count.
    setup_fight(at, init_rolls=(3, 6))
    fight = timeline_for(storage, campaign.id, host)["fight"]
    assert fight["mode"] == "side"
    counts = {s["side"]: set() for s in fight["slots"]}
    for s in fight["slots"]:
        counts[s["side"]].add(s["count"])
    assert counts == {"party": {3}, "enemy": {6}}


def test_released_round_shows_its_outcomes(storage, campaign, at, host, party):
    setup_fight(at, spells=[{"caster": "Pippa", "spell": "sleep"}])
    rules_ctx = at(19, 6)
    from delve.play import combat

    combat.combat_round(rules_ctx, [{"attacker": "Garrek", "target": "Goblin 1"}])
    id = fight_id(storage, campaign)
    assert timeline_for(storage, campaign.id, host)["fight"]["released"] is False
    storage.combat_rounds.release(id, 1, "2026-10-25T12:00:00+00:00")
    fight = timeline_for(storage, campaign.id, host)["fight"]
    states = {s["name"]: s["state"] for s in fight["slots"]}
    assert fight["released"] is True
    assert states == {"Pippa": "acted", "Garrek": "acted", "Goblin 1": "dead", "Goblin 2": "waiting"}
    assert fight["slots"][0]["ongoing"]["state"] == "completed"


def test_old_fight_without_rows_shows_its_order(storage, campaign, at, host, party):
    """A fight stored before 0022 has no rows: its order is read from the fight itself."""
    from delve.play import combat

    setup_fight(at)
    _, raw = storage.combats.live(campaign.id)
    combat.end_combat(at())
    id = storage.combats.create(campaign.id, rules.from_json(raw).phase, raw)
    fight = timeline_for(storage, campaign.id, host)["fight"]
    assert fight["combat_id"] == id and len(fight["slots"]) == 4


def test_a_seat_never_sees_a_secret_planted_everywhere(storage, campaign, at, party):
    """The fourth wall: an enemy named, given a declared spell and a reason that are all the DM's secret."""
    setup_fight(at)
    on_a_map(storage, campaign, party, seen={"hall"})
    edit_round(
        storage,
        campaign,
        lambda s: (
            s
            if s["side"] == "party"
            else {
                **s,
                "name": SECRET if s["id"] == "mon_2" else s["name"],
                "ongoing": {**_spell(SECRET), "reason": SECRET},
            }
        ),
    )
    id, raw = storage.combats.live(campaign.id)
    fight = rules.from_json(raw)
    storage.combats.save(id, fight.phase, rules.to_json(replace(fight, declared={"mon_1": {"spell": SECRET}})))
    for seat in (seats.owner_seat(storage, campaign.id), player_seat(storage, campaign, [party[0]])):
        assert SECRET not in json.dumps(timeline_for(storage, campaign.id, seat))


# ----- faces (DEL-275) -----


def test_a_seen_monster_has_its_kind_and_no_picture_yet(storage, campaign, at, host, party):
    setup_fight(at)
    goblins = [s for s in timeline_for(storage, campaign.id, host)["fight"]["slots"] if s["side"] == "enemy"]
    assert [s["monster"] for s in goblins] == [
        {"kind": "Goblin", "picture": None, "version": None, "painting": False}
    ] * 2


def test_a_seen_monster_shows_its_kinds_picture(storage, campaign, at, host, party):
    sha = storage.blobs.put(b"goblin", "image/webp")
    storage.monster_pictures.put(MonsterPicture("goblin", "Goblin", blob=sha, mime="image/webp", source="seeded"))
    setup_fight(at)
    goblin = next(s for s in timeline_for(storage, campaign.id, host)["fight"]["slots"] if s["side"] == "enemy")
    assert goblin["monster"]["picture"] == "goblin" and goblin["monster"]["version"]


def test_an_unseen_monster_has_no_kind(storage, campaign, at, host, party):
    setup_fight(at)
    on_a_map(storage, campaign, party, seen={"hall"})
    hidden = next(s for s in timeline_for(storage, campaign.id, host)["fight"]["slots"] if s["name"] is None)
    assert "monster" not in hidden


def test_the_party_has_no_monster(storage, campaign, at, host, party):
    setup_fight(at)
    mine = [s for s in timeline_for(storage, campaign.id, host)["fight"]["slots"] if s["side"] == "party"]
    assert all("monster" not in s and s["character_id"] for s in mine)
