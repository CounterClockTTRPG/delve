"""`play.characters`: creation, the exact-or-ambiguous lookup, damage and healing, XP, the party, coin, rest, NPCs."""

from dataclasses import replace

import pytest

from delve.dice import ScriptedRng, SeededRng
from delve.domain.campaigns import CampaignState
from delve.domain.characters import Effect
from delve.domain.world import TraitsPortrait
from delve.play import characters, images
from delve.play.characters import NotFound, PlayError
from delve.play.context import context_for
from delve.rules.classic import names
from delve.rules.classic.tables import Healing
from tests.fixtures.play_reference import PlayReference
from tests.fixtures.rulesets import over

GARREK = {"race": "human", "cls": "Fighter", "level": 3, "hp_max": 24, "ac": 4, "thac0": 18}


def events(ctx, type=None):
    return [e for e in ctx.storage.events.list(ctx.campaign_id) if type is None or e.type == type]


# --- creation ----------------------------------------------------------------------------------------------------


def test_create_fills_saves_from_the_class_table_and_logs(ctx):
    garrek = characters.create(ctx, name="Garrek", sheet=GARREK)
    assert garrek.id.startswith("chr_") and len(garrek.id) == len("chr_") + 12
    assert (garrek.kind, garrek.order, garrek.sheet.label, garrek.sheet.levels) == ("pc", 0, "Garrek", {"fighter": 3})
    assert garrek.state.hp == 24
    # OSRIC's fighter table at 3rd level (AD&D 2e's warrior table is tested in its pack).
    assert garrek.sheet.saves == {
        "death_paralysis_poison": 13,
        "petrification_polymorph": 14,
        "aimed_magic_items": 15,
        "breath_weapons": 16,
        "spells": 16,
    }
    assert ctx.storage.characters.get(garrek.id) == garrek
    [event] = events(ctx)
    assert (event.type, event.data, event.beat, event.session) == (
        "character_created",
        {"character_id": garrek.id, "name": "Garrek", "kind": "pc"},
        "beat-1",
        1,
    )


def test_create_character_names_by_dice(make_ctx):
    """A PC the DM makes up gets its name from the dice, for its sheet's race and gender (Features 18)."""
    sheet = {"race": "dwarf", "gender": "female", "cls": "fighter", "level": 1, "hp_max": 9}
    dwarf = characters.create(make_ctx(seed=11), sheet=sheet)
    assert dwarf.name and dwarf.name == names.generate(SeededRng(11), race="dwarf", female=True)
    assert dwarf.sheet.label == dwarf.name
    [event] = events(make_ctx())
    assert event.data == {"character_id": dwarf.id, "name": dwarf.name, "kind": "pc"}


def test_create_character_keeps_a_given_name(make_ctx):
    """A name the player or the book gives is kept exactly (trimmed), and no dice are drawn for it."""
    ctx = make_ctx(seed=11)
    before = ctx.dice.rng._random.getstate()
    anselm = characters.create(ctx, name="  Brother Anselm ", sheet={"race": "human", "gender": "male"})
    assert anselm.name == "Brother Anselm"
    assert ctx.dice.rng._random.getstate() == before


def test_create_character_names_an_unknown_race(make_ctx):
    for race in ("half-ogre", "Aasimar", ""):
        assert characters.create(make_ctx(seed=5), sheet={"race": race, "hp_max": 6}).name.strip()
    assert characters.create(make_ctx(seed=5), sheet={"hp_max": 6}).name.strip()


