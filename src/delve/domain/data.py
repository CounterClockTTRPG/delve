"""Plain data to and from JSON-shaped dicts, for the frozen dataclasses of the domain.

`from_dict(cls, raw)` checks every key against the dataclass's fields and every value against the field's type
(`str`, `int`, `float`, `bool`, `Literal[…]`, `X | None`, `tuple[X, ...]`, `list[X]`, `dict[K, V]`, nested
dataclasses), and raises `DataError` naming the field. Keys of `dict[int, V]` may come as strings, as JSON makes them.
`to_dict(obj)` is the reverse, with tuples as lists.
"""

from __future__ import annotations

import dataclasses
import types
from collections.abc import Mapping
from functools import cache
from typing import Any, Literal, Union, get_args, get_origin, get_type_hints


class DataError(ValueError):
    """A value that doesn't fit its field; `field` is the path, such as `attacks[0].speed`."""

    def __init__(self, field: str, message: str) -> None:
        self.field = field
        super().__init__(f"{field}: {message}" if field else message)


@cache
def _hints(cls: type) -> dict[str, Any]:
    return get_type_hints(cls)


def _name(tp: Any) -> str:
    return getattr(tp, "__name__", None) or str(tp).replace("typing.", "")


def _decode(tp: Any, value: Any, path: str) -> Any:
    origin, args = get_origin(tp), get_args(tp)
    if tp is Any:
        return value
    if origin in (Union, types.UnionType):
        if value is None and type(None) in args:
            return None
        for option in args:
            if option is type(None):
                continue
            try:
                return _decode(option, value, path)
            except DataError:
                continue
        raise DataError(path, f"expected {' or '.join(_name(a) for a in args)}, got {value!r}")
    if origin is Literal:
        if value not in args:
            raise DataError(path, f"expected one of {', '.join(repr(a) for a in args)}, got {value!r}")
        return value
    if dataclasses.is_dataclass(tp):
        if not isinstance(value, Mapping):
            raise DataError(path, f"expected an object, got {value!r}")
        return from_dict(tp, value, path)
    if origin in (tuple, list):
        if isinstance(value, str | bytes | Mapping) or not hasattr(value, "__iter__"):
            raise DataError(path, f"expected a list, got {value!r}")
        item = args[0] if args else Any
        decoded = [_decode(item, v, f"{path}[{i}]") for i, v in enumerate(value)]
        return tuple(decoded) if origin is tuple else decoded
    if origin is dict:
        if not isinstance(value, Mapping):
            raise DataError(path, f"expected an object, got {value!r}")
        key_type, value_type = args or (Any, Any)
        out = {}
        for k, v in value.items():
            if key_type is int and isinstance(k, str):
                try:
                    k = int(k)
                except ValueError:
                    raise DataError(f"{path}.{k}", "expected a whole-number key") from None
            out[_decode(key_type, k, path)] = _decode(value_type, v, f"{path}.{k}")
        return out
    if tp is bool:
        if not isinstance(value, bool):
            raise DataError(path, f"expected true or false, got {value!r}")
        return value
    if tp is int:
        if isinstance(value, bool) or not isinstance(value, int):
            if isinstance(value, float) and value.is_integer():
                return int(value)
            raise DataError(path, f"expected a whole number, got {value!r}")
        return value
    if tp is float:
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise DataError(path, f"expected a number, got {value!r}")
        return float(value)
    if tp is str:
        if not isinstance(value, str):
            raise DataError(path, f"expected text, got {value!r}")
        return value
    raise DataError(path, f"unsupported field type {_name(tp)}")


def from_dict[T](cls: type[T], raw: Mapping[str, Any], path: str = "") -> T:
    """An instance of the dataclass `cls` from a JSON-shaped dict; missing keys take the field defaults."""
    fields = {f.name: f for f in dataclasses.fields(cls) if f.init}  # type: ignore[arg-type]
    unknown = sorted(set(raw) - set(fields))
    if unknown:
        where = f"{path}." if path else ""
        raise DataError(f"{where}{unknown[0]}", f"unknown field; the fields of {cls.__name__} are {', '.join(fields)}")
    hints = _hints(cls)
    values = {name: _decode(hints[name], value, f"{path}.{name}" if path else name) for name, value in raw.items()}
    try:
        return cls(**values)
    except TypeError as error:  # a required field is missing
        raise DataError(path, str(error)) from None


OMIT_IF_NONE = "omit_if_none"
"""A field's metadata key: with it true, `to_dict` leaves the field out while it is None (an optional key added later,
so that older records' dicts stay as they were)."""


def to_dict(obj: Any) -> Any:
    """A dataclass (or a value inside one) as JSON-shaped data: dicts, lists and scalars; a field marked
    `OMIT_IF_NONE` is left out while it is None."""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {
            f.name: to_dict(getattr(obj, f.name))
            for f in dataclasses.fields(obj)
            if not (f.metadata.get(OMIT_IF_NONE) and getattr(obj, f.name) is None)
        }
    if isinstance(obj, tuple | list):
        return [to_dict(v) for v in obj]
    if isinstance(obj, Mapping):
        return {k: to_dict(v) for k, v in obj.items()}
    return obj
