"""Checks every request passes before it reaches a route (spec §11), and the headers every response carries."""

from __future__ import annotations

import fcntl
import ipaddress
import os
import re
import secrets
import socket
import struct
from collections.abc import Iterable, Mapping
from pathlib import Path
from urllib.parse import urlsplit

from starlette.datastructures import Headers
from starlette.requests import HTTPConnection
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from delve.play.avatars import AVATAR_LIMIT, AVATAR_TYPES
from delve.play.module_banners import BANNER_LIMIT, BANNER_TYPES
from delve.play.talk_pictures import TALK_PICTURE_LIMIT, TALK_PICTURE_TYPES

# Every source is this host: no CDN. The map editor's Monaco worker comes from the bundle, or a blob made from it.
# `form-action 'self'`: a form that markup slipped onto a page can't post off-site (DEL-151).
CSP = (
    "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; object-src 'none'; "
    "base-uri 'none'; frame-ancestors 'none'; form-action 'self'; worker-src 'self' blob:"
)
SECURITY_HEADERS = [
    (b"content-security-policy", CSP.encode()),
    (b"x-content-type-options", b"nosniff"),
]
PORTRAIT_EDITOR_PATH = "/vendor/portraitgen/web/"
"""portraitgen's own editor, unchanged (DEL-238): the sheet's Edit portrait shows it in a frame, so Delve's own pages,
and only they, may frame it."""
PORTRAIT_EDITOR_HEADERS = [
    (b"content-security-policy", CSP.replace("frame-ancestors 'none'", "frame-ancestors 'self'").encode()),
    (b"x-content-type-options", b"nosniff"),
]
WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
# The writes that aren't JSON: a `.dscn` upload, an attachment's bytes, a book to convert, a world map's picture to
# read, an avatar, a module's banner, a picture pasted into table talk, and a board post's picture. None of their
# types is CORS-safelisted, so a cross-site form can't send one; `text/plain` would be, and isn't taken.
UPLOAD_PATH = "/api/modules/import"
UPLOAD_TYPES = frozenset({"application/zip", "application/vnd.dscn+zip"})
UPLOAD_LIMIT = 64 * 1024 * 1024
# The most bytes a JSON body may have (DEL-159): a whole module is about 2 MB, a map's source under 1 MB. It's
# checked before the body reaches a route, and so before anyone is known to be logged in.
JSON_LIMIT = 8 * 1024 * 1024
JSON_TOO_LONG = f"a JSON body may be at most {JSON_LIMIT} bytes"
ATTACHMENT_PATH = re.compile(r"/api/modules/[^/]+/assets")
ATTACHMENT_TYPES = frozenset({"image/png", "image/jpeg", "image/webp", "image/gif", "image/svg+xml", "application/pdf"})
CONVERSION_PDF_PATH = "/api/conversions/pdf"
PDF_TYPE = "application/pdf"
PDF_LIMIT = 256 * 1024 * 1024
"""Books are large: the conversion's upload streams to a temporary file, never to memory."""
CONVERSION_WORLDMAP_PATH = "/api/conversions/worldmap"
WORLDMAP_TYPES = frozenset({"image/png", "image/jpeg", "image/webp"})
"""A world map's picture to read (plan 7 Task 12): at most `UPLOAD_LIMIT` bytes, streamed to a temporary file too."""
PACK_UPLOAD_PATH = "/api/packs"
"""A ruleset's or a setting's `.delvepack` to install (DEL-366): a zip, at most `PACK_LIMIT` bytes, streamed to a
temporary file; the owner's alone."""
PACK_TYPES = frozenset({"application/zip", "application/octet-stream", "application/x-zip-compressed"})
PACK_LIMIT = 256 * 1024 * 1024
ADDITIONS_PATH = re.compile(r"/api/settings/[^/]+/additions")
"""A file of a setting's additions to import (DEL-366): a zip, at most `ADDITIONS_LIMIT` bytes."""
ADDITIONS_LIMIT = 128 * 1024 * 1024
BANNER_UPLOAD_PATH = re.compile(r"/api/modules/[^/]+/banner/upload")
"""A module's banner picture (DEL-123): one of `BANNER_TYPES`, at most `BANNER_LIMIT` bytes."""
TALK_PICTURE_PATH = re.compile(r"/api/campaigns/[^/]+/talk/picture")
"""A picture pasted into table talk (DEL-294): one of `TALK_PICTURE_TYPES`, at most `TALK_PICTURE_LIMIT` bytes."""
BOARD_PICTURE_PATH = re.compile(r"/api/board/posts/[^/]+/picture")
"""A picture in a board post (DEL-297): as a talk picture, one of `TALK_PICTURE_TYPES`, at most `TALK_PICTURE_LIMIT`
bytes."""
AVATAR_PATH = "/api/account/avatar"
"""An account's avatar picture (players and tavern Task D3): one of `AVATAR_TYPES`, at most `AVATAR_LIMIT` bytes."""
OFF_LINK_PATH = re.compile(r"/api/mail/off/[^/]+")
"""An email's one-click off link (DEL-314): a mail program posts `List-Unsubscribe=One-Click` form-encoded (RFC
8058), or a page posts nothing. The token in the path is the secret, so a cross-site form gains nothing; the body
is never read, and may be at most `OFF_LINK_LIMIT` bytes."""
OFF_LINK_TYPES = frozenset({"", "application/json", "application/x-www-form-urlencoded", "multipart/form-data"})
OFF_LINK_LIMIT = 1024
# A route may tighten the CSP with a policy of its own (the browser enforces both); every other header it sets stays.
COMBINED_HEADERS = frozenset({b"content-security-policy"})
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
# The DM's tool bridge (`delve dm-bridge`): not the owner token, but a loopback client with this process's secret.
INTERNAL_PREFIX = "/internal/"
BRIDGE_HEADER = "x-delve-bridge"


