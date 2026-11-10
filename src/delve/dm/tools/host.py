"""The DM's tool host: transport-neutral, so plateau 2b serves it over MCP and the tests call it directly (spec §6.3).

`call` validates the arguments against the tool's schema, opens a `CampaignContext` for the campaign and beat, and
runs the tool in one `storage.transaction()`: its writes, rolls and events commit together or not at all. A refusal
(an unknown name, a rule the state refuses, bad notation) answers `{"error", "hint"?, "candidates"?}` and rolls the
call back; it never raises. `batch` is the one tool that isn't one transaction: each of its steps is its own call.

The host watches the dice of each call (and of each batch step) and puts their ids in `rolled` (DEL-270), never in
the answer the DM reads: the table takes them when it writes the call's story row.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from delve.dice import BadNotation, Rng, watching
from delve.dm.tools import (
    combat,
    composites,
    dice,
    factions,
    house_rules,
    images,
    lookups,
    lore,
    map,
    merchant,
    module,
    notes,
    party,
    pictures,
    possessions,
    pregens,
    rolled,
    say,
    tell,
    travel,
    world,
)
from delve.dm.tools.schema import ToolSpec, mismatch, plain, usage
from delve.domain.campaigns import MissingPack
from delve.domain.data import DataError
from delve.domain.settings import Job
from delve.packs.catalogs import IN_TREE, Catalogs
from delve.play.clock import Clock, SystemClock
from delve.play.context import NotFound, PlayError, always_paid, context_for
from delve.rules.catalog import entry as ruleset_entry
from delve.rules.classic.checks import CheckError
from delve.rules.ruleset import NO_LOOKUPS
from delve.storage.interfaces import Storage

__all__ = ["NO_LOOKUPS_ERROR", "ToolHost", "ToolSpec", "all_specs"]

NO_LOOKUPS_ERROR = "the ruleset has no lookups"


def all_specs() -> list[ToolSpec]:
    """Every tool of the DM's surface, in the order the DM is shown them."""
    return [
        *lookups.SPECS,
        *lore.SPECS,
        *dice.SPECS,
        *party.SPECS,
        *possessions.SPECS,
        *combat.SPECS,
        *map.SPECS,
        *module.SPECS,
        *pregens.SPECS,
        *images.SPECS,
        *pictures.SPECS,
        *tell.SPECS,
        *say.SPECS,
        *notes.SPECS,
        *world.SPECS,
        *travel.SPECS,
        *factions.SPECS,
        *house_rules.SPECS,
        *merchant.SPECS,
        *composites.SPECS,
    ]


def error(message: str, hint: str = "", candidates: Iterable[Any] | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"error": message}
    if hint:
        out["hint"] = hint
    if candidates:
        out["candidates"] = list(candidates)
    return out


def unwrapped(spec: ToolSpec, args: dict[str, Any]) -> dict[str, Any]:
    """`args` without a stray `args` key, for a tool with no `args` of its own: the DM sometimes nests the batch
    step's shape in a call's arguments (`{"args": null, "text": …}`). A null one is dropped, an object one opened
    when its keys don't clash with the others; anything else is left for the schema to refuse."""
    if "args" not in args or "args" in spec.params.get("properties", {}):
        return args
    inner = args["args"]
    rest = {k: v for k, v in args.items() if k != "args"}
    if inner is None:
        return rest
    if isinstance(inner, dict) and not inner.keys() & rest.keys():
        return {**rest, **inner}
    return args


