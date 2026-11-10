"""The words of Delve's emails: the `email.*` strings of the web app's dictionaries (`web/src/i18n/<language>.json`),
so one set of words serves the page and the mail. In a wheel the dictionaries are inside the package
(`delve/i18n/web`); from the repository they are read where the web app keeps them.
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path

import delve
from delve.domain.settings import LANGUAGES

_PACKAGED = Path(delve.__file__).resolve().parent / "i18n" / "web"
_IN_REPO = Path(__file__).resolve().parents[3] / "web" / "src" / "i18n"
DICTIONARIES_DIR = _IN_REPO if _IN_REPO.is_dir() else _PACKAGED
FALLBACK = "en"


def _words(language: str) -> dict[str, str]:
    # Only Delve's own languages name a file, or a cache entry: anything else is English.
    return _load(language if language in LANGUAGES else FALLBACK)


@cache
def _load(language: str) -> dict[str, str]:
    path = DICTIONARIES_DIR / f"{language}.json"
    if not path.is_file():
        path = DICTIONARIES_DIR / f"{FALLBACK}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    return {key: value for key, value in data.items() if key.startswith("email.")}


def keys(language: str) -> set[str]:
    """The `email.*` keys of a language."""
    return set(_words(language))


def text(language: str, key: str, **values: str) -> str:
    """A string in a language (English for one Delve doesn't have), its `{placeholders}` filled from `values`.

    A key that isn't there raises `KeyError`: the dictionaries' tests keep every language complete.
    """
    return _words(language)[key].format(**values)


def template(language: str, key: str) -> str:
    """A string as it is written, `{placeholders}` and all (for a caller that fills them its own way)."""
    return _words(language)[key]
