"""The message board (DEL-297): zones, topics, posts, read marks and first visits."""

from __future__ import annotations

from dataclasses import asdict, replace

from sqlalchemy import delete, func, literal_column, select, update
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.exc import IntegrityError

from delve.domain import new_id
from delve.domain.board import Post, Topic, Zone
from delve.storage.sqlite.db import Database
from delve.storage.sqlite.tables import board_follows, board_posts, board_reads, board_topics, board_visits, board_zones


def _zone(row) -> Zone:
    return Zone(**{**row._mapping, "moderators": tuple(row.moderators), "members": tuple(row.members)})


def _zone_values(zone: Zone) -> dict:
    return {**asdict(zone), "moderators": list(zone.moderators), "members": list(zone.members)}


def _topic(row) -> Topic:
    return Topic(**row._mapping)


def _post(row) -> Post:
    return Post(**row._mapping)


class SqliteBoardRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def create_zone(self, zone: Zone) -> Zone:
        try:
            with self._db.begin() as connection:
                last = connection.execute(select(func.max(board_zones.c.position))).scalar()
                position = zone.position if zone.id else (0 if last is None else last + 1)
                stored = replace(zone, id=zone.id or new_id("bzn"), position=position)
                connection.execute(board_zones.insert().values(_zone_values(stored)))
        except IntegrityError:
            raise ValueError("another zone belongs to the campaign") from None
        return stored

    def get_zone(self, id: str) -> Zone | None:
        with self._db.connect() as connection:
            row = connection.execute(select(board_zones).where(board_zones.c.id == id)).first()
        return None if row is None else _zone(row)

    def zones(self) -> list[Zone]:
        query = select(board_zones).order_by(board_zones.c.position, board_zones.c.created_at, board_zones.c.id)
        with self._db.connect() as connection:
            return [_zone(row) for row in connection.execute(query)]

    def zone_of_campaign(self, campaign_id: str) -> Zone | None:
        with self._db.connect() as connection:
            row = connection.execute(select(board_zones).where(board_zones.c.campaign_id == campaign_id)).first()
        return None if row is None else _zone(row)

    def save_zone(self, zone: Zone) -> Zone:
        values = {key: value for key, value in _zone_values(zone).items() if key not in ("id", "created_at")}
        try:
            with self._db.begin() as connection:
                changed = connection.execute(update(board_zones).where(board_zones.c.id == zone.id).values(values))
                if changed.rowcount == 0:
                    raise KeyError(zone.id)
        except IntegrityError:
            raise ValueError("another zone belongs to the campaign") from None
        return zone

    def delete_zone(self, id: str) -> None:
        with self._db.begin() as connection:
            connection.execute(delete(board_zones).where(board_zones.c.id == id))

    def add_topic(self, topic: Topic, first: Post) -> tuple[Topic, Post]:
        stored = replace(topic, id=new_id("btp"))
        stored_first = replace(first, id=new_id("bps"), topic_id=stored.id)
        with self._db.begin() as connection:
            connection.execute(board_topics.insert().values(asdict(stored)))
            connection.execute(board_posts.insert().values(asdict(stored_first)))
        return stored, stored_first

    def get_topic(self, id: str) -> Topic | None:
        with self._db.connect() as connection:
            row = connection.execute(select(board_topics).where(board_topics.c.id == id)).first()
        return None if row is None else _topic(row)

    def topics(self, zone_id: str) -> list[Topic]:
        query = (
            select(board_topics)
            .where(board_topics.c.zone_id == zone_id)
            .order_by(board_topics.c.pinned.desc(), board_topics.c.last_post_at.desc(), board_topics.c.id)
        )
        with self._db.connect() as connection:
            return [_topic(row) for row in connection.execute(query)]

    def save_topic(self, topic: Topic) -> Topic:
        values = {"title": topic.title, "pinned": topic.pinned, "locked": topic.locked}
        with self._db.begin() as connection:
            changed = connection.execute(update(board_topics).where(board_topics.c.id == topic.id).values(values))
            if changed.rowcount == 0:
                raise KeyError(topic.id)
        return topic

    def delete_topic(self, id: str) -> None:
        with self._db.begin() as connection:
            connection.execute(delete(board_topics).where(board_topics.c.id == id))

    def add_post(self, post: Post) -> Post:
        stored = replace(post, id=new_id("bps"))
        with self._db.begin() as connection:
            changed = connection.execute(
                update(board_topics)
                .where(board_topics.c.id == post.topic_id)
                .values(last_post_at=post.created_at, last_author_id=post.author_id, posts=board_topics.c.posts + 1)
            )
            if changed.rowcount == 0:
                raise KeyError(post.topic_id)
            connection.execute(board_posts.insert().values(asdict(stored)))
        return stored

    def get_post(self, id: str) -> Post | None:
        with self._db.connect() as connection:
            row = connection.execute(select(board_posts).where(board_posts.c.id == id)).first()
        return None if row is None else _post(row)

    def posts(self, topic_id: str, offset: int = 0, limit: int = 30) -> list[Post]:
        query = (
            select(board_posts)
            .where(board_posts.c.topic_id == topic_id)
            .order_by(board_posts.c.created_at, literal_column("rowid"))
            .offset(offset)
            .limit(limit)
        )
        with self._db.connect() as connection:
            return [_post(row) for row in connection.execute(query)]

    def post_index(self, post: Post) -> int:
        """Posts before this one: earlier in time, or the same time and an earlier row."""
        rowid = select(literal_column("rowid")).where(board_posts.c.id == post.id).scalar_subquery()
        before = select(func.count()).where(
            board_posts.c.topic_id == post.topic_id,
            (board_posts.c.created_at < post.created_at)
            | ((board_posts.c.created_at == post.created_at) & (literal_column("rowid") < rowid)),
        )
        with self._db.connect() as connection:
            return connection.execute(before).scalar_one()

    def save_post(self, post: Post) -> Post:
        values = {"text": post.text, "edited_at": post.edited_at, "removed": post.removed, "picture": post.picture}
        with self._db.begin() as connection:
            changed = connection.execute(update(board_posts).where(board_posts.c.id == post.id).values(values))
            if changed.rowcount == 0:
                raise KeyError(post.id)
        return post

    def mark_read(self, account_id: str, topic_id: str, at: str) -> None:
        statement = insert(board_reads).values(account_id=account_id, topic_id=topic_id, at=at)
        statement = statement.on_conflict_do_update(
            index_elements=["account_id", "topic_id"], set_={"at": statement.excluded.at}, where=board_reads.c.at < at
        )
        try:
            with self._db.begin() as connection:
                connection.execute(statement)
        except IntegrityError:
            pass  # the topic went a moment ago: nothing to mark

    def read_marks(self, account_id: str) -> dict[str, str]:
        with self._db.connect() as connection:
            rows = connection.execute(select(board_reads).where(board_reads.c.account_id == account_id))
            return {row.topic_id: row.at for row in rows}

    def first_visit(self, account_id: str) -> str | None:
        with self._db.connect() as connection:
            return connection.execute(
                select(board_visits.c.first_at).where(board_visits.c.account_id == account_id)
            ).scalar()

    def set_first_visit(self, account_id: str, at: str) -> None:
        with self._db.begin() as connection:
            connection.execute(insert(board_visits).values(account_id=account_id, first_at=at).on_conflict_do_nothing())

    def follow(self, account_id: str, topic_id: str) -> None:
        statement = insert(board_follows).values(account_id=account_id, topic_id=topic_id).on_conflict_do_nothing()
        try:
            with self._db.begin() as connection:
                connection.execute(statement)
        except IntegrityError:
            pass  # the topic or the account went a moment ago: nothing to follow

    def unfollow(self, account_id: str, topic_id: str) -> None:
        with self._db.begin() as connection:
            connection.execute(
                delete(board_follows).where(
                    board_follows.c.account_id == account_id, board_follows.c.topic_id == topic_id
                )
            )

    def followers(self, topic_id: str) -> list[tuple[str, str | None]]:
        with self._db.connect() as connection:
            rows = connection.execute(
                select(board_follows.c.account_id, board_follows.c.notified_at)
                .where(board_follows.c.topic_id == topic_id)
                .order_by(board_follows.c.account_id)
            )
            return [(row.account_id, row.notified_at) for row in rows]

    def following(self, account_id: str, topic_id: str) -> bool:
        with self._db.connect() as connection:
            return (
                connection.execute(
                    select(board_follows.c.topic_id).where(
                        board_follows.c.account_id == account_id, board_follows.c.topic_id == topic_id
                    )
                ).first()
                is not None
            )

    def set_notified(self, account_id: str, topic_id: str, at: str) -> None:
        with self._db.begin() as connection:
            connection.execute(
                update(board_follows)
                .where(board_follows.c.account_id == account_id, board_follows.c.topic_id == topic_id)
                .values(notified_at=at)
            )
