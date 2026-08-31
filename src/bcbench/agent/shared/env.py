import os

# BC container connection details/credentials the harness uses to build the MCP config and to reach the
# container. They must NOT leak into a launched agent's own process environment: otherwise the agent can
# read the credentials and query BC's API directly from a shell, bypassing the MCP server the benchmark
# is meant to exercise. BC_CONTAINER_NAME is withheld for the same reason (it lets the agent target the
# container directly, e.g. `docker exec ... sqlcmd`). MCP servers still receive what they need through
# other channels (an embedded env block for altool; the BC MCP gateway injects the auth header upstream,
# so the agent's MCP config stays credential-free), so withholding these from the agent process closes
# the direct-API/direct-DB side-doors without breaking MCP connectivity.
_WITHHELD_ENV_PREFIXES = ("BC_SERVER_", "BC_MCP_")
_WITHHELD_ENV_VARS = frozenset({"BC_CONTAINER_NAME"})


def agent_subprocess_env(overrides: dict[str, str] | None = None, *, pass_bc_credentials: bool = False) -> dict[str, str]:
    env = dict(os.environ)
    if not pass_bc_credentials:
        env = {k: v for k, v in env.items() if not k.startswith(_WITHHELD_ENV_PREFIXES) and k not in _WITHHELD_ENV_VARS}
    if overrides:
        env.update(overrides)
    return env
