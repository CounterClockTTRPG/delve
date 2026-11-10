import pytest
from fastapi.testclient import TestClient

from delve.web import guard
from delve.web.app import create_app
from delve.web.guard import CSP, host_of

CORS_ORIGIN = "http://evil.example"


@pytest.fixture
def echo(app):
    @app.post("/api/echo")
    async def echo_route(body: dict):
        return body

    return app


def test_post_form_encoded_415(echo, local):
    response = local.post("/api/echo", data={"a": "1"})
    assert response.status_code == 415
    assert "application/json" in response.json()["error"]


def test_write_without_content_type_415(echo, local):
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        assert local.request(method, "/api/echo").status_code == 415


def test_post_json_passes(echo, local):
    response = local.post("/api/echo", json={"a": 1})
    assert response.status_code == 200
    assert response.json() == {"a": 1}
    assert local.post(
        "/api/echo", content=b"{}", headers={"Content-Type": "application/json; charset=utf-8"}
    ).is_success


def test_a_json_body_past_the_limit_is_refused_before_any_route(echo, local, monkeypatch):
    """DEL-159: 413 for a JSON body that says it is past `JSON_LIMIT`, and for one sent in chunks with no
    Content-Length that passes it; a body within it, chunked or not, reaches the route whole."""
    monkeypatch.setattr(guard, "JSON_LIMIT", 1000)
    big = b'{"a": "' + b"x" * 1000 + b'"}'

    said = local.post("/api/echo", content=big, headers={"Content-Type": "application/json"})
    assert said.status_code == 413 and "JSON body" in said.json()["error"]

    def chunks(body: bytes):
        for at in range(0, len(body), 100):
            yield body[at : at + 100]

    chunked = local.post("/api/echo", content=chunks(big), headers={"Content-Type": "application/json"})
    assert chunked.status_code == 413

    small = b'{"a": "' + b"x" * 500 + b'"}'
    passed = local.post("/api/echo", content=chunks(small), headers={"Content-Type": "application/json"})
    assert passed.status_code == 200 and passed.json() == {"a": "x" * 500}
    assert local.put("/api/echo", json={"a": 1}).status_code == 405, "a write of another method is read and routed"


def test_cross_origin_403(echo, local):
    response = local.post("/api/echo", json={}, headers={"Origin": CORS_ORIGIN})
    assert response.status_code == 403
    assert response.json() == {"error": "cross-origin requests are refused"}
    assert local.get("/api/health", headers={"Origin": "http://localhost:7811"}).status_code == 403
    assert local.get("/api/health", headers={"Origin": "null"}).status_code == 403


def test_same_origin_passes(echo, local):
    assert local.post("/api/echo", json={}, headers={"Origin": "http://localhost:7810"}).status_code == 200
    assert local.get("/api/health", headers={"Origin": "http://LOCALHOST:7810"}).status_code == 200


def test_bad_host_421(app):
    with TestClient(app, base_url="http://evil.example:7810", client=("127.0.0.1", 50000)) as client:
        response = client.get("/api/health")
    assert response.status_code == 421
    assert "evil.example" in response.json()["error"]
    assert response.headers["content-security-policy"] == CSP


@pytest.mark.parametrize("base_url", ["http://localhost", "http://127.0.0.1:7810", "http://[::1]:9999"])
def test_loopback_hosts_allowed(app, base_url):
    with TestClient(app, base_url=base_url) as client:
        assert client.get("/api/health").status_code == 200


def test_machine_address_allowed(app, monkeypatch):
    monkeypatch.setattr(guard, "machine_addresses", lambda: {"192.168.1.20"})
    with TestClient(app, base_url="http://192.168.1.20:7810") as client:
        assert client.get("/api/health").status_code == 200


def test_allowed_hosts_env(config, storage, registries, static_dir, monkeypatch):
    monkeypatch.setenv("DELVE_ALLOWED_HOSTS", "delve.lan, Table.Example ")
    app = create_app(config, storage, registries, static_dir=static_dir)
    for base_url in ("http://delve.lan:7810", "http://table.example"):
        with TestClient(app, base_url=base_url) as client:
            assert client.get("/api/health").status_code == 200
    with TestClient(app, base_url="http://other.lan") as client:
        assert client.get("/api/health").status_code == 421


