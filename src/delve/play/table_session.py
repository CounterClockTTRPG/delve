"""The table's session state (DEL-199): `gathering`, `playing` or on a `break`, moved by the host and the co-hosts,
and the raised hands.

A table gathers before a session and after one: its seats talk and ask the DM, and an act or a pass is refused
(`NotStarted`), except at a solo table (at most one seat that plays and hasn't left), where the first act starts the
session as it always did. The host starts the session (`start_session`) with a choice for each PC whose player isn't
there: the DM plays it `in_character`, cautiously, it stays in the background (`hold_back`), or it is `out` of the
session. That choice is the PC's fallback in every beat of the session that no submission covers it in
(`delve.play.beats`), and an `out` PC gets no line at all. The start is a beat of its own, with one Delve-written
`session` submission that tells the DM to open the scene and how the absent PCs take part; it runs at once.

A break (`take_break`) refuses acts, passes and go (`OnABreak`), and stops an open beat's timer: nothing closes the
beat until the table is back to the story (`back_to_story`), when the beat's `opened_at`, and so its deadline, moves
on by the length of the break, and its timer runs again. A beat the DM is answering finishes.

The host ends the session (`end_session`): the table gathers at once, its choices and hands cleared, and a last
`session` beat asks the DM to bring the scene to a pause and call `end_session(recap)`. The DM's own `end_session`,
in any beat, gathers the table too (`session_ended`).

A table without a stored state gathers while the pregame's rule says so (`delve.play.pregame`) and no session of the
DM's is under way, and plays otherwise, so a table mid-session when this came keeps playing.

Any seat raises its own hand, with an optional point; it lowers its own, and the host and co-hosts lower anyone's.

Mid-session (DEL-224), a seat steps away (`step_away`), or the host or a co-host marks one away: beats stop waiting
for it, tab open or not, and its PCs take a part meanwhile, the one the seat chose or the table's fallback. It is
back (`come_back`) when it says so, when the host says so, or when it acts or passes (`back_on_act`). The host and
co-hosts also set any PC's part for the rest of the session (`set_part`), as at its start: that choice wins over a
seat's own. The session's end clears both.

Every change is published as the `table` event, with the table as the play state shows it (`table_json`).
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Any

from delve.domain.campaigns import ABSENT_MODES, Beat, Seat, TableSession
from delve.play import pregame
from delve.play.context import PlayError
from delve.play.seats import ONLY_THE_HOST, TABLE_RIGHTS, NotAllowed
from delve.play.table import AppServices, BeatRunning, ensure_installed, one_line, start_beat, starts_session
from delve.storage.interfaces import Storage

__all__ = [
    "POINT_CHARS",
    "NotStarted",
    "OnABreak",
    "SessionRefused",
    "admit",
    "back_on_act",
    "back_to_story",
    "come_back",
    "current",
    "end_line",
    "end_session",
    "lower_hand",
    "on_break",
    "raise_hand",
    "session_ended",
    "set_part",
    "solo",
    "start_line",
    "start_session",
    "started_by_act",
    "step_away",
    "table_json",
    "take_break",
]

POINT_CHARS = 200
"""How long a raised hand's point may be."""
NOT_STARTED = "The session hasn't started yet: the host starts it."
ON_A_BREAK = "The table is on a break."


class SessionRefused(PlayError):
    """The table's session state refuses it (409)."""


class NotStarted(SessionRefused):
    """An act or a pass while the table gathers, at a table that isn't solo."""

    def __init__(self) -> None:
        super().__init__(NOT_STARTED, "Talk at the table until the host starts the session.")


class OnABreak(SessionRefused):
    """An act, a pass or go while the table is on a break."""

    def __init__(self) -> None:
        super().__init__(ON_A_BREAK, "The host takes the table back to the story.")


# ----- reading -----


