"""The two stores' connections (cloud storage plan Task 4): `backup-store.json`, `library-store.json` and `install-id`
in the data dir, at 0600 and written atomically, as `delve.images.connections` writes the owner's tokens. A credential
is written in and never shown: not in a repr, and not in an error.

Never a real call: the stores are `httpx.MockTransport` fakes or a local folder."""

import asyncio
import json
import os
import stat

import httpx
import pytest

from delve.cloud import connections
from delve.cloud.azure import AzureBlobStore
from delve.cloud.connections import (
    StoreConfig,
    Stores,
    check_config,
    install_id,
    library_right,
    load_store,
    open_store,
    record_right,
    recorded_right,
    same_place,
    save_store,
)
from delve.cloud.s3 import S3Store
from delve.cloud.store import LocalStore
from tests.cloud.test_azure import SIG, sas_url
from tests.cloud.test_s3 import BUCKET, ENDPOINT, KEY_ID, SECRET, FakeS3


def run(coro):
    return asyncio.run(coro)


def azure(sp="racwdl") -> StoreConfig:
    return StoreConfig(provider="azure", sas_url=sas_url(sp))


def s3(right=None, secret=SECRET) -> StoreConfig:
    return StoreConfig(
        provider="s3", endpoint=ENDPOINT, bucket=BUCKET, access_key_id=KEY_ID, secret_access_key=secret, right=right
    )


def test_a_store_file_is_0600_and_atomic(tmp_path, monkeypatch):
    save_store(tmp_path, "backup", azure(), keep_secret=False)
    path = tmp_path / "backup-store.json"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert load_store(tmp_path, "backup") == azure()
    assert load_store(tmp_path, "library") is None

    def interrupted(source, target):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", interrupted)
    with pytest.raises(OSError):
        save_store(tmp_path, "backup", s3(), keep_secret=False)
    assert load_store(tmp_path, "backup") == azure(), "a write that failed leaves the stored file whole"
    assert sorted(item.name for item in tmp_path.iterdir()) == ["backup-store.json"], "no temporary file is left"

    monkeypatch.undo()
    save_store(tmp_path, "backup", None, keep_secret=False)
    assert not path.exists()
    assert load_store(tmp_path, "backup") is None


def test_keep_secret_keeps_the_stored_sas(tmp_path):
    save_store(tmp_path, "library", azure(), keep_secret=False)
    save_store(tmp_path, "library", StoreConfig(provider="azure"), keep_secret=True)
    assert load_store(tmp_path, "library").sas_url == sas_url()

    save_store(tmp_path, "backup", s3(), keep_secret=False)
    save_store(tmp_path, "backup", s3(secret=""), keep_secret=True)
    assert load_store(tmp_path, "backup").secret_access_key == SECRET
    # Another access key gets no stored secret: it was the old key's.
    with pytest.raises(ValueError) as error:
        save_store(tmp_path, "backup", StoreConfig(
            provider="s3", endpoint=ENDPOINT, bucket=BUCKET, access_key_id="OTHERKEY"), keep_secret=True)
    assert SECRET not in str(error.value)
    assert load_store(tmp_path, "backup").access_key_id == KEY_ID, "nothing is written for a refused one"
    with pytest.raises(ValueError):
        save_store(tmp_path, "library", StoreConfig(provider="azure"), keep_secret=False)


def test_a_refused_config_names_no_credential(tmp_path):
    for config in (
        StoreConfig(provider="azure", sas_url="http://delveacct.blob.core.windows.net/delve?sv=1&sig=" + SIG),
        StoreConfig(provider="azure", sas_url=f"https://delveacct.blob.core.windows.net/?sv=1&sig={SIG}"),
        StoreConfig(provider="s3", endpoint="http://acct.r2.cloudflarestorage.com", bucket=BUCKET,
                    access_key_id=KEY_ID, secret_access_key=SECRET),
        StoreConfig(provider="s3", endpoint=ENDPOINT, bucket=BUCKET, access_key_id=KEY_ID,
                    secret_access_key=SECRET + " two words"),
        s3(right="read"),
        StoreConfig(provider="local", root="relative/folder"),
        StoreConfig(provider="ftp"),  # type: ignore[arg-type]
    ):
        with pytest.raises(ValueError) as error:
            save_store(tmp_path, "backup", config, keep_secret=False)
        assert SIG not in str(error.value) and SECRET not in str(error.value)
        assert "SECRET" not in repr(error.value)
    assert not (tmp_path / "backup-store.json").exists()


