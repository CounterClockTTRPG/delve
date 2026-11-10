"""`play.sessions`: sessions and recaps, the clock (ttrpg2 `tools/log.py`), and the primer (ttrpg2 `session_primer`,
without strongholds, light or weather)."""

from dataclasses import replace

import pytest

from delve.dice import ScriptedRng
from delve.domain.histories import History
from delve.domain.modules import ModuleMap
from delve.modules.books.convert import FRONT_MATTER
from delve.modules.dscn import Bundle
from delve.modules.importer import import_bundle
from delve.modules.source import ModuleSource, TextDoc, save_source
from delve.play import characters, inventory, moves, sessions, spells
from delve.play.context import PlayError, context_for
from tests.fixtures import SAMPLES
from tests.fixtures.play_reference import PlayReference
from tests.fixtures.rulesets import over


def events(ctx, type):
    return [e for e in ctx.storage.events.list(ctx.campaign_id) if e.type == type]


def clock(ctx):
    state = ctx.storage.campaign_states.get(ctx.campaign_id)
    return state.day, state.hour, state.minute


def test_session_cycle_and_recap(ctx):
    """ttrpg2 `new_session` raises the session number and logs `session_start`; the recap is stored when it ends."""
    first = sessions.new_session(ctx, "Into the crypt")
    assert (first["session"], first["title"]) == (1, "Into the crypt")  # the campaign starts in session 1
    ended = sessions.end_session(ctx, "They found the hidden crypt.")
    assert ended == {"session": 1, "title": "Into the crypt", "recap_md": "They found the hidden crypt."}
    second = sessions.new_session(ctx, "The ritualist")
    assert second["session"] == 2 and ctx.storage.campaign_states.get(ctx.campaign_id).session == 2
    assert [e.data["session"] for e in events(ctx, "session_start")] == [1, 2]
    assert events(ctx, "session_start")[1].session == 2  # the event is in the new session
    assert [e.session for e in events(ctx, "session_end")] == [1]
    stored = ctx.storage.sessions.list(ctx.campaign_id)
    assert [(s.number, s.recap_md) for s in stored] == [(1, "They found the hidden crypt."), (2, None)]
    with pytest.raises(PlayError):
        sessions.new_session(ctx, " ")


def test_end_session_without_a_start(ctx):
    out = sessions.end_session(ctx, "A short one.")
    assert (out["session"], out["title"]) == (1, "Session 1")


def test_advance_time_rolls_over_midnight(ctx):
    """ttrpg2 `advance_time`: the clock starts at dawn, day 1, and rolls into the next day at hour 24."""
    out = sessions.advance_time(ctx, 30)
    assert out == {"minutes_advanced": 30, "day": 1, "time": "06:30", "period": "dawn", "date": "1 Planting 576 CY"}
    out = sessions.advance_time(ctx, 18 * 60)
    assert (out["day"], out["time"], out["period"], out["days_passed"]) == (2, "00:30", "night", 1)
    assert clock(ctx) == (2, 0, 30)
    assert [
        p
        for h, p in ((9, "morning"), (12, "midday"), (15, "afternoon"), (19, "evening"), (22, "night"))
        if sessions.set_time(ctx, h)["period"] == p
    ] == ["morning", "midday", "afternoon", "evening", "night"]


def test_set_time_clamps_and_keeps_the_day(ctx):
    """ttrpg2 `set_time`: hour 0-23 and minute 0-59, the day unchanged."""
    sessions.advance_time(ctx, 24 * 60)
    assert sessions.set_time(ctx, 30, 75) == {"day": 2, "time": "23:59", "period": "night"}
    assert sessions.set_time(ctx, 6) == {"day": 2, "time": "06:00", "period": "dawn"}
    assert clock(ctx) == (2, 6, 0)


