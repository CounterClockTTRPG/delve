"""The DM's prompt (plan 2b Task 3): `dm.md`, ttrpg2's DM procedure with Delve's tools and words, and the addenda
`build_system_prompt` puts after it in a fixed order, for the prompt cache."""

import re

import pytest

from delve.config import Config
from delve.dice import SeededRng
from delve.dm.prompt import DETAIL_LEVELS, DM_PROCEDURE, TONES, XP_AWARDS, build_system_prompt, procedure
from delve.dm.tools import ToolHost
from delve.domain.characters import Sheet
from delve.domain.modules import ModuleMap
from delve.play.context import context_for
from delve.play.house_rules import set_campaign_house_rules
from delve.storage import open_storage
from tests.dm.tools.test_tools import CUT, DEFERRED, IN_2A, IN_2B, IN_THE_APP
from tests.fixtures import SAMPLES, rulesets

# Every tool name ttrpg2 had: a backticked one in dm.md must be one of Delve's.
TTRPG2_TOOLS = set(IN_2A) | set(IN_2B) | IN_THE_APP | set(DEFERRED) | CUT


@pytest.fixture
def storage(tmp_path):
    opened = open_storage(Config(data_dir=tmp_path / "store"))
    yield opened
    opened.close()


@pytest.fixture
def specs(storage):
    return {spec.name for spec in ToolHost(storage, lambda: SeededRng(1)).specs()}


@pytest.fixture
def ctx(storage):
    """A campaign with a lizardfolk fighter and a human mage in the party, a dwarf NPC, and house rules of every kind
    chosen for it: some for the prompt, some for the tools."""
    module = storage.modules.create("The Crypt")
    storage.modules.put_map(module.id, ModuleMap("crypt", "map", (SAMPLES / "crypt.dmap").read_text(), True))
    campaign = storage.campaigns.create(
        "Tuesday", module.id, storage.revisions.snapshot(module.id).number, ruleset="osric", setting="greyhawk"
    )
    storage.characters.create(campaign.id, "Ssth", sheet=Sheet(label="Ssth", race="Lizardfolk", cls="Fighter"))
    storage.characters.create(campaign.id, "Corwin", sheet=Sheet(label="Corwin", race="Human", cls="Mage"))
    storage.characters.create(campaign.id, "Borin", kind="npc", sheet=Sheet(label="Borin", race="Dwarf", cls="Thief"))
    rules = storage.house_rules
    chosen = [
        rules.create(title="Speak plainly", body_md="NPCs never monologue.", kind="behaviour", phases=["behaviour"]),
        rules.create(title="Lizardfolk swim", body_md="They swim at 12.", kind="race", subject="lizardfolk"),
        rules.create(title="Critical hits", body_md="A natural 20 doubles damage.", phases=["combat"]),
        rules.create(title="Max HP at level 1", body_md="Start at maximum HP.", phases=["character-creation"]),
        rules.create(
            title="Mages wear leather", body_md="Mages may wear leather armour.", kind="class", subject="mage"
        ),
        rules.create(title="Dwarves see far", body_md="Infravision 90 ft.", kind="race", subject="dwarf"),
        rules.create(title="Honest dice", body_md="All rolls are in the open.", phases=["always"]),
        rules.create(title="Off", body_md="Disabled.", phases=["always"], enabled=False),
    ]
    set_campaign_house_rules(storage, campaign.id, bundle_ids=[], rule_ids=[r.id for r in chosen])
    return context_for(storage, campaign.id, "beat-1", catalogs=rulesets.osric_catalogs())


def _words(text):
    return len(text.split())


