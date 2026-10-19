"""Frozen-finding verifier v2. CLI validates protected captures without model calls.

Run with ``uv run python -m tools.review_voting_pilot --help``. A policy-aware
capture producer is required: this module never exports raw source into prompts.
The original baseline driver and v1 artifacts remain at their original revision.
"""

import argparse
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any, TypedDict

from bcbench_core.scoring import f1_score, precision_recall

from bcbench.agent.copilot.metrics import parse_output
from bcbench.dataset.codereview import CodeReviewEntry, ReviewComment
from bcbench.evaluate.codereview_judge import judge_verdicts
from bcbench.results.codereview import assign_comment_matches, candidate_comment_pairs
from tools.review_voting_evidence import (
    ADAPTER_VERSION,
    PROMPT_VERSION,
    EvidenceBundle,
    ResolvedDecision,
    check_bundle,
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
    args = [
        cli,
        "--no-auto-update",
        "--no-custom-instructions",
        "--disable-builtin-mcps",
        "--available-tools=none",
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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-dir", type=Path, required=True)
    parser.add_argument("--bundle", type=Path, required=True, help="Trusted policy-filtered capture, not raw file content")
    parser.add_argument("--bundle-sha256", required=True, help="Independently frozen bundle digest")
    arguments = parser.parse_args()
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
