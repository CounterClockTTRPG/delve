"""The two stores' connections (cloud storage plan Task 4): the owner's private backup store and the shared module
library, each a file in the data dir, and the install's id.

`backup-store.json` and `library-store.json` hold a `StoreConfig`, and `install-id` the id Delve makes once (`ins_` and
12 hex digits); each is written at mode 0600 and atomically, as `delve.images.connections` writes the owner's tokens.
A credential (a SAS URL's query string, an S3 secret access key) is written in and never read back out: a
`StoreConfig`'s repr leaves it out, a refused config's `ValueError` never names it, and the stores' errors are Delve's
own words (`delve.cloud.store`).

A library's right is what `probe` finds the credential can do. R2's tokens only tell read from write, so for an S3
store the owner's choice in `right` (`publish`, the default, or `manage`) caps it, and Delve enforces the difference.

`Stores` (on `app.state.stores`) holds the stores the files name, each with an `httpx.AsyncClient` of its own that the
store closes. Only saving a library and its Test probe it, and they record the right they find in its file
(`probed`); `start` builds the stores with that right and makes no request, so a start leaves no probe object behind.
"""

from __future__ import annotations

import contextlib
import json
import secrets
from dataclasses import asdict, dataclass, fields, replace
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

import httpx

from delve.cloud.azure import AzureBlobStore, parse_sas
from delve.cloud.s3 import S3Store
from delve.cloud.store import RIGHTS, LocalStore, ObjectStore, Right, probe
from delve.images.connections import write_secret

StoreKind = Literal["backup", "library"]
Provider = Literal["azure", "s3", "local"]

KINDS: tuple[StoreKind, ...] = ("backup", "library")
PROVIDERS: tuple[Provider, ...] = ("azure", "s3", "local")
STORE_FILES: dict[StoreKind, str] = {"backup": "backup-store.json", "library": "library-store.json"}
INSTALL_ID_FILE = "install-id"
PROBED_KEY = "probed"  # the library's right as last probed, beside its config
# The owner's cap on an S3 write credential's library right; `publish` when they chose none.
S3_CHOICES: tuple[Right, ...] = ("publish", "manage")
DEFAULT_S3_RIGHT: Right = "publish"
TIMEOUT = httpx.Timeout(60.0, connect=10.0)


@dataclass(frozen=True)
class StoreConfig:
    provider: Provider
    sas_url: str = ""
    endpoint: str = ""
    bucket: str = ""
    access_key_id: str = ""
    secret_access_key: str = ""
    root: str = ""
    right: Right | None = None

    def __repr__(self) -> str:
        shown = {"provider": self.provider}
        if self.sas_url:
            shown["container"] = self.sas_url.split("?", 1)[0]
        for name in ("endpoint", "bucket", "root", "right"):
            if getattr(self, name):
                shown[name] = getattr(self, name)
        return f"StoreConfig({', '.join(f'{key}={value!r}' for key, value in shown.items())})"

    __str__ = __repr__

    @property
    def secret(self) -> str:
        """The credential's secret part, whatever the provider: the SAS URL, or the secret access key."""
        return self.sas_url if self.provider == "azure" else self.secret_access_key


def check_config(config: StoreConfig) -> StoreConfig:
    """The config, stripped, when Delve can use it; otherwise `ValueError` with the reason, never naming a value."""
    if config.provider not in PROVIDERS:
        raise ValueError("Choose Azure, S3 or a folder.")
    if config.provider == "azure":
        sas_url = _text(config.sas_url, "The SAS URL")
        parse_sas(sas_url)
        return StoreConfig(provider="azure", sas_url=sas_url)
    if config.provider == "s3":
        endpoint = _text(config.endpoint, "The endpoint").rstrip("/")
        try:
            parts = urlsplit(endpoint)
            parts.port  # noqa: B018 — refuses a port that isn't a number
        except ValueError:
            raise ValueError("The endpoint isn't a URL Delve can use.") from None
        if parts.scheme != "https" or not parts.hostname:
            raise ValueError("The endpoint starts with https://.")
        if parts.username is not None or parts.password is not None or parts.path or parts.query or parts.fragment:
            raise ValueError("The endpoint is the address alone, such as https://<account>.r2.cloudflarestorage.com.")
        bucket = _text(config.bucket, "The bucket")
        if "/" in bucket or any(char.isspace() for char in bucket):
            raise ValueError("A bucket's name has no slashes or spaces.")
        if config.right is not None and config.right not in S3_CHOICES:
            raise ValueError("Choose publish or manage for a write key.")
        return StoreConfig(
            provider="s3", endpoint=endpoint, bucket=bucket, access_key_id=_word(config.access_key_id, "access key id"),
            secret_access_key=_word(config.secret_access_key, "secret access key"), right=config.right,
        )
    root = _text(config.root, "The folder")
    if not Path(root).is_absolute():
        raise ValueError("The folder is a full path, starting with /.")
    if not Path(root).is_dir():
        raise ValueError("That folder isn't there.")
    return StoreConfig(provider="local", root=root)