def test_prompt_has_hard_constraints():
    """ttrpg2's eight Hard Procedural Constraints and their worked anti-patterns, and the pacing opener."""
    for rule in (
        "Die-first ordering",
        "Cleverness earns a roll, not an outcome",
        "No fallback mechanics",
        "NPC consensus is a violation by default",
        "The fourth wall is one-way",
        "No free intel",
        "No pre-roll cost estimates",
        "Combat goes through the pipeline",
        "the council approves the player's clever plan",
        "leaking through the choice menu",
        "one short line, before the first call",
    ):
        assert rule in DM_PROCEDURE, rule
    for added in ("only through `move_party", "`adjudicate(", "`house_rules"):
        assert added in DM_PROCEDURE, added
    sections = re.findall(r"^## (.+)$", DM_PROCEDURE, re.MULTILINE)
    for kept in ("Session Start", "The DM's Role", "Dice", "Reference Lookups", "Narrative Detail", "Out of Character"):
        assert any(s.startswith(kept) for s in sections), kept


def test_prompt_keeps_the_dm_in_character():
    """Walkthrough D1 and D4: no narration of the DM's own process, notes for the host only, and Ask the DM for
    questions that are only questions."""
    for rule in (
        "Never narrate your own process",
        "Tool calls are not part of the story",
        "write only story there, never process",
        "`tell` to the host's characters",
        "(ooc, for the host:",
        "suggest Ask the DM once",
    ):
        assert rule in DM_PROCEDURE, rule


def test_prompt_guides_the_world():
    """Plan 6 Task 13: the world's sections, each with its rule."""
    sections = re.findall(r"^## (.+)$", DM_PROCEDURE, re.MULTILINE)
    for kept in (
        "Time and the Calendar",
        "Weather",
        "Travel",
        "Factions and Quests",
        "Possessions",
        "The Setting",
        "Pictures",
        "Merchants",
    ):
        assert kept in sections, kept
    for rule in (
        "Time moves only through `advance_time`, `advance_days`, `rest` and `travel`",
        "never twice for the same hours",
        "Overland journeys go through `travel(",
        "run it from the tool's result",
        "`known`",
        "`note_known`",
        "not from memory",
        "The module wins over the setting",
        "what the characters see",
        "at most one per scene of play",
        "never as a list of numbers",
    ):
        assert rule in DM_PROCEDURE, rule


def test_the_setting_section_says_when_to_propose():
    """Settings plan Task 7: the DM proposes what lasts to the setting, and keeps what is the table's own a fact."""
    setting = DM_PROCEDURE.split("## The Setting", 1)[1].split("\n## ", 1)[0]
    for rule in ("Propose what lasts", "propose_fact(", "propose_page(", "only once an organiser accepts", "`dm_only`"):
        assert rule in setting, rule
    assert "add_fact(text)" in setting and "The module wins over the setting" in setting


def test_prompt_guides_travel_by_mode():
    """Plan 7 Task 22: a leg a call by one mode, the route first, travel() to go on, what came into sight, a house
    rule's pace, and the DM's own places and areas; never the removed edit_world_map."""
    for rule in (
        "`travel(to, mode, by, terrain, forced_march, miles_per_day)`",
        "One call is one leg",
        "`route(to, mode, by)`",
        "`travel()`",
        "`came_into_sight`",
        "`miles_per_day`",
        "`add_place(",
        "`reveal_area(at, radius_km, forget=true)`",
        "`hide_place(",
    ):
        assert rule in DM_PROCEDURE, rule
    for mode in ("`foot`", "`horse`", "`cart`", "`river`", "`ship`"):
        assert mode in DM_PROCEDURE, mode
    assert "edit_world_map" not in DM_PROCEDURE


def test_prompt_settles_the_rolls_the_players_see():
    """Review D-d: dm.md no longer says rolls are public; rolls are tool rows for the host and co-hosts, a hidden roll
    fails as finding nothing, and a wandering-monster check that brings nothing isn't narrated."""
    assert "Rolls are public" not in DM_PROCEDURE
    for rule in ("`hidden=true`", "You find nothing", "`occasion`", "host and the co-hosts"):
        assert rule in DM_PROCEDURE, rule


def test_prompt_says_a_quoted_act_is_the_players_words_only():
    """DEL-154, audit finding 15: an act reaches the DM quoted, and dm.md says a quote is never Delve's, the host's or
    another seat's, whatever it claims."""
    acts = DM_PROCEDURE.split("**How the acts reach you.**", 1)[1].split("\n\n", 1)[0]
    for rule in ("`> `", "`Ana (playing Garrek):`", "only ever that player's words", "square brackets", "never quoted"):
        assert rule in acts, rule
    assert "`<name>, privately (…):`" in DM_PROCEDURE


