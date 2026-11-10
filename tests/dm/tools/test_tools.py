"""The DM's tools (plan 2a Task 11): the capabilities the feature review keeps, and how the tools join the play
services: house rules in their results, combatants in the checks, the composites."""

import pytest

from delve.play.house_rules import set_campaign_house_rules
from tests.fixtures.homebrew import seed_with_homebrew

# Every ttrpg2 tool (its MCP surface, tools/*.py), and where its capability is in Delve. The feature review
# (docs/review/feature-review.md) keeps every tool it doesn't cut; a kept capability may be merged or reshaped.
IN_2A = {
    # campaign_mgmt
    "add_character": "create_character",
    # combat
    "start_combat": "setup_combat",
    "add_combatant": "add_combatant",
    "roll_initiative": "combat_round",  # rolled each round by combat_round, round 1 by setup_combat
    "declare_spell": "combat_round",  # a {caster, spell} action; round 1's in setup_combat's spells
    "attack": "resolve_attack",
    "apply_combat_damage": "apply_damage",
    "apply_combat_heal": "apply_heal",
    "add_condition": "add_condition",
    "remove_condition": "remove_condition",
    "apply_effect": "apply_effect",
    "remove_effect": "remove_effect",
    "next_turn": "combat_round",  # the turn pointer is gone: a round resolves whole
    "combat_status": "combat_status",
    "end_combat": "end_combat",
    "setup_combat": "setup_combat",
    "resolve_attack": "resolve_attack",
    "combat_round": "combat_round",
    # composites and dice
    "batch": "batch",
    "roll": "roll",
    "reaction": "reaction",
    "morale_check": "morale_check",
    "check_encounter": "encounter_check",
    "determine_encounter": "encounter_check",
    "surprise_check": "surprise_check",
    "saving_throw": "saving_throw",
    "system_shock": "system_shock",
    "resurrection_check": "resurrection_check",
    "skill_check": "skill_check",
    "scout": "scout",
    "council": "council",
    # dungml_play: the map updates through the moves themselves
    "dungml_status": "room",
    "dungml_locales": "move_party",  # an unknown map answers with the module's maps
    "dungml_use_locale": "move_party",  # map=
    "dungml_rooms": "room",
    "dungml_reveal": "door",  # a secret door found; rooms are revealed by moving into them
    # log
    "log_note": "log_note",
    "new_session": "new_session",
    "advance_calendar": "advance_time",
    "advance_time": "advance_time",
    "set_time": "set_time",
    # lookup
    "monster_lookup": "monster_lookup",
    "spell_lookup": "spell_lookup",
    "class_lookup": "class_lookup",
    "generate_treasure": "generate_treasure",
    "award_treasure": "award_treasure",
    "loot_pile": "loot_pile",
    "claim_loot": "claim_loot",
    "item_lookup": "item_lookup",
    "ability_lookup": "ability_lookup",
    "proficiency_lookup": "proficiency_lookup",
    "proficiency_groups": "proficiency_lookup",
    "turning_undead": "turning_undead",
    # lore
    "session_primer": "session_primer",
    # party
    "party_status": "party_status",
    "set_marching_order": "set_marching_order",
    "character_status": "get_character",
    "apply_damage": "apply_damage",
    "apply_heal": "apply_heal",
    "memorize_spells": "memorize_spells",
    "cast_spell": "cast_spell",
    "spell_status": "spell_status",
    "use_spell_slot": "cast_spell",  # slots are structured: a spell is cast, not a slot spent
    "rest": "rest",
    "award_xp": "award_xp",
    "update_coin": "update_coin",
    # rooms and rules
    "move_party": "move_party",
    "room": "room",
    "door": "door",
    "note_room": "note_room",
    "rules_lookup": "rules_lookup",
    "rules_section": "rules_section",
    # secrets
    "dm_note": "dm_note",
    "dm_secrets": "dm_secrets",
    "dm_secret_update": "dm_secret_update",
    # survival: inventory and encumbrance stay (feature review, "Keep, changed")
    "add_inventory": "add_item",
    "inventory": "inventory",
    "transfer": "transfer",
    "encumbrance": "encumbrance",
    # world
    "introduce_npc": "introduce_npc",
    "set_npc_stats": "update_character",
    "update_stats": "update_character",
    "quick_npc": "create_character",
    "set_disposition": "set_disposition",
    "get_character": "get_character",
    "update_character": "update_character",
    "list_characters": "party_status",
}

