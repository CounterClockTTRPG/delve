"""The world-map language, ported from ttrpg2's `tools/world_map.py` (its `WORLD-MAP-PLAN.md` is the design).

Block-based, Structurizr-style; whitespace-insensitive, `#` comments, statements end at a newline or `;`:

    workspace <ident> {
        styles { <selector> { <attr> <value>; … } … }      # kind | kind.prop<op>value | [tag]
        model {
            kingdom <ident> { <props> }
            city <ident> { at x,y; pop n; in <ident>; contains { <features> } }
            road <ident> { from <ident>; to <ident>; via x,y …; surface dirt }
            river <ident> { points x,y … }
            terrain <ident> { polygon x,y …; biome forest }
            poi <ident> { at x,y; kind event }
            dungeon <ident> { in <ident.path>; room <ident> { at x,y size w,h }; passage { from a; to b } }
        }
        views { view <ident> { scope <ident>; include cities, roads, …; units miles; scale n; styles { … } } }
    }

`!include <name>` inlines another text anywhere a statement fits. ttrpg2 read it from the campaign folder; here the
caller hands the texts in (`includes`, by the name the directive gives), and the port reads no file. Every feature may
carry `description "…"`, `tags [a, b]` and `doc <path>`, which only the DM ever sees.

Only the language came over. What changed: errors are `WorldMapError(line, message)`, with the line in the text
given (an error inside an include names the `!include` line and the include's own line); text after the workspace
is refused instead of ignored; and the feature index is `WorldModel.index`.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

MAX_INCLUDE_DEPTH = 8

KINDS = frozenset(
    {"kingdom", "city", "road", "river", "lake", "terrain", "poi", "building", "street", "dungeon", "room", "passage"}
)
"""The twelve feature kinds. The set is closed: a new kind needs code."""


class WorldMapError(Exception):
    """A world map that doesn't read: `line` (1-based, in the text given; None when no line applies) and `message`."""

    def __init__(self, line: int | None, message: str) -> None:
        self.line = line
        self.message = message
        super().__init__(f"line {line}: {message}" if line is not None else message)


# --- the model -------------------------------------------------------------------------------------------------------


@dataclass
class Coord:
    x: float
    y: float


@dataclass
class IdentPath:
    """A dotted reference, e.g. `orlane.temple-merikka`."""

    parts: list[str]

    @property
    def text(self) -> str:
        return ".".join(self.parts)


@dataclass
class Property:
    name: str
    values: list[Any]
    """Numbers, strings, `Coord`s, `IdentPath`s; the tags for `tags`."""
    line: int = 0


@dataclass
class StyleRule:
    """One `selector { attrs }` rule. The selector is `{"kind"}`, `{"kind", "prop", "op", "value"}` or `{"tag"}`."""

    selector: dict[str, Any]
    attrs: dict[str, Any]
    line: int = 0


@dataclass
class Feature:
    kind: str
    name: str
    """Its identifier; empty for a `passage`, the one feature without a name."""
    properties: dict[str, Property] = field(default_factory=dict)
    children: list[Feature] = field(default_factory=list)
    """The features of its `contains` block, or a dungeon's rooms and passages."""
    line: int = 0

    def get(self, prop: str, default: Any = None) -> Any:
        p = self.properties.get(prop)
        return p.values if p is not None else default

    def get_one(self, prop: str, default: Any = None) -> Any:
        p = self.properties.get(prop)
        if p is None or not p.values:
            return default
        return p.values[0]


@dataclass
class View:
    name: str
    properties: dict[str, Property] = field(default_factory=dict)
    styles: list[StyleRule] = field(default_factory=list)
    line: int = 0


@dataclass
class WorldModel:
    """A parsed and checked world map: ttrpg2's `Workspace`."""

    name: str
    styles: list[StyleRule] = field(default_factory=list)
    model: list[Feature] = field(default_factory=list)
    views: list[View] = field(default_factory=list)
    index: dict[str, Feature] = field(default_factory=dict)
    """Every named feature by its path: `orlane`, `orlane.golden-grain-inn`."""


# --- the preprocessor ------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Origin:
    line: int
    """The line in the text given."""
    include: str | None = None
    """The include it came from, and its line there."""
    include_line: int = 0


