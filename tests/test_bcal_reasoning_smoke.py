import importlib
import io
import json
import subprocess
import sys
import zipfile
from argparse import Namespace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
smoke = importlib.import_module("bcal_reasoning_smoke")


def test_authorized_smoke_has_three_medium_only_single_model_budgets():
    policies = [smoke.smoke_config(model) for model in smoke.MODELS]
    assert len(policies) == 3
    assert sum(policy.max_provider_attempts for policy in policies) == 90
    assert all(policy.max_provider_attempts == 30 and len(policy.policies) == 1 for policy in policies)
    assert all(policy.policies[0].reasoning_effort == "medium" and policy.policies[0].auxiliary == "forbid" for policy in policies)
    assert "gold" not in smoke.TASK.casefold()
    assert "business records" in smoke.TASK


@pytest.mark.parametrize("outcomes", [[0, 0, 0], [1, 0, 1], [1, 1, 1], ["timeout", 0, 0]])
def test_smoke_executes_each_model_once_sequentially_and_counts_failed_attempts(tmp_path, monkeypatch, outcomes):
    from bcbench.agent.bcal import agent

    work, output = tmp_path / "work", tmp_path / "safe"
    work.mkdir()
    output.mkdir()
    monkeypatch.setattr(smoke, "validate_admission", lambda _: {"status": "offline-admitted"})
    calls = []

    def run(command, **kwargs):
        private = Path(command[command.index("--output") + 1])
        model = private.name.removesuffix(".execution")
        index = len(calls)
        assert model == smoke.MODELS[index]
        assert "--execute" in command
        assert kwargs["timeout"] == 480
        calls.append(model)
        private.mkdir()
        failed = outcomes[index] != 0
        events = [{"model": model, "role": "main", "httpStatus": 429 if failed else 200} for _ in range(30 if failed else 4)]
        (private / "receipt.json").write_text(json.dumps({"status": "failed" if failed else "completed"}))
        (private / "provider-attempts.json").write_text(json.dumps({"limit": 30, "attempts": len(events), "events": events}))
        if outcomes[index] == "timeout":
            raise subprocess.TimeoutExpired(command, 480)
        if failed:
            raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(agent, "_run_bcal_process", run)
    args = Namespace(work=work, output=output, package=tmp_path, archive=tmp_path / "package.nupkg")
    smoke.execute(args)
    matrix = json.loads((output / "matrix.json").read_bytes())
    assert calls == list(smoke.MODELS)
    assert matrix["providerAttempts"] == sum(4 if result == 0 else 30 for result in outcomes)
    assert matrix["providerAttempts"] <= 90
    assert matrix["judgeCalls"] == 0
    assert matrix["status"] == ("completed" if all(result == 0 for result in outcomes) else "completed-with-failures")
    with pytest.raises(FileExistsError):
        smoke.execute(args)
    assert len(calls) == 3


@pytest.mark.parametrize("failure", ["overcap", "wrong-model", "missing-ledger"])
def test_smoke_stops_remaining_models_on_untrustworthy_accounting(tmp_path, monkeypatch, failure):
    from bcbench.agent.bcal import agent

    (tmp_path / "work").mkdir()
    (tmp_path / "safe").mkdir()
    monkeypatch.setattr(smoke, "validate_admission", lambda _: {})
    calls = []

    def run(command, **kwargs):
        calls.append(True)
        private = Path(command[command.index("--output") + 1])
        private.mkdir()
        (private / "receipt.json").write_text('{"status":"failed"}')
        if failure != "missing-ledger":
            model = smoke.MODELS[1] if failure == "wrong-model" else smoke.MODELS[0]
            events = [{"model": model, "role": "main"} for _ in range(31 if failure == "overcap" else 1)]
            (private / "provider-attempts.json").write_text(json.dumps({"limit": 30, "attempts": len(events), "events": events}))

    monkeypatch.setattr(agent, "_run_bcal_process", run)
    with pytest.raises(smoke.AdmissionError):
        smoke.execute(Namespace(work=tmp_path / "work", output=tmp_path / "safe", package=tmp_path, archive=tmp_path / "package.nupkg"))
    assert len(calls) == 1
    assert json.loads((tmp_path / "safe" / "matrix.json").read_bytes())["status"] == "infrastructure-failed"


