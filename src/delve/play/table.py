"""The table: beats, the story, the DM log and the players' feed (spec §7.1, §7.5).

A beat opens with the players' submissions (`delve.play.beats`), and closes when everyone present has submitted, the
host says go, or the beat timer runs out. With one player, submitting closes it at once. The beat is `running` while
the DM answers, and `close_beat` ends it as `done`, `failed` or `cancelled`. A campaign has one beat open or running at
a time; a submission while the DM answers is refused with `BeatRunning`.

The story is what the players see, entry by entry. It is built only through `feed_entry_for`, from the DM's events:
the text of one reply becomes one `dm_text`, a tool call and its result one `tool` row through `player_view` (the
tool's name, and whether it was refused: spec §7.5's allow-list), and a DM-only tool nothing at all. The DM's raw stream never enters the story; it goes to the DM log, which only the DM view reads.

Entries follow a tool row: `end_session`'s `recap`; `show_image`'s `image`, `{asset, caption}`, one of the two tool
outputs `player_view` lets past, made only when the campaign's pinned revision holds that image for the players; and
`tell`'s `dm_text`, the other, for the campaign's PCs it names only (their ids are its `told_to`). A tell's row has the
same audience, and a refused tell makes none: the other seats don't learn that something was told. `say`'s `say`
entry is an NPC's line for everyone: `{speaker: {id, name, portrait}, mood, text}`, rebuilt from the campaign's own
NPC, so a forged result names no other character and carries nothing else of its sheet. An entry for some
characters is stored for the seats that play them as it is stored (`audience.resolve`): a PC claimed or released
later doesn't show its past tells to its new seat.

A reply's paragraph that starts `(ooc, for the host:` (dm.md's note for a host who plays no character) is the host's
alone: it is held back while it streams, so no part of it reaches the table, and stored at the reply's end as a
`dm_text` of its own for the host's seat. Only a paragraph that may still become such a note is held back; the rest
of the reply streams as it comes.

A reply that only tells again what an earlier reply of the beat told (the model repeating itself across a tool call,
D3) is told once: its text, with whitespace collapsed, equal to an earlier reply's, is dropped and logged. While a reply
is still the start of an earlier one it is held back; once it says something else, it shows. A beat's first reply
always streams at once.

A beat that failed for a reason that may pass (`DMError.retryable`: the usage limit, a crash, a restart mid-beat) can
be retried (table voice and fixes Task D1): its `dm_error` says `retryable` and, for the usage limit, `resets_at`.
`retry_beat` plays the same beat row again, with the same acts, while it is the campaign's latest and no beat is open
or running. Nothing of the first attempt is undone or applied twice: its rolls keep their keys, so the dice already
rolled come back (the no-re-roll rule), and the DM's message starts with `RETRY_NOTE`, the mutating tool calls the
DM log holds for the beat, applied and not to be made again. The error entry is marked `retried`, so one failure is
retried once; a second press finds the beat running (`BeatRunning`).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any

from delve.dm.fake import event_from_dict, event_to_dict
from delve.dm.prompt import DEFAULT_DETAIL, DEFAULT_XP_AWARDS, DETAIL_LEVELS, TONES, XP_AWARDS, build_system_prompt
from delve.dm.provider import (
    ConversationSpec,
    DMConversation,
    DMError,
    DMEvent,
    DMProvider,
    TextDelta,
    ToolCall,
    ToolResult,
    TurnEnd,
)
from delve.dm.tools.composites import BATCH
from delve.dm.tools.redact import SAY, SHOW_IMAGE, TELL, player_view
from delve.dm.tools.rolled import ROLLED, CallDice
from delve.dm.tools.say import handed_to_dm, said_line
from delve.dm.tools.schema import ToolSpec
from delve.domain import new_id
from delve.domain.campaigns import BEAT_ENDS, Beat, BeatStatus, DmLogEntry, Seat, SeatRole, StoryEntry, StoryKind
from delve.domain.settings import BackendChoice, Effort, Job
from delve.modules.source import pinned_source
from delve.packs.catalogs import IN_TREE, Catalogs
from delve.play import hotseat, house_rules, timeline, translate
from delve.play.audience import (
    TOOL_ROWS,
    Audience,
    can_see,
    for_characters,
    for_seats,
    resolve,
    roles_for,
    seat_controls,
)
from delve.play.clock import Clock, SystemClock
from delve.play.context import PlayError, always_paid, context_for, missing_pack
from delve.play.portraits import PORTRAIT_STYLES
from delve.play.seats import TABLE_RIGHTS, NotAllowed
from delve.play.story_dice import ENEMY_DICE, SeatDice
from delve.storage.interfaces import Storage

__all__ = [
    "PAID_PER_DAY",
    "RETRY_NOTE",
    "AppServices",
    "Beat",
    "BeatRunning",
    "DmLogEntry",
    "NotRetryable",
    "PendingCalls",
    "StoryEntry",
    "add_entry",
    "beat_changed",
    "beat_json",
    "cancel_beat",
    "close_beat",
    "current_beat",
    "deadline",
    "dm_log",
    "dm_message",
    "ensure_installed",
    "feed",
    "feed_entry_for",
    "log_dm_event",
    "one_line",
    "open_beat",
    "play_settings",
    "quoted",
    "retry_beat",
    "retry_state",
    "run_beat",
    "running_beat",
    "seat_dice",
    "set_play_settings",
    "settle",
    "start_beat",
    "starts_session",
    "story",
    "told",
    "tools_counted",
    "wait_beat",
]

STILL_ANSWERING = "the DM is still answering"
SpecLookup = Callable[[str], ToolSpec | None]
FOR_THE_HOST = "(ooc, for the host:"
_PARAGRAPH_BREAK = re.compile(r"(\n[ \t]*\n)")
log = logging.getLogger(__name__)

STORE_EVERY = 1.0
"""How often, in seconds, the reply being written is stored while it streams (DEL-241): it is also stored when it
first shows and when it ends. A page that missed some of its words has them again with the next store's `story`."""
PUBLISH_EVERY = 0.1
"""How often, in seconds, the table is sent the reply's new words while it streams (DEL-241), those since together."""


class BeatRunning(PlayError):
    """The campaign already has a beat the DM is answering."""

    def __init__(self, beat: Beat) -> None:
        self.beat = beat
        super().__init__(STILL_ANSWERING, "Wait for the DM's answer, or cancel the beat.")


# ----- beats -----


def open_beat(storage: Storage, campaign_id: str, submission: dict[str, Any]) -> Beat:
    """Open a beat with the owner's `submission` (`{"player", "character_ids", "kind": "act", "text"}`), which closes
    it at once: it runs, and the act is the story's next `player_act`. `BeatRunning` while a beat runs."""
    with storage.transaction():
        running = storage.beats.current(campaign_id)
        if running is not None:
            raise BeatRunning(running)
        try:
            beat = storage.beats.open(campaign_id, [submission], status="running")
        except ValueError:
            raise BeatRunning(storage.beats.current(campaign_id)) from None
        storage.story.append(campaign_id, beat.id, "player_act", dict(submission))
    return beat


def close_beat(storage: Storage, beat_id: str, status: BeatStatus, clock: Clock | None = None) -> Beat:
    """End the beat as `done`, `failed` or `cancelled`, at the time of `clock` (the table's; the system's without
    one)."""
    if status not in BEAT_ENDS:
        raise ValueError(f"a beat ends as one of {', '.join(BEAT_ENDS)}, not {status!r}")
    beat = storage.beats.get(beat_id)
    if beat is None:
        raise KeyError(beat_id)
    closed_at = (clock or SystemClock()).now().isoformat()
    return storage.beats.save(replace(beat, status=status, closed_at=closed_at))


def current_beat(storage: Storage, campaign_id: str) -> Beat | None:
    """The beat that is open or running, if there is one."""
    return storage.beats.current(campaign_id)


# ----- the story -----


def story(
    storage: Storage,
    campaign_id: str,
    viewer_seat: Seat,
    before_seq: int | None = None,
    limit: int = 50,
    kind: StoryKind | None = None,
) -> dict[str, Any]:
    """`{"entries", "has_more"}`: the last `limit` entries before `before_seq` that `viewer_seat` may see, oldest
    first, and whether it may see earlier ones. Entries for others are left out, and the page counts only what the
    seat sees. With `kind`, only entries of that kind: the talk panel's own pages (DEL-219). A tool row is as the
    seat sees it, with the dice it may read (`story_dice`, DEL-270): never the ids its payload keeps."""
    controls = seat_controls(storage, viewer_seat)
    rows = seat_dice(storage, campaign_id, viewer_seat.role)
    seen: list[StoryEntry] = []
    before, batch = before_seq, max(limit + 1, 50)
    while len(seen) <= limit:
        page = storage.story.list(campaign_id, before_seq=before, limit=batch, kind=kind)
        shown = []
        for e in page:
            if not can_see(viewer_seat, e.audience, controls):
                continue
            if e.kind == "tool":
                row = rows.row(e.payload)
                if row is None:
                    continue
                e = replace(e, payload=row)
            shown.append(e)
        seen[:0] = shown
        if len(page) < batch:
            break
        before = page[0].seq
    return {"entries": seen[-limit:] if limit else [], "has_more": len(seen) > limit}


