"""A setting written as files (DEL-351): one Markdown page per file with a TOML header, lore facts in TOML, world maps
in the `.map` language, all in one folder. Delve's own setting, Aun, is one; it needs no wiki dump and no
`reference.db`, and the folder moves into a pack as it is.

A page file:

    +++
    title = "Pale Tower"
    kind = "place"
    aliases = ["The Pale Tower"]
    categories = ["Hask", "Ruins"]

    [fields]
    type = "ruin"
    +++
    Markdown, with [[links]] and `::: dm` sections.

The folder holds `pages/*.md`, `facts/*.toml` (`[[fact]]` tables of `text`, `category` and an optional `dm_only`) and
the maps a subclass names in `MAPS`. It is read on first use, once."""

from __future__ import annotations

import hashlib
import re
import secrets
import sqlite3
import threading
import tomllib
from dataclasses import dataclass
from pathlib import Path

from delve.domain.reference import LoreFact, ReferenceHit, SettingPage
from delve.domain.world import Calendar, WorldMapSource
from delve.setting.text import player_text

_HEADER = re.compile(r"\A\+\+\+\n(.*?)\n\+\+\+\n?(.*)\Z", re.DOTALL)
_ARTICLE = re.compile(r"^the\s+", re.IGNORECASE)
SNIPPET_WORDS = 16


class PageFileError(ValueError):
    """A page or fact file that doesn't read, or a folder whose pages clash."""


def read_page(text: str) -> SettingPage:
    """The page in `text`: its TOML header, then its Markdown. Raises `PageFileError` without a header, a title or a
    kind."""
    match = _HEADER.match(text.replace("\r\n", "\n"))
    if not match:
        raise PageFileError("a page starts with a +++ header and closes it with +++")
    try:
        header = tomllib.loads(match.group(1))
    except tomllib.TOMLDecodeError as error:
        raise PageFileError(f"the header doesn't read: {error}") from None
    title, kind = str(header.get("title") or "").strip(), str(header.get("kind") or "").strip()
    if not title or not kind:
        raise PageFileError("a page's header gives its title and its kind")
    fields = {str(key): str(value) for key, value in (header.get("fields") or {}).items() if str(value).strip()}
    categories = tuple(str(c) for c in header.get("categories") or ())
    return SettingPage(title, kind, fields, match.group(2).strip() + "\n", categories, format="markdown")


def _aliases(text: str) -> tuple[str, ...]:
    match = _HEADER.match(text.replace("\r\n", "\n"))
    header = tomllib.loads(match.group(1)) if match else {}
    return tuple(str(a) for a in header.get("aliases") or ())


def _key(title: str) -> str:
    """A title as pages are found by: any case, with or without a leading "the"."""
    return _ARTICLE.sub("", " ".join(title.split())).casefold()


def _summary(page: SettingPage) -> str:
    return ", ".join(f"{key}: {value}" for key, value in page.fields.items())


@dataclass(frozen=True)
class _Loaded:
    pages: tuple[SettingPage, ...]
    by_key: dict[str, SettingPage]
    facts: tuple[LoreFact, ...]
    index: sqlite3.Connection