@pytest.fixture
def table(storage):
    module = storage.modules.create("The Crypt")
    storage.modules.put_map(module.id, ModuleMap("crypt", "map", (SAMPLES / "crypt.dmap").read_text(), True))
    campaign = storage.campaigns.create(
        "Tuesday", module.id, storage.revisions.snapshot(module.id).number, ruleset="osric", setting="greyhawk"
    )
    ctx = context_for(storage, campaign.id, "beat-1", ScriptedRng((1,)), catalogs=over(PlayReference()))  # the weather the primer rolls
    characters.create(
        ctx,
        name="Garrek",
        sheet={
            "race": "human",
            "cls": "Fighter",
            "level": 3,
            "hp_max": 24,
            "ac": 4,
            "thac0": 18,
            "ability_scores": {"str": 12},
            "attacks": [{"name": "Long sword", "speed": 5, "damage_sm": "1d8", "damage_l": "1d12"}],
        },
    )
    characters.create(ctx, name="Hesh", sheet={"cls": "Cleric", "level": 2, "hp_max": 12, "spell_slots": {1: 2}})
    characters.create(ctx, name="Tira", kind="npc", sheet={})
    return ctx


def test_primer_shape(table, monkeypatch):
    """The successor of ttrpg2's `session_primer`: what the DM needs to pick up a session in one call. No
    strongholds or light (cut); the date and the weather are plateau 6's."""
    ctx = table
    sessions.new_session(ctx, "Into the crypt")
    sessions.end_session(ctx, "They entered the crypt.")
    sessions.new_session(ctx, "The ritualist")
    sessions.advance_time(ctx, 90)
    characters.apply_damage(ctx, "Garrek", 5)
    inventory.add_item(ctx, "Garrek", "Plate mail")
    inventory.add_item(ctx, "Garrek", "Torch", qty=6)
    spells.memorize(ctx, "Hesh", ["Bless", "Cure Light Wounds"])
    spells.cast(ctx, "Hesh", "Bless")
    characters.set_marching_order(ctx, ["Hesh"])
    moves.move(ctx, to="room.entry_hall")
    moves.move(ctx, to="corridor.main_hall", characters=["Hesh"])

    primer = sessions.primer(ctx)
    assert set(primer) == {
        "day",
        "date",
        "time",
        "weather",
        "period",
        "session",
        "last_recap",
        "party",
        "marching_order",
        "positions",
        "recent_events",
        "combat",
        "module",
        "quests",
        "clocks",
        "history",
    }
    assert (primer["day"], primer["time"], primer["period"]) == (1, "07:30", "dawn")
    assert primer["date"]["label"] == "1 Planting 576 CY" and primer["date"]["season"] == "Low summer"
    assert primer["weather"] == {
        "day": 1,
        "terrain": "wilderness",
        "label": "clear",
        "effect": "Bright and hot.",
        "pace": 1.0,
    }
    assert primer["session"] == {"number": 2, "title": "The ritualist"}
    assert primer["last_recap"] == {"session": 1, "title": "Into the crypt", "recap_md": "They entered the crypt."}
    assert primer["marching_order"] == ["Hesh", "Garrek"]
    hesh, garrek = primer["party"]
    assert garrek == {
        "id": garrek["id"],
        "name": "Garrek",
        "race": "human",
        "cls": "Fighter",
        "levels": {"fighter": 3},
        "hp": 19,
        "hp_max": 24,
        "ac": 4,
        "thac0": 18,
        "attacks": [
            {
                "name": "Long sword",
                "speed": 5,
                "attacks": 1,
                "thac0": None,
                "damage_sm": "1d8",
                "damage_l": "1d12",
                "range": None,
            }
        ],
        "conditions": [],
        "effects": [],
        "spells": {"memorized": [], "uncast": []},
        "inventory": "Plate mail, Torch x6",
        "encumbrance": "moderate",
        "possessions": [],
    }
    assert hesh["spells"] == {"memorized": ["Bless", "Cure Light Wounds"], "uncast": ["Cure Light Wounds"]}

    # An item's notes stay with it (owner item 7): Ask the DM and the DM read them from here.
    inventory.add_item(ctx, "Hesh", "Long sword", notes="Vessa, a talking sword")
    assert "Long sword x1 (Vessa, a talking sword)" in sessions.primer(ctx)["party"][0]["inventory"]
    assert primer["positions"] == [
        {"map": "crypt", "location": "corridor.main_hall", "label": "main_hall", "characters": ["Hesh"]},
        {"map": "crypt", "location": "room.entry_hall", "label": "Entry Hall", "characters": ["Garrek"]},
    ]
    assert len(primer["recent_events"]) == 8
    assert primer["recent_events"][-1]["type"] == "moved"
    assert set(primer["recent_events"][-1]) == {"id", "type", "session", "beat", "data", "at"}
    assert primer["combat"] is None
    assert set(primer["module"]) == {"title", "opening", "sections", "maps", "images", "unmapped"}

    summary = {"round": 2, "order": ["Garrek", "goblin 1"]}
    monkeypatch.setattr(sessions, "_live_combat", lambda ctx: summary)
    assert sessions.primer(ctx)["combat"] == summary


