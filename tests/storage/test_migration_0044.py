"""Migration 0044 (DEL-314): an account linked to Google before email came, with no address of its own, gets the
address Google verified, confirmed, as linking gives it now; an account with an address, confirmed or waiting, keeps
it, and one whose identity has no verified address stays without. Plain UPDATE: no table is rebuilt."""

import sqlite3

from delve.config import Config
from delve.storage import open_storage
from tests.storage.test_migration_0020 import _upgrade_to
from tests.storage.test_migrations import HEAD, db_revision

NOW = "2026-10-30T12:00:00+00:00"


def test_migration_0044_fills_the_address_of_an_account_linked_to_google(tmp_path):
    config = Config(data_dir=tmp_path / "data")
    config.data_dir.mkdir()
    _upgrade_to(config, "0043_email")
    with sqlite3.connect(config.db_path) as db:
        for account, email, pending, google in (
            ("acc_linked", None, None, "ana@gmail.com"),
            ("acc_own", "mine@example.org", None, "bob@gmail.com"),
            ("acc_waiting", None, "typed@example.org", "cy@gmail.com"),
            ("acc_unverified", None, None, ""),
            ("acc_password", None, None, None),
        ):
            db.execute(
                "INSERT INTO accounts (id, username, created_at, display_name, email, email_pending) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (account, account, NOW, account, email, pending),
            )
            if google is not None:
                db.execute(
                    "INSERT INTO account_identities (provider, subject, account_id, email, linked_at) "
                    "VALUES ('google', ?, ?, ?, ?)",
                    (f"sub-{account}", account, google, NOW),
                )
    storage = open_storage(config)
    try:
        assert db_revision(config) == HEAD
    finally:
        storage.close()
    with sqlite3.connect(config.db_path) as db:
        got = {row[0]: (row[1], row[2]) for row in db.execute("SELECT id, email, email_pending FROM accounts")}
    assert got == {
        "acc_linked": ("ana@gmail.com", None),
        "acc_own": ("mine@example.org", None),
        "acc_waiting": (None, "typed@example.org"),
        "acc_unverified": (None, None),
        "acc_password": (None, None),
    }