def test_create_keeps_given_saves_and_multiclass_levels(ctx):
    grusk = characters.create(
        ctx,
        name="Grusk",
        sheet={"cls": "Fighter/Thief", "levels": {"Fighter": 1, "thief": 2}, "hp_max": 10, "saves": {"spell": 9}},
    )
    assert grusk.sheet.levels == {"fighter": 1, "thief": 2}
    assert grusk.sheet.saves["spells"] == 9
    assert grusk.sheet.saves["petrification_polymorph"] == 12  # the better of thief (12) and fighter (15) in OSRIC
    pippa = characters.create(ctx, name="Pippa", sheet={"hp_max": 4})
    assert pippa.sheet.saves == {} and pippa.sheet.levels == {}  # no class: saves at 0-level, and say so
    tira = characters.create(ctx, name="Tira", kind="npc", sheet={"notes_md": "Owes the guild.", "disposition": -45})
    assert (tira.kind, tira.order, tira.sheet.kind) == ("npc", None, "npc")
    assert [c.order for c in characters.party(ctx)] == [0, 1]


def test_create_and_update_store_saves_under_their_long_names(ctx):
    """The first session's sheet had `para` and `rsw`: it rolled right, but the sheet showed those saves blank."""
    dwarf = characters.create(ctx, name="Dwarf", sheet={**GARREK, "saves": {"para": 9, "RSW": 11, "spell": 12}})
    assert dwarf.sheet.saves == {
        "death_paralysis_poison": 9,
        "aimed_magic_items": 11,
        "petrification_polymorph": 14,
        "breath_weapons": 16,
        "spells": 12,
    }
    updated = characters.update(ctx, dwarf.id, {"saves": {**dwarf.sheet.saves, "bw": 10, "poly": 8}})
    assert updated.sheet.saves == {
        "death_paralysis_poison": 9,
        "aimed_magic_items": 11,
        "petrification_polymorph": 8,
        "breath_weapons": 10,
        "spells": 12,
    }
    assert ctx.storage.characters.get(dwarf.id).sheet.saves == updated.sheet.saves


def test_create_validates_the_sheet(ctx):
    with pytest.raises(PlayError) as caught:
        characters.create(ctx, name="Garrek", sheet={"hp_max": "lots"})
    assert "hp_max" in caught.value.message
    with pytest.raises(PlayError) as caught:
        characters.create(ctx, name="Garrek", sheet={"wings": 2})
    assert "wings" in caught.value.message and "hp_max" in caught.value.hint
    with pytest.raises(PlayError):
        characters.create(ctx, name="Grusk", sheet={"cls": "Fighter/Thief", "levels": {"thief": 2}})
    with pytest.raises(PlayError):
        characters.create(ctx, name="Grim", kind="monster", sheet={})
    assert ctx.storage.characters.list(ctx.campaign_id) == [] and events(ctx) == []


# --- lookup ------------------------------------------------------------------------------------------------------


def test_exact_or_ambiguous_never_prefix(ctx):
    """Review Focus 1: "Gob" is neither "Goblin 1" nor "Goblin 2"; two characters called "Goblin" are ambiguous. A
    name matches exactly, ignoring case, or by id; there is no prefix match (ttrpg2's `char_key_for` matched the first
    prefix, as `test_known_bug_targets_match_by_prefix` pins for combat)."""
    one = characters.create(ctx, name="Goblin 1", kind="npc", sheet={})
    two = characters.create(ctx, name="Goblin 2", kind="npc", sheet={})
    twin_a = characters.create(ctx, name="Goblin", kind="npc", sheet={})
    twin_b = characters.create(ctx, name="Goblin", kind="npc", sheet={})

    with pytest.raises(NotFound) as caught:
        characters.get(ctx, "Gob")
    assert caught.value.message == "No character 'Gob'."
    assert {c["id"] for c in caught.value.candidates} == {one.id, two.id, twin_a.id, twin_b.id}

    with pytest.raises(NotFound) as caught:
        characters.get(ctx, "goblin")
    assert "ambiguous" in caught.value.message
    assert caught.value.candidates == [
        {"id": twin_a.id, "name": "Goblin", "kind": "npc"},
        {"id": twin_b.id, "name": "Goblin", "kind": "npc"},
    ]
    assert caught.value.hint

    assert characters.get(ctx, "GOBLIN 2") == two
    assert characters.get(ctx, "  goblin 1 ") == one
    assert characters.get(ctx, twin_b.id) == twin_b

    with pytest.raises(NotFound) as caught:
        characters.get(ctx, "Orc")
    assert len(caught.value.candidates) == 4  # nothing near: every character is a candidate


