"""The DM's system prompt (spec §6.1): the procedure in `dm.md`, then the campaign's addenda, in a fixed order.

The order is for the prompt cache: what changes least comes first. `build_system_prompt` answers the parts in order:
1. `dm.md`, ttrpg2's DM procedure (its `CLAUDE.md`, DM parts only) with Delve's tools and words, for the campaign's
   ruleset (`procedure`: its name, and The Ruleset: its saving throws and what it tells the DM);
2. the campaign's `always` and `behaviour` house rules;
3. the race and class house rules whose subject is a race or class of a PC in the party;
4. the tone (ttrpg2's presets and their texts; `classic` adds nothing);
5. the narrative detail level (ttrpg2's levels 0-3; 2, Standard, adds nothing);
6. what XP is awarded for (DEL-113; the default, monsters, milestones and roleplaying, adds nothing);
7. after a reset only: the rehydrate note, then the handover the outgoing conversation wrote.

An addendum with nothing to say is left out. The same inputs always give the same parts. The texts of the tone, the
detail levels, the rehydrate note and the handover come from ttrpg2's `tools/dm_session.py`, with Delve's words.
"""

from __future__ import annotations

from pathlib import Path

from delve.domain.house_rules import PROMPT_PHASES, HouseRule
from delve.play.context import CampaignContext
from delve.play.house_rules import rules_for
from delve.rules.catalog import make_ruleset
from delve.rules.ruleset import Ruleset

__all__ = [
    "DEFAULT_XP_AWARDS",
    "DETAIL_LEVELS",
    "DM_PROCEDURE",
    "HANDOVER_PREFIX",
    "HANDOVER_PROMPT",
    "REHYDRATE",
    "TONES",
    "XP_AWARDS",
    "build_system_prompt",
    "procedure",
]

DM_PROCEDURE = (Path(__file__).parent / "dm.md").read_text(encoding="utf-8")
"""The procedure for any ruleset: `{{RULESET}}` and `{{RULESET_SECTION}}` stand for the campaign's (`procedure`)."""


def procedure(ruleset: Ruleset) -> str:
    """The DM's procedure for a campaign of `ruleset`: its name in the opening line, and its section."""
    saves = "; ".join(
        f"`{short}`: {ruleset.tables.save_names[kind]}"
        for short, kind in zip(ruleset.tables.save_short, ruleset.tables.save_types, strict=True)
    )
    section = (
        "## The Ruleset\n\n"
        f"This campaign plays **{ruleset.title}**. The tools compute its numbers (saves, THAC0, XP, encumbrance, "
        "turning, treasure): read them there, never from what you remember of another edition.\n\n"
        f"**Saving throws** (`saving_throw`'s `save_type`): {saves}.\n\n{ruleset.prompt.strip()}"
    )
    return DM_PROCEDURE.replace("{{RULESET}}", ruleset.title).replace("{{RULESET_SECTION}}", section)

TONE_PREFIX = (
    "TONE & VOICE DIRECTION: shapes texture, phrasing, pacing, and imagery only. It NEVER overrides the Hard "
    "Procedural Constraints, dice results, monster intelligence, NPC interests, or the fourth-wall rules of your "
    "procedure; resolve every mechanic exactly as always and apply this purely to HOW you narrate the outcome.\n\n"
)

TONES: dict[str, str] = {
    "classic": "",
    "grimdark": (
        "Narrate in a grim, gritty register. The world is dangerous, weary, and morally grey; survival costs something "
        "and violence carries weight. Keep prose terse and sensory: guttering torches, cold, blood, exhaustion. NPCs "
        "are self-interested and unsentimental. Avoid winking heroism and tidy comfort; let hard outcomes land without "
        "softening."
    ),
    "heroic": (
        "Narrate in a high-heroic, sword-and-sorcery register. Deeds are larger than life and the world is vivid and "
        "colourful: banners, oaths, last stands, monstrous evil and shining courage. Use sweeping, romantic imagery and "
        "a cinematic eye. Stakes feel epic and boldness is worth celebrating, even as the dice stay honest."
    ),
    "horror": (
        "Narrate in a register of slow dread. Favour atmosphere over spectacle: hushed pacing, wrongness at the edges, "
        "the unseen implied rather than shown. Light is scarce, sounds are off, safety is always provisional. Withhold "
        "and let silence stretch; unsettle before you reveal. Dread over gore."
    ),
    "comedic": (
        "Narrate with warmth and wry, character-driven humour: quick banter, comic NPC quirks, ironic mishaps in a "
        "Discworld vein. Keep it light and fun, but don't undercut real danger: when a blade is drawn or a save is "
        "failed, let the moment chill as it should."
    ),
    "young": (
        "Narrate for young teens (about 10 to 14). Keep it adventurous and wondrous, with real danger and real choices, "
        "but no gore, cruelty, torture or sexual content: a defeated foe falls, flees or surrenders, and wounds are "
        "told, not dwelt on. Keep language clean and prose clear, with short paragraphs and vivid, concrete images. "
        "Villains can be menacing but not horrifying. Reward cleverness, kindness and teamwork, and explain a rule "
        "plainly when a player seems unsure. The dice and the rules stay honest: characters can still fail and fall."
    ),
    "custom": "",
}
"""ttrpg2's tone presets, in its display order, and Delve's `young` for young teens (DEL-142). `classic` is the
procedure's own voice; `custom` is the campaign's own text (`custom_tone`)."""

