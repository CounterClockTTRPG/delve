"""Campaigns, which pin a revision of their module; the seats at their table and the characters in them; the
campaign's own state; its events, notes and sessions."""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from delve.domain import data
from delve.domain.characters import CharacterState, Kind, Sheet
from delve.domain.world import Journey, StartDate, Weather, WorldPosition

COINS = ("pp", "gp", "ep", "sp", "cp")


def default_ruleset(offered: Sequence[str], preferred: Collection[str] = ()) -> str:
    """The first offered ruleset that is `preferred` (its pack says so, DEL-307), else the first offered ("" when none
    is)."""
    return next((id for id in offered if id in preferred), next(iter(offered), ""))


def default_setting(offered: Sequence[str], preferred: Collection[str] = ()) -> str:
    """The first offered setting that is `preferred`, else "", which is no setting."""
    return next((id for id in offered if id in preferred), "")


CampaignStatus = str
"""An open enum: one of `CAMPAIGN_STATUSES` as Delve sets it, kept as text."""
CAMPAIGN_STATUSES: tuple[CampaignStatus, ...] = ("in_progress", "paused", "complete")

VoiceSetting = Literal["allowed", "off"]
VOICE_SETTINGS: tuple[VoiceSetting, ...] = ("allowed", "off")
"""Whether the people at a campaign's table may talk in voice (table voice and fixes Task 0); `allowed` by default."""

InitiativeMode = Literal["combatant", "side"]
INITIATIVE_MODES: tuple[InitiativeMode, ...] = ("combatant", "side")
"""How a campaign's fights roll initiative: per combatant (the default) or per side, the PHB's standard method."""

Visibility = Literal["private", "public"]
ObserverRule = Literal["anyone", "approved", "nobody"]
OBSERVER_RULES: tuple[ObserverRule, ...] = ("anyone", "approved", "nobody")
"""Who may watch a table (DEL-215): `anyone` with the join link (the default), those a host lets in (`approved`: a
watcher asks, as a player does at a public table), or `nobody`."""
SeatAsk = Literal["player", "observer"]
VISIBILITIES: tuple[Visibility, ...] = ("private", "public")
"""Who finds a campaign's table (DEL-204): `private`, only those its join link brings in (the default), or `public`,
the accounts of this Delve too, who ask to join."""
DESCRIPTION_LENGTH = 4000
"""The most characters a table's description has."""
MOST_SLOTS = 20
"""The most places for players a table has, when it limits them."""


class MissingPack(Exception):
    """A campaign's ruleset or setting that this install doesn't have: its pack isn't installed (DEL-307)."""

    def __init__(self, kind: Literal["ruleset", "setting"], id: str) -> None:
        self.kind = kind
        self.id = id
        self.message = f"This campaign's {kind}, {id}, isn't installed."
        super().__init__(self.message)


@dataclass(frozen=True)
class Campaign:
    """A playthrough of a module's pinned `revision`, in its `ruleset` and its `setting` ("": no setting)."""

    id: str
    name: str
    module_id: str
    revision: int
    created_at: str
    ruleset: str
    setting: str
    join_token: str = ""
    """The token of the campaign's join link (plan 4 Task 2): the host's to share, never in the campaign's JSON."""
    status: CampaignStatus = "in_progress"
    """`in_progress`, `paused` or `complete` (plan 7 Task 1)."""
    voice: VoiceSetting = "allowed"
    """Whether voice is allowed at the table (table voice and fixes Task 0), set by the host."""
    initiative: InitiativeMode = "combatant"
    """The fights' initiative mode, set by the host; a change takes effect at the next round."""
    observers: ObserverRule = "anyone"
    """Who may watch the table (DEL-215), set by the host."""
    visibility: Visibility = "private"
    """Who finds the table (DEL-204), set by an organiser."""
    description: str = ""
    """The table's description for its players (DEL-204), Markdown: how they play together, what they expect of each
    other, whether newcomers are welcome. Players only: the DM never reads it, so it never goes into a prompt."""
    slots: int | None = None
    """The places for players (DEL-204), 1 to `MOST_SLOTS`, or None for no limit. A live `player` or `cohost` seat
    takes one; the host and observers take none."""
    schedule: dict[str, Any] | None = None
    """When the table plays (DEL-204 part C), as `delve.play.schedule` checks it: `{"every_weeks", "first", "start",
    "end", "time_zone", "changes"}`, set by an organiser, its next session moved or skipped by the host; None for
    none."""


SeatRole = Literal["host", "cohost", "player", "observer"]
SEAT_ROLES: tuple[SeatRole, ...] = ("host", "cohost", "player", "observer")