def seat_dice(storage: Storage, campaign_id: str, role: SeatRole) -> SeatDice:
    """How a seat of `role` sees the campaign's tool rows and their dice, with the table's `enemy_dice` and
    `show_dice` options."""
    settings = play_settings(storage, campaign_id)
    return SeatDice(storage, campaign_id, role, settings["enemy_dice"], show_dice=settings["show_dice"])


def add_entry(
    storage: Storage,
    campaign_id: str,
    beat_id: str | None,
    kind: StoryKind,
    payload: dict,
    audience: Audience = None,
) -> StoryEntry:
    """Append an entry to the story, for `audience` (None: everyone at the table; characters, the seats that play
    them now). Its payload must already be player-safe."""
    return storage.story.append(campaign_id, beat_id, kind, payload, resolve(storage, campaign_id, audience))


# ----- the DM log -----


def log_dm_event(storage: Storage, campaign_id: str, beat_id: str | None, raw_event_json: dict[str, Any]) -> None:
    """Keep one event of the DM's raw stream, for the DM view."""
    storage.dm_log.append(campaign_id, beat_id, raw_event_json)


def dm_log(storage: Storage, campaign_id: str, beat_id: str | None = None) -> list[DmLogEntry]:
    """The campaign's DM log, oldest first; one beat's with `beat_id`."""
    return storage.dm_log.list(campaign_id, beat_id)


# ----- the players' feed -----


@dataclass
class PendingCalls:
    """What the feed remembers within one beat of one campaign: the tool calls waiting for their result, the
    `dm_text` entry of the reply being written as it shows now (stored or not) and its whole text so far, the host's
    seat (for a note for the host),
    and the entries the end of the last reply made, which `feed` stores before the event's own. `told` is what the
    beat's replies have shown, with whitespace collapsed (`_collapsed`): kept for the beat, not reset per reply."""

    campaign_id: str
    beat_id: str | None
    calls: dict[str, ToolCall] = field(default_factory=dict)
    reply: StoryEntry | None = None
    host_seat: str | None = None
    text: str = ""
    ended: list[StoryEntry] = field(default_factory=list)
    told: set[str] = field(default_factory=set)
    logged: list[str] = field(default_factory=list)
    """The reply's text deltas not in the DM log yet, which keeps a reply as one row (`feed`, DEL-241)."""
    saved: tuple[str, str] | None = None
    """The id and the text of the reply as last stored, and when (`clock`): `feed` stores it at most every
    `store_every` seconds while it streams."""
    saved_at: float = 0.0
    store_every: float = field(default_factory=lambda: STORE_EVERY)
    clock: Callable[[], float] = time.monotonic
    dice: Callable[[str, dict[str, Any]], CallDice | None] | None = None
    """What a call `(name, args)` rolled, as the tool host put it (`rolled.ROLLED.take`, DEL-270): its row keeps the
    ids. None (a replay of the DM log, a test) keeps none."""


def feed_entry_for(event: DMEvent, spec_lookup: SpecLookup, pending_calls: PendingCalls) -> StoryEntry | None:
    """The story entry `event` makes, or None when it makes none (yet). Not stored: `seq` and `at` are set when it is.

    - A `TextDelta` extends the reply's `dm_text`: the same entry, with the same id, for every delta until a tool
      call, an error or the end of the reply. A note for the host is held back (`for_the_table`); None while the
      delta shows nothing new. Any other event ends the reply: its last words, and its notes for the host as one
      `dm_text` for the host's seat, go to `pending_calls.ended`.
    - A `ToolCall` waits for its `ToolResult`; together they make one `tool` entry, `{name, summary, result}`, with
      `player_view` shows it: `{name}`, or `{name, failed}` for a refusal. DM-only and unknown tools make none, nor
      does a call with `hidden: true`, a roll the players mustn't know failed.
    - A `DMError` is a `dm_error` with its message, whether it is `retryable` and its `resets_at`. Usage and the end
      of the reply make none.
    """
    if isinstance(event, TextDelta):
        pending_calls.text += event.text
        shown = for_the_table(pending_calls.text)[0]
        if pending_calls.reply is None and pending_calls.told and _may_repeat(pending_calls, shown):
            return None
        return _shown(pending_calls, shown)
    pending_calls.ended = _end_reply(pending_calls)
    if isinstance(event, ToolCall):
        pending_calls.calls[event.id] = event
        return None
    if isinstance(event, ToolResult):
        call = pending_calls.calls.pop(event.id, None)
        spec = spec_lookup(call.name) if call is not None else None
        if call is None or spec is None or not spec.player_visible or call.args.get("hidden") is True:
            return None
        # The call's id, so the host's look at the call finds it in the DM log (DEL-172); `player_row` drops it.
        payload = {**_tool_row(spec, call, event, spec_lookup), "call_id": event.id}
        if pending_calls.dice is not None:
            payload = _with_dice(payload, call.args, pending_calls.dice(call.name, call.args))
        row = _draft(pending_calls, "tool", payload)
        if spec.name == TELL:
            told = _told(spec, event)
            return replace(row, audience=for_characters(told["characters"])) if told is not None else None
        return row
    if isinstance(event, DMError):
        return _draft(pending_calls, "dm_error", _error(event.message, event.retryable, event.resets_at))
    return None


def _error(message: str, retryable: bool, resets_at: str | None = None) -> dict[str, Any]:
    """A `dm_error` payload: the message, whether the beat may be tried again, and when the usage limit ends."""
    return {"message": message, "retryable": retryable, "resets_at": resets_at}


def tool_call_of(storage: Storage, spec_lookup: SpecLookup, entry: StoryEntry) -> dict[str, Any] | None:
    """A `tool` entry's call and its reply, as the DM made them: `{name, args, ok, result}`, the host's to read (backlog
    Features 19). The DM log keeps every call and result of the entry's beat; a row holds its call's id (DEL-172),
    and a row stored before that is found by replaying the log through `feed_entry_for`, which made the beat's tool
    rows from it in this order. None for another kind of entry, or a row the log doesn't hold."""
    if entry.kind != "tool" or entry.beat_id is None:
        return None
    call_id = entry.payload.get("call_id")
    if isinstance(call_id, str):
        return _logged_call(storage, entry, call_id)
    rows = [e.id for e in storage.story.list(entry.campaign_id) if e.beat_id == entry.beat_id and e.kind == "tool"]
    pending = PendingCalls(entry.campaign_id, entry.beat_id)
    calls: dict[str, ToolCall] = {}
    made: list[tuple[ToolCall, ToolResult]] = []
    for logged in dm_log(storage, entry.campaign_id, entry.beat_id):
        try:
            event = event_from_dict(logged.raw_event_json)
        except (ValueError, TypeError):
            continue  # the runner's own notes, such as a provider that failed
        if isinstance(event, ToolCall):
            calls[event.id] = event
        drafted = feed_entry_for(event, spec_lookup, pending)
        if isinstance(event, ToolResult) and drafted is not None and drafted.kind == "tool" and event.id in calls:
            made.append((calls[event.id], event))
    if entry.id not in rows or rows.index(entry.id) >= len(made):
        return None
    call, result = made[rows.index(entry.id)]
    return {"name": call.name, "args": call.args, "ok": result.ok, "result": _content(result.content)}


def _logged_call(storage: Storage, entry: StoryEntry, call_id: str) -> dict[str, Any] | None:
    """The call `call_id` of the entry's beat and its result, from the DM log, without reading the story."""
    call: ToolCall | None = None
    result: ToolResult | None = None
    for logged in dm_log(storage, entry.campaign_id, entry.beat_id):
        if logged.raw_event_json.get("id") != call_id:
            continue
        try:
            event = event_from_dict(logged.raw_event_json)
        except (ValueError, TypeError):
            continue
        if isinstance(event, ToolCall):
            call = event
        elif isinstance(event, ToolResult):
            result = event
    if call is None or result is None:
        return None
    return {"name": call.name, "args": call.args, "ok": result.ok, "result": _content(result.content)}


