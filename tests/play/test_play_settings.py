"""A campaign's play settings (portraits plan Task 2): the portrait style joins them, `illustrated` until the organiser
chooses another. The custom tone (DEL-204) is the organiser's own text for the tone `custom`."""

import pytest

from delve.play.context import PlayError
from delve.play.portraits import PORTRAIT_STYLES
from delve.play.table import play_settings, set_play_settings


def test_portrait_style_defaults_to_as_in_preferences(storage, campaign):
    """DEL-252: null, the styles Preferences pick for PCs and NPCs (`images.portrait_style`), illustrated by default."""
    assert play_settings(storage, campaign.id)["portrait_style"] is None
    # A campaign stored before styles has none stored, and keeps the look it had.
    assert "portrait_style" not in (storage.play_settings.get(campaign.id) or {})


def test_portrait_style_is_stored(storage, campaign):
    assert set_play_settings(storage, campaign.id, {"portrait_style": "inkwash"})["portrait_style"] == "inkwash"
    assert play_settings(storage, campaign.id)["portrait_style"] == "inkwash"
    assert play_settings(storage, campaign.id)["tone"] == "classic"


def test_portrait_style_rejects_unknown(storage, campaign):
    with pytest.raises(PlayError) as refused:
        set_play_settings(storage, campaign.id, {"portrait_style": "cubist"})
    assert "cubist" in str(refused.value)
    assert all(style in refused.value.hint for style in PORTRAIT_STYLES)
    assert play_settings(storage, campaign.id)["portrait_style"] is None
    set_play_settings(storage, campaign.id, {"portrait_style": "anime"})
    assert set_play_settings(storage, campaign.id, {"portrait_style": None})["portrait_style"] is None, (
        "null is as in Preferences (DEL-252)"
    )


def test_custom_tone_is_stored_stripped(storage, campaign):
    assert play_settings(storage, campaign.id)["custom_tone"] == "", "none until an organiser writes one"
    stored = set_play_settings(storage, campaign.id, {"tone": "custom", "custom_tone": "  Like a radio play.  "})
    assert (stored["tone"], stored["custom_tone"]) == ("custom", "Like a radio play.")
    assert play_settings(storage, campaign.id)["custom_tone"] == "Like a radio play."
    assert set_play_settings(storage, campaign.id, {"tone": "horror"})["custom_tone"] == "Like a radio play.", "kept"
    empty = set_play_settings(storage, campaign.id, {"tone": "custom", "custom_tone": "   "})
    assert (empty["tone"], empty["custom_tone"]) == ("custom", ""), "custom without a text is as classic"
    assert set_play_settings(storage, campaign.id, {"custom_tone": " " + "x" * 2000 + " "})["custom_tone"] == "x" * 2000


def test_custom_tone_refuses_too_long_or_not_text(storage, campaign):
    with pytest.raises(PlayError) as refused:
        set_play_settings(storage, campaign.id, {"custom_tone": "x" * 2001})
    assert refused.value.message == "A custom tone is at most 2000 characters."
    with pytest.raises(PlayError):
        set_play_settings(storage, campaign.id, {"custom_tone": 7})
    assert play_settings(storage, campaign.id)["custom_tone"] == ""
