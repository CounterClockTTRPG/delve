"""Every DM tool in an SRD 3.5 campaign (DEL-388, I7): each core tool the tool host lists for srd35, and the pack's
own, called at least once with sane arguments through the host, with the tripwire on, and the web's character page.
A refusal is an answer; an uncaught exception is the failure this looks for (the empty carrying tables, the surprise
die of 0, a per-day cast without its caster all raised or refused here before)."""

from __future__ import annotations

import itertools

FIGHTER = {"str": 16, "dex": 13, "con": 14, "int": 10, "wis": 12, "cha": 8}
CLERIC = {"str": 14, "dex": 10, "con": 14, "int": 10, "wis": 15, "cha": 12}
WIZARD = {"str": 8, "dex": 16, "con": 10, "int": 17, "wis": 12, "cha": 10}

SKIPPED: dict[str, str] = {}
"""Tools not called, each with why: none, every tool srd35 lists is called."""

REFUSALS_EXPECTED = {
    "surprise_check": "3.5 has no surprise roll",
    "morale_check": "3.5 has no morale check",
    "reaction": "3.5 has no reaction roll",
    "council": "3.5 has no reaction roll",
}
"""Tools whose refusal is the 3.5 answer, by the start of it."""


ANSWERED = (
    "session_primer", "encumbrance", "inventory", "party_status", "get_character", "set_build", "setup_combat",
    "combat_round", "resolve_attack", "add_combatant", "update_combatant", "provoke", "end_combat", "saving_throw",
    "skill_check", "turning_undead", "memorize_spells", "spell_status", "award_xp", "update_character", "rest",
    "drain_level",
)  # fmt: skip
"""Tools that must answer without a refusal: the ones a 3.5 session lives on."""


