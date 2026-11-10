"""The module's text for the DM (spec §8.1; ttrpg2 `tools/module_ref.py` and `module_key` in `tools/scenario.py`): a
search over the text of the revision the campaign pinned, and a room's keyed text. Module text is canon the players
never read, so both tools are DM-only: what the DM narrates from them is its own words."""

from __future__ import annotations

import re
from typing import Any

from delve.dm.tools.schema import ToolSpec, integer, params, string, tool
from delve.modules.dscn.refs import ENTITY_REF_KINDS, parse_ref, refs_in_value
from delve.modules.text import Key, ModuleText, TextSection
from delve.play.context import CampaignContext, NotFound, PlayError
from delve.play.moves import locate, party_place

SPECS: list[ToolSpec] = []

NO_TEXT = "this module has no text"
MAX_RESULTS = 20
HEADINGS = 10
"""At most this many headings a search that found nothing suggests."""


def _pinned(ctx: CampaignContext) -> tuple[str, int, ModuleText]:
    """The campaign's module, its pinned revision, and that revision's text."""
    campaign = ctx.storage.campaigns.get(ctx.campaign_id)
    raw = ctx.storage.module_texts.revision(campaign.module_id, campaign.revision) if campaign else None
    if campaign is None or raw is None:
        raise PlayError(NO_TEXT)
    return campaign.module_id, campaign.revision, ModuleText.from_json(raw)


@tool(
    SPECS,
    "module_lookup",
    params(
        "query",
        query=string('Words to find, e.g. "fire beetles", "the ritual".'),
        section=string('Only results whose heading path contains this, e.g. "C2", "Level Two", "Room Key".'),
        limit=integer("How many results; 5 by default.", minimum=1, maximum=MAX_RESULTS),
    ),
    mutates=False,
    player_visible=False,
)
def module_lookup(ctx: CampaignContext, query: str, section: str = "", limit: int = 5) -> dict[str, Any]:
    """Search the text of the module this campaign plays: room keys, overviews, NPCs, wandering-monster tables. Each
    result is a paragraph with its section's anchor and heading path. DM-only: never read it out; narrate what the
    characters perceive in your own words. move_party and room already carry each room's boxed text and DM notes from
    the map, and module_key gives a room's keyed text; reach for this for what they don't hold."""
    module_id, revision, text = _pinned(ctx)
    results = ctx.storage.module_texts.search(module_id, revision, query, limit, section=section)
    out: dict[str, Any] = {"query": query, "section": section or None, "count": len(results), "results": results}
    if results:
        return out
    # Nothing holds every word (DEL-330: half the lookups of a Ruins evening found nothing): those holding any of
    # them, best first, and the headings that name one, to look under with `section`.
    results = ctx.storage.module_texts.search(module_id, revision, query, limit, section=section, any_word=True)
    words = {w.casefold() for w in re.findall(r"[\w'-]+", query) if len(w) > 2}
    headings = list(
        dict.fromkeys(
            " > ".join(s.heading_path)
            for s in text.sections
            if s.heading_path and words & {w.casefold() for w in re.findall(r"[\w'-]+", s.heading_path[-1])}
        )
    )[:HEADINGS]
    out.update(count=len(results), results=results, matched="any word")
    if headings:
        out["headings"] = headings
    if not results and not headings:
        out["hint"] = "Nothing in the module holds these words: try another name for it, or a section."
    return out


@tool(
    SPECS,
    "module_key",
    params(
        "room",
        room=string(
            "The room: its key (C2), its id (room.throne_chamber), bare name (throne_chamber) or label (Throne Room)."
        ),
        part=string(
            "The part of the module the key is in, for a key two parts share: its name as module_key gives it "
            '(haunted-house), its text id or one word of its title ("ship").'
        ),
    ),
    mutates=False,
    player_visible=False,
)
def module_key(ctx: CampaignContext, room: str, part: str = "") -> dict[str, Any]:
    """A keyed room of the module, by its key or as move_party names rooms: its read-aloud text (the boxed text, for
    the players), its DM text (never read it aloud), the NPCs there and its encounters, with their stats: `encounters`
    is every encounter keyed to the room, its main one (`encounter`) first. A key two parts of the module share (the
    house's 7 and the ship's 7) takes `part`, or the key as written (`sea-ghost-7`)."""
    _, _, text = _pinned(ctx)
    key = _keyed(ctx, text, room, part)
    section = text.section(key.text_anchor) if key.text_anchor else None
    map_name, node = _node(key)
    return {
        "key": key.key,
        "part": key.part,
        "title": key.title,
        "map": map_name,
        "node": node,
        "anchor": key.text_anchor,
        "read_aloud": (section.read_aloud or "") if section else "",
        "dm_text": _dm_text(text, section),
        "npcs": [_entity(text, ref) for ref in key.npcs],
        "encounter": _entity(text, key.encounter) if key.encounter else None,
        "encounters": _encounters(text, key),
        "assets": list(key.assets),
    }


def _encounters(text: ModuleText, key: Key) -> list[dict[str, Any]]:
    """Every encounter of the room: the one its `keys[]` entry names, then each whose record's `key` names it, as
    written or, for a record in the key's own part (one of its refs names the key's text), as printed (`key:7` for
    `sea-ghost-ship-7`), as an older conversion wrote it."""
    first = [_entity(text, key.encounter)] if key.encounter else []
    printed = key.key.removeprefix(f"{key.part}-") if key.part else key.key
    named = [
        dict(record)
        for record in text.entities.get("encounters", [])
        if f"encounter:{record.get('id')}" != key.encounter
        and (
            record.get("key") == f"key:{key.key}"
            or (record.get("key") == f"key:{printed}" and _in_text(record, _text_id(key)))
        )
    ]
    return first + named


