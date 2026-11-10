"""A test setting pack: the fake setting under the pack's id."""

from __future__ import annotations

from pathlib import Path

from delve.setting.fake import FakeSetting


class TestSetting(FakeSetting):
    __test__ = False
    id = "test-setting"
    title = "Test setting"


class Pack:
    def setting(self, root: Path, exclude: frozenset[str]) -> TestSetting:
        return TestSetting()


PACK = Pack()
