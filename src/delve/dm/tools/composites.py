"""Composite tools: `batch`, and the scene composites `scout` and `council` (ttrpg2 `tools/composites.py` and
`tools/dice.py`).

Every step the rules owe used to cost the DM a model round trip; composites run the sequence server-side, in order,
and hand back every result at once. `batch` keeps ttrpg2's semantics exactly (`composites.py:40-119`): at most 25 steps
in order, a result or an error per step, `batch` itself denied as a step, and with `stop_on_error` a stop after the
first failing step, which is included. In Delve each step is also its own transaction, so the steps before a failure
stay done. `scout` and `council` are single tools, one transaction each.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from delve.dm.tools import dice
from delve.dm.tools import notes as time
from delve.dm.tools.schema import ToolSpec, array, boolean, integer, params, string, strings, tool
from delve.play.context import CampaignContext, NotFound, PlayError
from delve.rules.classic.checks import CheckError

SPECS: list[ToolSpec] = []

BATCH = "batch"

# A generous ceiling: long enough for a full combat round's worth of bookkeeping, short enough that a runaway list
# can't stall a beat.
_MAX_STEPS = 25

# Tools that must never run inside a batch: nesting (batch-in-batch), and ttrpg2's turn-scoped checklist, should plateau
# 2b bring it back.
_BATCH_DENY = {"batch", "pre_turn_check"}

StepRunner = Callable[[str, dict[str, Any]], dict[str, Any]]


class UnknownTool(LookupError):
    """A step names no tool."""


class StepError(ValueError):
    """A step whose arguments don't fit its tool."""


def batch(
    steps: list[Any], stop_on_error: bool = True, *, run: StepRunner, exists: Callable[[str], bool]
) -> dict[str, Any]:
    """ttrpg2's `batch`: run each step `{tool, args}` through `run`, strictly in order."""
    if not isinstance(steps, list) or not steps:
        return {"error": "steps must be a non-empty list of {tool, args} dicts."}
    if len(steps) > _MAX_STEPS:
        return {"error": f"Too many steps ({len(steps)}); the cap is {_MAX_STEPS}."}

    results: list[dict[str, Any]] = []
    stopped_early = False

    for i, step in enumerate(steps):
        if not isinstance(step, dict):
            results.append({"step": i, "error": f"not a dict: {step!r}"})
            if stop_on_error:
                stopped_early = True
                break
            continue

        name = str(step.get("tool") or "").strip()
        args = step.get("args") or {}
        if not isinstance(args, dict):
            results.append({"step": i, "tool": name, "error": "args must be an object"})
            if stop_on_error:
                stopped_early = True
                break
            continue

        if name in _BATCH_DENY:
            results.append(
                {"step": i, "tool": name, "error": f"'{name}' cannot run inside batch — call it on its own."}
            )
            if stop_on_error:
                stopped_early = True
                break
            continue

        if not exists(name):
            results.append({"step": i, "tool": name, "error": "unknown tool"})
            if stop_on_error:
                stopped_early = True
                break
            continue

        try:
            out = run(name, args)
            entry = {"step": i, "tool": name, "result": out}
        except Exception as exc:  # noqa: BLE001 - ttrpg2: a step that raises is that step's error
            entry = {"step": i, "tool": name, "error": str(exc)}

        results.append(entry)
        if stop_on_error and (
            "error" in entry or (isinstance(entry.get("result"), dict) and "error" in entry["result"])
        ):
            stopped_early = True
            break

    out: dict[str, Any] = {
        "ran": len(results),
        "requested": len(steps),
        "stopped_early": stopped_early,
        "results": results,
    }
    if stopped_early:
        # Said outright, with what never ran (DEL-334: a stopped batch read as done, and its XP awards were lost).
        failed = results[-1]
        error = failed.get("error") or (failed.get("result") or {}).get("error")
        out["not_run"] = [str(s.get("tool") or "?") if isinstance(s, dict) else "?" for s in steps[len(results) :]]
        out["stopped"] = (
            f"Step {failed['step']} ({failed.get('tool') or '?'}) failed: {error}. "
            + (f"These steps did not run: {', '.join(out['not_run'])}." if out["not_run"] else "")
        ).strip()
    return out


@tool(
    SPECS,
    BATCH,
    params(
        "steps",
        steps=array('The calls, in order: [{"tool": "advance_time", "args": {"minutes": 10}}, …]. At most 25.'),
        stop_on_error=boolean("Stop at the first failing step (default true); false runs the rest regardless."),
    ),
    mutates=True,
)
def _batch(ctx: CampaignContext, steps: list[Any], stop_on_error: bool = True) -> dict[str, Any]:
    """Run several tool calls in one round trip, strictly in order, each step as its own call: steps
    [{"tool": "advance_time", "args": {"minutes": 10}}, {"tool": "encounter_check", "args": {"terrain": "dungeon"}}].
    Use it when every step's arguments are known up front; when a later call needs an earlier result (damage after an
    attack), use the purpose-built composite instead (resolve_attack, combat_round, setup_combat, scout, council).
    With stop_on_error (the default) it halts at the first failing step and reports what ran. Not for batch itself.
    At most 25 steps."""
    raise RuntimeError("batch runs in the tool host, step by step")  # pragma: no cover - ToolHost.call runs it


