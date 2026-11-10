"""Ask the DM (spec §7.3): a question out of band, answered by a side pass with no tools, so it never holds up the
table and can change nothing.

The side pass is told the question, the asker's own characters as they know themselves (spec §7.3: never another
seat's), the time of day, what happened this session as the asker saw it (the session's story entries that `can_see`
lets them see, so never a tell to another seat, up to `SESSION_CHARS`), the last recap they saw, the table's text of
a carried party's history (never the DM's), the app's Help for a question about Delve itself, with the asker's role
(DEL-221, `delve.play.help_topics`), and up to three paragraphs of the rules for the question. An observer's question
comes with no characters, and the host's with the PCs nobody has claimed besides their own. It answers from the
rules, the setting and what the characters know, never from the module, and never names a room by its key number: it
is never given module text, DM secrets, NPC notes, hidden rooms or the DM log, so it can't leak them. With a setting,
up to `SETTING_HITS` of its hits for the question follow the rules (settings plan Task 6), read through the setting
layer as a seat reads it: the install's pages and facts and this campaign's proposals, never anything DM-only.

The question is put into English first, and the side pass answers in English (spec §7.7, stored state stays English).
The question and its answer are stored as `ask` and `answer` story entries outside any beat, for the asker's seat
only (`{"seats": [asker]}`), and published for it alone; playing alone, that is the owner's seat. The question keeps
the asker's own words, and the answer is translated into the asker's language (`delve.play.translate`). Its usage
goes into the DM log as an `ask` row under no beat, `{"type": "ask", "usage": {input_tokens, output_tokens,
cost_usd}}` (null when the provider reported none), so the organiser's costs count every Ask; it holds no words.
"""

from __future__ import annotations

import re
from dataclasses import asdict
from typing import Any

from delve.dm.provider import Usage
from delve.domain.campaigns import Seat, StoryEntry
from delve.play import translate
from delve.play.audience import for_seats, seat_controls
from delve.play.context import PlayError, context_for
from delve.play.help_topics import help_for
from delve.play.sessions import primer
from delve.play.setting_layer import layer_for
from delve.play.table import AppServices, add_entry, log_dm_event, story, told
from delve.rules.ruleset import NO_LOOKUPS
from delve.setting.catalog import make_setting
from delve.setting.text import wiki_markdown

__all__ = ["RECENT", "SESSION_CHARS", "SETTING_HITS", "SETTING_PAGE_CHARS", "AskFailed", "ask", "ask_prompt"]

RULES_SNIPPETS = 3
SETTING_HITS = 3
"""At most this many of the setting's hits for the question."""
SETTING_PAGE_CHARS = 600
"""At most this many characters of a page the question names, after its hit."""
RECENT = 8
"""At least this many of the asker's last story entries, as "WHAT HAPPENED THIS SESSION", from before it if need be."""
SESSION_CHARS = 8000
"""At most this many characters of the session's entries; past it, the newest that fit (but never fewer than
`RECENT`)."""
_PAGE = 200
# The story entries that say what happened: not tool rows, images, the DM's errors.
_RECENT_KINDS = frozenset({"player_act", "dm_text", "say", "recap", "talk", "ask", "answer"})

ASK_RULES = (
    "You are the Dungeon Master's assistant at a table playing {ruleset}, answering a player's question out of band: "
    "it is not an action and changes nothing in the game. Answer from the rules, the setting and what the characters "
    "know; never from the module. You don't know the module's rooms, monsters, secrets or plot: if the answer would "
    "need them, say that the characters will have to find out in play. When the question is about the rules, give "
    "the actual figures from the rulebook paragraphs below (the numbers, dice and table rows that apply to the "
    "asker's characters), and never say that the DM should confirm: you are the one answering. Answer in a few "
    "sentences, plainly, in English. Don't narrate, don't roll dice, and don't decide what happens. Never name a room "
    "by a key number ('room 4'): name it as the characters know it. Answer only what is asked; don't volunteer more "
    "of the setting than the question needs. A question about Delve itself, the app (its screens, buttons, seats, "
    "invites, sessions, settings), is not a rules question: answer it from HOW DELVE WORKS below, with the steps for "
    "the asker's role, and name the Help topic they are in. If the Help doesn't say, say so; never invent a button."
)

