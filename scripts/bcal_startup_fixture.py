"""Once-only actual-package startup control with no external inference path."""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import shutil
import socket
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar, Never
from unittest.mock import patch

import bcal_reasoning_evaluation as evaluation
from bcal_reasoning_coding import ROOT, AdmissionError, CodingPolicy, ProviderBudget, load_module, write_json
from bcal_reasoning_package import load_pin, owner_admission
from bcal_reasoning_smoke import TASK, materialize_symbols


@contextmanager
def loopback_only() -> Iterator[dict]:
    counters = {"blockedExternalConnects": 0}
    connect, connect_ex, resolve = socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo

    def check(host: str) -> None:
        try:
            allowed = host == "localhost" or ipaddress.ip_address(host).is_loopback
        except ValueError:
            allowed = False
        if not allowed:
            counters["blockedExternalConnects"] += 1
            raise AdmissionError("Offline fixture forbids external sockets and DNS.")

    def restricted_connect(client: socket.socket, address: tuple) -> None:
        check(address[0])
        return connect(client, address)

    def restricted_connect_ex(client: socket.socket, address: tuple) -> int:
        check(address[0])
        return connect_ex(client, address)

    def restricted_resolve(host: str, port: int | str | None, family: int = 0, type: int = 0, proto: int = 0, flags: int = 0) -> list:
        check(host)
        return resolve(host, port, family, type, proto, flags)

    with patch.object(socket.socket, "connect", restricted_connect), patch.object(socket.socket, "connect_ex", restricted_connect_ex), patch.object(socket, "getaddrinfo", restricted_resolve):
        yield counters


@contextmanager
def offline_route(policy: CodingPolicy, budget: ProviderBudget, key: str) -> Iterator[str]:
    proxy = load_module("startup_fixture_proxy", ROOT / "src" / "bcbench" / "agent" / "bcal" / "bc_eval_sdk_proxy.py")

    class Response:
        status_code = 400
        headers: ClassVar = {"content-type": "application/json"}

        def iter_bytes(self) -> Iterator[bytes]:
            yield b'{"error":{"message":"Offline initialization boundary stop","type":"fixture"}}'

    requests = 0

    @contextmanager
    def forward(route: str, body: dict) -> Iterator[Response]:
        nonlocal requests
        requests += 1
        budget.observe_route("forward_entered")
        if requests != 1:
            raise proxy.ProxyError("The offline fixture admits one request only.")
        policy.verify_wire(body)
        if not isinstance(body.get("tools"), list) or len(body["tools"]) < 2:
            raise proxy.ProxyError("Production tool catalog unavailable.")
        budget.observe_route("wire_validated")
        yield Response()

    class Handler(proxy._handler(key, policy.model, "responses", forward)):
        def do_GET(self) -> None:
            budget.observe_route("local_get")
            super().do_GET()

        def do_POST(self) -> None:
            budget.observe_route("local_post")
            super().do_POST()

        def _error(self, status: int, message: str) -> None:
            budget.observe_route("proxy_error", status=status)
            budget.fail()
            super()._error(status, message)

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            budget.observe_route("listener_ready")
            yield f"http://127.0.0.1:{server.server_port}"
        finally:
            server.shutdown()
            thread.join()
            budget.observe_route("listener_stopped")


def verify_denial(path: Path) -> dict:
    proof = json.loads(path.read_bytes())
    if not (
        proof.get("status") == "outbound-denial-active"
        and proof.get("allPrograms") is True
        and proof.get("allProtocols") is True
        and proof.get("ipv4NonLoopbackDenied") is True
        and proof.get("ipv6NonLoopbackDenied") is True
        and proof.get("profilesEnabled") is True
        and proof.get("externalTcpProbeBlocked") is True
        and proof.get("loopbackTcpProbeAllowed") is True
        and proof.get("rulesVerified") == 2
    ):
        raise AdmissionError("External network denial is not verified; no fixture child admitted.")
    return proof


