"""What the rest of Delve sees of storage: repositories with methods, never a query.

Ids that don't exist: `get` answers None and `delete` does nothing; every other method raises `KeyError`.
Every write joins the open `Storage.transaction()`, if there is one.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any, Literal, Protocol

from delve.dice import Roll, RollKey
from delve.domain.accounts import Account, AccountLink, Identity, LoginSession, Profile
from delve.domain.board import Post, Topic, Zone
from delve.domain.campaigns import (
    Beat,
    Campaign,
    CampaignState,
    CampaignStatus,
    Character,
    CombatRound,
    Departure,
    DmLogEntry,
    Event,
    InitiativeMode,
    JoinRequest,
    Note,
    NoteKind,
    ObserverRule,
    Seat,
    SeatAsk,
    SeatRole,
    Session,
    StoryEntry,
    StoryKind,
    TableSession,
    Translation,
    TranslationStatus,
    Visibility,
    VoiceSetting,
)
from delve.domain.characters import CharacterState, Kind, Sheet
from delve.domain.conversions import Conversion, ConversionKind, ConversionMode, ConversionStatus
from delve.domain.histories import Carry, History
from delve.domain.house_rules import Bundle, HouseRule, Phase
from delve.domain.house_rules import Kind as RuleKind
from delve.domain.mail import Confirmation, Outgoing
from delve.domain.modules import (
    BannerSource,
    CommentStatus,
    LibraryOrigin,
    Module,
    ModuleCategory,
    ModuleComment,
    ModuleHead,
    ModuleMap,
    Revision,
)
from delve.domain.novels import Novel
from delve.domain.setting_content import Proposal, ProposalKind, ProposalStatus, SettingAddition, SettingFact
from delve.domain.world import (
    CampaignFact,
    CampaignImage,
    CampaignWorldMap,
    Clock,
    Faction,
    ImageKind,
    ImageStatus,
    Merchant,
    MonsterPicture,
    Possession,
    PossessionKind,
    Quest,
    QuestStatus,
    WorldMapSource,
    WorldPicture,
)
from delve.modules.source import ModuleSource


class CategoryNameTaken(ValueError):
    """Another module category has this name, in any case (DEL-114)."""


class ModuleInUse(Exception):
    """A module that campaigns are played from can't be deleted."""

    def __init__(self, module_id: str, campaign_ids: tuple[str, ...]) -> None:
        self.module_id = module_id
        self.campaign_ids = campaign_ids
        super().__init__(f"module {module_id} is used by campaigns {', '.join(campaign_ids)}")


class SnapshotRefused(Exception):
    """A snapshot this database won't take: from a newer Delve, over an item that is here, or a campaign whose module
    revision isn't. Its message is for the owner."""


SnapshotKind = Literal["module", "campaign", "setting"]
SNAPSHOT_KINDS: tuple[SnapshotKind, ...] = ("module", "campaign", "setting")


@dataclass(frozen=True)
class Snapshot:
    """A module, a campaign or a setting as rows (cloud storage, DEL-110): `rows` by table, JSON-ready and ordered by
    primary key, from a database at migration `head`. `blobs` are the shas of the blobs the rows reference; their
    `blobs` rows (with their mime) are in `rows`, their bytes in the blob store."""

    kind: SnapshotKind
    item_id: str
    head: str
    rows: dict[str, list[dict[str, Any]]]
    blobs: frozenset[str]


@dataclass(frozen=True)
class UnusedBlob:
    """A file of the blob store nothing names (DEL-36): `mime` and `created_at` are None for a file without its
    `blobs` row, such as the blobs of a refused restore, whose rows rolled back and whose files stayed."""

    sha: str
    size: int
    mime: str | None
    created_at: str | None


@dataclass(frozen=True)
class UnusedBlobs:
    """What a prune deletes, or deleted: `blobs`, largest first, and `kept`, how many more nothing names yet but that
    are too new to go (written within the grace period, or since a job still running started)."""

    blobs: list[UnusedBlob]
    kept: int

    @property
    def size(self) -> int:
        return sum(blob.size for blob in self.blobs)


@dataclass(frozen=True)
class BackupItem:
    """What the backup store last got of an item: its bundle's hash and size, and when."""

    kind: SnapshotKind
    item_id: str
    hash: str
    size: int
    backed_up_at: str


@dataclass(frozen=True)
class CampaignActivity:
    """How much a campaign has been played: its latest closed beat (or session), its sessions, and their time."""

    last_played: str | None
    sessions: int
    playtime_s: int


class SettingsRepository(Protocol):
    def load(self) -> dict[str, Any]:
        """The raw stored settings, `{}` when nothing is stored."""
        ...

    def save(self, raw: dict[str, Any]) -> None:
        """Replace the stored settings with `raw`."""
        ...

    def update(self, patch: dict[str, Any], *, within: str | None = None) -> dict[str, Any]:
        """Change only `patch`'s keys of the stored settings, or, `within` a key, only those keys of the dict stored
        under it (a value there that isn't a dict is replaced). Read and written in one transaction, so two changes
        to different keys at once both stay. The settings as they now are."""
        ...


class ModuleRepository(Protocol):
    """Modules' working copies. Maps are listed in the order they were first put."""

    def create(self, title: str, metadata: dict[str, Any] | None = None, *, draft: bool = False) -> Module: ...

    def get(self, id: str) -> Module | None: ...

    def list(self) -> list[Module]:
        """Every module, oldest first."""
        ...

    def heads(self) -> dict[str, ModuleHead]:
        """Every module's title and banner, by its id, in one read, without its maps and revisions (DEL-172)."""
        ...

    def delete(self, id: str) -> None:
        """Delete the module with its maps, revisions and blob links. Raises `ModuleInUse` if campaigns use it."""
        ...

    def rename(self, id: str, title: str) -> Module: ...

    def set_metadata(self, id: str, metadata: dict[str, Any]) -> Module: ...

    def set_draft(self, id: str, draft: bool) -> Module:
        """Mark the module a draft or ready; a draft can't start a campaign."""
        ...

    def set_library(
        self, id: str, *, key: str, version: int, hash: str, origin: LibraryOrigin, author: str | None
    ) -> Module:
        """Record the module's entry in the shared library (DEL-110). Not an edit: `updated_at` stays."""
        ...

    def take_working_copy(self, id: str, source_id: str) -> Module:
        """Replace the module's working copy (title, metadata, maps, text and source) with `source_id`'s, which is
        left without one, and link `source_id`'s blobs to it too; its revisions, its other links and its library
        entry stay. A library update (DEL-110) moves a version imported as a scratch module this way."""
        ...

    def put_map(self, id: str, map: ModuleMap) -> Module:
        """Add the map, or replace the one with its name. A default map makes every other map not the default."""
        ...

    def delete_map(self, id: str, name: str) -> Module: ...

    def set_default_map(self, id: str, name: str) -> Module: ...

    def changed_since(self, id: str, revision: int | None) -> bool:
        """Whether the title, metadata, maps or text differ from that revision's; always True for None."""
        ...

    def set_category(self, id: str, category_id: str | None) -> Module:
        """Put the module in a category, or in none (DEL-114). Not an edit: `updated_at` stays. A category that doesn't
        exist raises `KeyError`."""
        ...

    def set_banner(self, id: str, blob: str, mime: str, source: BannerSource) -> Module:
        """Show this picture as the module's banner (DEL-123), linked to it as its `banner` blob, ending any painting
        under way or failed. Not an edit."""
        ...

    def banner_painting(self, id: str, prompt: str) -> Module:
        """Mark a banner being painted from `prompt`; the picture shown, if any, stays until it lands."""
        ...

    def banner_failed(self, id: str, error: str) -> Module:
        """Mark the painting failed, with what went wrong; the picture shown, if any, stays."""
        ...

    def clear_banner(self, id: str) -> Module:
        """No banner: the picture and any painting's state go."""
        ...


