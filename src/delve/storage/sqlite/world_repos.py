"""The world's campaign tables (plan 6 Task 2): factions, clocks, quests, the campaign's own facts, possessions, world
maps, merchants and generated images. Rows are the records' `to_dict()`; lists come back oldest first. And the
install's world-map pictures and setting maps (plan 7 Task 1)."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Connection, Table, func, select, text
from sqlalchemy.dialects.sqlite import insert

from delve.domain.world import (
    CampaignFact,
    CampaignImage,
    CampaignWorldMap,
    Clock,
    Faction,
    ImageKind,
    ImageStatus,
    Merchant,
    MonsterPicture,
    Possession,
    PossessionKind,
    Quest,
    QuestStatus,
    WorldPicture,
)
from delve.storage.sqlite.db import Database
from delve.storage.sqlite.play_repos import _require_campaign
from delve.storage.sqlite.tables import (
    campaign_facts,
    campaign_images,
    characters,
    clocks,
    factions,
    merchants,
    monster_pictures,
    possessions,
    quests,
    world_maps,
    world_pictures,
)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _upsert(connection: Connection, table: Table, row: dict[str, Any], keep: tuple[str, ...] = ()) -> None:
    """Insert the row, or update the one with its primary key in place (it keeps its place in the list), all but the
    `keep` columns."""
    keys = [column.name for column in table.primary_key.columns]
    statement = insert(table).values(row)
    statement = statement.on_conflict_do_update(
        index_elements=keys,
        set_={k: statement.excluded[k] for k in row if k not in keys and k not in keep},
    )
    connection.execute(statement)


class _CampaignRecords[R]:
    """A table keyed by (campaign_id, `key`), whose rows are the records of `record`."""

    table: Table
    record: type[R]
    key = "id"

    def __init__(self, db: Database) -> None:
        self._db = db

    def _get(self, connection: Connection, campaign_id: str, key: str) -> R | None:
        query = select(self.table).where(self.table.c.campaign_id == campaign_id, self.table.c[self.key] == key)
        row = connection.execute(query).first()
        return None if row is None else self.record.from_dict(dict(row._mapping))

    def get(self, campaign_id: str, id: str) -> R | None:
        with self._db.connect() as connection:
            return self._get(connection, campaign_id, id)

    def _list(self, campaign_id: str, *where: Any) -> list[R]:
        query = select(self.table).where(self.table.c.campaign_id == campaign_id, *where).order_by(text("rowid"))
        with self._db.connect() as connection:
            return [self.record.from_dict(dict(row._mapping)) for row in connection.execute(query)]

    def list(self, campaign_id: str) -> list[R]:
        return self._list(campaign_id)

    def put(self, record: R, /) -> R:
        with self._db.begin() as connection:
            _require_campaign(connection, record.campaign_id)
            _upsert(connection, self.table, record.to_dict())
        return record

    def delete(self, campaign_id: str, id: str) -> None:
        query = self.table.delete().where(self.table.c.campaign_id == campaign_id, self.table.c[self.key] == id)
        with self._db.begin() as connection:
            connection.execute(query)


class SqliteFactionRepository(_CampaignRecords[Faction]):
    table = factions
    record = Faction

    def list(self, campaign_id: str, *, known: bool | None = None) -> list[Faction]:
        return self._list(campaign_id, *(() if known is None else (factions.c.known == known,)))

    def delete(self, campaign_id: str, id: str) -> None:
        with self._db.transaction(), self._db.begin() as connection:
            connection.execute(
                clocks.update()
                .where(clocks.c.campaign_id == campaign_id, clocks.c.faction_id == id)
                .values(faction_id=None)
            )
            super().delete(campaign_id, id)


class SqliteQuestRepository(_CampaignRecords[Quest]):
    table = quests
    record = Quest

    def list(self, campaign_id: str, *, status: QuestStatus | None = None, known: bool | None = None) -> list[Quest]:
        where = [quests.c.status == status] if status is not None else []
        if known is not None:
            where.append(quests.c.known == known)
        return self._list(campaign_id, *where)


class SqlitePossessionRepository(_CampaignRecords[Possession]):
    table = possessions
    record = Possession

    def list(
        self, campaign_id: str, *, owner_id: str | None = None, kind: PossessionKind | None = None
    ) -> list[Possession]:
        where = [possessions.c.owner_id == owner_id] if owner_id is not None else []
        if kind is not None:
            where.append(possessions.c.kind == kind)
        return self._list(campaign_id, *where)

    def put(self, possession: Possession) -> Possession:
        now = _now()
        row = {**replace(possession, created_at=possession.created_at or now, updated_at=now).to_dict()}
        with self._db.begin() as connection:
            _require_campaign(connection, possession.campaign_id)
            if possession.owner_id is not None:
                owner = select(characters.c.id).where(
                    characters.c.id == possession.owner_id, characters.c.campaign_id == possession.campaign_id
                )
                if connection.execute(owner).first() is None:
                    raise KeyError(possession.owner_id)
            _upsert(connection, possessions, row, keep=("created_at",))
            return self._get(connection, possession.campaign_id, possession.id)


class SqliteWorldMapRepository(_CampaignRecords[CampaignWorldMap]):
    table = world_maps
    record = CampaignWorldMap
    key = "name"

    def get(self, campaign_id: str, name: str) -> CampaignWorldMap | None:
        return super().get(campaign_id, name)

    def put(self, world_map: CampaignWorldMap) -> CampaignWorldMap:
        return super().put(replace(world_map, updated_at=_now()))

    def delete(self, campaign_id: str, name: str) -> None:
        super().delete(campaign_id, name)


class SqliteMerchantRepository(_CampaignRecords[Merchant]):
    table = merchants
    record = Merchant


class _Numbered[R]:
    """A table with an autoincrement `id` and a `campaign_id`, whose rows are the records of `record`."""

    table: Table
    record: type[R]

    def __init__(self, db: Database) -> None:
        self._db = db

    def get(self, id: int) -> R | None:
        with self._db.connect() as connection:
            row = connection.execute(select(self.table).where(self.table.c.id == id)).first()
        return None if row is None else self.record.from_dict(dict(row._mapping))

    def _list(self, campaign_id: str, *where: Any) -> list[R]:
        query = select(self.table).where(self.table.c.campaign_id == campaign_id, *where).order_by(self.table.c.id)
        with self._db.connect() as connection:
            return [self.record.from_dict(dict(row._mapping)) for row in connection.execute(query)]

    def add(self, record: R, /) -> R:
        row = {k: v for k, v in record.to_dict().items() if k != "id"}
        with self._db.begin() as connection:
            _require_campaign(connection, record.campaign_id)
            id = connection.execute(self.table.insert().values(row)).inserted_primary_key[0]
        return replace(record, id=id)

    def delete(self, id: int) -> None:
        with self._db.begin() as connection:
            connection.execute(self.table.delete().where(self.table.c.id == id))


class SqliteClockRepository(_Numbered[Clock]):
    table = clocks
    record = Clock

    def list(self, campaign_id: str, *, faction_id: str | None = None, running: bool | None = None) -> list[Clock]:
        where = [clocks.c.faction_id == faction_id] if faction_id is not None else []
        if running is not None:
            where.append(clocks.c.done_day.is_(None) if running else clocks.c.done_day.is_not(None))
        return self._list(campaign_id, *where)

    def put(self, clock: Clock) -> Clock:
        values = {k: v for k, v in clock.to_dict().items() if k not in ("id", "campaign_id")}
        query = clocks.update().where(clocks.c.id == clock.id, clocks.c.campaign_id == clock.campaign_id)
        with self._db.begin() as connection:
            if connection.execute(query.values(values)).rowcount == 0:
                raise KeyError(clock.id)
        return clock


class SqliteCampaignFactRepository(_Numbered[CampaignFact]):
    table = campaign_facts
    record = CampaignFact

    def list(self, campaign_id: str, *, query: str = "", category: str = "") -> list[CampaignFact]:
        where = [func.lower(campaign_facts.c.text).contains(query.lower(), autoescape=True)] if query else []
        if category:
            where.append(campaign_facts.c.category == category)
        return self._list(campaign_id, *where)


class SqliteCampaignImageRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def get(self, id: str) -> CampaignImage | None:
        with self._db.connect() as connection:
            row = connection.execute(select(campaign_images).where(campaign_images.c.id == id)).first()
        return None if row is None else CampaignImage.from_dict(dict(row._mapping))

    def _list(self, *where: Any) -> list[CampaignImage]:
        query = select(campaign_images).where(*where).order_by(text("rowid"))
        with self._db.connect() as connection:
            return [CampaignImage.from_dict(dict(row._mapping)) for row in connection.execute(query)]

    def list(
        self,
        campaign_id: str,
        *,
        kind: ImageKind | None = None,
        subject_id: str | None = None,
        status: ImageStatus | None = None,
    ) -> list[CampaignImage]:
        where = [campaign_images.c.campaign_id == campaign_id]
        for column, value in (("kind", kind), ("subject_id", subject_id), ("status", status)):
            if value is not None:
                where.append(campaign_images.c[column] == value)
        return self._list(*where)

    def painting(self) -> list[CampaignImage]:
        return self._list(campaign_images.c.status == "painting")

    def everywhere(self, kind: ImageKind, status: ImageStatus) -> list[CampaignImage]:
        return self._list(campaign_images.c.kind == kind, campaign_images.c.status == status)

    def put(self, image: CampaignImage) -> CampaignImage:
        row = replace(image, created_at=image.created_at or _now()).to_dict()
        with self._db.begin() as connection:
            _require_campaign(connection, image.campaign_id)
            _upsert(connection, campaign_images, row, keep=("created_at", "campaign_id"))
            stored = connection.execute(select(campaign_images).where(campaign_images.c.id == image.id)).one()
        return CampaignImage.from_dict(dict(stored._mapping))

    def delete(self, id: str) -> None:
        with self._db.begin() as connection:
            connection.execute(campaign_images.delete().where(campaign_images.c.id == id))


class SqliteWorldPictureRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def get(self, id: str) -> WorldPicture | None:
        with self._db.connect() as connection:
            row = connection.execute(select(world_pictures).where(world_pictures.c.id == id)).first()
        return None if row is None else WorldPicture.from_dict(dict(row._mapping))

    def put(self, picture: WorldPicture) -> WorldPicture:
        with self._db.begin() as connection:
            _upsert(connection, world_pictures, replace(picture, created_at=_now()).to_dict(), keep=("created_at",))
            row = connection.execute(select(world_pictures).where(world_pictures.c.id == picture.id)).one()
        return WorldPicture.from_dict(dict(row._mapping))


class SqliteMonsterPictureRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def get(self, slug: str) -> MonsterPicture | None:
        with self._db.connect() as connection:
            row = connection.execute(select(monster_pictures).where(monster_pictures.c.slug == slug)).first()
        return None if row is None else MonsterPicture.from_dict(dict(row._mapping))

    def list(self) -> list[MonsterPicture]:
        with self._db.connect() as connection:
            rows = connection.execute(select(monster_pictures).order_by(monster_pictures.c.slug)).all()
        return [MonsterPicture.from_dict(dict(row._mapping)) for row in rows]

    def put(self, picture: MonsterPicture) -> MonsterPicture:
        now = _now()
        row = replace(picture, created_at=now, updated_at=now).to_dict()
        with self._db.begin() as connection:
            _upsert(connection, monster_pictures, row, keep=("created_at",))
            stored = connection.execute(select(monster_pictures).where(monster_pictures.c.slug == picture.slug)).one()
        return MonsterPicture.from_dict(dict(stored._mapping))
