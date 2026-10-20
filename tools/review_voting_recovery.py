"""Offline recovery of the specific, proven pre-inference v3 preparation failure."""

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from bcbench.dataset.codereview import CodeReviewEntry
from tools import review_voting_pilot as pilot
from tools.review_voting_paths import copy_tree, snapshot_inventory, validate_inventory


def prove_no_inference(root: Path) -> dict[str, Any]:
    marker = root / "execution" / "started.json"
    marker.stat()
    for entry in root.iterdir():
        if entry.name.startswith("case-"):
            children = sorted(child.name for child in entry.iterdir())
            if children != ["source"]:
                raise ValueError(f"Unexpected inference or execution artifact: {entry.name}/{children}")
    if (root / "results.json").exists():
        raise ValueError("An execution result exists; continuation is not permitted")
    return {
        "origin": str(root),
        "execution_marker_sha256": pilot.sha(marker),
        "baseline_invocations": 0,
        "verifier_invocations": 0,
        "judge_invocations": 0,
        "basis": "No baseline/voter/judge directories or outputs; only the pre-baseline partial source directory exists.",
    }


def expected_source_inventory(source: Path, entry: CodeReviewEntry, scratch: Path) -> dict[str, str]:
    if entry.project_paths:
        raise ValueError("Independent recovery does not support project-path setup transformations")
    scratch.mkdir(parents=True)
    objects = scratch / "objects"
    objects.mkdir()
    old_objects = pilot.command(["git", "rev-parse", "--path-format=absolute", "--git-path", "objects"], source)
    env = dict(os.environ)
    env.update(GIT_INDEX_FILE=str(scratch / "index"), GIT_OBJECT_DIRECTORY=str(objects), GIT_ALTERNATE_OBJECT_DIRECTORIES=old_objects)

    def git(*args: str, patch: bytes | None = None) -> bytes:
        result = subprocess.run(["git", "-c", "core.longpaths=true", *args], cwd=source, env=env, input=patch, capture_output=True, check=False)
        if result.returncode:
            raise RuntimeError(f"Independent Git inventory failed: {args}, exit {result.returncode}")
        return result.stdout

    git("read-tree", entry.base_commit)
    # Match bcbench_core.git.apply_patch's native text-file serialization exactly.
    patch_file = scratch / "dataset.patch"
    patch_file.write_text(entry.patch, encoding="utf-8")
    git("apply", "--cached", "--whitespace=nowarn", "--ignore-whitespace", str(patch_file))
    records = git("ls-files", "--stage", "-z").decode("utf-8").rstrip("\0").split("\0")
    expected = {}
    for record in records:
        metadata, path = record.split("\t", 1)
        mode, blob, stage = metadata.split()
        if mode not in ("100644", "100755") or stage != "0" or path in expected:
            raise ValueError(f"Unsupported Git inventory entry: {path}")
        expected[path] = blob
    return expected


