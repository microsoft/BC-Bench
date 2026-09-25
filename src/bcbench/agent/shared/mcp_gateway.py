"""A localhost MCP gateway that fronts the BC MCP endpoint for a benchmarked agent.

Why this exists: the agent must reach BC *only* through the MCP server, never the raw OData ``/api``
or the SQL database. The BC container serves ``/api`` and ``/mcp`` on the same port, so a plain
firewall cannot separate them, and putting the Basic credentials in the agent's MCP config leaks them
onto the agent process command line (recoverable via ``Get-CimInstance Win32_Process``), which the
agent could replay against ``/api``.

This gateway closes both holes: it path-restricts to ``/mcp`` (everything else -> 403) and injects the
Basic auth / Company / ConfigurationName headers itself, so the agent's MCP config carries only a
credential-free ``http://127.0.0.1:<port>/.../mcp`` URL. The upstream endpoint and credentials come
from typed container configuration populated at the CLI boundary.
"""

import base64
import json
import socket
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from http.client import HTTPConnection, HTTPException, IncompleteRead
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import cast
from urllib.parse import urlsplit

from bcbench.exceptions import AgentError
from bcbench.logger import get_logger
from bcbench.types import AgentRuntimeConfig, ContainerConfig

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
# BC composes its MCP tool catalog on the first tools/list of a session; on a cold container it is slow
# (~45s) and sometimes drops the connection, so a single warm-up attempt often fails. Retry each
# handshake (bounded per attempt) until BC returns the catalog or the total budget is spent. The budget
# is generous because a cold insider-29 container can take several minutes to compose the catalog.
_PROBE_TIMEOUT_SECONDS = 120
_WARMUP_BUDGET_SECONDS = 600
_WARMUP_RETRY_DELAY_SECONDS = 5


class _WarmupStageError(Exception):
    pass


class _ClientDisconnected(Exception):
    pass


def _remaining_seconds(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("warm-up deadline expired")
    return remaining


@contextmanager
def _probe_connection(host: str, port: int, deadline: float) -> Iterator[HTTPConnection]:
    connection = HTTPConnection(host, port, timeout=_remaining_seconds(deadline))
    timer: threading.Timer | None = None
    expired = threading.Event()
    try:
        connection.connect()
        probe_socket = connection.sock
        assert probe_socket is not None
        remaining = _remaining_seconds(deadline)
        probe_socket.settimeout(remaining)

        def interrupt() -> None:
            expired.set()
            with suppress(OSError):  # The response may have already closed the socket.
                probe_socket.shutdown(socket.SHUT_RDWR)

        # A socket timeout alone is an inactivity timeout: trickled headers, JSON, or an incomplete
        # SSE line can otherwise keep a blocking read alive indefinitely. Interrupt that same socket
        # at the absolute deadline, even if HTTPConnection has handed ownership to HTTPResponse.
        timer = threading.Timer(remaining, interrupt)
        timer.daemon = True
        timer.start()
        try:
            yield connection
            _remaining_seconds(deadline)
        except (OSError, HTTPException) as exc:
            if expired.is_set() or time.monotonic() >= deadline:
                raise TimeoutError("warm-up deadline expired") from exc
            raise
    finally:
        if timer is not None:
            timer.cancel()
            timer.join()
        connection.close()


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
        while True:
            _remaining_seconds(deadline)
            raw_line = response.readline()
            _remaining_seconds(deadline)
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
    _remaining_seconds(deadline)
    text = response.read().decode("utf-8", errors="replace")
    _remaining_seconds(deadline)
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

    def _rpc(
        self, host: str, port: int, extra_headers: dict[str, str], method: str, params: dict | None, *, deadline: float, request_id: int | None = None, session_id: str | None = None
    ) -> tuple[str | None, dict]:
        started = time.monotonic()
        try:
            payload: dict[str, object] = {"jsonrpc": "2.0", "method": method}
            if request_id is not None:
                payload["id"] = request_id
            if params is not None:
                payload["params"] = params
            headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream", **extra_headers}
            if session_id:
                headers["Mcp-Session-Id"] = session_id
            with _probe_connection(host, port, deadline) as connection:
                connection.request("POST", self._mcp_path, body=json.dumps(payload).encode(), headers=headers)
                with connection.getresponse() as response:
                    returned_session = response.getheader("Mcp-Session-Id")
                    result = _read_jsonrpc(response, deadline=deadline)
        except Exception as exc:
            raise _WarmupStageError(f"{method} failed after {time.monotonic() - started:.1f}s ({type(exc).__name__}: {exc})") from exc
        else:
            return returned_session, result

    def _handshake_tools(self, deadline: float) -> list[str]:
        """initialize -> notifications/initialized -> tools/list against BC; caches the tools/list result."""
        session_id, _ = self._rpc(
            self._origin_host,
            self._origin_port,
            self._injected_headers,
            "initialize",
            {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "bcbench-probe", "version": "1.0"}},
            deadline=deadline,
            request_id=1,
        )
        if session_id:
            self._rpc(self._origin_host, self._origin_port, self._injected_headers, "notifications/initialized", None, deadline=deadline, session_id=session_id)
        _, listed = self._rpc(self._origin_host, self._origin_port, self._injected_headers, "tools/list", {}, deadline=deadline, request_id=2, session_id=session_id)
        result = listed.get("result")
        tools = [name for t in (result or {}).get("tools", []) if isinstance(t, dict) and isinstance(name := t.get("name"), str)]
        if tools and isinstance(result, dict):
            with self._lock:
                self._cached_tools_result = result
        return tools

    def warm_up(self) -> list[str]:
        """Prime BC's tool catalog and cache the tools/list result before the agent connects.

        BC composes the tool catalog on the first tools/list of a session (slow, ~45s, sometimes dropped
        by the server), which can blow past the agent's MCP startup timeout so it registers zero tools.
        The agent's client only calls tools/list once at session init, so if that first call misses, the
        tools never register and the agent flails. Retry the handshake until BC returns the catalog (or
        the budget is spent) so the cache is populated before the agent starts and its tools/list is
        served instantly. Best-effort: never raises -- a failed warm-up must not break a run.
        """
        started = time.monotonic()
        deadline = started + _WARMUP_BUDGET_SECONDS
        attempt = 0
        failure = "tools/list never returned tools"
        while time.monotonic() < deadline:
            attempt += 1
            try:
                tools = self._handshake_tools(min(deadline, time.monotonic() + _PROBE_TIMEOUT_SECONDS))
            except Exception as exc:
                failure = str(exc)
                cause = exc.__cause__ if isinstance(exc, _WarmupStageError) else exc
                if not isinstance(cause, (OSError, HTTPException)):
                    logger.exception(f"BC MCP warm-up attempt {attempt} failed unexpectedly (non-fatal)")
                tools = []
            else:
                failure = "tools/list never returned tools"
            if tools:
                logger.info(f"BC MCP warm-up: cached {len(tools)} tool(s) on attempt {attempt} after {time.monotonic() - started:.1f}s: {tools}")
                return tools
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            delay = min(_WARMUP_RETRY_DELAY_SECONDS, remaining)
            logger.info(f"BC MCP warm-up attempt {attempt} after {time.monotonic() - started:.1f}s: {failure}; retrying in {delay:.1f}s if budget remains")
            time.sleep(delay)
        logger.warning(f"BC MCP warm-up gave up after {attempt} attempt(s) and {time.monotonic() - started:.1f}s: {failure}")
        return []