def test_primer_has_the_live_fight(table):
    """The primer's `combat` is the live fight's `combat_status`, and None again once it has ended."""
    from delve.play import combat

    ctx = table
    goblin = {"name": "goblin", "count": 1, "hp": 5, "ac": 6, "thac0": 20, "dmg": "1d6", "weapon_speed": 6}
    fighting = context_for(ctx.storage, ctx.campaign_id, "beat-2", ScriptedRng((5, 4, 3, 4, 2)), catalogs=over(PlayReference()))
    combat.setup_combat(fighting, enemies=[goblin])
    primer = sessions.primer(ctx)
    assert primer["combat"] == combat.combat_status(ctx)
    assert primer["combat"]["round"] == 1
    combat.end_combat(ctx)
    assert sessions.primer(ctx)["combat"] is None


def test_primer_of_a_new_campaign(make_ctx):
    primer = sessions.primer(make_ctx(1))
    assert primer["party"] == [] and primer["positions"] == [] and primer["recent_events"] == []
    assert primer["session"] == {"number": 1, "title": None} and primer["last_recap"] is None


def test_primer_names_the_module(storage):
    """The DM's only view of the module it runs (it reads no files): the title, the opening, the headings that
    module_lookup searches, and each map with where the party starts. The crypt declares no party_start, so its start
    is its first room."""
    module = import_bundle(storage, Bundle.load(SAMPLES / "scenarios" / "crypt-of-saint-vellis").to_zip()).module
    campaign = storage.campaigns.create(
        "Tuesday", module.id, storage.revisions.snapshot(module.id).number, ruleset="osric", setting="greyhawk"
    )
    ctx = context_for(storage, campaign.id, "beat-1", ScriptedRng((1,)), catalogs=over(PlayReference()))  # the weather the primer rolls

    block = sessions.primer(ctx)["module"]
    assert block["title"] == "The Crypt of Saint Vellis"
    assert "The party is hired by [[npc:prior-anselm]] to find out why." in block["opening"]
    assert block["sections"][:2] == ["Introduction > The Crypt of Saint Vellis", "Keyed encounters > C1. Entry Hall"]
    assert block["maps"] == [{"name": "crypt", "default": True, "start": {"id": "room.entry_hall", "label": "Entry Hall"}}]
    assert block["unmapped"] == []  # every keyed part of the crypt is on its map


def test_primer_opens_on_the_first_chapter_not_the_front_matter(storage):
    """Faithful modules C4: the cover's garble is never the DM's opening, wherever the front matter is."""
    module = storage.modules.create("Saltmarsh")
    cover = "## Dungeon Module U1\n\nD A N M E A C E D V G 9076\n"
    introduction = "# Introduction\n\n> Saltmarsh is a quiet town.\n\nRumours.\n"
    texts = [
        TextDoc(FRONT_MATTER, "Front matter", "gm", None, cover),
        TextDoc("introduction", "Introduction", "gm", None, introduction),
    ]
    save_source(storage, module.id, ModuleSource(texts=texts))
    campaign = storage.campaigns.create(
        "Tuesday", module.id, storage.revisions.snapshot(module.id).number, ruleset="osric", setting="greyhawk"
    )
    ctx = context_for(storage, campaign.id, "beat-1", ScriptedRng((1,)), catalogs=over(PlayReference()))  # the weather the primer rolls

    opening = sessions.primer(ctx)["module"]["opening"]

    assert "Saltmarsh is a quiet town." in opening and "Rumours." in opening
    assert "9076" not in opening