def test_the_install_id_is_made_once(tmp_path):
    made = install_id(tmp_path)
    assert made.startswith("ins_") and len(made) == 16
    int(made.removeprefix("ins_"), 16)
    assert install_id(tmp_path) == made
    path = tmp_path / "install-id"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert path.read_text().strip() == made


def test_repr_holds_no_secret(tmp_path):
    for config in (azure(), s3()):
        shown = repr(config) + str(config)
        assert SIG not in shown and "sig=" not in shown and SECRET not in shown
    assert "delveacct.blob.core.windows.net/delve" in repr(azure())
    assert ENDPOINT in repr(s3())


def test_open_store_gives_each_provider(tmp_path):
    async def go():
        client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(500)))
        opened = [
            open_store(azure(), client),
            open_store(s3(), client),
            open_store(StoreConfig(provider="local", root=str(tmp_path)), client),
        ]
        await client.aclose()
        return opened

    opened = run(go())
    assert [type(store) for store in opened] == [AzureBlobStore, S3Store, LocalStore]
    assert opened[2].label == str(tmp_path)


@pytest.mark.parametrize(
    ("allow", "choice", "right"),
    [
        (("list", "get"), None, "read"),
        (("list", "get"), "manage", "read"),
        (("list", "get", "create", "put", "delete"), None, "publish"),
        (("list", "get", "create", "put", "delete"), "publish", "publish"),
        (("list", "get", "create", "put", "delete"), "manage", "manage"),
    ],
)
def test_an_s3_write_credential_is_capped_by_the_owners_choice(allow, choice, right):
    """R2 enforces only read versus write; the owner's choice of publish or manage is Delve's own cap."""
    fake = FakeS3(allow=allow)
    config = s3(right=choice)
    assert run(library_right(fake.store(), config)) == right
    assert fake.objects == {}, "the probe cleaned up after itself"


def test_azure_and_local_rights_are_the_probes(tmp_path):
    from tests.cloud.test_azure import FakeAzure

    fake = FakeAzure("rl")
    store = AzureBlobStore(sas_url("rl"), client=httpx.AsyncClient(transport=httpx.MockTransport(fake)))
    assert run(library_right(store, azure("rl"))) == "read"
    local = StoreConfig(provider="local", root=str(tmp_path), right="publish")
    assert run(library_right(LocalStore(tmp_path), local)) == "manage", "only an S3 right is capped"


def test_stores_build_the_saved_stores_and_close_them(tmp_path):
    (tmp_path / "backup").mkdir()
    save_store(tmp_path, "backup", StoreConfig(provider="local", root=str(tmp_path / "backup")), keep_secret=False)
    save_store(tmp_path, "library", s3(right="manage"), keep_secret=False)
    record_right(tmp_path, "manage")
    closed = []

    async def go():
        stores = Stores(tmp_path, transport=httpx.MockTransport(FakeS3().handle))
        await stores.start()
        found = (type(stores.backup), type(stores.library), stores.library_right)
        client = stores.library._client
        save_store(tmp_path, "library", None, keep_secret=False)
        await stores.reload("library")
        closed.append(client.is_closed)
        found += (stores.library, stores.library_right)
        await stores.aclose()
        return found

    assert run(go()) == (LocalStore, S3Store, "manage", None, None)
    assert closed == [True], "the replaced store's client is closed"