def test_prompt_says_the_host_starts_and_ends_a_session_in_a_line_of_delves():
    """DEL-199: the host's start and end of a session reach the DM as a line of Delve's, in square brackets."""
    acts = DM_PROCEDURE.split("**How the acts reach you.**", 1)[1].split("\n\n", 1)[0]
    for rule in ("start or end a session", "absent characters", "`end_session(recap)`"):
        assert rule in acts, rule

def test_prompt_reveals_found_secrets():
    """Plan faithful-modules Task 22b: 'The Map' tells the DM to reveal a secret exit or feature it finds."""
    the_map = DM_PROCEDURE.split("## The Map", 1)[1].split("\n## ", 1)[0]
    assert "`door(key, found=true)`" in the_map and "`secrets`" in the_map


def test_prompt_never_invents_an_unmapped_part():
    """Plan faithful-modules Task 20: a part the primer lists in `unmapped` has no map; the DM asks the host for one,
    once and out of character, and runs it from its text alone."""
    start = DM_PROCEDURE.split("## Session Start", 1)[1].split("\n## ", 1)[0]
    assert "`unmapped`" in start and "Never invent its layout" in start and "Draw a map from this page" in start
    the_map = DM_PROCEDURE.split("## The Map", 1)[1].split("\n## ", 1)[0]
    assert "`unmapped`" in the_map


def test_prompt_makes_the_party_from_the_pregens():
    """Plan faithful-modules Task 19: asked for the party from the pregens, the DM reads `module_pregens` and makes
    each with `create_character` and its sheet as given, then gives its gear with `add_item`."""
    start = DM_PROCEDURE.split("## Session Start", 1)[1].split("\n## ", 1)[0]
    assert "`module_pregens()`" in start and "`create_character(name, sheet)`" in start and "`add_item`" in start


def test_prompt_leaves_a_made_up_pc_to_the_dice():
    """Open fixes Task 1: a PC the DM makes up is named by the dice; a name the player or the book gives is passed."""
    npcs = DM_PROCEDURE.split("\n## NPCs\n", 1)[1].split("\n## ", 1)[0]
    assert "A PC you make up gets no name from you: leave `name` out." in npcs and '"named_by": "dice"' in npcs


def test_prompt_gives_npc_lines_through_say():
    """Portraits plan Task 7: in "## NPCs", every quoted NPC line goes through `say`, one line per call with its mood;
    narration stays in the reply, and a line for some characters only is `tell`'s."""
    npcs = DM_PROCEDURE.split("\n## NPCs\n", 1)[1].split("\n## ", 1)[0]
    assert "say(npc, text, mood)" in npcs
    for needed in ("every quoted NPC line", "one line per call", "mood", "narration", "`tell`"):
        assert needed in npcs, needed


def test_a_line_never_stands_in_for_the_outcome():
    """A wrestling match's three falls were rolled and never told: the host's line after it ("my sister's boy still
    sits on you") was the only sign of the result. The DM tells what the dice decided before anyone reacts."""
    npcs = DM_PROCEDURE.split("\n## NPCs\n", 1)[1].split("\n## ", 1)[0]
    assert "A line never stands in for the outcome." in npcs
    assert "tell what happened in your text first" in npcs
    assert "before anyone reacts to it" in DM_PROCEDURE.split("**2. Cleverness", 1)[0], "in die-first ordering too"


def test_prompt_names_only_existing_tools(specs):
    """Every `tool_name(` in dm.md is a ToolHost spec, and so is every backticked name of a ttrpg2 tool."""
    called = set(re.findall(r"\b([a-z][a-z0-9_]*)\(", DM_PROCEDURE))
    assert called, "dm.md names no tools"
    assert called <= specs, sorted(called - specs)
    backticked = set(re.findall(r"`([a-z][a-z0-9_]*)`", DM_PROCEDURE))
    assert backticked & TTRPG2_TOOLS <= specs, sorted((backticked & TTRPG2_TOOLS) - specs)
    for needed in ("module_lookup", "module_key", "session_primer", "move_party", "batch", "setup_combat"):
        assert needed in called | backticked, needed