def test_primer_names_the_parts_without_a_map(storage):
    """Faithful modules F1: a part whose keyed headings have no room on a map that parses is `unmapped`, so the DM
    asks the host for a map instead of inventing one. The ship is on the crypt's map; the house has no map."""
    module = storage.modules.create("Saltmarsh")
    storage.modules.put_map(module.id, ModuleMap("ship", "map", (SAMPLES / "crypt.dmap").read_text(), True))
    storage.modules.put_map(module.id, ModuleMap("broken", "map", "map broken {", False))
    ship = "# The Sea Ghost\n\n## 1. Entry Hall\n\nThe deck.\n\n## 2. Hold\n\nCargo.\n"
    house = "# The Haunted House\n\n## 1. Kitchen\n\nPots.\n\n## 2. Cellar\n\nDark.\n\n## 3. Stair\n\nUp.\n"
    texts = [
        TextDoc("intro", "Introduction", "gm", None, "# Introduction\n\nRumours.\n"),
        TextDoc("ship", "The Sea Ghost", "gm", "ship", ship),
        TextDoc("house", "The Haunted House", "gm", "broken", house),
    ]
    save_source(storage, module.id, ModuleSource(texts=texts))
    campaign = storage.campaigns.create(
        "Tuesday", module.id, storage.revisions.snapshot(module.id).number, ruleset="osric", setting="greyhawk"
    )
    ctx = context_for(storage, campaign.id, "beat-1", ScriptedRng((1,)), catalogs=over(PlayReference()))  # the weather the primer rolls

    assert sessions.primer(ctx)["module"]["unmapped"] == [{"text": "house", "title": "The Haunted House", "keys": 3}]


def test_primer_module_start_is_the_party_start(storage):
    module = storage.modules.create("The Crypt")
    source = (SAMPLES / "crypt.dmap").read_text().replace("  legend\n", '  legend\n  party_start "throne_chamber"\n')
    storage.modules.put_map(module.id, ModuleMap("crypt", "map", source, True))
    campaign = storage.campaigns.create(
        "Tuesday", module.id, storage.revisions.snapshot(module.id).number, ruleset="osric", setting="greyhawk"
    )
    ctx = context_for(storage, campaign.id, "beat-1", ScriptedRng((1,)), catalogs=over(PlayReference()))  # the weather the primer rolls
    [crypt] = sessions.primer(ctx)["module"]["maps"]
    assert crypt["start"]["id"] == "room.throne_chamber"


def test_primer_module_without_maps_or_text(storage):
    """A module can be text only, or not written yet: the DM runs it from what there is."""
    module = storage.modules.create("Rumours of Hommlet")
    storage.modules.put_map(module.id, ModuleMap("broken", "map", "map broken {", False))
    campaign = storage.campaigns.create(
        "Tuesday", module.id, storage.revisions.snapshot(module.id).number, ruleset="osric", setting="greyhawk"
    )
    ctx = context_for(storage, campaign.id, "beat-1", ScriptedRng((1,)), catalogs=over(PlayReference()))  # the weather the primer rolls
    assert sessions.primer(ctx)["module"] == {
        "title": "Rumours of Hommlet",
        "opening": "",
        "sections": [],
        "maps": [{"name": "broken", "default": False, "start": None, "offline": True}],
        "images": [],
        "unmapped": [],
    }
    empty = storage.modules.create("Blank")
    other = storage.campaigns.create(
        "Wednesday", empty.id, storage.revisions.snapshot(empty.id).number, ruleset="osric", setting="greyhawk"
    )
    blank = context_for(storage, other.id, "beat-1", ScriptedRng((1,)), catalogs=over(PlayReference()))  # the weather the primer rolls
    assert sessions.primer(blank)["module"] == {
        "title": "Blank",
        "opening": "",
        "sections": [],
        "maps": [],
        "images": [],
        "unmapped": [],
    }


