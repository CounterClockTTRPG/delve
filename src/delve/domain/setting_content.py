"""The setting's content of this install (settings plan Task 2), over the shipped setting, which stays read-only: the
pages an organiser added or overrode, the setting's facts, and the DM's proposals."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from delve.domain import data

ProposalKind = Literal["page", "edit", "fact"]
ProposalStatus = Literal["pending", "accepted", "rejected"]
EditMode = Literal["append", "replace"]


def title_key(title: str) -> str:
    """The title a page is matched by: its whitespace collapsed to single spaces, casefolded."""
    return " ".join(title.split()).casefold()


class _Record:
    """`from_dict` and `to_dict` for the frozen dataclasses below."""

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Any:
        return data.from_dict(cls, raw)

    def to_dict(self) -> dict[str, Any]:
        return data.to_dict(self)


@dataclass(frozen=True)
class SettingAddition(_Record):
    """A page of the setting on this install, one per setting and `title_key`. `text` is Markdown with `[[Title]]` /
    `[[Title|label]]` links and `::: dm` sections. Whether it is a new page or an override is never stored: it is an
    override when the shipped setting has a page of that title. Storage sets `created_at` and `updated_at`."""

    setting: str
    title: str
    kind: str = ""
    fields: dict[str, str] = field(default_factory=dict)
    text: str = ""
    dm_only: bool = False
    created_at: str = ""
    updated_at: str = ""


@dataclass(frozen=True)
class SettingFact(_Record):
    """A lore fact of the setting on this install. `id` is given by storage (0 before it is added)."""

    id: int
    setting: str
    text: str
    category: str = ""
    dm_only: bool = False
    created_at: str = ""


@dataclass(frozen=True)
class Proposal(_Record):
    """What a campaign's DM proposed to the setting: a new page (`page`), an edit of a page (`edit`, appended or
    replacing its text by `mode`) or a fact (`fact`). It applies at once to its own campaign, and to every campaign
    once accepted. `id` is given by storage (0 before it is added)."""

    id: int
    setting: str
    campaign_id: str
    kind: ProposalKind
    title: str = ""
    text: str = ""
    mode: EditMode = "append"
    page_kind: str = ""
    category: str = ""
    dm_only: bool = False
    status: ProposalStatus = "pending"
    created_at: str = ""
    decided_at: str | None = None
