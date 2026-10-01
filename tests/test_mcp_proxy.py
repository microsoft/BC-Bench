import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from bcbench.diagnostics import mcp_proxy
from bcbench.diagnostics.mcp_diagnostics import SafeDiagnosticSnapshot

SECRET = "super-secret-token-source-and-password"
INVOCATION = "a" * 32


def _command(tmp_path, script, *args):
    return [sys.executable, "-u", mcp_proxy.__file__, str(tmp_path), INVOCATION, "--", sys.executable, "-u", "-c", script, *args]


def _snapshots(tmp_path):
    return [json.loads(path.read_text()) for path in (tmp_path / "diagnostics" / "al-mcp-transport" / INVOCATION).glob("*.json")]


def test_proxy_preserves_binary_streams_arguments_environment_and_cwd(tmp_path: Path):
    (tmp_path / ".env").write_text(f"BCBENCH_MUST_NOT_LOAD={SECRET}\n", encoding="utf-8")
    wire = b'{"jsonrpc":"2.0","id":1,"method":"tools/list","secret":"' + SECRET.encode() + b'"}\r\n\x00\xff partial'
    stderr = SECRET.encode() * 6000
    script = f"""
import os, sys
assert os.getcwd() == {str(tmp_path)!r}
assert os.environ["BC_SERVER_PASSWORD"] == {SECRET!r}
assert "BCBENCH_MUST_NOT_LOAD" not in os.environ
assert sys.argv[1:] == ["argument with spaces", "quoted\\"argument"]
sys.stderr.buffer.write({stderr!r})
sys.stderr.buffer.flush()
sys.stdout.buffer.write(sys.stdin.buffer.read())
sys.stdout.buffer.flush()
"""
    # Keep the Windows command line bounded; the child creates the large stderr stream.
    script = script.replace(repr(stderr), f"{SECRET.encode()!r} * 6000")
    env = dict(os.environ, BC_SERVER_PASSWORD=SECRET, GITHUB_ACTIONS="true")
    result = subprocess.run(_command(tmp_path, script, "argument with spaces", 'quoted"argument'), input=wire, capture_output=True, cwd=tmp_path, env=env, timeout=20, check=True)
    assert result.stdout == wire
    assert result.stderr == stderr
    snapshots = _snapshots(tmp_path)
    assert len(snapshots) == 1
    state = snapshots[0]["transport"]
    assert state["process"]["exit_code"] == 0
    assert state["process"]["cleanup"] == "complete"
    assert SECRET not in json.dumps(snapshots)


def test_proxy_observes_actual_connection_with_no_extra_requests(tmp_path: Path):
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"secret": SECRET}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "al_publish", "arguments": {"password": SECRET}}},
        {"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 3, "reason": SECRET}},
    ]
    script = f"""
import json, sys
requests = [json.loads(line) for line in sys.stdin.buffer]
assert requests == {requests!r}
for request in requests:
    if "id" not in request:
        continue
    if request["method"] == "tools/list":
        result = {{"tools": [{{"name": "al_publish", "description": {SECRET!r}}}, {{"name": "al_run_tests"}}]}}
    elif request["method"] == "tools/call":
        result = {{"isError": True, "content": [{{"type": "text", "text": "HTTP 401 Unauthorized: " + {SECRET!r}}}]}}
    else:
        result = {{"capabilities": {{"tools": {{}}}}}}
    print(json.dumps({{"jsonrpc": "2.0", "id": request["id"], "result": result}}), flush=True)
"""
    wire = b"".join(json.dumps(request).encode() + b"\n" for request in requests)
    result = subprocess.run(_command(tmp_path, script), input=wire, capture_output=True, timeout=20, check=True)
    assert len(result.stdout.splitlines()) == 3
    snapshots = _snapshots(tmp_path)
    state = snapshots[0]["transport"]
    assert state["lists"][0]["tool_names"] == ["al_publish", "al_run_tests"]
    assert state["target_call_requests"] == {"al_publish": 1, "al_run_tests": 0}
    assert state["process"]["cleanup"] == "complete"
    assert SECRET not in json.dumps(snapshots)


@pytest.mark.parametrize("mode", ["missing", "crash"])
def test_startup_failure_retains_safe_exit_and_protocol_stage(tmp_path: Path, mode: str):
    command = _command(tmp_path, f"import sys;sys.stderr.write('You must install or update .NET {SECRET}');sys.exit(7)")
    if mode == "missing":
        command = [*command[:6], str(tmp_path / SECRET)]
    result = subprocess.run(command, input=b"", capture_output=True, timeout=20, check=False)
    snapshots = _snapshots(tmp_path)
    assert result.returncode != 0
    assert len(snapshots) == 1
    state = snapshots[0]["transport"]
    assert state["lists"] == []
    if mode == "missing":
        assert state["process"]["failure_stage"] == "process_spawn"
        assert state["process"]["os_error"] is not None
        assert SECRET.encode() not in result.stderr
    else:
        assert state["process"]["exit_code"] == 7
    assert SECRET not in json.dumps(snapshots)


