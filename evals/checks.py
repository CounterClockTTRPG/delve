"""Checks: one function per rule of `delve/dm/prompt/dm.md`, run against a whole Trace.

A check takes (case, trace) and returns a list of Findings; empty means the trace keeps the rule. Register a new one
with @check("name"); see README.

Beat-scoped expectations come from the case (`beats[i].expect`); a check that needs one skips beats without it. The
global checks (pacing, meta, hidden intel, tools outside Delve) run on every beat.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from functools import cache

from delve.dm.tools import all_specs
from delve.dm.tools.redact import DM_ONLY_KEYS
from evals.trace import Beat, ToolCall, Trace

CHECKS: dict[str, Callable] = {}


@dataclass
class Finding:
    check: str
    beat: int
    message: str

    def __str__(self) -> str:
        return f"[{self.check}] beat {self.beat}: {self.message}"


def check(name: str):
    def deco(fn):
        CHECKS[name] = fn
        fn.check_name = name
        return fn

    return deco


# Tools that put dice on the table (Hard Constraint #1 and the composites that run them). Any one of these counts as
# "the roll" unless the case's expectation names specific tools.
ROLL_TOOLS = {
    "roll",
    "saving_throw",
    "skill_check",
    "ability_check",
    "reaction",
    "resolve_attack",
    "combat_round",
    "setup_combat",
    "council",
    "scout",
    "morale_check",
    "surprise_check",
    "encounter_check",
    "turning_undead",
    "system_shock",
    "resurrection_check",
    "generate_treasure",
    "award_treasure",
}

COMBAT_OPENERS = {"setup_combat"}
COMBAT_RESOLVERS = {"combat_round", "resolve_attack"}


def _expects(case: dict, i: int) -> dict:
    return _beat(case, i).get("expect") or {}


def _beat(case: dict, i: int) -> dict:
    beats = case.get("beats") or []
    return beats[i] if i < len(beats) else {}


def _is_ooc(beat: Beat) -> bool:
    return beat.player.strip().lower().startswith("(ooc")


# ── 1. Die-first ─────────────────────────────────────────────────────────


@check("die_first")
def die_first(case: dict, trace: Trace) -> list[Finding]:
    """Hard Constraint #1: the roll lands before the outcome is narrated.

    expect.roll = {"tools": [...], "outcome": [regex, ...]} (or a list of them). The beat must call one of `tools`
    (default: any roll tool), and no `outcome` pattern may appear in narration emitted before that call. An outcome
    narrated with no roll at all fails too."""
    out = []
    for i, beat in enumerate(trace.beats):
        rolls = _expects(case, i).get("roll")
        if not rolls:
            continue
        for want in rolls if isinstance(rolls, list) else [rolls]:
            tools = want.get("tools") or sorted(ROLL_TOOLS)
            idx = beat.first_index(tools)
            if idx is None:
                out.append(Finding("die_first", i, f"no roll among {tools} this beat"))
                continue
            before = beat.text_before(idx)
            for pat in want.get("outcome") or []:
                m = re.search(pat, before, re.IGNORECASE)
                if m:
                    out.append(
                        Finding("die_first", i, f"outcome {m.group(0)!r} narrated before {beat.events[idx].name}")
                    )
    return out


# ── 2. Combat pipeline ──────────────────────────────────────────────────


@check("combat_pipeline")
def combat_pipeline(case: dict, trace: Trace) -> list[Finding]:
    """Hard Constraint #8: combat runs through setup_combat → combat_round/resolve_attack → end_combat, and hit points
    move only through the fight.

    Across the whole trace: no attack outside a live fight; no hp edit through update_character while a fight is
    live; apply_damage in a fight only after a roll since the last one (a trap's or a spell's damage is rolled
    first); no fight ended with zero resolution events. Per beat, expect.combat requires a resolution event that beat
    and expect.combat_ends requires end_combat by the end of it."""
    out = []
    live = False
    resolved = 0
    for i, beat in enumerate(trace.beats):
        exp = _expects(case, i)
        beat_resolved = 0
        rolled_since_damage = False
        for call in beat.tool_calls:
            for name, args in call.steps():
                if name in COMBAT_OPENERS:
                    live, resolved = True, 0
                    rolled_since_damage = True
                elif name in COMBAT_RESOLVERS:
                    if not live:
                        out.append(Finding("combat_pipeline", i, f"{name} with no setup_combat"))
                    resolved += 1
                    beat_resolved += 1
                    rolled_since_damage = True
                elif name == "end_combat":
                    if live and resolved == 0:
                        out.append(Finding("combat_pipeline", i, "fight ended with zero resolution events"))
                    live = False
                elif name == "update_character" and live and any(k.startswith("hp") for k in args.get("patch") or {}):
                    out.append(Finding("combat_pipeline", i, "update_character edits hp in a fight"))
                elif name == "apply_damage" and live:
                    if not rolled_since_damage:
                        out.append(Finding("combat_pipeline", i, "apply_damage in a fight with no roll behind it"))
                    rolled_since_damage = False
                elif name in ROLL_TOOLS:
                    rolled_since_damage = True
        if exp.get("combat") and beat_resolved == 0:
            out.append(Finding("combat_pipeline", i, "combat beat with zero pipeline resolution events"))
        if exp.get("combat_ends") and live:
            out.append(Finding("combat_pipeline", i, "fight left live (no end_combat)"))
    return out


# ── 3. No hidden intel in end-of-beat choices ───────────────────────────

_PAREN_PROMPT_RE = re.compile(r"\(([^()]{10,800})\)\s*$", re.DOTALL)
_OPTION_LINE_RE = re.compile(r"^\s*(?:[-*•]|\d+[.)]|[a-z][.)])\s+\S")
_HIDDEN_FEATURE_RE = re.compile(
    r"\b(hidden|secret|concealed|disguised)\s+"
    r"(door|doorway|passage|passageway|trap|chamber|trigger|switch|lever|"
    r"compartment|stair|stairs|panel|button|plate|alcove|niche|tunnel|exit|"
    r"mechanism|catch|latch)\b",
    re.IGNORECASE,
)


def choices(beat: Beat) -> str:
    """The end-of-beat choice prompt: a trailing parenthesised block, else trailing bullet/numbered option lines, else
    a last paragraph that asks a question. Empty when the beat ends without one."""
    text = beat.narration.rstrip()
    if not text:
        return ""
    m = _PAREN_PROMPT_RE.search(text)
    if m and ("?" in m.group(1) or " or " in m.group(1).lower()):
        return m.group(1).strip()
    lines = [line for line in text.splitlines() if line.strip()]
    if lines and not _OPTION_LINE_RE.match(lines[-1]) and lines[-1].endswith("?"):
        tail, lines = [lines[-1]], lines[:-1]  # "What do you do?" after a list
    else:
        tail = []
    opts = []
    for line in reversed(lines):
        if not _OPTION_LINE_RE.match(line):
            break
        opts.append(line)
    if opts:
        return "\n".join(list(reversed(opts)) + tail)
    last = text.split("\n\n")[-1].strip()
    return last if last.endswith("?") else ""


@cache
def _dm_only_keys(tool: str) -> frozenset[str]:
    """The keys of a tool's result that are DM-only wherever they are: `dm_only` and the others the players' filter
    always drops, plus the tool's own `dm_only_keys`."""
    specs = {spec.name: spec for spec in all_specs()}
    return frozenset(DM_ONLY_KEYS) | frozenset(specs[tool].dm_only_keys if tool in specs else ())