def feed(
    storage: Storage,
    event: DMEvent,
    raw_event_json: dict[str, Any],
    spec_lookup: SpecLookup,
    pending_calls: PendingCalls,
) -> list[StoryEntry]:
    """Log one DM event in the DM log, and put the story entries it makes: those the end of a reply made, then its
    own; answers them as stored.

    A reply costs a few writes however many deltas it streams in (DEL-241, review P3): its deltas are one row of the
    DM log, `{type: text, text}` with their text joined, written before the event that ends the reply (or by
    `settle`); its `dm_text` is stored when it first shows, then at most every `store_every` seconds, and when it
    ends. In between, `pending_calls.reply` holds what it shows, and the runner sends the table only its new words
    (`_Streamed`). `raw_event_json` of a delta is not kept: the runner's is `event_to_dict(event)`, which the joined
    row is too."""
    pending = pending_calls
    if isinstance(event, TextDelta):
        pending.logged.append(event.text)
        entry = feed_entry_for(event, spec_lookup, pending)
        if entry is None:
            return []
        stored_lately = pending.clock() - pending.saved_at < pending.store_every
        if pending.saved is not None and pending.saved[0] == entry.id and stored_lately:
            return []
        return [_put(storage, pending, entry)]
    _log_text(storage, pending)
    log_dm_event(storage, pending.campaign_id, pending.beat_id, raw_event_json)
    unsaved = _unsaved(pending)
    entry = feed_entry_for(event, spec_lookup, pending)
    drafts, pending.ended = [*pending.ended, *([entry] if entry is not None else [])], []
    if unsaved is not None and all(draft.id != unsaved.id for draft in drafts):
        drafts.insert(0, unsaved)  # the reply's last words showed with a delta not stored
    return [_put(storage, pending, draft) for draft in drafts]


def settle(storage: Storage, pending: PendingCalls) -> list[StoryEntry]:
    """Write what `feed` holds back of a reply that stops without an event that ends it (the beat is cancelled, or
    fails): its deltas' row of the DM log, and its words as they show, stored. Answers the entries stored."""
    _log_text(storage, pending)
    unsaved = _unsaved(pending)
    return [_put(storage, pending, unsaved)] if unsaved is not None else []


def _log_text(storage: Storage, pending: PendingCalls) -> None:
    if pending.logged:
        text, pending.logged = "".join(pending.logged), []
        log_dm_event(storage, pending.campaign_id, pending.beat_id, event_to_dict(TextDelta(text)))


def _unsaved(pending: PendingCalls) -> StoryEntry | None:
    """The reply being written, when it shows words that aren't stored."""
    reply = pending.reply
    if reply is None or pending.saved == (reply.id, reply.payload["text"]):
        return None
    return reply


def _put(storage: Storage, pending: PendingCalls, draft: StoryEntry) -> StoryEntry:
    put = storage.story.put(replace(draft, audience=resolve(storage, draft.campaign_id, draft.audience)))
    if put.kind == "dm_text":
        pending.saved, pending.saved_at = (put.id, str(put.payload["text"])), pending.clock()
    if pending.reply is not None and pending.reply.id == put.id:
        pending.reply = put
    return put


def for_the_table(text: str, *, whole: bool = False) -> tuple[str, str]:
    """A reply's text so far as `(what the table may read, the notes for the host)`. A paragraph that starts
    `FOR_THE_HOST` (in any case) is the host's, with the paragraph break after it. Until the reply is `whole`, its
    last paragraph is held back while it may still become one. Without notes, the whole reply is its text as it is;
    with them, it loses the blank space at its end."""
    parts = _PARAGRAPH_BREAK.split(text)
    shown, notes = "", []
    for i in range(0, len(parts), 2):
        paragraph, head = parts[i], parts[i].lstrip().casefold()
        if head.startswith(FOR_THE_HOST):
            notes.append(paragraph.strip())
        elif whole or i < len(parts) - 1 or not FOR_THE_HOST.startswith(head):
            shown += paragraph + (parts[i + 1] if i + 1 < len(parts) else "")
    return (shown.rstrip() if whole and notes else shown), "\n\n".join(notes)


def _shown(pending: PendingCalls, text: str) -> StoryEntry | None:
    """The reply's `dm_text` with `text`: None when it shows nothing, or nothing new."""
    reply = pending.reply
    if not text or (reply is not None and reply.payload["text"] == text):
        return None
    reply = _draft(pending, "dm_text", {"text": text}) if reply is None else replace(reply, payload={"text": text})
    pending.reply = reply
    return reply


def _end_reply(pending: PendingCalls) -> list[StoryEntry]:
    """The entries the end of the reply makes: its last words, when they show more than it did, and its notes for
    the host, for the host's seat alone (nobody's without one)."""
    shown, notes = for_the_table(pending.text, whole=True)
    if pending.reply is None and _collapsed(shown) in pending.told:
        log.warning("beat %s: the DM told again what it told before; dropped: %r", pending.beat_id, shown[:80])
        ended = []
    else:
        ended = [entry] if pending.text and (entry := _shown(pending, shown)) is not None else []
    if pending.reply is not None:
        pending.told.add(_collapsed(pending.reply.payload["text"]))
    if notes:
        host = for_seats([pending.host_seat] if pending.host_seat else [])
        ended.append(_draft(pending, "dm_text", {"text": notes}, host))
    pending.text, pending.reply = "", None
    return ended


def _collapsed(text: str) -> str:
    return " ".join(text.split())


def _may_repeat(pending: PendingCalls, text: str) -> bool:
    """Whether a reply not shown yet is still the start of one the beat told: then it may be a repeat (D3)."""
    said = _collapsed(text)
    return any(told.startswith(said) for told in pending.told)


def _draft(pending: PendingCalls, kind: StoryKind, payload: dict[str, Any], audience: Audience = None) -> StoryEntry:
    return StoryEntry(new_id("sty"), pending.campaign_id, pending.beat_id, 0, kind, payload, audience=audience)


def _tool_row(spec: ToolSpec, call: ToolCall, result: ToolResult, spec_lookup: SpecLookup) -> dict[str, Any]:
    content = _content(result.content)
    answer = content if isinstance(content, dict) else {}
    view = player_view(spec, call.args, answer if result.ok else {"error": True}) or {}
    row: dict[str, Any] = {"name": spec.name, **({"failed": True} if view.get("failed") else {})}
    steps = _batch_steps(call.args, answer, spec_lookup) if spec.name == "batch" else []
    return {**row, "steps": steps} if steps else row


def _batch_steps(args: dict[str, Any], answer: dict[str, Any], spec_lookup: SpecLookup) -> list[dict[str, Any]]:
    """A batch's steps as its row lists them, so the story shows the calls rather than the batch: each step's index
    and tool, and whether it was refused (or never ran). Those the table never sees (a tool not shown to players, a
    hidden call) are left out, as they are outside a batch."""
    asked = args.get("steps")
    got = answer.get("results")
    results = {r.get("step"): r for r in got if isinstance(r, dict)} if isinstance(got, list) else {}
    steps = []
    for i, step in enumerate(asked if isinstance(asked, list) else []):
        if not isinstance(step, dict):
            continue
        spec = spec_lookup(str(step.get("tool") or ""))
        step_args = step.get("args") if isinstance(step.get("args"), dict) else {}
        if spec is None or not spec.player_visible or step_args.get("hidden") is True:
            continue
        done = results.get(i)
        out = done.get("result") if done else None
        refused = done is None or "error" in done or (isinstance(out, dict) and "error" in out)
        steps.append({"step": i, "name": spec.name, **({"failed": True} if refused else {})})
    return steps


SECRET_BY_DEFAULT = frozenset({"scout"})
"""The tools whose dice are secret unless the call says `secret: false` (DEL-273): a scout's Move Silently, Hide in
Shadows and Detect Noise are checks the character can't know the result of."""


def _secret(name: Any, args: Any) -> bool:
    """Whether a call's dice are kept from the players: it says `secret: true`, or its tool's are secret by default."""
    asked = args.get("secret") if isinstance(args, dict) else None
    return asked is True or (name in SECRET_BY_DEFAULT and asked is not False)


