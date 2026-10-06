"""Explicit process environments for launched coding agents."""

from collections.abc import Collection, Mapping


def agent_subprocess_env(
    parent_env: Mapping[str, str],
    overrides: Mapping[str, str] | None = None,
    exclude_vars: Collection[str] = (),
    exclude_prefixes: tuple[str, ...] = (),
) -> dict[str, str]:
    env = {key: value for key, value in parent_env.items() if key not in exclude_vars and not key.startswith(exclude_prefixes)}
    if overrides:
        env.update(overrides)
    return env