def _in_text(record: dict[str, Any], text_id: str | None) -> bool:
    """Whether one of the record's refs names the text `text_id`."""
    refs = (parse_ref(raw) for raw in refs_in_value(record))
    return text_id is not None and any(r is not None and r.kind == "text" and r.id == text_id for r in refs)


def _node(key: Key) -> tuple[str | None, str | None]:
    ref = parse_ref(key.node) if key.node else None
    if ref is None or ref.kind != "map":
        return None, None
    return ref.id, ref.fragment


def _keyed(ctx: CampaignContext, text: ModuleText, room: str, part: str = "") -> Key:
    """The key `room` names, in the part `part` names when given: by its key as written, its printed key within its
    part (`<part>-<room>`, and a key no other part shares by its part too: "introduction-8" for 8), or its node first
    (on any map), else the room on the party's map. A key two parts share is
    the one on the party's map, when the party stands on one of them; a key as printed before its title ("B3" for "B3.
    Water-Gate") finds it when nothing else does (DEL-330)."""
    wanted = room.strip()
    keys = text.keys
    if part.strip():
        tid = _part(text, part)
        keys = [k for k in keys if _text_id(k) == tid]
    hits = [
        k
        for k in keys
        if wanted.casefold() in (k.key.casefold(), f"{k.part}-{k.key}".casefold())
        or k.key.casefold() == f"{k.part}-{wanted}".casefold()
        or wanted in (k.node, _node(k)[1])
    ]
    if not hits and wanted:
        printed = re.compile(rf"^{re.escape(wanted)}(?![\w])", re.IGNORECASE)
        hits = [k for k in keys if printed.match(k.key) or printed.match(k.title or "")]
    if len({k.part for k in hits}) > 1:
        here = party_place(ctx)[0]
        on_map = [k for k in hits if here is not None and _node(k)[0] == here]
        if len({k.part for k in on_map}) == 1:
            hits = on_map
    if len({k.part for k in hits}) > 1:
        raise NotFound(
            f"The key '{room}' is in more than one part.",
            _key_candidates(hits),
            hint=f"Name the part, as module_key(room='{wanted}', part='<part>'), or the key as written.",
        )
    if len(hits) > 1:
        raise NotFound(f"The room '{room}' has more than one key.", _key_candidates(hits), hint="Name the key.")
    if hits:
        return hits[0]
    try:
        map_name, node = locate(ctx, wanted)
    except NotFound as unknown:
        raise NotFound(
            unknown.message, unknown.candidates or _key_candidates(keys), hint="Name a key or a room of the map."
        ) from None
    found = next((k for k in keys if _node(k) == (map_name, node)), None)
    if found is None and part.strip():
        raise NotFound(f"No room '{room}' in the part '{part}'.", _key_candidates(keys), hint="Name a key of the part.")
    if found is None:
        raise PlayError(f"The room '{room}' ({node}) has no keyed text.", hint="Search the text with module_lookup.")
    return found


def _key_candidates(keys: list[Key]) -> list[dict[str, Any]]:
    return [{"key": k.key, "title": k.title, "node": k.node, "part": k.part} for k in keys]


def _text_id(key: Key) -> str | None:
    return key.text_anchor.split("#", 1)[0] if key.text_anchor else None


def _part(text: ModuleText, part: str) -> str:
    """The id of the one text with keys that `part` names: by its id, its part or one word of its title, or the start
    of its id or part ("kovel" for kovel-mansion, DEL-330). A text whose keys name no part is named by its id."""
    want = part.strip().casefold()
    parts: dict[str, str] = {}
    for k in text.keys:
        if (tid := _text_id(k)) is not None:
            parts.setdefault(tid, k.part or tid)
    titles = {s.anchor.split("#", 1)[0]: s.heading_path[0] for s in text.sections if s.heading_path}

    def names(tid: str, slug: str) -> bool:
        return want in (tid.casefold(), slug.casefold()) or want in re.findall(r"\w+", titles.get(tid, "").casefold())

    hits = [tid for tid, slug in parts.items() if names(tid, slug)] or [
        tid
        for tid, slug in parts.items()
        if want and (tid.casefold().startswith(want) or slug.casefold().startswith(want))
    ]
    if len(hits) == 1:
        return hits[0]
    candidates = [{"part": slug, "title": titles.get(tid, tid), "text": tid} for tid, slug in parts.items()]
    message = f"No part '{part}' has keys." if not hits else f"The part '{part}' names more than one part."
    raise NotFound(message, candidates, hint="Name the part as a candidate gives it.")


def _dm_text(text: ModuleText, section: TextSection | None) -> str:
    """The section's DM text with its sub-sections ("Treasure", "Development"), which follow it in reading order."""
    if section is None:
        return ""
    parts = [section.markdown] if section.markdown else []
    depth = len(section.heading_path)
    for sub in text.sections[text.sections.index(section) + 1 :]:
        if len(sub.heading_path) <= depth or sub.heading_path[:depth] != section.heading_path:
            break
        heading = "#" * min(6, len(sub.heading_path)) + " " + sub.heading_path[-1]
        parts.append("\n\n".join(p for p in (heading, sub.read_aloud or "", sub.markdown) if p))
    return "\n\n".join(parts)


def _entity(text: ModuleText, ref: str) -> dict[str, Any]:
    """The entity record a reference names (`npc:ritualist`), or the reference alone when the module lacks it."""
    parsed = parse_ref(ref)
    kind = ENTITY_REF_KINDS.get(parsed.kind) if parsed else None
    records = text.entities.get(kind, []) if kind else []
    found = next((r for r in records if parsed and r.get("id") == parsed.id), None)
    return dict(found) if found is not None else {"ref": ref, "missing": True}