def test_client_eof_does_not_introduce_a_tool_completion_deadline(tmp_path: Path):
    script = "import sys,time;sys.stdin.buffer.read();time.sleep(3);sys.stdout.buffer.write(b'completed\\n')"
    result = subprocess.run(_command(tmp_path, script), input=b"", capture_output=True, timeout=15, check=True)
    state = _snapshots(tmp_path)[0]["transport"]
    assert result.stdout == b"completed\n"
    assert state["process"]["termination"] == "natural_exit"
    assert state["process"]["cleanup"] == "complete"


def test_natural_parent_exit_does_not_wait_for_descendants_stdout(tmp_path: Path):
    script = "import subprocess,sys;subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'],stdout=sys.stdout,stderr=sys.stderr);print('done',flush=True)"
    result = subprocess.run(_command(tmp_path, script), input=b"", capture_output=True, timeout=15, check=True)
    assert result.stdout == b"done\r\n" or result.stdout == b"done\n"
    state = _snapshots(tmp_path)[0]["transport"]
    assert state["process"]["termination"] == "natural_exit"
    assert state["process"]["cleanup"] == "complete"


def test_observer_overflow_is_explicit_and_does_not_invent_absence(tmp_path: Path):
    snapshot = SafeDiagnosticSnapshot(tmp_path, invocation_id=INVOCATION, connection_id="b" * 32)
    worker = mcp_proxy.ObservationWorker(snapshot)
    worker.dropped.set()
    worker.submit("server", b'{"jsonrpc":"2.0","id":1,"result":{"tools":[]}}\n')
    worker.close()
    state = json.loads(snapshot.path.read_text())["transport"]
    assert "observer_queue_overflow" in state["observation_issues"]
    assert state["lists"] == []
    assert state["observation_complete"] is False


def test_downstream_closed_stops_only_the_owned_server(tmp_path: Path):
    script = "import sys,time;print('ready',flush=True);time.sleep(30)"
    process = subprocess.Popen(_command(tmp_path, script), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        process.stdout.close()
        assert process.wait(timeout=15) != 0
        state = _snapshots(tmp_path)[0]["transport"]
        assert state["process"]["termination"] == "downstream_closed"
        assert state["process"]["cleanup"] == "complete"
        assert "server_relay_interrupted" in state["observation_issues"]
        assert state["observation_complete"] is False
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        process.stdin.close()
        process.stderr.close()


def test_reconnections_use_distinct_snapshots(tmp_path: Path):
    processes = [subprocess.Popen(_command(tmp_path, "pass"), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(2)]
    try:
        for process in processes:
            assert process.communicate(b"", timeout=15) == (b"", b"")
            assert process.returncode == 0
        snapshots = _snapshots(tmp_path)
        assert len(snapshots) == 2
        assert len({snapshot["connection_id"] for snapshot in snapshots}) == 2
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)


def test_snapshot_failure_never_contaminates_protocol_stdout(tmp_path: Path):
    output_path = tmp_path / SECRET
    output_path.write_text("not a directory", encoding="utf-8")
    wire = b'{"jsonrpc":"2.0","id":1,"method":"tools/list"}\r\n'
    script = "import sys;sys.stdout.buffer.write(sys.stdin.buffer.read())"
    result = subprocess.run(
        _command(output_path, script),
        input=wire,
        capture_output=True,
        env=dict(os.environ, GITHUB_ACTIONS="true"),
        timeout=15,
        check=True,
    )
    assert result.stdout == wire
    assert b"filesystem_error" in result.stderr
    assert SECRET.encode() not in result.stderr
    assert b"::warning" not in result.stdout


def test_partial_writes_preserve_every_byte(monkeypatch):
    written = bytearray()

    def short_write(fd, data):
        written.extend(data[:2])
        return min(len(data), 2)

    monkeypatch.setattr(mcp_proxy.os, "write", short_write)
    message = b"\xff\x00\r\nbinary protocol bytes\n"
    mcp_proxy._write_all(1, message)
    assert written == message


@pytest.mark.skipif(sys.platform != "win32", reason="Nested Windows job ownership")
def test_outer_agent_timeout_cleans_proxy_and_actual_server(tmp_path: Path):
    from bcbench.agent.shared.diagnostic_process import DiagnosticProcess
    from tests.test_diagnostic_process import ChildProcessHandle

    script = "import os,time,json;print(json.dumps({'pid':os.getpid()}),flush=True);time.sleep(30)"
    child = None
    try:
        with DiagnosticProcess(_command(tmp_path, script), tmp_path, dict(os.environ)) as process:
            line = next(process.lines(time.monotonic() + 10))
            child = ChildProcessHandle(json.loads(line)["pid"])
            assert not child.wait(0)
        assert process.cleanup_complete
        assert child.wait(1000)
        assert len(_snapshots(tmp_path)) == 1
    finally:
        if child is not None:
            child.close()