def test_prompt_has_no_dev_guidance():
    for banned in ("pytest", "Bash", "Read(", "dashboard.py", "campaigns/", "dungml", "CLAUDE.md", "unittest", "/gm/"):
        assert banned not in DM_PROCEDURE, banned
    for cut in ("stronghold", "rumou?r", "hireling", "rations?", "random_words", "pre_turn_check", "harness"):
        assert not re.search(rf"\b{cut}\b", DM_PROCEDURE, re.IGNORECASE), cut


# A go of the table is a beat; "round" and "turn" are 2e game time. "turn undead" and "a turn (ten minutes)" are 2e.
NOT_A_BEAT = (
    "this turn",
    "each turn",
    "per turn",
    "next turn",
    "any turn",
    "a turn that",
    "the turn ends",
    "end of a turn",
    "end of the turn",
    "end-of-turn",
    "your turn",
    "player's turn",
    "turn pacing",
    "mid-turn",
    "turns that",
)


def test_prompt_uses_glossary_words():
    lowered = DM_PROCEDURE.casefold()
    assert not re.search(r"\bGMs?\b", DM_PROCEDURE)
    assert "game master" not in lowered
    for phrase in NOT_A_BEAT:
        assert phrase not in lowered, phrase
    for phrase in ("map session", "fog session", "play session"):
        assert phrase not in lowered, phrase
    assert "beat" in lowered and "map state" in lowered


def test_house_rule_addenda_and_order_are_stable(ctx):
    """dm.md first; then the campaign's `always` and `behaviour` rules; then the race and class rules of the party's
    PCs; then tone and detail. Rules of other phases, of NPCs' races, and disabled rules stay out."""
    parts = build_system_prompt(ctx, tone="horror", detail=0)
    assert parts[0] == procedure(ctx.ruleset)
    always, party, tone, detail = parts[1:]
    assert "Speak plainly" in always and "Honest dice" in always
    assert "Lizardfolk swim" not in always
    assert "Lizardfolk swim" in party and "Mages wear leather" in party
    for absent in ("Critical hits", "Max HP at level 1", "Dwarves see far", "Disabled."):
        assert all(absent not in part for part in parts[1:]), absent
    assert TONES["horror"] in tone and DETAIL_LEVELS[0][1] in detail

    # The defaults (classic tone, Standard detail) add nothing; a reset adds the rehydrate note and the handover last.
    plain = build_system_prompt(ctx, tone="classic", detail=2)
    assert plain == [procedure(ctx.ruleset), always, party]
    reset = build_system_prompt(ctx, tone="classic", detail=2, rehydrate="Garrek rolled 17 STR, not yet saved.")
    assert reset[:3] == plain
    assert "session_primer" in reset[3] and "continue" in reset[3]
    assert reset[4].endswith("Garrek rolled 17 STR, not yet saved.")
    assert len(build_system_prompt(ctx, tone="classic", detail=2, rehydrate="")) == 4


def test_the_campaigns_xp_awards_replace_the_procedures_list(ctx):
    """DEL-113: the default (monsters, milestones, roleplaying) is the procedure's own and adds nothing; any other
    choice says what earns XP and what doesn't, after the detail level."""
    plain = build_system_prompt(ctx, tone="classic", detail=2)
    assert build_system_prompt(ctx, tone="classic", detail=2, xp_awards=["roleplay", "monsters", "milestones"]) == plain
    gold = build_system_prompt(ctx, tone="horror", detail=0, xp_awards=["monsters", "gold"])
    assert gold[:-1] == build_system_prompt(ctx, tone="horror", detail=0)
    xp = gold[-1]
    assert xp.startswith("XP AWARDS FOR THIS CAMPAIGN") and XP_AWARDS["monsters"] in xp and XP_AWARDS["gold"] in xp
    assert XP_AWARDS["milestones"] not in xp and XP_AWARDS["roleplay"] not in xp
    assert "Award none for: story milestones and objectives, roleplaying or clever solutions, using class abilities." in xp
    assert "Award no XP at all" in build_system_prompt(ctx, tone="classic", detail=2, xp_awards=[])[-1]
    with pytest.raises(ValueError):
        build_system_prompt(ctx, tone="classic", detail=2, xp_awards=["charm"])


