"""A setting over a wiki (spec §10): the wiki's pages, typed tables (its kinds), full-text search and lore facts, in
one setting pack's `pack.db` (DEL-307). Core keeps the reader and the build; a wiki setting pack (installed, not
shipped) gives its snapshots, its table prefix, its kinds, its calendar and its maps, and its entry is a `WikiPack`.
The queries are ttrpg2's wiki and lore-fact tools'."""

from __future__ import annotations

import hashlib
import re
import sqlite3
import threading
from collections.abc import Collection, Mapping, Sequence
from pathlib import Path
from typing import Protocol

from delve.domain.reference import LoreFact, ReferenceHit, SettingPage
from delve.domain.world import Calendar, WorldMapSource
from delve.packs import store

PACK_DB = "pack.db"
REDIRECT_HOPS = 5
SEARCH_CAP = 50
LORE_FACTS_CAP = 100
NOT_FIELDS = frozenset({"page", "extra"})
"""Typed-table columns that aren't a page's fields: its key, and the infobox's image and caption."""


class WikiStore(Protocol):
    """One wiki: its pages, typed rows and search, and its lore facts."""

    def page(self, title: str) -> SettingPage | None:
        """The page titled `title` (ignoring case; the exact case first), following up to 5 redirects; None when there
        is no such page or the redirects lead nowhere."""
        ...

    def rows(self, table: str, query: str, limit: int) -> list[SettingPage]:
        """The rows of the typed table `table` whose name or page contains `query` (ignoring case), by page title. An
        unknown table raises `ValueError`."""
        ...

    def search(self, query: str, limit: int) -> list[ReferenceHit]:
        """Full-text search of the pages, best first, redirects left out: `kind` is the wiki's page type, `key` and
        `title` the page title, `text` a snippet with the hits in `<<…>>`. Every word must match; the query's words
        are quoted, so they are never FTS syntax. `limit` is capped at 50."""
        ...

    def lore_facts(
        self, n: int, category: str = "", seed: int | None = None, *, exclude: Collection[str] = ()
    ) -> list[LoreFact]:
        """Up to `n` (at most 100) lore facts drawn at random, of `category` if one is given and of no category in
        `exclude`. The same `seed` gives the same draw."""
        ...


