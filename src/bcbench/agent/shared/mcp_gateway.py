"""A localhost MCP gateway that fronts the BC MCP endpoint for a benchmarked agent.

Why this exists: the agent must reach BC *only* through the MCP server, never the raw OData ``/api``
or the SQL database. The BC container serves ``/api`` and ``/mcp`` on the same port, so a plain
firewall cannot separate them, and putting the Basic credentials in the agent's MCP config leaks them
onto the agent process command line (recoverable via ``Get-CimInstance Win32_Process``), which the
agent could replay against ``/api``.

This gateway closes both holes: it path-restricts to ``/mcp`` (everything else -> 403) and injects the
Basic auth / Company / ConfigurationName headers itself, so the agent's MCP config carries only a
credential-free ``http://127.0.0.1:<port>/.../mcp`` URL. The upstream endpoint and credentials come
from the harness environment (``BC_MCP_URL`` / ``BC_SERVER_*`` / ``BC_MCP_COMPANY``), which is never
scrubbed for the harness itself.
"""

import base64
import json
import os
import threading
import time
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from bcbench.exceptions import AgentError
from bcbench.logger import get_logger

logger = get_logger(__name__)

# Must match the configuration name the setup-time AL app creates (scripts/al/mcp-config-setup).
_CONFIGURATION_NAME = "BCBench"

# Connection-level headers that must not be forwarded across a proxy hop (RFC 7230 6.1), plus the
# framing/credential headers this gateway sets itself.
_HOP_BY_HOP = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
    }
)
_STRIPPED_REQUEST_HEADERS = _HOP_BY_HOP | {"host", "content-length", "accept-encoding", "authorization", "company", "configurationname"}

_UPSTREAM_TIMEOUT_SECONDS = 600
_STREAM_CHUNK_BYTES = 8192
_PROBE_TIMEOUT_SECONDS = 180


def _header_safe(key: str, value: str) -> bool:
    """A header is safe to relay only if neither key nor value contains CR/LF (HTTP response splitting)."""
    return not any(c in key or c in value for c in ("\r", "\n"))


def _jsonrpc_method_and_id(body: bytes | None) -> tuple[str | None, object]:
    if not body:
        return None, None
    try:
        obj = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None, None
    if not isinstance(obj, dict):
        return None, None
    return obj.get("method"), obj.get("id")


def _read_jsonrpc(response, deadline: float) -> dict:  # noqa: ANN001 - http.client.HTTPResponse
    """Parse a JSON-RPC result from an MCP response body (application/json or SSE).

    For SSE, read line by line and return as soon as a JSON-RPC result/error arrives: the BC MCP
    endpoint keeps the event stream open for later messages, so reading to EOF would block until the
    socket times out even though the answer already arrived.
    """
    content_type = response.getheader("Content-Type", "") or ""
    if "text/event-stream" in content_type:
        while time.monotonic() < deadline:
            raw_line = response.readline()
            if not raw_line:
                break
            line = raw_line.decode("utf-8", errors="replace").strip()
            if line.startswith("data:"):
                try:
                    obj = json.loads(line[5:].strip())
                except json.JSONDecodeError:
                    continue
                if isinstance(obj, dict) and ("result" in obj or "error" in obj):
                    return obj
        return {}
    text = response.read().decode("utf-8", errors="replace")
    try:
        return json.loads(text) if text.strip() else {}
    except json.JSONDecodeError:
        return {}