# Words too common to search the rules for.
_STOPWORDS = frozenset(
    {
        "and", "are", "can", "does", "for", "from", "has", "have", "how", "its", "nor", "not", "our", "that", "the",
        "their", "them", "then", "there", "this", "was", "what", "when", "where", "which", "who", "why", "will",
        "with", "you", "your", "also",
    }
)  # fmt: skip


class AskFailed(PlayError):
    """The side pass gave no answer: its provider failed or is missing."""


async def ask(services: AppServices, campaign_id: str, question: str, *, asker: str) -> str:
    """Ask the DM `question` for the campaign: the side pass's answer, stored with the question in the story for the
    seat `asker` (its id) alone."""
    question = question.strip()
    if not question:
        raise PlayError("Ask a question.")
    if services.storage.campaigns.get(campaign_id) is None:
        raise PlayError(f"No campaign '{campaign_id}'.")
    seat = services.storage.seats.get(asker)
    if seat is None or seat.campaign_id != campaign_id:
        raise PlayError(f"No seat '{asker}' at this table.")
    english = await translate.to_english(services, campaign_id, question, seat.language)
    provider, choice = services.side(campaign_id)
    used: list[Usage] = []
    try:
        prompt = ask_prompt(services, campaign_id, english.text, seat)
        answer = (await provider.side_call(prompt, choice, on_usage=used.append)).strip()
    except Exception as error:  # any provider failure is the same refusal to the player
        raise AskFailed("The DM couldn't answer the question.", "Ask again in a moment.") from error
    if not answer:
        raise AskFailed("The DM gave no answer.", "Ask again in a moment.")
    storage = services.storage
    audience = for_seats([asker])
    words = {"text": english.text, "original": question, "language": seat.language}
    if english.failed:
        words["translation"] = "failed"
    with storage.transaction():
        asked = add_entry(storage, campaign_id, None, "ask", words, audience)
        answered = add_entry(storage, campaign_id, None, "answer", {"text": answer}, audience)
        log_dm_event(storage, campaign_id, None, {"type": "ask", "usage": asdict(used[-1]) if used else None})
    for entry in (asked, answered):
        told(services, entry)
        translate.translate_entry(services, entry, also=[asker])
    return answer


def ask_prompt(services: AppServices, campaign_id: str, question: str, asker: Seat) -> str:
    """The side pass's prompt: the rule of answering, the asker's characters, what happened this session, the last
    recap, the party's earlier history as the table knows it, the rules for the question, and the question."""
    ruleset = context_for(services.storage, campaign_id, "ask", catalogs=services.catalogs).ruleset
    parts = [ASK_RULES.replace("{ruleset}", ruleset.title if ruleset is not None else "a roleplaying game")]
    known = _what_the_characters_know(services, campaign_id, asker)
    if known:
        parts.append(known)
    app = help_for(_words(question), asker.role)
    if app:
        parts.append(app)
    session = _what_happened_this_session(services, campaign_id, asker)
    if session:
        parts.append(session)
    recap = _last_recap(services, campaign_id, asker)
    if recap:
        parts.append(recap)
    history = _earlier_history(services, campaign_id)
    if history:
        parts.append(history)
    rules = _rules(services, campaign_id, question)
    if rules:
        parts.append(rules)
    setting = _setting(services, campaign_id, question)
    if setting:
        parts.append(setting)
    parts.append(f"THE PLAYER'S QUESTION:\n{question}")
    return "\n\n".join(parts)