def verify_knowledge(origin: Path, root: Path, config: dict[str, Any]) -> dict[str, Any]:
    reference = root / "validation" / "knowledge-reference"
    pilot.command(["git", "clone", "--quiet", "--shared", "--no-checkout", str(origin / "knowledge"), str(reference)])
    pilot.command(["git", "config", "core.longpaths", "true"], reference)
    pilot.command(["git", "checkout", "--quiet", "--detach", config["bcquality_sha"]], reference)
    scripts = root / "engine" / "agents" / "ALReviewAgent" / "scripts"

    def quote(path: Path) -> str:
        return str(path).replace("'", "''")

    env = {key: value for key, value in os.environ.items() if not key.startswith("BCQUALITY_")}
    result = subprocess.run(
        [
            "pwsh",
            "-NoProfile",
            "-Command",
            (
                f"$ErrorActionPreference='Stop'; $cfg=& '{quote(scripts / 'Get-BCQualityConfig.ps1')}'; "
                f"& '{quote(scripts / 'Invoke-BCQualityFilter.ps1')}' -BCQualityRoot '{quote(reference)}' -Config $cfg | Out-Null"
            ),
        ],
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if result.returncode:
        raise RuntimeError(f"Pinned knowledge filter failed: {result.stderr}")
    expected, actual = snapshot_inventory(reference), snapshot_inventory(origin / "knowledge")
    if set(actual) != set(expected):
        raise ValueError("Filtered knowledge path inventory differs from pinned checkout/filter")
    generated = {"_filter-report.json": "bcqualityRoot", "_skill-index.json": "generatedAt"}
    canonical = {}
    for path, record in expected.items():
        if path not in generated:
            if record != actual[path]:
                raise ValueError(f"Pinned knowledge content mismatch: {path}")
            continue
        original = json.loads((origin / "knowledge" / path).read_text(encoding="utf-8-sig"))
        rebuilt = json.loads((reference / path).read_text(encoding="utf-8-sig"))
        dynamic_field = generated[path]
        if dynamic_field not in original or dynamic_field not in rebuilt:
            raise ValueError(f"Missing declared generated field: {path}/{dynamic_field}")
        original.pop(dynamic_field)
        rebuilt.pop(dynamic_field)
        if original != rebuilt:
            raise ValueError(f"Pinned knowledge generated semantics mismatch: {path}")
        canonical[path] = {"excluded_dynamic_field": dynamic_field, "canonical_sha256": pilot.digest_json(original)}
    return {"inventory": actual, "generated_comparisons": canonical, "reference_inventory": expected}


def prepare_continuation(origin: Path, root: Path, benchmark: Path) -> None:
    proof = prove_no_inference(origin)
    selection = json.loads((origin / "selection.json").read_text(encoding="utf-8"))
    config = pilot.load_config()
    identity = pilot.implementation_identity(benchmark)
    if selection["config"] != config or any(selection[key] != identity[key] for key in ("dataset_sha256", "config_sha256", "shared_config_sha256")):
        raise ValueError("Frozen input configuration changed; continuation refused")
    if pilot.probe_cli(Path(selection["cli"]["path"]), config) != selection["cli"]:
        raise ValueError("Frozen executable changed; continuation refused")
    if pilot.get_pr_review_version(origin / "engine") != config["engine_sha"]:
        raise ValueError("Original engine is not clean at its frozen pin")
    if pilot.command(["git", "rev-parse", "HEAD"], origin / "knowledge") != config["bcquality_sha"]:
        raise ValueError("Original knowledge pin changed")
    root.mkdir(parents=True, exist_ok=False)
    claim = {"destination": str(root), "created_unix": time.time(), **proof}
    with (origin / "continuation-claim.json").open("x", encoding="utf-8") as stream:
        json.dump(claim, stream, indent=2)
    pilot.save(root / "zero-inference-proof.json", proof)
    pilot.save(
        root / "preparation-revision.json",
        {
            "revision": "strict-long-paths-v3-r1",
            "origin": str(origin),
            "historical_readiness": "invalid: enumeration silently omitted unstatable long paths",
            "historical_records": {name: pilot.sha(origin / name) for name in ("selection.json", "inputs.json", "preflight.json", "readiness-summary.json")},
            "limits": {"baseline": 6, "verifier": 18, "judge_batches": 6, "retries": 0},
            "original_selection": selection,
        },
    )
    copy_tree(origin / "engine", root / "engine")
    entries = pilot.selected_entries(benchmark, config)
    digests = []
    for number, entry in enumerate(entries, 1):
        case = f"case-{number:02}"
        source = origin / "prepared" / case / "source"
        expected = expected_source_inventory(source, entry, root / "validation" / case)
        actual = snapshot_inventory(source)
        validate_inventory(actual, expected)
        pilot.save(
            root / "validation" / case / "manifest.json",
            {
                "instance_id": entry.instance_id,
                "base_commit": entry.base_commit,
                "patch_serialization": "bcbench_core.git.apply_patch: UTF-8 native text newline",
                "expected_git_blobs": expected,
                "inventory": actual,
            },
        )
        destination = root / "prepared" / case / "source"
        copy_tree(source, destination)
        if snapshot_inventory(destination) != actual:
            raise ValueError(f"Execution preparation copy changed {case}")
        # Live tools still use ordinary paths. Keep every planned verifier path below MAX_PATH.
        if os.name == "nt" and any(len(str(root / case / "voter-1" / "work" / "source" / path)) >= 260 for path in actual):
            raise ValueError("Choose a shorter fresh continuation root for live CLI source views")
        digests.append(pilot.digest_json([(path, item["sha256"]) for path, item in actual.items()]))
    knowledge = verify_knowledge(origin, root, config)
    pilot.save(root / "validation" / "knowledge-manifest.json", knowledge)
    copy_tree(origin / "knowledge", root / "knowledge")
    if snapshot_inventory(root / "knowledge") != knowledge["inventory"]:
        raise ValueError("Knowledge copy changed the frozen input")
    pilot.save(root / "selection.json", {"config": config, **identity, "cli": selection["cli"]})
    pilot.save(root / "inputs.json", {"source_sha256": digests, "knowledge_sha256": pilot.tree_digest(root / "knowledge")})
    if prove_no_inference(origin) != proof:
        raise ValueError("Original execution changed during recovery")
    pilot.save(root / "preflight.json", pilot.preflight(root, benchmark))
