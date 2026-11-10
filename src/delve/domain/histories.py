"""Histories and carries (carry-the-party-on plan Task 1). A party carried on from one campaign into a new one takes
its history along: one per campaign, written by Claude as a job in two versions, the DM's (`dm_md`, which may hold
secrets) and the table's (`table_md`, only what the whole table was told). A carry is the link from the old campaign
to the new one, with the ids of the characters that went."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from delve.domain import data

HistoryStatus = Literal["writing", "done", "failed"]


class _Record:
    """`from_dict` and `to_dict` for the frozen dataclasses below."""

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Any:
        return data.from_dict(cls, raw)

    def to_dict(self) -> dict[str, Any]:
        return data.to_dict(self)


@dataclass(frozen=True)
class History(_Record):
    """A campaign's history, as Markdown: the DM's and the table's texts. `edited` is set when the host has replaced
    them by hand. `conversion_id` is the job that writes it and `cost_usd` its spend. Storage sets `created_at` and
    `updated_at`."""

    campaign_id: str
    dm_md: str = ""
    table_md: str = ""
    status: HistoryStatus = "writing"
    error: str | None = None
    edited: bool = False
    conversion_id: str | None = None
    cost_usd: float | None = None
    created_at: str = ""
    updated_at: str = ""


@dataclass(frozen=True)
class Carry(_Record):
    """A party carried on from `from_campaign_id` (None once that campaign is deleted) into `to_campaign_id`, with the
    old campaign's ids of the characters that went. `id` is given by storage, as is `carried_at`."""

    id: int
    from_campaign_id: str | None
    to_campaign_id: str
    character_ids: tuple[str, ...]
    carried_at: str = ""
