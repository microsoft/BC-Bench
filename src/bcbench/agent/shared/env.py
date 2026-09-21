import os
import re
from collections.abc import Mapping
from ntpath import splitdrive
from pathlib import Path

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
_AGENT_ENV_ALLOWLIST = frozenset(
    {
        "ALLUSERSPROFILE",
        "APPDATA",
        "COMSPEC",
        "COPILOT_GITHUB_TOKEN",
        "CLAUDE_CODE_OAUTH_TOKEN",
        "GH_TOKEN",
        "HOMEDRIVE",
        "HOMEPATH",
        "LOCALAPPDATA",
        "NODE_PATH",
        "PATH",
        "PATHEXT",
        "PROGRAMDATA",
        "PROGRAMFILES",
        "PROGRAMFILES(X86)",
        "SYSTEMDRIVE",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "USERPROFILE",
        "WINDIR",
    }
)
_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:$")


def production_agent_profile_environment(agent_logs: Path) -> dict[str, str]:
    profile = agent_logs / "profile"
    profile_text = str(profile)
    home_drive, home_path = splitdrive(profile_text)
    if _WINDOWS_DRIVE.fullmatch(home_drive) is None or not home_path.startswith(("\\", "/")):
        raise ValueError(f"Production agent profile must use an absolute Windows drive path: {profile}")
    local_app_data = profile / "AppData" / "Local"
    temp = profile / "temp"
    return {
        "APPDATA": str(profile / "AppData" / "Roaming"),
        "LOCALAPPDATA": str(local_app_data),
        "USERPROFILE": profile_text,
        "HOMEDRIVE": home_drive,
        "HOMEPATH": home_path,
        "TEMP": str(temp),
        "TMP": str(temp),
    }


def agent_subprocess_env(
    overrides: Mapping[str, str] | None = None,
    *,
    pass_bc_credentials: bool = False,
    allowlist: bool = False,
    final_overrides: Mapping[str, str] | None = None,
) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if key.upper() in _AGENT_ENV_ALLOWLIST} if allowlist else dict(os.environ)
    if not allowlist and not pass_bc_credentials:
        env = {k: v for k, v in env.items() if not k.startswith(_WITHHELD_ENV_PREFIXES) and k not in _WITHHELD_ENV_VARS}
    if overrides:
        env.update(overrides)
    if final_overrides:
        env.update(final_overrides)
    return env
