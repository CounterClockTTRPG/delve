import pytest

from delve.domain.world import PLAIN_CALENDAR
from delve.rules.ruleset import ReferenceHit
from delve.setting.fake import FakeSetting


def test_identity_and_kinds():
    setting = FakeSetting()
    assert setting.id == "fake-setting"
    assert setting.title
    assert setting.kinds() == ("place", "deity", "faction")


def test_setting_lookup():
    setting = FakeSetting()
    hits = setting.lookup("place", "hommlet")
    assert [hit.title for hit in hits] == ["Hommlet"]
    assert all(isinstance(hit, ReferenceHit) and hit.kind == "place" for hit in hits)
    assert setting.lookup("deity", "zzz") == []


def test_setting_lookup_respects_limit():
    deity = ReferenceHit("deity", "d", "Deity", "")
    setting = FakeSetting({"place": [], "deity": [deity] * 8, "faction": []})
    assert len(setting.lookup("deity", "de")) == 5
    assert len(setting.lookup("deity", "de", limit=2)) == 2


def test_setting_unknown_kind_lists_kinds():
    with pytest.raises(ValueError, match="place, deity, faction"):
        FakeSetting().lookup("spell", "sleep")


def test_the_fake_setting_has_the_whole_shape():
    fake = FakeSetting()
    assert fake.calendar() is PLAIN_CALENDAR
    assert fake.world_maps() == ()
    assert [hit.title for hit in fake.search("verbobonc")] == ["Verbobonc"]
    assert fake.page("Hommlet").text == "A quiet village in the Viscounty of Verbobonc."
    assert fake.page("Blackmoor") is None
    assert len(fake.lore_facts(1)) == 1
