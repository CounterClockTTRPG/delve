"""Beats for a table (plan 4 Task 4, spec §7.1): submissions, the closing rules, the beat timer and the fallback.

A beat is `open` from its first submission. Each seat submits once, an act or a pass, for its own characters (the host
for any); a second submission from a seat replaces its first. The beat closes, and becomes `running` while the DM
answers, at the first of:
- every present seat that plays a character has submitted (`waiting_for` is empty). A seat is present while its
  browser listens to the event stream, or did in the last 30 s, and a seat that submitted counts as present. So with
  one seat present, a submission closes the beat at once: solo play waits for nothing;
- the host or a co-host says go (`go`);
- the beat timer runs out (play settings' `beat_timer_s`): its deadline is `opened_at` plus the timer.
At closing, the PCs no submission covered, of the seats that didn't submit and those nobody plays, get a `fallback`
submission with the host's chosen fallback, hold back or in character. The acts become the story's `player_act`
entries, and the DM gets every submission at once (`delve.play.table.dm_message`).

While the beat is open, each seat sees the others' acts so far (`pending`), marked draft, and its own. A private act
(plan 7 Task 17) is for the DM alone: no other seat sees it pending, its `player_act` entry is for its own seat, and
the DM is asked to answer it through `tell`. An observer sees no pending act at all.

The host plays every PC nobody has claimed (the party's decision for plateau 4): by default the host's submission
covers them too, and the host holds a beat up while there are such PCs.

A PC that left the party (`delve.play.departures`) counts for none of it: a submission doesn't cover it by default, it
holds no beat up, and it gets no fallback line.

A Delve that starts with an open beat closes it at once with the submissions it has, unless its timer still runs
(`resume`).

The table's session state (`delve.play.table_session`, DEL-199) has its say: while the table gathers, acts and passes
are refused, except at a solo table, whose first act starts the session; on a break, acts, passes and go are refused,
and nothing closes an open beat, neither its timer nor the seats going. A PC the host chose a part for at the session's
start, absent, gets that part as its fallback, and one `out` of the session no line at all. The beats that start and
end a session have one `session` submission, Delve's line, and no fallbacks.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import replace
from typing import Any, Literal

from delve.domain.campaigns import Beat, Character, MissingPack, Seat, StoryEntry
from delve.play import hotseat, table_session, translate
from delve.play.audience import for_seats, seat_controls
from delve.play.context import PlayError, missing_pack
from delve.play.seats import OBSERVERS, TABLE_RIGHTS, NotAllowed
from delve.play.table import (
    AppServices,
    BeatRunning,
    beat_changed,
    deadline,
    ensure_installed,
    play_settings,
    start_beat,
)

log = logging.getLogger(__name__)

__all__ = [
    "NoOpenBeat",
    "SubmissionKind",
    "go",
    "pending",
    "recheck",
    "resume",
    "stop_timers",
    "submit",
    "submit_in_english",
    "timer_changed",
    "waiting_for",
]

SubmissionKind = Literal["act", "pass", "fallback", "session"]
NO_OPEN_BEAT = "There is no open beat."
PRIVATE_PASS = "A pass can't be private."


class NoOpenBeat(PlayError):
    """Go, with no beat open (409)."""

    def __init__(self) -> None:
        super().__init__(NO_OPEN_BEAT, "A beat opens with the first act or pass.")


def submit(
    services: AppServices,
    campaign_id: str,
    seat: Seat,
    kind: Literal["act", "pass"],
    text: str = "",
    characters: list[str] | None = None,
    *,
    original: str | None = None,
    untranslated: bool = False,
    private: bool = False,
    player: str | None = None,
) -> Beat:
    """The seat acts or passes in the campaign's beat, which opens with it when none is open. Answers the beat, which
    is `running` when this submission closed it.

    `text` is in English, and `original` the seat's own words (the same when not given); `untranslated` marks words
    whose translation into English failed (`submit_in_english`). `characters` defaults to the seat's own and must be
    among them, except for the host and co-hosts (`PlayError`, 422). A `private` act is for the DM alone; a pass can't
    be private (`PlayError`). An observer gets `NotAllowed`; a beat the DM is answering `BeatRunning`; a table that
    gathers `table_session.NotStarted`, unless it is solo (its act starts the session), and one on a break
    `table_session.OnABreak`.

    `player` is a hotseat player at the host's screen (DEL-365, `delve.play.hotseat`): the submission is theirs, for
    their characters by default, and replaces only their own earlier one. It can't be private (`PlayError`)."""
    storage = services.storage
    ensure_installed(services, campaign_id)
    if seat.role == "observer":
        raise NotAllowed(OBSERVERS)
    if private and kind != "act":
        raise PlayError(PRIVATE_PASS, "Only an act can be for the DM alone.")
    playing = hotseat.player(storage, campaign_id, seat, player) if player is not None else None
    if playing is not None and private:
        raise PlayError(hotseat.PRIVATE, "Send it as an act for the table.")
    starts = table_session.admit(storage, campaign_id)
    table_session.back_on_act(services, campaign_id, seat)
    with storage.transaction():
        beat = storage.beats.current(campaign_id)
        if beat is not None and beat.status == "running":
            raise BeatRunning(beat)
        if playing is not None and characters is None:
            characters = list(playing["characters"])
        mine = _characters_for(storage, campaign_id, seat, characters)
        submission = {
            "seat_id": seat.id,
            "kind": kind,
            "characters": mine,
            "text": text if kind == "act" else "",
            "original": (text if original is None else original) if kind == "act" else "",
            "language": seat.language,
            "at": services.clock.now().isoformat(),
        }
        if private:
            submission["private"] = True
        if playing is not None:
            submission["hotseat"] = playing["id"]
            submission["player_name"] = playing["name"]
        if untranslated and kind == "act":
            submission["translation"] = "failed"
        key = _key(submission)
        others = [s for s in beat.submissions if _key(s) != key] if beat is not None else []
        submissions = [*others, submission]
        closing = not waiting_for(services, campaign_id, submissions)
        if beat is None:
            try:
                beat = storage.beats.open(campaign_id, submissions, status="running" if closing else "open")
            except ValueError:
                raise BeatRunning(storage.beats.current(campaign_id)) from None
            if closing:  # solo play: open and closed at once, as before plateau 4
                beat, entries = _closed(services, beat)
        else:
            beat = storage.beats.save(replace(beat, submissions=tuple(submissions)))
            if closing:
                beat, entries = _closed(services, beat)
    if closing:
        _started(services, beat, entries)
    else:
        beat_changed(services, beat)
        _arm(services, beat)
    if starts:
        table_session.started_by_act(services, campaign_id)
    return beat


