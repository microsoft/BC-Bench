"""One-shot pilot: --root executes; --validate-evidence explicitly validates offline.

Execution requires --captures-dir (default: ROOT/protected-captures) containing
manifest.json mapping case-01..case-06 to independently frozen capture digests.
Each case directory there must contain capture.json (EvidenceCapture schema),
source/ and knowledge/ immutable snapshots. A trusted policy-aware producer must
provide the captured views; none is built in. Never fill captures with raw text
to work around redaction. All six inputs are checked before baseline work.
Snapshots must match the patched target and the engine-pinned filtered knowledge
copy (excluding .git, _review*, _run*, agent-output*). Later mismatches fail closed.
Capture identities exclude unknown baseline candidates; these are hash-bound
into one identical verifier bundle only AFTER the baseline findings are frozen.

Execute: uv run python tools\\review_voting_pilot.py --root ROOT
Validate: uv run python -m tools.review_voting_pilot --validate-evidence
          --case-dir CASE --bundle BUNDLE --bundle-sha256 DIGEST
"""

import argparse
import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, TypedDict

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bcbench_core.scoring import f1_score, precision_recall

from bcbench.agent.copilot.metrics import parse_output
from bcbench.agent.pr_review.agent import get_pr_review_version, run_pr_review_agent
from bcbench.dataset.codereview import CodeReviewEntry, ReviewComment
from bcbench.evaluate.codereview import CodeReviewPipeline
from bcbench.evaluate.codereview_judge import judge_verdicts
from bcbench.results.codereview import assign_comment_matches, candidate_comment_pairs
from bcbench.types import EvaluationCategory
from tools.review_voting_evidence import (
    ADAPTER_VERSION,
    PROMPT_VERSION,
    EvidenceBundle,
    EvidenceCapture,
    ResolvedDecision,
    aggregate,
    check_bundle,
    check_capture,
    digest_json,
    evidence_prompt,
    resolve_evidence,
    validate_votes,
)

MODEL = "gpt-5.6-sol"
JUDGE = "gpt-5.3-codex"


class Candidate(TypedDict):
    id: str
    comment: dict[str, Any]


def save(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def command(args: list[str], cwd: Path | None = None) -> str:
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True, encoding="utf-8", check=False)
    if result.returncode:
        raise RuntimeError(f"Command failed ({result.returncode}): {args}\n{result.stderr}")
    return result.stdout.strip()


def start_once(folder: Path) -> float:
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / "started.json").open("x", encoding="utf-8") as stream:
        json.dump({"started_unix": time.time(), "policy": "one attempt, never retry"}, stream)
    return time.monotonic()


