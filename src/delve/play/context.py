"""What every play service is handed: the storage, the dice of this beat, the event log, and the
campaign's setting (read through the setting layer, as the DM reads it) and ruleset (`delve.rules.catalog`).

A tool call opens one `CampaignContext` and runs inside one `storage.transaction()` (Task 11's tool host does both), so
its writes, rolls and events commit together or not at all.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from delve.dice import Dice, Rng, SystemRng
from delve.domain.campaigns import Campaign, Event, MissingPack
from delve.domain.reference import RulesetReference
from delve.domain.settings import Job
from delve.packs.catalogs import IN_TREE, Catalogs
from delve.play.clock import Clock, SystemClock
from delve.play.setting_layer import layer_for
from delve.rules.catalog import entry as ruleset_entry
from delve.rules.catalog import make_ruleset
from delve.rules.classic.tables import RuleTables
from delve.rules.fake import FakeRuleset
from delve.rules.ruleset import NO_LOOKUPS, Ruleset
from delve.setting.catalog import entry as setting_entry
from delve.setting.catalog import make_setting
from delve.setting.setting import Setting
from delve.storage.interfaces import Storage


class PlayError(Exception):
    """A request the rules or the state refuse; `hint` says what would work. Tools answer `{"error", "hint"}`."""

    def __init__(self, message: str, hint: str = "") -> None:
        self.message = message
        self.hint = hint
        super().__init__(message)


class NotFound(PlayError, LookupError):
    """An unknown or ambiguous name. `candidates` are `{"id", "name"}` of the characters (or things) it could be."""

    def __init__(self, message: str, candidates: Iterable[dict[str, Any]] = (), hint: str = "") -> None:
        self.candidates = list(candidates)
        super().__init__(
            message, hint or ("Name one of the candidates exactly, or use its id." if self.candidates else "")
        )


SYSTEM_RNG = SystemRng()


def always_paid(job: Job) -> bool:
    """The paid-images gate when nobody says which model is chosen: every painting costs money."""
    return True


@dataclass
class CampaignContext:
    storage: Storage
    dice: Dice
    campaign_id: str
    beat: str
    setting: Setting | None
    """The campaign's setting as its DM reads it: the setting layer, with the install's pages and facts and
    this campaign's proposals; None when it has none."""
    ruleset: Ruleset | None = None
    """The campaign's ruleset (`delve.rules.catalog`); what the play services ask of the rules. Made by `context_for`;
    None only for a context made by hand without one."""
    image_paid: Callable[[Job], bool] = always_paid
    """Whether the model Preferences chose for an image job costs money (`delve.play.images.is_paid`, as the app
    wires it); every one does by default."""
    clock: Clock = field(default_factory=SystemClock)
    """The clock the table keeps time by (`AppServices.clock`, as the tool host is handed it): what a play service
    stamps its rows with."""

    @property
    def lookups(self) -> RulesetReference:
        """The campaign's ruleset's lookups: its monsters, spells, items, classes and rules; none (`NO_LOOKUPS`) for a
        ruleset that has none."""
        reference = self.ruleset.reference if self.ruleset is not None else None
        return reference if reference is not None else NO_LOOKUPS

    @property
    def rules(self) -> RuleTables:
        """The campaign's ruleset's numbers for the classic engine."""
        if self.ruleset is None:
            raise PlayError("This campaign has no ruleset.")
        return self.ruleset.tables

    def log(self, type: str, **data: Any) -> Event:
        """Append an event to the campaign's log, in the current session and beat."""
        state = self.storage.campaign_states.get(self.campaign_id)
        session = state.session if state is not None else 1
        return self.storage.events.append(self.campaign_id, type, data, session=session, beat=self.beat)


def _has_ruleset(catalogs: Catalogs, ruleset_id: str) -> bool:
    return not ruleset_id or ruleset_id == FakeRuleset.id or ruleset_entry(ruleset_id, catalogs.rulesets) is not None


def _has_setting(catalogs: Catalogs, setting_id: str | None) -> bool:
    return not setting_id or setting_entry(setting_id, catalogs.settings) is not None


def missing_pack(catalogs: Catalogs, campaign: Campaign) -> MissingPack | None:
    """What the campaign needs that isn't installed: its ruleset, else its setting; None when it has both. No ruleset
    id (the fake one) and no setting are never missing."""
    if not _has_ruleset(catalogs, campaign.ruleset):
        return MissingPack("ruleset", campaign.ruleset)
    if not _has_setting(catalogs, campaign.setting):
        return MissingPack("setting", campaign.setting or "")
    return None


def context_for(
    storage: Storage,
    campaign_id: str,
    beat: str,
    rng: Rng = SYSTEM_RNG,
    *,
    image_paid: Callable[[Job], bool] = always_paid,
    catalogs: Catalogs = IN_TREE,
    allow_missing: bool = False,
    clock: Clock | None = None,
) -> CampaignContext:
    """The context of one campaign in one beat. Its dice log to `storage.rolls`, so a roll repeated within the beat is
    the stored one. Its `setting` is the one the campaign names, as the DM sees the setting layer, and its `ruleset`
    the one it plays (whose lookups `lookups` reads), both out of `catalogs`. `MissingPack` when the campaign's ruleset or setting isn't in them; with
    `allow_missing`, the fake ruleset and no setting stand in, for reading a campaign (never playing it) that lacks its pack.
    It keeps time by `clock`, the system's without one."""
    campaign = storage.campaigns.get(campaign_id)
    if campaign is None:
        raise NotFound(f"No campaign '{campaign_id}'.")
    if not allow_missing and (missing := missing_pack(catalogs, campaign)) is not None:
        raise missing
    ruleset_id = campaign.ruleset if _has_ruleset(catalogs, campaign.ruleset) else None
    setting_id = campaign.setting if _has_setting(catalogs, campaign.setting) else None
    return CampaignContext(
        storage,
        Dice(rng, storage.rolls, campaign_id, beat),
        campaign_id,
        beat,
        layer_for(storage, make_setting(setting_id, catalogs.settings), campaign_id=campaign_id, dm=True),
        make_ruleset(ruleset_id, catalogs.rulesets),
        image_paid,
        clock or SystemClock(),
    )
