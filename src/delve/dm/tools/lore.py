"""Lore: the setting's wiki (ttrpg2's wiki tool), the campaign's own facts (ttrpg2's `add_campaign_fact`,
`list_lore_facts`) and a search of what the campaign wrote down (ttrpg2 `search_lore`). The wiki is the reference
store's, read-only, read through the setting layer: with the install's own pages and facts and this campaign's
proposals, each result saying where it comes from (`origin`). A shipped page's text stays the wiki's markup. A
campaign's facts are DM-only, and so are the DM's proposals to the setting (`propose_page`, `propose_fact`, settings
plan Task 7)."""

from __future__ import annotations

import re
from typing import Any

from delve.dm.tools.schema import ToolSpec, boolean, integer, params, string, tool
from delve.domain.setting_content import Proposal
from delve.domain.world import CampaignFact
from delve.play import proposals
from delve.play.context import CampaignContext, PlayError
from delve.play.setting_layer import SettingLayer
from delve.setting.setting import Setting

SPECS: list[ToolSpec] = []

LOOKUP_LIMIT = 20
PAGE_CAP = 4000
SEARCH_HITS = 20
EXCERPT = 100
PROPOSAL_APPLIES = "In this campaign now; in every campaign once an organiser accepts it."


def _setting(ctx: CampaignContext) -> Setting:
    if ctx.setting is None:
        raise PlayError(
            "This campaign has no setting.",
            hint="Its world is the module's own: use module_lookup, and rules_lookup for the rules.",
        )
    return ctx.setting


@tool(
    SPECS,
    "setting_lookup",
    params(
        "kind",
        "query",
        kind=string(
            "place, realm, deity, character, organization, creature, item, plane, holiday, building or archfiend."
        ),
        query=string("Part of the name: 'Hardby', 'Boccob'; every row of the kind when empty."),
    ),
    mutates=False,
)
def setting_lookup(ctx: CampaignContext, kind: str, query: str) -> dict[str, Any]:
    """The setting's entries of one kind whose name contains the query (at most 20), each with its facts in one line.
    When exactly one matches, its wiki page comes too: its fields, its categories and its text, cut at 4,000
    characters. It holds the install's own pages and facts, and this campaign's proposals; `dm_only` marks what is for
    you alone. Find an entry by its words with setting_search."""
    setting = _setting(ctx)
    try:
        hits = setting.lookup(kind, query, LOOKUP_LIMIT)
    except ValueError:
        raise PlayError(
            f"{setting.title} has no kind '{kind}'.", hint=f"The kinds are {', '.join(setting.kinds())}."
        ) from None
    found: dict[str, Any] = {
        "kind": kind,
        "query": query,
        "count": len(hits),
        "results": [
            {"title": hit.title, "text": hit.text, "origin": hit.origin, "dm_only": hit.dm_only} for hit in hits
        ],
    }
    page = setting.page(hits[0].title) if len(hits) == 1 else None
    if page is not None:
        found["page"] = {
            "title": page.title,
            "kind": page.kind,
            "origin": "proposal" if page.campaign_id else page.origin,
            "dm_only": page.dm_only,
            "fields": page.fields,
            "categories": list(page.categories),
            "text": page.text[:PAGE_CAP],
            "truncated": len(page.text) > PAGE_CAP,
        }
    return found


@tool(
    SPECS,
    "setting_search",
    params(
        "query",
        query=string("Words the page holds: 'Circle of Eight', 'Iuz Old'. Every word must match."),
        limit=integer("At most this many pages (default 10).", minimum=1, maximum=50),
    ),
    mutates=False,
)
def setting_search(ctx: CampaignContext, query: str, limit: int = 10) -> dict[str, Any]:
    """Full-text search of the setting's wiki, best first: each page's title, its kind and an excerpt with the hits
    in <<…>>; a fact comes as kind "fact". It holds the install's own pages and facts, and this campaign's proposals;
    `dm_only` marks what is for you alone. Read a page with setting_lookup."""
    hits = _setting(ctx).search(query, limit)
    return {
        "query": query,
        "count": len(hits),
        "results": [
            {"title": hit.title, "kind": hit.kind, "excerpt": hit.text, "origin": hit.origin, "dm_only": hit.dm_only}
            for hit in hits
        ],
    }


