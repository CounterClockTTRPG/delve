"""A keyed room's read-aloud text, told to the players as the module wrote it (DEL-357): `read_aloud` gives the key's
boxed text to the story word for word, and each of its quotes that is a sentence of its own as the speaker's `say`
line, in the passage's order. The DM of campaign sword (beat 34, room 1B) gave a talking door's three quotes with
`say` and none of the rest: the door, the runes and the song with the riddle's clues never reached the players.

The table makes the entries from the result (`delve.play.table`): narration as `dm_text`, lines as `say`, after the
tool's row and so after the DM's words before the call. Only the key's `read_aloud` field is in the result, never its
DM text; the same passage again in a beat tells nothing (an event of the beat remembers it)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from delve.dm.tools.module import _keyed, _pinned
from delve.dm.tools.say import said_line, speaker_of
from delve.dm.tools.schema import ToolSpec, params, string, tool
from delve.play.context import CampaignContext, PlayError

SPECS: list[ToolSpec] = []
READ_ALOUD = "read_aloud"
TOLD = "read_aloud"
"""The event that remembers a passage told in a beat."""

MARKS = '"“”'
EMPHASIS = "*_"
SENTENCE_END = ".!?…"
_PARAGRAPH = re.compile(r"\n[ \t]*\n")
_ENDS_A_SENTENCE = re.compile(r"[.!?…—–-][*_’']*$")
_SOFT_BREAK = re.compile(r"(?<!\\)[ \t]*\n[ \t]*")


@dataclass(frozen=True)
class Part:
    """A piece of a passage: narration as the module wrote it, or the words of a quote (`spoken`), without its marks."""

    text: str
    spoken: bool = False


def passage(text: str) -> list[Part]:
    """The passage `text` in its order: its narration, and its quotes of their own as spoken parts.

    A quote is spoken when it is a sentence of its own: it opens a paragraph or follows a sentence's end, its words end
    one (. ! ? … or a dash), and what follows starts another sentence or ends the paragraph. In the modules' boxed
    texts most quotes are not: an attribution follows ("Halt!" cries the guard), a lead-in comes before (a sign reads,
    "EXIT."), or they are a word in quotes (a giant "X"). Those stay in their sentence, told whole: cut out, the rest
    would read as a fragment, or a sign would speak. A quote inside an italic run stays too, and so does a quote left
    open, unless the next paragraph opens one (a speech over paragraphs). Narration keeps its line breaks and
    Markdown; a spoken part keeps the italics around it and loses its soft line breaks."""
    parts: list[Part] = []
    told = 0
    paragraphs = _paragraphs(text)
    for n, (start, end) in enumerate(paragraphs):
        following = text[paragraphs[n + 1][0] : paragraphs[n + 1][1]] if n + 1 < len(paragraphs) else ""
        for cut, words in _spoken(text[start:end], following):
            narration = text[told : start + cut[0]].strip()
            if narration:
                parts.append(Part(narration))
            parts.append(Part(_SOFT_BREAK.sub(" ", words.strip()), spoken=True))
            told = start + cut[1]
    rest = text[told:].strip()
    if rest:
        parts.append(Part(rest))
    return parts


def _paragraphs(text: str) -> list[tuple[int, int]]:
    """Each paragraph's start and end in `text`."""
    spans, at = [], 0
    for gap in _PARAGRAPH.finditer(text):
        spans.append((at, gap.start()))
        at = gap.end()
    spans.append((at, len(text)))
    return [(s, e) for s, e in spans if text[s:e].strip()]


def _quotes(para: str) -> tuple[list[tuple[int, int]], int | None]:
    """The paragraph's quotes, each `(start, end)` with its marks, and where a quote left open starts. A mark after a
    space (or a bracket, an emphasis, a dash) and before a word opens; one after a word closes; one that does neither
    (6” thick) is no quote mark."""
    spans: list[tuple[int, int]] = []
    opened: int | None = None
    for i, ch in enumerate(para):
        if ch not in MARKS:
            continue
        before, after = para[i - 1 : i], para[i + 1 : i + 2]
        opens = (not before or before.isspace() or before in "([*_—–-") and bool(after) and not after.isspace()
        closes = bool(before) and not before.isspace() and (not after or after.isspace() or after in ".,;:!?)*_—–-…’'")
        if opened is not None and closes:
            spans.append((opened, i + 1))
            opened = None
        elif opens:
            opened = i  # an earlier one left open was a stray mark
    return spans, opened