def test_primer_has_history_when_done(table):
    """Carry-the-party-on plan Task 6: a carried party's history is the DM's text, read every session."""
    ctx = table
    assert sessions.primer(ctx)["history"] is None, "a campaign that wasn't carried on"
    ctx.storage.histories.put(History(ctx.campaign_id))
    assert sessions.primer(ctx)["history"] is None, "still writing, nothing written yet"
    ctx.storage.histories.put(
        History(ctx.campaign_id, dm_md="## Loose ends\nThe abbot lives.", table_md="Ours.", status="done")
    )
    assert sessions.primer(ctx)["history"] == "## Loose ends\nThe abbot lives."


def test_primer_history_none_while_its_texts_are_empty(table):
    """A history without a DM's text yet gives the DM nothing, whatever its status."""
    ctx = table
    for status in ("writing", "failed"):
        history = History(ctx.campaign_id, dm_md="  ", table_md="Ours.", status=status)
        ctx.storage.histories.put(replace(history, error="Claude stopped." if status == "failed" else None))
        assert sessions.primer(ctx)["history"] is None, status


def test_primer_reads_the_history_a_failed_write_again_kept(table):
    """Review fix: a Write again that fails, is orphaned or still runs keeps the old texts, and the DM reads them."""
    ctx = table
    for status, error in (("failed", "Claude stopped."), ("failed", "Delve stopped while writing."), ("writing", None)):
        ctx.storage.histories.put(
            History(
                ctx.campaign_id, dm_md="## Loose ends\nThe abbot lives.", table_md="Ours.", status=status, error=error
            )
        )
        assert sessions.primer(ctx)["history"] == "## Loose ends\nThe abbot lives.", (status, error)


def test_a_long_opening_is_cut_and_says_where_the_rest_is(storage):
    """DEL-79: a module's whole first chapter was the primer's opening, 40 KB for one module. It stops after
    `OPENING_CHARS`, at a paragraph, and `opening_more` says how to read the rest."""
    module = storage.modules.create("The Long Road")
    paragraphs = [f"Paragraph {i}: " + "the road winds on " * 20 for i in range(40)]
    introduction = "# Introduction\n\n" + "\n\n".join(paragraphs) + "\n"
    save_source(storage, module.id, ModuleSource(texts=[TextDoc("introduction", "Introduction", "gm", None, introduction)]))
    campaign = storage.campaigns.create(
        "Tuesday", module.id, storage.revisions.snapshot(module.id).number, ruleset="osric", setting="greyhawk"
    )
    ctx = context_for(storage, campaign.id, "beat-1", ScriptedRng((1,)), catalogs=over(PlayReference()))

    block = sessions.primer(ctx)["module"]
    assert len(block["opening"]) <= sessions.OPENING_CHARS + 2
    assert block["opening"].startswith("Paragraph 0:") and block["opening"].endswith(" …")
    assert "Paragraph 39" not in block["opening"]
    assert block["opening_more"].endswith("module_lookup 'Introduction' reads it.")


def test_a_short_opening_comes_whole(storage):
    module = storage.modules.create("Short")
    texts = [TextDoc("introduction", "Introduction", "gm", None, "# Introduction\n\nA short walk.\n")]
    save_source(storage, module.id, ModuleSource(texts=texts))
    campaign = storage.campaigns.create(
        "Tuesday", module.id, storage.revisions.snapshot(module.id).number, ruleset="osric", setting="greyhawk"
    )
    block = sessions.primer(context_for(storage, campaign.id, "beat-1", ScriptedRng((1,)), catalogs=over(PlayReference())))["module"]
    assert "A short walk." in block["opening"] and "opening_more" not in block


