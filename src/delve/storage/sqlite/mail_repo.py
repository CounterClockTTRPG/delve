"""The outbox and the confirmations of addresses (DEL-314). The outbox keeps no recipient address."""

from __future__ import annotations

from dataclasses import asdict

from sqlalchemy import delete, func, select, update

from delve.domain.mail import Confirmation, Outgoing
from delve.storage.sqlite.db import Database
from delve.storage.sqlite.tables import email_confirmations, mail_outbox

DROPPED = "dropped"


def _outgoing(row) -> Outgoing:
    return Outgoing(**dict(row._mapping))


class SqliteMailRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def add(self, outgoing: Outgoing) -> None:
        with self._db.begin() as connection:
            connection.execute(mail_outbox.insert().values(**asdict(outgoing)))

    def due(self, now_iso: str, limit: int) -> list[Outgoing]:
        query = (
            select(mail_outbox)
            .where(mail_outbox.c.sent_at.is_(None), mail_outbox.c.failed_at.is_(None), mail_outbox.c.next_at <= now_iso)
            .order_by(mail_outbox.c.next_at, mail_outbox.c.created_at, mail_outbox.c.id)
            .limit(limit)
        )
        with self._db.connect() as connection:
            return [_outgoing(row) for row in connection.execute(query)]

    def _set(self, id: str, **values) -> None:
        with self._db.begin() as connection:
            connection.execute(update(mail_outbox).where(mail_outbox.c.id == id).values(values))

    def sent(self, id: str, at: str) -> None:
        self._set(id, sent_at=at, reply_to=None)

    def retry(self, id: str, attempts: int, next_at: str) -> None:
        self._set(id, attempts=attempts, next_at=next_at)

    def failed(self, id: str, at: str, failure: str) -> None:
        self._set(id, failed_at=at, failure=failure, reply_to=None)

    def dropped(self, id: str, at: str) -> None:
        self.failed(id, at, DROPPED)

    def recent_failures(self, limit: int, *, dropped: bool = True) -> list[Outgoing]:
        query = select(mail_outbox).where(mail_outbox.c.failed_at.is_not(None))
        if not dropped:
            query = query.where(mail_outbox.c.failure != DROPPED)
        query = query.order_by(mail_outbox.c.failed_at.desc(), mail_outbox.c.id).limit(limit)
        with self._db.connect() as connection:
            return [_outgoing(row) for row in connection.execute(query)]

    def waiting(self) -> int:
        query = (
            select(func.count())
            .select_from(mail_outbox)
            .where(mail_outbox.c.sent_at.is_(None), mail_outbox.c.failed_at.is_(None))
        )
        with self._db.connect() as connection:
            return connection.execute(query).scalar_one()

    def sent_since(self, at: str) -> int:
        query = select(func.count()).select_from(mail_outbox).where(mail_outbox.c.sent_at >= at)
        with self._db.connect() as connection:
            return connection.execute(query).scalar_one()

    def prune_sent(self, before: str) -> None:
        with self._db.begin() as connection:
            connection.execute(delete(mail_outbox).where(mail_outbox.c.sent_at < before))

    def put_confirmation(self, confirmation: Confirmation) -> None:
        with self._db.begin() as connection:
            connection.execute(
                delete(email_confirmations).where(
                    email_confirmations.c.account_id == confirmation.account_id,
                    email_confirmations.c.used_at.is_(None),
                )
            )
            connection.execute(email_confirmations.insert().values(**asdict(confirmation)))

    def confirmation(self, token_hash: str) -> Confirmation | None:
        with self._db.connect() as connection:
            row = connection.execute(
                select(email_confirmations).where(email_confirmations.c.token_hash == token_hash)
            ).first()
        return None if row is None else Confirmation(**dict(row._mapping))

    def use_confirmation(self, token_hash: str, at: str) -> bool:
        with self._db.begin() as connection:
            changed = connection.execute(
                update(email_confirmations)
                .where(email_confirmations.c.token_hash == token_hash, email_confirmations.c.used_at.is_(None))
                .values(used_at=at)
            )
            return changed.rowcount == 1
