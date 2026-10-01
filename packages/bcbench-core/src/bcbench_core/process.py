from collections.abc import Mapping
from collections.abc import Set as AbstractSet


def scrub_environment(
    environment: Mapping[str, str],
    *,
    excluded_prefixes: tuple[str, ...] = (),
    excluded_names: AbstractSet[str] = frozenset(),
    overrides: Mapping[str, str] | None = None,
) -> dict[str, str]:
    env = {key: value for key, value in environment.items() if not key.startswith(excluded_prefixes) and key not in excluded_names}
    if overrides:
        env.update(overrides)
    return env
