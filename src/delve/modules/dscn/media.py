"""Asset media types — the allow-list, magic-byte sniffing and the SVG
active-content check (spec §9.1)."""
from __future__ import annotations

import base64
import re
import xml.parsers.expat

ALLOWED_TYPES = (
    "image/png", "image/jpeg", "image/webp", "image/gif", "image/svg+xml",
    "application/pdf", "text/plain", "text/markdown", "audio/mpeg", "audio/ogg",
)

IMAGE_TYPES = ("image/png", "image/jpeg", "image/webp", "image/gif", "image/svg+xml")

_SUFFIX_TYPES = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".webp": "image/webp", ".gif": "image/gif", ".svg": "image/svg+xml",
    ".pdf": "application/pdf", ".txt": "text/plain", ".md": "text/markdown",
    ".mp3": "audio/mpeg", ".ogg": "audio/ogg",
}


def type_for_name(name: str) -> str | None:
    dot = name.rfind(".")
    return _SUFFIX_TYPES.get(name[dot:].lower()) if dot >= 0 else None


def sniff(data: bytes) -> str | None:
    """Best-effort media type from content; None if unrecognised."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    if data.startswith(b"OggS"):
        return "audio/ogg"
    if data.startswith(b"ID3") or data[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"):
        return "audio/mpeg"
    head = data[:2048].lstrip(b"\xef\xbb\xbf").lstrip()
    if head.startswith(b"<") and b"<svg" in data[:4096]:
        return "image/svg+xml"
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    return "text/plain"


def type_matches(declared: str, data: bytes) -> bool:
    got = sniff(data)
    if declared in ("text/plain", "text/markdown"):
        return got in ("text/plain",)
    return got == declared


# The SVG check parses the picture with expat and walks what a browser would
# see, instead of matching a pattern over the bytes, which mixed case, a
# namespace prefix (`<svg:script>`) or an entity-encoded `javascript&#58;`
# walked past (DEL-154, audit finding 12). A DOCTYPE with an internal subset
# is refused, so no entity or default attribute is ever declared or expanded;
# a plain one (Illustrator writes it) passes, as expat never fetches its DTD.
_ACTIVE_ELEMENTS = frozenset({
    "script", "foreignobject", "iframe", "embed", "object", "handler", "listener",
})
_ANIMATIONS = frozenset({"set", "animate", "animatemotion", "animatetransform"})
_LINKS = frozenset({"href", "src"})
_CSS_URL_RX = re.compile(r"url\(\s*(['\"]?)(.*?)\1\s*\)", re.IGNORECASE | re.DOTALL)
_URL_NOISE_RX = re.compile(r"[\x00-\x20]+")
_SAFE_DATA = ("data:image/png", "data:image/jpeg", "data:image/gif", "data:image/webp")


class _Active(Exception):
    """Raised from a parser handler: the picture is active, stop reading it."""


def _local(name: str) -> str:
    """A name without its prefix, folded: `svg:Script` and `script` alike."""
    return name.rpartition(":")[2].lower()


def _unsafe_url(value: str, *, local_only: bool = False) -> bool:
    """A link that runs script, holds a document, or reaches outside the
    picture. Browsers drop tabs, newlines and spaces inside a URL's scheme,
    so they are dropped here too before it is read. Only a fragment (`#id`)
    and a raster `data:image/…` stay in; a nested `data:image/svg+xml`
    would be a picture this check never read. `local_only` (`<use>`) takes
    a fragment alone."""
    url = _URL_NOISE_RX.sub("", value).lower()
    if not url or url.startswith("#"):
        return False
    if local_only:
        return True
    return not url.startswith(_SAFE_DATA)


def _unsafe_css(text: str) -> bool:
    if "@import" in text.lower():
        return True
    return any(_unsafe_url(m.group(2)) for m in _CSS_URL_RX.finditer(text))


def _start(name: str, attrs: dict[str, str]) -> None:
    element = _local(name)
    if element in _ACTIVE_ELEMENTS:
        raise _Active(name)
    for attr, value in attrs.items():
        if attr == "xmlns" or attr.startswith("xmlns:"):
            continue
        local = _local(attr)
        if local.startswith("on"):
            raise _Active(attr)
        if local in _LINKS and _unsafe_url(value, local_only=element == "use"):
            raise _Active(attr)
        if local == "style" and _unsafe_css(value):
            raise _Active(attr)
    if element in _ANIMATIONS and _local(attrs.get("attributeName", "")) in _LINKS:
        raise _Active(name)  # it would write a link no check has read


def _refuse(*_args) -> None:
    raise _Active("DOCTYPE, entity or stylesheet")


def svg_is_active(data: bytes) -> bool:
    """True if an SVG carries script, event handlers, foreignObject or
    embedded documents, links that run script or reach outside the picture
    (an external `<use>`, image or stylesheet, CSS `@import` or `url()`), a
    DOCTYPE that declares anything, or is not well-formed XML. Such SVGs are
    rejected, not sanitised — a scenario's art never needs them."""
    parser = xml.parsers.expat.ParserCreate()
    parser.SetParamEntityParsing(xml.parsers.expat.XML_PARAM_ENTITY_PARSING_NEVER)
    parser.StartDoctypeDeclHandler = lambda _name, _system, _public, internal: _refuse() if internal else None
    parser.EntityDeclHandler = _refuse
    parser.ExternalEntityRefHandler = _refuse
    parser.ProcessingInstructionHandler = lambda target, _data: (
        _refuse() if target.lower() == "xml-stylesheet" else None)
    styles: list[str] = []  # the text of <style> elements, read once parsed
    inside = [0]

    def start(name: str, attrs: dict[str, str]) -> None:
        _start(name, attrs)
        if inside[0] or _local(name) == "style":
            inside[0] += 1

    def end(_name: str) -> None:
        inside[0] = max(inside[0] - 1, 0)

    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.CharacterDataHandler = lambda text: styles.append(text) if inside[0] else None
    try:
        parser.Parse(data, True)
    except (_Active, xml.parsers.expat.ExpatError, ValueError):
        return True
    return _unsafe_css("".join(styles))


def data_uri(mime: str, data: bytes) -> str:
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"