def _session(call) -> None:
    """The calls, in the order a session might make them."""

    def pc(name, cls, race, hp, scores):
        call("create_character", name=name, sheet={"cls": cls, "level": 1, "race": race, "hp_max": hp,
                                                   "ability_scores": scores})  # fmt: skip

    pc("Bram", "Fighter", "Human", 12, FIGHTER)
    pc("Dorna", "Cleric", "Dwarf", 10, CLERIC)
    pc("Elowen", "Wizard", "Elf", 4, WIZARD)
    call("set_build", character="Bram", feats=["power attack"], weapon="longsword", armor="chain mail",
         shield="heavy steel shield")  # fmt: skip
    call("set_build", character="Dorna", domains=["war", "good"], weapon="warhammer", armor="scale mail")
    call("set_build", character="Elowen", weapon="dagger")

    # The session's start, the books and the campaign's notes.
    call("new_session", title="One")
    call("session_primer")
    call("rules_lookup", query="attack of opportunity")
    call("rules_section", source="carrying-movement-and-exploration", section="Carrying Capacity")
    call("monster_lookup", name="orc")
    call("spell_lookup", name="sleep", caster="wizard")
    call("item_lookup", name="bag of holding")
    call("class_lookup", class_name="fighter", level=2)
    call("race_lookup", race="elf")
    call("ability_lookup", ability="str", score="16")
    call("proficiency_lookup", name="longsword")
    call("setting_lookup", kind="deity", query="pelor")
    call("setting_search", query="greyhawk")
    call("add_fact", text="The crypt is old.")
    call("facts", query="crypt")
    call("propose_page", title="The Crypt", text="An old crypt.")
    call("propose_fact", text="The crypt has a vestry.")
    call("search_campaign", query="crypt")
    call("house_rules")

    # Checks.
    call("roll", notation="1d20", purpose="a test")
    call("saving_throw", character="Bram", save_type="fort", dc=12)
    call("skill_check", character="Bram", skill="climb", dc=10)
    call("ability_check", character="Bram", ability="str")
    call("surprise_check")
    call("morale_check", rating=8)
    call("encounter_check", terrain="dungeon", level=1)
    call("system_shock", character="Bram")
    call("resurrection_check", character="Bram")
    call("scout", character="Bram")
    call("turning_undead", level=1, undead="human warrior skeleton", character="Dorna")

    # Characters and NPCs.
    call("get_character", ref="Bram")
    call("update_character", ref="Bram", patch={"background": "A soldier."}, reason="backstory")
    npc = call("introduce_npc", race="human", gender="male", description="innkeeper")
    npc_name = npc.get("name", "the innkeeper")
    call("set_disposition", npc=npc_name, value=2, reason="a good tip")
    call("reaction", npc=npc_name)
    call("say", npc=npc_name, text="Welcome.")
    call("council", npcs=[npc_name])
    call("party_status")
    call("set_marching_order", order=["Bram", "Dorna", "Elowen"])
    call("leave_party", character="Elowen", reason="left")
    call("rejoin_party", character="Elowen")
    call("portrait", of="Bram")
    call("tell", characters=["Bram"], text="You hear a whisper.")

    # Gear and coin.
    call("update_coin", delta="+50gp")
    call("add_item", character="Bram", item="rope", qty=1)
    call("add_item", character="Bram", item="torch", qty=2)
    call("transfer", item="torch", qty=1, source="Bram", dest="Dorna")
    call("remove_item", character="Dorna", item="torch", qty=1)
    call("inventory", character="Bram")
    call("encumbrance", character="Bram")
    call("add_possession", name="The Cottage", kind="house", owner="Bram")
    call("update_possession", id="The Cottage", notes="Draughty.")
    call("possessions")
    call("possession", id="The Cottage")
    call("remove_possession", id="The Cottage")
    call("magic_merchant", merchant="Old Tam")
    call("buy_magic_item", merchant="Old Tam", item="potion of cure light wounds", character="Bram")

    # Spells.
    call("set_spell_loadout", character="Elowen", known={"1": ["Sleep", "Magic Missile"]}, default={"1": ["Sleep"]})
    call("memorize_spells", character="Elowen", spells=["Sleep", "Magic Missile"])
    call("memorize_spells", character="Dorna", spells=["Bless", "Cure Light Wounds", "Magic Weapon"])
    call("cast_spell", character="Elowen", spell_name="Magic Missile")
    call("cast_spell", character="Bram", spell_name="Sleep")
    call("spell_status", character="Elowen")

    # The map.
    call("place_party", at="Greyhawk")
    call("move_party", to="room.entry_hall")
    call("room")
    call("door", door="entry_hall")
    call("note_room", text="Dust everywhere.")
    call("module_lookup", query="crypt")
    call("module_key", room="entry_hall")
    call("read_aloud", room="entry_hall", speaker=npc_name)
    call("module_pregens")
    call("show_image", asset="crypt.png")
    call("paint_scene", brief="The crypt's door.")
    call("distance", a="Greyhawk", b="Dyvers")
    call("nearest", kind="city")
    call("world_map")
    call("reveal_place", feature="Dyvers")
    call("hide_place", feature="Dyvers")
    call("reveal_area", at="Greyhawk", radius_km=10)
    call("add_place", name="The Old Mill", kind="ruin", at="Greyhawk")
    call("route", to="Dyvers")
    call("travel", to="Dyvers", mode="foot")

    # The fight.
    call("setup_combat", enemies=[{"name": "orc", "count": 2}, {"name": "human warrior skeleton", "count": 1}])
    call("combat_status")
    call("combat_round", actions=[
        {"attacker": "Bram", "target": "Orc 1"},
        {"caster": "Elowen", "spell": "Sleep", "target": "Orc 2"},
        {"attacker": "Orc 1", "target": "Dorna"},
    ])  # fmt: skip
    call("resolve_attack", attacker="Dorna", target="Orc 1")
    call("throw_missile", thrower="Elowen", target="Orc 2", missile="oil")
    call("update_combatant", id="Orc 2", stats={"hp": 3}, ac=15)
    call("add_combatant", name="ghoul", count=1)
    call("apply_effect", target="Bram", name="bless", duration=10, to_hit=1, source="Dorna")
    call("remove_effect", target="Bram", name="bless")
    call("add_condition", name="Orc 2", condition="flat-footed")
    call("remove_condition", name="Orc 2", condition="flat-footed")
    call("adjudicate", note="The orc slips on the wet stone.")
    call("interrupt", combatant="Elowen", reason="jostled")
    call("set_stance", combatant="Bram", power_attack=1)
    call("provoke", provoker="Orc 1", threatened_by=["Bram"])
    call("remove_combatant", id="Ghoul", reason="fled")
    call("end_combat")

    # After the fight.
    call("generate_treasure", treasure_types="A")
    call("award_treasure", treasure_types="A")
    call("loot_pile")
    call("claim_loot", index=0, character="Bram")
    call("apply_damage", character="Elowen", amount=3)
    call("apply_heal", character="Elowen", amount=2)
    call("award_xp", character="Bram", amount=1000)
    call("update_character", ref="Bram", patch={"level": 2}, reason="2nd level")
    call("rest", days=1, bed_rest=True)
    call("drain_level", character="Bram", levels=1, reason="a wight")

    # The DM's notes, the world and time.
    note = call("dm_note", text="The ghoul serves the ritualist.", tags=["ghoul"])
    call("dm_secrets", tag="ghoul")
    call("dm_secret_update", secret_id=note.get("id", "x"), revealed=True)
    call("log_note", text="A hard fight.")
    call("factions")
    call("update_faction", id="the-ritualists", name="The Ritualists", reputation_change=-1)
    clock = call("add_clock", label="The ritual", segments=4)
    clock_id = clock.get("clock", {}).get("id", 0)
    call("advance_clock", id=clock_id, segments=1)
    call("clocks")
    call("remove_clock", id=clock_id)
    call("add_quest", id="crypt", title="Clear the crypt")
    call("update_quest", id="crypt", note="The ghoul fled.")
    call("quests")
    call("advance_time", minutes=10)
    call("set_time", hour=18)
    call("advance_days", days=1)
    call("weather_check", terrain="plains")
    call("calendar")
    call("batch", steps=[{"tool": "party_status", "args": {}}, {"tool": "calendar", "args": {}}])
    call("session_summary")
    call("end_session", recap="The party cleared the entry hall.")