async def submit_in_english(
    services: AppServices,
    campaign_id: str,
    seat: Seat,
    kind: Literal["act", "pass"],
    text: str = "",
    characters: list[str] | None = None,
    *,
    private: bool = False,
    player: str | None = None,
) -> Beat:
    """`submit`, with an act's words put into English first (`translate.to_english`), keeping the original. A failed
    translation joins the beat as it is, marked: it never holds the beat up. English words go straight in."""
    ensure_installed(services, campaign_id)
    if kind != "act" or translate.is_english(seat.language):
        return submit(services, campaign_id, seat, kind, text, characters, private=private, player=player)
    if seat.role == "observer":
        raise NotAllowed(OBSERVERS)
    table_session.admit(services.storage, campaign_id)
    beat = services.storage.beats.current(campaign_id)
    if beat is not None and beat.status == "running":
        raise BeatRunning(beat)
    if player is not None:
        hotseat.player(services.storage, campaign_id, seat, player)  # refused before anything reaches Claude
    english = await translate.to_english(services, campaign_id, text, seat.language)
    return submit(
        services, campaign_id, seat, kind, english.text, characters,
        original=text, untranslated=english.failed, private=private, player=player,
    )


def go(services: AppServices, campaign_id: str, seat: Seat) -> Beat:
    """The host or a co-host closes the open beat with the submissions it has. `NotAllowed` for anyone else,
    `NoOpenBeat` without an open beat, `BeatRunning` while the DM answers, `table_session.OnABreak` on a break."""
    if seat.role not in TABLE_RIGHTS:
        raise NotAllowed("Only the host can do that.")
    ensure_installed(services, campaign_id)
    if table_session.on_break(services.storage, campaign_id):
        raise table_session.OnABreak()
    beat = services.storage.beats.current(campaign_id)
    if beat is not None and beat.status == "running":
        raise BeatRunning(beat)
    closed = _close(services, campaign_id, beat.id) if beat is not None else None
    if closed is None:
        raise NoOpenBeat()
    return closed


