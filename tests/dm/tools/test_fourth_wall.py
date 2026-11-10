"""The fourth wall in tool results (plan 2a Task 12, Review Focus 4; spec §7.5): what the players' feed may show of a
tool result is built by `redact.player_view`, an allow-list. A secret planted in DM-only data never reaches a
perceived field or a player view."""

import json

import pytest

from delve.dm.tools.redact import player_view
from delve.play.table import set_play_settings
from delve.play.timeline import timeline_for
from tests.dm.tools.conftest import SECRET

DM_ONLY_TOOLS = {
    "dm_note",
    "dm_secrets",
    "dm_secret_update",
    "encounter_check",
    "note_room",
    "room",
    "generate_treasure",
    "session_primer",
    "session_summary",
    "module_lookup",
    "module_key",
    "module_pregens",
    "add_fact",
    "propose_page",
    "propose_fact",
    "facts",
    "search_campaign",
    "factions",
    "update_faction",
    "add_clock",
    "advance_clock",
    "remove_clock",
    "clocks",
    "quests",
    "possession",
    "world_map",
    "add_place",
    "hide_place",
    "reveal_area",
    "route",
}

# A hidden place added to Greyhawk's region map (km from its top left, east of the Free City), its description and DM
# notes planted: the players' map leaves it out.
HIDDEN_PLACE = {
    "name": "Lich Tower",
    "kind": "ruin",
    "at": "200,160",
    "description": SECRET,
    "notes": f"{SECRET}: the lich sleeps.",
    "hidden": True,
    "map": "greyhawk-region",
}

CORWIN = {"race": "Elf", "cls": "Mage", "level": 1, "hp_max": 4, "ac": 10, "thac0": 20, "spell_slots": {"1": 1}}
PONY = {"hp_max": 9, "thac0": 19}
"""A pony's stats, given: OSRIC has no mount defaults."""

