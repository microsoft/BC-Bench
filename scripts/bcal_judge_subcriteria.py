"""Explicit diagnostic-only subcriteria evaluation; never changes official scores."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from tempfile import TemporaryDirectory


def require(condition: object) -> None:
    if not condition:
        raise ValueError("Invalid diagnostic evidence contract.")


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def valid_hash(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch("[0-9a-f]{64}", value) is not None


def select_specification(job: dict, specification: dict, instance_id: str | None) -> dict:
    if instance_id is None:
        return specification
    require(isinstance(specification, dict) and set(specification) == {"schemaVersion", "cases"} and type(specification["schemaVersion"]) is int and specification["schemaVersion"] == 1)
    require(isinstance(specification["cases"], list))
    ids = set()
    selected = None
    for case in specification["cases"]:
        require(isinstance(case, dict) and set(case) == {"instanceId", "inputSha256", "parents"} and isinstance(case["instanceId"], str) and case["instanceId"] not in ids)
        ids.add(case["instanceId"])
        require(valid_hash(case["inputSha256"]))
        if case["instanceId"] == instance_id:
            require(isinstance(job["input"], str) and case["inputSha256"] == sha256(job["input"].encode("utf-8")))
            selected = {"schemaVersion": 1, "parents": case["parents"]}
    require(selected is not None)
    return selected


def criteria_projection(job: dict, official: dict, specification: dict) -> list[dict]:
    require(
        isinstance(job, dict)
        and set(job) == {"input", "output", "expected"}
        and isinstance(job["input"], str)
        and isinstance(job["output"], str)
        and isinstance(job["expected"], dict)
        and set(job["expected"]) == {"assertions"}
    )
    expected = job["expected"]["assertions"]
    require(
        isinstance(expected, list)
        and bool(expected)
        and all(isinstance(item, dict) and isinstance(item.get("text"), str) for item in expected)
        and isinstance(official, dict)
        and set(official) == {"quality", "testPassed", "assertionPass"}
        and type(official["quality"]) in (int, float)
        and 0 <= official["quality"] <= 1
        and type(official["testPassed"]) is bool
        and isinstance(official["assertionPass"], list)
        and len(official["assertionPass"]) == len(expected)
        and all(type(value) is bool for value in official["assertionPass"])
        and official["quality"] == sum(official["assertionPass"]) / len(expected)
        and official["testPassed"] == all(passed for assertion, passed in zip(expected, official["assertionPass"], strict=True) if assertion.get("level") in {"critical", "expected"})
    )
    require(
        isinstance(specification, dict)
        and set(specification) == {"schemaVersion", "parents"}
        and type(specification["schemaVersion"]) is int
        and specification["schemaVersion"] == 1
        and isinstance(specification["parents"], list)
        and bool(specification["parents"])
    )
    projected = []
    positions = set()
    ids = set()
    texts = set()
    for parent in specification["parents"]:
        require(isinstance(parent, dict) and set(parent) == {"assertionPosition1", "assertionSha256", "subcriteria"})
        position = parent["assertionPosition1"]
        require(type(position) is int and 1 <= position <= len(expected) and position not in positions)
        positions.add(position)
        require(parent["assertionSha256"] == sha256(expected[position - 1]["text"].encode("utf-8")))
        require(isinstance(parent["subcriteria"], list) and len(parent["subcriteria"]) >= 2)
        for criterion in parent["subcriteria"]:
            require(isinstance(criterion, dict) and set(criterion) == {"id", "text"})
            identifier, text = criterion["id"], criterion["text"]
            require(isinstance(identifier, str) and re.fullmatch("[a-z][a-z0-9-]{0,63}", identifier) is not None and identifier not in ids)
            require(isinstance(text, str) and 0 < len(text) <= 2000 and text not in texts)
            ids.add(identifier)
            texts.add(text)
            projected.append(
                {
                    "id": identifier,
                    "text": text,
                    "criterionSha256": sha256(text.encode("utf-8")),
                    "parentAssertionPosition1": position,
                    "parentAssertionSha256": parent["assertionSha256"],
                    "officialParentPassed": official["assertionPass"][position - 1],
                }
            )
    require(len(projected) <= 64)
    return projected


def reference_projection(criteria: list[dict], evidence: dict | None, source_root: Path | None) -> dict[str, dict]:
    projected = {item["id"]: {"available": False, "reason": "not-supplied", "references": []} for item in criteria}
    if evidence is None:
        require(source_root is None)
        return projected
    require(source_root is not None and source_root.is_dir())
    require(
        isinstance(evidence, dict)
        and set(evidence) == {"schemaVersion", "criteria"}
        and type(evidence["schemaVersion"]) is int
        and evidence["schemaVersion"] == 1
        and isinstance(evidence["criteria"], list)
    )
    root = source_root.resolve()
    seen = set()
    for item in evidence["criteria"]:
        require(isinstance(item, dict) and set(item) == {"id", "references"} and item["id"] in projected and item["id"] not in seen)
        seen.add(item["id"])
        require(isinstance(item["references"], list) and 0 < len(item["references"]) <= 16)
        references = []
        for reference in item["references"]:
            require(isinstance(reference, dict) and set(reference) == {"path", "sourceSha256", "startLine", "endLine"})
            relative = reference["path"]
            require(isinstance(relative, str) and bool(relative) and ":" not in relative and not any(ord(char) < 32 for char in relative))
            path = Path(relative)
            require(not path.is_absolute() and not path.drive and ".." not in path.parts and path.suffix.lower() == ".al")
            resolved = (root / path).resolve()
            require(resolved.is_relative_to(root) and resolved.is_file())
            content = resolved.read_bytes()
            require(valid_hash(reference["sourceSha256"]) and sha256(content) == reference["sourceSha256"])
            start, end = reference["startLine"], reference["endLine"]
            require(type(start) is int and type(end) is int and 1 <= start <= end <= len(content.decode("utf-8-sig").splitlines()))
            safe = {
                "sourceSha256": reference["sourceSha256"],
                "startLine": start,
                "endLine": end,
                "verification": "content-and-range-only",
                "relevance": "reviewer-supplied-not-independently-verified",
            }
            require(safe not in references)
            references.append(safe)
        projected[item["id"]] = {"available": True, "references": references}
    return projected


def run(args: argparse.Namespace) -> None:
    from bcal_governed_study import legacy_diagnostic_receipt
    from bcal_study_transport import judge, write_json

    require(not args.output.exists())
    job_bytes, official_bytes = args.input.read_bytes(), args.official_output.read_bytes()
    job, official = json.loads(job_bytes), json.loads(official_bytes)
    specification_bytes = args.subcriteria.read_bytes()
    criteria = criteria_projection(job, official, select_specification(job, json.loads(specification_bytes), getattr(args, "instance_id", None)))
    evidence_bytes = args.source_references.read_bytes() if args.source_references else None
    references = reference_projection(criteria, json.loads(evidence_bytes) if evidence_bytes is not None else None, args.source_root)
    receipt = {
        "schemaVersion": 1,
        "kind": "diagnostic-subcriteria-not-official-scoring",
        "status": "failed",
        "officialScoringUnchanged": True,
        "officialScoresSha256": sha256(official_bytes),
        "privateJudgeInputSha256": sha256(job_bytes),
        "subcriteriaSpecificationSha256": sha256(specification_bytes),
        "instanceIdSha256": sha256(args.instance_id.encode("utf-8")) if getattr(args, "instance_id", None) else None,
        "sourceReferencesSha256": sha256(evidence_bytes) if evidence_bytes is not None else None,
        "criteria": [{key: value for key, value in criterion.items() if key != "text"} | {"verdict": "unavailable", "implementationEvidence": references[criterion["id"]]} for criterion in criteria],
    }
    try:
        with TemporaryDirectory(prefix="private-subcriteria-", dir=args.output.parent) as directory:
            private = Path(directory)
            diagnostic_input, diagnostic_output = private / "input.json", private / "output.json"
            write_json(diagnostic_input, {"input": job["input"], "output": job["output"], "expected": {"assertions": [{"text": item["text"], "level": "expected"} for item in criteria]}})
            try:
                judge(argparse.Namespace(input=diagnostic_input, output=diagnostic_output))
            finally:
                receipt["judgeDiagnostics"] = legacy_diagnostic_receipt(private / "output.diagnostics.json")
            result = json.loads(diagnostic_output.read_bytes())
            require(len(result["assertionPass"]) == len(criteria) and all(type(value) is bool for value in result["assertionPass"]))
            for item, passed in zip(receipt["criteria"], result["assertionPass"], strict=True):
                item["verdict"] = "pass" if passed else "fail"
            receipt["status"] = "completed"
    finally:
        require(args.input.read_bytes() == job_bytes and args.official_output.read_bytes() == official_bytes and args.subcriteria.read_bytes() == specification_bytes)
        require((args.source_references.read_bytes() if args.source_references else None) == evidence_bytes)
        require(reference_projection(criteria, json.loads(evidence_bytes) if evidence_bytes is not None else None, args.source_root) == references)
        write_json(args.output, receipt)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--official-output", type=Path, required=True)
    parser.add_argument("--subcriteria", type=Path, required=True)
    parser.add_argument("--instance-id")
    parser.add_argument("--source-references", type=Path)
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        run(args)
    except Exception as error:  # noqa: BLE001 - exclude private input/path/body at the command boundary
        sys.stderr.write(f"Diagnostic subcriteria failed: {type(error).__name__}\n")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
