"""Fights under a d20 engine (DEL-387): combatants, attacks, initiative and XP come from the engine, and the fight rules
`initiative_once` and `highest_first` keep the order rolled in round 1, highest first."""

from dataclasses import replace
from fractions import Fraction

import pytest

from delve.dice import Dice, SeededRng
from delve.play import characters
from delve.play.context import context_for
from delve.rules.classic import combat as rules
from delve.rules.classic.tables import FightRules
from delve.rules.fake import FAKE_TABLES
from tests.fixtures.d20 import d20_catalogs, fake_engine
from tests.fixtures.rulesets import osric
from tests.rules.classic.test_combat import REF, dice, fight_with_goblins


@pytest.fixture
def ctx(d20_storage, d20_campaign):
    fake_engine().called.clear()
    return context_for(d20_storage, d20_campaign.id, "beat-1", catalogs=d20_catalogs())


@pytest.fixture
def fighter(ctx):
    return characters.create(ctx, name="Bram", sheet={"cls": "Fighter", "level": 2, "hp_max": 12})


def _fight(ctx):
    return rules.from_json(ctx.storage.combats.live(ctx.campaign_id)[1])


def _goblins(d20_call, **over):
    return d20_call("setup_combat", enemies=[{"name": "goblin", "count": 2, **over}], surprise=False)


def _attacks():
    return [
        {"attacker": "Bram", "target": "Goblin 1", "targets": ["Goblin 2"]},
        {"attacker": "Goblin 1", "target": "Bram"},
        {"attacker": "Goblin 2", "target": "Bram"},
    ]


def test_a_fight_runs_on_the_engine(ctx, fighter, d20_call):
    setup = _goblins(d20_call)
    assert "error" not in setup, setup
    assert "thac0" not in setup["party_attacks"]["Bram"]
    for beat in ("beat-2", "beat-3"):
        out = d20_call("combat_round", beat=beat, actions=_attacks())
        assert "error" not in out, out
    assert {"combatant_from_sheet", "combatant_from_monster", "initiative", "swing"} <= fake_engine().called
    fight = _fight(ctx)
    assert fight.combatants[fighter.id].d20 == fighter.sheet.d20
    assert all(c.d20 is not None for c in fight.combatants.values())


def test_initiative_is_rolled_once_highest_first(ctx, fighter, d20_call):
    setup = _goblins(d20_call, hp=50)
    totals = [entry["total"] for entry in setup["order"]]
    assert totals == sorted(totals, reverse=True)
    order = [entry["id"] for entry in setup["order"]]
    first = d20_call("combat_round", beat="beat-2", actions=[])
    assert "initiative" not in first
    second = d20_call("combat_round", beat="beat-3", actions=[])
    assert "initiative" not in second
    id = ctx.storage.combats.live(ctx.campaign_id)[0]
    assert [slot["id"] for slot in ctx.storage.combat_rounds.get(id, 2).slots] == order
    assert list(_fight(ctx).order) == order


def test_a_late_monster_gets_a_place(ctx, fighter, d20_call):
    _goblins(d20_call, hp=50)
    d20_call("combat_round", beat="beat-2", actions=[])
    added = d20_call("add_combatant", beat="beat-3", name="goblin", stats={"hp": 50})
    late = added["individuals"][0]["id"]
    fight = _fight(ctx)
    assert late in fight.order and fight.combatants[late].init is not None
    inits = [fight.combatants[id].init for id in fight.order]
    assert inits == sorted(inits, reverse=True)
    d20_call("combat_round", beat="beat-4", actions=[])
    id = ctx.storage.combats.live(ctx.campaign_id)[0]
    assert late in [slot["id"] for slot in ctx.storage.combat_rounds.get(id, 2).slots]


def test_the_end_awards_xp_by_the_engine(ctx, fighter, d20_call):
    _goblins(d20_call, hp=1)
    for name in ("Goblin 1", "Goblin 2"):
        d20_call("apply_damage", character=name, amount=5)
    out = d20_call("end_combat", beat="beat-2")
    assert out["groups"][0]["xp_earned"] == 200
    assert "xp_for_defeated" in fake_engine().called


def test_a_throw_and_a_single_attack_use_the_engine(ctx, fighter, d20_call):
    _goblins(d20_call, hp=50)
    thrown = d20_call("throw_missile", thrower="Bram", target="Goblin 1", missile="oil")
    assert "error" not in thrown, thrown
    swung = d20_call("resolve_attack", beat="beat-2", attacker="Goblin 2", target="Bram")
    assert "error" not in swung, swung
    assert "swing" in fake_engine().called


def test_drained_rebuilds_the_combatant_through_the_engine(ctx, fighter, d20_call):
    _goblins(d20_call, hp=50)
    thac0 = _fight(ctx).combatants[fighter.id].thac0
    fake_engine().called.clear()
    characters.drain_level(ctx, fighter.id, 1)
    drained = characters.get(ctx, fighter.id)
    c = _fight(ctx).combatants[fighter.id]
    assert c.hp_max == drained.sheet.hp_max and c.hp == drained.state.hp
    assert c.d20 == drained.sheet.d20 and c.d20["attack"] == 1
    assert c.thac0 == thac0
    assert "combatant_from_sheet" in fake_engine().called


def test_rearm_rebuilds_the_combatant_through_the_engine(ctx, fighter, d20_call):
    _goblins(d20_call, hp=50)
    thac0 = _fight(ctx).combatants[fighter.id].thac0
    fake_engine().called.clear()
    axe = {"name": "Axe", "damage_sm": "1d8", "damage_l": "1d8"}
    characters.update(ctx, fighter.id, {"attacks": [axe]})
    c = _fight(ctx).combatants[fighter.id]
    assert [b.name for b in c.attacks] == ["Axe"] and c.thac0 == thac0
    assert "combatant_from_sheet" in fake_engine().called


