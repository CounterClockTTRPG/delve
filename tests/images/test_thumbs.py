"""The banners' card copies (DEL-234): made once, kept under the picture's blob, and none for what can't be read."""

import io

from PIL import Image

from delve.images.thumbs import CARD_WIDTH, card_thumbnail

BLOB = "a" * 64


def png(width: int, height: int) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (width, height), (10, 120, 90)).save(out, "PNG")
    return out.getvalue()


def test_a_wide_picture_gets_a_card_copy_kept_for_next_time(tmp_path):
    made = card_thumbnail(tmp_path, BLOB, png(2400, 1028))
    assert made is not None and Image.open(io.BytesIO(made)).size == (CARD_WIDTH, round(1028 * CARD_WIDTH / 2400))
    assert card_thumbnail(tmp_path, BLOB, b"not read again") == made, "the kept copy, not the bytes given"


def test_no_copy_for_a_small_picture_bytes_that_aren_t_one_or_a_name_that_isn_t_a_blob(tmp_path):
    assert card_thumbnail(tmp_path, BLOB, png(800, 300)) is None
    assert card_thumbnail(tmp_path, BLOB, b"\x89PNG not really") is None
    assert card_thumbnail(tmp_path, "../../etc/passwd", png(2400, 1000)) is None
    assert not (tmp_path / "thumbs").exists() or not any((tmp_path / "thumbs").iterdir())
