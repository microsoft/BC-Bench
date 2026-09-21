from __future__ import annotations

import json
import logging
import socket
import sys
from collections import deque
from collections.abc import AsyncIterator, Callable
from http import HTTPStatus
from pathlib import Path

import anyio
import uvicorn
from anyio.streams.text import TextReceiveStream
from mcp.client.stdio import StdioServerParameters, get_default_environment
from mcp.server.streamable_http import StreamableHTTPServerTransport
from mcp.shared.message import ServerMessageMetadata, SessionMessage
from mcp.types import ErrorData, JSONRPCError, JSONRPCMessage, JSONRPCNotification, JSONRPCRequest, RequestId
from sse_starlette import EventSourceResponse
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import Message, Receive, Scope, Send

_EVENT_BUFFER_SIZE = 256


class _BridgeTransport(StreamableHTTPServerTransport):
    def __init__(self, session_id: str, timeout: int) -> None:
        super().__init__(mcp_session_id=session_id)
        self.timeout = timeout
        self.failure: Exception | None = None
        self._events: deque[tuple[int, float, JSONRPCMessage]] = deque()
        self._event_id = 0
        self._delivered_id = 0
        self._events_changed = anyio.Event()
        self._events_connected = False

    def buffer_event(self, message: JSONRPCMessage) -> None:
        if len(self._events) == _EVENT_BUFFER_SIZE:
            if self._events[0][0] > self._delivered_id:
                raise BufferError("AL MCP undelivered event buffer exhausted")
            self._events.popleft()
        self._event_id += 1
        self._events.append((self._event_id, anyio.current_time(), message))
        self._events_changed.set()
        self._events_changed = anyio.Event()

    async def watch_event_deadlines(self) -> None:
        def expired() -> bool:
            return any(event_id > self._delivered_id and anyio.current_time() - created >= self.timeout for event_id, created, _ in self._events)

        await _wait_until(expired)
        raise TimeoutError("AL MCP server event delivery timed out")

    async def _handle_get_request(self, request: Request, send: Send) -> None:
        if not await self._validate_request_headers(request, send):
            return
        if not self._check_accept_headers(request)[1]:
            await self._create_error_response("Client must accept text/event-stream", HTTPStatus.NOT_ACCEPTABLE)(request.scope, request.receive, send)
            return
        if self._events_connected:
            await self._create_error_response("Only one SSE stream is allowed", HTTPStatus.CONFLICT)(request.scope, request.receive, send)
            return
        try:
            cursor = int(request.headers.get("last-event-id", str(self._delivered_id)))
        except ValueError:
            await self._create_error_response("Invalid event cursor", HTTPStatus.BAD_REQUEST)(request.scope, request.receive, send)
            return
        oldest_cursor = self._events[0][0] - 1 if self._events else 0
        if not oldest_cursor <= cursor <= self._event_id:
            await self._create_error_response("Event cursor expired or unknown", HTTPStatus.CONFLICT)(request.scope, request.receive, send)
            return
        self._events_connected = True

        async def events() -> AsyncIterator[dict[str, str]]:
            nonlocal cursor
            while not self.is_terminated:
                if self._events and cursor < self._events[0][0] - 1:
                    raise RuntimeError("AL MCP event history expired during replay")
                changed = self._events_changed
                event = next((event for event in self._events if event[0] > cursor), None)
                if event is None:
                    await changed.wait()
                else:
                    event_id, _, message = event
                    yield {"id": str(event_id), "event": "message", "data": message.model_dump_json(by_alias=True, exclude_unset=True)}
                    cursor = event_id
                    self._delivered_id = max(self._delivered_id, event_id)

        try:
            await EventSourceResponse(events(), headers={"Mcp-Session-Id": str(self.mcp_session_id)}, send_timeout=self.timeout)(request.scope, request.receive, send)
        finally:
            self._events_connected = False

    async def _handle_post_request(self, scope: Scope, request: Request, receive: Receive, send: Send) -> None:
        try:
            with anyio.fail_after(self.timeout):
                payload = json.loads(await request.body())
        except ValueError:
            payload = None
        request_id = payload.get("id") if isinstance(payload, dict) and "method" in payload else None
        if not isinstance(request_id, str | int):
            with anyio.fail_after(self.timeout):
                await super()._handle_post_request(scope, request, receive, send)
            return
        started = False
        completed = False
        sse_start: Message | None = None

        async def fail_response(status: HTTPStatus) -> None:
            error = JSONRPCError(jsonrpc="2.0", id=request_id, error=ErrorData(code=-32603, message="AL MCP upstream transport failed"))
            body = error.model_dump_json().encode()
            if not started:
                await Response(body, status_code=status, media_type="application/json")(scope, receive, send)
            else:
                await send({"type": "http.response.body", "body": b"event: message\r\ndata: " + body + b"\r\n\r\n", "more_body": False})

        async def checked_send(message: Message) -> None:
            nonlocal started, completed, sse_start
            if message["type"] == "http.response.start" and message["status"] == 200:
                sse_start = message
                return
            if sse_start is not None and message["type"] == "http.response.body":
                for line in message.get("body", b"").splitlines():
                    if line.startswith(b"data:"):
                        data = json.loads(line[5:])
                        completed |= data.get("id") == request_id and ("result" in data or "error" in data)
                if not message.get("more_body", False) and not completed:
                    self.failure = RuntimeError("AL MCP response stream closed without a response")
                    await fail_response(HTTPStatus.BAD_GATEWAY)
                    return
                if not started:
                    await send(sse_start)
                    started = True
            elif message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            with anyio.fail_after(self.timeout):
                await super()._handle_post_request(scope, request, receive, checked_send)
        except TimeoutError as error:
            self.failure = error
            with anyio.fail_after(1):
                await fail_response(HTTPStatus.GATEWAY_TIMEOUT)

    async def terminate(self) -> None:
        await super().terminate()
        self._events_changed.set()