def _with_dice(payload: dict[str, Any], args: dict[str, Any], dice: CallDice | None) -> dict[str, Any]:
    """The row with the ids of the rolls its call made (DEL-270): `rolls` on the row, or on each of a batch's steps,
    and `secret` on a check the DM marked secret, whose dice no seat but the host's sees. The story shows them through
    `story_dice`; `player_row` drops both. A row without dice is as it was."""
    if not dice:
        return payload
    out = dict(payload)
    rolls = dice.get("rolls")
    if isinstance(rolls, list) and rolls:
        out["rolls"] = list(rolls)
        if _secret(payload.get("name"), args):
            out["secret"] = True
    by_step = dice.get("steps")
    asked = args.get("steps")
    if isinstance(by_step, dict) and by_step and isinstance(out.get("steps"), list) and isinstance(asked, list):
        steps = []
        for step in out["steps"]:
            ids = by_step.get(step.get("step"))
            if ids:
                step_args = asked[step["step"]].get("args") if isinstance(asked[step["step"]], dict) else None
                secret = _secret(step.get("name"), step_args)
                step = {**step, "rolls": list(ids), **({"secret": True} if secret else {})}
            steps.append(step)
        out["steps"] = steps
    return out


def _content(content: Any) -> Any:
    """A tool result as JSON: as it is, from a JSON string, or from claude's `[{type: text, text}]` blocks."""
    if isinstance(content, list) and all(isinstance(b, dict) and b.get("type") == "text" for b in content):
        content = "".join(str(b.get("text", "")) for b in content)
    if isinstance(content, str):
        try:
            return json.loads(content)
        except ValueError:
            return content
    return content


# ----- the beat runner -----

DIDNT_ANSWER = "The DM didn't answer: "
PROVIDER_FAILED = "the DM provider failed"
ENDED_WITH_ERROR = "the reply ended with an error"
INTERRUPTED = "Delve stopped during the beat"

# The hidden instruction before the act of a beat that starts a session of play (ttrpg2's session start).
BEGIN_SESSION = (
    "[Not from the player, and never to be mentioned to them: this beat starts a session of play. Before you answer, "
    "call session_primer() and read it silently, then start the session with new_session(title), giving it a short "
    "title of your own. Then answer the player's act below.]"
)

# How the DM's message marks a private act (plan 7 Task 17): the DM answers it through `tell`, never in the reply.
PRIVATELY = "privately (only the DM knows; tell them the outcome with tell, and keep it out of your reply)"
# How it marks an act whose translation into English failed: the player's own words follow.
UNTRANSLATED = "in their own words (not translated)"
QUOTE = ">"
"""What starts every line of a player's words in the DM's message (DEL-154, audit finding 15): no line of theirs can
start as one of Delve's does."""

ChoiceFor = Callable[[str], tuple[DMProvider, BackendChoice]]


@dataclass
class _Live:
    """A beat this process is answering: its task, its conversation once open, and the tool calls so far."""

    beat: Beat
    task: asyncio.Task | None = None
    stream: asyncio.Task | None = None
    conversation: DMConversation | None = None
    tool_count: int = 0
    cancelled: bool = False
    note: str = ""
    """What the DM's message starts with: `RETRY_NOTE` for a retried beat, else nothing."""
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    """When the DM started on this answer, by the table's clock (`start_beat` gives it): a retried beat's time counts
    from its retry, not from its opening."""


@dataclass
class AppServices:
    """What the table is handed by the app: the storage, the tools' specs (for the feed), the DM
    provider and choice of each campaign for the DM job, for side passes and for translation (Preferences, with the
    campaign's own override; translation falls back to the side passes' choice), and `publish(kind, data, *, scope,
    campaign_id, audience, language)`, which puts an event on the app's event stream
    (`delve.web.events.EventBus.publish`): the table's events have the scope `table`, a story entry's event has the
    entry's audience, and a translation's its language too. The beats keep time by `clock`, and ask
    `present(campaign_id)` which seats are at the table now (`EventBus.present`); `timers` holds each open beat's
    timer task, and `translating` the translations under way (`delve.play.translate`)."""

    storage: Storage
    spec_lookup: SpecLookup
    dm: ChoiceFor
    side: ChoiceFor
    publish: Callable[..., Any] = lambda kind, data, **where: None
    live: dict[str, _Live] = field(default_factory=dict)
    clock: Clock = field(default_factory=SystemClock)
    present: Callable[[str], set[str]] = lambda campaign_id: set()
    timers: dict[str, asyncio.Task] = field(default_factory=dict)
    translation: ChoiceFor | None = None
    translating: set[asyncio.Task] = field(default_factory=set)
    images: Callable[[Job], tuple[Any, BackendChoice]] | None = None
    """The image provider and choice of an image job (Preferences'), and whether that choice costs money
    (`image_paid`, paid by default); `painting` holds the paintings under way, by image id (`delve.play.images`)."""
    image_paid: Callable[[Job], bool] = always_paid
    painting: dict[str, asyncio.Task] = field(default_factory=dict)
    catalogs: Catalogs = IN_TREE
    """The rulesets and settings a campaign can name (`delve.packs.catalogs`)."""


def beat_json(
    beat: Beat, deadline: datetime | None = None, started: datetime | None = None, now: datetime | None = None
) -> dict[str, Any]:
    """A beat for the play screen, with how long the DM has been at it (from `opened_at`, or from `started`, when the
    DM started on its retry, until it closed or `now`, the table's clock's time), the seats that have submitted (never what they wrote), and the beat timer's deadline
    while it is open. Never the tool count, which is the host's and the co-hosts' (`beat_tools`)."""
    start = started or datetime.fromisoformat(beat.opened_at)
    end = datetime.fromisoformat(beat.closed_at) if beat.closed_at else (now or datetime.now(UTC))
    return {
        "id": beat.id,
        "number": beat.number,
        "status": beat.status,
        "opened_at": beat.opened_at,
        "closed_at": beat.closed_at,
        "elapsed_s": max(0, int((end - start).total_seconds())),
        "submitted": submitted(beat),
        "deadline": deadline.isoformat() if deadline is not None and beat.status == "open" else None,
    }


def submitted(beat: Beat) -> list[str]:
    """The seats that acted or passed in the beat, in order, each once (a hotseat's seat acts once for each of its
    players, DEL-365)."""
    seats = [s.get("seat_id", s.get("player")) for s in beat.submissions if s.get("kind") in ("act", "pass")]
    return list(dict.fromkeys(seats))


def entry_json(entry: StoryEntry) -> dict[str, Any]:
    return asdict(entry)


def running_beat(services: AppServices, campaign_id: str) -> dict[str, Any] | None:
    """The campaign's current beat for the play screen, or None. A beat left running by a Delve that stopped is
    closed as failed first."""
    _close_orphan(services, campaign_id)
    beat = current_beat(services.storage, campaign_id)
    if beat is None:
        return None
    return beat_json(beat, deadline(services.storage, beat), _started(services, beat), services.clock.now())


def ensure_installed(services: AppServices, campaign_id: str) -> None:
    """`MissingPack` when the campaign's ruleset or setting isn't installed: no beat starts for it."""
    campaign = services.storage.campaigns.get(campaign_id)
    if campaign is not None and (missing := missing_pack(services.catalogs, campaign)) is not None:
        raise missing


async def run_beat(services: AppServices, campaign_id: str, submission: dict[str, Any]) -> Beat:
    """Open a beat with one act that closes it at once, and let the DM answer it (`start_beat`). Answers the opened
    beat; `BeatRunning` while a beat is open or runs. A table's beats are opened by `delve.play.beats.submit`."""
    ensure_installed(services, campaign_id)
    _close_orphan(services, campaign_id)
    beat = open_beat(services.storage, campaign_id, submission)
    start_beat(services, beat, services.storage.story.list(campaign_id, limit=1))
    return beat


def start_beat(services: AppServices, beat: Beat, entries: list[StoryEntry] = (), *, note: str = "") -> None:
    """Let the DM answer a beat that has just closed (`running`), in a background task of its own, which runs on when
    the request that closed it goes away. `entries` are the story entries its closing made, published here.

    The answer streams into the story and the DM log, each stored entry published as `story`, and the beat closes as
    `done`, or as `failed` with a `dm_error` entry, or as `cancelled` (`cancel_beat`). `beat` is published when the
    beat starts running and when it closes. `note` goes before the beat's message (`retry_beat`'s)."""
    ensure_installed(services, beat.campaign_id)
    live = _Live(beat, note=note, started_at=services.clock.now())
    services.live[beat.campaign_id] = live
    house_rules.forget_beat(beat.campaign_id, beat.id)
    beat_changed(services, beat)
    for entry in entries:
        told(services, entry)
        translate.translate_entry(services, entry)
    live.task = asyncio.create_task(_answer(services, live))


async def cancel_beat(services: AppServices, campaign_id: str) -> bool:
    """Stop the DM's answer to the running beat, which closes as `cancelled`; False when no beat is running here."""
    live = services.live.get(campaign_id)
    if live is None or live.task is None or live.task.done():
        return False
    live.cancelled = True
    if live.conversation is not None:
        await live.conversation.cancel()
    if live.stream is not None:
        live.stream.cancel()
    return True


