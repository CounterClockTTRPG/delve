"""The owner's connections (portraits plan Task 3): the Replicate token and assetgen's URL and token.

Each is a file under the data dir at mode 0600, written atomically: `replicate-token` (as `replicate.load_token`
always read it) and `assetgen.json` (`{"url", "token"}`). Delve has no other secret store, and the Preferences JSON
never holds them. A token never leaves these files: it isn't answered, logged, published or put in an error, and
`Assetgen`'s repr leaves it out.

assetgen's URL is guarded against server-side request forgery (`check_url`): http or https, the address alone, and
every address its host resolves to on loopback or a private LAN. It is checked at save and again at each connection,
which covers a name rebound between the two.
"""

from __future__ import annotations

import contextlib
import enum
import ipaddress
import json
import os
import socket
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

import httpx

from delve.domain.backends import Registry
from delve.images.replicate import API_URL, REPLICATE, REPLICATE_CAPABILITIES, TOKEN_ENV, TOKEN_FILE, load_token

ASSETGEN_FILE = "assetgen.json"
TEST_TIMEOUT_S = 10.0

ReplicateState = Literal["unset", "set", "environment"]
Resolve = Callable[[str, int], list[str]]

# Loopback and the private LAN ranges; link-local (169.254.0.0/16, the cloud's metadata service), shared address space
# and the rest of `is_private`'s reserved ranges are refused.
PRIVATE_NETWORKS = tuple(
    ipaddress.ip_network(net)
    for net in ("127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "::1/128", "fc00::/7")
)


class ConnectionError(Exception):  # the plan's name: a refused URL, never the builtin socket error
    """A URL Delve won't connect to, with the reason; never the URL itself, which might hold a secret."""


class Keep(enum.Enum):
    """`save_assetgen`'s token: keep the stored one."""

    KEEP = "keep"


KEEP = Keep.KEEP


@dataclass(frozen=True)
class Assetgen:
    url: str
    token: str | None = field(default=None, repr=False)


@dataclass(frozen=True)
class CheckResult:
    """What a connection's Test answered: whether it worked, in words for the owner (never a token)."""

    ok: bool
    message: str


def replicate_state(data_dir: Path, environ: Mapping[str, str] | None = None) -> ReplicateState:
    """`environment` when `REPLICATE_API_TOKEN` holds a token (it wins), `set` when the file does, else `unset`."""
    environ = os.environ if environ is None else environ
    if environ.get(TOKEN_ENV, "").strip():
        return "environment"
    return "set" if load_token(data_dir, {}) is not None else "unset"


def save_replicate(data_dir: Path, token: str) -> None:
    """Write `<data dir>/replicate-token` at 0600. A token is one word of printable characters, else `ValueError`
    (`TypeError` when it isn't text)."""
    write_secret(data_dir / TOKEN_FILE, _token(token) + "\n")


def remove_replicate(data_dir: Path) -> None:
    (data_dir / TOKEN_FILE).unlink(missing_ok=True)


def load_assetgen(data_dir: Path) -> Assetgen | None:
    """The stored assetgen connection; None without one, or when its file is broken or its URL refused."""
    try:
        stored = json.loads((data_dir / ASSETGEN_FILE).read_text(encoding="utf-8"))
        url = check_url(stored["url"], resolve=_no_resolve)
    except (OSError, ValueError, KeyError, TypeError, ConnectionError):
        return None
    token = stored.get("token")
    return Assetgen(url, token if isinstance(token, str) and token else None)


def save_assetgen(data_dir: Path, url: str, token: str | None | Keep = KEEP) -> Assetgen:
    """Write `<data dir>/assetgen.json` at 0600 with `check_url`'s URL; `KEEP` keeps the stored token, None removes
    it. A refused URL raises `ConnectionError` and a token that isn't one `ValueError`, and nothing is written."""
    url = check_url(url)
    if token is KEEP:
        stored = load_assetgen(data_dir)
        token = stored.token if stored is not None else None
    elif token is not None:
        token = _token(token)
    write_secret(data_dir / ASSETGEN_FILE, json.dumps({"url": url, "token": token}) + "\n")
    return Assetgen(url, token)


def remove_assetgen(data_dir: Path) -> None:
    (data_dir / ASSETGEN_FILE).unlink(missing_ok=True)


def check_url(url: str, *, resolve: Resolve | None = None) -> str:
    """The URL normalised (`scheme://host[:port]`, lowercase, no trailing slash), when it is http or https, the
    address alone (no user, path, query or fragment), and every address its host resolves to is on loopback or a
    private LAN. Otherwise `ConnectionError` with the reason."""
    if not isinstance(url, str):
        raise ConnectionError("The URL must be text.")
    try:
        parts = urlsplit(url.strip())
        port = parts.port
    except ValueError:
        raise ConnectionError("That isn't a URL Delve can use.") from None
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        raise ConnectionError("The URL must start with http:// or https://.")
    host = parts.hostname
    if not host:
        raise ConnectionError("The URL has no host.")
    if parts.username is not None or parts.password is not None:
        raise ConnectionError("The URL must not hold a user or a password.")
    if parts.path not in ("", "/") or parts.query or parts.fragment or url.strip().endswith(("?", "#")):
        raise ConnectionError("The URL must be assetgen's address alone, such as http://localhost:8765.")
    addresses = _addresses(host, port or (443 if scheme == "https" else 80), resolve or _resolve)
    if not addresses or not all(_private(address) for address in addresses):
        raise ConnectionError("assetgen must be on this machine or the local network (a loopback or private address).")
    netloc = f"[{host}]" if ":" in host else host
    return f"{scheme}://{netloc}" + (f":{port}" if port is not None else "")


def _addresses(host: str, port: int, resolve: Resolve) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    try:
        return [ipaddress.ip_address(host)]
    except ValueError:
        pass
    try:
        found = resolve(host, port)
    except OSError:
        raise ConnectionError("The URL's host can't be found.") from None
    try:
        return [ipaddress.ip_address(address.split("%", 1)[0]) for address in found]
    except ValueError:
        raise ConnectionError("The URL's host can't be found.") from None


def _private(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return any(address in network for network in PRIVATE_NETWORKS if network.version == address.version)


def _resolve(host: str, port: int) -> list[str]:
    return [str(info[4][0]) for info in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)]


def _no_resolve(host: str, port: int) -> list[str]:
    """Loading the stored file checks its form only; the address is checked again at each connection."""
    return ["127.0.0.1"]


def _token(token: str) -> str:
    """The token stripped; `TypeError` or `ValueError` (never naming it) when it isn't text, or is empty or not one
    word of printable text."""
    if not isinstance(token, str):
        raise TypeError("The token must be text.")
    token = token.strip()
    if not token:
        raise ValueError("The token is empty.")
    if not token.isprintable() or any(char.isspace() for char in token):
        raise ValueError("A token is one word, without spaces or line breaks.")
    return token


def write_secret(path: Path, text: str) -> None:
    """Write `text` to `path` at 0600, atomically: a temporary file beside it, then a rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            os.fchmod(file.fileno(), 0o600)
            file.write(text)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temporary)
        raise


def register_replicate(images: Registry, data_dir: Path, environ: Mapping[str, str] | None = None) -> object | None:
    """Register Replicate with the token `load_token` finds, replacing it in its place, or unregister it without one.
    The provider it dropped (built with the old token), for the caller to close; otherwise None."""
    token = load_token(data_dir, environ)
    if token is None:
        return images.unregister(REPLICATE)

    def replicate():
        from delve.images.replicate import ReplicateImages

        return ReplicateImages(token, client=httpx.AsyncClient())

    return images.register(REPLICATE_CAPABILITIES, replicate)


async def check_replicate(data_dir: Path, client: httpx.AsyncClient, environ: Mapping[str, str] | None = None):
    """Replicate's `GET /v1/account` with the token: the status code only, never the body Replicate answers."""
    token = load_token(data_dir, environ)
    if token is None:
        return CheckResult(False, "No Replicate token is set.")
    try:
        response = await client.get(
            f"{API_URL}/account", headers={"Authorization": f"Bearer {token}"}, timeout=TEST_TIMEOUT_S
        )
    except httpx.HTTPError as error:
        return CheckResult(False, f"Replicate can't be reached ({type(error).__name__}).")
    if response.status_code in (401, 403):
        return CheckResult(False, f"Replicate refused the token (HTTP {response.status_code}).")
    if response.status_code != 200:
        return CheckResult(False, f"Replicate answered HTTP {response.status_code}.")
    return CheckResult(True, "Replicate accepted the token.")


async def check_assetgen(data_dir: Path, client: httpx.AsyncClient, *, resolve: Resolve | None = None):
    """assetgen's `GET /api/models`, its URL checked again first: the number of image models, or the status code
    only, never the body assetgen answers."""
    stored = load_assetgen(data_dir)
    if stored is None:
        return CheckResult(False, "assetgen isn't set up.")
    try:
        url = check_url(stored.url, resolve=resolve)
    except ConnectionError as error:
        return CheckResult(False, str(error))
    headers = {"Authorization": f"Bearer {stored.token}"} if stored.token else {}
    try:
        response = await client.get(f"{url}/api/models", headers=headers, timeout=TEST_TIMEOUT_S)
    except httpx.HTTPError as error:
        return CheckResult(False, f"assetgen isn't answering ({type(error).__name__}).")
    if response.status_code != 200:
        return CheckResult(False, f"assetgen failed ({response.status_code}).")
    try:
        answer = response.json()
    except ValueError:
        return CheckResult(False, "assetgen answered something other than JSON.")
    models = answer.get("models") if isinstance(answer, dict) else answer
    if not isinstance(models, list):
        return CheckResult(False, "assetgen answered no list of models.")
    images = sum(1 for model in models if isinstance(model, dict) and model.get("kind") == "image")
    return CheckResult(True, f"assetgen answered, with {images} image model{'' if images == 1 else 's'}.")