class ModuleCategoryRepository(Protocol):
    """The organisers' categories of modules (DEL-114), in their order. Names are unique in any case."""

    def list(self) -> list[ModuleCategory]:
        """Every category, in order."""
        ...

    def get(self, id: str) -> ModuleCategory | None: ...

    def create(self, name: str) -> ModuleCategory:
        """A new category, last. `CategoryNameTaken` for a name another has."""
        ...

    def rename(self, id: str, name: str) -> ModuleCategory:
        """`KeyError` for an unknown id, `CategoryNameTaken` for a name another has."""
        ...

    def move(self, id: str, position: int) -> list[ModuleCategory]:
        """Put the category at `position` (from 0, clamped), the others closing up around it; the whole new order."""
        ...

    def delete(self, id: str) -> int:
        """Delete the category; its modules get none. How many modules it had; `KeyError` for an unknown id."""
        ...


class RevisionRepository(Protocol):
    def snapshot(self, module_id: str) -> Revision:
        """The latest revision if the module hasn't changed since, otherwise a new one numbered after it."""
        ...

    def get(self, module_id: str, number: int) -> Revision | None: ...

    def latest(self, module_id: str) -> Revision | None: ...


class ModuleTextRepository(Protocol):
    """Module text as the raw JSON of `delve.modules.text.ModuleText.to_json`: the working copy's, and each
    revision's, which `RevisionRepository.snapshot` copies and indexes. A module without text has None."""

    def get(self, module_id: str) -> dict[str, Any] | None:
        """The working copy's text."""
        ...

    def put(self, module_id: str, raw: dict[str, Any]) -> None:
        """Replace the working copy's text; the module then differs from its revisions until the next snapshot."""
        ...

    def revision(self, module_id: str, number: int) -> dict[str, Any] | None:
        """The text that revision was made with."""
        ...

    def search(
        self, module_id: str, revision: int, query: str, limit: int = 5, *, section: str = "", any_word: bool = False
    ) -> list[dict[str, Any]]:
        """The best paragraphs of the revision's sections for the words of `query`, as `{anchor, heading_path,
        snippet}`; only sections whose heading path contains `section`, when given. Every word must be there, or with
        `any_word` any of them but the commonest ("the", "of"), best ranked first (DEL-330)."""
        ...


class ModuleSourceRepository(Protocol):
    """Module sources (`delve.modules.source.ModuleSource`): the working copy's, and each revision's, which
    `RevisionRepository.snapshot` copies. Use `delve.modules.source.load_source` to read the working copy: a module
    imported before sources existed has none until then."""

    def get(self, module_id: str) -> ModuleSource | None: ...

    def updated_at(self, module_id: str) -> str | None:
        """When the working copy's source was last put, without reading it; None when it has none."""
        ...

    def put(self, module_id: str, source: ModuleSource) -> None:
        """Replace the working copy's source; the module then differs from its revisions until the next snapshot."""
        ...

    def revision(self, module_id: str, number: int) -> ModuleSource | None:
        """The source that revision pinned."""
        ...

    def pin_legacy(self, module_id: str, source: ModuleSource) -> None:
        """Give `source` to the module's revisions that have none: they were made before sources existed."""
        ...


class CampaignRepository(Protocol):
    def create(
        self,
        name: str,
        module_id: str,
        revision: int,
        *,
        ruleset: str,
        setting: str,
    ) -> Campaign:
        """A campaign pinned to an existing revision of the module, in `ruleset` and `setting` ("": no setting),
        with a new join token."""
        ...

    def get(self, id: str) -> Campaign | None: ...

    def list(self) -> list[Campaign]:
        """Every campaign, oldest first."""
        ...

    def set_revision(self, id: str, revision: int) -> Campaign: ...

    def set_status(self, id: str, status: CampaignStatus) -> Campaign:
        """Set the campaign's status (`in_progress`, `paused` or `complete`); `KeyError` for no such campaign."""
        ...

    def set_voice(self, id: str, voice: VoiceSetting) -> Campaign:
        """Allow voice at the table or switch it off (`allowed`, `off`); `KeyError` for no such campaign,
        `ValueError` for another value."""
        ...

    def set_initiative(self, id: str, mode: InitiativeMode) -> Campaign:
        """Set the fights' initiative mode (`combatant`, `side`); `KeyError` for no such campaign, `ValueError` for
        another value."""
        ...

    def set_observers(self, id: str, rule: ObserverRule) -> Campaign:
        """Set who may watch the table (`anyone`, `approved`, `nobody`, DEL-215); `KeyError` for no such campaign,
        `ValueError` for another value."""
        ...

    def set_listing(self, id: str, visibility: Visibility, description: str, slots: int | None) -> Campaign:
        """Set the table's listing (DEL-204): its visibility (`private`, `public`), its players' description (at most
        `DESCRIPTION_LENGTH` characters) and its places for players (1 to `MOST_SLOTS`, None: no limit); `KeyError`
        for no such campaign, `ValueError` for a value outside those, which changes nothing."""
        ...

    def set_schedule(self, id: str, schedule: dict[str, Any] | None) -> Campaign:
        """Set the table's schedule (DEL-204 part C) as given, already checked (`delve.play.schedule.parse`), or None
        for none; `KeyError` for no such campaign."""
        ...

    def activity(self, campaign_id: str) -> CampaignActivity:
        """When it was last played, how many sessions it has, and their playtime in seconds: an ended session counts
        to its end, an open one up to its last closed beat. `KeyError` for no such campaign."""
        ...

    def activities(self) -> dict[str, CampaignActivity]:
        """Every campaign's `activity`, by its id, in one read: for the list of campaigns (DEL-172)."""
        ...

    def by_join_token(self, token: str) -> Campaign | None:
        """The campaign whose join link holds `token`; None for an unknown or replaced one."""
        ...

    def new_join_token(self, id: str) -> Campaign:
        """Replace the campaign's join token with a new one, so the old link stops working; `KeyError` for no such
        campaign."""
        ...

    def delete(self, id: str) -> None:
        """Delete the campaign with its characters and map states."""
        ...