def _fact(fact: CampaignFact) -> dict[str, Any]:
    return {"id": fact.id, "text": fact.text, "category": fact.category, "day": fact.day}


@tool(
    SPECS,
    "add_fact",
    params(
        "text",
        text=string("The fact, in a sentence that reads well alone: a victory, a death, a debt, a vow."),
        category=string("Free-form: victory, death, debt, rumour."),
    ),
    mutates=True,
    areas=(),
    player_visible=False,
)
def add_fact(ctx: CampaignContext, text: str, category: str = "") -> dict[str, Any]:
    """Record a fact of this campaign's own, on today's campaign day: what happened, what the party owes, what it
    vowed. DM-only; find it again with facts."""
    if not text.strip():
        raise PlayError("A fact needs its text.")
    state = ctx.storage.campaign_states.get(ctx.campaign_id)
    fact = CampaignFact(0, ctx.campaign_id, text.strip(), category.strip(), state.day if state else 1)
    added = ctx.storage.campaign_facts.add(fact)
    # In the event log too, so the session's summary has it (DEL-328).
    ctx.log("fact", fact_id=added.id, text=added.text, category=added.category)
    return {"fact": _fact(added)}


@tool(
    SPECS,
    "facts",
    params(query=string("Part of the fact's text, any case; every fact when empty.")),
    mutates=False,
    player_visible=False,
)
def facts(ctx: CampaignContext, query: str = "") -> dict[str, Any]:
    """The campaign's own facts, oldest first, with the day each was recorded."""
    found = ctx.storage.campaign_facts.list(ctx.campaign_id, query=query.strip())
    return {"count": len(found), "facts": [_fact(fact) for fact in found]}


def _layer(ctx: CampaignContext) -> SettingLayer:
    setting = _setting(ctx)
    assert isinstance(setting, SettingLayer), "the DM's setting is the setting layer"
    return setting


def _proposed(proposal: Proposal) -> dict[str, Any]:
    return {
        "proposal": {
            "id": proposal.id,
            "kind": proposal.kind,
            "title": proposal.title,
            "status": proposal.status,
            "dm_only": proposal.dm_only,
        },
        "applies": PROPOSAL_APPLIES,
    }


@tool(
    SPECS,
    "propose_page",
    params(
        "title",
        "text",
        title=string("The page's title: 'Zzyzx Hollow' for a new page, or an existing page's, such as 'Hardby'."),
        text=string("The page's text in Markdown; for an existing page, what to add to it (or its new text)."),
        kind=string(
            "place, realm, deity, character, organization, creature, item, plane, holiday, building or archfiend."
        ),
        dm_only=boolean("True when the players mustn't learn it."),
        mode=string(
            "For an existing page: append (the default) adds the text, replace puts it in the page's place.",
            enum=["append", "replace"],
        ),
    ),
    mutates=True,
    areas=(),
    player_visible=False,
)
def propose_page(
    ctx: CampaignContext, title: str, text: str, kind: str = "", dm_only: bool = False, mode: str = "append"
) -> dict[str, Any]:
    """Propose a lasting page of the world to the setting: a new village, an NPC's fate, a homebrew deity. A title the
    setting has already makes it an edit of that page. Never what matters only to this table: use add_fact. It holds
    in this campaign at once, and in every campaign once an organiser accepts it; a second proposal of the same page
    joins the first."""
    layer = _layer(ctx)
    if not text.strip():
        raise PlayError("A proposal needs its text.")
    if kind and kind not in layer.kinds():
        raise PlayError(f"{layer.title} has no kind '{kind}'.", hint=f"The kinds are {', '.join(layer.kinds())}.")
    if not " ".join(title.split()):
        raise PlayError("A proposal of a page needs its title.")
    return _proposed(
        proposals.propose_page(
            ctx.storage, layer, ctx.campaign_id, title, text.strip(), kind=kind, dm_only=dm_only, mode=mode
        )
    )


