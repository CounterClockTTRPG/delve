"""What a tool is (`ToolSpec`), the JSON Schema of its arguments, and its result as plain JSON.

A tool module lists its tools with `@tool(SPECS, name, params, mutates=…)` on a function `fn(ctx, **args) -> dict`; the
function's docstring, as one paragraph, is the description the DM reads. `params` are built with `params(...)` and the
field helpers, so every schema is an object that names its required arguments and refuses unknown ones. A mutating
tool names the `areas` of the play screen it may change (`AREAS`), so a call tells the table only those (DEL-168).
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import best_match

from delve.dice import Roll, roll_json
from delve.play.context import CampaignContext

# What a mutating tool may change, as the play screen reads it again (DEL-168). Each area but `state` is also an
# event of its own elsewhere; any of them reads the play state again.
AREAS = (
    "characters",  # the sheets: hit points, gear, coin, spells, the party itself
    "map_state",  # where the characters are on a map, and what they have found there (every map's views)
    "combat",  # the fight
    "world",  # the date, the time and the weather, the world map, the quests the party knows
    "state",  # only the play state: the session's number, and what no other area names
)


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    """One paragraph, written for the DM."""
    params: dict[str, Any]
    """The JSON Schema of the arguments: an object."""
    fn: Callable[[CampaignContext, dict[str, Any]], dict[str, Any]]
    mutates: bool
    player_visible: bool
    """Whether the result may appear in the players' feed (through `redact.player_view`). False for DM-only tools."""
    dm_only_keys: tuple[str, ...] = ()
    """Keys of the result that are DM-only wherever they are, besides `dm_only` (plan 2a Task 12)."""
    areas: tuple[str, ...] | None = None
    """The `AREAS` a call may change, which the play screen reads again after it; none for a tool that changes nothing
    a seat reads (a roll, a DM note). None, left out, is every area (DEL-168)."""


def tool(
    specs: list[ToolSpec],
    name: str,
    params: dict[str, Any],
    *,
    mutates: bool,
    player_visible: bool = True,
    dm_only_keys: Iterable[str] = (),
    areas: Iterable[str] | None = None,
) -> Callable[[Callable[..., dict[str, Any]]], Callable[..., dict[str, Any]]]:
    """Add the decorated `fn(ctx, **args)` to `specs` as the tool `name`; its docstring is the description."""

    touched = None if areas is None else tuple(areas)
    unknown = set(touched or ()) - set(AREAS)
    if unknown:
        raise ValueError(f"{name}: unknown areas {sorted(unknown)}")

    def register(fn: Callable[..., dict[str, Any]]) -> Callable[..., dict[str, Any]]:
        description = " ".join((fn.__doc__ or "").split())
        specs.append(
            ToolSpec(
                name=name,
                description=description,
                params=params,
                fn=lambda ctx, args: fn(ctx, **args),
                mutates=mutates,
                player_visible=player_visible,
                dm_only_keys=tuple(dm_only_keys),
                areas=touched,
            )
        )
        return fn

    return register


# --- the schemas -------------------------------------------------------------------------------------------------


def params(*required: str, **properties: dict[str, Any]) -> dict[str, Any]:
    """An object schema with these properties, the `required` ones named, and no others allowed."""
    missing = [name for name in required if name not in properties]
    if missing:
        raise ValueError(f"required but not a property: {', '.join(missing)}")
    return {"type": "object", "properties": properties, "required": list(required), "additionalProperties": False}


def string(description: str, **extra: Any) -> dict[str, Any]:
    return {"type": "string", "description": description, **extra}


def integer(description: str, **extra: Any) -> dict[str, Any]:
    return {"type": "integer", "description": description, **extra}


def boolean(description: str, **extra: Any) -> dict[str, Any]:
    return {"type": "boolean", "description": description, **extra}


def array(description: str, items: dict[str, Any] | None = None, **extra: Any) -> dict[str, Any]:
    return {"type": "array", "description": description, **({"items": items} if items else {}), **extra}


def obj(description: str, **extra: Any) -> dict[str, Any]:
    return {"type": "object", "description": description, **extra}


def strings(description: str) -> dict[str, Any]:
    return array(description, {"type": "string"})


def check_schema(schema: dict[str, Any]) -> None:
    """Raise `jsonschema.SchemaError` when `schema` isn't a valid JSON Schema (2020-12)."""
    Draft202012Validator.check_schema(schema)


def mismatch(schema: dict[str, Any], args: Mapping[str, Any]) -> str | None:
    """Why `args` don't fit `schema`, in one line; None when they fit."""
    error = best_match(Draft202012Validator(schema).iter_errors(args))
    if error is None:
        return None
    where = ".".join(str(p) for p in error.absolute_path)
    return f"{where}: {error.message}" if where else error.message


def usage(spec: ToolSpec) -> str:
    """The arguments of a tool, for a hint: `name(required, optional?)`."""
    properties = spec.params.get("properties", {})
    required = spec.params.get("required", [])
    names = [n if n in required else f"{n}?" for n in properties]
    return f"{spec.name}({', '.join(names)})"


# --- results as JSON ---------------------------------------------------------------------------------------------


def plain(value: Any) -> Any:
    """`value` as JSON: rolls as `roll_json`, dataclasses as objects, tuples and sets as lists, keys as strings."""
    if isinstance(value, Roll):
        return roll_json(value)
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: plain(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, Mapping):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, frozenset | set):
        return sorted(plain(v) for v in value)
    if isinstance(value, list | tuple):
        return [plain(v) for v in value]
    return value