def _dm_only_strings(value, keys: frozenset[str]) -> list[str]:
    """Every string under a DM-only key in a tool result."""
    found = []
    if isinstance(value, dict):
        for k, v in value.items():
            if k in keys:
                found.extend(_all_strings(v))
            else:
                found.extend(_dm_only_strings(v, keys))
    elif isinstance(value, list):
        for v in value:
            found.extend(_dm_only_strings(v, keys))
    return found


def _all_strings(value) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _all_strings(v)]
    if isinstance(value, list):
        return [s for v in value for s in _all_strings(v)]
    return []


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", text.lower())


def _shares_ngram(a: str, b: str, n: int = 4) -> str | None:
    wa = _words(a)
    grams = {" ".join(wa[k : k + n]) for k in range(len(wa) - n + 1)}
    wb = _words(b)
    for k in range(len(wb) - n + 1):
        g = " ".join(wb[k : k + n])
        if g in grams:
            return g
    return None


def hidden_terms(case: dict) -> list[str]:
    terms = list(case.get("hidden_terms") or [])
    for s in case.get("secrets") or []:
        terms.extend(s.get("terms") or [])
    return terms


@check("no_hidden_intel")
def no_hidden_intel(case: dict, trace: Trace) -> list[Finding]:
    """Hard Constraint #5 and the "leaking through the choice menu" anti-pattern: the end-of-beat choices name nothing
    DM-only: no term from the case's secrets/hidden_terms or the beat's expect.hidden_terms, no 4-word run from any
    DM-only result text seen so far, no "hidden door"-style feature. An Ask the DM answer (a beat with "ask": true)
    is player-facing whole, so all of it is checked."""
    out = []
    terms = hidden_terms(case)
    dm_only: list[str] = []
    for i, beat in enumerate(trace.beats):
        for call in beat.tool_calls:
            dm_only.extend(_dm_only_strings(call.result, _dm_only_keys(call.name)))
        prompt = beat.narration if _beat(case, i).get("ask") else choices(beat)
        if not prompt:
            continue
        for term in terms + list(_expects(case, i).get("hidden_terms") or []):
            if re.search(rf"\b{re.escape(term)}\b", prompt, re.IGNORECASE):
                out.append(Finding("no_hidden_intel", i, f"choice prompt names hidden {term!r}"))
        for s in dm_only:
            gram = _shares_ngram(s, prompt)
            if gram:
                out.append(Finding("no_hidden_intel", i, f"choice prompt repeats dm_only text {gram!r}"))
        for m in _HIDDEN_FEATURE_RE.finditer(prompt):
            out.append(Finding("no_hidden_intel", i, f"choice prompt names {m.group(0)!r}"))
    return out


