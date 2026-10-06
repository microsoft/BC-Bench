import os

from bcbench_core.agent.env import agent_subprocess_env as build_agent_subprocess_env

# BC container connection details/credentials the harness uses to build the MCP config and to reach the
# container. They must NOT leak into a launched agent's own process environment: otherwise the agent can
# read the credentials and query BC's API directly from a shell, bypassing the MCP server the benchmark
# is meant to exercise. BC_CONTAINER_NAME is withheld for the same reason (it lets the agent target the
# container directly, e.g. `docker exec ... sqlcmd`). MCP servers still receive what they need through
# other channels (an embedded env block for altool; the BC MCP gateway injects the auth header upstream,
# so the agent's MCP config stays credential-free), so withholding these from the agent process closes
# the direct-API/direct-DB side-doors without breaking MCP connectivity.
_WITHHELD_ENV_PREFIXES = ("BC_SERVER_", "BC_MCP_")
_WITHHELD_ENV_VARS = frozenset({"BC_COMPANY", "BC_CONTAINER_NAME"})


def agent_subprocess_env(overrides: dict[str, str] | None = None, *, pass_bc_credentials: bool = False) -> dict[str, str]:
    return build_agent_subprocess_env(
        os.environ,
        overrides,
        exclude_vars=() if pass_bc_credentials else _WITHHELD_ENV_VARS,
        exclude_prefixes=() if pass_bc_credentials else _WITHHELD_ENV_PREFIXES,
    )
