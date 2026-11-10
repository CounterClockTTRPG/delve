"""Passwords (players and tavern Task B2): scrypt from `hashlib`, stored as
`scrypt$<n>$<r>$<p>$<salt>$<key>` (URL-safe base64 without padding), so a hash checks with the parameters it was
made with after Delve's own change. A check never raises for a hash, and never logs or says the password; it raises
`PasswordsBusy` when no scrypt place frees up in `SCRYPT_WAIT_S` (Clara's final audit, finding 3)."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import secrets
import threading

SCRYPT_N = 2**15
SCRYPT_R = 8
SCRYPT_P = 1
SALT_BYTES = 16
KEY_BYTES = 32
MAXMEM = 64 * 1024 * 1024
SCRYPT_AT_ONCE = 4
"""At most this many scrypt runs at once (32 MB each), however many logins come in together (audit-auth finding 4)."""

SCRYPT_WAIT_S = 10.0
BUSY = "Busy: try again in a moment."

_running = threading.BoundedSemaphore(SCRYPT_AT_ONCE)


class PasswordsBusy(RuntimeError):
    """Every scrypt place stayed taken for `SCRYPT_WAIT_S`: nothing was checked or hashed. Not a `PlayError`, so no
    route mistakes it for a wrong password; the web answers it 503."""


_dummies: dict[int, str] = {}


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _scrypt(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    if not _running.acquire(timeout=SCRYPT_WAIT_S):
        raise PasswordsBusy(BUSY)
    try:
        return hashlib.scrypt(password.encode(), salt=salt, n=n, r=r, p=p, maxmem=MAXMEM, dklen=KEY_BYTES)
    finally:
        _running.release()


def hash_password(password: str) -> str:
    """The password's hash with a fresh salt, at Delve's current parameters."""
    salt = secrets.token_bytes(SALT_BYTES)
    key = _scrypt(password, salt, SCRYPT_N, SCRYPT_R, SCRYPT_P)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${_b64(salt)}${_b64(key)}"


def check_password(password: str, stored: str | None) -> bool:
    """Whether `password` is the one `stored` was made from; False for no hash or a malformed one."""
    if not stored:
        return False
    try:
        scheme, n, r, p, salt, key = stored.split("$")
        if scheme != "scrypt" or not salt or not key:
            return False
        expected = _unb64(key)
        computed = _scrypt(password, _unb64(salt), int(n), int(r), int(p))
    except (ValueError, TypeError, OverflowError, MemoryError, binascii.Error):
        return False
    return hmac.compare_digest(computed, expected)


def dummy_check(password: str) -> None:
    """Check `password` against a hash nobody's password made, so a login for an unknown username costs what one for
    a known username does."""
    if SCRYPT_N not in _dummies:
        _dummies[SCRYPT_N] = hash_password(secrets.token_urlsafe(16))
    check_password(password, _dummies[SCRYPT_N])
