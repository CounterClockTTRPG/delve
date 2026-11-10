"""Reference syntax — `<kind>:<id>[#<fragment>]` (spec §6)."""
from __future__ import annotations

import re
from dataclasses import dataclass

# Kinds that resolve inside the bundle.
INTERNAL_KINDS = (
    "map", "text", "key", "asset",
    "npc", "faction", "quest", "rumor", "secret", "encounter", "pregen",
    "worldmap",
)
# Kinds that name a slug in the consuming system's reference DB.
EXTERNAL_KINDS = ("monster", "item", "spell")
KINDS = INTERNAL_KINDS + EXTERNAL_KINDS

# entity kind (ref prefix) -> manifest `entities` key
ENTITY_REF_KINDS = {
    "npc": "npcs", "faction": "factions", "quest": "quests",
    "rumor": "rumors", "secret": "secrets", "encounter": "encounters",
    "pregen": "pregens",
}

_KIND_ALT = "|".join(KINDS)
REF_RX = re.compile(rf"^({_KIND_ALT}):([^#\s]+)(?:#(\S+))?$")
# In Markdown: [label](npc:x) / ![](asset:x) links, and the [[npc:x]] shorthand.
_MD_LINK_RX = re.compile(rf"\]\(\s*((?:{_KIND_ALT}):[^)\s]+)\s*\)")
_MD_WIKI_RX = re.compile(rf"\[\[\s*((?:{_KIND_ALT}):[^\]\s]+)\s*\]\]")

ID_RX = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


@dataclass(frozen=True)
class Ref:
    kind: str
    id: str
    fragment: str | None = None

    @property
    def external(self) -> bool:
        return self.kind in EXTERNAL_KINDS

    def __str__(self) -> str:
        return f"{self.kind}:{self.id}" + (f"#{self.fragment}" if self.fragment else "")


def parse_ref(s: str) -> Ref | None:
    if not isinstance(s, str):
        return None
    m = REF_RX.match(s.strip())
    if not m:
        return None
    return Ref(m.group(1), m.group(2), m.group(3))


def is_ref(s: object) -> bool:
    return isinstance(s, str) and REF_RX.match(s.strip()) is not None


def refs_in_markdown(md: str) -> list[str]:
    """Every ref used as a link target or `[[…]]` shorthand, in order."""
    out: list[tuple[int, str]] = []
    for rx in (_MD_LINK_RX, _MD_WIKI_RX):
        out += [(m.start(), m.group(1)) for m in rx.finditer(md)]
    return [r for _, r in sorted(out)]


def refs_in_value(value: object) -> list[str]:
    """Walk a YAML/JSON value, collecting strings that are refs, plus refs
    inside long strings (Markdown descriptions)."""
    found: list[str] = []

    def walk(v: object) -> None:
        if isinstance(v, str):
            if is_ref(v):
                found.append(v.strip())
            elif "\n" in v or "](" in v or "[[" in v:
                found.extend(refs_in_markdown(v))
        elif isinstance(v, dict):
            for k, x in v.items():
                if isinstance(k, str) and k.startswith("x-"):
                    continue  # extensions are opaque
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)

    walk(value)
    return found


def slugify(s: str) -> str:
    s = re.sub(r"[^a-z0-9._-]+", "-", s.lower()).strip("-.")
    return s or "x"