@pytest.mark.parametrize("recorded", [None, "read", "publish", "manage"])
def test_start_makes_no_request_to_the_store(tmp_path, recorded):
    """A probe on a publish-only SAS leaves its object behind, so a start never probes: it takes the right PUT or Test
    recorded."""
    save_store(tmp_path, "backup", azure(), keep_secret=False)
    save_store(tmp_path, "library", azure("rcl"), keep_secret=False)
    record_right(tmp_path, recorded)
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(500)

    async def go():
        stores = Stores(tmp_path, transport=httpx.MockTransport(handler))
        await stores.start()
        found = (type(stores.backup), type(stores.library), stores.library_right)
        await stores.aclose()
        return found

    assert run(go()) == (AzureBlobStore, AzureBlobStore, recorded)
    assert requests == []


def test_the_recorded_right_stays_beside_the_config(tmp_path):
    record_right(tmp_path, "manage")
    assert not (tmp_path / "library-store.json").exists(), "nothing is recorded without a library"
    save_store(tmp_path, "library", s3(right="manage"), keep_secret=False)
    record_right(tmp_path, "publish")
    path = tmp_path / "library-store.json"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert json.loads(path.read_text())["probed"] == "publish"
    assert recorded_right(tmp_path) == "publish"
    assert load_store(tmp_path, "library") == s3(right="manage"), "the config reads as before"
    record_right(tmp_path, None)
    assert recorded_right(tmp_path) is None
    assert "probed" not in json.loads(path.read_text())
    path.write_text(json.dumps({**json.loads(path.read_text()), "probed": "everything"}))
    assert recorded_right(tmp_path) is None


def test_a_broken_store_file_is_no_store(tmp_path):
    (tmp_path / "backup-store.json").write_text("{not json")
    assert load_store(tmp_path, "backup") is None
    (tmp_path / "library-store.json").write_text(json.dumps({"provider": "azure", "sas_url": "nonsense"}))
    assert load_store(tmp_path, "library") is None
    assert connections.STORE_FILES == {"backup": "backup-store.json", "library": "library-store.json"}


def azure_at(url: str) -> StoreConfig:
    return check_config(StoreConfig(provider="azure", sas_url=f"{url}?sv=1&sig=x"))


def s3_at(endpoint: str, bucket: str = "lib") -> StoreConfig:
    return check_config(StoreConfig(provider="s3", endpoint=endpoint, bucket=bucket, access_key_id="a",
                                    secret_access_key="s"))


@pytest.mark.parametrize("url", [
    "https://acc.blob.core.windows.net:443/backups",
    "https://ACC.blob.core.windows.net/backups",
    "https://acc.blob.core.windows.net./backups",
    "https://acc.blob.core.windows.net//backups",
    "https://acc.blob.core.windows.net/backups/",
    "https://acc.blob.core.windows.net:443//Backups//",
])
def test_one_azure_container_written_otherwise_is_the_same_place(url):
    assert same_place(azure_at("https://acc.blob.core.windows.net/backups"), azure_at(url))


@pytest.mark.parametrize("url", [
    "https://acc.blob.core.windows.net/library",
    "https://other.blob.core.windows.net/backups",
    "https://acc.blob.core.windows.net:8443/backups",
])
def test_another_azure_container_is_another_place(url):
    assert not same_place(azure_at("https://acc.blob.core.windows.net/backups"), azure_at(url))


@pytest.mark.parametrize("endpoint", [
    "https://acct.r2.cloudflarestorage.com:443",
    "https://ACCT.r2.cloudflarestorage.com.",
    "https://acct.r2.cloudflarestorage.com./",
])
def test_one_s3_bucket_written_otherwise_is_the_same_place(endpoint):
    assert same_place(s3_at("https://acct.r2.cloudflarestorage.com"), s3_at(endpoint))


def test_another_s3_endpoint_port_or_bucket_is_another_place():
    base = s3_at("https://acct.r2.cloudflarestorage.com")
    assert not same_place(base, s3_at("https://acct.r2.cloudflarestorage.com:8443"))
    assert not same_place(base, s3_at("https://other.r2.cloudflarestorage.com"))
    assert not same_place(base, s3_at("https://acct.r2.cloudflarestorage.com", "backups"))


def test_a_sas_url_with_userinfo_is_refused():
    with pytest.raises(ValueError):
        azure_at("https://x@acc.blob.core.windows.net/backups")
