from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass
from types import MappingProxyType


@dataclass(frozen=True, init=False)
class CategoryRegistry[K: str, T](Mapping[K, T]):
    """Explicit, lazy category providers; importing a registry never loads its categories."""

    _providers: Mapping[K, Callable[[], T]]

    def __init__(self, providers: Iterable[tuple[K, Callable[[], T]]]) -> None:
        registered: dict[K, Callable[[], T]] = {}
        for name, provider in providers:
            if not name or name in registered:
                raise ValueError(f"Empty or duplicate category name: {name!r}")
            registered[name] = provider
        object.__setattr__(self, "_providers", MappingProxyType(registered))

    def __getitem__(self, name: K) -> T:
        return self._providers[name]()

    def __iter__(self) -> Iterator[K]:
        return iter(self._providers)

    def __len__(self) -> int:
        return len(self._providers)

    def __contains__(self, name: object) -> bool:
        return name in self._providers
