from delve.maps.dsl import list_renderers
from tests.fixtures import SAMPLES
from tests.web.test_modules_api import BROKEN_MAP, GOOD_MAP

TWO_ROOMS = (
    'map "Two" {\n  grid { bounds 30 x 10 }\n}\n\n'
    'room "a" {\n  rect 1,1 4 x 4\n}\n\n'
    'room "b" {\n  rect 10,1 4 x 4\n}\n\n'
    'room "c" {\n  rect 20,1 4 x 4\n}\n\n'
    'corridor "hall" {\n  width 1\n  segment line from 5,3 to 10,3\n}\n\n'
    "door at 5,3 {\n  connects room.a, corridor.hall\n}\n"
)


def test_dsl_render(local):
    response = local.post("/api/dsl/render", json={"source": GOOD_MAP})
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"svg", "diagnostics"}
    assert "<svg" in body["svg"]
    renderer = list_renderers()[-1]
    assert local.post("/api/dsl/render", json={"source": GOOD_MAP, "renderer": renderer}).status_code == 200


def test_dsl_parse_error_400_never_500(local):
    for path in ("/api/dsl/render", "/api/dsl/parse", "/api/dsl/connectivity"):
        response = local.post(path, json={"source": BROKEN_MAP})
        assert response.status_code == 400, path
        assert set(response.json()) == {"error", "line", "column"}
        assert response.json()["line"] == 6
    garbage = local.post("/api/dsl/render", json={"source": "\x00{{{ ]]] map"})
    assert garbage.status_code == 400


def test_dsl_parse_returns_model(local):
    response = local.post("/api/dsl/parse", json={"source": GOOD_MAP})
    assert response.status_code == 200
    model = response.json()["map"]
    assert model["map"]["name"] == "Two rooms"
    assert "a" in model["rooms"]


def test_dsl_connectivity(local):
    response = local.post("/api/dsl/connectivity", json={"source": TWO_ROOMS})
    assert response.status_code == 200
    nodes = {node["id"]: node for node in response.json()["nodes"]}
    assert set(nodes["room.a"]) == {"id", "kind", "name", "connected", "doors", "connections"}
    assert nodes["room.a"]["connected"] is True
    assert nodes["room.a"]["connections"] == [
        {"to": "corridor.hall", "type": "wooden", "state": "closed", "direction": "both"}
    ]
    assert nodes["room.c"]["connected"] is False
    assert nodes["room.c"]["doors"] == 0
    assert nodes["room.c"]["kind"] == "room"


def test_dsl_unknown_module_404(local):
    response = local.post("/api/dsl/render", json={"source": GOOD_MAP, "module_id": "mod_000000000000"})
    assert response.status_code == 404
    assert "error" in response.json()


def test_dsl_renders_every_sample(local):
    for path in sorted(SAMPLES.glob("*.dmap")):
        response = local.post("/api/dsl/render", json={"source": path.read_text()})
        assert response.status_code == 200, path.name
