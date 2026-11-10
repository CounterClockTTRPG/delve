"""The DM's proposals to the setting (settings plan Task 8): proposed, merged, edited, and accepted or rejected by an
organiser.

A proposal applies at once to its own campaign (the setting layer reads it there), and to every campaign once it is
accepted, when it becomes an ordinary addition or fact of the install. A rejected one stays its campaign's: that
table already played with it. One campaign's pending proposals of the same kind and page merge into one, so the
organiser reviews one item per page; facts never merge."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from delve.domain.setting_content import Proposal, SettingAddition, SettingFact, title_key
from delve.play.setting_layer import SettingLayer
from delve.setting.text import dm_section, wiki_markdown
from delve.storage.interfaces import Storage


class ProposalRefused(ValueError):
    """A proposal that can't be found (`status` 404) or decided as asked (409, 422)."""

    def __init__(self, message: str, status: int) -> None:
        self.status = status
        super().__init__(message)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _joined(base: str, text: str) -> str:
    return f"{base}\n\n{text}" if base else text


def propose_page(
    storage: Storage,
    layer: SettingLayer,
    campaign_id: str,
    title: str,
    text: str,
    *,
    kind: str = "",
    dm_only: bool = False,
    mode: str = "append",
) -> Proposal:
    """A new page, or an edit of the page `layer` reads as `title` (stored under that page's title), for the campaign.
    A pending proposal of the campaign of the same kind and title takes it in: a new page's text, or a replace,
    replaces its text; an append is joined to it after a blank line. It is DM-only if either was, and an edit of a
    DM-only page always is."""
    title = " ".join(title.split())
    pending = storage.proposals.list(layer.id, campaign_id=campaign_id, status="pending")
    proposed = [p for p in pending if p.kind == "page" and title_key(p.title) == title_key(title)]
    if proposed:
        found, merged_kind = proposed[-1], "page"
    else:
        page = layer.page(title)
        merged_kind = "edit" if page is not None else "page"
        if page is not None:
            title, dm_only = page.title, dm_only or page.dm_only
        same = [p for p in pending if p.kind == merged_kind and title_key(p.title) == title_key(title)]
        found = same[-1] if same else None
    edit_mode = "replace" if merged_kind == "edit" and mode == "replace" else "append"
    if found is None:
        return storage.proposals.add(
            Proposal(
                0,
                layer.id,
                campaign_id,
                merged_kind,
                title=title,
                text=text,
                mode=edit_mode,
                page_kind=kind,
                dm_only=dm_only,
            )
        )
    if merged_kind == "page" or edit_mode == "replace":
        merged = replace(found, text=text, mode=edit_mode if merged_kind == "edit" else found.mode)
    else:
        merged = replace(found, text=_joined(found.text, text))
    return storage.proposals.put(replace(merged, page_kind=kind or found.page_kind, dm_only=found.dm_only or dm_only))


def propose_fact(
    storage: Storage, layer: SettingLayer, campaign_id: str, text: str, *, category: str = "", dm_only: bool = False
) -> Proposal:
    """A fact of the setting, for the campaign; never merged with another."""
    return storage.proposals.add(
        Proposal(0, layer.id, campaign_id, "fact", text=text, category=category, dm_only=dm_only)
    )


def _pending(storage: Storage, proposal_id: int) -> Proposal:
    proposal = storage.proposals.get(proposal_id)
    if proposal is None:
        raise ProposalRefused(f"There is no proposal {proposal_id}.", 404)
    if proposal.status != "pending":
        raise ProposalRefused(f"This proposal was {proposal.status} already.", 409)
    return proposal


def edit(
    storage: Storage,
    proposal_id: int,
    *,
    title: str | None = None,
    text: str | None = None,
    category: str | None = None,
    page_kind: str | None = None,
    dm_only: bool | None = None,
) -> Proposal:
    """The pending proposal with the fields given changed."""
    proposal = _pending(storage, proposal_id)
    changes: dict = {"category": category, "page_kind": page_kind, "dm_only": dm_only}
    if title is not None:
        changes["title"] = " ".join(title.split())
        if proposal.kind != "fact" and not changes["title"]:
            raise ProposalRefused("A proposal of a page needs its title.", 422)
    if text is not None:
        if not text.strip():
            raise ProposalRefused("A proposal needs its text.", 422)
        changes["text"] = text
    return storage.proposals.put(replace(proposal, **{k: v for k, v in changes.items() if v is not None}))


def accept(storage: Storage, layer: SettingLayer, proposal_id: int) -> SettingAddition | SettingFact:
    """The pending proposal made the install's: a fact, a new page, or the page it edits as an addition (an override
    of a shipped page), its text appended (in a DM-only section when the proposal is DM-only) or replaced. `layer` is
    the organisers' (`dm=True`, no campaign)."""
    with storage.transaction():
        proposal = _pending(storage, proposal_id)
        made: SettingAddition | SettingFact
        if proposal.kind == "fact":
            made = storage.setting_facts.add(
                SettingFact(0, proposal.setting, proposal.text, proposal.category, proposal.dm_only)
            )
        elif proposal.kind == "page":
            if layer.page(proposal.title) is not None:
                raise ProposalRefused(
                    f"There is a page titled {proposal.title} already: edit the proposal's title, or reject it.", 409
                )
            made = storage.setting_pages.put(
                SettingAddition(
                    proposal.setting,
                    proposal.title,
                    kind=proposal.page_kind,
                    text=proposal.text,
                    dm_only=proposal.dm_only,
                )
            )
        else:
            made = storage.setting_pages.put(_edited(layer, proposal))
        storage.proposals.put(replace(proposal, status="accepted", decided_at=_now()))
        return made


def _edited(layer: SettingLayer, proposal: Proposal) -> SettingAddition:
    """The addition an accepted edit makes of the page it edits; the proposal's text alone when that page is gone."""
    base = layer.page(proposal.title)
    if base is None:
        return SettingAddition(
            proposal.setting, proposal.title, kind=proposal.page_kind, text=proposal.text, dm_only=proposal.dm_only
        )
    added = layer.addition(base.title)
    if proposal.mode == "replace":
        text, dm_only = proposal.text, base.dm_only or proposal.dm_only
    else:
        before = wiki_markdown(base.text) if base.format == "wiki" else base.text
        text = _joined(before, dm_section(proposal.text) if proposal.dm_only else proposal.text)
        dm_only = base.dm_only
    # An override without a kind of its own keeps the shipped page's (the shipped kind is a table, not a kind).
    kind = added.kind if added is not None else ("" if base.origin == "shipped" else proposal.page_kind)
    return SettingAddition(
        proposal.setting, base.title, kind=kind, fields=dict(base.fields), text=text, dm_only=dm_only
    )


def reject(storage: Storage, proposal_id: int) -> Proposal:
    """The pending proposal rejected: it no longer reaches the other campaigns, and stays its own campaign's."""
    proposal = _pending(storage, proposal_id)
    return storage.proposals.put(replace(proposal, status="rejected", decided_at=_now()))
