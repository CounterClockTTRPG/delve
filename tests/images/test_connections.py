"""The owner's connections (portraits plan Task 3): the Replicate token and assetgen's URL and token, in files under the
data dir at 0600, and the URL guard against server-side request forgery (Review Focus 5). Never a real call: the
guard's resolver is a fake, and the tests use a planted token."""

import json
import stat

import pytest

from delve.domain.backends import Registry
from delve.images import connections
from delve.images.connections import (
    ASSETGEN_FILE,
    KEEP,
    Assetgen,
    ConnectionError,
    check_url,
    load_assetgen,
    register_replicate,
    remove_assetgen,
    remove_replicate,
    replicate_state,
    save_assetgen,
    save_replicate,
)
from delve.images.replicate import REPLICATE, TOKEN_ENV, TOKEN_FILE, load_token

TOKEN = "tok-SECRET-XYZZY"


def mode(path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_replicate_state_follows_the_file_and_the_environment(tmp_path):
    assert replicate_state(tmp_path, {}) == "unset"
    save_replicate(tmp_path, TOKEN)
    assert replicate_state(tmp_path, {}) == "set"
    assert replicate_state(tmp_path, {TOKEN_ENV: "r8_other"}) == "environment", "the environment wins"
    remove_replicate(tmp_path)
    assert replicate_state(tmp_path, {}) == "unset"
    remove_replicate(tmp_path)  # removing nothing is fine


def test_save_replicate_writes_the_token_at_0600(tmp_path):
    data_dir = tmp_path / "data"
    save_replicate(data_dir, f"  {TOKEN}\n")
    path = data_dir / TOKEN_FILE
    assert mode(path) == 0o600
    assert path.read_text() == TOKEN + "\n"
    assert load_token(data_dir, {}) == TOKEN
    assert [p.name for p in data_dir.iterdir()] == [TOKEN_FILE], "no temporary file is left behind"


def test_save_replicate_replaces_a_wider_file(tmp_path):
    path = tmp_path / TOKEN_FILE
    path.write_text("old")
    path.chmod(0o644)
    save_replicate(tmp_path, TOKEN)
    assert mode(path) == 0o600 and path.read_text().strip() == TOKEN


@pytest.mark.parametrize("token", ["", "   ", "two words", "line\nbreak", "tab\there", "nul\x00", 42, None])
def test_save_replicate_refuses_a_token_that_is_not_one(tmp_path, token):
    with pytest.raises((TypeError, ValueError)) as excinfo:
        save_replicate(tmp_path, token)
    assert not (tmp_path / TOKEN_FILE).exists()
    assert not isinstance(token, str) or token.strip() == "" or token not in str(excinfo.value)


def test_assetgen_is_stored_at_0600_and_keeps_its_token(tmp_path):
    assert load_assetgen(tmp_path) is None
    save_assetgen(tmp_path, "http://localhost:8765/", TOKEN)
    path = tmp_path / ASSETGEN_FILE
    assert mode(path) == 0o600
    assert json.loads(path.read_text()) == {"url": "http://localhost:8765", "token": TOKEN}
    assert load_assetgen(tmp_path) == Assetgen("http://localhost:8765", TOKEN)

    save_assetgen(tmp_path, "http://127.0.0.1:8766", KEEP)
    assert load_assetgen(tmp_path) == Assetgen("http://127.0.0.1:8766", TOKEN), "KEEP keeps the stored token"
    save_assetgen(tmp_path, "http://127.0.0.1:8766", None)
    assert load_assetgen(tmp_path) == Assetgen("http://127.0.0.1:8766", None), "None removes it"
    save_assetgen(tmp_path, "http://127.0.0.1:8766", KEEP)
    assert load_assetgen(tmp_path) == Assetgen("http://127.0.0.1:8766", None)

    remove_assetgen(tmp_path)
    assert load_assetgen(tmp_path) is None
    remove_assetgen(tmp_path)


def test_assetgen_refuses_a_bad_url_and_keeps_what_was_stored(tmp_path):
    save_assetgen(tmp_path, "http://localhost:8765", TOKEN)
    with pytest.raises(ConnectionError):
        save_assetgen(tmp_path, "http://169.254.169.254", KEEP)
    assert load_assetgen(tmp_path) == Assetgen("http://localhost:8765", TOKEN)


def test_a_broken_assetgen_file_is_no_connection(tmp_path):
    (tmp_path / ASSETGEN_FILE).write_text("{not json")
    assert load_assetgen(tmp_path) is None
    (tmp_path / ASSETGEN_FILE).write_text(json.dumps({"url": "file:///etc/passwd"}))
    assert load_assetgen(tmp_path) is None, "a URL the guard refuses is never loaded"


def test_assetgen_repr_hides_its_token():
    assert TOKEN not in repr(Assetgen("http://localhost:8765", TOKEN))
    assert TOKEN not in str(Assetgen("http://localhost:8765", TOKEN))


def fake_resolver(table: dict[str, list[str]]):
    def resolve(host: str, port: int) -> list[str]:
        if host not in table:
            raise OSError("no such host")
        return table[host]

    return resolve


RESOLVER = fake_resolver(
    {
        "localhost": ["127.0.0.1", "::1"],
        "example.com": ["93.184.215.14"],
        "nas.lan": ["192.168.1.20"],
        "sneaky.lan": ["192.168.1.20", "93.184.215.14"],
        "metadata.lan": ["169.254.169.254"],
    }
)


@pytest.mark.parametrize(
    ("url", "normalised"),
    [
        ("http://localhost:8765", "http://localhost:8765"),
        ("http://localhost:8765/", "http://localhost:8765"),
        ("HTTP://LocalHost:8765", "http://localhost:8765"),
        ("http://[::1]:8765", "http://[::1]:8765"),
        ("http://127.0.0.1:8765", "http://127.0.0.1:8765"),
        ("https://10.0.0.5", "https://10.0.0.5"),
        ("http://172.16.4.2:8765", "http://172.16.4.2:8765"),
        ("http://192.168.1.20:8765", "http://192.168.1.20:8765"),
        ("http://nas.lan:8765", "http://nas.lan:8765"),
        ("http://[fd00::5]:8765", "http://[fd00::5]:8765"),
        ("  http://localhost:8765  ", "http://localhost:8765"),
    ],
)
def test_check_url_accepts_loopback_and_private_addresses(url, normalised):
    assert check_url(url, resolve=RESOLVER) == normalised


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/",  # the cloud's metadata service: link-local, never private enough
        "http://metadata.lan",
        "file:///etc/passwd",
        "http://example.com",
        "http://sneaky.lan:8765",  # every address must pass, not just one
        "http://localhost:8765/../../",
        "http://localhost:8765/api",
        "http://localhost:8765?x=1",
        "http://localhost:8765#top",
        "http://user:pass@localhost:8765",
        "http://0.0.0.0:8765",
        "http://[::ffff:169.254.169.254]",
        "http://100.64.0.1",
        "http://8.8.8.8",
        "ftp://localhost",
        "localhost:8765",
        "http://",
        "http://nowhere.lan",
        "http://localhost:99999",
        "",
    ],
)
def test_check_url_refuses_everything_else(url):
    with pytest.raises(ConnectionError) as excinfo:
        check_url(url, resolve=RESOLVER)
    assert str(excinfo.value), "with a reason"


