"""One-shot verifier-only smoke for the separately authorized cases03 and06."""

import argparse
import json
import os
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bcbench.dataset.codereview import CodeReviewEntry, ReviewComment
from tools import review_voting_pilot as pilot
from tools.review_voting_evidence import RESOLVER_VERSION, SHARED_ROOTS_PROMPT_VERSION, ResolvedDecision, digest_json, evidence_prompt
from tools.review_voting_paths import filesystem_path
from tools.review_voting_reanalyze import verify_history

CASES = ((3, "synthetic__errh-tryfunction-swallowed-01", 1), (6, "synthetic__get-clean-01", 0))
VERSION = "copy-free-engineering-smoke-v5"


def remaining_slot_guard(previous: Path, output: Path, voter: int) -> None:
    if voter not in (2, 3) or any((root / "case-06" / f"voter-{voter}").exists() for root in (previous, output)):
        raise FileExistsError("Remaining slot already started or not authorized; never retry")


def continuation_binding(previous: Path, corrected: Path) -> dict[str, Any]:
    verify_history(previous, read(corrected / "historical-smoke-hashes.json"))
    outcome = read(previous / "outcome.json")
    if (outcome["status"], outcome["stage"], outcome["verifier_starts"], outcome["returned_calls"]) != ("halted", "case-06/voter-1", 4, 4):
        raise ValueError("Continuation requires exactly the historical four-call halted smoke")
    hashes = {str(path): pilot.sha(path) for path in (previous / "manifest.json", previous / "outcome.json", corrected / "historical-smoke-hashes.json", corrected / "analysis/results.json")}
    for case, voter in (("case-03", 1), ("case-03", 2), ("case-03", 3), ("case-06", 1)):
        folder = previous / case / f"voter-{voter}"
        current_path = corrected / "analysis" / case / f"voter-{voter}" / "decisions.json"
        current = [ResolvedDecision.model_validate_json(json.dumps(d)) for d in read(current_path)]
        raw = read(folder / "final.txt")
        if [d.decision.model_dump(mode="json") for d in current] != raw or any(d.evidence_resolution != "tool_view_matched" or d.resolver_version != RESOLVER_VERSION for d in current):
            raise ValueError("Retained corrected votes do not match raw decisions/current resolver")
        for path in (current_path, folder / "final.txt", folder / "decisions.json", folder / "invocation.json", folder / "stdout.jsonl", folder / "usage.json"):
            hashes[str(path)] = pilot.sha(path)
    return {"previous": str(previous), "corrected": str(corrected), "sha256": hashes}


def prepare_remaining(previous: Path, corrected: Path, output: Path) -> None:
    for voter in (2, 3):
        remaining_slot_guard(previous, output, voter)
    binding = continuation_binding(previous, corrected)
    old = read(previous / "manifest.json")
    prepare(Path(old["historical_root"]), output)
    manifest = read(output / "manifest.json")
    if digest_json(manifest["guards"]) != digest_json(old["guards"]) or manifest["prompt_sha256"] != old["prompt_sha256"]:
        raise ValueError("Continuation changed frozen inference inputs or prompt")
    manifest.update(
        version="copy-free-remaining-two-v7",
        continuation=binding,
        budget={"baseline": 0, "verifier": 2, "judge": 0, "retries": 0},
        acquisition="Mixed sequence: four retained calls from original smoke, two newly authorized calls; unchanged inference inputs, corrected resolver.",
    )
    pilot.save(output / "manifest.json", manifest)
    pilot.save(output / "prepared.json", {"manifest_sha256": pilot.sha(output / "manifest.json"), "paid_calls": 0})


def read(path: Path) -> Any:  # noqa: ANN401 - Historical JSON artifacts have distinct object and array schemas.
    return json.loads(path.read_text(encoding="utf-8"))


