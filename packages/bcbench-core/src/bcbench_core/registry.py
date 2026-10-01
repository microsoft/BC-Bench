from collections.abc import Callable, Iterable, Iterator, Mapping
from types import MappingProxyType


class CategoryRegistry[T](Mapping[str, T]):
    """Explicit, lazy category providers; importing a registry never loads its categories."""

    def __init__(self, providers: Iterable[tuple[str, Callable[[], T]]]) -> None:
        registered: dict[str, Callable[[], T]] = {}
        for name, provider in providers:
            if not name or name in registered:
                raise ValueError(f"Empty or duplicate category name: {name!r}")
            registered[name] = provider
        self._providers = MappingProxyType(registered)

    def __getitem__(self, name: str) -> T:
        return self._providers[name]()

    def __iter__(self) -> Iterator[str]:
        return iter(self._providers)

    def __len__(self) -> int:
        return len(self._providers)

    def __contains__(self, name: object) -> bool:
        return name in self._providers