def test_the_fake_swing_falls_back_to_1d3(ctx, fighter):
    engine = fake_engine()
    dice = Dice(SeededRng(3), ctx.storage.rolls, ctx.campaign_id, "beat-1/x")
    a = rules.Combatant(id="a", name="A", side="party", d20={"attack": 30})
    t = rules.Combatant(id="t", name="T", side="enemy", d20={"defence": 1})
    for attacker in (
        replace(a, attacks=(rules.AttackBlock("fist", "", ""),)),
        replace(a, attacks=(rules.AttackBlock("fist", "1d6", "1d6"),), weapon=4),
    ):
        swing = engine.swing(attacker, t, "", dice, 1, ctx.rules.fight)
        assert swing.hit and swing.damage_die == "1d3"


def test_the_switches_alone_leave_osric_as_it_is():
    fight = replace(fight_with_goblins(), rules=osric().tables.fight)
    fight, _ = rules.roll_initiative(fight, dice(3, 5, 2), REF, "combatant", osric().tables)
    fight, _ = rules.run_round(fight, dice(), REF, [], "combatant", osric().tables)
    assert fight.order == ()
    stored = rules.to_json(fight)["rules"]
    assert "initiative_once" not in stored and "highest_first" not in stored


def test_the_switches_work_without_an_engine():
    switched = FightRules(initiative_once=True, highest_first=True)
    fight = replace(fight_with_goblins(), rules=switched)
    fight, out = rules.roll_initiative(fight, dice(3, 5, 2), REF, "combatant", FAKE_TABLES)
    order = [entry["id"] for entry in out["order"]]
    assert [entry["total"] for entry in out["order"]] == sorted((e["total"] for e in out["order"]), reverse=True)
    fight, result = rules.run_round(fight, dice(), REF, [], "combatant", FAKE_TABLES)
    assert result.initiative is None and list(fight.order) == order
    fight, group = rules.add_monsters(fight, dice(4), REF, "goblin", overrides={"hp": 5}, rules=FAKE_TABLES)
    late = group["individuals"][0]["id"]
    assert late in fight.order and fight.combatants[late].init is not None


def test_the_status_shows_the_engines_numbers(ctx, fighter, d20_call):
    _goblins(d20_call, hp=50)
    status = d20_call("combat_status")
    assert status["combatants"]
    for entry in status["combatants"]:
        assert "thac0" not in entry and "ac" not in entry and entry["d20"]["defence"]


def test_an_osric_status_keeps_ac_and_thac0():
    status = rules.status(fight_with_goblins())
    for entry in status["combatants"]:
        assert "ac" in entry and "thac0" in entry and "d20" not in entry


def test_one_down_at_setup_keeps_a_place(ctx, fighter, d20_call):
    characters.update(ctx, fighter.id, {"hp": 0})
    setup = _goblins(d20_call, hp=50)
    order = [entry["id"] for entry in setup["order"]]
    assert fighter.id in order
    first = d20_call("combat_round", beat="beat-2", actions=[{"attacker": "Bram", "target": "Goblin 1"}])
    assert any(r.get("skipped") for r in first["actions"] if r.get("attacker") == "Bram"), first["actions"]
    d20_call("apply_heal", beat="beat-3", character="Bram", amount=5)
    second = d20_call("combat_round", beat="beat-4", actions=[{"attacker": "Bram", "target": "Goblin 1"}])
    swung = [r for r in second["actions"] if r.get("attacker") == "Bram"]
    assert swung and not any(r.get("skipped") for r in swung), second["actions"]
    id = ctx.storage.combats.live(ctx.campaign_id)[0]
    assert [slot["id"] for slot in ctx.storage.combat_rounds.get(id, 2).slots] == order


def test_the_engine_reads_the_reference_row(ctx, fighter, d20_call, monkeypatch):
    """`combatant_from_monster` takes the monster's whole row, as the protocol says, not the classic slice of it."""
    seen = []
    engine = fake_engine()
    made = engine.combatant_from_monster
    monkeypatch.setattr(engine, "combatant_from_monster", lambda row, c, over: seen.append(row) or made(row, c, over))
    assert "error" not in _goblins(d20_call, hp=5)
    assert seen == [ctx.lookups.monster("goblin")[0]] * 2


@pytest.mark.parametrize(
    ("raw", "shape"),
    [
        ("1d8+1", (1, 8, 1)),
        ("2d10+4", (2, 10, 4)),
        ("12d12", (12, 12, 0)),
        ("9d8–9", (9, 8, -9)),  # the SRD's en dash
        ("3d8-6", (3, 8, -6)),
        ("4d10 + 20", (4, 10, 20)),
    ],
)
def test_a_d20_monsters_hit_dice_keep_their_die_and_bonus(raw, shape):  # R18
    hd = rules._parse_hd(raw, dice_notation=True)
    assert (hd["dice"], hd["sides"], hd["mod"]) == shape
    # The classic reading is unchanged: the first number, on d8s.
    classic = rules._parse_hd(raw)
    assert (classic["sides"], classic["mod"]) == (8, 0)


@pytest.mark.parametrize("raw", ["1-1", "1+1", "3", "1/2", "2 hp", "1d8+1 plus 2d8+6", ""])
def test_an_osric_hit_dice_line_reads_as_before(raw):  # R18
    assert rules._parse_hd(raw, dice_notation=True) == rules._parse_hd(raw)


def test_a_d20_monster_has_at_least_1_hp_a_die():  # R18
    # 3d8-6 on three 1s is -3: the SRD gives at least 1 hit point a Hit Die, so 3.
    hd = rules._parse_hd("3d8-6", dice_notation=True)
    assert rules._roll_monster_hp(dice(1, 1, 1), hd, actor="mon_1") == 3
    roll = dice(8, 8, 8)
    assert rules._roll_monster_hp(roll, hd, actor="mon_1") == 18