def _what_the_characters_know(services: AppServices, campaign_id: str, asker: Seat) -> str:
    """The sheets of the PCs the asker plays, as `primer` digests them, and the time of day. Nothing about other
    seats' characters, NPCs, places or events."""
    ctx = context_for(services.storage, campaign_id, "ask", catalogs=services.catalogs)
    if ctx.lookups is NO_LOOKUPS:
        return ""
    # A question reads the campaign and never writes it (DEL-161): no weather rolled, no factions seeded.
    digest = primer(ctx, roll_weather=False)
    own = seat_controls(services.storage, asker)
    party = [pc for pc in digest["party"] if pc["id"] in own]
    lines = [f"THE ASKER'S CHARACTERS (what they know of themselves), day {digest['day']}, {digest['period']}:"]
    for pc in party:
        lines.append(f"- {_pc_line(pc)}")
    if not party:
        lines.append("- (no characters of the asker)")
    return "\n".join(lines)


def _what_happened_this_session(services: AppServices, campaign_id: str, asker: Seat) -> str:
    """The story entries with words of the current session (those at or after its `started_at`; every one before
    the first session starts) that `story` lets the asker's seat see, oldest first, in English. Past `SESSION_CHARS`
    only the newest that fit; and never fewer than the last `RECENT`, from before the session if need be."""
    started = _session_started(services, campaign_id)
    lines: list[str] = []
    used, cut, before = 0, False, None
    while True:
        page = story(services.storage, campaign_id, asker, before_seq=before, limit=_PAGE)
        for entry in reversed(page["entries"]):
            line = _story_line(entry)
            if not line:
                continue
            if len(lines) >= RECENT:
                if entry.at < started:
                    break
                if used + len(line) > SESSION_CHARS:
                    cut = True
                    break
            lines.append(line)
            used += len(line)
        else:
            if page["has_more"] and page["entries"]:
                before = page["entries"][0].seq
                continue
        break
    if not lines:
        return ""
    head = ["WHAT HAPPENED THIS SESSION (as the asker saw it, oldest first):"]
    if cut:
        head.append("(earlier entries left out)")
    return "\n".join([*head, *(f"- {line}" for line in reversed(lines))])


def _session_started(services: AppServices, campaign_id: str) -> str:
    """When the campaign's current session started: "" (the whole story) before its first session starts."""
    state = services.storage.campaign_states.get(campaign_id)
    session = services.storage.sessions.get(campaign_id, state.session)
    return session.started_at if session is not None else ""


def _last_recap(services: AppServices, campaign_id: str, asker: Seat) -> str:
    """The text of the last `recap` story entry the asker's seat may see, if a session has a recap at all."""
    if not any(s.recap_md for s in services.storage.sessions.list(campaign_id)):
        return ""
    before = None
    while True:
        page = story(services.storage, campaign_id, asker, before_seq=before, limit=_PAGE)
        for entry in reversed(page["entries"]):
            text = str(entry.payload.get("text") or "").strip() if entry.kind == "recap" else ""
            if text:
                return f"LAST RECAP (of the last session):\n{text}"
        if not page["has_more"] or not page["entries"]:
            return ""
        before = page["entries"][0].seq


def _earlier_history(services: AppServices, campaign_id: str) -> str:
    """The table's text of the campaign's history, whenever it has one (a failed Write again keeps it); never the
    DM's, which may hold secrets."""
    history = services.storage.histories.get(campaign_id)
    if history is None or not history.table_md.strip():
        return ""
    return f"THE PARTY'S EARLIER HISTORY (what the table knows):\n{history.table_md}"


def _story_line(entry: StoryEntry) -> str:
    if entry.kind not in _RECENT_KINDS:
        return ""
    text = str(entry.payload.get("text") or "").strip()
    if not text:
        return ""
    if entry.kind == "dm_text":
        return f"The DM: {text}"
    if entry.kind == "say":
        speaker = entry.payload.get("speaker")
        name = str(speaker.get("name") or "An NPC") if isinstance(speaker, dict) else "An NPC"
        return f'{name} said: "{text}"'
    if entry.kind == "recap":
        return f"Recap: {text}"
    if entry.kind == "ask":
        return f"The asker asked the DM: {text}"
    if entry.kind == "answer":
        return f"The DM answered: {text}"
    name = str(entry.payload.get("name") or "A player")
    return f"{name} (table talk): {text}" if entry.kind == "talk" else f"{name}: {text}"