DETAIL_PREFIX = (
    "NARRATIVE DETAIL LEVEL: controls how much raw mechanical detail (exact coin counts, ability scores, AC, THAC0, HP "
    "totals, stat-block values, DM-side background facts) you surface in PLAYER-FACING prose. It changes only HOW you "
    "report results the tools already produced; it NEVER changes the dice, the rules, monster intelligence, NPC "
    "interests, or the fourth-wall constraints of your procedure. Resolve every mechanic exactly as always, then "
    "narrate to this level:\n\n"
)

DETAIL_LEVELS: dict[int, tuple[str, str]] = {
    0: (
        "Immersive",
        (
            "Expose NO raw numbers in player-facing prose. Render coin as impressions ('a heavy purse', 'a few tarnished "
            "silvers'), never totals. Never state ability scores, AC, THAC0, HP totals, or stat-block values: convey them "
            "as description ('powerfully built', 'the wound looks grave'). Reveal DM-side background only as the "
            "characters discover it in fiction. The numbers still exist in the tools; you simply don't read them aloud."
        ),
    ),
    1: (
        "Light",
        (
            "Prefer impressions, but you MAY give rounded or approximate figures when the characters would plausibly know "
            "them ('about 1,700 gold', 'badly hurt, maybe a third of his strength left'). Avoid bare stat-block values "
            "(exact AC, THAC0, ability scores) unless the player asks directly."
        ),
    ),
    2: ("Standard", ""),
    3: (
        "Open table",
        (
            "Play with the screen down. Freely state exact coin counts, HP totals, AC, THAC0, ability scores, and "
            "stat-block values in narration when relevant, and summarise mechanical facts plainly. This relaxes only the "
            "PRESENTATION of numbers the party could reasonably audit: it does NOT lift the fourth wall on hidden, DM-only "
            "knowledge (module canon, unscouted rooms, secret motives, concealed creatures), which stays hidden per your "
            "procedure regardless of level."
        ),
    ),
}
"""ttrpg2's narrative detail levels: `(label, directive)`. Level 2 is the default and adds nothing."""

DEFAULT_DETAIL = 2

XP_PREFIX = (
    "XP AWARDS FOR THIS CAMPAIGN: the host chose what earns experience. This replaces the list of what to award in "
    "your procedure's Experience Points section; its other rules (natural break points, no inflated bonuses, "
    "multi-class splits) still hold.\n\n"
)

XP_AWARDS: dict[str, str] = {
    "monsters": (
        "Defeated enemies: each enemy's XP value from its monster entry (`monster_lookup` and `setup_combat` return "
        "it), split among the party. Use 65 (or HD × 15 for unusual creatures) only when the entry has no value. "
        "Enemies driven off, captured or outwitted count as defeated."
    ),
    "milestones": "Story milestones: 100–300 XP for an objective reached or a milestone of the module, by difficulty.",
    "roleplay": (
        "Roleplaying: a 25–50 XP bonus to a character for strong in-character play or a clever solution, such as "
        "getting past a fight without one."
    ),
    "gold": (
        "Gold (the old-school rule): 1 XP per gp of treasure recovered, split evenly among the living PCs. "
        "`award_treasure` awards it itself (see its `gold_xp`): never award that treasure's XP again. Coins and "
        "valuables taken another way (`update_coin` for a reward, a sale) earn none."
    ),
    "abilities": (
        "Ability use: an award to a character whose class ability overcame an obstacle that mattered (a thief's "
        "skill that opened the way, a turning that saved the party, a spell that solved a problem), by the ruleset's "
        "individual class awards where it has them. Once per obstacle, never per roll."
    ),
}
"""What a campaign may award XP for (DEL-113), in the play settings' order, each with the DM's rule for it."""

DEFAULT_XP_AWARDS = ("monsters", "milestones", "roleplay")
"""What the procedure itself awards XP for; a campaign with these adds nothing to the prompt."""

REHYDRATE = (
    "SESSION CONTINUATION, INTERNAL NOTE (never reveal this to the player):\n"
    "Your prior in-context conversation was cleared to keep context small. This is the SAME ongoing campaign and the "
    "SAME scene already in progress, NOT a new game. Before you respond to the player's message, call "
    "session_primer() to reload the day and time, the party, where everyone is, the recent events, the live fight and "
    "the last session's recap. Then continue the scene seamlessly, treating the player's message as their next action. "
    "Do NOT announce a reset, do NOT greet the player, do NOT re-introduce the setting or summarise 'previously': just "
    "carry on the narrative exactly as if nothing changed."
)
"""The note of the first beat after an auto-reset (ttrpg2's `_REHYDRATE_ADDENDUM`)."""