def test_add_monsters_rolls_the_rows_dice_under_d20(monkeypatch):  # R18
    rows = {"ogre": {"name": "ogre", "hit_dice": "4d8+11", "ac": "5", "damage": "2d8"}}
    monkeypatch.setattr(rules, "_monster_stats", lambda reference, name: rows.get(name))
    log_dice = dice(1, 2, 3, 4)
    _, group = rules.add_monsters(fight_with_goblins(), log_dice, REF, "ogre", d20=fake_engine())
    (rolled,) = [r for _, r in log_dice.log.rolls if r.key.purpose == "hp"]
    assert rolled.notation == "4d8+11" and group["individuals"][0]["hp"] == 1 + 2 + 3 + 4 + 11
    osric_dice = dice(1, 2, 3, 4)
    _, classic = rules.add_monsters(fight_with_goblins(), osric_dice, REF, "ogre")
    (rolled,) = [r for _, r in osric_dice.log.rolls if r.key.purpose == "hp"]
    assert rolled.notation == "4d8" and classic["individuals"][0]["hp"] == 1 + 2 + 3 + 4


def _ogre(monkeypatch, line: str, parts):
    """An ogre whose row's Hit Dice line is `line`, and the fake engine reading `line` as `parts` (None: unread)."""
    rows = {"ogre": {"name": "ogre", "hit_dice": line, "ac": "5", "damage": "2d8"}}
    monkeypatch.setattr(rules, "_monster_stats", lambda reference, name: rows.get(name))
    engine = fake_engine()
    monkeypatch.setattr(engine, "read_hit_dice", lambda raw: parts if raw == line else None)
    return engine


def _hp_rolls(rolled: Dice) -> list[str]:
    """The hit point rolls' notations, a line of parts rolling one each as `hp#1`, `hp#2`…"""
    return [r.notation for _, r in rolled.log.rolls if r.key.purpose.split("#")[0] == "hp"]


def test_a_compound_hit_dice_line_rolls_each_part(monkeypatch):  # DEL-402
    # "4d8+19 plus 4d12+16" (a barbarian ogre): each part rolled with its bonus, the two summed.
    engine = _ogre(monkeypatch, "4d8+19 plus 4d12+16", (rules.HitDie(4, 8, 19), rules.HitDie(4, 12, 16)))
    rolled = dice(1, 2, 3, 4, 5, 6, 7, 8)
    _, group = rules.add_monsters(fight_with_goblins(), rolled, REF, "ogre", d20=engine)
    assert _hp_rolls(rolled) == ["4d8+19", "4d12+16"]
    assert group["individuals"][0]["hp"] == (1 + 2 + 3 + 4 + 19) + (5 + 6 + 7 + 8 + 16)
    assert "notes" not in group


def test_a_fraction_of_a_hit_die_keeps_its_share_rounded_down(monkeypatch):  # DEL-402
    # "1/2 d6+1" (a grig): a d6 of 5 halved is 2 (rounded down), +1 is 3.
    engine = _ogre(monkeypatch, "1/2 d6+1", (rules.HitDie(1, 6, 1, Fraction(1, 2)),))
    rolled = dice(5)
    _, group = rules.add_monsters(fight_with_goblins(), rolled, REF, "ogre", d20=engine)
    assert _hp_rolls(rolled) == ["1d6"] and group["individuals"][0]["hp"] == 3
    # "1/4 d8" (a bat) on a 3: a quarter of it is nothing, but a creature has at least 1 hit point.
    engine = _ogre(monkeypatch, "1/4 d8", (rules.HitDie(1, 8, 0, Fraction(1, 4)),))
    _, group = rules.add_monsters(fight_with_goblins(), dice(3), REF, "ogre", d20=engine)
    assert group["individuals"][0]["hp"] == 1


def test_a_compound_line_has_at_least_1_hp_a_whole_die(monkeypatch):  # DEL-402
    # "1d8-4 plus 2d8-9" on 1s: -3 and -7, but three Hit Dice give at least 3.
    engine = _ogre(monkeypatch, "1d8-4 plus 2d8-9", (rules.HitDie(1, 8, -4), rules.HitDie(2, 8, -9)))
    _, group = rules.add_monsters(fight_with_goblins(), dice(1, 1, 1), REF, "ogre", d20=engine)
    assert group["individuals"][0]["hp"] == 3


def test_a_line_the_engine_cant_read_says_its_hp_was_read_in_part(monkeypatch):  # DEL-402
    engine = _ogre(monkeypatch, "1d8+1 plus 2d8+6", None)
    _, group = rules.add_monsters(fight_with_goblins(), dice(4), REF, "ogre", d20=engine)
    (note,) = group["notes"]
    assert "'1d8+1 plus 2d8+6'" in note and "in part" in note and "hp=" in note
    # With hp passed nothing is said: the DM set it.
    _, given = rules.add_monsters(fight_with_goblins(), dice(), REF, "ogre", d20=engine, overrides={"hp": 20})
    assert "notes" not in given and given["individuals"][0]["hp"] == 20


def test_a_line_the_core_reads_whole_needs_no_note(monkeypatch):  # R18, DEL-402
    engine = _ogre(monkeypatch, "4d8+11", None)
    _, group = rules.add_monsters(fight_with_goblins(), dice(1, 2, 3, 4), REF, "ogre", d20=engine)
    assert "notes" not in group and group["individuals"][0]["hp"] == 1 + 2 + 3 + 4 + 11
    # Nor does an OSRIC line, read the classic way.
    _ogre(monkeypatch, "1d8+1 plus 2d8+6", None)
    _, classic = rules.add_monsters(fight_with_goblins(), dice(4), REF, "ogre")
    assert "notes" not in classic