def isolated_environment(home: Path) -> dict[str, str]:
    home.mkdir(parents=True, exist_ok=True)
    env = {key: value for key, value in os.environ.items() if not key.startswith(("COPILOT_", "BCQUALITY_", "GITHUB_", "REVIEW_", "AGENT_", "OTEL_"))}
    token = os.environ.get("COPILOT_GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        raise RuntimeError("Missing COPILOT_GITHUB_TOKEN/GH_TOKEN; no model call attempted")
    env.update(
        HOME=str(home),
        USERPROFILE=str(home),
        COPILOT_HOME=str(home / ".copilot"),
        COPILOT_GITHUB_TOKEN=token,
        GH_TOKEN=token,
        CI="true",
        COPILOT_AUTO_UPDATE="false",
        GIT_TERMINAL_PROMPT="0",
        GIT_AUTHOR_NAME="BC-Bench local pilot",
        GIT_AUTHOR_EMAIL="bcbench-pilot@example.invalid",
        GIT_COMMITTER_NAME="BC-Bench local pilot",
        GIT_COMMITTER_EMAIL="bcbench-pilot@example.invalid",
    )
    return env


def run_verifier(
    folder: Path,
    source: Path,
    knowledge: Path,
    patch: str,
    candidates: list[Candidate],
    cli: str,
    *,
    bundle: EvidenceBundle,
    expected_bundle_sha256: str,
) -> list[ResolvedDecision]:
    check_bundle(bundle, expected_bundle_sha256, source, knowledge, candidates, patch)
    candidate_ids = [c["id"] for c in candidates]
    if len(candidate_ids) != len(set(candidate_ids)):
        raise ValueError("Duplicate candidate IDs")
    if not candidate_ids:
        return []
    if not any(v.tree == "source" and v.status == "available" for v in bundle.views):
        raise ValueError("Source view unavailable/redacted; no model invocation permitted")
    start = start_once(folder)
    work = folder / "work"
    work.mkdir()
    prompt = evidence_prompt(bundle, candidates)
    (folder / "prompt.txt").write_text(prompt, encoding="utf-8")
    save(work / "protected-evidence.json", [{"id": key, **view.model_dump(mode="json")} for key, view in bundle.indexed_views().items()])
    args = [
        cli,
        "--no-auto-update",
        "--no-custom-instructions",
        "--disable-builtin-mcps",
        "--available-tools=view,rg,glob",
        "--allow-all-tools",
        "--no-ask-user",
        "--output-format=json",
        "--model=" + MODEL,
        "--context=default",
        "--usage-output-file",
        str(folder / "usage.json"),
        "--log-dir",
        str(folder / "logs"),
        "--prompt",
        prompt,
    ]
    save(folder / "evidence-bundle.json", bundle.model_dump(mode="json"))
    save(
        folder / "invocation.json",
        {
            "args": args,
            "cwd": str(work),
            "model": MODEL,
            "adapter_version": ADAPTER_VERSION,
            "prompt_version": PROMPT_VERSION,
            "bundle_sha256": expected_bundle_sha256,
            "adapter_sha256": sha(Path(__file__)),
            "evidence_adapter_sha256": sha(Path(__file__).with_name("review_voting_evidence.py")),
        },
    )
    with (folder / "stdout.jsonl").open("w", encoding="utf-8") as out, (folder / "stderr.txt").open("w", encoding="utf-8") as err:
        try:
            completed = subprocess.run(args, cwd=work, env=isolated_environment(folder / "home"), stdout=out, stderr=err, timeout=1800, check=False)
        except (subprocess.TimeoutExpired, OSError) as exc:
            save(folder / "process.json", {"status": "failed", "error_type": type(exc).__name__, "wall_seconds": time.monotonic() - start})
            raise
    save(folder / "process.json", {"exit_code": completed.returncode, "wall_seconds": time.monotonic() - start})
    if completed.returncode:
        raise RuntimeError(f"Verifier failed with exit {completed.returncode}: {folder}")
    metrics, response = parse_output((folder / "stdout.jsonl").read_text(encoding="utf-8").splitlines())
    (folder / "final.txt").write_text(response or "", encoding="utf-8")
    if metrics is not None:
        save(folder / "parsed-metrics.json", metrics.model_dump(mode="json"))
    try:
        decisions = validate_votes(candidate_ids, json.loads(response or ""))
        check_bundle(bundle, expected_bundle_sha256, source, knowledge, candidates, patch)
        resolved = resolve_evidence(decisions, bundle)
    except (ValueError, TypeError, OSError) as exc:
        save(folder / "validation-failure.json", {"status": "failed", "error_type": type(exc).__name__, "reason": str(exc)})
        raise
    save(folder / "decisions.json", [d.model_dump(mode="json") for d in resolved])
    return resolved


def score_arms(entry: CodeReviewEntry, candidates: list[Candidate], arms: dict[str, list[str]], folder: Path) -> dict[str, dict[str, Any]]:
    generated = [ReviewComment.model_validate(c["comment"]) for c in candidates]
    keys = {id(comment): c["id"] for comment, c in zip(generated, candidates, strict=True)}
    expected = candidate_comment_pairs(entry.expected_comments, generated)
    ignored = candidate_comment_pairs(entry.ignored_comments, generated)
    folder.mkdir(parents=True, exist_ok=True)
    if expected or ignored:
        start_once(folder)
    verdicts = judge_verdicts(expected + ignored, folder, model=JUDGE)
    save(
        folder / "edges.json",
        [
            {"gold_bucket": "expected" if n < len(expected) else "ignored", "gold": gold.model_dump(mode="json"), "candidate_id": keys[id(candidate)], "match": match}
            for n, ((gold, candidate), match) in enumerate(zip(expected + ignored, verdicts, strict=True))
        ],
    )
    accepted_expected = [pair for pair, verdict in zip(expected, verdicts[: len(expected)], strict=True) if verdict]
    accepted_ignored = [pair for pair, verdict in zip(ignored, verdicts[len(expected) :], strict=True) if verdict]
    result = {}
    for name, selected in arms.items():
        matches, neutrals = assign_comment_matches(
            [pair for pair in accepted_expected if keys[id(pair[1])] in selected],
            [pair for pair in accepted_ignored if keys[id(pair[1])] in selected],
        )
        precision, recall = precision_recall(len(matches), len(selected) - len(neutrals), len(entry.expected_comments))
        result[name] = {
            "generated": len(selected),
            "expected": len(entry.expected_comments),
            "matched": len(matches),
            "ignored": len(neutrals),
            "false": len(selected) - len(neutrals) - len(matches),
            "missed": len(entry.expected_comments) - len(matches),
            "precision": precision,
            "recall": recall,
            "f1": f1_score(precision, recall),
            "matched_ids": [keys[id(c)] for _, c in matches],
            "ignored_ids": [keys[id(c)] for _, c in neutrals],
        }
    return result


def _load_captures(capture_dir: Path, cases: list[tuple[str, str]]) -> list[EvidenceCapture]:
    manifest = json.loads((capture_dir / "manifest.json").read_text(encoding="utf-8"))
    names = [f"case-{n:02}" for n in range(1, 7)]
    if len(cases) != 6 or not isinstance(manifest, dict) or set(manifest) != set(names):
        raise ValueError("Six complete capture entries required")
    captures = []
    for name, (instance_id, patch) in zip(names, cases, strict=True):
        record = manifest[name]
        if not isinstance(record, dict) or set(record) != {"instance_id", "sha256"} or record["instance_id"] != instance_id:
            raise ValueError(f"Capture selection mismatch: {name}")
        case = capture_dir / name
        capture = EvidenceCapture.model_validate_json((case / "capture.json").read_text(encoding="utf-8"))
        check_capture(capture, record["sha256"], case / "source", case / "knowledge", patch)
        if {v.tree for v in capture.views} != {"source", "knowledge"} or any(v.status != "available" for v in capture.views):
            raise ValueError(f"Protected source/knowledge view unavailable or redacted: {name}")
        captures.append(capture)
    return captures


def preflight_captures(capture_dir: Path, cases: list[tuple[str, str]]) -> list[EvidenceCapture]:
    help_text = (
        f"Protected captures are required before any baseline: {capture_dir}. "
        "Provide manifest.json with exactly case-01..case-06 entries "
        "({instance_id, sha256}) and, for each case, capture.json plus source/ and knowledge/ snapshots. "
        "capture.json must be an EvidenceCapture from a trusted policy-aware capture mechanism. "
        "No supported capture producer is bundled; do not substitute raw text or bypass redaction."
    )
    try:
        captures = _load_captures(capture_dir, cases)
    except (OSError, ValueError, TypeError) as exc:
        raise ValueError(f"{help_text}\nPreflight failed: {exc}") from exc
    return captures


def run(root: Path, benchmark: Path, captures_dir: Path | None = None) -> None:
    selection = json.loads((root / "selection.json").read_text(encoding="utf-8"))
    if len(selection["cases"]) != 6 or len({c["instance_id"] for c in selection["cases"]}) != 6:
        raise ValueError("Exactly six unique frozen cases required")
    if (root / "execution" / "started.json").exists() or any((root / f"case-{n:02}").exists() for n in range(1, 7)):
        raise FileExistsError("One-shot execution requires fresh output paths; historical/partial runs cannot be retried")
    entries_by_id = {e.instance_id: e for e in CodeReviewEntry.load(benchmark / "dataset" / "codereview.jsonl")}
    entries = [entries_by_id[c["instance_id"]] for c in selection["cases"]]
    captures = preflight_captures(captures_dir or root / "protected-captures", [(e.instance_id, e.patch) for e in entries])
    if get_pr_review_version(root / "engine") != selection["engine_commit"]:
        raise ValueError("Engine identity differs from frozen selection")
    if command(["git", "rev-parse", "HEAD"], benchmark) != selection["benchmark_commit"]:
        raise ValueError("Benchmark identity differs from frozen selection")
    cli = shutil.which("copilot.exe") or shutil.which("copilot")
    if cli is None:
        raise RuntimeError("Copilot CLI missing")
    for base in {entry.base_commit for entry in entries}:
        command(["git", "update-ref", f"refs/heads/pilot-base-{base}", base], root / "target-store")
    start = start_once(root / "execution")
    save(
        root / "metadata.json",
        {
            "selection": selection,
            "selection_sha256": sha(root / "selection.json"),
            "dataset_sha256": sha(benchmark / "dataset" / "codereview.jsonl"),
            "adapter_sha256": sha(Path(__file__)),
            "adapter_version": ADAPTER_VERSION,
            "prompt_version": PROMPT_VERSION,
            "evidence_adapter_sha256": sha(Path(__file__).with_name("review_voting_evidence.py")),
            "capture_sha256": [capture.sha256 for capture in captures],
            "cli_path": cli,
            "cli_sha256": sha(Path(cli)),
            "cli_version": command([cli, "--version"]),
            "workflow_cli_pin": "1.0.82",
            "baseline_label": "BC-Bench pinned-engine baseline",
            "observed_leaf_models": None,
            "ci_exact_reproduction": False,
        },
    )
    logging.basicConfig(filename=root / "driver.log", level=logging.DEBUG, encoding="utf-8")
    sources = []
    original_environment = dict(os.environ)
    try:
        for index, entry in enumerate(entries, 1):
            case = root / f"case-{index:02}"
            case.mkdir()
            save(case / "gold-private.json", entry.model_dump(mode="json"))
            source = case / "source"
            command(["git", "clone", "--quiet", "--shared", "--no-checkout", str(root / "target-store"), str(source)])
            command(["git", "config", "core.longpaths", "true"], source)
            command(["git", "checkout", "--quiet", "--detach", entry.base_commit], source)
            CodeReviewPipeline().setup_workspace(entry, source)
            baseline = case / "baseline"
            baseline_start = start_once(baseline)
            os.environ.clear()
            os.environ.update(original_environment)
            os.environ.update(isolated_environment(baseline / "home"))
            metrics, _ = run_pr_review_agent(entry, MODEL, EvaluationCategory.CODE_REVIEW, source, baseline, engine_path=root / "engine")
            save(baseline / "metrics.json", metrics.model_dump(mode="json"))
            save(baseline / "elapsed.json", {"seconds": time.monotonic() - baseline_start})
            raw = json.loads((source / "review.json").read_text(encoding="utf-8"))
            (source / "review.json").replace(case / "frozen-review.json")
            candidates = [{"id": f"F{n:03}", "comment": comment} for n, comment in enumerate(raw, 1)]
            save(case / "candidates.json", candidates)
            save(case / "source-identity.json", {"head": command(["git", "rev-parse", "HEAD"], source), "base": entry.base_commit})
            (case / "frozen.diff").write_text(entry.patch, encoding="utf-8")
            sources.append(source)
            print(f"Baseline {index}/6 complete: {len(candidates)} candidates", flush=True)
        for index, (entry, source, capture) in enumerate(zip(entries, sources, captures, strict=True), 1):
            case = source.parent
            candidates = json.loads((case / "candidates.json").read_text(encoding="utf-8"))
            knowledge = case / "knowledge"
            shutil.copytree(case / "baseline" / "bcquality", knowledge, ignore=shutil.ignore_patterns(".git", "_review*", "_run*", "agent-output*"))
            bundle = EvidenceBundle.model_validate_json(json.dumps(capture.model_dump(mode="json") | {"candidates_sha256": digest_json(candidates)}))
            check_bundle(bundle, bundle.sha256, source, knowledge, candidates, entry.patch)
            save(case / "evidence-bundle.json", bundle.model_dump(mode="json"))
            save(case / "evidence-identity.json", {"capture_sha256": capture.sha256, "bundle_sha256": bundle.sha256})
            voters = (
                [run_verifier(case / f"voter-{voter}", source, knowledge, entry.patch, candidates, cli, bundle=bundle, expected_bundle_sha256=bundle.sha256) for voter in range(1, 4)]
                if candidates
                else []
            )
            save(case / "arms.json", aggregate([c["id"] for c in candidates], voters, bundle))
            print(f"Verification {index}/6 complete; calls={len(voters)}", flush=True)
        results = []
        for entry, source in zip(entries, sources, strict=True):
            case = source.parent
            os.environ.clear()
            os.environ.update(original_environment)
            os.environ.update(isolated_environment(case / "judge-home"))
            scores = score_arms(entry, json.loads((case / "candidates.json").read_text()), json.loads((case / "arms.json").read_text()), case / "judge")
            save(case / "scores.json", scores)
            results.append({"instance_id": entry.instance_id, "arms": scores})
        save(root / "results.json", {"cases": results, "total_wall_seconds": time.monotonic() - start})
    except Exception as exc:
        save(root / "failure.json", {"type": type(exc).__name__, "message": str(exc), "unix": time.time()})
        raise
    finally:
        os.environ.clear()
        os.environ.update(original_environment)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, help="Execute the original bounded pilot (protected captures required)")
    parser.add_argument("--captures-dir", type=Path, help="Default: ROOT/protected-captures; validated before baseline work")
    parser.add_argument("--validate-evidence", action="store_true", help="Explicit offline-only mode; no model calls")
    parser.add_argument("--case-dir", type=Path)
    parser.add_argument("--bundle", type=Path, help="Trusted policy-filtered capture bundle, not raw file content")
    parser.add_argument("--bundle-sha256", help="Independently frozen bundle digest")
    arguments = parser.parse_args(argv)
    if not arguments.validate_evidence:
        if arguments.root is None or any((arguments.case_dir, arguments.bundle, arguments.bundle_sha256)):
            parser.error("Execution requires --root; offline options require explicit --validate-evidence")
        run(arguments.root.resolve(), Path(__file__).resolve().parents[1], arguments.captures_dir)
        return
    if arguments.root or arguments.captures_dir or not all((arguments.case_dir, arguments.bundle, arguments.bundle_sha256)):
        parser.error("--validate-evidence requires --case-dir, --bundle and --bundle-sha256, without execution options")
    case = arguments.case_dir
    check_bundle(
        EvidenceBundle.model_validate_json(arguments.bundle.read_text(encoding="utf-8")),
        arguments.bundle_sha256,
        case / "source",
        case / "knowledge",
        json.loads((case / "candidates.json").read_text(encoding="utf-8")),
        (case / "frozen.diff").read_text(encoding="utf-8"),
    )
    print("Evidence identities valid; semantic correctness and source visibility are not certified.")


if __name__ == "__main__":
    main()