def test_sol_diagnostic_executes_only_one_frozen_arm_with_total_thirty_cap(tmp_path, monkeypatch):
    from bcbench.agent.bcal import agent

    (tmp_path / "work").mkdir()
    (tmp_path / "safe").mkdir()
    monkeypatch.setattr(smoke, "validate_admission", lambda _: {})
    calls = []

    def run(command, **kwargs):
        private = Path(command[command.index("--output") + 1])
        assert private.name == smoke.MODELS[0] + ".execution"
        private.mkdir()
        calls.append(command)
        (private / "receipt.json").write_text('{"status":"failed"}')
        (private / "provider-attempts.json").write_text(
            json.dumps(
                {
                    "limit": 30,
                    "attempts": 1,
                    "events": [{"model": smoke.MODELS[0], "role": "main"}],
                }
            )
        )
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(agent, "_run_bcal_process", run)
    args = Namespace(work=tmp_path / "work", output=tmp_path / "safe", package=tmp_path, archive=tmp_path / "package.nupkg")
    smoke.execute(args, (smoke.MODELS[0],))
    matrix = json.loads((args.output / "matrix.json").read_bytes())
    assert len(calls) == len(matrix["models"]) == 1
    assert matrix["totalProviderAttemptCap"] == 30
    assert matrix["providerAttempts"] == 1
    assert matrix["status"] == "completed-with-failures"


def test_materializes_only_exact_frozen_symbol_bytes(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    manifest_path = root / "experiments" / "bcal-sdk-policy" / "symbols.json"
    manifest_path.parent.mkdir(parents=True)
    cache = tmp_path / "cache" / "version"
    cache.mkdir(parents=True)
    files = []
    import hashlib

    for index in range(350):
        name = f"synthetic-{index}.app"
        (cache / name).write_bytes(str(index).encode())
        files.append({"path": name, "bytes": len(str(index)), "sha256": hashlib.sha256(str(index).encode()).hexdigest()})
    manifest_path.write_text(json.dumps({"cacheVersion": "version", "files": files, "setSha256": "synthetic-set"}))
    monkeypatch.setattr(smoke, "ROOT", root)
    monkeypatch.setattr(smoke, "SYMBOL_MANIFEST_SHA", smoke.sha(manifest_path))
    monkeypatch.setattr(smoke, "SYMBOL_PATHS", tuple(row["path"] for row in files[:5]))
    monkeypatch.setattr(smoke, "verify_symbol_closure", lambda _: [])
    result = smoke.materialize_symbols(tmp_path / "cache", tmp_path / "symbols")
    assert result["count"] == len(list((tmp_path / "symbols").glob("*.app"))) == 5
    (cache / "synthetic-1.app").write_bytes(b"wrong")
    with pytest.raises(smoke.AdmissionError, match="payload differs"):
        smoke.materialize_symbols(tmp_path / "cache", tmp_path / "other-symbols")


@pytest.mark.parametrize("dependency", ["valid", "absent", "newer"])
def test_nested_symbol_manifest_dependency_closure_is_verified(tmp_path, dependency):
    system_id = "8874ed3a-0643-4247-9ced-7a7002f7135d"
    with zipfile.ZipFile(tmp_path / "System.app", "w") as archive:
        archive.writestr("NavxManifest.xml", f'<Package><App Id="{system_id}" Version="28.0.0.0"/></Package>')
    dep_id = "missing" if dependency == "absent" else system_id
    version = "29.0.0.0" if dependency == "newer" else "28.0.0.0"
    inner = io.BytesIO()
    with zipfile.ZipFile(inner, "w") as archive:
        archive.writestr(
            "NavxManifest.xml",
            f'<Package><App Id="synthetic" Version="28.0.0.0" Platform="28.0.0.0"><Dependency Id="{dep_id}" MinVersion="{version}"/></App></Package>',
        )
    with zipfile.ZipFile(tmp_path / "Synthetic.app", "w") as archive:
        archive.writestr("readytorunappmanifest.json", json.dumps({"EmbeddedAppFileName": "inner.app"}))
        archive.writestr("inner.app", inner.getvalue())
    if dependency == "valid":
        assert len(smoke.verify_symbol_closure(tmp_path)) == 2
    else:
        with pytest.raises(smoke.AdmissionError, match="dependency"):
            smoke.verify_symbol_closure(tmp_path)