TRACED = """map "level-1" {
  grid {
    bounds 40 x 20
  }
}
room "r15" {
  rect 30,2 6 x 6
  label "15"
}
room "r1" {
  rect 2,2 6 x 6
  label "1"
}
room "r4" {
  rect 12,2 6 x 6
  label "4"
}
"""


def test_without_a_party_start_the_party_starts_at_the_lowest_key(storage):
    """DEL-187: a traced map drew room 15 first, and the DM started Thracia's party there, not at room 1, the Entry
    Hall. Without a `party_start`, the start is the room with the lowest key."""
    module = storage.modules.create("Thracia")
    storage.modules.put_map(module.id, ModuleMap("level-1", "map", TRACED, is_default=True))
    campaign = storage.campaigns.create(
        "Tuesday", module.id, storage.revisions.snapshot(module.id).number, ruleset="osric", setting="greyhawk"
    )
    ctx = context_for(storage, campaign.id, "beat-1", ScriptedRng((1,)), catalogs=over(PlayReference()))
    (level,) = sessions.primer(ctx)["module"]["maps"]
    assert level["start"]["id"] == "room.r1"


def test_level_fit_warns_when_the_party_is_outside_the_modules_levels(storage):
    """DEL-187: Thracia is for levels 3 to 8; a party of level 1 learned it only from the DM's note."""
    module = storage.modules.create("Thracia", {"party": {"levels": {"min": 3, "max": 8}}})
    campaign = storage.campaigns.create(
        "Tuesday", module.id, storage.revisions.snapshot(module.id).number, ruleset="osric", setting="greyhawk"
    )
    ctx = context_for(storage, campaign.id, "beat-1", ScriptedRng(()), catalogs=over(PlayReference()))
    assert sessions.level_fit(ctx) is None, "no party yet"
    characters.create(ctx, name="Garrek", sheet={"race": "Dwarf", "cls": "Fighter", "levels": {"fighter": 1}, "hp_max": 9})
    assert sessions.level_fit(ctx) == {"min": 3, "max": 8, "party": 1.0}
    characters.create(ctx, name="Pippa", sheet={"race": "Halfling", "cls": "Thief", "levels": {"thief": 9}, "hp_max": 9})
    assert sessions.level_fit(ctx) is None, "level 5 on average fits"

    bare = storage.modules.create("No levels")
    other = storage.campaigns.create(
        "Wednesday", bare.id, storage.revisions.snapshot(bare.id).number, ruleset="osric", setting="greyhawk"
    )
    lone = context_for(storage, other.id, "beat-1", ScriptedRng(()), catalogs=over(PlayReference()))
    characters.create(lone, name="Ulf", sheet={"race": "Human", "cls": "Fighter", "levels": {"fighter": 1}, "hp_max": 9})
    assert sessions.level_fit(lone) is None, "the module doesn't say"


def test_the_primer_and_party_status_give_each_pcs_pronouns_and_deity(table):
    """DEL-327: where the DM reads the party, each PC's pronouns (the gender's unless the sheet gives its own) and the
    god it serves; a sheet that says neither shows neither."""
    from delve.dm.tools.party import party_status

    characters.update(table, "Hesh", {"gender": "female", "deity": "St. Cuthbert"})
    pcs = {c["name"]: c for c in sessions.primer(table)["party"]}
    hesh, garrek = pcs["Hesh"], pcs["Garrek"]
    assert (hesh["pronouns"], hesh["deity"]) == ("she/her", "St. Cuthbert")
    assert "pronouns" not in garrek and "deity" not in garrek
    brief = {c["name"]: c for c in party_status(table)["party"]}
    assert (brief["Hesh"]["pronouns"], brief["Hesh"]["deity"]) == ("she/her", "St. Cuthbert")