def current(storage: Storage, campaign_id: str) -> TableSession:
    """The table's session state: the stored one, or without one, gathering while the pregame lasts and no session
    of the DM's is under way, else playing."""
    stored = storage.table_sessions.get(campaign_id)
    if stored is not None:
        return stored
    gathers = pregame.in_pregame(storage, campaign_id) and starts_session(storage, campaign_id)
    return TableSession(campaign_id, "gathering" if gathers else "playing")


def on_break(storage: Storage, campaign_id: str) -> bool:
    return current(storage, campaign_id).state == "break"


def solo(storage: Storage, campaign_id: str) -> bool:
    """Whether the table is solo: at most one seat that isn't an observer and hasn't left."""
    playing = [s for s in storage.seats.list(campaign_id) if s.role != "observer" and s.left_at is None]
    return len(playing) <= 1


def table_json(storage: Storage, campaign_id: str) -> dict[str, Any]:
    """The table's session state for the play screen: the state and since when, whether the table is solo, the
    absent PCs' choices, the raised hands of the seats still at the table, oldest first, and those seats that are
    away, with the part their PCs take."""
    state = current(storage, campaign_id)
    here = {s.id for s in storage.seats.list(campaign_id) if s.left_at is None}
    hands = sorted(
        (
            {"seat_id": seat_id, "at": hand.get("at"), "point": hand.get("point")}
            for seat_id, hand in state.hands.items()
        ),
        key=lambda hand: hand["at"] or "",
    )
    return {
        "state": state.state,
        "since": state.since,
        "solo": solo(storage, campaign_id),
        "absent": dict(state.absent),
        "hands": [hand for hand in hands if hand["seat_id"] in here],
        "away": [
            {"seat_id": seat_id, "at": away.get("at"), "part": away.get("part")}
            for seat_id, away in sorted(state.away.items(), key=lambda item: item[1].get("at") or "")
            if seat_id in here
        ],
    }


# ----- acts while the table gathers or rests -----


def admit(storage: Storage, campaign_id: str) -> bool:
    """Whether the table lets an act or a pass in now: `OnABreak` on a break, `NotStarted` while it gathers, unless
    it is solo. True when the act starts the session (a solo table that gathers), for `started_by_act` once the act
    is in."""
    state = current(storage, campaign_id).state
    if state == "break":
        raise OnABreak()
    if state == "gathering":
        if not solo(storage, campaign_id):
            raise NotStarted()
        return True
    return False


def started_by_act(services: AppServices, campaign_id: str) -> None:
    """A solo table's first act started its session: the table plays."""
    _put(services, replace(current(services.storage, campaign_id), state="playing", since=_now(services)))


# ----- the host's transitions -----


def start_session(
    services: AppServices, campaign_id: str, seat: Seat, absent: dict[str, str]
) -> tuple[TableSession, Beat]:
    """The host or a co-host starts the session, with a choice for each absent PC (`absent`, character id to
    `in_character`, `hold_back` or `out`): the table plays, and a beat runs at once in which the DM opens the scene.
    `NotAllowed` for anyone else; `PlayError` for an unknown PC or choice; `SessionRefused` unless the table gathers
    with no beat open, `BeatRunning` while the DM answers."""
    _must_run_the_table(seat)
    ensure_installed(services, campaign_id)
    storage = services.storage
    names = _pc_names(storage, campaign_id)
    unknown = [cid for cid in absent if cid not in names]
    if unknown:
        raise PlayError(f"No such character in this campaign: {', '.join(unknown)}.")
    modes = [mode for mode in absent.values() if mode not in ABSENT_MODES]
    if modes:
        raise PlayError(
            f"Unknown choice '{modes[0]}' for an absent character.", f"Use one of {', '.join(ABSENT_MODES)}."
        )
    with storage.transaction():
        state = current(storage, campaign_id)
        if state.state != "gathering":
            raise SessionRefused("The session has already started.", "End it first.")
        _no_beat(storage, campaign_id)
        playing = replace(state, state="playing", since=_now(services), absent=dict(absent), break_at=None)
        storage.table_sessions.put(playing)
        beat = _session_beat(
            services, campaign_id, seat, start_line({names[cid]: mode for cid, mode in absent.items()})
        )
    _changed(services, campaign_id)
    start_beat(services, beat)
    return playing, beat