@dataclass(frozen=True)
class Seat:
    """A person at one campaign's table (spec §7.2, §11): a display name, a language and a role. Exactly one seat of
    a campaign is its `host`. `organiser` gives the install's organiser rights too; `owner` marks the install's
    owner's own seat, which has no token: the owner token stands for it. A seat that left keeps its row, with
    `left_at`. `account_id` is the account that sits in it (players and tavern Task B1); a seat made before accounts
    has none and is reached by its token."""

    id: str
    campaign_id: str
    name: str
    language: str
    role: SeatRole
    organiser: bool = False
    owner: bool = False
    joined_at: str = ""
    left_at: str | None = None
    account_id: str | None = None


JoinRequestStatus = Literal["pending", "accepted", "declined", "withdrawn"]
JOIN_REQUEST_STATUSES: tuple[JoinRequestStatus, ...] = ("pending", "accepted", "declined", "withdrawn")


@dataclass(frozen=True)
class JoinRequest:
    """An account's request to join a public table (DEL-204): `pending` until a host or a co-host `accepted` it (with
    the `seat_id` it made, or the account's seat there already) or `declined` it, or the account `withdrawn` it, at
    `decided_at`. `messages` is the short thread between the player and the hosts, oldest first, each `{"from":
    "player"|"host", "name", "text", "at"}`; the first is the player's note, when it gave one. The messages are for
    people only: the DM never reads them. An account has at most one pending request per table."""

    id: str
    campaign_id: str
    account_id: str
    status: JoinRequestStatus = "pending"
    messages: tuple[dict[str, Any], ...] = ()
    created_at: str = ""
    decided_at: str | None = None
    seat_id: str | None = None
    role: SeatAsk = "player"
    """What the account asks to be (DEL-215): a `player`, or an `observer` at a table whose watchers a host lets in."""


Departure = Literal["died", "retired", "left"]
DEPARTURES: tuple[Departure, ...] = ("died", "retired", "left")
"""Why a PC left the party (backlog Features 26): it keeps its sheet, history and place in the story."""


@dataclass(frozen=True)
class Character:
    """A PC or an NPC. `order` is the PC's place in the marching order, front first; NPCs have None.
    `controller_id` is the seat that plays the PC; None when nobody does (and for NPCs). `departure` is why the PC
    left the party, and `departed_at` when; both None while it is in it (table voice and fixes Task 0)."""

    id: str
    campaign_id: str
    name: str
    kind: Kind = "pc"
    sheet: Sheet = field(default_factory=Sheet)
    state: CharacterState = field(default_factory=CharacterState)
    order: int | None = None
    created_at: str = ""
    controller_id: str | None = None
    departure: Departure | None = None
    departed_at: str | None = None


@dataclass(frozen=True)
class LootItem:
    """Something in the party's loot pile, waiting to be claimed."""

    kind: str
    """gem, art, magic, or item (something a character put down)."""
    description: str
    value_gp: float = 0
    category: str = ""
    qty: int = 1


def _no_coin() -> dict[str, int]:
    return dict.fromkeys(COINS, 0)


@dataclass(frozen=True)
class CampaignState:
    """The campaign's clock, session number, the party's coin and its loot pile; the date its day 1 is
    (`start_date`, None until the calendar first gives it one), today's weather per terrain, and where the party is
    on a world map (`world`) with the journey it is on (`journey`)."""

    campaign_id: str
    day: int = 1
    hour: int = 6
    """Dawn, as ttrpg2 starts."""
    minute: int = 0
    session: int = 1
    coin: dict[str, int] = field(default_factory=_no_coin)
    loot: tuple[LootItem, ...] = ()
    start_date: StartDate | None = None
    weather: tuple[Weather, ...] = ()
    """The weather rolled for each terrain, the last rolled last."""
    world: WorldPosition | None = None
    journey: Journey | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> CampaignState:
        return data.from_dict(cls, raw)

    def to_dict(self) -> dict[str, Any]:
        return data.to_dict(self)


@dataclass(frozen=True)
class Event:
    """One entry of a campaign's event log, numbered in the order they were appended."""

    id: int
    campaign_id: str
    session: int
    beat: str
    type: str
    data: dict[str, Any]
    at: str


NoteKind = Literal["secret", "room", "log"]


@dataclass(frozen=True)
class Note:
    """The DM's notes. A `secret` is DM-only until `revealed`; a `room` note is the DM's memory of what the party
    changed in a room of a map (`map_name`, `node`); a `log` note is a public line of the chronicle."""

    id: str
    campaign_id: str
    kind: NoteKind
    text: str
    tags: tuple[str, ...] = ()
    related_to: str = ""
    """The character, NPC, place or quest it is about."""
    revealed: bool = False
    map_name: str | None = None
    node: str | None = None
    session: int = 1
    created_at: str = ""
    updated_at: str = ""