class RequestGuard:
    """ASGI middleware: refuses unknown hosts (421), cross-origin requests (403), a WebSocket handshake of either
    (closed with 4421 or 4403 before the app sees it), and writes that aren't JSON (415),
    except the `.dscn` upload, which must be a zip (415), and an attachment upload, which must be one of
    `ATTACHMENT_TYPES` (415), each of at most `UPLOAD_LIMIT` bytes (413), and a PDF to convert, which must be
    `application/pdf` (415) of at most `PDF_LIMIT` bytes (413), and a world map's picture to read, which must be
    one of `WORLDMAP_TYPES` (415) of at most `UPLOAD_LIMIT` bytes (413), and an avatar, which must be one of
    `AVATAR_TYPES` (415) of at most `AVATAR_LIMIT` bytes (413), and a pack or a setting's additions (DEL-366), which
    must be a zip (415) of at most `PACK_LIMIT` or `ADDITIONS_LIMIT` bytes (413); refuses the internal routes (403) to anyone
    but a loopback client with the bridge secret; and adds the CSP and nosniff headers to every response, refusals
    included."""

    def __init__(self, app: ASGIApp, env: Mapping[str, str] = os.environ) -> None:
        self.app = app
        self.extra_hosts = allowed_hosts(env)
        self.machine_hosts = frozenset(machine_addresses())

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "websocket":
            code = self.handshake_refusal(scope)
            if code is not None:
                await receive()  # the handshake's `websocket.connect`
                await send({"type": "websocket.close", "code": code})
                return
            await self.app(scope, receive, send)
            return
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                present = {name.lower() for name, _ in headers}
                ours = PORTRAIT_EDITOR_HEADERS if scope["path"].startswith(PORTRAIT_EDITOR_PATH) else SECURITY_HEADERS
                added = [(n, v) for n, v in ours if n not in present or n in COMBINED_HEADERS]
                message["headers"] = [*headers, *added]
            await send(message)

        refusal = self.refusal(scope)
        if refusal is not None:
            await refusal(scope, receive, send_with_headers)
            return
        if scope["method"] in WRITE_METHODS and _is_json(scope):
            # A body sent without a Content-Length, or past the one it gave: read it here, up to the limit, before any
            # route does (a JSON body is read whole anyway), and give the route what was read.
            read = await _read_capped(receive, JSON_LIMIT)
            if read is None:
                await JSONResponse({"error": JSON_TOO_LONG}, status_code=413)(scope, receive, send_with_headers)
                return
            receive = _replay(read, receive)
        await self.app(scope, receive, send_with_headers)

    def handshake_refusal(self, scope: Scope) -> int | None:
        """421 for a `Host` Delve doesn't answer to, 403 for an `Origin` that isn't the request's host, else None; a
        WebSocket's handshake is refused with the close code 4421 or 4403 (table voice and fixes Task V1.1), since
        a browser sends its cookies on a handshake from any origin."""
        headers = Headers(scope=scope)
        host_header = headers.get("host", "")
        if not self.host_allowed(host_of(host_header)):
            return 4421
        origin = headers.get("origin")
        if origin is not None and urlsplit(origin).netloc.lower() != host_header.lower():
            return 4403
        return None

    def refusal(self, scope: Scope) -> JSONResponse | None:
        headers = Headers(scope=scope)
        code = self.handshake_refusal(scope)
        if code == 4421:
            host_header = headers.get("host", "")
            return JSONResponse({"error": f"host {host_header!r} is not one Delve answers to"}, status_code=421)
        if code == 4403:
            return JSONResponse({"error": "cross-origin requests are refused"}, status_code=403)

        if scope["path"].startswith(INTERNAL_PREFIX):
            refused = bridge_refusal(scope, headers)
            if refused is not None:
                return refused

        if scope["method"] in WRITE_METHODS:
            media_type = headers.get("content-type", "").split(";")[0].strip().lower()
            if scope["method"] == "POST" and scope["path"] == UPLOAD_PATH:
                return upload_refusal(media_type, headers.get("content-length"))
            if scope["method"] == "POST" and ATTACHMENT_PATH.fullmatch(scope["path"]):
                return attachment_refusal(media_type, headers.get("content-length"))
            if scope["method"] == "POST" and scope["path"] == CONVERSION_PDF_PATH:
                return pdf_refusal(media_type, headers.get("content-length"))
            if scope["method"] == "POST" and scope["path"] == CONVERSION_WORLDMAP_PATH:
                return worldmap_refusal(media_type, headers.get("content-length"))
            if scope["method"] == "POST" and scope["path"] == AVATAR_PATH:
                return avatar_refusal(media_type, headers.get("content-length"))
            if scope["method"] == "POST" and (
                TALK_PICTURE_PATH.fullmatch(scope["path"]) or BOARD_PICTURE_PATH.fullmatch(scope["path"])
            ):
                return talk_picture_refusal(media_type, headers.get("content-length"))
            if scope["method"] == "POST" and scope["path"] == PACK_UPLOAD_PATH:
                return zip_refusal(media_type, headers.get("content-length"), PACK_LIMIT, "a pack")
            if scope["method"] == "POST" and ADDITIONS_PATH.fullmatch(scope["path"]):
                return zip_refusal(media_type, headers.get("content-length"), ADDITIONS_LIMIT, "a setting's additions")
            if scope["method"] == "POST" and BANNER_UPLOAD_PATH.fullmatch(scope["path"]):
                return banner_refusal(media_type, headers.get("content-length"))
            if scope["method"] == "POST" and OFF_LINK_PATH.fullmatch(scope["path"]):
                return off_link_refusal(media_type, headers.get("content-length"))
            if media_type != "application/json":
                return JSONResponse({"error": "send the body as application/json"}, status_code=415)
            if _too_long(headers.get("content-length"), JSON_LIMIT):
                return JSONResponse({"error": JSON_TOO_LONG}, status_code=413)
        return None

    def host_allowed(self, host: str) -> bool:
        if host in LOOPBACK_HOSTS or host in self.extra_hosts or host in self.machine_hosts:
            return True
        if not host:
            return False
        # An address the machine got after Delve started, for example from DHCP.
        self.machine_hosts = frozenset(machine_addresses())
        return host in self.machine_hosts