def _swings_by(out, name: str) -> list[dict]:
    return [a for a in out["actions"] if a.get("attacker") == name and "skipped" not in a]


@pytest.mark.parametrize(("declared", "count"), [({}, 2), ({"condition": "charging"}, 1), ({"single": True}, 1)])
def test_a_charge_or_a_single_attack_is_one_attack_under_d20(ctx, d20_call, declared, count):  # DEL-389
    # Bram swings twice a round (attacks 2); a charge, or a declared `single` (a move and an attack), is one attack,
    # and it spends the round's.
    characters.create(
        ctx,
        name="Bram",
        sheet={
            "cls": "Fighter",
            "level": 2,
            "hp_max": 12,
            "attacks": [{"name": "sword", "attacks": 2, "damage_sm": "1d8"}],
        },
    )
    _goblins(d20_call, hp=500)
    out = d20_call("combat_round", actions=[{"attacker": "Bram", "target": "Goblin 1", **declared}])
    swings = _swings_by(out, "Bram")
    assert len(swings) == count
    assert swings[-1]["attacks_remaining_this_round"] == 0
    # The next round's full attack has both again.
    out = d20_call("combat_round", beat="beat-2", actions=[{"attacker": "Bram", "target": "Goblin 1"}])
    assert len(_swings_by(out, "Bram")) == 2


def test_charging_without_an_engine_keeps_every_attack(d20_storage, d20_host, d20_campaign):  # DEL-389
    # OSRIC: a charging fighter of 2 attacks a round still swings twice, and `single` means nothing there.
    campaign = d20_storage.campaigns.create(
        "Osric", d20_campaign.module_id, d20_campaign.revision, ruleset="osric", setting="greyhawk"
    )

    def call(tool, **args):
        return d20_host.call(campaign.id, "beat-1", tool, args)

    out = call("create_character", name="Garrek",
               sheet={"cls": "Fighter", "level": 7, "hp_max": 50, "thac0": 14,
                      "attacks": [{"name": "sword", "attacks": 2, "damage_sm": "1d8"}]})  # fmt: skip
    assert "error" not in out, out
    assert "error" not in call("setup_combat", enemies=[{"name": "goblin", "count": 1, "hp": 500}], surprise=False)
    out = call(
        "combat_round", actions=[{"attacker": "Garrek", "target": "Goblin", "condition": "charging", "single": True}]
    )
    assert len(_swings_by(out, "Garrek")) == 2


def _tied(ties_by_bonus):
    """Garrek (roll 8 + 4) and a goblin of 1 hp (roll 11 + 1) tied on 12, Garrek at the goblin and it at him."""
    fight = fight_with_goblins(goblins=1, hp=1)
    switched = FightRules(initiative_once=True, highest_first=True, ties_by_bonus=ties_by_bonus)
    garrek, goblin = fight.combatants["chr_garrek"], fight.combatants["mon_1"]
    tied = {garrek.id: replace(garrek, init=12, init_roll=8), goblin.id: replace(goblin, init=12, init_roll=11)}
    fight = replace(fight, rules=switched, combatants={**fight.combatants, **tied}, phase="round")
    fight = rules._ordered(replace(fight, order=(goblin.id, garrek.id)))
    # Without an engine a declaration places the combatant again by its weapon speed; the rolls are dropped so the
    # order stands as set.
    fight = replace(fight, combatants={id: replace(c, init_roll=None) for id, c in fight.combatants.items()})
    actions = [{"attacker": "Goblin", "target": "Garrek"}, {"attacker": "Garrek", "target": "Goblin"}]
    return rules.run_round(fight, dice(20, 6, 20, 3), REF, actions, "combatant", FAKE_TABLES)


def test_a_tie_without_the_switch_acts_simultaneously():
    """No `ties_by_bonus` (2e, OSRIC): a tie is one group, each swing against the state at its start, so the goblin
    Garrek fells still swings at him."""
    fight, result = _tied(None)
    swings = {s["attacker"]: s for s in result.actions}
    assert swings["Garrek"]["hit"] and fight.combatants["mon_1"].hp <= 0
    assert swings["Goblin"]["hit"] and fight.combatants["chr_garrek"].hp < 30


def test_a_tie_broken_by_the_bonus_acts_one_after_another():
    """`ties_by_bonus` (3.5): Garrek's +4 acts before the goblin's +1, and the goblin he fells draws no swing."""
    fight, result = _tied(True)
    assert list(fight.order) == ["chr_garrek", "mon_1"]
    swings = {s["attacker"]: s for s in result.actions}
    assert swings["Garrek"]["hit"] and fight.combatants["mon_1"].hp <= 0
    assert "skipped" in swings["Goblin"] and fight.combatants["chr_garrek"].hp == 30


def test_a_tie_on_total_and_bonus_rolls_off():
    """Two goblins tied on 12 with the same +1: each rolls a d20, again while they tie, and the higher acts first;
    Garrek, on his own total, rolls nothing."""
    fight = fight_with_goblins(goblins=2, hp=5)
    on = {"chr_garrek": (15, 11), "mon_1": (12, 11), "mon_2": (12, 11)}
    fight = replace(fight, combatants={id: replace(c, init=on[id][0], init_roll=on[id][1])
                                       for id, c in fight.combatants.items()})  # fmt: skip
    able, rolls = rules._roll_off(fight, dice(9, 9, 4, 17), list(fight.combatants.values()))
    assert [r.total for r in rolls] == [9, 9, 4, 17] and {r.key.actor for r in rolls} == {"mon_1", "mon_2"}
    fight = rules._ordered(replace(fight, rules=FightRules(highest_first=True, ties_by_bonus=True),
                                   order=tuple(c.id for c in able)))  # fmt: skip
    assert list(fight.order) == ["chr_garrek", "mon_2", "mon_1"]