def take_break(services: AppServices, campaign_id: str, seat: Seat) -> TableSession:
    """The host or a co-host takes a break: acts, passes and go wait, and an open beat's timer stops. A running beat
    finishes. `SessionRefused` unless the table plays."""
    _must_run_the_table(seat)
    state = current(services.storage, campaign_id)
    if state.state != "playing":
        raise SessionRefused("The table isn't playing.", "Take a break during the session.")
    now = _now(services)
    resting = _put(services, replace(state, state="break", since=now, break_at=now))
    timer = services.timers.pop(campaign_id, None)
    if timer is not None:
        timer.cancel()
    return resting


def back_to_story(services: AppServices, campaign_id: str, seat: Seat) -> TableSession:
    """The host or a co-host ends the break: the table plays, and an open beat's opening, and so its deadline, moves
    on by the length of the break, its timer running again. `SessionRefused` unless the table is on a break."""
    from delve.play import beats  # beats imports this module

    _must_run_the_table(seat)
    storage = services.storage
    state = current(storage, campaign_id)
    if state.state != "break":
        raise SessionRefused("The table isn't on a break.")
    now = services.clock.now()
    rested = now - datetime.fromisoformat(state.break_at) if state.break_at else None
    with storage.transaction():
        beat = storage.beats.current(campaign_id)
        if beat is not None and beat.status == "open" and rested is not None and rested.total_seconds() > 0:
            opened = datetime.fromisoformat(beat.opened_at) + rested
            storage.beats.save(replace(beat, opened_at=opened.isoformat()))
        playing = replace(state, state="playing", since=now.isoformat(), break_at=None)
        storage.table_sessions.put(playing)
    _changed(services, campaign_id)
    beats.timer_changed(services, campaign_id)
    return playing


def end_session(services: AppServices, campaign_id: str, seat: Seat) -> tuple[TableSession, Beat]:
    """The host or a co-host ends the session: the table gathers at once, its absent choices and hands cleared, and a
    beat runs in which the DM brings the scene to a pause and makes the recap. `SessionRefused` while the table
    gathers or a beat is open, `BeatRunning` while the DM answers."""
    _must_run_the_table(seat)
    ensure_installed(services, campaign_id)
    storage = services.storage
    with storage.transaction():
        state = current(storage, campaign_id)
        if state.state == "gathering":
            raise SessionRefused("The session hasn't started.")
        _no_beat(storage, campaign_id)
        gathered = _gathered(services, state)
        storage.table_sessions.put(gathered)
        beat = _session_beat(services, campaign_id, seat, end_line())
    _changed(services, campaign_id)
    start_beat(services, beat)
    return gathered, beat


def session_ended(services: AppServices, campaign_id: str) -> None:
    """The DM's `end_session` made the recap: the table gathers, unless it already does."""
    state = current(services.storage, campaign_id)
    if state.state != "gathering":
        _put(services, _gathered(services, state))


# ----- the raised hands -----


def raise_hand(services: AppServices, campaign_id: str, seat: Seat, point: str | None) -> TableSession:
    """The seat raises its hand, with a point of at most `POINT_CHARS` characters (`PlayError` past them); raising it
    again replaces the point and keeps when it was raised."""
    point = (point or "").strip() or None
    if point is not None and len(point) > POINT_CHARS:
        raise PlayError(f"A point is at most {POINT_CHARS} characters.", "Say the rest at the table.")
    storage = services.storage
    with storage.transaction():
        state = current(storage, campaign_id)
        at = (state.hands.get(seat.id) or {}).get("at") or _now(services)
        raised = replace(state, hands={**state.hands, seat.id: {"at": at, "point": point}})
        storage.table_sessions.put(raised)
    _changed(services, campaign_id)
    return raised


