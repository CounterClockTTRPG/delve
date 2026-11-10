"""Parsed maps cached by their text and includes (plan 2a Task 14, DEL-166): each map text is parsed, and its graph
built, once, whatever module, revision or campaign it comes from; `with_tokens` and the map state reuse the graph, and
the editor's `derive`, the ref repair and the module list read the same cache."""

import pytest

from delve.domain.modules import ModuleMap
from delve.maps import sources
from delve.maps import state as map_state
from delve.maps.dsl import DmapError
from delve.maps.tokens import Token, with_tokens
from tests.fixtures import SAMPLES

CRYPT = (SAMPLES / "crypt.dmap").read_text()
MAPS = (ModuleMap("crypt", "map", CRYPT, is_default=True),)


@pytest.fixture
def counted(monkeypatch):
    """How often the parser and the graph builder run."""
    sources.clear_cache()
    calls = {"parse": 0, "graph": 0}
    parse, build = sources.parse, sources.build_graph

    def counting_parse(*args, **kwargs):
        calls["parse"] += 1
        return parse(*args, **kwargs)

    def counting_build(*args, **kwargs):
        calls["graph"] += 1
        return build(*args, **kwargs)

    monkeypatch.setattr(sources, "parse", counting_parse)
    monkeypatch.setattr(sources, "build_graph", counting_build)
    yield calls
    sources.clear_cache()


def test_a_revisions_map_is_parsed_once(counted):
    dmap, graph = sources.parsed_map("mod_1", 1, MAPS, "crypt")
    again, graph_again = sources.parsed_map("mod_1", 1, MAPS, "crypt")
    assert again is dmap and graph_again is graph
    assert counted == {"parse": 1, "graph": 1}


def test_the_same_text_is_parsed_once_wherever_it_comes_from(counted):
    """The cache keys on the text and its includes (DEL-166), not on the module and revision: another revision, another
    module, or a module's working maps with the same text read the same parsed map. Before, revisions were apart."""
    dmap, _ = sources.parsed_map("mod_1", 1, MAPS, "crypt")
    assert sources.parsed_map("mod_1", 2, MAPS, "crypt")[0] is dmap  # another revision
    assert sources.parsed_map("mod_2", 1, MAPS, "crypt")[0] is dmap  # another module
    assert sources.cached_map(MAPS, "crypt") is dmap
    assert sources.cached_source(CRYPT) is dmap
    assert counted == {"parse": 1, "graph": 1}


def test_an_edited_include_is_parsed_again(counted):
    """An include is part of the key: a library edited under the same map text parses the map again."""
    lib = sources.library_source("city.dmap")
    maps = (ModuleMap("crypt", "map", 'include "lib"\n' + CRYPT, is_default=True), ModuleMap("lib", "library", lib, is_default=False))
    first = sources.cached_map(maps, "crypt")
    edited = (maps[0], ModuleMap("lib", "library", lib + "\n# edited\n", is_default=False))
    assert sources.cached_map(edited, "crypt") is not first
    assert sources.cached_map(maps, "crypt") is first


def test_parse_source_still_parses_afresh(counted):
    """`parse_source` and `parse_map` are for callers that change what they get: never the shared map."""
    shared = sources.cached_source(CRYPT)
    assert sources.parse_source(CRYPT) is not shared
    assert sources.parse_map(MAPS, "crypt") is not shared


def test_the_graph_is_reused_by_tokens_and_the_map_state(counted):
    dmap, graph = sources.parsed_map("mod_1", 1, MAPS, "crypt")
    assert sources.graph_of(dmap) is graph
    with_tokens(dmap, [Token("mon_1", "Goblin 1", "room.entry_hall", "enemy")])
    state = map_state.move(map_state.MapState.empty(), dmap, ["chr_1"], "room.entry_hall")
    map_state.reveal(state, dmap, ["chr_1"], "room.throne_chamber")
    assert counted == {"parse": 1, "graph": 1}


def test_a_map_that_does_not_parse_is_not_cached(counted):
    broken = (ModuleMap("crypt", "map", "map broken {", is_default=True),)
    for _ in range(2):
        with pytest.raises(DmapError):
            sources.parsed_map("mod_1", 1, broken, "crypt")
    assert not sources._parsed
    with pytest.raises(KeyError):
        sources.parsed_map("mod_1", 1, MAPS, "cottage")


def test_the_cache_is_bounded(counted):
    texts = [CRYPT + f"\n# {n}\n" for n in range(sources.CACHE_SIZE + 5)]
    for text in texts:
        sources.cached_source(text)
    sources.cached_source(texts[0])  # the oldest was dropped
    assert counted["parse"] == sources.CACHE_SIZE + 6


def test_a_graph_goes_with_its_map(counted):
    """A cached map's graph lives in its entry, not in the cache of other maps' graphs, so maps that `derive` reads
    never push out the graphs play uses (DEL-166)."""
    dmap = sources.cached_source(CRYPT)
    graph = sources.graph_of(dmap)
    assert not sources._graphs
    copy = dmap.model_copy()
    assert sources.graph_of(copy) is not graph and len(sources._graphs) == 1


def test_an_edited_campaign_map_is_parsed_again(counted):
    """A campaign's own map (campaign maps, 2026-10-23) changes under the same module, revision and name: the cache
    keys on its source too, so an edit is never served stale."""
    first = sources.parsed_map("mod_1", 1, MAPS, "crypt")[0]
    edited = (ModuleMap("crypt", "map", CRYPT.replace("Entry Hall", "Front Hall", 1), is_default=True),)
    assert CRYPT != edited[0].source
    again = sources.parsed_map("mod_1", 1, edited, "crypt")[0]
    assert again is not first
    assert counted["parse"] == 2