def upload_refusal(media_type: str, content_length: str | None) -> JSONResponse | None:
    """415 for an upload that isn't a zip, 413 for one that says it is past `UPLOAD_LIMIT`. The route counts too."""
    if media_type not in UPLOAD_TYPES:
        return JSONResponse(
            {"error": "send the .dscn file as application/zip or application/vnd.dscn+zip"}, status_code=415
        )
    if _too_long(content_length):
        return JSONResponse({"error": f"a .dscn upload may be at most {UPLOAD_LIMIT} bytes"}, status_code=413)
    return None


def attachment_refusal(media_type: str, content_length: str | None) -> JSONResponse | None:
    """415 for an attachment that isn't one of `ATTACHMENT_TYPES`, 413 for one that says it is past `UPLOAD_LIMIT`. The
    route counts too, and checks the bytes against the type."""
    if media_type not in ATTACHMENT_TYPES:
        allowed = ", ".join(sorted(ATTACHMENT_TYPES))
        return JSONResponse({"error": f"send an attachment as one of {allowed}"}, status_code=415)
    if _too_long(content_length):
        return JSONResponse({"error": f"an attachment may be at most {UPLOAD_LIMIT} bytes"}, status_code=413)
    return None


def zip_refusal(media_type: str, content_length: str | None, limit: int, what: str) -> JSONResponse | None:
    """415 for a pack or a setting's additions (DEL-366) that isn't sent as a zip, 413 for one that says it is past
    `limit`. The route counts too, and checks the file itself."""
    if media_type not in PACK_TYPES:
        return JSONResponse({"error": f"send {what} as application/zip"}, status_code=415)
    if _too_long(content_length, limit):
        return JSONResponse({"error": f"{what} may be at most {limit} bytes"}, status_code=413)
    return None