async def wait_beat(services: AppServices, campaign_id: str) -> Beat | None:
    """Wait for the beat this process is answering to close; the closed beat, or None when there is none."""
    live = services.live.get(campaign_id)
    if live is None:
        return None
    if live.task is not None:
        await asyncio.shield(live.task)
    return services.storage.beats.get(live.beat.id)


def dm_message(storage: Storage, campaign_id: str, beat: Beat) -> str:
    """What the DM is sent for the beat, in English, after the hidden session start when the beat starts a session
    of play.

    Each act is a line of Delve's saying who acts, over the player's words `quoted`: every line of them starts `> `,
    and no line of Delve's does, so a player's words can't pose as another seat's act, a pass, a fallback or a note of
    Delve's (DEL-154, audit finding 15); dm.md tells the DM that a quote is only ever that player's words. The names
    in Delve's lines are the players' words too, so each is made one line (`one_line`).

    A beat of one act and nothing else (solo play) is the quoted act alone, under the acting characters' names unless
    it is the whole party. Otherwise each act is `<seat> (playing <names>):` over its quote, a pass `<seat>
    passes.`, and a fallback or a `session` submission (the host's start or end of a session,
    `delve.play.table_session`) its own line. A private act, in either, is under `<name>,
    privately (…):` (`PRIVATELY`), the solo one's name the characters' or else the seat's; an act whose translation
    failed is marked `UNTRANSLATED` so. A hotseat player's act or pass (DEL-365) is under the player's name in place
    of the seat's."""
    characters = storage.characters.list(campaign_id)
    pcs = {c.id for c in characters if c.kind == "pc"}
    names = {c.id: one_line(c.name) for c in characters}
    seat_names = {s.id: one_line(s.name) for s in storage.seats.list(campaign_id)}
    lines = []
    for submission in beat.submissions:
        text = str(submission.get("text", "")).strip()
        kind = submission.get("kind", "act")
        acting = [cid for cid in _acting(submission) if cid in names]
        if kind in ("fallback", "session"):  # a line of Delve's
            lines.append(text)
            continue
        seat = seat_names.get(submission.get("seat_id", submission.get("player")), "A player")
        if submission.get("hotseat"):  # one of the players at the host's screen (DEL-365)
            seat = one_line(submission.get("player_name") or seat)
        if kind == "pass":
            lines.append(f"{seat} passes.")
            continue
        private = submission.get("private") is True
        marks = [PRIVATELY] if private else []
        if submission.get("translation") == "failed":
            marks.append(UNTRANSLATED)
        if len(beat.submissions) == 1:
            who = ", ".join(names[cid] for cid in acting) if acting and set(acting) != pcs else ""
            if marks and not who:
                who = seat if private else "The player"
        else:
            who = f"{seat} (playing {', '.join(names[cid] for cid in acting)})" if acting else seat
        if who:
            lines.append(f"{', '.join([who, *marks])}:")
        lines.append(quoted(text))
    message = "\n".join(lines)
    return f"{BEGIN_SESSION}\n\n{message}" if starts_session(storage, campaign_id) else message


def quoted(text: str) -> str:
    """A player's words as the DM's message quotes them: every line, whatever breaks it (`str.splitlines`: a carriage
    return, a Unicode line or paragraph separator too), starts `> `, and a blank one is `>` alone."""
    return "\n".join(f"{QUOTE} {line.rstrip()}" if line.strip() else QUOTE for line in text.splitlines() or [""])


def one_line(name: str) -> str:
    """A name as one line of Delve's: its whitespace, line breaks included, collapsed."""
    return " ".join(str(name).split())


def _acting(submission: dict[str, Any]) -> list[str]:
    """The characters of a submission (`character_ids` in a beat stored before plateau 4)."""
    return list(submission.get("characters", submission.get("character_ids")) or [])


def starts_session(storage: Storage, campaign_id: str) -> bool:
    """Whether the campaign's current session hasn't been started yet, or has ended."""
    state = storage.campaign_states.get(campaign_id)
    session = storage.sessions.get(campaign_id, state.session if state is not None else 1)
    return session is None or session.ended_at is not None


def _close_orphan(services: AppServices, campaign_id: str) -> None:
    """Close as failed a beat left running by a Delve that stopped. An open beat isn't one: it waits for its
    submissions, and the start of Delve closes it (`delve.play.beats.resume`)."""
    beat = current_beat(services.storage, campaign_id)
    live = services.live.get(campaign_id)
    if beat is None or beat.status != "running" or (live is not None and live.beat.id == beat.id and live.task):
        return
    with services.storage.transaction():
        entry = add_entry(services.storage, campaign_id, beat.id, "dm_error", _error(DIDNT_ANSWER + INTERRUPTED, True))
        told(services, entry)
        closed = close_beat(services.storage, beat.id, "failed", services.clock)
    beat_changed(services, closed)
    # No `timeline.after_beat`: a failed beat releases no outcome, as nobody narrated them (Retry does).


def beat_changed(services: AppServices, beat: Beat) -> None:
    """Publish the beat to its table: who has submitted and the deadline, never what they wrote."""
    shown = beat_json(beat, deadline(services.storage, beat), _started(services, beat), services.clock.now())
    data = {
        "campaign_id": beat.campaign_id,
        "beat_id": beat.id,
        "status": beat.status,
        "submitted": shown["submitted"],
        "deadline": shown["deadline"],
        "beat": shown,
    }
    services.publish("beat", data, scope="table", campaign_id=beat.campaign_id)


def _started(services: AppServices, beat: Beat) -> datetime | None:
    """When this process's DM started on the beat, if it answers it (or answered it last)."""
    live = services.live.get(beat.campaign_id)
    return live.started_at if live is not None and live.beat.id == beat.id else None


def tools_counted(services: AppServices, live: _Live, runners: Audience) -> None:
    """Publish the running beat's tool calls so far as `beat_tools`, for the host and the co-hosts (`runners`) only:
    the players and observers never learn how busy the DM is (plan 7 Task 18)."""
    data = {"campaign_id": live.beat.campaign_id, "beat_id": live.beat.id, "tool_count": live.tool_count}
    services.publish("beat_tools", data, scope="table", campaign_id=live.beat.campaign_id, audience=runners)


# The roles a tool row goes out to, each as it sees the row (DEL-270): its dice are for each to read differently.
_ROW_VIEWS: tuple[tuple[SeatRole, ...], ...] = (("host",), ("cohost",), ("player", "observer"))


def told(services: AppServices, entry: StoryEntry) -> None:
    """Publish a stored story entry, for the seats its audience and its kind's roles let see it. A tool row goes out
    as `story` pages show it (`player_row`), without the `call_id` only the host's look at the call reads (DEL-172),
    once for each of `_ROW_VIEWS` that sees it, as it sees it (`story_dice`, DEL-270): the event stream sends one
    event to every seat of its roles, so the host's dice never go out with a player's."""
    if entry.kind != "tool":
        data = {"campaign_id": entry.campaign_id, "entry": entry_json(entry)}
        roles = roles_for(entry.kind, entry.payload)
        where = {"scope": "table", "campaign_id": entry.campaign_id, "audience": entry.audience, "roles": roles}
        services.publish("story", data, **where)
        return
    for roles in _ROW_VIEWS:
        row = seat_dice(services.storage, entry.campaign_id, roles[0]).row(entry.payload)
        if row is None:
            continue
        data = {"campaign_id": entry.campaign_id, "entry": entry_json(replace(entry, payload=row))}
        where = {"scope": "table", "campaign_id": entry.campaign_id, "audience": entry.audience, "roles": roles}
        services.publish("story", data, **where)


async def _answer(services: AppServices, live: _Live) -> None:
    storage, beat = services.storage, live.beat
    status: BeatStatus = "failed"
    try:
        live.stream = asyncio.create_task(_stream(services, live))
        try:
            status = await live.stream
        except asyncio.CancelledError:
            if not live.cancelled:
                raise
            status = "cancelled"
    except Exception as error:  # noqa: BLE001 (a beat always closes, never a hung page)
        log_dm_event(storage, beat.campaign_id, beat.id, {"type": "runner_error", "error": repr(error)})
        entry = add_entry(storage, beat.campaign_id, beat.id, "dm_error", _error(DIDNT_ANSWER + PROVIDER_FAILED, True))
        told(services, entry)
        status = "failed"
    finally:
        if live.cancelled:
            status = "cancelled"
        closed = close_beat(storage, beat.id, status, services.clock)
        beat_changed(services, closed)
        timeline.after_beat(services, closed)