def recheck(services: AppServices, campaign_id: str) -> Beat | None:
    """Close the campaign's open beat when it no longer waits for anyone: a seat went away or left, or no longer
    plays a character. Call it when the seats or their presence change. The beat when it closed, else None; always
    None on a break."""
    beat = services.storage.beats.current(campaign_id)
    if beat is None or beat.status != "open" or table_session.on_break(services.storage, campaign_id):
        return None
    if waiting_for(services, campaign_id, list(beat.submissions)):
        return None
    return _close(services, campaign_id, beat.id)


def resume(services: AppServices) -> None:
    """At the start of Delve: an open beat whose timer still runs gets its timer again; any other open beat closes
    at once, with the submissions it has. One on a break waits for the table to be back to the story, and one of a
    campaign whose pack isn't installed stays open."""
    storage = services.storage
    for campaign in storage.campaigns.list():
        if (missing := missing_pack(services.catalogs, campaign)) is not None:
            log.warning("campaign %s left as it is: %s", campaign.id, missing.message)
            continue
        beat = storage.beats.current(campaign.id)
        if beat is None or beat.status != "open" or table_session.on_break(storage, campaign.id):
            continue
        until = deadline(storage, beat)
        if until is not None and services.clock.now() < until:
            _arm(services, beat)
        else:
            _close(services, campaign.id, beat.id)


def pending(storage, campaign_id: str, seat: Seat) -> list[dict[str, Any]]:
    """The open beat's submissions as `seat` may see them, before the beat closes: its own first, then the others'
    that aren't private, as `{seat_id, name, kind, text, characters, private, at, hotseat}`. `text` is the act's own
    words for a seat of its language, else the English. A hotseat player's (DEL-365) has the player's id as `hotseat`
    and their name as `name`; any other's `hotseat` is None. An observer sees none, nor does anyone once the beat has
    closed."""
    beat = storage.beats.current(campaign_id)
    if seat.role == "observer" or beat is None or beat.status != "open":
        return []
    names = {s.id: s.name for s in storage.seats.list(campaign_id)}
    mine = [s for s in beat.submissions if s.get("seat_id") == seat.id]
    theirs = [s for s in beat.submissions if s.get("seat_id") != seat.id and not s.get("private")]
    return [
        {
            "seat_id": s.get("seat_id"),
            "name": s.get("player_name") if s.get("hotseat") else names.get(s.get("seat_id"), ""),
            "hotseat": s.get("hotseat"),
            "kind": s.get("kind"),
            "text": (s.get("original") or s.get("text", "")) if s.get("language") == seat.language else s.get("text", ""),
            "characters": list(s.get("characters") or []),
            "private": bool(s.get("private")),
            "at": s.get("at", ""),
        }
        for s in [*mine, *theirs]
        if s.get("kind") in ("act", "pass")
    ]


def stop_timers(services: AppServices) -> list[asyncio.Task]:
    """Cancel the beat timers (when Delve stops); the cancelled tasks, to await."""
    tasks = list(services.timers.values())
    services.timers.clear()
    for task in tasks:
        task.cancel()
    return tasks


def waiting_for(services: AppServices, campaign_id: str, submissions: list[dict[str, Any]]) -> set[str]:
    """The seats the beat still waits for: present, not away (DEL-224), not observers, playing a character, and
    without a submission. A seat that submitted counts as present. The host's seat with hotseat players (DEL-365)
    has submitted once each of them has, and, when it plays characters none of them does, it has for itself too."""
    storage = services.storage
    done = {s.get("seat_id") for s in submissions if s.get("kind") in ("act", "pass")}
    unfinished = _hotseat_unfinished(storage, campaign_id, submissions)
    away = set(table_session.current(storage, campaign_id).away)
    here = (services.present(campaign_id) - away) | done
    return {
        seat.id
        for seat in storage.seats.list(campaign_id)
        if seat.id in here
        and (seat.id not in done or seat.id in unfinished)
        and seat.left_at is None
        and seat.role != "observer"
        and _in_party(storage, campaign_id, seat_controls(storage, seat))
    }


def _key(submission: dict[str, Any]) -> hotseat.SubmissionKey:
    return (submission.get("seat_id"), submission.get("hotseat"))