def pdf_refusal(media_type: str, content_length: str | None) -> JSONResponse | None:
    """415 for a book to convert that isn't `application/pdf`, 413 for one that says it is past `PDF_LIMIT`. The route
    counts too, and checks that the bytes start as a PDF."""
    if media_type != PDF_TYPE:
        return JSONResponse({"error": f"send the book as {PDF_TYPE}"}, status_code=415)
    if _too_long(content_length, PDF_LIMIT):
        return JSONResponse({"error": f"a PDF to convert may be at most {PDF_LIMIT} bytes"}, status_code=413)
    return None


def worldmap_refusal(media_type: str, content_length: str | None) -> JSONResponse | None:
    """415 for a world map's picture that isn't one of `WORLDMAP_TYPES`, 413 for one that says it is past
    `UPLOAD_LIMIT`. The route counts too, and checks the bytes against the type."""
    if media_type not in WORLDMAP_TYPES:
        allowed = ", ".join(sorted(WORLDMAP_TYPES))
        return JSONResponse({"error": f"send a world map's picture as one of {allowed}"}, status_code=415)
    if _too_long(content_length):
        return JSONResponse({"error": f"a world map's picture may be at most {UPLOAD_LIMIT} bytes"}, status_code=413)
    return None


def avatar_refusal(media_type: str, content_length: str | None) -> JSONResponse | None:
    """415 for an avatar that isn't one of `AVATAR_TYPES`, 413 for one that says it is past `AVATAR_LIMIT`. The route
    counts too, and checks the bytes against the type."""
    if media_type not in AVATAR_TYPES:
        allowed = ", ".join(sorted(AVATAR_TYPES))
        return JSONResponse({"error": f"send an avatar as one of {allowed}"}, status_code=415)
    if _too_long(content_length, AVATAR_LIMIT):
        return JSONResponse({"error": f"an avatar may be at most {AVATAR_LIMIT} bytes"}, status_code=413)
    return None


