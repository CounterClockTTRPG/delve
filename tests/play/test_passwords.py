"""Passwords (players and tavern Task B2): scrypt hashes that carry their own parameters, and checks that never raise."""

import hashlib
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from delve.play import passwords
from delve.play.passwords import check_password, dummy_check, hash_password


def test_hash_round_trip():
    stored = hash_password("correct horse battery")
    assert check_password("correct horse battery", stored)
    assert not check_password("correct horse battery!", stored)
    assert not check_password("", stored)
    assert "correct horse battery" not in stored


def test_salted():
    assert hash_password("correct horse battery") != hash_password("correct horse battery")


@pytest.mark.real_scrypt
def test_parameters_stored(monkeypatch):
    assert passwords.SCRYPT_N == 2**15
    assert hash_password("correct horse battery").startswith("scrypt$32768$8$1$")
    monkeypatch.setattr(passwords, "SCRYPT_N", 2**10)
    older = hash_password("correct horse battery")
    assert older.startswith("scrypt$1024$8$1$")
    monkeypatch.setattr(passwords, "SCRYPT_N", 2**15)
    assert check_password("correct horse battery", older), "a hash checks with the parameters it was made with"


def test_fast_in_tests():
    assert passwords.SCRYPT_N == 2**10, "the fast_scrypt fixture of tests/conftest.py"


@pytest.mark.parametrize(
    "stored",
    [
        "",
        None,
        "scrypt$x",
        "bcrypt$2b$12$abcdefghijklmnopqrstuv",
        "scrypt$1024$8$1$not base64!$a2V5",
        "scrypt$1000$8$1$c2FsdA$a2V5",  # n not a power of 2
        "scrypt$1073741824$8$1$c2FsdA$a2V5",  # past the memory cap
        "scrypt$-1$8$1$c2FsdA$a2V5",
        "scrypt$1024$8$1$c2FsdA$",
    ],
)
def test_malformed_is_false(stored):
    assert check_password("correct horse battery", stored) is False


def test_dummy_check_costs_a_check():
    assert dummy_check("anything at all") is None


def test_at_most_four_scrypt_checks_at_once(monkeypatch):
    """Audit finding 4: forty parallel logins took forty scrypt runs of 32 MB each."""
    running, most, lock = [0], [0], threading.Lock()
    real = hashlib.scrypt

    def counted(*args, **kwargs):
        with lock:
            running[0] += 1
            most[0] = max(most[0], running[0])
        time.sleep(0.05)
        try:
            return real(*args, **kwargs)
        finally:
            with lock:
                running[0] -= 1

    stored = hash_password("correct horse battery")
    monkeypatch.setattr(hashlib, "scrypt", counted)
    with ThreadPoolExecutor(12) as pool:
        assert all(pool.map(lambda _: check_password("correct horse battery", stored), range(12)))
    assert most[0] == passwords.SCRYPT_AT_ONCE == 4


def test_scrypt_waits_then_is_busy(monkeypatch):
    """Clara's final audit, finding 3: a check that waits `SCRYPT_WAIT_S` for a place raises `PasswordsBusy`, never
    answers False, and gives no place away."""
    stored = hash_password("correct horse battery")
    monkeypatch.setattr(passwords, "SCRYPT_WAIT_S", 0.01)
    monkeypatch.setattr(passwords, "_running", threading.BoundedSemaphore(1))
    passwords._running.acquire()
    with pytest.raises(passwords.PasswordsBusy):
        check_password("correct horse battery", stored)
    with pytest.raises(passwords.PasswordsBusy):
        hash_password("correct horse battery")
    passwords._running.release()
    assert check_password("correct horse battery", stored)
    assert passwords.SCRYPT_WAIT_S == 0.01 and passwords.PasswordsBusy.__mro__[1] is RuntimeError
