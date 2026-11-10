"""Characters, PCs and NPCs, in a campaign: their sheet and state as JSON, the PCs' marching order, and a PC's
departure from the party, which only `set_departure` changes.

`save` stores the whole row as the caller read it, so of two saves from two reads the last wins. What changes often
from its own read saves its part alone: `save_state` the hit points, conditions, effects, inventory and spells (a
fight's write-through, a heal, a purchase), `save_sheet` the name and the sheet (a portrait landing, a disposition),
so a portrait painted while the party fought doesn't put its hit points back, nor a hit take the portrait away."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace

from sqlalchemy import Connection, delete, func, select, text, update

from delve.domain import new_id
from delve.domain.campaigns import DEPARTURES, Character, Departure
from delve.domain.characters import CharacterState, Kind, Sheet
from delve.storage.sqlite.db import Database
from delve.storage.sqlite.tables import campaigns, characters


def _from(row) -> Character:
    sheet = Sheet.from_dict({**row.sheet, "label": row.name, "kind": row.kind})
    return Character(
        id=row.id,
        campaign_id=row.campaign_id,
        name=row.name,
        kind=row.kind,
        sheet=sheet,
        state=CharacterState.from_dict(row.state),
        order=row.order,
        created_at=row.created_at,
        controller_id=row.controller_id,
        departure=row.departure,
        departed_at=row.departed_at,
    )


def _sheet_json(sheet: Sheet) -> dict:
    raw = sheet.to_dict()
    del raw["label"], raw["kind"]
    return raw


def _next_order(connection: Connection, campaign_id: str) -> int:
    last = connection.execute(
        select(func.max(characters.c.order)).where(characters.c.campaign_id == campaign_id)
    ).scalar()
    return 0 if last is None else last + 1


class SqliteCharacterRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def create(
        self,
        campaign_id: str,
        name: str,
        *,
        kind: Kind = "pc",
        sheet: Sheet | None = None,
        state: CharacterState | None = None,
        order: int | None = None,
    ) -> Character:
        with self._db.begin() as connection:
            if connection.execute(select(campaigns.c.id).where(campaigns.c.id == campaign_id)).first() is None:
                raise KeyError(campaign_id)
            if kind == "pc" and order is None:
                order = _next_order(connection, campaign_id)
            character = Character(
                id=new_id("chr"),
                campaign_id=campaign_id,
                name=name,
                kind=kind,
                sheet=replace(sheet or Sheet(), label=name, kind=kind),
                state=state or CharacterState(),
                order=order if kind == "pc" else None,
                created_at=datetime.now(UTC).isoformat(),
            )
            connection.execute(characters.insert().values(self._row(character)))
        return character

    @staticmethod
    def _row(character: Character) -> dict:
        return {
            "id": character.id,
            "campaign_id": character.campaign_id,
            "name": character.name,
            "kind": character.kind,
            "sheet": _sheet_json(character.sheet),
            "state": character.state.to_dict(),
            "order": character.order,
            "created_at": character.created_at,
        }

    def get(self, id: str) -> Character | None:
        with self._db.connect() as connection:
            row = connection.execute(select(characters).where(characters.c.id == id)).first()
        return None if row is None else _from(row)

    def list(self, campaign_id: str) -> list[Character]:
        query = select(characters).where(characters.c.campaign_id == campaign_id).order_by(text("rowid"))
        with self._db.connect() as connection:
            return [_from(row) for row in connection.execute(query)]

    def rename(self, id: str, name: str) -> Character:
        with self._db.begin() as connection:
            row = connection.execute(select(characters).where(characters.c.id == id)).first()
            if row is None:
                raise KeyError(id)
            connection.execute(update(characters).where(characters.c.id == id).values(name=name))
        return replace(_from(row), name=name, sheet=replace(_from(row).sheet, label=name))

    def save(self, character: Character) -> Character:
        saved = replace(
            character,
            sheet=replace(character.sheet, label=character.name, kind=character.kind),
            order=character.order if character.kind == "pc" else None,
        )
        row = self._row(saved)
        del row["id"], row["campaign_id"], row["created_at"]
        with self._db.begin() as connection:
            found = connection.execute(
                select(
                    characters.c.campaign_id,
                    characters.c.controller_id,
                    characters.c.departure,
                    characters.c.departed_at,
                ).where(characters.c.id == character.id)
            ).first()
            if found is None or found.campaign_id != character.campaign_id:
                raise KeyError(character.id)
            connection.execute(update(characters).where(characters.c.id == character.id).values(row))
        # The seat that plays it changes only through the seats (`SeatRepository.set_controller`), and its departure
        # only through `set_departure`, so a character saved from an older read never comes back to the party.
        return replace(
            saved, controller_id=found.controller_id, departure=found.departure, departed_at=found.departed_at
        )

    def save_state(self, character: Character) -> Character:
        return self._save_part(character, {"state": character.state.to_dict()})

    def save_sheet(self, character: Character) -> Character:
        sheet = replace(character.sheet, label=character.name, kind=character.kind)
        return self._save_part(character, {"name": character.name, "sheet": _sheet_json(sheet)})

    def _save_part(self, character: Character, values: dict) -> Character:
        """Store `values` alone, the columns of one part; the character answered is the stored one with them."""
        with self._db.begin() as connection:
            row = connection.execute(select(characters).where(characters.c.id == character.id)).first()
            if row is None or row.campaign_id != character.campaign_id:
                raise KeyError(character.id)
            connection.execute(update(characters).where(characters.c.id == character.id).values(values))
        return _from(SimpleNamespace(**{**row._asdict(), **values}))

    def set_departure(self, id: str, departure: Departure | None, at: str | None = None) -> Character:
        if departure is not None and departure not in DEPARTURES:
            raise ValueError(f"A character leaves the party as one of {', '.join(DEPARTURES)}, not {departure!r}.")
        departed_at = None if departure is None else at or datetime.now(UTC).isoformat()
        with self._db.begin() as connection:
            row = connection.execute(select(characters).where(characters.c.id == id)).first()
            if row is None:
                raise KeyError(id)
            values = {"departure": departure, "departed_at": departed_at}
            connection.execute(update(characters).where(characters.c.id == id).values(values))
        return replace(_from(row), departure=departure, departed_at=departed_at)

    def delete(self, id: str) -> None:
        with self._db.begin() as connection:
            connection.execute(delete(characters).where(characters.c.id == id))