# Kept, and built in plateau 6 (plan 6). The season is derived from the date, so set_season becomes calendar.
IN_6 = {
    # the magic merchant (plan 6 Task 9)
    "magic_merchant": "magic_merchant",
    "buy_magic_item": "buy_magic_item",
    # greyhawk: the setting's wiki, through the campaign's setting
    "greyhawk_metadata": "setting_lookup",  # an unknown kind answers with the kinds
    "greyhawk_category": "setting_lookup",
    "greyhawk_lookup": "setting_lookup",  # one hit brings its page
    "greyhawk_search": "setting_search",
    # lore and lore facts: the setting's facts are the reference's, read-only; a campaign's own are its table's
    "add_campaign_fact": "add_fact",
    "list_lore_facts": "facts",
    "search_lore": "search_campaign",
    # days and the weather (plan 6 Task 4)
    "set_season": "calendar",
    "weather_check": "weather_check",
    "current_weather": "weather_check",  # rolled once a day, so asking again answers today's
    "list_terrains": "weather_check",  # an unknown terrain is refused with the terrains
    # Factions and clocks (plan 6 Task 5): one update tool, and the clocks tick with the days.
    "add_faction": "update_faction",  # an unknown id with a name makes the faction
    "set_faction": "update_faction",
    "change_reputation": "update_faction",  # reputation_change
    "list_factions": "factions",
    "add_faction_clock": "add_clock",
    "list_clocks": "clocks",
    "remove_clock": "remove_clock",
    "tick_world": "advance_days",  # every new day ticks the countdowns
    "add_quest": "add_quest",
    "update_quest": "update_quest",
    "complete_quest": "update_quest",  # status complete, with a note
    "fail_quest": "update_quest",
    "quest_status": "quests",
    "active_quests": "quests",  # status active
    # holdings (Task 6): houses and mounts are one kind of thing, a possession
    "add_house": "add_possession",
    "list_houses": "possessions",
    "get_house": "possession",
    "update_house": "update_possession",
    "add_mount": "add_possession",
    "list_mounts": "possessions",
    "get_mount": "possession",
    "update_mount": "update_possession",
    # world maps and travel (Task 8): the campaign's own copies, the party's one place on them
    "travel": "travel",
    "get_world_map": "world_map",
    "list_world_maps": "world_map",  # its answer lists the campaign's maps
    "list_world_map_views": "world_map",
    "place_party_on_map": "place_party",
    "world_map_distance_direct": "distance",
    "world_map_distance_via_roads": "distance",  # one answer, both distances
    "world_map_nearest": "nearest",
    "add_world_map_feature": "add_place",  # plan 7 Task 9: the DM adds a place; editing the map is the organiser's
}

# Kept, but in the app rather than among the DM's tools: campaigns are made and maps viewed in Delve itself.
IN_THE_APP = {
    "create_campaign",
    "list_campaigns",
    "close_campaign",
    "switch_campaign",
    "campaign_info",
    "dungml_view",  # the two map routes, fog view and DM view
    "refresh_sheet",  # sheets are data, drawn by the web app
    "scenario_import",  # POST /api/modules/import
    "random_lore_facts",  # GET /api/campaigns/{id}/lore/random, the play screen's "Did you know"
    "compile_world_map_view",  # the world-map view routes cut it on the server
    # plan 7 Task 11: the organiser makes and edits the world maps, in the world-map editor
    "create_world_map",
    "update_world_map",
    "remove_world_map_feature",
}

# Kept, and built in 2b: the module's text for the DM, unpacked from the .dscn on import.
IN_2B = {
    "module_lookup": "module_lookup",
    "module_key": "module_key",
}

# Kept, for a later plateau (spec §14).
DEFERRED = {
    "pre_turn_check": "2b",  # its evals decide whether it comes back (spec §6.3)
    "scenario_export": "3",
    "set_character_location": "6",
    "item_update": "6",  # the reference is read-only; rarities matter for the magic merchant
    "random_words": "6",
    **dict.fromkeys(
        [
            "regenerate_house_portrait",
            "regenerate_mount_portrait",
            "generate_scene",
            "generate_portrait",
            "regenerate_portrait",
            "add_lore_fact",
            "update_lore_fact",
            "delete_lore_fact",
            "npc_history",
            "location_history",
            "party_timeline",
            "create_area",
            "create_location",
            "update_location",
            "get_location",
            "list_locations",
        ],
        "6",
    ),
}