# --- changes -----------------------------------------------------------------------------------------------------


def test_update_sheet_and_state(ctx):
    garrek = characters.create(ctx, name="Garrek", sheet=GARREK)
    changed = characters.update(
        ctx,
        "garrek",
        {"name": "Garrek the Grey", "ac": 3, "hp": 20, "effects": [{"name": "bless", "duration": 6, "to_hit": 1}]},
        reason="new armour",
    )
    assert (changed.id, changed.name, changed.sheet.label, changed.sheet.ac, changed.state.hp) == (
        garrek.id,
        "Garrek the Grey",
        "Garrek the Grey",
        3,
        20,
    )
    assert changed.state.effects == (Effect("bless", 6, to_hit=1),)
    assert ctx.storage.characters.get(garrek.id) == changed
    event = events(ctx, "character_updated")[0]
    assert event.data["fields"] == ["ac", "effects", "hp", "name"] and event.data["reason"] == "new armour"

    assert characters.update(ctx, "Garrek the Grey", {"level": 4}).sheet.levels == {"fighter": 4}
    with pytest.raises(PlayError):
        characters.update(ctx, garrek.id, {"hp": "full"})
    with pytest.raises(PlayError):
        characters.update(ctx, garrek.id, {"wings": 2})


def test_update_levels_of_a_multiclass(ctx):
    """ttrpg2 `UpdateLevelsTests`: a multi-class character's levels name every class, and a bare level is refused."""
    characters.create(ctx, name="Grusk", sheet={"cls": "Fighter/Thief", "level": 1, "hp_max": 10})
    grusk = characters.update(ctx, "Grusk", {"levels": {"Thief": 2, "fighter": 1}})
    assert grusk.sheet.levels == {"fighter": 1, "thief": 2}
    with pytest.raises(PlayError):
        characters.update(ctx, "Grusk", {"levels": {"thief": 3}})
    with pytest.raises(PlayError):
        characters.update(ctx, "Grusk", {"level": 2})


def test_damage_downs_and_floors_at_minus_ten(ctx):
    """PHB ch. 9 / DMG ch. 9: 0 hit points or fewer is down; -10 is dead, and lower isn't counted."""
    characters.create(ctx, name="Pippa", sheet={"hp_max": 10})
    hurt = characters.apply_damage(ctx, "Pippa", 12)
    assert (hurt["hp_before"], hurt["hp_after"], hurt["downed"], hurt["dead"]) == (10, -2, True, False)
    assert characters.get(ctx, "Pippa").state.conditions == ("downed",)
    dead = characters.apply_damage(ctx, "Pippa", 20)
    assert (dead["hp_after"], dead["dead"]) == (-10, True)
    assert characters.get(ctx, "Pippa").state.conditions == ("downed", "dead"), "dead is stored, not only downed"
    with pytest.raises(PlayError):
        characters.apply_damage(ctx, "Pippa", -3)
    assert [e.data["hp_after"] for e in events(ctx, "damage")] == [-2, -10]


def test_a_raise_that_sets_hit_points_clears_dead_and_downed(ctx):
    """Raise dead or resurrection, then the DM sets hp (the heal's hint): above -10 the character is no longer dead,
    above 0 no longer downed. Setting conditions alone leaves them as given."""
    characters.create(ctx, name="Pippa", sheet={"hp_max": 10})
    characters.apply_damage(ctx, "Pippa", 30)
    characters.update(ctx, "Pippa", {"conditions": ["downed", "dead", "cursed"]})
    assert characters.get(ctx, "Pippa").state.conditions == ("downed", "dead", "cursed")
    characters.update(ctx, "Pippa", {"hp": 1})
    assert characters.get(ctx, "Pippa").state.conditions == ("cursed",)
    characters.update(ctx, "Pippa", {"hp": -10})
    assert characters.get(ctx, "Pippa").state.conditions == ("cursed", "downed", "dead")


