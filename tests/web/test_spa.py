from fastapi.testclient import TestClient

from delve.web.app import create_app
from tests.web.conftest import BASE_URL, INDEX_HTML


def test_spa_fallback_serves_index_for_client_route(local):
    for path in ("/", "/settings", "/modules", "/campaigns/some/deep/route"):
        response = local.get(path)
        assert response.status_code == 200, path
        assert response.headers["content-type"].startswith("text/html")
        assert response.text == INDEX_HTML


def test_static_file_served(local):
    response = local.get("/assets/app.js")
    assert response.status_code == 200
    assert response.text == "console.log('delve')"


def test_a_build_file_that_isnt_there_is_404(local):
    """A page open since before a deploy asks for the old build's files: a 404, never index.html in a script's place."""
    response = local.get("/assets/ImportWorldMap-Bh0zazTQ.js")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("text/plain")


def test_unknown_api_path_json_404(local):
    for method, path in (("GET", "/api/nope"), ("GET", "/api"), ("GET", "/api/assets/app.js")):
        response = local.request(method, path)
        assert response.status_code == 404, path
        assert response.json() == {"error": "not found"}
    response = local.post("/api/nope", json={})
    assert response.status_code == 404
    assert response.json() == {"error": "not found"}


def test_unknown_api_path_needs_no_token(lan):
    assert lan.get("/api/nope").json() == {"error": "not found"}


def test_wrong_method_on_known_route_405_json(local):
    response = local.post("/api/health", json={})
    assert response.status_code == 405
    assert "error" in response.json()


def test_path_outside_static_dir_not_served(local, static_dir):
    (static_dir.parent / "secret.txt").write_text("secret")
    for path in ("/../secret.txt", "/%2e%2e/secret.txt", "/assets/%2e%2e/%2e%2e/secret.txt"):
        assert "secret" not in local.get(path).text


def test_missing_build_message(config, storage, registries, tmp_path):
    app = create_app(config, storage, registries, static_dir=tmp_path / "no-build")
    with TestClient(app, base_url=BASE_URL, client=("127.0.0.1", 50000)) as client:
        response = client.get("/settings")
        assert response.status_code == 200
        assert "make build" in response.text
        assert client.get("/api/nope").json() == {"error": "not found"}


def test_a_build_file_is_cached_for_good_and_gzipped(local):
    """Build files carry their content's hash in the name (DEL-167): cached as immutable, gzipped when the browser
    takes it, and a 304 for the ETag it already has. index.html is never cached."""
    plain = local.get("/assets/app.js", headers={"Accept-Encoding": "identity"})
    assert plain.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert "content-encoding" not in plain.headers and plain.text == "console.log('delve')"
    packed = local.get("/assets/app.js", headers={"Accept-Encoding": "gzip, br"})
    assert packed.headers["content-encoding"] == "gzip" and packed.text == "console.log('delve')"
    assert packed.headers["content-type"].split(";")[0] in ("text/javascript", "application/javascript")
    again = local.get("/assets/app.js", headers={"If-None-Match": plain.headers["etag"]})
    assert again.status_code == 304 and again.content == b""
    assert local.get("/").headers["cache-control"] == "no-cache"