class BcMcpGateway:
    def __init__(self, upstream_url: str, username: str, password: str, company: str | None) -> None:
        split = urlsplit(upstream_url)
        if not split.hostname:
            raise AgentError(f"BC MCP upstream URL is malformed: {upstream_url!r}")

        self._origin_host: str = split.hostname
        self._origin_port: int = split.port or (443 if split.scheme == "https" else 80)
        base_path: str = split.path.rstrip("/")
        self._mcp_path: str = f"{base_path}/mcp"
        self._base_path: str = base_path

        injected: dict[str, str] = {
            "Authorization": f"Basic {base64.b64encode(f'{username}:{password}'.encode()).decode()}",
            "ConfigurationName": _CONFIGURATION_NAME,
        }
        if company:
            injected["Company"] = company
        self._injected_headers: dict[str, str] = injected

        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._forwarded_count = 0
        self.base_url: str | None = None
        # tools/list "result" object captured during warm-up. BC composes the tool catalog per MCP
        # session and the first tools/list is slow (~45s) and sometimes dropped by the server, which
        # blows past the agent's MCP startup timeout so the server registers zero tools. The catalog is
        # identical across sessions, so once warm-up has it the gateway answers tools/list from here,
        # decoupling the agent from BC's cold per-session composition.
        self._cached_tools_result: dict[str, object] | None = None

    @property
    def forwarded_count(self) -> int:
        with self._lock:
            return self._forwarded_count

    def _note_forwarded(self) -> None:
        with self._lock:
            self._forwarded_count += 1

    def start(self) -> "BcMcpGateway":
        gateway = self
        server = ThreadingHTTPServer(("127.0.0.1", 0), _build_handler(gateway))
        self._server = server
        port = server.server_address[1]
        self.base_url = f"http://127.0.0.1:{port}{self._base_path}"
        self._thread = threading.Thread(target=server.serve_forever, name="bc-mcp-gateway", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
        logger.info(f"BC MCP gateway forwarded {self.forwarded_count} request(s) to the BC MCP endpoint")

    def _rpc(self, host: str, port: int, extra_headers: dict[str, str], method: str, params: dict | None, request_id: int | None = None, session_id: str | None = None) -> tuple[str | None, dict]:
        connection = HTTPConnection(host, port, timeout=_PROBE_TIMEOUT_SECONDS)
        try:
            payload: dict[str, object] = {"jsonrpc": "2.0", "method": method}
            if request_id is not None:
                payload["id"] = request_id
            if params is not None:
                payload["params"] = params
            headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream", **extra_headers}
            if session_id:
                headers["Mcp-Session-Id"] = session_id
            connection.request("POST", self._mcp_path, body=json.dumps(payload).encode(), headers=headers)
            response = connection.getresponse()
            returned_session = response.getheader("Mcp-Session-Id")
            return returned_session, _read_jsonrpc(response, deadline=time.monotonic() + _PROBE_TIMEOUT_SECONDS)
        finally:
            connection.close()

    def _handshake_tools(self) -> list[str]:
        """initialize -> notifications/initialized -> tools/list against BC; caches the tools/list result."""
        session_id, _ = self._rpc(
            self._origin_host,
            self._origin_port,
            self._injected_headers,
            "initialize",
            {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "bcbench-probe", "version": "1.0"}},
            request_id=1,
        )
        if session_id:
            self._rpc(self._origin_host, self._origin_port, self._injected_headers, "notifications/initialized", None, session_id=session_id)
        _, listed = self._rpc(self._origin_host, self._origin_port, self._injected_headers, "tools/list", {}, request_id=2, session_id=session_id)
        result = listed.get("result")
        tools = [t.get("name") for t in (result or {}).get("tools", []) if isinstance(t, dict)]
        if tools and isinstance(result, dict):
            with self._lock:
                self._cached_tools_result = result
        return tools

    def warm_up(self) -> list[str]:
        """Prime BC's tool catalog and cache the tools/list result before the agent connects.

        BC composes the tool catalog on the first tools/list of a session (slow, ~45s, sometimes dropped
        by the server), which can blow past the agent's MCP startup timeout so it registers zero tools.
        Fetching it once here warms BC and lets the gateway serve the agent's tools/list from cache.
        Best-effort: never raises -- a failed warm-up must not break a run.
        """
        try:
            tools = self._handshake_tools()
        except Exception as exc:  # noqa: BLE001 - warm-up must never break a run
            logger.warning(f"BC MCP warm-up failed (non-fatal): {exc}")
            return []
        else:
            logger.info(f"BC MCP warm-up: cached {len(tools)} tool(s): {tools}")
            return tools