# --- scene composites --------------------------------------------------------------------------------------------


def _answer(fn: Callable[..., dict[str, Any]], ctx: CampaignContext, **args: Any) -> dict[str, Any]:
    """A tool's answer inside a composite: its result, or its refusal as `{"error", "hint"?}`, as ttrpg2's tools
    answered."""
    try:
        return fn(ctx, **args)
    except NotFound as refused:
        out: dict[str, Any] = {"error": refused.message}
        if refused.candidates:
            out["candidates"] = refused.candidates
        return out
    except PlayError as refused:
        return {"error": refused.message, **({"hint": refused.hint} if refused.hint else {})}
    except CheckError as refused:
        return {"error": str(refused), **({"hint": refused.hint} if refused.hint else {})}


@tool(
    SPECS,
    "scout",
    params(
        "character",
        character=string("The scout, a PC or NPC."),
        checks=strings('Skills to roll; default ["move silently", "hide in shadows", "detect noise"].'),
        minutes=integer("The time the move takes (default 10, the dungeon turn).", minimum=0),
        secret=boolean(
            "Whether the checks' dice are kept from the players (default true: a scout can't know whether they were "
            "seen or heard). False for checks the character would know, such as climbing."
        ),
        terrain=string("dungeon, wilderness, road or urban, for the encounter check (default dungeon)."),
    ),
    mutates=True,
    areas=("characters", "world"),
)
def scout(
    ctx: CampaignContext,
    character: str,
    checks: list[str] | None = None,
    minutes: int = 10,
    terrain: str = "dungeon",
    secret: bool = True,
) -> dict[str, Any]:
    """Resolve a scouting move in one call: each named skill check, then the encounter check for the time spent, then
    the clock. checks are the character's skills, partly matched (default move silently, hide in shadows, detect
    noise); pass an explicit list to match the fiction. Rolls happen before you narrate, in this order; a failed
    stealth check is a failed approach. A check the character doesn't have is reported, never substituted. Its dice
    are secret by default: the players don't see them (DEL-273)."""
    if checks is None:
        checks = ["move silently", "hide in shadows", "detect noise"]
    # Each scouting move's checks are their own: another move in the beat, later in game time, rolls fresh.
    occasion = f"scout, {dice.game_time(ctx)}"
    out: dict[str, Any] = {
        "character": character,
        "checks": [
            _answer(dice.skill_check, ctx, character=character, skill=name, occasion=occasion) for name in checks
        ],
        "encounter": _answer(dice.encounter_check, ctx, terrain=terrain),
    }
    if minutes:
        out["time"] = _answer(time.advance_time, ctx, minutes=int(minutes))
    return out


@tool(
    SPECS,
    "council",
    params(
        "npcs",
        npcs=array(
            'The NPCs weighing in: ["Tira", "Shalfey"] or, better, [{"npc": "Tira", "modifier": -4, "interest": "the '
            'relic leaves her temple"}].',
            {"anyOf": [{"type": "string"}, {"type": "object"}]},
        ),
        base_modifier=integer("Added to every NPC's modifier: a persuasive speech, a shared threat."),
    ),
    mutates=True,
    areas=(),
)
def council(ctx: CampaignContext, npcs: list[Any], base_modifier: int = 0) -> dict[str, Any]:
    """Roll a reaction for every NPC weighing in on a proposal: one call, one roll per NPC. Consensus is rolled, never
    assumed. Each NPC votes their own interest, so pass this proposal's modifier per NPC; their disposition is
    already folded in. interest is kept on the record, not used in the maths. If every roll comes back friendly, that
    is the dice talking."""
    if not npcs:
        return {"error": "npcs must be a non-empty list of names or {npc, modifier, interest} dicts."}
    votes: list[dict[str, Any]] = []
    for entry in npcs:
        if isinstance(entry, str):
            name, modifier, interest = entry, 0, ""
        elif isinstance(entry, dict):
            name = str(entry.get("npc") or entry.get("slug") or "")
            modifier = int(entry.get("modifier") or 0)
            interest = str(entry.get("interest") or "")
        else:
            votes.append({"error": f"unusable entry: {entry!r}"})
            continue
        if not name:
            votes.append({"error": f"entry has no npc: {entry!r}"})
            continue
        result = _answer(dice.reaction, ctx, npc=name, modifier=modifier + int(base_modifier))
        vote: dict[str, Any] = {"npc": name, "modifier_applied": modifier + int(base_modifier)}
        if interest:
            vote["interest"] = interest
        vote["reaction"] = result
        votes.append(vote)

    rolled = [v for v in votes if isinstance(v.get("reaction"), dict) and "error" not in v["reaction"]]
    attitudes = [str(v["reaction"].get("result", "")) for v in rolled]
    return {
        "votes": votes,
        "count": len(rolled),
        "attitudes": attitudes,
        "unanimous": bool(attitudes) and len(set(attitudes)) == 1,
    }
