"""Re-resolve existing permitted views and reuse frozen judge edges; no inference."""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bcbench.dataset.codereview import CodeReviewEntry
from tools.review_voting_evidence import RESOLVER_VERSION, aggregate, file_digest, resolve_evidence, validate_votes
from tools.review_voting_pilot import save, score_frozen_edges, summarize_scores


def read(path: Path) -> Any:  # noqa: ANN401 - Historical JSON has per-artifact schemas validated at use sites.
    return json.loads(path.read_text(encoding="utf-8"))


def verify_history(root: Path, manifest: dict[str, Any]) -> None:
    if Path(manifest["root"]).resolve() != root.resolve():
        raise ValueError("Historical manifest root mismatch")
    for name, digest in manifest["artifacts"].items():
        path = root / name
        if not path.resolve().is_relative_to(root.resolve()) or file_digest(path) != digest:
            raise ValueError(f"Historical artifact changed: {name}")


def reanalyze(root: Path, output: Path, hashes: Path) -> dict[str, Any]:
    if output.resolve().is_relative_to(root.resolve()):
        raise ValueError("Corrected analysis must be outside the historical execution root")
    manifest = read(hashes)
    verify_history(root, manifest)
    output.mkdir(parents=True, exist_ok=False)
    selection = read(root / "selection.json")
    results: list[dict[str, Any]] = []
    changes = []
    coverage = []
    for n, instance in enumerate(selection["config"]["cases"], 1):
        case = root / f"case-{n:02}"
        row: dict[str, Any] = {"instance_id": instance, "baseline_completed": (case / "candidates.json").is_file(), "scored": False, "paired": False}
        coverage.append(row)
        if not row["baseline_completed"]:
            row["exclusion"] = "Baseline interrupted; no frozen candidates"
            continue
        candidates = read(case / "candidates.json")
        ids = [c["id"] for c in candidates]
        voters = []
        for number in range(1, 4):
            voter = case / f"voter-{number}"
            if not (voter / "decisions.json").exists():
                voters.append(None)
                continue
            old = read(voter / "decisions.json")
            raw = [item["decision"] for item in old]
            if read(voter / "final.txt") != raw:
                raise ValueError("Persisted decisions differ from the original final response")
            decisions = validate_votes(ids, raw)
            events = [json.loads(line) for line in (voter / "stdout.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
            work = Path(read(voter / "invocation.json")["cwd"])
            resolved = resolve_evidence(decisions, events, work)
            voters.append(resolved)
            save(output / case.name / voter.name / "decisions.json", [item.model_dump(mode="json") for item in resolved])
            for before, after in zip(old, resolved, strict=True):
                changes.append(
                    {
                        "case": case.name,
                        "id": after.decision.id,
                        "voter": number,
                        "raw_verdict": after.decision.verdict,
                        "old_resolution": before["evidence_resolution"],
                        "new_resolution": after.evidence_resolution,
                        "reason": after.reason,
                        "semantic_correctness": after.semantic_correctness,
                    }
                )
        try:
            arms = aggregate(ids, voters if candidates else [])
            row["paired"] = True
        except ValueError as exc:
            arms = {"A": ids}
            row["exclusion"] = str(exc)
        save(output / case.name / "arms.json", arms)
        if not (case / "scores.json").exists():
            row["paired"] = False
            row["exclusion"] = row.get("exclusion", "Scoring never started")
            continue
        entry = CodeReviewEntry.model_validate(read(case / "gold-private.json"))
        if entry.instance_id != instance:
            raise ValueError("Frozen case identity changed")
        scores = score_frozen_edges(entry, candidates, arms, read(case / "judge" / "edges.json"))
        if scores["A"] != read(case / "scores.json")["A"]:
            raise ValueError("Reused baseline score differs from original")
        row["scored"] = True
        save(output / case.name / "scores.json", scores)
        save(output / case.name / "candidate-labels.json", read(case / "candidate-labels.json"))
        results.append({"instance_id": instance, "paired": row["paired"], "arms": scores})
    summary = summarize_scores(results)
    for name, rows in (("full_scored_baseline", results), ("complete_case_paired", [r for r in results if r["paired"]])):
        for arm in ("A",) if name == "full_scored_baseline" else ("A", "B", "C"):
            target = summary[name] if name == "full_scored_baseline" else summary[name][arm]
            target.update({f"macro_{key}": sum(r["arms"][arm][key] for r in rows) / len(rows) if rows else None for key in ("precision", "recall", "f1")})
    verify_history(root, manifest)
    report = {
        "resolver_version": RESOLVER_VERSION,
        "resolver_sha256": file_digest(Path(__file__).with_name("review_voting_evidence.py")),
        "analysis_sha256": file_digest(Path(__file__)),
        "historical_manifest_sha256": file_digest(hashes),
        "historical_artifacts_verified_unchanged": len(manifest["artifacts"]),
        "new_model_calls": 0,
        "new_judge_calls": 0,
        "original_configuration": selection["config"],
        "coverage": coverage,
        "validity_changes": changes,
        "cases": results,
        "summary": summary,
        "denominators": {"selected": 6, "baseline_completed": sum(r["baseline_completed"] for r in coverage), "baseline_scored": len(results), "paired_scored": sum(r["paired"] for r in results)},
        "limitation": "Corrected reference resolution only, not new votes or adjudication. Frozen benchmark judge labels are not unquestionable semantic truth. Interrupted/unstarted cases remain excluded.",
    }
    save(output / "results.json", report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--historical-hashes", type=Path, required=True)
    args = parser.parse_args()
    result = reanalyze(args.root, args.output, args.historical_hashes)
    print(json.dumps({"resolver": RESOLVER_VERSION, "denominators": result["denominators"], "summary": result["summary"]}, indent=2))


if __name__ == "__main__":
    main()