def _preprocess(
    text: str, includes: Mapping[str, str], seen: tuple[str, ...] = (), parent: _Origin | None = None
) -> tuple[list[str], list[_Origin]]:
    """The text with every `!include` inlined, and where each of its lines came from."""
    if len(seen) > MAX_INCLUDE_DEPTH:
        raise WorldMapError(parent.line if parent else None, f"!include nesting deeper than {MAX_INCLUDE_DEPTH}")
    lines: list[str] = []
    origins: list[_Origin] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        # A line of an include is placed at the root's `!include` line, and named by the innermost include.
        here = _Origin(number) if parent is None else _Origin(parent.line, seen[-1], number)
        stripped = raw.lstrip()
        if not stripped.startswith("!include"):
            lines.append(raw)
            origins.append(here)
            continue
        target = stripped[len("!include") :].strip().strip('"')
        if not target:
            raise _located(here, "!include needs a name")
        if target in seen:
            raise _located(here, f"!include cycle at {target!r}")
        if target not in includes:
            raise _located(here, f"!include not found: {target!r}")
        inner, inner_origins = _preprocess(includes[target], includes, (*seen, target), here)
        lines.extend(inner)
        origins.extend(inner_origins)
    return lines, origins


def _located(origin: _Origin, message: str) -> WorldMapError:
    if origin.include is None:
        return WorldMapError(origin.line, message)
    return WorldMapError(origin.line, f"{message} (in {origin.include}, line {origin.include_line})")


# --- the tokenizer ---------------------------------------------------------------------------------------------------


@dataclass
class _Token:
    type: str
    value: Any
    line: int


# Order matters: STRING before HEX and COMMENT (a '#' inside a string is text); HEX before COMMENT (#abc is a colour,
# '# foo' a comment); COORD before NUMBER ('412,308' is one token).
_TOKEN_RE = re.compile(
    r"""
    (?P<STRING>   "(?:[^"\\\n]|\\.)*" )
    | (?P<HEX>      \#[0-9a-fA-F]{3,8}\b )
    | (?P<COMMENT>  \#[^\n]* )
    | (?P<NEWLINE>  \n )
    | (?P<WS>       [ \t\r]+ )
    | (?P<COORD>    -?\d+(?:\.\d+)?,-?\d+(?:\.\d+)? )
    | (?P<NUMBER>   -?\d+(?:\.\d+)? )
    | (?P<OP>       != | >= | <= | = | > | < )
    | (?P<LBRACE>   \{ )
    | (?P<RBRACE>   \} )
    | (?P<LBRACKET> \[ )
    | (?P<RBRACKET> \] )
    | (?P<COMMA>    , )
    | (?P<SEMI>     ; )
    | (?P<IDENT>    [a-zA-Z_][\w./-]* )
    """,
    re.VERBOSE,
)


def _number(raw: str) -> float | int:
    return float(raw) if "." in raw else int(raw)


def _tokenize(text: str) -> list[_Token]:
    tokens: list[_Token] = []
    line = 1
    pos = 0
    while pos < len(text):
        m = _TOKEN_RE.match(text, pos)
        if not m:
            raise WorldMapError(line, f"unexpected character {text[pos]!r}")
        kind, raw = m.lastgroup or "", m.group()
        pos = m.end()
        if kind in ("WS", "COMMENT"):
            continue
        if kind == "NEWLINE":
            tokens.append(_Token("NEWLINE", "\n", line))
            line += 1
        elif kind == "STRING":
            tokens.append(_Token("STRING", raw[1:-1].replace('\\"', '"').replace("\\\\", "\\"), line))
        elif kind == "HEX":
            tokens.append(_Token("HEX", raw.lower(), line))
        elif kind == "NUMBER":
            tokens.append(_Token("NUMBER", _number(raw), line))
        elif kind == "COORD":
            xs, ys = raw.split(",")
            tokens.append(_Token("COORD", Coord(_number(xs), _number(ys)), line))
        else:
            tokens.append(_Token(kind, raw, line))
    tokens.append(_Token("EOF", None, line))
    return tokens


# --- the parser ------------------------------------------------------------------------------------------------------

_COORD_LIST_PROPS = {"polygon", "points", "via"}
_CHILD_KINDS = {"room", "building", "street", "passage"}
"""The kinds that, written straight inside a feature (without `contains`), are its children."""


def _shown(token: _Token) -> str:
    return "end of text" if token.type == "EOF" else f"{token.type} {token.value!r}"