class FileSetting:
    """A setting over the folder `root`. A subclass gives its `id`, `title`, `KINDS` (in the order the DM is shown
    them), `CALENDAR` and `MAPS` (each map's file stem and title)."""

    id: str
    title: str
    KINDS: tuple[str, ...]
    CALENDAR: Calendar
    MAPS: tuple[tuple[str, str], ...] = ()
    world: str = ""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self._loaded: _Loaded | None = None
        self._lock = threading.Lock()

    # --- reading the folder ------------------------------------------------------------------------------------

    def _load(self) -> _Loaded:
        with self._lock:
            if self._loaded is None:
                self._loaded = self._read()
            return self._loaded

    def _read(self) -> _Loaded:
        pages: list[SettingPage] = []
        by_key: dict[str, SettingPage] = {}
        for path in sorted((self.root / "pages").glob("*.md")):
            text = path.read_text("utf-8")
            try:
                page = read_page(text)
            except PageFileError as error:
                raise PageFileError(f"{path.name}: {error}") from None
            if page.kind not in self.KINDS:
                raise PageFileError(f"{path.name}: unknown kind '{page.kind}'; kinds: {', '.join(self.KINDS)}")
            for name in {_key(name): name for name in (page.title, *_aliases(text))}.values():
                if (other := by_key.get(_key(name))) is not None:
                    raise PageFileError(f"{path.name}: '{name}' already names the page {other.title}")
                by_key[_key(name)] = page
            pages.append(page)
        facts: list[LoreFact] = []
        for path in sorted((self.root / "facts").glob("*.toml")):
            try:
                rows = tomllib.loads(path.read_text("utf-8")).get("fact") or []
            except tomllib.TOMLDecodeError as error:
                raise PageFileError(f"{path.name}: {error}") from None
            for row in rows:
                text = str(row.get("text") or "").strip()
                if text:
                    facts.append(
                        LoreFact(
                            len(facts) + 1, text, str(row.get("category") or ""), self.id, bool(row.get("dm_only"))
                        )
                    )
        return _Loaded(tuple(pages), by_key, tuple(facts), self._index(pages))

    @staticmethod
    def _index(pages: list[SettingPage]) -> sqlite3.Connection:
        """An in-memory full-text index of the pages' player text: DM-only sections are never searched."""
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        conn.execute("CREATE VIRTUAL TABLE pages USING fts5(title, kind UNINDEXED, text, tokenize='unicode61')")
        conn.executemany(
            "INSERT INTO pages (title, kind, text) VALUES (?, ?, ?)",
            [(page.title, page.kind, player_text(page.text)) for page in pages],
        )
        return conn

    # --- the Setting protocol ----------------------------------------------------------------------------------

    def kinds(self) -> tuple[str, ...]:
        return self.KINDS

    def lookup(self, kind: str, query: str, limit: int = 5) -> list[ReferenceHit]:
        if kind not in self.KINDS:
            raise ValueError(f"unknown kind '{kind}'; kinds: {', '.join(self.KINDS)}")
        needle = (query or "").strip().casefold()
        found = [
            page
            for page in self._load().pages
            if page.kind == kind
            and (not needle or needle in page.title.casefold() or needle in _summary(page).casefold())
        ]
        found.sort(key=lambda page: page.title)
        return [ReferenceHit(kind, page.title, page.title, _summary(page)) for page in found[: max(0, limit)]]

    def calendar(self) -> Calendar:
        return self.CALENDAR

    def world_maps(self) -> tuple[WorldMapSource, ...]:
        return tuple(
            WorldMapSource(name, title, (self.root / f"{name}.map").read_text("utf-8")) for name, title in self.MAPS
        )

    def search(self, query: str, limit: int = 10) -> list[ReferenceHit]:
        words = [word for word in re.findall(r"[\w'-]+", query or "") if word.strip("-'")]
        if not words:
            return []
        loaded = self._load()
        match = " ".join(f'"{word}"' for word in words)
        with self._lock:
            rows = loaded.index.execute(
                f"SELECT title, kind, snippet(pages, 2, '<<', '>>', ' … ', {SNIPPET_WORDS}) FROM pages"
                " WHERE pages MATCH ? ORDER BY rank LIMIT ?",
                (match, max(1, int(limit or 10))),
            ).fetchall()
        return [ReferenceHit(kind, title, title, snippet) for title, kind, snippet in rows]

    def page(self, title: str) -> SettingPage | None:
        return self._load().by_key.get(_key(title or ""))

    def lore_facts(self, n: int, category: str = "", seed: int | None = None) -> list[LoreFact]:
        """As the reference draws them: every fact ordered by a hash of the seed and its id, a fresh seed if none."""
        key = secrets.token_hex(8) if seed is None else seed
        pool = [fact for fact in self._load().facts if category in ("", fact.category)]
        pool.sort(key=lambda fact: hashlib.sha256(f"{key}:{fact.id}".encode()).digest())
        return pool[: max(0, int(n))]