class SqliteWikiStore:
    """A wiki in a SQLite file, opened read-only: the tables `<prefix>pages` (with `<prefix>pages_fts`),
    `<prefix>categories`, the typed `<prefix><table>` of `tables`, and `lore_facts`.

    One connection serves the whole app: every query runs under a lock and is fetched whole before the lock is let go
    (sqlite3 refuses one connection used by two threads at once)."""

    def __init__(self, db: Path, prefix: str, tables: Sequence[str]) -> None:
        self.prefix = prefix
        self.tables = tuple(tables)
        self._conn = sqlite3.connect(f"{Path(db).resolve().as_uri()}?mode=ro", uri=True, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _fetch(self, sql: str, params: list | tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def page(self, title: str) -> SettingPage | None:
        p, key = self.prefix, (title or "").strip()
        if not key:
            return None
        rows = self._fetch(
            f"SELECT title FROM {p}pages WHERE title = ? COLLATE NOCASE"
            " ORDER BY CASE WHEN title = ? THEN 0 ELSE 1 END LIMIT 1",
            (key, key),
        )
        if not rows:
            return None
        current = rows[0]["title"]
        seen = {current}
        for _ in range(REDIRECT_HOPS + 1):
            (row,) = self._fetch(
                f"SELECT title, type, is_redirect, redirect_target, raw_text FROM {p}pages WHERE title = ?", (current,)
            ) or [None]
            if row is None:
                return None
            if not row["is_redirect"]:
                return self._page(row)
            current = row["redirect_target"] or ""
            if not current or current in seen:
                return None
            seen.add(current)
        return None

    def rows(self, table: str, query: str, limit: int) -> list[SettingPage]:
        p = self.prefix
        if table not in self.tables:
            raise ValueError(f"unknown kind '{table}'; use one of: {', '.join(self.tables)}")
        q = f"%{(query or '').strip()}%"
        rows = self._fetch(
            f"SELECT t.*, p.type AS page_type, p.raw_text AS page_text FROM {p}{table} t"
            f" LEFT JOIN {p}pages p ON p.title = t.page"
            " WHERE t.name LIKE ? COLLATE NOCASE OR t.page LIKE ? COLLATE NOCASE ORDER BY t.page LIMIT ?",
            (q, q, max(0, int(limit))),
        )
        return [
            SettingPage(
                title=row["page"],
                kind=table,
                fields=_fields(row, {"page_type", "page_text"}),
                text=row["page_text"] or "",
                categories=self._categories(row["page"]),
            )
            for row in rows
        ]

    def search(self, query: str, limit: int) -> list[ReferenceHit]:
        p = self.prefix
        limit = max(1, min(int(limit or 10), SEARCH_CAP))
        # One quoted phrase per word: ttrpg2 doubled the quotes of a phrase query instead, so '"Circle of Eight"'
        # became a phrase of quotes and found nothing.
        q = " ".join(f'"{word}"' for word in re.findall(r"[\w'-]+", query or "") if word.strip("-'"))
        if not q:
            return []
        rows = self._fetch(
            f"SELECT p.title, p.type, snippet({p}pages_fts, 1, '<<', '>>', ' … ', 16) AS snippet"
            f" FROM {p}pages_fts JOIN {p}pages p ON p.rowid = {p}pages_fts.rowid"
            f" WHERE {p}pages_fts MATCH ? AND p.is_redirect = 0 ORDER BY rank LIMIT ?",
            (q, limit),
        )
        return [ReferenceHit(row["type"] or "", row["title"], row["title"], row["snippet"]) for row in rows]

    def lore_facts(
        self, n: int, category: str = "", seed: int | None = None, *, exclude: Collection[str] = ()
    ) -> list[LoreFact]:
        n = max(0, min(int(n), LORE_FACTS_CAP))
        if n == 0:
            return []
        clauses, params = (["category = ?"], [category]) if category else ([], [])
        if exclude:
            clauses.append(f"category NOT IN ({', '.join('?' for _ in exclude)})")
            params.extend(exclude)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        if seed is None:
            rows = self._fetch(f"SELECT * FROM lore_facts {where} ORDER BY random() LIMIT ?", [*params, n])
        else:
            # A draw the seed alone decides: every fact ordered by a hash of the seed and its id.
            rows = sorted(
                self._fetch(f"SELECT * FROM lore_facts {where}", params),
                key=lambda row: hashlib.sha256(f"{seed}:{row['id']}".encode()).digest(),
            )[:n]
        return [LoreFact(row["id"], row["text"], row["category"], row["source"]) for row in rows]

    def _page(self, row: sqlite3.Row) -> SettingPage:
        """The page `row`, with the first typed row that holds it."""
        kind, fields = row["type"] or "", {}
        for table in self.tables:
            typed = self._fetch(f"SELECT * FROM {self.prefix}{table} WHERE page = ?", (row["title"],))
            if typed:
                kind, fields = table, _fields(typed[0])
                break
        return SettingPage(row["title"], kind, fields, row["raw_text"] or "", self._categories(row["title"]))

    def _categories(self, title: str) -> tuple[str, ...]:
        rows = self._fetch(f"SELECT category FROM {self.prefix}categories WHERE page = ? ORDER BY category", (title,))
        return tuple(row["category"] for row in rows)


def _fields(row: sqlite3.Row, skip: Collection[str] = frozenset()) -> dict[str, str]:
    """A typed row's non-empty values, as text, without its key, its infobox image or the joined columns."""
    return {
        key: str(value)
        for key, value in dict(row).items()
        if key not in NOT_FIELDS and key not in skip and value is not None and str(value).strip()
    }


def build_wiki(data_dir: Path, db: Path, snapshots: Sequence[str], prefix: str) -> str:
    """Write a wiki pack's `db` from its gzipped SQL `snapshots` in `data_dir` (checked against `SHA256SUMS`), with
    the full-text index `<prefix>pages_fts`; returns the checksum file's sha. The file is put in place whole or not
    at all."""
    return store.load_snapshots(
        data_dir,
        db,
        snapshots,
        {},
        {f"{prefix}pages": ("title", "raw_text")},
        tokenizers={f"{prefix}pages": "unicode61"},
    )


def _summary(page: SettingPage) -> str:
    """A row's fields but its name, as one line: "realm: Hardby, size: Large town"."""
    return ", ".join(f"{key}: {value}" for key, value in page.fields.items() if key != "name")


class WikiSetting:
    """A setting over a wiki `store`. Without one it still has its kinds, its calendar and its maps, and every lookup
    finds nothing. Its lore facts leave out the categories in `exclude`, the ones other settings claim. A subclass
    gives its `id`, `title`, `KINDS`, `CALENDAR` and `MAPS`."""

    id: str
    title: str
    KINDS: Mapping[str, tuple[str, ...]]
    """Each kind and the wiki's typed tables that hold it, in the order the DM is shown the kinds."""
    CALENDAR: Calendar
    MAPS: tuple[WorldMapSource, ...] = ()
    world: str = ""

    def __init__(self, store: WikiStore | None = None, exclude: frozenset[str] = frozenset()) -> None:
        self.store = store
        self.exclude = exclude

    def kinds(self) -> tuple[str, ...]:
        return tuple(self.KINDS)

    def lookup(self, kind: str, query: str, limit: int = 5) -> list[ReferenceHit]:
        if kind not in self.KINDS:
            raise ValueError(f"unknown kind '{kind}'; kinds: {', '.join(self.KINDS)}")
        if self.store is None:
            return []
        rows = [row for table in self.KINDS[kind] for row in self.store.rows(table, query, limit)]
        rows.sort(key=lambda page: page.title)
        return [ReferenceHit(kind, page.title, page.title, _summary(page)) for page in rows[:limit]]

    def calendar(self) -> Calendar:
        return self.CALENDAR

    def world_maps(self) -> tuple[WorldMapSource, ...]:
        return self.MAPS

    def search(self, query: str, limit: int = 10) -> list[ReferenceHit]:
        return [] if self.store is None else self.store.search(query, limit)

    def page(self, title: str) -> SettingPage | None:
        return None if self.store is None else self.store.page(title)

    def lore_facts(self, n: int, category: str = "", seed: int | None = None) -> list[LoreFact]:
        return [] if self.store is None else self.store.lore_facts(n, category, seed, exclude=self.exclude)


class WikiPack:
    """A wiki setting pack's entry: the `setting` class it makes, its table `prefix`, the `snapshots` in its `data/`
    its `pack.db` is built from, and its typed `tables` in the order a page's kind is looked for (by default the
    kinds' tables). It opens one `SqliteWikiStore` per pack folder the first time a setting is
    made, and opens it anew once `pack.db` is rebuilt (`delve pack rebuild`); without a `pack.db` the setting has no
    pages and no facts."""

    def __init__(
        self, setting: type[WikiSetting], prefix: str, snapshots: Sequence[str], tables: Sequence[str] = ()
    ) -> None:
        self.setting_class = setting
        self.prefix = prefix
        self.snapshots = tuple(snapshots)
        self.tables = tuple(tables) or tuple(dict.fromkeys(t for ts in setting.KINDS.values() for t in ts))
        self._opened: dict[Path, tuple[tuple[int, int], SqliteWikiStore]] = {}
        self._lock = threading.Lock()

    def setting(self, root: Path, exclude: frozenset[str]) -> WikiSetting:
        return self.setting_class(self.store(root), exclude)

    def store(self, root: Path) -> SqliteWikiStore | None:
        """The wiki of the pack at `root`; None while it has no `pack.db`."""
        db = root / PACK_DB
        try:
            info = db.stat()
        except FileNotFoundError:
            return None
        stamp = (info.st_mtime_ns, info.st_size)
        with self._lock:
            held = self._opened.get(db)
            if held is not None and held[0] == stamp:
                return held[1]
            fresh = SqliteWikiStore(db, self.prefix, self.tables)
            self._opened[db] = (stamp, fresh)
        if held is not None:
            held[1].close()
        return fresh

    def build(self, root: Path, db: Path) -> None:
        build_wiki(root / "data", db, self.snapshots, self.prefix)