# Cut by the feature review: they must not come back.
CUT = {
    "stronghold",
    "stronghold_staff",
    "pay_staff",
    "stronghold_work",
    "pay_work",
    "stronghold_feature",
    "stronghold_obligation",
    "settle_obligation",
    "settle_rations",
    "consume",
    "light_torch",
    "extinguish_light",
    "light_state",
    "hire",
    "loyalty_check",
    "adjust_loyalty",
    "add_rumor",
    "gossip",
    "list_rumors",
    "audit_session",
    "create_map",
    "place_combatant",
    "get_map_state",
}

# New in Delve, for capabilities the feature review reshaped: one inventory, structured spell loadouts, sessions
# with recaps, house rules; the module's images shown to the players (plan 3 Task 8); and narration for some
# characters (plan 4 Task 5).
NEW = {
    "race_lookup",
    "show_image",
    "tell",
    "ability_check",
    "remove_item",
    "set_spell_loadout",
    "end_session",
    "house_rules",
    "remove_combatant",
    "adjudicate",
    "advance_days",
    "advance_clock",
    "portrait",  # plan 6 Task 10: ttrpg2's generate_portrait and regenerate_*_portrait, for characters and possessions
    "paint_scene",  # plan 6 Task 10: ttrpg2's generate_scene, painted in the background
    "remove_possession",
    "reveal_place",  # plan 6 Task 8: a hidden place of a world map becomes the players'
    "hide_place",  # plan 7 Task 9: the party forgets a place or a road
    "reveal_area",  # plan 7 Task 9: the party learns (or forgets) the land around a place
    "route",  # plan 7 Task 10: the way a leg would take by a mode, without travelling
    "module_pregens",  # faithful modules Task 19: the module's pregenerated characters, with the sheets they make
    "propose_page",  # settings Task 7: a new page of the setting, or an edit, for an organiser to accept
    "propose_fact",  # settings Task 7: a lasting fact of the setting, for an organiser to accept
    "say",  # portraits Task 7: an NPC's line, its own story entry with the speaker and the mood
    "leave_party",  # table voice and fixes Task C2: a PC died, retired or left
    "rejoin_party",  # table voice and fixes Task C2: a departed PC comes back
    "interrupt",  # table voice and fixes Task B1.3: break a combatant's ongoing action
    "drain_level",  # DEL-320: an energy drain takes a level, with its hit points, XP, THAC0, saves and slots
    "session_summary",  # DEL-328: what the session recorded, to write its whole recap from
    "throw_missile",  # DEL-333: a flask of oil or a vial of holy water, thrown
    "update_combatant",  # DEL-333: a combatant's numbers as the module or a ruling says
}


def test_tool_names_cover_feature_review(host):
    """Every ttrpg2 tool is accounted for once: in 2a's or 2b's tools, in the app, deferred to a plateau, or cut. Every kept
    capability of 2a has its tool, no cut tool exists, and the feature review's reshaped capabilities are there:
    inventory and encumbrance, structured spell loadouts, the marching order, batch, and rules lookup by ruleset."""
    groups = [set(IN_2A), set(IN_2B), set(IN_6), IN_THE_APP, set(DEFERRED), CUT]
    every = set().union(*groups)
    assert sum(len(g) for g in groups) == len(every), "a ttrpg2 tool is in two groups"
    assert len(every) == 190, "ttrpg2 has 190 tools"
    names = {spec.name for spec in host.specs()}
    assert set(IN_2A.values()) | set(IN_2B.values()) | set(IN_6.values()) | NEW == names
    assert not CUT & names
    kept_changed = {"add_item", "remove_item", "transfer", "inventory", "encumbrance"}
    kept_changed |= {"set_spell_loadout", "memorize_spells", "cast_spell", "spell_status", "set_marching_order"}
    assert kept_changed | {"batch"} <= names
    assert "ruleset" not in host.spec("rules_lookup").params["properties"]  # the campaign's own, always


# --- house rules in the results (spec §9) ------------------------------------------------------------------------


@pytest.fixture
def table(storage, campaign):
    """The campaign plays with the seed bundle, "My table (from ttrpg2)", with homebrew (`tests.fixtures.homebrew`)."""
    bundle = seed_with_homebrew(storage)
    set_campaign_house_rules(storage, campaign.id, bundle_ids=[bundle.id], rule_ids=[])
    return bundle


def test_create_character_returns_creation_rules(call, table):
    out = call("create_character", name="Ssth", sheet={"race": "Lizardfolk", "cls": "Fighter", "hp_max": 9})
    titles = [r["title"] for r in out["house_rules"]]
    assert "Roll 4D6 for abilities" in titles and "Characters start at maximum HP for level 1" in titles
    assert any(r["subject"] == "lizardfolk" for r in out["house_rules"])
    assert all("character-creation" in r["phases"] for r in out["house_rules"])


