"""One explicitly authorized reassessment of the preserved engineering smoke."""

import argparse
import json
from pathlib import Path
from typing import Any

from bcbench.evaluate import review_voting as voting
from bcbench.evaluate.review_verification import ResolvedDecision, aggregate

SMOKE_RUN = 39611471920
SMOKE_REVISION = "3ebaaad89884d29fc5d4ad8212aa0434bab988dd"
SUMMARY_SHA256 = "0915c95dd4be67c9b50ea6fe0e2399851de95e05363a3980e7d0aac27356860d"
ARTIFACT_DIGESTS = {
    "voting-summary-smoke": "sha256:0a2f4fec45e1b77d8be01ec87b1247b839985a665f602130076677e21692a93a",
    "voting-entry-synthetic__errh-tryfunction-swallowed-01": "sha256:3c795ef02d08fa622cd0ae589830c14d08165eecefb70bac26e2cfc8f582271f",
    "voting-entry-synthetic__get-clean-01": "sha256:b3f1917fe6bf79d6c4261617040fea73c5836732ddd3fecbb2feaa3c9a880b8b",
}
ALLOWED_CHANGES = {
    ".github/workflows/pr-review-voting.yml",
    "EXPERIMENT.md",
    "src/bcbench/evaluate/review_voting.py",
    "src/bcbench/evaluate/review_voting_gate.py",
    "tests/test_review_voting_gate.py",
}


def check_revision(revision: str) -> dict[str, str]:
    if voting.checked_command(["git", "rev-parse", f"{revision}^"]) != SMOKE_REVISION:
        raise ValueError("Authorization is limited to the immediate gate-only successor of the original smoke")
    changed = set(voting.checked_command(["git", "diff", "--name-only", SMOKE_REVISION, revision]).splitlines())
    if not changed <= ALLOWED_CHANGES:
        raise ValueError("Changes extend beyond the authorized gate, tests and documentation")
    path = "src/bcbench/evaluate/review_voting.py"
    old = voting.checked_command(["git", "show", f"{SMOKE_REVISION}:{path}"])
    new = voting.checked_command(["git", "show", f"{revision}:{path}"])
    gate_only = old.replace(
        'exercised = complete and all(r["candidates"] > 0 for r in rows)',
        'exercised = complete and any(r["candidates"] > 0 for r in rows)',
    ).replace(
        "Smoke has nonempty frozen candidates in BOTH cases so all six voter invocations are exercised",
        "At least one smoke case exercises all three voters; zero-candidate cases need no voters",
    )
    if gate_only != new:
        raise ValueError("Generation, verifier or scoring implementation changed")
    return {
        path: voting.checked_command(["git", "rev-parse", f"{SMOKE_REVISION}:{path}"])
        for path in (
            "src/bcbench/evaluate/review_voting.py",
            "src/bcbench/evaluate/review_verification.py",
            "src/bcbench/agent/pr_review/agent.py",
            "dataset/codereview.jsonl",
        )
    }


def assess_entries(entries: Path) -> list[dict[str, Any]]:
    paths = list(entries.rglob("result.json"))
    rows = [voting.read(path) for path in paths]
    if len(rows) != 2 or {row["instance_id"] for row in rows} != set(voting.SMOKE):
        raise ValueError("Exactly the original two smoke entries are required")
    for path, row in zip(paths, rows, strict=True):
        if row["config"] != voting.config() or not all(row[key] is True for key in ("baseline_complete", "baseline_scored", "paired", "operational_success")) or row["errors"]:
            raise ValueError("Smoke has a configuration, baseline, evidence or scoring failure")
        voting.validate_baseline(path.parent / "baseline")
        candidates = voting.read(path.parent / "candidates.json")
        ids = [candidate["id"] for candidate in candidates]
        if len(ids) != row["candidates"] or set(row["scores"]) != {"A", "B", "C"}:
            raise ValueError("Candidate or scoring artifacts incomplete")
        voters = []
        for n in (1, 2, 3):
            folder = path.parent / f"voter-{n}"
            if not ids:
                if folder.exists():
                    raise ValueError("Zero candidates must not consume verifier calls")
                continue
            decisions = voting.read(folder / "decisions.json")
            voters.append([ResolvedDecision.model_validate_json(json.dumps(value)) for value in decisions])
            if voting.read(folder / "metrics.json")["observed_models"] != [voting.ROOT_MODEL]:
                raise ValueError("Observed verifier model differs")
        if aggregate(ids, voters) != row["arms"]:
            raise ValueError("Recorded arms differ from resolved original votes")
        edges = voting.read(path.parent / "judge/edges.json")
        if any(type(edge["match"]) is not bool for edge in edges):
            raise ValueError("Invalid original judge edge")
        if edges and voting.read(path.parent / "judge/metrics.json")["observed_models"] != [voting.JUDGE]:
            raise ValueError("Observed judge model differs")
    if not any(row["candidates"] > 0 for row in rows):
        raise ValueError("At least one case must exercise all three verifiers")
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--entries", type=Path, required=True)
    parser.add_argument("--run-metadata", type=Path, required=True)
    parser.add_argument("--artifact-metadata", type=Path, required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    code_hashes = check_revision(args.revision)
    run = voting.read(args.run_metadata)
    if (run["id"], run["head_sha"], run["run_attempt"], run["conclusion"], run["path"]) != (SMOKE_RUN, SMOKE_REVISION, 1, "failure", ".github/workflows/pr-review-evaluation.yml"):
        raise ValueError("Original failed smoke run identity differs")
    digests = {item["name"]: item["digest"] for item in voting.read(args.artifact_metadata)["artifacts"]}
    if any(digests.get(name) != digest for name, digest in ARTIFACT_DIGESTS.items()) or voting.file_hash(args.summary) != SUMMARY_SHA256:
        raise ValueError("Original artifact identities differ")
    summary = voting.read(args.summary)
    if summary["smoke_gate_passed"] is not False or summary["selection"]["config"] != voting.config():
        raise ValueError("Original gate status or inference configuration changed")
    rows = assess_entries(args.entries)
    voting.save(
        args.output,
        {
            "assessment": "engineering-gate-v2-user-authorized",
            "decision": "User explicitly approved on 2026-10-21: allow clean zero candidates and launch one full 145-entry run; original failed smoke status is preserved.",
            "original_run": SMOKE_RUN,
            "original_revision": SMOKE_REVISION,
            "revised_revision": args.revision,
            "original_conclusion": "failure",
            "original_summary_sha256": SUMMARY_SHA256,
            "original_artifact_digests": ARTIFACT_DIGESTS,
            "original_code_blob_ids": code_hashes,
            "config_sha256": voting.digest_json(voting.config()),
            "revised_gate_passed": True,
            "baseline_scored": len(rows),
            "nonempty_cases_with_three_valid_voters": sum(row["candidates"] > 0 for row in rows),
            "quality_gate": False,
            "new_smoke_calls": 0,
        },
    )


if __name__ == "__main__":
    main()