def _build_handler(gateway: BcMcpGateway) -> type[BaseHTTPRequestHandler]:
    class _ProxyHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def __init__(self, request: socket.socket, client_address: tuple[str, int], server: ThreadingHTTPServer) -> None:
            try:
                super().__init__(request, client_address, server)
            except (ConnectionResetError, BrokenPipeError, _ClientDisconnected) as exc:
                self.close_connection = True
                logger.debug(f"BC MCP gateway client disconnected: {exc}")

        def _write(self, data: bytes) -> None:
            try:
                self.wfile.write(data)
            except (ConnectionResetError, BrokenPipeError) as exc:
                raise _ClientDisconnected(str(exc)) from exc

        def _flush(self) -> None:
            try:
                self.wfile.flush()
            except (ConnectionResetError, BrokenPipeError) as exc:
                raise _ClientDisconnected(str(exc)) from exc

        def end_headers(self) -> None:
            self._response_started = True
            try:
                super().end_headers()
            except (ConnectionResetError, BrokenPipeError) as exc:
                raise _ClientDisconnected(str(exc)) from exc

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
                with response:
                    if rpc_method == "initialize" and response.status == 200 and "text/event-stream" in (response.getheader("Content-Type", "") or ""):
                        self._relay_initialize(response)
                    else:
                        self._relay(response)
            except (OSError, HTTPException):
                logger.exception(f"BC MCP gateway upstream failure during {self.command} {rpc_method or self.path}")
                self.close_connection = True
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
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Content-Length", str(len(event)))
            self.end_headers()
            self._write(event)
            self._flush()
            return True

        def _relay_initialize(self, response) -> None:  # noqa: ANN001 - http.client.HTTPResponse
            """Relay the initialize SSE reply but strip capabilities.experimental from the result.

            BC advertises ``capabilities.experimental = {"x-ms-headerless": true}``; Claude's MCP client
            fails the connection when it sees it (bisected against a replica of BC's exact initialize
            response). Rewrite just that first result event, then keep relaying faithfully so the stream
            behaves exactly like BC's for everything else.
            """
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
                self._write(b"%X\r\n" % len(out_line))
                self._write(out_line)
                self._write(b"\r\n")
                self._flush()
            else:
                raise TimeoutError("upstream initialize stream deadline expired")
            # Keep relaying (holding the stream open) exactly like BC until the upstream or client closes.
            self._write(b"0\r\n\r\n")
            self._flush()

        def _relay(self, response) -> None:  # noqa: ANN001 - http.client.HTTPResponse
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
                # Parse first, then emit the re-serialised int: the raw value skips the _header_safe
                # check above, and an unparsable length must fail before any bytes reach the client.
                remaining = int(content_length)
                self.send_header("Content-Length", str(remaining))
                self.end_headers()
                while remaining > 0:
                    chunk = response.read(min(_STREAM_CHUNK_BYTES, remaining))
                    if not chunk:
                        raise IncompleteRead(b"", remaining)
                    self._write(chunk)
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
                    self._write(b"%X\r\n" % len(chunk))
                    self._write(chunk)
                    self._write(b"\r\n")
                    self._flush()
                self._write(b"0\r\n\r\n")
            self._flush()

        do_GET = _handle
        do_POST = _handle
        do_DELETE = _handle

    return _ProxyHandler


def start_bc_mcp_gateway(runtime: AgentRuntimeConfig | None) -> BcMcpGateway | None:
    """Start a localhost MCP gateway in front of the BC container, or return None when disabled."""
    if runtime is None or not runtime.bc_mcp:
        return None

    container: ContainerConfig = runtime.container
    gateway = BcMcpGateway(
        upstream_url=cast(str, container.mcp_url),
        username=container.username,
        password=container.password,
        company=container.company,
    ).start()
    logger.info(f"BC MCP gateway listening at {gateway.base_url}/mcp (credential-free; path-restricted to /mcp)")
    gateway.warm_up()
    return gateway