def talk_picture_refusal(media_type: str, content_length: str | None) -> JSONResponse | None:
    """415 for a talk picture that isn't one of `TALK_PICTURE_TYPES`, 413 for one that says it is past
    `TALK_PICTURE_LIMIT`. The route counts too, and checks the bytes against the type."""
    if media_type not in TALK_PICTURE_TYPES:
        allowed = ", ".join(sorted(TALK_PICTURE_TYPES))
        return JSONResponse({"error": f"send a picture as one of {allowed}"}, status_code=415)
    if _too_long(content_length, TALK_PICTURE_LIMIT):
        return JSONResponse({"error": f"a picture may be at most {TALK_PICTURE_LIMIT} bytes"}, status_code=413)
    return None


def banner_refusal(media_type: str, content_length: str | None) -> JSONResponse | None:
    """415 for a module banner's picture that isn't one of `BANNER_TYPES`, 413 for one that says it is past
    `BANNER_LIMIT`. The route counts too, and checks the bytes against the type."""
    if media_type not in BANNER_TYPES:
        allowed = ", ".join(sorted(BANNER_TYPES))
        return JSONResponse({"error": f"send a banner as one of {allowed}"}, status_code=415)
    if _too_long(content_length, BANNER_LIMIT):
        return JSONResponse({"error": f"a banner may be at most {BANNER_LIMIT} bytes"}, status_code=413)
    return None


def off_link_refusal(media_type: str, content_length: str | None) -> JSONResponse | None:
    """415 for an off link's post that isn't one of `OFF_LINK_TYPES`, 413 for one past `OFF_LINK_LIMIT`."""
    if media_type not in OFF_LINK_TYPES:
        return JSONResponse({"error": "send nothing, a form or JSON"}, status_code=415)
    if _too_long(content_length, OFF_LINK_LIMIT):
        return JSONResponse({"error": f"an off link's post may be at most {OFF_LINK_LIMIT} bytes"}, status_code=413)
    return None


def _is_json(scope: Scope) -> bool:
    media_type = Headers(scope=scope).get("content-type", "").split(";")[0].strip().lower()
    return media_type == "application/json"


async def _read_capped(receive: Receive, limit: int) -> list[Message] | None:
    """The request's body messages, up to the end of the body or a disconnect; None once they pass `limit` bytes."""
    messages: list[Message] = []
    size = 0
    while True:
        message = await receive()
        messages.append(message)
        if message["type"] != "http.request":
            return messages
        size += len(message.get("body", b""))
        if size > limit:
            return None
        if not message.get("more_body", False):
            return messages


def _replay(messages: list[Message], receive: Receive) -> Receive:
    """A `receive` that gives `messages` first, then whatever comes after them (a disconnect)."""
    pending = list(messages)

    async def replayed() -> Message:
        return pending.pop(0) if pending else await receive()

    return replayed


def _too_long(content_length: str | None, limit: int = UPLOAD_LIMIT) -> bool:
    return content_length is not None and content_length.strip().isdigit() and int(content_length) > limit


def bridge_refusal(scope: Scope, headers: Headers) -> JSONResponse | None:
    """403 unless the request is from this machine and sends the app's bridge secret (`app.state.bridge_secret`)."""
    expected = getattr(getattr(scope.get("app"), "state", None), "bridge_secret", None)
    presented = headers.get(BRIDGE_HEADER, "")
    if (
        not is_this_machine(HTTPConnection(scope))
        or not expected
        or not secrets.compare_digest(presented.encode(), expected.encode())
    ):
        return JSONResponse({"error": "the internal routes are for Delve's DM bridge only"}, status_code=403)
    return None


# What a proxy adds. A tunnel on this machine (such as `cloudflared`) forwards every visitor from loopback, with one of
# these or with the public name it answers to as the host.
PROXY_HEADERS = (
    "forwarded",
    "x-forwarded-for",
    "x-forwarded-host",
    "x-forwarded-proto",
    "x-real-ip",
    "cf-connecting-ip",
    "true-client-ip",
)