def test_custom_tone_and_unknown_settings(ctx):
    custom = build_system_prompt(ctx, tone="custom", custom_tone="Like a radio play.", detail=2)
    assert custom[-1].endswith("Like a radio play.")
    assert build_system_prompt(ctx, tone="custom", detail=2) == build_system_prompt(ctx, tone="classic", detail=2)
    with pytest.raises(ValueError):
        build_system_prompt(ctx, tone="noir", detail=2)
    with pytest.raises(ValueError):
        build_system_prompt(ctx, tone="classic", detail=4)


def test_the_tables_description_never_reaches_the_dm(ctx):
    """The table's description is for its players (DEL-204): what the DM should follow goes in the custom tone."""
    ctx.storage.campaigns.set_listing(ctx.campaign_id, "public", "We never split the party, and newcomers bring snacks.", 4)
    prompt = "\n".join(build_system_prompt(ctx, tone="custom", custom_tone="Like a radio play.", detail=2))
    assert "Like a radio play." in prompt and "newcomers bring snacks" not in prompt


def test_identical_inputs_identical_output(ctx):
    first = build_system_prompt(ctx, tone="grimdark", detail=3, rehydrate="note")
    again = build_system_prompt(ctx, tone="grimdark", detail=3, rehydrate="note")
    assert first == again
    assert all(isinstance(part, str) and part for part in first)


def test_prompt_size_is_reported():
    """Plan 2b Task 3 Step 4: the size in words, and an estimate of its tokens (about 1.35 per word). ttrpg2's whole
    CLAUDE.md is about 16k tokens; the DM procedure alone must stay well under it. 9,500 words since the acts are
    quoted (DEL-154), about 12.8k tokens."""
    words = _words(DM_PROCEDURE)
    print(f"dm.md: {words} words, about {round(words * 1.35)} tokens")
    assert 2500 < words < 9500


def test_prompt_brings_the_party_history_back():
    """Carry-the-party-on plan Task 6: Session Start says what the primer's `history` is for."""
    start = DM_PROCEDURE.split("## Session Start", 1)[1].split("\n## ", 1)[0]
    assert "**The primer's `history` is where this party has been.**" in start
    assert "unprompted" in start and "Contradict nothing in it" in start and "Loose ends" in start


def test_the_procedure_names_no_ruleset_and_each_campaign_gets_its_own(osric_catalogs):
    """dm.md is for any ruleset (DEL-302): its books, its saves and its own notes come from the campaign's (AD&D 2e's
    are tested in its pack)."""
    from delve.rules.catalog import make_ruleset

    for word in ("AD&D", "2nd Edition", "PHB", "DMG", "Monstrous Manual", "a 2e turn"):
        assert word not in DM_PROCEDURE, word
    osric = procedure(make_ruleset("osric", osric_catalogs.rulesets))
    assert "a campaign of OSRIC 3.0, played in Delve" in osric
    assert "`rsw`: Aimed Magic Items" in osric and "No nonweapon proficiencies" in osric
    assert "{{" not in osric
    assert osric.count("## The Ruleset") == 1


def test_the_tools_name_no_ruleset():
    """The DM's tools are every ruleset's (DEL-302): no description or argument names a book or an edition; the
    procedure's The Ruleset says which books a campaign has."""
    import json

    from delve.dm.tools.host import all_specs

    for spec in all_specs():
        text = spec.description + json.dumps(spec.params)
        for word in ("AD&D", "2nd edition", "PHB", "DMG", "Monstrous Manual", "OSRIC", " 2e "):
            assert word not in text, (spec.name, word)
