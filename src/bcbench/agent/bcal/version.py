import json
import subprocess

from pydantic import BaseModel, Field, ValidationError

from bcbench.exceptions import AgentError


class InstalledTool(BaseModel):
    package_id: str = Field(alias="packageId", min_length=1)
    version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+(?:\.[0-9]+)?(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$")
    commands: list[str]


class InstalledTools(BaseModel):
    version: int
    data: list[InstalledTool]


def parse_bcal_version(output: str, expected: str | None = None) -> str:
    try:
        tools = InstalledTools.model_validate_json(output)
    except (ValidationError, json.JSONDecodeError) as exc:
        raise AgentError("Cannot read installed BCAL NuGet version from dotnet tool list JSON") from exc
    if tools.version != 1:
        raise AgentError(f"Unsupported dotnet tool list JSON format: {tools.version}")
    matches = [tool for tool in tools.data if "bcal" in tool.commands]
    if len(matches) != 1:
        raise AgentError(f"Expected exactly one installed global NuGet tool providing bcal; found {len(matches)}")
    version = matches[0].version
    if expected is not None and version != expected.strip():
        raise AgentError(f"Installed BCAL NuGet version {version} does not match the workflow-recorded version {expected!r}")
    return version


def get_bcal_version(expected: str | None = None) -> str:
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
    return parse_bcal_version(result.stdout, expected)