def _hotseat_unfinished(storage, campaign_id: str, submissions: list[dict[str, Any]]) -> set[str]:
    """The host's seat, while one of its hotseat players hasn't acted or passed, or (with characters of its own
    besides theirs) it hasn't for itself; else nothing."""
    players = hotseat.players(storage, campaign_id)
    host = hotseat.host_seat(storage, campaign_id) if players else None
    if host is None:
        return set()
    keys = {_key(s) for s in submissions if s.get("kind") in ("act", "pass")}
    if any((host.id, p["id"]) not in keys for p in players):
        return {host.id}
    theirs = {cid for p in players for cid in p["characters"]}
    own = _in_party(storage, campaign_id, seat_controls(storage, host) - theirs)
    pcs = {c.id for c in storage.characters.list(campaign_id) if c.kind == "pc"}
    if own & pcs and (host.id, None) not in keys:
        return {host.id}
    return set()


def _in_party(storage, campaign_id: str, ids: set[str]) -> set[str]:
    """`ids` without the PCs that left the party."""
    if not ids:
        return ids
    return {c.id for c in storage.characters.list(campaign_id) if c.id in ids and c.departure is None}


# ----- closing -----


def _characters_for(storage, campaign_id: str, seat: Seat, characters: list[str] | None) -> list[str]:
    """The characters a submission is for: the seat's own by default; given, they must be its own, or the table's
    for the host and co-hosts."""
    known = storage.characters.list(campaign_id)
    own = seat_controls(storage, seat)
    if characters is None:
        mine = [c.id for c in known if c.id in own and c.departure is None]
        return hotseat.rest(storage, campaign_id, seat, mine)
    ids = {c.id for c in known}
    unknown = [ref for ref in characters if ref not in ids]
    if unknown:
        raise PlayError(f"No such character in this campaign: {', '.join(unknown)}.")
    if seat.role not in TABLE_RIGHTS:
        names = {c.id: c.name for c in known}
        others = [names[ref] for ref in characters if ref not in own]
        if others:
            raise PlayError(f"You don't play {', '.join(others)}.", "Act for your own characters.")
    return list(dict.fromkeys(characters))


def _close(services: AppServices, campaign_id: str, beat_id: str) -> Beat | None:
    """Close the open beat `beat_id` and let the DM answer it; None when it is no longer open, the table is on a
    break, or the campaign's ruleset or setting isn't installed."""
    storage = services.storage
    with storage.transaction():
        beat = storage.beats.current(campaign_id)
        if beat is None or beat.id != beat_id or beat.status != "open":
            return None
        if table_session.on_break(storage, campaign_id):
            return None
        try:
            ensure_installed(services, campaign_id)
        except MissingPack:
            return None  # the beat stays open, as it was, until its pack is installed
        closed, entries = _closed(services, beat)
    _started(services, closed, entries)
    return closed


def _closed(services: AppServices, beat: Beat) -> tuple[Beat, list[StoryEntry]]:
    """The beat, running, with its fallbacks, and the `player_act` entries of its acts, a private one for its seat
    alone; within a transaction."""
    storage = services.storage
    seat_names = {s.id: s.name for s in storage.seats.list(beat.campaign_id)}
    submissions = [*beat.submissions, *_fallbacks(services, beat)]
    running = storage.beats.save(replace(beat, status="running", submissions=tuple(submissions)))
    entries = [
        storage.story.append(
            beat.campaign_id,
            beat.id,
            "player_act",
            {**s, "name": s.get("player_name") if s.get("hotseat") else seat_names.get(s["seat_id"], "")},
            for_seats([s["seat_id"]]) if s.get("private") else None,
        )
        for s in beat.submissions
        if s.get("kind") == "act"
    ]
    return running, entries


