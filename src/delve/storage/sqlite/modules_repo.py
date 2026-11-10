"""Modules: the working copy in `modules`, `module_maps`, `module_texts` and `module_sources`, and immutable revisions
in `module_revisions`, which copy the text and the source, and whose text is indexed for search when they are made."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Connection, delete, func, select, text, update
from sqlalchemy.dialects.sqlite import insert

from delve.domain import new_id
from delve.domain.modules import (
    BannerSource,
    LibraryOrigin,
    Module,
    ModuleBanner,
    ModuleCategory,
    ModuleHead,
    ModuleMap,
    Revision,
)
from delve.storage.interfaces import CategoryNameTaken, ModuleInUse
from delve.storage.sqlite.db import Database
from delve.storage.sqlite.module_sources_repo import revision_source, working_source
from delve.storage.sqlite.module_texts_repo import drop_index, index_revision, revision_text, working_text
from delve.storage.sqlite.tables import (
    campaigns,
    module_blobs,
    module_categories,
    module_maps,
    module_revisions,
    module_sources,
    module_texts,
    modules,
)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _map_from(raw: Any) -> ModuleMap:
    return ModuleMap(name=raw["name"], role=raw["role"], source=raw["source"], is_default=bool(raw["is_default"]))


def _map_to_json(map: ModuleMap) -> dict[str, Any]:
    return {"name": map.name, "role": map.role, "source": map.source, "is_default": map.is_default}


def _load(connection: Connection, id: str) -> Module | None:
    row = connection.execute(select(modules).where(modules.c.id == id)).first()
    if row is None:
        return None
    maps = connection.execute(
        select(module_maps).where(module_maps.c.module_id == id).order_by(module_maps.c.position)
    ).mappings()
    head = connection.execute(
        select(func.max(module_revisions.c.number)).where(module_revisions.c.module_id == id)
    ).scalar()
    return Module(
        id=row.id,
        title=row.title,
        metadata=row.metadata,
        maps=tuple(_map_from(m) for m in maps),
        head_revision=head,
        updated_at=row.updated_at,
        draft=bool(row.draft),
        library_key=row.library_key,
        library_version=row.library_version,
        library_hash=row.library_hash,
        library_origin=row.library_origin,
        library_author=row.library_author,
        category_id=row.category_id,
        banner=_banner(row),
    )


_NO_BANNER = {"banner_blob": None, "banner_mime": None, "banner_source": None, "banner_status": None,
              "banner_error": None, "banner_prompt": None}  # fmt: skip


def _banner(row: Any) -> ModuleBanner | None:
    """The row's banner, None when it has neither a picture nor a painting."""
    if row.banner_blob is None and row.banner_status is None:
        return None
    return ModuleBanner(row.banner_blob, row.banner_mime, row.banner_source, row.banner_status, row.banner_error,
                        row.banner_prompt)  # fmt: skip


def _require(connection: Connection, id: str) -> Module:
    module = _load(connection, id)
    if module is None:
        raise KeyError(id)
    return module


def _touch(connection: Connection, id: str) -> None:
    connection.execute(update(modules).where(modules.c.id == id).values(updated_at=_now()))


def _revision(connection: Connection, module_id: str, number: int | None = None) -> Revision | None:
    query = select(module_revisions).where(module_revisions.c.module_id == module_id)
    if number is None:
        query = query.order_by(module_revisions.c.number.desc()).limit(1)
    else:
        query = query.where(module_revisions.c.number == number)
    row = connection.execute(query).first()
    if row is None:
        return None
    return Revision(
        module_id=row.module_id,
        number=row.number,
        title=row.title,
        metadata=row.metadata,
        maps=tuple(_map_from(m) for m in row.maps),
        created_at=row.created_at,
    )


def _same(connection: Connection, module: Module, revision: Revision | None) -> bool:
    if revision is None:
        return False
    if (module.title, module.metadata, module.maps) != (revision.title, revision.metadata, revision.maps):
        return False
    if working_source(connection, module.id) != revision_source(connection, module.id, revision.number):
        return False
    return working_text(connection, module.id) == revision_text(connection, module.id, revision.number)


class SqliteModuleRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def create(self, title: str, metadata: dict[str, Any] | None = None, *, draft: bool = False) -> Module:
        now = _now()
        row = {
            "id": new_id("mod"),
            "title": title,
            "metadata": metadata or {},
            "created_at": now,
            "updated_at": now,
            "draft": draft,
        }
        with self._db.begin() as connection:
            connection.execute(modules.insert().values(row))
            return _require(connection, row["id"])

    def get(self, id: str) -> Module | None:
        with self._db.connect() as connection:
            return _load(connection, id)

    def list(self) -> list[Module]:
        with self._db.connect() as connection:
            ids = connection.execute(select(modules.c.id).order_by(text("rowid"))).scalars().all()
            return [_require(connection, id) for id in ids]

    def heads(self) -> dict[str, ModuleHead]:
        with self._db.connect() as connection:
            rows = connection.execute(select(modules).order_by(text("rowid"))).all()
        return {row.id: ModuleHead(row.title, _banner(row)) for row in rows}

    def delete(self, id: str) -> None:
        with self._db.begin() as connection:
            used_by = connection.execute(
                select(campaigns.c.id).where(campaigns.c.module_id == id).order_by(text("rowid"))
            ).scalars()
            campaign_ids = tuple(used_by)
            if campaign_ids:
                raise ModuleInUse(id, campaign_ids)
            connection.execute(delete(modules).where(modules.c.id == id))
            drop_index(connection, id)

    def rename(self, id: str, title: str) -> Module:
        return self._update(id, title=title)

    def set_metadata(self, id: str, metadata: dict[str, Any]) -> Module:
        return self._update(id, metadata=metadata)

    def set_draft(self, id: str, draft: bool) -> Module:
        return self._update(id, draft=draft)

    def set_library(
        self, id: str, *, key: str, version: int, hash: str, origin: LibraryOrigin, author: str | None
    ) -> Module:
        with self._db.begin() as connection:
            _require(connection, id)
            values = {"library_key": key, "library_version": version, "library_hash": hash,
                      "library_origin": origin, "library_author": author}
            connection.execute(update(modules).where(modules.c.id == id).values(**values))
            return _require(connection, id)

    def take_working_copy(self, id: str, source_id: str) -> Module:
        with self._db.begin() as connection:
            _require(connection, id)
            source = _require(connection, source_id)
            # A newer version's banner (DEL-123) comes along; without one, the module keeps its own.
            banner = (
                {"banner_blob": source.banner.blob, "banner_mime": source.banner.mime, "banner_source": source.banner.source}
                if source.banner is not None and source.banner.blob is not None
                else {}
            )
            connection.execute(
                update(modules)
                .where(modules.c.id == id)
                .values(title=source.title, metadata=source.metadata, updated_at=_now(), **banner)
            )
            for table in (module_maps, module_texts, module_sources):
                connection.execute(delete(table).where(table.c.module_id == id))
                connection.execute(update(table).where(table.c.module_id == source_id).values(module_id=id))
            # The links are added, never dropped: the module's revisions may still show the pictures they had.
            links = connection.execute(
                select(module_blobs.c.role, module_blobs.c.sha256).where(module_blobs.c.module_id == source_id)
            ).all()
            for role, sha in links:
                row = {"module_id": id, "role": role, "sha256": sha}
                connection.execute(insert(module_blobs).values(row).on_conflict_do_nothing())
            return _require(connection, id)

    def put_map(self, id: str, map: ModuleMap) -> Module:
        with self._db.begin() as connection:
            _require(connection, id)
            position = connection.execute(
                select(func.coalesce(func.max(module_maps.c.position) + 1, 0)).where(module_maps.c.module_id == id)
            ).scalar()
            if map.is_default:
                connection.execute(update(module_maps).where(module_maps.c.module_id == id).values(is_default=False))
            upsert = insert(module_maps).values(module_id=id, position=position, **_map_to_json(map))
            upsert = upsert.on_conflict_do_update(
                index_elements=[module_maps.c.module_id, module_maps.c.name],
                set_={"role": map.role, "source": map.source, "is_default": map.is_default},
            )
            connection.execute(upsert)
            _touch(connection, id)
            return _require(connection, id)

    def delete_map(self, id: str, name: str) -> Module:
        with self._db.begin() as connection:
            _require(connection, id)
            gone = connection.execute(
                delete(module_maps).where(module_maps.c.module_id == id, module_maps.c.name == name)
            )
            if gone.rowcount == 0:
                raise KeyError(name)
            _touch(connection, id)
            return _require(connection, id)

    def set_default_map(self, id: str, name: str) -> Module:
        with self._db.begin() as connection:
            module = _require(connection, id)
            if name not in {m.name for m in module.maps}:
                raise KeyError(name)
            connection.execute(
                update(module_maps).where(module_maps.c.module_id == id).values(is_default=module_maps.c.name == name)
            )
            _touch(connection, id)
            return _require(connection, id)

    def changed_since(self, id: str, revision: int | None) -> bool:
        with self._db.connect() as connection:
            module = _require(connection, id)
            return revision is None or not _same(connection, module, _revision(connection, id, revision))

    def set_category(self, id: str, category_id: str | None) -> Module:
        with self._db.begin() as connection:
            _require(connection, id)
            if category_id is not None and connection.execute(
                select(module_categories.c.id).where(module_categories.c.id == category_id)
            ).first() is None:
                raise KeyError(category_id)
            connection.execute(update(modules).where(modules.c.id == id).values(category_id=category_id))
            return _require(connection, id)

    def set_banner(self, id: str, blob: str, mime: str, source: BannerSource) -> Module:
        with self._db.begin() as connection:
            _require(connection, id)
            connection.execute(insert(module_blobs).values(module_id=id, role="banner", sha256=blob).on_conflict_do_nothing())
            values = {**_NO_BANNER, "banner_blob": blob, "banner_mime": mime, "banner_source": source}
            connection.execute(update(modules).where(modules.c.id == id).values(**values))
            return _require(connection, id)

    def banner_painting(self, id: str, prompt: str) -> Module:
        return self._banner_state(id, banner_status="painting", banner_error=None, banner_prompt=prompt)

    def banner_failed(self, id: str, error: str) -> Module:
        return self._banner_state(id, banner_status="failed", banner_error=error)

    def clear_banner(self, id: str) -> Module:
        return self._banner_state(id, **_NO_BANNER)

    def _banner_state(self, id: str, **values: Any) -> Module:
        with self._db.begin() as connection:
            _require(connection, id)
            connection.execute(update(modules).where(modules.c.id == id).values(**values))
            return _require(connection, id)

    def _update(self, id: str, **values: Any) -> Module:
        with self._db.begin() as connection:
            _require(connection, id)
            connection.execute(update(modules).where(modules.c.id == id).values(updated_at=_now(), **values))
            return _require(connection, id)


class SqliteRevisionRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def snapshot(self, module_id: str) -> Revision:
        with self._db.begin() as connection:
            module = _require(connection, module_id)
            latest = _revision(connection, module_id)
            if latest is not None and _same(connection, module, latest):
                return latest
            number = 1 if latest is None else latest.number + 1
            raw_text = working_text(connection, module_id)
            connection.execute(
                module_revisions.insert().values(
                    module_id=module_id,
                    number=number,
                    title=module.title,
                    metadata=module.metadata,
                    maps=[_map_to_json(m) for m in module.maps],
                    created_at=_now(),
                    text=raw_text,
                    source=working_source(connection, module_id),
                )
            )
            index_revision(connection, module_id, number, raw_text)
            return _revision(connection, module_id, number)

    def get(self, module_id: str, number: int) -> Revision | None:
        with self._db.connect() as connection:
            return _revision(connection, module_id, number)

    def latest(self, module_id: str) -> Revision | None:
        with self._db.connect() as connection:
            return _revision(connection, module_id)


class SqliteModuleCategoryRepository:
    """The organisers' categories of modules (DEL-114). A deleted one's modules get none, in the same transaction."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def list(self) -> list[ModuleCategory]:
        with self._db.connect() as connection:
            return _categories(connection)

    def get(self, id: str) -> ModuleCategory | None:
        with self._db.connect() as connection:
            return next((c for c in _categories(connection) if c.id == id), None)

    def create(self, name: str) -> ModuleCategory:
        with self._db.begin() as connection:
            listed = _categories(connection)
            _free(listed, name)
            category = ModuleCategory(new_id("cat"), name, len(listed))
            connection.execute(insert(module_categories).values(id=category.id, name=name, position=category.position))
            return category

    def rename(self, id: str, name: str) -> ModuleCategory:
        with self._db.begin() as connection:
            listed = _categories(connection)
            found = next((c for c in listed if c.id == id), None)
            if found is None:
                raise KeyError(id)
            _free([c for c in listed if c.id != id], name)
            connection.execute(update(module_categories).where(module_categories.c.id == id).values(name=name))
            return ModuleCategory(id, name, found.position)

    def move(self, id: str, position: int) -> list[ModuleCategory]:
        with self._db.begin() as connection:
            listed = _categories(connection)
            found = next((c for c in listed if c.id == id), None)
            if found is None:
                raise KeyError(id)
            rest = [c for c in listed if c.id != id]
            rest.insert(max(0, min(position, len(rest))), found)
            for index, category in enumerate(rest):
                connection.execute(
                    update(module_categories).where(module_categories.c.id == category.id).values(position=index)
                )
            return _categories(connection)

    def delete(self, id: str) -> int:
        with self._db.begin() as connection:
            listed = _categories(connection)
            if not any(c.id == id for c in listed):
                raise KeyError(id)
            moved = connection.execute(update(modules).where(modules.c.category_id == id).values(category_id=None))
            connection.execute(delete(module_categories).where(module_categories.c.id == id))
            for index, category in enumerate(c for c in listed if c.id != id):
                connection.execute(
                    update(module_categories).where(module_categories.c.id == category.id).values(position=index)
                )
            return moved.rowcount


def _categories(connection: Connection) -> list[ModuleCategory]:
    rows = connection.execute(select(module_categories).order_by(module_categories.c.position, module_categories.c.name))
    return [ModuleCategory(row.id, row.name, row.position) for row in rows]


def _free(others: list[ModuleCategory], name: str) -> None:
    if any(c.name.casefold() == name.casefold() for c in others):
        raise CategoryNameTaken(name)