@tool(
    SPECS,
    "propose_fact",
    params(
        "text",
        text=string("The fact, in a sentence that reads well alone: 'The Gynarch of Hardby owes the party her life.'"),
        category=string("Free-form: history, people, place."),
        dm_only=boolean("True when the players mustn't learn it."),
    ),
    mutates=True,
    areas=(),
    player_visible=False,
)
def propose_fact(ctx: CampaignContext, text: str, category: str = "", dm_only: bool = False) -> dict[str, Any]:
    """Propose a lasting fact of the world to the setting: a new village, an NPC's fate, a homebrew deity. Never what
    matters only to this table: use add_fact. It holds in this campaign at once, and in every campaign once an
    organiser accepts it."""
    layer = _layer(ctx)
    if not text.strip():
        raise PlayError("A proposal needs its text.")
    return _proposed(
        proposals.propose_fact(
            ctx.storage, layer, ctx.campaign_id, text.strip(), category=category.strip(), dm_only=dm_only
        )
    )


def _excerpt(text: str, at: int) -> str:
    """About 100 characters around `at`, on one line, with ellipses where it was cut."""
    start, end = max(0, at - EXCERPT // 2), min(len(text), at + EXCERPT // 2)
    return ("…" if start else "") + text[start:end].replace("\n", " ") + ("…" if end < len(text) else "")


@tool(
    SPECS,
    "search_campaign",
    params("query", query=string("The words to find, any case: a name, a place, 'the silver key'.")),
    mutates=False,
    player_visible=False,
)
def search_campaign(ctx: CampaignContext, query: str) -> dict[str, Any]:
    """Find words in what this campaign wrote down: the story (in English), your notes, the campaign's facts (debts,
    vows, gifts) and the event log, newest first. At most 20 hits, each with its source and about 100 characters around the match; each source has its share,
    so many story hits don't hide the notes, and `cut` says there were more than these."""
    words = query.strip()
    if not words:
        raise PlayError("Search for some words.")
    needle = re.compile(re.escape(words), re.IGNORECASE)
    # The database finds them, newest first (DEL-172): one more than all the hits, to know when they were cut.
    found: dict[str, list[tuple[str, str]]] = {
        "story": [
            (f"story #{entry.seq}", entry.payload["text"])
            for entry in ctx.storage.story.search(ctx.campaign_id, words, SEARCH_HITS + 1)
        ],
        "notes": [
            (f"note {note.id}", note.text) for note in ctx.storage.notes.search(ctx.campaign_id, words, SEARCH_HITS + 1)
        ],
        "facts": [
            (f"fact {fact.id}" + (f" ({fact.category})" if fact.category else ""), fact.text)
            for fact in reversed(ctx.storage.campaign_facts.list(ctx.campaign_id, query=words))
        ][: SEARCH_HITS + 1],
        "events": [
            (f"event #{event.id}", text)
            for event in ctx.storage.events.search(ctx.campaign_id, words, SEARCH_HITS + 1)
            if event.type != "fact"  # found among the facts
            and (text := next((v for v in event.data.values() if isinstance(v, str) and needle.search(v)), None))
        ],
    }
    shares = _shares({name: len(hits) for name, hits in found.items()}, SEARCH_HITS)
    results = []
    for name, hits in found.items():
        for source, text in hits[: shares[name]]:
            match = needle.search(text)
            results.append({"source": source, "excerpt": _excerpt(text, match.start() if match else 0)})
    cut = sum(len(hits) for hits in found.values()) > len(results)
    answer: dict[str, Any] = {"query": query, "count": len(results), "results": results, "cut": cut}
    if cut:
        answer["hint"] = f"There are more hits than these {len(results)}: search with more words to find older ones."
    return answer


def _shares(available: dict[str, int], total: int) -> dict[str, int]:
    """How many hits each source shows, `total` at most: an equal share each, and what a source leaves unused goes to
    the others, in order (DEL-172)."""
    shares = dict.fromkeys(available, 0)
    left = total
    while left > 0:
        wanting = [name for name in available if shares[name] < available[name]]
        if not wanting:
            break
        each = max(1, left // len(wanting))
        for name in wanting:
            give = min(each, available[name] - shares[name], left)
            shares[name] += give
            left -= give
            if left == 0:
                break
    return shares
