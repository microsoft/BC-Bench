import argparse
import base64
import json
import os
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from queue import Empty, Queue
from threading import Thread
from typing import Any, TextIO

import yaml

from bcbench.agent.shared import build_mcp_config
from bcbench.config import get_config
from bcbench.dataset import BugFixEntry
from bcbench.operations import apply_patch, categorize_projects, clean_project_paths, set_runtime_version, setup_repo_prebuild
from bcbench.operations.bc_operations import _escape_ps_string, build_ps_app_build_and_publish
from bcbench.types import AgentRuntimeConfig, ContainerConfig, EvaluationCategory

INSTANCE_ID = "microsoftInternal__NAV-223493"
MCP_STARTUP_TIMEOUT = 180
MCP_TIMEOUT = get_config().timeout.build_baseapp


def redact(text: str, secrets: tuple[str, ...]) -> str:
    values: list[str] = [secret for secret in secrets if secret]
    for secret in sorted(values, key=lambda value: -len(value)):
        text = text.replace(secret, "***")
    return text


def read_saved_patch(path: Path) -> str:
    lines = [line for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    if len(lines) != 1:
        raise ValueError("Expected exactly one saved result")
    result = json.loads(lines[0])
    if result.get("instance_id") != INSTANCE_ID:
        raise ValueError("Saved result has an unexpected instance_id")
    patch = result.get("output")
    if not isinstance(patch, str) or not patch.strip():
        raise ValueError("Saved result does not contain a generated patch")
    return patch


def require_disposable_workspace(repo_path: Path, container_name: str) -> None:
    workspace = os.environ.get("GITHUB_WORKSPACE")
    if (
        os.environ.get("GITHUB_ACTIONS") != "true"
        or os.environ.get("BCBENCH_PUBLISH_REPRO") != INSTANCE_ID
        or workspace is None
        or repo_path.resolve() != (Path(workspace) / "testbed").resolve()
        or container_name != "bcbench-223493"
    ):
        raise ValueError("This diagnostic is restricted to its disposable Actions workspace and container")


class Evidence:
    def __init__(self, root: Path, secrets: tuple[str, ...]) -> None:
        self.root = root
        self.secrets = secrets
        self.records: list[dict[str, Any]] = []
        root.mkdir(parents=True, exist_ok=True)

    def write(self, name: str, text: str) -> None:
        (self.root / name).write_text(redact(text, self.secrets), encoding="utf-8")

    def record(self, phase: str, returncode: int, duration: float, stdout: str = "", stderr: str = "", *, timed_out: bool = False) -> None:
        self.write(f"{phase}.stdout.log", stdout)
        self.write(f"{phase}.stderr.log", stderr)
        self.records.append({"phase": phase, "finished_at": datetime.now(UTC).isoformat(), "duration_seconds": duration, "returncode": returncode, "timed_out": timed_out})
        self.write("summary.json", json.dumps(self.records, indent=2))
        print(f"{phase}: exit={returncode}, duration={duration:.1f}s, timed_out={timed_out}", flush=True)


def _text(value: str | bytes | None) -> str:
    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value or ""


def run_powershell(script: str, phase: str, evidence: Evidence, *, timeout: int) -> bool:
    started = time.monotonic()
    print(f"{datetime.now(UTC).isoformat()} Starting {phase}", flush=True)
    try:
        result = subprocess.run(["pwsh", "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, check=False)
    except subprocess.TimeoutExpired as error:
        evidence.record(phase, 124, time.monotonic() - started, _text(error.stdout), _text(error.stderr), timed_out=True)
        return False
    evidence.record(phase, result.returncode, time.monotonic() - started, result.stdout, result.stderr)
    return result.returncode == 0


def build_projects(entry: BugFixEntry, repo_path: Path, container: ContainerConfig, evidence: Evidence, phase: str) -> bool:
    config = get_config()
    for index, project in enumerate(entry.project_paths):
        script = build_ps_app_build_and_publish(container.name, container.username, container.password, repo_path / project, entry.environment_setup_version)
        timeout = config.timeout.build_baseapp if "BaseApp" in project else config.timeout.build_app
        if not run_powershell(script, f"{phase}-{index}", evidence, timeout=timeout):
            return False
    return True


def snapshot(container: ContainerConfig, evidence: Evidence, phase: str) -> None:
    script = """
$ErrorActionPreference = 'Stop'
Import-Module BcContainerHelper -Force -DisableNameChecking
Invoke-ScriptInBcContainer -containerName '__CONTAINER__' -scriptblock {
    $ErrorActionPreference = 'Stop'
    $apps = @(Get-NAVAppInfo -ServerInstance BC -Tenant default -TenantSpecificProperties |
        Select-Object AppId, PackageId, Name, Publisher, @{Name='Version';Expression={$_.Version.ToString()}}, Scope, IsInstalled, SyncState, NeedsUpgrade)
    $query = 'SELECT [Name], [Published As], [Tenant ID], [Version Major], [Version Minor], [Version Build], [Version Revision] FROM [CRONUS].[dbo].[Published Application] ORDER BY [Name]'
    $catalog = @(Invoke-Sqlcmd -ServerInstance '.' -Query $query |
        Select-Object Name, 'Published As', 'Tenant ID', 'Version Major', 'Version Minor', 'Version Build', 'Version Revision')
    [pscustomobject]@{ capturedAt=(Get-Date).ToUniversalTime().ToString('o'); apps=$apps; publishedCatalog=$catalog } |
        ConvertTo-Json -Depth 6
}
""".replace("__CONTAINER__", _escape_ps_string(container.name))
    if not run_powershell(script, phase, evidence, timeout=120):
        print(f"::warning::Could not capture {phase}; see its stderr artifact", flush=True)


def read_response(messages: Queue[str | None], request_id: int, timeout: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise Empty
        line = messages.get(timeout=remaining)
        if line is None:
            raise RuntimeError("AL MCP closed its stdout before responding")
        response = json.loads(line)
        if response.get("id") == request_id:
            return response


def send(process: subprocess.Popen[str], message: dict[str, Any]) -> None:
    if process.stdin is None:
        raise RuntimeError("AL MCP stdin is unavailable")
    process.stdin.write(json.dumps(message) + "\n")
    process.stdin.flush()


def response_failed(response: dict[str, Any]) -> bool:
    result = response.get("result", {})
    if "error" in response or result.get("isError", False):
        return True
    for content in result.get("content", []):
        if content.get("type") != "text":
            continue
        try:
            payload = json.loads(content["text"])
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and payload.get("succeeded") is False:
            return True
    return False


def request(
    process: subprocess.Popen[str],
    messages: Queue[str | None],
    evidence: Evidence,
    request_id: int,
    method: str,
    params: dict[str, Any],
    *,
    timeout: float = MCP_TIMEOUT,
) -> dict[str, Any] | None:
    phase = f"mcp-{request_id}-{params.get('name', method.replace('/', '-'))}"
    evidence.write(f"{phase}.request.json", json.dumps({"method": method, "params": params}, indent=2))
    started = time.monotonic()
    send(process, {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
    try:
        response = read_response(messages, request_id, timeout)
    except Empty:
        evidence.record(phase, 124, time.monotonic() - started, timed_out=True)
        send(process, {"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": request_id, "reason": "Configured MCP deadline elapsed"}})
        return None
    failed = response_failed(response)
    evidence.record(phase, int(failed), time.monotonic() - started, json.dumps(response, indent=2))
    return None if failed else response


def pump_stream(stream: TextIO, destination: TextIO, secrets: tuple[str, ...], messages: Queue[str | None] | None = None) -> None:
    for line in stream:
        destination.write(f"{datetime.now(UTC).isoformat()} {redact(line, secrets)}")
        destination.flush()
        if messages is not None:
            messages.put(line)
    if messages is not None:
        messages.put(None)


def run_al_mcp(entry: BugFixEntry, repo_path: Path, container: ContainerConfig, evidence: Evidence) -> bool:
    config_path = get_config().paths.agent_share_dir / "config.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    configuration, _ = build_mcp_config(config, entry, repo_path, runtime=AgentRuntimeConfig(container=container, al_mcp=True))
    if configuration is None:
        raise ValueError("AL MCP configuration was not generated")
    server = json.loads(configuration)["mcpServers"]["altool"]
    _, app_projects = categorize_projects(entry.project_paths)
    if len(app_projects) != 1:
        raise ValueError("The fixed reproduction entry must have exactly one product project")
    project = str(repo_path / app_projects[0])
    messages: Queue[str | None] = Queue()
    command = [server["command"], *server["args"], "--nolog"]
    started = time.monotonic()
    with (
        (evidence.root / "mcp.stdout.log").open("w", encoding="utf-8") as stdout,
        (evidence.root / "mcp.stderr.log").open("w", encoding="utf-8") as stderr,
        subprocess.Popen(
            command, cwd=repo_path, env={**os.environ, **server.get("env", {})}, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace"
        ) as process,
    ):
        if process.stdout is None or process.stderr is None or process.stdin is None:
            raise RuntimeError("AL MCP redirected streams are unavailable")
        readers = [
            Thread(target=pump_stream, args=(process.stdout, stdout, evidence.secrets, messages), daemon=True),
            Thread(target=pump_stream, args=(process.stderr, stderr, evidence.secrets), daemon=True),
        ]
        for reader in readers:
            reader.start()
        try:
            if (
                request(
                    process,
                    messages,
                    evidence,
                    1,
                    "initialize",
                    {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "bcbench-publish-reproduction", "version": "1.0"}},
                    timeout=MCP_STARTUP_TIMEOUT,
                )
                is None
            ):
                return False
            send(process, {"jsonrpc": "2.0", "method": "notifications/initialized"})
            if request(process, messages, evidence, 2, "tools/list", {}, timeout=MCP_STARTUP_TIMEOUT) is None:
                return False
            if request(process, messages, evidence, 3, "tools/call", {"name": "al_build", "arguments": {"projectPath": project, "onlyErrors": True}}) is None:
                return False
            return request(process, messages, evidence, 4, "tools/call", {"name": "al_publish", "arguments": {"projectPath": project, "skipBuild": True}}) is not None
        finally:
            process.stdin.close()
            forced_shutdown = False
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                forced_shutdown = True
                process.kill()
                process.wait(timeout=15)
            for reader in readers:
                reader.join(timeout=5)
                if reader.is_alive():
                    raise RuntimeError("AL MCP output reader did not stop")
            evidence.record("mcp-shutdown", process.returncode, time.monotonic() - started, timed_out=forced_shutdown)


def replay(entry: BugFixEntry, repo_path: Path, container: ContainerConfig, patch: str, evidence: Evidence) -> bool:
    apply_patch(repo_path, patch, "saved generated fix")
    snapshot(container, evidence, "before-mcp")
    mcp_ok = run_al_mcp(entry, repo_path, container, evidence)
    snapshot(container, evidence, "after-mcp")
    test_projects, _ = categorize_projects(entry.project_paths)
    clean_project_paths(repo_path, test_projects)
    apply_patch(repo_path, entry.test_patch, "hidden test patch")
    try:
        evaluation_ok = build_projects(entry, repo_path, container, evidence, "evaluator")
    finally:
        snapshot(container, evidence, "after-evaluator")
    return mcp_ok and evaluation_ok


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay the approved publishing diagnostic in its disposable CI job.")
    parser.add_argument("--repo-path", type=Path, required=True)
    parser.add_argument("--result-file", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    container = ContainerConfig(
        name=os.environ["BC_CONTAINER_NAME"],
        username=os.environ["BC_SERVER_USERNAME"],
        password=os.environ["BC_SERVER_PASSWORD"],
        company=os.environ["BC_COMPANY"],
        server_url=os.environ["BC_SERVER_URL"],
        server_instance=os.environ["BC_SERVER_INSTANCE"],
    )
    require_disposable_workspace(args.repo_path, container.name)
    basic_auth = base64.b64encode(f"{container.username}:{container.password}".encode()).decode()
    evidence = Evidence(args.output_dir, (container.password, basic_auth, os.environ.get("GITHUB_TOKEN", ""), os.environ.get("GH_TOKEN", "")))
    patch = read_saved_patch(args.result_file)
    entry = BugFixEntry.load(EvaluationCategory.BUG_FIX.dataset_path, entry_id=INSTANCE_ID)[0]
    evidence.write(
        "entry.json",
        json.dumps(
            {"instance_id": INSTANCE_ID, "source_run": "34091156251", "base_commit": entry.base_commit, "bc_version": entry.environment_setup_version, "mcp_timeout_seconds": MCP_TIMEOUT}, indent=2
        ),
    )
    setup_repo_prebuild(entry, args.repo_path)
    if not build_projects(entry, args.repo_path, container, evidence, "baseline"):
        snapshot(container, evidence, "failed-baseline")
        return 1
    set_runtime_version(args.repo_path, entry.project_paths)
    return 0 if replay(entry, args.repo_path, container, patch, evidence) else 1


if __name__ == "__main__":
    raise SystemExit(main())