def _build_handler(gateway: BcMcpGateway) -> type[BaseHTTPRequestHandler]:
    class _ProxyHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, format: str, *args: object) -> None:  # match stdlib signature; silence access log
            pass

        def _path_allowed(self) -> bool:
            path_only = self.path.split("?", 1)[0]
            return path_only == gateway._mcp_path or path_only.startswith(gateway._mcp_path + "/")

        def _handle(self) -> None:
            if not self._path_allowed():
                self.send_error(403, "Forbidden")
                return

            length = self.headers.get("Content-Length")
            body: bytes | None = self.rfile.read(int(length)) if length else None
            rpc_method, rpc_id = _jsonrpc_method_and_id(body)
            self._response_started = False

            if rpc_method == "tools/list" and self._serve_cached_tools(rpc_id):
                return

            request_headers: dict[str, str] = {k: v for k, v in self.headers.items() if k.lower() not in _STRIPPED_REQUEST_HEADERS}
            request_headers["Host"] = f"{gateway._origin_host}:{gateway._origin_port}"
            request_headers.update(gateway._injected_headers)

            connection = HTTPConnection(gateway._origin_host, gateway._origin_port, timeout=_UPSTREAM_TIMEOUT_SECONDS)
            try:
                connection.request(self.command, self.path, body=body, headers=request_headers)
                response = connection.getresponse()
                gateway._note_forwarded()
                # Relay faithfully, byte-for-byte, holding streams open exactly as BC does (its MCP
                # server keeps SSE streams open as the client's event channel). The one exception is the
                # initialize reply: BC advertises capabilities.experimental = {"x-ms-headerless": true},
                # which makes some MCP clients fail the connection; strip it so the client sees a standard
                # server (BC still works over the normal header-based session the warm-up uses).
                if rpc_method == "initialize" and response.status == 200 and "text/event-stream" in (response.getheader("Content-Type", "") or ""):
                    self._relay_initialize(response)
                else:
                    self._relay(response)
            except (ConnectionError, OSError) as error:
                # The client (agent) closing its side mid-stream is normal; don't misreport it as an
                # upstream failure, and don't try to send an error once the response has begun.
                if self._response_started:
                    logger.debug(f"BC MCP gateway client disconnected during {self.command} {rpc_method or self.path}: {error}")
                    self.close_connection = True
                else:
                    logger.exception(f"BC MCP gateway failed to reach upstream for {self.command} {rpc_method or self.path}")
                    self.send_error(502, "Bad Gateway")
            except Exception:
                logger.exception(f"BC MCP gateway error handling {self.command} {rpc_method or self.path}")
                if not self._response_started:
                    self.send_error(502, "Bad Gateway")
            finally:
                connection.close()

        def _serve_cached_tools(self, request_id: object) -> bool:
            """Answer tools/list from the warm-up cache, bypassing BC's slow per-session composition.

            Framed as a single-event SSE stream (then closed) to mirror how BC replies to tools/list, so
            the client sees the same transport it would from the real endpoint.
            """
            with gateway._lock:
                cached = gateway._cached_tools_result
            if cached is None:
                return False
            event = ("event: message\ndata: " + json.dumps({"jsonrpc": "2.0", "id": request_id, "result": cached}) + "\n\n").encode()
            self._response_started = True
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Content-Length", str(len(event)))
            self.end_headers()
            self.wfile.write(event)
            self.wfile.flush()
            return True

        def _relay_initialize(self, response) -> None:  # noqa: ANN001 - http.client.HTTPResponse
            """Relay the initialize SSE reply but strip capabilities.experimental from the result.

            BC advertises ``capabilities.experimental = {"x-ms-headerless": true}``; Claude's MCP client
            fails the connection when it sees it (bisected against a replica of BC's exact initialize
            response). Rewrite just that first result event, then keep relaying faithfully so the stream
            behaves exactly like BC's for everything else.
            """
            self._response_started = True
            forwarded_headers = [(k, v) for k, v in response.getheaders() if k.lower() not in _HOP_BY_HOP and k.lower() not in ("content-length", "content-type") and _header_safe(k, v)]
            self.send_response_only(200)
            for key, value in forwarded_headers:
                self.send_header(key, value)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()

            deadline = time.monotonic() + _UPSTREAM_TIMEOUT_SECONDS
            rewritten = False
            while time.monotonic() < deadline:
                raw_line = response.readline()
                if not raw_line:
                    break
                out_line = raw_line
                stripped = raw_line.decode("utf-8", errors="replace").strip()
                if not rewritten and stripped.startswith("data:"):
                    try:
                        obj = json.loads(stripped[5:].strip())
                    except json.JSONDecodeError:
                        obj = None
                    if isinstance(obj, dict) and isinstance(obj.get("result"), dict):
                        capabilities = obj["result"].get("capabilities")
                        if isinstance(capabilities, dict):
                            capabilities.pop("experimental", None)
                        out_line = ("data: " + json.dumps(obj) + "\n").encode()
                        rewritten = True
                self.wfile.write(b"%X\r\n" % len(out_line))
                self.wfile.write(out_line)
                self.wfile.write(b"\r\n")
                self.wfile.flush()
            # Keep relaying (holding the stream open) exactly like BC until the upstream or client closes.
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()

        def _relay(self, response) -> None:  # noqa: ANN001 - http.client.HTTPResponse
            self._response_started = True
            self.send_response_only(response.status)
            content_length: str | None = None
            for key, value in response.getheaders():
                lowered = key.lower()
                if lowered == "content-length":
                    content_length = value
                    continue
                if lowered in _HOP_BY_HOP:
                    continue
                if not _header_safe(key, value):
                    continue
                self.send_header(key, value)

            if content_length is not None:
                self.send_header("Content-Length", content_length)
                self.end_headers()
                remaining = int(content_length)
                while remaining > 0:
                    chunk = response.read(min(_STREAM_CHUNK_BYTES, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
            else:
                # No content length -> stream (e.g. SSE) with our own chunked framing, flushing each
                # block so server-sent events reach the agent as they arrive. Use read1(): plain read()
                # blocks trying to fill the whole buffer, which stalls an SSE stream the server holds
                # open after a small event (that stall is what made tools/list time out through here).
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()
                while True:
                    chunk = response.read1(_STREAM_CHUNK_BYTES)
                    if not chunk:
                        break
                    self.wfile.write(b"%X\r\n" % len(chunk))
                    self.wfile.write(chunk)
                    self.wfile.write(b"\r\n")
                    self.wfile.flush()
                self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()

        do_GET = _handle
        do_POST = _handle
        do_DELETE = _handle

    return _ProxyHandler


def start_bc_mcp_gateway(enabled: bool) -> BcMcpGateway | None:
    """Start a localhost MCP gateway in front of the BC container, or return None when disabled."""
    if not enabled:
        return None

    upstream = os.environ.get("BC_MCP_URL")
    if not upstream:
        raise AgentError("BC MCP requested but BC_MCP_URL is not set; container setup must export it.")

    gateway = BcMcpGateway(
        upstream_url=upstream,
        username=os.environ.get("BC_SERVER_USERNAME", ""),
        password=os.environ.get("BC_SERVER_PASSWORD", ""),
        company=os.environ.get("BC_MCP_COMPANY"),
    ).start()
    logger.info(f"BC MCP gateway listening at {gateway.base_url}/mcp (credential-free; path-restricted to /mcp)")
    gateway.warm_up()
    return gateway
