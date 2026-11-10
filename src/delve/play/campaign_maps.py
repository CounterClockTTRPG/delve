"""A campaign's own maps (campaign maps, 2026-10-23): dungeon maps made for one campaign, such as a district the table
invented, never part of its module's canon. They are played beside the maps of the revision the campaign pinned, by
the same moves, views and exits, and stay out of the module, its revisions and its export. An own map may include the
revision's libraries. A module map named like an own map gives way to it, so an upgrade never swaps the table's map.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from delve.domain.campaigns import Campaign
    from delve.domain.modules import ModuleMap, Revision
    from delve.storage.interfaces import Storage


def with_own_maps(revision: Revision, own: Sequence[ModuleMap]) -> Revision:
    """`revision` with the campaign's own maps after its own, a module map of the same name left out."""
    names = {m.name for m in own}
    return replace(revision, maps=(*[m for m in revision.maps if m.name not in names], *own))


def played_revision(storage: Storage, campaign: Campaign) -> Revision | None:
    """The revision the campaign pinned, with its own maps; None when the revision is missing."""
    revision = storage.revisions.get(campaign.module_id, campaign.revision)
    return None if revision is None else with_own_maps(revision, storage.campaign_maps.list(campaign.id))


def own_names(storage: Storage, campaign_id: str) -> set[str]:
    """The names of the campaign's own maps."""
    return {m.name for m in storage.campaign_maps.list(campaign_id)}
