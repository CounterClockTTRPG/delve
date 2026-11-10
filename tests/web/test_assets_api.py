"""Attachments (plan 3 Task 4): upload, describe, delete and serve a module's files, and the hostile uploads refused
(Review Focus 4)."""

import pytest

from delve.modules.dscn import sha256
from delve.web.guard import UPLOAD_LIMIT
from tests.web.test_module_source_api import delete, imported
from tests.web.test_modules_api import CRYPT, blob_files, create
from tests.web.test_preferences_api import published

PNG = (CRYPT / "assets" / "img" / "ritualist-token.png").read_bytes()
JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00" + b"\x00" * 32
SVG = b'<svg xmlns="http://www.w3.org/2000/svg" width="4" height="4"><rect width="4" height="4"/></svg>'
PDF = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj << >> endobj\ntrailer << >>\n%%EOF\n"


def upload(local, mid, name, data, media_type):
    return local.post(f"/api/modules/{mid}/assets", params={"name": name}, content=data, headers={"Content-Type": media_type})


def attachments(local, mid) -> list[dict]:
    return local.get(f"/api/modules/{mid}/source").json()["attachments"]


def test_upload_an_attachment(local, storage):
    mid = create(local)["id"]
    response = upload(local, mid, "Map of the Crypt.png", PNG, "image/png")
    assert response.status_code == 201
    attachment = response.json()
    assert attachment == {
        "id": "map-of-the-crypt",
        "type": "image/png",
        "sha256": sha256(PNG),
        "size": len(PNG),
        "description": "",
        "audience": "gm",
        "role": "attachment",
        "cut": None,
    }
    assert attachments(local, mid) == [attachment]
    assert storage.blobs.get(sha256(PNG)) == PNG
    assert ("attachment", sha256(PNG)) in storage.blobs.links(mid)


@pytest.mark.parametrize(
    ("name", "data", "media_type"),
    [("photo.jpg", JPEG, "image/jpeg"), ("plan.svg", SVG, "image/svg+xml"), ("rules.pdf", PDF, "application/pdf")],
)
def test_every_allowed_type_uploads(local, name, data, media_type):
    mid = create(local)["id"]
    response = upload(local, mid, name, data, media_type)
    assert response.status_code == 201 and response.json()["type"] == media_type


def test_an_id_is_made_unique(local):
    mid = create(local)["id"]
    ids = [upload(local, mid, "Door.png", PNG, "image/png").json()["id"] for _ in range(3)]
    assert ids == ["door", "door-2", "door-3"]
    assert upload(local, mid, "noextension", PNG, "image/png").json()["id"] == "noextension"
    assert upload(local, mid, "!!.png", PNG, "image/png").json()["id"] == "x"


def test_upload_needs_a_name_and_a_module(local):
    mid = create(local)["id"]
    no_name = local.post(f"/api/modules/{mid}/assets", content=PNG, headers={"Content-Type": "image/png"})
    assert no_name.status_code == 422 and "error" in no_name.json()
    assert upload(local, "mod_000000000000", "a.png", PNG, "image/png").status_code == 404


