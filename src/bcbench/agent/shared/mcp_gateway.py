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
import os
import threading
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

            request_headers: dict[str, str] = {k: v for k, v in self.headers.items() if k.lower() not in _STRIPPED_REQUEST_HEADERS}
            request_headers["Host"] = f"{gateway._origin_host}:{gateway._origin_port}"
            request_headers.update(gateway._injected_headers)

            connection = HTTPConnection(gateway._origin_host, gateway._origin_port, timeout=_UPSTREAM_TIMEOUT_SECONDS)
            try:
                connection.request(self.command, self.path, body=body, headers=request_headers)
                response = connection.getresponse()
                gateway._note_forwarded()
                self._relay(response)
            except Exception:
                logger.exception("BC MCP gateway failed to reach the upstream endpoint")
                self.send_error(502, "Bad Gateway")
            finally:
                connection.close()

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
                # block so server-sent events reach the agent as they arrive.
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()
                while True:
                    chunk = response.read(_STREAM_CHUNK_BYTES)
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
    return gateway