class SeatRepository(Protocol):
    """The seats at each campaign's table, oldest first, and the seat that plays each character. A seat that left
    keeps its row. A seat's token is known only by its SHA-256 hex digest."""

    def create(
        self,
        campaign_id: str,
        name: str,
        language: str,
        role: SeatRole,
        *,
        organiser: bool = False,
        owner: bool = False,
        token_hash: str | None = None,
        account_id: str | None = None,
    ) -> Seat:
        """A new seat; `ValueError` for a second owner's seat in the campaign, a token hash in use, or a second live
        seat of the account at the campaign."""
        ...

    def get(self, id: str) -> Seat | None: ...

    def by_token_hash(self, token_hash: str) -> Seat | None: ...

    def for_account(self, account_id: str, campaign_id: str) -> Seat | None:
        """The account's live seat at the campaign's table."""
        ...

    def of_account(self, account_id: str) -> list[Seat]:
        """The account's live seats, at every table, oldest first."""
        ...

    def owner_seat(self, campaign_id: str) -> Seat | None:
        """The install's owner's seat at the campaign's table."""
        ...

    def by_campaign(self) -> dict[str, list[Seat]]:
        """Every campaign's seats, each campaign's as `list` answers them: for a list of campaigns (DEL-172)."""
        ...

    def list(self, campaign_id: str) -> list[Seat]:
        """Every seat of the campaign, those that left too."""
        ...

    def save(self, seat: Seat) -> Seat:
        """Store the seat's name, language, role, organiser, joined_at, left_at and account_id; a seat with an account
        loses its token in the same save. `ValueError` when it would be a second live seat of its account at the
        campaign."""
        ...

    def set_controller(self, character_id: str, seat_id: str | None) -> None:
        """Let the seat play the character (None: no seat); `KeyError` for a seat of another campaign."""
        ...

    def controlled(self, seat_id: str) -> list[str]:
        """The ids of the characters the seat plays, oldest first."""
        ...


class JoinRequestRepository(Protocol):
    """Requests to join a public table (DEL-204), each an account's at a campaign. An account has at most one
    `pending` request per table, and any number decided."""

    def create(
        self,
        campaign_id: str,
        account_id: str,
        messages: Sequence[dict[str, Any]],
        created_at: str,
        role: SeatAsk = "player",
    ) -> JoinRequest:
        """A new pending request with its first `messages` (the player's note, or none), to be a `role` (DEL-215);
        `KeyError` for an unknown campaign or account, `ValueError` when the account has a pending request there
        already."""
        ...

    def get(self, id: str) -> JoinRequest | None: ...

    def of_account(self, account_id: str) -> list[JoinRequest]:
        """The account's requests, at every table, newest first."""
        ...

    def of_campaign(self, campaign_id: str) -> list[JoinRequest]:
        """The table's requests, oldest first."""
        ...

    def save(self, request: JoinRequest) -> JoinRequest:
        """Store the request's status, messages, decided_at and seat_id; `KeyError` for an unknown request."""
        ...


class BoardRepository(Protocol):
    """The message board (DEL-297): zones, their topics, and the posts in a topic, with each account's read marks.
    Deleting a zone takes its topics, posts and marks; deleting a topic, its posts and marks."""

    def create_zone(self, zone: Zone) -> Zone:
        """Store the zone with a fresh id when its id is empty, after the last in `position`; `ValueError` when
        another zone has its `campaign_id`."""
        ...

    def get_zone(self, id: str) -> Zone | None: ...

    def zones(self) -> list[Zone]:
        """Every zone, by `position`."""
        ...

    def zone_of_campaign(self, campaign_id: str) -> Zone | None: ...

    def save_zone(self, zone: Zone) -> Zone:
        """Store the zone's fields; `KeyError` for an unknown zone, `ValueError` when another has its campaign."""
        ...

    def delete_zone(self, id: str) -> None: ...

    def add_topic(self, topic: Topic, first: Post) -> tuple[Topic, Post]:
        """Store the topic and its first post, both with fresh ids, in one transaction."""
        ...

    def get_topic(self, id: str) -> Topic | None: ...

    def topics(self, zone_id: str) -> list[Topic]:
        """The zone's topics, pinned first, then by `last_post_at`, newest first."""
        ...

    def save_topic(self, topic: Topic) -> Topic:
        """Store the topic's title, pinned and locked; `KeyError` for an unknown topic."""
        ...

    def delete_topic(self, id: str) -> None: ...

    def add_post(self, post: Post) -> Post:
        """Store the post with a fresh id; the topic's `last_post_at`, `last_author_id` and `posts` follow, in the
        same transaction. `KeyError` for an unknown topic."""
        ...

    def get_post(self, id: str) -> Post | None: ...

    def posts(self, topic_id: str, offset: int = 0, limit: int = 30) -> list[Post]:
        """The topic's posts, oldest first."""
        ...

    def post_index(self, post: Post) -> int:
        """The post's 0-based place in its topic."""
        ...

    def save_post(self, post: Post) -> Post:
        """Store the post's text, edited_at, removed and picture; `KeyError` for an unknown post."""
        ...

    def mark_read(self, account_id: str, topic_id: str, at: str) -> None:
        """Note that the account has read the topic up to `at`, keeping the later of that and what is stored; nothing
        for a topic that is gone."""
        ...

    def read_marks(self, account_id: str) -> dict[str, str]:
        """Topic id to the time of the newest post the account has read."""
        ...

    def first_visit(self, account_id: str) -> str | None: ...

    def set_first_visit(self, account_id: str, at: str) -> None:
        """Note the account's first visit, only when none is stored."""
        ...

    def follow(self, account_id: str, topic_id: str) -> None:
        """Follow the topic (DEL-314); nothing when already following or the topic is gone."""
        ...

    def unfollow(self, account_id: str, topic_id: str) -> None: ...

    def followers(self, topic_id: str) -> list[tuple[str, str | None]]:
        """The accounts following the topic, with when each was last mailed about it, by account id."""
        ...

    def following(self, account_id: str, topic_id: str) -> bool: ...

    def set_notified(self, account_id: str, topic_id: str, at: str) -> None: ...


class AccountRepository(Protocol):
    """Accounts with their profiles, oldest first (players and tavern Task B1). A username is stored case-folded and
    looked up as given. The password's hash is never part of an `Account`: only `password_hash` and
    `set_password_hash` read and write it. The changes raise `KeyError` for an unknown account."""

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
        """A new account without a password; `ValueError` for a username in use. `pending`: a sign-up that waits for
        approval (DEL-156)."""
        ...

    def get(self, id: str) -> Account | None: ...

    def by_username(self, username: str) -> Account | None: ...

    def by_external_id(self, external_id: str) -> Account | None: ...

    def list(self) -> list[Account]: ...

    def has_owner(self) -> bool:
        """Whether any account is an owner, without reading them (DEL-172): asked on every request from this machine
        until one is."""
        ...

    def password_hash(self, id: str) -> str | None: ...

    def set_password_hash(self, id: str, password_hash: str) -> None: ...

    def save_profile(self, id: str, profile: Profile) -> Account: ...

    def set_organiser(self, id: str, organiser: bool) -> Account: ...

    def set_owner(self, id: str, owner: bool) -> Account: ...

    def set_disabled(self, id: str, disabled_at: str | None) -> Account: ...

    def set_reset_asked(self, id: str, asked_at: str | None) -> Account:
        """When the player asked for a new password (DEL-268), or None once it is answered. `KeyError` for an unknown
        id."""
        ...

    def approve(self, id: str) -> Account:
        """The pending account is approved: no longer `pending`. `KeyError` for an unknown id."""
        ...

    def delete_pending(self, id: str) -> bool:
        """Delete the account if it is still pending (a rejected sign-up, DEL-156); whether it was deleted."""
        ...

    def set_email(self, id: str, *, email: str | None, email_pending: str | None) -> None:
        """Store the confirmed address and the one waiting for its link (DEL-314); `KeyError` for an unknown account."""
        ...

    def set_mail_switches(self, id: str, *, mail_host: bool, mail_board: bool) -> None:
        """Store the switches for a host's mail and the board's; `KeyError` for an unknown account."""
        ...

    def with_email(self, address: str) -> list[Account]:
        """The enabled, approved accounts whose confirmed address is `address`, whatever its case."""
        ...