async def _stream(services: AppServices, live: _Live) -> BeatStatus:
    """Send the beat to the DM and feed its reply into the story; the status the beat closes with. The reply's text
    is translated paragraph by paragraph as it streams, for the seats that read another language."""
    storage, beat = services.storage, live.beat
    campaign_id = beat.campaign_id
    provider, choice = services.dm(campaign_id)
    conversation = await provider.open(ConversationSpec(campaign_id, system_prompt(services, campaign_id), choice))
    live.conversation = conversation
    pending = PendingCalls(campaign_id, beat.id, host_seat=_host_seat(storage, campaign_id))
    pending.dice = lambda name, args: ROLLED.take(campaign_id, beat.id, name, args)
    runners = for_seats([s.id for s in storage.seats.list(campaign_id) if s.role in TOOL_ROWS and s.left_at is None])
    # The calls whose results make story entries of their own, by id: their tool's name.
    makers: dict[str, str] = {}
    reason = "error"
    erred = False
    reply: translate.Outgoing | _NoTranslation | None = None
    streamed = _Streamed(services, pending)
    try:
        message = dm_message(storage, campaign_id, beat)
        async for event in conversation.send(f"{live.note}\n\n{message}" if live.note else message):
            raw = event_to_dict(event)
            if isinstance(event, ToolCall):
                # A batch counts as its steps, as the story's tools chip does.
                steps = event.args.get("steps") if event.name == BATCH else None
                live.tool_count += len(steps) if isinstance(steps, list) and steps else 1
                tools_counted(services, live, runners)
                if event.name in STORY_MAKERS or event.name == BATCH:
                    makers[event.id] = event.name
            if isinstance(event, DMError):
                erred = True
                event = replace(event, message=DIDNT_ANSWER + event.message)
            stored = feed(storage, event, raw, services.spec_lookup, pending)
            for entry in stored:
                if reply is not None and entry.id == reply.entry.id:
                    reply.grow(str(entry.payload["text"]))  # the reply's last words, before it ends
                    told(services, entry)
                elif entry.kind == "dm_text" and (pending.reply is None or entry.id != pending.reply.id):
                    _told_and_translated(services, entry)  # a note for the host, or a reply held back to its end
                else:
                    told(services, entry)
            streamed.grew(stored)
            reply = _translated_reply(services, pending.reply, reply)
            timeline.after_event(services, campaign_id, beat.id, event, stored)
            if isinstance(event, ToolResult) and event.id in makers:
                for name, result in _made_by(makers.pop(event.id), event):
                    _make(services, campaign_id, beat.id, name, result)
            if isinstance(event, TurnEnd):
                reason = event.reason
                break
    finally:
        streamed.close()
        ROLLED.forget(campaign_id, beat.id)
        for entry in settle(storage, pending):  # a reply cut off, by a cancel or a failure
            told(services, entry)
        if reply is not None:
            reply.end()
    if reason == "done":
        return "done"
    if reason == "cancelled":
        return "cancelled"
    if not erred:
        entry = add_entry(storage, campaign_id, beat.id, "dm_error", _error(DIDNT_ANSWER + ENDED_WITH_ERROR, False))
        told(services, entry)
    return "failed"


# ----- retrying a failed beat -----

# What the DM is told before the acts of a beat it is answering again (table voice and fixes Task D1).
RETRY_NOTE = (
    "[Not from the players, and never to be mentioned to them: Delve sends you this beat again, because your answer "
    "to it was cut off. What you wrote before it stopped is already in the story. {applied} Carry on from there: first "
    "narrate what those calls did that the story doesn't tell yet (a round's hits, a death), then answer the acts "
    "below.]"
)
APPLIED = "These tool calls of an earlier attempt were applied and stand, each with what it did; don't make them again:"
RESULT_CHARS = 400
"""At most this much of each applied call's result in the retry's note (DEL-336)."""
UNANSWERED = "(no answer came back: check whether it was applied before you make it again)"
NOTHING_APPLIED = "No tool call of an earlier attempt changed anything."
NOT_RETRYABLE = "Only the latest beat can be tried again, when the DM didn't answer it."


class NotRetryable(PlayError):
    """The beat isn't the campaign's latest, didn't fail, or failed for a reason that trying again won't mend (409)."""

    def __init__(self) -> None:
        super().__init__(NOT_RETRYABLE, "Act again instead.")


def retry_state(services: AppServices, campaign_id: str, seat: Seat) -> dict[str, Any]:
    """`{beat_id, may_retry, resets_at}` for the campaign's latest beat: whether `seat` may retry it now, and when the
    usage limit that stopped it ends. A beat left running by a Delve that stopped is closed as failed first."""
    _close_orphan(services, campaign_id)
    beat = services.storage.beats.latest(campaign_id)
    error = _retryable_error(services.storage, beat) if beat is not None else None
    return {
        "beat_id": beat.id if beat is not None else None,
        "may_retry": error is not None and _may_retry(beat, seat),
        "resets_at": error.payload.get("resets_at") if error is not None else None,
    }


def retry_beat(services: AppServices, campaign_id: str, beat_id: str, seat: Seat) -> Beat:
    """Play the failed beat again with the same acts: the same beat row runs again (`start_beat`), its error marked
    `retried`, and the DM told which of its tool calls were applied (`RETRY_NOTE`). `KeyError` for a beat of no such
    id at this table; `BeatRunning` while a beat is open or runs (a second press); `NotRetryable` for a beat that isn't
    the latest, or not failed for a reason that may pass; `NotAllowed` for a seat that isn't the host, a co-host or
    one whose submission is in the beat."""
    storage = services.storage
    ensure_installed(services, campaign_id)
    _close_orphan(services, campaign_id)
    beat = storage.beats.get(beat_id)
    if beat is None or beat.campaign_id != campaign_id:
        raise KeyError(beat_id)
    with storage.transaction():
        current = storage.beats.current(campaign_id)
        if current is not None:
            raise BeatRunning(current)
        latest = storage.beats.latest(campaign_id)
        error = _retryable_error(storage, beat) if latest is not None and latest.id == beat.id else None
        if error is None:
            raise NotRetryable
        if not _may_retry(beat, seat):
            raise NotAllowed("Only the host, or a player who acted in it, can try the beat again.")
        note = RETRY_NOTE.format(applied=_applied(services, campaign_id, beat.id))
        marked = storage.story.put(replace(error, payload={**error.payload, "retried": True}))
        beat = storage.beats.save(replace(beat, status="running", closed_at=None))
    told(services, marked)
    start_beat(services, beat, note=note)
    return beat


def _may_retry(beat: Beat, seat: Seat) -> bool:
    return seat.role in TABLE_RIGHTS or seat.id in submitted(beat)


def _retryable_error(storage: Storage, beat: Beat) -> StoryEntry | None:
    """The failed beat's last error from the runner (one with `retryable`), when it is retryable and not retried yet.
    The story is read from its end back to the beat's entries; an entry of another beat means it has none."""
    if beat.status != "failed":
        return None
    before, page_size = None, 100
    while True:
        page = storage.story.list(beat.campaign_id, before_seq=before, limit=page_size)
        for entry in reversed(page):
            if entry.beat_id == beat.id and entry.kind == "dm_error" and "retryable" in entry.payload:
                retryable = entry.payload["retryable"] is True and not entry.payload.get("retried")
                return entry if retryable else None
            if entry.beat_id is not None and entry.beat_id != beat.id:
                return None
        if len(page) < page_size:
            return None
        before = page[0].seq


def _brief(answer: Any) -> str:
    """An applied call's result in a line: a fight round's actions and outcomes, else its JSON, cut short."""
    if isinstance(answer, dict) and isinstance(answer.get("actions"), list):
        keys = ("attacker", "caster", "actor", "target", "spell", "missile", "hit", "damage", "dead", "downed")
        keys = (*keys, "skipped")
        answer = {
            "actions": [{k: a[k] for k in keys if k in a} for a in answer["actions"] if isinstance(a, dict)],
            **({"outcomes": answer["outcomes"]} if "outcomes" in answer else {}),
        }
    text = json.dumps(answer, sort_keys=True, ensure_ascii=False)
    return text if len(text) <= RESULT_CHARS else text[:RESULT_CHARS] + "…"


