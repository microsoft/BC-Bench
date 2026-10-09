import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from bcbench.dataset import NL2ALEntry
from bcbench.types import NL2ALDataset


def read_rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").split("\n") if line.strip()]


def import_bundle(bundle: Path, output: Path) -> dict[str, Any]:
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))

    def read_verified(relative: Path) -> list[dict[str, Any]]:
        key = relative.as_posix()
        hashes = {name.replace("\\", "/"): item["sha256"] for name, item in manifest["files"].items()}
        path = bundle / relative
        if key not in hashes or hashlib.sha256(path.read_bytes()).hexdigest() != hashes[key]:
            raise ValueError(f"Reviewed bundle file hash mismatch: {key}")
        return read_rows(path)

    canonical_path = bundle / "canonical" / "cases.jsonl"
    canonical_sha = hashlib.sha256(canonical_path.read_bytes()).hexdigest()
    if canonical_sha != manifest["canonical_sha256"]:
        raise ValueError("Canonical data does not match the reviewed bundle manifest")
    cases = {row["case_id"]: row for row in read_rows(canonical_path)}
    panels: dict[NL2ALDataset, list[dict[str, Any]]] = {}
    for panel in (NL2ALDataset.GOLD, NL2ALDataset.CHALLENGE):
        rows = read_verified(Path("bcbench") / "single_turn" / f"{panel.value}.jsonl")
        for row in rows:
            case = cases[row["instance_id"]]
            row["metadata"] = {"area": case["area"], "family": case["family"], "tier": case["split"]}
            row["language"] = case["language"]
        panels[panel] = rows
    if len(panels[NL2ALDataset.GOLD]) <= 100:
        raise ValueError("Single-shot gold must contain more than 100 cases")
    scenario_index = json.loads((bundle / "bcal_local" / "index.json").read_text(encoding="utf-8"))
    runnable_ids = set(scenario_index["case_ids"])
    conversations = []
    deferred_conversations = []
    for tier in ("gold", "challenge"):
        for row in read_verified(Path("bcbench") / "future_multiturn" / f"{tier}.jsonl"):
            case = cases[row["instance_id"]]
            turns = [{"prompt": turn["user_prompt"], "intent": turn["intent"], "expected": turn["expected_complete_artifact"]} for turn in row["turns"]]
            checkpoints = [turn["expected"] for turn in turns if turn["intent"] == "customize"]
            if not checkpoints:
                raise ValueError(f"Functional conversation lacks an artifact checkpoint: {row['instance_id']}")
            conversation = {
                    "metadata": {"area": case["area"], "family": case["family"], "tier": tier},
                    "instance_id": row["instance_id"],
                    "created_at": "2026-10-09",
                    "environment_setup_version": row["environment_setup_version"],
                    "project_paths": ["BcalDataset"],
                    "nl_prompt": turns[0]["prompt"],
                    "expected": checkpoints[-1],
                    "page": row["page"],
                    "audience": row["audience"],
                    "language": case["language"],
                    "turns": turns,
            }
            if row["instance_id"] in runnable_ids:
                if any(turn["intent"] != "customize" for turn in turns):
                    raise ValueError(f"Native scenario requires unmapped interactions: {row['instance_id']}")
                conversations.append(conversation)
            else:
                deferred_conversations.append(conversation)
    if {row["instance_id"] for row in conversations} != runnable_ids:
        raise ValueError("Native scenario index does not match the functional conversation export")
    panels[NL2ALDataset.MULTITURN] = conversations
    summary: dict[str, Any] = {"version": manifest["version"], "source_canonical_sha256": canonical_sha, "status": "candidate_not_execution_calibrated", "panels": {}}
    validated = {panel: [NL2ALEntry.model_validate(row) for row in rows] for panel, rows in panels.items()}
    for panel, entries in validated.items():
        if len({entry.instance_id for entry in entries}) != len(entries):
            raise ValueError(f"Duplicate instance IDs in {panel}")
    output.mkdir(parents=True, exist_ok=True)
    for panel, entries in validated.items():
        name = "nl2al.jsonl" if panel is NL2ALDataset.GOLD else f"nl2al_{panel.value}.jsonl"
        data = "".join(json.dumps(entry.model_dump(mode="json", exclude_none=True), ensure_ascii=False) + "\n" for entry in entries).encode("utf-8")
        (output / name).write_bytes(data)
        summary["panels"][panel.value] = {
            "file": name,
            "count": len(entries),
            "sha256": hashlib.sha256(data).hexdigest(),
            "evaluation_scope": "final_artifact" if panel is NL2ALDataset.MULTITURN else "single_turn",
        }
    deferred = [NL2ALEntry.model_validate(row) for row in deferred_conversations]
    deferred_bytes = "".join(json.dumps(entry.model_dump(mode="json", exclude_none=True), ensure_ascii=False) + "\n" for entry in deferred).encode("utf-8")
    (output / "nl2al_multiturn_pending.jsonl").write_bytes(deferred_bytes)
    summary["deferred_multiturn"] = {
        "file": "nl2al_multiturn_pending.jsonl",
        "count": len(deferred),
        "sha256": hashlib.sha256(deferred_bytes).hexdigest(),
        "reason": "Requires explicit active-page context and/or ask_user interaction mappings; not selected by the current runner.",
    }
    (output / "nl2al_manifest.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Import only publishable BC-Bench panels from a reviewed local bundle.")
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--output", type=Path, default=Path("dataset"))
    args = parser.parse_args()
    print(json.dumps(import_bundle(args.bundle, args.output), indent=2))


if __name__ == "__main__":
    main()
