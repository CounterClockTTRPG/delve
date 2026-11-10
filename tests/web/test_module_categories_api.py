"""Module categories (DEL-114) through the API: organisers keep the list; a module has one or none, and says so in
the module list and its own answer."""


def test_categories_are_made_renamed_moved_and_deleted(local):
    made = [local.post("/api/module-categories", json={"name": n}).json() for n in ("Megadungeons", "One-shots", " Arcs ")]
    assert [c["name"] for c in made] == ["Megadungeons", "One-shots", "Arcs"], "trimmed"
    assert local.post("/api/module-categories", json={"name": "one-shots"}).status_code == 409
    assert local.post("/api/module-categories", json={"name": " "}).status_code == 422
    assert local.post("/api/module-categories", json={"name": "x" * 61}).status_code == 422
    moved = local.put(f"/api/module-categories/{made[2]['id']}", json={"position": 0}).json()
    assert [c["name"] for c in moved] == ["Arcs", "Megadungeons", "One-shots"]
    renamed = local.put(f"/api/module-categories/{made[1]['id']}", json={"name": "One shots"}).json()
    assert [c["name"] for c in renamed] == ["Arcs", "Megadungeons", "One shots"]
    assert local.put("/api/module-categories/cat_none", json={"name": "Z"}).status_code == 404
    assert local.request("DELETE", f"/api/module-categories/{made[0]['id']}", json={}).status_code == 204
    assert [c["name"] for c in local.get("/api/module-categories").json()] == ["Arcs", "One shots"]
    assert local.request("DELETE", f"/api/module-categories/{made[0]['id']}", json={}).status_code == 404


def test_a_module_has_one_category_or_none(local):
    module = local.post("/api/modules", json={"title": "Crypt"}).json()
    assert module["category"] is None and module["banner"] is None
    mega = local.post("/api/module-categories", json={"name": "Megadungeons"}).json()
    put = local.patch(f"/api/modules/{module['id']}", json={"category_id": mega["id"]}).json()
    assert put["category"] == {"id": mega["id"], "name": "Megadungeons"}
    assert put["updated_at"] == module["updated_at"], "a category is no edit"
    listed = next(m for m in local.get("/api/modules").json() if m["id"] == module["id"])
    assert listed["category"] == {"id": mega["id"], "name": "Megadungeons"}
    assert local.patch(f"/api/modules/{module['id']}", json={"title": "Crypt II"}).json()["category"]["id"] == mega["id"], (
        "left out, unchanged"
    )
    assert local.patch(f"/api/modules/{module['id']}", json={"category_id": "cat_none"}).status_code == 422
    local.request("DELETE", f"/api/module-categories/{mega['id']}", json={})
    assert local.get(f"/api/modules/{module['id']}").json()["category"] is None, "its category went: none"


def test_players_cant_touch_categories(player):
    assert player.get("/api/module-categories").status_code == 403
    assert player.post("/api/module-categories", json={"name": "Mine"}).status_code == 403
