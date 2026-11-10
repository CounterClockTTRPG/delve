"""A test ruleset pack: the fake ruleset under the pack's id."""

from __future__ import annotations

from pathlib import Path

from delve.rules.fake import FakeRuleset


class TestRuleset(FakeRuleset):
    __test__ = False
    id = "test-ruleset"
    title = "Test ruleset"


class Pack:
    def ruleset(self, root: Path) -> TestRuleset:
        return TestRuleset()


PACK = Pack()