def test_csp_header_present(local):
    for path in ("/api/health", "/settings", "/api/nope"):
        response = local.get(path)
        assert response.headers["content-security-policy"] == CSP
        assert response.headers["x-content-type-options"] == "nosniff"
    assert CSP == (
        "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; object-src 'none'; "
        "base-uri 'none'; frame-ancestors 'none'; form-action 'self'; worker-src 'self' blob:"
    )


def test_csp_has_worker_src_and_no_external_hosts(local):
    """Monaco's editor worker runs from the bundle (or a blob of it); nothing loads from another host."""
    csp = local.get("/maps/mod_000000000000/map").headers["content-security-policy"]
    directives = dict(d.strip().split(" ", 1) for d in csp.split(";"))
    assert directives["worker-src"] == "'self' blob:"
    assert "http" not in csp.lower()
    assert "*" not in csp
    for sources in directives.values():
        for source in sources.split():
            assert source in {"'self'", "'none'", "'unsafe-inline'", "data:", "blob:"}, source


@pytest.mark.parametrize(
    ("header", "host"),
    [("localhost:7810", "localhost"), ("[::1]:7810", "::1"), ("[::1]", "::1"), ("Delve.LAN", "delve.lan"), ("", "")],
)
def test_host_of(header, host):
    assert host_of(header) == host


def test_machine_addresses_include_no_loopback_name():
    addresses = guard.machine_addresses()
    assert all(isinstance(a, str) for a in addresses)
    assert "localhost" not in addresses


def test_lan_addresses_leave_out_loopback_link_local_and_bridges(monkeypatch):
    pairs = [
        ("lo", "127.0.0.1"),
        ("wlan0", "192.168.1.20"),
        ("docker0", "172.17.0.1"),
        ("br-1a2b", "172.18.0.1"),
        ("eth0", "10.0.0.5"),
        ("eth0", "fe80::1"),
        ("eth0", "2001:db8::5"),
        ("lo", "::1"),
    ]
    monkeypatch.setattr(guard, "_interface_addresses", lambda: iter(pairs))
    assert guard.lan_addresses() == ["10.0.0.5", "192.168.1.20", "2001:db8::5"]
    assert guard.machine_addresses() == {address for _, address in pairs}


def test_avatar_wrong_type_415(local):
    for media_type in ("image/gif", "image/svg+xml", "application/json", "text/plain"):
        response = local.post(guard.AVATAR_PATH, content=b"GIF89a", headers={"Content-Type": media_type})
        assert response.status_code == 415, media_type
        assert response.json() == {"error": "send an avatar as one of image/jpeg, image/png, image/webp"}


def test_avatar_too_large_413(local):
    headers = {"Content-Type": "image/png", "Content-Length": str(guard.AVATAR_LIMIT + 1)}
    response = local.post(guard.AVATAR_PATH, content=b"\0" * (guard.AVATAR_LIMIT + 1), headers=headers)
    assert response.status_code == 413
    assert response.json() == {"error": f"an avatar may be at most {guard.AVATAR_LIMIT} bytes"}
    assert guard.AVATAR_LIMIT == 2 * 1024 * 1024


def test_avatar_only_post_is_raw(local):
    """Only the POST is the exception: the DELETE that takes the picture away is JSON, as every other write."""
    response = local.delete(guard.AVATAR_PATH, headers={"Content-Type": "image/png"})
    assert response.status_code == 415
    assert "application/json" in response.json()["error"]


def test_only_portraitgens_editor_may_be_framed_and_only_by_delve(local):
    """DEL-238: the sheet's Edit portrait frames portraitgen's editor; every other page stays unframeable."""
    editor = local.get("/vendor/portraitgen/web/index.html").headers["content-security-policy"]
    assert editor == CSP.replace("frame-ancestors 'none'", "frame-ancestors 'self'")
    assert local.get("/vendor/portraitgen-web/").headers["content-security-policy"] == CSP
    assert local.get("/settings").headers["content-security-policy"] == CSP