def test_create_character_name_is_optional(host, call):
    """A PC the DM makes up is named by the dice; a name the player or the book gives is kept (Features 18)."""
    [spec] = [spec for spec in host.specs() if spec.name == "create_character"]
    assert "name" in spec.params["properties"] and "name" not in spec.params["required"]
    rolled = call("create_character", sheet={"race": "elf", "gender": "female", "cls": "Mage", "hp_max": 4})
    assert rolled["named_by"] == "dice" and rolled["name"].strip()
    given = call("create_character", name=" Brother Anselm", sheet={"race": "human", "hp_max": 8})
    assert (given["named_by"], given["name"]) == ("given", "Brother Anselm")


def test_add_item_and_item_lookup_return_item_rules(call, party, table):
    added = call("add_item", character="Garrek", item="Shrinking Blade")
    assert [r["subject"] for r in added["house_rules"]] == ["shrinking-blade"]
    assert call("add_item", character="Garrek", item="Long sword")["house_rules"] == []
    looked = call("item_lookup", name="shrinking blade")
    # Given whole by add_item in this beat, the rule comes by name only now (DEL-79).
    assert [(r["title"], r["given"]) for r in looked["house_rules"]] == [
        (added["house_rules"][0]["title"], "whole earlier in this beat")
    ]


def test_award_xp_brings_level_up_rules(call, party, table):
    out = call("award_xp", character="Garrek", amount=2000)
    assert out["level_up_hints"] and {r["title"] for r in out["house_rules"]} >= {"Ignore level caps"}


def test_house_rules_tool_by_phase_and_query(call, table):
    always = call("house_rules")
    assert always["phase"] is None
    levels = call("house_rules", phase="level-up")
    assert {r["title"] for r in levels["rules"]} >= {"Players can opt to reroll HP once", "Ignore level caps"}
    found = call("house_rules", phase="items", query="tyr")
    assert [r["subject"] for r in found["rules"]] == ["hand-of-tyr"]
    assert call("house_rules", phase="sometimes")["error"].startswith("Bad arguments")


# --- checks and damage for anyone in the fight -------------------------------------------------------------------


def test_saving_throw_and_damage_take_combatants(call, party):
    call("move_party", to="Entry Hall")
    call("setup_combat", enemies=[{"name": "goblin", "count": 2, "hp": 5}])
    save = call("saving_throw", character="mon_2", save_type="para")
    assert save["basis"] == "monster: HD 1d8-1 hit points saves as intelligent 0" and save["round"] == 1
    hit = call("apply_damage", character="Goblin 1", amount=2)
    assert (hit["id"], hit["hp_after"]) == ("mon_1", 3)
    healed = call("apply_heal", character="mon_1", amount=1)
    assert healed["hp_after"] == 4
    garrek = call("apply_damage", character="Garrek", amount=4)
    assert garrek["in_combat"] and garrek["hp_after"] == 6
    ambiguous = call("apply_damage", character="Goblin", amount=1)
    assert ambiguous["error"].startswith("No character 'Goblin'")


def test_resurrection_check_costs_a_point_of_constitution(call, party):
    out = call("resurrection_check", character="Garrek")
    assert (out["con_before"], out["con_after"]) == (15, 14)
    assert call("get_character", ref="Garrek")["sheet"]["ability_scores"]["con"] == 14


def test_rules_lookup_searches_the_campaigns_own_ruleset(host, storage, campaign):
    out = host.call(campaign.id, "beat-1", "rules_lookup", {"query": "surprise"})
    assert out["ruleset"] == "osric" and out["count"] >= 1
    missing = storage.campaigns.create(
        "Elsewhere", campaign.module_id, campaign.revision, ruleset="no-such-rules", setting="greyhawk"
    )
    out = host.call(missing.id, "beat-1", "rules_lookup", {"query": "surprise"})
    assert out["error"] == "This campaign's ruleset, no-such-rules, isn't installed."


# --- scout and council, as ttrpg2's ------------------------------------------------------------------------------


