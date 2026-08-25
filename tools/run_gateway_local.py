import importlib.util
import os
import sys
import time

_spec = importlib.util.spec_from_file_location(
    "mcp_gateway",
    os.path.join(os.path.dirname(__file__), "..", "src", "bcbench", "agent", "shared", "mcp_gateway.py"),
)
_mod = importlib.util.module_from_spec(_spec)
# Stub the two bcbench imports mcp_gateway needs so we don't pull the whole package.
import types  # noqa: E402

_exc = types.ModuleType("bcbench.exceptions")
_exc.AgentError = type("AgentError", (Exception,), {})
_log = types.ModuleType("bcbench.logger")
import logging  # noqa: E402

logging.basicConfig(level=logging.INFO)
_log.get_logger = lambda _name: logging.getLogger("mcp_gateway")
sys.modules["bcbench.exceptions"] = _exc
sys.modules["bcbench.logger"] = _log
_spec.loader.exec_module(_mod)
start_bc_mcp_gateway = _mod.start_bc_mcp_gateway

os.environ["BC_MCP_URL"] = sys.argv[1]  # upstream mock, e.g. http://127.0.0.1:8765/BC
os.environ["BC_SERVER_USERNAME"] = "admin"
os.environ["BC_SERVER_PASSWORD"] = "secret"

gw = start_bc_mcp_gateway(enabled=True)
print(f"GATEWAY_URL={gw.base_url}/mcp", flush=True)
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    gw.stop()