def _casting(cast_on_turn, *, completes_round=1):
    """Garrek under way with a spell declared in round 1 (one action unless it completes later), in a fight on
    `cast_on_turn`."""
    from delve.rules.classic.initiative import Ongoing

    fight = fight_with_goblins(goblins=1)
    fight = replace(fight, rules=FightRules(initiative_once=True, highest_first=True, cast_on_turn=cast_on_turn))
    spell = Ongoing("spell", "Magic Missile", started_round=1, completes_round=completes_round, modifier=1)
    garrek = replace(fight.combatants["chr_garrek"], ongoing=spell)
    return replace(fight, round=1, combatants={**fight.combatants, garrek.id: garrek})


def test_a_hit_before_the_casters_turn_spoils_the_spell_without_the_switch():
    """No `cast_on_turn` (2e, OSRIC): a hit before the spell is cast spoils it."""
    fight, hurt = rules._hurt(_casting(None), "chr_garrek", 3)
    assert hurt["spell_disrupted"] and fight.combatants["chr_garrek"].ongoing.state == "interrupted"


def test_a_hit_before_the_casters_turn_leaves_a_one_action_spell_on_the_switch():
    """`cast_on_turn` (3.5): a one-action spell is cast on the caster's own turn, so a hit earlier in the round leaves
    it under way; one that spans rounds is still spoilt (the DM's Concentration check)."""
    fight, hurt = rules._hurt(_casting(True), "chr_garrek", 3)
    assert not hurt["spell_disrupted"] and fight.combatants["chr_garrek"].ongoing.under_way
    assert fight.combatants["chr_garrek"].hp == 27
    _, long = rules._hurt(_casting(True, completes_round=2), "chr_garrek", 3)
    assert long["spell_disrupted"]


def _once():
    fight = replace(fight_with_goblins(goblins=1, hp=50), rules=FightRules(initiative_once=True, highest_first=True))
    fight, _ = rules.roll_initiative(fight, dice(5, 3), REF, "combatant", FAKE_TABLES)
    return fight


def test_end_counts_the_rounds_played_under_initiative_once():
    fight = _once()
    assert rules.end(fight)[1]["rounds"] == 0
    for _ in range(2):
        fight, _ = rules.run_round(fight, dice(), REF, [], "combatant", FAKE_TABLES)
    assert rules.end(fight)[1]["rounds"] == 2


def test_classic_end_counts_rounds_as_before():
    fight, _ = rules.roll_initiative(fight_with_goblins(), dice(1, 2, 3), REF, "combatant", FAKE_TABLES)
    assert rules.end(fight)[1]["rounds"] == 1
    fight, _ = rules.run_round(fight, dice(), REF, [], "combatant", FAKE_TABLES)
    assert rules.end(fight)[1]["rounds"] == 1


def _brawl(bram_hp: int = 5) -> rules.Combat:
    """Under the fake engine, Goblin 1 (init 15) and Goblin 2 (init 10) act before Bram (hp `bram_hp`) and Mira, each
    goblin's attack 1d6 at +0 against a defence of 10."""
    sword = rules.AttackBlock("club", "1d6", "1d6")

    def made(id: str, name: str, side: str, hp: int, init: int) -> rules.Combatant:
        numbers = {"attack": 0, "defence": 10, "save": 0}
        return rules.Combatant(id, name, side, hp=hp, hp_max=30, attacks=(sword,), init=init, d20=numbers)

    them = (made("gob_1", "Goblin 1", "enemy", 8, 15), made("gob_2", "Goblin 2", "enemy", 8, 10),
            made("bram", "Bram", "party", bram_hp, 5), made("mira", "Mira", "party", 30, 3))  # fmt: skip
    return rules.Combat(
        phase="round", round=1, order=tuple(c.id for c in them),
        rules=FightRules(initiative_once=True, highest_first=True, ties_by_bonus=True),
        combatants={c.id: c for c in them},
    )  # fmt: skip


def _goblins_at_bram(fight: rules.Combat, *faces: int, fallback: bool = True) -> list[dict]:
    actions = [{"attacker": "Goblin 1", "target": "Bram"},
               {"attacker": "Goblin 2", "target": "Bram", **({"targets": ["Mira"]} if fallback else {})}]  # fmt: skip
    _, result = rules.run_round(fight, dice(*faces), REF, actions, "combatant", FAKE_TABLES, d20=fake_engine())
    return [a for a in result.actions if a.get("attacker") == "Goblin 2"]


def test_a_target_dropped_in_the_round_is_passed_over_under_d20():  # DEL-441, Review Focus 5
    # Goblin 1's 20 hits Bram (hp 5) for 6: -1, down. Goblin 2's target is Bram, its fallback Mira: it swings at Mira.
    (swing,) = _goblins_at_bram(_brawl(), 20, 6, 15, 3)
    assert (swing["target"], swing["hit"], swing["damage"]) == ("Mira", True, 3)
    # With no fallback standing, Goblin 2 rolls nothing, and says who still stands.
    (skipped,) = _goblins_at_bram(_brawl(), 20, 6, fallback=False)
    assert skipped["skipped"] == "target down — attack not rolled" and skipped["target"] == "Bram"
    assert skipped["living_foes"] == ["Mira"]


def test_a_target_down_at_declaration_is_attacked_as_declared():  # DEL-441, Review Focus 5
    # Bram is at -1 when the round is declared: Goblin 2 attacks him as declared (a coup de grâce), not Mira; Goblin 1's
    # 2 misses.
    (swing,) = _goblins_at_bram(_brawl(bram_hp=-1), 2, 15, 3)
    assert (swing["target"], swing["hit"]) == ("Bram", True)