class _Parser:
    def __init__(self, tokens: list[_Token]) -> None:
        self.tokens = tokens
        self.pos = 0

    def peek(self) -> _Token:
        return self.tokens[min(self.pos, len(self.tokens) - 1)]

    def at(self, type_: str, value: Any = None) -> bool:
        t = self.peek()
        return t.type == type_ and (value is None or t.value == value)

    def consume(self, type_: str, value: Any = None) -> _Token:
        t = self.peek()
        if t.type != type_:
            raise WorldMapError(t.line, f"expected {value or type_}, got {_shown(t)}")
        if value is not None and t.value != value:
            raise WorldMapError(t.line, f"expected {value!r}, got {t.value!r}")
        self.pos += 1
        return t

    def skip_term(self) -> None:
        while self.peek().type in ("NEWLINE", "SEMI"):
            self.pos += 1

    def parse(self) -> WorldModel:
        self.skip_term()
        self.consume("IDENT", "workspace")
        ws = WorldModel(name=self.consume("IDENT").value)
        self.consume("LBRACE")
        while True:
            self.skip_term()
            t = self.peek()
            if t.type == "RBRACE":
                break
            if t.type != "IDENT":
                raise WorldMapError(t.line, f"expected a section (styles, model or views), got {_shown(t)}")
            if t.value == "styles":
                ws.styles.extend(self.parse_styles_block())
            elif t.value == "model":
                ws.model.extend(self.parse_model_block())
            elif t.value == "views":
                ws.views.extend(self.parse_views_block())
            else:
                raise WorldMapError(t.line, f"unknown workspace section {t.value!r}")
        self.consume("RBRACE")
        self.skip_term()
        if not self.at("EOF"):
            raise WorldMapError(self.peek().line, f"unexpected {_shown(self.peek())} after the workspace")
        return ws

    # --- styles

    def parse_styles_block(self) -> list[StyleRule]:
        self.consume("IDENT", "styles")
        self.consume("LBRACE")
        rules: list[StyleRule] = []
        while True:
            self.skip_term()
            if self.at("RBRACE"):
                break
            rules.append(self.parse_style_rule())
        self.consume("RBRACE")
        return rules

    def parse_style_rule(self) -> StyleRule:
        line = self.peek().line
        selector: dict[str, Any]
        if self.at("LBRACKET"):
            self.consume("LBRACKET")
            selector = {"tag": self.consume("IDENT").value}
            self.consume("RBRACKET")
        else:
            kind_full = self.consume("IDENT").value
            if "." in kind_full:
                kind, prop = kind_full.split(".", 1)
                op = self.consume("OP").value
                selector = {"kind": kind, "prop": prop, "op": op, "value": self.parse_scalar()}
            else:
                selector = {"kind": kind_full}
        self.consume("LBRACE")
        attrs: dict[str, Any] = {}
        while True:
            self.skip_term()
            if self.at("RBRACE"):
                break
            key = self.consume("IDENT").value
            attrs[key] = self.parse_scalar()
        self.consume("RBRACE")
        return StyleRule(selector=selector, attrs=attrs, line=line)

    def parse_scalar(self) -> Any:
        t = self.peek()
        if t.type in ("NUMBER", "STRING", "HEX", "IDENT"):
            self.pos += 1
            return t.value
        raise WorldMapError(t.line, f"expected a value, got {_shown(t)}")

    # --- model

    def parse_model_block(self) -> list[Feature]:
        self.consume("IDENT", "model")
        self.consume("LBRACE")
        features: list[Feature] = []
        while True:
            self.skip_term()
            if self.at("RBRACE"):
                break
            features.append(self.parse_feature())
        self.consume("RBRACE")
        return features

    def parse_feature(self) -> Feature:
        kind_tok = self.consume("IDENT")
        name = "" if kind_tok.value == "passage" else self.consume("IDENT").value
        feat = Feature(kind=kind_tok.value, name=name, line=kind_tok.line)
        self.consume("LBRACE")
        while True:
            self.skip_term()
            if self.at("RBRACE"):
                break
            t = self.peek()
            if t.type == "IDENT" and t.value == "contains":
                self.pos += 1
                self.consume("LBRACE")
                while True:
                    self.skip_term()
                    if self.at("RBRACE"):
                        break
                    feat.children.append(self.parse_feature())
                self.consume("RBRACE")
            elif t.type == "IDENT" and t.value in _CHILD_KINDS:
                feat.children.append(self.parse_feature())
            else:
                self.parse_property_into(feat.properties)
        self.consume("RBRACE")
        return feat

    def parse_property_into(self, dst: dict[str, Property]) -> None:
        name_tok = self.consume("IDENT")
        name = name_tok.value
        values: list[Any] = []
        if name in _COORD_LIST_PROPS:
            while self.peek().type in ("COORD", "NUMBER"):
                if self.peek().type == "NUMBER":
                    t = self.peek()
                    raise WorldMapError(t.line, f"{name!r} expects coord pairs (x,y), got a bare number {t.value}")
                values.append(self.consume("COORD").value)
        elif name == "tags":
            self.consume("LBRACKET")
            while not self.at("RBRACKET"):
                values.append(self.consume("IDENT").value)
                if self.at("COMMA"):
                    self.pos += 1
            self.consume("RBRACKET")
        elif name == "include":
            while True:
                t = self.peek()
                if t.type == "COMMA":
                    self.pos += 1
                elif t.type == "IDENT":
                    self.pos += 1
                    values.append(t.value)
                else:
                    break
        else:
            # Every other property takes one value, so `at 0,0 size 4,4` is two properties without a `;`.
            t = self.peek()
            if t.type in ("NEWLINE", "SEMI", "RBRACE", "EOF"):
                pass  # a flag without a value
            elif t.type in ("COORD", "NUMBER", "STRING", "HEX"):
                self.pos += 1
                values.append(t.value)
            elif t.type == "IDENT":
                self.pos += 1
                values.append(IdentPath(t.value.split(".")) if "." in t.value else t.value)
            else:
                raise WorldMapError(t.line, f"property {name!r}: unexpected {_shown(t)}")
        dst[name] = Property(name=name, values=values, line=name_tok.line)

    # --- views

    def parse_views_block(self) -> list[View]:
        self.consume("IDENT", "views")
        self.consume("LBRACE")
        views: list[View] = []
        while True:
            self.skip_term()
            if self.at("RBRACE"):
                break
            views.append(self.parse_view())
        self.consume("RBRACE")
        return views

    def parse_view(self) -> View:
        view_tok = self.consume("IDENT", "view")
        v = View(name=self.consume("IDENT").value, line=view_tok.line)
        self.consume("LBRACE")
        while True:
            self.skip_term()
            if self.at("RBRACE"):
                break
            if self.at("IDENT", "styles"):
                v.styles.extend(self.parse_styles_block())
            else:
                self.parse_property_into(v.properties)
        self.consume("RBRACE")
        return v