class AccountLinkRepository(Protocol):
    """One-time links that set or reset a password, known only by their token's SHA-256 hex digest."""

    def put(self, token_hash: str, link: AccountLink) -> None: ...

    def get(self, token_hash: str) -> AccountLink | None: ...

    def use(self, token_hash: str, used_at: str) -> bool:
        """Mark the link used; False when it is unknown or was used already."""
        ...

    def drop_unused(self, account_id: str) -> None:
        """Delete the account's links that weren't used."""
        ...


class MailRepository(Protocol):
    """The outbox and the confirmations of addresses (DEL-314). The outbox keeps no recipient address; its rows go
    with their account."""

    def add(self, outgoing: Outgoing) -> None: ...

    def due(self, now_iso: str, limit: int) -> list[Outgoing]:
        """Unsent, not failed messages whose `next_at` has come, oldest first."""
        ...

    def sent(self, id: str, at: str) -> None:
        """Mark the message sent, and clear its `reply_to`."""
        ...

    def retry(self, id: str, attempts: int, next_at: str) -> None: ...

    def failed(self, id: str, at: str, failure: str) -> None:
        """Give up on the message, and clear its `reply_to`."""
        ...

    def dropped(self, id: str, at: str) -> None:
        """Give up on the message because nobody should get it: failed with the failure `dropped`."""
        ...

    def recent_failures(self, limit: int, *, dropped: bool = True) -> list[Outgoing]:
        """The failed messages, newest first; without the dropped ones for `dropped=False`."""
        ...

    def waiting(self) -> int:
        """How many messages are neither sent nor failed, due or not."""
        ...

    def sent_since(self, at: str) -> int:
        """How many messages were sent at or after `at`."""
        ...

    def prune_sent(self, before: str) -> None:
        """Delete the messages sent before `before`."""
        ...

    def put_confirmation(self, confirmation: Confirmation) -> None:
        """Store the confirmation after deleting the account's other unused ones."""
        ...

    def confirmation(self, token_hash: str) -> Confirmation | None: ...

    def use_confirmation(self, token_hash: str, at: str) -> bool:
        """Mark the confirmation used; False when it is unknown or was used already."""
        ...


class IdentityRepository(Protocol):
    """The outside identities accounts log in with (DEL-206), by provider and subject."""

    def get(self, provider: str, subject: str) -> Identity | None: ...

    def list(self, account_id: str) -> list[Identity]:
        """The account's identities, by provider."""
        ...

    def add(self, identity: Identity) -> Identity:
        """Link the identity, at its `linked_at`; `ValueError` when it is another account's, the account has one of
        that provider already, or the account is unknown."""
        ...

    def remove(self, account_id: str, provider: str) -> bool:
        """Unlink the account's identity of `provider`; False when it has none."""
        ...


class LoginSessionRepository(Protocol):
    """The browsers logged in to each account (players and tavern Task C1), known only by their token's SHA-256 hex
    digest. Times are ISO strings."""

    def create(self, account_id: str, token_hash: str, device: str, address: str, now: str) -> LoginSession:
        """A new login session; `ValueError` for a token hash in use or an unknown account."""
        ...

    def by_token_hash(self, token_hash: str) -> LoginSession | None: ...

    def touch(self, id: str, now: str) -> None:
        """Mark the session used at `now`."""
        ...

    def list(self, account_id: str) -> list[LoginSession]:
        """The account's sessions, the most recently used first."""
        ...

    def end(self, id: str) -> None: ...

    def end_all(self, account_id: str, *, but: str | None = None) -> None:
        """End every session of the account, except the one with the id `but`."""
        ...


class CharacterRepository(Protocol):
    """PCs and NPCs. A character's `sheet.label` is always its `name`, and `sheet.kind` its `kind`. Its
    `controller_id` changes only through `SeatRepository.set_controller`."""

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
        """A new character. A PC without an `order` goes to the back of the marching order; an NPC has none."""
        ...

    def get(self, id: str) -> Character | None: ...

    def list(self, campaign_id: str) -> list[Character]:
        """The campaign's characters, PCs and NPCs, oldest first."""
        ...

    def rename(self, id: str, name: str) -> Character: ...

    def save(self, character: Character) -> Character:
        """Store the character's name, kind, sheet, state and order; raises `KeyError` if it isn't in its campaign.
        Its controller and its departure stay as stored, and are answered as stored."""
        ...

    def save_state(self, character: Character) -> Character:
        """Store the character's state alone, so a sheet saved since its read stays; `KeyError` as `save`. The
        character answered is the stored one with that state."""
        ...

    def save_sheet(self, character: Character) -> Character:
        """Store the character's name and sheet alone, so a state saved since its read stays; `KeyError` as `save`.
        The character answered is the stored one with that name and sheet."""
        ...

    def set_departure(self, id: str, departure: Departure | None, at: str | None = None) -> Character:
        """The PC leaves the party (`died`, `retired`, `left`) at `at` (now by default), or comes back with None;
        `KeyError` for no such character, `ValueError` for another value."""
        ...

    def delete(self, id: str) -> None: ...


class MapStateRepository(Protocol):
    """Map states as the raw JSON of `delve.maps.state.to_json`, per campaign and map name."""

    def get(self, campaign_id: str, map_name: str) -> dict[str, Any] | None: ...

    def put(self, campaign_id: str, map_name: str, raw: dict[str, Any]) -> None: ...

    def list(self, campaign_id: str) -> dict[str, dict[str, Any]]:
        """The campaign's map states by map name."""
        ...


class CampaignMapRepository(Protocol):
    """A campaign's own maps (campaign maps, 2026-10-23), by name, in the order they were first put: dungeon maps made
    for one campaign, never its module's canon, each a playable `map` (never a library or the default), gone with the
    campaign."""

    def get(self, campaign_id: str, name: str) -> ModuleMap | None: ...

    def list(self, campaign_id: str) -> list[ModuleMap]: ...

    def put(self, campaign_id: str, name: str, source: str) -> None:
        """Add the map, or replace the source of the one with its name in place; `KeyError` for an unknown campaign."""
        ...

    def delete(self, campaign_id: str, name: str) -> None: ...


class CampaignStateRepository(Protocol):
    def get(self, campaign_id: str) -> CampaignState | None:
        """The campaign's state; a fresh `CampaignState` when none is stored yet."""
        ...

    def put(self, state: CampaignState) -> None: ...


class RollRepository(Protocol):
    """The dice log of every campaign: `delve.dice.RollLog`, plus listing."""

    def find(self, campaign_id: str, key: RollKey) -> Roll | None: ...

    def record(self, campaign_id: str, roll: Roll) -> None:
        """Log a roll; one roll per key and campaign."""
        ...

    def list(self, campaign_id: str, beat: str | None = None) -> list[Roll]:
        """The campaign's rolls in the order they were logged; one beat's with `beat`."""
        ...

    def get_many(self, campaign_id: str, ids: Iterable[str]) -> dict[str, Roll]:
        """The campaign's rolls of these ids, by id; an id it has no roll of is left out (DEL-270)."""
        ...