def _fallbacks(services: AppServices, beat: Beat) -> list[dict[str, Any]]:
    """A `fallback` submission for each seat that didn't submit, and one for the PCs nobody plays, with the PCs of
    theirs that no submission covered: one for each part they take, the host's choice for an absent PC, else the part
    its away seat chose (`table_session`), else the play settings' fallback; none for a PC out of the session. A beat
    that starts or ends a session has none. A hotseat player who didn't submit (DEL-365) is as a seat that didn't:
    their PCs get a fallback of theirs, though the host's seat submitted for the others."""
    storage = services.storage
    if any(s.get("kind") == "session" for s in beat.submissions):
        return []
    covered = {cid for s in beat.submissions for cid in s.get("characters") or []}
    done = {s.get("seat_id") for s in beat.submissions if not s.get("hotseat")}
    players_done = {s.get("hotseat") for s in beat.submissions if s.get("hotseat")}
    player_of = {cid: p for p in hotseat.players(storage, beat.campaign_id) for cid in p["characters"]}
    fallback = play_settings(storage, beat.campaign_id)["fallback"]
    state = table_session.current(storage, beat.campaign_id)
    absent, away = state.absent, state.away
    host = hotseat.host_seat(storage, beat.campaign_id) if player_of else None
    left: dict[tuple[str | None, str | None, str], list[Character]] = {}
    for character in storage.characters.list(beat.campaign_id):
        if character.kind != "pc" or character.departure is not None or character.id in covered:
            continue
        playing = player_of.get(character.id)
        if playing is not None and playing["id"] in players_done:
            continue  # its hotseat player submitted, for other characters
        if playing is None and character.controller_id is not None and character.controller_id in done:
            continue  # its player submitted, for other characters
        seat_id = host.id if playing is not None and host is not None else character.controller_id
        own = (away.get(character.controller_id or "") or {}).get("part")
        mode = absent.get(character.id) or own or fallback
        if mode != "out":
            left.setdefault((seat_id, playing["id"] if playing else None, mode), []).append(character)
    at = services.clock.now().isoformat()
    return [
        {
            "seat_id": seat_id,
            "kind": "fallback",
            "characters": [c.id for c in pcs],
            "text": _fallback_line(mode, [c.name for c in pcs]),
            "original": "",
            "language": "en",
            "at": at,
            **({"hotseat": player_id} if player_id else {}),
        }
        for (seat_id, player_id, mode), pcs in left.items()
    ]


def _fallback_line(mode: str, names: list[str]) -> str:
    """The fallback's line of the DM's message: one line of Delve's, so a character's name, a player's words, is made
    one line too (DEL-154, audit finding 15)."""
    who = ", ".join(" ".join(name.split()) for name in names)
    if mode == "in_character":
        return (
            f"(Nobody is playing {who} this beat: play a cautious action for them — keep watch or follow the party; "
            "spend no spell or charge, and start no fight.)"
        )
    return f"({who} {'holds' if len(names) == 1 else 'hold'} back this beat: they do nothing.)"


def _started(services: AppServices, beat: Beat, entries: list[StoryEntry]) -> None:
    timer = services.timers.pop(beat.campaign_id, None)
    if timer is not None and timer is not asyncio.current_task():
        timer.cancel()
    start_beat(services, beat, entries)


# ----- the beat timer -----


def _arm(services: AppServices, beat: Beat) -> None:
    """(Re)start the open beat's timer from the play settings: none without a beat timer."""
    old = services.timers.pop(beat.campaign_id, None)
    if old is not None:
        old.cancel()
    until = deadline(services.storage, beat)
    if until is not None:
        services.timers[beat.campaign_id] = asyncio.create_task(_timer(services, beat.campaign_id, beat.id))


async def _timer(services: AppServices, campaign_id: str, beat_id: str) -> None:
    """Wait for the beat's deadline, then close it, whoever is at the table. The deadline is read again after each
    wait, since the host may change the timer."""
    clock = services.clock
    while True:
        beat = services.storage.beats.get(beat_id)
        until = deadline(services.storage, beat) if beat is not None else None
        if until is None:
            return
        left = (until - clock.now()).total_seconds()
        if left <= 0:
            break
        await clock.sleep(min(left, 1.0))
    if services.timers.get(campaign_id) is asyncio.current_task():
        del services.timers[campaign_id]
    # A closing that fails leaves the beat to `go`, or to the next start; the failure is logged, as nobody awaits
    # this task to see it.
    try:
        _close(services, campaign_id, beat_id)
    except Exception:
        log.exception("The beat timer couldn't close beat %s of campaign %s", beat_id, campaign_id)


def timer_changed(services: AppServices, campaign_id: str) -> None:
    """The host changed the beat timer, or the table is back to the story: the open beat's timer starts again from
    its `opened_at`. On a break it waits for the table to be back."""
    beat = services.storage.beats.current(campaign_id)
    if beat is not None and beat.status == "open" and not table_session.on_break(services.storage, campaign_id):
        until = deadline(services.storage, beat)
        if until is not None and services.clock.now() >= until:
            _close(services, campaign_id, beat.id)
        else:
            _arm(services, beat)
            beat_changed(services, beat)
