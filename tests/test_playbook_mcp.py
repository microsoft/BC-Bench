import json
import subprocess
import sys
from pathlib import Path

from tests.test_playbooks import write_package


def test_playbook_mcp_routes_paths_over_stdio(tmp_path: Path):
    playbook_dir = write_package(tmp_path)
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-11-25"}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "route_bug_fix_playbook",
                "arguments": {"confirmed_paths": ["App/Layers/W1/BaseApp/Warehouse/Activity/Foo.Codeunit.al"]},
            },
        },
    ]

    result = subprocess.run(
        [sys.executable, "-m", "bcbench.playbook_mcp", str(playbook_dir)],
        input="\n".join(json.dumps(request) for request in requests) + "\n",
        capture_output=True,
        text=True,
        check=True,
    )

    responses = [json.loads(line) for line in result.stdout.splitlines()]
    assert responses[0]["result"]["protocolVersion"] == "2025-11-25"
    assert responses[1]["result"]["tools"][0]["name"] == "route_bug_fix_playbook"
    route = responses[2]["result"]["structuredContent"]
    assert route["status"] == "loaded"
    assert route["playbook_id"] == "warehouse"
    assert route["content"] == "# Warehouse\n"


def test_playbook_mcp_rejects_empty_paths(tmp_path: Path):
    playbook_dir = write_package(tmp_path)
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "route_bug_fix_playbook", "arguments": {"confirmed_paths": []}},
    }

    result = subprocess.run(
        [sys.executable, "-m", "bcbench.playbook_mcp", str(playbook_dir)],
        input=json.dumps(request) + "\n",
        capture_output=True,
        text=True,
        check=True,
    )

    response = json.loads(result.stdout)
    assert response["error"]["code"] == -32602
