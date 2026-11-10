"""The Email connection's settings (DEL-314): which provider sends, the address mail comes from, and the public URL
its links start with, in `<data dir>/mail.json`; Emailit's API key in `<data dir>/emailit-key` (0600), unless
`EMAILIT_API_KEY` holds one, which wins, as `REPLICATE_API_TOKEN` does. The key is never read back to the web.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from delve.images.connections import write_secret

SETTINGS_FILE = "mail.json"
KEY_ENV = "EMAILIT_API_KEY"
KEY_FILE = "emailit-key"
ALLOWED_HOSTS_ENV = "DELVE_ALLOWED_HOSTS"
"""Read here as `delve.web.guard.allowed_hosts` reads it: `delve.mail` doesn't import the web layer."""
PROVIDERS = ("log", "emailit")

KeyState = Literal["unset", "set", "environment"]


@dataclass(frozen=True)
class MailSettings:
    """`log` writes each message's kind, account and subject to the log and sends nothing; `emailit` sends."""

    provider: Literal["log", "emailit"] = "log"
    sender: str = ""
    public_url: str = ""


def load(data_dir: Path) -> MailSettings:
    """The saved settings; the defaults without a file, or when it is broken."""
    try:
        stored = json.loads((data_dir / SETTINGS_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return MailSettings()
    if not isinstance(stored, dict):
        return MailSettings()
    provider = stored.get("provider")
    sender, public_url = stored.get("sender"), stored.get("public_url")
    return MailSettings(
        provider=provider if provider in PROVIDERS else "log",
        sender=sender if isinstance(sender, str) else "",
        public_url=public_url if isinstance(public_url, str) else "",
    )


def save(data_dir: Path, settings: MailSettings) -> None:
    write_secret(data_dir / SETTINGS_FILE, json.dumps(asdict(settings), indent=2) + "\n")


def _key(key: str) -> str:
    """The key stripped; `TypeError` or `ValueError` (never naming it) when it isn't one word of printable text."""
    if not isinstance(key, str):
        raise TypeError("The key must be text.")
    key = key.strip()
    if not key:
        raise ValueError("The key is empty.")
    if not key.isprintable() or any(char.isspace() for char in key):
        raise ValueError("A key is one word, without spaces or line breaks.")
    return key


def load_key(data_dir: Path, environ: Mapping[str, str] | None = None) -> str | None:
    """Emailit's key: `EMAILIT_API_KEY`, else `<data dir>/emailit-key`; None without one."""
    environ = os.environ if environ is None else environ
    key = environ.get(KEY_ENV, "").strip()
    if key:
        return key
    try:
        key = (data_dir / KEY_FILE).read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return key or None


def key_state(data_dir: Path, environ: Mapping[str, str] | None = None) -> KeyState:
    """`environment` when `EMAILIT_API_KEY` holds a key (it wins), `set` when the file does, else `unset`."""
    environ = os.environ if environ is None else environ
    if environ.get(KEY_ENV, "").strip():
        return "environment"
    return "set" if load_key(data_dir, {}) is not None else "unset"


def save_key(data_dir: Path, key: str) -> None:
    write_secret(data_dir / KEY_FILE, _key(key) + "\n")


def remove_key(data_dir: Path) -> None:
    (data_dir / KEY_FILE).unlink(missing_ok=True)


def _allowed_hosts(env: Mapping[str, str]) -> set[str]:
    """`DELVE_ALLOWED_HOSTS`'s names as `guard.allowed_hosts` takes them: lowercased, without a port."""
    names = set()
    for entry in env.get(ALLOWED_HOSTS_ENV, "").split(","):
        entry = entry.strip().lower()
        if not entry:
            continue
        if entry.startswith("["):
            entry = entry[1 : entry.find("]")] if "]" in entry else ""
        elif ":" in entry:
            entry = entry.rpartition(":")[0]
        if entry:
            names.add(entry)
    return names


def default_public_url(env: Mapping[str, str] | None = None) -> str | None:
    """`https://<name>` when Delve answers on exactly one name besides its addresses, else None."""
    names = _allowed_hosts(os.environ if env is None else env)
    return f"https://{next(iter(names))}" if len(names) == 1 else None


def public_url(data_dir: Path, env: Mapping[str, str] | None = None) -> str | None:
    """Where a link in an email points: the saved public URL, else the default (`default_public_url`), else None."""
    saved = load(data_dir).public_url.strip().rstrip("/")
    return saved or default_public_url(env)


def mail_enabled(data_dir: Path, environ: Mapping[str, str] | None = None) -> bool:
    """Whether mail really goes: Emailit chosen, with a key, a sender and a public URL."""
    settings = load(data_dir)
    return (
        settings.provider == "emailit"
        and load_key(data_dir, environ) is not None
        and bool(settings.sender.strip())
        and public_url(data_dir, environ) is not None
    )