def test_heal_does_not_revive_dead(ctx):
    """A heal never raises the dead: HP stays at -10 and the call answers an error with a hint to use a raise.

    Rule: PHB ch. 9 and DMG ch. 9 (Hit Points, Death's Door): at -10 a character is dead, and only raise dead or
    resurrection bring it back. (ttrpg2's `test_known_bug_heal_revives_the_dead` pins the same bug in the combat
    tracker, fixed in Task 7.)"""
    characters.create(ctx, name="Pippa", sheet={"hp_max": 10})
    characters.apply_damage(ctx, "Pippa", 12)
    healed = characters.apply_heal(ctx, "Pippa", 5)
    assert (healed["hp_before"], healed["hp_after"], healed["healed"]) == (-2, 3, 5)
    assert characters.get(ctx, "Pippa").state.conditions == ()
    assert characters.apply_heal(ctx, "Pippa", 50)["hp_after"] == 10  # up to the maximum

    characters.apply_damage(ctx, "Pippa", 25)
    with pytest.raises(PlayError) as caught:
        characters.apply_heal(ctx, "Pippa", 12)
    assert "dead" in caught.value.message and "raise dead" in caught.value.hint
    pippa = characters.get(ctx, "Pippa")
    assert pippa.state.hp == -10 and pippa.state.conditions == ("downed", "dead")
    assert len(events(ctx, "heal")) == 2


def test_award_xp_multiclass_split(ctx):
    """ttrpg2 `test_class_xp.AwardXpTests`: a multi-class award splits evenly between the classes (PHB ch. 3), each
    class levels on its own table, and the hint names only the class that crossed."""
    characters.create(ctx, name="Grusk", sheet={"cls": "Fighter/Thief", "level": 1, "hp_max": 10})
    characters.update(ctx, "Grusk", {"xp": 2400})
    out = characters.award_xp(ctx, "Grusk", 200)
    assert out["xp_total"] == 2600
    by = {row["class"]: row for row in out["per_class"]}
    assert (by["Thief"]["xp"], by["Thief"]["ready"], by["Fighter"]["ready"]) == (1300, True, False)
    [hint] = out["level_up_hints"]
    assert "Thief level 2" in hint and "Fighter" not in hint
    assert characters.get(ctx, "Grusk").state.xp == 2600

    characters.create(ctx, name="Ysolde", sheet={"cls": "Fighter", "level": 1, "hp_max": 10})
    single = characters.award_xp(ctx, "Ysolde", 2000)
    assert "Fighter level 2" in single["level_up_hints"][0]
    assert [row["xp"] for row in single["per_class"]] == [2000]
    assert [e.data["xp_total"] for e in events(ctx, "xp_awarded")] == [2600, 2000]


def test_marching_order(ctx):
    """ttrpg2 `set_marching_order`: the named characters go to the front in that order, the rest fall in behind."""
    for name in ("Garrek", "Mira", "Pippa", "Anselm"):
        characters.create(ctx, name=name, sheet={"hp_max": 8})
    characters.create(ctx, name="Tira", kind="npc", sheet={})
    assert [c.name for c in characters.party(ctx)] == ["Garrek", "Mira", "Pippa", "Anselm"]

    order = characters.set_marching_order(ctx, ["pippa", "Anselm", "Pippa"])
    assert [c.name for c in order] == ["Pippa", "Anselm", "Garrek", "Mira"]
    assert [c.name for c in characters.party(ctx)] == ["Pippa", "Anselm", "Garrek", "Mira"]
    assert [c.order for c in characters.party(ctx)] == [0, 1, 2, 3]
    assert events(ctx, "marching_order")[0].data["order"] == ["Pippa", "Anselm", "Garrek", "Mira"]

    with pytest.raises(PlayError):
        characters.set_marching_order(ctx, ["Tira"])
    with pytest.raises(NotFound):
        characters.set_marching_order(ctx, ["Pip"])
    assert [c.name for c in characters.party(ctx)] == ["Pippa", "Anselm", "Garrek", "Mira"]


