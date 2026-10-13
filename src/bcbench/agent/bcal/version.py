import re
import subprocess

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from bcbench.exceptions import AgentError

NUGET_VERSION_PATTERN = r"^[0-9]+\.[0-9]+\.[0-9]+(?:\.[0-9]+)?(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"


class InstalledTool(BaseModel):
    model_config = ConfigDict(strict=True)

    package_id: str = Field(alias="packageId", min_length=1)
    version: str = Field(pattern=NUGET_VERSION_PATTERN)
    commands: list[str]


class InstalledTools(BaseModel):
    model_config = ConfigDict(strict=True)

    version: int
    data: list[InstalledTool]


def parse_bcal_version(output: str) -> str:
    try:
        tools = InstalledTools.model_validate_json(output)
    except ValidationError as exc:
        raise AgentError("Cannot read installed BCAL NuGet version from dotnet tool list JSON") from exc
    if tools.version != 1:
        raise AgentError(f"Unsupported dotnet tool list JSON format: {tools.version}")
    matches = [tool for tool in tools.data if any(command.casefold() == "bcal" for command in tool.commands)]
    if len(matches) != 1:
        raise AgentError(f"Expected exactly one installed global NuGet tool providing bcal; found {len(matches)}")
    return matches[0].version


def verify_bcal_version(actual: str, expected: str | None) -> None:
    if expected is None:
        return
    normalized = expected.strip()
    if re.fullmatch(NUGET_VERSION_PATTERN, normalized) is None:
        raise AgentError("Expected BCAL NuGet version must be an exact, non-empty version")
    if actual != normalized:
        raise AgentError(f"Installed BCAL NuGet version {actual} does not match expected version {expected!r}")


def get_bcal_version() -> str:
    try:
        result = subprocess.run(
            ["dotnet", "tool", "list", "--global", "--format", "json"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise AgentError("Cannot discover the installed BCAL NuGet version; dotnet tool list --global --format json must succeed") from exc
    return parse_bcal_version(result.stdout)
