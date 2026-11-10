"""A campaign's own maps (campaign maps, 2026-10-23), by name, in the order they were first put."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import delete, func, select

from delve.domain.modules import ModuleMap
from delve.storage.sqlite.db import Database
from delve.storage.sqlite.tables import campaign_maps, campaigns


def _map(name: str, source: str) -> ModuleMap:
    return ModuleMap(name, "map", source, False)


class SqliteCampaignMapRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def get(self, campaign_id: str, name: str) -> ModuleMap | None:
        query = select(campaign_maps.c.source).where(
            campaign_maps.c.campaign_id == campaign_id, campaign_maps.c.name == name
        )
        with self._db.connect() as connection:
            source = connection.execute(query).scalar()
        return None if source is None else _map(name, source)

    def list(self, campaign_id: str) -> list[ModuleMap]:
        query = (
            select(campaign_maps.c.name, campaign_maps.c.source)
            .where(campaign_maps.c.campaign_id == campaign_id)
            .order_by(campaign_maps.c.position)
        )
        with self._db.connect() as connection:
            return [_map(name, source) for name, source in connection.execute(query)]

    def put(self, campaign_id: str, name: str, source: str) -> None:
        now = datetime.now(UTC).isoformat()
        where = (campaign_maps.c.campaign_id == campaign_id, campaign_maps.c.name == name)
        with self._db.begin() as connection:
            if connection.execute(select(campaigns.c.id).where(campaigns.c.id == campaign_id)).first() is None:
                raise KeyError(campaign_id)
            if connection.execute(select(campaign_maps.c.name).where(*where)).first() is not None:
                connection.execute(campaign_maps.update().where(*where).values(source=source, updated_at=now))
                return
            last = connection.execute(
                select(func.max(campaign_maps.c.position)).where(campaign_maps.c.campaign_id == campaign_id)
            ).scalar()
            connection.execute(
                campaign_maps.insert().values(
                    campaign_id=campaign_id,
                    name=name,
                    position=0 if last is None else last + 1,
                    source=source,
                    created_at=now,
                    updated_at=now,
                )
            )

    def delete(self, campaign_id: str, name: str) -> None:
        with self._db.begin() as connection:
            connection.execute(
                delete(campaign_maps).where(campaign_maps.c.campaign_id == campaign_id, campaign_maps.c.name == name)
            )
