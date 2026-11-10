"""House rules, bundles with their ordered rules, and each campaign's choice of bundles and rules (spec §9)."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime

from sqlalchemy import Connection, Table, delete, select, text, update

from delve.domain import new_id
from delve.domain.house_rules import PHASES, Bundle, HouseRule, Kind, Phase
from delve.storage.sqlite.db import Database
from delve.storage.sqlite.tables import (
    campaigns,
    house_rules,
    house_rules_bundle_rules,
    house_rules_bundles,
    house_rules_campaign_bundles,
    house_rules_campaign_rules,
)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _rule_from(row) -> HouseRule:
    return HouseRule(
        id=row.id,
        title=row.title,
        body_md=row.body_md,
        kind=row.kind,
        phases=frozenset(row.phases),
        ruleset=row.ruleset,
        setting=row.setting,
        subject=row.subject,
        enabled=bool(row.enabled),
    )


def _rule_row(rule: HouseRule) -> dict:
    return {
        "title": rule.title,
        "body_md": rule.body_md,
        "kind": rule.kind,
        "phases": [p for p in PHASES if p in rule.phases],
        "ruleset": rule.ruleset,
        "setting": rule.setting,
        "subject": rule.subject,
        "enabled": rule.enabled,
    }


def _missing(connection: Connection, table: Table, ids: Iterable[str]) -> str | None:
    """The first of `ids` that `table` doesn't have."""
    wanted = list(dict.fromkeys(ids))
    found = set(connection.execute(select(table.c.id).where(table.c.id.in_(wanted))).scalars())
    return next((id for id in wanted if id not in found), None)


def _require(connection: Connection, table: Table, ids: Iterable[str]) -> None:
    missing = _missing(connection, table, ids)
    if missing is not None:
        raise KeyError(missing)


class SqliteHouseRuleRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def create(
        self,
        *,
        title: str,
        body_md: str = "",
        kind: Kind = "general",
        phases: Iterable[Phase] = (),
        ruleset: str | None = None,
        setting: str | None = None,
        subject: str | None = None,
        enabled: bool = True,
    ) -> HouseRule:
        rule = HouseRule(new_id("hr"), title, body_md, kind, frozenset(phases), ruleset, setting, subject, enabled)
        now = _now()
        with self._db.begin() as connection:
            connection.execute(
                house_rules.insert().values(id=rule.id, **_rule_row(rule), created_at=now, updated_at=now)
            )
        return rule

    def get(self, id: str) -> HouseRule | None:
        with self._db.connect() as connection:
            row = connection.execute(select(house_rules).where(house_rules.c.id == id)).first()
        return None if row is None else _rule_from(row)

    def list(self) -> list[HouseRule]:
        with self._db.connect() as connection:
            return [_rule_from(r) for r in connection.execute(select(house_rules).order_by(text("rowid")))]

    def save(self, rule: HouseRule) -> HouseRule:
        with self._db.begin() as connection:
            changed = connection.execute(
                update(house_rules).where(house_rules.c.id == rule.id).values(**_rule_row(rule), updated_at=_now())
            )
            if changed.rowcount == 0:
                raise KeyError(rule.id)
        return rule

    def delete(self, id: str) -> None:
        with self._db.begin() as connection:
            connection.execute(delete(house_rules).where(house_rules.c.id == id))


def _rule_ids(connection: Connection, bundle_id: str) -> tuple[str, ...]:
    query = (
        select(house_rules_bundle_rules.c.rule_id)
        .where(house_rules_bundle_rules.c.bundle_id == bundle_id)
        .order_by(house_rules_bundle_rules.c.position)
    )
    return tuple(connection.execute(query).scalars())


def _put_rule_ids(connection: Connection, bundle_id: str, rule_ids: tuple[str, ...]) -> None:
    connection.execute(delete(house_rules_bundle_rules).where(house_rules_bundle_rules.c.bundle_id == bundle_id))
    rows = [{"bundle_id": bundle_id, "rule_id": id, "position": i} for i, id in enumerate(rule_ids)]
    if rows:
        connection.execute(house_rules_bundle_rules.insert(), rows)


class SqliteBundleRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def create(self, *, title: str, description_md: str = "", rule_ids: Iterable[str] = ()) -> Bundle:
        bundle = Bundle(new_id("hb"), title, description_md, tuple(dict.fromkeys(rule_ids)))
        now = _now()
        with self._db.begin() as connection:
            _require(connection, house_rules, bundle.rule_ids)
            connection.execute(
                house_rules_bundles.insert().values(
                    id=bundle.id, title=title, description_md=description_md, created_at=now, updated_at=now
                )
            )
            _put_rule_ids(connection, bundle.id, bundle.rule_ids)
        return bundle

    def get(self, id: str) -> Bundle | None:
        with self._db.connect() as connection:
            row = connection.execute(select(house_rules_bundles).where(house_rules_bundles.c.id == id)).first()
            if row is None:
                return None
            return Bundle(row.id, row.title, row.description_md, _rule_ids(connection, row.id))

    def list(self) -> list[Bundle]:
        with self._db.connect() as connection:
            rows = connection.execute(select(house_rules_bundles).order_by(text("rowid"))).all()
            return [Bundle(r.id, r.title, r.description_md, _rule_ids(connection, r.id)) for r in rows]

    def save(self, bundle: Bundle) -> Bundle:
        saved = Bundle(bundle.id, bundle.title, bundle.description_md, tuple(dict.fromkeys(bundle.rule_ids)))
        with self._db.begin() as connection:
            _require(connection, house_rules, saved.rule_ids)  # before any write, so a refusal changes nothing
            changed = connection.execute(
                update(house_rules_bundles)
                .where(house_rules_bundles.c.id == bundle.id)
                .values(title=bundle.title, description_md=bundle.description_md, updated_at=_now())
            )
            if changed.rowcount == 0:
                raise KeyError(bundle.id)
            _put_rule_ids(connection, bundle.id, saved.rule_ids)
        return saved

    def delete(self, id: str) -> None:
        with self._db.begin() as connection:
            connection.execute(delete(house_rules_bundles).where(house_rules_bundles.c.id == id))


class SqliteCampaignHouseRulesRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def get(self, campaign_id: str) -> tuple[list[str], list[str]] | None:
        with self._db.connect() as connection:
            if connection.execute(select(campaigns.c.id).where(campaigns.c.id == campaign_id)).first() is None:
                return None
            bundles = connection.execute(
                select(house_rules_campaign_bundles.c.bundle_id)
                .where(house_rules_campaign_bundles.c.campaign_id == campaign_id)
                .order_by(house_rules_campaign_bundles.c.position)
            ).scalars()
            rules = connection.execute(
                select(house_rules_campaign_rules.c.rule_id)
                .where(house_rules_campaign_rules.c.campaign_id == campaign_id)
                .order_by(house_rules_campaign_rules.c.position)
            ).scalars()
            return list(bundles), list(rules)

    def put(self, campaign_id: str, bundle_ids: Iterable[str], rule_ids: Iterable[str]) -> None:
        bundle_ids, rule_ids = list(dict.fromkeys(bundle_ids)), list(dict.fromkeys(rule_ids))
        with self._db.begin() as connection:
            _require(connection, campaigns, [campaign_id])
            _require(connection, house_rules_bundles, bundle_ids)
            _require(connection, house_rules, rule_ids)
            for table in (house_rules_campaign_bundles, house_rules_campaign_rules):
                connection.execute(delete(table).where(table.c.campaign_id == campaign_id))
            if bundle_ids:
                connection.execute(
                    house_rules_campaign_bundles.insert(),
                    [{"campaign_id": campaign_id, "bundle_id": id, "position": i} for i, id in enumerate(bundle_ids)],
                )
            if rule_ids:
                connection.execute(
                    house_rules_campaign_rules.insert(),
                    [{"campaign_id": campaign_id, "rule_id": id, "position": i} for i, id in enumerate(rule_ids)],
                )
