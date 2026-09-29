import os

# BC container connection details/credentials the harness uses to build the MCP config and to reach the
# container. They must NOT leak into a launched agent's own process environment: otherwise the agent can
# read the credentials and query BC's API directly from a shell, bypassing the MCP server the benchmark
# is meant to exercise. BC_CONTAINER_NAME is withheld for the same reason (it lets the agent target the
# container directly, e.g. `docker exec ... sqlcmd`). MCP servers still receive what they need through
# other channels (an embedded env block for altool; the BC MCP gateway injects the auth header upstream,
# so the agent's MCP config stays credential-free), so withholding these from the agent process closes
# the direct-API/direct-DB side-doors without breaking MCP connectivity.
_AGENT_ENV_VARS = frozenset(
    {
        "PATH",
        "PATHEXT",
        "HOME",
        "USERPROFILE",
        "SYSTEMROOT",
        "WINDIR",
        "COMSPEC",
        "SYSTEMDRIVE",
        "PROGRAMFILES",
        "PROGRAMFILES(X86)",
        "TEMP",
        "TMP",
        "TMPDIR",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "APPDATA",
        "LOCALAPPDATA",
        "XDG_CONFIG_HOME",
        "XDG_CACHE_HOME",
        "XDG_DATA_HOME",
        "COPILOT_GITHUB_TOKEN",
        "CLAUDE_CODE_OAUTH_TOKEN",
        "ANTHROPIC_API_KEY",
    }
)
_BC_ENV_PREFIXES = ("BC_SERVER_", "BC_MCP_")
_BC_ENV_VARS = frozenset({"BC_COMPANY", "BC_CONTAINER_NAME"})


def agent_subprocess_env(overrides: dict[str, str] | None = None, *, pass_bc_credentials: bool = False) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k in _AGENT_ENV_VARS or (pass_bc_credentials and (k.startswith(_BC_ENV_PREFIXES) or k in _BC_ENV_VARS))}
    if overrides:
        env.update(overrides)
    return env