class EventRepository(Protocol):
    """The story log: events numbered in the order they were appended."""

    def append(self, campaign_id: str, type: str, data: dict[str, Any], *, session: int, beat: str) -> Event: ...

    def list(
        self,
        campaign_id: str,
        *,
        after: int | None = None,
        types: Iterable[str] | None = None,
        limit: int | None = None,
        beat: str | None = None,
    ) -> list[Event]:
        """Oldest first: those after event `after`, of the `types`, of the beat `beat`, at most `limit`."""
        ...

    def recent(self, campaign_id: str, n: int) -> list[Event]:
        """The last `n` events, oldest first."""
        ...

    def search(self, campaign_id: str, words: str, limit: int) -> list[Event]:
        """Newest first, at most `limit`: the events with a string value (at the top of their data) that contains
        `words`, ignoring the case of ASCII letters (DEL-172)."""
        ...


class CombatRepository(Protocol):
    """Fights as the raw JSON of `delve.rules.classic.combat.to_json`, with their phase. A campaign has at most one live
    fight: one whose phase isn't "ended"."""

    def live(self, campaign_id: str) -> tuple[str, dict[str, Any]] | None:
        """The id and state of the campaign's live fight, if there is one."""
        ...

    def create(self, campaign_id: str, phase: str, raw: dict[str, Any]) -> str:
        """Store a new fight and answer its id. Raises `ValueError` while the campaign has a live one."""
        ...

    def save(self, id: str, phase: str, raw: dict[str, Any]) -> None: ...

    def get(self, id: str) -> dict[str, Any] | None: ...


class NoteRepository(Protocol):
    """The DM's notes: secrets, room notes and chronicle lines, oldest first."""

    def create(
        self,
        campaign_id: str,
        kind: NoteKind,
        text: str,
        *,
        tags: Iterable[str] = (),
        related_to: str = "",
        map_name: str | None = None,
        node: str | None = None,
        session: int = 1,
    ) -> Note: ...

    def get(self, id: str) -> Note | None: ...

    def list(
        self, campaign_id: str, *, kind: NoteKind | None = None, map_name: str | None = None, node: str | None = None
    ) -> list[Note]:
        """The campaign's notes, oldest first; of one kind, or one room's with `map_name` and `node`."""
        ...

    def search(self, campaign_id: str, words: str, limit: int) -> list[Note]:
        """Newest first, at most `limit`: the notes whose text contains `words`, ignoring the case of ASCII letters
        (DEL-172)."""
        ...

    def save(self, note: Note) -> Note:
        """Store the note's text, tags, related_to and revealed."""
        ...


class SessionRepository(Protocol):
    """The campaign's sessions, by number."""

    def start(self, campaign_id: str, number: int, title: str) -> Session: ...

    def get(self, campaign_id: str, number: int) -> Session | None: ...

    def list(self, campaign_id: str) -> list[Session]:
        """In order of number."""
        ...

    def end(self, campaign_id: str, number: int, recap_md: str) -> Session:
        """Store the recap and when it ended."""
        ...


class HouseRuleRepository(Protocol):
    """The library of house rules, shared by every campaign."""

    def create(
        self,
        *,
        title: str,
        body_md: str = "",
        kind: RuleKind = "general",
        phases: Iterable[Phase] = (),
        ruleset: str | None = None,
        setting: str | None = None,
        subject: str | None = None,
        enabled: bool = True,
    ) -> HouseRule: ...

    def get(self, id: str) -> HouseRule | None: ...

    def list(self) -> list[HouseRule]:
        """Every rule, oldest first."""
        ...

    def save(self, rule: HouseRule) -> HouseRule:
        """Store every field of an existing rule."""
        ...

    def delete(self, id: str) -> None:
        """Delete the rule, and take it out of every bundle and campaign."""
        ...


class BundleRepository(Protocol):
    """House-rule bundles: their ordered `rule_ids` name existing rules (`KeyError` otherwise)."""

    def create(self, *, title: str, description_md: str = "", rule_ids: Iterable[str] = ()) -> Bundle: ...

    def get(self, id: str) -> Bundle | None: ...

    def list(self) -> list[Bundle]:
        """Every bundle, oldest first."""
        ...

    def save(self, bundle: Bundle) -> Bundle: ...

    def delete(self, id: str) -> None:
        """Delete the bundle, and take it out of every campaign; its rules stay."""
        ...


class CampaignHouseRulesRepository(Protocol):
    """Which bundles and single rules a campaign points to, in order. It copies nothing (spec §9)."""

    def get(self, campaign_id: str) -> tuple[list[str], list[str]] | None:
        """`(bundle_ids, rule_ids)`, empty for a campaign that chose none; None for an unknown campaign."""
        ...

    def put(self, campaign_id: str, bundle_ids: Iterable[str], rule_ids: Iterable[str]) -> None:
        """Replace the campaign's choice; `KeyError` for an unknown campaign, bundle or rule."""
        ...


class BeatRepository(Protocol):
    """Beats, numbered from 1 per campaign. A campaign has at most one current beat: one that is open or running."""

    def open(self, campaign_id: str, submissions: list[dict[str, Any]], status: str = "open") -> Beat:
        """A new beat numbered after the last. Raises `ValueError` while the campaign has a current one."""
        ...

    def get(self, id: str) -> Beat | None: ...

    def current(self, campaign_id: str) -> Beat | None:
        """The campaign's open or running beat, if there is one."""
        ...

    def latest(self, campaign_id: str) -> Beat | None:
        """The campaign's beat of the highest number, whatever its status; None before its first."""
        ...

    def save(self, beat: Beat) -> Beat:
        """Store the beat's status, submissions, opened_at (a break moves it on) and closed_at."""
        ...


class StoryRepository(Protocol):
    """The story the players see, numbered by `seq` per campaign in the order entries were first put."""

    def append(
        self,
        campaign_id: str,
        beat_id: str | None,
        kind: StoryKind,
        payload: dict[str, Any],
        audience: dict[str, list[str]] | None = None,
    ) -> StoryEntry: ...

    def put(self, entry: StoryEntry) -> StoryEntry:
        """Add the entry, numbered after the campaign's last, or replace the payload of the stored one with its id;
        answers it as stored. An entry's audience is set when it is added, and stays."""
        ...

    def get(self, id: str) -> StoryEntry | None: ...

    def list(
        self,
        campaign_id: str,
        *,
        before_seq: int | None = None,
        limit: int | None = None,
        kind: StoryKind | None = None,
    ) -> list[StoryEntry]:
        """The last `limit` entries before `before_seq`, oldest first; only those of `kind` when given (DEL-219)."""
        ...

    def search(self, campaign_id: str, words: str, limit: int) -> list[StoryEntry]:
        """Newest first, at most `limit`: the entries whose payload's `text` contains `words`, ignoring the case of
        ASCII letters (DEL-172)."""
        ...


class TranslationRepository(Protocol):
    """Story entries in other languages than English: one row per entry and language."""

    def put(
        self, entry_id: str, language: str, text: str, status: TranslationStatus, *, answer: str | None = None
    ) -> Translation:
        """Store the entry's translation so far, with its shared answer's (`answer`), replacing what was there."""
        ...

    def for_entries(self, entry_ids: Iterable[str], language: str) -> dict[str, Translation]:
        """The translations into `language` of those entries that have one, by entry id."""
        ...

    def fail_unfinished(self) -> int:
        """Mark every translation still `translating` as `failed` (at the start of Delve); how many there were."""
        ...