def test_check_url_resolves_names_by_default(monkeypatch):
    seen = []

    def getaddrinfo(host, port, *args, **kwargs):
        seen.append((host, port))
        return [(None, None, None, "", ("93.184.215.14", port))]

    monkeypatch.setattr(connections.socket, "getaddrinfo", getaddrinfo)
    with pytest.raises(ConnectionError):
        check_url("http://rebound.lan:8765")
    assert seen == [("rebound.lan", 8765)]


def test_register_replicate_follows_the_token(tmp_path):
    registry: Registry[object] = Registry()
    register_replicate(registry, tmp_path, {})
    assert REPLICATE not in [caps.id for caps in registry.capabilities()]

    save_replicate(tmp_path, TOKEN)
    register_replicate(registry, tmp_path, {})
    assert [caps.id for caps in registry.capabilities()] == [REPLICATE]
    register_replicate(registry, tmp_path, {})
    assert [caps.id for caps in registry.capabilities()] == [REPLICATE], "registering again replaces it"

    remove_replicate(tmp_path)
    register_replicate(registry, tmp_path, {})
    assert registry.capabilities() == []
    register_replicate(registry, tmp_path, {TOKEN_ENV: TOKEN})
    assert [caps.id for caps in registry.capabilities()] == [REPLICATE], "the environment's token registers it"