def _pc_line(pc: dict[str, Any]) -> str:
    levels = "/".join(str(n) for n in pc["levels"].values()) if pc["levels"] else ""
    who = " ".join(part for part in (pc["race"], pc["cls"], levels) if part)
    facts = [f"HP {pc['hp']}/{pc['hp_max']}", f"AC {pc['ac']}", f"THAC0 {pc['thac0']}"]
    if pc["conditions"]:
        facts.append("conditions: " + ", ".join(pc["conditions"]))
    if pc["spells"]["memorized"]:
        facts.append("spells memorized: " + ", ".join(pc["spells"]["memorized"]))
    if pc["inventory"]:
        facts.append("carrying: " + pc["inventory"])
    return f"{pc['name']}" + (f", {who}" if who else "") + ": " + "; ".join(facts)


def _rules(services: AppServices, campaign_id: str, question: str) -> str:
    """Up to three paragraphs of the campaign's ruleset's rulebooks that match the question's words, best first."""
    lookups = context_for(services.storage, campaign_id, "ask", catalogs=services.catalogs).lookups
    words = _words(question)
    if not words:
        return ""
    query = " OR ".join(f'"{word}"' for word in words)
    try:
        found = lookups.rules_search(query, limit=RULES_SNIPPETS)
    except ValueError:
        return ""
    if not found:
        return ""
    lines = ["FROM THE RULEBOOKS (searched for the question):"]
    for rule in found[:RULES_SNIPPETS]:
        where = ", ".join(part for part in (rule["source"].upper(), rule["chapter"], rule["section"]) if part)
        lines.append(f"- {where}: {rule['snippet']}")
    return "\n".join(lines)


def _setting(services: AppServices, campaign_id: str, question: str) -> str:
    """Up to `SETTING_HITS` hits of the campaign's setting for the question, as a seat may read them: all its words
    at once, else each word of 4 letters or more alone, longest first. A hit whose title the question names is
    followed by the start of its page, as Markdown."""
    campaign = services.storage.campaigns.get(campaign_id)
    shipped = None
    if campaign is not None:
        shipped = make_setting(campaign.setting, services.catalogs.settings)
    layer = layer_for(services.storage, shipped, campaign_id=campaign_id, dm=False)
    words = _words(question)
    if layer is None or not words:
        return ""
    hits = layer.search(" ".join(words), SETTING_HITS)
    if not hits:
        seen: set[str] = set()
        for word in sorted((w for w in words if len(w) >= 4), key=len, reverse=True):
            for hit in layer.search(word, SETTING_HITS):
                if hit.key not in seen and len(hits) < SETTING_HITS:
                    seen.add(hit.key)
                    hits.append(hit)
    if not hits:
        return ""
    asked = question.casefold()
    lines = [f"FROM THE SETTING, {layer.title} (searched for the question):"]
    for hit in hits:
        lines.append(f"- {hit.title}: {hit.text}")
        page = layer.page(hit.title) if hit.kind != "fact" and hit.title.casefold() in asked else None
        if page is not None:
            text = wiki_markdown(page.text) if page.format == "wiki" else page.text
            lines.append(text.strip()[:SETTING_PAGE_CHARS])
    return "\n".join(lines)


def _words(question: str) -> list[str]:
    """The question's words worth searching for, once each, in order: longer than 2 letters and not too common."""
    found = [w for w in re.findall(r"[^\W_]+", question.lower()) if len(w) > 2 and w not in _STOPWORDS]
    return list(dict.fromkeys(found))
