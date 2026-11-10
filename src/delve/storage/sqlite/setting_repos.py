"""The setting's content of this install (settings plan Task 2): its added and overridden pages, its facts, the DM's
proposals and the setting's own world maps. Searches match in Python, casefolded, never by SQL `LIKE`, so `%` and `_`
are plain characters."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from sqlalchemy import Connection, select, text

from delve.domain.setting_content import Proposal, ProposalKind, ProposalStatus, SettingAddition, SettingFact, title_key
from delve.domain.world import WorldMapSource
from delve.storage.sqlite.db import Database
from delve.storage.sqlite.play_repos import _now, _require_campaign
from delve.storage.sqlite.tables import proposals, setting_facts, setting_maps, setting_pages
from delve.storage.sqlite.world_repos import _upsert


def _holds(query: str, *texts: str) -> bool:
    needle = query.casefold()
    return any(needle in t.casefold() for t in texts)


def _addition(row: Any) -> SettingAddition:
    return SettingAddition.from_dict({k: v for k, v in row._mapping.items() if k != "title_key"})


class SqliteSettingPageRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def _get(self, connection: Connection, setting: str, title: str) -> SettingAddition | None:
        query = select(setting_pages).where(
            setting_pages.c.setting == setting, setting_pages.c.title_key == title_key(title)
        )
        row = connection.execute(query).first()
        return None if row is None else _addition(row)

    def get(self, setting: str, title: str) -> SettingAddition | None:
        with self._db.connect() as connection:
            return self._get(connection, setting, title)

    def list(self, setting: str, *, kind: str | None = None, query: str = "") -> list[SettingAddition]:
        where = [setting_pages.c.setting == setting]
        if kind is not None:
            where.append(setting_pages.c.kind == kind)
        statement = select(setting_pages).where(*where).order_by(setting_pages.c.title_key)
        with self._db.connect() as connection:
            found = [_addition(row) for row in connection.execute(statement)]
        return [a for a in found if _holds(query, a.title, a.text)] if query else found

    def put(self, addition: SettingAddition) -> SettingAddition:
        now = _now()
        row = {**replace(addition, created_at=now, updated_at=now).to_dict(), "title_key": title_key(addition.title)}
        with self._db.begin() as connection:
            _upsert(connection, setting_pages, row, keep=("created_at",))
            stored = self._get(connection, addition.setting, addition.title)
        assert stored is not None
        return stored

    def delete(self, setting: str, title: str) -> None:
        query = setting_pages.delete().where(
            setting_pages.c.setting == setting, setting_pages.c.title_key == title_key(title)
        )
        with self._db.begin() as connection:
            connection.execute(query)


def _fact(row: Any) -> SettingFact:
    return SettingFact.from_dict({k: v for k, v in row._mapping.items() if k != "updated_at"})


class SqliteSettingFactRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def _get(self, connection: Connection, id: int) -> SettingFact | None:
        row = connection.execute(select(setting_facts).where(setting_facts.c.id == id)).first()
        return None if row is None else _fact(row)

    def get(self, id: int) -> SettingFact | None:
        with self._db.connect() as connection:
            return self._get(connection, id)

    def list(self, setting: str, *, query: str = "") -> list[SettingFact]:
        statement = select(setting_facts).where(setting_facts.c.setting == setting).order_by(setting_facts.c.id)
        with self._db.connect() as connection:
            found = [_fact(row) for row in connection.execute(statement)]
        return [f for f in found if _holds(query, f.text)] if query else found

    def add(self, fact: SettingFact) -> SettingFact:
        now = _now()
        row = {k: v for k, v in replace(fact, created_at=now).to_dict().items() if k != "id"}
        with self._db.begin() as connection:
            id = connection.execute(setting_facts.insert().values({**row, "updated_at": now})).inserted_primary_key[0]
            stored = self._get(connection, id)
        assert stored is not None
        return stored

    def put(self, fact: SettingFact) -> SettingFact:
        values = {k: v for k, v in fact.to_dict().items() if k not in ("id", "created_at")}
        query = setting_facts.update().where(setting_facts.c.id == fact.id).values({**values, "updated_at": _now()})
        with self._db.begin() as connection:
            if connection.execute(query).rowcount == 0:
                raise KeyError(fact.id)
            stored = self._get(connection, fact.id)
        assert stored is not None
        return stored

    def delete(self, id: int) -> None:
        with self._db.begin() as connection:
            connection.execute(setting_facts.delete().where(setting_facts.c.id == id))


class SqliteProposalRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def _get(self, connection: Connection, id: int) -> Proposal | None:
        row = connection.execute(select(proposals).where(proposals.c.id == id)).first()
        return None if row is None else Proposal.from_dict(dict(row._mapping))

    def get(self, id: int) -> Proposal | None:
        with self._db.connect() as connection:
            return self._get(connection, id)

    def list(
        self,
        setting: str | None = None,
        *,
        campaign_id: str | None = None,
        status: ProposalStatus | None = None,
        kind: ProposalKind | None = None,
    ) -> list[Proposal]:
        where = [
            proposals.c[column] == value
            for column, value in (
                ("setting", setting),
                ("campaign_id", campaign_id),
                ("status", status),
                ("kind", kind),
            )
            if value is not None
        ]
        statement = select(proposals).where(*where).order_by(proposals.c.id)
        with self._db.connect() as connection:
            return [Proposal.from_dict(dict(row._mapping)) for row in connection.execute(statement)]

    def add(self, proposal: Proposal) -> Proposal:
        row = {k: v for k, v in replace(proposal, created_at=_now()).to_dict().items() if k != "id"}
        with self._db.begin() as connection:
            _require_campaign(connection, proposal.campaign_id)
            id = connection.execute(proposals.insert().values(row)).inserted_primary_key[0]
            stored = self._get(connection, id)
        assert stored is not None
        return stored

    def put(self, proposal: Proposal) -> Proposal:
        values = {k: v for k, v in proposal.to_dict().items() if k not in ("id", "created_at")}
        query = proposals.update().where(proposals.c.id == proposal.id).values(values)
        with self._db.begin() as connection:
            _require_campaign(connection, proposal.campaign_id)
            if connection.execute(query).rowcount == 0:
                raise KeyError(proposal.id)
            stored = self._get(connection, proposal.id)
        assert stored is not None
        return stored


def _world_map(row: Any) -> WorldMapSource:
    return WorldMapSource(
        row.name, row.title, "", geo=row.geo, picture=row.picture, status=row.status, reading=row.reading
    )


class SqliteSettingMapRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def _get(self, connection: Connection, setting: str, name: str) -> WorldMapSource | None:
        query = select(setting_maps).where(setting_maps.c.setting == setting, setting_maps.c.name == name)
        row = connection.execute(query).first()
        return None if row is None else _world_map(row)

    def get(self, setting: str, name: str) -> WorldMapSource | None:
        with self._db.connect() as connection:
            return self._get(connection, setting, name)

    def list(self, setting: str) -> list[WorldMapSource]:
        query = select(setting_maps).where(setting_maps.c.setting == setting).order_by(text("rowid"))
        with self._db.connect() as connection:
            return [_world_map(row) for row in connection.execute(query)]

    def put(self, setting: str, world_map: WorldMapSource) -> WorldMapSource:
        if world_map.geo is None:
            raise ValueError(f"the setting map {world_map.name!r} has no GeoJSON document")
        now = _now()
        row = {
            "setting": setting,
            "name": world_map.name,
            "title": world_map.title,
            "geo": world_map.geo,
            "picture": world_map.picture,
            "status": world_map.status,
            "reading": world_map.reading,
            "created_at": now,
            "updated_at": now,
        }
        with self._db.begin() as connection:
            _upsert(connection, setting_maps, row, keep=("created_at",))
            stored = self._get(connection, setting, world_map.name)
        assert stored is not None
        return stored

    def delete(self, setting: str, name: str) -> None:
        query = setting_maps.delete().where(setting_maps.c.setting == setting, setting_maps.c.name == name)
        with self._db.begin() as connection:
            connection.execute(query)
