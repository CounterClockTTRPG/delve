"""An imported `.dscn` whose manifest names a `cover` picture gets that picture's middle band as its banner (DEL-378),
as if the organiser had picked it; a bundle that brings Delve's own banner keeps that one, and one without either has
none."""

import hashlib
import io
from pathlib import Path

from PIL import Image

from delve.modules.dscn import Bundle
from delve.modules.importer import BANNER_MARK

ZIP = {"Content-Type": "application/zip"}
SAMPLE = Path(__file__).resolve().parents[2] / "samples" / "lady-of-the-weir"


def test_an_imported_cover_becomes_the_banner(local):
    module = local.post("/api/modules/import", content=Bundle.load(SAMPLE).to_zip(), headers=ZIP).json()
    assert module["banner"]["source"] == "picture:cover"
    banner = Image.open(io.BytesIO(local.get(f"/api/modules/{module['id']}/banner").content))
    assert abs(banner.width / banner.height - 21 / 9) < 0.02


def test_a_bundle_without_a_cover_gets_no_banner(local):
    bundle = Bundle.load(SAMPLE)
    bundle.manifest.pop("cover")
    module = local.post("/api/modules/import", content=bundle.to_zip(), headers=ZIP).json()
    assert module["banner"] is None


def test_a_bundle_with_delves_own_banner_keeps_it(local):
    bundle = Bundle.load(SAMPLE)
    portrait = next(a for a in bundle.manifest["assets"] if a["id"] == "wenna-portrait")
    bundle.manifest["assets"].append({**portrait, "id": "banner", BANNER_MARK: "uploaded"})
    module = local.post("/api/modules/import", content=bundle.to_zip(), headers=ZIP).json()
    assert module["banner"]["source"] == "uploaded"


def test_a_corrupt_cover_is_a_warning_not_a_failed_import(local):
    bundle = Bundle.load(SAMPLE)
    junk = b"\x89PNG\r\n\x1a\n" + b"not really a picture" * 20
    bundle.files["assets/img/broken.png"] = junk
    bundle.manifest["assets"].append({"id": "broken", "file": "assets/img/broken.png", "type": "image/png",
                                      "sha256": hashlib.sha256(junk).hexdigest(), "size": len(junk),
                                      "audience": "player"})  # fmt: skip
    bundle.manifest["cover"] = "asset:broken"
    response = local.post("/api/modules/import", content=bundle.to_zip(), headers=ZIP)
    assert response.status_code == 201
    assert response.json()["banner"] is None
    assert any(w.startswith("The cover can't be the banner") for w in response.json()["warnings"])