async def _wait_until(predicate: Callable[[], bool]) -> None:
    while not predicate():  # noqa: ASYNC110 - these external process/file states do not expose async events
        await anyio.sleep(0.02)


async def serve(config_path: Path) -> None:
    config = json.loads(await anyio.Path(config_path).read_text(encoding="utf-8"))
    parameters = StdioServerParameters.model_validate(config["server"])
    root = config_path.parent
    path = f"/{config['token']}/mcp"
    transport = _BridgeTransport(config["token"], config["timeout"])
    stopping = False
    initializing_request: RequestId | None = None

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        headers = dict(scope["headers"])
        if scope["path"] != path or scope["query_string"]:
            await Response(status_code=404)(scope, receive, send)
            return
        if headers.get(b"host") != f"127.0.0.1:{port}".encode():
            await Response(status_code=421)(scope, receive, send)
            return
        if b"origin" in headers:
            await Response(status_code=403)(scope, receive, send)
            return
        try:
            await transport.handle_request(scope, receive, send)
        except Exception as error:
            transport.failure = error
            await transport.terminate()
            raise

    with socket.socket() as listener, (root / "server-stderr.txt").open("w", encoding="utf-8") as stderr:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        listener.listen()
        server = uvicorn.Server(uvicorn.Config(app, lifespan="off", access_log=False, log_config=None, timeout_graceful_shutdown=2))
        async with (
            await anyio.open_process(
                [parameters.command, *parameters.args],
                env={**get_default_environment(), **(parameters.env or {})},
                cwd=parameters.cwd,
                stderr=stderr,
            ) as process,
            transport.connect() as (http_read, http_write),
            anyio.create_task_group() as tasks,
        ):
            if process.stdin is None or process.stdout is None:
                raise RuntimeError("AL MCP stdio pipes unavailable")
            stdin, stdout = process.stdin, process.stdout

            async def to_stdio() -> None:
                nonlocal initializing_request
                try:
                    async for message in http_read:
                        if isinstance(message, Exception):
                            raise message
                        if isinstance(message.message.root, JSONRPCRequest) and message.message.root.method == "initialize":
                            initializing_request = message.message.root.id
                        with anyio.fail_after(config["timeout"]):
                            await stdin.send((message.message.model_dump_json(by_alias=True, exclude_unset=True) + "\n").encode())
                except (anyio.ClosedResourceError, anyio.BrokenResourceError):
                    if not stopping:
                        raise

            async def from_stdio() -> None:
                nonlocal initializing_request
                buffer = ""
                async for chunk in TextReceiveStream(stdout, encoding="utf-8", errors="strict"):
                    lines = (buffer + chunk).split("\n")
                    buffer = lines.pop()
                    for line in lines:
                        message = JSONRPCMessage.model_validate_json(line)
                        metadata = None
                        if isinstance(message.root, JSONRPCNotification | JSONRPCRequest):
                            if initializing_request is None:
                                transport.buffer_event(message)
                                continue
                            metadata = ServerMessageMetadata(related_request_id=initializing_request)
                        elif message.root.id == initializing_request:
                            initializing_request = None
                        with anyio.fail_after(config["timeout"]):
                            await http_write.send(SessionMessage(message, metadata))
                if not stopping:
                    raise RuntimeError("AL MCP stdio transport closed unexpectedly")

            async def watch_process() -> None:
                # Process.wait can wait for inherited pipes after the server itself has exited.
                await _wait_until(lambda: process.returncode is not None)
                if not stopping:
                    raise RuntimeError("AL MCP server exited unexpectedly")

            tasks.start_soon(to_stdio)
            tasks.start_soon(from_stdio)
            tasks.start_soon(watch_process)
            tasks.start_soon(transport.watch_event_deadlines)
            tasks.start_soon(server.serve, [listener])
            await _wait_until(lambda: server.started)
            (root / "ready.json").write_text(json.dumps({"url": f"http://127.0.0.1:{port}{path}"}), encoding="utf-8")
            # File existence during a Windows rename is not a signal that the publishing handle closed.
            (root / "ready").touch()
            await _wait_until(lambda: (root / "shutdown").exists() or transport.is_terminated or transport.failure is not None)
            stopping = True
            (root / "state.txt").write_text("closing-http")
            await transport.terminate()
            (root / "state.txt").write_text("closing-stdin")
            await stdin.aclose()
            (root / "state.txt").write_text("waiting-server")
            with anyio.move_on_after(2) as graceful:
                await _wait_until(lambda: process.returncode is not None)
            if graceful.cancel_called:
                process.terminate()
                with anyio.fail_after(2):
                    await _wait_until(lambda: process.returncode is not None)
            server.should_exit = True
            (root / "state.txt").write_text("cancelling-transport-tasks")
            tasks.cancel_scope.cancel()
        (root / "state.txt").write_text("stopped")
    if transport.failure is not None:
        raise transport.failure


def main() -> int:
    # Third-party transport diagnostics may contain upstream credentials or arbitrary server payloads.
    logging.disable(logging.CRITICAL)
    try:
        anyio.run(serve, Path(sys.argv[1]))
    except Exception as error:  # noqa: BLE001 - persist only structural diagnostics; raw transport errors may contain credentials

        def kinds(exception: BaseException) -> list[str]:
            if isinstance(exception, BaseExceptionGroup):
                return [kind for child in exception.exceptions for kind in kinds(child)]
            return [type(exception).__name__]

        Path(sys.argv[1]).with_name("failure.json").write_text(json.dumps({"error_types": kinds(error)}), encoding="utf-8")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
