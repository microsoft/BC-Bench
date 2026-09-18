import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import NotRequired, TypedDict, cast


class _WorkerRequest(TypedDict):
    command: list[str]
    cwd: str
    env: dict[str, str]
    parent_environment_keys: NotRequired[list[str]]


def _load_request(path: Path) -> _WorkerRequest:
    return cast(_WorkerRequest, json.loads(path.read_text(encoding="utf-8")))


def _wait_for_gate(path: Path, timeout_seconds: float) -> None:
    deadline = time.monotonic() + timeout_seconds
    while not path.is_file():
        if time.monotonic() >= deadline:
            raise TimeoutError(f"Launch gate was not created within {timeout_seconds} seconds")
        time.sleep(0.01)


def main(arguments: list[str] | None = None) -> int:
    args = sys.argv[1:] if arguments is None else arguments
    if len(args) != 3:
        raise ValueError("Expected request path, gate path, and startup timeout")

    request = _load_request(Path(args[0]))
    _wait_for_gate(Path(args[1]), float(args[2]))
    sys.stdout.flush()
    sys.stderr.flush()
    process = subprocess.Popen(
        request["command"],
        cwd=Path(request["cwd"]),
        env={**request["env"], **{name: os.environ[name] for name in request.get("parent_environment_keys", [])}},
    )
    return process.wait()


if __name__ == "__main__":
    raise SystemExit(main())