def _applied(services: AppServices, campaign_id: str, beat_id: str) -> str:
    """The beat's mutating tool calls so far, from its DM log, as `RETRY_NOTE`'s list: those that were answered and
    not refused, and those no answer came back for (they may have been applied). Reading tools change nothing."""
    calls: dict[str, ToolCall] = {}
    results: dict[str, ToolResult] = {}
    for logged in dm_log(services.storage, campaign_id, beat_id):
        try:
            event = event_from_dict(logged.raw_event_json)
        except (ValueError, TypeError, KeyError):
            continue  # the runner's own notes, such as a provider that failed
        if isinstance(event, ToolCall):
            calls[event.id] = event
        elif isinstance(event, ToolResult):
            results[event.id] = event
    lines = []
    for call in calls.values():
        spec = services.spec_lookup(call.name)
        if spec is not None and not spec.mutates:
            continue
        shown = f"- {call.name} {json.dumps(call.args, sort_keys=True, ensure_ascii=False)}"
        result = results.get(call.id)
        if result is None:
            lines.append(f"{shown} {UNANSWERED}")
        elif result.ok and not (isinstance(answer := _content(result.content), dict) and "error" in answer):
            # What it did, so the retry narrates it (DEL-336: a round lost to a crash was never told).
            lines.append(f"{shown}\n  → {_brief(answer)}")
    return "\n".join([APPLIED, *lines]) if lines else NOTHING_APPLIED


def _host_seat(storage: Storage, campaign_id: str) -> str | None:
    """The id of the table's host's seat, for a note for the host."""
    return next((s.id for s in storage.seats.list(campaign_id) if s.role == "host" and s.left_at is None), None)


def _translated_reply(
    services: AppServices, current: StoryEntry | None, reply: translate.Outgoing | _NoTranslation | None
) -> translate.Outgoing | _NoTranslation | None:
    """Feed the reply being written to its translations: a new reply starts them, and the end of one ends them."""
    if reply is not None and (current is None or current.id != reply.entry.id):
        reply.end()
        reply = None
    if current is None:
        return None
    if reply is None:
        reply = translate.out_of_english(services, current)
        if reply is None:
            return _NoTranslation(current)
    reply.grow(str(current.payload.get("text", "")))
    return reply


class _Streamed:
    """What the table has been sent of the reply being written (DEL-241, review P3). A reply `feed` stores goes out
    whole, as a `story` event; between, only its new words, as `story_text` `{campaign_id, entry_id, at, text}`, where
    `text` follows the reply's first `at` characters, with the reply's audience and roles. They go at most every
    `PUBLISH_EVERY` seconds, the words since then together, and none once the reply is stored again or ends: its
    `story` has them. A page that misses some words (its text isn't `at` long) waits for that `story`, which comes at
    least every `STORE_EVERY` seconds. Should the reply's words change other than at their end, it goes out whole."""

    def __init__(self, services: AppServices, pending: PendingCalls) -> None:
        self._services, self._pending = services, pending
        self._id: str | None = None
        self._text = ""
        self._sent_at = 0.0
        self._later: asyncio.TimerHandle | None = None

    def grew(self, stored: list[StoryEntry]) -> None:
        """After an event: the reply as stored, if it was (then it went out whole), else its new words, soon."""
        reply = self._pending.reply
        loop = asyncio.get_running_loop()
        if reply is not None and any(entry.id == reply.id for entry in stored):
            self.close()
            self._id, self._text, self._sent_at = reply.id, str(reply.payload["text"]), loop.time()
            return
        if reply is None or reply.id != self._id:
            self.close()  # it ended, or isn't shown yet
            return
        wait = self._sent_at + PUBLISH_EVERY - loop.time()
        if wait <= 0:
            self._send()
        elif self._later is None:
            self._later = loop.call_later(wait, self._send)

    def close(self) -> None:
        if self._later is not None:
            self._later.cancel()
            self._later = None

    def _send(self) -> None:
        self._later = None
        reply = self._pending.reply
        if reply is None or reply.id != self._id:
            return
        text = str(reply.payload["text"])
        if text == self._text:
            return
        if text.startswith(self._text):
            at = len(self._text)
            data = {"campaign_id": reply.campaign_id, "entry_id": reply.id, "at": at, "text": text[at:]}
            roles = roles_for(reply.kind, reply.payload)
            self._services.publish(
                "story_text", data, scope="table", campaign_id=reply.campaign_id, audience=reply.audience, roles=roles
            )
        else:
            told(self._services, reply)
        self._text, self._sent_at = text, asyncio.get_running_loop().time()


class _NoTranslation:
    """A reply nobody needs translated: remembered, so its seats aren't looked up again at every delta."""

    def __init__(self, entry: StoryEntry) -> None:
        self.entry = entry

    def grow(self, text: str) -> None:
        pass

    def end(self, text: str | None = None) -> None:
        pass


def _told_and_translated(services: AppServices, entry: StoryEntry) -> None:
    told(services, entry)
    translate.translate_entry(services, entry)


# The tools whose results make story entries of their own, beside their tool row: a recap, a picture shown, a tell
# and a said line.
STORY_MAKERS = ("end_session", SHOW_IMAGE, TELL, SAY)


def _made_by(name: str, result: ToolResult) -> list[tuple[str, ToolResult]]:
    """The results that make story entries, as `(tool, result)`: the call's own, or for a `batch` each step's of those
    tools, in order, so a line said as a step of a batch is said as it would be on its own."""
    if name != BATCH:
        return [(name, result)]
    content = _content(result.content)
    if not result.ok or not isinstance(content, dict) or not isinstance(content.get("results"), list):
        return []
    return [
        (step["tool"], ToolResult(result.id, True, step["result"]))
        for step in content["results"]
        if isinstance(step, dict) and step.get("tool") in STORY_MAKERS and "result" in step
    ]


def _make(services: AppServices, campaign_id: str, beat_id: str, name: str, result: ToolResult) -> None:
    """The story entry a `name` result makes, stored and told, if it makes one. A recap also ends the table's session:
    it gathers."""
    storage = services.storage
    if name == "end_session" and (recap := _recap(result)) is not None:
        from delve.play import table_session  # it imports this module

        _told_and_translated(services, add_entry(storage, campaign_id, beat_id, "recap", recap))
        table_session.session_ended(services, campaign_id)  # the table gathers (DEL-199)
    elif name == SHOW_IMAGE and (image := _image(services, campaign_id, result)) is not None:
        told(services, add_entry(storage, campaign_id, beat_id, "image", image))
    elif name == TELL and (whisper := _tell(services, campaign_id, result)) is not None:
        _told_and_translated(services, add_entry(storage, campaign_id, beat_id, "dm_text", *whisper))
    elif name == SAY and (said := _said(services, campaign_id, beat_id, result)) is not None:
        _told_and_translated(services, add_entry(storage, campaign_id, beat_id, "say", said))


def _recap(result: ToolResult) -> dict[str, Any] | None:
    content = _content(result.content)
    if not result.ok or not isinstance(content, dict) or "error" in content or not content.get("recap_md"):
        return None
    return {"text": content["recap_md"], "session": content.get("session"), "title": content.get("title")}


def _image(services: AppServices, campaign_id: str, result: ToolResult) -> dict[str, str] | None:
    """The `image` entry of a `show_image` result, through `player_view`: None unless the campaign's pinned revision
    holds that image for the players."""
    spec = services.spec_lookup(SHOW_IMAGE)
    content = _content(result.content)
    if spec is None or not result.ok or not isinstance(content, dict):
        return None
    image = (player_view(spec, {}, content) or {}).get("image")
    campaign = services.storage.campaigns.get(campaign_id)
    if image is None or campaign is None:
        return None
    source = pinned_source(services.storage, campaign.module_id, campaign.revision)
    shown = {a.id for a in source.player_images()} if source is not None else set()
    return image if image["asset"] in shown else None


def _told(spec: ToolSpec, result: ToolResult) -> dict[str, Any] | None:
    """A `tell` result's `{characters, text}`, through `player_view`; None for a refusal or anything other."""
    content = _content(result.content)
    if not result.ok or not isinstance(content, dict):
        return None
    return (player_view(spec, {}, content) or {}).get("told")


def _tell(services: AppServices, campaign_id: str, result: ToolResult) -> tuple[dict[str, Any], Audience] | None:
    """The `dm_text` entry of a `tell` result, with the campaign's PCs it names as `told_to`, and its audience, those
    PCs: None when it names none."""
    spec = services.spec_lookup(TELL)
    told = _told(spec, result) if spec is not None else None
    if told is None:
        return None
    pcs = {c.id for c in services.storage.characters.list(campaign_id) if c.kind == "pc"}
    ids = [i for i in told["characters"] if i in pcs]
    return ({"text": told["text"], "told_to": ids}, for_characters(ids)) if ids else None


