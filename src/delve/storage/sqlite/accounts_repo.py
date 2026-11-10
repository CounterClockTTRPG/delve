"""Accounts with their profiles, and the one-time links that set or reset a password (players and tavern Task B1).

A password's hash is read and written only by `password_hash` and `set_password_hash`; an `Account` says only
whether it has one."""

from __future__ import annotations

from dataclasses import asdict, fields
from datetime import UTC, datetime

from sqlalchemy import delete, exists, func, select, text, update
from sqlalchemy.exc import IntegrityError

from delve.domain import new_id
from delve.domain.accounts import Account, AccountLink, Identity, Profile
from delve.storage.sqlite.db import Database
from delve.storage.sqlite.tables import account_identities, account_links, accounts

PROFILE_FIELDS = tuple(field.name for field in fields(Profile))
COLUMNS = (
    accounts.c.id,
    accounts.c.username,
    accounts.c.organiser,
    accounts.c.owner,
    accounts.c.created_at,
    accounts.c.disabled_at,
    accounts.c.external_id,
    accounts.c.pending,
    accounts.c.request_note,
    accounts.c.reset_asked_at,
    accounts.c.email,
    accounts.c.email_pending,
    accounts.c.mail_host,
    accounts.c.mail_board,
    (accounts.c.password_hash.is_not(None)).label("has_password"),
    *(accounts.c[name] for name in PROFILE_FIELDS),
)


def _from(row) -> Account:
    values = row._mapping
    return Account(
        id=values["id"],
        username=values["username"],
        profile=Profile(**{name: values[name] for name in PROFILE_FIELDS}),
        organiser=bool(values["organiser"]),
        owner=bool(values["owner"]),
        created_at=values["created_at"],
        disabled_at=values["disabled_at"],
        external_id=values["external_id"],
        has_password=bool(values["has_password"]),
        pending=bool(values["pending"]),
        request_note=values["request_note"],
        reset_asked_at=values["reset_asked_at"],
        email=values["email"],
        email_pending=values["email_pending"],
        mail_host=bool(values["mail_host"]),
        mail_board=bool(values["mail_board"]),
    )


class SqliteAccountRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def create(
        self,
        username: str,
        profile: Profile,
        *,
        organiser: bool = False,
        owner: bool = False,
        pending: bool = False,
        request_note: str = "",
    ) -> Account:
        account = Account(
            new_id("acc"),
            username,
            profile,
            organiser,
            owner,
            datetime.now(UTC).isoformat(),
            pending=pending,
            request_note=request_note,
        )
        try:
            with self._db.begin() as connection:
                connection.execute(
                    accounts.insert().values(
                        id=account.id,
                        username=username,
                        organiser=organiser,
                        owner=owner,
                        created_at=account.created_at,
                        pending=pending,
                        request_note=request_note,
                        **asdict(profile),
                    )
                )
        except IntegrityError:
            raise ValueError("the username is in use") from None
        return account

    def get(self, id: str) -> Account | None:
        return self._one(accounts.c.id == id)

    def by_username(self, username: str) -> Account | None:
        return self._one(accounts.c.username == username)

    def by_external_id(self, external_id: str) -> Account | None:
        return self._one(accounts.c.external_id == external_id)

    def _one(self, *where) -> Account | None:
        with self._db.connect() as connection:
            row = connection.execute(select(*COLUMNS).where(*where)).first()
        return None if row is None else _from(row)

    def list(self) -> list[Account]:
        with self._db.connect() as connection:
            return [_from(row) for row in connection.execute(select(*COLUMNS).order_by(text("rowid")))]

    def has_owner(self) -> bool:
        with self._db.connect() as connection:
            return bool(connection.execute(select(exists().where(accounts.c.owner.is_(True)))).scalar())

    def password_hash(self, id: str) -> str | None:
        with self._db.connect() as connection:
            return connection.execute(select(accounts.c.password_hash).where(accounts.c.id == id)).scalar()

    def set_password_hash(self, id: str, password_hash: str) -> None:
        self._update(id, password_hash=password_hash)

    def save_profile(self, id: str, profile: Profile) -> Account:
        return self._update(id, **asdict(profile))

    def set_organiser(self, id: str, organiser: bool) -> Account:
        return self._update(id, organiser=organiser)

    def set_owner(self, id: str, owner: bool) -> Account:
        return self._update(id, owner=owner)

    def set_disabled(self, id: str, disabled_at: str | None) -> Account:
        return self._update(id, disabled_at=disabled_at)

    def set_reset_asked(self, id: str, asked_at: str | None) -> Account:
        return self._update(id, reset_asked_at=asked_at)

    def set_email(self, id: str, *, email: str | None, email_pending: str | None) -> None:
        self._update(id, email=email, email_pending=email_pending)

    def set_mail_switches(self, id: str, *, mail_host: bool, mail_board: bool) -> None:
        self._update(id, mail_host=mail_host, mail_board=mail_board)

    def with_email(self, address: str) -> list[Account]:
        where = (
            func.lower(accounts.c.email) == address.lower(),
            accounts.c.disabled_at.is_(None),
            accounts.c.pending.is_(False),
        )
        with self._db.connect() as connection:
            return [_from(row) for row in connection.execute(select(*COLUMNS).where(*where).order_by(text("rowid")))]

    def approve(self, id: str) -> Account:
        return self._update(id, pending=False)

    def delete_pending(self, id: str) -> bool:
        query = delete(accounts).where(accounts.c.id == id, accounts.c.pending.is_(True))
        with self._db.begin() as connection:
            return connection.execute(query).rowcount == 1

    def _update(self, id: str, **values) -> Account:
        with self._db.begin() as connection:
            if connection.execute(update(accounts).where(accounts.c.id == id).values(values)).rowcount == 0:
                raise KeyError(id)
            return _from(connection.execute(select(*COLUMNS).where(accounts.c.id == id)).one())


class SqliteAccountLinkRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def put(self, token_hash: str, link: AccountLink) -> None:
        with self._db.begin() as connection:
            connection.execute(account_links.insert().values(token_hash=token_hash, **asdict(link)))

    def get(self, token_hash: str) -> AccountLink | None:
        query = select(
            account_links.c.account_id,
            account_links.c.kind,
            account_links.c.created_at,
            account_links.c.expires_at,
            account_links.c.used_at,
            account_links.c.by_owner,
        ).where(account_links.c.token_hash == token_hash)
        with self._db.connect() as connection:
            row = connection.execute(query).first()
        return None if row is None else AccountLink(**row._mapping)

    def use(self, token_hash: str, used_at: str) -> bool:
        query = (
            update(account_links)
            .where(account_links.c.token_hash == token_hash, account_links.c.used_at.is_(None))
            .values(used_at=used_at)
        )
        with self._db.begin() as connection:
            return connection.execute(query).rowcount == 1

    def drop_unused(self, account_id: str) -> None:
        query = delete(account_links).where(account_links.c.account_id == account_id, account_links.c.used_at.is_(None))
        with self._db.begin() as connection:
            connection.execute(query)


class SqliteIdentityRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def get(self, provider: str, subject: str) -> Identity | None:
        query = select(account_identities).where(
            account_identities.c.provider == provider, account_identities.c.subject == subject
        )
        with self._db.connect() as connection:
            row = connection.execute(query).first()
        return None if row is None else Identity(**row._mapping)

    def list(self, account_id: str) -> list[Identity]:
        query = (
            select(account_identities)
            .where(account_identities.c.account_id == account_id)
            .order_by(account_identities.c.provider)
        )
        with self._db.connect() as connection:
            return [Identity(**row._mapping) for row in connection.execute(query)]

    def add(self, identity: Identity) -> Identity:
        try:
            with self._db.begin() as connection:
                connection.execute(account_identities.insert().values(**asdict(identity)))
        except IntegrityError:
            raise ValueError("the identity is linked already, or the account is unknown") from None
        return identity

    def remove(self, account_id: str, provider: str) -> bool:
        query = delete(account_identities).where(
            account_identities.c.account_id == account_id, account_identities.c.provider == provider
        )
        with self._db.begin() as connection:
            return connection.execute(query).rowcount == 1
