"""Records Claude groups as one (faithful modules C3): a book's parts are read apart, so one person may be drafted in
each, under another name ("Ned", "Ned Shakeshaft", "the spy").

Each kind that holds people or groups (`DEDUPED`) with two records or more is sent once with `prompts/dedupe.md`, one
line per record, and Claude answers the groups of ids that are one, the record to keep first. A group is merged by
`merge_into`'s rules, which `convert.merge_entities_mapped` uses for records of one name. An answer that isn't such a list, an
id it doesn't know, or a record in two groups merges nothing of that kind, and says so. The records passed in are never
changed.
"""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from importlib import resources
from typing import Any

from delve.modules.books.calls import Halt, all_of
from delve.modules.books.fences import unfenced
from delve.modules.source import Warning

Complete = Callable[[str], Awaitable[str]]

DEDUPED = {"npcs": "person", "factions": "faction"}
"""The kinds sent to be grouped, with what one record of the kind is, for the prompt."""
_KIND_NAMES = {"npcs": "NPCs", "factions": "factions"}
_REF_KINDS = {"npcs": "npc", "factions": "faction"}
_SENTENCE = re.compile(r"(.+?[.!?])(?:\s|$)", re.DOTALL)


def _empty(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def merge_into(kept: dict[str, Any], record: dict[str, Any]) -> None:
    """`record` merged into `kept`, in place: the `summary`s joined with a blank line (each once), and of every other
    field but `id` and `name` the first value that isn't empty kept."""
    summary = record.get("summary")
    if isinstance(summary, str) and summary.strip():
        had = kept.get("summary")
        parts = [p for p in (had.strip() if isinstance(had, str) else "").split("\n\n") if p]
        if summary.strip() not in parts:
            kept["summary"] = "\n\n".join([*parts, summary.strip()])
    for name, value in record.items():
        if name not in ("id", "name", "summary") and _empty(kept.get(name)) and not _empty(value):
            kept[name] = value


def _line(record: dict[str, Any]) -> str:
    summary = " ".join(str(record.get("summary") or "").split())
    first = _SENTENCE.match(summary)
    fields = [record.get("id"), record.get("name"), record.get("role"), first.group(1) if first else summary]
    return " | ".join(" ".join(str(f or "").split()) for f in fields)


def _prompt(kind: str, records: list[dict[str, Any]]) -> str:
    template = resources.files("delve.modules.books").joinpath("prompts", "dedupe.md").read_text("utf-8")
    values = {"kind": _KIND_NAMES[kind], "what": DEDUPED[kind], "records": "\n".join(map(_line, records))}
    for name, value in values.items():
        template = template.replace("{{" + name + "}}", value)
    return template


def _groups(reply: str, ids: set[str]) -> list[list[str]] | None:
    """The groups of two or more of an answer; None when it isn't a list of lists of known ids, each id once."""
    try:
        raw = json.loads(unfenced(reply))
    except ValueError:
        return None
    if not isinstance(raw, list) or not all(isinstance(g, list) for g in raw):
        return None
    seen: set[str] = set()
    for group in raw:
        for id in group:
            if not isinstance(id, str) or id not in ids or id in seen:
                return None
            seen.add(id)
    return [group for group in raw if len(group) > 1]


async def dedupe_entities(
    entities: dict[str, list[dict[str, Any]]], complete: Complete
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, str], list[Warning]]:
    """`entities` with the records Claude groups as one merged, the refs of the records merged away (as
    `{"npc:ned-2": "npc:ned"}`), and the warnings: `entities-merged` for each group, `entities-not-deduplicated` for a
    kind whose answer couldn't be used."""
    sent = [kind for kind in DEDUPED if len(entities.get(kind, [])) > 1]

    async def ask(kind: str) -> str | None:
        try:
            return await complete(_prompt(kind, entities[kind]))
        except Halt:
            raise
        except Exception:  # noqa: BLE001 (the records stay as they are)
            return None

    replies = dict(zip(sent, await all_of([ask(kind) for kind in sent]), strict=True))
    result = dict(entities)
    renamed: dict[str, str] = {}
    warnings: list[Warning] = []
    for kind in sent:
        records = entities[kind]
        reply = replies[kind]
        groups = _groups(reply, {str(r.get("id")) for r in records}) if reply is not None else None
        if groups is None:
            message = f"Claude's answer on which {_KIND_NAMES[kind]} are one couldn't be used: check them for doubles."
            warnings.append(Warning("entities-not-deduplicated", message, kind))
            continue
        by_id = {str(r.get("id")): dict(r) for r in records}
        dropped: set[str] = set()
        ref = _REF_KINDS[kind]
        for keep, *others in groups:
            for other in others:
                merge_into(by_id[keep], by_id[other])
                renamed[f"{ref}:{other}"] = f"{ref}:{keep}"
                dropped.add(other)
            names = ", ".join(str(by_id[id].get("name") or id) for id in [keep, *others])
            warnings.append(Warning("entities-merged", f"Merged as one: {names}.", f"{ref}:{keep}"))
        result[kind] = [by_id[str(r.get("id"))] for r in records if str(r.get("id")) not in dropped]
    return result, renamed, warnings