def test_hostile_uploads_are_refused(local, config):
    mid = create(local)["id"]
    before = blob_files(config)
    hostile = [
        ("evil.svg", b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>', "image/svg+xml", 400),
        ("handler.svg", b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"/>', "image/svg+xml", 400),
        ("liar.jpg", PNG, "image/jpeg", 400),
        ("notes.txt", b"just text", "text/plain", 415),
        ("page.html", b"<html></html>", "text/html", 415),
        ("form.png", PNG, "application/x-www-form-urlencoded", 415),
        ("big.png", PNG + b"\0" * (UPLOAD_LIMIT + 1024 * 1024 - len(PNG)), "image/png", 413),
    ]
    for name, data, media_type, status in hostile:
        response = upload(local, mid, name, data, media_type)
        assert response.status_code == status, name
        assert "error" in response.json(), name
        assert attachments(local, mid) == [], name
    assert local.post(f"/api/modules/{mid}/assets", params={"name": "a.png"}, content=PNG).status_code == 415
    assert blob_files(config) == before


def test_too_large_without_content_length_413(local, config, monkeypatch):
    monkeypatch.setattr("delve.web.routes.assets.UPLOAD_LIMIT", 1000)
    mid = create(local)["id"]
    before = blob_files(config)

    def chunks():
        yield PNG
        for _ in range(10):
            yield b"\0" * 200

    response = local.post(
        f"/api/modules/{mid}/assets", params={"name": "a.png"}, content=chunks(), headers={"Content-Type": "image/png"}
    )
    assert response.status_code == 413
    assert attachments(local, mid) == [] and blob_files(config) == before


def test_a_cross_site_upload_is_refused(local):
    mid = create(local)["id"]
    response = local.post(
        f"/api/modules/{mid}/assets",
        params={"name": "a.png"},
        content=PNG,
        headers={"Content-Type": "image/png", "Origin": "http://evil.example"},
    )
    assert response.status_code == 403 and attachments(local, mid) == []


def test_describe_an_attachment(local):
    mid = create(local)["id"]
    upload(local, mid, "door.png", PNG, "image/png")
    response = local.patch(
        f"/api/modules/{mid}/assets/door", json={"description": "The door. Show it at the gate.", "audience": "player"}
    )
    assert response.status_code == 200
    assert response.json()["description"] == "The door. Show it at the gate."
    assert response.json()["audience"] == "player"
    only_audience = local.patch(f"/api/modules/{mid}/assets/door", json={"audience": "gm"}).json()
    assert only_audience["description"] == "The door. Show it at the gate." and only_audience["audience"] == "gm"
    assert attachments(local, mid) == [only_audience]
    assert local.patch(f"/api/modules/{mid}/assets/door", json={"audience": "dm"}).status_code == 422
    assert local.patch(f"/api/modules/{mid}/assets/nothing", json={"description": "x"}).status_code == 404


def test_delete_an_attachment_leaves_a_warning(local, storage):
    mid = imported(local)
    assert delete(local, f"/api/modules/{mid}/assets/ritualist-token").status_code == 204
    source = local.get(f"/api/modules/{mid}/source").json()
    assert source["attachments"] == []
    assert "asset:ritualist-token" in {w["ref"] for w in source["warnings"] if w["code"] == "missing-attachment"}
    # The bytes stay in the blob store: a pinned revision may still show them.
    assert storage.blobs.get(sha256(PNG)) == PNG
    assert delete(local, f"/api/modules/{mid}/assets/ritualist-token").status_code == 404
    assert local.get(f"/api/modules/{mid}/assets/ritualist-token").status_code == 404


def test_served_bytes_have_their_type(local):
    mid = imported(local)
    response = local.get(f"/api/modules/{mid}/assets/ritualist-token")
    assert response.status_code == 200
    assert response.content == PNG
    assert response.headers["content-type"] == "image/png"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "sandbox" not in response.headers.get_list("content-security-policy")
    assert local.get(f"/api/modules/{mid}/assets/nothing").status_code == 404


def test_served_svg_is_sandboxed(local):
    mid = create(local)["id"]
    upload(local, mid, "plan.svg", SVG, "image/svg+xml")
    response = local.get(f"/api/modules/{mid}/assets/plan")
    assert response.status_code == 200 and response.content == SVG
    assert response.headers["content-type"] == "image/svg+xml"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "sandbox" in response.headers.get_list("content-security-policy")


def test_attachments_are_for_organisers(lan):
    assert lan.get("/api/modules/mod_000000000000/assets/a").status_code in (401, 403)


def test_attachment_changes_publish_modules(local, app):
    mid = create(local)["id"]
    upload(local, mid, "door.png", PNG, "image/png")
    local.patch(f"/api/modules/{mid}/assets/door", json={"description": "A door."})
    delete(local, f"/api/modules/{mid}/assets/door")
    events = [(event.type, event.data) for event in published(app)]
    assert events[-3:] == [("modules", {"id": mid})] * 3


def test_export_refuses_a_module_with_missing_refs(local):
    mid = imported(local)
    assert local.get(f"/api/modules/{mid}/export.dscn").status_code == 200
    delete(local, f"/api/modules/{mid}/assets/ritualist-token")
    response = local.get(f"/api/modules/{mid}/export.dscn")
    assert response.status_code == 409
    body = response.json()
    assert body["error"] == "the module refers to missing attachments or entities"
    assert {w["code"] for w in body["warnings"]} == {"missing-attachment"}
    assert "asset:ritualist-token" in {w["ref"] for w in body["warnings"]}