def run(args: argparse.Namespace) -> None:
    denial = verify_denial(args.network_proof)
    if any(name.startswith("LLM_API_") or name in {"OPENAI_API_KEY", "AZURE_CLIENT_SECRET"} for name in os.environ):
        raise AdmissionError("Provider credential/configuration environment is forbidden.")
    args.output.mkdir(exist_ok=False)
    write_json(args.output / "execution-once.json", {"source": os.environ["GITHUB_SHA"], "runId": os.environ["GITHUB_RUN_ID"], "fixture": "startup-first400-control"})
    with loopback_only() as network:
        pin = load_pin()
        owner_admission(pin)
        pin.verify(args.package, args.archive)
        args.work.mkdir(exist_ok=False)
        symbols = args.work / "symbols"
        symbol_receipt = materialize_symbols(args.symbol_cache, symbols)
        package = args.work / "worker-0" / "package"
        shutil.copytree(args.package, package)
        pin.verify(package, args.archive)
        cell = "000-gpt-56-reasoning-sol"
        private = args.work / cell
        private.mkdir()
        job = args.work / f"{cell}.job.json"
        write_json(
            job,
            {
                "cell": cell,
                "gold": False,
                "model": evaluation.MODELS[0],
                "instanceId": "synthetic-clamp-priority",
                "prompt": TASK,
                "page": 22,
                "audience": "Technical",
                "project": "smoke",
                "expected": [],
                "safety": False,
            },
        )
        receipt_path = args.output / f"{cell}.json"

        def forbidden_send(_self: ProviderBudget, _role: str, _body: dict, _operation: Callable) -> Never:
            raise AdmissionError("Provider HTTP dispatch is forbidden in this fixture.")

        with patch.object(evaluation, "provider_route", offline_route), patch.object(ProviderBudget, "send", forbidden_send):
            evaluation.run_code(argparse.Namespace(package=package, archive=args.archive, job=job, private=private, receipt=receipt_path, symbols=symbols, study_budget=None))
        pin.verify(package, args.archive)
        pin.verify(args.package, args.archive)
    receipt = json.loads(receipt_path.read_bytes())
    account = receipt["accounting"]
    terminal = receipt["terminalEvidence"]
    stages = account["routeStages"]
    turns = terminal.get("turns", [])
    requests = sum(turn.get("modelRequests", 0) for turn in turns)
    local_requests = stages.get("local_post", 0)
    valid = (
        receipt["providerAttempts"] == 0
        and account["events"] == []
        and receipt["auxiliaryInvocations"] == 0
        and receipt["runtimeCleanupVerified"] is True
        and receipt["processEvidence"]["outcome"] == "nonzero_exit"
        and receipt["processEvidence"]["exitCode"] == 1
        and terminal.get("runtimeModel") == evaluation.MODELS[0]
        and terminal.get("runtimeAppliedEffort") == "medium"
        and len(turns) == 1
        and turns[0].get("terminalState") == "error"
        and requests in (0, 1)
        and local_requests == stages.get("forward_entered", 0) == stages.get("wire_validated", 0) == requests
        and all(turn.get("toolCalls") == 0 for turn in turns)
        and network["blockedExternalConnects"] == 0
        and "authentication_started" not in stages
    )
    write_json(
        args.output / "startup-fixture-summary.json",
        {
            "status": "diagnostic-complete" if valid else "diagnostic-evidence-invalid",
            "benchCommit": os.environ["GITHUB_SHA"],
            "runId": os.environ["GITHUB_RUN_ID"],
            "package": pin.model_dump(),
            "fixture": "first-native-response-is-synthetic400",
            "providerAttempts": receipt["providerAttempts"],
            "judgeCalls": 0,
            "auxiliaryInvocations": receipt["auxiliaryInvocations"],
            "nativeModelRequests": requests,
            "localPosts": local_requests,
            "hostedZeroRequestFailureReproduced": requests == 0 if valid else None,
            "processEvidence": receipt["processEvidence"],
            "terminalEvidence": terminal,
            "validationFailureStage": receipt.get("failureStage"),
            "routeStages": stages,
            "networkDenial": denial,
            "parentSocketGuard": network,
            "packagePayloadUnchanged": True,
            "symbolCount": symbol_receipt["count"],
            "domainPass": False,
            "rawMessagesRetained": False,
            "retries": 0,
        },
    )
    if not valid:
        raise AdmissionError("Offline startup fixture evidence does not meet the diagnostic contract.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("package", "archive", "symbol-cache", "work", "output", "network-proof"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    try:
        run(args)
    except Exception as error:  # noqa: BLE001 - only closed categories may cross the private fixture boundary
        write_json(args.output.parent / "startup-fixture-failure.json", {"status": "diagnostic-stopped", "category": evaluation.failure_category(error), "rawMessageRetained": False})
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