def _said(services: AppServices, campaign_id: str, beat_id: str, result: ToolResult) -> dict[str, Any] | None:
    """The `say` entry of a `say` result, through `player_view`, rebuilt from the campaign's NPC it names: None for a
    refusal, or a speaker who isn't one of the campaign's NPCs or a PC handed to the DM in this beat."""
    spec = services.spec_lookup(SAY)
    content = _content(result.content)
    if spec is None or not result.ok or not isinstance(content, dict):
        return None
    said = (player_view(spec, {}, content) or {}).get("said")
    npc = services.storage.characters.get(said["speaker"]["id"]) if said is not None else None
    if said is None or npc is None or npc.campaign_id != campaign_id:
        return None
    if npc.kind != "npc" and not handed_to_dm(services.storage, campaign_id, beat_id, npc):
        return None
    return said_line(npc, said["text"], said["mood"])


def system_prompt(services: AppServices, campaign_id: str) -> str:
    """The DM's system prompt for the campaign, with its tone and detail level (the play settings)."""
    settings = play_settings(services.storage, campaign_id)
    ctx = context_for(services.storage, campaign_id, "prompt", catalogs=services.catalogs)
    parts = build_system_prompt(
        ctx,
        tone=settings["tone"],
        detail=settings["detail"],
        custom_tone=settings.get("custom_tone", ""),
        xp_awards=settings["xp_awards"],
    )
    return "\n\n".join(parts)


# ----- the campaign's play settings -----

DEFAULT_PLAY_SETTINGS: dict[str, Any] = {
    "tone": "classic",
    "custom_tone": "",
    "detail": DEFAULT_DETAIL,
    "effort": None,
    "model": None,
    "beat_timer_s": None,
    "fallback": "hold_back",
    "paid_images": False,
    "paid_images_per_day": 20,
    # None: as Preferences pick portraitgen's style for PCs and for NPCs (DEL-252).
    "portrait_style": None,
    "xp_awards": list(DEFAULT_XP_AWARDS),
    # The enemies' dice in the story: behind the screen, or in the open for every seat (DEL-270).
    "enemy_dice": "screen",
    # The dice in the story at all, for the seats but the host's: shown, or the story only in words (DEL-280).
    "show_dice": True,
    # Pictures pasted into table talk: off until the host allows them (DEL-294).
    "talk_pictures": False,
    # Several players at the host's screen, each acting for their own characters (DEL-365, `delve.play.hotseat`).
    "hotseat": False,
    "hotseat_players": [],
}
FALLBACKS = ("hold_back", "in_character")
BEAT_TIMER_S = (30, 1800)
PAID_PER_DAY = DEFAULT_PLAY_SETTINGS["paid_images_per_day"]
"""The paid pictures a campaign paints in 24 hours by default (DEL-153, `delve.play.images`): an evening's scenes and
a party's portraits, with room to spare, at a few cents each."""
PAID_PER_DAY_RANGE = (1, 500)
CUSTOM_TONE_LENGTH = 2000
"""The most characters of an organiser's own tone (`custom_tone`), which the DM reads with the tone `custom`."""


def play_settings(storage: Storage, campaign_id: str) -> dict[str, Any]:
    """The campaign's tone and detail level, the organiser's own tone for `custom` (`custom_tone`, "" for none), its DM
    model and effort (None: as in Preferences), and the beat timer (in seconds, None for none) with its fallback for the characters nobody acted for, and whether paid images are on
    (`paid_images`, off until the host turns them on) with how many paid pictures it paints in 24 hours
    (`paid_images_per_day`, DEL-153), the style its portraits are drawn in (`portrait_style`, None: as in Preferences,
    DEL-252),
    what XP is awarded for (`xp_awards`, some of `XP_AWARDS`; DEL-113), and whether the story shows the enemies' dice
    to every seat (`enemy_dice`, `screen` or `open`; DEL-270), whether it shows the seats but the host's any dice at
    all (`show_dice`; DEL-280), and whether the seats may paste pictures into table talk (`talk_pictures`, off until
    the host allows them; DEL-294), and hotseat play with its players (`hotseat`, `hotseat_players`; DEL-365)."""
    return {**DEFAULT_PLAY_SETTINGS, **(storage.play_settings.get(campaign_id) or {})}


def deadline(storage: Storage, beat: Beat) -> datetime | None:
    """When the open beat's timer runs out: `opened_at` plus the campaign's beat timer. None without a timer, and for
    a beat that isn't open."""
    timer = play_settings(storage, beat.campaign_id)["beat_timer_s"]
    if beat.status != "open" or timer is None:
        return None
    return datetime.fromisoformat(beat.opened_at) + timedelta(seconds=timer)


def set_play_settings(storage: Storage, campaign_id: str, raw: dict[str, Any]) -> dict[str, Any]:
    """Store the campaign's play settings; `PlayError` for an unknown tone, detail level, effort, fallback or portrait
    style, a custom tone that isn't text or is past `CUSTOM_TONE_LENGTH` (it is stored stripped; the tone `custom`
    with none is as `classic`), or a beat timer or a number of paid pictures a day out of its range. Whether the model and effort are offered by the DM's provider is for the caller to
    check."""
    settings = {**play_settings(storage, campaign_id), **raw}
    timer = settings["beat_timer_s"]
    if timer is not None and (type(timer) is not int or not BEAT_TIMER_S[0] <= timer <= BEAT_TIMER_S[1]):
        raise PlayError("The beat timer is 30 to 1800 seconds.", "Or none: null.")
    if settings["fallback"] not in FALLBACKS:
        raise PlayError(f"Unknown fallback '{settings['fallback']}'.", f"Use one of {', '.join(FALLBACKS)}.")
    if settings["tone"] not in TONES:
        raise PlayError(f"Unknown tone '{settings['tone']}'.", f"Use one of {', '.join(TONES)}.")
    if not isinstance(settings["custom_tone"], str):
        raise PlayError("A custom tone is text.")
    settings["custom_tone"] = settings["custom_tone"].strip()
    if len(settings["custom_tone"]) > CUSTOM_TONE_LENGTH:
        raise PlayError(f"A custom tone is at most {CUSTOM_TONE_LENGTH} characters.")
    if settings["detail"] not in DETAIL_LEVELS or isinstance(settings["detail"], bool):
        raise PlayError(f"Unknown detail level '{settings['detail']}'.", "Use 0, 1, 2 or 3.")
    if settings["effort"] is not None and settings["effort"] not in {str(e) for e in Effort}:
        raise PlayError(f"Unknown effort '{settings['effort']}'.", f"Use one of {', '.join(map(str, Effort))}.")
    if settings["model"] is not None and not isinstance(settings["model"], str):
        raise PlayError("The model is a name.")
    if not isinstance(settings["paid_images"], bool):
        raise PlayError("Paid images are on or off: true or false.")
    if not isinstance(settings["show_dice"], bool):
        raise PlayError("The dice in the story are shown or not: true or false.")
    if not isinstance(settings["talk_pictures"], bool):
        raise PlayError("Pictures in table talk are on or off: true or false.")
    if not isinstance(settings["hotseat"], bool):
        raise PlayError("Hotseat is on or off: true or false.")
    if "hotseat_players" in raw:
        settings["hotseat_players"] = hotseat.validated(storage, campaign_id, raw["hotseat_players"])
    per_day = settings["paid_images_per_day"]
    if type(per_day) is not int or not PAID_PER_DAY_RANGE[0] <= per_day <= PAID_PER_DAY_RANGE[1]:
        raise PlayError("Paid pictures a day are 1 to 500.", "Turn paid images off for none.")
    if settings["portrait_style"] is not None and settings["portrait_style"] not in PORTRAIT_STYLES:
        raise PlayError(
            f"Unknown portrait style '{settings['portrait_style']}'.", f"Use one of {', '.join(PORTRAIT_STYLES)}."
        )
    if settings["enemy_dice"] not in ENEMY_DICE:
        raise PlayError(f"Unknown enemy_dice '{settings['enemy_dice']}'.", f"Use one of {', '.join(ENEMY_DICE)}.")
    awards = settings["xp_awards"]
    if not isinstance(awards, list) or not all(isinstance(name, str) and name in XP_AWARDS for name in awards):
        raise PlayError("XP awards are a list of what earns XP.", f"Use any of {', '.join(XP_AWARDS)}.")
    settings["xp_awards"] = [name for name in XP_AWARDS if name in awards]  # in order, once each
    stored = {key: settings[key] for key in DEFAULT_PLAY_SETTINGS}
    storage.play_settings.put(campaign_id, stored)
    return play_settings(storage, campaign_id)
