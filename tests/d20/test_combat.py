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
