import os

# BC container connection details/credentials the harness uses to build the MCP config and to reach the
# container. They must NOT leak into a launched agent's own process environment: otherwise the agent can
# read the credentials and query BC's API directly from a shell, bypassing the MCP server the benchmark
# is meant to exercise. MCP servers still receive what they need through the MCP configuration (an
# embedded env block for altool, an auth header for the BC MCP server), so withholding these from the
# agent process closes the direct-API side-door without breaking MCP connectivity.
_WITHHELD_ENV_PREFIXES = ("BC_SERVER_", "BC_MCP_")
_WITHHELD_ENV_VARS = frozenset({"BC_CONTAINER_NAME"})


def agent_subprocess_env(overrides: dict[str, str] | None = None) -> dict[str, str]:
    """``os.environ`` for a launched agent, with the BC container connection vars removed."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(_WITHHELD_ENV_PREFIXES) and k not in _WITHHELD_ENV_VARS}
    if overrides:
        env.update(overrides)
    return env
