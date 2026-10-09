import json
import subprocess
from unittest.mock import patch

import pytest

from bcbench.agent.bcal.version import get_bcal_version, parse_bcal_version
from bcbench.exceptions import AgentError


def tools(*entries):
    return json.dumps({"version": 1, "data": list(entries)})


BCAL = {"packageId": "example.bcal.cli", "version": "18.0.38.47039-beta", "commands": ["bcal"]}


def test_reads_actual_nuget_version_without_normalizing_prerelease_or_fourth_component():
    other = {"packageId": "other.tool", "version": "9.9.9", "commands": ["other"]}
    assert parse_bcal_version(tools(other, BCAL)) == "18.0.38.47039-beta"


def test_recorded_version_is_checked_not_blindly_trusted():
    assert parse_bcal_version(tools(BCAL), "18.0.38.47039-beta") == BCAL["version"]
    with pytest.raises(AgentError, match="does not match"):
        parse_bcal_version(tools(BCAL), "18.0.1.1-beta")


@pytest.mark.parametrize(
    "output",
    [tools(), tools(BCAL, BCAL), tools({**BCAL, "version": "latest"}), "not json", '{"version":2,"data":[]}', '{"version":1,"data":[{"packageId":"bcal","commands":["bcal"]}]}'],
)
def test_missing_ambiguous_or_invalid_discovery_is_not_unknown_success(output):
    with pytest.raises(AgentError):
        parse_bcal_version(output)


def test_discovery_calls_structured_global_tool_list():
    with patch("bcbench.agent.bcal.version.subprocess.run", return_value=subprocess.CompletedProcess([], 0, stdout=tools(BCAL))) as run:
        assert get_bcal_version() == BCAL["version"]
    assert run.call_args.args[0] == ["dotnet", "tool", "list", "--global", "--format", "json"]
    assert run.call_args.kwargs["check"] is True
    assert run.call_args.kwargs["timeout"] == 30


@pytest.mark.parametrize("error", [FileNotFoundError("dotnet missing"), subprocess.CalledProcessError(1, "dotnet"), subprocess.TimeoutExpired("dotnet", 30)])
def test_discovery_failure_is_explicit(error):
    with patch("bcbench.agent.bcal.version.subprocess.run", side_effect=error), pytest.raises(AgentError, match="Cannot discover"):
        get_bcal_version()