# One call of every tool the players may see, and of every tool that returns `perceived`, in an order that makes
# each of them succeed: lookups, checks, characters, inventory, spells, treasure, the map, a fight, notes and time.
SESSION = [
    ("rules_lookup", {"query": "surprise"}),
    ("rules_section", {"source": "pg", "section": "Surprise"}),
    ("monster_lookup", {"name": "goblin"}),
    ("spell_lookup", {"name": "sleep"}),
    ("item_lookup", {"name": "long sword"}),
    ("class_lookup", {"class_name": "fighter", "level": 1}),
    ("race_lookup", {"race": "elf"}),
    ("ability_lookup", {"ability": "str", "score": "16"}),
    ("proficiency_lookup", {"group": "warrior"}),
    ("turning_undead", {"level": 3, "undead": "skeleton"}),
    ("setting_lookup", {"kind": "place", "query": "Hardby"}),
    ("setting_search", {"query": "Circle of Eight"}),
    ("roll", {"notation": "1d20", "purpose": "the lever"}),
    ("saving_throw", {"character": "Garrek", "save_type": "spell"}),
    ("skill_check", {"character": "Pippa", "skill": "move silently"}),
    ("ability_check", {"character": "Garrek", "ability": "str"}),
    ("reaction", {"npc": "Tira"}),
    ("morale_check", {"rating": 10}),
    ("surprise_check", {}),
    ("encounter_check", {"terrain": "dungeon"}),
    ("system_shock", {"character": "Garrek"}),
    ("resurrection_check", {"character": "Pippa"}),
    ("create_character", {"name": "Corwin", "sheet": CORWIN}),
    ("get_character", {"ref": "Tira"}),
    ("update_character", {"ref": "Tira", "patch": {"background": "the innkeeper"}}),
    ("introduce_npc", {"race": "human", "description": "a guard"}),
    ("set_disposition", {"npc": "Tira", "value": 20}),
    ("party_status", {}),
    ("set_marching_order", {"order": ["Pippa", "Garrek"]}),
    ("leave_party", {"character": "Pippa", "reason": "retired"}),
    ("rejoin_party", {"character": "Pippa"}),
    ("award_xp", {"character": "Garrek", "amount": 100}),
    ("update_coin", {"delta": "+50gp"}),
    ("rest", {"days": 1}),
    ("add_item", {"character": "Garrek", "item": "Torch", "qty": 3}),
    ("remove_item", {"character": "Garrek", "item": "Torch"}),
    ("transfer", {"item": "Torch", "qty": 1, "source": "Garrek", "dest": "loot"}),
    ("inventory", {}),
    ("encumbrance", {"character": "Garrek"}),
    ("set_spell_loadout", {"character": "Corwin", "known": {"1": ["Sleep"]}, "default": {"1": ["Sleep"]}}),
    ("memorize_spells", {"character": "Corwin"}),
    ("spell_status", {"character": "Corwin"}),
    ("cast_spell", {"character": "Corwin", "spell_name": "Sleep"}),
    ("award_treasure", {"treasure_types": "Individual 3"}),
    ("loot_pile", {}),
    ("claim_loot", {"index": 0, "character": "Pippa"}),
    ("magic_merchant", {"merchant": "ostler", "settlement": "city", "name": "Ostler's"}),
    ("buy_magic_item", {"merchant": "ostler", "item": "0", "character": "Garrek", "price_gp": 1}),
    ("move_party", {"to": "Entry Hall"}),  # the room with the planted note
    ("room", {}),
    ("move_party", {"to": "Vestry"}),  # the secret door to the planted hidden room
    ("room", {"query": "Vestry"}),
    ("door", {"door": "42,20", "state": "open"}),
    ("door", {"door": "trapdoor_4", "found": True}),  # the planted secret trapdoor, found
    ("move_party", {"to": "Throne Room", "characters": ["Pippa"]}),
    ("setup_combat", {"enemies": [{"name": "goblin", "count": 2, "hp": 5}]}),
    ("resolve_attack", {"attacker": "Garrek", "target": "Goblin 1"}),
    ("throw_missile", {"thrower": "Pippa", "target": "Goblin 2", "missile": "oil"}),
    (
        "combat_round",
        {
            "actions": [
                {"attacker": "Garrek", "target": "Goblin 2"},
                {"actor": "Pippa", "action": "binds the door", "rounds": 2},
            ]
        },
    ),
    ("interrupt", {"combatant": "Pippa", "reason": "Pippa was hit"}),
    ("add_combatant", {"name": "goblin", "stats": {"hp": 5}}),
    ("update_combatant", {"id": "mon_3", "stats": {"ac": 5, "dmg": "1d6"}}),
    ("apply_effect", {"target": "Garrek", "name": "bless", "duration": 3, "to_hit": 1}),
    ("remove_effect", {"target": "Garrek", "name": "bless"}),
    ("add_condition", {"name": "Garrek", "condition": "prone"}),
    ("remove_condition", {"name": "Garrek", "condition": "prone"}),
    ("adjudicate", {"note": "The goblin slips on the bones."}),
    ("apply_damage", {"character": "mon_3", "amount": 1}),
    ("apply_heal", {"character": "mon_3", "amount": 1}),
    ("remove_combatant", {"id": "mon_3", "reason": "fled"}),
    ("combat_status", {}),
    ("end_combat", {}),
    ("log_note", {"text": "The party entered the crypt."}),
    ("new_session", {"title": "Into the crypt"}),
    ("advance_time", {"minutes": 10}),
    ("set_time", {"hour": 8}),
    ("add_quest", {"id": "find-the-relic", "title": "Find the relic", "stakes": "The ward fails."}),
    ("update_quest", {"id": "find-the-relic", "note": "The abbot lied.", "note_known": False}),
    ("factions", {}),
    ("clocks", {}),
    ("quests", {}),
    ("advance_days", {"days": 2, "reason": "waiting out the rain"}),  # after rest, the planted clock completes
    ("weather_check", {"terrain": "road"}),
    ("calendar", {}),
    ("house_rules", {}),
    ("show_image", {"asset": "gate", "caption": "The gate"}),
    ("tell", {"characters": ["Pippa"], "text": "A draught from the wall."}),
    ("say", {"npc": "Tira", "text": "Welcome, travellers.", "mood": "smile"}),
    ("portrait", {"of": "Garrek"}),
    ("paint_scene", {"brief": f"{SECRET}: the lich behind the altar.", "caption": "The altar"}),
    ("scout", {"character": "Pippa"}),
    ("council", {"npcs": ["Tira"]}),
    ("add_possession", {"name": "Bess", "kind": "mount", "owner": "Garrek", "species": "pony", "stats": PONY}),
    ("update_possession", {"id": "Bess", "hp_change": -2}),
    ("possessions", {}),
    ("possession", {"id": "Bess"}),
    ("remove_possession", {"id": "Bess"}),
    (
        "batch",
        {
            "steps": [
                {"tool": "dm_secrets", "args": {}},
                {"tool": "room", "args": {"query": "Entry Hall"}},
                {"tool": "move_party", "args": {"to": "Entry Hall"}},
                {"tool": "get_character", "args": {"ref": "Tira"}},
                {"tool": "roll", "args": {"notation": "1d6", "purpose": "a batch roll"}},
            ]
        },
    ),
    ("end_session", {"recap": "They explored the crypt."}),
    ("add_fact", {"text": "The party entered the crypt."}),
    ("facts", {}),
    ("search_campaign", {"query": "innkeeper"}),
    ("place_party", {"at": "greyhawk"}),
    ("distance", {"a": "greyhawk", "b": "hardby"}),
    ("nearest", {"kind": "ruin", "n": 5}),  # the planted hidden tower among them, marked hidden
    ("distance", {"a": "greyhawk", "b": "hardby", "mode": "foot"}),
    ("route", {"to": "hardby"}),
    ("world_map", {"feature": "lich-tower"}),
    ("travel", {"to": "castle-greyhawk"}),
    ("reveal_place", {"feature": "lich-tower"}),
    ("add_place", {"name": "Oakhollow", "kind": "village", "at": "greyhawk", "notes": SECRET}),
    ("hide_place", {"feature": "castle-track"}),
    ("reveal_area", {"at": "hardby", "radius_km": 20}),
    ("reveal_area", {"at": "hardby", "radius_km": 5, "forget": True}),
    # Last: under OSRIC a 1st-level character drained dies, and Garrek still has to fight above.
    ("drain_level", {"character": "Garrek", "reason": "a wight's touch"}),
]


