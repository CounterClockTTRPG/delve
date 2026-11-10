"""The storage Protocols against the SQLite storage that implements them (DEL-177): every method a Protocol declares
is there, with the same parameters, in the same order, of the same kinds and with the same defaults. `make ci` runs
no type checker, so this is what keeps a caller written against `interfaces.py` working against the real thing:
a keyword argument named in the Protocol and not in the repository, or a default that differs, fails here first.

Annotations aren't compared: a generic base repository spells them its own way (`R | None` for `Faction | None`), and
neither are positional-only parameters' names."""

import inspect

import pytest

from delve.config import Config
from delve.storage import interfaces, open_storage

PROTOCOLS = {
    name: cls
    for name, cls in vars(interfaces).items()
    # `typing.is_protocol` is 3.13's; it reads this flag.
    if inspect.isclass(cls) and cls.__module__ == interfaces.__name__ and getattr(cls, "_is_protocol", False)
}


@pytest.fixture(scope="module")
def storage(tmp_path_factory):
    opened = open_storage(Config(data_dir=tmp_path_factory.mktemp("parity") / "data"))
    yield opened
    opened.close()


def implementations(storage) -> dict[str, object]:
    """Each Protocol's implementation: the storage for `Storage`, and each of its repositories for the Protocol its
    attribute is annotated with."""
    found: dict[str, object] = {"Storage": storage}
    for attribute, annotation in interfaces.Storage.__annotations__.items():
        found[str(annotation)] = getattr(storage, attribute)
    return found


def declared_methods(protocol: type) -> dict[str, object]:
    """The methods `protocol` itself declares (not `object`'s or `Protocol`'s), private ones left out."""
    return {
        name: member
        for name, member in vars(protocol).items()
        if inspect.isfunction(member) and not name.startswith("_")
    }


def shape(function: object) -> list[tuple[str, inspect._ParameterKind, object]]:
    """A signature's parameters after `self`: name, kind and default. A positional-only parameter's name is no
    caller's business, so a generic base repository may call it `record` where the Protocol says `quest`."""
    parameters = list(inspect.signature(function).parameters.values())[1:]
    return [("" if p.kind is p.POSITIONAL_ONLY else p.name, p.kind, p.default) for p in parameters]


def test_every_protocol_has_an_implementation(storage):
    assert set(implementations(storage)) == set(PROTOCOLS), "a Protocol no Storage attribute is annotated with"


@pytest.mark.parametrize("name", sorted(PROTOCOLS))
def test_the_implementation_matches_its_protocol(storage, name):
    implementation = type(implementations(storage)[name])
    drifted = []
    for method, declared in declared_methods(PROTOCOLS[name]).items():
        actual = getattr(implementation, method, None)
        if not callable(actual):
            drifted.append(f"{method}: missing from {implementation.__name__}")
        elif shape(actual) != shape(declared):
            drifted.append(f"{method}: {inspect.signature(declared)} declared, {inspect.signature(actual)} implemented")
    assert not drifted, f"{implementation.__name__} against {name}:\n" + "\n".join(drifted)