def test_update_coin(ctx):
    assert characters.update_coin(ctx, "+450pp")["coin"] == {"pp": 450, "gp": 0, "ep": 0, "sp": 0, "cp": 0}
    assert characters.update_coin(ctx, " -10SP ")["coin"]["sp"] == -10
    assert ctx.storage.campaign_states.get(ctx.campaign_id).coin["pp"] == 450
    with pytest.raises(PlayError) as caught:
        characters.update_coin(ctx, "fifty gold")
    assert "+450pp" in caught.value.hint
    assert [e.data["delta"] for e in events(ctx, "coin")] == ["+450pp", "-10SP"]


def test_a_portrait_from_an_old_read_keeps_the_hit_points_taken_since(ctx):
    """A portrait lands from the character as it was read when the painting began; the fight's damage since stays,
    and the portrait stays through the next hit (the sheet and the state are saved apart)."""
    characters.create(ctx, name="Garrek", sheet={**GARREK, "hp_max": 20})
    painted = characters.get(ctx, "Garrek")
    characters.apply_damage(ctx, "Garrek", 5)
    images._set_portrait(ctx.storage, painted, TraitsPortrait("a grim fighter", painted.id))
    stored = characters.get(ctx, "Garrek")
    assert stored.state.hp == 15 and stored.sheet.portrait is not None
    characters.apply_damage(ctx, "Garrek", 1)
    assert characters.get(ctx, "Garrek").sheet.portrait is not None


def test_rest_natural_healing(ctx, monkeypatch):
    """PHB ch. 9 (Natural Healing), as ttrpg2's `rest`, the engine's own rates: 1 hp a day, 3 a day of bed rest plus
    the Constitution bonus for each full week (a warrior's bracketed bonus); the dead don't heal; `full` restores
    everyone living."""
    monkeypatch.setattr(ctx.ruleset, "tables", replace(ctx.rules, healing=Healing()), raising=False)  # not OSRIC's
    characters.create(ctx, name="Garrek", sheet={**GARREK, "hp_max": 40, "ability_scores": {"con": 17}})
    characters.create(ctx, name="Pippa", sheet={"hp_max": 10, "ability_scores": {"con": 16}})
    characters.create(ctx, name="Bones", sheet={"hp_max": 10})
    characters.update(ctx, "Garrek", {"hp": 1})
    characters.update(ctx, "Pippa", {"hp": 1})
    characters.apply_damage(ctx, "Bones", 30)

    out = characters.rest(ctx, days=2)
    assert out["rate_per_day"] == 1 and out["basis"] == "1 hp/day x 2 day(s) (light activity)"
    assert out["healing"]["Garrek"]["hp_after"] == 3 and out["healing"]["Bones"]["hp_after"] == -10
    assert out["still_wounded"] == ["Garrek", "Pippa", "Bones"]

    week = characters.rest(ctx, "Garrek", days=7, bed_rest=True)
    assert week["rested"] == ["Garrek"]
    assert week["healing"]["Garrek"] == {
        "hp_before": 3,
        "hp_after": 27,
        "healed": 24,
        "at_max": False,
        "con_weekly_bonus": 3,
    }
    assert characters.rest(ctx, "Pippa", days=7, bed_rest=True)["healing"]["Pippa"]["hp_after"] == 10

    full = characters.rest(ctx, full=True)
    assert full["healing"]["Garrek"]["at_max"] and full["healing"]["Pippa"]["at_max"]
    assert full["healing"]["Bones"]["hp_after"] == -10, "the DM's override heals the living, never the dead"
    assert "dead" in characters.get(ctx, "Bones").state.conditions
    assert "still_wounded" not in full
    assert len(events(ctx, "rest")) == 4