def same_place(one: StoreConfig, other: StoreConfig) -> bool:
    """Whether two checked configs name one place: an Azure container (its host and container), an S3 bucket (its
    endpoint's host and its name), or a folder (its resolved path), a folder inside the other or holding it included.
    A host is compared lowercased, without a trailing dot or the default port 443. The backup store and the library are never one, or the library's credential, a friend's,
    would reach the owner's backups."""
    if one.provider != other.provider:
        return False
    if one.provider == "local":
        first, second = Path(one.root).resolve(), Path(other.root).resolve()
        return first.is_relative_to(second) or second.is_relative_to(first)
    return _place(one) == _place(other)


def _place(config: StoreConfig) -> tuple[str, ...]:
    if config.provider == "azure":
        container_url, _ = parse_sas(config.sas_url)
        host, _, container = container_url.removeprefix("https://").partition("/")
        return (_host(host), container.strip("/").lower())
    return (_host(urlsplit(config.endpoint).netloc), config.bucket.lower())


def _host(netloc: str) -> str:
    """A checked URL's host, as a store's place: lowercased, without a trailing dot or the default port 443."""
    parts = urlsplit(f"//{netloc}")
    host = (parts.hostname or "").rstrip(".")
    return host if parts.port in (None, 443) else f"{host}:{parts.port}"


def load_store(data_dir: Path, kind: StoreKind) -> StoreConfig | None:
    """The stored store of `kind`; None without one, or when its file is broken."""
    try:
        stored = json.loads((data_dir / STORE_FILES[kind]).read_text(encoding="utf-8"))
        known = {field.name for field in fields(StoreConfig)}
        return check_config(StoreConfig(**{key: value for key, value in stored.items() if key in known}))
    except (OSError, ValueError, TypeError, AttributeError):
        return None


def kept_secret(data_dir: Path, kind: StoreKind, config: StoreConfig) -> StoreConfig:
    """`config` with the stored credential's secret when it sends none: the stored SAS URL for Azure, or the stored
    secret access key for S3 when the access key id is the stored one's."""
    stored = load_store(data_dir, kind)
    if stored is None or stored.provider != config.provider or config.secret:
        return config
    if config.provider == "azure":
        return replace(config, sas_url=stored.sas_url)
    key_id = config.access_key_id
    if config.provider == "s3" and isinstance(key_id, str) and key_id.strip() == stored.access_key_id:
        return replace(config, secret_access_key=stored.secret_access_key)
    return config


def save_store(data_dir: Path, kind: StoreKind, config: StoreConfig | None, *, keep_secret: bool) -> None:
    """Write the store of `kind` at 0600, or remove it for None. `keep_secret` keeps the stored secret when `config`
    sends none (`kept_secret`). A config Delve can't use raises `ValueError`, and nothing is written."""
    path = data_dir / STORE_FILES[kind]
    if config is None:
        path.unlink(missing_ok=True)
        return
    if keep_secret:
        config = kept_secret(data_dir, kind, config)
    config = check_config(config)
    stored = {key: value for key, value in asdict(config).items() if value}
    write_secret(path, json.dumps(stored) + "\n")