class DmLogRepository(Protocol):
    """The DM's raw stream per campaign and beat, in the order it was appended. DM-only."""

    def append(self, campaign_id: str, beat_id: str | None, raw: dict[str, Any]) -> DmLogEntry: ...

    def list(self, campaign_id: str, beat_id: str | None = None) -> list[DmLogEntry]: ...

    def costs(self, campaign_id: str) -> list[dict[str, Any]]:
        """The log summed per beat, in the order the beats began: `{beat, at, ask, tools, input, output, cost}`, with
        the tool calls, the tokens and the `cost_usd` of the beat's usage events (`cost` None while none carried one).
        Each Ask is a row of its own (`ask`, its `beat` `ask-<n>`), in its place among the beats, with its usage."""
        ...


class DmSessionRepository(Protocol):
    """The DM provider's resumable conversation per campaign: which provider, its session id (the `claude -p`
    session to `--resume`), and how many tokens its context holds."""

    def get(self, campaign_id: str) -> dict[str, Any] | None:
        """`{"provider", "session_id", "context_tokens", "updated_at"}`, or None when nothing is stored."""
        ...

    def set(self, campaign_id: str, provider: str, session_id: str | None, context_tokens: int) -> None:
        """Store it, replacing what was there; `KeyError` for an unknown campaign."""
        ...

    def clear(self, campaign_id: str) -> None:
        """Forget it, so the next beat starts a fresh conversation."""
        ...


class PlaySettingsRepository(Protocol):
    """The campaign's own play settings: `{"tone", "detail", "effort", "model"}`, as the play API stores them."""

    def get(self, campaign_id: str) -> dict[str, Any] | None: ...

    def put(self, campaign_id: str, raw: dict[str, Any]) -> None:
        """Replace them; `KeyError` for an unknown campaign."""
        ...


class TableSessionRepository(Protocol):
    """The table's session state (DEL-199), one per campaign: None until the first change stores it."""

    def get(self, campaign_id: str) -> TableSession | None: ...

    def put(self, session: TableSession) -> None:
        """Replace it; `KeyError` for an unknown campaign."""
        ...


class ConversionRepository(Protocol):
    """Conversions, newest first. At most one is `running`; the others wait `queued`."""

    def create(
        self,
        kind: ConversionKind,
        title: str,
        mode: ConversionMode,
        *,
        target: dict[str, Any] | None = None,
        status: ConversionStatus = "running",
        comments: str = "",
    ) -> Conversion:
        """A new `running` (or `queued`) conversion at no step yet, on `target` (`{"module_id", …}`) if it works on
        something that exists, with the PDF form's `comments`; `ValueError` for a running one while another one runs,
        or another status."""
        ...

    def get(self, id: str) -> Conversion | None: ...

    def list(self, limit: int = 20) -> list[Conversion]:
        """The last `limit`, newest first."""
        ...

    def for_module(self, module_id: str) -> list[Conversion]:
        """Every conversion that made the module (`module_id`) or works on it (`target.module_id`), newest first,
        however many there are."""
        ...

    def running(self) -> Conversion | None: ...

    def paused(self) -> list[Conversion]:
        """The paused jobs (thorough conversions), oldest first."""
        ...

    def queued(self) -> list[Conversion]:
        """The queued jobs, oldest first (by when they were made): the order they start in."""
        ...

    def queue_paused(self) -> bool:
        """Whether the queue's switch is paused: then no queued job starts. False until it is set."""
        ...

    def set_queue_paused(self, paused: bool) -> None: ...

    def save(self, conversion: Conversion) -> Conversion:
        """Store its status, progress, module, warnings, error, result and questions (and title, and comments), with
        a new `updated_at`. `closed` stays as stored, and is answered as stored."""
        ...

    def set_closed(self, id: str, closed: Sequence[str]) -> Conversion:
        """Store the keys of its closed questions and doubts (`question:<id>`, `doubt:<index>`), de-duplicated in
        the order given, and answer the job."""
        ...


class CombatRoundRepository(Protocol):
    """A fight's rounds as the initiative timeline shows them, one per fight and round; they go with the fight."""

    def put(self, row: CombatRound) -> CombatRound:
        """Add the round, or replace all of it but `released_at`, which only `release` sets; answers it as stored.
        `KeyError` for an unknown fight."""
        ...

    def get(self, combat_id: str, round: int) -> CombatRound | None: ...

    def latest(self, combat_id: str) -> CombatRound | None:
        """The fight's highest round."""
        ...

    def list(self, combat_id: str) -> list[CombatRound]:
        """The fight's rounds, by round."""
        ...

    def release(self, combat_id: str, round: int, at: str) -> bool:
        """Let the table see the round's outcomes from `at`, once; False when it was already released, or is
        unknown."""
        ...

    def unreleased(self, campaign_id: str) -> list[CombatRound]:
        """The campaign's resolved rounds not released yet, oldest first."""
        ...


class ModuleCommentRepository(Protocol):
    """Fix-it comments on a module, oldest first; deleting the module deletes them."""

    def create(
        self, module_id: str, text: str, *, anchor: dict[str, Any] | None = None, author: str = ""
    ) -> ModuleComment:
        """A new `open` comment; `KeyError` for an unknown module."""
        ...

    def get(self, id: str) -> ModuleComment | None: ...

    def list(self, module_id: str) -> list[ModuleComment]: ...

    def with_status(self, module_id: str, *statuses: CommentStatus) -> list[ModuleComment]:
        """The module's comments in one of `statuses`, oldest first."""
        ...

    def for_conversion(self, conversion_id: str) -> list[ModuleComment]:
        """The comments the job acts on, oldest first."""
        ...

    def save(self, comment: ModuleComment) -> ModuleComment:
        """Store its text, anchor, status, job, revision, error and author with a new `updated_at`; `KeyError` for
        an unknown comment, `ValueError` for a status not in `COMMENT_STATUSES`."""
        ...


class FactionRepository(Protocol):
    """The campaign's factions, by id, in the order they were first put."""

    def get(self, campaign_id: str, id: str) -> Faction | None: ...

    def list(self, campaign_id: str, *, known: bool | None = None) -> list[Faction]:
        """Every faction, or only the known (or unknown) ones."""
        ...

    def put(self, faction: Faction, /) -> Faction:
        """Add the faction, or replace the one with its id; `KeyError` for an unknown campaign."""
        ...

    def delete(self, campaign_id: str, id: str) -> None:
        """Delete the faction; its clocks stay, with no faction."""
        ...


class ClockRepository(Protocol):
    """Clocks, numbered by storage, oldest first."""

    def get(self, id: int) -> Clock | None: ...

    def list(self, campaign_id: str, *, faction_id: str | None = None, running: bool | None = None) -> list[Clock]:
        """The campaign's clocks; one faction's, or only the running (no `done_day`) or done ones."""
        ...

    def add(self, clock: Clock, /) -> Clock:
        """Store a new clock (its `id` is ignored) and answer it with its id; `KeyError` for an unknown campaign."""
        ...

    def put(self, clock: Clock) -> Clock:
        """Store every field of an existing clock of its campaign."""
        ...

    def delete(self, id: int) -> None: ...


class QuestRepository(Protocol):
    """The campaign's quests, by id, in the order they were first put."""

    def get(self, campaign_id: str, id: str) -> Quest | None: ...

    def list(
        self, campaign_id: str, *, status: QuestStatus | None = None, known: bool | None = None
    ) -> list[Quest]: ...

    def put(self, quest: Quest, /) -> Quest:
        """Add the quest, or replace the one with its id; `KeyError` for an unknown campaign."""
        ...

    def delete(self, campaign_id: str, id: str) -> None: ...