@pytest.fixture
def planted(call, party):
    """The secret planted in every kind of DM-only data: the hidden room's label, text and DM notes (in the map),
    the NPC Tira's story (`notes_md`, by `party`), a DM secret, and a DM note on the entry hall."""
    assert "error" not in call("dm_note", text=f"{SECRET}: the innkeeper reports to the cult.", tags=["motive"])
    assert "error" not in call("note_room", text=f"{SECRET}: the chest is a mimic.", query="Entry Hall")
    assert "error" not in call("update_faction", id="cult", name="The Cult", notes=f"{SECRET}: the abbot leads it.")
    assert "error" not in call("add_clock", label="The eye wakes", days=3, faction="cult", on_complete=SECRET)
    assert "error" not in call("add_place", **HIDDEN_PLACE)
    return call


@pytest.fixture(autouse=True)
def paid_images(storage, campaign):
    """paint_scene paints only with paid images on (plan 6 Task 10)."""
    set_play_settings(storage, campaign.id, {"paid_images": True})


def _perceived(value):
    """Every `perceived` value in a result, at any depth."""
    if isinstance(value, dict):
        for key, inner in value.items():
            if key == "perceived":
                yield inner
            yield from _perceived(inner)
    elif isinstance(value, list):
        for inner in value:
            yield from _perceived(inner)


def test_planted_secret_never_in_player_view_or_perceived(planted, host):
    """For every tool the players may see, and every tool that returns `perceived`: the planted secret is absent from
    each `perceived` and from the player view, though the DM's own answers do carry it (so the plant is real)."""
    covered = set()
    dm_saw_it = set()
    for name, args in SESSION:
        result = planted(name, **args)
        assert "error" not in result, (name, result)
        spec = host.spec(name)
        covered.add(name)
        if SECRET in json.dumps(result):
            dm_saw_it.add(name)
        for perceived in _perceived(result):
            assert SECRET not in json.dumps(perceived), (name, perceived)
        view = player_view(spec, args, result)
        if spec.player_visible:
            assert view is not None, name
            assert SECRET not in json.dumps(view), (name, view)
        else:
            assert view is None, name
    visible = {spec.name for spec in host.specs() if spec.player_visible}
    assert visible | {"room"} <= covered
    # The plant reached the DM: Tira's story, the entry hall's note, the hidden room behind the vestry's secret door.
    assert {"get_character", "update_character", "move_party", "room", "batch"} <= dm_saw_it
    # …and the faction's notes and the clock's on_complete, also when the clock completes in a pass of days.
    assert {"factions", "clocks", "advance_days"} <= dm_saw_it
    # …and the hidden place's DM notes, which only world_map answers.
    assert "world_map" in dm_saw_it and not {"nearest", "travel", "reveal_place", "place_party"} & dm_saw_it


