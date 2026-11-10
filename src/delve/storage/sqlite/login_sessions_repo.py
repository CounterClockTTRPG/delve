"""Login sessions (players and tavern Task C1): the browsers logged in to each account, by their token's hash."""

from __future__ import annotations

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError

from delve.domain import new_id
from delve.domain.accounts import LoginSession
from delve.storage.sqlite.db import Database
from delve.storage.sqlite.tables import login_sessions

COLUMNS = (
    login_sessions.c.id,
    login_sessions.c.account_id,
    login_sessions.c.created_at,
    login_sessions.c.last_used_at,
    login_sessions.c.device,
    login_sessions.c.address,
)


class SqliteLoginSessionRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def create(self, account_id: str, token_hash: str, device: str, address: str, now: str) -> LoginSession:
        login = LoginSession(new_id("lgn"), account_id, now, now, device, address)
        try:
            with self._db.begin() as connection:
                connection.execute(
                    login_sessions.insert().values(
                        id=login.id,
                        account_id=account_id,
                        token_hash=token_hash,
                        created_at=now,
                        last_used_at=now,
                        device=device,
                        address=address,
                    )
                )
        except IntegrityError:
            raise ValueError("the token is in use, or there is no such account") from None
        return login

    def by_token_hash(self, token_hash: str) -> LoginSession | None:
        with self._db.connect() as connection:
            row = connection.execute(select(*COLUMNS).where(login_sessions.c.token_hash == token_hash)).first()
        return None if row is None else LoginSession(**row._mapping)

    def touch(self, id: str, now: str) -> None:
        with self._db.begin() as connection:
            connection.execute(update(login_sessions).where(login_sessions.c.id == id).values(last_used_at=now))

    def list(self, account_id: str) -> list[LoginSession]:
        query = (
            select(*COLUMNS)
            .where(login_sessions.c.account_id == account_id)
            .order_by(login_sessions.c.last_used_at.desc(), login_sessions.c.created_at.desc())
        )
        with self._db.connect() as connection:
            return [LoginSession(**row._mapping) for row in connection.execute(query)]

    def end(self, id: str) -> None:
        with self._db.begin() as connection:
            connection.execute(delete(login_sessions).where(login_sessions.c.id == id))

    def end_all(self, account_id: str, *, but: str | None = None) -> None:
        query = delete(login_sessions).where(login_sessions.c.account_id == account_id)
        if but is not None:
            query = query.where(login_sessions.c.id != but)
        with self._db.begin() as connection:
            connection.execute(query)
