"""Modules' domain: the homebrew tag (DEL-226)."""

from delve.domain.modules import homebrew


def test_homebrew_adds_the_tag_once():
    assert homebrew(None) == {"tags": ["homebrew"]}
    assert homebrew({"tags": ["caves"], "title": "X"}) == {"tags": ["caves", "homebrew"], "title": "X"}
    assert homebrew({"tags": ["Homebrew"]}) == {"tags": ["Homebrew"]}, "as written, whatever its case"
    metadata = {"tags": ["caves"]}
    homebrew(metadata)
    assert metadata == {"tags": ["caves"]}, "a copy"