def historical_guards(history: Path) -> dict[str, Any]:
    selection, checkpoint, inputs = [read(history / name) for name in ("selection.json", "checkpoint.json", "inputs.json")]
    if selection["config"] != pilot.load_config():
        raise ValueError("Frozen experiment configuration changed")
    for name, expected in checkpoint["artifact_sha256"].items():
        if pilot.sha(history / name) != expected:
            raise ValueError(f"Historical checkpoint artifact changed: {name}")
    if len(inputs["source_sha256"]) != 6:
        raise ValueError("Checkpoint must bind all six selected inputs")
    origin = Path(read(history / "zero-inference-proof.json")["origin"])
    cases = []
    protected = {name: pilot.sha(history / name) for name in ("selection.json", "checkpoint.json", "inputs.json")}
    for index, instance_id, expected_count in CASES:
        case = history / f"case-{index:02}"
        if selection["config"]["cases"][index - 1] != instance_id:
            raise ValueError("Preselected smoke case mismatch")
        if any((case / f"voter-{n}").exists() for n in (1, 2, 3)) or (case / "judge").exists():
            raise ValueError("Selected historical stage already started; never retry")
        entry = CodeReviewEntry.model_validate(read(case / "gold-private.json"))
        candidates = read(case / "candidates.json")
        reconstructed = [{"id": f"F{n:03}", "comment": ReviewComment.model_validate(c).model_dump(mode="json")} for n, c in enumerate(read(case / "frozen-review.json"), 1)]
        if entry.instance_id != instance_id or len(entry.expected_comments) != expected_count or len(candidates) != 1 or candidates != reconstructed:
            raise ValueError("Frozen sample/candidate metadata mismatch")
        manifest = read(history / f"validation-r2/case-{index:02}/manifest.json")
        if manifest["instance_id"] != instance_id or manifest["base_commit"] != entry.base_commit:
            raise ValueError("Source checkpoint identity mismatch")
        source, knowledge = origin / "prepared" / case.name / "source", history / "knowledge"
        context = {"base_commit": entry.base_commit, "changed_paths": [line[6:].strip() for line in entry.patch.splitlines() if line.startswith("+++ b/")]}
        guards = pilot.shared_root_guards(source, knowledge, context)
        for relative in context["changed_paths"]:
            if filesystem_path(source / relative).stat().st_size != manifest["inventory"][relative]["bytes"]:
                raise ValueError("Changed source size differs from completed checkpoint")
        for name in ("gold-private.json", "candidates.json", "frozen-review.json", "baseline/started.json", "baseline/metrics.json"):
            protected[f"{case.name}/{name}"] = pilot.sha(case / name)
        cases.append(
            {
                "case": case.name,
                "instance_id": instance_id,
                "source": str(source),
                "knowledge": str(knowledge),
                "context": context,
                "candidates": candidates,
                "guards": guards,
                "source_sha256": inputs["source_sha256"][index - 1],
                "knowledge_sha256": inputs["knowledge_sha256"],
            }
        )
    return {
        "selection": selection,
        "cases": cases,
        "protected_sha256": protected,
        "content_checkpoint_utc": checkpoint["content_checkpoint_utc"],
        "provenance": checkpoint["provenance"],
        "interval_change_risk": "Historical content validation, not fresh byte verification. Shallow root/changed-file guards cannot detect every external modification.",
    }


def prepare(history: Path, output: Path) -> None:
    if output.exists():
        raise FileExistsError("Smoke output must be fresh; preserve previous phases")
    guards = historical_guards(history)
    selection = guards["selection"]
    probe = pilot.probe_cli(Path(selection["cli"]["path"]), selection["config"])
    if probe != selection["cli"]:
        raise ValueError("Frozen executable identity changed")
    benchmark = Path(__file__).resolve().parents[1]
    implementation = pilot.implementation_identity(benchmark)
    if implementation["dataset_sha256"] != selection["dataset_sha256"]:
        raise ValueError("Frozen dataset changed")
    output.mkdir(parents=True)
    manifest = {
        "version": VERSION,
        "created_utc": datetime.now(UTC).isoformat(),
        "historical_root": str(history),
        "budget": {"baseline": 0, "verifier": 6, "judge": 0, "retries": 0},
        "guards": guards,
        "implementation": implementation,
        "driver_sha256": pilot.sha(Path(__file__)),
        "prompt_version": SHARED_ROOTS_PROMPT_VERSION,
        "resolver_version": RESOLVER_VERSION,
        "prompt_sha256": digest_json(evidence_prompt(shared_roots=True)),
        "purpose": "Engineering smoke only; no judging or semantic accuracy claim",
    }
    for case in guards["cases"]:
        pilot.prepare_verifier_context(output / case["case"], Path(case["source"]), Path(case["knowledge"]), case["context"], case["candidates"], case["source_sha256"], case["knowledge_sha256"])
    pilot.save(output / "manifest.json", manifest)
    pilot.save(output / "prepared.json", {"manifest_sha256": pilot.sha(output / "manifest.json"), "paid_calls": 0})


def execution_guards(output: Path) -> dict[str, Any]:
    if (output / "execution").exists() or any((output / f"case-{i:02}" / f"voter-{n}").exists() for i, _, _ in CASES for n in (1, 2, 3)):
        raise FileExistsError("Smoke already started; never reset or retry")
    manifest = read(output / "manifest.json")
    if pilot.sha(output / "manifest.json") != read(output / "prepared.json")["manifest_sha256"]:
        raise ValueError("Smoke manifest changed")
    if "continuation" in manifest:
        binding = manifest["continuation"]
        if continuation_binding(Path(binding["previous"]), Path(binding["corrected"])) != binding:
            raise ValueError("Retained votes or correction artifacts changed")
        for voter in (2, 3):
            remaining_slot_guard(Path(binding["previous"]), output, voter)
    if manifest["driver_sha256"] != pilot.sha(Path(__file__)) or manifest["implementation"] != pilot.implementation_identity(Path(__file__).resolve().parents[1]):
        raise ValueError("Smoke implementation changed")
    if digest_json(historical_guards(Path(manifest["historical_root"]))) != digest_json(manifest["guards"]):
        raise ValueError("Historical or shared input guards changed")
    selection = manifest["guards"]["selection"]
    if pilot.probe_cli(Path(selection["cli"]["path"]), selection["config"]) != selection["cli"]:
        raise ValueError("Frozen executable identity changed")
    if not (os.environ.get("COPILOT_GITHUB_TOKEN") or os.environ.get("GH_TOKEN")):
        raise ValueError("Missing credentials; no inference started")
    return manifest