def is_this_machine(connection: HTTPConnection) -> bool:
    """Whether the request comes from this machine, and not through a proxy on it: its client is loopback, it carries
    none of `PROXY_HEADERS` (an empty one counts), and its host is a loopback or machine address, never a name such as
    one from `DELVE_ALLOWED_HOSTS`. The one test of it: the owner without a token, the bridge, the invite's LAN
    address."""
    client = connection.client
    if client is None or not _loopback(client.host):
        return False
    if any(name in connection.headers for name in PROXY_HEADERS):
        return False
    host = host_of(connection.headers.get("host", ""))
    if host == "localhost" or _loopback(host):
        return True
    return _is_address(host) and host in machine_addresses()


def from_a_proxy_here(connection: HTTPConnection) -> bool:
    """Whether a proxy on this machine forwarded the request: its client is loopback, and it isn't this machine's own
    (`is_this_machine`). Only such a proxy's headers are believed; a LAN client's are its own say. Such a request is
    a tunnel's visitor, and is refused the owner token (DEL-154, audit finding 9)."""
    client = connection.client
    return client is not None and _loopback(client.host) and not is_this_machine(connection)


def client_address(connection: HTTPConnection) -> str:
    """The address the request comes from, for the login and join limits (players and tavern Task C2). From a proxy
    on this machine, the address that proxy sets: the rightmost `X-Forwarded-For` entry (the one our own proxy
    appended; cloudflared appends the visitor too), else `X-Real-IP`, else `Forwarded`'s last `for=`. So a visitor
    can't pick a fresh address by sending the left-hand entries, and visitors behind one tunnel aren't one address.
    Otherwise the client's own address, whatever headers it sends. `CF-Connecting-IP` and `True-Client-IP` are never
    read: a proxy that doesn't set them passes on the visitor's own (audit-auth finding 5)."""
    own = connection.client.host if connection.client is not None else ""
    if not from_a_proxy_here(connection):
        return own
    headers = connection.headers
    forwarded_for = [entry.strip() for entry in headers.get("x-forwarded-for", "").split(",") if entry.strip()]
    if forwarded_for:
        return forwarded_for[-1]
    real_ip = headers.get("x-real-ip", "").strip()
    if real_ip:
        return real_ip
    found = _forwarded(headers.get("forwarded", ""), "for")
    return _without_port(found[-1]) if found else own


def came_over_https(connection: HTTPConnection) -> bool:
    """Whether the browser reached Delve over HTTPS: the URL's scheme is https, or a proxy on this machine says so
    (`X-Forwarded-Proto: https`, or `Forwarded: …proto=https`). The `Secure` flag of the session cookie follows it."""
    if connection.url.scheme == "https":
        return True
    if not from_a_proxy_here(connection):
        return False
    proto = connection.headers.get("x-forwarded-proto", "").split(",")[-1].strip().lower()
    if proto:
        return proto == "https"
    found = _forwarded(connection.headers.get("forwarded", ""), "proto")
    return bool(found) and found[-1].lower() == "https"


def _forwarded(header: str, key: str) -> list[str]:
    """The values of `key` in a `Forwarded` header (RFC 7239), in order, quotes taken off."""
    values = []
    for element in header.split(","):
        for pair in element.split(";"):
            name, _, value = pair.partition("=")
            if name.strip().lower() == key and value.strip():
                values.append(value.strip().strip('"'))
    return values


def _without_port(node: str) -> str:
    """A `Forwarded` node's address: `[2001:db8::7]:4711` is `2001:db8::7`, `192.0.2.1:80` is `192.0.2.1`."""
    if node.startswith("["):
        return node[1 : node.find("]")] if "]" in node else node
    return node.rpartition(":")[0] if node.count(":") == 1 else node


