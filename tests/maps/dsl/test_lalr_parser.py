"""The parser runs LALR for speed; this pins that it reads the same trees the
grammar's original Earley parser did. A grammar edit that stays LALR-clean
but changes how something parses under LALR only would fail here."""

from pathlib import Path

import pytest
from lark import Lark

from delve.maps.dsl.parser import _GRAMMAR_PATH, _LIBRARY_DIR, _get_parser
from tests.fixtures import SAMPLES

_SOURCES = sorted(
    [*SAMPLES.glob("**/*.dmap"), *_LIBRARY_DIR.glob("*.dmap")]
)


@pytest.fixture(scope="module")
def earley() -> Lark:
    return Lark.open(
        str(_GRAMMAR_PATH),
        parser="earley",
        lexer="dynamic_complete",
        propagate_positions=True,
        maybe_placeholders=False,
    )


def test_parser_is_lalr() -> None:
    assert _get_parser().options.parser == "lalr"


def test_corpus_is_not_empty() -> None:
    assert len(_SOURCES) > 10


@pytest.mark.parametrize("path", _SOURCES, ids=lambda p: p.name)
def test_lalr_matches_earley(path: Path, earley: Lark) -> None:
    text = path.read_text(encoding="utf-8")
    assert _get_parser().parse(text) == earley.parse(text)
