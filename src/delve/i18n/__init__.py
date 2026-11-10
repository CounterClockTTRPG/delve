"""Translation of player input and DM output: the glossaries of game terms per language (`glossary/<language>.yaml`,
spec §7.7). The translation passes themselves are `delve.play.translate`."""

from __future__ import annotations

import re
from importlib import resources

import yaml

__all__ = ["KEEP", "glossary"]

KEEP = "keep"
_CODE = re.compile(r"[a-z]{2,3}(-[a-z0-9]{2,8})?")


def glossary(language: str) -> dict[str, str | None]:
    """The game terms for `language`, English term first: its translation, or None to keep the English term. Empty
    for a language without a glossary."""
    if not _CODE.fullmatch(language):
        return {}
    found = resources.files("delve.i18n").joinpath("glossary", f"{language}.yaml")
    if not found.is_file():
        return {}
    raw = yaml.safe_load(found.read_text("utf-8")) or {}
    return {str(term): None if str(said) == KEEP else str(said) for term, said in raw.items()}