def _is_address(text: str) -> bool:
    try:
        ipaddress.ip_address(text)
    except ValueError:
        return False
    return True


def _loopback(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    mapped = getattr(ip, "ipv4_mapped", None)
    return ip.is_loopback or (mapped is not None and mapped.is_loopback)


def host_of(header: str) -> str:
    """The host in a `Host` header, lowercased, without its port or IPv6 brackets."""
    header = header.strip().lower()
    if header.startswith("["):
        return header[1 : header.find("]")] if "]" in header else ""
    return header.rpartition(":")[0] if ":" in header else header


def allowed_hosts(env: Mapping[str, str] = os.environ) -> frozenset[str]:
    """The names Delve answers on besides this machine's addresses (`DELVE_ALLOWED_HOSTS`), such as its tunnel's."""
    return frozenset(_hosts(env.get("DELVE_ALLOWED_HOSTS", "").split(",")))


def _hosts(entries: Iterable[str]) -> set[str]:
    return {host_of(entry) for entry in entries if entry.strip()}


def machine_addresses() -> set[str]:
    """The IP addresses of this machine's interfaces, loopback included, without asking any other machine."""
    addresses = {address for _, address in _interface_addresses()}
    return addresses or set(_routed_addresses())


# Interfaces other devices can't reach Delve through: containers' and VMs' bridges.
VIRTUAL_INTERFACES = ("docker", "br-", "veth", "virbr", "vmnet", "lxcbr", "cni", "flannel")


def lan_addresses() -> list[str]:
    """The addresses another device on the LAN can reach Delve at: no loopback, link-local or virtual bridge; IPv4
    first."""
    found = set()
    pairs = list(_interface_addresses()) or [("", address) for address in _routed_addresses()]
    for name, text in pairs:
        address = ipaddress.ip_address(text)
        if name.startswith(VIRTUAL_INTERFACES) or address.is_loopback or address.is_link_local:
            continue
        found.add(address)
    return [str(a) for a in sorted(found, key=lambda a: (a.version, a))]


def lan_origins(port: int) -> list[str]:
    """`http://<address>:<port>` for each of `lan_addresses`, IPv6 in brackets: where another device opens Delve, for
    `delve token`'s links and a table's join link."""
    hosts = [f"[{a}]" if ":" in a else a for a in lan_addresses()]
    return [f"http://{host}:{port}" for host in hosts]


def _interface_addresses() -> Iterable[tuple[str, str]]:
    yield from _ipv4_interface_addresses()
    yield from _ipv6_interface_addresses()


_SIOCGIFADDR = 0x8915


def _ipv4_interface_addresses() -> Iterable[tuple[str, str]]:
    """Each interface's name and IPv4 address, by ioctl (Linux)."""
    try:
        interfaces = socket.if_nameindex()
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    except OSError:
        return
    with probe:
        for _, name in interfaces:
            try:
                answer = fcntl.ioctl(probe.fileno(), _SIOCGIFADDR, struct.pack("256s", name.encode()[:15]))
            except OSError:
                continue
            yield name, socket.inet_ntoa(answer[20:24])


def _ipv6_interface_addresses(path: Path = Path("/proc/net/if_inet6")) -> Iterable[tuple[str, str]]:
    """Each interface's name and IPv6 addresses (Linux)."""
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return
    for line in lines:
        fields = line.split()
        if len(fields) == 6 and len(fields[0]) == 32:
            yield fields[5], str(ipaddress.IPv6Address(bytes.fromhex(fields[0])))


def _routed_addresses() -> Iterable[str]:
    """Elsewhere: the addresses the default routes leave from. Connecting a UDP socket sends nothing."""
    yield "127.0.0.1"
    for family, target in ((socket.AF_INET, "192.0.2.1"), (socket.AF_INET6, "2001:db8::1")):
        try:
            with socket.socket(family, socket.SOCK_DGRAM) as probe:
                probe.connect((target, 9))
                yield probe.getsockname()[0]
        except OSError:
            continue