def _spoken(para: str, following: str) -> list[tuple[tuple[int, int], str]]:
    """The paragraph's spoken quotes: each one's cut `(start, end)`, with the italics around it, and its words."""
    spans, opened = _quotes(para)
    candidates = [(s, e, para[s + 1 : e - 1]) for s, e in spans]
    goes_on = following.lstrip(EMPHASIS)[:1]
    if opened is not None and not para[:opened].strip(" \t" + EMPHASIS) and goes_on and goes_on in MARKS:
        candidates.append((opened, len(para.rstrip()), para[opened + 1 :].rstrip()))
    out = []
    for s, e, words in candidates:
        k = 0  # the italics around the quote: as many emphasis marks before it as the same after it
        while s - k > 0 and e + k < len(para) and para[s - k - 1] in EMPHASIS and para[e + k] == para[s - k - 1]:
            k += 1
        cut = (s - k, e + k)
        before, after = para[: cut[0]].rstrip(), para[cut[1] :].lstrip().lstrip(EMPHASIS)
        starts = not before or before[-1] in SENTENCE_END + MARKS + ")"
        follows = not after or after[0].isupper() or after[0] in MARKS
        in_italics = before.count("*") % 2 == 1
        if starts and follows and not in_italics and _ENDS_A_SENTENCE.search(words.strip()):
            out.append((cut, para[cut[0] : s] + words + para[e : cut[1]]))
    return out


def _speakers(value: Any) -> list[str]:
    """`speaker` as a list of names or ids: one, a list of them, or none."""
    if isinstance(value, str):
        return [value] if value.strip() else []
    return [str(v) for v in value or [] if str(v).strip()]


@tool(
    SPECS,
    READ_ALOUD,
    params(
        "room",
        room=string("The keyed room, as module_key takes it: its key (C2), id, bare name or label."),
        part=string("The part of the module the key is in, for a key two parts share, as module_key takes it."),
        speaker={
            "anyOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}],
            "description": "Who speaks the passage's quotes, an NPC by id or exact name as say takes it "
            "(introduce_npc first); for several speakers, a list, one for each quoted line in order. Give it whenever "
            "the passage has quotes: left out, they stay in the narration, with no voice.",
        },
    ),
    mutates=True,
    areas=(),
)
def read_aloud(ctx: CampaignContext, room: str, part: str = "", speaker: Any = None) -> dict[str, Any]:
    """Tell a keyed room's read-aloud text (its boxed text) to the players when play reaches it: it appears in the
    story word for word after your narration so far, songs, verse and inscriptions as written, and each quote that is
    a sentence of its own as the `speaker`'s say line, in the passage's order. Don't tell it again in your reply: go on
    from where it ends. Only the read-aloud reaches the players, never the key's DM text; the same passage again in
    this beat tells nothing."""
    _, _, text = _pinned(ctx)
    key = _keyed(ctx, text, room, part)
    section = text.section(key.text_anchor) if key.text_anchor else None
    boxed = (section.read_aloud or "").strip() if section else ""
    if not boxed:
        raise PlayError(f"{key.key} has no read-aloud text.", hint="Narrate the room from module_key in your words.")
    done = ctx.storage.events.list(ctx.campaign_id, types=[TOLD], beat=ctx.beat)
    if any(e.data.get("key") == key.key and e.data.get("part") == key.part for e in done):
        return {"key": key.key, "title": key.title, "told": "already, earlier in this beat: it is in the story"}
    names = _speakers(speaker)
    parts = passage(boxed) if names else [Part(boxed)]
    lines = [p.text for p in parts if p.spoken]
    if len(names) > 1 and len(names) != len(lines):
        quoted = "; ".join(f"{n}. {line[:60]}" for n, line in enumerate(lines, 1))
        raise PlayError(
            f"{len(names)} speakers for {len(lines)} quoted lines.",
            hint=f"Name one speaker for them all, or one for each line in order: {quoted or 'none'}.",
        )
    speakers = [speaker_of(ctx, name) for name in names]
    out, n = [], 0
    for p in parts:
        if p.spoken:
            out.append({"said": said_line(speakers[min(n, len(speakers) - 1)], p.text)})
            n += 1
        else:
            out.append({"text": p.text})
    ctx.log(TOLD, key=key.key, part=key.part, lines=n)
    return {"key": key.key, "title": key.title, "read_aloud": out}