class CampaignFactRepository(Protocol):
    """The campaign's own lore facts, numbered by storage, oldest first."""

    def get(self, id: int) -> CampaignFact | None: ...

    def list(self, campaign_id: str, *, query: str = "", category: str = "") -> list[CampaignFact]:
        """The facts whose text holds `query` (any case), of `category` when given."""
        ...

    def add(self, fact: CampaignFact, /) -> CampaignFact:
        """Store a new fact (its `id` is ignored) and answer it with its id; `KeyError` for an unknown campaign."""
        ...


class PossessionRepository(Protocol):
    """The campaign's possessions, by id, in the order they were first put. A deleted owner leaves a possession to
    the party (`owner_id` None)."""

    def get(self, campaign_id: str, id: str) -> Possession | None: ...

    def list(
        self, campaign_id: str, *, owner_id: str | None = None, kind: PossessionKind | None = None
    ) -> list[Possession]:
        """Every possession, or one character's, or one kind's."""
        ...

    def put(self, possession: Possession) -> Possession:
        """Add the possession, or replace the one with its id, and answer it as stored: `created_at` is kept from
        the first put and `updated_at` is now. `KeyError` for an unknown campaign, or an owner not of the
        campaign."""
        ...

    def delete(self, campaign_id: str, id: str) -> None: ...


class WorldMapRepository(Protocol):
    """The campaign's world maps, by name, in the order they were first put."""

    def get(self, campaign_id: str, name: str) -> CampaignWorldMap | None: ...

    def list(self, campaign_id: str) -> list[CampaignWorldMap]: ...

    def put(self, world_map: CampaignWorldMap) -> CampaignWorldMap:
        """Add the map, or replace the one with its name, and answer it with a new `updated_at`; `KeyError` for an
        unknown campaign."""
        ...

    def delete(self, campaign_id: str, name: str) -> None: ...


class MerchantRepository(Protocol):
    """The campaign's magic merchants and their shelves, by id, in the order they were first put. A deleted NPC
    leaves the merchant with no `npc_id`."""

    def get(self, campaign_id: str, id: str) -> Merchant | None: ...

    def list(self, campaign_id: str) -> list[Merchant]: ...

    def put(self, merchant: Merchant, /) -> Merchant:
        """Add the merchant, or replace the one with its id; `KeyError` for an unknown campaign."""
        ...


class CampaignImageRepository(Protocol):
    """Generated images, oldest first. Their bytes are in the blob store, which keeps them when a row goes."""

    def get(self, id: str) -> CampaignImage | None: ...

    def list(
        self,
        campaign_id: str,
        *,
        kind: ImageKind | None = None,
        subject_id: str | None = None,
        status: ImageStatus | None = None,
    ) -> list[CampaignImage]: ...

    def painting(self) -> list[CampaignImage]:
        """Every image still `painting`, across campaigns: those a stopped Delve left behind, at its start."""
        ...

    def everywhere(self, kind: ImageKind, status: ImageStatus) -> list[CampaignImage]:
        """Every campaign's images of that kind and status, oldest first: for a list of campaigns (DEL-172)."""
        ...

    def put(self, image: CampaignImage) -> CampaignImage:
        """Add the image, or replace the one with its id, and answer it as stored, `created_at` kept from the first
        put; `KeyError` for an unknown campaign."""
        ...

    def delete(self, id: str) -> None: ...


class WorldPictureRepository(Protocol):
    """World-map pictures and their tiles, by the original's sha256: shared by every map that uses them."""

    def get(self, id: str) -> WorldPicture | None: ...

    def put(self, picture: WorldPicture) -> WorldPicture:
        """Add the picture, or replace the one with its id, and answer it as stored, `created_at` kept from the first
        put."""
        ...


class MonsterPictureRepository(Protocol):
    """The kinds of monsters' pictures, by slug, for every campaign (DEL-275)."""

    def get(self, slug: str) -> MonsterPicture | None: ...

    def list(self) -> list[MonsterPicture]:
        """Every kind's, by slug."""
        ...

    def put(self, picture: MonsterPicture) -> MonsterPicture:
        """Add the picture, or replace the one with its slug, and answer it as stored, `created_at` kept from the first
        put."""
        ...


class SettingPageRepository(Protocol):
    """A setting's added and overridden pages on this install, one per setting and `title_key`: a title is matched
    with its whitespace collapsed and casefolded. Whether a page is an override is the shipped setting's to say."""

    def get(self, setting: str, title: str) -> SettingAddition | None: ...

    def list(self, setting: str, *, kind: str | None = None, query: str = "") -> list[SettingAddition]:
        """The setting's pages by title; one kind's, or those whose title or text holds `query` (casefolded, `%` and
        `_` plain characters)."""
        ...

    def put(self, addition: SettingAddition) -> SettingAddition:
        """Add the page, or replace the one with its `title_key`, and answer it as stored: `created_at` is kept from
        the first put, `updated_at` is now, and the title is spelt as this put spells it."""
        ...

    def delete(self, setting: str, title: str) -> None: ...


class SettingFactRepository(Protocol):
    """A setting's facts on this install, numbered by storage, oldest first."""

    def get(self, id: int) -> SettingFact | None: ...

    def list(self, setting: str, *, query: str = "") -> list[SettingFact]:
        """The setting's facts, or those whose text holds `query` (casefolded, `%` and `_` plain characters)."""
        ...

    def add(self, fact: SettingFact) -> SettingFact:
        """Store a new fact (its `id` is ignored) and answer it with its id."""
        ...

    def put(self, fact: SettingFact) -> SettingFact:
        """Store every field of an existing fact but its `created_at`, and answer it as stored."""
        ...

    def delete(self, id: int) -> None: ...


class ProposalRepository(Protocol):
    """The DM's proposals to the settings, numbered by storage, oldest first. Deleting a campaign deletes its
    proposals."""

    def get(self, id: int) -> Proposal | None: ...

    def list(
        self,
        setting: str | None = None,
        *,
        campaign_id: str | None = None,
        status: ProposalStatus | None = None,
        kind: ProposalKind | None = None,
    ) -> list[Proposal]:
        """Every proposal, or those of one setting, campaign, status or kind."""
        ...

    def add(self, proposal: Proposal) -> Proposal:
        """Store a new proposal (its `id` is ignored) and answer it with its id; `KeyError` for an unknown campaign."""
        ...

    def put(self, proposal: Proposal) -> Proposal:
        """Store every field of an existing proposal but its `created_at`, and answer it as stored."""
        ...


class SettingMapRepository(Protocol):
    """A setting's own world maps on this install, by name, in the order they were first put. A setting's map is
    always a Delve GeoJSON document; its `dsl` reads as empty."""

    def get(self, setting: str, name: str) -> WorldMapSource | None: ...

    def list(self, setting: str) -> list[WorldMapSource]: ...

    def put(self, setting: str, world_map: WorldMapSource) -> WorldMapSource:
        """Add the map, or replace the one with its name, and answer it as stored; `ValueError` when it has no
        `geo`."""
        ...

    def delete(self, setting: str, name: str) -> None: ...