def test_one_disabled_at_the_rounds_start_and_dropped_in_it_is_passed_over():  # DEL-441 x DEL-434, final review
    # Under disabled_at_zero Bram at 0 is disabled, standing, when the round begins. Goblin 1's 20 hits him for 3: -3,
    # down. Goblin 2's target is Bram, its fallback Mira: it swings at Mira (15 hits for 3), not at Bram again. Bram,
    # dying, rolls d% 50 at the round's end.
    fight = replace(_brawl(bram_hp=0), rules=replace(_brawl().rules, disabled_at_zero=True, stabilise_chance=10))
    (swing,) = _goblins_at_bram(fight, 20, 3, 15, 3, 50)
    assert (swing["target"], swing["hit"], swing["damage"]) == ("Mira", True, 3)


def test_classic_targets_unchanged():  # DEL-441
    """Without an engine a downed primary target is still attacked, as before (`up`); the classic case of a felled
    group's foes is `test_an_attacker_whose_foes_all_fell_earlier_in_its_group_makes_no_roll`."""
    fight = _brawl()
    fight = replace(fight, combatants={id: replace(c, d20=None, thac0=1) for id, c in fight.combatants.items()})
    actions = [
        {"attacker": "Goblin 1", "target": "Bram"},
        {"attacker": "Goblin 2", "target": "Bram", "targets": ["Mira"]},
    ]
    _, result = rules.run_round(fight, dice(20, 6, 15, 3), REF, actions, "combatant", FAKE_TABLES)
    (swing,) = [a for a in result.actions if a.get("attacker") == "Goblin 2"]
    assert swing["target"] == "Bram"


# --- disabled at 0 hp and the dying's roll to stabilise (DEL-434, DEL-442) --------------------------------------------

DYING = FightRules(initiative_once=True, highest_first=True, ties_by_bonus=True, disabled_at_zero=True,
                   stabilise_chance=10)  # fmt: skip


def _hurt_party(rules_: FightRules = DYING, *, oryn_hp: int = 3, rate: float = 1.0) -> rules.Combat:
    """Under the fake engine, a goblin (init 15, hp 8) and Oryn (init 5, hp `oryn_hp`, `rate` attacks a round), each
    attack 1d6 at +0 against a defence of 10."""
    club = rules.AttackBlock("club", "1d6", "1d6", rate=rate)
    numbers = {"attack": 0, "defence": 10, "save": 0}
    goblin = rules.Combatant("gob_1", "Goblin", "enemy", hp=8, hp_max=8, attacks=(club,), init=15, d20=numbers)
    oryn = rules.Combatant("oryn", "Oryn", "party", hp=oryn_hp, hp_max=20, attacks=(club,), init=5, d20=numbers)
    them = (goblin, oryn)
    return rules.Combat(phase="round", round=1, order=("gob_1", "oryn"), rules=rules_,
                        combatants={c.id: c for c in them})  # fmt: skip


def _round(fight, actions, *faces):
    return rules.run_round(fight, dice(*faces), REF, actions, "combatant", FAKE_TABLES, d20=fake_engine())


def test_at_zero_a_pc_is_disabled_and_acts():  # DEL-434
    # An attack of opportunity (the goblin's 15 hits defence 10; its 1d6 rolls 3) leaves Oryn (hp 3) at 0: disabled,
    # not downed, and no bleeding.
    fight, hit = rules.attack(_hurt_party(), dice(15, 3), "gob_1", "oryn", d20=fake_engine())
    assert (hit["hp_after"], hit["downed"], hit.get("disabled")) == (0, False, True)
    oryn = fight.combatants["oryn"]
    assert "disabled" in oryn.conditions and "downed" not in oryn.conditions
    # In the round his declared Sleep goes off: a cast, strenuous, so after it he is at -1, downed, dying. At the
    # round's end he rolls to stabilise (d% 55: no) and bleeds to -2.
    fight, result = _round(fight, [{"caster": "Oryn", "spell": "Sleep"}], 55)
    (cast,) = [a for a in result.actions if a.get("caster") == "Oryn"]
    assert cast["cast"] is True and "Oryn strains and falls: −1, dying" in cast["notes"]
    oryn = fight.combatants["oryn"]
    assert oryn.hp == -2 and "downed" in oryn.conditions and "disabled" not in oryn.conditions
    assert result.end_of_round[0].startswith("Oryn bleeds 1 HP (hp now -2")


def test_a_disabled_fighter_makes_one_attack():  # DEL-434, Review Focus 2
    # Oryn at 0 swings twice a round (rate 2), but disabled he makes one attack (15 hits, 1d6 rolls 3: the goblin to 5),
    # and the attack drops him to -1. Without the flag he'd be skipped (`test_classic_zero_is_still_downed`).
    fight, result = _round(_hurt_party(oryn_hp=0, rate=2), [{"attacker": "Oryn", "target": "Goblin"}], 15, 3, 55)
    swings = [a for a in result.actions if a.get("attacker") == "Oryn"]
    assert len(swings) == 1 and swings[0]["hit"] and swings[0]["attacks_remaining_this_round"] == 0
    assert "Oryn strains and falls: −1, dying" in swings[0]["notes"]
    assert fight.combatants["gob_1"].hp == 5 and fight.combatants["oryn"].hp == -2  # -1, then bled (d% 55)


def test_a_free_action_isnt_strenuous_and_healing_clears_disabled():  # DEL-434, Review Focus 2
    # A free-form action (drawing back) at 0 is no strain: Oryn stays at 0, disabled, and doesn't bleed.
    fight, result = _round(_hurt_party(oryn_hp=0), [{"actor": "Oryn", "action": "backs away"}])
    oryn = fight.combatants["oryn"]
    assert (oryn.hp, "disabled" in oryn.conditions) == (0, True) and result.end_of_round == ()
    assert rules.status(fight)["combatants"][1]["status"] == "disabled"
    fight, healed = rules.heal(fight, "oryn", 4)
    assert healed["hp_after"] == 4 and "disabled" not in fight.combatants["oryn"].conditions