def test_the_primer_brings_what_is_lost_late_in_a_session(table):
    """DEL-328: after its context is cut the DM forgot where the boat was, a debt and its own note; the primer brings
    the newest facts, every possession with its owner and place, and the newest secret notes."""
    from delve.dm.tools.lore import add_fact
    from delve.domain.world import Possession
    from delve.play import notes

    add_fact(table, "Marcus hired the six for 60 gp each.", "debt")
    table.storage.possessions.put(
        Possession(table.campaign_id, "pos_boat", "Rowboat", "vehicle", location="tied at the fish-market stair")
    )
    notes.dm_note(table, "The grating is jammed down with a new chain.")
    primer = sessions.primer(table)
    assert primer["facts"] == ["day 1 (debt): Marcus hired the six for 60 gp each."]
    assert primer["possessions"] == ["Rowboat (vehicle, the party): tied at the fish-market stair"]
    assert primer["dm_notes"] == ["The grating is jammed down with a new chain."]


def test_the_session_summary_is_what_the_session_recorded(table):
    """DEL-328: the recap was written from the last scenes alone; the summary has the whole session, one line each,
    without the clock's ticks."""
    from delve.dm.tools.lore import add_fact

    sessions.new_session(table, "Into the crypt")
    table.log("log_note", id="note_1", text="The party reached the crypt at dusk.")
    sessions.advance_time(table, 30)
    add_fact(table, "Ilde owes the party 300 gp for the axe.", "debt")
    characters.award_xp(table, "Garrek", 120)
    sessions.new_session(table, "The ritualist")
    table.log("log_note", id="note_2", text="Later.")
    first = sessions.session_summary(table, 1)
    assert first["title"] == "Into the crypt"
    assert first["lines"] == [
        "log_note: The party reached the crypt at dusk.",
        "fact: Ilde owes the party 300 gp for the axe.",
        "xp: Garrek +120 (120)",
    ]
    assert sessions.session_summary(table)["lines"] == ["log_note: Later."]


def test_search_campaign_finds_the_facts(table):
    """DEL-328: the DM searched "wages" and "Marcus owed" for the party's pay, and the debt was a fact it couldn't
    search; once, not again as the fact's event."""
    from delve.dm.tools.lore import add_fact, search_campaign

    add_fact(table, "Marcus Ariol hired the six guards for 60 gp each.", "debt")
    found = search_campaign(table, "Marcus Ariol")
    assert [(r["source"], r["excerpt"]) for r in found["results"]] == [
        ("fact 1 (debt)", "Marcus Ariol hired the six guards for 60 gp each.")
    ]


def test_level_fit_is_for_the_start_of_play_only(storage):
    """The owner's report: "The module is written for levels 1 to 1; the party is level 1.2" after a level up. Once
    the game has awarded XP the party's level is the game's own doing, and the warning stays away."""
    module = storage.modules.create("Barrowmaze", {"party": {"levels": {"min": 1, "max": 1}}})
    campaign = storage.campaigns.create(
        "Friday", module.id, storage.revisions.snapshot(module.id).number, ruleset="osric", setting="greyhawk"
    )
    ctx = context_for(storage, campaign.id, "beat-1", ScriptedRng(()), catalogs=over(PlayReference()))
    characters.create(ctx, name="Ulf", sheet={"race": "Human", "cls": "Fighter", "levels": {"fighter": 2}, "hp_max": 9})
    assert sessions.level_fit(ctx) == {"min": 1, "max": 1, "party": 2.0}, "a party picked outside the module"
    characters.award_xp(ctx, "Ulf", 100)
    assert sessions.level_fit(ctx) is None


def test_a_pc_who_left_the_party_is_in_no_group(table):
    """Barrowmaze: Leoric, dead in room 3 of the Mound of Ooze, showed on the play screen as a group of his own, an
    empty "3:" with "no map". His place stays in the map state, for when he is raised and rejoins."""
    from delve.play import departures

    moves.move(table, to="room.entry_hall")
    moves.move(table, to="corridor.main_hall", characters=["Hesh"])
    assert len(sessions.positions(table)) == 2
    departures.leave_party(table, "Hesh", "died")
    assert [g["characters"] for g in sessions.positions(table)] == [["Garrek"]]
