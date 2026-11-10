"""Which of the module's own wandering tables a check rolls on where the party is (DEL-321).

A table placed where the party is wins over one placed more widely, and any placed table over one placed nowhere:
a keyed room (`key:C2`, or its room `map:crypt#throne_chamber`) over the section of text that keys it
(`text:crypt-key#c2`), over that whole text (`text:crypt-key`), over the map (`map:crypt`). A table placed nowhere is
for anywhere its kind allows. Two that tie are the DM's to choose between; with none, the ruleset's tables roll.
"""

from __future__ import annotations

from dataclasses import dataclass

from delve.domain.wandering import WanderingTable, fits, table, wandering_tables
from delve.modules.dscn.refs import Ref, parse_ref
from delve.modules.text import Key, ModuleText
from delve.play.context import CampaignContext, NotFound
from delve.play.moves import party_place
from delve.rules.classic.terrain import TERRAIN_ALIASES

RULESET = "ruleset"
"""The `table` that asks for the ruleset's tables, as if the module had none."""

def world(ctx: CampaignContext) -> str:
    """The world the campaign's setting is on (its `world`: "aun"), as the ruleset's encounter entries tag theirs
    ("Human (Cerilia)"), so a wandering encounter of another world stays out of the campaign (DEL-337); "" without a
    setting or for a setting that names none, which keeps every entry."""
    layer = ctx.setting
    shipped = getattr(layer, "shipped", layer)
    return str(getattr(shipped, "world", "") or "")


@dataclass(frozen=True)
class Choice:
    """The table to roll on (None: the ruleset's), or the tables the DM is to choose between."""

    table: WanderingTable | None = None
    choose: tuple[WanderingTable, ...] = ()


def choice(ctx: CampaignContext, terrain: str, named: str = "") -> Choice:
    """The module's table for a check in `terrain` where the party is, or the one `named` (its id or name, or
    `RULESET`). `NotFound` for a name no table of the module has."""
    text = _text(ctx)
    if text is None:
        return Choice()
    records = [
        r for r in text.entities.get("encounters", []) if isinstance(r, dict) and isinstance(r.get("table"), list)
    ]
    if named.strip():
        return Choice(_named(records, named.strip()))
    tables = wandering_tables(records)
    if not tables:
        return Choice()
    map_name, node = party_place(ctx)
    key = _key(text, map_name, node)
    scored = [(_score(t, map_name, node, key), t) for t in tables]
    placed = [(score, t) for score, t in scored if score > 0]
    if placed:
        best = max(score for score, _ in placed)
        return _one([t for score, t in placed if score == best])
    word = terrain.strip().casefold()
    return _one([t for score, t in scored if score == 0 and fits(t.kind, TERRAIN_ALIASES.get(word, word))])


def _one(tables: list[WanderingTable]) -> Choice:
    if len(tables) == 1:
        return Choice(tables[0])
    return Choice(choose=tuple(tables)) if tables else Choice()


def _named(records: list[dict], named: str) -> WanderingTable | None:
    if named.casefold() == RULESET:
        return None
    for record in records:
        if named.casefold() in (str(record.get("id", "")).casefold(), str(record.get("name", "")).casefold()):
            return table(record)
    raise NotFound(
        f"The module has no table '{named}'.",
        [{"id": str(r["id"]), "name": str(r.get("name") or r["id"])} for r in records if r.get("id")]
        + [{"id": RULESET, "name": "the ruleset's tables"}],
    )


def _score(t: WanderingTable, map_name: str | None, node: str | None, key: Key | None) -> int:
    """How closely the table is placed where the party is: 4 its room, 3 the room's section of text, 2 that text, 1
    its map; 0 for a table placed nowhere, and -1 for one placed only elsewhere."""
    if not t.where:
        return 0
    doc, _, section = (key.text_anchor or "").partition("#") if key is not None else ("", "", "")
    return max(_ref_score(parse_ref(raw), map_name, node, key, doc, section) for raw in t.where)


def _ref_score(ref: Ref | None, map_name: str | None, node: str | None, key: Key | None, doc: str, section: str) -> int:
    if ref is None:
        return -1
    if ref.kind == "key":
        return 4 if key is not None and ref.id.casefold() == key.key.casefold() else -1
    if ref.kind == "map" and ref.id == map_name:
        if not ref.fragment:
            return 1
        return 4 if ref.fragment == node else -1
    if ref.kind == "text" and doc and ref.id == doc:
        if not ref.fragment:
            return 2
        return 3 if ref.fragment == section else -1
    return -1


def _key(text: ModuleText, map_name: str | None, node: str | None) -> Key | None:
    """The keyed room the party is in, when the room has a key."""
    if map_name is None or node is None:
        return None
    return next((k for k in text.keys if k.node == f"map:{map_name}#{node}"), None)


def _text(ctx: CampaignContext) -> ModuleText | None:
    campaign = ctx.storage.campaigns.get(ctx.campaign_id)
    raw = ctx.storage.module_texts.revision(campaign.module_id, campaign.revision) if campaign else None
    return ModuleText.from_json(raw) if raw is not None else None