def assess_call(folder: Path, decisions: list[ResolvedDecision]) -> dict[str, Any]:
    events = [json.loads(line) for line in (folder / "stdout.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    tools = sorted({e["data"]["toolName"] for e in events if e.get("type") == "tool.execution_start"})
    models = sorted({e["data"]["model"] for e in events if isinstance(e.get("data", {}).get("model"), str)})
    valid = bool(decisions) and all(d.evidence_resolution == "tool_view_matched" for d in decisions)
    return {
        "valid_decisions": valid,
        "requested_tools": tools,
        "observed_models": models,
        "gate_passed": valid and set(tools) <= {"view", "rg", "glob"},
        "decisions": [d.model_dump(mode="json") for d in decisions],
        "permission_limit": "Available tools and input guards observed; no adversarial path escape or OS ACL sandbox test.",
    }


def execute(output: Path) -> None:
    manifest = execution_guards(output)
    start = pilot.start_once(output / "execution")
    state: dict[str, Any] = {"status": "running", "pid": os.getpid(), "started_utc": datetime.now(UTC).isoformat(), "stage": "entry", "verifier_starts": 0}
    stop = threading.Event()

    def heartbeat() -> None:
        while not stop.is_set():
            pilot.save(output / "heartbeat.json", state | {"utc": datetime.now(UTC).isoformat(), "elapsed_seconds": time.monotonic() - start})
            stop.wait(10)

    thread = threading.Thread(target=heartbeat, daemon=True)
    thread.start()
    results = []
    try:
        for case in manifest["guards"]["cases"]:
            continuation = manifest.get("continuation")
            if continuation and case["case"] != "case-06":
                continue
            for voter in (2, 3) if continuation else (1, 2, 3):
                if continuation:
                    remaining_slot_guard(Path(continuation["previous"]), output, voter)
                if time.monotonic() - start > 3 * 3600:
                    raise TimeoutError("Phase deadline reached; no next invocation")  # noqa: TRY301 - Persist terminal status before re-raising.
                if digest_json(pilot.shared_root_guards(Path(case["source"]), Path(case["knowledge"]), case["context"])) != digest_json(case["guards"]):
                    raise ValueError("Shared inputs changed before next invocation")  # noqa: TRY301 - Persist terminal status before re-raising.
                folder = output / case["case"] / f"voter-{voter}"
                state.update(stage=f"{case['case']}/voter-{voter}", verifier_starts=state["verifier_starts"] + 1)
                pilot.save(output / "heartbeat.json", state | {"utc": datetime.now(UTC).isoformat()})
                print(json.dumps({"event": "verifier-launch", **state}), flush=True)
                decisions = pilot.run_verifier(
                    folder,
                    Path(case["source"]),
                    Path(case["knowledge"]),
                    case["context"],
                    case["candidates"],
                    manifest["guards"]["selection"]["cli"]["path"],
                    read(output / case["case"] / "context-receipt.json"),
                )
                assessment = assess_call(folder, decisions)
                pilot.save(folder / "smoke-assessment.json", assessment)
                results.append({"case": case["case"], "voter": voter, **assessment})
                pilot.save(output / "results.json", {"calls": results, "semantic_scoring": "not performed"})
                print(json.dumps({"event": "verifier-complete", "stage": state["stage"], "gate_passed": assessment["gate_passed"]}), flush=True)
                if not assessment["gate_passed"]:
                    raise ValueError("Live evidence/tool gate failed; stop without retries or further spending")  # noqa: TRY301 - Persist terminal status before re-raising.
        state["status"] = "completed"
    except Exception as exc:
        state.update(status="halted", error_type=type(exc).__name__, reason=str(exc))
        raise
    finally:
        stop.set()
        thread.join(timeout=15)
        pilot.save(
            output / "outcome.json",
            state | {"ended_utc": datetime.now(UTC).isoformat(), "wall_seconds": time.monotonic() - start, "returned_calls": len(results), "baseline_calls": 0, "judge_calls": 0},
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare", action="store_true")
    mode.add_argument("--execute", action="store_true")
    mode.add_argument("--prepare-remaining", type=Path, metavar="PRIOR_SMOKE")
    parser.add_argument("--corrected-analysis", type=Path)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--historical-root", type=Path, default=Path(r"C:\bv3-e900-02"))
    args = parser.parse_args()
    if args.prepare_remaining:
        if args.corrected_analysis is None:
            parser.error("--prepare-remaining requires --corrected-analysis")
        prepare_remaining(args.prepare_remaining.resolve(), args.corrected_analysis.resolve(), args.root.resolve())
    elif args.prepare:
        prepare(args.historical_root.resolve(), args.root.resolve())
    else:
        execute(args.root.resolve())


if __name__ == "__main__":
    main()
