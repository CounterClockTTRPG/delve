"""The browsers an account logged in on before: the device cookie (DEL-154, audit finding 8; OWASP's "device
cookies").

A login that succeeds sets `delve_device` to `<account id>.<issued>.<nonce>.<mac>`, the MAC an HMAC-SHA256 of the rest
with `<data dir>/device-secret` (32 random bytes as hex, mode 0600). Nothing is stored per device: the server knows a
cookie is its own by the MAC, and how old it is by `issued` (Unix seconds), valid `DEVICE_DAYS`. The login throttle
lets a valid cookie for the account being logged in to past that username's lock from everywhere, so strangers can't
lock its owner out of a browser they used before; the device has a lock of its own instead (`LoginThrottle`).

A cookie gives no rights: it doesn't log anyone in, and only ever spares a lock. Making a new `device-secret` (delete
the file and restart Delve) ends every device cookie at once.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from pathlib import Path

DEVICE_DAYS = 365
DEVICE_SECRET_FILE = "device-secret"


def device_secret_path(data_dir: Path) -> Path:
    return data_dir / DEVICE_SECRET_FILE


def _mac(secret: str, body: str) -> str:
    digest = hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def new_device_cookie(secret: str, account_id: str, now: float) -> str:
    """A device cookie's value for `account_id`, issued at `now` (Unix seconds)."""
    body = f"{account_id}.{int(now)}.{secrets.token_urlsafe(16)}"
    return f"{body}.{_mac(secret, body)}"


def device_of(secret: str, value: str | None, account_id: str | None, now: float) -> str | None:
    """The device's nonce when `value` is a device cookie this server made for `account_id`, at most `DEVICE_DAYS`
    old; else None (no cookie, another account's, a forged or an expired one)."""
    if not value or account_id is None:
        return None
    parts = value.split(".")
    if len(parts) != 4:
        return None
    owner, issued, nonce, mac = parts
    if not hmac.compare_digest(mac.encode(), _mac(secret, f"{owner}.{issued}.{nonce}").encode()):
        return None
    if owner != account_id or not issued.isdigit() or not 0 <= now - int(issued) <= DEVICE_DAYS * 24 * 60 * 60:
        return None
    return nonce
