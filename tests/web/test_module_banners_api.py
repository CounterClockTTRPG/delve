"""A module's banner (DEL-123) through the API: uploaded or picked from the module's pictures, cut to 21:9 at the
crop position, served to organisers, and removed. The guard lets only the picture types through."""

import io

from PIL import Image

from tests.web.test_assets_api import upload as upload_attachment
from tests.web.test_modules_api import create


def picture(width: int, height: int, fmt: str = "PNG") -> bytes:
    """A picture whose top half is red and bottom half blue, to see which band was kept."""
    image = Image.new("RGB", (width, height), (0, 0, 255))
    image.paste((255, 0, 0), (0, 0, width, height // 2))
    out = io.BytesIO()
    image.save(out, fmt)
    return out.getvalue()


def banner_of(local, mid) -> Image.Image:
    response = local.get(f"/api/modules/{mid}/banner")
    assert response.status_code == 200 and response.headers["content-type"] == "image/webp"
    assert response.headers["x-content-type-options"] == "nosniff"
    return Image.open(io.BytesIO(response.content))


def test_an_uploaded_banner_is_its_21_9_band(local):
    mid = create(local)["id"]
    assert local.get(f"/api/modules/{mid}/banner").status_code == 404
    sent = local.post(f"/api/modules/{mid}/banner/upload", params={"position": 0}, content=picture(800, 1000),
                      headers={"Content-Type": "image/png"})  # fmt: skip
    assert sent.status_code == 200, sent.text
    assert sent.json()["banner"] == {"version": sent.json()["banner"]["version"], "source": "uploaded", "status": None,
                                     "error": None}  # fmt: skip
    top = banner_of(local, mid)
    assert top.size == (800, round(800 * 9 / 21)) and top.convert("RGB").getpixel((400, 10))[0] > 200, "the top band: red"
    local.post(f"/api/modules/{mid}/banner/upload", params={"position": 1}, content=picture(800, 1000),
               headers={"Content-Type": "image/png"})  # fmt: skip
    assert banner_of(local, mid).convert("RGB").getpixel((400, 300))[2] > 200, "the bottom band: blue"
    wide = local.post(f"/api/modules/{mid}/banner/upload", content=picture(4000, 600, "JPEG"),
                      headers={"Content-Type": "image/jpeg"})  # fmt: skip
    # Reduced to 2400 px a side first (2400 x 360), then the 21:9 band across.
    assert wide.status_code == 200 and banner_of(local, mid).size == (840, 360), "a wider picture: a band across"


def test_a_banner_upload_must_be_a_picture_of_its_type(local):
    mid = create(local)["id"]
    url = f"/api/modules/{mid}/banner/upload"
    assert local.post(url, content=b"GIF89a", headers={"Content-Type": "image/gif"}).status_code == 415
    assert local.post(url, content=b"not a png", headers={"Content-Type": "image/png"}).status_code == 400
    assert local.post(url, params={"position": 2}, content=picture(10, 10), headers={"Content-Type": "image/png"}).status_code == 422


def test_one_of_the_modules_pictures_becomes_the_banner(local):
    mid = create(local)["id"]
    attached = upload_attachment(local, mid, "Cover.png", picture(600, 900), "image/png").json()
    used = local.put(f"/api/modules/{mid}/banner", json={"picture": attached["id"], "position": 0.5})
    assert used.status_code == 200 and used.json()["banner"]["source"] == f"picture:{attached['id']}"
    assert banner_of(local, mid).size == (600, round(600 * 9 / 21))
    assert local.put(f"/api/modules/{mid}/banner", json={"picture": "nothing"}).status_code == 404
    removed = local.request("DELETE", f"/api/modules/{mid}/banner", json={})
    assert removed.status_code == 200 and removed.json()["banner"] is None
    assert local.get(f"/api/modules/{mid}/banner").status_code == 404


def test_players_cant_see_or_set_a_module_banner(local, player):
    mid = create(local)["id"]
    assert player.get(f"/api/modules/{mid}/banner").status_code == 403
    assert player.post(f"/api/modules/{mid}/banner/upload", content=picture(10, 10),
                       headers={"Content-Type": "image/png"}).status_code == 403  # fmt: skip


def test_a_banner_is_painted_with_the_free_fake_and_lands(local):
    import time

    mid = create(local)["id"]
    assert local.get(f"/api/modules/{mid}/banner/paint").json() == {"paid": False, "allowed": True}
    started = local.post(f"/api/modules/{mid}/banner/paint", json={"hint": "at dusk"})
    assert started.status_code == 202 and started.json()["banner"]["status"] == "painting"
    for _ in range(100):
        banner = local.get(f"/api/modules/{mid}").json()["banner"]
        if banner["status"] is None:
            break
        time.sleep(0.05)
    assert banner["source"] == "painted" and banner["version"], banner
    assert local.get(f"/api/modules/{mid}/banner").status_code == 200


def test_the_banner_travels_in_the_dscn_and_comes_back_as_the_banner(local):
    import zipfile

    from tests.web.test_campaigns_api import crypt_module

    mid = crypt_module(local, title="The Crypt")["id"]
    local.post(f"/api/modules/{mid}/banner/upload", content=picture(840, 600), headers={"Content-Type": "image/png"})
    exported = local.get(f"/api/modules/{mid}/export.dscn")
    assert exported.status_code == 200, exported.text
    with zipfile.ZipFile(io.BytesIO(exported.content)) as bundle:
        import json

        manifest = json.loads(bundle.read("scenario.json"))
    [asset] = [a for a in manifest.get("assets", []) if a.get("x-delve-banner")]
    assert asset["x-delve-banner"] == "uploaded" and asset["audience"] == "player" and asset["type"] == "image/webp"

    imported = local.post("/api/modules/import", content=exported.content, headers={"Content-Type": "application/zip"})
    assert imported.status_code == 201, imported.text
    again = imported.json()
    assert again["banner"]["source"] == "uploaded" and again["banner"]["version"]
    assert local.get(f"/api/modules/{again['id']}/banner").content == local.get(f"/api/modules/{mid}/banner").content
    attachments = local.get(f"/api/modules/{again['id']}/source").json()["attachments"]
    assert all(a["id"] != asset["id"] for a in attachments), "the banner, not an attachment"


def test_a_card_asks_for_a_small_copy_of_the_banner(app, local):
    """DEL-234: `?size=card` is an 800-wide WebP of the banner, made once and kept under the picture's blob; the
    picture itself stays as it was. A banner no wider than a card is served as it is. Both answer 304 to their ETag."""
    mid = create(local)["id"]
    assert local.get(f"/api/modules/{mid}/banner", params={"size": "card"}).status_code == 404
    local.post(f"/api/modules/{mid}/banner/upload", content=picture(2400, 2000),
               headers={"Content-Type": "image/png"})  # fmt: skip
    full = local.get(f"/api/modules/{mid}/banner")
    card = local.get(f"/api/modules/{mid}/banner", params={"size": "card"})
    assert card.status_code == 200 and card.headers["content-type"] == "image/webp"
    assert Image.open(io.BytesIO(card.content)).size == (800, round(800 * 9 / 21))
    assert len(card.content) < len(full.content) and card.headers["etag"] != full.headers["etag"]
    kept = list((app.state.config.data_dir / "thumbs").glob("*-800.webp"))
    assert len(kept) == 1 and kept[0].read_bytes() == card.content
    assert local.get(f"/api/modules/{mid}/banner", params={"size": "card"}).content == card.content

    again = local.get(f"/api/modules/{mid}/banner", params={"size": "card"}, headers={"If-None-Match": card.headers["etag"]})
    assert again.status_code == 304 and again.content == b""
    assert local.get(f"/api/modules/{mid}/banner", headers={"If-None-Match": full.headers["etag"]}).status_code == 304
    assert local.get(f"/api/modules/{mid}/banner", params={"size": "huge"}).status_code == 422

    local.post(f"/api/modules/{mid}/banner/upload", content=picture(800, 1000), headers={"Content-Type": "image/png"})
    narrow = local.get(f"/api/modules/{mid}/banner", params={"size": "card"})
    assert narrow.content == local.get(f"/api/modules/{mid}/banner").content, "no wider than a card: the picture"
