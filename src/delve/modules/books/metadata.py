"""A module's descriptive metadata, read from its whole text (owner addition 2026-10-24): one side call with
`prompts/metadata.md`, its answer checked field by field against the format's schema, and only the fields the
module doesn't have yet filled. Every conversion does it as it makes the module (`runner._make_module`), and
`complete_metadata` fills a module made before."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from jsonschema import Draft202012Validator

from delve.modules.books.calls import Halt
from delve.modules.books.convert import Complete, _fill, _prompt
from delve.modules.books.fences import unfenced
from delve.modules.dscn.validate import schema
from delve.modules.source import TextDoc, Warning

FIELDS = (
    "subtitle", "summary", "description", "authors", "publisher", "system", "system_name", "setting", "language",
    "party", "duration", "tags", "content_warnings",
)  # fmt: skip
"""The metadata the call may give: the book's own facts, never the release, licence, homepage or cover."""
METADATA_CHARS = 400_000
"""The most of the text the call is sent (about 100k tokens); a longer module's end is left out."""
UNREAD = "metadata-unread"
UNREAD_MESSAGE = "The module's metadata couldn't be read from its text ({reason}); fill it in on its details."


def module_text(texts: Sequence[TextDoc]) -> str:
    """The module's texts in order, each under its title, cut at `METADATA_CHARS`."""
    whole = "\n\n".join(f"# {text.title}\n\n{text.markdown.strip()}" for text in texts)
    return whole[:METADATA_CHARS]


def _empty(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def merged(existing: Mapping[str, Any], found: Mapping[str, Any]) -> dict[str, Any]:
    """`existing` with the fields it lacks taken from `found`; an object field it has (the party) gets only the keys
    it lacks. Nothing it has is changed."""
    result = dict(existing)
    for key, value in found.items():
        have = result.get(key)
        if _empty(have):
            result[key] = value
        elif isinstance(have, dict) and isinstance(value, dict):
            result[key] = {**value, **{k: v for k, v in have.items() if not _empty(v)}}
    return result


def parse(reply: str) -> dict[str, Any]:
    """The answer's fields that fit the format's schema; ValueError (no JSON) or TypeError (no object) else."""
    data = json.loads(unfenced(reply))
    if not isinstance(data, dict):
        raise TypeError("the answer isn't a JSON object")
    properties, defs = schema()["properties"], schema()["$defs"]
    kept = {}
    for key in FIELDS:
        value = data.get(key)
        if not _empty(value) and Draft202012Validator({**properties[key], "$defs": defs}).is_valid(value):
            kept[key] = value
    return kept


async def read_metadata(texts: Sequence[TextDoc], title: str, complete: Complete) -> dict[str, Any]:
    """The metadata the module's text gives, as `parse` keeps it."""
    prompt = _fill(_prompt("metadata.md"), title=title, text=module_text(texts))
    return parse(await complete(prompt))


async def complete_metadata(
    existing: Mapping[str, Any], texts: Sequence[TextDoc], title: str, complete: Complete
) -> tuple[dict[str, Any], list[Warning]]:
    """`existing` with its empty fields filled from the text, and no warning; when the call fails or its answer
    can't be read, `existing` as it is with a warning, so the module is still made."""
    if not texts:
        return dict(existing), []
    try:
        found = await read_metadata(texts, title, complete)
    except Halt:
        raise
    except Exception as error:  # noqa: BLE001 (the metadata never stops a module being made)
        reason = str(error) or type(error).__name__
        return dict(existing), [Warning(UNREAD, UNREAD_MESSAGE.format(reason=reason), "metadata")]
    return merged(existing, found), []