def test_scout_rolls_skills_then_encounter_then_time(call, party, storage, campaign):
    out = call("scout", character="Pippa", checks=["move silently", "climb walls"], minutes=10)
    move, climb = out["checks"]
    assert move["skill"] == "move_silently" and move["needed"] == 25
    assert climb["error"] == "Skill 'climb walls' not found for Pippa."  # reported, never substituted
    assert out["encounter"]["terrain"] == "dungeon" and out["time"]["time"] == "06:10"
    purposes = [r.key.purpose for r in storage.rolls.list(campaign.id)]
    assert purposes[:2] == ["skill:move_silently#scout, day 1 06:00", "encounter:check#day 1 06:00"]
    # the next scouting move in the beat, ten minutes later, rolls its own (review D-b)
    call("scout", character="Pippa", checks=["move silently"], minutes=10)
    purposes = [r.key.purpose for r in storage.rolls.list(campaign.id)]
    assert purposes[-2:] == ["skill:move_silently#scout, day 1 06:10", "encounter:check#day 1 06:10"]


def test_council_rolls_one_reaction_per_npc(call, party):
    call("set_disposition", npc="Tira", value=45)
    out = call(
        "council",
        npcs=[{"npc": "Tira", "modifier": -4, "interest": "the relic leaves her temple"}, "Nobody"],
        base_modifier=1,
    )
    tira, nobody = out["votes"]
    assert tira["modifier_applied"] == -3 and tira["interest"] == "the relic leaves her temple"
    assert tira["reaction"]["disposition_applied"] == 11 and tira["reaction"]["modifier"] == 8  # OSRIC: 45 / 4
    assert nobody["reaction"]["error"] == "No character 'Nobody'."
    assert out["count"] == 1 and out["attitudes"] == [tira["reaction"]["result"]] and out["unanimous"]
    assert call("council", npcs=[])["error"].startswith("npcs must be")


def test_a_monster_lookup_gives_three_whole_and_names_the_rest(call):
    """DEL-79: "rat" answered ten whole entries, 45 KB. The best three come whole; `also` names the others."""
    out = call("monster_lookup", name="rat")
    assert out["count"] > 3 and len(out["monsters"]) == 3
    assert "rat" in out["monsters"][0]["name"].lower().split()  # "Giant rat (big)": names as players say them (DEL-325)
    assert len(out["also"]) == out["count"] - 3 and all(isinstance(name, str) for name in out["also"])
    whole = call("monster_lookup", name=out["also"][0])
    assert whole["monsters"][0]["name"] == out["also"][0], "a name in also looks its entry up"


def test_house_rules_come_whole_once_a_beat(host, campaign, table):
    """DEL-79: making a party gave every character the same creation rules, 18 KB each. A beat's first result gives
    each rule whole, the next ones by name; another beat, or the same beat run again (Retry), gives them whole."""
    from delve.play.house_rules import forget_beat

    def make(name, beat):
        sheet = {"race": "Human", "cls": "Fighter", "hp_max": 9}
        return host.call(campaign.id, beat, "create_character", {"name": name, "sheet": sheet})["house_rules"]

    first = make("Garrek", "beat-7")
    assert first and all("body_md" in rule for rule in first)
    again = make("Garrick", "beat-7")
    assert [(r["id"], r["given"]) for r in again] == [(r["id"], "whole earlier in this beat") for r in first]
    assert all("body_md" in rule for rule in make("Garth", "beat-8"))
    forget_beat(campaign.id, "beat-7")
    assert all("body_md" in rule for rule in make("Gareth", "beat-7"))


def test_add_item_keeps_the_dms_notes_apart(call, party):
    """DEL-181: `dm_notes` are what only the DM knows of an item; the item's `notes` are the players'."""
    out = call("add_item", character="Garrek", item="Glass phial", notes="cloudy", dm_notes="neutralize poison")
    assert (out["item"]["notes"], out["item"]["dm_notes"]) == ("cloudy", "neutralize poison")
    again = call("add_item", character="Garrek", item="Glass phial")
    assert again["item"]["qty"] == 2 and again["item"]["dm_notes"] == "neutralize poison", "kept when more are added"


def test_roll_takes_its_actor(call, party, storage):
    """DEL-274: a PC's own roll is logged as theirs, by id or exact name; an unknown one names the characters."""
    garrek = party[0]["id"]
    out = call("roll", notation="3d20", purpose="Garrek wrestling", actor="Garrek")
    (logged,) = [r for r in storage.rolls.list(storage.campaigns.list()[0].id) if r.id == out["id"]]
    assert logged.key.actor == garrek
    assert "error" in call("roll", notation="1d6", purpose="x", actor="Nobody")
    mine = call("roll", notation="1d6", purpose="the DM's own")
    assert next(r for r in storage.rolls.list(storage.campaigns.list()[0].id) if r.id == mine["id"]).key.actor is None