def lower_hand(services: AppServices, campaign_id: str, seat: Seat, seat_id: str) -> TableSession:
    """Lower `seat_id`'s hand: the seat's own, or anyone's for the host and co-hosts (`NotAllowed` otherwise). A hand
    that isn't up stays down, and nothing is told."""
    if seat_id != seat.id and seat.role not in TABLE_RIGHTS:
        raise NotAllowed("Only the host lowers another's hand.")
    storage = services.storage
    with storage.transaction():
        state = current(storage, campaign_id)
        if seat_id not in state.hands:
            return state
        lowered = replace(state, hands={k: v for k, v in state.hands.items() if k != seat_id})
        storage.table_sessions.put(lowered)
    _changed(services, campaign_id)
    return lowered


# ----- away mid-session (DEL-224) -----


def step_away(
    services: AppServices, campaign_id: str, seat: Seat, seat_id: str, part: str | None = None
) -> TableSession:
    """`seat_id` steps away: the seat's own, or any seat's for the host and co-hosts (`NotAllowed` otherwise), with
    the part its PCs take meanwhile (`ABSENT_MODES`, or None for the table's fallback; `PlayError` for another).
    Beats stop waiting for it, so an open beat that waited only for it closes. Stepping away again changes the part
    and keeps when it began. `SessionRefused` unless the session is under way; `PlayError` for a seat that isn't at
    the table or doesn't play."""
    from delve.play import beats  # beats imports this module

    if seat_id != seat.id:
        _must_run_the_table(seat)
    if part is not None and part not in ABSENT_MODES:
        raise PlayError(f"Unknown part '{part}'.", f"Use one of {', '.join(ABSENT_MODES)}, or none.")
    storage = services.storage
    away_seat = storage.seats.get(seat_id)
    if away_seat is None or away_seat.campaign_id != campaign_id or away_seat.left_at is not None:
        raise PlayError("No such seat at this table.")
    if away_seat.role == "observer":
        raise PlayError("An observer doesn't play, so isn't waited for.")
    with storage.transaction():
        state = current(storage, campaign_id)
        if state.state == "gathering":
            raise SessionRefused("The session hasn't started.", "Step away once the table plays.")
        at = (state.away.get(seat_id) or {}).get("at") or _now(services)
        stepped = replace(state, away={**state.away, seat_id: {"at": at, "part": part}})
        storage.table_sessions.put(stepped)
    _changed(services, campaign_id)
    beats.recheck(services, campaign_id)
    return stepped


def come_back(services: AppServices, campaign_id: str, seat: Seat, seat_id: str) -> TableSession:
    """`seat_id` is back: the seat's own, or any seat's for the host and co-hosts (`NotAllowed` otherwise). Beats
    wait for it again from the next. A seat that isn't away stays as it is, and nothing is told."""
    if seat_id != seat.id:
        _must_run_the_table(seat)
    storage = services.storage
    with storage.transaction():
        state = current(storage, campaign_id)
        if seat_id not in state.away:
            return state
        back = replace(state, away={k: v for k, v in state.away.items() if k != seat_id})
        storage.table_sessions.put(back)
    _changed(services, campaign_id)
    return back


def back_on_act(services: AppServices, campaign_id: str, seat: Seat) -> None:
    """A seat that acts or passes is back, if it was away."""
    if seat.id in current(services.storage, campaign_id).away:
        come_back(services, campaign_id, seat, seat.id)


def set_part(services: AppServices, campaign_id: str, seat: Seat, character_id: str, part: str | None) -> TableSession:
    """The host or a co-host sets the part a PC takes in the beats its player doesn't act in, for the rest of the
    session (`ABSENT_MODES`), or None to leave it to its player again (their own part when away, else the table's
    fallback). `NotAllowed` for anyone else; `PlayError` for an unknown PC or part; `SessionRefused` unless the
    session is under way. Who a beat waits for doesn't change."""
    _must_run_the_table(seat)
    storage = services.storage
    if character_id not in _pc_names(storage, campaign_id):
        raise PlayError(f"No such character in this campaign: {character_id}.")
    if part is not None and part not in ABSENT_MODES:
        raise PlayError(f"Unknown part '{part}'.", f"Use one of {', '.join(ABSENT_MODES)}, or none.")
    with storage.transaction():
        state = current(storage, campaign_id)
        if state.state == "gathering":
            raise SessionRefused("The session hasn't started.", "Choose at the start of the session.")
        absent = {k: v for k, v in state.absent.items() if k != character_id}
        if part is not None:
            absent[character_id] = part
        changed = replace(state, absent=absent)
        storage.table_sessions.put(changed)
    _changed(services, campaign_id)
    return changed