def record_right(data_dir: Path, right: Right | None) -> None:
    """Record the library's probed right in its file (`probed`), for the next start; nothing without a library."""
    path = data_dir / STORE_FILES["library"]
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if not isinstance(stored, dict):
        return
    stored.pop(PROBED_KEY, None)
    if right is not None:
        stored[PROBED_KEY] = right
    write_secret(path, json.dumps(stored) + "\n")


def recorded_right(data_dir: Path) -> Right | None:
    """The library's right as PUT or Test last probed it; None when none is recorded."""
    try:
        right = json.loads((data_dir / STORE_FILES["library"]).read_text(encoding="utf-8")).get(PROBED_KEY)
    except (OSError, ValueError, AttributeError):
        return None
    return right if right in RIGHTS else None


def open_store(config: StoreConfig, client: httpx.AsyncClient) -> ObjectStore:
    """The store `config` names, over `client` (a folder needs none)."""
    if config.provider == "azure":
        return AzureBlobStore(config.sas_url, client=client)
    if config.provider == "s3":
        return S3Store(config.endpoint, config.bucket, config.access_key_id, config.secret_access_key, client=client)
    return LocalStore(Path(config.root))


def install_id(data_dir: Path) -> str:
    """This install's id, made once: `ins_` and 12 hex digits, in `<data dir>/install-id`."""
    path = data_dir / INSTALL_ID_FILE
    with contextlib.suppress(OSError):
        stored = path.read_text(encoding="utf-8").strip()
        if stored.startswith("ins_") and len(stored) == 16:
            return stored
    made = "ins_" + secrets.token_hex(6)
    write_secret(path, made + "\n")
    return made


async def library_right(store: ObjectStore, config: StoreConfig) -> Right | None:
    """What the credential may do to the library: `probe`'s right, which for S3 is capped at the owner's choice."""
    right = await probe(store)
    if config.provider != "s3" or right is None or right == "read":
        return right
    return "manage" if right == "manage" and config.right == "manage" else "publish"


class Stores:
    """The backup store and the library the data dir's files name, and the library's right: the one PUT or Test last
    probed, recorded in its file (None when none is, or when the credential can't even list). Building them makes no
    request, so a start never probes (a publish-only SAS can't delete its probe object)."""

    def __init__(self, data_dir: Path, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.data_dir = data_dir
        self.transport = transport  # tests set an `httpx.MockTransport`
        self.backup: ObjectStore | None = None
        self.library: ObjectStore | None = None
        self.library_right: Right | None = None
        # Each downloaded module whose entry has a newer version, with that version (`library.check_updates`).
        self.updates: dict[str, int] = {}

    def open(self, config: StoreConfig) -> ObjectStore:
        """A store for `config`, with a client of its own: the caller closes it (`aclose`), or hands it to `reload`."""
        if config.provider == "local":
            return LocalStore(Path(config.root))
        return open_store(config, httpx.AsyncClient(transport=self.transport, timeout=TIMEOUT))

    async def start(self) -> None:
        """Build both stores from their files, with the library's recorded right."""
        for kind in KINDS:
            await self.reload(kind)

    async def reload(self, kind: StoreKind, *, opened: ObjectStore | None = None) -> None:
        """Build the store of `kind` from its file again, closing the one it replaces; `opened` is a store already
        open for that file. The library's right is the one its file records."""
        config = load_store(self.data_dir, kind)
        if config is None:
            if opened is not None:
                await opened.aclose()
            await self._replace(kind, None)
            return
        await self._replace(kind, opened if opened is not None else self.open(config))
        if kind == "library":
            self.library_right = recorded_right(self.data_dir)

    async def aclose(self) -> None:
        for kind in KINDS:
            await self._replace(kind, None)

    async def _replace(self, kind: StoreKind, store: ObjectStore | None) -> None:
        old: ObjectStore | None = getattr(self, kind)
        setattr(self, kind, store)
        if kind == "library":
            self.library_right = None
            self.updates = {}
        if old is not None and old is not store:
            await old.aclose()


def _text(value: Any, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{what} is missing.")
    return value.strip()


def _word(value: Any, what: str) -> str:
    """One word of printable text, as a key is; the reason never names it."""
    text = _text(value, f"The {what}")
    if not text.isprintable() or any(char.isspace() for char in text):
        raise ValueError(f"The {what} is one word, without spaces or line breaks.")
    return text