def test_a_strained_attackers_late_cleave_is_allowed_once():  # Ruling R2
    # Oryn's one attack at 0 strained him to -1; a late attack of that round (Cleave's, due) is still his, and the -1
    # landed once: he stays at -1 (stable here, d% 7), not -2.
    fight, _ = _round(_hurt_party(oryn_hp=0), [{"attacker": "Oryn", "target": "Goblin"}], 15, 3, 7)
    assert fight.combatants["oryn"].hp == -1 and "stable" in fight.combatants["oryn"].conditions
    fight, late = rules.attack(fight, dice(15, 2), "oryn", "gob_1", d20=fake_engine(), late=True)
    assert late["hit"] and fight.combatants["oryn"].hp == -1 and fight.combatants["gob_1"].hp == 3
    # Without having strained in that round, one down is refused as before.
    with pytest.raises(rules.CombatError, match="down"):
        rules.attack(_hurt_party(oryn_hp=-1), dice(15, 2), "oryn", "gob_1", d20=fake_engine())


def test_the_dying_roll_to_stabilise():  # DEL-442, Review Focus 1
    # Oryn at -3, dying: at the round's end he rolls d% (stabilise:oryn:1); 7 is 10 or less, so he is stable and loses
    # nothing, and the next round he neither bleeds nor rolls again (no die is scripted for it).
    fight, result = _round(_hurt_party(oryn_hp=-3), [], 7)
    (roll,) = [r for r in result.rolls if r.key.purpose == "stabilise"]
    assert (roll.key.actor, roll.key.combat_round, roll.notation, roll.total) == ("oryn", 1, "1d100", 7)
    assert result.end_of_round[0].startswith("Oryn is stable")
    oryn = fight.combatants["oryn"]
    assert (oryn.hp, "stable" in oryn.conditions) == (-3, True)
    fight, result = _round(fight, [])
    assert fight.combatants["oryn"].hp == -3 and result.end_of_round == ()
    # Healed above 0, stable and downed come off; healed only to 0 he is disabled.
    up, _ = rules.heal(fight, "oryn", 5)
    assert up.combatants["oryn"].hp == 2 and not {"stable", "downed"} & set(up.combatants["oryn"].conditions)
    zero, out = rules.heal(fight, "oryn", 3)
    healed_to_zero = zero.combatants["oryn"].conditions
    assert "disabled" in healed_to_zero and "downed" not in healed_to_zero
    assert out["notes"] == ["Oryn regains consciousness, disabled at 0 hp."]
    # d% 55 is more than 10: he bleeds 1, to -4.
    fight, result = _round(_hurt_party(oryn_hp=-3), [], 55)
    assert fight.combatants["oryn"].hp == -4 and "stable" not in fight.combatants["oryn"].conditions


def test_the_goblin_still_dies_at_zero_under_the_flag():  # decision 3
    fight, out = rules.damage(_hurt_party(), "gob_1", 8)
    assert out["dead"] and "disabled" not in fight.combatants["gob_1"].conditions


def test_classic_zero_is_still_downed():  # DEL-434: without the flag, as before
    plain = FightRules(initiative_once=True, highest_first=True, ties_by_bonus=True)
    fight, result = _round(_hurt_party(plain, oryn_hp=0), [{"attacker": "Oryn", "target": "Goblin"}])
    assert [a.get("skipped") for a in result.actions] == ["down — cannot act"]
    fight, out = rules.damage(_hurt_party(plain), "oryn", 3)
    assert out["downed"] and "disabled" not in out and "downed" in fight.combatants["oryn"].conditions
    from delve.rules.classic.life import life_conditions

    assert life_conditions((), 0) == ("downed",)
    assert life_conditions((), 0, disabled_at_zero=True) == ("disabled",)
    assert life_conditions(("disabled",), -1, disabled_at_zero=True) == ("downed",)
    assert life_conditions(("disabled",), 3, disabled_at_zero=True) == ()


def test_stable_comes_off_when_healed_to_zero_or_more_out_of_a_fight():  # DEL-442, final review
    # As the fight's heal does: at 0 or more one is no longer dying, so no longer stable; below 0 it stays. Without the
    # flag (2e, OSRIC) a stable the DM gave is left as it is.
    from delve.rules.classic.life import life_conditions

    assert life_conditions(("downed", "stable"), 0, disabled_at_zero=True) == ("disabled",)
    assert life_conditions(("downed", "stable"), 4, disabled_at_zero=True) == ()
    assert life_conditions(("downed", "stable"), -2, disabled_at_zero=True) == ("downed", "stable")
    assert life_conditions(("downed", "stable"), 4) == ("stable",)


def test_a_stable_pc_healed_to_zero_who_strains_is_dying_again():  # Review Focus 1, 2
    # Stable at -3 (d% 7), healed 3 to 0: disabled, no longer stable. His attack (15 hits, 1d6 rolls 3) strains him to
    # -1, dying again, so the round's end rolls for him (55: not stable) and he bleeds to -2.
    fight, _ = _round(_hurt_party(oryn_hp=-3), [], 7)
    fight, _ = rules.heal(fight, "oryn", 3)
    assert "stable" not in fight.combatants["oryn"].conditions
    fight, result = _round(fight, [{"attacker": "Oryn", "target": "Goblin"}], 15, 3, 55)
    assert [r.total for r in result.rolls if r.key.purpose == "stabilise"] == [55]
    assert fight.combatants["oryn"].hp == -2 and "stable" not in fight.combatants["oryn"].conditions


