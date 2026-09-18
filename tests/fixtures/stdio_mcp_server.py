import json
import os
import subprocess
import sys
import time
from pathlib import Path


def send(message):
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", **message}) + "\n")
    sys.stdout.flush()


Path("server.pid").write_text(str(os.getpid()))
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
Path("descendant.pid").write_text(str(child.pid))
for line in sys.stdin:
    message = json.loads(line)
    method = message.get("method")
    request_id = message.get("id")
    if method == "initialize":
        send({"id": request_id, "result": {"protocolVersion": "2025-03-26", "capabilities": {"tools": {}}, "serverInfo": {"name": "fixture", "version": "1"}}})
    elif method == "tools/list":
        send({"id": request_id, "result": {"tools": [{"name": "echo", "inputSchema": {"type": "object"}}]}})
    elif method == "tools/call":
        send({"id": request_id, "result": {"content": [{"type": "text", "text": json.dumps(message["params"])}]}})
    elif method == "fixture/wait":
        Path("waiting").touch()
    elif method == "notifications/cancelled":
        send({"id": message["params"]["requestId"], "error": {"code": -32800, "message": message["params"]["reason"]}})
    elif method == "fixture/error":
        send({"id": request_id, "error": {"code": -32001, "message": "upstream failure", "data": {"detail": 42}}})
    elif method == "fixture/crash":
        sys.exit(3)
    elif method == "fixture/invalid":
        sys.stdout.write("not JSON\n")
        sys.stdout.flush()
    elif method == "fixture/events":
        send({"method": "notifications/tools/list_changed"})
        send({"id": "server-request", "method": "roots/list"})
        send({"id": request_id, "result": {}})
    elif request_id == "server-request":
        Path("server-response.json").write_text(json.dumps(message))
    elif method == "fixture/secret-ready":
        send({"id": request_id, "result": {"configured": bool(os.environ.get("BC_SERVER_PASSWORD"))}})
    elif request_id is not None:
        send({"id": request_id, "error": {"code": -32601, "message": "Unknown method"}})
time.sleep(60)