class NovelRepository(Protocol):
    """Novels of campaigns and modules, newest first. A novel has exactly one source (`ValueError` otherwise, and
    `KeyError` for an unknown one), and deleting its campaign or its module deletes it."""

    def create(self, novel: Novel) -> Novel:
        """Add the novel, with a new id when its own is empty, and answer it as stored, its dates set."""
        ...

    def get(self, id: str) -> Novel | None: ...

    def save(self, novel: Novel) -> Novel:
        """Replace the stored novel with this one, `created_at` kept, and answer it as stored."""
        ...

    def for_campaign(self, campaign_id: str) -> list[Novel]: ...

    def for_module(self, module_id: str) -> list[Novel]: ...

    def delete(self, id: str) -> bool:
        """Delete the novel; False when there was none."""
        ...

    def writing(self) -> list[Novel]:
        """Every novel still `writing`, across sources: those a stopped Delve left behind, at its start."""
        ...


class HistoryRepository(Protocol):
    """A campaign's history, one per campaign; deleting the campaign deletes it."""

    def get(self, campaign_id: str) -> History | None: ...

    def put(self, history: History) -> History:
        """Add the campaign's history, or replace it with `created_at` kept, and answer it as stored, its dates set;
        `KeyError` for an unknown campaign."""
        ...

    def writing(self) -> list[History]:
        """Every history still `writing`: those a stopped Delve left behind, at its start."""
        ...


class CarryRepository(Protocol):
    """The parties carried on, from a campaign into a new one. A campaign is carried into once, and may be carried on
    from more than once. Deleting the old campaign keeps the carry with `from_campaign_id` None; deleting the new one
    deletes it."""

    def add(self, from_campaign_id: str, to_campaign_id: str, character_ids: Sequence[str]) -> Carry:
        """Record the carry and answer it as stored; `KeyError` for an unknown campaign, `ValueError` when the new
        campaign already has an origin."""
        ...

    def origin(self, to_campaign_id: str) -> Carry | None:
        """The carry the campaign was made by, if any."""
        ...

    def all(self) -> list[Carry]:
        """Every carry, oldest first: for a list of campaigns (DEL-172)."""
        ...

    def onward(self, from_campaign_id: str) -> list[Carry]:
        """The carries out of the campaign, oldest first."""
        ...


class SnapshotRepository(Protocol):
    """Modules, campaigns and settings as rows, for a backup's bundles (cloud storage, DEL-110).

    A module is its working copy with all its revisions and their attachments' links; a campaign every row of its own,
    the story's translations and the house rules it points to (never `campaign_carries`); a setting its pages, facts
    and maps on this install, with their world pictures. A module's or a campaign's own id that doesn't exist is a
    `KeyError`; a setting is whatever rows it has."""

    def dump(self, kind: SnapshotKind, item_id: str) -> Snapshot:
        """The item as it is, ordered so that two dumps of an unchanged item are equal."""
        ...

    def restore(self, snapshot: Snapshot, *, replace: bool) -> list[str]:
        """Write the snapshot in one transaction and answer its warnings. `SnapshotRefused` for a snapshot from a
        newer Delve, for an item that is here unless `replace` (which first deletes the item's rows, keeping a module's
        row and its revisions that campaigns play), and for a campaign whose module revision isn't here. House rules,
        world pictures and blobs already here are kept; a seat whose account isn't here loses it, with a warning; a
        counter id taken here gives the table's rows new ones. A blob's bytes must already be in the blob store."""
        ...

    def item_ids(self, kind: SnapshotKind) -> list[str]:
        """The ids of every item of the kind here, sorted."""
        ...

    def title(self, kind: SnapshotKind, item_id: str) -> str:
        """A module's title, a campaign's name, or a setting's id; `KeyError` for a module or campaign not here."""
        ...


class BackupItemRepository(Protocol):
    """What the backup store last got of each item, one record per kind and id."""

    def get(self, kind: SnapshotKind, item_id: str) -> BackupItem | None: ...

    def put(self, item: BackupItem) -> None:
        """Record the item's backup, replacing the one before."""
        ...

    def list(self) -> list[BackupItem]:
        """Every record, by kind and id."""
        ...


class BlobStore(Protocol):
    """Files, content-addressed by their sha256 hex digest."""

    def put(self, data: bytes, mime: str) -> str:
        """Store `data` (once, whole or not at all) and return its sha256 hex digest."""
        ...

    def put_file(self, source: Path, mime: str) -> str:
        """`put` for the bytes of the file at `source`, streamed, so a large file is never held in memory whole."""
        ...

    def get(self, sha: str) -> bytes | None: ...

    def exists(self, sha: str) -> bool: ...

    def link(self, module_id: str, role: str, sha: str) -> None:
        """Attach a stored blob to a module under `role`; the `.dscn` import uses `"source-bundle"`."""
        ...

    def links(self, module_id: str) -> list[tuple[str, str]]:
        """The module's `(role, sha)` pairs, sorted."""
        ...

    def unused(self, grace: timedelta) -> UnusedBlobs:
        """The blobs nothing names any more, and older than `grace`: what `prune` would delete now."""
        ...

    def prune(self, grace: timedelta) -> UnusedBlobs:
        """Delete what `unused` finds, checked afresh while no one else may write, and answer what went."""
        ...


class Storage(Protocol):
    settings: SettingsRepository
    modules: ModuleRepository
    module_categories: ModuleCategoryRepository
    revisions: RevisionRepository
    module_texts: ModuleTextRepository
    module_sources: ModuleSourceRepository
    campaigns: CampaignRepository
    seats: SeatRepository
    join_requests: JoinRequestRepository
    board: BoardRepository
    accounts: AccountRepository
    account_links: AccountLinkRepository
    mail: MailRepository
    account_identities: IdentityRepository
    login_sessions: LoginSessionRepository
    characters: CharacterRepository
    map_states: MapStateRepository
    campaign_maps: CampaignMapRepository
    blobs: BlobStore
    campaign_states: CampaignStateRepository
    rolls: RollRepository
    events: EventRepository
    combats: CombatRepository
    combat_rounds: CombatRoundRepository
    notes: NoteRepository
    sessions: SessionRepository
    house_rules: HouseRuleRepository
    house_rule_bundles: BundleRepository
    campaign_house_rules: CampaignHouseRulesRepository
    beats: BeatRepository
    story: StoryRepository
    translations: TranslationRepository
    dm_log: DmLogRepository
    dm_sessions: DmSessionRepository
    play_settings: PlaySettingsRepository
    table_sessions: TableSessionRepository
    conversions: ConversionRepository
    module_comments: ModuleCommentRepository
    factions: FactionRepository
    clocks: ClockRepository
    quests: QuestRepository
    campaign_facts: CampaignFactRepository
    possessions: PossessionRepository
    world_maps: WorldMapRepository
    merchants: MerchantRepository
    campaign_images: CampaignImageRepository
    world_pictures: WorldPictureRepository
    monster_pictures: MonsterPictureRepository
    setting_pages: SettingPageRepository
    setting_facts: SettingFactRepository
    proposals: ProposalRepository
    setting_maps: SettingMapRepository
    novels: NovelRepository
    histories: HistoryRepository
    carries: CarryRepository
    snapshots: SnapshotRepository
    backup_items: BackupItemRepository

    def transaction(self) -> AbstractContextManager[None]:
        """One transaction: every repository write inside it commits together when the block ends, or not at all when
        it raises. Writes outside a transaction commit on their own. A transaction inside another joins it. It takes
        the write lock as it begins, so what it reads stays true until it commits: keep slow work out of it."""
        ...

    def reading(self) -> AbstractContextManager[None]:
        """Reads that all see one moment of the database, holding no lock: writes meanwhile go on, unseen by them.
        For reading only; inside a `transaction()` it joins that one."""
        ...

    def close(self) -> None: ...
