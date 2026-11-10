"""What each provider can do, and the registry the app picks providers from."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from typing import Generic, TypeVar

from delve.domain.settings import Effort, Job

T = TypeVar("T")


@dataclass(frozen=True)
class ModelInfo:
    """What Preferences show of a model: its label, the backend it runs on (`replicate`, `local`), its price in the
    provider's own words (None when it gives none), and whether it costs money, which the paid-images gate asks."""

    label: str
    backend: str
    price: str | None
    paid: bool


@dataclass(frozen=True)
class ProviderCapabilities:
    """A provider's id and title, the jobs it does, and the models and efforts Preferences may offer for it, with
    what is known of each model (`model_info`). A live provider's (`Registry.register_live`) are read anew each time,
    and say why it can't be used now (`problem`), such as assetgen being down. A `development` provider (a fake) is
    for developing Delve, not for play, which Preferences say."""

    id: str
    title: str
    jobs: frozenset[Job]
    models: tuple[str, ...] = ()
    efforts: tuple[Effort, ...] = ()
    default_model: str | None = None
    model_info: Mapping[str, ModelInfo] = field(default_factory=dict)
    problem: str | None = None
    live: bool = False
    development: bool = False


class Registry(Generic[T]):  # noqa: UP046 (the plan names this form)
    """The providers of one layer, by id, in the order they were registered.

    A provider is built by its factory on the first `get` and reused after that. Providers come and go at run time
    (a token saved or removed in Connections): registering a known id replaces it in its place, and `unregister`
    drops one. A live provider's capabilities are read from its `caps()` on every `capabilities` and `for_job`, so a
    model added to it later shows without a restart.
    """

    def __init__(self) -> None:
        self._caps: dict[str, ProviderCapabilities | Callable[[], ProviderCapabilities]] = {}
        self._factories: dict[str, Callable[[], T]] = {}
        self._built: dict[str, T] = {}

    def register(self, caps: ProviderCapabilities, factory: Callable[[], T]) -> T | None:
        """Register `caps.id`. A known id is replaced in its place, and what its old factory built is dropped and
        answered, for the caller to close; otherwise None."""
        return self._put(caps.id, caps, factory)

    def register_live(self, id: str, caps: Callable[[], ProviderCapabilities], factory: Callable[[], T]) -> T | None:
        """Register `id` with capabilities read from `caps()` on each read, marked `live`; as `register` otherwise."""
        return self._put(id, lambda: replace(caps(), id=id, live=True), factory)

    def _put(
        self, id: str, caps: ProviderCapabilities | Callable[[], ProviderCapabilities], factory: Callable[[], T]
    ) -> T | None:
        self._caps[id] = caps
        self._factories[id] = factory
        return self._built.pop(id, None)

    def unregister(self, id: str) -> T | None:
        """Drop the provider `id`, if registered; the provider it had built, for the caller to close, or None."""
        self._caps.pop(id, None)
        self._factories.pop(id, None)
        return self._built.pop(id, None)

    def capabilities(self) -> list[ProviderCapabilities]:
        return [caps if isinstance(caps, ProviderCapabilities) else caps() for caps in self._caps.values()]

    def get(self, id: str) -> T:
        if id not in self._factories:
            known = ", ".join(self._caps) or "none"
            raise KeyError(f"unknown provider '{id}'; known: {known}")
        if id not in self._built:
            self._built[id] = self._factories[id]()
        return self._built[id]

    def built(self) -> list[T]:
        """The providers built so far."""
        return list(self._built.values())
