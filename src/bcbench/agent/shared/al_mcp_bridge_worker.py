from __future__ import annotations

import json
import logging
import socket
import sys
from collections.abc import Callable
from pathlib import Path

import anyio
import uvicorn
from anyio.streams.text import TextReceiveStream
from mcp.client.stdio import StdioServerParameters, get_default_environment
from mcp.server.streamable_http import StreamableHTTPServerTransport
from mcp.shared.message import SessionMessage
from mcp.types import JSONRPCMessage, JSONRPCNotification, JSONRPCRequest
from starlette.responses import Response
from starlette.types import Receive, Scope, Send


async def _wait_until(predicate: Callable[[], bool]) -> None:
    while not predicate():  # noqa: ASYNC110 - these external process/file states do not expose async events
        await anyio.sleep(0.02)


async def serve(config_path: Path) -> None:
    config = json.loads(await anyio.Path(config_path).read_text(encoding="utf-8"))
    parameters = StdioServerParameters.model_validate(config["server"])
    root = config_path.parent
    path = f"/{config['token']}/mcp"
    transport = StreamableHTTPServerTransport(mcp_session_id=config["token"])
    events_connected = anyio.Event()
    stopping = False
    failed = False

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        nonlocal failed
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
        if scope["method"] == "GET":
            events_connected.set()
        try:
            with anyio.fail_after(config["timeout"]):
                await transport.handle_request(scope, receive, send)
        except TimeoutError:
            failed = True
            await transport.terminate()

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
                try:
                    async for message in http_read:
                        if isinstance(message, Exception):
                            raise message
                        await stdin.send((message.message.model_dump_json(by_alias=True, exclude_unset=True) + "\n").encode())
                except (anyio.ClosedResourceError, anyio.BrokenResourceError):
                    if not stopping:
                        raise

            async def from_stdio() -> None:
                buffer = ""
                async for chunk in TextReceiveStream(stdout, encoding="utf-8", errors="strict"):
                    lines = (buffer + chunk).split("\n")
                    buffer = lines.pop()
                    for line in lines:
                        message = JSONRPCMessage.model_validate_json(line)
                        if isinstance(message.root, JSONRPCNotification | JSONRPCRequest):
                            with anyio.fail_after(5):
                                await events_connected.wait()
                        await http_write.send(SessionMessage(message))
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
            tasks.start_soon(server.serve, [listener])
            await _wait_until(lambda: server.started)
            (root / "ready.json").write_text(json.dumps({"url": f"http://127.0.0.1:{port}{path}"}), encoding="utf-8")
            # File existence during a Windows rename is not a signal that the publishing handle closed.
            (root / "ready").touch()
            await _wait_until(lambda: (root / "shutdown").exists() or transport.is_terminated)
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
    if failed:
        raise RuntimeError("AL MCP HTTP transport timed out")


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