def test_a_disabled_thrower_throws_once_and_strains():  # DEL-434, fix round 1
    # resolve_attack's sibling throw_missile: Oryn at 0 (rate 2) throws oil at the goblin (15 hits, 2d6 rolls 3 + 2):
    # one throw, his attacks spent, and he strains to -1.
    fight, out = rules.throw(_hurt_party(oryn_hp=0, rate=2), dice(15, 3, 2), "oryn", "gob_1", "oil", REF,
                             d20=fake_engine())  # fmt: skip
    oryn = fight.combatants["oryn"]
    assert out["hit"] and out["attacks_remaining_this_round"] == 0 and oryn.attacks_used == 2
    assert oryn.hp == -1 and "Oryn strains and falls: −1, dying" in out["notes"]


def test_a_disabled_clerics_cure_on_himself_costs_no_strain():  # ruling: "unless the activity increased his hp"
    # Oryn at 0 casts a cure (Sleep stands in: the reference's one spell) at himself: he strains to -1, and at the
    # round's end bleeds to -2 (d% 55). The DM heals him 8 before the next round: the strain and the bleeding come
    # back first, so he ends at 8, not 7 (nor 6); once only.
    fight, _ = _round(_hurt_party(oryn_hp=0), [{"caster": "Oryn", "spell": "Sleep", "target": "Oryn"}], 55)
    assert fight.combatants["oryn"].hp == -2
    fight, healed = rules.heal(fight, "oryn", 8)
    assert (healed["hp_after"], healed["strain_refunded"]) == (8, 2)
    fight, again = rules.heal(fight, "oryn", 1)
    assert again["hp_after"] == 9 and "strain_refunded" not in again
    # A cast at the goblin raised nothing: no refund.
    fight, _ = _round(_hurt_party(oryn_hp=0), [{"caster": "Oryn", "spell": "Sleep", "target": "Goblin"}], 55)
    _, healed = rules.heal(fight, "oryn", 8)
    assert healed["hp_after"] == 6 and "strain_refunded" not in healed


# --- nonlethal damage (DEL-421, DEL-455) ----------------------------------------------------------------------------


def _subdued(fight: rules.Combat, id: str, **d20) -> rules.Combat:
    """The fight with combatant `id`'s `d20` taking `d20` too (the fake engine's `subdual`: its hits are nonlethal)."""
    c = fight.combatants[id]
    return replace(fight, combatants={**fight.combatants, id: replace(c, d20={**(c.d20 or {}), **d20})})


def test_nonlethal_knocks_out_and_the_round_passes_over_it():  # DEL-421
    # Goblin 1's sap (20 hits, 1d6 rolls 6) is nonlethal: Bram keeps his 5 hp and has 6 nonlethal, more than his hp, so
    # he is unconscious. Goblin 2 passes him over for its fallback Mira (15 hits, 3), and Bram's own attack is skipped.
    fight = _subdued(_brawl(), "gob_1", subdual=True)
    actions = [{"attacker": "Goblin 1", "target": "Bram"},
               {"attacker": "Goblin 2", "target": "Bram", "targets": ["Mira"]},
               {"attacker": "Bram", "target": "Goblin 1"}]  # fmt: skip
    fight, result = rules.run_round(fight, dice(20, 6, 15, 3), REF, actions, "combatant", FAKE_TABLES,
                                    d20=fake_engine())  # fmt: skip
    sap, swing, bram = result.actions
    assert (sap["damage"], sap["nonlethal"], sap["hp_after"], sap.get("unconscious")) == (0, 6, 5, True)
    assert (swing["target"], swing["damage"]) == ("Mira", 3)
    assert bram["skipped"] == "unconscious — cannot act"
    assert (fight.combatants["bram"].hp, fight.combatants["bram"].d20["nonlethal"]) == (5, 6)
    shown = {e["id"]: e for e in rules.status(fight, d20=fake_engine())["combatants"]}
    assert (shown["bram"]["status"], shown["bram"]["nonlethal"]) == ("unconscious", 6)


def test_staggered_makes_one_attack():  # DEL-421
    # Bram at 5 hp with 5 nonlethal is staggered: he swings twice a round (rate 2) but makes one attack (15 hits, 3),
    # and, not disabled, takes no strain.
    fight = _brawl()
    bram = replace(fight.combatants["bram"], attacks=(rules.AttackBlock("club", "1d6", "1d6", rate=2),))
    fight = _subdued(replace(fight, combatants={**fight.combatants, "bram": bram}), "bram", nonlethal=5)
    fight, result = rules.run_round(fight, dice(15, 3), REF, [{"attacker": "Bram", "target": "Goblin 1"}], "combatant",
                                    FAKE_TABLES, d20=fake_engine())  # fmt: skip
    swings = [a for a in result.actions if a.get("attacker") == "Bram"]
    assert len(swings) == 1 and swings[0]["attacks_remaining_this_round"] == 0
    assert fight.combatants["bram"].hp == 5 and fight.combatants["gob_1"].hp == 5
    assert rules.status(fight, d20=fake_engine())["combatants"][2]["status"] == "staggered"


def test_a_monster_knocked_out_by_nonlethal_is_defeated():  # DEL-421, Review Focus 3
    fight = _subdued(_brawl(), "gob_1", nonlethal=9)
    _, outcome = rules.end(fight, d20=fake_engine())
    assert outcome["enemies"][0]["fate"] == "down" and outcome["defeated"] == {"goblin": 1}


def test_no_engine_nonlethal_state_plays_as_before():  # DEL-421: only an engine reads nonlethal
    fight = _brawl()
    marked = {id: replace(c, d20={"nonlethal": 99}, thac0=1) for id, c in fight.combatants.items()}
    fight = replace(fight, combatants=marked)
    _, result = rules.run_round(fight, dice(20, 6), REF, [{"attacker": "Bram", "target": "Goblin 1"}], "combatant",
                                FAKE_TABLES)  # fmt: skip
    assert "skipped" not in result.actions[0]
    assert rules.status(fight)["combatants"][2]["status"] == "active"
    assert rules.end(fight)[1]["enemies"][0]["fate"] == "standing"