# --- the second pass: the index and the references -------------------------------------------------------------------


def ident_text(value: Any) -> str:
    return value.text if isinstance(value, IdentPath) else str(value)


def _validate(ws: WorldModel) -> None:
    index: dict[str, Feature] = {}

    def walk(features: list[Feature], parent: str = "") -> None:
        for f in features:
            if f.kind not in KINDS:
                raise WorldMapError(f.line, f"unknown feature kind {f.kind!r}")
            path = f"{parent}.{f.name}" if parent else f.name
            if f.name:
                if path in index:
                    raise WorldMapError(f.line, f"duplicate identifier {path!r} (already at line {index[path].line})")
                index[path] = f
            walk(f.children, path)

    walk(ws.model)

    def resolves(text: str, scope: str) -> bool:
        if text in index:
            return True
        while scope:
            if f"{scope}.{text}" in index:
                return True
            scope = scope.rsplit(".", 1)[0] if "." in scope else ""
        return False

    def check_refs(features: list[Feature], scope: str = "") -> None:
        for f in features:
            for prop in ("from", "to", "in"):
                p = f.properties.get(prop)
                if p and p.values and not resolves(ident_text(p.values[0]), scope):
                    raise WorldMapError(p.line, f"unresolved reference {ident_text(p.values[0])!r}")
            check_refs(f.children, f"{scope}.{f.name}" if scope else f.name)

    check_refs(ws.model)

    for v in ws.views:
        scope = v.properties.get("scope")
        if scope and scope.values:
            text = ident_text(scope.values[0])
            if text != ws.name and text not in index:
                raise WorldMapError(v.line, f"view {v.name!r}: scope {text!r} is neither the workspace nor a feature")
    ws.index = index


# --- the entry points ------------------------------------------------------------------------------------------------


def parse(text: str, includes: Mapping[str, str] | None = None) -> WorldModel:
    """The checked model of a world map's DSL `text`; `includes` holds the texts its `!include`s name. Raises
    `WorldMapError` with the line, in `text`, of what doesn't read."""
    lines, origins = _preprocess(text, includes or {})
    try:
        ws = _Parser(_tokenize("\n".join(lines))).parse()
        _validate(ws)
    except WorldMapError as e:
        if e.line is None or not origins:
            raise
        raise _located(origins[min(e.line, len(origins)) - 1], e.message) from None
    return ws


def is_workspace(text: str) -> bool:
    """Whether `text` is a whole world map (it starts with `workspace`), not a fragment that others `!include`."""
    for raw in text.splitlines():
        s = raw.strip()
        if s and not s.startswith("#"):
            return bool(re.match(r"workspace\b", s))
    return False