# ----- the DM's lines -----


def start_line(absent: dict[str, str]) -> str:
    """The session submission's line that starts a session: one line of Delve's, in square brackets, telling the DM
    to open the scene and, for the absent PCs by name, which the DM plays, which stay in the background and which sit
    the session out. Each name is made one line (DEL-154)."""
    by_mode: dict[str, list[str]] = {}
    for name, mode in absent.items():
        by_mode.setdefault(mode, []).append(one_line(name))
    parts = ["[Not from a player: the host starts this session of play. Open the scene for the party."]
    if who := by_mode.get("in_character"):
        parts.append(
            f"Nobody plays {_names(who)} yet: play them yourself, cautiously, until their player arrives (keep watch "
            "or follow the party; spend no spell or charge, and start no fight)."
        )
    if who := by_mode.get("hold_back"):
        parts.append(f"{_names(who)} {_be(who)} in the background this session, doing nothing.")
    if who := by_mode.get("out"):
        parts.append(f"{_names(who)} {_be(who)} not with the party this session: keep them out of the scene.")
    return " ".join(parts) + "]"


def end_line() -> str:
    """The session submission's line that ends a session: bring the scene to a pause and make the recap."""
    return (
        "[Not from a player: the host ends this session of play. Bring the scene to a pause in a few lines, then "
        "call end_session(recap) with the session's recap.]"
    )


def _names(names: list[str]) -> str:
    return ", ".join(names)


def _be(names: list[str]) -> str:
    return "is" if len(names) == 1 else "are"


# ----- helpers -----


def _session_beat(services: AppServices, campaign_id: str, seat: Seat, line: str) -> Beat:
    """A running beat of one `session` submission, within a transaction: no fallbacks, no acts in the story."""
    submission = {
        "seat_id": seat.id,
        "kind": "session",
        "characters": [],
        "text": line,
        "original": "",
        "language": "en",
        "at": _now(services),
    }
    try:
        return services.storage.beats.open(campaign_id, [submission], status="running")
    except ValueError:
        raise BeatRunning(services.storage.beats.current(campaign_id)) from None


def _no_beat(storage: Storage, campaign_id: str) -> None:
    beat = storage.beats.current(campaign_id)
    if beat is not None and beat.status == "running":
        raise BeatRunning(beat)
    if beat is not None:
        raise SessionRefused("A beat is open.", "Say go, or wait for it to close.")


def _gathered(services: AppServices, state: TableSession) -> TableSession:
    return replace(state, state="gathering", since=_now(services), absent={}, hands={}, break_at=None, away={})


def _pc_names(storage: Storage, campaign_id: str) -> dict[str, str]:
    return {c.id: c.name for c in storage.characters.list(campaign_id) if c.kind == "pc"}


def _must_run_the_table(seat: Seat) -> None:
    if seat.role not in TABLE_RIGHTS:
        raise NotAllowed(ONLY_THE_HOST)


def _now(services: AppServices) -> str:
    return services.clock.now().isoformat()


def _put(services: AppServices, state: TableSession) -> TableSession:
    services.storage.table_sessions.put(state)
    _changed(services, state.campaign_id)
    return state


def _changed(services: AppServices, campaign_id: str) -> None:
    """Publish the `table` event: the table's session state as the play state shows it."""
    data = {"campaign_id": campaign_id, "table": table_json(services.storage, campaign_id)}
    services.publish("table", data, scope="table", campaign_id=campaign_id)