def test_dm_only_tools_have_no_player_view(planted, host):
    """The DM-only tools are exactly the plan's and ttrpg2's bodyless ones (notes, secrets, the room, the unawarded
    hoard, the primer, the module's text), and their results never reach the players' feed, whatever they hold."""
    assert {spec.name for spec in host.specs() if not spec.player_visible} == DM_ONLY_TOOLS
    secrets = planted("dm_secrets")
    assert SECRET in json.dumps(secrets)
    hidden = planted("room", query="room.hidden_crypt")
    assert hidden["perceived"] == {} and SECRET in json.dumps(hidden["dm_only"])
    for name in DM_ONLY_TOOLS:
        assert player_view(host.spec(name), {}, secrets) is None


def test_a_kept_back_pregen_is_the_dms(planted, host):
    """Faithful modules Task 19: `module_pregens` gives the DM every pregen, a `gm` one with its planted background
    too; the players' feed shows nothing of it."""
    out = planted("module_pregens")
    assert SECRET in json.dumps(out)
    assert player_view(host.spec("module_pregens"), {}, out) is None


def test_a_found_secret_keeps_its_dm_notes(planted, host):
    """Plan Task 22b: a secret trapdoor found shows to the characters, its DM notes never: neither the found call's
    player view nor the room's perceived holds them, while the DM's half still does."""
    planted("move_party", to="Vestry")
    before = planted("room", query="Vestry")
    assert "chest" not in json.dumps(before["perceived"]) and SECRET in json.dumps(before["dm_only"])
    found = planted("door", door="trapdoor_4", found=True)
    assert found["revealed"] is True and SECRET not in json.dumps(found)
    assert player_view(host.spec("door"), {"door": "trapdoor_4", "found": True}, found) == {}
    after = planted("room", query="Vestry")
    assert "chest" in json.dumps(after["perceived"]) and SECRET not in json.dumps(after["perceived"])
    assert SECRET in json.dumps(after["dm_only"]["secret_features"])


# The tool outputs past the allow-list: the image the DM shows (plan 3 Task 8), what it tells some characters
# (plan 4 Task 5), which the table addresses to them, and an NPC's line (portraits plan Task 7).
SHOWN = {
    "show_image": {"image": {"asset": "gate", "caption": "The gate"}},
    "tell": {"told": {"characters": ["<pippa>"], "text": "A draught from the wall."}},
    "say": {
        "said": {
            # Tira is drawn when she is made (DEL-248): portraitgen's traits, from her sheet.
            "speaker": {
                "id": "<tira>",
                "name": "Tira",
                "portrait": {"kind": "traits", "describe": "a human", "seed": "<tira>"},
            },
            "mood": "smile",
            "text": "Welcome, travellers.",
        }
    },
}


def test_player_view_is_an_allow_list(planted, host, party):
    """Spec §7.5: the players' feed shows a tool by its name, never its inputs or its result. Results carry what the
    old deny-list missed: in the first real session, setup_combat showed a monster's stat block (what it really is,
    its hit points, what can hurt it), and roll purposes named hidden checks. The exceptions are the image
    show_image shows, what tell tells some characters and the line say gives an NPC."""
    for name, args in SESSION:
        spec = host.spec(name)
        if spec.player_visible:
            view = json.dumps(player_view(spec, args, planted(name, **args)))
            view = view.replace(party[1]["id"], "<pippa>").replace(party[2]["id"], "<tira>")
            assert json.loads(view) == SHOWN.get(name, {}), name