def test_every_dm_tool_answers_in_an_srd35_campaign(srd35_tripwire, srd35_host, srd35_storage, srd35_campaign):
    from delve.dice import SeededRng
    from delve.play.context import context_for
    from delve.web.routes.characters import character_json
    from tests.fixtures.rulesets import srd35_catalogs

    listed = {spec.name for spec in srd35_host.specs("srd35")}
    beats = itertools.count(1)
    called: set[str] = set()
    raised: list[str] = []
    answers: dict[str, list[dict]] = {}

    def call(tool, /, **args):
        assert tool in listed, f"{tool} isn't a tool of srd35"
        called.add(tool)
        try:
            out = srd35_host.call(srd35_campaign.id, f"beat-{next(beats)}", tool, args)
        except Exception as error:  # noqa: BLE001 - what this test looks for
            raised.append(f"{tool} {args}: {type(error).__name__}: {error}")
            return {}
        answers.setdefault(tool, []).append(out)
        return out

    _session(call)
    assert raised == []
    assert listed - set(SKIPPED) - called == set()
    for tool, said in REFUSALS_EXPECTED.items():
        assert all(out.get("error", "").startswith(said) for out in answers[tool]), (tool, answers[tool])
    ctx = context_for(srd35_storage, srd35_campaign.id, "beat-web", SeededRng(1), catalogs=srd35_catalogs())
    for character in srd35_storage.characters.list(srd35_campaign.id):
        page = character_json(character, ctx)
        assert character.kind != "pc" or ("encumbrance" in page and "d20" in page["sheet"]), page
    for tool in ANSWERED:
        assert all("error" not in out for out in answers[tool]), (tool, answers[tool])
