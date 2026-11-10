"""A pack's `pack.toml`."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from delve.packs.api import PACK_API

MANIFEST_NAME = "pack.toml"
_ID = re.compile(r"[a-z0-9-]+")
_KINDS = ("ruleset", "setting")


class PackError(ValueError):
    """A pack that cannot be read or used; the message says why."""


@dataclass(frozen=True)
class PackManifest:
    id: str
    kind: Literal["ruleset", "setting"]
    title: str
    version: str
    delve_api: int
    package: str
    entry: str
    fact_categories: frozenset[str] = frozenset()
    preferred: bool = False
    """`preferred = true`: a new campaign takes this pack's ruleset or setting when the install has it (DEL-307), so
    core names none of them."""

    @classmethod
    def read(cls, folder: Path) -> PackManifest:
        """Read `folder/pack.toml`; a missing file or a missing or invalid field raises `PackError` naming it."""
        path = folder / MANIFEST_NAME
        try:
            raw = tomllib.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise PackError(f"no {MANIFEST_NAME}") from None
        except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
            raise PackError(f"{MANIFEST_NAME} unreadable: {error}") from error

        pack_id = _text(raw, "id")
        if not _ID.fullmatch(pack_id):
            raise PackError(f"id '{pack_id}' must be lowercase letters, digits and hyphens")
        kind = _text(raw, "kind")
        if kind not in _KINDS:
            raise PackError(f"kind '{kind}' must be 'ruleset' or 'setting'")
        delve_api = raw.get("delve_api")
        if isinstance(delve_api, bool) or not isinstance(delve_api, int):
            raise PackError("delve_api missing or not a whole number")
        if delve_api != PACK_API:
            raise PackError(f"delve_api {delve_api}; this Delve reads {PACK_API}")
        package = _text(raw, "package")
        if not package.isidentifier():
            raise PackError(f"package '{package}' is not a package name")
        entry = _text(raw, "entry")
        module, _, attr = entry.partition(":")
        if not module or not attr:
            raise PackError(f"entry '{entry}' must be 'module:attr'")
        categories = raw.get("fact_categories", [])
        if not isinstance(categories, list) or not all(isinstance(c, str) for c in categories):
            raise PackError("fact_categories must be a list of strings")
        if categories and kind != "setting":
            raise PackError("fact_categories belongs to settings only")
        preferred = raw.get("preferred", False)
        if not isinstance(preferred, bool):
            raise PackError("preferred must be true or false")
        return cls(
            id=pack_id,
            kind=kind,  # type: ignore[arg-type]  # checked against _KINDS above
            title=_text(raw, "title"),
            version=_text(raw, "version"),
            delve_api=delve_api,
            package=package,
            entry=entry,
            fact_categories=frozenset(categories),
            preferred=preferred,
        )


def _text(raw: dict, field: str) -> str:
    value = raw.get(field)
    if not isinstance(value, str) or not value.strip():
        raise PackError(f"{field} missing or not text")
    return value