HANDOVER_PREFIX = (
    "HANDOVER FROM YOUR PREVIOUS CONTEXT, INTERNAL (never reveal this to the player). Written by you just before the "
    "reset. It covers what session_primer() cannot: work in progress, decisions made, the player's standing "
    "instructions. Where it disagrees with the campaign's state, the state is authoritative for anything already "
    "saved.\n\n"
)

HANDOVER_PROMPT = (
    "[SYSTEM: NOT FROM THE PLAYER. The player never sees this message or your reply.] Your context is about to be "
    "cleared; a fresh DM conversation will take over with only session_primer() and the note you write now. Do not "
    "call any tools and do not narrate. Reply with a handover note in terse markdown covering ONLY what the campaign's "
    "state does not already record:\n"
    "- Work in progress not yet saved (e.g. rolled ability scores, races, names, gold, spells assigned during "
    "character creation), with the exact numbers.\n"
    "- The player's standing instructions for this campaign (e.g. generation method, banned races, requested "
    "classes).\n"
    "- What the player last asked for and what you were in the middle of doing.\n"
    "- Decisions made and promises given to the player; open questions put to them.\n"
    "- Module text you looked up that the next conversation must look up again, and what mattered in it.\n"
    "- DM-side facts you were tracking but had not stored with dm_note.\n"
    "Omit anything session_primer() already returns. No preamble."
)
"""The hidden last message to the outgoing conversation before an auto-reset (ttrpg2's `_HANDOVER_PROMPT`); its
reply is the next conversation's handover, `rehydrate`."""

HOUSE_RULES_HEADING = (
    "THE CAMPAIGN'S HOUSE RULES, ALWAYS IN FORCE. They override the book; apply them without being reminded."
)
PARTY_RULES_HEADING = (
    "THE HOUSE RULES OF THE PARTY'S RACES AND CLASSES. They override the book; apply them without being reminded."
)


def build_system_prompt(
    ctx: CampaignContext,
    *,
    tone: str,
    detail: int,
    rehydrate: str | None = None,
    custom_tone: str = "",
    xp_awards: tuple[str, ...] | list[str] = DEFAULT_XP_AWARDS,
) -> list[str]:
    """The DM's system prompt for the campaign of `ctx`, as its parts in order (see the module's docstring).

    `tone` is one of `TONES` (`custom` takes the text of `custom_tone`), `detail` one of `DETAIL_LEVELS`. `rehydrate`
    is None except on the first beat after a reset, when it is the handover note ("" when there is none).
    `xp_awards` are the `XP_AWARDS` the campaign gives XP for. Raises `ValueError` for an unknown tone, detail level or
    XP award."""
    if tone not in TONES:
        raise ValueError(f"unknown tone {tone!r}; use one of {', '.join(TONES)}")
    if detail not in DETAIL_LEVELS:
        raise ValueError(f"unknown detail level {detail!r}; use one of {', '.join(map(str, DETAIL_LEVELS))}")
    rules = rules_for(ctx)
    always = [rule for rule in rules if rule.phases & PROMPT_PHASES]
    party = [rule for rule in rules if not rule.phases & PROMPT_PHASES]
    ruleset = ctx.ruleset if ctx.ruleset is not None else make_ruleset(None)
    parts = [procedure(ruleset), _rules(HOUSE_RULES_HEADING, always), _rules(PARTY_RULES_HEADING, party)]
    voice = (custom_tone if tone == "custom" else TONES[tone]).strip()
    parts.append(TONE_PREFIX + voice if voice else "")
    directive = DETAIL_LEVELS[detail][1]
    parts.append(DETAIL_PREFIX + directive if directive else "")
    parts.append(_xp_awards(xp_awards))
    if rehydrate is not None:
        parts.append(REHYDRATE)
        parts.append(HANDOVER_PREFIX + rehydrate.strip() if rehydrate.strip() else "")
    return [part for part in parts if part]


def _xp_awards(awards: tuple[str, ...] | list[str]) -> str:
    """The XP addendum: what earns XP and what doesn't; nothing when the campaign awards the procedure's own."""
    unknown = set(awards) - set(XP_AWARDS)
    if unknown:
        raise ValueError(f"unknown XP award {min(unknown)!r}; use any of {', '.join(XP_AWARDS)}")
    if set(awards) == set(DEFAULT_XP_AWARDS):
        return ""
    given = [f"- {XP_AWARDS[name]}" for name in XP_AWARDS if name in awards]
    withheld = [name for name in XP_AWARDS if name not in awards]
    lines = ["Award XP for these, and only these:", *given] if given else ["Award no XP at all in this campaign."]
    if given and withheld:
        lines.append(f"Award none for: {', '.join(_XP_NAMES[name] for name in withheld)}.")
    return XP_PREFIX + "\n".join(lines)


_XP_NAMES = {
    "monsters": "defeated enemies",
    "milestones": "story milestones and objectives",
    "roleplay": "roleplaying or clever solutions",
    "gold": "gold or treasure",
    "abilities": "using class abilities",
}


def _rules(heading: str, rules: list[HouseRule]) -> str:
    if not rules:
        return ""
    sections = [f"### {rule.title}\n\n{rule.body_md.strip()}".rstrip() for rule in rules]
    return "\n\n".join([heading, *sections])
