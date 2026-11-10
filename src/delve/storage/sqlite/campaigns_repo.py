"""Campaigns, each pinned to a revision of its module, each with the token of its join link, its status, its voice
setting, its initiative mode, its listing and its schedule."""

from __future__ import annotations

import secrets
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Connection, delete, func, select, text, update

from delve.domain import new_id
from delve.domain.campaigns import (
    DESCRIPTION_LENGTH,
    INITIATIVE_MODES,
    MOST_SLOTS,
    OBSERVER_RULES,
    VISIBILITIES,
    VOICE_SETTINGS,
    Campaign,
    CampaignStatus,
    InitiativeMode,
    ObserverRule,
    Visibility,
    VoiceSetting,
)
from delve.storage.interfaces import CampaignActivity
from delve.storage.sqlite.db import Database
from delve.storage.sqlite.tables import beats, campaigns, module_revisions, sessions


def _from(row) -> Campaign:
    return Campaign(
        id=row.id,
        name=row.name,
        module_id=row.module_id,
        revision=row.revision,
        created_at=row.created_at,
        ruleset=row.ruleset,
        setting=row.setting or "",
        join_token=row.join_token or "",
        status=row.status,
        voice=row.voice,
        initiative=row.initiative,
        observers=row.observers,
        visibility=row.visibility,
        description=row.description,
        slots=row.slots,
        schedule=row.schedule,
    )


def _require_revision(connection: Connection, module_id: str, revision: int) -> None:
    found = connection.execute(
        select(module_revisions.c.number).where(
            module_revisions.c.module_id == module_id, module_revisions.c.number == revision
        )
    ).first()
    if found is None:
        raise KeyError(f"{module_id} revision {revision}")


class SqliteCampaignRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def create(
        self,
        name: str,
        module_id: str,
        revision: int,
        *,
        ruleset: str,
        setting: str,
    ) -> Campaign:
        row = {
            "id": new_id("cmp"),
            "name": name,
            "module_id": module_id,
            "revision": revision,
            "created_at": datetime.now(UTC).isoformat(),
            "ruleset": ruleset,
            "setting": setting,
            "join_token": secrets.token_urlsafe(24),
            "status": "in_progress",
            "voice": "allowed",
            "initiative": "combatant",
            "visibility": "private",
            "description": "",
            "slots": None,
            "schedule": None,
        }
        with self._db.begin() as connection:
            _require_revision(connection, module_id, revision)
            connection.execute(campaigns.insert().values(row))
        return Campaign(**row)

    def get(self, id: str) -> Campaign | None:
        with self._db.connect() as connection:
            row = connection.execute(select(campaigns).where(campaigns.c.id == id)).first()
        return None if row is None else _from(row)

    def list(self) -> list[Campaign]:
        with self._db.connect() as connection:
            return [_from(row) for row in connection.execute(select(campaigns).order_by(text("rowid")))]

    def set_revision(self, id: str, revision: int) -> Campaign:
        with self._db.begin() as connection:
            row = connection.execute(select(campaigns).where(campaigns.c.id == id)).first()
            if row is None:
                raise KeyError(id)
            _require_revision(connection, row.module_id, revision)
            connection.execute(update(campaigns).where(campaigns.c.id == id).values(revision=revision))
        return replace(_from(row), revision=revision)

    def set_status(self, id: str, status: CampaignStatus) -> Campaign:
        return self._set(id, status=status)

    def set_voice(self, id: str, voice: VoiceSetting) -> Campaign:
        if voice not in VOICE_SETTINGS:
            raise ValueError(f"Voice is one of {', '.join(VOICE_SETTINGS)}, not {voice!r}.")
        return self._set(id, voice=voice)

    def set_initiative(self, id: str, mode: InitiativeMode) -> Campaign:
        if mode not in INITIATIVE_MODES:
            raise ValueError(f"The initiative mode is one of {', '.join(INITIATIVE_MODES)}, not {mode!r}.")
        return self._set(id, initiative=mode)

    def set_observers(self, id: str, rule: ObserverRule) -> Campaign:
        if rule not in OBSERVER_RULES:
            raise ValueError(f"Who may watch is one of {', '.join(OBSERVER_RULES)}, not {rule!r}.")
        return self._set(id, observers=rule)

    def set_listing(self, id: str, visibility: Visibility, description: str, slots: int | None) -> Campaign:
        if visibility not in VISIBILITIES:
            raise ValueError(f"The visibility is one of {', '.join(VISIBILITIES)}, not {visibility!r}.")
        if len(description) > DESCRIPTION_LENGTH:
            raise ValueError(f"A description has at most {DESCRIPTION_LENGTH} characters.")
        if slots is not None and not 1 <= slots <= MOST_SLOTS:
            raise ValueError(f"A table has 1 to {MOST_SLOTS} places for players, or no limit.")
        return self._set(id, visibility=visibility, description=description, slots=slots)

    def set_schedule(self, id: str, schedule: dict[str, Any] | None) -> Campaign:
        return self._set(id, schedule=schedule)

    def _set(self, id: str, **values: Any) -> Campaign:
        with self._db.begin() as connection:
            row = connection.execute(select(campaigns).where(campaigns.c.id == id)).first()
            if row is None:
                raise KeyError(id)
            connection.execute(update(campaigns).where(campaigns.c.id == id).values(**values))
        return replace(_from(row), **values)

    def activity(self, campaign_id: str) -> CampaignActivity:
        found = self._activities(campaigns.c.id == campaign_id)
        if campaign_id not in found:
            raise KeyError(campaign_id)
        return found[campaign_id]

    def activities(self) -> dict[str, CampaignActivity]:
        return self._activities()

    def _activities(self, *where: Any) -> dict[str, CampaignActivity]:
        """Each campaign's activity, in one read of its sessions, each with its last beat (DEL-172)."""
        last_beat = (
            select(func.max(beats.c.closed_at))
            .where(beats.c.campaign_id == campaigns.c.id, beats.c.closed_at >= sessions.c.started_at)
            .scalar_subquery()
        )
        last_closed = select(func.max(beats.c.closed_at)).where(beats.c.campaign_id == campaigns.c.id).scalar_subquery()
        query = (
            select(campaigns.c.id, sessions.c.started_at, sessions.c.ended_at, last_beat, last_closed)
            .select_from(campaigns.outerjoin(sessions, sessions.c.campaign_id == campaigns.c.id))
            .where(*where)
        )
        with self._db.connect() as connection:
            rows = connection.execute(query).all()
        by_campaign: dict[str, list[Any]] = {}
        for row in rows:
            by_campaign.setdefault(row.id, []).append(row)
        return {id: _activity(found) for id, found in by_campaign.items()}

    def by_join_token(self, token: str) -> Campaign | None:
        if not token:
            return None
        with self._db.connect() as connection:
            row = connection.execute(select(campaigns).where(campaigns.c.join_token == token)).first()
        return None if row is None else _from(row)

    def new_join_token(self, id: str) -> Campaign:
        token = secrets.token_urlsafe(24)
        with self._db.begin() as connection:
            row = connection.execute(select(campaigns).where(campaigns.c.id == id)).first()
            if row is None:
                raise KeyError(id)
            connection.execute(update(campaigns).where(campaigns.c.id == id).values(join_token=token))
        return replace(_from(row), join_token=token)

    def delete(self, id: str) -> None:
        with self._db.begin() as connection:
            connection.execute(delete(campaigns).where(campaigns.c.id == id))


def _activity(rows: list[Any]) -> CampaignActivity:
    """A campaign's activity from its rows of `_activities`: one per session (one with no session when it has none)."""
    played = [r for r in rows if r.started_at is not None]
    seconds = 0.0
    for row in played:
        end = row.ended_at or row[3]
        if end is not None:
            seconds += max(0.0, (datetime.fromisoformat(end) - datetime.fromisoformat(row.started_at)).total_seconds())
    moments = [rows[0][4], *(r.started_at for r in played), *(r.ended_at for r in played)]
    last = max((m for m in moments if m is not None), default=None)
    return CampaignActivity(last_played=last, sessions=len(played), playtime_s=int(seconds))