class ToolHost:
    """The tools of `specs` (the whole surface by default) over one storage. `rng_factory` makes the
    dice of each call: `SystemRng` in play, a `SeededRng` in tests. `image_paid` is the paid-images gate the pictures
    ask (`CampaignContext.image_paid`). `dice_out` is where each call's dice go for its story row (DEL-270). A campaign
    whose ruleset has no lookups (a pack's whose `pack.db` isn't built) answers every tool with
    `{"error": "the ruleset has no lookups"}`. Its calls keep time by `clock` (the app's, `AppServices.clock`), the
    system's without one."""

    def __init__(
        self,
        storage: Storage,
        rng_factory: Callable[[], Rng],
        *,
        specs: Iterable[ToolSpec] | None = None,
        image_paid: Callable[[Job], bool] = always_paid,
        dice_out: rolled.Rolled = rolled.ROLLED,
        catalogs: Catalogs = IN_TREE,
        clock: Clock | None = None,
    ) -> None:
        self.storage = storage
        self.clock = clock or SystemClock()
        self.rng_factory = rng_factory
        self.image_paid = image_paid
        self.dice_out = dice_out
        self.catalogs = catalogs
        self._specs = {spec.name: spec for spec in (all_specs() if specs is None else specs)}

    def specs(self) -> list[ToolSpec]:
        return list(self._specs.values())

    def spec(self, name: str) -> ToolSpec | None:
        return self._specs.get(name)

    def call(self, campaign_id: str, beat: str, name: str, args: dict[str, Any]) -> dict[str, Any]:
        """Run the tool `name` with `args` for the campaign in this beat; its answer as a JSON object. What it rolled
        goes to `dice_out`, for every call, a refused one too, so calls alike stay in step with their rows."""
        dice: rolled.CallDice = {"rolls": []}
        try:
            return self._call(campaign_id, beat, name, args, dice)
        finally:
            self.dice_out.put(campaign_id, beat, name, args, dice)

    def _call(
        self, campaign_id: str, beat: str, name: str, args: dict[str, Any], dice: rolled.CallDice
    ) -> dict[str, Any]:
        spec = self._specs.get(name)
        if spec is None:
            return error(f"Unknown tool '{name}'.", "See the tool list.")
        if not isinstance(args, dict):
            return error("args must be an object", f"Call it as {usage(spec)}.")
        args = unwrapped(spec, args)
        wrong = mismatch(spec.params, args)
        if wrong is not None:
            return error(f"Bad arguments for {name}: {wrong}", f"Call it as {usage(spec)}.")
        if spec.name == composites.BATCH:
            steps: dict[int, list[str]] = {}
            dice.clear()
            dice["steps"] = steps
            run = self._step(campaign_id, beat, args.get("steps"), steps)
            return composites.batch(**args, run=run, exists=self._specs.__contains__)
        return self._run(spec, campaign_id, beat, args, dice["rolls"])

    def _run(
        self, spec: ToolSpec, campaign_id: str, beat: str, args: dict[str, Any], rolls: list[str] | None = None
    ) -> dict[str, Any]:
        """One call in one transaction; the ids of the rolls it returned go to `rolls`, once each, in order, when it
        isn't rolled back (DEL-270)."""
        try:
            with self.storage.transaction(), watching() as seen:
                ctx = context_for(
                    self.storage,
                    campaign_id,
                    beat,
                    self.rng_factory(),
                    image_paid=self.image_paid,
                    catalogs=self.catalogs,
                    clock=self.clock,
                )
                if ctx.lookups is NO_LOOKUPS:
                    # Only a ruleset with lookups can play; a pack's ruleset that reads its `pack.db` has none until
                    # that is built.
                    found = ruleset_entry(ctx.ruleset.id, self.catalogs.rulesets) if ctx.ruleset else None
                    if found is not None:
                        return error(NO_LOOKUPS_ERROR, f"Run: delve pack rebuild {found.id}")
                    return error(NO_LOOKUPS_ERROR, "Play a campaign whose ruleset has lookups.")
                answer = plain(spec.fn(ctx, dict(args)))
            if rolls is not None:
                rolls.extend(dict.fromkeys(roll.id for roll in seen if roll.id not in rolls))
            return answer
        except MissingPack as missing:
            return error(missing.message, "Install its pack, or play another campaign.")
        except NotFound as refused:
            return error(refused.message, refused.hint, refused.candidates)
        except PlayError as refused:
            return error(refused.message, refused.hint)
        except CheckError as refused:
            return error(str(refused), refused.hint, refused.candidates)
        except BadNotation as refused:
            return error(str(refused), refused.hint)
        except DataError as refused:
            return error(str(refused), f"Call it as {usage(spec)}.")

    def _step(self, campaign_id: str, beat: str, asked: Any, rolls: dict[int, list[str]]) -> composites.StepRunner:
        """How `batch` runs one step: as a call of its own, so in its own transaction. A schema mismatch is the
        step's error, as a validation error raised in ttrpg2; a tool's refusal is its result. Each step's dice go to
        `rolls` under its index in `asked`, the batch's steps: `batch` runs them in order, so a step is the next one
        asked that has its tool and arguments (DEL-270)."""
        listed = asked if isinstance(asked, list) else []
        after = 0

        def index_of(name: str, args: dict[str, Any]) -> int | None:
            nonlocal after
            for i in range(after, len(listed)):
                step = listed[i]
                same = isinstance(step, dict) and str(step.get("tool") or "").strip() == name
                if same and (step.get("args") or {}) == args:
                    after = i + 1
                    return i
            return None

        def run(name: str, args: dict[str, Any]) -> dict[str, Any]:
            index = index_of(name, args)
            spec = self._specs.get(name)
            if spec is None:
                raise composites.UnknownTool(name)
            args = unwrapped(spec, args)
            wrong = mismatch(spec.params, args)
            if wrong is not None:
                raise composites.StepError(f"Bad arguments for {name}: {wrong}. Call it as {usage(spec)}.")
            if index is None:
                return self._run(spec, campaign_id, beat, args)
            return self._run(spec, campaign_id, beat, args, rolls.setdefault(index, []))

        return run