@dataclass(frozen=True)
class Session:
    """One evening of play, numbered from 1 in its campaign; `recap_md` is written when it ends."""

    campaign_id: str
    number: int
    title: str
    started_at: str = ""
    ended_at: str | None = None
    recap_md: str | None = None


BeatStatus = Literal["open", "running", "done", "failed", "cancelled"]
BEAT_ENDS: tuple[BeatStatus, ...] = ("done", "failed", "cancelled")


@dataclass(frozen=True)
class CombatRound:
    """One round of a fight as the initiative timeline shows it (table voice and fixes Task 0): the slots in
    initiative order, each `{id, name, side, character_id, node, count, group, ongoing}` (the DM's truth, which the
    timeline redacts per seat), the round's `outcomes` once it is resolved (`resolved_at`), and when the table may
    see them (`released_at`, once the DM's text for the round has arrived). `beat_id` is the beat whose tool call
    rolled it."""

    combat_id: str
    round: int
    campaign_id: str
    mode: InitiativeMode
    slots: tuple[dict[str, Any], ...]
    outcomes: dict[str, Any] | None = None
    beat_id: str | None = None
    rolled_at: str = ""
    resolved_at: str | None = None
    released_at: str | None = None


@dataclass(frozen=True)
class Beat:
    """One go of the table (spec §7.1), numbered from 1 in its campaign. A beat is `open` while players submit and
    `running` while the DM answers; it ends `done`, `failed` or `cancelled`, with `closed_at`. A submission is
    `{"player", "character_ids", "kind": "act", "text"}`; with one player, submitting closes the beat at once."""

    id: str
    campaign_id: str
    number: int
    status: BeatStatus
    submissions: tuple[dict[str, Any], ...] = ()
    opened_at: str = ""
    closed_at: str | None = None


TableState = Literal["gathering", "playing", "break"]
TABLE_STATES: tuple[TableState, ...] = ("gathering", "playing", "break")
AbsentMode = Literal["in_character", "hold_back", "out"]
ABSENT_MODES: tuple[AbsentMode, ...] = ("in_character", "hold_back", "out")


@dataclass(frozen=True)
class TableSession:
    """The table's session state (DEL-199): `gathering` before a session and after one, `playing`, or on a `break`,
    since `since`. `absent` is the host's choice for a PC whose player isn't there, at the session's start or during
    it (by character id: played `in_character` by the DM, `hold_back` in the background, or `out` of the session);
    `hands` the raised hands, by seat id, `{"at", "point"}`; `away` the seats that stepped away, or that the host
    marked away, mid-session (DEL-224), by seat id, `{"at", "part"}` with the part their PCs take meanwhile (an
    `AbsentMode`, or None for the table's fallback); `break_at` when the break began, while on one."""

    campaign_id: str
    state: TableState
    since: str | None = None
    absent: dict[str, AbsentMode] = field(default_factory=dict)
    hands: dict[str, dict[str, Any]] = field(default_factory=dict)
    break_at: str | None = None
    away: dict[str, dict[str, Any]] = field(default_factory=dict)


StoryKind = Literal[
    "player_act", "dm_text", "tool", "image", "dm_error", "recap", "ask", "answer", "talk", "scene", "say"
]


@dataclass(frozen=True)
class StoryEntry:
    """One entry of a campaign's story, numbered by `seq` in its campaign. Its `payload` is already player-safe for
    every kind the player sees; the DM's raw stream is in the DM log, never here. `beat_id` is None outside a beat
    (an Ask the DM). `audience` says who at the table may see it: None for everyone, or `{"characters": [ids]}` or
    `{"seats": [ids]}` (`delve.play.audience`)."""

    id: str
    campaign_id: str
    beat_id: str | None
    seq: int
    kind: StoryKind
    payload: dict[str, Any]
    at: str = ""
    audience: dict[str, list[str]] | None = None


TranslationStatus = Literal["translating", "done", "failed"]


@dataclass(frozen=True)
class Translation:
    """A story entry's text in one language other than English (spec §7.7), as far as it has been translated: still
    `translating`, `done`, or `failed`, which leaves the English to read. The entry itself stays English."""

    entry_id: str
    language: str
    text: str
    status: TranslationStatus
    updated_at: str = ""
    answer: str | None = None
    """An Ask the DM's shared answer in this language (plan 7 Task 18), beside the entry's own `text`."""


@dataclass(frozen=True)
class DmLogEntry:
    """One event of the DM's raw stream, as JSON: a DM-only record for debugging."""

    campaign_id: str
    beat_id: str | None
    raw_event_json: dict[str, Any]
    at: str = ""