def test_a_dm_only_image_shows_nothing(planted, host):
    """Plan 3 Review Focus 3: show_image refuses the DM-only image, whose description holds the secret; an unknown
    id's candidates are the player images only; a refusal shows only that it failed."""
    spec = host.spec("show_image")
    refused = planted("show_image", asset="lich")
    assert refused["error"] == "That image is for the DM only."
    assert SECRET not in json.dumps(refused)
    assert player_view(spec, {"asset": "lich"}, refused) == {"failed": True}
    unknown = planted("show_image", asset="altar")
    assert [c["id"] for c in unknown["candidates"]] == ["gate"]
    assert SECRET not in json.dumps(unknown)
    # Anything else in a result stays out, whatever the DM's provider sends back.
    smuggled = {"image": {"asset": "gate", "caption": "", "description": SECRET}, "dm_only": SECRET}
    assert player_view(spec, {}, smuggled) == {"image": {"asset": "gate", "caption": ""}}


def test_a_tell_shows_its_text_and_nothing_else(planted, host, party):
    """Plan 4 Review Focus 1: a tell's text is for the characters it names, and the table addresses it to their seats
    (tests/dm/tools/test_tell.py). The view holds the ids and the text only, whatever else the result carries, and a
    refusal names nobody: its candidates are the DM's."""
    spec = host.spec("tell")
    told = planted("tell", characters=["Garrek"], text=f"{SECRET} whispers your name.")
    assert player_view(spec, {}, told) == {
        "told": {"characters": [party[0]["id"]], "text": f"{SECRET} whispers your name."}
    }
    smuggled = {"told": {"characters": [party[0]["id"]], "text": "Psst.", "dm_only": SECRET}, "dm_only": SECRET}
    assert player_view(spec, {}, smuggled) == {"told": {"characters": [party[0]["id"]], "text": "Psst."}}
    for bad in ({"told": {"characters": [], "text": "Psst."}}, {"told": {"characters": [1], "text": "Psst."}}, {}):
        assert player_view(spec, {}, bad) == {}
    refused = planted("tell", characters=["Tira"], text=SECRET)
    assert player_view(spec, {}, refused) == {"failed": True}
    assert SECRET not in json.dumps(refused)


def test_a_say_shows_its_speaker_mood_and_line_and_nothing_else(planted, host, party):
    """Portraits plan Task 7: an NPC's line is for everyone. The view holds the speaker's id, name and portrait, the
    mood and the text, whatever else the result carries: never the NPC's planted story, nor a mood outside the
    vocabulary. A refusal shows only that it failed."""
    spec = host.spec("say")
    said = planted("say", npc="Tira", text="The cellar? Nothing down there.", mood="wink")
    assert SECRET in json.dumps(planted("get_character", ref="Tira")) and SECRET not in json.dumps(said)
    portrait = {"kind": "traits", "describe": "a human", "seed": party[2]["id"]}  # drawn when she was made (DEL-248)
    speaker = {"id": party[2]["id"], "name": "Tira", "portrait": portrait}
    assert player_view(spec, {}, said) == {
        "said": {"speaker": speaker, "mood": "wink", "text": "The cellar? Nothing down there."}
    }
    portrait = {"kind": "traits", "describe": "grey braids", "seed": "t", "notes": SECRET}
    smuggled = {
        "said": {
            "speaker": {**speaker, "portrait": portrait, "notes_md": SECRET},
            "mood": SECRET,
            "text": "Psst.",
            "dm_only": SECRET,
        },
        "dm_only": SECRET,
    }
    assert player_view(spec, {}, smuggled) == {
        "said": {
            "speaker": {**speaker, "portrait": {"kind": "traits", "describe": "grey braids", "seed": "t"}},
            "mood": "neutral",
            "text": "Psst.",
        }
    }
    image = {**speaker, "portrait": {"kind": "image", "image_id": "img_1", "brief": SECRET}}
    assert player_view(spec, {}, {"said": {"speaker": image, "mood": "cry", "text": "Oh."}})["said"]["speaker"] == {
        **speaker,
        "portrait": {"kind": "image", "image_id": "img_1"},
    }
    for bad in (
        {"said": {"speaker": {"id": "", "name": "Tira"}, "mood": "cry", "text": "Oh."}},
        {"said": {"speaker": speaker, "mood": "cry", "text": ""}},
        {
            "said": {
                "speaker": {**speaker, "portrait": {"kind": "painted", "url": SECRET}},
                "mood": "cry",
                "text": "Oh.",
            }
        },
        {},
    ):
        assert player_view(spec, {}, bad) == {}, bad
    refused = planted("say", npc="Garrek", text=SECRET)
    assert player_view(spec, {}, refused) == {"failed": True}
    assert SECRET not in json.dumps(refused)


