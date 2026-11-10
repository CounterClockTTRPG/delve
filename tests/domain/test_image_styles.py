"""The install's image style (DEL-202): the campaign's tone, a preset, or the owner's own words."""

from delve.domain.image_styles import (
    BROM,
    CUSTOM_LIMIT,
    PRESET_IDS,
    PRESETS,
    ImageStyle,
    parse,
    stored_style_text,
    style_text,
)


def test_the_presets():
    assert [p.id for p in PRESETS] == [
        "elmore", "brom", "diterlizzi", "frazetta", "vallejo", "hildebrandt", "froud", "woodcut",
    ]  # fmt: skip
    assert {p.id for p in PRESETS if p.sample} == PRESET_IDS - {"elmore", "brom", "diterlizzi"}, "ttrpg3's eight"
    assert all(p.prompt.endswith(".") and p.name for p in PRESETS)


def test_a_stored_style_is_read_or_falls_back_to_the_tone():
    assert parse(None) == (ImageStyle(), None)
    assert parse({"preset": "woodcut"}) == (ImageStyle("woodcut"), None)
    assert parse({"preset": "custom", "custom": "  ink   and\nwash "}) == (ImageStyle("custom", "ink and wash"), None)
    assert parse({"preset": "custom", "custom": "x" * 2000})[0].custom == "x" * CUSTOM_LIMIT
    assert parse({"preset": "custom", "custom": " "}) == (ImageStyle(), "a custom style needs words")
    assert parse({"preset": "pixel art"}) == (ImageStyle(), "'pixel art' is not a preset")
    assert parse(["woodcut"]) == (ImageStyle(), "not a mapping")


def test_a_style_s_words():
    assert style_text(ImageStyle()) == "", "the tone's: the provider picks the painter"
    assert style_text(ImageStyle("brom")) == BROM
    assert style_text(ImageStyle("custom", "ink and wash")) == "ink and wash"
    assert style_text(ImageStyle("woodcut", "kept for later")).startswith("High-contrast black-ink woodcut")
    assert stored_style_text({"image_style": {"preset": "froud"}}).startswith("Delicate watercolour fantasy")
    assert stored_style_text({}) == stored_style_text(None) == stored_style_text({"image_style": 3}) == ""