# --- NPCs --------------------------------------------------------------------------------------------------------


def test_names_deterministic_with_seeded_rng(make_ctx):
    first = [characters.introduce_npc(make_ctx(seed=7), race=race).name for race in ("human", "dwarf", "elf")]
    again = [characters.introduce_npc(make_ctx(seed=7), race=race).name for race in ("human", "dwarf", "elf")]
    other = [characters.introduce_npc(make_ctx(seed=8), race=race).name for race in ("human", "dwarf", "elf")]
    assert first == again and first != other


def test_introduce_npc_logs_event(make_ctx):
    ctx = make_ctx(seed=3)
    npc = characters.introduce_npc(ctx, race="halfling", gender="female", description="innkeeper")
    assert (npc.kind, npc.order, npc.sheet.race, npc.sheet.gender, npc.sheet.background) == (
        "npc",
        None,
        "halfling",
        "female",
        "innkeeper",
    )
    assert npc.name and " " in npc.name
    [event] = events(ctx)
    assert (event.type, event.data) == (
        "npc_met",
        {"character_id": npc.id, "name": npc.name, "race": "halfling", "notes": "innkeeper"},
    )
    assert characters.party(ctx) == []
    assert ctx.storage.rolls.list(ctx.campaign_id) == []  # names come from the dice, not from logged rolls


def test_set_disposition(ctx):
    characters.create(ctx, name="Tira", kind="npc", sheet={})
    out = characters.set_disposition(ctx, "tira", -45, reason="saw the theft")
    assert (out["before"], out["after"], out["band"], out["modifier_applied_to_reaction"]) == (0, -45, "Hostile", -11)
    assert characters.set_disposition(ctx, "Tira", 250)["after"] == 100
    assert characters.get(ctx, "Tira").sheet.disposition == 100
    assert events(ctx, "disposition_change")[0].data["notes"] == "saw the theft"
    characters.create(ctx, name="Garrek", sheet={})
    with pytest.raises(PlayError):
        characters.set_disposition(ctx, "Garrek", 10)


# --- the context and the transaction -----------------------------------------------------------------------------


def test_context_for(storage, campaign):
    ctx = context_for(storage, campaign.id, "beat-9", ScriptedRng([4]), catalogs=over(PlayReference()))
    assert (ctx.campaign_id, ctx.beat, ctx.dice.beat, ctx.dice.campaign_id) == (
        campaign.id,
        "beat-9",
        "beat-9",
        campaign.id,
    )
    roll = ctx.dice.d(6, purpose="test")
    assert storage.rolls.list(campaign.id) == [roll]  # the dice log to storage
    storage.campaign_states.put(CampaignState(campaign.id, session=4))
    event = ctx.log("log", text="The bell tolls.")
    assert (event.session, event.beat, event.data) == (4, "beat-9", {"text": "The bell tolls."})
    with pytest.raises(NotFound):
        context_for(storage, "cmp_000000000000", "beat-1", catalogs=over(PlayReference()))


def test_a_failed_call_leaves_nothing(make_ctx):
    """Review Focus 3, one level up: a service call inside a transaction that fails halfway leaves no character,
    event or roll."""
    ctx = make_ctx(15)
    with pytest.raises(RuntimeError), ctx.storage.transaction():
        characters.create(ctx, name="Garrek", sheet=GARREK)
        characters.update_coin(ctx, "+50gp")
        ctx.dice.d(20, purpose="save:spell", actor="chr_garrek00000")
        raise RuntimeError("the next write fails")
    assert ctx.storage.characters.list(ctx.campaign_id) == []
    assert events(ctx) == [] and ctx.storage.rolls.list(ctx.campaign_id) == []
    assert ctx.storage.campaign_states.get(ctx.campaign_id).coin["gp"] == 0