def test_the_dm_gets_room_notes_and_npc_stories(planted, host):
    """The keys tools mark DM-only reach the DM, and the players get nothing of those results."""
    moved = planted("move_party", to="Entry Hall")
    assert SECRET in moved["room_notes"][0]["text"]
    assert player_view(host.spec("move_party"), {"to": "Entry Hall"}, moved) == {}
    tira = planted("get_character", ref="Tira")
    assert SECRET in tira["sheet"]["notes_md"]
    assert player_view(host.spec("get_character"), {"ref": "Tira"}, tira) == {}


def test_a_refusal_shows_only_that_it_failed(host):
    """A refusal's message echoes the DM's input ("No room 'crypt'"), and its candidates may name rooms the characters
    never found."""
    refused = {"error": "No room 'crypt'.", "hint": "Name one.", "candidates": [{"label": SECRET}]}
    assert player_view(host.spec("move_party"), {"to": "crypt"}, refused) == {"failed": True}


def test_a_batch_shows_nothing_of_its_steps(planted, host):
    args = {
        "steps": [{"tool": "dm_secrets", "args": {}}, {"tool": "move_party", "args": {"to": "Entry Hall"}}],
        "stop_on_error": False,
    }
    assert player_view(host.spec("batch"), args, planted("batch", **args)) == {}


def test_a_possessions_notes_are_the_dms(planted, host, party):
    """Plan 6 Review Focus 1: a possession's `notes_md` reaches the DM through `possession` only, a DM-only tool;
    the list, and the add and update answers, never carry it."""
    added = planted("add_possession", name="The Gull", kind="ship", notes=f"{SECRET}: smuggles for the cult.")
    updated = planted("update_possession", id="The Gull", location="Hardby harbour")
    listed = planted("possessions")
    for name, result in (("add_possession", added), ("update_possession", updated), ("possessions", listed)):
        assert "error" not in result and SECRET not in json.dumps(result), name
        assert player_view(host.spec(name), {}, result) == {}
    assert SECRET in planted("possession", id="The Gull")["notes_md"]
    assert not host.spec("possession").player_visible


def test_an_enemys_interrupted_action_stays_the_dms(planted, host, storage, campaign, party):
    """Decision 10, the enemy side of `interrupt`: what an enemy was doing is planted as the secret. The DM's half
    holds it; what the characters perceive, the players' feed and a player's timeline (its round released) never do."""
    assert "error" not in planted("setup_combat", enemies=[{"name": "goblin", "count": 1, "hp": 5}], surprise=False)
    assert "error" not in planted("combat_round", actions=[{"actor": "Goblin", "action": SECRET, "rounds": 3}])
    args = {"combatant": "Goblin", "reason": "The goblin is knocked down"}
    out = planted("interrupt", **args)
    assert out["kind"] == "other" and out["dm_only"] == {"what": SECRET}
    assert SECRET not in json.dumps(list(_perceived(out))) and SECRET not in json.dumps(out["perceived"])
    assert SECRET not in json.dumps(player_view(host.spec("interrupt"), args, out))

    seat = storage.seats.create(campaign.id, "Ana", "en", "player")
    storage.seats.set_controller(party[0]["id"], seat.id)
    for row in storage.combat_rounds.unreleased(campaign.id):
        storage.combat_rounds.release(row.combat_id, row.round, "2026-10-25T12:00:00+00:00")
    fight = timeline_for(storage, campaign.id, seat)["fight"]
    goblin = next(s for s in fight["slots"] if s["side"] == "enemy")
    assert (goblin["ongoing"]["what"], goblin["ongoing"]["reason"]) == (None, None)
    assert SECRET not in json.dumps(fight)