# ── Cheap checks the hard constraints suggest ───────────────────────────

_DICE_RE = re.compile(r"\b\d*d(?:4|6|8|10|12|20|100)\b", re.IGNORECASE)


def _tool_name_re(trace: Trace) -> re.Pattern | None:
    # Only multi-word tool names: "roll", "room" or "door" are prose too.
    names = {c.name for c in trace.tool_calls if "_" in c.name}
    names |= {n for n in ROLL_TOOLS | COMBAT_OPENERS if "_" in n}
    return re.compile(r"\b(" + "|".join(sorted(map(re.escape, names))) + r")\b")


@check("pacing_line")
def pacing_line(case: dict, trace: Trace) -> list[Finding]:
    """Pacing a Beat: text before the first tool call is one short line, with no paragraph, no dice and no tool
    names. (An absent line is not flagged.)"""
    out = []
    names = _tool_name_re(trace)
    for i, beat in enumerate(trace.beats):
        idx = next((k for k, e in enumerate(beat.events) if isinstance(e, ToolCall)), None)
        if idx is None:
            continue
        before = beat.text_before(idx).strip()
        if not before:
            continue
        sentences = [s for s in re.split(r"(?<=[.!?…])\s+", before) if s.strip()]
        if "\n" in before or len(sentences) > 2 or len(before) > 300:
            out.append(
                Finding(
                    "pacing_line",
                    i,
                    f"opener before the first call is {len(before)} chars, {len(sentences)} sentences",
                )
            )
        if _DICE_RE.search(before) or (names and names.search(before)):
            out.append(Finding("pacing_line", i, "opener names dice or tools"))
    return out


_META_RE = re.compile(
    r"mcp__|system[- ]reminder|task[- ]tools?\b|\btool (?:call|result|output)s?\b|"
    r"\bpre[-_ ]turn[-_ ]check\b|\bdeferred tools?\b",
    re.IGNORECASE,
)


# The DM's own planning and procedure in the story (DEL-329): "All misses. End combat, award the hoard", "I rolled the
# outcome of your search before writing any of this".
_PROCEDURE_RE = re.compile(
    r"\b(?:end|start) (?:the )?combat\b|\baward (?:the )?(?:hoard|xp|treasure)\b|\bI (?:rolled|will roll|'ll roll)\b|"
    r"\bbefore writing\b",
    re.IGNORECASE,
)


@check("no_meta")
def no_meta(case: dict, trace: Trace) -> list[Finding]:
    """The fourth wall: in-fiction narration never mentions harness housekeeping or tool names, nor the DM's own
    planning and procedure (DEL-329). Out-of-character beats ("(ooc: …") are exempt."""
    out = []
    names = _tool_name_re(trace)
    for i, beat in enumerate(trace.beats):
        if _is_ooc(beat):
            continue
        text = beat.narration
        for m in _META_RE.finditer(text):
            out.append(Finding("no_meta", i, f"narration mentions {m.group(0)!r}"))
        for m in _PROCEDURE_RE.finditer(text):
            out.append(Finding("no_meta", i, f"narration plans or describes the DM's procedure: {m.group(0)!r}"))
        if names:
            for m in names.finditer(text):
                out.append(Finding("no_meta", i, f"narration names tool {m.group(0)!r}"))
    return out


@check("no_state_bypass")
def no_state_bypass(case: dict, trace: Trace) -> list[Finding]:
    """Delve's tools are the only door to campaign state and module text: the DM has no file tools, so any call to a
    tool outside mcp__delve__ (Read, Bash, another MCP server) is a bypass."""
    out = []
    for i, beat in enumerate(trace.beats):
        for call in beat.tool_calls:
            if not call.is_delves:
                out.append(Finding("no_state_bypass", i, f"{call.raw_name} is not one of Delve's tools"))
    return out


def run_checks(case: dict, trace: Trace, names=None) -> list[Finding]:
    names = names or case.get("checks") or list(CHECKS)
    findings = []
    for name in names:
        findings.extend(CHECKS[name](case, trace))
    return findings
