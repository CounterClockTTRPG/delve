"""Requests to join a public table (DEL-204), with their thread of messages."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict
from typing import Any

from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError

from delve.domain import new_id
from delve.domain.campaigns import JoinRequest, SeatAsk
from delve.storage.sqlite.db import Database
from delve.storage.sqlite.tables import accounts, campaigns, join_requests


def _from(row) -> JoinRequest:
    return JoinRequest(**{**row._mapping, "messages": tuple(dict(m) for m in row.messages)})


class SqliteJoinRequestRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def create(
        self,
        campaign_id: str,
        account_id: str,
        messages: Sequence[dict[str, Any]],
        created_at: str,
        role: SeatAsk = "player",
    ) -> JoinRequest:
        request = JoinRequest(
            new_id("jrq"), campaign_id, account_id, "pending", tuple(dict(m) for m in messages), created_at, role=role
        )
        try:
            with self._db.begin() as connection:
                for table, id in ((campaigns, campaign_id), (accounts, account_id)):
                    if connection.execute(select(table.c.id).where(table.c.id == id)).first() is None:
                        raise KeyError(id)
                connection.execute(join_requests.insert().values({**asdict(request), "messages": list(messages)}))
        except IntegrityError:
            raise ValueError("the account has a pending request at the campaign") from None
        return request

    def get(self, id: str) -> JoinRequest | None:
        with self._db.connect() as connection:
            row = connection.execute(select(join_requests).where(join_requests.c.id == id)).first()
        return None if row is None else _from(row)

    def of_account(self, account_id: str) -> list[JoinRequest]:
        query = (
            select(join_requests)
            .where(join_requests.c.account_id == account_id)
            .order_by(join_requests.c.created_at.desc(), text("rowid DESC"))
        )
        with self._db.connect() as connection:
            return [_from(row) for row in connection.execute(query)]

    def of_campaign(self, campaign_id: str) -> list[JoinRequest]:
        query = (
            select(join_requests)
            .where(join_requests.c.campaign_id == campaign_id)
            .order_by(join_requests.c.created_at, text("rowid"))
        )
        with self._db.connect() as connection:
            return [_from(row) for row in connection.execute(query)]

    def save(self, request: JoinRequest) -> JoinRequest:
        values = {
            "status": request.status,
            "messages": [dict(m) for m in request.messages],
            "decided_at": request.decided_at,
            "seat_id": request.seat_id,
        }
        try:
            with self._db.begin() as connection:
                changed = connection.execute(
                    update(join_requests).where(join_requests.c.id == request.id).values(values)
                )
                if changed.rowcount == 0:
                    raise KeyError(request.id)
        except IntegrityError:
            raise ValueError("the account has a pending request at the campaign, or the seat is unknown") from None
        return request
